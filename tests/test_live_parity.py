"""Options de parité live/backtest : stratégies actives, SL/TP de la stratégie, plancher de risque."""

from superbot.brain.strategy_engine import StrategyEngine
from superbot.components.signal_executor import _strategy_sl_tp


def test_enabled_strategies_filters_engine():
    assert set(StrategyEngine({"ENABLED_STRATEGIES": ["MURPHY_TREND"]}).strategies) == {"MURPHY_TREND"}
    assert set(StrategyEngine({"ENABLED_STRATEGIES": "murphy_trend, ELDER_TRIPLE_SCREEN"}).strategies) == {
        "MURPHY_TREND", "ELDER_TRIPLE_SCREEN"}
    assert len(StrategyEngine({}).strategies) == 7          # vide = toutes (comportement inchangé)
    assert StrategyEngine({"ENABLED_STRATEGIES": ["INCONNUE"]}).strategies == {}  # nom faux : aucun trade


def test_engine_configure_keeps_filter():
    engine = StrategyEngine()
    engine.configure({"ENABLED_STRATEGIES": ["MURPHY_TREND"]})
    assert set(engine.strategies) == {"MURPHY_TREND"}


def test_murphy_min_adx_threshold():
    import pandas as pd
    from superbot.brain.regime_detector import RegimeResult
    from superbot.strategy.murphy_trend import MurphyTrendStrategy

    n = 40
    close = [100 + i * 0.1 for i in range(n)]
    df = pd.DataFrame({"open": close, "high": [c + 0.05 for c in close], "low": [c - 0.05 for c in close],
                       "close": close, "ema_fast": [c - 0.2 for c in close], "ema_slow": [c - 0.5 for c in close],
                       "ema_trend": [c - 1.0 for c in close], "adx": 22.0, "rsi": 60.0, "atr": 0.3})
    regime = RegimeResult(regime="trending_bull", confidence=0.8)
    args = (df, "EURUSD", regime, "forex_major", close[-1])
    assert MurphyTrendStrategy({}).analyze(*args).trigger_long is True            # défaut 20 : inchangé
    assert MurphyTrendStrategy({"MURPHY_MIN_ADX": 25}).analyze(*args).trigger_long is False


def test_strategy_sl_tp_only_when_enabled_and_coherent(monkeypatch):
    long_sig = {"should_long": True, "sl_price": 1.0950, "tp_price": 1.1100}
    monkeypatch.setattr("superbot.config.USE_STRATEGY_SL_TP", False)
    assert _strategy_sl_tp(long_sig, 1.1000) is None

    monkeypatch.setattr("superbot.config.USE_STRATEGY_SL_TP", True)
    assert _strategy_sl_tp(long_sig, 1.1000) == (1.0950, 1.1100)
    assert _strategy_sl_tp(long_sig, 1.0940) is None        # prix réel déjà sous le SL : repli ATR
    short_sig = {"should_short": True, "sl_price": 1.1050, "tp_price": 1.0900}
    assert _strategy_sl_tp(short_sig, 1.1000) == (1.1050, 1.0900)
    assert _strategy_sl_tp({"should_long": True, "sl_price": 0, "tp_price": 1.2}, 1.1) is None
