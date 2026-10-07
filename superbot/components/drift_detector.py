import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger("drift_detector")

def detect_model_drift(bot):
    """
    Détecte une éventuelle dérive du modèle en surveillant le taux de victoire récent.
    Met en pause le bot en cas de dérive sévère et réduit le risque.
    """
    # Check if pause expired
    if hasattr(bot, '_drift_pause_until'):
        if datetime.now(timezone.utc) >= bot._drift_pause_until:
            bot.is_paused = False
            del bot._drift_pause_until
            log.info("▶️ Fin de la pause de dérive. Reprise du trading.")
        else:
            return  # Still paused

    # Filtrer uniquement les trades CLÔTURÉS avec P&L valide
    closed_trades = [t for t in bot.risk_manager.trade_history if t.get('status') == 'closed' and t.get('pnl') is not None]

    if len(closed_trades) < 10:
        return  # Pas assez de données pour détecter une dérive

    # Ne ré-évaluer la dérive que lorsqu'un nouveau trade a été clôturé
    closed_count = len(closed_trades)
    if getattr(bot, '_last_drift_checked_trades', 0) == closed_count:
        return
    bot._last_drift_checked_trades = closed_count

    # Calculer le taux de victoire sur les 10 derniers trades clôturés
    recent = closed_trades[-10:]
    winning = sum(1 for t in recent if t.get('pnl', 0) > 0)
    win_rate = winning / len(recent) if recent else 0.0

    # Plancher de sécurité strict : le risque ne doit jamais descendre sous 0.5%
    MIN_ADAPTIVE_RISK = 0.5

    # Chaque réduction n'est appliquée qu'UNE fois (le code dupliqué divisait le risque par 8).
    if win_rate < 0.20:
        bot.adaptive_risk_pct = max(MIN_ADAPTIVE_RISK, round(bot.adaptive_risk_pct * 0.5, 2))
        if getattr(bot, 'auto_unpause', False):
            log.warning(f"⚠️ Dérive détectée: taux de victoire ({win_rate:.2f}). Réduction du risque de 50% (auto-unpause actif: pas de pause pour maintenir le trading continu).")
        else:
            log.error(f"🚨 Dérive sévère détectée: taux de victoire ({win_rate:.2f}). Mise en pause 2h et réduction du risque de 50%.")
            bot.is_paused = True
            bot._drift_pause_until = datetime.now(timezone.utc) + timedelta(hours=2)
    elif win_rate < 0.30:
        log.warning(f"⚠️ Dérive modérée détectée: taux de victoire ({win_rate:.2f}). Réduction du risque de 25%.")
        bot.adaptive_risk_pct = max(MIN_ADAPTIVE_RISK, round(bot.adaptive_risk_pct * 0.75, 2))

