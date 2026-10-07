import os
import sys
import json
import argparse
import glob
import math
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NexQuant - Analyse de Backtest</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/apexcharts"></script>
    <style>
        :root {
            --bg: #070913;
            --surface: #0a0e1a;
            --card: rgba(16, 22, 41, 0.75);
            --border: #1e293b;
            --txt: #f3f4f6;
            --txt-secondary: #9ca3af;
            --accent-cyan: #06b6d4;
            --accent-blue: #3b82f6;
            --accent-purple: #8b5cf6;
            --green: #10b981;
            --red: #ef4444;
            --amber: #f59e0b;
            --radius-lg: 12px;
            --radius-md: 8px;
            --radius-sm: 4px;
        }
        body {
            background-color: var(--bg);
            color: var(--txt);
            font-family: 'Plus Jakarta Sans', sans-serif;
            margin: 0;
            padding: 20px;
        }
        h1, h2, h3, h4 { font-family: 'Outfit', sans-serif; }
        .data-text { font-family: 'JetBrains Mono', monospace; }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border);
        }
        
        .grid-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            padding: 20px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }
        
        .card-title {
            color: var(--txt-secondary);
            font-size: 0.875rem;
            margin-bottom: 10px;
            font-weight: 500;
        }
        
        .card-value {
            font-size: 1.5rem;
            font-weight: 700;
            font-family: 'Outfit', sans-serif;
        }
        
        .positive { color: var(--green); }
        .negative { color: var(--red); }
        
        .chart-container {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            padding: 20px;
            margin-bottom: 30px;
        }
        
        .chart-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 30px;
        }
        @media (max-width: 760px) {
            body { padding: 12px; }
            .header { align-items: flex-start; flex-direction: column; }
            .chart-grid { grid-template-columns: 1fr; gap: 12px; }
            .grid-cards { grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 10px; }
            .chart-container, .card { padding: 14px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>NexQuant SuperBot - Rapport de Backtest</h1>
                <p style="color: var(--txt-secondary)">Symbole: <span id="lbl-symbol" class="data-text"></span> | Période: <span id="lbl-period" class="data-text"></span></p>
            </div>
        </div>

        <h2>Résumé des Performances</h2>
        <div class="grid-cards">
            <div class="card">
                <div class="card-title">Rendement Total</div>
                <div id="val-return" class="card-value data-text"></div>
            </div>
            <div class="card">
                <div class="card-title">Max Drawdown</div>
                <div id="val-dd" class="card-value data-text negative"></div>
            </div>
            <div class="card">
                <div class="card-title">Ratio de Sharpe</div>
                <div id="val-sharpe" class="card-value data-text"></div>
            </div>
            <div class="card">
                <div class="card-title">Win Rate</div>
                <div id="val-winrate" class="card-value data-text"></div>
            </div>
            <div class="card">
                <div class="card-title">Facteur de Profit</div>
                <div id="val-profit-factor" class="card-value data-text"></div>
            </div>
            <div class="card">
                <div class="card-title">Total Trades</div>
                <div id="val-trades" class="card-value data-text"></div>
            </div>
        </div>

        <div class="chart-container">
            <h2>Courbe d'Équité & Drawdown</h2>
            <div id="chart-equity"></div>
        </div>

        <div class="chart-grid">
            <div class="chart-container">
                <h2>Distribution des P&L</h2>
                <div id="chart-pnl-dist"></div>
            </div>
            <div class="chart-container">
                <h2>Trades par Régime de Marché</h2>
                <div id="chart-regimes"></div>
            </div>
        </div>
    </div>

    <script>
        const rawData = {{REPLACE_JSON_DATA}};
        
        // Populate header
        document.getElementById('lbl-symbol').innerText = rawData.metadata.symbol + ' (' + rawData.metadata.timeframe + ')';
        document.getElementById('lbl-period').innerText = rawData.metadata.start_date + ' au ' + rawData.metadata.end_date;
        
        // Format numbers
        const formatPct = (val) => (val > 0 ? '+' : '') + val.toFixed(2) + '%';
        const formatNum = (val) => val.toFixed(2);
        
        // Populate cards
        const ret = rawData.metrics.total_return_pct;
        const retEl = document.getElementById('val-return');
        retEl.innerText = formatPct(ret);
        retEl.classList.add(ret > 0 ? 'positive' : 'negative');
        
        document.getElementById('val-dd').innerText = formatPct(-Math.abs(rawData.metrics.max_drawdown_pct));
        document.getElementById('val-sharpe').innerText = formatNum(rawData.metrics.sharpe_ratio);
        document.getElementById('val-winrate').innerText = rawData.metrics.win_rate.toFixed(1) + '%';
        document.getElementById('val-profit-factor').innerText = formatNum(rawData.metrics.profit_factor);
        document.getElementById('val-trades').innerText = rawData.stats.total_trades;

        // Common Chart Options
        const commonOptions = {
            chart: {
                foreColor: '#9ca3af',
                toolbar: { show: false },
                background: 'transparent',
                animations: { enabled: false }
            },
            theme: { mode: 'dark' },
            grid: { borderColor: '#1e293b' },
            tooltip: { theme: 'dark' }
        };

        // Equity Curve
        const equityOptions = {
            ...commonOptions,
            series: [{
                name: 'Équité',
                data: rawData.equity_curve
            }],
            chart: { type: 'area', height: 400 },
            colors: ['#06b6d4'],
            fill: {
                type: 'gradient',
                gradient: { shadeIntensity: 1, opacityFrom: 0.4, opacityTo: 0.05, stops: [0, 100] }
            },
            dataLabels: { enabled: false },
            stroke: { curve: 'straight', width: 2 },
            xaxis: { labels: { show: false }, tooltip: { enabled: false } },
            yaxis: { title: { text: 'Balance' } }
        };
        new ApexCharts(document.querySelector("#chart-equity"), equityOptions).render();

        // PNL Distribution
        const pnlData = rawData.trades.map(t => t.pnl_pct);
        const pnlOptions = {
            ...commonOptions,
            series: [{
                name: 'P&L %',
                data: pnlData
            }],
            chart: { type: 'histogram', height: 300 },
            colors: ['#3b82f6'],
            plotOptions: { bar: { borderRadius: 2 } },
            dataLabels: { enabled: false }
        };
        if(pnlData.length > 0 && ApexCharts.exec !== undefined) {
             // simplified for generic array
             const scatterOptions = {
                 ...commonOptions,
                 series: [{ name: 'P&L', data: rawData.trades.map((t, i) => [i, t.pnl_pct]) }],
                 chart: { type: 'scatter', height: 300 },
                 colors: ['#8b5cf6'],
                 xaxis: { title: { text: 'Trade' } }
             };
             new ApexCharts(document.querySelector("#chart-pnl-dist"), scatterOptions).render();
        }

        // Regimes (Donut)
        const regimes = {};
        rawData.trades.forEach(t => {
            regimes[t.market_regime] = (regimes[t.market_regime] || 0) + 1;
        });
        const regimeOptions = {
            ...commonOptions,
            series: Object.values(regimes),
            labels: Object.keys(regimes),
            chart: { type: 'donut', height: 300 },
            colors: ['#06b6d4', '#3b82f6', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444']
        };
        new ApexCharts(document.querySelector("#chart-regimes"), regimeOptions).render();
        
    </script>
</body>
</html>
"""

ANALYTICS_TEMPLATE = r"""
<section class="chart-container">
  <h2>Risque et rendements mensuels</h2>
  <div class="grid-cards" id="risk-cards"></div>
  <div class="chart-grid">
    <div><h3>Drawdown</h3><div id="chart-drawdown"></div></div>
    <div><h3>Rendements mensuels</h3><div id="chart-monthly"></div></div>
    <div><h3>Métriques roulantes (20 trades)</h3><div id="chart-rolling"></div></div>
    <div><h3>Durée des trades</h3><div id="chart-duration"></div></div>
  </div>
</section>
<section class="chart-container" id="comparison-panel" hidden>
  <h2>Comparaison des backtests</h2>
  <div id="comparison-table"></div>
  <div id="chart-comparison"></div>
  <div id="chart-correlation"></div>
</section>
<section class="chart-container" id="walk-forward-panel" hidden>
    <h2>Walk-forward : In-Sample / Out-of-Sample</h2>
    <div id="walk-forward-table"></div>
</section>
<section class="chart-container" id="optimization-panel" hidden>
  <h2>Sensibilité des paramètres</h2>
  <div id="optimization-summary"></div>
  <div id="chart-optimization"></div>
  <div id="chart-optimization-heatmap"></div>
</section>
<script>
  const analysisData = {{REPLACE_ANALYTICS_DATA}};
  const primary = analysisData.results[0];
  const metrics = primary.metrics;
  const risk = primary.risk;
    const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const base = { chart: { foreColor: '#9ca3af', background: 'transparent', toolbar: { show: false } }, theme: { mode: 'dark' }, grid: { borderColor: '#1e293b' }, tooltip: { theme: 'dark' } };
  const cards = [
    ['VaR 95%', `${risk.var_95.toFixed(2)}%`], ['Expected Shortfall 95%', `${risk.expected_shortfall_95.toFixed(2)}%`],
    ['Tail Ratio', risk.tail_ratio == null ? 'n/a' : risk.tail_ratio.toFixed(2)],
    ['Recovery Factor', risk.recovery_factor.toFixed(2)], ['Série gagnante max.', risk.max_win_streak],
    ['Série perdante max.', risk.max_loss_streak]
  ];
    document.getElementById('risk-cards').innerHTML = cards.map(([label, value]) => `<div class="card"><div class="card-title">${escapeHTML(label)}</div><div class="card-value data-text">${escapeHTML(value)}</div></div>`).join('');

  new ApexCharts(document.querySelector('#chart-drawdown'), {
    ...base, series: [{ name: 'Drawdown (%)', data: primary.drawdown_curve }],
    chart: { type: 'area', height: 260, background: 'transparent', toolbar: { show: false } },
    colors: ['#ef4444'], yaxis: { max: 0, labels: { formatter: value => `${value.toFixed(1)}%` } },
    dataLabels: { enabled: false }, stroke: { width: 2 }
  }).render();

  const monthly = primary.monthly_returns;
  const monthlyYears = [...new Set(Object.keys(monthly).map(month => month.slice(0, 4)))].sort();
  const monthNames = ['Jan','Fév','Mar','Avr','Mai','Juin','Juil','Août','Sep','Oct','Nov','Déc'];
  new ApexCharts(document.querySelector('#chart-monthly'), {
    ...base, series: monthlyYears.map(year => ({ name: year, data: monthNames.map((month, index) => ({ x: month, y: monthly[`${year}-${String(index + 1).padStart(2, '0')}`] ?? null })) })),
    chart: { type: 'heatmap', height: 260, background: 'transparent', toolbar: { show: false } },
    plotOptions: { heatmap: { colorScale: { ranges: [{ from: -1000000, to: -0.00001, color: '#ef4444' }, { from: 0, to: 1000000, color: '#10b981' }] } } },
    dataLabels: { enabled: true, formatter: value => value == null ? '' : `${value.toFixed(2)}%` }
  }).render();

  new ApexCharts(document.querySelector('#chart-rolling'), {
    ...base, series: [
      { name: 'Sharpe', data: primary.rolling.map(item => item.sharpe) },
      { name: 'Win rate (%)', data: primary.rolling.map(item => item.win_rate) }
    ], chart: { type: 'line', height: 260, background: 'transparent', toolbar: { show: false } },
    colors: ['#06b6d4', '#f59e0b'], stroke: { width: 2 }, dataLabels: { enabled: false }
  }).render();

  const durationPoints = primary.trades.map((trade, index) => ({ x: index + 1, y: trade.duration_minutes })).filter(point => point.y != null);
  new ApexCharts(document.querySelector('#chart-duration'), {
    ...base, series: [{ name: 'Minutes', data: durationPoints }],
    chart: { type: 'scatter', height: 260, background: 'transparent', toolbar: { show: false } },
    colors: ['#3b82f6'], xaxis: { title: { text: 'Trade' } }, yaxis: { title: { text: 'Minutes' } }
  }).render();

    if (analysisData.walk_forward) {
        document.getElementById('walk-forward-panel').hidden = false;
        const inSample = analysisData.walk_forward.in_sample;
        const outSample = analysisData.walk_forward.out_sample;
        const rows = [
            ['Rendement total', `${inSample.total_return_pct.toFixed(2)}%`, `${outSample.total_return_pct.toFixed(2)}%`],
            ['Drawdown maximum', `${inSample.max_drawdown_pct.toFixed(2)}%`, `${outSample.max_drawdown_pct.toFixed(2)}%`],
            ['Ratio de Sharpe', inSample.sharpe_ratio.toFixed(2), outSample.sharpe_ratio.toFixed(2)],
            ['Win rate', `${inSample.win_rate.toFixed(1)}%`, `${outSample.win_rate.toFixed(1)}%`],
            ['Nombre de trades', inSample.total_trades, outSample.total_trades]
        ];
        document.getElementById('walk-forward-table').innerHTML = `<div class="table-container"><table><thead><tr><th>Métrique</th><th>In-Sample : ${escapeHTML(analysisData.walk_forward.in_sample_name)}</th><th>Out-of-Sample : ${escapeHTML(analysisData.walk_forward.out_sample_name)}</th></tr></thead><tbody>${rows.map(row => `<tr><td>${escapeHTML(row[0])}</td><td>${row[1]}</td><td>${row[2]}</td></tr>`).join('')}</tbody></table></div>`;
    }

  if (analysisData.results.length > 1) {
    document.getElementById('comparison-panel').hidden = false;
    const rows = analysisData.results.map(item => `<tr><td>${escapeHTML(item.metadata.symbol)} ${escapeHTML(item.metadata.timeframe)}</td><td>${item.metrics.total_return_pct.toFixed(2)}%</td><td>${item.metrics.max_drawdown_pct.toFixed(2)}%</td><td>${item.metrics.sharpe_ratio.toFixed(2)}</td><td>${item.metrics.win_rate.toFixed(1)}%</td><td>${item.metrics.profit_factor.toFixed(2)}</td><td>${item.stats.total_trades}</td></tr>`).join('');
    document.getElementById('comparison-table').innerHTML = `<div class="table-container"><table><thead><tr><th>Backtest</th><th>Rendement</th><th>Max DD</th><th>Sharpe</th><th>Win rate</th><th>Profit factor</th><th>Trades</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    new ApexCharts(document.querySelector('#chart-comparison'), {
      ...base, series: analysisData.results.map(item => ({ name: `${item.metadata.symbol} ${item.metadata.timeframe}`, data: item.equity_curve })),
      chart: { type: 'line', height: 320, background: 'transparent', toolbar: { show: false } },
      stroke: { width: 2 }, dataLabels: { enabled: false }, title: { text: 'Courbes d’équité' }
    }).render();
    const labels = analysisData.comparison.labels;
    new ApexCharts(document.querySelector('#chart-correlation'), {
      ...base, series: labels.map((label, row) => ({ name: label, data: labels.map((column, col) => ({ x: column, y: analysisData.comparison.matrix[row][col] })) })),
      chart: { type: 'heatmap', height: 300, background: 'transparent', toolbar: { show: false } },
      dataLabels: { enabled: true, formatter: value => value == null ? 'n/a' : value.toFixed(2) }, title: { text: 'Corrélation des rendements' }
    }).render();
  }

  if (analysisData.optimization.parameters.length) {
    document.getElementById('optimization-panel').hidden = false;
    document.getElementById('optimization-summary').textContent = `Meilleur rendement observé : ${analysisData.optimization.best.return.toFixed(2)}% (${analysisData.optimization.best.report})`;
    const parameter = analysisData.optimization.parameters[0];
    new ApexCharts(document.querySelector('#chart-optimization'), {
      ...base, series: [{ name: 'Rendement (%)', data: parameter.points.map(point => ({ x: Number(point.value), y: point.return })) }],
      chart: { type: 'line', height: 300, background: 'transparent', toolbar: { show: false } },
      xaxis: { type: 'numeric', title: { text: parameter.name } }, stroke: { width: 2 }, markers: { size: 5 }
    }).render();
    if (analysisData.optimization.heatmap.length) {
      const heatmap = analysisData.optimization.heatmap;
      const xs = [...new Set(heatmap.map(point => String(point.x)))];
      const ys = [...new Set(heatmap.map(point => String(point.y)))];
      new ApexCharts(document.querySelector('#chart-optimization-heatmap'), {
        ...base, series: ys.map(y => ({ name: y, data: xs.map(x => ({ x, y: heatmap.find(point => String(point.x) === x && String(point.y) === y)?.return ?? null })) })),
        chart: { type: 'heatmap', height: 300, background: 'transparent', toolbar: { show: false } },
        dataLabels: { enabled: true, formatter: value => value == null ? '' : `${value.toFixed(2)}%` }, title: { text: 'Deux paramètres' }
      }).render();
    }
  }
</script>
"""


def _number(value, default=0.0):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _parse_datetime(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None


def _percentile(values, percentile):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def normalize_backtest_result(data: dict, source: str = "backtest") -> dict:
    metadata = data.get('metadata') or {}
    source_metrics = data.get('metrics') or {}
    source_stats = data.get('stats') or {}

    def value(name, default=0):
        return data.get(name, source_metrics.get(name, source_stats.get(name, default)))

    trades = []
    for raw_trade in data.get('trades') or []:
        if not isinstance(raw_trade, dict):
            continue
        trade = dict(raw_trade)
        trade['pnl'] = _number(trade.get('pnl'))
        trade['pnl_pct'] = _number(trade.get('pnl_pct', trade.get('return_pct')))
        trade['market_regime'] = trade.get('market_regime') or 'unknown'
        entry_time = _parse_datetime(trade.get('entry_time'))
        exit_time = _parse_datetime(trade.get('exit_time'))
        duration = (exit_time - entry_time).total_seconds() / 60 if entry_time and exit_time else None
        trade['duration_minutes'] = max(0, duration) if duration is not None else None
        trades.append(trade)

    equity = [_number(item) for item in data.get('equity_curve', []) if _number(item) > 0]
    initial = _number(data.get('initial_balance', metadata.get('initial_balance')))
    if not initial and equity:
        initial = equity[0]
    if not equity and initial:
        equity = [initial]
        for trade in trades:
            equity.append(equity[-1] + trade['pnl'])
    final = _number(data.get('final_balance', metadata.get('final_balance')), equity[-1] if equity else initial)
    total_return = value('total_return_pct', value('total_return', None))
    if total_return is None:
        total_return = (final / initial - 1) * 100 if initial else 0
    drawdown = []
    peak = equity[0] if equity else 0
    for balance in equity:
        peak = max(peak, balance)
        drawdown.append((balance / peak - 1) * 100 if peak else 0)
    maximum_drawdown = abs(_number(value('max_drawdown_pct', value('max_drawdown', min(drawdown, default=0)))))
    win_rate = _number(value('win_rate', 0))
    if 0 <= win_rate <= 1:
        win_rate *= 100
    win_count = int(_number(value('winning_trades', source_stats.get('winning_trades', sum(t['pnl'] > 0 for t in trades)))))
    loss_count = int(_number(value('losing_trades', source_stats.get('losing_trades', sum(t['pnl'] < 0 for t in trades)))))
    stats = {
        **source_stats,
        'total_trades': int(_number(value('total_trades', len(trades)))),
        'winning_trades': win_count,
        'losing_trades': loss_count,
    }
    metrics = {
        'total_return_pct': _number(total_return),
        'max_drawdown_pct': maximum_drawdown,
        'sharpe_ratio': _number(value('sharpe_ratio')),
        'sortino_ratio': _number(value('sortino_ratio')),
        'calmar_ratio': _number(value('calmar_ratio')),
        'profit_factor': _number(value('profit_factor')),
        'win_rate': win_rate,
    }
    metadata = {
        'symbol': data.get('symbol', metadata.get('symbol', 'N/A')),
        'timeframe': data.get('timeframe', metadata.get('timeframe', 'N/A')),
        'start_date': data.get('start_date', metadata.get('start_date', 'N/A')),
        'end_date': data.get('end_date', metadata.get('end_date', 'N/A')),
        'initial_balance': initial,
        'final_balance': final,
        'source': source,
    }

    returns = [trade['pnl_pct'] for trade in trades]
    monthly = {}
    for trade in trades:
        exit_time = _parse_datetime(trade.get('exit_time') or trade.get('timestamp'))
        if exit_time:
            key = exit_time.strftime('%Y-%m')
            monthly[key] = monthly.get(key, 0.0) + trade['pnl_pct']
    rolling = []
    for end in range(1, len(returns) + 1):
        window = returns[max(0, end - 20):end]
        mean = sum(window) / len(window)
        deviation = math.sqrt(sum((item - mean) ** 2 for item in window) / len(window))
        rolling.append({
            'sharpe': mean / deviation if deviation else 0.0,
            'win_rate': sum(item > 0 for item in window) / len(window) * 100,
        })
    losses = [item for item in returns if item < 0]
    wins = [item for item in returns if item > 0]
    max_win_streak = max_loss_streak = current_win = current_loss = 0
    for item in returns:
        current_win = current_win + 1 if item > 0 else 0
        current_loss = current_loss + 1 if item < 0 else 0
        max_win_streak = max(max_win_streak, current_win)
        max_loss_streak = max(max_loss_streak, current_loss)
    var_95 = _percentile(returns, 0.05)
    risk = {
        'var_95': var_95,
        'expected_shortfall_95': sum(item for item in returns if item <= var_95) / max(1, sum(item <= var_95 for item in returns)),
        'tail_ratio': (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) if wins and losses else None,
        'recovery_factor': metrics['total_return_pct'] / maximum_drawdown if maximum_drawdown else 0.0,
        'max_win_streak': max_win_streak,
        'max_loss_streak': max_loss_streak,
    }
    return {
        'metadata': metadata, 'metrics': metrics, 'stats': stats, 'trades': trades,
        'equity_curve': equity, 'drawdown_curve': drawdown, 'monthly_returns': monthly,
        'rolling': rolling, 'risk': risk, 'params': data.get('params_used', data.get('parameters', {})),
        'walk_forward': data.get('walk_forward'),
    }


def load_backtest_results(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as result_file:
        data = json.load(result_file)
    if not isinstance(data, dict):
        raise ValueError('Le JSON de résultat doit contenir un objet.')
    return normalize_backtest_result(data, Path(path).stem)


def build_analysis_payload(results: List[dict], optimize_parameters: List[str] = None) -> dict:
    comparison = {'labels': [item['metadata']['source'] for item in results], 'matrix': []}
    returns = []
    for item in results:
        curve = item['equity_curve']
        returns.append([right / left - 1 for left, right in zip(curve, curve[1:]) if left])
    for left in returns:
        row = []
        for right in returns:
            count = min(len(left), len(right))
            x, y = left[-count:], right[-count:]
            if count < 2:
                row.append(None)
                continue
            x_mean, y_mean = sum(x) / count, sum(y) / count
            covariance = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y))
            x_variance = sum((a - x_mean) ** 2 for a in x)
            y_variance = sum((b - y_mean) ** 2 for b in y)
            row.append(covariance / math.sqrt(x_variance * y_variance) if x_variance and y_variance else None)
        comparison['matrix'].append(row)

    optimization = {'parameters': [], 'heatmap': [], 'best': None}
    names = optimize_parameters or []
    for name in names:
        points = [
            {'value': item['params'][name], 'return': item['metrics']['total_return_pct'], 'report': item['metadata']['source']}
            for item in results if isinstance(item['params'], dict) and name in item['params']
        ]
        if points:
            optimization['parameters'].append({'name': name, 'points': points})
    if len(names) > 1:
        x_name, y_name = names[:2]
        optimization['heatmap'] = [
            {'x': item['params'][x_name], 'y': item['params'][y_name], 'return': item['metrics']['total_return_pct']}
            for item in results if isinstance(item['params'], dict) and x_name in item['params'] and y_name in item['params']
        ]
    candidates = [point | {'parameter': parameter['name']} for parameter in optimization['parameters'] for point in parameter['points']]
    if candidates:
        optimization['best'] = max(candidates, key=lambda point: point['return'])
    return {'results': results, 'comparison': comparison, 'optimization': optimization, 'walk_forward': None}

def print_summary(data: dict):
    print("+" + "-"*48 + "+")
    print(f"| NexQuant SuperBot Backtest Summary".ljust(49) + "|")
    print("+" + "-"*48 + "+")
    
    meta = data.get("metadata", {})
    print(f"| Symbol: {meta.get('symbol', 'N/A')} ({meta.get('timeframe', 'N/A')})".ljust(49) + "|")
    print(f"| Period: {meta.get('start_date', 'N/A')} - {meta.get('end_date', 'N/A')}".ljust(49) + "|")
    print("+" + "-"*48 + "+")
    
    metrics = data.get("metrics", {})
    stats = data.get("stats", {})
    
    lines = [
        f"Return:        {metrics.get('total_return_pct', 0):+.2f}%",
        f"Max Drawdown:  {metrics.get('max_drawdown_pct', 0):.2f}%",
        f"Sharpe Ratio:  {metrics.get('sharpe_ratio', 0):.2f}",
        f"Win Rate:      {metrics.get('win_rate', 0):.1f}%",
        f"Profit Factor: {metrics.get('profit_factor', 0):.2f}",
        f"Total Trades:  {stats.get('total_trades', 0)}"
    ]
    for line in lines:
        print(f"| {line}".ljust(49) + "|")
    print("+" + "-"*48 + "+")
    risk = data.get('risk', {})
    print(
        f"VaR 95%: {risk.get('var_95', 0):.2f}% | "
        f"ES 95%: {risk.get('expected_shortfall_95', 0):.2f}% | "
        f"Tail ratio: {risk.get('tail_ratio') if risk.get('tail_ratio') is not None else 'n/a'}"
    )


def export_static_chart(results: List[dict], output_path: Path, extension: str):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"Export {extension.upper()} ignoré : installez matplotlib pour l’activer.", file=sys.stderr)
        return

    figure, (equity_axis, drawdown_axis) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    for result in results:
        label = f"{result['metadata']['symbol']} {result['metadata']['timeframe']} ({result['metadata']['source']})"
        equity_axis.plot(result['equity_curve'], label=label)
        drawdown_axis.plot(result['drawdown_curve'], label=label)
    equity_axis.set_title('Courbes d’équité')
    equity_axis.set_ylabel('Solde')
    equity_axis.legend(loc='best')
    equity_axis.grid(alpha=0.25)
    drawdown_axis.set_title('Drawdown')
    drawdown_axis.set_ylabel('%')
    drawdown_axis.set_xlabel('Observation')
    drawdown_axis.grid(alpha=0.25)
    figure.tight_layout()
    target = output_path.with_suffix(f'.{extension}')
    figure.savefig(target, dpi=150, bbox_inches='tight')
    plt.close(figure)
    print(f"Export {extension.upper()} généré : {target}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="NexQuant Backtest Visualizer")
    parser.add_argument("--input", nargs="+", required=True, help="Fichier(s) JSON ou motifs glob")
    parser.add_argument("--output", default="reports/analysis.html", help="Chemin du rapport HTML")
    parser.add_argument("--compare", action="store_true", help="Afficher le comparatif multi-backtests")
    parser.add_argument("--optimize", nargs="+", metavar="PARAM", help="Analyser un ou deux paramètres variables")
    parser.add_argument("--walk-forward", action="store_true", help="Comparer les deux fichiers d’entrée comme In-Sample puis Out-of-Sample")
    parser.add_argument("--png", action="store_true", help="Exporter aussi les graphiques en PNG (matplotlib optionnel)")
    parser.add_argument("--pdf", action="store_true", help="Exporter aussi les graphiques en PDF (matplotlib optionnel)")
    args = parser.parse_args(argv)

    files = []
    for pattern in args.input:
        files.extend(glob.glob(pattern))
    files = list(dict.fromkeys(files))
    if not files:
        parser.error("Aucun fichier d’entrée trouvé.")

    results = []
    for file_path in files:
        try:
            results.append(load_backtest_results(file_path))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            parser.error(f"Impossible de charger {file_path}: {exc}")

    if args.walk_forward and len(results) != 2:
        parser.error("--walk-forward requiert exactement deux rapports : In-Sample puis Out-of-Sample.")

    if args.compare and len(results) < 2:
        print("Comparaison demandée avec un seul rapport : génération du rapport individuel.")
    for result in results:
        print_summary(result)
    if len(results) > 1:
        print("Comparaison : " + " | ".join(
            f"{item['metadata']['source']} {item['metrics']['total_return_pct']:+.2f}%"
            for item in results
        ))

    payload = build_analysis_payload(results, args.optimize)
    if args.walk_forward:
        def walk_forward_metrics(result):
            return {
                'total_return_pct': result['metrics']['total_return_pct'],
                'max_drawdown_pct': result['metrics']['max_drawdown_pct'],
                'sharpe_ratio': result['metrics']['sharpe_ratio'],
                'win_rate': result['metrics']['win_rate'],
                'total_trades': result['stats']['total_trades'],
            }

        payload['walk_forward'] = {
            'in_sample_name': results[0]['metadata']['source'],
            'out_sample_name': results[1]['metadata']['source'],
            'in_sample': walk_forward_metrics(results[0]),
            'out_sample': walk_forward_metrics(results[1]),
        }
    primary = results[0]
    html_content = HTML_TEMPLATE.replace(
        "{{REPLACE_JSON_DATA}}",
        json.dumps(primary, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c"),
    )
    analytics_html = ANALYTICS_TEMPLATE.replace(
        "{{REPLACE_ANALYTICS_DATA}}",
        json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c"),
    )
    html_content = html_content.replace("</body>", analytics_html + "</body>")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', encoding='utf-8') as report_file:
        report_file.write(html_content)
    print(f"Rapport HTML généré : {output_path}")
    if args.png:
        export_static_chart(results, output_path, 'png')
    if args.pdf:
        export_static_chart(results, output_path, 'pdf')
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
