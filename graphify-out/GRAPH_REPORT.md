# Graph Report - hl-bot  (2026-10-24)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 503 nodes · 896 edges · 34 communities (14 shown, 12 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 53 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `de743308`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- S/R Detection Strategy
- HyperliquidClient
- tools.py
- app.py
- RiskManager
- bot.py
- Scalper
- TradingBot
- HyperliquidClient
- terminal.js
- Evaluator
- ResearchJournal
- python-dotenv
- monitor.py
- ResearchService
- research/__init__.py
- healthcheck.py
- FillLedger
- git_push.py
- Path
- Path
- PositionReconciler
- RiskManager
- HyperliquidClient
- research.js
- browser_check.py

## God Nodes (most connected - your core abstractions)
1. `HyperliquidClient` - 51 edges
2. `ResearchService` - 34 edges
3. `TradingBot` - 25 edges
4. `ResearchJournal` - 24 edges
5. `RiskManager` - 22 edges
6. `Scalper` - 21 edges
7. `SRDetector` - 14 edges
8. `PositionReconciler` - 14 edges
9. `FillLedger` - 13 edges
10. `Evaluator` - 12 edges

## Surprising Connections (you probably didn't know these)
- `print_overall_stats()` --calls--> `FillLedger`  [INFERRED]
  scripts/monitor.py → src/learning/ledger.py
- `NumPy Numerical Computing Library` --references--> `S/R Detection Strategy`  [INFERRED]
  requirements.txt → README.md
- `CoverageTests` --uses--> `ResearchJournal`  [INFERRED]
  tests/test_research.py → src/research/journal.py
- `main()` --calls--> `HyperliquidClient`  [EXTRACTED]
  main.py → src/exchange/hyperliquid.py
- `main()` --calls--> `FillLedger`  [EXTRACTED]
  scripts/snapshot_perf.py → src/learning/ledger.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Dashboard Technology Stack** — requirements_flask, requirements_flask_socketio, src_dashboard_templates_index_dashboard_ui, src_dashboard_templates_index_pnl_chart, src_dashboard_templates_index_socketio_client [EXTRACTED 1.00]
- **Project Python Dependencies** — requirements_hyperliquid_python_sdk, requirements_flask, requirements_flask_socketio, requirements_python_dotenv, requirements_pandas, requirements_numpy, requirements_websockets [EXTRACTED 1.00]
- **Self-Learning Feedback Cycle: Evaluator Adjusts S/R Detection** — agents_learning_agent, readme_trade_evaluator, readme_self_learning_loop, agents_sr_detection_agent [EXTRACTED 1.00]
- **Strategy Components: Detection, Placement, Risk, and Learning** — readme_sr_detection_strategy, readme_order_placement, readme_risk_management_strategy, readme_self_learning_loop [EXTRACTED 1.00]
- **Trading Pipeline: Data to Detection to Execution to Risk to Learning** — agents_market_data_agent, agents_sr_detection_agent, agents_scalper_agent, agents_risk_manager_agent, agents_learning_agent [EXTRACTED 1.00]

## Communities (34 total, 12 thin omitted)

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
Cohesion: 0.12
Nodes (3): RiskManager, RiskState, RiskTests

### Community 5 - "bot.py"
Cohesion: 0.07
Nodes (15): ndarray, main(), Chronological research replay of live signal rules; never submits orders.…, replay(), Tape, Durable account risk controls. Percentages are fractions internally., atr(), bracket_distances() (+7 more)

### Community 6 - "Scalper"
Cohesion: 0.13
Nodes (7): OrderBlock, HyperliquidClient, RiskManager, Scalper, TradeSignal, SRDetector, SRLevel

### Community 7 - "TradingBot"
Cohesion: 0.12
Nodes (4): main(), Match fill to active signal without removing it (partial fills reuse the…, TradingBot, EmergencyTests

### Community 9 - "terminal.js"
Cohesion: 0.34
Nodes (16): aggregate(), book(), chart(), fmt(), levelLines, num(), options, pnl() (+8 more)

### Community 11 - "ResearchJournal"
Cohesion: 0.11
Nodes (9): ExperimentEngine, Fixed, observation-only experiments. No execution or parameter fitting., Bounded state machines: arm, confirm later, expire. Reset on data gaps., ResearchJournal, ExperimentTests, JournalUpgradeTests, market(), Prospective confirmation, missing-data gates and upgrade compatibility. (+1 more)

### Community 13 - "monitor.py"
Cohesion: 0.24
Nodes (13): bot_status(), live_tail(), load_json(), main(), parse_duration(), print_header(), print_overall_stats(), print_recent_trades() (+5 more)

### Community 20 - "ResearchService"
Cohesion: 0.07
Nodes (17): Path, Persistent prospective markouts. These are quote-based research, not filled…, active_blocks(), finite(), Microstructure, normalize_book(), Sampled L2/trade hypotheses. Scores are heuristics, never probabilities., divergence() (+9 more)

### Community 23 - "FillLedger"
Cohesion: 0.13
Nodes (10): main(), Append cost-inclusive exchange ledger and risk snapshots; safe for hourly cron., FillLedger, Durable exchange-fill journal; actual costs, no inferred round trips., complete_trades(), Reconstruct flat-to-flat episodes only when exchange position continuity is…, Short-lived SQLite transactions with deterministic connection cleanup., transaction() (+2 more)

### Community 28 - "PositionReconciler"
Cohesion: 0.15
Nodes (5): HyperliquidClient, RiskManager, PositionReconciler, Return fills that closed a position but weren't processed this session., ExchangeTests

### Community 31 - "research.js"
Cohesion: 0.42
Nodes (10): renderResearch(), researchBandRender(), researchCard(), researchColor(), researchEmpty(), researchHeatmap(), researchNames, researchResults() (+2 more)

## Knowledge Gaps
- **15 isolated node(s):** `levelLines`, `options`, `Flask Web Framework`, `Hyperliquid Python SDK`, `NumPy Numerical Computing Library` (+10 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 143 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **12 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ResearchService` connect `ResearchService` to `ResearchJournal`, `PositionReconciler`, `bot.py`, `TradingBot`?**
  _High betweenness centrality (0.148) - this node is a cross-community bridge._
- **Why does `HyperliquidClient` connect `HyperliquidClient` to `bot.py`, `TradingBot`?**
  _High betweenness centrality (0.135) - this node is a cross-community bridge._
- **Why does `TradingBot` connect `TradingBot` to `ResearchService`, `app.py`, `PositionReconciler`, `bot.py`?**
  _High betweenness centrality (0.092) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `ResearchService` (e.g. with `TradingBot` and `ResearchJournal`) actually correct?**
  _`ResearchService` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `TradingBot` (e.g. with `ResearchService` and `EmergencyTests`) actually correct?**
  _`TradingBot` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `ResearchJournal` (e.g. with `ResearchService` and `JournalUpgradeTests`) actually correct?**
  _`ResearchJournal` has 4 INFERRED edges - model-reasoned connections that need verification._
- **What connects `levelLines`, `options`, `Flask Web Framework` to the rest of the system?**
  _15 weakly-connected nodes found - possible documentation gaps or missing edges._