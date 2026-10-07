"""Les SL/TP live doivent suivre SL_ATR_MULT / TP_ATR_MULT configurés (ratios de régime)."""

from superbot.risk.risk_manager import RiskManager


def test_default_base_keeps_historical_values():
    m = RiskManager.get_regime_sl_tp_multipliers("ranging", "LONDON", "forex")
    assert m == {"sl_atr_mult": 1.2, "tp_atr_mult": 1.8}
    m = RiskManager.get_regime_sl_tp_multipliers("breakout", "LONDON", "forex")
    assert m == {"sl_atr_mult": 1.8, "tp_atr_mult": 3.6}


def test_configured_multipliers_are_applied_to_orders():
    rm = RiskManager({"SL_ATR_MULT": 2.0, "TP_ATR_MULT": 4.0})
    sl, tp = rm.calculate_sl_tp_levels(entry_price=1.1000, atr_value=0.0020, position_side="LONG",
                                       asset_type="forex", symbol="EURUSD", hmm_regime="trending_bull")
    assert abs((1.1000 - sl) - 2.0 * 0.0020) < 1e-9
    assert abs((tp - 1.1000) - 4.0 * 0.0020) < 1e-9
