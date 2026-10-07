from __future__ import annotations
"""
Stratégie 5 : London Open Breakout (Asian Box Expansion)
=========================================================
Référence : Stratégie institutionnelle Forex & Or (London Session Breakout)

Mécanisme :
1. Boîte de session asiatique (00:00 - 07:00 UTC) : Définit le range de référence (`asian_high`, `asian_low`).
2. Filtre de range : Si le range asiatique est trop large (> 50 pips en Forex, > $25 sur l'Or), le breakout est ignoré car l'énergie est déjà dépensée.
3. Fenêtre de déclenchement : 07:00 - 10:30 UTC (Ouverture de la bourse de Londres & Francfort).
4. Signal d'entrée :
   - Long : Clôture ou dépassement de `asian_high` + buffer de 2 pips avec volume croissant.
   - Short : Clôture ou dépassement de `asian_low` - buffer de 2 pips avec volume croissant.
5. Gestion du risque :
   - SL : Ligne médiane de la boîte asiatique (50% de retracement).
   - TP : 2.0 $\times$ amplitude du range asiatique.
"""

from typing import Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime, timezone
import pandas as pd

from superbot.strategy.base_strategy import BaseStrategy, SignalResult
if TYPE_CHECKING:
    from superbot.brain.regime_detector import RegimeResult
from superbot.strategy.knowledge_base import calculate_asian_range, utc_bar_times


class LondonBreakoutStrategy(BaseStrategy):
    """Stratégie d'ouverture de session de Londres (London Breakout)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(name="LONDON_BREAKOUT", config=config)
        self.max_asian_range_pips = float(self.config.get("MAX_ASIAN_RANGE_PIPS", 50.0))
        self.tp_range_mult = float(self.config.get("TP_ASIAN_RANGE_MULT", 1.8))

    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str,
        regime: RegimeResult,
        asset_class: str,
        current_price: float,
        pip_size: float = 0.0001
    ) -> SignalResult:
        if df is None or len(df) < 5:
            return SignalResult(strategy_name=self.name, market_regime=regime.regime)

        last = df.iloc[-1]
        close = current_price if current_price > 0 else float(last['close'])
        atr = float(last.get('atr', 0.0))
        if atr <= 0:
            atr = abs(float(last['high']) - float(last['low']))

        import logging
        log = logging.getLogger("nexquant.london_breakout")
        
        # Vérifier l'heure UTC actuelle
        current_hour = 8
        if hasattr(df.index, 'hour') and len(df.index) > 0:
            current_hour = utc_bar_times(df)[-1].hour  # heure UTC réelle (bougies MT5 en heure serveur)
        elif 'time' in df.columns and pd.api.types.is_datetime64_any_dtype(df['time']):
            current_hour = df['time'].iloc[-1].hour
        else:
            log.warning("LondonBreakout: Fallback to real-time clock! This will break backtesting.")
            current_hour = datetime.now(timezone.utc).hour

        # La stratégie n'opère qu'entre 07:00 UTC et 11:30 UTC
        is_london_window = (7 <= current_hour <= 11)

        asian_high, asian_low, asian_range = calculate_asian_range(df)
        asian_range_pips = (asian_range / pip_size) if pip_size > 0 else (asian_range / 0.0001)

        # Filtre sur la largeur de la session asiatique
        is_valid_asian_range = (0 < asian_range_pips <= self.max_asian_range_pips)

        trigger_long = False
        trigger_short = False

        buffer = 2.0 * pip_size
        if is_london_window and is_valid_asian_range:
            if close >= (asian_high + buffer):
                trigger_long = True
            elif close <= (asian_low - buffer):
                trigger_short = True

        score = 0.0
        if trigger_long:
            score += 5.0
            if is_london_window:
                score += 2.0
            if regime.regime in ['breakout', 'trending_bull']:
                score += 2.0
            if asian_range_pips <= 35:
                score += 1.0  # Compression asiatique très serrée
        elif trigger_short:
            score += 5.0
            if is_london_window:
                score += 2.0
            if regime.regime in ['breakout', 'trending_bear']:
                score += 2.0
            if asian_range_pips <= 35:
                score += 1.0

        sl_price = 0.0
        tp_price = 0.0
        rr_ratio = 0.0

        asian_mid = (asian_high + asian_low) / 2.0 if (asian_high > asian_low) else (close - atr)

        if trigger_long:
            sl_price = asian_mid
            stop_dist = max(close - sl_price, atr * 0.5)
            tp_price = close + max(asian_range * self.tp_range_mult, stop_dist * 2.0)
            rr_ratio = (tp_price - close) / stop_dist

        elif trigger_short:
            sl_price = asian_mid
            stop_dist = max(sl_price - close, atr * 0.5)
            tp_price = close - max(asian_range * self.tp_range_mult, stop_dist * 2.0)
            rr_ratio = (close - tp_price) / stop_dist

        return SignalResult(
            should_long=trigger_long and score >= 6.0 and is_london_window,
            should_short=trigger_short and score >= 6.0 and is_london_window,
            trigger_long=trigger_long,
            trigger_short=trigger_short,
            total_score=score,
            strategy_name=self.name,
            market_regime=regime.regime,
            confidence=regime.confidence if (trigger_long or trigger_short) else 0.0,
            entry_price=close,
            sl_price=sl_price,
            tp_price=tp_price,
            rr_ratio=rr_ratio,
            reason=f"London Breakout (AsianRange={asian_range_pips:.1f}p, Hour={current_hour}h UTC)",
            extra_data={
                "asian_high": round(asian_high, 5),
                "asian_low": round(asian_low, 5),
                "asian_range_pips": round(asian_range_pips, 1),
                "is_london_window": is_london_window
            }
        )
