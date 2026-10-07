"""Régressions du dashboard legacy et des vues analytics."""

import json
import io
from http.server import ThreadingHTTPServer

from superbot.dashboard.dashboard import (
    DashboardServer,
    DashboardHandler,
    _is_displayable_closed_trade,
    load_global_trades,
)


def test_ghost_cleanup_is_not_a_closed_trade():
    ghost = {
        "symbol": "EURUSD",
        "status": "closed",
        "close_reason": "GHOST_CLEANUP",
        "entry_price": 50000.0,
        "pnl": None,
    }
    assert not _is_displayable_closed_trade(ghost)


def test_closed_trade_requires_real_exit_and_pnl():
    incomplete = {
        "symbol": "EURUSD",
        "status": "closed",
        "entry_price": 1.1,
        "pnl": None,
    }
    valid = {
        "symbol": "EURUSD",
        "status": "closed",
        "entry_price": 1.1,
        "exit_price": 1.105,
        "pnl": 50.0,
    }
    assert not _is_displayable_closed_trade(incomplete)
    assert _is_displayable_closed_trade(valid)


def test_dashboard_uses_threaded_http_server():
    server = DashboardServer(host="127.0.0.1", port=0)
    server.start()
    try:
        assert isinstance(server.server, ThreadingHTTPServer)
    finally:
        server.stop()


def test_performance_data_uses_closed_trade_history():
    handler = DashboardHandler.__new__(DashboardHandler)
    handler.dashboard_data_func = None
    raw_data = {
        "account": {"initial_balance": 10000},
        "global_history": [
            {"status": "closed", "pnl": 100, "pnl_pct": 1, "timestamp": "2026-01-02T12:00:00Z"},
            {"status": "closed", "pnl": -50, "pnl_pct": -0.5, "timestamp": "2026-02-02T12:00:00Z"},
            {"status": "open", "pnl": 500},
        ],
    }

    data = handler._prepare_performance_data(raw_data)

    assert data["equity_curve"] == [10000, 10100, 10050]
    assert data["drawdown_curve"][-1] < 0
    assert data["metrics"]["total_trades"] == 2
    assert data["metrics"]["win_rate"] == 50
    assert data["monthly_returns"] == {"2026-01": 1, "2026-02": -0.5}


def test_trade_data_includes_duration_and_price_fields():
    handler = DashboardHandler.__new__(DashboardHandler)
    handler.dashboard_data_func = None
    raw_data = {"trades": [{
        "status": "closed",
        "symbol": "EURUSD",
        "direction": "LONG",
        "entry_time": "2026-01-02T10:00:00",
        "exit_time": "2026-01-02T12:30:00",
        "entry_price": 1.1,
        "exit_price": 1.105,
        "pnl": 25,
    }]}

    data = handler._prepare_trades_data(raw_data)

    trade = data["trades"][0]
    assert trade["side"] == "LONG"
    assert trade["duration_seconds"] == 9000
    assert trade["entry_price"] == 1.1
    assert data["stats"]["total_pnl"] == 25


def test_comparison_and_parameter_sensitivity_load_saved_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKTEST_RESULTS_DIR", str(tmp_path))
    for name, score_min, total_return, equity, monthly_returns in (
        ("baseline", 5, 4.0, [10000, 10200, 10400], [1, 3]),
        ("optimized", 7, 8.0, [10000, 10400, 10800], [2, 6]),
    ):
        with (tmp_path / f"{name}.json").open("w", encoding="utf-8") as report_file:
            json.dump({
                "symbol": "EURUSD",
                "total_return_pct": total_return,
                "max_drawdown_pct": 2,
                "sharpe_ratio": 1.2,
                "win_rate": 60,
                "profit_factor": 1.5,
                "total_trades": 10,
                "equity_curve": equity,
                "params_used": {"SCORE_MIN": score_min},
                "trades": [
                    {"exit_time": "2026-01-15T12:00:00Z", "pnl_pct": monthly_returns[0]},
                    {"exit_time": "2026-02-15T12:00:00Z", "pnl_pct": monthly_returns[1]},
                ],
            }, report_file)

    handler = DashboardHandler.__new__(DashboardHandler)
    handler.dashboard_data_func = None
    comparison = handler._prepare_compare_data()
    optimization = handler._prepare_optimize_data()

    assert comparison["comparison_available"]
    assert comparison["strategies"][1]["total_return"] == 8
    assert comparison["correlation"]["matrix"][0][1] == 1
    assert comparison["period_returns"][0]["data"] == [
        {"x": "2026-01", "y": 1}, {"x": "2026-02", "y": 3}
    ]
    assert optimization["available"]
    assert optimization["best_result"]["value"] == 7
    assert optimization["best_result"]["return"] == 8


def test_comparison_api_is_available_without_live_dashboard_data(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKTEST_RESULTS_DIR", str(tmp_path))
    handler = DashboardHandler.__new__(DashboardHandler)
    handler.dashboard_data_func = None
    handler.wfile = io.BytesIO()
    response = {}
    handler.send_response = lambda status: response.update(status=status)
    handler.send_header = lambda *_args: None
    handler.end_headers = lambda: None

    handler._serve_api_compare_data()

    assert response["status"] == 200
    payload = json.loads(handler.wfile.getvalue())
    assert not payload["comparison_available"]
    assert "deux rapports" in payload["message"]


def test_advanced_dashboard_pages_and_navigation_are_generated():
    handler = DashboardHandler.__new__(DashboardHandler)
    for page in (
        handler._generate_performance_html(),
        handler._generate_trades_html(),
        handler._generate_compare_html(),
        handler._generate_optimize_html(),
    ):
        assert '<html lang="fr">' in page
        assert "@media (max-width: 800px)" in page
    assert ".grid-2 > *, .card, .chart-container" in handler._generate_trades_html()

    dashboard = handler._generate_dashboard_html()
    assert "window.location.href='/performance'" in dashboard
    assert "window.location.href='/optimize'" in dashboard


def test_trade_charts_include_all_pairs_and_follow_pair_filter():
    handler = DashboardHandler.__new__(DashboardHandler)
    page = handler._generate_trades_html()

    assert "type: 'bar'" in page
    assert "horizontal: true" in page
    assert "updatePriceChart(chartTrades, priceSymbol)" in page
    assert "chart: { type: 'line'" in page
    assert "chart: { type: 'scatter'" not in page


def test_optimization_empty_state_hides_analytics_controls():
    handler = DashboardHandler.__new__(DashboardHandler)
    page = handler._generate_optimize_html()

    assert 'id="optimize-results" hidden' in page
    assert "resultsRoot.hidden = false" in page


def test_optimization_ignores_categorical_params_without_sweep(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKTEST_RESULTS_DIR", str(tmp_path))
    for name, strategy in (("first", "trend"), ("second", "reversion")):
        (tmp_path / f"{name}.json").write_text(json.dumps({
            "total_return_pct": 2,
            "params_used": {"STRATEGY_NAME": strategy},
        }), encoding="utf-8")

    handler = DashboardHandler.__new__(DashboardHandler)
    handler.dashboard_data_func = None
    data = handler._prepare_optimize_data()

    assert not data["available"]
    assert data["parameters"] == []


def test_optimization_keeps_walk_forward_without_parameter_sweep(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKTEST_RESULTS_DIR", str(tmp_path))
    (tmp_path / "walk-forward.json").write_text(json.dumps({
        "total_return_pct": 4,
        "walk_forward": {
            "in_sample": {"total_return_pct": 5},
            "out_sample": {"total_return_pct": 3},
        },
    }), encoding="utf-8")

    handler = DashboardHandler.__new__(DashboardHandler)
    handler.dashboard_data_func = None
    data = handler._prepare_optimize_data()

    assert data["available"]
    assert not data["parameter_available"]
    assert data["walk_forward"][0]["out_sample"]["total_return_pct"] == 3


def test_strategy_correlation_aligns_shared_calendar_months(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKTEST_RESULTS_DIR", str(tmp_path))
    reports = (
        ("first", [100, 110, 90, 120], [1, 2, 4, 3], ["2026-01", "2026-02", "2026-03", "2026-04"]),
        ("second", [500, 350, 600, 580], [4, 8, 6, 2], ["2026-02", "2026-03", "2026-04", "2026-05"]),
    )
    for name, equity, monthly_returns, months in reports:
        (tmp_path / f"{name}.json").write_text(json.dumps({
            "total_return_pct": 4,
            "equity_curve": equity,
            "trades": [
                {"exit_time": f"{month}-15T12:00:00Z", "pnl_pct": value}
                for month, value in zip(months, monthly_returns, strict=True)
            ],
            "params_used": {"SCORE_MIN": 5 if name == "first" else 7},
        }), encoding="utf-8")

    handler = DashboardHandler.__new__(DashboardHandler)
    comparison = handler._prepare_compare_data()

    assert abs(comparison["correlation"]["matrix"][0][1] - 1.0) < 1e-9


def _closed(pid, pnl, **extra):
    return {"position_id": pid, "symbol": "EURUSD", "side": "LONG", "status": "closed",
            "entry_price": 1.1, "exit_price": 1.101, "pnl": pnl,
            "timestamp": "2026-10-01T10:00:00+00:00", **extra}


def _write_journal(folder, rows):
    lines = [json.dumps(r) for r in rows]
    (folder / "trades_mt5.jsonl").write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def test_load_global_trades_reads_configured_log_dir_and_dedupes(tmp_path, monkeypatch):
    monkeypatch.setattr("superbot.config.LOG_DIR", tmp_path)
    rows = [_closed(1, 10.0), _closed(1, 10.0), _closed(2, -4.0)]
    _write_journal(tmp_path, rows)

    closed, active = load_global_trades()

    assert sorted(t["position_id"] for t in closed) == [1, 2]
    assert active == []


def _serve_api_data(raw):
    handler = DashboardHandler.__new__(DashboardHandler)
    handler.dashboard_data_func = lambda: raw
    handler.wfile = io.BytesIO()
    handler.send_response = lambda status: None
    handler.send_header = lambda *_args: None
    handler.end_headers = lambda: None
    handler._serve_api_data()
    return json.loads(handler.wfile.getvalue())


def test_api_data_win_rate_from_history_and_no_fake_balance(tmp_path, monkeypatch):
    monkeypatch.setattr("superbot.config.LOG_DIR", tmp_path)
    rows = [_closed(1, 10.0), _closed(2, 5.0), _closed(3, -5.0), _closed(4, -2.5)]
    _write_journal(tmp_path, rows)

    perf = _serve_api_data({"stats": {}, "account": {}})["performance"]

    assert perf["win_rate"] == 0.5
    assert perf["profit_factor"] == 2.0
    assert perf["initial_balance"] is None and perf["current_balance"] is None


def test_performance_initial_capital_derived_from_balance():
    handler = DashboardHandler.__new__(DashboardHandler)
    handler.dashboard_data_func = None
    raw_data = {
        "account": {"balance": 950, "initial_balance": 940},
        "global_history": [
            {"status": "closed", "pnl": 100, "timestamp": "2026-01-02T12:00:00Z"},
            {"status": "closed", "pnl": -50, "timestamp": "2026-02-02T12:00:00Z"},
        ],
    }
    data = handler._prepare_performance_data(raw_data)
    assert data["equity_curve"] == [900, 1000, 950]


def test_trade_duration_uses_open_time():
    handler = DashboardHandler.__new__(DashboardHandler)
    handler.dashboard_data_func = None
    trade = _closed(7, 3.0, open_time="2026-10-01T09:00:00+00:00", exit_time="2026-10-01T10:00:00+00:00")
    data = handler._prepare_trades_data({"trades": [trade]})
    assert data["trades"][0]["duration_seconds"] == 3600


def test_dashboard_escapes_external_text():
    page = DashboardHandler.__new__(DashboardHandler)._generate_dashboard_html()
    assert "String(text ?? '')" in page and "&quot;" in page
    for raw in ("${ev.currency", "${ev.source", "${s.reason", "${d2.reason", "${t.symbol}", "${sym}"):
        assert raw not in page
