"""
Unit and Integration tests for:
1. UnifiedAlphaStrategy (Visual curve analysis, slope, curvature, Gold directional symmetry, R:R >= 2.0)
2. PerformanceLearner (10-minute cooldown on consecutive losses, post-mortem diagnosis, adaptive parameters)
3. ReportGenerator (Post-mortem logging and active pause reporting)
4. Loss limit disablement (ENABLE_LOSS_LIMIT = False)
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from superbot.strategy.unified_alpha import UnifiedAlphaStrategy
from superbot.brain.performance_learner import PerformanceLearner
from superbot.brain.report_generator import ReportGenerator
from superbot.brain.regime_detector import RegimeResult
from superbot.indicators.technical_indicators import TechnicalIndicators
from superbot.risk.risk_manager import RiskManager


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
        "TP_ATR_MULT": 3.0,
    }


class TestUnifiedAlphaStrategy:

    def test_visual_curve_analysis_uptrend(self, base_config):
        strat = UnifiedAlphaStrategy(base_config)
        # Create a clean upward sloping curve
        prices = [100.0 + i * 0.5 for i in range(40)]
        df = pd.DataFrame({"close": prices, "high": [p + 0.3 for p in prices], "low": [p - 0.3 for p in prices]})
        curve = strat.calculate_market_curve(df, current_price=prices[-1], atr=0.5)

        assert curve["slope_norm"] > 0.3
        assert curve["curve_bias"] > 0
        assert curve["structure"] in ["BULLISH_HH_HL", "HH_HL"]
        assert not curve["is_concave_top"]

    def test_visual_curve_analysis_downtrend(self, base_config):
        strat = UnifiedAlphaStrategy(base_config)
        # Create a clean downward sloping curve
        prices = [100.0 - i * 0.5 for i in range(40)]
        df = pd.DataFrame({"close": prices, "high": [p + 0.3 for p in prices], "low": [p - 0.3 for p in prices]})
        curve = strat.calculate_market_curve(df, current_price=prices[-1], atr=0.5)

        assert curve["slope_norm"] < -0.3
        assert curve["curve_bias"] < 0
        assert curve["structure"] in ["BEARISH_LH_LL", "LH_LL"]
        assert not curve["is_convex_bottom"]

    def test_concave_top_detection_penalizes_buy_on_gold(self, base_config):
        strat = UnifiedAlphaStrategy(base_config)
        calc = TechnicalIndicators(base_config)

        # Create an inverted parabolic curve (concave top: rise then rollover at peak)
        t = np.linspace(0, np.pi, 50)
        base_price = 2600.0
        prices = base_price + 30.0 * np.sin(t)
        # End at the rollover phase
        dates = pd.date_range("2026-01-01", periods=50, freq="1h")
        df = pd.DataFrame({
            "open": prices - 0.5,
            "high": prices + 1.0,
            "low": prices - 1.0,
            "close": prices,
            "volume": [1500]*50
        }, index=dates)

        df_ind = calc.calculate_all_indicators(df)
        curve = strat.calculate_market_curve(df_ind, current_price=float(prices[-1]), atr=2.0)

        # Curvature should be negative (concave top)
        assert curve["curvature"] < 0 or curve["is_concave_top"]

        # Run analyze on XAUUSD
        regime = RegimeResult(regime="trending_bull", confidence=0.7)
        res = strat.analyze(df_ind, "XAUUSD", regime, "commodity", current_price=float(prices[-1]))

        # Under a concave top rollover, BUY must NEVER trigger
        assert not res.should_long, "Concave rollover top on Gold must NOT trigger a LONG signal!"

    def test_bearish_symmetry_triggers_short_on_gold(self, base_config):
        strat = UnifiedAlphaStrategy(base_config)
        calc = TechnicalIndicators(base_config)

        # Create sharp bearish momentum
        dates = pd.date_range("2026-01-01", periods=50, freq="1h")
        prices = [2700.0 - i * 1.5 for i in range(50)]
        df = pd.DataFrame({
            "open": [p + 0.8 for p in prices],
            "high": [p + 1.2 for p in prices],
            "low": [p - 0.8 for p in prices],
            "close": prices,
            "volume": [2000]*50
        }, index=dates)

        df_ind = calc.calculate_all_indicators(df)
        regime = RegimeResult(regime="trending_bear", confidence=0.9)
        res = strat.analyze(df_ind, "XAUUSD", regime, "commodity", current_price=prices[-1])

        # Must trigger SHORT and have R:R >= 2.0
        assert res.should_short
        assert not res.should_long
        assert res.rr_ratio >= 2.0
        assert res.sl_price > prices[-1]
        assert res.tp_price < prices[-1]

    def test_post_mortem_adapted_params_increase_conviction_requirement(self, base_config):
        strat = UnifiedAlphaStrategy(base_config)
        calc = TechnicalIndicators(base_config)

        dates = pd.date_range("2026-01-01", periods=50, freq="1h")
        prices = [1.0800 + i * 0.0003 for i in range(50)]
        df = pd.DataFrame({
            "open": [p - 0.0002 for p in prices],
            "high": [p + 0.0004 for p in prices],
            "low": [p - 0.0002 for p in prices],
            "close": prices,
            "volume": [1000]*50
        }, index=dates)

        df_ind = calc.calculate_all_indicators(df)
        regime = RegimeResult(regime="trending_bull", confidence=0.8)

        # Baseline evaluation
        res_baseline = strat.analyze(df_ind, "EURUSD", regime, "forex_major", current_price=prices[-1])

        # Adapted params boosting required score by +2.0
        adapted = {"score_min_boost": 2.0, "sl_atr_mult_boost": 0.5, "tp_atr_mult_boost": 1.0}
        res_adapted = strat.analyze(
            df_ind, "EURUSD", regime, "forex_major", current_price=prices[-1], adapted_params=adapted
        )

        assert res_adapted.score_min == res_baseline.score_min + 2.0
        if res_adapted.should_long:
            # SL should be wider
            assert (prices[-1] - res_adapted.sl_price) > (prices[-1] - res_baseline.sl_price)


class TestConsecutiveLossesAndCooldown:

    def test_10_min_pause_triggered_on_consecutive_losses(self, base_config, tmp_path):
        rg = ReportGenerator(reports_dir=str(tmp_path))
        learner = PerformanceLearner()
        learner._report_generator = rg

        symbol = "XAUUSD"
        other_symbol = "EURUSD"

        # Trade 1: Loss
        trade1 = {"symbol": symbol, "pnl": -12.50, "entry_price": 2650.0, "exit_price": 2645.0, "atr": 2.0}
        learner.on_trade_closed(trade1)
        assert not learner.is_symbol_blocked(symbol), "Single loss must not block symbol"

        # Trade 2: Consecutive Loss on XAUUSD
        trade2 = {"symbol": symbol, "pnl": -15.00, "entry_price": 2645.0, "exit_price": 2640.0, "atr": 2.0}
        learner.on_trade_closed(trade2)

        # 10-minute pause must now be ACTIVE for XAUUSD
        assert learner.is_symbol_blocked(symbol), "2 consecutive losses must trigger 10-min pause on symbol"
        # Other symbols must remain completely unblocked
        assert not learner.is_symbol_blocked(other_symbol), "Other symbols must NOT be blocked!"

        # Check active pauses metadata
        active_pauses = learner.get_active_pauses()
        assert symbol in active_pauses
        assert active_pauses[symbol]["consecutive_losses"] == 2
        assert 9.0 <= active_pauses[symbol]["remaining_minutes"] <= 10.0

        # Check adapted parameters
        adapted = learner.get_symbol_adapted_params(symbol)
        assert adapted.get("score_min_boost") == 1.0
        assert adapted.get("sl_atr_mult_boost") == 0.2

        # Check ReportGenerator recorded the post-mortem event
        events = rg._current_session_events.get("post_mortems", [])
        assert len(events) == 1
        assert events[0]["symbol"] == symbol
        assert events[0]["consecutive_losses"] == 2

        # Generate daily report and ensure the section is present
        report_md = rg.generate_daily_report()
        assert "Diagnostics Post-Mortem & Analyses de Pertes" in report_md
        assert "XAUUSD" in report_md
        assert "Pause déclenchée" in report_md or "Action conservatoire" in report_md

    def test_automatic_resumption_after_10_minutes(self):
        learner = PerformanceLearner()
        symbol = "GBPUSD"

        # Set consecutive losses blocked 11 minutes ago
        past_time = datetime.now(timezone.utc) - timedelta(minutes=11)
        learner._symbol_consecutive_losses[symbol] = {"count": 2, "blocked_at": past_time}

        # Symbol should automatically unblock upon check
        assert not learner.is_symbol_blocked(symbol)
        assert learner._symbol_consecutive_losses[symbol]["count"] == 0


class TestLossLimitDisablement:

    def test_enable_loss_limit_false_prevents_kill_switch(self):
        rm = RiskManager(config={"ENABLE_LOSS_LIMIT": False})
        # Ensure loss limit is disabled
        assert not rm.ENABLE_LOSS_LIMIT

        # Simulate a 10% loss today
        rm.day_start_balance = 100.0
        current_balance = 90.0

        # Kill switch must NOT fire
        is_killed = rm.check_kill_switch(current_balance)
        assert not is_killed, "check_kill_switch must return False when ENABLE_LOSS_LIMIT is False"

