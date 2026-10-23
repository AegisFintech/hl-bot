# Public market research — 2026-10-23

## Scope and separation

Observe real public BTC market conditions; execute no research orders anywhere. Existing execution remains Hyperliquid testnet only, with the persistent 5% risk halt. The research package has no trading-client import, signing key, funded secondary account or signal-promotion path. Mainnet read access is market research, not permission to trade real funds.

## Implemented hypotheses

| Component | Evidence | Interpretation and limits |
| --- | --- | --- |
| L2 depth imbalance | Bid/ask dollar liquidity in 5/10/25bps bands; coverage flags | Score uses symmetric *observed* price distance so truncated books are not treated as complete. Standard feed is aggregated depth, not all orders. |
| Resting walls | Level >=100,000 USD and >=3x median level size | Track sampled persistence; reset after >15s gaps. Disappearance does not prove cancellation intent/spoofing. |
| Absorption | >=100,000 USD aggressive pressure, signed imbalance beyond 0.25, <2bps adverse price progress over >=45s, persistent opposing wall | Bullish/bearish research hypothesis; level replenishment is a sampled residual using observed executions, not hidden-order identification. |
| Executed flow | Deduplicated mainnet trade WebSocket; rolling 60s dollars | Requires 60s uninterrupted stream warmup; no biased recent-trades polling substitute. Queue overflow/reconnect invalidates coverage. |
| Large prints and wallet watch | Executions >=100,000 USD; associated public addresses | Up to two addresses automatically selected from fresh large prints every 120s; optional RESEARCH_WALLETS overrides, maximum three. Identity, other accounts and hedges are unknown. |
| Liquidations | Liquidation ledger entries for watched public wallets, last hour | Confirmed account events only. No fabricated market-wide liquidation map or global liquidation-exhaustion signal. |
| Candle order blocks | Existing three-candle detector applied to closed mainnet bars | Confirm only after following candle closes; drop invalidated and >6h zones. Persistent wall overlap is confluence, not proof of institutional inventory. |
| Funding, OI, premium | Mainnet BTC asset context | Variable hourly rate, not a guaranteed APR or directional prediction. |
| Sentiment | Alternative.me daily Fear & Greed, source timestamp | Background regime context; stale source visibly flagged. No fast trade from the daily index. |
| Cross-venue divergence | HL perp vs Kraken BTC/USDC spot best quotes | Indicative candidate only. Model four legs, 4.5bps HL and assumed conservative 60bps Kraken per leg, plus 2bps slippage/leg; exit basis assumed zero. No executable arbitrage/hedge claim. |

The directional score is 40 × symmetric depth imbalance + 35 × valid executed-flow imbalance + 25 × absorption direction. Bullish >=25, bearish <=-25, otherwise neutral. Missing flow contributes no directional weight. Scores are fixed heuristics, **not probabilities**. Confluence is shown separately to avoid counting correlated candle evidence twice. Stale books suppress the score and divergence candidate.

## Prospective measurement

Private SQLite research journal persists signal-time bid/ask/mid, reason, direction, fixed funding context and markouts at 10/60/300/900 seconds. Entries and exits use the relevant bid/ask, subtract 9bps total taker fees and 4bps total slippage, and apply an absolute frozen-rate funding debit stress when available. No funding credit is assumed. These are quote-based proxies, not executions or realized returns. Mid-price favorable/adverse excursions are sampled, not intrabar extremes.

Late markouts (>15s after a horizon) are marked missed rather than filled with future data. Pending observations survive restart. Long and short unconditional five-minute controls expose drift; samples overlap and are correlated, so displayed positive-rate is not a calibrated win probability. No automatic promotion or parameter fitting. Store observation summaries every 15s; retain seven days of those summaries, while event/outcome history persists. No reliable backfill is invented for wall persistence or absorption before collection began.

## Source and operating details

- [Hyperliquid streams](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions): mainnet BTC trades stream, public data only.
- [Hyperliquid info API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint): sampled L2 every ~5s; market context and closed candles every ~60s; watched wallets every ~120s.
- [Kraken public L2](https://docs.kraken.com/api-reference/market-data/get-order-book): BTC/USDC comparison every ~15s. Coinbase's USDC/USD product returned 404 in source checks, so use direct same-quote Kraken spot rather than assuming fiat parity.
- [Alternative.me](https://alternative.me/crypto/fear-and-greed-index/): hourly cache of daily published sentiment; attribution/link appears on dashboard.
- [Funding mechanics](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding): hourly funding, variable rates.
- [Order-flow price impact research](https://arxiv.org/abs/1011.6402): plausible market mechanism in equities; neither proof of crypto prediction nor net profitability.

Sources time out after five seconds and report failure/age rather than replacing data with zeros. Observer failures are isolated from execution; the account's risk state is never reset. Inspect `/api/research` and the dashboard research section. Runtime data is ignored under data/research.sqlite. Never interpret observations as actionable mainnet orders.
