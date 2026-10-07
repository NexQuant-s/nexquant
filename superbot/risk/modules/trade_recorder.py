import logging
import os
import json
from datetime import datetime, timezone
from typing import Dict, Any, List
log = logging.getLogger(__name__)


def record_trade(rm, trade_record: Dict[str, Any]):
    """
    Enregistre un trade clôturé dans l'historique pour le calcul de Kelly et l'analyse.
    Écrit également le trade dans un fichier JSON Lines pour persistance.

    Args:
        trade_record: Dictionnaire contenant les détails du trade
    """
    try:
        # Ajouter un timestamp de clôture si absent.
        if 'timestamp' not in trade_record:
            trade_record['timestamp'] = datetime.now(timezone.utc).isoformat()
        # S'assurer que le timestamp est une string pour la sérialisation JSON
        elif isinstance(trade_record['timestamp'], datetime):
            trade_record['timestamp'] = trade_record['timestamp'].isoformat()

        # Ensure _pending_features exists
        if not hasattr(rm, '_pending_features'):
            rm._pending_features = {}

        is_closed = trade_record.get('status') == 'closed' or trade_record.get('pnl') is not None
        symbol = trade_record.get('symbol')

        if not is_closed and symbol:
            rm._pending_features[symbol] = {
                'symbol': symbol,
                'side': trade_record.get('side'),
                'entry_price': trade_record.get('entry_price'),
                'signal_score': trade_record.get('signal_score'),
                'market_regime': trade_record.get('market_regime'),
                'features': trade_record.get('features')
            }
        
        if is_closed and symbol:
            pending = rm._pending_features.pop(symbol, {})
            for k, v in pending.items():
                if k not in trade_record or trade_record[k] is None:
                    trade_record[k] = v

        # Sérialiser les mutations de l'état partagé (trade_history,
        # consecutive_losses, last_trade_close_time) entre threads.
        with rm._history_lock:
            if is_closed:
                rm.trade_history.append(trade_record)

                # Garder seulement les 500 derniers trades pour la sécurité mémoire
                # (la BD SQLite est la vraie source de vérité)
                if len(rm.trade_history) > 500:
                    rm.trade_history = rm.trade_history[-500:]


            # Mise à jour des pertes consécutives
            symbol = trade_record.get('symbol')
            if symbol and trade_record.get('status') == 'closed' and trade_record.get('pnl') is not None:
                if trade_record.get('pnl', 0) < 0:
                    rm.consecutive_losses[symbol] = rm.consecutive_losses.get(symbol, 0) + 1
                    log.info(f"📉 Perte enregistrée pour {symbol}. Série de pertes: {rm.consecutive_losses[symbol]}")
                else:
                    rm.consecutive_losses[symbol] = 0
                    log.debug(f"📈 Gain enregistré pour {symbol}. Réinitialisation de la série de pertes.")
                # Enregistrer l'heure de clôture pour le cooldown.
                rm.last_trade_close_time[symbol] = datetime.now(timezone.utc)

            # N'écrire que les trades clôturés dans le fichier JSONL, sous le
            # même verrou pour éviter les écritures concurrentes corrompues.
            if is_closed:
                from superbot.config import TRADE_LOG_FILE
                trades_file = str(TRADE_LOG_FILE)
                log_dir = os.path.dirname(trades_file)
                os.makedirs(log_dir, exist_ok=True)
                with open(trades_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(trade_record, ensure_ascii=False, default=str) + '\n')

        log.debug(f"Trade enregistré: {trade_record.get('symbol', 'Unknown')} | P&L: {trade_record.get('pnl', 0):.2f}")

    except Exception as e:
        log.error(f"Erreur lors de l'enregistrement du trade: {e}")

def load_trade_history_from_disk(rm):
    """
    Charge l'historique des trades enregistrés depuis le fichier JSON Lines.
    Ne charge que les trades CLÔTURÉS avec un P&L valide pour éviter les erreurs Kelly.
    """
    try:
        from superbot.config import TRADE_LOG_FILE
        trades_file = str(TRADE_LOG_FILE)
        if not os.path.exists(trades_file):
            log.info("Aucun fichier d'historique de trades trouvé sur le disque.")
            return

        loaded_trades = []
        with open(trades_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        trade = json.loads(line.strip())
                        # Ne conserver que les trades clôturés AVEC un P&L valide
                        # Un trade ouvert n'a pas de champ 'pnl'
                        status = trade.get('status', 'closed' if trade.get('pnl') is not None else 'open')
                        if status == 'closed' and trade.get('pnl') is not None:
                            trade['status'] = 'closed'
                            loaded_trades.append(trade)
                    except Exception:
                        continue

        # Garder les 500 plus récents pour la sécurité mémoire
        # (la BD SQLite est la vraie source de vérité)
        rm.trade_history = loaded_trades[-500:]
        log.info(f"Historique de trading chargé depuis le disque : {len(rm.trade_history)} trades clôturés trouvés.")
    except Exception as e:
        log.error(f"Erreur lors du chargement de l'historique de trades : {e}")

# Fenêtre de rapprochement d'une ligne « bot » (sans ticket) avec un trade broker.
# Large car les anciennes lignes broker étaient horodatées en heure serveur (UTC+2/+3).
_MATCH_WINDOW_SECONDS = 6 * 3600
# Champs qui font foi côté broker (écrasent l'estimation du bot)
_BROKER_TRUTH_FIELDS = ('entry_price', 'exit_price', 'pnl', 'size', 'timestamp', 'open_time',
                        'close_reason', 'ticket', 'position_id')


def _parse_ts(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _same_trade(row: Dict[str, Any], ref: Dict[str, Any]) -> bool:
    """Même symbole, même sens, même prix d'entrée et clôtures proches dans le temps."""
    entry = float(ref.get('entry_price') or 0.0)
    if (row.get('symbol') != ref.get('symbol') or row.get('side') != ref.get('side') or entry <= 0
            or abs(float(row.get('entry_price') or 0.0) - entry) > entry * 1e-5):
        return False
    gap = abs((_parse_ts(row.get('timestamp')) - _parse_ts(ref.get('timestamp'))).total_seconds())
    return gap <= _MATCH_WINDOW_SECONDS


def _apply_broker_truth(row: Dict[str, Any], broker_trade: Dict[str, Any]):
    for key in _BROKER_TRUTH_FIELDS:
        if broker_trade.get(key) is not None:
            row[key] = broker_trade[key]
    for key in ('symbol', 'side'):
        row.setdefault(key, broker_trade.get(key))
    row['status'] = 'closed'
    row['verified'] = True
    row['target'] = 1 if float(row.get('pnl') or 0.0) > 0 else 0


def dedupe_trade_rows(rows: List[Dict[str, Any]], broker_trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Réconcilie le journal local avec les trades broker (une ligne par position).

    - Ligne déjà liée au même `position_id` : mise à jour avec la vérité broker.
    - Ligne « bot » sans ticket correspondant au trade : enrichie (elle garde ses features ML).
    - Sinon le trade broker est ajouté.
    Les anciens doublons (ligne bot + ligne broker du même trade) sont fusionnés.
    """
    rows = [dict(r) for r in rows]
    by_pid = {r['position_id']: r for r in rows if r.get('position_id')}

    for bt in broker_trades:
        bt = dict(bt)
        for key in ('timestamp', 'open_time'):
            if isinstance(bt.get(key), datetime):
                bt[key] = bt[key].isoformat()
        pid = bt.get('position_id')
        target = by_pid.get(pid) if pid else None
        if target is None:
            candidates = [r for r in rows if not r.get('position_id') and _same_trade(r, bt)]
            if candidates:
                ts = _parse_ts(bt.get('timestamp'))
                target = min(candidates, key=lambda r: abs((_parse_ts(r.get('timestamp')) - ts).total_seconds()))
        if target is None:
            target = {}
            rows.append(target)
        _apply_broker_truth(target, bt)
        if pid:
            by_pid[pid] = target

    # Fusionner les lignes bot orphelines dans la ligne broker du même trade (doublons historiques)
    merged_ids = set()
    for row in rows:
        if row.get('position_id'):
            continue
        twin = next((r for r in by_pid.values() if id(r) not in merged_ids and _same_trade(r, row)), None)
        if twin is not None:
            for key, value in row.items():
                if key not in twin or twin[key] is None:
                    twin[key] = value
            merged_ids.add(id(twin))
            row['_drop'] = True

    rows = [r for r in rows if not r.pop('_drop', False)]
    rows.sort(key=lambda r: _parse_ts(r.get('timestamp')))
    return rows


def merge_broker_history(rm, broker_trades: List[Dict[str, Any]]):
    """
    Fusionne l'historique du broker avec le journal local (sans doublons ni troncature).

    Le fichier JSONL conserve l'intégralité de l'historique ; seule la mémoire est
    limitée aux 500 derniers trades.
    """
    if not broker_trades:
        return

    from superbot.config import TRADE_LOG_FILE
    trades_file = str(TRADE_LOG_FILE)

    with rm._history_lock:
        rows = []
        if os.path.exists(trades_file):
            with open(trades_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        try:
                            rows.append(json.loads(line))
                        except json.JSONDecodeError:
                            log.warning("Ligne illisible ignorée dans le journal des trades.")
        else:
            rows = list(rm.trade_history)

        before = len(rows)
        rows = dedupe_trade_rows(rows, broker_trades)

        try:
            os.makedirs(os.path.dirname(trades_file), exist_ok=True)
            tmp_file = trades_file + '.tmp'
            with open(tmp_file, 'w', encoding='utf-8') as f:
                for t in rows:
                    f.write(json.dumps(t, ensure_ascii=False, default=str) + '\n')
            os.replace(tmp_file, trades_file)  # écriture atomique
        except Exception as e:
            log.error(f"Erreur lors de la sauvegarde post-fusion: {e}")

        rm.trade_history = [t for t in rows if t.get('status') == 'closed' and t.get('pnl') is not None][-500:]

    log.info(
        f"Fusion de l'historique broker terminée : {before} → {len(rows)} lignes dans le journal, "
        f"{sum(1 for t in rows if t.get('verified'))} vérifiées broker."
    )