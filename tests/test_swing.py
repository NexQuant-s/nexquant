"""Pullback de tendance D1 et gestionnaire swing : signal, dimensionnement, idempotence, stops suiveurs, sorties."""

import json

import numpy as np
import pandas as pd
import pytest

from superbot import swing_runner as sr
from superbot.strategy import trend_pullback_d1 as strat


def make_bars(n=300, drift=0.0008):
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    close = 100 * (1 + drift) ** np.arange(n)
    return pd.DataFrame({"open": close, "high": close * 1.004, "low": close * 0.996, "close": close}, index=idx)


class FakeAd:
    def __init__(self, bars, now_offset_h=2.0, balance=1000.0):
        self.bars, self.balance, self.equity = bars, balance, balance
        self.now = bars.index[-1] + pd.Timedelta(days=1, hours=now_offset_h)
        self.pos, self.opened, self.closed, self.sl_calls, self.pnl = [], [], [], [], 7.5
        self.bid, self.ask = 129.0, 129.2
        self.vmin = 0.01

    def d1_bars(self, symbol, n=400): return self.bars
    def tick(self, symbol): return self.bid, self.ask, 0
    def server_now(self, symbol): return self.now
    def account(self): return self.balance, self.equity
    def positions(self, magic): return [dict(p) for p in self.pos]
    def spec(self, symbol): return dict(vmin=self.vmin, vstep=0.01, vmax=100.0, tick_size=0.1, tick_value=1.0, digits=1, stops_level_price=0.0)

    def open(self, symbol, side, lots, sl, magic, comment):
        self.opened.append((symbol, side, lots, sl, magic))
        self.pos.append(dict(symbol=symbol, ticket=900 + len(self.opened), side=side, lots=lots, price=self.ask, sl=sl, tp=0.0, magic=magic))
        return True, 900 + len(self.opened), self.ask, ""

    def set_sl(self, ticket, symbol, sl):
        self.sl_calls.append((ticket, round(sl, 1)))
        return True

    def close(self, symbol, pos):
        self.closed.append(symbol)
        self.pos = [p for p in self.pos if p["symbol"] != symbol]
        return True

    def closed_pnl(self, ticket): return self.pnl


@pytest.fixture
def cfg():
    return sr.SwingConfig(symbols=["US500"], risk_pct=0.5, max_positions=3, enabled=True)


@pytest.fixture
def signal(monkeypatch):
    monkeypatch.setattr(sr.strat, "evaluate", lambda bars, p=strat.DEFAULT_PARAMS: {"side": "LONG", "atr": 2.0, "close": 129.0})


# ── stratégie pure ──────────────────────────────────────────────────────────────
def test_strategy_signals_long_on_trend_pullback():
    df = make_bars()
    ema20 = strat._ema(df["close"], 20).iloc[-1]
    df.iloc[-1, df.columns.get_loc("low")] = ema20 * 0.99          # touche l'EMA20…
    df.iloc[-1, df.columns.get_loc("close")] = ema20 * 1.004       # …et reclôture au-dessus
    df.iloc[-1, df.columns.get_loc("open")] = ema20 * 1.01
    sig = strat.evaluate(df)
    assert sig and sig["side"] == "LONG" and sig["atr"] > 0


def test_strategy_no_signal_without_pullback_or_with_short_history():
    assert strat.evaluate(make_bars()) is None                   # tendance pure, aucun repli sur l'EMA20
    assert strat.evaluate(make_bars(n=100)) is None              # historique insuffisant


def test_trailing_stop_follows_extreme_and_never_retreats():
    since = pd.DataFrame({"high": [110.0, 130.0, 125.0], "low": [99.0, 108.0, 120.0]})
    assert strat.trailing_stop("LONG", 100.0, since, 2.0, 96.0) == 124.0     # 130 - 3 x 2
    assert strat.trailing_stop("LONG", 100.0, since, 2.0, 126.0) == 126.0    # ne recule jamais
    short = pd.DataFrame({"high": [101.0, 99.0], "low": [90.0, 80.0]})
    assert strat.trailing_stop("SHORT", 100.0, short, 2.0, 104.0) == 86.0    # 80 + 3 x 2


# ── gestionnaire ────────────────────────────────────────────────────────────────
def test_entry_sizes_risk_and_is_idempotent(tmp_path, cfg, signal):
    ad = FakeAd(make_bars())
    notes = []
    s = sr.run_once(ad, cfg, tmp_path / "state.json", notify=notes.append)
    assert s["opened"] == ["US500"] and len(ad.opened) == 1
    symbol, side, lots, sl, magic = ad.opened[0]
    # stop = 2 x ATR(2.0) = 4 -> 40 €/lot ; risque 5 € -> 0,125 lot -> 0,12
    assert (side, lots, magic) == ("LONG", 0.12, 20201) and sl == pytest.approx(129.2 - 4.0)
    assert notes and "US500" in notes[0]
    assert sr.run_once(ad, cfg, tmp_path / "state.json")["opened"] == [] and len(ad.opened) == 1   # même bougie : rien


def test_paused_stale_and_too_early_do_not_open(tmp_path, cfg, signal):
    bars = make_bars()
    ad = FakeAd(bars); sr.run_once(ad, cfg, tmp_path / "a.json", paused=True)
    assert ad.opened == []
    ad = FakeAd(bars, now_offset_h=10.0); sr.run_once(ad, cfg, tmp_path / "b.json")          # > 8 h : périmé
    assert ad.opened == [] and sr.load_state(tmp_path / "b.json")["processed"]["US500"]
    ad = FakeAd(bars, now_offset_h=0.3); sr.run_once(ad, cfg, tmp_path / "c.json")           # < 1 h : trop tôt
    assert ad.opened == [] and "US500" not in sr.load_state(tmp_path / "c.json")["processed"]


def test_position_cap_and_minimum_lot_risk_guard(tmp_path, cfg, signal):
    ad = FakeAd(make_bars())
    ad.pos = [dict(symbol=f"X{i}", ticket=i, side="LONG", lots=0.1, price=1, sl=0, tp=0, magic=20201) for i in range(3)]
    sr.run_once(ad, cfg, tmp_path / "a.json"); assert ad.opened == []                         # 3 positions déjà ouvertes
    ad = FakeAd(make_bars(), balance=100.0); ad.vmin = 1.0                                    # lot minimum = 40 € > 1 % de 100 €
    sr.run_once(ad, cfg, tmp_path / "b.json"); assert ad.opened == []


def _open_state(tmp_path, bars, signal_back=3, side="LONG", entry=100.0, atr=2.0, sl=96.0):
    state = {"positions": {"US500": {"ticket": 901, "side": side, "signal_date": str(bars.index[-1 - signal_back].date()),
                                     "entry_price": entry, "atr": atr, "sl": sl, "lots": 0.1}}, "processed": {}}
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")


def test_trailing_stop_is_moved_on_new_bar(tmp_path, cfg):
    bars = make_bars(); bars.iloc[-1, bars.columns.get_loc("high")] = 130.0
    ad = FakeAd(bars); ad.pos = [dict(symbol="US500", ticket=901, side="LONG", lots=0.1, price=100.0, sl=96.0, tp=0.0, magic=20201)]
    _open_state(tmp_path, bars)
    s = sr.run_once(ad, cfg, tmp_path / "state.json")
    assert s["trailed"] == ["US500"] and ad.sl_calls == [(901, 124.0)]
    assert sr.run_once(ad, cfg, tmp_path / "state.json")["trailed"] == []                     # même bougie : pas de doublon


def test_time_exit_after_max_bars(tmp_path, cfg):
    bars = make_bars()
    ad = FakeAd(bars); ad.pos = [dict(symbol="US500", ticket=901, side="LONG", lots=0.1, price=100.0, sl=96.0, tp=0.0, magic=20201)]
    _open_state(tmp_path, bars, signal_back=20)
    s = sr.run_once(ad, cfg, tmp_path / "state.json")
    assert s["closed"] == ["US500"] and ad.closed == ["US500"]
    rows = [json.loads(x) for x in (tmp_path / "swing_trades.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["close_reason"] == "time" and rows[0]["pnl"] == 7.5
    assert "US500" not in sr.load_state(tmp_path / "state.json")["positions"]


def test_position_closed_by_broker_stop_is_journaled(tmp_path, cfg):
    bars = make_bars(); ad = FakeAd(bars); ad.pnl = -4.9                                       # le broker n'a plus la position
    _open_state(tmp_path, bars)
    notes = []
    s = sr.run_once(ad, cfg, tmp_path / "state.json", notify=notes.append)
    assert s["closed"] == ["US500"] and "-4.9" in notes[0]
    assert json.loads((tmp_path / "swing_trades.jsonl").read_text(encoding="utf-8"))["close_reason"] == "stop"
