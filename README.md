# HL-Bot

High-frequency AI scalping bot for [Hyperliquid](https://hyperliquid.xyz) DEX.

Identifies support/resistance zones and order blocks from real-time price action, places stop orders beyond confirmed zones with tight TP/SL, and continuously learns from its own trading history to refine detection.

## Architecture

```
src/
├── exchange/          Hyperliquid API wrapper (REST + WebSocket)
│   └── hyperliquid.py
├── strategy/          Signal generation
│   ├── sr_detector.py S/R zone + order block detection
│   └── scalper.py     Entry/exit logic
├── risk/              Position and risk management
│   └── manager.py
├── learning/          Self-improvement engine
│   └── evaluator.py   Trade evaluation + parameter tuning
├── dashboard/         Live web dashboard
│   ├── app.py
│   └── templates/
└── bot.py             Main trading loop
```

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Hyperliquid API keys
```

## Configuration

Only three environment variables — everything else is in `config.py`:

| Variable | Description |
|----------|-------------|
| `HL_API_KEY` | Hyperliquid API key |
| `HL_API_SECRET` | Hyperliquid API secret (wallet private key) |
| `HL_TESTNET` | `true` for testnet demo trading (default) |

## Usage

```bash
# Run the trading bot
python main.py

# Run the dashboard only
python -m src.dashboard.app
```

## Strategy

1. **S/R Detection** — Identifies major support/resistance zones from swing highs/lows, volume clusters, and order flow
2. **Order Placement** — Stop orders placed beyond confirmed S/R zones
3. **Risk Management** — TP = 5 pips, SL = 10 pips per trade. High win-rate targeting
4. **Self-Learning** — Every trade is logged with full context. The evaluator computes which S/R patterns produce winners and adjusts detection parameters automatically

## Dashboard

Web UI at `http://localhost:8080` showing:
- Bot status (running/stopped, uptime)
- Open positions and pending orders
- Trade history with entry/exit details
- Cumulative P/L chart
- Live S/R levels overlaid on price

## Testnet

The bot defaults to Hyperliquid testnet. Get testnet funds at [https://app.hyperliquid-testnet.xyz](https://app.hyperliquid-testnet.xyz).

## License

MIT
