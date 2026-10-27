# Systematic trading development plan

Approved 2026-10-27. Execution is testnet only; mainnet research is public and observation-only. No real-fund deployment is included. The 10% daily aspiration is not a sizing input or acceptance criterion. Preserve the persistent 5% equity high-water halt, private evidence, frozen quality-v1 definitions and negative replay diagnostics.

## Delivery sequence and acceptance

| ID | Milestone | Concrete releases | Acceptance and dependencies | Status |
|---|---|---|---|---|
| M1 | Operational reliability | Durable incident timeline, loop heartbeat, recovery state telemetry; fault regressions | Stalled loops distinguishable from live HTTP server; recovery never releases drawdown halt | Implemented foundation; live incident evidence accumulating |
| M2 | Market-data continuity | Validated sorted candle merging; bounded background REST repair; coverage/gap/source diagnostics; eligibility gate | Reconnect/out-of-order/malformed data tested; no fabricated bars; invalid inputs block entries | Implemented foundation; coverage observation ongoing |
| M3 | Complete accounting | Durable submission intents/results, order events, replacement/emergency links; prospective equity bridge with explicit unexplained residual | Exchange IDs only; failures visible; no historical invention; funding/transfer coverage explicit | Implemented foundation; supported cash types only, uncertain-order resolution remains explicit |
| M4 | Execution simulator | Offline versioned replay input; conservative queue/partial-fill/latency/cost assumptions; stress cases and data-gap handling | Quote touch is not proof of fill; deterministic fixtures; no trading client or credentials | Planned; depends on M2/M3 |
| M5 | Validation framework | Versioned hypothesis registry; trial inventory; chronological split with horizon embargo; day-block uncertainty; machine-readable evidence gates | Untouched periods remain separate; missing evidence fails closed; no automatic promotion | Planned; depends on M4 |
| M6 | Regime strategy laboratory | Evaluate frozen trend/range controls; define new liquidity-shock cohorts separately; report abstentions and costs | Preserve quality-v1; new rules require new version/cohort; sufficiently long prospective observation | Existing v1 observing; new evaluations depend on M5 |
| M7 | Creative experiments | Prioritize failed aggression/absorption and crowding; document event/hedge prerequisites for liquidation and arbitrage | Public source health and sequence evidence; unavailable sources remain blocked | Existing detectors observing; expansion gated by M2/M5 |
| M8 | Controlled demo promotion | Written candidate review, immutable configuration, small demo allocation, rollback criteria | Future evidence review and separate implementation required; no auto-promotion or forced trading | Evidence-gated |
| M9 | Decision dashboard | Deliver operational/data/accounting panels with backend releases; add evidence, experiment and capacity views | Desktop/mobile, stale/missing values, safe rendering, no misleading profitability labels | Incremental alongside M1–M7 |
| M10 | Portfolio/capacity research | Offline correlation/concentration, executable depth, joint stress scenarios and expansion proposal | Multiple validated strategies/instruments required; execution remains BTC-only until separate validated change | Evidence/data-gated |

## Working rules

Each major release updates this plan, README.md, agents.md and AGENTS.md, rebuilds Graphify locally, runs relevant unit/failure tests, compilation, live health and browser checks for UI changes, then commits/pushes and confirms remote HEAD/CI. Keep the unrelated CLAUDE.md deletion untouched. Runtime observations, reports and screenshots remain ignored under data/ and artifacts/. Diagnostic samples expire after seven days; important order/accounting/experiment evidence is retained.

Implementation and evidence are separate statuses. Deliver code and reproducible tests immediately where feasible; do not mark a strategy validated because tooling exists, a fixed calendar period elapsed, or a raw signal count was reached. Unavailable prerequisites and future evidence are explicit dependencies, not grounds for fabricated completion. No new funded exchange integrations, secret sharing or mainnet trading are authorized.

## Initial findings

The candle cache previously replaced only the final matching timestamp; a late earlier update appended a duplicate out of order. Reconnect restored subscriptions but did not repair missing bars. The observer requires 60 contiguous closed bars, while the incumbent's admission check was less strict. Repair must address the underlying cache and enforce common data integrity without altering the frozen challenger definitions.

The quote audit links initial brackets by exact returned order IDs but replacement and emergency orders lack durable attribution. API response uncertainty and process crashes require an intent written before submission, followed by append-only observations; an HTTP response alone is not proof of a fill or final cancellation.

## Release progress

- M1/M2 foundation deployed as `1fb6bad`; 91 tests, desktop/mobile browser, live health and GitHub CI passed. Closed-bar coverage restored and observable. Long-run reliability/coverage evidence continues.
- M3 foundation adds durable submission/order lifecycle and a covered prospective equity bridge; 99 regressions. Client-order-ID resolution and unsupported movement normalization are explicit follow-up work, not claimed complete.
