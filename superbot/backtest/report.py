"""
NexQuant BacktestReport — Phase 1
====================================
Génère et exporte les résultats de backtest en JSON et en rapport visuel terminal.

Usage :
    report = BacktestReport(results, symbol='BTCUSDT', timeframe='1h')
    report.print_summary()
    report.print_trades_breakdown()
    json_path = report.save_json('results/btcusdt_2024.json')
    report.plot_equity_curve()   # Nécessite matplotlib
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from superbot.backtest.engine import BacktestResults

log = logging.getLogger("backtest.report")

# Répertoire par défaut pour les résultats
RESULTS_DIR = Path(__file__).parent / "results"


class BacktestReport:
    """
    Génère des rapports de backtest lisibles depuis un objet BacktestResults.
    """

    REGIME_COLORS = {
        'TRENDING': '[TREND]',
        'RANGING':  '[RANGE]',
        'UNKNOWN':  '[?????]',
    }

    def __init__(self, results: BacktestResults):
        self.results = results

    # ─── Affichage terminal ───────────────────────────────────────────────────

    def print_summary(self):
        """Affiche le résumé principal dans le terminal."""
        print(self.results.summary())
        self._print_regime_breakdown()

    def print_trades_breakdown(self, max_trades: int = 20):
        """Affiche le journal des trades (les N derniers)."""
        trades = self.results.trades[-max_trades:]
        if not trades:
            print("[BacktestReport] Aucun trade à afficher.")
            return

        sep = "-" * 90
        header = f"{'#':<4} {'Dir':<6} {'Entrée':<22} {'Sortie':<22} {'PnL%':>7} {'Résultat':<12} {'Régime':<12} {'Score':>6}"
        print("\n  JOURNAL DES TRADES (derniers %d)" % len(trades))
        print(sep)
        print(header)
        print(sep)

        for idx, t in enumerate(trades, 1):
            entry_str = t.entry_time.strftime('%Y-%m-%d %H:%M') if t.entry_time else 'N/A'
            exit_str = t.exit_time.strftime('%Y-%m-%d %H:%M') if t.exit_time else 'N/A'
            emoji = '[WIN]' if t.pnl > 0 else '[LOSS]'
            print(
                f"{idx:<4} {t.direction:<6} {entry_str:<22} {exit_str:<22} "
                f"{t.pnl_pct:>+7.2f}% {emoji} {t.result:<10} {t.market_regime:<12} {t.score:>6.1f}"
            )
        print(sep)

    def print_monthly_breakdown(self):
        """Affiche la performance mois par mois."""
        if not self.results.trades:
            return

        monthly: dict = {}
        for t in self.results.trades:
            if t.exit_time:
                key = t.exit_time.strftime('%Y-%m')
                monthly.setdefault(key, []).append(t.pnl_pct)

        print("\n  PERFORMANCE MENSUELLE")
        print("-" * 40)
        for month in sorted(monthly.keys()):
            month_pnls = monthly[month]
            total = sum(month_pnls)
            wins = sum(1 for p in month_pnls if p > 0)
            tag = '[+]' if total > 0 else '[-]'
            print(f"  {month}  {tag}  {total:>+7.2f}%   ({wins}/{len(month_pnls)} gagnants)")
        print("-" * 40)

    def _print_regime_breakdown(self):
        """Affiche la performance par régime de marché."""
        if not self.results.trades:
            return

        regimes: dict = {}
        for t in self.results.trades:
            r = t.market_regime
            regimes.setdefault(r, {'trades': 0, 'wins': 0, 'total_pnl': 0.0})
            regimes[r]['trades'] += 1
            if t.pnl > 0:
                regimes[r]['wins'] += 1
            regimes[r]['total_pnl'] += t.pnl_pct

        print("\n  PERFORMANCE PAR RÉGIME")
        print("-" * 55)
        for regime, data in regimes.items():
            icon = self.REGIME_COLORS.get(regime, '⚪')
            wr = data['wins'] / data['trades'] * 100 if data['trades'] > 0 else 0
            print(
                f"  {icon} {regime:<12} : {data['trades']:>4} trades | "
                f"Win-rate: {wr:.0f}% | PnL total: {data['total_pnl']:>+8.2f}%"
            )
        print("-" * 55)

    # ─── Export JSON ──────────────────────────────────────────────────────────

    def save_json(self, path: Optional[str] = None) -> Path:
        """
        Sauvegarde les résultats complets en JSON.

        Args:
            path: Chemin du fichier de sortie. Si None, génère un nom automatique.

        Returns:
            Path du fichier créé.
        """
        if path is None:
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            # Sanitize le symbole : 'BTC/USDT' -> 'BTC-USDT' pour ne pas casser le chemin.
            safe_symbol = self.results.symbol.replace('/', '-')
            filename = f"backtest_{safe_symbol}_{self.results.timeframe}_{timestamp}.json"
            output_path = RESULTS_DIR / filename
        else:
            output_path = Path(path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

        data = self.results.to_dict()

        # Nettoyer les valeurs non-JSON-sérialisables
        data = self._sanitize_for_json(data)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        log.info(f"[BacktestReport] Résultats sauvegardés -> {output_path}")
        print(f"\n  [JSON] Rapport sauvegarde : {output_path}")
        return output_path

    @staticmethod
    def _sanitize_for_json(obj):
        """Convertit récursivement les types non-JSON-sérialisables."""
        import math as _math
        if isinstance(obj, dict):
            return {k: BacktestReport._sanitize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [BacktestReport._sanitize_for_json(i) for i in obj]
        elif isinstance(obj, float):
            if _math.isnan(obj) or _math.isinf(obj):
                return None
            return round(obj, 6)
        elif hasattr(obj, 'isoformat'):  # datetime
            return obj.isoformat()
        return obj

    # ─── Visualisation (optionnel) ────────────────────────────────────────────

    def plot_equity_curve(self, save_path: Optional[str] = None):
        """
        Trace la courbe d'équité avec le drawdown en surimpression.
        Nécessite matplotlib.

        Args:
            save_path: Si fourni, sauvegarde l'image au lieu de l'afficher.
        """
        try:
            import matplotlib.pyplot as plt
            import pandas as pd
        except ImportError:
            log.warning("[BacktestReport] matplotlib non installé. pip install matplotlib")
            return

        equity = pd.Series(self.results.equity_curve)
        rolling_max = equity.cummax()
        drawdown = (equity - rolling_max) / rolling_max * 100

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), gridspec_kw={'height_ratios': [3, 1]})
        fig.suptitle(
            f"NexQuant Backtest — {self.results.symbol} {self.results.timeframe}\n"
            f"{self.results.start_date} → {self.results.end_date} | "
            f"Return: {self.results.total_return_pct:+.2f}% | "
            f"Sharpe: {self.results.sharpe_ratio:.2f} | "
            f"Max DD: {self.results.max_drawdown_pct:.2f}%",
            fontsize=11, fontweight='bold'
        )

        # Courbe d'équité
        ax1.plot(equity.values, color='#00C853', linewidth=1.5, label='Équité')
        ax1.axhline(self.results.initial_balance, color='gray', linestyle='--', alpha=0.5, label='Capital initial')
        ax1.fill_between(range(len(equity)), equity.values, self.results.initial_balance,
                         where=equity.values >= self.results.initial_balance,
                         alpha=0.15, color='#00C853')
        ax1.fill_between(range(len(equity)), equity.values, self.results.initial_balance,
                         where=equity.values < self.results.initial_balance,
                         alpha=0.15, color='#F44336')

        ax1.set_ylabel("Capital ($)", fontsize=10)
        ax1.legend(loc='upper left', fontsize=9)
        ax1.grid(True, alpha=0.3)
        ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'${x:,.0f}'))

        # Drawdown
        ax2.fill_between(range(len(drawdown)), drawdown.values, 0, alpha=0.6, color='#F44336')
        ax2.set_ylabel("Drawdown (%)", fontsize=10)
        ax2.set_xlabel("Bougies", fontsize=10)
        ax2.grid(True, alpha=0.3)
        ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f'{x:.1f}%'))

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            log.info(f"[BacktestReport] Graphique sauvegardé → {save_path}")
            print(f"  [IMG] Graphique sauvegarde : {save_path}")
        else:
            plt.show()

        plt.close(fig)


def compare_walk_forward(
    in_sample: BacktestResults,
    out_sample: BacktestResults,
):
    """
    Compare et affiche les résultats In-Sample vs Out-of-Sample.
    Permet de détecter le sur-apprentissage.
    """
    sep = "=" * 70
    print(f"\n{sep}")
    print("  ANALYSE WALK-FORWARD — Comparaison In-Sample vs Out-of-Sample")
    print(sep)

    metrics = [
        ("Rendement total (%)",  "total_return_pct",  "{:+.2f}%"),
        ("Max Drawdown (%)",     "max_drawdown_pct",   "{:.2f}%"),
        ("Ratio de Sharpe",      "sharpe_ratio",       "{:.3f}"),
        ("Ratio de Sortino",     "sortino_ratio",      "{:.3f}"),
        ("Win Rate",             "win_rate",           "{:.1%}"),
        ("Profit Factor",        "profit_factor",      "{:.2f}"),
        ("Nombre de trades",     "total_trades",       "{:d}"),
    ]

    header = f"  {'Métrique':<28} {'In-Sample':>16} {'Out-of-Sample':>18}"
    print(header)
    print("-" * 70)

    for label, attr, fmt in metrics:
        is_val = getattr(in_sample, attr, 0)
        oos_val = getattr(out_sample, attr, 0)
        is_str = fmt.format(is_val)
        oos_str = fmt.format(oos_val)

        # Indicateur de dégradation
        if attr == 'total_return_pct' and oos_val < is_val * 0.5:
            flag = "  ⚠️  (dégradation)"
        elif attr == 'max_drawdown_pct' and oos_val > is_val * 1.5:
            flag = "  ⚠️  (risque accru)"
        else:
            flag = ""

        print(f"  {label:<28} {is_str:>16} {oos_str:>18}{flag}")

    print(sep)

    # Diagnostic global de sur-apprentissage.
    # Le ratio OOS/IS n'a de sens que si l'In-Sample est positif ; sinon on
    # compare directement les rendements (OOS meilleur ou moins mauvais = pas de dégradation).
    if in_sample.total_return_pct > 0:
        oos_is_ratio = out_sample.total_return_pct / in_sample.total_return_pct
        if oos_is_ratio >= 0.7:
            print("  [OK]  Strategie robuste -- Out-of-Sample >= 70% des performances In-Sample")
        elif oos_is_ratio >= 0.4:
            print("  [~~]  Strategie acceptable -- legere degradation Out-of-Sample (normal)")
        else:
            print("  [!!]  Risque de sur-apprentissage -- forte degradation Out-of-Sample")
    elif out_sample.total_return_pct >= in_sample.total_return_pct:
        print("  [OK]  Pas de degradation Out-of-Sample (In-Sample negatif, OOS meilleur ou equivalent)")
    else:
        print("  [!!]  Out-of-Sample encore plus degrade qu'un In-Sample deja negatif")
    print(sep + "\n")
