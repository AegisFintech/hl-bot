# Repository operating instructions

This is an actively running Hyperliquid **testnet** bot. User authorizes review, implementation, service pause/restart, strategy changes, testing, commits and pushes. Never expose or commit .env credentials. No mainnet actions are authorized.

- Preserve unrelated user changes, including the existing CLAUDE.md deletion.
- Risk: persistent 5% equity high-water drawdown halt; never reset peak or unlock a halt at midnight/restart. Include unrealized losses. Cancel orders and flatten on breach; execution may overshoot during outages/gaps.
- Target 10% daily is unverified; never size from it or claim guaranteed returns.
- Every major milestone: update README.md, agents.md and this file, rebuild Graphify, commit and push.
- Use `python3 -m unittest discover -s tests -v` for regression tests. Add meaningful risk/execution coverage.
- Graphify: `graphify extract . --code-only --no-cluster`, then `graphify export html`. Exclude .env/data/vendor scripts via .graphifyignore. Track graphify-out/graph.json and graphify-out/graph.html explicitly; caches stay ignored.
- Architecture and milestone status are in docs/OVERHAUL.md and agents.md.

Current milestone: review and research complete; risk/execution implementation next.

Milestone 2 complete: risk/execution regressions pass. Runtime state is private under data/. Unsupported account modes and corrupt risk state fail closed. Do not remove an existing halt or risk state to restart trading. Next: dashboard and research replay.

Milestone 3 complete: dashboard Python and Chromium checks pass. Browser verification: install requirements-dev.txt, `python3 -m playwright install --with-deps chromium`, run service, then `python3 scripts/browser_check.py`. Screenshots under artifacts/ are private. Next: research replay and final deployment audit.

Final implementation milestone: 20 regressions; desktop/mobile Chromium; accepted signed testnet bracket followed by verified cancellation; service restart/health verification. Research remains negative and must not be described as profitable. Preserve docs/replay-initial-diagnostic.json and docs/replay-results.json. Risk baseline is the first trustworthy cutover account snapshot, not a reconstructed historical peak. Refresh report with `graphify cluster-only . --no-label --no-viz` after extraction, then export HTML; no external LLM is required. CI runs Python regressions; browser checks are local against the running demo service.

Final race audit: expired entries cancel parent orders individually and force reconciliation before removing children only when confirmed flat. This preserves protection if an entry filled since cached position sync. Twenty-one regression tests now pass, including this case.
