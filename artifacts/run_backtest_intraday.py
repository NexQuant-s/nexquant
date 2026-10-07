"""Backtest de bout en bout sur le timeframe de production (intraday).

Récupère l'historique 15m/1h via l'API publique Binance (aucune clé requise)
à travers le DataFetcher, puis rejoue la configuration de production sur ces
bougies et produit un rapport de performance.

Usage :
    python artifacts/run_backtest_intraday.py
"""

import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BACKTEST_MODE", "true")


# Sortie redirigée → fichier : forcer UTF-8 (sinon cp1252 plante sur « → »).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

for _name in ("strategy", "backtest.engine", "backtest.data_fetcher", "backtest.report", "root", "urllib3"):
    logging.getLogger(_name).setLevel(logging.WARNING)

import superbot.config as cfg
from superbot.backtest.engine import BacktestEngine
from superbot.backtest.report import BacktestReport, compare_walk_forward
from superbot.backtest.data_fetcher import DataFetcher
from superbot.strategy.strategy import TradingStrategy


# (symbole, timeframe, début, fin) — 15m = timeframe de production (1 an),
# 1h = validation plus longue (2 ans).
RUNS = [
    ("BTC/USDT", "15m", "2025-08-15", "2026-08-15"),
    ("ETH/USDT", "15m", "2025-08-15", "2026-08-15"),
    ("BTC/USDT", "1h",  "2024-08-15", "2026-08-15"),
    ("ETH/USDT", "1h",  "2024-08-15", "2026-08-15"),
]


def build_config(broker_type: str) -> dict:
    d = {k: getattr(cfg, k) for k in dir(cfg) if k.isupper()}
    d["BROKER_TYPE"] = broker_type
    return d


def run_one(fetcher: DataFetcher, symbol: str, timeframe: str, start: str, end: str):
    df = fetcher.fetch(symbol, timeframe, start=start, end=end)
    print(f"    {len(df)} bougies | {df.index[0]} → {df.index[-1]}")

    config = build_config("binance")
    strategy = TradingStrategy(config)
    engine = BacktestEngine(df, config, symbol=symbol, timeframe=timeframe, broker_type="binance")
    results = engine.run(strategy, warmup_bars=100)

    report = BacktestReport(results)
    report.print_summary()
    report.save_json()
    return results


def main() -> int:
    print("\n" + "#" * 72)
    print("#  NEXQUANT — BACKTEST INTRADAY (Binance public klines, 15m/1h)")
    print("#" * 72)

    fetcher = DataFetcher("binance")
    all_results = {}

    for symbol, timeframe, start, end in RUNS:
        label = f"{symbol} {timeframe}"
        print(f"\n{'=' * 72}\n>>> {label}  ({start} → {end})\n{'=' * 72}")
        print("    Téléchargement des données…")
        try:
            all_results[label] = run_one(fetcher, symbol, timeframe, start, end)
        except Exception as e:
            import traceback
            print(f"[ERREUR] {label}: {e}")
            traceback.print_exc()
            all_results[label] = None

    # Walk-forward sur le timeframe de production (sur-apprentissage ?)
    print("\n" + "=" * 72)
    print(">>> WALK-FORWARD BTC/USDT 15m (70% in-sample / 30% out-of-sample)")
    print("=" * 72)
    try:
        df_btc = fetcher.fetch("BTC/USDT", "15m", start="2025-08-15", end="2026-08-15")
        config = build_config("binance")
        engine = BacktestEngine(df_btc, config, symbol="BTC/USDT",
                                timeframe="15m", broker_type="binance")
        strategy = TradingStrategy(config)
        in_sample, out_sample = engine.run_walk_forward(strategy, train_ratio=0.7, warmup_bars=100)
        compare_walk_forward(in_sample, out_sample)
    except Exception as e:
        import traceback
        print(f"[ERREUR] walk-forward BTC 15m: {e}")
        traceback.print_exc()

    # Synthèse consolidée
    print("\n" + "=" * 72)
    print("  SYNTHÈSE")
    print("=" * 72)
    print(f"  {'Run':<18} {'Return':>9} {'MaxDD':>8} {'Sharpe':>8} {'WinRate':>8} {'PF':>6} {'Trades':>7}")
    print("-" * 72)
    for label, r in all_results.items():
        if r is None:
            print(f"  {label:<18} {'FAILED':>9}")
            continue
        print(
            f"  {label:<18} {r.total_return_pct:>+8.2f}% {r.max_drawdown_pct:>7.2f}% "
            f"{r.sharpe_ratio:>8.2f} {r.win_rate*100:>7.1f}% {r.profit_factor:>6.2f} {r.total_trades:>7}"
        )
    print("-" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
