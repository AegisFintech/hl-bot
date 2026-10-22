# Trading overhaul — 2026-10-22

## Mandate
Use existing Hyperliquid testnet funds only. Target 10% daily is an aspiration, not an established edge or sizing input. Maximum equity drawdown is 5% from a persistent high-water mark including unrealized PnL. Cancel orders, flatten positions and latch the halt on breach. Market gaps, outages and execution latency can exceed a threshold; it cannot guarantee a loss ceiling.

## Review findings
- Risk default was 10%; kill threshold 15%; midnight reset erased peak equity; restart erased all risk state. A kill stopped the loop without liquidating.
- Available margin was mistaken for equity. Account abstraction must be queried explicitly to avoid double counting unified USDC.
- Stops were trigger-limit orders with a tiny buffer, vulnerable to remaining unfilled.
- A USD 80 BTC target and USD 20 stop ignored volatility and costs. Account fee API reports maker 1.5bps / taker 4.5bps per side. A USD 80 move at USD 84,000 is only 9.52bps before costs.
- Latest 2,000 exchange fills: gross realized -5.608055 USDC, fees 9.193680 USDC, net -14.801735 USDC before funding. Local 122-trade report claimed +0.278778 gross and omitted fees; these have different windows and are not comparable.
- Local trade Sharpe multiplied per-trade dollar PnL by sqrt(252), which is not an annualized return Sharpe.
- Missing tests, deployment checks, cost-aware replay, stale-feed gating, durable fill identity, and coherent account analytics.
- Existing Graphify output is present but stale and ignored by Git. Preserve the unrelated pre-existing deletion of CLAUDE.md and untracked runtime data.

## Milestones
1. Review and research: this plan, secure Git workflow, reproducible Graphify graph and operating instructions.
2. Risk and execution: persistent 5% halt, correct equity, freshness gates, risk-based sizing, fee-aware volatility brackets, safe stop execution, fill ledger and regression tests.
3. Professional terminal: responsive chart, live depth/tape, equity/drawdown, exposures, orders/fills/journal, costs and expectancy, strategy diagnostics, clear freshness/error states and CSV export.
4. Validation and deployment: chronological replay with costs and conservative ambiguous-bar assumptions, browser desktop/mobile tests, testnet API smoke checks, service restart, updated graph/docs, final commit and push.

## Acceptance and promotion
All automated regressions and browser checks must pass. Verify testnet endpoints and no secret tracking. No martingale, no drawdown reset at midnight, no mainnet deployment. Use fixed, conservative defaults and do not optimize repeatedly on the holdout. Keep a chronological forward demo evaluation; require at least 100 closed trades and 30 days across regimes, positive net expectancy and profit factor >1.2 after actual fees/funding, and drawdown below 5% before even considering real funds. These are proposed research gates, not proof of future returns. No available short run can validate 10% per day.

## Research and design sources
- [Hyperliquid fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees): model both entry and exit fees; query actual account rates.
- [Order types](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types): post-only entries and reduce-only stop-market exits.
- [Account abstraction](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/account-abstraction-modes): distinguish standard and unified equity.
- [TradingView account manager](https://www.tradingview.com/support/solutions/43000786138-what-is-the-account-manager/): summary equity/margin/PnL and separate positions, orders, history and journal.
- [Kraken Pro interface](https://support.kraken.com/au/articles/kraken-pro-trading-interface-guide): dense modular chart/book layout, depth bars, tooltips and market ribbon.
- [Probability of backtest overfitting](https://escholarship.org/uc/item/4w1110bb): avoid treating selected historical winners as evidence of a durable edge.
- [Graphify](https://github.com/Graphify-Labs/graphify): local deterministic code graph; exclude credentials and runtime data.

## Milestone 2 implementation
Implemented persistent risk state with exact 5% breach, zero-equity loss handling, no daily peak reset, latched halt and repeated cancel/flatten recovery. Actual account mode is `unifiedAccount`; equity uses spot USDC total plus perp unrealized PnL, never available margin. Actual account rates initialize execution economics. Stop-market protection, post-only entries, size rounding downward, 0.25% maximum risk budget per trade and remaining-drawdown reservation now gate orders. Closed candle trend/rejection, ATR/noise-floor brackets and net reward/risk filters replace fixed-dollar economics. Disable unvalidated tuning overlays and in-sample live learning. A SQLite fill ledger provides idempotency and exact fee-inclusive realized fill accounting. Legacy gross trade journal is preserved and labeled.

Validation: 11 regression tests passed covering persistent/midnight risk, zero/stale/invalid equity, corrupt state, sizing, fee accounting, unified equity, downward size rounding and stop order payloads. Real demo API smoke confirms unified equity and fee rates; legacy resting orders cancelled during the maintenance pause.

## Milestone 3 implementation
Replaced the dashboard with the Aegis terminal: responsive dark layout, local TradingView candlesticks/volume with 1m/5m/15m aggregation and S/R toggle, live order depth and trade tape, equity/net P&L/exposure/drawdown tiles, searchable positions/orders/fill journal, persisted equity/drawdown chart, strategy gate reasons and execution analytics. Read-only CSV export includes actual fees; raw fill data uses DOM text nodes. Shared five-second API cache limits browser fanout. Disconnected/stale/error states are explicit. No fabricated chart data or returns. Funding exclusion and closing-fill statistics are labeled; complete trade statistics are not inferred from partial fills.

Validation: 15 Python regressions pass; Chromium desktop (1512x1100) and mobile (390x844) pass chart rendering, tabs, filtering, timeframe, level toggle, fit view, CSV download, overflow and disconnected-state checks with zero page errors. Browser screenshots are private under artifacts/.

## Milestone 4 — validation and deployment

Final local suite: 20 regressions, including cancellation failure that must still close exposure, halt short-circuit, stop-market geometry/side, ambiguous replay bars and non-fills. Added secret-free GitHub Actions regression workflow, read-only deployment healthcheck, cost-inclusive hourly snapshots and corrected CLI monitoring. SDK version pinned to the verified 0.24.0 transport. Startup hydrates history to avoid a one-minute blind wait; stale pending-order maintenance is throttled. Recovery preserves existing stop/target prices on partial-fill resizing and rejects stop-limit protection. Expected post-only entry rejection backs off; accepted entries with incomplete brackets latch a halt. Emergency cleanup covers the account's instruments, keeps attempting closes after cancellation failures, and confirms orders/positions against the exchange.

Signed demo smoke: an approximately 12 USDC distant post-only entry plus TP/SL was accepted (`resting`, `waitingForFill`, `waitingForFill`). Cancelled immediately; exchange confirmed zero orders and zero positions. No real funds or mainnet order endpoints used.

### Research outcome

5,000 chronological testnet one-minute bars (~3.5 days), split 70/30. The initial diagnostic produced no fills: 160 of 164 candidates failed net reward/risk economics, four failed the one-bar fill assumption. Preserved at `replay-initial-diagnostic.json`. Corrected the analytical target floor to solve `(target - costs)/(stop + costs) >= 1.5`, modeled five-minute resting entries, aligned replay UTC resets with simulation time, and charged entry fees at fill. These are implementation corrections after observing the first sample, so the later segment is explicitly **not a pristine holdout**. No parameter sweep or historical winner selection was performed.

Final diagnostic (`replay-results.json`):

| Segment | Closed simulated trades | Net USDC | Return | Max sampled drawdown | Profit factor |
| --- | ---: | ---: | ---: | ---: | ---: |
| First 70% | 12 | -1.081568 | -0.1102% | 0.1266% | 0.5019 |
| Later 30% | 4 | -0.923609 | -0.0941% | 0.0941% | 0.0000 |

The strategy has **not** demonstrated an edge. Engineering improvements are deployed for tightly capped forward demo evaluation, not promoted as a profitable strategy. Do not scale risk or introduce real capital based on these results. Actual funding is not imported into fill-based P&L; equity includes it. Replay uses a modeled funding debit and cannot reproduce book queue priority, true spread history, exchange outages or intrabar account equity. Replay cash starts at cutover demo equity, not an inferred historical balance.

### Subsequent research gates

Collect execution observations under fixed parameters and preserve an untouched future validation window. Study whether trend pullback candidates show favorable post-entry markouts after all costs before allocating more turnover. Measure fill probability, adverse selection, stop slippage, fee/funding drag and complete-trade expectancy by regime. Reject negative-expectancy variants instead of widening leverage. Any future strategy revision must receive a separate version, chronological comparison and risk regression checks; the current 10% daily target has no supporting evidence. Thirty days and 100 complete forward trades are minimum proposed samples, not a guarantee or automatic mainnet permission.

Operational baseline: approximately 981.069527 USDC at cutover; persistent peak initialized from observed account equity because the legacy bot did not preserve a valid account-level high-water series. Drawdown threshold triggers recovery but cannot guarantee an exact 5% realized ceiling during gaps/outages. Keep runtime state and fills backed up. Pre-existing CLAUDE.md deletion is preserved uncommitted; private data and credentials are not tracked.

Dashboard serving uses in-process Waitress (eight threads) so the bot reference remains available without a development server or unsafe multi-process state assumptions.
