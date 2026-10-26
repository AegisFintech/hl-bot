# Graph Report - hl-bot  (2026-10-26)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 571 nodes · 1045 edges · 38 communities (17 shown, 13 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 59 edges (avg confidence: 0.88)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `be0616bb`
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
- FillLedger
- python-dotenv
- monitor.py
- ResearchJournal
- research/__init__.py
- healthcheck.py
- complete_trades
- git_push.py
- Path
- Path
- PositionReconciler
- RiskManager
- HyperliquidClient
- QualityAudit
- research.js
- ResearchService
- SRDetector
- quality.js
- browser_check.py

## God Nodes (most connected - your core abstractions)
1. `HyperliquidClient` - 54 edges
2. `ResearchService` - 32 edges
3. `ResearchJournal` - 28 edges
4. `TradingBot` - 28 edges
5. `QualityAudit` - 23 edges
6. `RiskManager` - 22 edges
7. `Scalper` - 21 edges
8. `FillLedger` - 18 edges
9. `PositionReconciler` - 14 edges
10. `SRDetector` - 14 edges

## Surprising Connections (you probably didn't know these)
- `print_overall_stats()` --calls--> `FillLedger`  [INFERRED]
  scripts/monitor.py → src/learning/ledger.py
- `RetentionTests` --uses--> `ResearchJournal`  [INFERRED]
  tests/test_storage_retention.py → src/research/journal.py
- `CoverageTests` --uses--> `ResearchJournal`  [INFERRED]
  tests/test_research.py → src/research/journal.py
- `NumPy Numerical Computing Library` --references--> `S/R Detection Strategy`  [INFERRED]
  requirements.txt → README.md
- `main()` --calls--> `HyperliquidClient`  [EXTRACTED]
  main.py → src/exchange/hyperliquid.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Dashboard Technology Stack** — requirements_flask, requirements_flask_socketio, src_dashboard_templates_index_dashboard_ui, src_dashboard_templates_index_pnl_chart, src_dashboard_templates_index_socketio_client [EXTRACTED 1.00]
- **Project Python Dependencies** — requirements_hyperliquid_python_sdk, requirements_flask, requirements_flask_socketio, requirements_python_dotenv, requirements_pandas, requirements_numpy, requirements_websockets [EXTRACTED 1.00]
- **Self-Learning Feedback Cycle: Evaluator Adjusts S/R Detection** — agents_learning_agent, readme_trade_evaluator, readme_self_learning_loop, agents_sr_detection_agent [EXTRACTED 1.00]
- **Strategy Components: Detection, Placement, Risk, and Learning** — readme_sr_detection_strategy, readme_order_placement, readme_risk_management_strategy, readme_self_learning_loop [EXTRACTED 1.00]
- **Trading Pipeline: Data to Detection to Execution to Risk to Learning** — agents_market_data_agent, agents_sr_detection_agent, agents_scalper_agent, agents_risk_manager_agent, agents_learning_agent [EXTRACTED 1.00]

## Communities (38 total, 13 thin omitted)

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
Cohesion: 0.10
Nodes (12): main(), Chronological research replay of live signal rules; never submits orders.…, replay(), Tape, Durable exchange-fill journal; actual costs, no inferred round trips., Durable account risk controls. Percentages are fractions internally., atr(), bracket_distances() (+4 more)

### Community 6 - "Scalper"
Cohesion: 0.13
Nodes (7): OrderBlock, HyperliquidClient, RiskManager, Scalper, TradeSignal, SRDetector, SRLevel

### Community 7 - "TradingBot"
Cohesion: 0.14
Nodes (3): Match fill to active signal without removing it (partial fills reuse the…, TradingBot, EmergencyTests

### Community 9 - "terminal.js"
Cohesion: 0.34
Nodes (16): aggregate(), book(), chart(), fmt(), levelLines, num(), options, pnl() (+8 more)

### Community 11 - "FillLedger"
Cohesion: 0.13
Nodes (8): main(), main(), Append cost-inclusive exchange ledger and risk snapshots; safe for hourly cron., FillLedger, Keep 30 days dense, then hourly min/max equity, max peak and last. Risk…, file_handler(), File logs reopen after external rotation; operational stdout stays in journald., RetentionTests

### Community 13 - "monitor.py"
Cohesion: 0.24
Nodes (13): bot_status(), live_tail(), load_json(), main(), parse_duration(), print_header(), print_overall_stats(), print_recent_trades() (+5 more)

### Community 20 - "ResearchJournal"
Cohesion: 0.11
Nodes (9): ExperimentEngine, Fixed, observation-only experiments. No execution or parameter fitting., Bounded state machines: arm, confirm later, expire. Reset on data gaps., ResearchJournal, ExperimentTests, JournalUpgradeTests, market(), Prospective confirmation, missing-data gates and upgrade compatibility. (+1 more)

### Community 23 - "complete_trades"
Cohesion: 0.38
Nodes (4): complete_trades(), Reconstruct flat-to-flat episodes only when exchange position continuity is…, fill(), TradeEpisodeTests

### Community 28 - "PositionReconciler"
Cohesion: 0.15
Nodes (5): HyperliquidClient, RiskManager, PositionReconciler, Return fills that closed a position but weren't processed this session., ExchangeTests

### Community 31 - "QualityAudit"
Cohesion: 0.07
Nodes (23): compact(), Offline one-time compaction. Stop hl-bot before running; backups stay private., Read-only chronological challenger report; stdout JSON, optional private output., report(), FundingSync, Read-only testnet funding synchronization, outside the trading/risk loop., candle_context(), challenger() (+15 more)

### Community 32 - "research.js"
Cohesion: 0.42
Nodes (10): renderResearch(), researchBandRender(), researchCard(), researchColor(), researchEmpty(), researchHeatmap(), researchNames, researchResults() (+2 more)

### Community 34 - "ResearchService"
Cohesion: 0.07
Nodes (16): Path, active_blocks(), finite(), Microstructure, normalize_book(), Sampled L2/trade hypotheses. Scores are heuristics, never probabilities., divergence(), Public read-only collectors on a daemon thread, isolated from demo execution.… (+8 more)

### Community 35 - "SRDetector"
Cohesion: 0.16
Nodes (4): ndarray, OrderBlock, SRDetector, SRLevel

## Knowledge Gaps
- **15 isolated node(s):** `researchNames`, `levelLines`, `options`, `Flask Web Framework`, `Hyperliquid Python SDK` (+10 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 155 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `HyperliquidClient` connect `HyperliquidClient` to `SRDetector`, `FillLedger`, `bot.py`, `TradingBot`?**
  _High betweenness centrality (0.145) - this node is a cross-community bridge._
- **Why does `ResearchService` connect `ResearchService` to `SRDetector`, `ResearchJournal`?**
  _High betweenness centrality (0.112) - this node is a cross-community bridge._
- **Why does `FillLedger` connect `FillLedger` to `SRDetector`, `RiskManager`, `bot.py`, `monitor.py`, `QualityAudit`?**
  _High betweenness centrality (0.088) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `ResearchService` (e.g. with `ResearchJournal` and `CoverageTests`) actually correct?**
  _`ResearchService` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `ResearchJournal` (e.g. with `ResearchService` and `JournalUpgradeTests`) actually correct?**
  _`ResearchJournal` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `TradingBot` (e.g. with `HyperliquidClient` and `FundingSync`) actually correct?**
  _`TradingBot` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `QualityAudit` (e.g. with `TradingBot` and `ChronologicalReportTests`) actually correct?**
  _`QualityAudit` has 3 INFERRED edges - model-reasoned connections that need verification._