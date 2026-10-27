# Execution continuity and recovery

## Incident reviewed on 2026-10-27 UTC

At 2026-10-26 02:41:05 UTC, Hyperliquid testnet rejected protection with `Only post-only orders allowed immediately after network upgrade`. The old reconciler latched a permanent risk halt. The position subsequently closed at 02:43:03, but the bot intentionally never released that latch, leaving execution stopped and the dashboard suggesting active cleanup even after exchange-confirmed flat exposure.

Earlier replacement churn had a separate local cause: binary float multiplication followed by flooring could truncate an exact 0.00007 BTC lot to 0.00006. Every reconciliation detected that size mismatch and replaced the same protection. Decimal truncation from the input string now preserves exact lots and still rounds genuinely fractional lots down. Exchange size precision follows the asset's `szDecimals`: [official lot-size documentation](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size).

Live review found zero positions/orders, equity 980.042469 USDC, persistent peak 982.046801 and drawdown approximately 0.2041%. A deliberate operator-authorized review migrated only this identified protective-order halt into a recovery pause; the private before/after record is `data/operational-reviews.jsonl`. The peak was not reset. No general restart-time halt release or deletion of risk state was introduced.

## Two separate safety states

- **Risk halt:** `halted`, including 5% high-water drawdown or unreadable state. Always blocks entries and activates cleanup. Never automatically clears, even if equity later recovers, the day changes or the process restarts.
- **Execution recovery:** `execution_paused`, for protection rejection/exception, unconfirmed protection cancellation, ambiguous submission, incomplete accepted bracket or startup reconciliation failure. Also blocks entries and activates cleanup. Persists the cause, deadline and incident count. The terminal displays `RECOVERING`, cleanup result and earliest retry time.

Cancel failure must not prevent attempting a close. Cleanup enumerates full account exposure and known instruments, cancels, attempts close, cancels again and then independently retrieves positions, orders and account equity. It retries no faster than five seconds; request duration can lengthen this interval. Recovery's successful-check counter resets if confirmation fails, exposure/orders remain, equity is nonpositive or quotes are older than ten seconds. Three successful checks must be at least fifteen seconds apart. The operational cooldown is 60s, 120s, 240s, etc., capped at 1800s; incident count persists conservatively and is not reset at midnight. Restart restarts the successful-check sequence while retaining the deadline. Final resume also requires fresh equity, drawdown below the limit and no permanent halt.

These are successful read/flat checks, not proof that every exchange order type is currently accepted. If maintenance still rejects the next real demo bracket, the bot returns to recovery with a longer cooldown. It does not send speculative probe orders. Safe abstention and recovery take precedence over forced continuous exposure. Exchange outages, restricted order modes, gaps and failed closes can prevent immediate flattening or exceed a trigger threshold.

Protection replacement re-reads positions after cancellation, avoids replacing already closed exposure and requires two acknowledged resting trigger IDs. Invalid/rejected responses enter recovery. Entry submission exceptions are treated as ambiguous outcomes and enter recovery rather than blindly retrying the order.

## Verification and operation

Run the repository regression suite, compilation, `python3 scripts/browser_check.py` against the service, and `python3 scripts/healthcheck.py`. Health returns nonzero while operational recovery, permanent halt, stale feeds/equity or API errors are present. The dashboard distinguishes a confirmed-flat halt from exposure still being closed. Observe `bot.log` and private state for the cause and persisted deadline; never delete the risk file to resume trading.

Regression coverage includes exact lot idempotence/downward truncation, recovery persistence/backoff, stale equity/quotes, failed confirmation, open orders, cancellation failure, closure during replacement, three-check resume and permanent drawdown rejection of auto-resume. Browser fixtures cover automatic recovery text and operator-required drawdown text on the existing desktop/mobile terminal.
