# Modules and milestone history

## Execution and risk

| Module | Current responsibility |
| --- | --- |
| `src/exchange/hyperliquid.py` | Testnet SDK transport, precision, account-mode-aware equity, BBO/L2/candle/trade subscriptions, protected orders |
| `src/strategy/sr_detector.py` | S/R clustering and candle-pattern order blocks; patterns do not identify institutional orders |
| `src/strategy/scalper.py` | Closed-candle trend pullback/rejection candidates; post-only entry admission, freshness and exposure checks |
| `src/strategy/economics.py` | ATR/noise-floor brackets and fee/spread/slippage reward/risk geometry |
| `src/risk/manager.py` | Persistent account high-water peak, exact 5% latched halt, daily loss/entry limits and conservative sizing |
| `src/reconciler.py` | Validate protective stop-market/target side and size; preserve protective prices during partial-fill recovery |
| `src/bot.py` | Lifecycle, fill handling, stale-entry expiration, cancel/flatten/verify retries and observer startup |
| `src/learning/ledger.py` | Durable idempotent actual-fee fill accounting and equity history |
| `src/learning/evaluator.py` | Preserved legacy gross journal; live parameter fitting is disabled |

Execution uses demo funds only. Drawdown peak/halt survives midnight and restart. The threshold triggers recovery but cannot guarantee an exact realized ceiling through gaps/outages. No risk-state deletion or automated halt reset. The requested 10% daily return remains unproven.

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
