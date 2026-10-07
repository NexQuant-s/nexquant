import logging
from contextlib import nullcontext
from datetime import datetime, timezone
from superbot.config import BROKER_TYPE

log = logging.getLogger("position_syncer")


def _iso(value):
    """datetime -> ISO-8601 ; chaîne ou None inchangés."""
    return value.isoformat() if hasattr(value, 'isoformat') else value


def _find_broker_closure(bot, symbol, old_pos):
    """
    Retrouve la clôture réelle d'une position chez le broker.

    1. Par ticket de position (exact, sans ambiguïté de date ni de fuseau).
    2. Sinon, dans l'historique récent : uniquement un deal du même ticket, ou du même
       symbole/sens/prix d'entrée. Ne jamais rattacher la clôture d'une autre position.
    """
    position_id = old_pos.get('position_id')
    if position_id and hasattr(bot.broker, 'get_closed_position'):
        try:
            closed = bot.broker.get_closed_position(position_id)
            if closed:
                return closed
        except Exception as e:
            log.warning(f"Lecture des deals de la position #{position_id} ({symbol}) impossible : {e}")

    try:
        history = bot.broker.get_trade_history(days=2)
    except Exception as e:
        log.debug(f"Impossible de récupérer l'historique broker pour la fermeture de {symbol} : {e}")
        return None

    side = 'buy' if old_pos.get('side', 'LONG') == 'LONG' else 'sell'
    entry = float(old_pos.get('entry_price') or 0.0)
    for t in history or []:
        if position_id and t.get('position_id') == position_id:
            return t
        if (t.get('symbol') == symbol and t.get('side') == side and entry > 0
                and abs(float(t.get('entry_price') or 0.0) - entry) <= entry * 1e-5):
            return t
    return None

def sync_positions_with_broker(bot):
    """
    Synchronise l'état interne des positions du bot et du RiskManager avec le broker.
    """
    try:
        active_positions = {}
        failed_symbols = set()
        # Snapshot sous verrou : les boucles ci-dessous itèrent sur une copie,
        # insensibles aux suppressions concurrentes (ex: thread webhook).
        _lock = getattr(bot, '_lock', None)
        with (_lock if _lock is not None else nullcontext()):
            positions_snapshot = dict(bot.positions)
        for symbol in bot.instruments:
            try:
                pos = bot.broker.get_position(symbol)
                if pos and pos.get('size', 0) > 0:
                    old_pos = positions_snapshot.get(symbol, {})
                    active_positions[symbol] = {
                        'side': pos['side'],
                        'size': pos['size'],
                        'entry_price': pos['entry_price'],
                        'stop_loss': pos.get('stop_loss', 0.0) or old_pos.get('stop_loss', 0.0),
                        'take_profit': pos.get('take_profit', 0.0) or old_pos.get('take_profit', 0.0),
                        'liquidation_price': pos.get('liquidation_price', 0.0),
                        'timestamp': old_pos.get('timestamp') or pos.get('timestamp') or datetime.now(timezone.utc),
                        'status': 'open',
                        # Préserver les métadonnées d'ouverture entre deux syncs
                        'market_regime': old_pos.get('market_regime', 'UNKNOWN'),
                        'strategy_name': old_pos.get('strategy_name', 'UNKNOWN'),
                        'features': old_pos.get('features', {}),
                        # Ticket de position broker : clé exacte pour retrouver la clôture
                        'position_id': pos.get('ticket') or old_pos.get('position_id'),
                    }
            except Exception as e:
                log.warning(f"Erreur API lors de la vérification de la position de {symbol} : {e}")
                failed_symbols.add(symbol)

        # Détecter les positions fermées
        for symbol, old_pos in positions_snapshot.items():
            if symbol in failed_symbols:
                # En cas d'échec de l'API, on conserve la position en mémoire pour éviter d'ouvrir des doublons
                log.warning(f"⚠️ Impossible de vérifier le statut de la position {symbol}. Maintien en mémoire par sécurité.")
                active_positions[symbol] = old_pos
                continue
                
            if symbol not in active_positions:
                log.info(f"Position fermée détectée pour {symbol}")
                
                # Nettoyer les ordres conditionnels restants (ex. TP/SL orphelins)
                try:
                    bot.broker.cancel_all_orders(symbol)
                except Exception as e:
                    log.warning(f"⚠️ Impossible d'annuler les ordres orphelins restants pour {symbol} : {e}")
                
                entry_price = old_pos.get('entry_price', 0.0)
                side = old_pos.get('side', 'LONG')
                size = old_pos.get('size', 0.0)
                closed = _find_broker_closure(bot, symbol, old_pos)

                if closed:
                    exit_price = closed['exit_price']
                    pnl = closed['pnl']
                    entry_price = closed.get('entry_price') or entry_price
                    close_reason = closed.get('close_reason', 'unknown')
                    verified = True
                    log.info(
                        f"Clôture {symbol} confirmée par le broker (position #{closed.get('position_id')}) : "
                        f"Exit={exit_price}, P&L={pnl:+.2f}, motif={close_reason}"
                    )
                else:
                    # Repli : estimation au prix courant (non vérifiée, exclue de l'apprentissage ML)
                    exit_price, pnl = 0.0, 0.0
                    close_reason, verified = 'estimated', False
                    try:
                        exit_price = bot.broker.get_current_price(symbol)
                        if side == 'LONG':
                            raw_pnl = (exit_price - entry_price) * size
                        else:
                            raw_pnl = (entry_price - exit_price) * size
                        # Conversion devise de cotation → devise du compte
                        pnl = bot._convert_pnl_to_account_currency(symbol, raw_pnl, exit_price)
                        log.warning(f"Clôture {symbol} non trouvée chez le broker — estimation : Exit={exit_price}, P&L={pnl:.2f} (brut={raw_pnl:.2f})")
                    except Exception as e:
                        log.error(f"Erreur lors du calcul théorique de fermeture pour {symbol} : {e}")

                if not exit_price or exit_price <= 0 or not entry_price or entry_price <= 0:
                    # Un prix nul produirait un P&L aberrant (ex: -2176€) qui fausserait
                    # les statistiques, le Kelly et l'apprentissage : on n'enregistre rien.
                    log.error(
                        f"🚫 Clôture {symbol} ignorée : prix invalide (entrée={entry_price}, sortie={exit_price}). "
                        f"Le trade sera récupéré depuis l'historique broker au prochain démarrage."
                    )
                    continue

                # Enregistrer le trade clôturé
                if bot.risk_manager:
                    # Propager le régime de marché et les features ML de l'ouverture vers la clôture.
                    market_regime_at_open = old_pos.get('market_regime', 'UNKNOWN')
                    strategy_name = old_pos.get('strategy_name', 'UNKNOWN')
                    features_at_open = old_pos.get('features', {})
                    trade_record = {
                        'symbol': symbol,
                        'side': 'buy' if side == 'LONG' else 'sell',
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'position_size': size,
                        'pnl': pnl,
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'status': 'closed',
                        'market_regime': market_regime_at_open,
                        'strategy_name': strategy_name,
                        'broker': getattr(bot, 'active_broker_type', BROKER_TYPE),
                        'target': 1 if pnl > 0 else 0,
                        'position_id': (closed or {}).get('position_id') or old_pos.get('position_id'),
                        'close_reason': close_reason,
                        # True = P&L lu dans les deals broker ; False = estimation
                        'verified': verified,
                        'open_time': _iso((closed or {}).get('open_time') or old_pos.get('timestamp')),
                    }
                    trade_record.update(features_at_open)
                    bot.risk_manager.record_trade(trade_record)

                    # Rafraîchir daily_pnl/monthly_pnl immédiatement pour que
                    # _can_take_new_trade() ne voie pas des valeurs périmées.
                    try:
                        new_balance = float(bot.broker.get_balance())
                        bot.risk_manager.update_account_balance(new_balance)
                        bot._cached_balance = new_balance
                        if getattr(bot, 'session_target_tracker', None):
                            bot.session_target_tracker.update(new_balance)
                            bot.session_target_tracker.log_progress(force=True)
                        log.debug(f"[BUG-A03] Solde mis à jour post-clôture {symbol}: {new_balance:.2f}")
                    except Exception as _e:
                        log.debug(f"[BUG-A03] Impossible de rafraîchir le solde post-clôture: {_e}")

                    # PnL de session/jour (alimente l'objectif et le mode défensif — n'était jamais appelé)
                    if getattr(bot, 'session_manager', None):
                        try:
                            bot.session_manager.register_trade(pnl)
                        except Exception as e:
                            log.debug(f"Erreur session_manager.register_trade : {e}")

                    # 🧠 V3 : Apprentissage de performance (Stats Stratégies + Blocage Symboles + SQLite DB)
                    if getattr(bot, 'performance_learner', None):
                        try:
                            res_pl = bot.performance_learner.on_trade_closed(trade_record)
                            log.info(
                                f"🧠 [PerformanceLearner] Trade appris : {symbol} ({strategy_name}) | "
                                f"PnL={pnl:+.2f}€ | Pertes consécutives={res_pl.get('consecutive_losses', 0)}"
                            )
                        except Exception as e:
                            log.debug(f"Erreur performance_learner : {e}")

                    # 🧠 V3 : Apprentissage en ligne
                    if getattr(bot, 'online_learner', None):
                        try:
                            import pandas as pd
                            # Reconstruire la ligne de dataframe pour le modèle
                            df_row = pd.Series(features_at_open)
                            ctx = {**features_at_open, 'regime': market_regime_at_open}
                            bot.online_learner.on_trade_closed(trade_record, df_row=df_row, context=ctx)
                        except Exception as e:
                            log.debug(f"Erreur online_learner : {e}")

                    # Envoi de la clôture à la télémétrie Cloud
                    if bot.telemetry.enabled:
                        try:
                            pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0.0
                            if side == 'SHORT':
                                pnl_pct = -pnl_pct
                            
                            bot.telemetry.push_position(
                                symbol=symbol,
                                side=side,
                                qty=size,
                                entry_price=entry_price,
                                current_price=exit_price,
                                pnl=pnl,
                                pnl_pct=pnl_pct,
                                status="closed",
                                broker=bot.broker.get_asset_type()
                            )
                        except Exception as e:
                            log.debug(f"Erreur envoi position (fermeture) télémétrie : {e}")

                    # 🎯 TRACKING P&L PAR ACTIF POUR BLOCAGE DYNAMIQUE
                    # Ajouter le P&L au cumul de session
                    current_pnl = bot.session_pnl_by_symbol.get(symbol, 0.0)
                    bot.session_pnl_by_symbol[symbol] = current_pnl + pnl

                    # Calculer le seuil de perte de session de manière hybride/safe
                    val = bot.ASSET_BLOCK_LOSS_THRESHOLD
                    enable_loss_limit = getattr(getattr(bot, 'risk_manager', None), 'ENABLE_LOSS_LIMIT', False)
                    if not enable_loss_limit:
                        threshold_usd = float('inf')  # Limite de pertes désactivée par configuration
                    elif val >= 1.0:
                        threshold_usd = val
                    elif 0.0 < val < 1.0:
                        threshold_usd = bot.initial_balance * val
                    else:
                        threshold_usd = float('inf')  # Désactivé si <= 0

                    if enable_loss_limit and bot.session_pnl_by_symbol[symbol] < -threshold_usd:
                        bot.blocked_symbols.add(symbol)
                        log.warning(f"🚫 {symbol} BLOQUÉ - Perte session: {bot.session_pnl_by_symbol[symbol]:.2f} USD (seuil: -{threshold_usd:.2f} USD)")
                    elif pnl < 0:
                        log.info(f"📉 {symbol} : {bot.session_pnl_by_symbol[symbol]:.2f} USD de perte cumulée en session")
        # Mettre à jour bot.positions + risk_manager.open_positions de façon atomique :
        # sinon un worker du cycle peut écrire sur l'ancien dict pendant le swap.
        with (_lock if _lock is not None else nullcontext()):
            bot.positions = active_positions

            if bot.risk_manager:
                prev_open = bot.risk_manager.open_positions
                bot.risk_manager.open_positions = {
                    symbol: {
                        'symbol': symbol,
                        'side': pos['side'],
                        'entry_price': pos['entry_price'],
                        'size': pos['size'],
                        'stop_loss': pos['stop_loss'],
                        'take_profit': pos['take_profit'],
                        'timestamp': pos['timestamp'].isoformat() if hasattr(pos['timestamp'], 'isoformat') else str(pos['timestamp']),
                        # Préserver l'état du trailing/break-even entre deux syncs
                        'atr_value': prev_open.get(symbol, {}).get('atr_value', 0.0),
                        'initial_sl': prev_open.get(symbol, {}).get('initial_sl', 0.0),
                        'break_even_activated': prev_open.get(symbol, {}).get('break_even_activated', False),
                        'trailing_stop_enabled': prev_open.get(symbol, {}).get('trailing_stop_enabled', True),
                    }
                    for symbol, pos in active_positions.items()
                }
        log.info(f"Synchronisation des positions réussie : {list(active_positions.keys())}")

        # Ghost Cleaner : supprimer les positions hors-instruments.
        # Après le sync standard, il peut rester des positions dans bot.positions
        # qui appartiennent à des symboles non listés dans bot.instruments
        # (ex: session précédente avec instruments différents, positions externes).
        # Le ghost cleaner les détecte et les supprime proprement.
        try:
            from superbot.components.ghost_cleaner import run_startup_ghost_check
            ghost_count = run_startup_ghost_check(bot)
            if ghost_count > 0:
                log.info(f"[GhostCleaner] {ghost_count} position(s) fantôme(s) nettoyée(s) au startup.")
        except Exception as e:
            log.warning(f"[GhostCleaner] Impossible d'exécuter le ghost check : {e}")

    except Exception as e:
        log.error(f"Erreur lors de la synchronisation des positions avec le broker : {e}")
