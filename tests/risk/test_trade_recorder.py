"""Tests de la réconciliation du journal des trades avec l'historique broker."""

import json
from datetime import datetime, timezone

from superbot.risk.risk_manager import RiskManager
from superbot.risk.modules.trade_recorder import dedupe_trade_rows, merge_broker_history


def _bot_row(**kw):
    row = {"symbol": "XAUUSD", "side": "sell", "entry_price": 4342.34, "exit_price": 4336.2,
           "pnl": 5.83, "timestamp": "2026-09-23T06:00:42.432592+00:00", "status": "closed", "rsi": 41.0}
    row.update(kw)
    return row


def _broker_trade(**kw):
    trade = {"symbol": "XAUUSD", "side": "sell", "entry_price": 4342.34, "exit_price": 4336.75,
             "pnl": 4.89, "timestamp": datetime(2026, 9, 23, 6, 0, 42, tzinfo=timezone.utc),
             "position_id": 101, "ticket": 501, "close_reason": "tp"}
    trade.update(kw)
    return trade


def test_broker_trade_enriches_bot_row_instead_of_duplicating():
    rows = dedupe_trade_rows([_bot_row()], [_broker_trade()])
    assert len(rows) == 1
    row = rows[0]
    assert row["pnl"] == 4.89            # vérité broker
    assert row["rsi"] == 41.0            # features ML conservées
    assert row["position_id"] == 101
    assert row["verified"] is True
    assert row["close_reason"] == "tp"


def test_same_position_merged_twice_stays_single_row():
    rows = dedupe_trade_rows([_bot_row()], [_broker_trade()])
    rows = dedupe_trade_rows(rows, [_broker_trade(pnl=4.9)])
    assert len(rows) == 1
    assert rows[0]["pnl"] == 4.9


def test_legacy_duplicates_are_collapsed():
    # Ancienne ligne broker horodatée en heure serveur (+3h) + ligne bot du même trade
    legacy_broker = {"symbol": "XAUUSD", "side": "sell", "entry_price": 4342.34, "exit_price": 4336.75,
                     "pnl": 4.89, "timestamp": "2026-09-23T09:00:42+00:00", "position_id": 101, "status": "closed"}
    rows = dedupe_trade_rows([_bot_row(), legacy_broker], [])
    assert len(rows) == 1
    assert rows[0]["pnl"] == 4.89
    assert rows[0]["rsi"] == 41.0


def test_different_trades_are_not_merged():
    other = _bot_row(side="buy", entry_price=4123.30, timestamp="2026-10-06T09:51:57+00:00")
    rows = dedupe_trade_rows([_bot_row(), other], [_broker_trade()])
    assert len(rows) == 2
    assert next(r for r in rows if r["side"] == "buy").get("verified") is None


def test_unknown_broker_trade_is_appended():
    rows = dedupe_trade_rows([], [_broker_trade()])
    assert len(rows) == 1
    assert rows[0]["symbol"] == "XAUUSD"
    assert rows[0]["timestamp"] == "2026-09-23T06:00:42+00:00"


def test_merge_never_truncates_the_journal(tmp_path, monkeypatch):
    journal = tmp_path / "trades.jsonl"
    old_rows = [_bot_row(entry_price=1000.0 + i, timestamp=f"2026-08-01T00:{i % 60:02d}:00+00:00")
                for i in range(600)]
    journal.write_text("".join(json.dumps(r) + "\n" for r in old_rows), encoding="utf-8")
    monkeypatch.setattr("superbot.config.TRADE_LOG_FILE", str(journal))

    rm = RiskManager({})
    merge_broker_history(rm, [_broker_trade()])

    lines = journal.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 601                  # tout l'historique est conservé
    assert len(rm.trade_history) == 500       # seule la mémoire est bornée
