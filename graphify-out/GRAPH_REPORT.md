# Graph Report - hl-bot  (2026-10-22)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 378 nodes · 640 edges · 30 communities (12 shown, 11 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 29 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `3beb9a77`
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
- SRDetector
- Evaluator
- python-dotenv
- monitor.py
- FillLedger
- Tape
- healthcheck.py
- browser_check.py
- git_push.py
- Path
- Path
- PositionReconciler
- RiskManager

## God Nodes (most connected - your core abstractions)
1. `HyperliquidClient` - 51 edges
2. `TradingBot` - 25 edges
3. `Scalper` - 23 edges
4. `RiskManager` - 22 edges
5. `PositionReconciler` - 16 edges
6. `SRDetector` - 13 edges
7. `FillLedger` - 13 edges
8. `Evaluator` - 12 edges
9. `render()` - 11 edges
10. `Tape` - 10 edges

## Surprising Connections (you probably didn't know these)
- `print_overall_stats()` --calls--> `FillLedger`  [INFERRED]
  scripts/monitor.py → src/learning/ledger.py
- `NumPy Numerical Computing Library` --references--> `S/R Detection Strategy`  [INFERRED]
  requirements.txt → README.md
- `main()` --calls--> `HyperliquidClient`  [EXTRACTED]
  main.py → src/exchange/hyperliquid.py
- `replay()` --calls--> `SRDetector`  [EXTRACTED]
  scripts/replay.py → src/strategy/sr_detector.py
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

## Communities (30 total, 11 thin omitted)

### Community 0 - "S/R Detection Strategy"
Cohesion: 0.08
Nodes (27): Dashboard Agent, Learning Agent, Market Data Agent, Risk Manager Agent, Scalper Agent, S/R Detection Agent, Live Web Dashboard, Exchange API Wrapper (REST + WebSocket) (+19 more)

### Community 2 - "tools.py"
Cohesion: 0.10
Nodes (33): beta_tool, append_audit(), get_recent_audit(), RunLimits, validate_file_path(), validate_tuning_pair(), validate_tuning_param(), run_agent() (+25 more)

### Community 3 - "app.py"
Cohesion: 0.10
Nodes (21): after_request, route, api_account(), api_fills(), api_orders(), api_performance(), api_pnl_chart(), api_positions() (+13 more)

### Community 5 - "bot.py"
Cohesion: 0.14
Nodes (11): main(), Chronological research replay of live signal rules; never submits orders.…, replay(), Durable exchange-fill journal; actual costs, no inferred round trips., Durable account risk controls. Percentages are fractions internally., atr(), bracket_distances(), Fixed execution economics shared by live strategy and replay. (+3 more)

### Community 6 - "Scalper"
Cohesion: 0.13
Nodes (7): OrderBlock, HyperliquidClient, RiskManager, Scalper, TradeSignal, SRDetector, SRLevel

### Community 7 - "TradingBot"
Cohesion: 0.13
Nodes (4): main(), Match fill to active signal without removing it (partial fills reuse the…, TradingBot, EmergencyTests

### Community 9 - "terminal.js"
Cohesion: 0.34
Nodes (16): aggregate(), book(), chart(), fmt(), levelLines, num(), options, pnl() (+8 more)

### Community 10 - "SRDetector"
Cohesion: 0.17
Nodes (4): ndarray, OrderBlock, SRDetector, SRLevel

### Community 11 - "Evaluator"
Cohesion: 0.13
Nodes (5): Path, HyperliquidClient, Evaluator, TradeRecord, RiskState

### Community 13 - "monitor.py"
Cohesion: 0.24
Nodes (13): bot_status(), live_tail(), load_json(), main(), parse_duration(), print_header(), print_overall_stats(), print_recent_trades() (+5 more)

### Community 20 - "FillLedger"
Cohesion: 0.24
Nodes (3): main(), Append cost-inclusive exchange ledger and risk snapshots; safe for hourly cron., FillLedger

### Community 28 - "PositionReconciler"
Cohesion: 0.15
Nodes (5): HyperliquidClient, RiskManager, PositionReconciler, Return fills that closed a position but weren't processed this session., ExchangeTests

## Knowledge Gaps
- **14 isolated node(s):** `levelLines`, `options`, `Flask Web Framework`, `Hyperliquid Python SDK`, `NumPy Numerical Computing Library` (+9 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 120 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **11 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `HyperliquidClient` connect `HyperliquidClient` to `bot.py`, `TradingBot`?**
  _High betweenness centrality (0.164) - this node is a cross-community bridge._
- **Why does `TradingBot` connect `TradingBot` to `app.py`, `bot.py`, `Scalper`, `Evaluator`, `PositionReconciler`?**
  _High betweenness centrality (0.116) - this node is a cross-community bridge._
- **Why does `Scalper` connect `Scalper` to `Evaluator`, `bot.py`, `TradingBot`?**
  _High betweenness centrality (0.102) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `TradingBot` (e.g. with `PositionReconciler` and `Scalper`) actually correct?**
  _`TradingBot` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `PositionReconciler` (e.g. with `TradingBot` and `ExchangeTests`) actually correct?**
  _`PositionReconciler` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `levelLines`, `options`, `Flask Web Framework` to the rest of the system?**
  _14 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `S/R Detection Strategy` be split into smaller, more focused modules?**
  _Cohesion score 0.08262108262108261 - nodes in this community are weakly interconnected._