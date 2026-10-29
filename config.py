import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from src.settings import Settings  # noqa: E402  (reads the environment loaded above)

DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

HL_MASTER_ACCOUNT = os.environ.get("HL_MASTER_ACCOUNT", "")
HL_API_PRIVATE_KEY = os.environ.get("HL_API_PRIVATE_KEY", "")
HL_TESTNET = os.environ.get("HL_TESTNET", "true").lower() == "true"
AUTO_TRANSFER_SPOT = os.environ.get("AUTO_TRANSFER_SPOT", "false").lower() == "true"

SETTINGS = Settings.from_env()
SYMBOLS = SETTINGS.coins
SYMBOL = SYMBOLS[0]
DASHBOARD_PORT = SETTINGS.dashboard_port

TRADES_FILE = DATA_DIR / "trades.json"
PERFORMANCE_FILE = DATA_DIR / "performance.json"
