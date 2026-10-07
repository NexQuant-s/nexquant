"""
Tests unitaires pour MarketRegimeDetector (Matières Premières & Forex).
"""
import pytest
import pandas as pd
import numpy as np
from superbot.brain.regime_detector import MarketRegimeDetector
from superbot.indicators.technical_indicators import TechnicalIndicators
from superbot.strategy.knowledge_base import calculate_hurst_exponent, calculate_half_life


@pytest.fixture
def base_config():
    return {
        "EMA_FAST": 9,
        "EMA_SLOW": 21,
        "EMA_TREND": 200,
        "HTF_EMA": 50,
        "D1_EMA": 50,
        "W1_EMA": 20,
        "RSI_LEN": 14,
        "MACD_FAST": 12,
        "MACD_SLOW": 26,
        "MACD_SIGNAL": 9,
        "ADX_LEN": 14,
        "BB_LEN": 20,
        "BB_STD": 2.0,
        "ATR_LEN": 14,
    }


class TestRegimeDetector:

    def test_hurst_exponent_calculation(self):
        np.random.seed(42)
        n = 300
        # Série en tendance persistante (momentum autocorrelé)
        inc = [0.1]
        for _ in range(n):
            inc.append(0.8 * inc[-1] + np.random.normal(0, 0.05))
        trending = pd.Series(100.0 + np.cumsum(inc))
        h_trend = calculate_hurst_exponent(trending)
        assert h_trend > 0.55

        # Série en retour à la moyenne fort (AR1 theta = 0.3)
        y = [100.0]
        for _ in range(n):
            y.append(100.0 + 0.3 * (y[-1] - 100.0) + np.random.normal(0, 0.5))
        mean_rev = pd.Series(y)
        h_mean_rev = calculate_hurst_exponent(mean_rev)
        assert h_mean_rev < 0.45

    def test_half_life_calculation(self):
        # Série AR(1) mean-reverting : y_t = 0.8 * y_{t-1} + e
        np.random.seed(42)
        y = [100.0]
        for _ in range(200):
            y.append(100.0 + 0.8 * (y[-1] - 100.0) + np.random.normal(0, 0.5))
        s = pd.Series(y)
        hl = calculate_half_life(s)
        assert 1.0 <= hl <= 15.0

    def test_detect_trending_bull(self, base_config):
        calc = TechnicalIndicators(base_config)
        np.random.seed(42)
        dates = pd.date_range("2026-01-01", periods=100, freq="1h")
        prices = 100.0 + np.cumsum(np.random.normal(0.5, 0.05, 100))
        df = pd.DataFrame({
            "open": prices - 0.2,
            "high": prices + 0.4,
            "low": prices - 0.3,
            "close": prices,
            "volume": [1000 + i * 5 for i in range(100)],
        }, index=dates)

        df_ind = calc.calculate_all_indicators(df)
        detector = MarketRegimeDetector()
        res = detector.detect(df_ind, symbol="EURUSD", asset_class="forex_major")

        assert res.regime == "trending_bull"
        assert res.confidence > 0.4

    def test_detect_trending_bear(self, base_config):
        calc = TechnicalIndicators(base_config)
        np.random.seed(42)
        dates = pd.date_range("2026-01-01", periods=100, freq="1h")
        prices = 200.0 - np.cumsum(np.random.normal(0.5, 0.05, 100))
        df = pd.DataFrame({
            "open": prices + 0.2,
            "high": prices + 0.3,
            "low": prices - 0.4,
            "close": prices,
            "volume": [1000 + i * 5 for i in range(100)],
        }, index=dates)

        df_ind = calc.calculate_all_indicators(df)
        detector = MarketRegimeDetector()
        res = detector.detect(df_ind, symbol="XAUUSD", asset_class="commodity_gold")

        assert res.regime == "trending_bear"
        assert res.confidence > 0.4

    def test_detect_ranging(self, base_config):
        calc = TechnicalIndicators(base_config)
        np.random.seed(42)
        dates = pd.date_range("2026-01-01", periods=100, freq="1h")
        # Oscillation autour de 100
        y = [100.0]
        for _ in range(99):
            y.append(100.0 + 0.3 * (y[-1] - 100.0) + np.random.normal(0, 0.1))
        prices = np.array(y)
        df = pd.DataFrame({
            "open": prices,
            "high": prices + 0.05,
            "low": prices - 0.05,
            "close": prices,
            "volume": [500] * 100,
        }, index=dates)

        df_ind = calc.calculate_all_indicators(df)
        detector = MarketRegimeDetector()
        res = detector.detect(df_ind, symbol="EURGBP", asset_class="forex_cross")

        assert res.regime in ["ranging", "pre_breakout", "choppy_noise"]

