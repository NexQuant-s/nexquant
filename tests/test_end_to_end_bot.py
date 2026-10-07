"""
Test d'intégration End-to-End complet pour NexQuant SuperBot (Forex & Commodities MT5).
"""
import pytest
from unittest.mock import patch
import pandas as pd
import numpy as np
from types import SimpleNamespace

from superbot.orchestrator import SuperBot
from superbot.strategy.strategy import TradingStrategy


@pytest.fixture
def mock_complete_mt5():
    """Fixture mockant intégralement MetaTrader5."""
    with patch("superbot.broker.mt5_client.mt5") as mock:
        mock.initialize.return_value = True
        mock.login.return_value = True
        mock.last_error.return_value = (0, "Success")
        mock.TRADE_RETCODE_DONE = 10009
        mock.ORDER_TYPE_BUY = 0
        mock.ORDER_TYPE_SELL = 1
        mock.ORDER_FILLING_IOC = 1
        mock.TRADE_ACTION_DEAL = 1
        mock.TRADE_ACTION_SLTP = 6
        mock.ORDER_TIME_GTC = 0
        mock.ACCOUNT_TRADE_MODE_DEMO = 2
        mock.TIMEFRAME_H1 = 16385

        mock.terminal_info.return_value = SimpleNamespace(connected=True)
        mock.account_info.return_value = SimpleNamespace(
            login=123456,
            balance=10000.0,
            equity=10000.0,
            profit=0.0,
            margin=0.0,
            margin_free=10000.0,
            margin_level=0.0,
            leverage=100,
            trade_mode=2,
            company="Fusion Markets",
            currency="USD",
        )

        def get_sym_info(sym):
            return SimpleNamespace(
                trade_contract_size=100.0 if "XAU" in sym else 100000.0,
                trade_tick_size=0.01 if "XAU" in sym else 0.00001,
                trade_tick_value=1.0,
                digits=2 if "XAU" in sym else 5,
                point=0.01 if "XAU" in sym else 0.00001,
                trade_stops_level=5,
                volume_min=0.01,
                volume_step=0.01,
                volume_max=100.0,
                filling_mode=2,
            )
        mock.symbol_info.side_effect = get_sym_info

        def get_tick(sym):
            if "XAU" in sym:
                return SimpleNamespace(bid=2500.00, ask=2500.20)
            return SimpleNamespace(bid=1.10000, ask=1.10015)
        mock.symbol_info_tick.side_effect = get_tick

        # Données de bougies réalistes
        mock_rates = np.array([
            (1700000000 + i * 3600, 1.1000 + i * 0.0001, 1.1020 + i * 0.0001, 1.0990 + i * 0.0001, 1.1010 + i * 0.0001, 1000 + i * 10, 0, 0)
            for i in range(100)
        ], dtype=[
            ('time', '<i8'), ('open', '<f8'), ('high', '<f8'),
            ('low', '<f8'), ('close', '<f8'), ('tick_volume', '<u8'),
            ('spread', '<i4'), ('real_volume', '<u8')
        ])
        mock.copy_rates_from_pos.return_value = mock_rates
        mock.positions_get.return_value = []
        mock.history_deals_get.return_value = []
        mock.order_send.return_value = SimpleNamespace(retcode=10009, order=999, comment="Done")

        yield mock


class TestEndToEndBot:

    def test_trading_strategy_analyzer(self):
        strat = TradingStrategy()
        dates = pd.date_range("2026-01-01", periods=60, freq="1h")
        prices = [100.0 + i * 0.3 for i in range(58)]
        prices.append(prices[-1] - 0.4)
        prices.append(prices[-2] + 0.8)
        df = pd.DataFrame({
            "open": [p - 0.1 for p in prices],
            "high": [p + 0.2 for p in prices],
            "low": [p - 0.2 for p in prices],
            "close": prices,
            "volume": [1000 + i * 10 for i in range(60)],
        }, index=dates)

        from superbot.indicators.technical_indicators import TechnicalIndicators
        calc = TechnicalIndicators()
        df_ind = calc.calculate_all_indicators(df)

        res = strat.analyze_market(df_ind, symbol="EURUSD")
        assert res["symbol"] == "EURUSD"
        assert "market_regime" in res
        assert "strategy_used" in res
        assert res["entry_price"] > 0

    def test_superbot_single_cycle(self, mock_complete_mt5):
        # Initialiser le SuperBot avec MT5 broker
        bot = SuperBot()
        assert bot.broker is not None
        assert bot.technical_indicators is not None
        assert bot.risk_manager is not None
        assert bot.strategy is not None

        # Exécuter le scan et le traitement d'un symbole
        bot._process_symbol("EURUSD")
        
        # Vérifier que les positions et le statut sont cohérents
        summary = bot.get_status()
        assert summary["running"] is False  # Loop is not started in unit test
        assert summary["broker"] == "MT5"
