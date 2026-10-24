# Aegis / HL-Bot

Hyperliquid testnet trading engine and professional monitoring terminal. Runs on existing demo funds only. The trading strategy is **experimental and not proven profitable**; the requested 10% daily return remains an unverified research target.

## What changed

- Persistent **5% account-equity high-water drawdown halt**, including unrealized P&L. Cancel, flatten and verify in a retry loop; keep the dashboard alive. Midnight and restart never reset the peak or release the halt. Market gaps/outages can exceed a trigger threshold.
- Account-mode-aware equity: confirmed unified-account USDC total plus unrealized P&L, with available margin kept separate. Peak tracking starts from the upgrade baseline because the previous bot did not persist a reliable account peak.
- Closed-candle S/R trend pullbacks, rejection confirmation, ATR-based stops and targets that explicitly budget fees, spread and slippage. Post-only entries, reduce-only stop-market exits, five-minute resting-entry expiration, and stale-data admission checks.
- Position size capped at $100 notional and 20% of equity, with estimated risk at most 0.25% of equity per trade and a reservation against remaining drawdown budget. Daily loss gate 2%, one position, 30 entry submissions per UTC day. No martingale or unvalidated runtime parameter fitting.
- Durable SQLite exchange-fill ledger with actual entry/exit fees and persistent equity samples. Legacy trade records remain available as **gross**, separate from net fill accounting. Funding is excluded from realized ledger analytics and clearly labeled; account equity reflects funding effects.
- Responsive Aegis terminal: candlestick/volume chart, 1m/5m/15m views, S/R overlays, order book, recent trades, account/risk summary, positions/orders/searchable fill journal, equity/drawdown charts, cost analytics, strategy diagnostics and CSV export. Explicit stale/disconnected states; local frontend assets.

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
| `AUTO_TRANSFER_SPOT` | Defaults false; transfers are not required for unified accounts |

Dashboard: `http://localhost:8080`. On this host the existing service is managed with `systemctl status/restart/stop hl-bot`. The terminal is read-only. Put authentication at the deployment boundary if exposing account information publicly.

## Verification and research

```bash
python3 -m unittest discover -s tests -v
python3 scripts/healthcheck.py
pip install -r requirements-dev.txt
python3 -m playwright install --with-deps chromium
python3 scripts/browser_check.py
python3 scripts/replay.py --fetch
python3 scripts/monitor.py
python3 scripts/snapshot_perf.py
```

Twenty-one regressions cover risk persistence/exact thresholds, stale/invalid equity, cost accounting, sizing, stop payloads, recovery, dashboard responses/CSV and conservative replay behavior. Real Chromium checks cover desktop/mobile, charts, tabs, filters, chart controls, CSV and offline handling. Browser screenshots are private under `artifacts/`.

[Review and overhaul plan](docs/OVERHAUL.md) contains findings and primary research sources. [Replay results](docs/replay-results.json) use 5,000 BTC 1m testnet bars, fixed parameters, actual fee rates, modeled adverse slippage and funding stress. Results do **not** establish profitability. The initial no-trade diagnostic is preserved; after fixing cost geometry this is not a pristine holdout. No real funds are authorized. Proposed promotion requires 30 days and at least 100 forward complete trades across regimes, positive net expectancy including actual funding, profit factor above 1.2 and drawdown below 5%.

## Risk operations

`data/risk_state.json` contains the persistent peak, daily counters and latched halt. Never delete it or reset the peak to restart trading. A halt requires operator investigation; there is deliberately no automatic or dashboard reset. Check `/api/terminal`, exchange positions/orders and logs to confirm flattening. Keep backups of private `data/ledger.sqlite`, risk state and existing trade history. Healthcheck returns nonzero for halted, disconnected or stale operation.

## Architecture and Graphify

| Module | Responsibility |
| --- | --- |
| `src/bot.py` | Lifecycle, exchange reconciliation, risk enforcement, fill processing |
| `src/exchange/hyperliquid.py` | SDK transport, precision, subscriptions, protected orders, account equity |
| `src/strategy/{sr_detector,scalper,economics}.py` | Closed-candle signals and cost-aware bracket geometry |
| `src/risk/manager.py` | Persistent risk limits, sizing and latched halt |
| `src/reconciler.py` | Protective stop/target validation and recovery |
| `src/learning/ledger.py` | Idempotent exchange-fill accounting and equity history |
| `src/dashboard/` | Read-only Flask/Waitress API and responsive terminal |
| `scripts/replay.py` | Chronological diagnostic replay of live signal rules |

[Graphify](https://github.com/Graphify-Labs/graphify) is installed and its [interactive graph](graphify-out/graph.html) and [machine-readable graph](graphify-out/graph.json) are versioned. Rebuild at each major milestone:

```bash
graphify extract . --code-only --no-cluster
graphify export html
```

`.graphifyignore` excludes secrets, account runtime data and vendored scripts. Extraction is local AST only; documentation relationships are not represented by this mode. See [AGENTS.md](AGENTS.md) for operating rules and [agents.md](agents.md) for module ownership and milestone history. Each major milestone updates documentation and graph, commits and pushes to the existing remote using credentials without printing them.

## Market research (2026-10-23)

A separate read-only observer now studies public **mainnet BTC** data while execution stays on testnet. It tracks sampled walls, symmetric depth, streamed aggressive flow, absorption hypotheses, closed-candle block confluence, large prints/public wallets, wallet-specific liquidations, funding, sentiment and indicative Kraken spot/perp divergence. A persistent journal measures prospective cost-adjusted 10s/1m/5m/15m markouts with unconditional controls. No research signal automatically places orders. See [research definitions and limitations](docs/RESEARCH.md). Dashboard integration follows this backend milestone.

The research workspace is now live in the dashboard: liquidity heatmap, directional evidence, wall persistence, block confluence, large prints and public-wallet size changes, daily sentiment, funding/OI and indicative cross-venue economics. Select 10s/1m/5m/15m outcome horizons and inspect recent event reasons/source health. New markouts are observations with modeled costs, not executed profits. Stale sources suppress directional recommendations. Run the regression suite and `scripts/browser_check.py` to validate both the research and execution terminal. Optional `RESEARCH_WALLETS` supplies up to three comma-separated public addresses; otherwise watch addresses associated with observed large prints. No wallet identity or whole-market liquidation coverage is implied.

Research milestone validation: 41 Python regression tests, JavaScript syntax validation, desktop/mobile Chromium checks, live public-source smoke checks and testnet healthcheck pass. The research journal is collecting real forward observations; initial samples do not establish an edge.

## Experiment overhaul (2026-10-24)

The [prioritized experiment backlog](docs/EXPERIMENTS.md) records nine hypotheses, exact initial rules and unavailable-data prerequisites. Three observation state machines evaluate failed aggression, replenishing wall defense and funding/OI crowding failures; no research orders are authorized. New events measure 30m/1h/4h alongside existing horizons; legacy history is preserved without invented backfills. Cost drag, non-overlapping windows and unconditional drift comparisons distinguish tiny directional moves from net expectancy. Execution accounting now reconstructs only position-continuous complete trades with all USDC entry/exit fees; funding remains excluded. SQLite connections close deterministically. Backend verification: 53 regressions pass. Dashboard integration follows this milestone.

The experiment dashboard is deployed: expandable nine-item roadmap, prerequisite/status labels, 30m/1h/4h horizon controls, signed move/cost drag/net scoreboard, non-overlapping window counts and means, descriptive matched-regime drift comparisons, and complete demo trade accounting. Legacy observations remain unmatched without a recorded regime. Backend and browser changes are covered by **57 regressions**, JavaScript syntax and desktop/mobile Chromium checks. Six hypotheses remain explicitly blocked on missing research inputs; wall consumption also requires cumulative execution attribution. They do not emit signals. No profitability or automatic promotion is claimed.
