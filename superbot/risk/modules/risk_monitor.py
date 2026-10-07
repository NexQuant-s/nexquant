import logging
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any
log = logging.getLogger(__name__)


def _is_night_session(start_utc: int = 20, end_utc: int = 6) -> bool:
    """
    Détermine si on est actuellement en session nocturne (heures UTC).

    La session nocturne correspond aux heures de faible liquidité durant lesquelles
    l'exposition doit être réduite pour éviter les sur-expositions liées au retournement
    de tendance lors de la session asiatique.

    Args:
        start_utc: Heure UTC de début de session nocturne (défaut: 20h)
        end_utc:   Heure UTC de fin   de session nocturne (défaut: 06h)

    Returns:
        True si l'heure courante (UTC) est dans la fenêtre nocturne
    """
    now_hour = datetime.now(timezone.utc).hour
    if start_utc > end_utc:  # Fenêtre traverse minuit (ex: 20h → 06h)
        return now_hour >= start_utc or now_hour < end_utc
    else:  # Fenêtre dans la même journée (ex: 08h → 18h)
        return start_utc <= now_hour < end_utc


def _can_take_new_trade(rm, account_balance: float, symbol: str = "") -> bool:
    """
    Vérifie si on peut prendre un nouveau trade basé sur les limites de risque.

    Args:
        account_balance: Solde actuel du compte
        symbol: Symbole de l'instrument

    Returns:
        True si on peut prendre un nouveau trade, False sinon
    """
    # Vérifier si on a déjà une position sur ce symbole
    if symbol and symbol in rm.open_positions:
        log.info(f"Position déjà ouverte pour {symbol}, rejet du nouveau trade.")
        return False

    # Vérifier les pertes consécutives sur ce symbole
    if symbol and rm.consecutive_losses.get(symbol, 0) >= 3:
        log.info(f"Symbole {symbol} bloqué (3 pertes consécutives atteintes).")
        return False

    # Cooldown : délai depuis la dernière clôture sur ce symbole.
    if symbol and symbol in rm.last_trade_close_time:
        last_close = rm.last_trade_close_time[symbol]
        now_utc = datetime.now(timezone.utc)
        # Rendre cohérent si last_close est naïf (ancienne données)
        if last_close.tzinfo is None:
            last_close = last_close.replace(tzinfo=timezone.utc)
        elapsed = (now_utc - last_close).total_seconds()
        if elapsed < rm.COOLDOWN_SECONDS:
            remaining_min = (rm.COOLDOWN_SECONDS - elapsed) / 60
            log.info(f"Cooldown actif pour {symbol} : {remaining_min:.0f}min restantes avant prochain trade autorisé")
            return False

    # Vérifier le nombre maximum de positions ouvertes
    # 🌙 PROTECTION NOCTURNE (fix sur-exposition 23-24/07/2026) :
    # En session nocturne (20h-06h UTC), limiter à MAX_OPEN_POSITIONS_NIGHT positions
    # pour éviter une sur-exposition corrélée sur les paires USD.
    try:
        from superbot.config import (
            MAX_OPEN_POSITIONS_NIGHT, NIGHT_SESSION_START_UTC, NIGHT_SESSION_END_UTC
        )
    except ImportError:
        MAX_OPEN_POSITIONS_NIGHT = 3
        NIGHT_SESSION_START_UTC = 20
        NIGHT_SESSION_END_UTC = 6

    if _is_night_session(NIGHT_SESSION_START_UTC, NIGHT_SESSION_END_UTC):
        effective_max = min(rm.MAX_OPEN_POSITIONS, MAX_OPEN_POSITIONS_NIGHT)
        if len(rm.open_positions) >= effective_max:
            log.info(
                f"🌙 Limite nocturne atteinte: {len(rm.open_positions)}/{effective_max} positions "
                f"(session nocturne 20h-06h UTC — réduction du risque d'exposition corrélée)"
            )
            return False
    elif len(rm.open_positions) >= rm.MAX_OPEN_POSITIONS:
        log.info(f"Nombre maximum de positions atteint: {len(rm.open_positions)}/{rm.MAX_OPEN_POSITIONS}")
        return False

    # Vérifier la limite de perte quotidienne et mensuelle (si activée)
    if getattr(rm, 'ENABLE_LOSS_LIMIT', False):
        daily_loss_amount = abs(min(0, rm.daily_pnl))
        daily_loss_pct = daily_loss_amount / account_balance * 100 if account_balance > 0 else 0
        max_daily_amount = getattr(rm, 'MAX_DAILY_LOSS_AMOUNT', 100.0)

        if daily_loss_amount >= max_daily_amount:
            log.info(f"🚫 Limite de perte quotidienne absolue atteinte: {daily_loss_amount:.2f}€ >= {max_daily_amount:.2f}€ max")
            return False

        effective_max_daily_loss = rm.MAX_DAILY_LOSS_PCT
        if account_balance > 0 and account_balance < 200.0:
            effective_max_daily_loss = max(rm.MAX_DAILY_LOSS_PCT, 15.0)

        if daily_loss_pct >= effective_max_daily_loss:
            log.info(f"Limite de perte quotidienne atteinte: {daily_loss_pct:.2f}% >= {effective_max_daily_loss}%")
            return False

        # Vérifier la limite de perte mensuelle
        monthly_loss_pct = abs(min(0, rm.monthly_pnl)) / account_balance * 100 if account_balance > 0 else 0
        effective_max_monthly_loss = rm.MAX_MONTHLY_LOSS_PCT
        if account_balance > 0 and account_balance < 200.0:
            effective_max_monthly_loss = max(rm.MAX_MONTHLY_LOSS_PCT, 25.0)

        if monthly_loss_pct >= effective_max_monthly_loss:
            log.info(f"Limite de perte mensuelle atteinte: {monthly_loss_pct:.2f}% >= {effective_max_monthly_loss}%")
            return False

    return True

def get_risk_metrics(rm, account_balance: float = 0.0) -> Dict[str, Any]:
    """
    Retourne les métriques de risque actuelles.

    Args:
        account_balance: Solde actuel du compte

    Returns:
        Dictionnaire contenant les métriques de risque
    """
    try:
        if account_balance <= 0:
            account_balance = getattr(rm, 'starting_balance', 10000.0)
        # Filtrer les None dans balance_after pour éviter un drawdown artificiel.
        balance_after_values = [
            t['balance_after'] for t in rm.trade_history
            if t.get('balance_after') is not None and isinstance(t['balance_after'], (int, float))
        ]
        peak_balance = max([rm.starting_balance] + balance_after_values + [account_balance])
        drawdown = peak_balance - account_balance
        drawdown_pct = (drawdown / peak_balance) * 100 if peak_balance > 0 else 0

        # Calculer le taux de victoire
        winning_trades = [t for t in rm.trade_history if t.get('pnl', 0) > 0]
        win_rate = len(winning_trades) / len(rm.trade_history) if rm.trade_history else 0

        # Calculer le profit factor
        gross_profit = sum([t['pnl'] for t in rm.trade_history if t.get('pnl', 0) > 0])
        gross_loss = abs(sum([t['pnl'] for t in rm.trade_history if t.get('pnl', 0) < 0]))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        # Calculer le gain moyen/perte moyenne
        avg_win = np.mean([t['pnl'] for t in winning_trades]) if winning_trades else 0
        losing_trades = [t for t in rm.trade_history if t.get('pnl', 0) < 0]
        avg_loss = np.mean([abs(t['pnl']) for t in losing_trades]) if losing_trades else 0

        # Risque actuel basé sur les positions ouvertes
        current_risk = 0.0
        for position in rm.open_positions.values():
            if 'size' in position and 'entry_price' in position and 'stop_loss' in position:
                risk_per_unit = abs(position['entry_price'] - position['stop_loss'])
                position_risk = position['size'] * risk_per_unit
                current_risk += position_risk

        current_risk_pct = (current_risk / account_balance) * 100 if account_balance > 0 else 0

        metrics = {
            'account_balance': account_balance,
            'starting_balance': rm.starting_balance,
            'total_pnl': account_balance - rm.starting_balance,
            'total_pnl_pct': ((account_balance / rm.starting_balance) - 1) * 100 if rm.starting_balance > 0 else 0,
            'daily_pnl': rm.daily_pnl,
            'daily_pnl_pct': (rm.daily_pnl / account_balance) * 100 if account_balance > 0 else 0,
            'monthly_pnl': rm.monthly_pnl,
            'monthly_pnl_pct': (rm.monthly_pnl / account_balance) * 100 if account_balance > 0 else 0,
            'drawdown': drawdown,
            'drawdown_pct': drawdown_pct,
            'open_positions_count': len(rm.open_positions),
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'trades_count': len(rm.trade_history),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'current_risk_pct': current_risk_pct,
            'kelly_fraction': rm._calculate_kelly_fraction(),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

        return metrics

    except Exception as e:
        log.error(f"Erreur lors du calcul des métriques de risque: {e}")
        return {'error': str(e), 'timestamp': datetime.now(timezone.utc).isoformat()}