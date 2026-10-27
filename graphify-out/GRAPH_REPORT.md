# Graph Report - hl-bot  (2026-10-27)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 595 nodes · 1107 edges · 39 communities (14 shown, 17 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 67 edges (avg confidence: 0.89)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `cd8d54d8`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- S/R Detection Strategy
- HyperliquidClient
- tools.py
- app.py
- RiskManager
- Scalper
- HyperliquidClient
- TradingBot
- HyperliquidClient
- terminal.js
- Evaluator
- FillLedger
- python-dotenv
- monitor.py
- ExperimentEngine
- research/__init__.py
- healthcheck.py
- browser_check.py
- git_push.py
- Path
- Path
- HyperliquidClient
- RiskManager
- HyperliquidClient
- QualityAudit
- research.js
- ResearchService
- SRDetector
- quality.js
- RiskManager
- RiskManager

## God Nodes (most connected - your core abstractions)
1. `HyperliquidClient` - 62 edges
2. `RiskManager` - 43 edges
3. `ResearchService` - 32 edges
4. `TradingBot` - 31 edges
5. `ResearchJournal` - 28 edges
6. `PositionReconciler` - 25 edges
7. `Scalper` - 25 edges
8. `QualityAudit` - 21 edges
9. `FillLedger` - 18 edges
10. `RecoveryTests` - 18 edges

## Surprising Connections (you probably didn't know these)
- `print_overall_stats()` --calls--> `FillLedger`  [INFERRED]
  scripts/monitor.py → src/learning/ledger.py
- `RetentionTests` --uses--> `ResearchJournal`  [INFERRED]
  tests/test_storage_retention.py → src/research/journal.py
- `NumPy Numerical Computing Library` --references--> `S/R Detection Strategy`  [INFERRED]
  requirements.txt → README.md
- `RecoveryTests` --uses--> `TradingBot`  [INFERRED]
  tests/test_recovery.py → src/bot.py
- `RecoveryTests` --uses--> `HyperliquidClient`  [INFERRED]
  tests/test_recovery.py → src/exchange/hyperliquid.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Dashboard Technology Stack** — requirements_flask, requirements_flask_socketio, src_dashboard_templates_index_dashboard_ui, src_dashboard_templates_index_pnl_chart, src_dashboard_templates_index_socketio_client [EXTRACTED 1.00]
- **Project Python Dependencies** — requirements_hyperliquid_python_sdk, requirements_flask, requirements_flask_socketio, requirements_python_dotenv, requirements_pandas, requirements_numpy, requirements_websockets [EXTRACTED 1.00]
- **Self-Learning Feedback Cycle: Evaluator Adjusts S/R Detection** — agents_learning_agent, readme_trade_evaluator, readme_self_learning_loop, agents_sr_detection_agent [EXTRACTED 1.00]
- **Strategy Components: Detection, Placement, Risk, and Learning** — readme_sr_detection_strategy, readme_order_placement, readme_risk_management_strategy, readme_self_learning_loop [EXTRACTED 1.00]
- **Trading Pipeline: Data to Detection to Execution to Risk to Learning** — agents_market_data_agent, agents_sr_detection_agent, agents_scalper_agent, agents_risk_manager_agent, agents_learning_agent [EXTRACTED 1.00]

## Communities (39 total, 17 thin omitted)

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
Nodes (12): PositionReconciler, Return fills that closed a position but weren't processed this session., Durable account risk controls. Percentages are fractions internally., Operational circuit breaker; never clears a durable risk halt., Caller must verify flat/no orders and sustained fresh account/feed reads., Explicit operator-reviewed migration, never called at startup or midnight., RiskManager, RiskState (+4 more)

### Community 5 - "Scalper"
Cohesion: 0.06
Nodes (15): OrderBlock, main(), Chronological research replay of live signal rules; never submits orders.…, replay(), Tape, atr(), bracket_distances(), Fixed execution economics shared by live strategy and replay. (+7 more)

### Community 7 - "TradingBot"
Cohesion: 0.14
Nodes (3): Match fill to active signal without removing it (partial fills reuse the…, TradingBot, EmergencyTests

### Community 9 - "terminal.js"
Cohesion: 0.34
Nodes (16): aggregate(), book(), chart(), fmt(), levelLines, num(), options, pnl() (+8 more)

### Community 11 - "FillLedger"
Cohesion: 0.08
Nodes (17): main(), compact(), Offline one-time compaction. Stop hl-bot before running; backups stay private., main(), Append cost-inclusive exchange ledger and risk snapshots; safe for hourly cron., FillLedger, Durable exchange-fill journal; actual costs, no inferred round trips., Keep 30 days dense, then hourly min/max equity, max peak and last. Risk… (+9 more)

### Community 13 - "monitor.py"
Cohesion: 0.24
Nodes (13): bot_status(), live_tail(), load_json(), main(), parse_duration(), print_header(), print_overall_stats(), print_recent_trades() (+5 more)

### Community 20 - "ExperimentEngine"
Cohesion: 0.20
Nodes (6): ExperimentEngine, Fixed, observation-only experiments. No execution or parameter fitting., Bounded state machines: arm, confirm later, expire. Reset on data gaps., ExperimentTests, market(), Prospective confirmation, missing-data gates and upgrade compatibility.

### Community 31 - "QualityAudit"
Cohesion: 0.08
Nodes (19): Read-only chronological challenger report; stdout JSON, optional private output., report(), FundingSync, Read-only testnet funding synchronization, outside the trading/risk loop., candle_context(), challenger(), QualityAudit, Prospective testnet audit and fixed quote challengers. No exchange access or… (+11 more)

### Community 32 - "research.js"
Cohesion: 0.42
Nodes (10): renderResearch(), researchBandRender(), researchCard(), researchColor(), researchEmpty(), researchHeatmap(), researchNames, researchResults() (+2 more)

### Community 34 - "ResearchService"
Cohesion: 0.06
Nodes (19): Path, ResearchJournal, active_blocks(), finite(), Microstructure, normalize_book(), Sampled L2/trade hypotheses. Scores are heuristics, never probabilities., divergence() (+11 more)

### Community 35 - "SRDetector"
Cohesion: 0.18
Nodes (4): ndarray, OrderBlock, SRDetector, SRLevel

## Knowledge Gaps
- **15 isolated node(s):** `researchNames`, `Flask Web Framework`, `Hyperliquid Python SDK`, `NumPy Numerical Computing Library`, `Pandas Data Analysis Library` (+10 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 160 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **17 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `HyperliquidClient` connect `HyperliquidClient` to `RiskManager`, `Scalper`, `TradingBot`, `Evaluator`, `FillLedger`?**
  _High betweenness centrality (0.146) - this node is a cross-community bridge._
- **Why does `RiskManager` connect `RiskManager` to `Evaluator`, `Scalper`, `TradingBot`?**
  _High betweenness centrality (0.106) - this node is a cross-community bridge._
- **Why does `ResearchService` connect `ResearchService` to `Evaluator`?**
  _High betweenness centrality (0.104) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `HyperliquidClient` (e.g. with `TradingBot` and `PositionReconciler`) actually correct?**
  _`HyperliquidClient` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `RiskManager` (e.g. with `TradingBot` and `PositionReconciler`) actually correct?**
  _`RiskManager` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `ResearchService` (e.g. with `ResearchJournal` and `CoverageTests`) actually correct?**
  _`ResearchService` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `TradingBot` (e.g. with `HyperliquidClient` and `PositionReconciler`) actually correct?**
  _`TradingBot` has 6 INFERRED edges - model-reasoned connections that need verification._