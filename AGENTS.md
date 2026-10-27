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

- `python3 -m unittest discover -s tests -v` — current baseline **117** regression tests.
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

## Experiment backend milestone — 2026-10-24

Current baseline: **53 regressions**. Fixed experiment definitions and unimplemented data dependencies are in docs/EXPERIMENTS.md. New signals have 30m/1h/4h outcomes; preserve legacy per-signal horizon sets. Non-overlapping windows remain dependent; unconditional baseline differences are not matched-regime alpha. Flat-to-flat execution episodes require position continuity and USDC fees and exclude funding. No detector submits orders or promotes itself.

## Experiment dashboard milestone — 2026-10-24

Current baseline: **57 regressions**. Verify nine expandable experiment cards, explicit unavailable-data prerequisites, 4h horizon, matched-control missing states and complete-trade accounting in desktop/mobile browser checks. Matched comparisons may reuse same-hour control pools and include later observations; they are descriptive, not a tradable input or causal proof. Six experiments and wall-consumption mode are blocked pending the documented data. Failed research cycles/comparison sources must suppress cached candidates even while the last quote is recent.

## Storage retention milestone — 2026-10-24

Current baseline: **60 regressions**. Preserve fills, signals/outcomes, missed horizons, source times, wallet baselines and agent audit history. Only diagnostic observations expire after seven days and equity older than 30 days is compacted to hourly minimum/maximum equity, maximum peak and last sample. Never use chart compaction to alter risk state. Offline migration must stop the bot, back up databases and check integrity. Weekly log rotation requires installed logrotate, its enabled timer and the checked-in journald service override to prevent duplicate file writes; retain four archives. Watched handlers must reopen renamed logs.

## Trade-quality milestone — 2026-10-26

Preserve `data/quality.sqlite` decisions, fill markouts, opportunity denominators and funding coverage. Challenger v1 rules are frozen in docs/TRADE_QUALITY.md; changes require a new version and prospective evidence. Testnet quote challengers must never be conflated with mainnet research or actual fills. Attribute orders by returned exchange ID; unknown historical/replacement exits remain unknown. Funding-adjusted episode results require full retrieved coverage and use explicit [open,close) timestamps. Never substitute zero for unavailable funding. Quote times are local websocket receipts; pre-horizon/stale/malformed cached quotes cannot complete markouts. The observer and funding collector cannot place orders, tune execution or change risk state. Incumbent candidates and five-minute challengers have different selection schedules; no matched head-to-head claim.

Trade-quality validation: **73 regression tests**, Python compilation, desktop/mobile Chromium with audit fixtures, missing funding, shadow horizon controls and stale/disconnected handling. `python3 scripts/quality_report.py --since EPOCH --until EPOCH` exports a read-only UTC calendar-week report; outcomes observed after the cutoff are excluded. Reports/screenshots stay private under artifacts/.

## Operational continuity milestone — 2026-10-27

Current baseline: **84 regressions**. Operational `execution_paused` is distinct from `halted`; only the former can auto-resume after persisted cooldown, three fresh successful exposure/account/feed checks at least 15s apart, flat positions and no orders. Reset successful-check counts on failed/stale confirmation. Preserve peak and every permanent risk halt. Retry delay increases from 60s to at most 1800s across incidents and restarts. Explicit review of a specific legacy protective-order halt is never automatic startup/midnight migration; retain its private before/after audit under data/. Do not turn exchange outages into a promise of continuous fills. Verify Decimal lot truncation preserves already exact sizes and never rounds new exposure upward. Browser checks cover `RECOVERING`, confirmed-flat cleanup and permanent drawdown `HALTED` wording.

## Roadmap M1/M2 foundation — 2026-10-27

Baseline **91 regressions**. Preserve docs/DEVELOPMENT_PLAN.md implementation/evidence statuses. Never synthesize missing candles. Closed bars must be finite, valid OHLC and minute-aligned; deduplicate/sort late updates. REST repairs only merge bars closed when the request began. Malformed updates require repair before eligibility. Background repair is bounded/backed off and must not submit orders. Retain incident boundaries; heartbeat singleton must distinguish a stalled loop from HTTP availability. No restart/midnight risk release. Browser covers operations panel, data degradation and disconnected state.

## Roadmap M3 accounting foundation — 2026-10-27

Baseline **99 regressions**. Preserve `data/execution.sqlite` intent/results/events, account baseline and retrieved coverage. Never resend ambiguous orders automatically or infer order roles from price. Entry intent persistence is required; audit failure must not prevent cancellation/flatten attempts. An unresolved intent is not proof of an open order. Bridge `within_tolerance` is provisional arithmetic, not an audited completeness guarantee; unsupported account event types/fees remain unknown. Retain explicit (baseline,end] boundary limitations and source coverage. Seven-day minute samples must never alter risk state. Historical features and quotes remain unknown.

## Offline research and readiness milestone — 2026-10-27

Baseline **117 regressions**. Offline validation has no network/signing/trading pathway. Never describe docs/examples synthetic outputs as market results. Passive-horizon-v1 is not a full TP/SL strategy simulator; queue/latency/participation/funding are supplied assumptions, and missing paths suppress profit results. Sparse markouts cannot substitute for real execution traces. Protocol changes require new hashes/versions and untouched future cohorts. Day bootstrap, declared trial adjustment and planning sample thresholds are limited review aids, not proof of independence/edge. Mixed actual/quote/simulated cohorts must be rejected. All review and portfolio outputs prohibit automatic promotion/allocation; M8/M10 remain evidence-gated. README/plan/registry/dashboard statuses must distinguish foundations from completion. Preserve final pre-submission candle and quote rechecks after slow account reads.
