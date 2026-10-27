# Graph Report - hl-bot  (2026-10-27)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 704 nodes · 1349 edges · 43 communities (18 shown, 17 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 69 edges (avg confidence: 0.89)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `04e361b9`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- S/R Detection Strategy
- HyperliquidClient
- tools.py
- simulate
- RiskManager
- Scalper
- HyperliquidClient
- TradingBot
- HyperliquidClient
- app.py
- .__init__
- FillLedger
- python-dotenv
- monitor.py
- ResearchJournal
- research/__init__.py
- ContinuityTests
- transaction
- git_push.py
- Path
- Path
- terminal.js
- RiskManager
- HyperliquidClient
- bot.py
- research.js
- ResearchService
- SRDetector
- quality.js
- browser_check.py
- RiskManager
- validation/__init__.py
- healthcheck.py
- market/__init__.py
- complete_trades

## God Nodes (most connected - your core abstractions)
1. `HyperliquidClient` - 62 edges
2. `RiskManager` - 38 edges
3. `ResearchService` - 32 edges
4. `TradingBot` - 32 edges
5. `ResearchJournal` - 28 edges
6. `transaction()` - 28 edges
7. `QualityAudit` - 24 edges
8. `PositionReconciler` - 23 edges
9. `Scalper` - 23 edges
10. `FillLedger` - 19 edges

## Surprising Connections (you probably didn't know these)
- `RecoveryTests` --uses--> `HyperliquidClient`  [INFERRED]
  tests/test_recovery.py → src/exchange/hyperliquid.py
- `print_overall_stats()` --calls--> `FillLedger`  [INFERRED]
  scripts/monitor.py → src/learning/ledger.py
- `RetentionTests` --uses--> `ResearchJournal`  [INFERRED]
  tests/test_storage_retention.py → src/research/journal.py
- `CoverageTests` --uses--> `ResearchJournal`  [INFERRED]
  tests/test_research.py → src/research/journal.py
- `ContinuityTests` --uses--> `Scalper`  [INFERRED]
  tests/test_continuity.py → src/strategy/scalper.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Dashboard Technology Stack** — requirements_flask, requirements_flask_socketio, src_dashboard_templates_index_dashboard_ui, src_dashboard_templates_index_pnl_chart, src_dashboard_templates_index_socketio_client [EXTRACTED 1.00]
- **Project Python Dependencies** — requirements_hyperliquid_python_sdk, requirements_flask, requirements_flask_socketio, requirements_python_dotenv, requirements_pandas, requirements_numpy, requirements_websockets [EXTRACTED 1.00]
- **Self-Learning Feedback Cycle: Evaluator Adjusts S/R Detection** — agents_learning_agent, readme_trade_evaluator, readme_self_learning_loop, agents_sr_detection_agent [EXTRACTED 1.00]
- **Strategy Components: Detection, Placement, Risk, and Learning** — readme_sr_detection_strategy, readme_order_placement, readme_risk_management_strategy, readme_self_learning_loop [EXTRACTED 1.00]
- **Trading Pipeline: Data to Detection to Execution to Risk to Learning** — agents_market_data_agent, agents_sr_detection_agent, agents_scalper_agent, agents_risk_manager_agent, agents_learning_agent [EXTRACTED 1.00]

## Communities (43 total, 17 thin omitted)

### Community 0 - "S/R Detection Strategy"
Cohesion: 0.08
Nodes (27): Dashboard Agent, Learning Agent, Market Data Agent, Risk Manager Agent, Scalper Agent, S/R Detection Agent, Live Web Dashboard, Exchange API Wrapper (REST + WebSocket) (+19 more)

### Community 2 - "tools.py"
Cohesion: 0.10
Nodes (33): beta_tool, append_audit(), get_recent_audit(), RunLimits, validate_file_path(), validate_tuning_pair(), validate_tuning_param(), run_agent() (+25 more)

### Community 3 - "simulate"
Cohesion: 0.11
Nodes (15): main(), Offline versioned simulation or evidence review; JSON input/output, no network., evaluate(), number(), protocol_hash(), Predeclared chronological review with dependent-day uncertainty; no promotion., Offline aligned daily-return/capacity diagnostics; never changes allocations., review_portfolio() (+7 more)

### Community 4 - "RiskManager"
Cohesion: 0.06
Nodes (9): PositionReconciler, Return fills that closed a position but weren't processed this session., Operational circuit breaker; never clears a durable risk halt., Caller must verify flat/no orders and sustained fresh account/feed reads., Explicit operator-reviewed migration, never called at startup or midnight., RiskManager, ExchangeTests, RecoveryTests (+1 more)

### Community 5 - "Scalper"
Cohesion: 0.05
Nodes (20): HyperliquidClient, OrderBlock, RiskManager, main(), Chronological research replay of live signal rules; never submits orders.…, replay(), Tape, Durable account risk controls. Percentages are fractions internally. (+12 more)

### Community 7 - "TradingBot"
Cohesion: 0.11
Nodes (5): Match fill to active signal without removing it (partial fills reuse the…, TradingBot, run_dashboard(), set_bot_reference(), EmergencyTests

### Community 9 - "app.py"
Cohesion: 0.10
Nodes (22): after_request, route, api_account(), api_development(), api_fills(), api_orders(), api_performance(), api_pnl_chart() (+14 more)

### Community 11 - "FillLedger"
Cohesion: 0.13
Nodes (8): main(), main(), Append cost-inclusive exchange ledger and risk snapshots; safe for hourly cron., FillLedger, Keep 30 days dense, then hourly min/max equity, max peak and last. Risk…, file_handler(), File logs reopen after external rotation; operational stdout stays in journald., RetentionTests

### Community 13 - "monitor.py"
Cohesion: 0.24
Nodes (13): bot_status(), live_tail(), load_json(), main(), parse_duration(), print_header(), print_overall_stats(), print_recent_trades() (+5 more)

### Community 20 - "ResearchJournal"
Cohesion: 0.11
Nodes (9): ExperimentEngine, Fixed, observation-only experiments. No execution or parameter fitting., Bounded state machines: arm, confirm later, expire. Reset on data gaps., ResearchJournal, ExperimentTests, JournalUpgradeTests, market(), Prospective confirmation, missing-data gates and upgrade compatibility. (+1 more)

### Community 22 - "ContinuityTests"
Cohesion: 0.15
Nodes (8): coverage(), merge_bars(), Deterministic closed-bar integrity shared by execution and diagnostics., Newest observed update per timestamp, sorted and bounded; never forward-fill., valid_bar(), Operations, bars(), ContinuityTests

### Community 23 - "transaction"
Cohesion: 0.10
Nodes (6): AccountAudit, ExecutionJournal, FundingSync, transaction(), AccountAuditTests, FundingTests

### Community 28 - "terminal.js"
Cohesion: 0.35
Nodes (17): aggregate(), book(), chart(), fmt(), levelLines, num(), options, pnl() (+9 more)

### Community 31 - "bot.py"
Cohesion: 0.07
Nodes (25): compact(), Offline one-time compaction. Stop hl-bot before running; backups stay private., Read-only chronological challenger report; stdout JSON, optional private output., report(), Prospective equity bridge and bounded public testnet account-event retrieval., Durable submission intent and exchange-ID lifecycle evidence, never price…, Read-only testnet funding synchronization, outside the trading/risk loop., Durable exchange-fill journal; actual costs, no inferred round trips. (+17 more)

### Community 32 - "research.js"
Cohesion: 0.42
Nodes (10): renderResearch(), researchBandRender(), researchCard(), researchColor(), researchEmpty(), researchHeatmap(), researchNames, researchResults() (+2 more)

### Community 34 - "ResearchService"
Cohesion: 0.07
Nodes (15): Path, active_blocks(), finite(), Microstructure, normalize_book(), Sampled L2/trade hypotheses. Scores are heuristics, never probabilities., divergence(), Indicative two-venue, four-leg roundtrip economics; no claim of executability. (+7 more)

### Community 35 - "SRDetector"
Cohesion: 0.18
Nodes (4): ndarray, OrderBlock, SRDetector, SRLevel

### Community 43 - "complete_trades"
Cohesion: 0.38
Nodes (4): complete_trades(), Reconstruct flat-to-flat episodes only when exchange position continuity is…, fill(), TradeEpisodeTests

## Knowledge Gaps
- **15 isolated node(s):** `levelLines`, `options`, `researchNames`, `Flask Web Framework`, `Hyperliquid Python SDK` (+10 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 182 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **17 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `HyperliquidClient` connect `HyperliquidClient` to `RiskManager`, `Scalper`, `TradingBot`, `.__init__`, `FillLedger`, `ContinuityTests`, `bot.py`?**
  _High betweenness centrality (0.129) - this node is a cross-community bridge._
- **Why does `ResearchService` connect `ResearchService` to `.__init__`, `ResearchJournal`, `bot.py`?**
  _High betweenness centrality (0.094) - this node is a cross-community bridge._
- **Why does `RiskManager` connect `RiskManager` to `.__init__`, `Scalper`?**
  _High betweenness centrality (0.076) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `HyperliquidClient` (e.g. with `TradingBot` and `PositionReconciler`) actually correct?**
  _`HyperliquidClient` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `RiskManager` (e.g. with `PositionReconciler` and `RecoveryTests`) actually correct?**
  _`RiskManager` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `ResearchService` (e.g. with `ResearchJournal` and `CoverageTests`) actually correct?**
  _`ResearchService` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `TradingBot` (e.g. with `HyperliquidClient` and `AccountAudit`) actually correct?**
  _`TradingBot` has 6 INFERRED edges - model-reasoned connections that need verification._