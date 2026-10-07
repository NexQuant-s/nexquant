"""
Tests unitaires pour le client MetaTrader 5 (MT5Client) avec mocks exhaustifs.
"""
import pytest
from unittest.mock import patch
import numpy as np
from types import SimpleNamespace

from superbot.broker.mt5_client import MT5Client


@pytest.fixture
def mock_mt5():
    """Fixture créant un mock complet du module MetaTrader5."""
    with patch("superbot.broker.mt5_client.mt5") as mock:
        mock.initialize.return_value = True
        mock.login.return_value = True
        mock.last_error.return_value = (0, "Success")
        mock.TRADE_RETCODE_DONE = 10009
        mock.TRADE_RETCODE_INVALID_FILL = 10030
        mock.ORDER_TYPE_BUY = 0
        mock.ORDER_TYPE_SELL = 1
        mock.ORDER_FILLING_FOK = 0
        mock.ORDER_FILLING_IOC = 1
        mock.ORDER_FILLING_RETURN = 2
        mock.POSITION_TYPE_BUY = 0
        mock.POSITION_TYPE_SELL = 1
        mock.TRADE_ACTION_DEAL = 1
        mock.TRADE_ACTION_SLTP = 6
        mock.TRADE_ACTION_REMOVE = 8
        mock.ORDER_TIME_GTC = 0
        mock.ACCOUNT_TRADE_MODE_REAL = 0
        mock.ACCOUNT_TRADE_MODE_DEMO = 2
        mock.TIMEFRAME_M1 = 1
        mock.TIMEFRAME_H1 = 16385
        mock.TIMEFRAME_D1 = 16408

        # Mock terminal_info
        mock.terminal_info.return_value = SimpleNamespace(connected=True)

        # Mock account_info
        mock.account_info.return_value = SimpleNamespace(
            login=123456,
            balance=10000.0,
            equity=10250.0,
            profit=250.0,
            margin=500.0,
            margin_free=9750.0,
            margin_level=2050.0,
            leverage=100,
            trade_mode=2,
            company="Fusion Markets",
            currency="EUR",
        )

        # Mock symbol_info
        def get_sym_info(sym):
            return SimpleNamespace(
                trade_contract_size=100000.0 if "EUR" in sym else 100.0,
                trade_tick_size=0.00001 if "EUR" in sym else 0.01,
                trade_tick_value=1.0 if "EUR" in sym else 1.0,
                digits=5 if "EUR" in sym else 2,
                point=0.00001 if "EUR" in sym else 0.01,
                trade_stops_level=10,  # 10 points StopLevel
                volume_min=0.01,
                volume_step=0.01,
                volume_max=100.0,
                filling_mode=2,  # SYMBOL_FILLING_IOC
            )
        mock.symbol_info.side_effect = get_sym_info

        # Mock symbol_info_tick
        def get_tick(sym):
            if "XAU" in sym or "GOLD" in sym:
                return SimpleNamespace(bid=2500.00, ask=2500.20)
            return SimpleNamespace(bid=1.10000, ask=1.10015)
        mock.symbol_info_tick.side_effect = get_tick

        yield mock


class TestMT5Client:

    def test_init_and_account_summary(self, mock_mt5):
        client = MT5Client(login=123456, password="pw", server="FusionMarkets-Demo")
        summary = client.get_account_summary()

        assert summary["balance"] == 10000.0
        assert summary["equity"] == 10250.0
        assert summary["unrealized_pnl"] == 250.0
        assert summary["free_margin"] == 9750.0
        assert summary["leverage"] == 100
        assert summary["currency"] == "EUR"
        assert summary["account_type"] == "MT5_DEMO"

    def test_fetch_candles(self, mock_mt5):
        client = MT5Client(login=123456, password="pw", server="FusionMarkets-Demo")
        
        # Simuler des taux retournés par copy_rates_from_pos
        mock_rates = np.array([
            (1700000000 + i * 3600, 1.1000 + i * 0.0001, 1.1020 + i * 0.0001, 1.0990 + i * 0.0001, 1.1010 + i * 0.0001, 1000 + i * 10, 0, 0)
            for i in range(10)
        ], dtype=[
            ('time', '<i8'), ('open', '<f8'), ('high', '<f8'),
            ('low', '<f8'), ('close', '<f8'), ('tick_volume', '<u8'),
            ('spread', '<i4'), ('real_volume', '<u8')
        ])
        mock_mt5.copy_rates_from_pos.return_value = mock_rates

        df = client.fetch_candles("EURUSD", "1h", limit=10)
        assert len(df) == 10
        assert list(df.columns) == ["open", "high", "low", "close", "volume", "server_utc_offset_s"]
        assert df.index.tz is not None  # UTC timestamp


    def test_get_spread(self, mock_mt5):
        client = MT5Client(login=123456, password="pw", server="FusionMarkets-Demo")
        # EURUSD: ask 1.10015, bid 1.10000 -> 0.00015 / 0.0001 = 1.5 pips
        spread_fx = client.get_spread("EURUSD")
        assert round(spread_fx, 1) == 1.5

        # XAUUSD: ask 2500.20, bid 2500.00 -> 0.20 / 0.10 = 2.0 pips
        spread_gold = client.get_spread("XAUUSD")
        assert round(spread_gold, 1) == 2.0

    def test_place_order_buy_success(self, mock_mt5):
        client = MT5Client(login=123456, password="pw", server="FusionMarkets-Demo")
        
        # Mock order_send return
        mock_mt5.order_send.return_value = SimpleNamespace(
            retcode=10009,  # TRADE_RETCODE_DONE
            order=999888,
            comment="Done"
        )

        res = client.place_order(
            symbol="EURUSD",
            side="BUY",
            amount=0.50,
            sl=1.0950,
            tp=1.1100,
            comment="Test Buy"
        )
        assert res is True
        assert mock_mt5.order_send.called
        sent_req = mock_mt5.order_send.call_args[0][0]
        assert sent_req["symbol"] == "EURUSD"
        assert sent_req["type"] == mock_mt5.ORDER_TYPE_BUY
        assert sent_req["volume"] == 0.50
        assert sent_req["sl"] == 1.0950
        assert sent_req["tp"] == 1.1100

    def test_place_order_stoplevel_clamping(self, mock_mt5):
        client = MT5Client(login=123456, password="pw", server="FusionMarkets-Demo")
        mock_mt5.order_send.return_value = SimpleNamespace(retcode=10009, order=111, comment="Done")

        # Prix ask = 1.10015. StopLevel = 10 points = 0.00010.
        # Si on demande un SL à 1.10010 (seulement 5 points de distance),
        # le client doit clamper le SL à 1.10015 - 0.00010 = 1.10005.
        client.place_order(
            symbol="EURUSD",
            side="BUY",
            amount=0.10,
            sl=1.10010,  # Trop proche
            tp=1.10500,
        )
        sent_req = mock_mt5.order_send.call_args[0][0]
        assert sent_req["sl"] <= 1.10005

    def test_place_order_filling_retry(self, mock_mt5):
        client = MT5Client(login=123456, password="pw", server="FusionMarkets-Demo")

        # Premier appel : échec INVALID_FILL (10030), deuxième appel : DONE (10009)
        mock_mt5.order_send.side_effect = [
            SimpleNamespace(retcode=10030, comment="Unsupported filling mode"),
            SimpleNamespace(retcode=10009, order=222, comment="Done"),
        ]

        res = client.place_order(
            symbol="EURUSD",
            side="BUY",
            amount=0.10,
            sl=1.0900,
            tp=1.1100,
        )
        assert res is True
        assert mock_mt5.order_send.call_count == 2

    def test_modify_sl_tp(self, mock_mt5):
        client = MT5Client(login=123456, password="pw", server="FusionMarkets-Demo")
        
        mock_pos = [SimpleNamespace(ticket=12345, symbol="EURUSD", volume=0.5, sl=1.0950, tp=1.1100)]
        mock_mt5.positions_get.return_value = mock_pos
        mock_mt5.order_send.return_value = SimpleNamespace(retcode=10009, comment="Done")

        res = client.modify_sl_tp("EURUSD", sl=1.0980, tp=1.1150)
        assert res is True
        assert mock_mt5.order_send.called
        sent_req = mock_mt5.order_send.call_args[0][0]
        assert sent_req["action"] == mock_mt5.TRADE_ACTION_SLTP
        assert sent_req["position"] == 12345
        assert sent_req["sl"] == 1.0980
        assert sent_req["tp"] == 1.1150

    def test_close_position(self, mock_mt5):
        client = MT5Client(login=123456, password="pw", server="FusionMarkets-Demo")
        
        mock_pos = [SimpleNamespace(ticket=555, symbol="EURUSD", volume=0.5, type=mock_mt5.POSITION_TYPE_BUY)]
        mock_mt5.positions_get.return_value = mock_pos
        mock_mt5.order_send.return_value = SimpleNamespace(retcode=10009, comment="Closed")

        res = client.close_position("EURUSD", reason="Take Profit Hit")
        assert res is True
        assert mock_mt5.order_send.called
        sent_req = mock_mt5.order_send.call_args[0][0]
        assert sent_req["type"] == mock_mt5.ORDER_TYPE_SELL
        assert sent_req["volume"] == 0.5
        assert sent_req["position"] == 555

    def test_get_closed_position_converts_server_time_and_aggregates(self, mock_mt5):
        import time as _time
        from datetime import datetime, timezone

        client = MT5Client(login=123456, password="pw", server="FusionMarkets-Demo")
        offset = 3 * 3600  # serveur en UTC+3
        now = int(_time.time())
        mock_mt5.symbol_info_tick.side_effect = lambda sym: SimpleNamespace(bid=1.1, ask=1.1001, time=now + offset)

        open_srv, close_srv = now + offset - 7200, now + offset - 600
        deals = [
            SimpleNamespace(entry=0, type=0, symbol="EURUSD", price=1.1000, volume=0.05, time=open_srv,
                            profit=0.0, commission=-0.2, swap=0.0, fee=0.0, reason=3, ticket=1, position_id=777),
            SimpleNamespace(entry=1, type=1, symbol="EURUSD", price=1.1030, volume=0.05, time=close_srv,
                            profit=15.0, commission=-0.2, swap=-0.1, fee=0.0, reason=5, ticket=2, position_id=777),
        ]
        mock_mt5.history_deals_get.return_value = deals

        trade = client.get_closed_position(777)

        mock_mt5.history_deals_get.assert_called_with(position=777)
        assert trade["side"] == "buy"
        assert trade["entry_price"] == pytest.approx(1.1000)
        assert trade["exit_price"] == pytest.approx(1.1030)
        assert trade["pnl"] == pytest.approx(14.5)
        assert trade["close_reason"] == "tp"
        assert trade["position_id"] == 777
        # Heure serveur ramenée en UTC
        assert trade["timestamp"] == datetime.fromtimestamp(close_srv - offset, timezone.utc)

    def test_get_closed_position_returns_none_while_open(self, mock_mt5):
        client = MT5Client(login=123456, password="pw", server="FusionMarkets-Demo")
        mock_mt5.history_deals_get.return_value = [
            SimpleNamespace(entry=0, type=1, symbol="XAUUSD", price=2500.0, volume=0.01, time=1,
                            profit=0.0, commission=0.0, swap=0.0, fee=0.0, reason=3, ticket=1, position_id=9),
        ]
        assert client.get_closed_position(9) is None

    def test_get_trade_history_one_row_per_position(self, mock_mt5):
        client = MT5Client(login=123456, password="pw", server="FusionMarkets-Demo")
        mk = lambda **kw: SimpleNamespace(**{"profit": 0.0, "commission": 0.0, "swap": 0.0, "fee": 0.0,
                                             "reason": 4, "ticket": 0, "volume": 0.01, "symbol": "XAUUSD", **kw})
        mock_mt5.history_deals_get.return_value = [
            mk(entry=0, type=1, price=2500.0, time=100, position_id=1),
            mk(entry=1, type=0, price=2510.0, time=200, position_id=1, profit=-10.0),
            mk(entry=0, type=0, price=2490.0, time=300, position_id=2),  # encore ouverte
        ]
        trades = client.get_trade_history(days=1)
        assert len(trades) == 1
        assert trades[0]["side"] == "sell"
        assert trades[0]["pnl"] == pytest.approx(-10.0)
        assert trades[0]["close_reason"] == "sl"
