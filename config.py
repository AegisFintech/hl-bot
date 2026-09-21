import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

HL_MASTER_ACCOUNT = os.environ.get("HL_MASTER_ACCOUNT", "")
HL_API_PRIVATE_KEY = os.environ.get("HL_API_PRIVATE_KEY", "")
HL_TESTNET = os.environ.get("HL_TESTNET", "true").lower() == "true"

SYMBOL = "BTC"
SYMBOLS = ["BTC"]
TIMEFRAME = "1m"
TP_PIPS = 150
SL_PIPS = 50
SR_LOOKBACK = 500
ORDER_SIZE_USD = 100
PROXIMITY_PCT = float(os.environ.get("PROXIMITY_PCT", "0.003"))

AUTO_TRANSFER_SPOT = os.environ.get("AUTO_TRANSFER_SPOT", "false").lower() == "true"

TRADES_FILE = DATA_DIR / "trades.json"
PERFORMANCE_FILE = DATA_DIR / "performance.json"
DASHBOARD_PORT = 8080
