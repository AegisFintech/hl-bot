'use strict';
let qualityPayload = null;
function qualityRows(id, rows) {
    const body = document.getElementById(id);
    body.replaceChildren();
    if (!rows.length) rows = [['No prospective measurements yet']];
    for (const row of rows) {
        const tr = document.createElement('tr');
        for (const value of row) {
            const td = document.createElement('td');
            td.textContent = value == null ? '—' : String(value);
            tr.append(td);
        }
        body.append(tr);
    }
}
function renderQuality(payload, disconnected=false) {
    qualityPayload = payload || {};
    const q = qualityPayload;
    const observing = q.status === 'observing' && !disconnected;
    text('quality-status', observing ? 'TESTNET · OBSERVING' : 'TESTNET · STALE / UNAVAILABLE');
    text('quality-decisions', q.decisions == null ? '—' : `${q.decisions} / ${q.admitted}`);
    text('quality-fills', q.parents_with_any_fill == null ? '—' : `${q.parents_with_any_fill} / ${q.admitted}`);
    text('quality-cost', q.execution?.decision_mid_cost_bps == null ? '—' : `${fmt(q.execution.decision_mid_cost_bps)} bps`);
    text('quality-funding', q.funding_state ? usd(q.funding_usdc) : '—');
    const f = q.funding_state;
    text('quality-funding-scope', f ? `Funding coverage: ${stamp(f.start_ms)} to ${stamp(f.through_ms)} UTC. ${f.error || (Date.now()/1000-f.updated>660 ? 'Synchronization catching up / stale' : 'Last synchronization healthy')}. Entry cost is fill-weighted decision-mid deviation, including queue-time market movement. Parent counts include pending/partial orders; they are not a final fill rate.` : 'Funding unavailable; never assumed zero. Entry execution benchmarks require recorded pre-fill decision quotes.');
    qualityRows('quality-attribution', (q.groups || []).map(g => [g.regime,g.setup,g.exit_reason,g.count,fmt(g.gross_pnl,4),fmt(g.fees,4),fmt(g.net_pnl,4)]));
    qualityRows('quality-markouts', (q.markouts || []).filter(m => m.n || m.missed).map(m => [m.role,`${m.horizon}s`,m.n,m.missed,fmt(m.mean_bps)]));
    const horizon = Number(document.getElementById('quality-horizon').value);
    const names = {baseline:'Unconditional control',shadow_trend_v1:'Trend continuation v1',shadow_range_v1:'Range reversion v1',incumbent_candidate_v1:'Actual incumbent candidate'};
    qualityRows('quality-challengers', (q.challenger?.results || []).filter(r => r.horizon === horizon).map(r => [names[r.kind] || r.kind,r.direction===1?'Long':'Short',r.n,r.nonoverlap_n,fmt(r.mean_net_bps),fmt(r.nonoverlap_mean_net_bps),`${fmt(r.matched_delta_bps)} / ${r.matched_n ?? 0}`,r.review_status]));
    const opportunities = q.opportunities || [];
    text('quality-opportunities', `Five-minute observations: ${opportunities.reduce((n,r)=>n+r.n,0)}. ${opportunities.map(r=>`${r.regime}: ${r.reason} (${r.n})`).join(' · ')}. Movement budget is a heuristic, not predicted return. Actual incumbent candidates use a different selection schedule; this is not a matched head-to-head test. Matched delta is a descriptive same-hour/regime baseline difference, not causal alpha; controls may include later observations. Short outcomes are correlated; compare future chronological periods without retuning.`);
    const reasons = document.getElementById('quality-reasons');
    reasons.replaceChildren();
    for (const d of q.recent_decisions || []) {
        const p = document.createElement('p');
        p.textContent = `${stamp(d.time)} UTC · ${d.side} · ${d.regime} · ${d.reason}`;
        reasons.append(p);
    }
    qualityRows('quality-episodes', (q.recent || []).slice().reverse().map(t=>[stamp(t.closed_at),t.regime,fmt(t.net_pnl,4),fmt(t.funding_usdc,4),fmt(t.net_after_funding,4)]));
    text('quality-scope', `${q.scope || 'Quality audit unavailable; historical conditions remain unknown.'} Prospective collection began ${stamp(q.started_at)} UTC. Quote outcomes are not fills or a portfolio backtest. Missing funding coverage displays —.`);
}
document.getElementById('quality-horizon').addEventListener('change', () => renderQuality(qualityPayload, typeof data === 'undefined' || !data || Date.now()/1000-data.timestamp>20));
