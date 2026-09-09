# HL-Bot — Hyperliquid AI Scalping System

## Project overview
High-frequency AI scalping bot for Hyperliquid DEX. Identifies support/resistance zones and order blocks, places stop orders with 5-pip TP / 10-pip SL. Runs on testnet for demo trading. Built for self-improvement — logs trades, evaluates performance, and refines detection.

## Architecture
- `src/exchange/` — Hyperliquid API wrapper (REST + WebSocket)
- `src/strategy/` — S/R detection, order block identification, scalping logic
- `src/risk/` — Position sizing, TP/SL management
- `src/learning/` — Trade evaluation, performance analysis, parameter tuning
- `src/dashboard/` — Flask web dashboard for live status and P/L
- `config.py` — Loads `.env`, all constants
- `main.py` — Entry point

## Commands
```bash
pip install -r requirements.txt    # install deps
python main.py                     # run the bot
python -m src.dashboard.app        # run dashboard only
```

## Key decisions
- Python 3.10+ required
- Hyperliquid Python SDK for exchange connectivity
- No backtesting — straight to testnet demo trading
- Minimal .env — only HL_API_KEY, HL_API_SECRET, HL_TESTNET
- Self-learning: trade log → evaluation → parameter adjustment

## Git workflow
Every task gets a GitHub issue. Work is done on feature branches, PRs auto-merged for traceability.
