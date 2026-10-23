# Repository operating instructions

## Scope and current state

This is an actively running Hyperliquid **testnet** bot. User authorizes review, research, implementation, service pause/restart, strategy changes, testing, commits and pushes. Public mainnet market/account reads are authorized for research; **no mainnet orders or real funds are authorized**. The current implementation includes a demo execution terminal and an isolated observation-only research workspace. See agents.md for module responsibilities and milestone history.

## Invariants

- Never expose or commit .env credentials. Runtime account/research data and screenshots remain ignored under data/ and artifacts/.
- Preserve unrelated user changes, including the existing CLAUDE.md deletion.
- Enforce persistent 5% account equity high-water drawdown halt, including unrealized losses. Never reset peak or unlock a halt at midnight/restart. Cancel orders, attempt closes even when cancellation fails, and verify/retry. Gaps/outages can exceed a trigger threshold.
- Risk baseline is the first trustworthy upgrade snapshot, not an invented historical peak. Do not delete risk state to resume trading.
- Target 10% daily is unverified. Prior replay is negative; do not size from this target, claim profitability or introduce real capital.
- Keep unvalidated runtime parameter fitting disabled. Preserve docs/replay-initial-diagnostic.json and docs/replay-results.json.
- `src/research` must never receive keys, import the trading client or submit orders. Promotion requires separate evidence and implementation; it is never automatic.
- Never conflate mainnet research with testnet charts/account metrics, large prints with known whale identity, sampled depth with the complete book, or watched-wallet liquidation events with a global feed.
- Research score and divergence candidates must be suppressed on stale/malformed data. Sentiment age includes its publication timestamp. Forward markouts are quote-based with assumed costs and correlated samples, not fills, actual profits or calibrated win probabilities. Preserve reasons, outcomes, source times, missed horizons and wallet baselines.

## Verification

- `python3 -m unittest discover -s tests -v` — current baseline **41** regression tests.
- `python3 -m compileall -q src scripts main.py config.py`.
- `python3 scripts/healthcheck.py` — local execution health; nonzero on halt/stale/unavailable state.
- Browser: install requirements-dev.txt and Chromium (`python3 -m playwright install --with-deps chromium`), run demo service, then `python3 scripts/browser_check.py`. It validates desktop/mobile, existing terminal controls, research band/horizon controls, and stale/disconnected handling. Screenshots are private under artifacts/.
- Public research smoke: GET local `/api/research`; check mainnet trade-stream coverage, book age and individual source health. New/reconnected trade streams warm up for 60s before imbalance/absorption evidence is eligible.
- Optional RESEARCH_WALLETS supplies at most three public addresses; empty enables bounded large-print discovery. No external funded exchange account is connected.

## Milestone workflow

Every major milestone: update README.md, agents.md and this file, rebuild Graphify, commit and push using credentials without exposing them. Use local deterministic extraction; no external LLM required:

```bash
graphify extract . --code-only --no-cluster
graphify cluster-only . --no-label --no-viz
graphify export html
```

`.graphifyignore` excludes credentials, runtime data and vendored scripts. Track graphify-out/graph.json, graph.html and GRAPH_REPORT.md explicitly; caches remain ignored. Confirm remote HEAD/CI after pushing. Full research definitions and operational limitations are in docs/RESEARCH.md; initial overhaul findings are in docs/OVERHAUL.md.
