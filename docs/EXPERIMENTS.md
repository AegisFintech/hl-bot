# Experiment backlog and implementation — 2026-10-24

Continuous monitoring does not imply continuous profitable trading. Current replay and early forward proxies are negative. Preserve the 5% persistent high-water halt, demo-only execution, disabled fitting and separate public observer. No signal promotion is automatic.

## Prioritized strategy list

| Priority | Experiment | Current implementation / prerequisite |
| --- | --- | --- |
| 1 | Failed whale aggression | Observation state machine: fresh >=$100k print opposed by absorption; subsequent >=2bps reversal within 120s. No identity claim. |
| 1 | Wall defense vs consumption | Defense observed after >=30s persistence, >=$25k sample executions and >=50% sampled refill, then >=2bps confirmation within 120s while wall remains. Consumption/retest blocked pending cumulative executed-depth attribution; disappearance alone is insufficient. |
| 1 | Crowded-trade failure | Observe hourly funding magnitude >=1bp and OI growth >=0.5% over 5–10m, a >=5bps sampled excursion, then later failure through its prior quote within 180s. Cancel if funding/context invalid or extension >=25bps. |
| 2 | Liquidation aftershock | Blocked pending verified broad liquidation coverage. Watched-wallet events are not a global feed. |
| 2 | Persistent whale execution | Blocked pending stable execution-sequence attribution; public wallets can have unknown hedges. |
| 2 | BTC/ETH relative value | Blocked pending synchronized ETH quotes, frozen trailing hedge estimates, paired costs and correlation-break stress. |
| 2 | Hedged funding carry | Blocked pending hedge/collateral simulation, borrow and variable funding; indicative basis is not a funded arbitrage. |
| 2 | Post-shock second move | Blocked pending independently timestamped event source and pre-event reference prices. |
| 3 | Cross-venue leadership | Blocked pending synchronized streaming quotes and explicit detection/execution delay modeling. Current polled Kraken comparison cannot validate a latency edge. |

Blocked means no signal is emitted, rather than substituting a weak proxy. Dependencies are part of the backlog, not evidence those strategies work. Funding and sentiment remain context; daily fear/greed is not a fast trigger.

## Measurement and system improvements

- **Implemented:** fixed arm/confirm/expire state machines; clear gap/incomplete-stream suppression; bounded memory; collector and candidate selection separated.
- **Implemented:** prospective 10s/1m/5m/15m/30m/1h/4h horizons. Migration freezes legacy events to their original four horizons so new evaluations do not invent historical outcomes. Pending new events survive restart; detector arms reset safely on restart.
- **Implemented:** mean signed mid move, modeled cost drag and net quote proxy; greedy non-overlapping window counts/means; same-direction unconditional drift comparison; explicit evidence review status. Non-overlap is not independence, and the unconditional comparison is **not time/regime matched or causal alpha**.
- **Implemented:** continuous-position flat-to-flat execution episodes including all USDC entry/exit fees, partial exits and reversal fee allocation. Exclude missing history, position gaps and invalid fee currencies. Funding is excluded; complete trade net does not replace account equity.
- **Implemented:** shared SQLite transaction helper closes connections deterministically; expanded Python formatting for research/accounting modules; avoid repeated writes for already measured horizons.
- **Dashboard milestone:** experiment catalog with blocked prerequisites, cost/benchmark scoreboard, expanded horizons and actual complete-trade summary.
- **Still required before promotion:** matched time/regime controls; frozen out-of-sample comparisons across regimes; timestamped execution fair quotes for adverse-selection/slippage attribution; actual funding attribution by episode; passive queue/fill modeling; opportunity and abstention denominators. These need additional data rather than a guessed statistic.

The current observer samples approximately every five seconds: it cannot resolve the sequence inside a sample or reconstruct queue priority/hidden orders. State thresholds are predeclared hypotheses, not fitted winners. Multiple experiments share underlying flow and are correlated. At least 100 non-overlapping windows is only a display review threshold, not validation or permission to trade. Positive proxies always require future validation; nothing auto-promotes. Thirty days/100 complete forward demo trades remain proposed minimum gates, not sufficient proof.

## Research basis

- [BIS crypto carry](https://www.bis.org/publications/working-paper-1087-crypto-carry): carry reflects leveraged demand and constrained arbitrage capital; margin/liquidation risks remain.
- [Hyperliquid funding](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding): variable hourly funding.
- [Price discovery](https://swlb1.aeaweb.org/articles?id=10.1257%2Fpandp.20191020): exchange leadership depends on integration and time.
- [Arbitrage frictions](https://arxiv.org/abs/1812.00595): settlement latency/default risks limit apparent arbitrage.

None of these publications validates our specific detectors. Runtime observations stay private under data/. Preserve original replay diagnostics.
