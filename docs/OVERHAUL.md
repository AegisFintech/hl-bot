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
