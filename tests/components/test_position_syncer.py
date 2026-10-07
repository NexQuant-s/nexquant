from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from superbot.risk.risk_manager import RiskManager
from superbot.components.position_syncer import sync_positions_with_broker


class FakeBroker:
    def __init__(self, position=None, open_positions=None, current_price=51000.0):
        self._position = position
        self._open_positions = open_positions or []
        self._current_price = current_price

    def get_position(self, symbol):
        return self._position

    def get_open_positions(self):
        return self._open_positions

    def cancel_all_orders(self, symbol):
        pass

    def get_trade_history(self, days=1):
        return []

    def get_current_price(self, symbol):
        return self._current_price

    def get_balance(self):
        return 10500.0

    def get_asset_type(self):
        return "crypto"


def _open_bot():
    bot = SimpleNamespace()
    bot.instruments = ["BTC/USDT"]
    bot.broker = FakeBroker(
        position={
            "side": "LONG", "size": 0.5, "entry_price": 50000.0,
            "stop_loss": 49000.0, "take_profit": 52000.0,
        },
        open_positions=[{"symbol": "BTC/USDT"}],
    )
    bot.positions = {
        "BTC/USDT": {
            "side": "LONG", "size": 0.5, "entry_price": 50000.0,
            "stop_loss": 49000.0, "take_profit": 52000.0,
            "market_regime": "TRENDING",
            "features": {"rsi": 55.0, "adx": 30.0},
            "timestamp": datetime(2026, 8, 1, tzinfo=timezone.utc),
        }
    }
    bot.risk_manager = RiskManager({})
    bot.risk_manager.open_positions = {
        "BTC/USDT": {
            "symbol": "BTC/USDT", "side": "LONG", "entry_price": 50000.0,
            "size": 0.5, "stop_loss": 49000.0, "take_profit": 52000.0,
            "atr_value": 500.0, "initial_sl": 49000.0,
            "break_even_activated": True, "trailing_stop_enabled": True,
        }
    }
    bot.telemetry = MagicMock()
    bot.telemetry.enabled = False
    bot.online_learner = None
    bot.session_pnl_by_symbol = {}
    bot.blocked_symbols = set()
    bot.ASSET_BLOCK_LOSS_THRESHOLD = 50.0
    bot.initial_balance = 10000.0
    return bot


def test_sync_preserves_market_regime_and_features():
    bot = _open_bot()
    sync_positions_with_broker(bot)
    pos = bot.positions["BTC/USDT"]
    assert pos["market_regime"] == "TRENDING"
    assert pos["features"] == {"rsi": 55.0, "adx": 30.0}
    assert pos["timestamp"] == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_sync_preserves_risk_manager_trailing_state():
    bot = _open_bot()
    sync_positions_with_broker(bot)
    rp = bot.risk_manager.open_positions["BTC/USDT"]
    assert rp["atr_value"] == 500.0
    assert rp["initial_sl"] == 49000.0
    assert rp["break_even_activated"] is True
    assert rp["trailing_stop_enabled"] is True


def test_sync_close_propagates_regime_features_and_broker():
    bot = _open_bot()
    bot.broker = FakeBroker(position=None, open_positions=[], current_price=51000.0)
    bot.risk_manager = MagicMock()
    bot.active_broker_type = "binance"
    bot._convert_pnl_to_account_currency = lambda symbol, raw_pnl, price: raw_pnl

    sync_positions_with_broker(bot)

    record = bot.risk_manager.record_trade.call_args[0][0]
    assert record["status"] == "closed"
    assert record["market_regime"] == "TRENDING"
    assert record["rsi"] == 55.0
    assert record["adx"] == 30.0
    assert record["broker"] == "binance"
    assert record["verified"] is False
    assert record["close_reason"] == "estimated"


def _closing_bot(broker):
    bot = _open_bot()
    bot.positions["BTC/USDT"]["strategy_name"] = "MURPHY_TREND"
    bot.positions["BTC/USDT"]["position_id"] = 4242
    bot.broker = broker
    bot.risk_manager = MagicMock()
    bot.active_broker_type = "mt5"
    bot._convert_pnl_to_account_currency = lambda symbol, raw_pnl, price: raw_pnl
    return bot


def test_sync_preserves_strategy_name_and_ticket():
    bot = _open_bot()
    bot.positions["BTC/USDT"]["strategy_name"] = "MURPHY_TREND"
    bot.broker._position["ticket"] = 4242
    sync_positions_with_broker(bot)
    pos = bot.positions["BTC/USDT"]
    assert pos["strategy_name"] == "MURPHY_TREND"
    assert pos["position_id"] == 4242


def test_close_uses_exact_broker_position():
    broker = FakeBroker(position=None, current_price=51000.0)
    broker.get_closed_position = lambda pid: {
        "symbol": "BTC/USDT", "side": "buy", "entry_price": 50000.0, "exit_price": 49500.0,
        "pnl": -12.5, "position_id": pid, "close_reason": "sl",
    } if pid == 4242 else None
    bot = _closing_bot(broker)

    sync_positions_with_broker(bot)

    record = bot.risk_manager.record_trade.call_args[0][0]
    assert record["pnl"] == -12.5
    assert record["exit_price"] == 49500.0
    assert record["close_reason"] == "sl"
    assert record["verified"] is True
    assert record["position_id"] == 4242
    assert record["strategy_name"] == "MURPHY_TREND"


def test_history_fallback_ignores_other_positions():
    broker = FakeBroker(position=None, current_price=51000.0)
    # Clôture plus ancienne du même symbole mais sens et prix d'entrée différents
    broker.get_trade_history = lambda days=1: [{
        "symbol": "BTC/USDT", "side": "sell", "entry_price": 48000.0, "exit_price": 47000.0,
        "pnl": 99.0, "position_id": 1,
    }]
    bot = _closing_bot(broker)

    sync_positions_with_broker(bot)

    record = bot.risk_manager.record_trade.call_args[0][0]
    assert record["pnl"] != 99.0
    assert record["verified"] is False


def test_close_with_invalid_exit_price_is_not_recorded():
    broker = FakeBroker(position=None, current_price=0.0)
    bot = _closing_bot(broker)

    sync_positions_with_broker(bot)

    bot.risk_manager.record_trade.assert_not_called()
    assert "BTC/USDT" not in bot.positions
