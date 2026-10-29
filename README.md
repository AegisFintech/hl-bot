# Aegis / HL-Bot

Hyperliquid **testnet** trading engine and monitoring terminal. Runs on demo funds only; no mainnet orders. Strategies are selected by fee-inclusive out-of-sample backtests, which are simulations, not a profit guarantee. The 10% daily figure remains an unverified aspiration and is not a sizing input.

## What it does (2026-10-29 overhaul)

- **Closed-bar strategy engine** (`STRATEGY`, default Donchian 20/10 breakout on 1h bars across BTC, ETH and SOL). Four pre-declared strategy families share one decision path between live trading and the backtester. See [docs/STRATEGY.md](docs/STRATEGY.md).
- **Always protected execution:** marketable IOC entries; one reduce-only stop-market order per position sized to the actual fill; stops move place-then-cancel and only tighten; exits close before cancelling stops. A position whose stop cannot be placed is closed.
- **Risk:** stop-out loses `RISK_PER_TRADE_PCT` of equity (default 0.5%, max 2%), per-position and gross leverage caps, `MAX_POSITIONS`, optional daily loss gate. A **drawdown breaker** flattens at `DRAWDOWN_LIMIT_PCT` (5%) from the peak, waits `BREAKER_COOLDOWN_HOURS` (12h), re-bases the peak and resumes automatically (operator decision 2026-10-29).
- **Operational resilience:** startup retries instead of exiting; operational pauses keep protected positions and resume after three healthy checks with decaying backoff; websocket watchdog reconnects silent streams; rate-limited, retrying info reads; the dashboard serves cached snapshots and never calls the exchange.
- **Visibility:** every bar-close decision records a per-coin reason (signal, blocking admission reason, unfilled entry, protection result) in the terminal, `/api/strategy` and the healthcheck.
- Durable fill ledger, execution journal, quality audit, equity bridge and the isolated mainnet research observer are retained.

## Run

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Configure the master wallet and authorized API signing wallet locally.
python3 main.py
```

| Environment variable | Purpose |
| --- | --- |
| `HL_MASTER_ACCOUNT` | Master wallet address holding demo funds |
| `HL_API_PRIVATE_KEY` | Authorized API wallet signing key; never commit |
| `HL_TESTNET` | Must be `true`; application refuses mainnet startup |
| `STRATEGY`, `STRATEGY_PARAMS`, `STRATEGY_INTERVAL`, `TRADE_COINS` | Strategy family, JSON parameters, bar interval, markets |
| `RISK_PER_TRADE_PCT`, `MAX_POSITIONS`, `MAX_LEVERAGE_PER_POSITION`, `MAX_GROSS_LEVERAGE` | Sizing and exposure caps |
| `DRAWDOWN_LIMIT_PCT`, `BREAKER_COOLDOWN_HOURS`, `BREAKER_AUTO_RESET` | Drawdown breaker |
| `DAILY_LOSS_LIMIT_PCT`, `MAX_DAILY_ENTRIES`, `ENTRY_SLIPPAGE_PCT`, `STOP_SLIPPAGE_PCT` | Optional gates and execution bounds |

All settings and defaults are in `.env.example`. Dashboard: `http://localhost:8080`. The service is managed with `systemctl status/restart/stop hl-bot`; `deploy/hl-bot.service` is a reference unit with `Restart=always`. The terminal is read-only. Put authentication at the deployment boundary if exposing account information publicly.

## Strategy research

```bash
python3 scripts/fetch_history.py --source binance --coins BTC,ETH,SOL --interval 1h --since 2021-01 --funding
python3 scripts/fetch_history.py --source binance --coins BTC,ETH,SOL --interval 4h --since 2021-01
python3 scripts/strategy_research.py --source binance --coins BTC,ETH,SOL --intervals 1h,4h
python3 scripts/account_history.py 0xYourMasterWallet --network testnet
```

The research script ranks pre-declared candidates on in-sample data only, sizes risk against the breaker, reports every candidate out of sample with a deflated Sharpe, writes `docs/strategy-research.json` and prints suggested `.env` lines. Nothing is applied automatically. **Status:** not yet run on real history (the development sandbox had no network access); the shipped default is a conventional starting point, not a selected result.

## Verification

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src scripts main.py config.py
python3 scripts/healthcheck.py
pip install -r requirements-dev.txt && python3 -m playwright install --with-deps chromium
python3 scripts/browser_check.py
```

177 regressions cover strategy decisions and causal indicators, the live engine (bar validation, persistence, adoption, catch-up), backtester execution conventions, sizing parity, protected entries/exits/stop moves, breaker trip/cooldown/re-base, operational recovery, startup retries, exchange price/lot rules, request retries, websocket replay/watchdog, dashboard snapshot isolation and the earlier accounting/research/quality suites.

## Risk operations

`data/risk_state.json` holds the peak, daily counters, breaker/pause state and a bounded `events` audit (trips, resets, migrations). Do not delete it; the breaker resumes on its own after the cooldown once flat. `data/strategy_state.json` holds per-coin position metadata (stop, best price, bars held); exchange positions always win over it. Healthcheck returns nonzero while the breaker is cooling down, during operational recovery, at startup or with stale data, and prints the resume time. See [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Architecture and Graphify

| Module | Responsibility |
| --- | --- |
| `src/bot.py` | Lifecycle, resilient startup, breaker/recovery cycles, bar-close strategy cycle, fills |
| `src/settings.py` | Environment-driven settings and validation |
| `src/strategy/{indicators,library,engine}.py` | Causal indicators, strategy decisions, live bar validation and position metadata |
| `src/executor.py` | IOC entries, stop protection and reconciliation, exits |
| `src/exchange/hyperliquid.py` | SDK transport, request budget/retries, price/lot rules, subscriptions, account equity |
| `src/risk/manager.py` | Breaker, operational pause, admission reasons and shared position sizing |
| `src/validation/backtest.py` | Event-driven backtester on the live decision path |
| `src/learning/*` | Fill ledger, execution journal, quality audit, funding and equity bridge |
| `src/dashboard/` | Read-only Flask/Waitress API and terminal |
| `src/strategy/{scalper,sr_detector,economics}.py`, `scripts/replay.py` | Retired scalper kept for the preserved replay diagnostics and the research observer |

[Graphify](https://github.com/Graphify-Labs/graphify) output is versioned in `graphify-out/`. Rebuild at each major milestone:

```bash
graphify extract . --code-only --no-cluster
graphify cluster-only . --no-label --no-viz
graphify export html
```

`.graphifyignore` excludes secrets, account runtime data and vendored scripts. See [AGENTS.md](AGENTS.md) for operating rules and [agents.md](agents.md) for module ownership and milestone history.

## History

The sections below describe earlier milestones. The scalper, permanent 5% halt and flatten-on-every-incident recovery they mention were replaced on 2026-10-29; earlier trade records remain gross/legacy as described.

### Market research (2026-10-23)

A separate read-only observer now studies public **mainnet BTC** data while execution stays on testnet. It tracks sampled walls, symmetric depth, streamed aggressive flow, absorption hypotheses, closed-candle block confluence, large prints/public wallets, wallet-specific liquidations, funding, sentiment and indicative Kraken spot/perp divergence. A persistent journal measures prospective cost-adjusted 10s/1m/5m/15m markouts with unconditional controls. No research signal automatically places orders. See [research definitions and limitations](docs/RESEARCH.md). Dashboard integration follows this backend milestone.

The research workspace is now live in the dashboard: liquidity heatmap, directional evidence, wall persistence, block confluence, large prints and public-wallet size changes, daily sentiment, funding/OI and indicative cross-venue economics. Select 10s/1m/5m/15m outcome horizons and inspect recent event reasons/source health. New markouts are observations with modeled costs, not executed profits. Stale sources suppress directional recommendations. Run the regression suite and `scripts/browser_check.py` to validate both the research and execution terminal. Optional `RESEARCH_WALLETS` supplies up to three comma-separated public addresses; otherwise watch addresses associated with observed large prints. No wallet identity or whole-market liquidation coverage is implied.

Research milestone validation: 41 Python regression tests, JavaScript syntax validation, desktop/mobile Chromium checks, live public-source smoke checks and testnet healthcheck pass. The research journal is collecting real forward observations; initial samples do not establish an edge.

### Experiment overhaul (2026-10-24)

The [prioritized experiment backlog](docs/EXPERIMENTS.md) records nine hypotheses, exact initial rules and unavailable-data prerequisites. Three observation state machines evaluate failed aggression, replenishing wall defense and funding/OI crowding failures; no research orders are authorized. New events measure 30m/1h/4h alongside existing horizons; legacy history is preserved without invented backfills. Cost drag, non-overlapping windows and unconditional drift comparisons distinguish tiny directional moves from net expectancy. Execution accounting now reconstructs only position-continuous complete trades with all USDC entry/exit fees; funding remains excluded. SQLite connections close deterministically. Backend verification: 53 regressions pass. Dashboard integration follows this milestone.

The experiment dashboard is deployed: expandable nine-item roadmap, prerequisite/status labels, 30m/1h/4h horizon controls, signed move/cost drag/net scoreboard, non-overlapping window counts and means, descriptive matched-regime drift comparisons, and complete demo trade accounting. Legacy observations remain unmatched without a recorded regime. Backend and browser changes are covered by **57 regressions**, JavaScript syntax and desktop/mobile Chromium checks. Six hypotheses remain explicitly blocked on missing research inputs; wall consumption also requires cumulative execution attribution. They do not emit signals. No profitability or automatic promotion is claimed.

### Storage and log retention — 2026-10-24

SQLite retains all exchange fills, signal reasons/outcomes (including missed horizons), source timestamps and wallet baselines for accounting and research. Diagnostic observations are compact minute samples retained seven days; repeated walls, prints, blocks and heatmaps stay in memory rather than being copied into every stored snapshot. Equity remains detailed for 30 days, then keeps each hour's minimum/maximum equity, maximum peak and final sample. This chart compaction never changes `data/risk_state.json` or unlocks a halt. A fill-time index speeds recent-fill reads. SQLite connections retain durable default synchronization.

File logs rotate weekly (seven days), retaining four archives, with compression after one cycle. Install `logrotate` and enable `logrotate.timer`; copy `deploy/hl-bot.logrotate` into `/etc/logrotate.d/hl-bot` and `deploy/logging.conf` into `/etc/systemd/system/hl-bot.service.d/logging.conf`, then daemon-reload/restart. Watched handlers reopen renamed files; the systemd override sends stdout/stderr to journald instead of duplicating the file log. The timer must run for rotation to occur. Journald retention is managed by the host separately. Agent audit history is retained as important operational evidence.

`scripts/compact_storage.py` is an **offline** migration: stop the bot first. It creates private one-time `data/*.pre-retention.sqlite` backups, compacts existing observations/equity, vacuums reclaimed pages and checks integrity. Backups remain ignored and are not duplicated on each run. Core learning/accounting tables are not pruned; future retention of those requires evidence-preserving aggregation. Verification: 60 regression tests, including retention boundaries and file rotation reopening.

### Trade-quality audit and shadow challengers — 2026-10-26

The dashboard now shows prospective **testnet** order attribution, entry/exit forward fill markouts, execution-price benchmarks, skipped-opportunity reasons and frozen trend/range quote challengers with unconditional controls. Historical entry conditions remain unknown. A separate read-only testnet funding collector supplies actual funding and episode net-after-funding only where API coverage spans the complete trade. Accounting and research evidence live in private `data/quality.sqlite`; no full quote/book archive is added. Demo execution rules, sizing and the persistent 5% halt are preserved. See [fixed rules, evidence definitions and review requirements](docs/TRADE_QUALITY.md); no challenger places orders or tunes itself. Actual incumbent candidates use a different schedule, so comparisons are descriptive rather than matched head-to-head profitability tests.

Trade-quality validation: **73 regression tests**, Python compilation, desktop/mobile Chromium with audit fixtures, missing funding, shadow horizon controls and stale/disconnected handling. `python3 scripts/quality_report.py --since EPOCH --until EPOCH` exports a read-only UTC calendar-week report; outcomes observed after the cutoff are excluded. Reports/screenshots stay private under artifacts/.

### Operational recovery — 2026-10-27

Temporary execution failures now use a persistent **execution recovery pause**, separate from the permanent 5% equity drawdown halt. Rejected/incomplete protection, uncertain order submission, failed protection cancellation and startup reconciliation failures block entries and activate account-wide cancel/flatten/verification. Recovery resumes only after confirmed flat/no orders, positive fresh account equity, fresh testnet quotes, three successful checks spaced at least 15 seconds apart and a persisted cooldown (60 seconds initially, increasing to a 30-minute maximum after repeated incidents). Failed/stale checks reset the success sequence. A restart cannot clear the pause or a risk halt. Read-only health checks fail during recovery.

The dashboard distinguishes `RECOVERING` from `HALTED` and displays confirmed cleanup status and retry time. Decimal lot-size truncation preserves exact exchange-sized positions, fixing repeated under-sized protection replacements caused by binary floating-point flooring (for example, 0.00007 BTC becoming 0.00006). Recovery re-reads exposure after cancellation before replacing orders. The reviewed legacy testnet network-upgrade rejection was moved explicitly into the new recovery workflow after verifying flat exposure; the high-water equity was preserved. Exchange maintenance can still prevent execution or flattening; the bot retries and never promises uninterrupted fills.

Validation: **84 regression tests**, Python compilation, desktop/mobile Chromium including recovery/drawdown dashboard fixtures, and live execution health. See [operational recovery](docs/OPERATIONS.md).

### Development roadmap and data continuity — 2026-10-27

The approved ten-milestone delivery plan is [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md), with explicit implementation versus future-evidence gates. The first reliability/data release adds a persistent loop heartbeat and incident boundaries, validated sorted/deduplicated closed candles, bounded background REST repair with backoff, reconnect quote invalidation and a shared candle-integrity entry gate. The terminal displays coverage, missing bars, rejected updates, repair status and incident timelines. Missing bars are never fabricated. Diagnostic heartbeat state is bounded; important incident history is retained. Validation baseline: **91 tests**.

### Prospective lifecycle and equity reconciliation — 2026-10-27

Order requests now retain durable submission intent, exact returned order IDs and deduplicated exchange status events, including recovery brackets and emergency closes. Failed intent persistence blocks new exposure; it never blocks an emergency close/cancel. Uncertain outcomes remain unresolved rather than blindly resubmitted. An independent public testnet history collector and fixed prospective account baseline support an equity bridge across fills, USDC fees, funding, known cash movements and unrealized P&L. Missing coverage/unsupported movements remain explicit. The terminal shows unexplained residuals and request/event evidence. See [docs/ACCOUNTING.md](docs/ACCOUNTING.md). Baseline: **99 regressions**; no change to strategy sizing or persistent risk peak.

### Offline research tools and evidence readiness — 2026-10-27

The terminal now shows all ten development milestones and the hypothesis/prerequisite inventory from [docs/RESEARCH_REGISTRY.json](docs/RESEARCH_REGISTRY.json). Offline tools provide a conservative passive-entry/fixed-horizon simulation, chronological protocol/cohort review and aligned portfolio/capacity diagnostics:

```bash
python3 scripts/research_evaluate.py simulate docs/examples/simulation.json
python3 scripts/research_evaluate.py review docs/examples/review.json
python3 scripts/research_evaluate.py portfolio docs/examples/portfolio.json
```

Examples are synthetic formats, not market evidence. The simulator requires trade volume and explicit queue/latency assumptions; quotes alone cannot establish fills. It does not yet model full brackets/cancel races or calibrated live queues. Reviews preserve source separation, observation cutoffs, horizon embargo, declared trials and dependent-day uncertainty, and never auto-promote. Portfolio diagnostics never change allocation. Full contracts, limitations and pending work: [docs/VALIDATION.md](docs/VALIDATION.md) and [development plan](docs/DEVELOPMENT_PLAN.md). Validation baseline: **117 regressions**, compilation, Chromium desktop/mobile, all three CLI formats and live health. No sizing, risk-peak or real-fund changes.

## Local verification and delivery

Builds, compilation and applicable tests run locally. GitHub CI is disabled. Each completed change set is committed and merged into `main`, then pushed with remote HEAD verification; changes made directly on `main` need no redundant merge. Major milestones also update documentation and rebuild Graphify.
