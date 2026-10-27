# Systematic trading development plan

Approved 2026-10-27. Execution is testnet only; mainnet research is public and observation-only. No real-fund deployment is included. The 10% daily aspiration is not a sizing input or acceptance criterion. Preserve the persistent 5% equity high-water halt, private evidence, frozen quality-v1 definitions and negative replay diagnostics.

## Delivery sequence and acceptance

| ID | Milestone | Concrete releases | Acceptance and dependencies | Status |
|---|---|---|---|---|
| M1 | Operational reliability | Durable incident timeline, loop heartbeat, recovery state telemetry; fault regressions | Stalled loops distinguishable from live HTTP server; recovery never releases drawdown halt | Implemented foundation; live incident evidence accumulating |
| M2 | Market-data continuity | Validated sorted candle merging; bounded background REST repair; coverage/gap/source diagnostics; eligibility gate | Reconnect/out-of-order/malformed data tested; no fabricated bars; invalid inputs block entries | Implemented foundation; coverage observation ongoing |
| M3 | Complete accounting | Durable submission intents/results, order events, replacement/emergency links; prospective equity bridge with explicit unexplained residual | Exchange IDs only; failures visible; no historical invention; funding/transfer coverage explicit | Implemented foundation; supported cash types only, uncertain-order resolution remains explicit |
| M4 | Execution simulator | Offline versioned replay input; conservative queue/partial-fill/latency/cost assumptions; stress cases and data-gap handling | Quote touch is not proof of fill; deterministic fixtures; no trading client or credentials | Offline foundation implemented; real trace capture/queue calibration/full bracket races pending |
| M5 | Validation framework | Versioned hypothesis registry; trial inventory; chronological split with horizon embargo; day-block uncertainty; machine-readable evidence gates | Untouched periods remain separate; missing evidence fails closed; no automatic promotion | Offline protocol/cohort review implemented; actual precommitted future cohort pending |
| M6 | Regime strategy laboratory | Evaluate frozen trend/range controls; define new liquidity-shock cohorts separately; report abstentions and costs | Preserve quality-v1; new rules require new version/cohort; sufficiently long prospective observation | Frozen v1 observing; inventory registered; future review pending |
| M7 | Creative experiments | Prioritize failed aggression/absorption and crowding; document event/hedge prerequisites for liquidation and arbitrage | Public source health and sequence evidence; unavailable sources remain blocked | Observers/inventory retained; unsupported feeds explicitly blocked |
| M8 | Controlled demo promotion | Written candidate review, immutable configuration, small demo allocation, rollback criteria | Future evidence review and separate implementation required; no auto-promotion or forced trading | Evidence-gated; offline review cannot promote |
| M9 | Decision dashboard | Deliver operational/data/accounting panels with backend releases; add evidence, experiment and capacity views | Desktop/mobile, stale/missing values, safe rendering, no misleading profitability labels | Operational/data/accounting/readiness dashboard deployed |
| M10 | Portfolio/capacity research | Offline correlation/concentration, executable depth, joint stress scenarios and expansion proposal | Multiple validated strategies/instruments required; execution remains BTC-only until separate validated change | Offline aligned/capacity diagnostics implemented; expansion evidence-gated |

## Working rules

Each major release updates this plan, README.md, agents.md and AGENTS.md, rebuilds Graphify locally, runs relevant unit/failure tests, compilation, live health and browser checks for UI changes, then commits/pushes and confirms remote HEAD/CI. Keep the unrelated CLAUDE.md deletion untouched. Runtime observations, reports and screenshots remain ignored under data/ and artifacts/. Diagnostic samples expire after seven days; important order/accounting/experiment evidence is retained.

Implementation and evidence are separate statuses. Deliver code and reproducible tests immediately where feasible; do not mark a strategy validated because tooling exists, a fixed calendar period elapsed, or a raw signal count was reached. Unavailable prerequisites and future evidence are explicit dependencies, not grounds for fabricated completion. No new funded exchange integrations, secret sharing or mainnet trading are authorized.

## Initial findings

The candle cache previously replaced only the final matching timestamp; a late earlier update appended a duplicate out of order. Reconnect restored subscriptions but did not repair missing bars. The observer requires 60 contiguous closed bars, while the incumbent's admission check was less strict. Repair must address the underlying cache and enforce common data integrity without altering the frozen challenger definitions.

The quote audit links initial brackets by exact returned order IDs but replacement and emergency orders lack durable attribution. API response uncertainty and process crashes require an intent written before submission, followed by append-only observations; an HTTP response alone is not proof of a fill or final cancellation.

## Release progress

- M1/M2 foundation deployed as `1fb6bad`; 91 tests, desktop/mobile browser, live health and GitHub CI passed. Closed-bar coverage restored and observable. Long-run reliability/coverage evidence continues.
- M3 foundation adds durable submission/order lifecycle and a covered prospective equity bridge; 99 regressions. Client-order-ID resolution and unsupported movement normalization are explicit follow-up work, not claimed complete.

- Offline M4/M5 foundations: passive-entry/fixed-horizon simulator, immutable supplied-protocol hashes, observation cutoffs, separate source cohorts, chronological/embargo checks, non-overlap/day-block review and declared-trial adjustment. Real execution trace capture/calibration and full bracket/cancel-race replay remain unfinished requirements.
- M6/M7 inventory records existing frozen observers and blocked data sources. No definitions were loosened or unvalidated strategy promoted.
- M8 remains evidence-gated: review tooling can return manual-review readiness but has no trading pathway. Untouched future evidence cannot be manufactured in a development session.
- M9 now exposes all ten milestone states and hypothesis prerequisites in the terminal.
- M10 has offline aligned-day correlation, supplied-history drawdown, joint stress and capacity diagnostics; multiple reviewed strategies are still unavailable. No allocation changes.
- Final release validation baseline: 117 regressions. Synthetic CLI format examples are tooling checks, not trading evidence. Detailed boundaries and follow-up work: docs/VALIDATION.md.

## Next executable work and evidence checkpoints

1. Collect a bounded real quote/trade trace only around eligible candidates, with explicit missing intervals and seven-day diagnostic expiry; calibrate passive assumptions against actual demo orders. This requires a separate versioned capture contract, not recycling sparse markouts as full traces.
2. Add client-order-ID/status resolution for uncertain intents and documented normalization for unsupported account movements. Preserve unknown state until actual evidence supports resolution.
3. Extend the simulator with mark-trigger TP/SL, cancel races, partial entry/exit interaction and protective-order outage behavior before comparing full strategies.
4. Commit an actual immutable protocol and complete trial inventory before a future holdout begins; accumulate untouched observations without tuning. Use the registry's planning thresholds as minimum review inputs, not a profitability guarantee.
5. Independently review any candidate before a separately implemented, small demo-only promotion. Portfolio expansion remains blocked until multiple strategies and synchronized capacity evidence exist.
