# Modules and milestone history

## Execution and risk (2026-10-29)

| Module | Current responsibility |
| --- | --- |
| `src/bot.py` | Lifecycle; dashboard-first resilient startup; breaker flatten/cooldown/re-base cycle; operational recovery with protected positions; bar-close strategy cycle; fills/order events |
| `src/settings.py` | Environment settings (strategy, coins, sizing, breaker, execution bounds) and validation |
| `src/strategy/indicators.py` | Causal EMA, Wilder ATR/RSI, Donchian prior/trailing channels, rate of change |
| `src/strategy/library.py` | `donchian`, `ema_trend`, `tsmom`, `rsi_reversion`; pure closed-bar decisions; stops only tighten |
| `src/strategy/engine.py` | Live bar validation (gaps, malformed, unpublished), per-coin position metadata persistence, adoption, catch-up, per-coin reasons |
| `src/executor.py` | IOC entries sized by risk, one reduce-only stop per position, place-then-cancel stop moves, close-then-cancel exits, orphan/resting-order cleanup |
| `src/exchange/hyperliquid.py` | Testnet SDK transport, info request budget and retries, 5-significant-figure price rules, Decimal lot truncation, deduplicated subscriptions with replay, websocket watchdog, account-mode-aware equity, API-wallet expiry |
| `src/risk/manager.py` | Drawdown breaker with audited auto-reset after cooldown, operational pause with decaying escalation, explicit admission reasons, shared `position_size` |
| `src/validation/backtest.py` | Event-driven multi-market backtest of the live decision path with fees, slippage, funding and breaker |
| `src/learning/ledger.py` | Durable idempotent actual-fee fill accounting and equity history |
| `src/learning/evaluator.py` | Preserved legacy gross journal; live parameter fitting is disabled |
| `src/strategy/{scalper,sr_detector,economics}.py` | Retired 1m scalper; kept for preserved replay diagnostics and the research observer's S/R blocks |

Execution uses demo funds only. The breaker threshold triggers a flatten but cannot guarantee an exact realised ceiling through gaps/outages. `src/reconciler.py` and the unused, non-functional `src/agent/` LLM tuner were removed on 2026-10-29.

## Public market observer

| Module | Current responsibility |
| --- | --- |
| `src/research/microstructure.py` | Sampled L2 depth, walls, streamed executed pressure, absorption hypotheses and closed-candle block confluence |
| `src/research/service.py` | Public mainnet BTC stream, source freshness, large-print wallet discovery, observed-wallet position/ledger reads, sentiment/funding and indicative Kraken comparison |
| `src/research/journal.py` | Persistent prospective 10s/1m/5m/15m quote markouts, fixed cost assumptions, sampled excursions, missed horizons, unconditional controls and wallet size baselines |
| `src/dashboard/` | Read-only demo account terminal plus a clearly separated mainnet research workspace; shared cached API, CSV fills export, source health and per-event explanations |

The observer has no signing keys or trading client and never submits orders. Scores are uncalibrated heuristics; large prints do not establish whale identity, watched-wallet liquidation counts are not a global feed, and modeled divergence is not executable arbitrage. Definitions: [RESEARCH.md](docs/RESEARCH.md).

## Completed milestones

- 2026-10-22: review/research plan, persistent 5% risk/execution overhaul, professional terminal, negative chronological replay and deployment audit. Final expiration-race fix: `9563c8c`. Twenty-one regressions and desktop/mobile checks passed. See [OVERHAUL.md](docs/OVERHAUL.md) and preserved replay reports.
- 2026-10-23: isolated public-market observer and prospective journal, committed/pushed as `7226b36`.
- 2026-10-23: research dashboard, wallet size changes, per-event cost explanations, source publication-age validation, source failure suppression and browser coverage. **41 regression tests**, JavaScript syntax, desktop/mobile Chromium and public-source/testnet health checks pass. Observer is deployed in observation mode; no profitability claim or signal promotion.

Every major milestone must update README.md, AGENTS.md, this file and Graphify, then commit and push. Credentials/runtime data/screenshots remain private. Preserve the pre-existing uncommitted CLAUDE.md deletion.

- 2026-10-24 backend milestone: `src/research/experiments.py` owns fixed observation-only state machines/catalog; service candidate selection extracted from collection. Journal stores each event's eligible horizons and reports cost drag/non-overlapping windows/unconditional drift diagnostics. `src/storage.py` owns connection lifetime; `src/learning/trades.py` reconstructs position-continuous flat-to-flat fee-inclusive episodes. 53 regressions pass. Full prioritized backlog and remaining data prerequisites: [EXPERIMENTS.md](docs/EXPERIMENTS.md).

- 2026-10-24 dashboard/validation milestone: readable research.js plus dedicated experiments.js roadmap/accounting renderer; extended horizon and cost/benchmark scoreboard, descriptive matched-hour/regime controls, source-failure suppression and complete-trade metrics. **57 regressions** and desktop/mobile checks pass. Six catalog ideas and wall-consumption mode remain blocked pending stated data prerequisites; no trading promotion.

## Storage retention milestone — 2026-10-24

`src/research/journal.py` stores compact seven-day minute diagnostics; event evidence remains durable. `src/learning/ledger.py` compacts equity older than 30 days to hourly min/max, peak and last observations without touching risk state or fills. `src/logging_setup.py` supplies watched handlers; `deploy/` contains weekly four-archive logrotate and journald service configuration. `scripts/compact_storage.py` performs offline backup/compaction/integrity validation. Baseline: 60 regressions. Keep one-time private migration backups ignored; retain agent audit and full research/accounting records.

## Trade-quality milestone — 2026-10-26

`src/learning/quality.py` owns closed-candle regimes, frozen v1 quote challengers, decision/order-ID attribution, prospective fill markouts and execution/funding display accounting. `src/learning/funding.py` reads only testnet public funding on an independent daemon, validates/paginates/deduplicates rows and persists coverage. `src/bot.py` captures candidate decisions/results and new fills and feeds a separate observer thread through atomic cached BBO snapshots. `src/dashboard/static/quality.js` renders the testnet-only audit. Definitions and limitations: docs/TRADE_QUALITY.md. Runtime evidence is private `data/quality.sqlite`; historical contexts remain unknown, no fitted parameters or promotion.

Trade-quality validation: **73 regression tests**, Python compilation, desktop/mobile Chromium with audit fixtures, missing funding, shadow horizon controls and stale/disconnected handling. `python3 scripts/quality_report.py --since EPOCH --until EPOCH` exports a read-only UTC calendar-week report; outcomes observed after the cutoff are excluded. Reports/screenshots stay private under artifacts/.

## Operational continuity milestone — 2026-10-27

`src/risk/manager.py` persists operational pause/reason/deadline/recovery count independently from durable risk halts. `src/bot.py` cancels/closes/verifies account exposure and requires three successful fresh checks at least 15s apart plus cooldown before operational resume; failures reset the checks. `src/reconciler.py` activates recovery on cancellation/protection failures and refreshes positions before replacement. `src/strategy/scalper.py` pauses on ambiguous submission or incomplete accepted brackets. `src/exchange/hyperliquid.py` uses Decimal downward lot truncation, preserving exact lots. Terminal and health check distinguish recovery from permanent risk halt. A specific legacy upgrade rejection was explicitly reviewed while flat; no automatic legacy halt migration runs at startup. Persistent peak/drawdown state retained. 84 regression tests plus Chromium desktop/mobile recovery and drawdown fixtures. See docs/OPERATIONS.md.

## Roadmap M1/M2 foundation — 2026-10-27

`docs/DEVELOPMENT_PLAN.md` tracks all ten milestones and evidence dependencies. `src/operations.py` stores one loop heartbeat and retained incident boundaries; observation gaps are not exact downtime. `src/market/candles.py` validates, deduplicates and sorts bounded bars without forward filling. Client merges REST closed bars without overwriting websocket forming bars; rejected updates inhibit eligibility until successful repair. A dedicated background thread repairs gaps with bounded REST/backoff independently from execution. The scalper shares the 60-closed-bar integrity gate. Dashboard and health expose heartbeat/data readiness. 91 regressions; private runtime DB `data/operations.sqlite`.

## Roadmap M3 accounting foundation — 2026-10-27

`src/learning/execution.py` persists intent-before-request, uncertain outcomes, exact coin/order-ID roles and nested exchange status events. Client request wrappers fail closed for unaudited entries, but always attempt exposure-reducing actions. Quality joins recovery/emergency exits without inventing parent features. `src/learning/accounting.py` independently retrieves public testnet fill/movement windows and computes a prospective equity bridge only at covered snapshot cutoffs. Important evidence persists; detailed bridge samples are minute-bounded for seven days. Unsupported movements, non-USDC fees and residuals require review. Dashboard exposes lifecycle and bridge states. 99 tests plus desktop/mobile browser fixtures. Full limitations: docs/ACCOUNTING.md.

## Roadmap offline foundations and decision views — 2026-10-27

`src/validation/simulator.py` models hypothetical passive-entry partial fills from aggressive volume with supplied queue/latency/participation and a costed fixed-horizon exit; gaps suppress profit results. It cannot replace full bracket/cancel-race replay or real queue calibration. `src/validation/evidence.py` validates supplied protocol hashes, future observation cutoffs, source cohorts, chronological embargo and non-overlap/day-block uncertainty with trial adjustment; manual review only. `src/validation/portfolio.py` uses common observed dates and unlevered diagnostic weights for correlation, joint stress, supplied-history drawdown and declared depth participation. None imports the trading client or promotes/allocates. `scripts/research_evaluate.py` exposes offline JSON workflows. Synthetic examples and docs/RESEARCH_REGISTRY.json make data/evidence blockers explicit. Read-only /api/development and terminal show all milestone states. Scalper rechecks candle/quote integrity after account admission reads. 117 regressions; docs/VALIDATION.md specifies pending real traces, bracket races, uncertain-intent resolution and future cohorts.

## Delivery workflow — 2026-10-27

User requires local builds, compilation and tests instead of GitHub CI. Removed the automatic GitHub Actions regression workflow. Commit each completed change set, integrate it into main and push; direct main commits already satisfy integration. Verify remote HEAD without triggering CI. Preserve the unrelated CLAUDE.md deletion.

## Strategy engine overhaul — 2026-10-29

Operator decisions: replace the scalper freely with the best out-of-sample fee-inclusive strategy, allow up to ~1% risk per trade across several coins, and make the drawdown halt auto-reset after a cooldown. Implemented the closed-bar engine, IOC/stop executor, auto-reset breaker, protected operational pauses, resilient startup, request budget/retries, websocket watchdog, cached dashboard snapshots and bounded summary queries. Research tooling: `scripts/fetch_history.py`, `scripts/strategy_research.py` (pre-declared candidates, in-sample selection, deflated Sharpe, printed settings) and `scripts/account_history.py`. Research could not run in the sandbox (no egress); the default Donchian 20/10 1h is provisional. 177 regressions; see docs/STRATEGY.md and docs/OPERATIONS.md.
