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

Twenty regressions cover risk persistence/exact thresholds, stale/invalid equity, cost accounting, sizing, stop payloads, recovery, dashboard responses/CSV and conservative replay behavior. Real Chromium checks cover desktop/mobile, charts, tabs, filters, chart controls, CSV and offline handling. Browser screenshots are private under `artifacts/`.

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
