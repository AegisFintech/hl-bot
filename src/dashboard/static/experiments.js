'use strict';
// Roadmap and actual execution accounting use the shared cached payload.
function renderExperiments(research, completed) {
    const experiments = research.experiments || [];
    const catalog = document.getElementById('experiment-catalog');
    catalog.replaceChildren();
    for (const experiment of experiments) {
        const card = document.createElement('details');
        card.className = 'experiment-card';
        const summary = document.createElement('summary');
        const title = document.createElement('b');
        title.textContent = `P${experiment.priority} · ${experiment.title}`;
        const status = document.createElement('span');
        status.className = 'badge muted';
        status.textContent = experiment.status.startsWith('blocked') ? 'DATA REQUIRED' : 'OBSERVING';
        summary.append(title, status);
        const mechanism = document.createElement('p');
        mechanism.textContent = experiment.mechanism;
        card.append(summary, mechanism);
        for (const [label, value] of [['Status', experiment.status], ['Rule', experiment.rule], ['Invalidation', experiment.invalidation]]) {
            const p = document.createElement('p');
            const strong = document.createElement('b');
            strong.textContent = `${label}: `;
            p.append(strong, document.createTextNode(value));
            card.append(p);
        }
        catalog.append(card);
    }
    if (!experiments.length) researchEmpty(catalog, 'Experiment definitions unavailable. No inferred status.');
    researchText('experiment-count', `${experiments.length} HYPOTHESES`);
    researchText('complete-count', completed ? fmt(completed.count, 0) : '—');
    researchText('complete-gross', usd(completed?.gross_pnl));
    researchText('complete-fees', usd(completed?.fees));
    researchText('complete-expectancy', usd(completed?.expectancy));
    researchColor('complete-expectancy', completed?.expectancy);
    researchText('complete-scope', completed ? `${completed.scope} Complete-episode net: ${usd(completed.net_pnl)}. Slippage and funding are not separately attributed.` : 'Complete-trade accounting unavailable. Incomplete position histories are excluded.');
}
