from __future__ import annotations
"""
Stratégie 6 : Intermarket & Time-Series Momentum (TSMOM)
=========================================================
Références :
- John J. Murphy — *Intermarket Analysis: Profiting from Global Market Relationships*
- Moskowitz, Ooi, Pedersen — *Time Series Momentum (Journal of Financial Economics)*

Mécanisme :
1. Calcul du momentum multi-horizons (Court, Moyen, Long terme : 12, 36, 72 périodes).
2. Filtre de cohérence inter-temporelle : tous les horizons de momentum doivent pointer
   dans la même direction (Consensus de tendance macro).
3. Confirmation par rapport au VWAP institutionnel et à l'EMA 200.
4. Conçu spécifiquement pour les grands flux macroéconomiques sur l'Or, le Pétrole et le Forex.
"""

from typing import Dict, Any, Optional, TYPE_CHECKING
import pandas as pd

from superbot.strategy.base_strategy import BaseStrategy, SignalResult
if TYPE_CHECKING:
    from superbot.brain.regime_detector import RegimeResult


class IntermarketMomentumStrategy(BaseStrategy):
    """Stratégie Time-Series Momentum & Intermarket Macro (Murphy / Moskowitz)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(name="INTERMARKET_MOMENTUM", config=config)
        self.sl_atr_mult = float(self.config.get("SL_ATR_MULT", 1.5))
        self.tp_atr_mult = float(self.config.get("TP_ATR_MULT", 3.5))

    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str,
        regime: RegimeResult,
        asset_class: str,
        current_price: float,
        pip_size: float = 0.0001
    ) -> SignalResult:
        if df is None or len(df) < 73:
            return SignalResult(strategy_name=self.name, market_regime=regime.regime)

        last = df.iloc[-1]
        close = current_price if current_price > 0 else float(last['close'])
        atr = float(last.get('atr', 0.0))
        if atr <= 0:
            atr = abs(float(last['high']) - float(last['low']))

        # Momentum sur 3 horizons : 12, 36, 72 périodes
        p_close = df['close']
        mom_12 = float((p_close.iloc[-1] / (p_close.iloc[-12] if p_close.iloc[-12] != 0 else 1e-10) - 1.0) * 100) if len(p_close) >= 12 else 0.0
        mom_36 = float((p_close.iloc[-1] / (p_close.iloc[-36] if p_close.iloc[-36] != 0 else 1e-10) - 1.0) * 100) if len(p_close) >= 36 else 0.0
        mom_72 = float((p_close.iloc[-1] / (p_close.iloc[-72] if p_close.iloc[-72] != 0 else 1e-10) - 1.0) * 100) if len(p_close) >= 72 else 0.0

        vwap = float(last.get('vwap', 0.0))
        ema_200 = float(last.get('ema_trend', 0.0))
        adx = float(last.get('adx', 20.0))

        # Consensus multi-horizon
        consensus_bullish = (mom_12 > 0) and (mom_36 > 0) and (mom_72 > 0)
        consensus_bearish = (mom_12 < 0) and (mom_36 < 0) and (mom_72 < 0)

        trigger_long = False
        trigger_short = False

        if consensus_bullish and adx >= 20:
            if vwap == 0 or close >= vwap:
                trigger_long = True

        if consensus_bearish and adx >= 20:
            if vwap == 0 or close <= vwap:
                trigger_short = True

        score = 0.0
        if trigger_long:
            score += 4.5
            if ema_200 > 0 and close > ema_200:
                score += 2.0
            if regime.regime in ['trending_bull', 'breakout']:
                score += 2.0
            if mom_12 > 1.0:
                score += 1.5
        elif trigger_short:
            score += 4.5
            if ema_200 > 0 and close < ema_200:
                score += 2.0
            if regime.regime in ['trending_bear', 'breakout']:
                score += 2.0
            if mom_12 < -1.0:
                score += 1.5

        sl_price = 0.0
        tp_price = 0.0
        rr_ratio = 0.0

        if trigger_long:
            sl_price = close - (self.sl_atr_mult * atr)
            stop_dist = max(close - sl_price, 1e-5)
            tp_price = close + (stop_dist * (self.tp_atr_mult / self.sl_atr_mult))
            rr_ratio = (tp_price - close) / stop_dist

        elif trigger_short:
            sl_price = close + (self.sl_atr_mult * atr)
            stop_dist = max(sl_price - close, 1e-5)
            tp_price = close - (stop_dist * (self.tp_atr_mult / self.sl_atr_mult))
            rr_ratio = (close - tp_price) / stop_dist

        return SignalResult(
            should_long=trigger_long and score >= 6.0,
            should_short=trigger_short and score >= 6.0,
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
            reason=f"Intermarket Momentum (M12={mom_12:.2f}%, M36={mom_36:.2f}%, M72={mom_72:.2f}%)",
            extra_data={
                "mom_12": round(mom_12, 2),
                "mom_36": round(mom_36, 2),
                "mom_72": round(mom_72, 2)
            }
        )
