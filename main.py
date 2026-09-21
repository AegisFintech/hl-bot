import logging

import config
from src.exchange.hyperliquid import HyperliquidClient
from src.bot import TradingBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("hl-bot")


def main():
    log.info("HL-Bot starting — %s on %s", config.SYMBOLS,
             "testnet" if config.HL_TESTNET else "MAINNET")

    client = HyperliquidClient(
        master_account=config.HL_MASTER_ACCOUNT,
        api_private_key=config.HL_API_PRIVATE_KEY,
        testnet=config.HL_TESTNET,
    )

    bot = TradingBot(
        client=client,
        coins=config.SYMBOLS,
        tp_pips=config.TP_PIPS,
        sl_pips=config.SL_PIPS,
        sr_lookback=config.SR_LOOKBACK,
        order_size_usd=config.ORDER_SIZE_USD,
        dashboard_port=config.DASHBOARD_PORT,
        trades_file=config.TRADES_FILE,
        performance_file=config.PERFORMANCE_FILE,
        auto_transfer_spot=config.AUTO_TRANSFER_SPOT,
        proximity_pct=config.PROXIMITY_PCT,
    )

    bot.start()


if __name__ == "__main__":
    main()
