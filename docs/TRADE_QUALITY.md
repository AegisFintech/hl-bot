# Trade quality audit and frozen shadow rules

Deployed 2026-10-26. Version: `quality-v1`. This is prospective observation on the **testnet** BTC feed used by the demo bot. Mainnet research remains separate. No challenger submits orders, fits parameters or promotes itself. The persistent account high-water halt and demo sizing are unchanged.

## Evidence and accounting

Private `data/quality.sqlite` retains candidate decisions (signal, closed-candle context, pre-submission quote, admission reason and returned order IDs), newly received fills, their available arrival quotes, forward fill markouts, five-minute opportunities, challenger outcomes and actual account funding. No full order-book/candle archive is added. Historical ledger fills keep their actual accounting but entry regime/setup/exit stay unknown without recorded evidence. This audit does not invent a historical strategy explanation.

Exchange order IDs join fills to recorded entry, take-profit and stop-loss order roles. These roles describe the submitted order, not an inferred exit cause from profitable/unprofitable price geometry. Manual, recovered or replacement orders without a recorded link remain unattributed. A process crash between exchange submission and result persistence can leave a decision without returned IDs; attribution then remains unknown. Only the first candidate per scan is attempted, as before; the audit does not enumerate every raw S/R level.

Signed entry-price deviation from the requested limit and from the recorded decision mid is measured only when that quote predates the fill. Positive cost means a worse execution price. The decision-mid measure includes movement while waiting in the queue and is not pure slippage. Averages are fill-weighted; partial fills are correlated. Parent orders with any fill are counted against accepted parents, including immature pending orders; this is not a final fill probability or queue model.

Newly received fills get signed mid-versus-fill-price observations at 10/60/300 seconds, with entry/exit/unattributed roles separated. Positive entry markout means subsequent movement in the entry direction. An exit's sign follows its transaction direction, so it is not an additional realized gain. Quotes use atomic cached bid/ask and **local websocket receipt time**, not guaranteed exchange event ordering. Quotes older than 10s, crossed/equal/non-finite quotes and pre-horizon cached observations cannot complete a horizon. More than 10s late is explicitly missed; pending rows survive restart. Sampled markouts do not measure intrabar extremes or actual achievable exits. The observer runs on its own thread and continues during a risk halt; failures do not authorize trading or reset risk state.

## Fixed challenger rules

Observe the first available fresh quote in each UTC five-minute bucket. Persist the bucket so restart cannot select a second opportunity. Store abstention reasons; missing quote periods are outside the observed denominator and are not reconstructed. Missing/stale candle context records an unavailable opportunity and does not create controls/candidates. A crash during multi-row bucket recording can omit candidates; no later backfill is attempted.

Use the latest 60 closed, contiguous one-minute bars. Each OHLC must be positive, finite and internally ordered. The latest closed bar must end within the preceding 120s. Features use the last 21 closes: signed 20-minute displacement, path efficiency (absolute displacement / total absolute changes), and the high/low of the preceding 20 bars, excluding the last bar.

- **Trend:** efficiency ≥0.35 and absolute 20-minute change ≥10bps. Follow the change direction only when the latest closed candle body confirms it. Heuristic movement budget = absolute trailing 20-minute change.
- **Range:** efficiency ≤0.20 and trailing range width ≥20bps. Buy only inside the lower 20% or sell inside the upper 20% of the trailing range. Outside-range quotes abstain. Movement budget = distance to range midpoint.
- **Transition:** abstain.
- Both rules reject spreads above 5bps and require movement budget ≥2 × (13bps + quoted spread). This is an uncalibrated historical-movement heuristic, **not predicted return**. It must be validated before becoming any execution admission filter.

Both unconditional long/short controls are recorded on valid-context opportunities. Actual incumbent candidates are recorded before execution admission on their own scan schedule. They are not synchronized five-minute decisions and must not be presented as a fair head-to-head strategy test. No simulated queue fills, overlapping position sizing or portfolio equity curve is claimed.

Challenger/actual-candidate quote outcomes use the existing 10/60/300/900/1800/3600/14400s journal: bid/ask spread plus fixed 9bps round-trip taker fees and 4bps slippage. Challenger funding is omitted because no future funding rate is supplied. This conservative taker model is distinct from actual passive demo fills. Marking uses received quote time, within the existing 15s horizon tolerance. Reasons, declared horizon sets and missed measurements remain durable. Same-hour regime/direction baseline differences and non-overlapping window means are descriptive; controls may be reused/include later observations, and windows are not independent.

## Funding

A separate daemon reads the public **testnet** `userFunding` endpoint every five minutes when caught up, starting at the earliest imported ledger fill. Backfill is bounded to one day per request/cycle. Responses at the 500-row limit cause time-window splitting; coverage is never advanced on invalid, stalled or capped responses. Successful response rows and coverage advance atomically. A one-hour overlap deduplicates events by timestamp/coin/hash. A dense overlap can stall safely with an explicit error rather than silently skip rows. Coverage describes retrieved API windows, not proof that the upstream never revises late events.

Complete flat-to-flat episodes show separate actual funding and net-after-funding **only** when synchronized coverage spans the whole episode. Funding uses the same coin and `[opened_at, closed_at)` event timestamps. Same-millisecond ordering around opening/closing fills is unresolved. Episode gross/fees/net-before-funding are preserved. No claim of complete account reconciliation is made: transfers, other ledger changes and missing fill history remain separate. Failed/stale synchronization is visible; unknown coverage displays a dash, never an assumed zero.

Official definitions: [funding and ledger API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals), [pagination](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint), [order types](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types).

## Review before any trading change

Freeze v1 during prospective collection. Review calendar-week UTC windows chronologically; do not repeatedly optimize the same weekend. Require a second untouched future period, sufficient non-overlapping episodes, uncertainty estimates with day/block dependence, matched market-regime controls, and explicit consideration of all tested hypotheses. The dashboard's 100-window status is a sample warning, not a promotion gate. Investigate measured execution costs and adverse selection separately from signal quote outcomes. No automatic promotion is implemented. The 10% daily target remains unverified.

Run `python3 scripts/quality_report.py --since EPOCH --until EPOCH` for a read-only UTC calendar-week comparison. It excludes outcomes not measured by the requested cutoff; output is JSON to stdout. Save private snapshots only under artifacts/. A rule change requires a new version **and a separate database/cohort**, not mixing v2 outcomes into v1.
