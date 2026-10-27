# Prospective order lifecycle and equity bridge

Deployed 2026-10-27. All observations are from the demo testnet account. `data/execution.sqlite` is private, ignored and retains important order/accounting evidence. Historical unlinked fills remain unknown. Nothing here changes equity high-water enforcement or authorizes additional exposure.

## Durable requests and events

Execution writes a UUID submission intent before sending entry requests. If that write fails, no new entry is sent. Responses retain returned exchange IDs and roles for initial entry/TP/SL, replacement TP/SL and emergency close. Cancellation requests/results are recorded separately; a cancel response is not an independently verified terminal exchange state. Websocket nested order updates are preserved and deduplicated by their canonical payload hash, including exchange status timestamp and local receipt time. Both instrument and order ID identify attribution.

Timeouts are explicit uncertain outcomes, not reasons to blindly resend. An intent without a persisted response remains unresolved even if subsequent evidence suggests completion; this conservative state requires inspection. No client-order-ID recovery or full historical order-status collector is claimed. A crash between exchange acceptance and response persistence may leave an unattributed fill. An emergency close or cancellation must still be attempted if the audit database is unavailable. New entry audit failures enter the existing safe execution recovery path.

The trade-quality audit joins recovered/emergency exit roles by exact returned IDs. It does not infer a parent entry or invent entry features; execution price benchmarks still require a genuine recorded pre-fill decision quote. Fill accounting remains in the separate durable fill ledger.

## Prospective equity reconciliation

The immutable reconciliation baseline is the first trustworthy snapshot for this release, independent from the existing risk baseline and peak. Positive finite equity and finite unrealized P&L are required. Keep at most one account sample per minute for seven days; retain the baseline, fills, funding, movements, coverage and order evidence.

A separate public testnet collector retrieves time-windowed fills and non-funding ledger events. It validates timestamps/finite fill values, splits capped windows and advances coverage only after persistence. Small overlapping windows allow recent records to be retrieved again idempotently. Fill imports never fabricate arrival quotes or change their exchange time. API history availability and late revisions limit completeness; retrieved coverage is not independent proof that the exchange returned every event. Funding retains its existing independent collector/coverage.

Select the latest account sample covered by all three retrieval cursors (fills, non-funding ledger and funding). From the fixed baseline to that sample calculate:

`equity change = realized P&L − USDC fees + funding + known cash movements + change in unrealized P&L + unexplained residual`

Use `(baseline,end]` event timestamps; same-millisecond event ordering and non-atomic REST snapshot boundaries remain unresolved. Simple USDC deposit/withdraw records without an explicit nonzero fee are recognized. All unsupported movements (including currently unclassified internal/spot transfers or liquidations) remain unknown and force review. Non-USDC fees, coverage errors, missing baseline funding coverage or residual exceeding 0.0001 USDC also prevent `within_tolerance`. `within_tolerance` is an arithmetic diagnostic, not an audited completeness guarantee. No later covered sample means warming up, not zero P&L/residual. Residuals are never used to alter fills or risk equity.

The dashboard displays coverage cutoff, each component, unexplained residual, unknown submission count and request/event details. It explicitly marks unavailable, warming, review and disconnected states. Snapshot lag is expected because collectors deliberately retrieve historical windows and funding synchronization is periodic.

Public endpoints and time-window limits: [Hyperliquid info API](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint). The installed official Python SDK provides `user_non_funding_ledger_updates`; unsupported event schemas are intentionally not guessed.
