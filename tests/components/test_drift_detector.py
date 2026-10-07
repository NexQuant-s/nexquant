from superbot.components.drift_detector import detect_model_drift
from superbot.components.runtime_config import RuntimeConfig
from superbot.risk.risk_manager import RiskManager
from superbot.strategy.strategy import TradingStrategy
from superbot.monitoring.bug_watchdog import BugWatchdog


class DummyBot:
    def __init__(self, risk_pct=1.0):
        self.risk_manager = RiskManager({'RISK_PCT': risk_pct})
        self.strategy = TradingStrategy({'SCORE_MIN': 6.0, 'RISK_PCT': risk_pct})
        self.runtime_config = RuntimeConfig(risk_pct=risk_pct, score_min=6.0)
        self.runtime_config.bind(self.risk_manager, self.strategy)
        self.auto_unpause = True
        self.is_paused = False

    @property
    def adaptive_risk_pct(self) -> float:
        return self.runtime_config.risk_pct

    @adaptive_risk_pct.setter
    def adaptive_risk_pct(self, value: float):
        self.runtime_config.set(risk_pct=value)


def test_drift_detector_bounded_decay():
    bot = DummyBot(risk_pct=1.0)
    bot.risk_manager.trade_history = [{'status': 'closed', 'pnl': -1.0} for _ in range(15)]

    detect_model_drift(bot)
    assert bot.adaptive_risk_pct >= 0.5

    first_risk = bot.adaptive_risk_pct
    detect_model_drift(bot)
    detect_model_drift(bot)
    detect_model_drift(bot)
    assert bot.adaptive_risk_pct == first_risk
    assert bot.adaptive_risk_pct >= 0.5


def test_bug_watchdog_auto_heals_invalid_risk():
    bot = DummyBot(risk_pct=1.0)
    watchdog = BugWatchdog(bot)

    bot.risk_manager.RISK_PCT = 0.0
    res = watchdog._check_risk_manager_coherence()

    assert res is None
    assert bot.risk_manager.RISK_PCT == 1.0


def test_drift_reductions_are_applied_once():
    # Dérive sévère (0 % de gain) : risque ÷ 2, pas ÷ 8
    bot = DummyBot(risk_pct=2.0)
    bot.risk_manager.trade_history = [{'status': 'closed', 'pnl': -1.0} for _ in range(10)]
    detect_model_drift(bot)
    assert bot.adaptive_risk_pct == 1.0

    # Dérive modérée (20-30 % de gain) : risque × 0.75, une seule fois
    bot = DummyBot(risk_pct=2.0)
    bot.risk_manager.trade_history = (
        [{'status': 'closed', 'pnl': 1.0} for _ in range(2)]
        + [{'status': 'closed', 'pnl': -1.0} for _ in range(8)]
    )
    detect_model_drift(bot)
    assert bot.adaptive_risk_pct == 1.5
