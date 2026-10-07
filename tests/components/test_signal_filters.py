"""Tests du filtre d'épuisement et de l'objectif journalier en % du solde."""

import pandas as pd
import pytest

from superbot.components.signal_executor import _exhaustion_reason, is_exhausted_entry


@pytest.mark.parametrize("side,rsi,bb_pos,expected", [
    ("LONG", 74.0, 0.80, True),    # surachat RSI
    ("LONG", 60.0, 0.99, True),    # au-dessus de la bande haute
    ("LONG", 55.0, 0.60, False),
    ("SHORT", 25.0, 0.40, True),   # survente RSI
    ("SHORT", 45.0, 0.01, True),   # sous la bande basse
    ("SHORT", 45.0, 0.40, False),
    ("", 90.0, 1.20, False),       # pas de signal
])
def test_is_exhausted_entry(side, rsi, bb_pos, expected):
    assert is_exhausted_entry(side, rsi, bb_pos) is expected


def _bar(rsi, close, upper=1.12, lower=1.08):
    return pd.DataFrame([{"rsi": rsi, "close": close, "bb_upper": upper, "bb_lower": lower}])


def test_exhaustion_reason_rejects_long_at_top(monkeypatch):
    monkeypatch.setattr("superbot.config.ENTRY_EXHAUSTION_FILTER", True)
    reason = _exhaustion_reason({"should_long": True}, _bar(rsi=75.0, close=1.11))
    assert "épuisement" in reason


def test_exhaustion_reason_allows_long_pullback(monkeypatch):
    monkeypatch.setattr("superbot.config.ENTRY_EXHAUSTION_FILTER", True)
    assert _exhaustion_reason({"should_long": True}, _bar(rsi=52.0, close=1.10)) == ""


def test_exhaustion_filter_can_be_disabled(monkeypatch):
    monkeypatch.setattr("superbot.config.ENTRY_EXHAUSTION_FILTER", False)
    assert _exhaustion_reason({"should_long": True}, _bar(rsi=90.0, close=1.13)) == ""


def test_daily_target_is_percentage_of_balance(monkeypatch):
    from superbot.brain.session_manager import SessionManager

    monkeypatch.setattr("superbot.config.DAILY_TARGET_PCT", 2.0)
    sm = SessionManager(daily_target_eur=100.0)
    assert sm._compute_daily_target(950.0) == 19.0
    assert sm._compute_daily_target(0.0) == 0.0
