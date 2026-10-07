import numpy as np
import pandas as pd
from unittest.mock import MagicMock, patch

from superbot.orchestrator import SuperBot


ENTRY_PRICE = 50000.0


class FakeBroker:
    """Broker simulé : OHLCV synthétique, exécution, et position état-courant."""

    def __init__(self, candles):
        self._candles = candles
        self.position = None
        self.orders = []

    def get_asset_type(self):
        return "crypto"

    def get_balance(self):
        return 10000.0

    def get_account_summary(self):
        return {"equity": 10000.0, "free_margin": 10000.0, "leverage": 1, "balance": 10000.0}

    def get_default_instruments(self):
        return ["BTC/USDT"]

    def get_default_news_assets(self):
        return []

    def get_symbol_info(self, symbol):
        return {"contract_size": 1.0, "tick_size": 0.01, "tick_value": 0.01}

    def get_min_order_size(self, symbol):
        return 0.001

    def get_step_size(self, symbol):
        return 0.0

    def get_spread(self, symbol):
        return 1.0

    def get_trade_history(self, days=1):
        return []

    def get_open_positions(self):
        return [self.position] if self.position else []

    def get_current_price(self, symbol):
        return ENTRY_PRICE + 500.0

    def cancel_all_orders(self, symbol):
        pass

    def fetch_candles(self, symbol, timeframe, limit):
        return self._candles

    def place_order(self, symbol, side, amount, sl, tp, comment):
        self.orders.append({"symbol": symbol, "side": side, "amount": amount, "sl": sl, "tp": tp})
        self.position = {
            "symbol": symbol,
            "side": "LONG" if side == "buy" else "SHORT",
            "size": amount,
            "entry_price": ENTRY_PRICE,
            "stop_loss": sl,
            "take_profit": tp,
        }
        return {"order_id": len(self.orders)}

    def get_position(self, symbol):
        if self.position and self.position.get("symbol") == symbol:
            return self.position
        return None


def _candles(n=100):
    dates = pd.date_range("2026-01-01", periods=n, freq="h")
    close = np.linspace(49000.0, ENTRY_PRICE, n)
    return pd.DataFrame(
        {
            "open": close - 50.0,
            "high": close + 100.0,
            "low": close - 100.0,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


def _signal():
    # Signal déterministe : la génération réelle (scoring/triggers) est couverte
    # par tests/strategy/. Ici on valide l'orchestration du pipeline.
    return {
        "total_score": 9.0,
        "score_min": 7.0,
        "rr_ratio": 2.0,
        "market_regime": "TRENDING",
        "hmm_label": "TRENDING",
        "should_long": True,
        "should_short": False,
        "trigger_long": True,
        "trigger_short": False,
        "entry_price": ENTRY_PRICE,
        "sl_price": ENTRY_PRICE * 0.98,
        "tp_price": ENTRY_PRICE * 1.04,
    }


def _build_bot(monkeypatch, tmp_path, broker):
    monkeypatch.setattr("superbot.config.TRADE_LOG_FILE", str(tmp_path / "trades.jsonl"))
    # Les bougies synthétiques montent linéairement : l'entrée se fait au plus haut et
    # serait (à juste titre) rejetée par le filtre d'épuisement, hors sujet ici.
    monkeypatch.setattr("superbot.config.ENTRY_EXHAUSTION_FILTER", False)
    # Rendre le filtre nocturne déterministe (indépendant de l'heure du run).
    monkeypatch.setattr(
        "superbot.components.signal_executor._is_night_session",
        lambda *a, **k: False,
    )

    fake_telemetry = MagicMock()
    fake_telemetry.enabled = False

    with patch("superbot.orchestrator.create_broker", return_value=broker), \
         patch("superbot.orchestrator.telemetry_client", fake_telemetry), \
         patch("superbot.orchestrator.ENABLE_DASHBOARD", False), \
         patch("superbot.orchestrator.WEBHOOK_ENABLED", False):
        bot = SuperBot()

    # Neutraliser l'état chargé depuis disque/cloud/DB pour un test déterministe.
    bot.telemetry = fake_telemetry
    bot.instruments = ["BTC/USDT"]  # le .env charge une liste forex (MT5), pas BTC
    bot.positions = {}
    bot.session_manager = None
    bot.performance_learner = None
    bot.regime_detector = None
    bot.strategy_engine = None
    bot.news_manager = None
    bot.online_learner = None
    bot.blocked_symbols = set()
    bot.session_pnl_by_symbol = {}
    bot.failed_execution_cooldowns = {}
    bot._cached_balance = 10000.0
    bot.risk_manager.trade_history = []
    bot.risk_manager.open_positions = {}
    bot.risk_manager.consecutive_losses = {}
    bot.risk_manager.last_trade_close_time = {}
    bot.risk_manager.daily_pnl = 0.0
    return bot


def test_full_pipeline_fetch_to_close(monkeypatch, tmp_path):
    broker = FakeBroker(_candles())
    bot = _build_bot(monkeypatch, tmp_path, broker)
    bot.strategy.analyze_market = lambda *a, **k: _signal()

    # 1. fetch (broker) → indicateurs réels → signal → exécution
    bot._process_symbol("BTC/USDT")

    assert bot.stats["trades_executed"] == 1
    assert len(broker.orders) == 1
    assert broker.orders[0]["side"] == "buy"
    pos = bot.positions["BTC/USDT"]
    assert pos["side"] == "LONG"
    assert pos["size"] > 0
    assert pos["market_regime"] == "TRENDING"
    assert "adx" in pos["features"]

    # 2. sync : le régime + les features survivent à la reconstruction
    bot._sync_positions_with_broker()
    assert bot.positions["BTC/USDT"]["market_regime"] == "TRENDING"
    assert "adx" in bot.positions["BTC/USDT"]["features"]

    # 3. clôture côté broker → le sync détecte la fermeture et enregistre le trade
    broker.position = None
    bot._sync_positions_with_broker()

    assert bot.positions == {}
    closed = [t for t in bot.risk_manager.trade_history if t.get("status") == "closed"]
    assert len(closed) == 1
    assert closed[0]["market_regime"] == "TRENDING"
    assert closed[0]["broker"] == bot.active_broker_type
    assert closed[0]["pnl"] > 0
    assert "adx" in closed[0]
