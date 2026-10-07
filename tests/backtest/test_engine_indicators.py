"""Le backtest doit fournir à la stratégie les mêmes données que le live (OHLCV + indicateurs)."""

import numpy as np
import pandas as pd

from superbot.backtest.engine import BacktestEngine


class _FakeIndicators:
    def calculate_all_indicators(self, df):
        out = df.copy()
        out["adx"] = 30.0
        out["ema_fast"] = out["close"]
        return out


class _SpyStrategy:
    def __init__(self):
        self.indicators = _FakeIndicators()
        self.seen_columns = set()

    def analyze_market(self, df, **_kw):
        self.seen_columns |= set(df.columns)
        return {"should_long": False, "should_short": False}


def test_backtest_slices_include_indicators():
    idx = pd.date_range("2026-01-05", periods=150, freq="15min", tz="UTC")
    close = 1.1 + np.cumsum(np.full(150, 1e-4))
    df = pd.DataFrame({"open": close, "high": close + 2e-4, "low": close - 2e-4,
                       "close": close, "volume": 100}, index=idx)
    spy = _SpyStrategy()
    BacktestEngine(df, {}, initial_balance=1000.0, symbol="EURUSD").run(spy, warmup_bars=100)
    assert {"adx", "ema_fast"} <= spy.seen_columns


def test_strategy_sessions_follow_bar_time_not_wall_clock():
    from superbot.strategy.strategy import TradingStrategy
    from superbot.brain.regime_detector import RegimeResult
    from superbot.strategy.base_strategy import SignalResult

    captured = {}

    class _Engine:
        def evaluate(self, **kw):
            captured["sessions"] = kw["active_sessions"]
            return SignalResult(strategy_name="NONE")

    class _Regime:
        def detect(self, **_kw):
            return RegimeResult(regime="ranging", confidence=0.5)

    idx = pd.date_range("2026-01-05 08:00", periods=30, freq="15min", tz="UTC")  # dernière barre 15:15 UTC
    df = pd.DataFrame({"open": 1.1, "high": 1.1, "low": 1.1, "close": 1.1, "volume": 1}, index=idx)
    TradingStrategy({}, strategy_engine=_Engine(), regime_detector=_Regime()).analyze_market(df, symbol="EURUSD")
    assert "LONDON" in captured["sessions"] and "OVERLAP" in captured["sessions"]
