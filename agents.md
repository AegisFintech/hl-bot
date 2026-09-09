# Agents

## Market Data Agent
**Module:** `src/exchange/hyperliquid.py`
**Role:** Connects to Hyperliquid via SDK. Streams real-time price data, orderbook depth, and candle history. Provides clean data interface to strategy agents.

## S/R Detection Agent
**Module:** `src/strategy/sr_detector.py`
**Role:** Analyzes price action to identify major support and resistance zones. Uses swing high/low clustering, volume profile, and order flow imbalance. Outputs ranked S/R levels with confidence scores.

## Scalper Agent
**Module:** `src/strategy/scalper.py`
**Role:** Core trading logic. Monitors price relative to S/R zones. Places stop orders beyond confirmed zones — buy stops above resistance breaks, sell stops below support breaks. Manages TP (5 pips) and SL (10 pips) per trade.

## Risk Manager Agent
**Module:** `src/risk/manager.py`
**Role:** Enforces position limits, max drawdown, and daily loss caps. Validates every order before submission. Kills the bot if risk thresholds are breached.

## Learning Agent
**Module:** `src/learning/evaluator.py`
**Role:** Post-trade analysis engine. Logs every trade with entry context (which S/R level, confidence, market conditions). Computes win rate, avg P/L, Sharpe ratio. Identifies which S/R patterns produce winning trades and feeds adjustments back to the detector.

## Dashboard Agent
**Module:** `src/dashboard/app.py`
**Role:** Flask web UI showing live bot status, open positions, trade history, cumulative P/L chart, and S/R levels on a price chart. Auto-refreshes via WebSocket.
