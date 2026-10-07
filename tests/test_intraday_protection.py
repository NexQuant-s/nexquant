"""Protections intra-journée (mode défensif, protection des gains, blocage de stratégies) et OFF_HOURS."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from superbot.brain.performance_learner import PerformanceLearner


def test_defensive_multiplier_is_fixed_not_cumulative():
    pl = PerformanceLearner()
    for _ in range(5):  # appelé toutes les 30 min : ne doit pas s'écraser vers 0
        pl.mid_session_check(current_pnl=-20.0, target_pnl=18.0, balance=920.0)
    assert pl.get_risk_multiplier() == PerformanceLearner.DEFENSIVE_MULT


def test_defensive_mode_expires_and_resets_daily():
    pl = PerformanceLearner()
    pl.mid_session_check(current_pnl=-20.0, target_pnl=18.0, balance=920.0)
    pl._defensive_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert pl.get_risk_multiplier() == 1.0
    pl.mid_session_check(current_pnl=30.0, target_pnl=18.0, balance=950.0)
    assert pl.get_risk_multiplier() == PerformanceLearner.PROFIT_PROTECTION_MULT
    pl.reset_daily()
    assert pl.get_risk_multiplier() == 1.0


def test_strategy_blocked_after_poor_results_without_double_counting():
    from superbot.brain.strategy_engine import StrategyEngine
    engine = StrategyEngine()
    pl = PerformanceLearner(strategy_engine=engine)
    for _ in range(10):
        pl.on_trade_closed({'symbol': 'EURUSD', 'pnl': -5.0, 'strategy_name': 'MURPHY_TREND'})
    assert engine._strategy_stats['MURPHY_TREND']['trades'] == 10
    pl.post_session_debrief({'trades': list(pl._session_trades), 'pnl_total': -50, 'pnl_target': 18})
    assert engine._strategy_stats['MURPHY_TREND']['trades'] == 10  # pas de ré-enregistrement
    assert pl.is_strategy_blocked('MURPHY_TREND')


def test_off_hours_commodities_allowed_outside_rollover(monkeypatch):
    from superbot.brain.session_manager import SessionManager, SESSION_DEFINITIONS

    sm = SessionManager(daily_target_eur=10.0)
    sm._current_session_name = "OFF_HOURS"
    sm._current_session = SESSION_DEFINITIONS["OFF_HOURS"]
    monkeypatch.setattr("superbot.broker.symbol_specs.is_rollover_period", lambda *a, **k: False)
    assert sm.can_trade_symbol("XAUUSD")[0] is True
    assert sm.can_trade_symbol("EURUSD")[0] is False
    monkeypatch.setattr("superbot.broker.symbol_specs.is_rollover_period", lambda *a, **k: True)
    assert sm.can_trade_symbol("XAUUSD")[0] is False


def test_risk_factor_combines_news_and_protection():
    from superbot.components.signal_executor import _risk_factor
    bot = MagicMock()
    bot.news_manager.get_risk_factor.return_value = 1.0
    bot.performance_learner.get_risk_multiplier.return_value = 0.3
    assert _risk_factor(bot) == 0.3
