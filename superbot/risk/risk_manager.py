"""
╔═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╩
"""
from typing import Dict, Any, Tuple, List, Optional
import logging
from datetime import datetime
import threading

log = logging.getLogger("risk_manager")


class RiskManager:
    """
    Gestionnaire de risque professionnel basé sur les principes d'Elder et Kabbaj.
    Implémente les règles des 2% par trade et 6% mensuel, la taille de position Kelly,
    l'ajustement basé sur la volatilité et la corrélation, ainsi que le trailing stop.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialise le gestionnaire de risque.

        Args:
            config: Dictionnaire contenant la configuration de risque
                   (RISK_PCT, MAX_DAILY_LOSS_PCT, MAX_MONTHLY_LOSS_PCT,
                    MAX_OPEN_POSITIONS, KELLY_FRACTION, etc.)
        """
        self.config = config
        self.ENABLE_LOSS_LIMIT = config.get('ENABLE_LOSS_LIMIT', False)
        self.RISK_PCT = config.get('RISK_PCT', 1.0)  # % du compte à risquer par trade
        self.MAX_DAILY_LOSS_PCT = config.get('MAX_DAILY_LOSS_PCT', 3.0)  # % max perte journalier
        self.MAX_MONTHLY_LOSS_PCT = config.get('MAX_MONTHLY_LOSS_PCT', 6.0)  # % max perte mensuel
        self.MAX_OPEN_POSITIONS = config.get('MAX_OPEN_POSITIONS', 2)  # Max positions simultanées
        self.KELLY_FRACTION = config.get('KELLY_FRACTION', 0.25)  # Fraction de Kelly à utiliser
        self.MIN_TRADES_FOR_KELLY = config.get('MIN_TRADES_FOR_KELLY', 20)  # Trades min pour Kelly
        self.SL_ATR_MULT = config.get('SL_ATR_MULT', 1.5)  # Multiplicateur ATR pour SL
        self.TP_ATR_MULT = config.get('TP_ATR_MULT', 3.0)  # Multiplicateur ATR pour TP
        self.TRAIL_ATR_MULT = config.get('TRAIL_ATR_MULT', 1.0)  # Multiplicateur ATR pour trailing
        self.TRAIL_ACTIVATE_ATR_MULT = config.get('TRAIL_ACTIVATE_ATR_MULT', 2.0)  # Distance d'activation du trailing (×ATR)
        self.BE_ATR_MULT = config.get('BE_ATR_MULT', 1.0)  # Multiplicateur ATR pour break-even
        self.BE_DYN_RR = config.get('BE_DYN_RR', True)  # Activer le break-even dynamique (1:1 R:R)
        self.BE_DYN_RR_RATIO = config.get('BE_DYN_RR_RATIO', 1.5)  # Ratio R:R pour le break-even dynamique
        self.MIN_POSITION_SIZE = config.get('MIN_POSITION_SIZE', 0.001)  # Taille min position
        self.MAX_POSITION_SIZE = config.get('MAX_POSITION_SIZE', 1000.0)  # Taille max position
        # Limite absolue journalière (en devise de compte)
        self.MAX_DAILY_LOSS_AMOUNT = config.get('MAX_DAILY_LOSS_AMOUNT', 100.0)

        # Verrou interne : sérialise l'accès à trade_history / open_positions /
        # consecutive_losses entre threads (workers du cycle, webhook, sync).
        self._history_lock = threading.RLock()


        # Multiplicateurs ATR dynamiques par type d'actif
        self.ATR_MULTIPLIERS = {
            'forex': {'sl': 1.5, 'tp': 3.0},
            # Paires JPY plus volatiles (150-250 pips/jour vs 60-100) : SL/TP élargis
            # pour éviter les fermetures prématurées tout en gardant un R:R de 1:2.
            'forex_jpy': {'sl': 2.0, 'tp': 4.0},
            'commodity': {'sl': 1.8, 'tp': 3.6},
            'stock': {'sl': 2.0, 'tp': 4.0},
            'crypto': {'sl': 2.5, 'tp': 5.0}
        }

        # Historique des trades pour le calcul de Kelly
        self.trade_history: List[Dict[str, Any]] = []
        self.daily_pnl = 0.0
        self.monthly_pnl = 0.0
        self.starting_balance = 0.0
        self.current_balance = 0.0
        self.day_start_balance = 0.0
        self.month_start_balance = 0.0
        self.last_daily_reset = datetime.now().date()
        self.last_monthly_reset = datetime.now().replace(day=1).date()

        # Protection par drawdown : suivi du pic d'équité pour calculer le drawdown en temps réel.
        # Le risque par trade est réduit progressivement lorsque le compte
        # est en drawdown : -20% de risque à 5% DD, -50% à 10% DD.
        self.peak_balance: float = 0.0  # Plus haut historique (établi au premier update_account_balance)
        self.drawdown_pct: float = 0.0  # Drawdown courant en %
        self.DRAWDOWN_REDUCE_5PCT = config.get('DRAWDOWN_REDUCE_5PCT', 0.20)   # -20% risque à 5% DD
        self.DRAWDOWN_REDUCE_10PCT = config.get('DRAWDOWN_REDUCE_10PCT', 0.50)  # -50% risque à 10% DD
        self.DRAWDOWN_THRESH_1 = config.get('DRAWDOWN_THRESH_1', 5.0)   # % déclencheur niveau 1
        self.DRAWDOWN_THRESH_2 = config.get('DRAWDOWN_THRESH_2', 10.0)  # % déclencheur niveau 2

        # Cooldown entre deux trades sur le même symbole : 1h = une bougie H1 complète
        # pour laisser le contexte marché changer.
        self.COOLDOWN_SECONDS = config.get('COOLDOWN_SECONDS', 300)
        self.last_trade_close_time: Dict[str, datetime] = {}  # symbol -> heure de dernière clôture

        # Positions actuelles et historique
        self.open_positions: Dict[str, Dict[str, Any]] = {}
        self.position_history: List[Dict[str, Any]] = []
        self.consecutive_losses: Dict[str, int] = {}

        log.info(f"RiskManager initialisé avec config: {self.config}")

    def update_account_balance(self, balance: float):
        """
        Met à jour le solde du compte et réinitialise les périodes si nécessaire.

        Args:
            balance: Nouveau solde du compte
        """
        if balance <= 0:
            return  # Ignore zero/negative balance from broker init

        from datetime import timezone
        # Réinitialisation quotidienne
        today = datetime.now(timezone.utc).date()
        if today > self.last_daily_reset:
            self.daily_pnl = 0.0
            self.last_daily_reset = today
            self.consecutive_losses = {}  # Reset daily consecutive losses
            self.day_start_balance = balance  # IMPORTANT: Update daily start balance
            # Nettoyer les cooldowns du jour précédent pour ne pas bloquer les premiers trades du jour.
            self.last_trade_close_time = {}
            log.debug("Réinitialisation du P&L journalier, pertes consécutives et cooldowns")

        # Réinitialisation mensuelle
        if today.month > self.last_monthly_reset.month or today.year > self.last_monthly_reset.year:
            self.monthly_pnl = 0.0
            self.last_monthly_reset = today.replace(day=1)
            log.debug("Réinitialisation du P&L mensuel")

        # Mettre à jour le solde
        if self.starting_balance <= 0:
            self.starting_balance = balance
        if self.day_start_balance <= 0:
            self.day_start_balance = balance
        if self.month_start_balance <= 0:
            self.month_start_balance = balance
        self.current_balance = balance

        # Évite un drawdown erroné quand peak_balance est encore 0 et le solde > 0.
        if self.peak_balance == 0.0 and balance > 0:
            self.peak_balance = balance
        elif balance > self.peak_balance:
            self.peak_balance = balance
        if self.peak_balance > 0:
            self.drawdown_pct = (self.peak_balance - balance) / self.peak_balance * 100
        else:
            self.drawdown_pct = 0.0

        # Calculer le P&L
        self.daily_pnl = balance - self.day_start_balance
        self.monthly_pnl = balance - self.month_start_balance

        log.debug(f"Solde mis à jour: {balance:.2f} | Daily P&L: {self.daily_pnl:.2f} | Monthly P&L: {self.monthly_pnl:.2f} | Drawdown: {self.drawdown_pct:.1f}%")

    def check_kill_switch(self, account_balance: float) -> bool:
        """
        Vérifie le Kill-Switch de Drawdown journalier et mensuel.
        Retourne True si le bot doit se mettre en auto-pause pour la journée.
        Si ENABLE_LOSS_LIMIT est False, la limite de perte est désactivée.
        """
        if not getattr(self, 'ENABLE_LOSS_LIMIT', False):
            return False

        if self.day_start_balance > 0:
            daily_loss_pct = abs(min(0, self.daily_pnl)) / self.day_start_balance * 100
            effective_max_daily = self.MAX_DAILY_LOSS_PCT
            if self.day_start_balance < 200.0:
                effective_max_daily = max(self.MAX_DAILY_LOSS_PCT, 15.0)
            if daily_loss_pct >= effective_max_daily:
                log.critical(f"⚠️ KILL-SWITCH ACTIVÉ : Perte journalière ({daily_loss_pct:.2f}%) >= {effective_max_daily}%.")
                return True
            if self.daily_pnl <= -self.MAX_DAILY_LOSS_AMOUNT:
                log.critical(f"⚠️ KILL-SWITCH ACTIVÉ : Perte absolue journalière ({self.daily_pnl:.2f}) <= {-self.MAX_DAILY_LOSS_AMOUNT}.")
                return True
        if self.month_start_balance > 0:
            monthly_loss_pct = abs(min(0, self.monthly_pnl)) / self.month_start_balance * 100
            effective_max_monthly = self.MAX_MONTHLY_LOSS_PCT
            if self.month_start_balance < 200.0:
                effective_max_monthly = max(self.MAX_MONTHLY_LOSS_PCT, 25.0)
            if monthly_loss_pct >= effective_max_monthly:
                log.critical(f"⚠️ KILL-SWITCH ACTIVÉ : Perte mensuelle ({monthly_loss_pct:.2f}%) >= {effective_max_monthly}%.")
                return True
        return False

    def _can_take_new_trade(self, account_balance: float = 0.0, symbol: str = "") -> bool:
        """Délègue à risk_monitor._can_take_new_trade sous verrou (lectures cohérentes)."""
        from superbot.risk.modules.risk_monitor import _can_take_new_trade
        with self._history_lock:
            return _can_take_new_trade(self, account_balance, symbol)

    def calculate_position_size(self, account_balance: float, entry_price: float,
                                stop_loss: float, symbol: str = "",
                                sentiment_factor: float = 1.0,
                                volatility_data: Optional[Dict[str, Any]] = None,
                                correlation_data: Optional[Dict[str, Any]] = None,
                                broker: Optional[Any] = None,
                                hmm_regime: str = "") -> Tuple[float, Dict[str, Any]]:
        from superbot.risk.modules.position_sizer import calculate_position_size
        return calculate_position_size(
            self, account_balance=account_balance, entry_price=entry_price,
            stop_loss=stop_loss, symbol=symbol,
            sentiment_factor=sentiment_factor, volatility_data=volatility_data,
            correlation_data=correlation_data, broker=broker, hmm_regime=hmm_regime
        )

    def _calculate_kelly_fraction(self) -> Optional[float]:
        from superbot.risk.modules.position_sizer import _calculate_kelly_fraction
        return _calculate_kelly_fraction(self)

    def calculate_sl_tp_levels(self, current_price: float = 0.0, atr: float = 0.0, direction: str = "LONG",
                               asset_type: str = "forex", symbol: str = "", hmm_regime: str = "TRENDING",
                               entry_price: Optional[float] = None, atr_value: Optional[float] = None,
                               position_side: Optional[str] = None, **kwargs) -> Tuple[float, float]:
        price = entry_price if entry_price is not None else current_price
        atr_val = atr_value if atr_value is not None else atr
        side = position_side if position_side is not None else direction
        from superbot.risk.modules.stop_manager import calculate_sl_tp_levels
        return calculate_sl_tp_levels(self, price, atr_val, side, asset_type, symbol, hmm_regime)

    def record_trade(self, trade_record: Dict[str, Any]):
        from superbot.risk.modules.trade_recorder import record_trade
        return record_trade(self, trade_record)

    def load_trade_history_from_disk(self):
        from superbot.risk.modules.trade_recorder import load_trade_history_from_disk
        return load_trade_history_from_disk(self)

    def merge_broker_history(self, broker_trades: list):
        from superbot.risk.modules.trade_recorder import merge_broker_history
        return merge_broker_history(self, broker_trades)

    def update_open_position(self, symbol: str, current_price: float):
        """
        Met à jour une position ouverte avec le prix actuel pour le trailing stop et le break-even.

        Args:
            symbol: Symbole de la position
            current_price: Prix actuel du marché
        """
        # Verrou interne : la mutation de open_positions[symbol] doit rester
        # cohérente face aux rebinds du position_syncer et aux autres threads.
        with self._history_lock:
            self._update_open_position_impl(symbol, current_price)

    def _update_open_position_impl(self, symbol: str, current_price: float):
        if symbol not in self.open_positions:
            return

        position = self.open_positions[symbol]

        if 'initial_sl' not in position or position['initial_sl'] == 0:
            position['initial_sl'] = position.get('stop_loss', 0.0)

        try:
            entry_price = position['entry_price']
            if entry_price <= 0:
                raw_pnl = 0.0
                pnl_pct = 0.0
            elif position['side'] == 'LONG':
                raw_pnl = (current_price - entry_price) * position['size']
                pnl_pct = (current_price / entry_price - 1) * 100
            else:  # SHORT
                raw_pnl = (entry_price - current_price) * position['size']
                pnl_pct = (entry_price - current_price) / entry_price * 100

            sym = position.get('symbol', symbol)
            normalized_sym = sym.strip().upper().replace("/", "")
            if normalized_sym.endswith("JPY") and current_price > 0:
                pnl = raw_pnl / current_price
                log.debug(f"Conversion PnL unrealized JPY→USD pour {sym}: {raw_pnl:.2f} JPY / {current_price:.3f} = {pnl:.2f} USD")
            else:
                pnl = raw_pnl

            position['current_price'] = current_price
            position['unrealized_pnl'] = pnl
            position['unrealized_pnl_pct'] = pnl_pct
            position['last_update'] = datetime.now().isoformat()

            self._check_trailing_stop(symbol, position, current_price)
            self._check_break_even(symbol, position, current_price)

        except Exception as e:
            log.error(f"Erreur lors de la mise à jour de la position {symbol}: {e}")

    def _check_trailing_stop(self, *args, **kwargs):
        # Signature robuste pour accepter n'importe quelle variante d'arguments
        symbol = kwargs.get('symbol')
        pos = kwargs.get('pos') or kwargs.get('position')
        current_price = kwargs.get('current_price')

        positional = list(args)
        if positional and hasattr(positional[0], 'open_positions'):
            positional = positional[1:]

        if len(positional) >= 3:
            symbol, pos, current_price = positional[0], positional[1], positional[2]
        elif len(positional) == 2:
            symbol, current_price = positional[0], positional[1]
            pos = self.open_positions.get(symbol)

        if pos is None and symbol in self.open_positions:
            pos = self.open_positions[symbol]

        if symbol and pos and current_price is not None:
            from superbot.risk.modules.stop_manager import _check_trailing_stop
            return _check_trailing_stop(self, symbol, pos, current_price)

    def _check_break_even(self, symbol: str, pos: dict, current_price: float):
        from superbot.risk.modules.stop_manager import _check_break_even
        return _check_break_even(self, symbol, pos, current_price)

    def get_risk_metrics(self, account_balance: float = 0.0) -> Dict[str, Any]:
        """Lecture cohérente des métriques sous verrou (trade_history / open_positions)."""
        from superbot.risk.modules.risk_monitor import get_risk_metrics
        with self._history_lock:
            return get_risk_metrics(self, account_balance)

    def reset_daily_stats(self):
        """Réinitialise les statistiques journalières."""
        self.daily_pnl = 0.0
        self.last_daily_reset = datetime.now().date()
        self.consecutive_losses = {}
        log.info("Statistiques journalières réinitialisées")

    def reset_monthly_stats(self):
        """Réinitialise les statistiques mensuelles."""
        self.monthly_pnl = 0.0
        self.last_monthly_reset = datetime.now().replace(day=1).date()
        log.info("Statistiques mensuelles réinitialisées")

    # =========================================================================
    # 🧠 V3 : TARGET-AWARE RISK MANAGEMENT
    # =========================================================================

    def get_target_aware_risk_pct(self, daily_pnl: float, daily_target: float,
                                   base_risk_pct: float = None) -> float:
        """
        Ajuste le risque par trade en fonction du PnL journalier vs objectif.
        Implémente la logique du plan V3 Phase 7.

        > 100% target atteint   ÷ 0.4 (mode ultra-conservation des gains)
        >  75% target atteint   ÷ 0.6 (mode conservation des gains)
        >  50% target atteint   ÷ 0.8 (légère réduction)
        PnL < -75% target       ÷ 3.0 (mode ultra-défensif)
        PnL < -50% target       ÷ 2.0 (mode défensif)
        PnL entre -50% et 0%    inchangé (zone neutre)
        PnL en retard important ×1.15 (légèrement plus agressif, cap 2%)
        """
        if base_risk_pct is None:
            base_risk_pct = self.RISK_PCT

        if daily_target <= 0:
            return base_risk_pct

        pct_achieved = daily_pnl / daily_target

        # PERTES : vérifier d'abord les cas de pertes (priorité absolue sur la protection)
        if daily_pnl < -0.75 * daily_target:
            # Perte sévère → mode ultra-défensif
            adjusted = base_risk_pct * 0.33
            log.warning(f"TargetAware: perte sévère ({daily_pnl:.1f}€) → risque ×0.33")
        elif daily_pnl < -0.50 * daily_target:
            # Perte modérée → mode défensif
            adjusted = base_risk_pct * 0.5
            log.warning(f"TargetAware: perte modérée ({daily_pnl:.1f}€) → risque ×0.5")
        # GAINS : ensuite vérifier les objectifs atteints
        elif pct_achieved >= 1.0:
            # Objectif atteint → mode ultra-conservation
            adjusted = base_risk_pct * 0.4
            log.debug(f"TargetAware: objectif atteint ({pct_achieved:.0%}) → risque ×0.4")
        elif pct_achieved >= 0.75:
            # 75% atteint → conservation
            adjusted = base_risk_pct * 0.6
            log.debug(f"TargetAware: 75% atteint ({pct_achieved:.0%}) → risque ×0.6")
        elif pct_achieved >= 0.5:
            # 50% atteint → légère réduction
            adjusted = base_risk_pct * 0.8
        elif pct_achieved < 0:
            # Zone de perte modérée (entre -50% et 0%) : ne pas modifier.
            adjusted = base_risk_pct
            log.debug(f"TargetAware: zone de perte modérée ({pct_achieved:.0%}) → risque inchangé")
        else:
            # Zone neutre (0-50%) ou en légèrement retard → légèrement plus agressif
            if pct_achieved < 0.25:
                adjusted = min(base_risk_pct * 1.15, 2.0)
                log.debug(f"TargetAware: en retard ({pct_achieved:.0%}) → risque ×1.15 (cap 2%)")
            else:
                adjusted = base_risk_pct

        return round(max(0.1, adjusted), 3)

    # Ratios de régime appliqués aux multiplicateurs de base (tendance = référence 1.0).
    # Avec la base 1.5/3.0 : range → 1.2/1.8, breakout → 1.8/3.6, haute vol → 2.0/4.0.
    _REGIME_SL_TP_RATIOS = (
        ('ranging', 0.8, 0.6),
        ('breakout', 1.2, 1.2),
        ('high_vol', 4.0 / 3.0, 4.0 / 3.0),
        ('volatile', 4.0 / 3.0, 4.0 / 3.0),
    )

    @staticmethod
    def get_regime_sl_tp_multipliers(regime: str, session: str = 'LONDON',
                                      asset_class: str = 'forex',
                                      base_sl: float = 1.5, base_tp: float = 3.0) -> dict:
        """
        Retourne les multiplicateurs SL/TP adaptatifs selon le régime + session + asset class.

        `base_sl` / `base_tp` = SL_ATR_MULT / TP_ATR_MULT configurés (.env) ; le régime
        applique un ratio relatif à la tendance (auparavant les valeurs étaient codées en dur
        et le .env était ignoré pour les ordres live).

        RANGING  → SL=0.8×base, TP=0.6×base (1.2/1.8 avec 1.5/3.0)
        TRENDING → base (1.5/3.0)
        HIGH_VOL → ×4/3 (2.0/4.0)
        BREAKOUT → ×1.2 (1.8/3.6)
        """
        sl_mult = float(base_sl)
        tp_mult = float(base_tp)

        regime_low = (regime or '').lower()
        session_up = (session or '').upper()

        # Ajustement par régime (ratios relatifs à la tendance)
        for key, sl_ratio, tp_ratio in RiskManager._REGIME_SL_TP_RATIOS:
            if key in regime_low:
                # arrondi intermédiaire : 1.5 × 1.2 doit valoir exactement 1.8 (pas 1.7999…)
                sl_mult = round(sl_mult * sl_ratio, 10)
                tp_mult = round(tp_mult * tp_ratio, 10)
                break

        # Ajustement supplémentaire par session
        if session_up == 'OVERLAP':
            sl_mult *= 1.1
            tp_mult *= 1.1
        elif session_up in ('OFF_HOURS', 'ASIA'):
            sl_mult *= 0.9
            tp_mult *= 0.85

        # Ajustement par asset class
        if asset_class == 'crypto':
            sl_mult *= 1.3
            tp_mult *= 1.3
        elif asset_class == 'forex_jpy':
            sl_mult *= 1.25
            tp_mult *= 1.25

        return {
            'sl_atr_mult': round(sl_mult, 2),
            'tp_atr_mult': round(tp_mult, 2),
        }



# Fonctions utilitaires pour une utilisation facile
def calculate_position_size_from_risk(account_balance: float, risk_pct: float,
                                    entry_price: float, stop_loss: float) -> float:
    """
    Fonction utilitaire pour calculer rapidement la taille de position basée sur le risque.

    Args:
        account_balance: Solde du compte
        risk_pct: Pourcentage du compte à risquer (ex: 2.0 pour 2%)
        entry_price: Prix d'entrée
        stop_loss: Niveau de stop loss

    Returns:
        Taille de position
    """
    risk_per_unit = abs(entry_price - stop_loss)
    if risk_per_unit <= 0:
        return 0.0
    risk_amount = account_balance * (risk_pct / 100.0)
    return risk_amount / risk_per_unit


# Export des classes et fonctions publiques
__all__ = [
    'RiskManager',
    'calculate_position_size_from_risk'
]