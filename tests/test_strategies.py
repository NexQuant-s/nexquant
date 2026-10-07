"""
Tests unitaires et d'intégration pour les 6 stratégies de trading et le StrategyEngine.
"""
import pytest
import pandas as pd
import numpy as np

from superbot.strategy.elder_triple_screen import ElderTripleScreenStrategy
from superbot.strategy.chan_mean_reversion import ChanMeanReversionStrategy
from superbot.strategy.murphy_trend import MurphyTrendStrategy
from superbot.strategy.volman_price_action import VolmanPriceActionStrategy
from superbot.strategy.london_breakout import LondonBreakoutStrategy
from superbot.strategy.intermarket_momentum import IntermarketMomentumStrategy
from superbot.brain.strategy_engine import StrategyEngine
from superbot.brain.regime_detector import RegimeResult
from superbot.indicators.technical_indicators import TechnicalIndicators


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
        "SL_ATR_MULT": 1.5,
        "TP_ATR_MULT": 3.5,
    }


class TestStrategies:

    def test_elder_triple_screen_bullish(self, base_config):
        calc = TechnicalIndicators(base_config)
        dates = pd.date_range("2026-01-01", periods=60, freq="1h")
        prices = [100.0 + i * 0.3 for i in range(60)]
        df = pd.DataFrame({
            "open": [p - 0.2 for p in prices],
            "high": [p + 0.4 for p in prices],
            "low": [p - 0.3 for p in prices],
            "close": prices,
            "volume": [1000 + i * 10 for i in range(60)],
        }, index=dates)

        df_ind = calc.calculate_all_indicators(df)
        regime = RegimeResult(regime="trending_bull", confidence=0.85)
        strat = ElderTripleScreenStrategy(base_config)
        res = strat.analyze(df_ind, "EURUSD", regime, "forex_major", current_price=prices[-1])

        assert res.strategy_name == "ELDER_TRIPLE_SCREEN"
        assert res.sl_price < res.entry_price
        assert res.tp_price > res.entry_price
        assert res.rr_ratio > 0

    def test_chan_mean_reversion(self, base_config):
        calc = TechnicalIndicators(base_config)
        dates = pd.date_range("2026-01-01", periods=60, freq="1h")
        # Série plate oscillant autour de 100
        prices = [100.0 + np.sin(i / 3.0) for i in range(59)]
        prices.append(97.5)  # Forte déviation sous la bande inférieure
        df = pd.DataFrame({
            "open": prices,
            "high": [p + 0.2 for p in prices],
            "low": [p - 0.2 for p in prices],
            "close": prices,
            "volume": [1000] * 60,
        }, index=dates)

        df_ind = calc.calculate_all_indicators(df)
        regime = RegimeResult(regime="ranging", confidence=0.75, hurst_exponent=0.35, half_life=8.0)
        strat = ChanMeanReversionStrategy(base_config)
        res = strat.analyze(df_ind, "EURGBP", regime, "forex_cross", current_price=97.5)

        assert res.strategy_name == "CHAN_MEAN_REVERSION"
        assert res.trigger_long is True
        assert res.tp_price > res.entry_price  # TP vise la moyenne

    def test_murphy_trend(self, base_config):
        calc = TechnicalIndicators(base_config)
        dates = pd.date_range("2026-01-01", periods=60, freq="1h")
        prices = [100.0 + i * 0.5 for i in range(60)]
        df = pd.DataFrame({
            "open": [p - 0.2 for p in prices],
            "high": [p + 0.5 for p in prices],
            "low": [p - 0.3 for p in prices],
            "close": prices,
            "volume": [1000 + i * 10 for i in range(60)],
        }, index=dates)

        df_ind = calc.calculate_all_indicators(df)
        regime = RegimeResult(regime="trending_bull", confidence=0.85)
        # Série strictement haussière (RSI ≈ 100) : on teste ici le déclenchement, garde désactivée
        strat = MurphyTrendStrategy({**base_config, "MURPHY_EXHAUSTION_GUARD": False})
        res = strat.analyze(df_ind, "XAUUSD", regime, "commodity_gold", current_price=prices[-1])

        assert res.strategy_name == "MURPHY_TREND"
        assert res.trigger_long is True
        assert res.rr_ratio > 1.5

        # Avec la garde (défaut) : pas d'achat en surachat
        guarded = MurphyTrendStrategy(base_config).analyze(df_ind, "XAUUSD", regime, "commodity_gold",
                                                           current_price=prices[-1])
        assert guarded.trigger_long is False and guarded.should_long is False
        assert "épuisement" in guarded.reason

    def test_volman_price_action(self, base_config):
        calc = TechnicalIndicators(base_config)
        dates = pd.date_range("2026-01-01", periods=60, freq="1h")
        prices = [100.0 + i * 0.2 for i in range(60)]
        df = pd.DataFrame({
            "open": prices,
            "high": [p + 0.1 for p in prices],
            "low": [p - 0.1 for p in prices],
            "close": prices,
            "volume": [1000] * 60,
        }, index=dates)

        df_ind = calc.calculate_all_indicators(df)
        regime = RegimeResult(regime="pre_breakout", confidence=0.7)
        strat = VolmanPriceActionStrategy(base_config)
        res = strat.analyze(df_ind, "EURUSD", regime, "forex_major", current_price=prices[-1])

        assert res.strategy_name == "VOLMAN_PRICE_ACTION"
        assert res.sl_price > 0
        assert res.tp_price > 0

    def test_london_breakout(self, base_config):
        calc = TechnicalIndicators(base_config)
        # Créer des bougies débutant à 00:00 UTC
        dates = pd.date_range("2026-01-01 00:00:00", periods=10, freq="1h", tz="UTC")
        # Session asiatique (00h-07h) compacte entre 1.1000 et 1.1020
        prices = [1.1005, 1.1010, 1.1015, 1.1008, 1.1012, 1.1018, 1.1014, 1.1025, 1.1035, 1.1040]
        df = pd.DataFrame({
            "open": prices,
            "high": [p + 0.0005 for p in prices],
            "low": [p - 0.0005 for p in prices],
            "close": prices,
            "volume": [1000] * 10,
        }, index=dates)

        df_ind = calc.calculate_all_indicators(df)
        regime = RegimeResult(regime="breakout", confidence=0.8)
        strat = LondonBreakoutStrategy(base_config)
        res = strat.analyze(df_ind, "EURUSD", regime, "forex_major", current_price=1.1040, pip_size=0.0001)

        assert res.strategy_name == "LONDON_BREAKOUT"
        assert res.trigger_long is True
        assert res.extra_data["is_london_window"] is True

    def test_intermarket_momentum(self, base_config):
        calc = TechnicalIndicators(base_config)
        dates = pd.date_range("2026-01-01", periods=100, freq="1h")
        prices = [50.0 + i * 0.4 for i in range(100)]
        df = pd.DataFrame({
            "open": [p - 0.2 for p in prices],
            "high": [p + 0.3 for p in prices],
            "low": [p - 0.3 for p in prices],
            "close": prices,
            "volume": [5000] * 100,
        }, index=dates)

        df_ind = calc.calculate_all_indicators(df)
        regime = RegimeResult(regime="trending_bull", confidence=0.85)
        strat = IntermarketMomentumStrategy(base_config)
        res = strat.analyze(df_ind, "XTIUSD", regime, "commodity_oil", current_price=prices[-1])

        assert res.strategy_name == "INTERMARKET_MOMENTUM"
        assert res.trigger_long is True

    def test_strategy_engine_adaptive_selection(self, base_config):
        calc = TechnicalIndicators(base_config)
        # Série synthétique strictement haussière (RSI ≈ 100) : garde Murphy désactivée ici
        engine = StrategyEngine({**base_config, "MURPHY_EXHAUSTION_GUARD": False})

        # Test A: Tendance haussière -> sélectionne une stratégie de tendance
        dates = pd.date_range("2026-01-01", periods=60, freq="1h")
        prices = [100.0 + i * 0.5 for i in range(60)]
        df = pd.DataFrame({
            "open": [p - 0.2 for p in prices],
            "high": [p + 0.4 for p in prices],
            "low": [p - 0.3 for p in prices],
            "close": prices,
            "volume": [1000 + i * 10 for i in range(60)],
        }, index=dates)
        df_ind = calc.calculate_all_indicators(df)

        regime_bull = RegimeResult(regime="trending_bull", confidence=0.85)
        sig = engine.evaluate(df_ind, "XAUUSD", regime_bull, "commodity_gold", current_price=prices[-1])
        assert sig.strategy_name in ["ELDER_TRIPLE_SCREEN", "MURPHY_TREND", "INTERMARKET_MOMENTUM"]
        assert sig.entry_price > 0
