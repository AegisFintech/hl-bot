'use strict';
// Render the same cached terminal payload; never creates extra exchange requests.
let researchBand = 5,
    researchLast = '',
    researchCurrent = null;
const researchNames = {
    book_flow: 'Depth + flow',
    absorption: 'Absorption',
    block_wall: 'Block + wall',
    large_trade: 'Large print',
    baseline: 'Unconditional control',
    failed_aggression: 'Failed aggression',
    wall_defense: 'Wall defense',
    crowded_failure: 'Crowded failure'
};

function researchText(id, value) {
    document.getElementById(id).textContent = value
}

function researchColor(id, value) {
    const el = document.getElementById(id);
    el.classList.remove('positive', 'negative', 'neutral');
    el.classList.add(value == null ? 'neutral' : value > 0 ? 'positive' : value < 0 ? 'negative' : 'neutral')
}

function researchEmpty(target, message) {
    const p = document.createElement('p');
    p.className = 'scope';
    p.textContent = message;
    target.replaceChildren(p)
}

function researchCard(title, value, detail, color = '') {
    const card = document.createElement('div');
    card.className = 'research-card';
    const top = document.createElement('div'),
        b = document.createElement('b'),
        v = document.createElement('span'),
        p = document.createElement('p');
    b.textContent = title;
    v.textContent = value;
    v.className = color;
    p.textContent = detail;
    top.append(b, v);
    card.append(top, p);
    return card
}

function researchRows(id, rows, columns, empty) {
    const body = document.getElementById(id);
    body.replaceChildren(...rows.map(row));
    if (!rows.length) {
        let tr = document.createElement('tr'),
            td = document.createElement('td');
        td.colSpan = columns;
        td.className = 'empty';
        td.textContent = empty;
        tr.append(td);
        body.append(tr)
    }
}

function researchBandRender() {
    const bands = researchCurrent?.market?.bands || [],
        band = bands.find(x => x.bps === researchBand);
    researchText('band-bids', usd(band?.bid_usd));
    researchText('band-asks', usd(band?.ask_usd));
    researchText('band-imbalance', band ? fmt(band.imbalance, 2) : '—');
    researchText('depth-coverage', band ? (band.bid_complete && band.ask_complete ? 'Full price-band coverage' : 'Truncated visible depth · not the complete band') : 'Depth unavailable')
}

function researchResults() {
    const j = researchCurrent?.journal || {},
        h = Number(document.getElementById('research-horizon').value);
    const results = (j.results || []).filter(r => r.horizon === h);
    researchRows('research-results', results.map(r => [(researchNames[r.kind] || r.kind) + ' · ' + (r.direction === 1 ? 'long' : 'short'), fmt(r.n, 0), fmt(r.nonoverlap_n, 0), fmt(r.mean_gross_bps, 2), fmt(r.mean_cost_drag_bps, 2), {
        text: fmt(r.mean_net_bps, 2),
        className: r.mean_net_bps >= 0 ? 'positive' : 'negative'
    }, fmt(r.nonoverlap_mean_net_bps, 2), fmt(r.matched_delta_bps, 2) + ' / ' + fmt(r.matched_n, 0), fmt(r.positive_rate * 100, 1) + '%', fmt(r.mean_favorable_bps, 2), fmt(r.mean_adverse_bps, 2), r.review_status || 'Insufficient evidence']), 12, 'No measured outcomes at this horizon yet. Forward observations must mature first.');
    researchText('research-event-count', (j.signal_count || 0) + ' EVENTS');
    researchText('research-benchmark', j.baseline_note || 'Matched controls need new prospective regime observations.');
    researchText('research-model', j.model || 'Quote-based outcomes are not executed trades or realized returns.');
    researchText('research-missed', `${j.missed_markouts||0} missed horizon samples · positive outcomes are descriptive, not calibrated probabilities. Overlapping signals are correlated.`);
    const events = document.getElementById('research-events');
    events.replaceChildren();
    for (const e of (j.recent || []).slice(0, 10)) {
        const line = document.createElement('div');
        line.className = 'evidence-line';
        let b = document.createElement('b');
        b.textContent = `${stamp(e.time)} UTC · ${researchNames[e.kind]||e.kind} · ${e.direction===1?'long':'short'}`;
        let p = document.createElement('div');
        p.textContent = e.reason;
        line.append(b, p);
        const outcome = (e.outcomes || []).find(x => x.horizon === h),
            explanation = document.createElement('div');
        explanation.textContent = outcome?.status === 'complete' ? `${h}s: ${fmt(outcome.gross_bps,2)}bps signed mid move → ${fmt(outcome.net_bps,2)}bps net proxy. ${outcome.net_bps>0?'Move exceeded modeled costs.':outcome.gross_bps>0?'Favorable move was insufficient after costs.':'Direction moved against the observation, with costs added.'}` : outcome?.status === 'missed' ? 'Horizon missed: no timely quote; outcome not invented.' : 'Waiting for this horizon to mature.';
        line.append(explanation);
        events.append(line)
    }
    if (!events.childNodes.length) researchEmpty(events, 'No prospective events recorded yet.')
}

function researchHeatmap() {
    const canvas = document.getElementById('depth-heatmap');
    if (!canvas) return;
    const ctx = canvas.getContext('2d'),
        rect = canvas.getBoundingClientRect(),
        dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(rect.width * dpr));
    canvas.height = Math.max(1, Math.round(rect.height * dpr));
    ctx.scale(dpr, dpr);
    const w = rect.width,
        h = rect.height;
    ctx.fillStyle = '#0d141e';
    ctx.fillRect(0, 0, w, h);
    const frames = researchCurrent?.market?.heatmap || [];
    researchText('heatmap-coverage', frames.length + ' SAMPLES');
    if (!frames.length) {
        ctx.fillStyle = '#8191a5';
        ctx.font = '11px sans-serif';
        ctx.fillText('Collecting real public liquidity snapshots…', 16, h / 2);
        return
    }
    const points = frames.flatMap(f => f.levels),
        lo = Math.min(...points.map(x => x[0])),
        hi = Math.max(...points.map(x => x[0])),
        range = hi - lo || 1,
        max = Math.max(...points.map(x => x[1]), 1),
        right = 65,
        bottom = 23,
        top = 8,
        plotW = w - right,
        plotH = h - bottom - top,
        cw = plotW / Math.max(30, frames.length);
    for (let i = 0; i < frames.length; i++) {
        for (const [price, value, side] of frames[i].levels) {
            let y = top + (hi - price) / range * plotH,
                alpha = .08 + .85 * Math.pow(value / max, .5);
            ctx.fillStyle = side === 'bid' ? `rgba(84,216,176,${alpha})` : `rgba(239,125,134,${alpha})`;
            ctx.fillRect(i * cw, y - 2, Math.max(1, cw - 1), 4)
        }
    }
    ctx.font = '9px monospace';
    ctx.fillStyle = '#8191a5';
    for (let i = 0; i <= 4; i++) {
        let y = top + plotH * i / 4;
        ctx.fillText(fmt(hi - range * i / 4), plotW + 6, y + 3);
        ctx.strokeStyle = '#203044';
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(plotW, y);
        ctx.stroke()
    }
    ctx.fillText(stamp(frames[0].time).slice(11), 7, h - 6);
    ctx.fillText(stamp(frames.at(-1).time).slice(11), Math.max(8, plotW - 60), h - 6);
    let mid = researchCurrent?.market?.mid;
    if (mid) {
        let y = top + (hi - mid) / range * plotH;
        ctx.strokeStyle = '#7da8fa';
        ctx.setLineDash([3, 4]);
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(plotW, y);
        ctx.stroke();
        ctx.setLineDash([])
    }
}

function renderResearch(payload) {
    researchCurrent = payload || {};
    const r = researchCurrent,
        m = r.market || {},
        sources = r.sources || {},
        stale = r.status === 'stale' || r.status === 'unavailable' || (data?.timestamp && Date.now() / 1000 - data.timestamp > 20);
    researchText('research-health', stale ? 'SOURCE STALE' : r.status === 'observing' ? 'MAINNET PUBLIC · LIVE' : 'WARMING UP');
    const notice = document.getElementById('research-notice');
    notice.className = 'notice' + (stale ? ' warning' : '');
    researchText('research-notice', stale ? 'Research data is stale or unavailable. Directional evidence is suspended; account risk controls operate independently.' : `Observation only · ${fmt(r.age_s,1)}s book age · ${m.flow?.complete?'continuous trade coverage':'trade stream warming up or incomplete'} · no research orders submitted.`);
    researchText('research-lean', stale ? 'Unavailable' : m.lean || 'Warming up');
    researchText('research-score', stale ? '—' : fmt(m.score, 0));
    researchColor('research-lean', stale ? null : m.score);
    document.getElementById('lean-marker').style.left = Math.max(0, Math.min(100, 50 + (stale ? 0 : num(m.score)) / 2)) + '%';
    const reasons = document.getElementById('lean-reasons');
    reasons.replaceChildren();
    for (const reason of m.reasons || ['Waiting for live public market evidence']) {
        let li = document.createElement('li');
        li.textContent = reason;
        reasons.append(li)
    }
    researchText('research-invalidation', m.invalidation || 'No calibrated probability. Signals are isolated from demo execution.');
    researchText('research-buys', usd(m.flow?.buy_usd));
    researchText('research-sells', usd(m.flow?.sell_usd));
    researchText('research-flow', fmt(m.flow?.imbalance, 2));
    researchText('flow-coverage', m.flow?.complete ? '60s STREAM' : 'COVERAGE WARM-UP');
    let buy = num(m.flow?.buy_usd),
        sell = num(m.flow?.sell_usd);
    document.getElementById('flow-share').style.width = (buy + sell ? buy / (buy + sell) * 100 : 50) + '%';
    researchText('research-absorption', stale ? 'Unavailable' : m.absorption ? m.absorption + ' · unvalidated' : 'No qualifying evidence');
    researchText('research-mid', usd(m.mid));
    const sentiment = sources.sentiment,
        value = sentiment?.value;
    researchText('sentiment-value', value?.value ?? '—');
    researchText('sentiment-label', sentiment?.stale ? 'Stale published value' : value?.label || 'Source unavailable');
    document.getElementById('sentiment-marker').style.left = (value?.value ?? 50) + '%';
    researchText('sentiment-time', value ? `Published ${stamp(value.published_at)} UTC · cache age ${fmt((sentiment.age_s||0)/60,0)}m` : 'Waiting for a published daily value');
    const walls = m.walls || [];
    researchText('wall-count', walls.length + ' WALLS');
    researchRows('wall-rows', walls.map(x => [{
        text: (x.side === 'bid' ? 'BID ' : 'ASK ') + fmt(x.price),
        className: x.side === 'bid' ? 'positive' : 'negative'
    }, usd(x.usd), fmt(x.persistence_s, 0) + 's']), 3, 'No qualifying large walls in visible depth.');
    researchText('wall-note', `${(m.disappeared_walls||[]).length} previously large levels left visible depth in this sample. Removal is not proof of spoofing. Sampled replenishment: ${usd(walls.reduce((a,x)=>a+num(x.observed_refill_usd),0))}.`);
    let blocks = m.blocks || [];
    researchText('block-count', blocks.length + ' ZONES');
    const bc = document.getElementById('block-cards');
    bc.replaceChildren(...blocks.map(b => researchCard(b.kind + ' · ' + fmt(b.low) + '–' + fmt(b.high), b.wall_confluence ? 'WALL CONFIRMED' : 'PATTERN ONLY', `Confirmed ${stamp(b.confirmed_at)} UTC · ${fmt(b.distance_bps,1)}bps from mainnet mid`, b.wall_confluence ? 'positive' : '')));
    if (!blocks.length) researchEmpty(bc, 'No active closed-candle zones within 10bps of mainnet price.');
    const prints = document.getElementById('large-print-list'),
        large = m.large_trades || [];
    prints.replaceChildren(...large.slice(0, 4).map(t => researchCard(t.side === 'B' ? 'Large aggressive buy' : 'Large aggressive sell', usd(t.usd), `${stamp(t.time)} UTC · ${fmt(t.price)} · trade size does not establish whale identity`, t.side === 'B' ? 'positive' : 'negative')));
    if (!large.length) researchEmpty(prints, 'No executed print ≥$100k in the current 60s window.');
    const wl = document.getElementById('wallet-list');
    wl.replaceChildren();
    for (const a of r.wallets?.accounts || []) {
        let positions = a.positions || [],
            detail = positions.length ? positions.map(p => `${p.coin} ${p.size>0?'long':'short'} ${fmt(Math.abs(p.size),5)}`).join(' · ') : 'No currently visible perp position';
        wl.append(researchCard(a.address.slice(0, 8) + '…' + a.address.slice(-5), a.recent_fills + ' fills / 1h', detail + ' · ' + (a.changes?.previous_at ? (a.changes.deltas.length ? a.changes.deltas.map(x => 'Δ ' + x.coin + ' ' + fmt(x.delta_size, 5)).join(' / ') : 'No size change since prior observation') : 'First observation; size-change baseline pending') + ' · other accounts/hedges unknown'))
    }
    if (!wl.childNodes.length) researchEmpty(wl, r.wallets?.status || 'Waiting for observed public wallets');
    researchText('liquidation-note', `${r.liquidations?.events?.length||0} confirmed watched-wallet liquidations in last hour. No global liquidation feed. ${sources.wallet_watch?.stale?'Wallet data stale.':''}`);
    const context = sources.context,
        c = context?.value;
    researchText('funding-health', context?.stale ? 'STALE' : c ? 'HOURLY' : 'UNAVAILABLE');
    researchText('research-funding', c ? fmt(c.funding_hourly * 100, 5) + '% / h' : '—');
    researchText('research-oi', fmt(c?.open_interest_btc, 2));
    researchText('research-premium', c ? fmt(c.premium * 10000, 2) + ' bps' : '—');
    researchText('research-volume', usd(c?.volume_24h_usd));
    researchText('funding-role', c ? `${c.funding_hourly>=0?'Longs pay shorts':'Shorts pay longs'} at this rate. Funding can reverse; no guaranteed carry or projected APR.` : 'Funding source unavailable; no rate assumed.');
    const d = stale ? null : r.divergence;
    researchText('divergence-net', d ? fmt(d.net_candidate_bps, 2) + ' bps' : '—');
    researchColor('divergence-net', d?.net_candidate_bps);
    researchText('divergence-gross', d ? fmt(d.opening_edge_bps, 2) + ' bps' : '—');
    researchText('divergence-cost', d ? fmt(d.modeled_roundtrip_cost_bps, 1) + ' bps' : '—');
    researchText('divergence-direction', d ? d.direction : 'Recent comparison quotes unavailable');
    researchText('divergence-note', d ? d.assumptions + ' Spot best-quote capacity ' + usd(d.spot_best_quote_capacity_usd) + '. Indicative only; borrow, basis and execution risks remain.' : 'Kraken BTC/USDC spot vs HL perp. No funded hedge or executable arbitrage claim.');
    const health = document.getElementById('research-sources');
    health.replaceChildren();
    for (const [name, source] of Object.entries(sources)) {
        const line = document.createElement('div');
        line.className = 'evidence-line';
        const dot = document.createElement('i');
        dot.className = 'source-dot' + (source.stale || source.error ? ' stale' : '');
        const label = document.createElement('b');
        label.textContent = name.replaceAll('_', ' ');
        line.append(dot, label, document.createTextNode(` · age ${fmt(source.age_s,0)}s · ${source.error|| (source.stale?'stale':'available')}`));
        health.append(line)
    }
    if (!health.childNodes.length) researchEmpty(health, 'Source checks warming up');
    researchBandRender();
    researchResults();
    researchHeatmap();
    renderExperiments(r, data?.performance?.complete_trades)
}
document.querySelectorAll('[data-depth-band]').forEach(button => button.addEventListener('click', () => {
    researchBand = Number(button.dataset.depthBand);
    document.querySelectorAll('[data-depth-band]').forEach(x => x.classList.toggle('selected', x === button));
    researchBandRender()
}));
document.getElementById('research-horizon').addEventListener('change', researchResults);
new ResizeObserver(researchHeatmap).observe(document.getElementById('depth-heatmap'));
setInterval(() => {
    if (typeof data === 'undefined' || !data) return;
    const key = JSON.stringify(data.research || {}) + ':' + (Date.now() / 1000 - data.timestamp > 20);
    if (key !== researchLast) {
        researchLast = key;
        renderResearch(data.research)
    }
}, 1000);
