import logging
import time
from pathlib import Path
from src.logging_setup import file_handler

import config
from src.exchange.hyperliquid import HyperliquidClient
from src.bot import TradingBot

logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler(Path(__file__).resolve().parent / "bot.log"), logging.StreamHandler()],
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("hl-bot")


def connect(delay=5):
    """The exchange being briefly unreachable must not crash-loop the service."""
    while True:
        try:
            return HyperliquidClient(
                master_account=config.HL_MASTER_ACCOUNT,
                api_private_key=config.HL_API_PRIVATE_KEY,
                testnet=config.HL_TESTNET,
            )
        except ValueError:
            raise  # Malformed key or address: retrying cannot help.
        except Exception as exc:
            log.error("Exchange client unavailable (%s); retrying in %ds", exc, delay)
            time.sleep(delay)
            delay = min(delay * 2, 300)


def main():
    settings = config.SETTINGS.validate()
    log.info("HL-Bot starting: %s %s on %s bars for %s (%s)", settings.strategy, settings.strategy_params or "",
             settings.interval, settings.coins, "testnet" if config.HL_TESTNET else "MAINNET")
    if not config.HL_TESTNET:
        raise SystemExit("Only testnet trading is authorized; set HL_TESTNET=true")
    bot = TradingBot(
        client=connect(),
        settings=settings,
        trades_file=config.TRADES_FILE,
        performance_file=config.PERFORMANCE_FILE,
    )
    bot.start()


if __name__ == "__main__":
    main()
