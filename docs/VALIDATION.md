# Offline simulation and research review tools

These tools have no network calls, exchange client, keys or promotion pathway. They do not consume an account's funds or change execution configuration. All examples under docs/examples are explicitly synthetic format demonstrations, not research evidence. Reports generated from runtime/account inputs belong under ignored artifacts/.

## Passive-entry execution simulation (M4 foundation)

`python3 scripts/research_evaluate.py simulate docs/examples/simulation.json`

Input is one candidate (`time`, `direction` ±1, `limit`, `size`, `entry_ttl_s`, `holding_s`), receipt-ordered quote/trade events and named assumption scenarios. Quotes require finite positive bid/ask with bid below ask. Trades require identity, positive price, nonnegative quantity and explicit aggressive `buy`/`sell` side. Duplicate trades cannot create extra fill volume; traces are bounded to 200,000 events.

Admission occurs after supplied latency and checks post-only crossing against the fresh arrival quote. A quote touching a limit is never sufficient evidence for a fill. Only opposing aggressive volume reaching that price can consume the supplied queue, with an explicit participation haircut. Partial entry quantities are retained. Queue size, participation and latency are assumptions, not measured queue rank or calibrated fill probability.

The modeled entry window ends at arrival + TTL. Exit uses the first fresh bid/ask at entry-window-end + holding horizon + latency, with adverse supplied slippage and taker fee. Funding cost is a signed supplied hourly assumption weighted by each partial fill's holding duration. Quotes must remain fresh through the modeled path; missing arrival data, excessive quote gaps or missing executable exit yield unavailable results with no profit number.

This is a passive-entry/fixed-horizon model, **not** a complete strategy backtest. It does not model TP/SL mark triggers, hidden liquidity, cancel races, shared multi-order queues, exchange maintenance or capital/liquidation constraints. Entry cancellation at TTL is idealized. Production trace capture, actual queue calibration and full bracket/race replay remain required before using it to judge deployment. Existing sparse quote markouts cannot be transformed into a complete execution trace. Do not call synthetic example results actual profit.

## Chronological evidence review (M5/M8 foundation)

`python3 scripts/research_evaluate.py review docs/examples/review.json`

A real protocol must be committed before its untouched evaluation period. Its SHA256 hash covers canonical JSON including version, lock time, training end, holdout bounds, maximum holding embargo, declared trial count/inventory completeness, minimum days/episodes, cost stress and execution-stress review flag. Each episode must carry the exact protocol hash/version, a unique ID, open/close/observation receipt timestamps, source (`demo_fill`, `quote` or `simulation`), net basis points and funding coverage flag. A hash binds the supplied configuration; it does not independently authenticate collection times or account results.

Evaluation excludes records outside the specified untouched interval or not yet observed by the cutoff. Mixed source cohorts, duplicate IDs, invalid chronology and holding periods longer than the embargo are rejected. Earliest-start non-overlapping episodes are selected deterministically; this is a descriptive sample, not a portfolio construction or independence guarantee. UTC calendar-week tables support chronological inspection.

Uncertainty resamples whole observed UTC-day mean outcomes with a fixed seed and a lower-tail adjustment for the declared number of trials. Day blocks preserve within-day clustering but not cross-day dependence. The report blocks review if the tail has insufficient bootstrap resolution, trial inventory is incomplete, days/windows are insufficient, the holdout is unfinished, funding is incomplete, source is not actual demo fills, stressed lower bound is nonpositive or execution stress review is absent. The default planning thresholds of 30 observed days and 100 non-overlapping episodes are choices to preregister, not proof that any sample size establishes profitability.

`review_ready` only means the supplied inputs passed these checks and need independent manual review. It never approves, sizes, promotes or changes a strategy. Source truth, selection bias, regime stability, account risk and full execution/failure modeling still require review. Changing a protocol requires a new version/hash and untouched future cohort. Keep failed trials and negative replay evidence.

## Portfolio and capacity diagnostics (M10 foundation)

`python3 scripts/research_evaluate.py portfolio docs/examples/portfolio.json`

Inputs supply per-strategy net daily return fractions on canonical UTC dates, nonnegative weights summing to at most one, evidence review statuses, full joint stress vectors and executable-depth assumptions. The report uses only common observed dates; it never forward-fills missing returns. It calculates supplied-history pairwise correlation, constant daily rebalanced hypothetical NAV/drawdown, joint stress loss and proposed order/depth participation. Unused weight is cash, with zero assumed return. Rebalancing costs are not modeled separately; inputs must already reflect appropriate costs and the interpretation remains hypothetical.

Fewer than 30 common days, missing independently reviewed strategies, historical drawdown reaching 5%, missing/limit-breaching joint stresses or capacity assumptions block the review. Correlation can fail during shocks and sampled depth is not guaranteed executable capacity. Supplied historical drawdown is not a future loss bound. Even a report without blockers remains manual-review-only with `approved:false`; BTC demo execution and the persistent account risk state remain unchanged.

## Hypothesis inventory (M6/M7)

`docs/RESEARCH_REGISTRY.json` records frozen trend/range cohorts, existing mainnet order-flow/crowding detectors and explicit prerequisites for liquidation, cross-venue, wallet/sentiment and portfolio research. Existing implemented observation-only experiments are not new verified strategies. Do not relax frozen definitions because initial results are weak. Missing global events, executable hedge data and future evidence remain genuine blockers, not synthetic substitutes.
