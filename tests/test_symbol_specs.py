"""
Tests unitaires pour les spécifications de symboles MT5 (symbol_specs.py)
"""
from superbot.broker.symbol_specs import (
    normalize_symbol_name,
    get_asset_class,
    get_pip_size,
    is_rollover_period,
    get_active_sessions,
    calculate_lot_size,
)


class TestSymbolSpecs:

    def test_normalize_symbol_name(self):
        assert normalize_symbol_name("EUR/USD") == "EURUSD"
        assert normalize_symbol_name("eurusd") == "EURUSD"
        assert normalize_symbol_name("GOLD") == "XAUUSD"
        assert normalize_symbol_name("XAU/USD") == "XAUUSD"
        assert normalize_symbol_name("WTI") == "XTIUSD"
        assert normalize_symbol_name("USOIL") == "XTIUSD"
        assert normalize_symbol_name("BRENT") == "XBRUSD"
        assert normalize_symbol_name("SILVER") == "XAGUSD"
        assert normalize_symbol_name("GAS") == "XNGUSD"
        assert normalize_symbol_name("") == ""

    def test_get_asset_class(self):
        # Commodities
        assert get_asset_class("XAUUSD") == "commodity_gold"
        assert get_asset_class("GOLD") == "commodity_gold"
        assert get_asset_class("XAGUSD") == "commodity_silver"
        assert get_asset_class("XTIUSD") == "commodity_oil"
        assert get_asset_class("WTI") == "commodity_oil"
        assert get_asset_class("XBRUSD") == "commodity_oil"
        assert get_asset_class("XNGUSD") == "commodity_gas"
        # Forex
        assert get_asset_class("EURUSD") == "forex_major"
        assert get_asset_class("GBPUSD") == "forex_major"
        assert get_asset_class("USDJPY") == "forex_jpy"
        assert get_asset_class("EURJPY") == "forex_jpy"
        assert get_asset_class("GBPJPY") == "forex_jpy"
        assert get_asset_class("EURGBP") == "forex_cross"
        assert get_asset_class("EURAUD") == "forex_cross"

    def test_get_pip_size(self):
        assert get_pip_size("EURUSD") == 0.0001
        assert get_pip_size("USDJPY") == 0.01
        assert get_pip_size("XAUUSD") == 0.10
        assert get_pip_size("XTIUSD") == 0.01
        assert get_pip_size("XAGUSD") == 0.01

    def test_is_rollover_period(self):
        # Rollover is between 21:55 and 23:05 UTC
        assert is_rollover_period(21, 54) is False
        assert is_rollover_period(21, 55) is True
        assert is_rollover_period(22, 0) is True
        assert is_rollover_period(22, 30) is True
        assert is_rollover_period(23, 4) is True
        assert is_rollover_period(23, 6) is False
        assert is_rollover_period(14, 0) is False

    def test_get_active_sessions(self):
        assert "ASIA" in get_active_sessions(2)
        assert "LONDON" in get_active_sessions(8)
        assert "OVERLAP" in get_active_sessions(14)
        assert "NEW_YORK" in get_active_sessions(18)
        assert "OFF_HOURS" in get_active_sessions(22)

    def test_calculate_lot_size_forex(self):
        # 10 000€ compte, 1% risque = 100€
        # EURUSD: entry 1.1000, SL 1.0980 (20 pips = 0.0020)
        # 1 lot EURUSD = 100 000. 20 pips sur 1 lot = 200€.
        # Lots requis = 100€ / 200€ = 0.50 lots.
        lots = calculate_lot_size(
            account_balance=10000.0,
            risk_pct=1.0,
            entry_price=1.1000,
            sl_price=1.0980,
            contract_size=100000.0,
            tick_size=0.00001,
            tick_value=1.0,
            volume_min=0.01,
            volume_step=0.01,
            volume_max=100.0,
            symbol="EURUSD",
        )
        assert lots == 0.50

    def test_calculate_lot_size_gold(self):
        # 10 000$ compte, 1% risque = 100$
        # XAUUSD: entry 2500.00, SL 2490.00 (Distance = $10)
        # 1 lot XAUUSD = 100 oz. $10 move on 1 lot = $1000.
        # Lots requis = 100$ / 1000$ = 0.10 lots.
        lots = calculate_lot_size(
            account_balance=10000.0,
            risk_pct=1.0,
            entry_price=2500.00,
            sl_price=2490.00,
            contract_size=100.0,
            tick_size=0.01,
            tick_value=1.0,  # 0.01 * 100 oz = $1.00 per tick
            volume_min=0.01,
            volume_step=0.01,
            volume_max=100.0,
            symbol="XAUUSD",
        )
        assert lots == 0.10

    def test_calculate_lot_size_oil(self):
        # 10 000$ compte, 1% risque = 100$
        # XTIUSD (WTI): entry 80.00, SL 79.00 (Distance = $1.00)
        # 1 lot WTI = 1000 bbl. $1.00 move on 1 lot = $1000.
        # Lots requis = 100$ / 1000$ = 0.10 lots.
        lots = calculate_lot_size(
            account_balance=10000.0,
            risk_pct=1.0,
            entry_price=80.00,
            sl_price=79.00,
            contract_size=1000.0,
            tick_size=0.01,
            tick_value=10.0,  # 0.01 * 1000 bbl = $10.00 per tick
            volume_min=0.01,
            volume_step=0.01,
            volume_max=100.0,
            symbol="XTIUSD",
        )
        assert lots == 0.10

    def test_calculate_lot_size_edge_cases(self):
        # Solde négatif ou nul
        assert calculate_lot_size(0.0, 1.0, 1.1000, 1.0980) == 0.0
        assert calculate_lot_size(-1000.0, 1.0, 1.1000, 1.0980) == 0.0
        # Risque nul
        assert calculate_lot_size(10000.0, 0.0, 1.1000, 1.0980) == 0.0
        # Entry == SL
        assert calculate_lot_size(10000.0, 1.0, 1.1000, 1.1000) == 0.0
        # Risque tellement infime que lot < volume_min (ex: solde 10€, 1% risque = 0.10€ avec SL large)
        assert calculate_lot_size(10.0, 1.0, 1.1000, 1.0500, volume_min=0.01) == 0.0
