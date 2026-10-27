# Graph Report - hl-bot  (2026-10-27)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 658 nodes · 1259 edges · 46 communities (21 shown, 17 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 73 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `1fb6bad6`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- S/R Detection Strategy
- HyperliquidClient
- tools.py
- app.py
- RiskManager
- bot.py
- HyperliquidClient
- TradingBot
- HyperliquidClient
- Scalper
- Evaluator
- FillLedger
- python-dotenv
- monitor.py
- ExperimentEngine
- research/__init__.py
- .__init__
- transaction
- git_push.py
- Path
- Path
- HyperliquidClient
- RiskManager
- HyperliquidClient
- QualityAudit
- research.js
- ResearchService
- test_research.py
- quality.js
- Microstructure
- RiskManager
- ResearchJournal
- healthcheck.py
- terminal.js
- market/__init__.py
- complete_trades
- divergence
- browser_check.py

## God Nodes (most connected - your core abstractions)
1. `HyperliquidClient` - 69 edges
2. `RiskManager` - 38 edges
3. `ResearchService` - 32 edges
4. `TradingBot` - 32 edges
5. `ResearchJournal` - 28 edges
6. `transaction()` - 28 edges
7. `QualityAudit` - 26 edges
8. `PositionReconciler` - 23 edges
9. `Scalper` - 22 edges
10. `FillLedger` - 19 edges

## Surprising Connections (you probably didn't know these)
- `print_overall_stats()` --calls--> `FillLedger`  [INFERRED]
  scripts/monitor.py → src/learning/ledger.py
- `RetentionTests` --uses--> `ResearchJournal`  [INFERRED]
  tests/test_storage_retention.py → src/research/journal.py
- `ContinuityTests` --uses--> `HyperliquidClient`  [INFERRED]
  tests/test_continuity.py → src/exchange/hyperliquid.py
- `SourceTests` --uses--> `ResearchService`  [INFERRED]
  tests/test_research.py → src/research/service.py
- `CoverageTests` --uses--> `ResearchJournal`  [INFERRED]
  tests/test_research.py → src/research/journal.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Dashboard Technology Stack** — requirements_flask, requirements_flask_socketio, src_dashboard_templates_index_dashboard_ui, src_dashboard_templates_index_pnl_chart, src_dashboard_templates_index_socketio_client [EXTRACTED 1.00]
- **Project Python Dependencies** — requirements_hyperliquid_python_sdk, requirements_flask, requirements_flask_socketio, requirements_python_dotenv, requirements_pandas, requirements_numpy, requirements_websockets [EXTRACTED 1.00]
- **Self-Learning Feedback Cycle: Evaluator Adjusts S/R Detection** — agents_learning_agent, readme_trade_evaluator, readme_self_learning_loop, agents_sr_detection_agent [EXTRACTED 1.00]
- **Strategy Components: Detection, Placement, Risk, and Learning** — readme_sr_detection_strategy, readme_order_placement, readme_risk_management_strategy, readme_self_learning_loop [EXTRACTED 1.00]
- **Trading Pipeline: Data to Detection to Execution to Risk to Learning** — agents_market_data_agent, agents_sr_detection_agent, agents_scalper_agent, agents_risk_manager_agent, agents_learning_agent [EXTRACTED 1.00]

## Communities (46 total, 17 thin omitted)

### Community 0 - "S/R Detection Strategy"
Cohesion: 0.08
Nodes (27): Dashboard Agent, Learning Agent, Market Data Agent, Risk Manager Agent, Scalper Agent, S/R Detection Agent, Live Web Dashboard, Exchange API Wrapper (REST + WebSocket) (+19 more)

### Community 2 - "tools.py"
Cohesion: 0.10
Nodes (33): beta_tool, append_audit(), get_recent_audit(), RunLimits, validate_file_path(), validate_tuning_pair(), validate_tuning_param(), run_agent() (+25 more)

### Community 3 - "app.py"
Cohesion: 0.09
Nodes (22): after_request, route, api_account(), api_fills(), api_orders(), api_performance(), api_pnl_chart(), api_positions() (+14 more)

### Community 4 - "RiskManager"
Cohesion: 0.05
Nodes (10): PositionReconciler, Return fills that closed a position but weren't processed this session., Operational circuit breaker; never clears a durable risk halt., Caller must verify flat/no orders and sustained fresh account/feed reads., Explicit operator-reviewed migration, never called at startup or midnight., RiskManager, RiskState, ExchangeTests (+2 more)

### Community 5 - "bot.py"
Cohesion: 0.06
Nodes (16): ndarray, main(), Chronological research replay of live signal rules; never submits orders.…, replay(), Tape, Durable account risk controls. Percentages are fractions internally., atr(), bracket_distances() (+8 more)

### Community 7 - "TradingBot"
Cohesion: 0.13
Nodes (3): Match fill to active signal without removing it (partial fills reuse the…, TradingBot, EmergencyTests

### Community 9 - "Scalper"
Cohesion: 0.13
Nodes (6): OrderBlock, RiskManager, Scalper, TradeSignal, SRDetector, SRLevel

### Community 11 - "FillLedger"
Cohesion: 0.13
Nodes (8): main(), main(), Append cost-inclusive exchange ledger and risk snapshots; safe for hourly cron., FillLedger, Keep 30 days dense, then hourly min/max equity, max peak and last. Risk…, file_handler(), File logs reopen after external rotation; operational stdout stays in journald., RetentionTests

### Community 13 - "monitor.py"
Cohesion: 0.24
Nodes (13): bot_status(), live_tail(), load_json(), main(), parse_duration(), print_header(), print_overall_stats(), print_recent_trades() (+5 more)

### Community 20 - "ExperimentEngine"
Cohesion: 0.20
Nodes (6): ExperimentEngine, Fixed, observation-only experiments. No execution or parameter fitting., Bounded state machines: arm, confirm later, expire. Reset on data gaps., ExperimentTests, market(), Prospective confirmation, missing-data gates and upgrade compatibility.

### Community 22 - ".__init__"
Cohesion: 0.14
Nodes (9): coverage(), merge_bars(), Deterministic closed-bar integrity shared by execution and diagnostics., Newest observed update per timestamp, sorted and bounded; never forward-fill., valid_bar(), Operations, Durable incident boundaries and bounded heartbeat state; no exchange actions., bars() (+1 more)

### Community 23 - "transaction"
Cohesion: 0.08
Nodes (11): AccountAudit, Prospective equity bridge and bounded public testnet account-event retrieval., ExecutionJournal, Durable submission intent and exchange-ID lifecycle evidence, never price…, FundingSync, Read-only testnet funding synchronization, outside the trading/risk loop., Durable exchange-fill journal; actual costs, no inferred round trips., Short-lived SQLite transactions with deterministic connection cleanup. (+3 more)

### Community 31 - "QualityAudit"
Cohesion: 0.12
Nodes (13): Read-only chronological challenger report; stdout JSON, optional private output., report(), candle_context(), challenger(), QualityAudit, Prospective testnet audit and fixed quote challengers. No exchange access or…, Closed, contiguous one-minute bars only; thresholds frozen before collection., V1 heuristic movement budget is NOT a fitted expected return. (+5 more)

### Community 32 - "research.js"
Cohesion: 0.42
Nodes (10): renderResearch(), researchBandRender(), researchCard(), researchColor(), researchEmpty(), researchHeatmap(), researchNames, researchResults() (+2 more)

### Community 34 - "ResearchService"
Cohesion: 0.12
Nodes (5): active_blocks(), Keep fixed candidate selection separate from collection and source refresh., ResearchService, CoverageTests, FailureSuppressionTests

### Community 35 - "test_research.py"
Cohesion: 0.16
Nodes (8): compact(), Offline one-time compaction. Stop hl-bot before running; backups stay private., compact_observation(), Persistent prospective markouts. These are quote-based research, not filled…, Diagnostic minute sample; event evidence lives in signals/outcomes., Sampled L2/trade hypotheses. Scores are heuristics, never probabilities., Public read-only collectors on a daemon thread, isolated from demo execution.…, JournalTests

### Community 37 - "Microstructure"
Cohesion: 0.25
Nodes (5): finite(), Microstructure, normalize_book(), book(), MicrostructureTests

### Community 39 - "ResearchJournal"
Cohesion: 0.24
Nodes (3): Path, ResearchJournal, JournalUpgradeTests

### Community 41 - "terminal.js"
Cohesion: 0.35
Nodes (17): aggregate(), book(), chart(), fmt(), levelLines, num(), options, pnl() (+9 more)

### Community 43 - "complete_trades"
Cohesion: 0.38
Nodes (4): complete_trades(), Reconstruct flat-to-flat episodes only when exchange position continuity is…, fill(), TradeEpisodeTests

### Community 44 - "divergence"
Cohesion: 0.29
Nodes (3): divergence(), Indicative two-venue, four-leg roundtrip economics; no claim of executability., SourceTests

## Knowledge Gaps
- **15 isolated node(s):** `researchNames`, `Flask Web Framework`, `Hyperliquid Python SDK`, `NumPy Numerical Computing Library`, `Pandas Data Analysis Library` (+10 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 172 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **17 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `HyperliquidClient` connect `HyperliquidClient` to `RiskManager`, `bot.py`, `TradingBot`, `Scalper`, `FillLedger`, `.__init__`, `transaction`?**
  _High betweenness centrality (0.189) - this node is a cross-community bridge._
- **Why does `ResearchService` connect `ResearchService` to `test_research.py`, `divergence`, `.__init__`, `ResearchJournal`?**
  _High betweenness centrality (0.106) - this node is a cross-community bridge._
- **Why does `RiskManager` connect `RiskManager` to `bot.py`, `.__init__`?**
  _High betweenness centrality (0.083) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `HyperliquidClient` (e.g. with `TradingBot` and `PositionReconciler`) actually correct?**
  _`HyperliquidClient` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `RiskManager` (e.g. with `PositionReconciler` and `RecoveryTests`) actually correct?**
  _`RiskManager` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `ResearchService` (e.g. with `ResearchJournal` and `CoverageTests`) actually correct?**
  _`ResearchService` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `TradingBot` (e.g. with `HyperliquidClient` and `AccountAudit`) actually correct?**
  _`TradingBot` has 6 INFERRED edges - model-reasoned connections that need verification._