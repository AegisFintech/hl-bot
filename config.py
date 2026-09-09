import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

HL_API_KEY = os.environ.get("HL_API_KEY", "")
HL_API_SECRET = os.environ.get("HL_API_SECRET", "")
HL_TESTNET = os.environ.get("HL_TESTNET", "true").lower() == "true"

SYMBOL = "BTC"
TIMEFRAME = "1m"
TP_PIPS = 5
SL_PIPS = 10
SR_LOOKBACK = 100
ORDER_SIZE_USD = 100

TRADES_FILE = DATA_DIR / "trades.json"
PERFORMANCE_FILE = DATA_DIR / "performance.json"
DASHBOARD_PORT = 8080
