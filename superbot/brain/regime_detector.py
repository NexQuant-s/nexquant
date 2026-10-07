"""
NexQuant SuperBot — Détecteur de Régime de Marché Multi-Facteurs (Forex & Commodities)
========================================================================================
Détection automatique et temps réel du régime de marché :
- TRENDING_BULL   : Tendance haussière forte (ADX > 22, EMA↑, Elder Vert, Hurst > 0.55)
- TRENDING_BEAR   : Tendance baissière forte (ADX > 22, EMA↓, Elder Rouge, Hurst > 0.55)
- RANGING         : Canal horizontal / oscillation (ADX < 20, BB étroites, Hurst < 0.45)
- BREAKOUT        : Cassure explosive (BB expansion, sortie Donchian, Volume spike)
- PRE_BREAKOUT    : Compression / Squeeze (BB Squeeze Keltner, contraction de volatilité)
- HIGH_VOLATILITY : Forte volatilité / Choc de liquidité (ATR spike > 1.8x, BB très larges)
- CHOPPY_NOISE    : Bruit sans direction ni range propre (Hurst ~ 0.50, faible amplitude -> NO TRADE)
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict
from datetime import datetime, timezone
import pandas as pd

from superbot.strategy.knowledge_base import calculate_hurst_exponent, calculate_half_life

log = logging.getLogger("nexquant.regime_detector")


@dataclass
class RegimeResult:
    """Résultat de la détection de régime."""
    regime: str                      # 'trending_bull' | 'trending_bear' | 'ranging' | 'high_volatility' | 'breakout' | 'pre_breakout' | 'choppy_noise'
    confidence: float                # 0.0 → 1.0
    adx_value: float = 0.0
    atr_value: float = 0.0
    hurst_exponent: float = 0.5
    half_life: float = 20.0
    bb_width_pct: float = 0.0
    rsi_value: float = 50.0
    volume_factor: float = 1.0
    factors: Dict[str, Any] = field(default_factory=dict)
    detected_at: str = ""

    def to_dict(self) -> Dict:
        return {
            'regime': self.regime,
            'confidence': round(self.confidence, 3),
            'adx': round(self.adx_value, 2),
            'atr': round(self.atr_value, 6),
            'hurst': round(self.hurst_exponent, 3),
            'half_life': round(self.half_life, 1),
            'bb_width_pct': round(self.bb_width_pct, 2),
            'rsi': round(self.rsi_value, 1),
            'volume_factor': round(self.volume_factor, 2),
            'detected_at': self.detected_at,
        }


# Seuils optimisés par classe d'actifs Forex & Matières Premières
REGIME_THRESHOLDS = {
    'forex': {
        'adx_trending': 22,
        'adx_ranging': 18,
        'bb_wide': 2.2,
        'bb_squeeze': 0.8,
        'rsi_overbought': 70,
        'rsi_oversold': 30,
        'atr_high_factor': 1.8,
        'volume_spike': 1.5,
    },
    'forex_jpy': {
        'adx_trending': 22,
        'adx_ranging': 16,
        'bb_wide': 2.8,
        'bb_squeeze': 0.9,
        'rsi_overbought': 72,
        'rsi_oversold': 28,
        'atr_high_factor': 2.0,
        'volume_spike': 1.5,
    },
    'forex_major': {
        'adx_trending': 22,
        'adx_ranging': 18,
        'bb_wide': 2.2,
        'bb_squeeze': 0.8,
        'rsi_overbought': 70,
        'rsi_oversold': 30,
        'atr_high_factor': 1.8,
        'volume_spike': 1.5,
    },
    'forex_cross': {
        'adx_trending': 24,
        'adx_ranging': 18,
        'bb_wide': 2.5,
        'bb_squeeze': 0.9,
        'rsi_overbought': 70,
        'rsi_oversold': 30,
        'atr_high_factor': 1.8,
        'volume_spike': 1.5,
    },
    'commodity': {
        'adx_trending': 24,
        'adx_ranging': 18,
        'bb_wide': 2.5,
        'bb_squeeze': 0.8,
        'rsi_overbought': 70,
        'rsi_oversold': 30,
        'atr_high_factor': 1.8,
        'volume_spike': 1.5,
    },
    'commodity_gold': {
        'adx_trending': 24,
        'adx_ranging': 18,
        'bb_wide': 2.5,
        'bb_squeeze': 0.8,
        'rsi_overbought': 70,
        'rsi_oversold': 30,
        'atr_high_factor': 1.8,
        'volume_spike': 1.5,
    },
    'commodity_oil': {
        'adx_trending': 25,
        'adx_ranging': 18,
        'bb_wide': 3.0,
        'bb_squeeze': 1.0,
        'rsi_overbought': 72,
        'rsi_oversold': 28,
        'atr_high_factor': 2.0,
        'volume_spike': 1.5,
    },
    'commodity_silver': {
        'adx_trending': 25,
        'adx_ranging': 18,
        'bb_wide': 3.2,
        'bb_squeeze': 1.0,
        'rsi_overbought': 72,
        'rsi_oversold': 28,
        'atr_high_factor': 2.0,
        'volume_spike': 1.5,
    },
    'commodity_gas': {
        'adx_trending': 26,
        'adx_ranging': 18,
        'bb_wide': 3.5,
        'bb_squeeze': 1.2,
        'rsi_overbought': 75,
        'rsi_oversold': 25,
        'atr_high_factor': 2.2,
        'volume_spike': 1.5,
    },
}

DEFAULT_THRESHOLDS = REGIME_THRESHOLDS['forex']


class MarketRegimeDetector:
    """
    Détecteur de régime de marché multi-facteurs thread-safe.
    """

    def __init__(self, db=None):
        self._db = db
        self._cache: Dict[str, RegimeResult] = {}
        log.info("MarketRegimeDetector MT5 (Forex & Commodities) initialisé")

    def detect(
        self,
        df: pd.DataFrame,
        symbol: str = "",
        asset_class: str = "forex",
        store_in_db: bool = True
    ) -> RegimeResult:
        """
        Détecte le régime de marché pour le symbole donné.
        """
        try:
            result = self._detect_regime(df, symbol, asset_class)
            result.detected_at = datetime.now(timezone.utc).isoformat()
            self._cache[symbol] = result

            if store_in_db and self._db and symbol:
                self._store_regime(symbol, result)

            return result
        except Exception as e:
            log.debug(f"Regime detection error ({symbol}): {e}")
            return RegimeResult(
                regime='ranging',
                confidence=0.3,
                detected_at=datetime.now(timezone.utc).isoformat()
            )

    def _detect_regime(self, df: pd.DataFrame, symbol: str, asset_class: str) -> RegimeResult:
        if df is None or len(df) < 20:
            return RegimeResult(regime='ranging', confidence=0.2)

        last = df.iloc[-1]
        thresholds = REGIME_THRESHOLDS.get(asset_class, DEFAULT_THRESHOLDS)

        # ─── 1. Extraction des indicateurs clés ────────────────────────────────
        adx = self._safe_float(last, 'adx', 20.0)
        atr = self._safe_float(last, 'atr', 0.0)
        rsi = self._safe_float(last, 'rsi', 50.0)
        close = self._safe_float(last, 'close', 1.0)
        bb_upper = self._safe_float(last, 'bb_upper', 0.0)
        bb_lower = self._safe_float(last, 'bb_lower', 0.0)
        ema_fast = self._safe_float(last, 'ema_fast', 0.0)
        ema_slow = self._safe_float(last, 'ema_slow', 0.0)
        ema_trend = self._safe_float(last, 'ema_trend', 0.0)
        macd_hist = self._safe_float(last, 'macd_histogram', 0.0)
        st_dir = self._safe_float(last, 'supertrend_trend', 0.0)
        elder_impulse = self._safe_float(last, 'elder_impulse', 0.0)
        bb_squeeze = bool(last.get('bb_squeeze', False)) if hasattr(last, 'get') else False
        volume = self._safe_float(last, 'volume', 0.0)

        # Volume factor
        vol_avg = float(df['volume'].iloc[-20:].mean()) if 'volume' in df.columns else 0.0
        volume_factor = volume / vol_avg if (vol_avg > 0 and volume > 0) else 1.0

        # Bollinger width %
        bb_width_pct = ((bb_upper - bb_lower) / close * 100) if (close > 0 and bb_upper > 0) else 0.0

        # ATR Factor
        atr_avg = float(df['atr'].iloc[-20:].mean()) if 'atr' in df.columns else atr
        atr_factor = atr / max(atr_avg, 1e-10) if atr_avg > 0 else 1.0

        # Calcul quantitatif : Exposant de Hurst & Demi-vie OU (Ernest Chan)
        hurst = calculate_hurst_exponent(df['close'], max_lag=20)
        half_life = calculate_half_life(df['close'])

        # ─── 2. Système de vote multi-facteurs ─────────────────────────────────
        votes: Dict[str, float] = {
            'trending_bull': 0.0,
            'trending_bear': 0.0,
            'ranging': 0.0,
            'high_volatility': 0.0,
            'breakout': 0.0,
            'pre_breakout': 0.0,
            'choppy_noise': 0.0,
        }
        factors = {
            'adx': adx,
            'hurst': hurst,
            'half_life': half_life,
            'bb_width_pct': bb_width_pct,
            'atr_factor': atr_factor,
            'elder_impulse': elder_impulse,
            'bb_squeeze': bb_squeeze,
        }

        # A. ADX & Directional Trend
        adx_trend = thresholds['adx_trending']
        adx_range = thresholds['adx_ranging']

        if adx >= adx_trend:
            pts = 30 if adx >= adx_trend * 1.2 else 20
            if ema_fast > 0 and ema_slow > 0:
                if ema_fast > ema_slow:
                    votes['trending_bull'] += pts
                else:
                    votes['trending_bear'] += pts
        elif adx < adx_range:
            votes['ranging'] += 35
            if 0.40 <= hurst <= 0.60:
                votes['choppy_noise'] += 20
        else:
            votes['ranging'] += 15

        # B. Exposant de Hurst (Chan)
        if hurst > 0.55:
            # Persistance de tendance
            if ema_fast > 0 and ema_slow > 0:
                if ema_fast > ema_slow:
                    votes['trending_bull'] += 25
                else:
                    votes['trending_bear'] += 25
        elif hurst < 0.45:
            # Retour à la moyenne
            votes['ranging'] += 35
        else:
            # Random walk
            if adx < 18:
                votes['choppy_noise'] += 25

        # C. Alignement des EMA (Murphy)
        if adx >= adx_range and ema_fast > 0 and ema_slow > 0:
            if ema_fast > ema_slow:
                votes['trending_bull'] += 15
                if ema_trend > 0 and ema_slow > ema_trend:
                    votes['trending_bull'] += 15  # Triple alignement parfait (Murphy)
            else:
                votes['trending_bear'] += 15
                if ema_trend > 0 and ema_slow < ema_trend:
                    votes['trending_bear'] += 15

        # D. Système d'Impulsion Elder (Elder)
        if elder_impulse == 1:
            votes['trending_bull'] += 15
        elif elder_impulse == -1:
            votes['trending_bear'] += 15
        else:
            votes['ranging'] += 5

        # E. Bollinger Bands & Squeeze (Carter & Murphy)
        if bb_squeeze:
            votes['pre_breakout'] += 35
            votes['breakout'] += 10
        elif bb_width_pct > thresholds['bb_wide']:
            votes['high_volatility'] += 30
        elif bb_width_pct < thresholds['bb_squeeze']:
            votes['pre_breakout'] += 25

        if bb_upper > 0 and bb_lower > 0:
            if close > bb_upper:
                votes['breakout'] += 25
                votes['trending_bull'] += 10
            elif close < bb_lower:
                votes['breakout'] += 25
                votes['trending_bear'] += 10

        # F. ATR Spike (Volatilité / Macro Event)
        if atr_factor > thresholds['atr_high_factor']:
            votes['high_volatility'] += 30
        elif atr_factor < 0.7:
            votes['ranging'] += 10
            votes['pre_breakout'] += 10

        # G. Supertrend & MACD confirmation
        if st_dir > 0:
            votes['trending_bull'] += 10
        elif st_dir < 0:
            votes['trending_bear'] += 10

        if macd_hist > 0:
            votes['trending_bull'] += 5
        elif macd_hist < 0:
            votes['trending_bear'] += 5

        # H. RSI Confirmation
        rsi_ob = thresholds.get('rsi_overbought', 70)
        rsi_os = thresholds.get('rsi_oversold', 30)
        if rsi > rsi_ob:
            votes['trending_bull'] += 10
            votes['high_volatility'] += 5
        elif rsi < rsi_os:
            votes['trending_bear'] += 10
            votes['high_volatility'] += 5

        # I. Volume Spike Confirmation
        vol_spike = thresholds.get('volume_spike', 1.5)
        if volume_factor > vol_spike:
            votes['breakout'] += 15
            votes['high_volatility'] += 10
        elif volume_factor < 0.5:
            votes['ranging'] += 10
            votes['choppy_noise'] += 5

        # ─── 3. Sélection du régime gagnant & Confiance ────────────────────────
        best_regime = max(votes, key=votes.get)
        total_votes = sum(votes.values())
        best_points = votes[best_regime]

        confidence = (best_points / total_votes) if total_votes > 0 else 0.5
        confidence = float(max(0.2, min(confidence, 0.95)))

        return RegimeResult(
            regime=best_regime,
            confidence=confidence,
            adx_value=adx,
            atr_value=atr,
            hurst_exponent=hurst,
            half_life=half_life,
            bb_width_pct=bb_width_pct,
            rsi_value=rsi,
            volume_factor=volume_factor,
            factors=factors
        )

    def _safe_float(self, row, col: str, default: float = 0.0) -> float:
        try:
            val = row.get(col, default) if hasattr(row, 'get') else getattr(row, col, default)
            if val is None or (isinstance(val, float) and math.isnan(val)):
                return default
            return float(val)
        except Exception:
            return default

    def _store_regime(self, symbol: str, result: RegimeResult):
        try:
            if hasattr(self._db, 'store_market_regime'):
                self._db.store_market_regime(
                    symbol=symbol,
                    regime=result.regime,
                    confidence=result.confidence,
                    adx=result.adx_value,
                    atr=result.atr_value,
                    details=result.factors
                )
        except Exception as e:
            log.debug(f"Erreur stockage régime DB ({symbol}): {e}")

    def get_risk_multiplier(self, regime: str) -> float:
        multipliers = {
            'trending_bull': 1.2, 'trending_bear': 1.2,
            'ranging': 0.8, 'breakout': 1.0,
            'pre_breakout': 0.9, 'high_volatility': 0.6,
            'choppy_noise': 0.4,
        }
        return multipliers.get(regime, 0.7)

    def get_score_min_adjustment(self, regime: str) -> int:
        adjustments = {
            'trending_bull': -1, 'trending_bear': -1,
            'ranging': 0, 'breakout': -2,
            'pre_breakout': -1, 'high_volatility': 1,
            'choppy_noise': 2,
        }
        return adjustments.get(regime, 0)

