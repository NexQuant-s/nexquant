import logging
import time
from datetime import datetime, timezone
from superbot.config import MAX_SPREAD_PIPS, MAX_FOREX_CURRENCY_EXPOSURE, BROKER_TYPE

# Imports en haut du fichier pour éviter de les refaire dans la hot path
from superbot.risk.modules.risk_monitor import _is_night_session
try:
    from superbot.config import SCORE_MIN_NIGHT, NIGHT_SESSION_START_UTC, NIGHT_SESSION_END_UTC
except ImportError:
    SCORE_MIN_NIGHT, NIGHT_SESSION_START_UTC, NIGHT_SESSION_END_UTC = 8, 20, 6

log = logging.getLogger("signal_executor")

def _reject_trade(bot, symbol: str, reason: str):
    log.info(f"🚫 Trade {symbol} rejeté : {reason}")
    if getattr(bot, 'report_generator', None):
        try:
            bot.report_generator.record_rejection_event(symbol, reason)
        except Exception as _exc:
            log.debug(f"Erreur ignorée (non bloquante) : {_exc}")

def _strategy_sl_tp(signal_data: dict, entry_price: float):
    """SL/TP proposés par la stratégie s'ils sont exploitables au prix d'entrée réel, sinon None.

    Activé par USE_STRATEGY_SL_TP : le backtest utilise ces niveaux (SL Donchian de Murphy) ; les
    remplacer par le SL/TP ATR × régime supprimait l'avantage mesuré (PF ≈ 1,0 au lieu de ≈ 1,5-1,8).
    """
    from superbot.config import USE_STRATEGY_SL_TP
    if not USE_STRATEGY_SL_TP:
        return None
    try:
        sl, tp = float(signal_data.get('sl_price') or 0), float(signal_data.get('tp_price') or 0)
    except (TypeError, ValueError):
        return None
    if sl <= 0 or tp <= 0 or entry_price <= 0:
        return None
    if signal_data.get('should_long'):
        return (sl, tp) if sl < entry_price < tp else None
    return (sl, tp) if tp < entry_price < sl else None


def _risk_factor(bot) -> float:
    """
    Facteur appliqué au risque par trade : sentiment/news × protection intra-journée
    (PerformanceLearner : ×0.3 en mode défensif, ×0.5 après +150 % de l'objectif).
    NB : position_sizer garde un plancher de 0.5 % de risque.
    """
    factor = 1.0
    if getattr(bot, 'news_manager', None):
        factor *= bot.news_manager.get_risk_factor()
    learner = getattr(bot, 'performance_learner', None)
    if learner is not None and hasattr(learner, 'get_risk_multiplier'):
        mult = learner.get_risk_multiplier()
        if mult < 1.0:
            log.info(f"🛡️ [PerformanceLearner] Risque réduit ×{mult} (protection intra-journée active)")
        factor *= mult
    return factor


def is_exhausted_entry(side: str, rsi: float, bb_pos: float, rsi_ob: float = 70.0,
                       rsi_os: float = 30.0, bb_extreme: float = 0.95) -> bool:
    """Achat en surachat (RSI ≥ OB ou prix au-dessus de 95 % des Bollinger) ou vente en survente."""
    if side == "LONG":
        return rsi >= rsi_ob or bb_pos > bb_extreme
    if side == "SHORT":
        return rsi <= rsi_os or bb_pos < 1.0 - bb_extreme
    return False


def _exhaustion_reason(signal_data: dict, df_with_indicators) -> str:
    """Motif de rejet si l'entrée se fait en zone d'épuisement (filtre ENTRY_EXHAUSTION_FILTER), sinon ''."""
    from superbot import config as _cfg
    if not _cfg.ENTRY_EXHAUSTION_FILTER or df_with_indicators is None or len(df_with_indicators) == 0:
        return ""
    side = "LONG" if signal_data.get('should_long') else ("SHORT" if signal_data.get('should_short') else "")
    last = df_with_indicators.iloc[-1]
    rsi = float(last.get('rsi', 50.0) or 50.0)
    close = float(last.get('close', 0.0) or 0.0)
    upper, lower = float(last.get('bb_upper', 0.0) or 0.0), float(last.get('bb_lower', 0.0) or 0.0)
    bb_pos = (close - lower) / (upper - lower) if upper > lower else 0.5
    if is_exhausted_entry(side, rsi, bb_pos, _cfg.RSI_OB, _cfg.RSI_OS, _cfg.ENTRY_BB_EXTREME):
        return f"Entrée {side} en zone d'épuisement (RSI={rsi:.1f}, position Bollinger={bb_pos:.2f})"
    return ""


def execute_signal_trade(bot, symbol: str, signal_data: dict, df_with_indicators):
    """
    Valide les filtres macro, calcule la taille de position de manière sécurisée et exécute l'ordre.
    """
    with bot._state_lock:
        bot.stats['signals_generated'] += 1

    # Normaliser le symbole pour l'aligner sur bot.positions (ex: WTIUSD → XTIUSD sur Fusion Markets)
    normalized_symbol = symbol
    if hasattr(bot.broker, 'normalize_symbol'):
        normalized_symbol = bot.broker.normalize_symbol(symbol)

    log.info(
        f"Signal pour {symbol} : {signal_data['market_regime']} | "
        f"Score: {signal_data['total_score']:.1f} | "
        f"Long: {signal_data['should_long']} | Short: {signal_data['should_short']} | "
        f"RR: {signal_data['rr_ratio']:.2f}"
    )

    # Vérification stricte du Risk:Reward minimum (>= 1.8) pour assurer des trades réfléchis et conséquents
    rr_val = float(signal_data.get('rr_ratio', 0.0))
    if rr_val < 1.8:
        _reject_trade(bot, symbol, f"Rapport Risque/Rendement insuffisant (R:R {rr_val:.2f} < 1.8)")
        return

    # 0. Vérifier le cooldown de l'actif suite à un échec d'exécution
    with bot._state_lock:
        in_cooldown = normalized_symbol in bot.failed_execution_cooldowns or symbol in bot.failed_execution_cooldowns
        cooldown_ts = bot.failed_execution_cooldowns.get(normalized_symbol, bot.failed_execution_cooldowns.get(symbol, 0))
        time_since_failure = time.time() - cooldown_ts if in_cooldown else 0

    if in_cooldown:
        if time_since_failure < 900:  # 15 minutes cooldown
            log.info(f"🚫 Trade {symbol} rejeté : Cooldown d'échec actif (reste {int(900 - time_since_failure)}s)")
            _reject_trade(bot, symbol, f"Cooldown d'échec actif (reste {int(900 - time_since_failure)}s)")
            return
        else:
            with bot._state_lock:
                bot.failed_execution_cooldowns.pop(normalized_symbol, None)
                bot.failed_execution_cooldowns.pop(symbol, None)
            bot._save_cooldowns()
            
    # Bloquer tout nouveau trade si une position est déjà ouverte sur ce symbole.
    # Plus de "Reversal" automatique : les positions existantes sont gérées
    # exclusivement par leurs SL/TP/trailing stops pour éviter les whipsaws destructeurs.
    existing_pos = bot.positions.get(normalized_symbol, {})
    existing_size = existing_pos.get('size', 0)
    if existing_size > 0:
        existing_side = existing_pos.get('side', '')
        cand_side = "LONG" if signal_data.get('should_long') else ("SHORT" if signal_data.get('should_short') else "")
        log.info(
            f"🚫 Trade {symbol} rejeté : Position {existing_side} déjà ouverte "
            f"(signal {cand_side} ignoré — pas de reversal automatique)."
        )
        _reject_trade(bot, symbol, f"Position {existing_side} déjà ouverte (signal {cand_side} ignoré)")
        return

    # ── Audit post-freeze (fix 24/07/2026) ──────────────────────────────────
    # Après un freeze long du cycle (ex: 6h26 à cause d'une erreur DNS),
    # le bot attend N cycles d'observation avant d'ouvrir de nouveaux trades.
    # Ceci évite d'entrer sur un marché qui a drastiquement changé de régime.
    post_freeze_remaining = getattr(bot, '_post_freeze_cooldown_cycles', 0)
    if post_freeze_remaining > 0:
        bot._post_freeze_cooldown_cycles = max(0, post_freeze_remaining - 1)
        log.warning(
            f"🔍 [Post-Freeze] Trade {symbol} rejeté — mode audit actif "
            f"({post_freeze_remaining} cycle(s) restant(s)). "
            f"Le bot observe le marché sans ouvrir de nouvelles positions."
        )
        _reject_trade(bot, symbol, f"Mode audit post-freeze actif ({post_freeze_remaining} cycle(s) restant(s))")
        return
    # ─────────────────────────────────────────────────────────────────────────

    # 0b. Vérifier le Trailing Profit Circuit Breaker
    if getattr(bot, '_circuit_breaker_paused', False):
        log.info(f"⏸️ [CircuitBreaker] Trade sur {symbol} rejeté — trading en pause automatique par protection des gains.")
        _reject_trade(bot, symbol, "Trading en pause automatique par protection des gains (Circuit Breaker)")
        return

    # 0c. Anti-Whipsaw Directional Cooldown
    if hasattr(bot, 'risk_manager') and bot.risk_manager:
        rm = bot.risk_manager
        
        # 1. Check 2+ consecutive losses in last 2 hours
        consecutive_losses = rm.consecutive_losses.get(symbol, 0) if hasattr(rm, 'consecutive_losses') else 0
        if consecutive_losses >= 2:
            last_close_time = rm.last_trade_close_time.get(symbol) if hasattr(rm, 'last_trade_close_time') else None
            if last_close_time:
                now_utc = datetime.now(timezone.utc)
                if isinstance(last_close_time, str):
                    try:
                        last_close_time = datetime.fromisoformat(last_close_time.replace('Z', '+00:00'))
                    except Exception:
                        last_close_time = None
                
                # Ensure timezone-aware comparison
                if last_close_time:
                    if last_close_time.tzinfo is None:
                        last_close_time = last_close_time.replace(tzinfo=timezone.utc)
                    if (now_utc - last_close_time).total_seconds() < 7200:
                        log.info(f"🚫 [Anti-Whipsaw] Trade {symbol} rejeté : 2+ pertes consécutives dans les 2 dernières heures.")
                        _reject_trade(bot, symbol, "2+ pertes consécutives récentes (Anti-Whipsaw)")
                        return

        # 2. Check if last trade was a loss < 45 mins ago and opposite direction
        last_trade = None
        if hasattr(rm, 'trade_history') and rm.trade_history:
            for t in reversed(rm.trade_history):
                if t.get('symbol') == symbol and str(t.get('status', 'closed')) == 'closed' and t.get('pnl') is not None:
                    last_trade = t
                    break
                    
        if last_trade and last_trade.get('pnl', 0) < 0:
            last_ts_str = last_trade.get('timestamp')
            if last_ts_str:
                try:
                    last_ts = datetime.fromisoformat(str(last_ts_str).replace('Z', '+00:00'))
                    if last_ts.tzinfo is None:
                        last_ts = last_ts.replace(tzinfo=timezone.utc)
                    now_utc = datetime.now(timezone.utc)
                    if (now_utc - last_ts).total_seconds() < 2700: # 45 minutes
                        # Le journal stocke 'buy'/'sell' ; le signal raisonne en LONG/SHORT.
                        last_side = {'BUY': 'LONG', 'SELL': 'SHORT'}.get(
                            str(last_trade.get('side', '')).upper(), str(last_trade.get('side', '')).upper())
                        cand_side = "LONG" if signal_data.get('should_long') else ("SHORT" if signal_data.get('should_short') else "")
                        if last_side and cand_side and last_side != cand_side:
                            log.info(f"🚫 [Anti-Whipsaw] Trade {symbol} rejeté : Perte récente (<45m) et signal opposé ({cand_side} vs {last_side}).")
                            _reject_trade(bot, symbol, f"Perte récente et signal opposé {cand_side} (Anti-Whipsaw)")
                            return
                except Exception as e:
                    log.debug(f"Erreur parsing timestamp Anti-Whipsaw: {e}")

    # 0d. Filtre d'épuisement : ne pas acheter en surachat ni vendre en survente
    exhaustion_reason = _exhaustion_reason(signal_data, df_with_indicators)
    if exhaustion_reason:
        _reject_trade(bot, symbol, exhaustion_reason)
        return

    # 1. Vérifier les filtres de nouvelles et de sentiment
    if getattr(bot, 'news_manager', None):
        should_avoid, news_event = bot.news_manager.should_avoid_trading_due_to_news(symbol)
    else:
        should_avoid, news_event = False, None
    if should_avoid:
        log.info(f"Trading évité pour {symbol} à cause des nouvelles : {news_event.title if news_event else 'Unknown'}")
        _reject_trade(bot, symbol, f"Trading évité à cause des nouvelles : {news_event.title if news_event else 'Unknown'}")
        return

    # 1b. Filtre de score nocturne (fix sur-exposition 23-24/07/2026) ─────────
    # En session nocturne (20h-06h UTC), exiger un score minimum plus élevé
    # pour éviter les entrées sur des signaux de qualité marginale.

    if _is_night_session(NIGHT_SESSION_START_UTC, NIGHT_SESSION_END_UTC):
        current_score = signal_data.get('total_score', 0)
        if current_score < SCORE_MIN_NIGHT:
            log.info(
                f"🌙 [NightFilter] Trade {symbol} rejeté — score {current_score:.1f} < "
                f"{SCORE_MIN_NIGHT} requis en session nocturne (20h-06h UTC)"
            )
            _reject_trade(bot, symbol, f"Score {current_score:.1f} < {SCORE_MIN_NIGHT} requis en session nocturne (20h-06h UTC)")
            return
    # ─────────────────────────────────────────────────────────────────────────

    # 2. Récupérer le solde et le prix d'entrée
    # get_balance() protégé contre les timeouts réseau ; en cas d'échec,
    # on retombe sur le cache du cycle précédent.
    try:
        account_balance = float(bot.broker.get_balance())
        if account_balance <= 0:
            raise ValueError(f"Solde invalide reçu du broker: {account_balance}")
        bot._cached_balance = account_balance
    except Exception as e:
        log.error(f"⚠️ [BUG-C2] get_balance() a échoué pour {symbol}: {e}")
        account_balance = bot._cached_balance
        if account_balance <= 0:
            log.error(f"⚠️ [BUG-C2] Aucun solde disponible (cache vide). Trade {symbol} annulé.")
            return
        log.warning(f"↩️ [BUG-C2] Utilisation du solde cache: {account_balance:.2f} pour {symbol}")
    entry_price = float(signal_data['entry_price'])

    # Déterminer la classe d'actif par symbole pour appliquer les bons filtres.
    from superbot.broker.symbol_specs import get_asset_class
    if hasattr(bot.broker, 'get_asset_class_for_symbol'):
        symbol_asset_class = bot.broker.get_asset_class_for_symbol(symbol)
    else:
        symbol_asset_class = get_asset_class(symbol) or bot.broker.get_asset_type()

    # 2d. Filtres avancés — appliqués selon la classe d'actif du symbole
    from superbot.components.forex_filters import (
        is_market_open, check_spread,
        check_currency_correlation, check_pivot_obstacle,
        check_major_news_window
    )

    # Seuil de spread différencié par classe d'actif
    try:
        from superbot.config import MAX_SPREAD_PIPS_CRYPTO, MAX_SPREAD_PIPS_COMMODITY
    except ImportError:
        MAX_SPREAD_PIPS_CRYPTO, MAX_SPREAD_PIPS_COMMODITY = 500.0, 30.0

    symbol_asset_str = str(symbol_asset_class or "").lower()
    if symbol_asset_str == 'crypto':
        spread_limit = MAX_SPREAD_PIPS_CRYPTO
    elif symbol_asset_str.startswith('commodity'):
        spread_limit = MAX_SPREAD_PIPS_COMMODITY
    else:
        spread_limit = MAX_SPREAD_PIPS

    # B. Garde-fou Spread (appliqué à TOUS les actifs, mais avec le bon seuil)
    if not check_spread(bot.broker, symbol, spread_limit):
        return

    # A. Garde-fou Marché Ouvert : Tout actif traditionnel (Forex & Commodities) est fermé le weekend
    if symbol_asset_class != 'crypto' and get_asset_class(symbol) != 'crypto':
        if not is_market_open(symbol):
            _reject_trade(bot, symbol, "Marché fermé pour le week-end (trading réservé aux cryptos)")
            return

    # Filtres spécifiques Forex (corrélation, pivots, news)
    if symbol_asset_class in ('forex', 'forex_jpy', 'forex_major', 'forex_cross'):
        # C. Corrélation de devises
        cand_side = 'LONG' if signal_data.get('should_long') else 'SHORT'
        if not check_currency_correlation(symbol, bot.positions, MAX_FOREX_CURRENCY_EXPOSURE, cand_side):
            return

        # D. Obstacle pivot
        atr_value = df_with_indicators.iloc[-1].get('atr', 0)
        strat_levels = _strategy_sl_tp(signal_data, entry_price)
        if strat_levels:
            sl_price = strat_levels[0]
        else:
            sl_price, _ = bot.risk_manager.calculate_sl_tp_levels(
                entry_price, atr_value,
                "LONG" if signal_data.get('should_long') else "SHORT",
                asset_type=symbol_asset_class, symbol=symbol
            )
        if not check_pivot_obstacle(entry_price, sl_price, df_with_indicators, signal_data.get('should_long', False), symbol):
            return

        # E. Filtre news économiques majeures (NFP, BCE, FOMC)
        avoid_minutes = bot.config.get('FOREX_NEWS_AVOID_MINUTES', 30) if hasattr(bot, 'config') else 30
        news_events = bot.news_manager.get_high_impact_events() if bot.news_manager and hasattr(bot.news_manager, 'get_high_impact_events') else None
        if not check_major_news_window(symbol, avoid_minutes=avoid_minutes, news_events=news_events):
            return

    # 2b. Filtre volume minimum (protection contre le slippage sur actifs illiquides)
    if symbol_asset_class == "crypto":
        from superbot.components.crypto_filters import check_crypto_volume
        if not check_crypto_volume(symbol, df_with_indicators):
            return

    # 2c. Filtre de dominance BTC pour les altcoins (MT5 crypto CFDs)
    # Ne pas ouvrir un SHORT sur un altcoin si BTC est en tendance haussière forte
    if symbol_asset_class == "crypto" and 'BTC' not in symbol.upper():
        btc_symbol = 'BTCUSD'
        if btc_symbol in bot.market_data and not bot.market_data[btc_symbol].empty:
            btc_df = bot.market_data[btc_symbol]
            btc_last = btc_df.iloc[-1]
            btc_ema_fast = btc_last.get('ema_21', btc_last.get('ema_fast', 0))
            btc_ema_slow = btc_last.get('ema_55', btc_last.get('ema_slow', 0))
            btc_adx = btc_last.get('adx', 0)
            btc_bullish_trend = btc_ema_fast > btc_ema_slow and btc_adx > 25
            btc_bearish_trend = btc_ema_fast < btc_ema_slow and btc_adx > 25

            if signal_data['should_short'] and btc_bullish_trend:
                log.info(f"🚨 Filtre dominance BTC : SHORT {symbol} rejeté — BTC est en tendance haussière forte (ADX={btc_adx:.1f})")
                return
            if signal_data['should_long'] and btc_bearish_trend:
                log.info(f"🚨 Filtre dominance BTC : LONG {symbol} rejeté — BTC est en tendance baissière forte (ADX={btc_adx:.1f})")
                return

    # 3. Déterminer le stop loss et take profit via le Risk Manager
    atr_value = float(df_with_indicators.iloc[-1].get('atr', 0))
    strat_levels = _strategy_sl_tp(signal_data, entry_price)
    if strat_levels:
        sl_price, tp_price = strat_levels
        log.info(f"[SL/TP] {symbol} : niveaux de la stratégie {signal_data.get('strategy_used', '')} "
                 f"(SL {sl_price:.5f} / TP {tp_price:.5f})")
    elif atr_value > 0 and bot.risk_manager:
        position_side = "LONG" if signal_data['should_long'] else "SHORT"
        # Passer le régime HMM pour les multiplicateurs adaptatifs.
        hmm_label = signal_data.get('hmm_label', signal_data.get('market_regime', ''))
        sl_price, tp_price = bot.risk_manager.calculate_sl_tp_levels(
            entry_price, atr_value, position_side,
            asset_type=bot.broker.get_asset_type(),
            symbol=symbol,
            hmm_regime=hmm_label
        )
    else:
        # Fallback : utiliser les valeurs calculées par la stratégie
        sl_price = signal_data.get('sl_price') or (entry_price * 0.98 if signal_data['should_long'] else entry_price * 1.02)
        tp_price = signal_data.get('tp_price') or (entry_price * 1.04 if signal_data['should_long'] else entry_price * 0.96)

    # Vérifier les limites de risque avant le sizing pour éviter des appels broker inutiles.
    if not bot.risk_manager._can_take_new_trade(account_balance, symbol):
        log.info(f"Limites de risque ou limite par symbole atteintes, pas de nouvel ordre pour {symbol}")
        return

    # Corrélation dynamique avancée : bloquer ou réduire la taille si corrélation > 70%.
    max_open_corr = 0.0
    corr_data = None
    try:
        import pandas as pd
        if len(df_with_indicators) >= 50:
            current_close = df_with_indicators['close'].tail(50)
            current_returns = current_close.pct_change().dropna()
            
            for open_sym, pos in bot.positions.items():
                if open_sym != symbol and pos.get('size', 0) > 0:
                    open_df = bot.market_data.get(open_sym)
                    if open_df is not None and len(open_df) >= 50:
                        open_close = open_df['close'].tail(50)
                        open_returns = open_close.pct_change().dropna()
                        
                        min_len = min(len(current_returns), len(open_returns))
                        if min_len >= 30:
                            corr = current_returns.tail(min_len).corr(open_returns.tail(min_len))
                            
                            # Si sens opposé, corrélation effective inversée
                            prop_side = "LONG" if signal_data.get('should_long') else "SHORT"
                            open_side = pos.get('side', 'LONG').upper()
                            effective_corr = corr if prop_side == open_side else -corr
                            
                            if pd.notna(effective_corr) and effective_corr > max_open_corr:
                                max_open_corr = effective_corr
    except Exception as e:
        log.warning(f"Erreur lors du calcul de corrélation avancée pour {symbol} : {e}")

    if max_open_corr >= 0.90:
        log.info(f"🚫 Trade {symbol} rejeté : Corrélation extrême ({max_open_corr:.2f} >= 0.90) avec une position ouverte.")
        _reject_trade(bot, symbol, f"Corrélation extrême ({max_open_corr:.2f} >= 0.90) avec une position ouverte")
        return
    elif max_open_corr > 0.70:
        corr_data = {'average_correlation': max_open_corr}
        log.info(f"⚠️ Corrélation élevée ({max_open_corr:.2f} > 0.70) détectée pour {symbol} : taille sera réduite.")

    # ── CONVICTION BOOST ─────────────────────────────────────────────────────
    # Augmente dynamiquement la taille de position quand TOUTES les conditions
    # suivantes sont réunies, indiquant une opportunité de haute qualité :
    #   1. Score ≥ score_min + 2 (signal très solide, pas juste au seuil)
    #   2. ADX ≥ 30 (tendance forte confirmée)
    #   3. Régime TRENDING (pas de range / pas de haute volatilité chaotique)
    #   4. Corrélation avec les positions ouvertes faible (< 0.70)
    # Le multiplicateur est plafonné à ×1.5 pour rester dans les limites
    # du risk management (le sizing final est toujours borné par la marge dispo).
    conviction_boost = 1.0
    score_raw_val = signal_data.get('total_score', 0)
    # score_min peut être None si le PerformanceLearner l'a modifié sans mettre à jour strategy.
    _raw_score_min = signal_data.get('score_min', None)
    if _raw_score_min is None:
        _raw_score_min = getattr(bot.strategy, 'score_min', None)
    score_min_val = int(_raw_score_min) if _raw_score_min is not None else 6
    adx_val = float(df_with_indicators.iloc[-1].get('adx', 0))
    regime_val = signal_data.get('market_regime', '').upper()

    high_score = score_raw_val >= (score_min_val + 1)
    strong_trend = adx_val >= 25
    trending_regime = 'TRENDING' in regime_val
    low_correlation = max_open_corr < 0.70

    if high_score and strong_trend and trending_regime and low_correlation:
        # Boost progressif selon le niveau du score
        score_excess = score_raw_val - score_min_val
        conviction_boost = min(1.15 + (score_excess * 0.10) + ((adx_val - 25) * 0.008), 1.50)
        log.info(
            f"🚀 [ConvictionBoost] {symbol} — Conditions probabilistes supérieures détectées "
            f"(Score={score_raw_val:.1f}/{score_min_val}, ADX={adx_val:.1f}, Régime={regime_val}). "
            f"Boost de taille : ×{conviction_boost:.2f}"
        )

    # ── VALIDATION MACHINE LEARNING (OnlineLearner / EnsembleScorer) ─────────
    win_prob = 0.5
    if getattr(bot, 'online_learner', None):
        try:
            latest_bar = df_with_indicators.iloc[-1]
            real_spread = bot.broker.get_spread(symbol) if hasattr(bot, 'broker') and bot.broker else 1.0
            ml_ctx = {
                'regime': signal_data.get('market_regime', 'ranging'),
                'session': getattr(bot.session_manager.get_current_session(), 'name', 'LONDON') if getattr(bot, 'session_manager', None) else 'LONDON',
                'spread_pips': real_spread,
                'strategy_name': signal_data.get('strategy_used', 'UNKNOWN'),
            }
            win_prob = bot.online_learner.get_prediction(latest_bar, ml_ctx)
            if 'details' not in signal_data or not isinstance(signal_data['details'], dict):
                signal_data['details'] = {}
            signal_data['details']['win_prob'] = win_prob

            from superbot import config as _cfg
            scorer = getattr(bot.online_learner, 'scorer', None)
            is_high_conviction_consensus = score_raw_val >= (score_min_val + 1.5)
            if _cfg.ML_SHADOW_MODE:
                # Mode ombre : prédiction journalisée pour calibration, sans effet sur le trade.
                log.info(f"🤖 [ML-ombre] {symbol} : prob. de gain prédite {win_prob:.1%} (sans effet)")
            elif scorer and getattr(scorer, 'is_trained', False):
                if win_prob < 0.15:
                    log.warning(f"🤖 [OnlineLearner] Trade {symbol} VETO ABSOLU : prob ML trop faible ({win_prob:.1%})")
                    return
                if win_prob < 0.25 and not is_high_conviction_consensus:
                    log.warning(f"🤖 [OnlineLearner] Trade {symbol} rejeté : prob ML faible ({win_prob:.1%}), score={score_raw_val}")
                    return
            elif win_prob > 0.60:
                conviction_boost = min(conviction_boost * 1.15, 1.50)
                log.info(f"🤖 [OnlineLearner] Boost probabilité ML ({win_prob:.1%}) appliqué pour {symbol} -> Boost={conviction_boost:.2f}")
            elif win_prob < 0.35 and not is_high_conviction_consensus:
                conviction_boost = max(conviction_boost * 0.85, 0.70)
                log.info(f"🤖 [OnlineLearner] Probabilité ML prudente ({win_prob:.1%}) -> Sizing ajusté (Boost={conviction_boost:.2f})")
        except Exception as _ml_e:
            log.debug(f"Erreur prédiction OnlineLearner ({symbol}): {_ml_e}")

    # 3. Calculer la taille de position avec le Risk Manager
    position_size, size_details = bot.risk_manager.calculate_position_size(
        account_balance=account_balance,
        entry_price=entry_price,
        stop_loss=sl_price,
        symbol=symbol,
        sentiment_factor=bot.news_manager.get_risk_factor() if bot.news_manager else 1.0,
        correlation_data=corr_data,
        broker=bot.broker,
        hmm_regime=hmm_label  # dimensionnement selon le régime HMM
    )

    # Appliquer le boost de conviction (après le calcul de base)
    if conviction_boost > 1.0 and position_size > 0:
        size_before_boost = position_size
        boosted_size = position_size * conviction_boost
        # Le boost est re-cappé par MAX_POSITION_SIZE et par la marge max disponible.
        boosted_size = min(boosted_size, bot.risk_manager.MAX_POSITION_SIZE)
        max_margin_size = size_details.get('max_size_by_margin') if isinstance(size_details, dict) else None
        if max_margin_size and max_margin_size > 0:
            boosted_size = min(boosted_size, max_margin_size)
        log.info(
            f"[ConvictionBoost] Taille {symbol} demandée : {size_before_boost:.6f} × {conviction_boost:.2f} = "
            f"{boosted_size:.6f} (cappé par MAX_POSITION_SIZE={bot.risk_manager.MAX_POSITION_SIZE} et marge disponible)"
        )
        position_size = boosted_size

    log.info(f"Risk sizing {symbol}: size={position_size:.6f} | details={size_details}")

    if position_size <= 0:
        log.debug(f"Taille de position nulle ou rejetée pour {symbol}, pas d'action")
        _reject_trade(bot, symbol, "Taille de position nulle ou marge insuffisante")
        return

    log.info(f"Taille de position calculée pour {symbol} : {position_size:.6f} | Risque : {size_details.get('actual_risk_pct', 0.0):.2f}% du compte")

    # Les limites de risque ont déjà été vérifiées avant le sizing.
    # Exécuter le trade chez le courtier.
    side = "buy" if signal_data['should_long'] else "sell"
    log.info(f"Exécution du trade : {side.upper()} {position_size:.6f} {symbol} @ {entry_price:.4f} | SL: {sl_price:.4f} | TP: {tp_price:.4f}")

    # Placer l'ordre
    try:
        order_result = bot.broker.place_order(
            symbol=symbol,
            side=side,
            amount=position_size,
            sl=sl_price,
            tp=tp_price,
            comment=f"SuperBot signal - {signal_data['market_regime']} - Score:{signal_data['total_score']:.1f}"
        )
    except Exception as e:
        log.error(f"⚠️ Chaos intercepté : Exception lors du placement d'ordre pour {symbol} : {e}")
        order_result = None

    if order_result:
        with bot._state_lock:
            bot.stats['trades_executed'] += 1
        log.info(f"Trade exécuté avec succès pour {symbol}")
        
        # Alimentation Prometheus
        if getattr(bot, 'prometheus', None):
            try:
                bot.prometheus.bot_trades_executed_total.labels(
                    symbol=symbol,
                    side=side.upper()
                ).inc()
            except Exception as e:
                log.debug(f"Erreur incrémentation métrique trades_executed: {e}")

        # Collecter les features techniques pour l'entraînement ultérieur du ML
        latest_row = df_with_indicators.iloc[-1]
        close = latest_row.get('close', 1)
        bb_upper = latest_row.get('bb_upper', close * 1.01)
        bb_lower = latest_row.get('bb_lower', close * 0.99)
        bb_pos = (close - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5
        atr_pct = (latest_row.get('atr', 0) / close) * 100 if close > 0 else 0

        features_dict = {
            'rsi': float(latest_row.get('rsi', 50)),
            # ── Fix P4 — La colonne s'appelle 'macd_histogram' dans TechnicalIndicators,
            # mais le trade log utilisait 'macd_hist' (toujours 0).
            'macd_hist': float(latest_row.get('macd_histogram', latest_row.get('macd_hist', 0))),
            'adx': float(latest_row.get('adx', 20)),
            'bb_pos': float(bb_pos),
            'atr_pct': float(atr_pct),
            # Score et probabilité prédite à l'entrée : nécessaires pour
            # calibrer le win rate contre les issues réalisées.
            'signal_score': float(signal_data.get('total_score', 0)),
            'win_prob': float(signal_data.get('details', {}).get('win_prob', 0.0)),
            # Moment de l'entrée (sinon le ML apprendrait l'heure de clôture)
            'hour_of_day': float(datetime.now(timezone.utc).hour),
            'day_of_week': float(datetime.now(timezone.utc).weekday()),
        }

        # Stratégie ayant généré le signal
        strat_name = signal_data.get('strategy_used', signal_data.get('strategy_name', 'MURPHY_TREND'))

        # Enregistrer le trade pour le suivi du risque
        trade_record = {
            'symbol': symbol,
            'side': side,
            'entry_price': entry_price,
            'position_size': position_size,
            'stop_loss': sl_price,
            'take_profit': tp_price,
            'initial_risk_amount': abs(entry_price - sl_price) * position_size,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'signal_score': signal_data['total_score'],
            'market_regime': signal_data['market_regime'],
            'strategy_name': strat_name,
            'broker': getattr(bot, 'active_broker_type', BROKER_TYPE)
        }
        # Inclure les indicateurs pour le Walk-Forward et la traçabilité des paramètres
        trade_record.update(features_dict)
        # Log les paramètres actifs de la stratégie
        trade_record['score_min'] = float(bot.strategy.config.get('SCORE_MIN', 6))
        trade_record['RSI_OB'] = float(bot.strategy.config.get('RSI_OB', 70))
        trade_record['ADX_TREND'] = float(bot.strategy.config.get('ADX_TREND', 25))

        bot.risk_manager.record_trade(trade_record)

        # Mettre à jour la position suivie
        bot._update_position_tracking(symbol, side, position_size, entry_price, sl_price, tp_price,
                                      market_regime=signal_data.get('market_regime', 'UNKNOWN'),
                                      features=features_dict,
                                      strategy_name=strat_name)

        # Enregistrer l'ordre exécuté dans le ReportGenerator
        if getattr(bot, 'report_generator', None):
            try:
                bot.report_generator.record_trade_event(
                    symbol=symbol,
                    side=side.upper(),
                    size=position_size,
                    entry_price=entry_price,
                    sl=sl_price,
                    tp=tp_price,
                    strategy=strat_name,
                    rationale=signal_data.get('decision_rationale', '')
                )
            except Exception as _re:
                log.debug(f"Erreur recording trade ReportGenerator: {_re}")

    else:
        log.error(f"Échec de l'exécution du trade pour {symbol}. Activation du cooldown de 15 minutes.")
        with bot._state_lock:
            bot.failed_execution_cooldowns[symbol] = time.time()
        bot._save_cooldowns()
