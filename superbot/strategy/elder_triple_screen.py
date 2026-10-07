from __future__ import annotations
"""
Stratégie 1 : Alexander Elder — Triple Screen & Impulse System
===============================================================
Référence : Dr. Alexander Elder — *Vivre du Trading* & *Trading for a Living*

Architecture des 3 Écrans :
1. Écran 1 (Marée / Tendance de fond HTF) : Direction de la moyenne mobile HTF (EMA 50/200)
   ET pente de l'histogramme MACD.
2. Écran 2 (Vague / Contre-tendance) : Force Index (2 périodes) ou Stochastique.
   - Si marée haussière : on attend un repli (Force Index 2 < 0 ou Stochastique < 30).
   - Si marée baissière : on attend un rebond (Force Index 2 > 0 ou Stochastique > 70).
3. Écran 3 (Déclenchement / Trigger) : Cassure du plus haut des 2 dernières bougies (Buy Stop)
   ou du plus bas des 2 dernières bougies (Sell Stop).

Gestion des Stops :
- SL : Chandelier Exit ou plus bas/haut des 5 dernières bougies.
- TP : Ratio R:R asymétrique (2.5R à 3.5R).
"""

from typing import Dict, Any, Optional, TYPE_CHECKING
import pandas as pd

from superbot.strategy.base_strategy import BaseStrategy, SignalResult
if TYPE_CHECKING:
    from superbot.brain.regime_detector import RegimeResult


class ElderTripleScreenStrategy(BaseStrategy):
    """Implémentation du système Triple Écran d'Alexander Elder."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(name="ELDER_TRIPLE_SCREEN", config=config)
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
        if df is None or len(df) < 30:
            return SignalResult(strategy_name=self.name, market_regime=regime.regime)

        last = df.iloc[-1]
        prev = df.iloc[-2]
        prev2 = df.iloc[-3]

        close = current_price if current_price > 0 else float(last['close'])
        atr = float(last.get('atr', 0.0))
        if atr <= 0:
            atr = abs(float(last['high']) - float(last['low']))
        atr = max(atr, 1e-5)
        self.sl_atr_mult = max(self.sl_atr_mult, 0.1)

        # ── Écran 1 : Tendance de fond ─────────────────────────────────────────
        # EMA rapide vs lente et pente de l'EMA
        ema_fast = float(last.get('ema_fast', 0.0))
        ema_slow = float(last.get('ema_slow', 0.0))
        ema_htf = float(last.get('ema_htf', 0.0))
        prev_ema_htf = float(prev.get('ema_htf', 0.0))

        macd_hist = float(last.get('macd_histogram', 0.0))
        prev_macd_hist = float(prev.get('macd_histogram', 0.0))

        if ema_htf <= 0 or prev_ema_htf <= 0:
            tide_bullish = (ema_fast > ema_slow) and (macd_hist > prev_macd_hist)
            tide_bearish = (ema_fast < ema_slow) and (macd_hist < prev_macd_hist)
        else:
            tide_bullish = (ema_fast > ema_slow) and (macd_hist > prev_macd_hist or ema_htf >= prev_ema_htf)
            tide_bearish = (ema_fast < ema_slow) and (macd_hist < prev_macd_hist or ema_htf <= prev_ema_htf)

        # ── Écran 2 : Vague / Pullback (Force Index & Stochastique) ─────────────
        fi_fast = float(last.get('force_index_fast', 0.0))
        stoch_k = float(last.get('stoch_k', 50.0))
        elder_impulse = int(last.get('elder_impulse', 0))
        rsi = float(last.get('rsi', 50.0))

        # En tendance haussière : repli ou impulsion haussière
        wave_bullish_pullback = (fi_fast <= 0 or stoch_k < 40) and (rsi < 65)
        # En tendance baissière : rallye ou impulsion baissière
        wave_bearish_pullback = (fi_fast >= 0 or stoch_k > 60) and (rsi > 35)

        # ── Écran 3 : Déclencheur / Trigger ────────────────────────────────────
        high_2 = max(float(prev['high']), float(prev2['high']))
        low_2 = min(float(prev['low']), float(prev2['low']))

        trigger_long = tide_bullish and wave_bullish_pullback and (close >= high_2 or elder_impulse == 1 or close >= float(prev['high']))
        trigger_short = tide_bearish and wave_bearish_pullback and (close <= low_2 or elder_impulse == -1 or close <= float(prev['low']))

        # Calcul du score (0-10)
        score = 0.0
        if trigger_long:
            score += 4.0
            if ema_fast > ema_slow > ema_htf:
                score += 2.0
            if elder_impulse == 1:
                score += 2.0
            if regime.regime == 'trending_bull':
                score += 2.0
        elif trigger_short:
            score += 4.0
            if ema_fast < ema_slow < ema_htf:
                score += 2.0
            if elder_impulse == -1:
                score += 2.0
            if regime.regime == 'trending_bear':
                score += 2.0

        # Calcul des niveaux Stop Loss et Take Profit
        sl_price = 0.0
        tp_price = 0.0
        rr_ratio = 0.0

        if trigger_long:
            # SL sous le plus bas récent ou Chandelier Exit
            ch_long = float(last.get('chandelier_long', 0.0))
            if ch_long > 0 and ch_long < close:
                sl_price = ch_long
            else:
                sl_price = close - (self.sl_atr_mult * atr)
            
            stop_dist = max(close - sl_price, atr * 0.5)
            tp_price = close + (stop_dist * self.tp_atr_mult / self.sl_atr_mult)
            rr_ratio = (tp_price - close) / stop_dist if stop_dist > 0 else 0.0

        elif trigger_short:
            ch_short = float(last.get('chandelier_short', 0.0))
            if ch_short > 0 and ch_short > close:
                sl_price = ch_short
            else:
                sl_price = close + (self.sl_atr_mult * atr)
            
            stop_dist = max(sl_price - close, atr * 0.5)
            tp_price = close - (stop_dist * self.tp_atr_mult / self.sl_atr_mult)
            rr_ratio = (close - tp_price) / stop_dist if stop_dist > 0 else 0.0
            
        else:
            if regime.regime == 'trending_bull':
                ch_long = float(last.get('chandelier_long', 0.0))
                if ch_long > 0 and ch_long < close:
                    sl_price = ch_long
                else:
                    sl_price = close - (self.sl_atr_mult * atr)
                
                stop_dist = max(close - sl_price, atr * 0.5)
                tp_price = close + (stop_dist * self.tp_atr_mult / self.sl_atr_mult)
                rr_ratio = (tp_price - close) / stop_dist if stop_dist > 0 else 0.0
            elif regime.regime == 'trending_bear':
                ch_short = float(last.get('chandelier_short', 0.0))
                if ch_short > 0 and ch_short > close:
                    sl_price = ch_short
                else:
                    sl_price = close + (self.sl_atr_mult * atr)
                
                stop_dist = max(sl_price - close, atr * 0.5)
                tp_price = close - (stop_dist * self.tp_atr_mult / self.sl_atr_mult)
                rr_ratio = (close - tp_price) / stop_dist if stop_dist > 0 else 0.0

        confidence = regime.confidence if (trigger_long or trigger_short) else 0.0

        return SignalResult(
            should_long=trigger_long and score >= 6.0,
            should_short=trigger_short and score >= 6.0,
            trigger_long=trigger_long,
            trigger_short=trigger_short,
            total_score=score,
            strategy_name=self.name,
            market_regime=regime.regime,
            confidence=confidence,
            entry_price=close,
            sl_price=sl_price,
            tp_price=tp_price,
            rr_ratio=rr_ratio,
            reason=f"Elder Triple Screen (Tide={tide_bullish or tide_bearish}, Impulse={elder_impulse})",
            extra_data={
                "force_index_fast": fi_fast,
                "stoch_k": stoch_k,
                "elder_impulse": elder_impulse
            }
        )

