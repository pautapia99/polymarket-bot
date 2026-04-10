"""Dashboard web para visualizar la actividad del bot."""
from flask import Flask, jsonify, render_template_string

import storage
from config import Config

app = Flask(__name__)

try:
    _CFG = Config.load()
except Exception:
    _CFG = None

INDEX_HTML = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Polymarket Bot Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif;
         margin: 0; background:#0b1020; color:#e6e8ee; }
  header { padding: 16px 24px; background:#11172e; border-bottom:1px solid #222a44; }
  h1 { margin:0; font-size:20px; }
  .grid { display:grid; grid-template-columns:repeat(4,1fr); gap:16px; padding:24px; }
  .card { background:#11172e; border:1px solid #222a44; border-radius:10px; padding:16px; }
  .card h3 { margin:0 0 6px; font-size:12px; text-transform:uppercase;
             letter-spacing:.05em; color:#8a93b2; font-weight:600; }
  .card .v { font-size:24px; font-weight:700; }
  .pos { color:#3ddc97; } .neg { color:#ff6b6b; } .mut { color:#8a93b2; }
  .chart-wrap { padding: 0 24px 24px; }
  .chart-card { background:#11172e; border:1px solid #222a44; border-radius:10px;
                padding:16px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { padding:8px 10px; text-align:left; border-bottom:1px solid #222a44; }
  th { color:#8a93b2; font-weight:600; text-transform:uppercase; font-size:11px; }
  .buy { color:#3ddc97; font-weight:600; } .sell { color:#ff6b6b; font-weight:600; }
  .badge { display:inline-block; padding:2px 6px; border-radius:4px; font-size:11px;
           background:#222a44; }
  .badge.dry { background:#3a3a00; color:#ffd966; }
  .badge.ok { background:#10301f; color:#3ddc97; }
  .badge.err { background:#3a1010; color:#ff6b6b; }
</style>
</head>
<body>
<header>
  <h1>Polymarket Bot — Dashboard
    <span id="modeBadge" class="badge" style="margin-left:8px;">—</span>
  </h1>
</header>

<div class="grid">
  <div class="card"><h3>Último bid</h3><div class="v" id="bid">—</div></div>
  <div class="card"><h3>Último ask</h3><div class="v" id="ask">—</div></div>
  <div class="card"><h3>Spread</h3><div class="v" id="spread">—</div></div>
  <div class="card"><h3>Mid</h3><div class="v" id="mid">—</div></div>
  <div class="card"><h3>Ticks registrados</h3><div class="v mut" id="tickc">—</div></div>
  <div class="card"><h3>Órdenes</h3><div class="v mut" id="ordc">—</div></div>
  <div class="card"><h3>Posición neta (shares)</h3><div class="v" id="net">—</div></div>
  <div class="card"><h3>P&amp;L realizado (USDC)</h3><div class="v" id="pnl">—</div></div>
</div>

<div class="grid">
  <div class="card"><h3>Snapshots recolectados</h3><div class="v" id="cRows">—</div></div>
  <div class="card"><h3>Tokens únicos</h3><div class="v mut" id="cTokens">—</div></div>
  <div class="card"><h3>Mercados únicos</h3><div class="v mut" id="cMarkets">—</div></div>
  <div class="card"><h3>Histórico (días)</h3><div class="v mut" id="cDays">—</div></div>
  <div class="card"><h3>Top traders trackeados</h3><div class="v" id="tTraders">—</div></div>
  <div class="card"><h3>Trades observados</h3><div class="v" id="tTrades">—</div></div>
  <div class="card"><h3>Último trade detectado</h3><div class="v mut" id="tLast">—</div></div>
  <div class="card"><h3>—</h3><div class="v mut">&nbsp;</div></div>
</div>

<div class="grid">
  <div class="card" style="grid-column:span 4;background:#0a1a10;border-color:#1b3d22;">
    <h3 style="color:#3ddc97;margin:0 0 12px;">🧠 Bot Inteligente</h3>
    <div style="display:flex;gap:40px;align-items:center;flex-wrap:wrap;">
      <div><div style="font-size:11px;color:#8a93b2;text-transform:uppercase;margin-bottom:4px;">Fase de autonomía</div>
           <div class="v pos" id="aiPhase" style="font-size:26px;">—</div></div>
      <div><div style="font-size:11px;color:#8a93b2;text-transform:uppercase;margin-bottom:4px;">Pares analizados</div>
           <div class="v mut" id="aiPairs">—</div></div>
      <div><div style="font-size:11px;color:#8a93b2;text-transform:uppercase;margin-bottom:4px;">Win rate medio</div>
           <div class="v" id="aiWinRate">—</div></div>
      <div><div style="font-size:11px;color:#8a93b2;text-transform:uppercase;margin-bottom:4px;">Señales generadas</div>
           <div class="v mut" id="aiSigTotal">—</div></div>
      <div><div style="font-size:11px;color:#8a93b2;text-transform:uppercase;margin-bottom:4px;">Win rate señales</div>
           <div class="v" id="aiSigWr">—</div></div>
    </div>
  </div>
</div>

<div class="chart-wrap">
  <div class="chart-card">
    <h3 style="margin:0 0 12px;color:#8a93b2;">🎯 Señales recientes del motor</h3>
    <table id="signalsTbl">
      <thead><tr><th>Hora</th><th>Side</th><th>Confianza</th><th>Precio</th>
                 <th>Traders</th><th>Fase</th><th>Mercado</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<div class="chart-wrap">
  <div class="chart-card">
    <h3 style="margin:0 0 12px;color:#8a93b2;">⚖️ Pesos aprendidos por trader</h3>
    <table id="traderStatsTbl">
      <thead><tr><th>Trader</th><th>Win Rate</th><th>Profit medio</th>
                 <th>Pares</th><th>Peso</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<div class="chart-wrap">
  <div class="chart-card">
    <h3 style="margin:0 0 12px;color:#8a93b2;">Trades recientes de top traders</h3>
    <table id="tracksTbl">
      <thead><tr><th>Hora</th><th>Trader</th><th>Side</th><th>Mercado</th>
                 <th>Outcome</th><th>Precio</th><th>Size</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<div class="grid" id="paperGrid" style="display:none;">
  <div class="card"><h3>Cash paper</h3><div class="v" id="pCash">—</div></div>
  <div class="card"><h3>Shares en cartera</h3><div class="v" id="pShares">—</div></div>
  <div class="card"><h3>Coste promedio</h3><div class="v" id="pAvg">—</div></div>
  <div class="card"><h3>Valor de mercado</h3><div class="v" id="pMv">—</div></div>
  <div class="card"><h3>P&amp;L no realizado</h3><div class="v" id="pUnreal">—</div></div>
  <div class="card"><h3>P&amp;L realizado</h3><div class="v" id="pReal">—</div></div>
  <div class="card"><h3>Equity total</h3><div class="v" id="pEq">—</div></div>
  <div class="card"><h3>Retorno %</h3><div class="v" id="pRet">—</div></div>
</div>

<div class="chart-wrap">
  <div class="chart-card">
    <h3 style="margin:0 0 12px;color:#8a93b2;">Precio (bid / ask / mid)</h3>
    <canvas id="priceChart" height="90"></canvas>
  </div>
</div>

<div class="chart-wrap">
  <div class="chart-card">
    <h3 style="margin:0 0 12px;color:#8a93b2;">Órdenes recientes</h3>
    <table id="ordersTbl">
      <thead><tr><th>Hora</th><th>Side</th><th>Precio</th><th>Shares</th>
                 <th>USDC</th><th>Estado</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>

<script>
let chart;
function fmt(v, d=3){ return v==null ? "—" : Number(v).toFixed(d); }
function fmtTs(ts){ return new Date(ts*1000).toLocaleTimeString(); }

async function refresh(){
  const [stats, ticks, orders, paper, coll, trk, lrn, sigs] = await Promise.all([
    fetch('/api/stats').then(r=>r.json()),
    fetch('/api/ticks').then(r=>r.json()),
    fetch('/api/orders').then(r=>r.json()),
    fetch('/api/paper').then(r=>r.json()),
    fetch('/api/collector').then(r=>r.json()),
    fetch('/api/tracker').then(r=>r.json()),
    fetch('/api/learner').then(r=>r.json()),
    fetch('/api/signals').then(r=>r.json()),
  ]);

  document.getElementById('cRows').textContent = (coll.rows||0).toLocaleString();
  document.getElementById('cTokens').textContent = coll.tokens||0;
  document.getElementById('cMarkets').textContent = coll.markets||0;
  if(coll.first_ts && coll.last_ts){
    const days = (coll.last_ts - coll.first_ts) / 86400;
    document.getElementById('cDays').textContent = days.toFixed(2);
  }

  const ts = trk.stats || {};
  document.getElementById('tTraders').textContent = ts.tracked_traders || 0;
  document.getElementById('tTrades').textContent = (ts.tracked_trades || 0).toLocaleString();
  document.getElementById('tLast').textContent = ts.last_trade_ts
    ? fmtTs(ts.last_trade_ts) : '—';

  // ── Bot Inteligente ──
  const ph = lrn.phase || {};
  document.getElementById('aiPhase').textContent =
    ph.num ? `Fase ${ph.num} – ${ph.name}` : '—';
  document.getElementById('aiPairs').textContent =
    (lrn.total_pairs || 0).toLocaleString();
  const wr = lrn.avg_win_rate;
  const wrEl = document.getElementById('aiWinRate');
  wrEl.textContent = wr != null ? (wr*100).toFixed(1)+'%' : '—';
  wrEl.className = 'v ' + (wr>0.55?'pos':wr<0.45?'neg':'mut');
  document.getElementById('aiSigTotal').textContent =
    (lrn.signal_stats?.total || 0).toLocaleString();
  const swr = lrn.signal_stats?.win_rate;
  const swrEl = document.getElementById('aiSigWr');
  swrEl.textContent = swr != null ? (swr*100).toFixed(1)+'%' : '—';
  swrEl.className = 'v ' + (swr>0.55?'pos':swr<0.45?'neg':'mut');

  // ── Señales recientes ──
  const sigBody = document.querySelector('#signalsTbl tbody');
  sigBody.innerHTML = (sigs.recent || []).map(s => {
    const sc = s.side === 'BUY' ? 'buy' : 'sell';
    const confPct = ((s.confidence||0)*100).toFixed(0)+'%';
    const bar = `<div style="display:inline-block;width:${confPct};height:6px;
      background:${s.side==='BUY'?'#3ddc97':'#ff6b6b'};border-radius:3px;
      vertical-align:middle;margin-right:6px;"></div>`;
    return `<tr>
      <td>${fmtTs(s.ts)}</td>
      <td class="${sc}">${s.side}</td>
      <td>${bar}${confPct}</td>
      <td>${fmt(s.avg_price,3)}</td>
      <td>${s.traders_count}</td>
      <td><span class="badge">${s.phase}</span></td>
      <td>${(s.title||s.slug||'').substring(0,55)}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="7" class="mut">Sin señales aún</td></tr>';

  // ── Pesos aprendidos ──
  const tsBody = document.querySelector('#traderStatsTbl tbody');
  tsBody.innerHTML = (lrn.top_traders || []).map(t => {
    const name = (t.pseudonym||t.wallet||'').substring(0,20);
    const wrCls = t.win_rate>0.55?'pos':t.win_rate<0.45?'neg':'mut';
    const barW = Math.round((t.weight||0)*100);
    const weightBar = `<div style="display:inline-block;width:${barW}px;height:6px;
      background:#3ddc97;border-radius:3px;vertical-align:middle;margin-right:6px;
      max-width:80px;"></div>`;
    return `<tr>
      <td>${name}</td>
      <td class="${wrCls}">${((t.win_rate||0)*100).toFixed(1)}%</td>
      <td>${((t.avg_profit_pct||0)*100).toFixed(2)}%</td>
      <td>${t.trades_analyzed||0}</td>
      <td>${weightBar}${(t.weight||0).toFixed(3)}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="5" class="mut">Learner acumulando datos...</td></tr>';

  const trBody = document.querySelector('#tracksTbl tbody');
  trBody.innerHTML = (trk.recent || []).map(t => {
    const sideCls = t.side === 'BUY' ? 'buy' : 'sell';
    const trader = (t.pseudonym || t.wallet || '').substring(0, 18);
    const market = (t.title || t.slug || '').substring(0, 50);
    return `<tr>
      <td>${fmtTs(t.ts)}</td>
      <td>${trader}</td>
      <td class="${sideCls}">${t.side}</td>
      <td>${market}</td>
      <td>${t.outcome || ''}</td>
      <td>${fmt(t.price, 3)}</td>
      <td>${fmt(t.size, 0)}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="7" class="mut">Sin trades aún</td></tr>';

  const badge = document.getElementById('modeBadge');
  badge.textContent = paper.mode || '—';
  badge.className = 'badge ' + (paper.mode==='PAPER'?'dry':paper.mode==='REAL'?'err':'ok');

  if(paper.enabled){
    document.getElementById('paperGrid').style.display='grid';
    document.getElementById('pCash').textContent = fmt(paper.cash, 2);
    document.getElementById('pShares').textContent = fmt(paper.shares, 2);
    document.getElementById('pAvg').textContent = paper.shares>0 ? fmt(paper.avg_cost, 3) : '—';
    document.getElementById('pMv').textContent = fmt(paper.market_value, 2);
    const ur = paper.unrealized || 0;
    const urEl = document.getElementById('pUnreal');
    urEl.textContent = fmt(ur, 2);
    urEl.className = 'v ' + (ur>0?'pos':ur<0?'neg':'mut');
    const re = paper.realized || 0;
    const reEl = document.getElementById('pReal');
    reEl.textContent = fmt(re, 2);
    reEl.className = 'v ' + (re>0?'pos':re<0?'neg':'mut');
    document.getElementById('pEq').textContent = fmt(paper.equity, 2);
    const ret = paper.return_pct || 0;
    const retEl = document.getElementById('pRet');
    retEl.textContent = (ret>=0?'+':'') + fmt(ret, 2) + '%';
    retEl.className = 'v ' + (ret>0?'pos':ret<0?'neg':'mut');
  }

  const last = stats.last_tick || {};
  document.getElementById('bid').textContent = fmt(last.bid);
  document.getElementById('ask').textContent = fmt(last.ask);
  document.getElementById('spread').textContent = fmt(last.spread);
  document.getElementById('mid').textContent = fmt(last.mid);
  document.getElementById('tickc').textContent = stats.tick_count;
  document.getElementById('ordc').textContent = stats.order_count;

  const net = stats.net_shares || 0;
  const netEl = document.getElementById('net');
  netEl.textContent = fmt(net, 2);
  netEl.className = 'v ' + (net>0?'pos':net<0?'neg':'mut');

  const pnl = stats.realized_usdc || 0;
  const pnlEl = document.getElementById('pnl');
  pnlEl.textContent = fmt(pnl, 2);
  pnlEl.className = 'v ' + (pnl>0?'pos':pnl<0?'neg':'mut');

  const labels = ticks.map(t => fmtTs(t.ts));
  const bids = ticks.map(t => t.bid);
  const asks = ticks.map(t => t.ask);
  const mids = ticks.map(t => t.mid);

  if(!chart){
    chart = new Chart(document.getElementById('priceChart'), {
      type:'line',
      data:{ labels, datasets:[
        {label:'bid', data:bids, borderColor:'#3ddc97', backgroundColor:'transparent', tension:.25, pointRadius:0},
        {label:'ask', data:asks, borderColor:'#ff6b6b', backgroundColor:'transparent', tension:.25, pointRadius:0},
        {label:'mid', data:mids, borderColor:'#8a93b2', borderDash:[4,4], backgroundColor:'transparent', tension:.25, pointRadius:0},
      ]},
      options:{
        animation:false,
        scales:{ y:{min:0,max:1, ticks:{color:'#8a93b2'}, grid:{color:'#222a44'}},
                 x:{ticks:{color:'#8a93b2', maxTicksLimit:8}, grid:{color:'#222a44'}}},
        plugins:{ legend:{labels:{color:'#e6e8ee'}}}
      }
    });
  } else {
    chart.data.labels = labels;
    chart.data.datasets[0].data = bids;
    chart.data.datasets[1].data = asks;
    chart.data.datasets[2].data = mids;
    chart.update();
  }

  const tbody = document.querySelector('#ordersTbl tbody');
  tbody.innerHTML = orders.map(o => {
    const sideCls = o.side === 'BUY' ? 'buy' : 'sell';
    let stCls = 'badge';
    if (o.dry_run) stCls += ' dry';
    else if (o.status === 'OK') stCls += ' ok';
    else if (o.status === 'ERROR') stCls += ' err';
    const stTxt = o.dry_run ? 'DRY' : o.status;
    return `<tr>
      <td>${fmtTs(o.ts)}</td>
      <td class="${sideCls}">${o.side}</td>
      <td>${fmt(o.price)}</td>
      <td>${fmt(o.size_shares,2)}</td>
      <td>${fmt(o.size_usdc,2)}</td>
      <td><span class="${stCls}">${stTxt}</span></td>
    </tr>`;
  }).join('') || '<tr><td colspan="6" class="mut">Sin órdenes todavía</td></tr>';
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/api/stats")
def api_stats():
    return jsonify(storage.fetch_stats())


@app.route("/api/ticks")
def api_ticks():
    return jsonify(storage.fetch_ticks(limit=300))


@app.route("/api/orders")
def api_orders():
    return jsonify(storage.fetch_orders(limit=100))


@app.route("/api/collector")
def api_collector():
    s = storage.fetch_snapshot_stats()
    return jsonify(s)


@app.route("/api/tracker")
def api_tracker():
    return jsonify({
        "stats": storage.fetch_tracker_stats(),
        "recent": storage.fetch_recent_tracked_trades(limit=20),
    })


@app.route("/api/learner")
def api_learner():
    import sqlite3
    stats = storage.fetch_trader_stats(limit=20)
    sig_stats = storage.fetch_signal_stats()
    phase, phase_name = storage.get_autonomy_phase()
    total_pairs = sum(s.get("trades_analyzed", 0) for s in stats)
    avg_wr = (
        sum(s["win_rate"] for s in stats) / len(stats) if stats else None
    )
    return jsonify({
        "phase": {"num": phase, "name": phase_name},
        "total_pairs": total_pairs,
        "avg_win_rate": round(avg_wr, 4) if avg_wr is not None else None,
        "top_traders": stats,
        "signal_stats": sig_stats,
    })


@app.route("/api/signals")
def api_signals():
    return jsonify({
        "recent": storage.fetch_recent_signals(limit=15),
        "stats":  storage.fetch_signal_stats(),
    })


@app.route("/api/paper")
def api_paper():
    if _CFG is None or not _CFG.paper_trading:
        # sin .env válido también devolvemos algo útil para que el dashboard no rompa
        mode = "REAL" if (_CFG and not _CFG.dry_run) else ("DRY" if _CFG else "—")
        return jsonify({"enabled": False, "mode": mode})

    cash = storage.get_paper_cash() or _CFG.initial_cash
    shares, cost = storage.get_paper_position(_CFG.token_id)
    last = storage.fetch_ticks(limit=1)
    mark = (last[-1]["mid"] if last and last[-1].get("mid") is not None else None)
    mv = (shares * mark) if (mark is not None) else 0.0
    unreal = (mv - cost) if shares > 0 else 0.0
    realized = storage.get_paper_realized()
    equity = cash + mv
    ret = ((equity - _CFG.initial_cash) / _CFG.initial_cash * 100.0) \
        if _CFG.initial_cash > 0 else 0.0
    return jsonify({
        "enabled": True,
        "mode": "PAPER",
        "cash": cash,
        "shares": shares,
        "cost_basis": cost,
        "avg_cost": (cost / shares) if shares > 0 else 0.0,
        "mark": mark,
        "market_value": mv,
        "unrealized": unreal,
        "realized": realized,
        "equity": equity,
        "initial_cash": _CFG.initial_cash,
        "return_pct": ret,
    })


if __name__ == "__main__":
    storage.init_db()
    app.run(host="127.0.0.1", port=5000, debug=False)
