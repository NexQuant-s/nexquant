"""
Phase 7 §4 — Nettoyage des Ghost Positions
============================================
Valide l'intégrité de l'état sauvegardé (state_*.json + risk_manager.open_positions)
en cross-référençant avec les positions RÉELLES du broker.

Supprime les "positions fantômes" : entrées dans le state qui n'ont plus de contrepartie
réelle sur le broker (ordre expiré, position clôturée hors-bot, restart forcé, etc.)

Usage autonome :
    python -m superbot.components.ghost_cleaner --broker mt5|binance|alpaca

Intégration automatique : appelé par _sync_positions_with_broker() à chaque startup.
"""
import logging
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

log = logging.getLogger("ghost_cleaner")


def clean_ghost_positions(
    bot_positions: Dict[str, Any],
    risk_manager_open_positions: Dict[str, Any],
    broker_real_positions: List[Dict[str, Any]],
    trade_history_path: Optional[str] = None,
    dry_run: bool = False
) -> Tuple[int, List[str]]:
    """
    Supprime les positions fantômes des dictionnaires internes du bot.

    Une position fantôme est une entrée dans bot.positions ou
    risk_manager.open_positions qui n'a PAS de correspondance dans
    les positions réelles retournées par le broker.

    Args:
        bot_positions: dict mutable — bot.positions
        risk_manager_open_positions: dict mutable — risk_manager.open_positions
        broker_real_positions: liste des positions réelles du broker (chaque élément
                               doit avoir au moins un champ 'symbol')
        trade_history_path: chemin vers trades.jsonl pour enregistrer les clôtures fantômes
        dry_run: si True, ne supprime rien, ne fait que reporter

    Returns:
        Tuple (nombre_de_ghosts_supprimés, liste_des_symboles_nettoyés)
    """
    # Construire l'ensemble des symboles réellement ouverts sur le broker
    real_symbols = set()
    # Table de correspondance des alias broker (WTIUSD ↔ XTIUSD, BRENTUSD ↔ XBRUSD…).
    _SYMBOL_ALIASES = {
        "XTIUSD": "WTIUSD", "WTIUSD": "XTIUSD",
        "WTI": "XTIUSD",
        "XBRUSD": "BRENTUSD", "BRENTUSD": "XBRUSD",
        "BRENT": "XBRUSD", "BRNUSD": "XBRUSD",
    }
    for pos in (broker_real_positions or []):
        sym = pos.get('symbol', '')
        if sym:
            real_symbols.add(sym)
            # Aussi ajouter les variantes de notation (BTC/USDT, BTCUSDT)
            real_symbols.add(sym.replace('/', ''))
            real_symbols.add(sym.replace('/', '-'))
            # Ajouter l'alias éventuel.
            alias = _SYMBOL_ALIASES.get(sym.upper())
            if alias:
                real_symbols.add(alias)

    log.info(f"[GhostCleaner] {len(real_symbols)} positions réelles sur le broker : {sorted(real_symbols)}")

    # Détecter les ghosts dans bot.positions
    ghost_symbols = []
    for symbol in list(bot_positions.keys()):
        sym_norm = symbol.replace('/', '').replace('-', '').upper()
        real_norms = {s.replace('/', '').replace('-', '').upper() for s in real_symbols}
        if (symbol not in real_symbols and sym_norm not in real_norms):
            ghost_symbols.append(symbol)
            log.warning(
                f"[GhostCleaner] 👻 POSITION FANTÔME détectée : {symbol} "
                f"(taille={bot_positions[symbol].get('size', '?')}, "
                f"entrée={bot_positions[symbol].get('entry_price', '?')})"
            )

    if not ghost_symbols:
        log.info("[GhostCleaner] ✅ Aucune position fantôme trouvée.")
        return 0, []

    if dry_run:
        log.info(f"[GhostCleaner] DRY RUN — {len(ghost_symbols)} ghosts identifiés (non supprimés) : {ghost_symbols}")
        return len(ghost_symbols), ghost_symbols

    # Supprimer les ghosts + enregistrer comme trades clôturés de PnL inconnu
    for symbol in ghost_symbols:
        pos_data = bot_positions.pop(symbol, {})
        rm_data = risk_manager_open_positions.pop(symbol, {})

        # Enregistrer la clôture forcée dans trades.jsonl pour traçabilité
        if trade_history_path:
            try:
                ghost_record = {
                    'symbol': symbol,
                    'status': 'closed',
                    'close_reason': 'GHOST_CLEANUP',
                    'side': pos_data.get('side', rm_data.get('side', 'UNKNOWN')),
                    'entry_price': pos_data.get('entry_price', rm_data.get('entry_price', 0)),
                    'size': pos_data.get('size', rm_data.get('size', 0)),
                    'pnl': None,  # PnL inconnu — position externe au bot
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'note': 'Clôturée automatiquement (ghost cleanup) — position absente du broker'
                }
                os.makedirs(os.path.dirname(trade_history_path), exist_ok=True)
                with open(trade_history_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(ghost_record, ensure_ascii=False, default=str) + '\n')
            except Exception as e:
                log.warning(f"[GhostCleaner] Impossible d'enregistrer la clôture fantôme pour {symbol} : {e}")

        log.info(f"[GhostCleaner] 🧹 Position fantôme supprimée : {symbol}")

    log.info(f"[GhostCleaner] Nettoyage terminé : {len(ghost_symbols)} position(s) fantôme(s) supprimée(s).")
    return len(ghost_symbols), ghost_symbols


def run_startup_ghost_check(bot) -> int:
    """
    Version intégrée — appelée depuis _sync_positions_with_broker() ou au startup.

    Lit les positions réelles du broker, détecte et supprime les ghosts dans
    bot.positions et bot.risk_manager.open_positions.

    Returns:
        Nombre de positions fantômes supprimées.
    """
    try:
        # Récupérer les positions réelles
        real_positions = []
        try:
            raw = bot.broker.get_open_positions()
            if isinstance(raw, list):
                real_positions = raw
            elif isinstance(raw, dict):
                real_positions = list(raw.values())
        except Exception as e:
            log.warning(f"[GhostCleaner] Impossible de récupérer les positions broker : {e}")
            return 0  # Ne pas nettoyer si on ne peut pas vérifier

        # Chemin du fichier de trades
        from superbot.config import LOG_DIR
        trades_file = os.path.join(str(LOG_DIR), 'trades.jsonl')

        # Dictionnaires mutables à nettoyer
        bot_positions = getattr(bot, 'positions', {})
        rm_open = getattr(getattr(bot, 'risk_manager', None), 'open_positions', {})

        count, cleaned = clean_ghost_positions(
            bot_positions=bot_positions,
            risk_manager_open_positions=rm_open,
            broker_real_positions=real_positions,
            trade_history_path=trades_file,
            dry_run=False
        )

        if count > 0:
            # Sauvegarder l'état nettoyé
            try:
                bot._save_cooldowns()
            except Exception as _exc:
                log.debug(f"Erreur ignorée (non bloquante) : {_exc}")

        return count

    except Exception as e:
        log.error(f"[GhostCleaner] Erreur lors du ghost check au startup : {e}")
        return 0


# ── Utilisation standalone ──────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    parser = argparse.ArgumentParser(description='NexQuant Ghost Position Cleaner')
    parser.add_argument('--broker', choices=['mt5'], default='mt5')
    parser.add_argument('--dry-run', action='store_true', help='Ne pas supprimer, juste reporter')
    parser.add_argument('--state-file', help='Chemin vers state_<broker>.json', default=None)
    args = parser.parse_args()

    # Chemin par défaut
    base_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
    state_file = args.state_file or os.path.join(base_dir, f'state_{args.broker}.json')
    trades_file = os.path.join(base_dir, 'trades.jsonl')

    if not os.path.exists(state_file):
        print(f"❌ Fichier d'état introuvable : {state_file}")
        sys.exit(1)

    # Charger l'état
    with open(state_file, 'r') as f:
        state = json.load(f)

    saved_positions = state.get('positions', {})
    print(f"\n📊 Positions dans {state_file} : {len(saved_positions)}")
    for sym, pos in saved_positions.items():
        print(f"  {sym}: side={pos.get('side','?')}, size={pos.get('size','?')}, entry={pos.get('entry_price','?')}")

    print("\n⚠️  Pour nettoyer automatiquement, lancez avec le broker actif.")
    print("   Le nettoyage complet nécessite une connexion broker pour croiser les données.")
    print("   En mode autonome, seule la liste est affichée.\n")

    # Détecter les positions dont le timestamp est très vieux (> 7 jours) sans PnL
    stale_count = 0
    now = datetime.now(timezone.utc)
    for sym, pos in list(saved_positions.items()):
        ts_str = pos.get('timestamp', pos.get('open_time', ''))
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                age_days = (now - ts).days
                if age_days > 7:
                    print(f"  ⚠️  {sym} : âgé de {age_days} jours (potentiellement fantôme)")
                    stale_count += 1
            except Exception as _exc:
                log.debug(f"Erreur ignorée (non bloquante) : {_exc}")

    if stale_count == 0:
        print("✅ Aucune position ancienne (> 7j) détectée.")
    else:
        print(f"\n🧹 {stale_count} position(s) potentiellement fantôme(s) identifiée(s).")
        print("   Relancez le bot — le ghost cleaner s'activera automatiquement au démarrage.")
