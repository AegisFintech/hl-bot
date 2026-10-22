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
