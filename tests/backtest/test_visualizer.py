import json

from scripts.backtest_visualizer import build_analysis_payload, load_backtest_results, main


def _native_report(score_min, equity, return_pct):
    return {
        "symbol": "EURUSD",
        "timeframe": "15m",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "initial_balance": 10000,
        "final_balance": equity[-1],
        "total_return_pct": return_pct,
        "max_drawdown_pct": 2,
        "sharpe_ratio": 1.2,
        "sortino_ratio": 1.5,
        "calmar_ratio": 2,
        "profit_factor": 1.6,
        "total_trades": 2,
        "winning_trades": 1,
        "losing_trades": 1,
        "win_rate": 0.5,
        "equity_curve": equity,
        "params_used": {"SCORE_MIN": score_min},
        "trades": [
            {
                "entry_time": "2026-01-02T10:00:00",
                "exit_time": "2026-01-02T11:30:00",
                "pnl": 100,
                "pnl_pct": 1,
                "direction": "LONG",
                "market_regime": "trend",
            },
            {
                "entry_time": "2026-01-03T10:00:00",
                "exit_time": "2026-01-03T12:00:00",
                "pnl": -50,
                "pnl_pct": -0.5,
                "direction": "SHORT",
                "market_regime": "range",
            },
        ],
    }


def test_loads_native_backtest_report_and_computes_risk(tmp_path):
    path = tmp_path / "native.json"
    path.write_text(json.dumps(_native_report(5, [10000, 10100, 10050], 0.5)), encoding="utf-8")

    result = load_backtest_results(str(path))

    assert result["metadata"]["symbol"] == "EURUSD"
    assert result["metrics"]["win_rate"] == 50
    assert result["trades"][0]["duration_minutes"] == 90
    assert result["drawdown_curve"][-1] < 0
    assert result["risk"]["var_95"] == -0.425
    assert result["risk"]["expected_shortfall_95"] == -0.5
    assert result["risk"]["max_loss_streak"] == 1


def test_normalizes_legacy_nested_fixture():
    result = load_backtest_results("scripts/test_backtest_data.json")

    assert result["metadata"]["symbol"] == "BTCUSDT"
    assert result["metrics"]["total_return_pct"] == 5
    assert result["metrics"]["win_rate"] == 60
    assert result["stats"]["total_trades"] == 20
    assert result["monthly_returns"]["2024-01"] == 2.0


def test_builds_parameter_comparison_and_cli_html(tmp_path):
    first_path = tmp_path / "baseline.json"
    second_path = tmp_path / "optimized.json"
    first_path.write_text(json.dumps(_native_report(5, [10000, 10200, 10400], 4)), encoding="utf-8")
    second_path.write_text(json.dumps(_native_report(7, [10000, 10400, 10800], 8)), encoding="utf-8")
    results = [load_backtest_results(str(first_path)), load_backtest_results(str(second_path))]
    payload = build_analysis_payload(results, ["SCORE_MIN"])

    assert payload["comparison"]["matrix"][0][1] == 1
    assert payload["optimization"]["best"]["value"] == 7
    assert payload["optimization"]["best"]["return"] == 8

    output_path = tmp_path / "report.html"
    assert main([
        "--input", str(first_path), str(second_path), "--compare",
        "--optimize", "SCORE_MIN", "--walk-forward", "--output", str(output_path),
    ]) == 0
    html = output_path.read_text(encoding="utf-8")
    assert "Courbes d’équité" in html
    assert "Corrélation des rendements" in html
    assert "Meilleur rendement observé" in html
    assert "Walk-forward : In-Sample / Out-of-Sample" in html