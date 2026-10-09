from __future__ import annotations
"""
Stratégie 3 : John J. Murphy — Suivi de Tendance Classique & Breakout de Donchian
================================================================================
Référence : John J. Murphy — *Technical Analysis of the Financial Markets*

Principes Fondamentaux :
1. Alignement de tendance multitemporel (EMA 21, EMA 55, EMA 200).
2. Cassure des canaux de Donchian à 20 périodes (Canal de Richard Donchian / Turtles).
3. Confirmation de momentum : ADX > 22, RSI au-delà de 50, MACD au-dessus de sa ligne de signal.
4. Idéal pour les tendances puissantes sur Matières Premières (Or, Pétrole) et Devises de tendance (USDJPY, GBPUSD).
"""

from typing import Dict, Any, Optional, TYPE_CHECKING
import pandas as pd

from superbot.strategy.base_strategy import BaseStrategy, SignalResult
if TYPE_CHECKING:
    from superbot.brain.regime_detector import RegimeResult


class MurphyTrendStrategy(BaseStrategy):
    """Stratégie de suivi de tendance et breakout de Donchian (John J. Murphy)."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(name="MURPHY_TREND", config=config)
        self.sl_atr_mult = float(self.config.get("SL_ATR_MULT", 1.5))
        self.tp_atr_mult = float(self.config.get("TP_ATR_MULT", 3.5))
        # Garde anti-épuisement : pas d'achat en surachat (RSI ≥ RSI_OB) ni de vente en survente.
        # Constat 22/09→06/10 : signaux « continuation » notés 10/10 avec RSI 74-80 en haut de mouvement.
        self.exhaustion_guard = bool(self.config.get("MURPHY_EXHAUSTION_GUARD", True))
        self.rsi_ob = float(self.config.get("RSI_OB", 70))
        self.rsi_os = float(self.config.get("RSI_OS", 30))
        # ADX minimum pour déclencher. Étude H1 broker 3 ans : 25 → PF 1,70/1,94 (train/test), gain total
        # conservé et moins de mois perdants (contre 1,58/1,86 à 20).
        self.min_adx = float(self.config.get("MURPHY_MIN_ADX", 20))
        # Distance minimale RÉELLE du stop (× ATR). 0 = comportement historique : le stop pouvait se retrouver
        # presque sur le prix d'entrée (canal de Donchian étroit) alors que l'objectif était calculé sur 0,5 ATR
        # → gains « +20 R » irréalisables (spread, stop minimum du broker) qui gonflaient le PF du backtest.
        self.min_sl_atr = float(self.config.get("MURPHY_MIN_SL_ATR", 0.0))

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
        close = current_price if current_price > 0 else float(last['close'])
        atr = float(last.get('atr', 0.0))
        if atr <= 0:
            atr = abs(float(last['high']) - float(last['low']))

        ema_21 = float(last.get('ema_21', last.get('ema_fast', 0.0)))
        ema_55 = float(last.get('ema_55', last.get('ema_slow', 0.0)))
        ema_200 = float(last.get('ema_trend', 0.0))

        donch_u = float(prev.get('donchian_upper_20', 0.0))
        donch_l = float(prev.get('donchian_lower_20', 0.0))
        donch_m = float(prev.get('donchian_middle_20', 0.0))
        
        if donch_u <= 0:
            donch_u = float(df['high'].rolling(20).max().iloc[-2])
        if donch_l <= 0:
            donch_l = float(df['low'].rolling(20).min().iloc[-2])
        if donch_m <= 0:
            donch_m = (donch_u + donch_l) / 2.0

        adx = float(last.get('adx', 20.0))
        rsi = float(last.get('rsi', 50.0))
        macd = float(last.get('macd', 0.0))
        macd_sig = float(last.get('macd_signal', 0.0))

        # Alignement de tendance (Murphy)
        bullish_alignment = (ema_21 > ema_55) and (ema_200 == 0 or ema_55 > ema_200 or close > ema_200)
        bearish_alignment = (ema_21 < ema_55) and (ema_200 == 0 or ema_55 < ema_200 or close < ema_200)

        # Breakout Donchian ou Pullback EMA 21
        trigger_long = False
        trigger_short = False

        if bullish_alignment and adx >= self.min_adx:
            if donch_u > 0 and close >= donch_u:
                trigger_long = True  # Breakout de plus haut de 20 périodes
            elif float(prev['low']) <= ema_21 and close > ema_21 and rsi >= 50:
                trigger_long = True  # Rebond / Pullback sur EMA 21
            elif close > ema_21 > ema_55 and rsi >= 50:
                trigger_long = True  # Continuation de tendance forte

        if bearish_alignment and adx >= self.min_adx:
            if donch_l > 0 and close <= donch_l:
                trigger_short = True  # Breakout de plus bas de 20 périodes
            elif float(prev['high']) >= ema_21 and close < ema_21 and rsi <= 50:
                trigger_short = True  # Rejet / Pullback sur EMA 21
            elif close < ema_21 < ema_55 and rsi <= 50:
                trigger_short = True  # Continuation de tendance forte

        exhausted = False
        if self.exhaustion_guard:
            if trigger_long and rsi >= self.rsi_ob:
                trigger_long, exhausted = False, True
            if trigger_short and rsi <= self.rsi_os:
                trigger_short, exhausted = False, True

        score = 0.0
        if trigger_long:
            score += 4.0
            if regime.regime in ['trending_bull', 'breakout']:
                score += 2.5
            if ema_200 > 0 and ema_55 > ema_200:
                score += 1.5
            if macd > macd_sig:
                score += 1.0
            if adx >= 25:
                score += 1.0
        elif trigger_short:
            score += 4.0
            if regime.regime in ['trending_bear', 'breakout']:
                score += 2.5
            if ema_200 > 0 and ema_55 < ema_200:
                score += 1.5
            if macd < macd_sig:
                score += 1.0
            if adx >= 25:
                score += 1.0

        sl_price = 0.0
        tp_price = 0.0
        rr_ratio = 0.0
        
        atr = max(atr, 1e-5)

        if trigger_long:
            sl_price = max(donch_m, close - (self.sl_atr_mult * atr)) if donch_m > 0 and donch_m < close else (close - self.sl_atr_mult * atr)
            if self.min_sl_atr > 0:
                sl_price = min(sl_price, close - self.min_sl_atr * atr)
            stop_dist = max(close - sl_price, atr * 0.5, 1e-5)
            tp_price = close + (stop_dist * (self.tp_atr_mult / self.sl_atr_mult))
            rr_ratio = (tp_price - close) / stop_dist

        elif trigger_short:
            sl_price = min(donch_m, close + (self.sl_atr_mult * atr)) if donch_m > 0 and donch_m > close else (close + self.sl_atr_mult * atr)
            if self.min_sl_atr > 0:
                sl_price = max(sl_price, close + self.min_sl_atr * atr)
            stop_dist = max(sl_price - close, atr * 0.5, 1e-5)
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
            reason=(f"Murphy Trend Following (Alignment={bullish_alignment or bearish_alignment}, ADX={adx:.1f})"
                    + (f" — entrée refusée : RSI {rsi:.1f} en zone d'épuisement" if exhausted else "")),
            extra_data={
                "donchian_upper_20": donch_u,
                "donchian_lower_20": donch_l,
                "ema_21": ema_21,
                "ema_55": ema_55
            }
        )
