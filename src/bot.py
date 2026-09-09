import time
import logging
import threading

from src.exchange.hyperliquid import HyperliquidClient
from src.strategy.sr_detector import SRDetector
from src.strategy.scalper import Scalper
from src.risk.manager import RiskManager
from src.learning.evaluator import Evaluator
from src.dashboard.app import set_bot_reference, run_dashboard

log = logging.getLogger(__name__)


class TradingBot:

    def __init__(self, client: HyperliquidClient, coin: str, tp_pips: int = 5,
                 sl_pips: int = 10, sr_lookback: int = 100, order_size_usd: float = 100,
                 dashboard_port: int = 8080, trades_file=None, performance_file=None):
        self.client = client
        self.coin = coin
        self.running = False
        self.start_time = None

        self.sr_detector = SRDetector(lookback=sr_lookback)
        self.risk_manager = RiskManager(order_size_usd=order_size_usd, max_position_size_usd=order_size_usd)
        self.evaluator = Evaluator(trades_file=trades_file, performance_file=performance_file)
        self.scalper = Scalper(
            client=client, sr_detector=self.sr_detector, risk_manager=self.risk_manager,
            coin=coin, tp_pips=tp_pips, sl_pips=sl_pips,
        )

        self._dashboard_port = dashboard_port
        self._fill_thread = None
        self._pending_signals = {}
        self._learning_interval = 300
        self._last_learning = 0.0

    def start(self):
        log.info("Starting HL-Bot on %s (%s)", self.coin,
                 "testnet" if self.client.testnet else "MAINNET")

        self._init_exchange()
        self._subscribe_feeds()
        self._start_dashboard()

        self.running = True
        self.start_time = time.time()
        log.info("Bot is live. Dashboard at http://localhost:%d", self._dashboard_port)

        try:
            self._run_loop()
        except KeyboardInterrupt:
            log.info("Shutting down...")
        finally:
            self.running = False

    def _init_exchange(self):
        equity = self.client.get_account_value()
        self.risk_manager.update_equity(equity)
        self.risk_manager.reset_daily()
        log.info("Account equity: $%.2f", equity)

        self.client.set_leverage(self.coin, 5, cross=True)
        log.info("Leverage set to 5x cross for %s", self.coin)

    def _subscribe_feeds(self):
        self.client.subscribe_bbo(self.coin)
        self.client.subscribe_candles(self.coin, "1m")
        self.client.subscribe_trades(self.coin)
        self.client.subscribe_fills(callback=self._on_fill)
        self.client.subscribe_order_updates(callback=self._on_order_update)
        log.info("Subscribed to WebSocket feeds for %s", self.coin)
        time.sleep(3)

    def _start_dashboard(self):
        set_bot_reference(self)
        thread = threading.Thread(target=run_dashboard, kwargs={"port": self._dashboard_port}, daemon=True)
        thread.start()

    def _run_loop(self):
        log.info("Waiting for initial candle data...")
        for _ in range(30):
            candles = self.client.get_cached_candles(self.coin)
            if len(candles) >= 20:
                break
            time.sleep(2)

        if len(self.client.get_cached_candles(self.coin)) < 20:
            candles = self.client.get_candles(self.coin, "1m", self.sr_detector.lookback * 60 * 1000)
            self.scalper.update_sr_levels(candles)
        else:
            self.scalper.update_sr_levels()

        log.info("S/R levels initialized. Entering main loop.")

        while self.running:
            try:
                self._tick()
            except Exception as e:
                log.error("Tick error: %s", e, exc_info=True)
            time.sleep(1)

    def _tick(self):
        equity = self.client.get_account_value()
        self.risk_manager.update_equity(equity)

        if self.risk_manager.should_kill():
            log.critical("Risk kill switch triggered — stopping bot")
            self.running = False
            return

        results = self.scalper.tick()
        for r in results:
            signal = r["signal"]
            self._pending_signals[signal["entry_price"]] = signal

        now = time.time()
        if now - self._last_learning > self._learning_interval:
            self._run_learning()
            self._last_learning = now

    def _on_fill(self, fills: list):
        for fill in fills:
            log.info("Fill: %s %s %s @ %s", fill.get("side"), fill.get("coin"),
                     fill.get("sz"), fill.get("px"))

            if fill.get("closedPnl") and float(fill["closedPnl"]) != 0:
                pnl = float(fill["closedPnl"])
                self.risk_manager.record_fill(pnl)

                exit_price = float(fill["px"])
                matched_signal = self._match_fill_to_signal(fill)
                if matched_signal:
                    exit_reason = "tp" if pnl > 0 else "sl"
                    self.evaluator.record_trade(
                        signal_dict=matched_signal, exit_price=exit_price,
                        size=float(fill["sz"]), pnl=pnl, exit_reason=exit_reason,
                    )

    def _on_order_update(self, updates: list):
        for update in updates:
            status = update.get("status")
            if status in ("canceled", "rejected"):
                log.info("Order %s: %s %s", status, update.get("coin"), update.get("oid"))

    def _match_fill_to_signal(self, fill: dict) -> dict | None:
        for price, signal in list(self._pending_signals.items()):
            if signal["coin"] == fill.get("coin"):
                self._pending_signals.pop(price, None)
                return signal
        return None

    def _run_learning(self):
        if len(self.evaluator.trades) < 10:
            return

        adjustments = self.evaluator.suggest_adjustments()
        if adjustments:
            log.info("Learning adjustments: %s", adjustments)
            self.sr_detector.apply_adjustments(adjustments)

        perf = self.evaluator.get_performance()
        log.info("Performance — Win rate: %.1f%%, PF: %.2f, Sharpe: %.2f, Trades: %d",
                 perf.get("win_rate", 0) * 100, perf.get("profit_factor", 0),
                 perf.get("sharpe_ratio", 0), perf.get("total_trades", 0))
