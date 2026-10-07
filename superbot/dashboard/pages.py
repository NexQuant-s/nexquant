
def get_shared_head(title: str) -> str:
    return f"""
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{title} — NexQuant</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Plus+Jakarta+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/>
<script src="https://cdn.jsdelivr.net/npm/apexcharts"></script>
<script>
  if (typeof ApexCharts === 'undefined') {{
    document.write('<script src="https://cdnjs.cloudflare.com/ajax/libs/apexcharts/3.41.0/apexcharts.min.js"><\\/script>');
  }}
</script>
<style>
:root {{
  --bg: #070913; --surface: #0a0e1a; --card: rgba(16, 22, 41, 0.75);
  --card-hover: rgba(22, 30, 56, 0.85); --border: rgba(255, 255, 255, 0.05);
  --border-focus: rgba(255, 255, 255, 0.12); --txt: #f3f4f6;
  --txt-secondary: #9ca3af; --txt-muted: #4b5563;
  --accent-cyan: #06b6d4; --accent-blue: #3b82f6; --accent-purple: #8b5cf6;
  --green: #10b981; --red: #ef4444; --amber: #f59e0b;
  --radius-lg: 16px; --radius-md: 10px; --radius-sm: 6px;
}}
.light-theme {{ --bg: #f3f4f6; --surface: #ffffff; --card: rgba(243,244,246,0.8); --card-hover: rgba(229,231,235,0.9); --border: rgba(0,0,0,0.08); --border-focus: rgba(0,0,0,0.15); --txt: #111827; --txt-secondary: #4b5563; --txt-muted: #9ca3af; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Plus Jakarta Sans', sans-serif; background: var(--bg); color: var(--txt); display: flex; height: 100vh; overflow: hidden; }}
h1, h2, h3, h4, h5, h6, .outfit {{ font-family: 'Outfit', sans-serif; }}
.mono {{ font-family: 'JetBrains Mono', monospace; }}

/* Sidebar Styles */
.sidebar {{ width: 260px; background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; flex-shrink: 0; overflow-y: auto; z-index: 10; }}
.sidebar-brand {{ padding: 24px; font-size: 20px; font-weight: 700; color: var(--accent-cyan); display: flex; align-items: center; gap: 12px; font-family: 'Outfit', sans-serif; }}
.sidebar-nav {{ padding: 12px; display: flex; flex-direction: column; gap: 4px; }}
.nav-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--txt-muted); padding: 16px 12px 8px; font-weight: 600; }}
.nav-item {{ display: flex; align-items: center; gap: 12px; padding: 10px 12px; color: var(--txt-secondary); text-decoration: none; border-radius: var(--radius-sm); transition: all 0.2s; font-size: 14px; }}
.nav-item i {{ width: 18px; text-align: center; }}
.nav-item:hover {{ background: rgba(255, 255, 255, 0.05); color: var(--txt); }}
.nav-item.active {{ background: rgba(6, 182, 212, 0.1); color: var(--accent-cyan); border-left: 3px solid var(--accent-cyan); padding-left: 9px; }}

/* Main Layout */
.main-wrapper {{ flex: 1; display: flex; flex-direction: column; overflow: hidden; position: relative; }}
.topbar {{ height: 64px; display: flex; align-items: center; justify-content: space-between; padding: 0 24px; background: rgba(10, 14, 26, 0.8); backdrop-filter: blur(10px); border-bottom: 1px solid var(--border); z-index: 5; flex-shrink: 0; }}
.page-title {{ font-size: 18px; font-weight: 600; display: flex; align-items: center; gap: 12px; }}
.content-area {{ flex: 1; overflow-y: auto; padding: 24px; }}

/* Component Styles */
.card {{ background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 20px; backdrop-filter: blur(10px); display: flex; flex-direction: column; }}
.card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }}
.card-title {{ font-size: 16px; font-weight: 600; color: var(--txt); }}
.grid-cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
.metric-card {{ background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 16px; transition: all 0.2s; }}
.metric-card:hover {{ background: var(--card-hover); border-color: var(--border-focus); transform: translateY(-2px); }}
.metric-label {{ color: var(--txt-secondary); font-size: 13px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }}
.metric-value {{ font-size: 24px; font-weight: 700; font-family: 'Outfit', sans-serif; }}
.metric-value.up {{ color: var(--green); }}
.metric-value.down {{ color: var(--red); }}
.grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 24px; }}
.grid-1 {{ display: grid; grid-template-columns: 1fr; gap: 24px; margin-bottom: 24px; }}
@media (max-width: 800px) {{
  body {{ display: block; height: auto; min-height: 100vh; overflow-x: hidden; }}
  .sidebar {{ width: 100%; max-height: none; overflow: visible; border-right: 0; border-bottom: 1px solid var(--border); }}
  .sidebar-brand {{ padding: 12px 16px; }}
  .sidebar-nav {{ display: flex; flex-direction: row; overflow-x: auto; padding: 8px; }}
  .nav-label {{ display: none; }}
  .nav-item {{ flex: 0 0 auto; white-space: nowrap; }}
  .main-wrapper {{ min-height: 0; overflow: visible; }}
  .content-area {{ overflow: visible; padding: 16px; }}
  .grid-2 {{ grid-template-columns: 1fr; gap: 16px; }}
  .grid-2 > *, .card, .chart-container {{ min-width: 0; max-width: 100%; }}
  .apexcharts-canvas, .apexcharts-svg {{ max-width: 100%; }}
  .grid-cards {{ grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }}
  .topbar {{ padding: 0 16px; }}
}}

/* Tables */
.table-container {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; }}
th {{ padding: 12px 16px; color: var(--txt-secondary); font-weight: 500; border-bottom: 1px solid var(--border); cursor: pointer; }}
th:hover {{ color: var(--txt); }}
td {{ padding: 12px 16px; border-bottom: 1px solid var(--border); }}
tr:hover td {{ background: rgba(255, 255, 255, 0.02); }}
.badge {{ padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; text-transform: uppercase; }}
.badge.win {{ background: rgba(16, 185, 129, 0.1); color: var(--green); border: 1px solid rgba(16, 185, 129, 0.2); }}
.badge.loss {{ background: rgba(239, 68, 68, 0.1); color: var(--red); border: 1px solid rgba(239, 68, 68, 0.2); }}
.badge.neutral {{ background: rgba(156, 163, 175, 0.1); color: var(--txt-secondary); border: 1px solid rgba(156, 163, 175, 0.2); }}
.text-green {{ color: var(--green); }}
.text-red {{ color: var(--red); }}

/* Inputs */
.control-group {{ display: flex; gap: 12px; align-items: center; margin-bottom: 20px; flex-wrap: wrap; }}
select, input {{ background: rgba(0,0,0,0.2); border: 1px solid var(--border); color: var(--txt); padding: 8px 12px; border-radius: var(--radius-sm); font-family: inherit; font-size: 14px; outline: none; }}
select:focus, input:focus {{ border-color: var(--accent-cyan); }}
.btn {{ background: var(--surface); border: 1px solid var(--border); color: var(--txt); padding: 8px 16px; border-radius: var(--radius-sm); cursor: pointer; font-family: inherit; font-size: 14px; transition: all 0.2s; }}
.btn:hover {{ border-color: var(--accent-cyan); color: var(--accent-cyan); }}

/* Chart Containers */
.chart-container {{ min-height: 350px; position: relative; }}

/* Scrollbar */
::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: rgba(255, 255, 255, 0.1); border-radius: 10px; }}
::-webkit-scrollbar-thumb:hover {{ background: rgba(255, 255, 255, 0.2); }}
</style>
</head>
"""

def get_sidebar(active_page: str) -> str:
    return f"""
<nav class="sidebar">
  <div class="sidebar-brand">
    <i class="fa-solid fa-bolt" style="color: var(--accent-cyan)"></i> NexQuant
  </div>
  <nav class="sidebar-nav">
    <div class="nav-label">Tableau de bord</div>
    <a href="/" class="nav-item {'active' if active_page == 'home' else ''}"><i class="fa-solid fa-shapes"></i><span>Vue d'ensemble</span></a>
    
    <div class="nav-label">Analyse Avancée</div>
    <a href="/performance" class="nav-item {'active' if active_page == 'performance' else ''}"><i class="fa-solid fa-chart-line"></i><span>Performance</span></a>
    <a href="/trades" class="nav-item {'active' if active_page == 'trades' else ''}"><i class="fa-solid fa-receipt"></i><span>Journal des Trades</span></a>
    <a href="/compare" class="nav-item {'active' if active_page == 'compare' else ''}"><i class="fa-solid fa-code-compare"></i><span>Comparaison</span></a>
    <a href="/optimize" class="nav-item {'active' if active_page == 'optimize' else ''}"><i class="fa-solid fa-sliders"></i><span>Optimisation</span></a>
  </nav>
</nav>
"""

def generate_performance_html() -> str:
    html = f"""<!DOCTYPE html>
<html lang="fr">
{get_shared_head("Performance")}
<body>
  {get_sidebar("performance")}
  <div class="main-wrapper">
    <header class="topbar">
      <div class="page-title">
        <i class="fa-solid fa-chart-line" style="color: var(--accent-cyan);"></i> Performance Analytics
      </div>
    </header>
    <main class="content-area" id="perf-content">
      
      <div class="grid-cards">
        <div class="metric-card"><div class="metric-label">Retour Total</div><div class="metric-value" id="val-total-return">--%</div></div>
        <div class="metric-card"><div class="metric-label">Max Drawdown</div><div class="metric-value down" id="val-max-dd">--%</div></div>
        <div class="metric-card"><div class="metric-label">Sharpe Ratio</div><div class="metric-value" id="val-sharpe">--</div></div>
        <div class="metric-card"><div class="metric-label">Sortino Ratio</div><div class="metric-value" id="val-sortino">--</div></div>
        <div class="metric-card"><div class="metric-label">Win Rate</div><div class="metric-value" id="val-win-rate">--%</div></div>
        <div class="metric-card"><div class="metric-label">Profit Factor</div><div class="metric-value" id="val-profit-factor">--</div></div>
        <div class="metric-card"><div class="metric-label">Calmar Ratio</div><div class="metric-value" id="val-calmar">--</div></div>
        <div class="metric-card"><div class="metric-label">Total Trades</div><div class="metric-value" id="val-trades-count">--</div></div>
      </div>

      <div class="grid-1">
        <div class="card">
          <div class="card-header"><div class="card-title">Courbe d'Équité & Drawdown</div></div>
          <div id="chart-equity" class="chart-container"></div>
        </div>
      </div>

      <div class="grid-2">
        <div class="card">
          <div class="card-header"><div class="card-title">Distribution des P&L</div></div>
          <div id="chart-distribution" class="chart-container"></div>
        </div>
        <div class="card">
          <div class="card-header"><div class="card-title">Sharpe Ratio Roulant (20 trades)</div></div>
          <div id="chart-rolling-sharpe" class="chart-container"></div>
        </div>
      </div>
      
      <div class="grid-1">
        <div class="card">
          <div class="card-header"><div class="card-title">Heatmap des Rendements Mensuels</div></div>
          <div id="chart-monthly" class="chart-container"></div>
        </div>
      </div>
      
    </main>
  </div>
  
  <script>
    let charts = {{}};
    const commonChartOptions = {{
      chart: {{ foreColor: '#9ca3af', toolbar: {{ show: false }}, background: 'transparent' }},
      theme: {{ mode: 'dark' }},
      grid: {{ borderColor: 'rgba(255,255,255,0.05)', strokeDashArray: 4 }},
      tooltip: {{ theme: 'dark' }}
    }};

    async function loadPerformanceData() {{
      try {{
        const res = await fetch('/api/performance-data');
        const data = await res.json();
        updateMetrics(data.metrics);
        updateEquityChart(data.equity_curve, data.drawdown_curve);
        updateDistributionChart(data.pnl_distribution);
        updateRollingSharpe(data.pnl_distribution);
        updateMonthlyReturns(data.monthly_returns);
      }} catch(err) {{
        console.error('Error fetching performance data:', err);
      }}
    }}

    function updateMetrics(metrics) {{
      if(!metrics) return;
      document.getElementById('val-total-return').textContent = (metrics.total_return || 0).toFixed(2) + '%';
      document.getElementById('val-total-return').className = 'metric-value ' + (metrics.total_return >= 0 ? 'up' : 'down');
      
      document.getElementById('val-max-dd').textContent = (metrics.max_drawdown || 0).toFixed(2) + '%';
      
      document.getElementById('val-sharpe').textContent = (metrics.sharpe_ratio || 0).toFixed(2);
      document.getElementById('val-sortino').textContent = (metrics.sortino_ratio || 0).toFixed(2);
      document.getElementById('val-calmar').textContent = (metrics.calmar_ratio || 0).toFixed(2);
      
      document.getElementById('val-win-rate').textContent = (metrics.win_rate || 0).toFixed(1) + '%';
      document.getElementById('val-profit-factor').textContent = metrics.profit_factor == null ? '∞' : Number(metrics.profit_factor).toFixed(2);
      document.getElementById('val-trades-count').textContent = metrics.total_trades || 0;
    }}

    function updateEquityChart(equity, drawdown) {{
      if(!equity || equity.length === 0) return;
      const xCategories = Array.from({{length: equity.length}}, (_, i) => i);
      
      if(charts.equity) charts.equity.destroy();
      charts.equity = new ApexCharts(document.querySelector("#chart-equity"), {{
        ...commonChartOptions,
        series: [{{ name: 'Equity', type: 'area', data: equity }}, {{ name: 'Drawdown', type: 'line', data: drawdown }}],
        chart: {{ type: 'line', height: 350, toolbar: {{ show: false }} }},
        colors: ['#06b6d4', '#ef4444'],
        fill: {{ type: ['gradient', 'solid'], gradient: {{ shadeIntensity: 1, opacityFrom: 0.4, opacityTo: 0.05 }} }},
        stroke: {{ width: [2, 1], curve: 'smooth' }},
        yaxis: [
          {{ title: {{ text: 'Equité (€)' }}, labels: {{ formatter: v => v.toFixed(0) }} }},
          {{ opposite: true, title: {{ text: 'Drawdown (%)' }}, max: 0, labels: {{ formatter: v => v.toFixed(1) + '%' }} }}
        ],
        xaxis: {{ categories: xCategories, labels: {{ show: false }} }}
      }});
      charts.equity.render();
    }}

    function updateDistributionChart(pnl) {{
      if(!pnl || pnl.length === 0) return;
      
      const bucketSize = 10;
      let buckets = {{}};
      pnl.forEach(val => {{
        let b = Math.floor(val / bucketSize) * bucketSize;
        buckets[b] = (buckets[b] || 0) + 1;
      }});
      
      let sortedKeys = Object.keys(buckets).map(Number).sort((a,b)=>a-b);
      let seriesData = sortedKeys.map(k => buckets[k]);
      let categories = sortedKeys.map(k => `${{k}} à ${{k+bucketSize}}€`);
      let colors = sortedKeys.map(k => k >= 0 ? '#10b981' : '#ef4444');

      if(charts.distribution) charts.distribution.destroy();
      charts.distribution = new ApexCharts(document.querySelector("#chart-distribution"), {{
        ...commonChartOptions,
        series: [{{ name: 'Trades', data: seriesData }}],
        chart: {{ type: 'bar', height: 300 }},
        colors: colors,
        plotOptions: {{ bar: {{ distributed: true }} }},
        xaxis: {{ categories: categories }},
        legend: {{ show: false }}
      }});
      charts.distribution.render();
    }}

    function updateRollingSharpe(pnl) {{
      if(!pnl || pnl.length < 20) return;
      let rolling = [];
      for(let i = 20; i <= pnl.length; i++) {{
        let window = pnl.slice(i-20, i);
        let mean = window.reduce((a,b)=>a+b, 0) / window.length;
        let sqDiffs = window.map(v => Math.pow(v - mean, 2));
        let std = Math.sqrt(sqDiffs.reduce((a,b)=>a+b, 0) / window.length);
        let sr = std === 0 ? 0 : mean / std;
        rolling.push(sr);
      }}

      if(charts.rollingSharpe) charts.rollingSharpe.destroy();
      charts.rollingSharpe = new ApexCharts(document.querySelector("#chart-rolling-sharpe"), {{
        ...commonChartOptions,
        series: [{{ name: 'Rolling Sharpe', data: rolling }}],
        chart: {{ type: 'line', height: 300 }},
        colors: ['#8b5cf6'],
        stroke: {{ width: 2, curve: 'smooth' }}
      }});
      charts.rollingSharpe.render();
    }}

    function updateMonthlyReturns(monthly) {{
      if(!monthly || Object.keys(monthly).length === 0) return;
      
      let years = {{}};
      Object.keys(monthly).forEach(m => {{
        let [y, mo] = m.split('-');
        if(!years[y]) years[y] = Array(12).fill(0);
        years[y][parseInt(mo)-1] = monthly[m];
      }});
      
      let series = Object.keys(years).sort().map(y => ({{
        name: y,
        data: years[y].map(v => ({{ x: 'M', y: v }})) 
      }}));
      
      const monthNames = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc'];
      series.forEach(s => {{
        s.data.forEach((d, i) => d.x = monthNames[i]);
      }});

      if(charts.monthly) charts.monthly.destroy();
      charts.monthly = new ApexCharts(document.querySelector("#chart-monthly"), {{
        ...commonChartOptions,
        series: series,
        chart: {{ type: 'heatmap', height: 300 }},
        plotOptions: {{
          heatmap: {{
            shadeIntensity: 0.5,
            colorScale: {{
              ranges: [
                {{ from: -9999, to: -0.01, name: 'Perte', color: '#ef4444' }},
                {{ from: 0, to: 9999, name: 'Profit', color: '#10b981' }}
              ]
            }}
          }}
        }},
        dataLabels: {{ enabled: true, formatter: v => v.toFixed(1) + '%' }}
      }});
      charts.monthly.render();
    }}

    document.addEventListener('DOMContentLoaded', () => {{
      loadPerformanceData();
      setInterval(loadPerformanceData, 30000);
    }});
  </script>
</body>
</html>
"""
    return html

def generate_trades_html() -> str:
    html = f"""<!DOCTYPE html>
<html lang="fr">
{get_shared_head("Journal des Trades")}
<body>
  {get_sidebar("trades")}
  <div class="main-wrapper">
    <header class="topbar">
      <div class="page-title">
        <i class="fa-solid fa-receipt" style="color: var(--accent-cyan);"></i> Journal des Trades
      </div>
    </header>
    <main class="content-area">
      
      <div class="grid-cards">
        <div class="metric-card"><div class="metric-label">Total Trades</div><div class="metric-value" id="val-total">--</div></div>
        <div class="metric-card"><div class="metric-label">Win Rate</div><div class="metric-value" id="val-win-rate">--%</div></div>
        <div class="metric-card"><div class="metric-label">P&L Moyen</div><div class="metric-value" id="val-avg-pnl">--</div></div>
        <div class="metric-card"><div class="metric-label">Meilleur Trade</div><div class="metric-value up" id="val-best">--</div></div>
        <div class="metric-card"><div class="metric-label">Pire Trade</div><div class="metric-value down" id="val-worst">--</div></div>
        <div class="metric-card"><div class="metric-label">P&L Total</div><div class="metric-value" id="val-total-pnl">--</div></div>
      </div>

      <div class="grid-2">
        <div class="card">
          <div class="card-header"><div class="card-title">P&L par Symbole</div></div>
          <div id="chart-symbol" class="chart-container" style="min-height: 250px;"></div>
        </div>
        <div class="card">
          <div class="card-header"><div class="card-title">Win Rate par Régime</div></div>
          <div id="chart-regime" class="chart-container" style="min-height: 250px;"></div>
        </div>
        <div class="card">
          <div class="card-header">
            <div class="card-title">Prix d'Entrée et de Sortie</div>
            <select id="price-symbol" aria-label="Paire du graphique"></select>
          </div>
          <div id="chart-prices" class="chart-container" style="min-height: 250px;"></div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <div class="card-title">Historique des Trades</div>
          <div class="control-group" style="margin-bottom:0;">
            <select id="filter-symbol">
              <option value="all">Tous les symboles</option>
            </select>
            <input id="filter-from" type="date" aria-label="Date de début" />
            <input id="filter-to" type="date" aria-label="Date de fin" />
            <select id="filter-status">
              <option value="all">Tous les statuts</option>
              <option value="win">Gagnants</option>
              <option value="loss">Perdants</option>
            </select>
          </div>
        </div>
        <div class="table-container">
          <table id="trades-table">
            <thead>
              <tr>
                <th data-key="timestamp">Date</th>
                <th data-key="symbol">Symbole</th>
                <th data-key="side">Dir</th>
                <th data-key="entry_price">Entrée</th>
                <th data-key="exit_price">Sortie</th>
                <th data-key="pnl">P&L</th>
                <th data-key="signal_score">Score</th>
                <th data-key="market_regime">Régime</th>
                <th data-key="duration_seconds">Durée</th>
              </tr>
            </thead>
            <tbody>
            </tbody>
          </table>
        </div>
        <div style="margin-top: 16px; display: flex; justify-content: space-between; align-items: center;">
          <div id="pagination-info" class="mono" style="color: var(--txt-secondary); font-size: 13px;"></div>
          <div style="display: flex; gap: 8px;">
            <button class="btn" id="btn-prev">Précédent</button>
            <button class="btn" id="btn-next">Suivant</button>
          </div>
        </div>
      </div>

    </main>
  </div>
  
  <script>
    let allTrades = [];
    let filteredTrades = [];
    let currentPage = 1;
    const itemsPerPage = 25;
    let charts = {{}};
    let sortKey = 'timestamp';
    let sortDirection = -1;

    function escapeHTML(value) {{
      return String(value ?? '').replace(/[&<>"']/g, char => ({{
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }})[char]);
    }}

    async function loadTradesData() {{
      try {{
        const res = await fetch('/api/trades-data');
        const data = await res.json();
        allTrades = data.trades || [];
        
        const symbols = [...new Set(allTrades.map(t => t.symbol).filter(Boolean))];
        const symSelect = document.getElementById('filter-symbol');
        symSelect.innerHTML = '<option value="all">Tous les symboles</option>' + 
          symbols.map(s => `<option value="${{s}}">${{s}}</option>`).join('');
        const priceSymbol = document.getElementById('price-symbol');
        priceSymbol.innerHTML = symbols.map(s => `<option value="${{escapeHTML(s)}}">${{escapeHTML(s)}}</option>`).join('');
        priceSymbol.value = symbols[0] || '';

        updateStats(data.stats);
        updateSymbolChart(data.symbol_stats);
        updateRegimeChart(data.regime_stats);
        
        applyFilters();
      }} catch(err) {{
        console.error(err);
      }}
    }}

    function updateStats(stats) {{
      if(!stats) return;
      document.getElementById('val-total').textContent = stats.total_count || 0;
      document.getElementById('val-win-rate').textContent = (stats.win_rate || 0).toFixed(1) + '%';
      
      const avg = (stats.avg_pnl || 0);
      document.getElementById('val-avg-pnl').textContent = avg.toFixed(2) + '€';
      document.getElementById('val-avg-pnl').className = 'metric-value ' + (avg >= 0 ? 'up' : 'down');
      
      document.getElementById('val-best').textContent = (stats.best_trade || 0).toFixed(2) + '€';
      document.getElementById('val-worst').textContent = (stats.worst_trade || 0).toFixed(2) + '€';
      
      const total = (stats.total_pnl || 0);
      document.getElementById('val-total-pnl').textContent = total.toFixed(2) + '€';
      document.getElementById('val-total-pnl').className = 'metric-value ' + (total >= 0 ? 'up' : 'down');
    }}

    function updateSymbolChart(stats) {{
      if(!stats || Object.keys(stats).length === 0) return;
      const entries = Object.entries(stats).sort((left, right) => left[1].pnl - right[1].pnl);
      const symbols = entries.map(([symbol]) => symbol);
      const values = entries.map(([, item]) => Number(item.pnl) || 0);
      
      if(charts.symbol) charts.symbol.destroy();
      charts.symbol = new ApexCharts(document.querySelector("#chart-symbol"), {{
        series: [{{ name: 'P&L net', data: values }}],
        chart: {{ type: 'bar', height: Math.max(280, symbols.length * 32), background: 'transparent', toolbar: {{ show: false }} }},
        theme: {{ mode: 'dark' }},
        plotOptions: {{ bar: {{ horizontal: true, distributed: true, barHeight: '62%', borderRadius: 3 }} }},
        colors: values.map(value => value >= 0 ? '#10b981' : '#ef4444'),
        dataLabels: {{ enabled: true, formatter: value => `${{value.toFixed(2)}} €`, style: {{ colors: ['#f3f4f6'] }} }},
        xaxis: {{ categories: symbols, labels: {{ formatter: value => Number(value).toFixed(0) }} }},
        yaxis: {{ labels: {{ maxWidth: 90 }} }},
        grid: {{ borderColor: 'rgba(255,255,255,0.08)' }},
        legend: {{ show: false }},
        tooltip: {{ y: {{ formatter: value => `${{value.toFixed(2)}} €` }} }}
      }});
      charts.symbol.render();
    }}

    function updateRegimeChart(stats) {{
      if(!stats || Object.keys(stats).length === 0) return;
      const regimes = Object.keys(stats);
      const data = regimes.map(r => (stats[r].wins / stats[r].total) * 100);
      
      if(charts.regime) charts.regime.destroy();
      charts.regime = new ApexCharts(document.querySelector("#chart-regime"), {{
        series: [{{ name: 'Win Rate %', data: data }}],
        chart: {{ type: 'bar', height: 250, background: 'transparent', toolbar: {{show:false}} }},
        theme: {{ mode: 'dark' }},
        plotOptions: {{ bar: {{ horizontal: true }} }},
        xaxis: {{ categories: regimes, max: 100 }},
        colors: ['#3b82f6']
      }});
      charts.regime.render();
    }}

    function updatePriceChart(trades, symbol) {{
      if(charts.prices) charts.prices.destroy();
      const target = document.querySelector('#chart-prices');
      const points = trades.filter(trade => trade.symbol === symbol)
        .filter(trade => Number.isFinite(Number(trade.entry_price)) && Number.isFinite(Number(trade.exit_price)))
        .sort((left, right) => String(left.timestamp).localeCompare(String(right.timestamp)));
      if(!symbol || !points.length) {{
        target.textContent = symbol ? 'Aucun trade pour cette paire et ces filtres.' : 'Aucune paire disponible.';
        return;
      }}
      if(charts.prices) charts.prices.destroy();
      target.textContent = '';
      const dates = points.map(trade => String(trade.timestamp || trade.entry_time || '').slice(0, 10));
      const labelStep = Math.max(1, Math.ceil(points.length / 8));
      charts.prices = new ApexCharts(target, {{
        series: [
          {{ name: 'Entrée', data: points.map(trade => Number(trade.entry_price)) }},
          {{ name: 'Sortie', data: points.map(trade => Number(trade.exit_price)) }}
        ],
        chart: {{ type: 'line', height: 320, background: 'transparent', toolbar: {{ show: false }} }},
        theme: {{ mode: 'dark' }}, colors: ['#06b6d4', '#f59e0b'],
        stroke: {{ width: 2, curve: 'straight' }}, markers: {{ size: 2, hover: {{ size: 5 }} }},
        dataLabels: {{ enabled: false }},
        xaxis: {{ categories: dates.map((date, index) => index % labelStep === 0 ? `${{date.slice(8, 10)}}/${{date.slice(5, 7)}}` : ''),
          title: {{ text: 'Date (JJ/MM)' }}, labels: {{ rotate: 0, hideOverlappingLabels: true, trim: false, maxHeight: 40 }} }},
        yaxis: {{ title: {{ text: `Prix ${{symbol}}` }}, labels: {{ formatter: value => Number(value).toLocaleString('fr-FR', {{ maximumFractionDigits: 5 }}) }} }},
        tooltip: {{
          x: {{ formatter: (value, options) => dates[options?.dataPointIndex] || value }},
          y: {{ formatter: value => Number(value).toLocaleString('fr-FR', {{ maximumFractionDigits: 5 }}) }}
        }}
      }});
      charts.prices.render();
    }}

    function applyFilters() {{
      const sym = document.getElementById('filter-symbol').value;
      const stat = document.getElementById('filter-status').value;
      const from = document.getElementById('filter-from').value;
      const to = document.getElementById('filter-to').value;
      
      filteredTrades = allTrades.filter(t => {{
        if(sym !== 'all' && t.symbol !== sym) return false;
        if(stat === 'win' && t.pnl <= 0) return false;
        if(stat === 'loss' && t.pnl > 0) return false;
        const tradeDate = String(t.timestamp || '').slice(0, 10);
        if(from && tradeDate < from) return false;
        if(to && tradeDate > to) return false;
        return true;
      }});

      filteredTrades.sort((left, right) => {{
        const a = left[sortKey] ?? '';
        const b = right[sortKey] ?? '';
        const comparison = typeof a === 'number' && typeof b === 'number'
          ? a - b : String(a).localeCompare(String(b), 'fr', {{ numeric: true }});
        return comparison * sortDirection;
      }});

      const priceSymbol = document.getElementById('price-symbol').value;
      const chartTrades = allTrades.filter(trade => {{
        if(trade.symbol !== priceSymbol) return false;
        if(stat === 'win' && trade.pnl <= 0) return false;
        if(stat === 'loss' && trade.pnl > 0) return false;
        const tradeDate = String(trade.timestamp || '').slice(0, 10);
        return (!from || tradeDate >= from) && (!to || tradeDate <= to);
      }});
      updatePriceChart(chartTrades, priceSymbol);
      
      currentPage = 1;
      renderTable();
    }}

    function renderTable() {{
      const tbody = document.querySelector('#trades-table tbody');
      tbody.innerHTML = '';
      
      const start = (currentPage - 1) * itemsPerPage;
      const end = start + itemsPerPage;
      const paginated = filteredTrades.slice(start, end);
      
      paginated.forEach(t => {{
        const isWin = t.pnl > 0;
        const pnlCls = isWin ? 'text-green' : (t.pnl < 0 ? 'text-red' : '');
        const pnlSign = isWin ? '+' : '';
        const dirIcon = String(t.side).toUpperCase() === 'LONG' || String(t.direction).toUpperCase() === 'LONG' ? 
            '<i class="fa-solid fa-arrow-up text-green"></i>' : '<i class="fa-solid fa-arrow-down text-red"></i>';
            
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td class="mono">${{escapeHTML(t.timestamp || t.entry_time || '--')}}</td>
          <td><b>${{escapeHTML(t.symbol || '--')}}</b></td>
          <td>${{dirIcon}}</td>
          <td class="mono">${{Number(t.entry_price || 0).toLocaleString('fr-FR')}}</td>
          <td class="mono">${{Number(t.exit_price || 0).toLocaleString('fr-FR')}}</td>
          <td class="mono ${{pnlCls}}"><b>${{pnlSign}}${{(t.pnl||0).toFixed(2)}}€</b></td>
          <td>${{t.signal_score || t.score || '--'}}</td>
          <td><span class="badge neutral">${{escapeHTML(t.market_regime || '--')}}</span></td>
          <td class="mono">${{t.duration_seconds == null ? '--' : Math.round(t.duration_seconds / 60) + ' min'}}</td>
        `;
        tbody.appendChild(tr);
      }});
      
      document.getElementById('pagination-info').textContent = 
        `Affichage ${{Math.min(start + 1, filteredTrades.length)}}-${{Math.min(end, filteredTrades.length)}} sur ${{filteredTrades.length}} trades`;
        
      document.getElementById('btn-prev').disabled = currentPage === 1;
      document.getElementById('btn-next').disabled = end >= filteredTrades.length;
    }}

    document.getElementById('filter-symbol').addEventListener('change', applyFilters);
    document.getElementById('price-symbol').addEventListener('change', applyFilters);
    document.getElementById('filter-status').addEventListener('change', applyFilters);
    document.getElementById('filter-from').addEventListener('change', applyFilters);
    document.getElementById('filter-to').addEventListener('change', applyFilters);
    document.querySelectorAll('#trades-table th[data-key]').forEach(header => {{
      header.addEventListener('click', () => {{
        sortDirection = sortKey === header.dataset.key ? -sortDirection : 1;
        sortKey = header.dataset.key;
        renderTable();
      }});
    }});
    
    document.getElementById('btn-prev').addEventListener('click', () => {{ if(currentPage > 1) {{ currentPage--; renderTable(); }} }});
    document.getElementById('btn-next').addEventListener('click', () => {{ if(currentPage * itemsPerPage < filteredTrades.length) {{ currentPage++; renderTable(); }} }});

    document.addEventListener('DOMContentLoaded', loadTradesData);
  </script>
</body>
</html>
"""
    return html

def generate_compare_html() -> str:
    html = f"""<!DOCTYPE html>
<html lang="fr">
{get_shared_head("Comparaison")}
<body>
  {get_sidebar("compare")}
  <div class="main-wrapper">
    <header class="topbar">
      <div class="page-title">
        <i class="fa-solid fa-code-compare" style="color: var(--accent-cyan);"></i> Comparaison des Stratégies
      </div>
    </header>
    <main class="content-area">
      <div id="compare-content" aria-live="polite"></div>
      <div class="grid-2" id="compare-charts" hidden>
        <section class="card"><div class="card-header"><div class="card-title">Profil de performance normalisé</div></div><div id="chart-radar" class="chart-container"></div></section>
        <section class="card"><div class="card-header"><div class="card-title">Corrélation des rendements</div></div><div id="chart-correlation" class="chart-container"></div></section>
        <section class="card"><div class="card-header"><div class="card-title">Comparaison mensuelle</div></div><div id="chart-period" class="chart-container"></div></section>
      </div>
    </main>
  </div>
  <script>
    const safeText = value => String(value ?? '').replace(/[&<>"']/g, char => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[char]);
    const metricSpecs = [
      ['total_return', 'Rendement'], ['max_drawdown', 'Drawdown'],
      ['sharpe_ratio', 'Sharpe'], ['win_rate', 'Win rate'], ['profit_factor', 'Profit factor']
    ];

    async function loadCompareData() {{
      try {{
        const res = await fetch('/api/compare-data');
        const data = await res.json();
        const container = document.getElementById('compare-content');
        if(!data.comparison_available) {{
          container.innerHTML = `<div class="card"><h2>Comparaison indisponible</h2><p style="color:var(--txt-secondary);margin-top:8px">${{safeText(data.message)}}</p></div>`;
          return;
        }}
        const strategies = data.strategies || [];
        const fmt = value => Number(value || 0).toFixed(2);
        container.innerHTML = `<div class="card"><div class="table-container"><table>
          <thead><tr><th>Rapport</th><th>Symbole / période</th><th>Rendement</th><th>Drawdown max</th><th>Sharpe</th><th>Win rate</th><th>Profit factor</th><th>Trades</th></tr></thead>
          <tbody>${{strategies.map(item => `<tr><td><b>${{safeText(item.name)}}</b></td><td>${{safeText(item.symbol)}} ${{safeText(item.timeframe)}}<br>${{safeText(item.start_date)}} → ${{safeText(item.end_date)}}</td><td class="mono">${{fmt(item.total_return)}}%</td><td class="mono">${{fmt(item.max_drawdown)}}%</td><td class="mono">${{fmt(item.sharpe_ratio)}}</td><td class="mono">${{fmt(item.win_rate)}}%</td><td class="mono">${{fmt(item.profit_factor)}}</td><td class="mono">${{item.total_trades}}</td></tr>`).join('')}}</tbody>
        </table></div></div>`;
        document.getElementById('compare-charts').hidden = false;
        const normalized = metricSpecs.map(([key]) => {{
          const values = strategies.map(item => Number(item[key] || 0));
          const low = Math.min(...values), high = Math.max(...values);
          return values.map(value => high === low ? 50 : (value - low) / (high - low) * 100);
        }});
        const drawdownIndex = metricSpecs.findIndex(([key]) => key === 'max_drawdown');
        normalized[drawdownIndex] = normalized[drawdownIndex].map(value => 100 - value);
        new ApexCharts(document.querySelector('#chart-radar'), {{
          series: strategies.map((item, index) => ({{ name: item.name, data: normalized.map(values => values[index]) }})),
          chart: {{ type: 'radar', height: 350, background: 'transparent', toolbar: {{ show: false }} }},
          theme: {{ mode: 'dark' }}, xaxis: {{ categories: metricSpecs.map(([, label]) => label) }},
          yaxis: {{ min: 0, max: 100, tickAmount: 4 }}, stroke: {{ width: 2 }}, fill: {{ opacity: 0.12 }}
        }}).render();

        const correlation = data.correlation || {{}};
        const matrix = correlation.matrix || [];
        const labels = correlation.labels || [];
        new ApexCharts(document.querySelector('#chart-correlation'), {{
          series: labels.map((label, row) => ({{ name: label, data: labels.map((column, col) => ({{ x: column, y: matrix[row]?.[col] }})) }})),
          chart: {{ type: 'heatmap', height: 350, background: 'transparent', toolbar: {{ show: false }} }},
          theme: {{ mode: 'dark' }}, dataLabels: {{ enabled: true, formatter: value => value == null ? 'n/a' : value.toFixed(2) }},
          plotOptions: {{ heatmap: {{ colorScale: {{ ranges: [
            {{ from: -1, to: -0.25, color: '#ef4444', name: 'Négative' }},
            {{ from: -0.25, to: 0.25, color: '#f59e0b', name: 'Faible' }},
            {{ from: 0.25, to: 1, color: '#10b981', name: 'Positive' }}
          ] }} }} }}
        }}).render();
        const periodSeries = (data.period_returns || []).filter(item => item.data.length);
        if(periodSeries.length) new ApexCharts(document.querySelector('#chart-period'), {{
          series: periodSeries,
          chart: {{ type: 'line', height: 350, background: 'transparent', toolbar: {{ show: false }} }},
          theme: {{ mode: 'dark' }}, colors: ['#06b6d4', '#f59e0b', '#10b981', '#ef4444'],
          stroke: {{ width: 2, curve: 'straight' }}, markers: {{ size: 4 }},
          xaxis: {{ type: 'category', title: {{ text: 'Mois' }} }},
          yaxis: {{ title: {{ text: 'Rendement mensuel (%)' }}, labels: {{ formatter: value => `${{value.toFixed(1)}}%` }} }},
          dataLabels: {{ enabled: false }}
        }}).render();
      }} catch(err) {{
        document.getElementById('compare-content').innerHTML = '<div class="card">Erreur de chargement des rapports de comparaison.</div>';
        console.error(err);
      }}
    }}
    document.addEventListener('DOMContentLoaded', loadCompareData);
  </script>
</body>
</html>
"""
    return html

def generate_optimize_html() -> str:
    html = f"""<!DOCTYPE html>
<html lang="fr">
{get_shared_head("Optimisation")}
<body>
  {get_sidebar("optimize")}
  <div class="main-wrapper">
    <header class="topbar">
      <div class="page-title">
        <i class="fa-solid fa-sliders" style="color: var(--accent-cyan);"></i> Optimisation des Paramètres
      </div>
    </header>
    <main class="content-area">
      <div id="optimize-status" aria-live="polite"></div>
      <div id="optimize-results" hidden>
        <div id="parameter-analytics" hidden>
          <div id="best-result"></div>
          <div class="grid-cards" id="params-container"></div>
          <div class="control-group"><label for="parameter-select">Paramètre analysé</label><select id="parameter-select" disabled></select></div>
          <div class="grid-2">
            <section class="card"><div class="card-header"><div class="card-title">Sensibilité univariée</div></div><div id="chart-sensitivity" class="chart-container"></div></section>
            <section class="card"><div class="card-header"><div class="card-title">Performance selon deux paramètres</div></div><div id="chart-heatmap" class="chart-container"></div></section>
          </div>
        </div>
        <section id="walk-forward-section" class="card" hidden><div class="card-header"><div class="card-title">Walk-forward</div></div><div id="walk-forward" class="table-container"></div></section>
      </div>
    </main>
  </div>
  
  <script>
    let sensitivityChart;
    const safeText = value => String(value ?? '').replace(/[&<>"']/g, char => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[char]);

    async function loadOptimizeData() {{
      try {{
        const res = await fetch('/api/optimize-data');
        const data = await res.json();
        const status = document.getElementById('optimize-status');
        const resultsRoot = document.getElementById('optimize-results');
        const parameterAnalytics = document.getElementById('parameter-analytics');
        if(!data.available) {{
          status.innerHTML = `<div class="card"><h2>Optimisation indisponible</h2><p style="color:var(--txt-secondary);margin-top:8px">${{safeText(data.message)}}</p></div>`;
          return;
        }}
        resultsRoot.hidden = false;
        const hasParameters = Boolean(data.parameter_available);
        parameterAnalytics.hidden = !hasParameters;
        status.textContent = hasParameters
          ? `${{data.results.length}} observations issues des rapports sauvegardés`
          : data.message;
        if(hasParameters) {{
          if(data.best_result) {{
            document.getElementById('best-result').innerHTML = `<div class="card" style="margin:16px 0"><b>Meilleur résultat observé</b>: ${{safeText(data.best_result.parameter)}} = ${{safeText(data.best_result.value)}} · rendement ${{Number(data.best_result.return).toFixed(2)}}% · ${{safeText(data.best_result.report)}}</div>`;
          }}
          const container = document.getElementById('params-container');
          container.innerHTML = data.parameters.map(parameter => `<div class="metric-card"><div class="metric-label">${{safeText(parameter.name)}}</div><div class="metric-value">${{parameter.values.length}} valeurs</div><div style="color:var(--txt-secondary);font-size:13px;margin-top:8px">${{parameter.values.map(safeText).join(', ')}}</div></div>`).join('');
          const select = document.getElementById('parameter-select');
          select.innerHTML = data.parameters.map(parameter => `<option value="${{safeText(parameter.name)}}">${{safeText(parameter.name)}}</option>`).join('');
          select.disabled = false;
          const drawSensitivity = () => {{
            const name = select.value;
            const points = data.results.filter(result => result.parameter === name)
              .map(result => ({{ x: Number(result.value), y: Number(result.return), meta: result.report }}))
              .sort((a, b) => a.x - b.x);
            if(sensitivityChart) sensitivityChart.destroy();
            sensitivityChart = new ApexCharts(document.querySelector('#chart-sensitivity'), {{
              series: [{{ name: 'Rendement (%)', data: points }}],
              chart: {{ type: 'line', height: 330, background: 'transparent', toolbar: {{ show: false }} }},
              theme: {{ mode: 'dark' }}, colors: ['#06b6d4'], stroke: {{ curve: 'straight', width: 2 }},
              markers: {{ size: 5 }}, xaxis: {{ type: 'numeric', title: {{ text: name }} }},
              yaxis: {{ title: {{ text: 'Rendement (%)' }} }}, tooltip: {{ x: {{ formatter: value => `${{name}}: ${{value}}` }} }}
            }});
            sensitivityChart.render();
          }};
          select.addEventListener('change', drawSensitivity);
          drawSensitivity();

          if(data.heatmap?.length && data.parameters.length > 1) {{
            const xValues = [...new Set(data.heatmap.map(point => String(point.x)))].sort((a,b) => Number(a)-Number(b));
            const yValues = [...new Set(data.heatmap.map(point => String(point.y)))].sort((a,b) => Number(a)-Number(b));
            new ApexCharts(document.querySelector('#chart-heatmap'), {{
              series: yValues.map(y => ({{ name: y, data: xValues.map(x => {{
                const point = data.heatmap.find(cell => String(cell.x) === x && String(cell.y) === y);
                return {{ x, y: point ? point.z : null }};
              }}) }})),
              chart: {{ type: 'heatmap', height: 330, background: 'transparent', toolbar: {{ show: false }} }},
              theme: {{ mode: 'dark' }}, dataLabels: {{ enabled: true, formatter: value => value == null ? '' : value.toFixed(2) + '%' }},
              plotOptions: {{ heatmap: {{ colorScale: {{ ranges: [
                {{ from: -1000, to: 0, color: '#ef4444', name: 'Perte' }},
                {{ from: 0, to: 1000, color: '#10b981', name: 'Profit' }}
              ] }} }} }}, xaxis: {{ title: {{ text: `${{data.parameters[0].name}} / ${{data.parameters[1].name}}` }} }}
            }}).render();
          }} else {{
            document.querySelector('#chart-heatmap').textContent = 'Deux paramètres variables sont nécessaires pour cette vue.';
          }}
        }}

        const wf = data.walk_forward || [];
        document.getElementById('walk-forward-section').hidden = !wf.length;
        document.getElementById('walk-forward').innerHTML = wf.length
          ? `<table><thead><tr><th>Rapport</th><th>In-sample</th><th>Out-of-sample</th></tr></thead><tbody>${{wf.map(item => `<tr><td>${{safeText(item.name)}}</td><td>${{Number(item.in_sample?.total_return_pct ?? item.in_sample?.total_return ?? 0).toFixed(2)}}%</td><td>${{Number(item.out_sample?.total_return_pct ?? item.out_sample?.total_return ?? 0).toFixed(2)}}%</td></tr>`).join('')}}</tbody></table>`
          : '<p style="color:var(--txt-secondary)">Aucun résultat walk-forward associé aux rapports.</p>';
      }} catch(err) {{
        console.error(err);
        document.getElementById('optimize-results').hidden = true;
        document.getElementById('optimize-status').textContent = 'Erreur lors du chargement des rapports d’optimisation.';
      }}
    }}
    document.addEventListener('DOMContentLoaded', loadOptimizeData);
  </script>
</body>
</html>
"""
    return html
