import json
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
                 dashboard_port: int = 8080, trades_file=None, performance_file=None,
                 auto_transfer_spot: bool = False):
        self.client = client
        self.coin = coin
        self.running = False
        self.start_time = None
        self.auto_transfer_spot = auto_transfer_spot

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
        self._leverage_set = False

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
        # === 1. URL audit ===
        urls = self.client.audit_urls()
        log.info("=== URL AUDIT ===")
        log.info("Info REST:     %s  [%s]", urls["info_rest"], "OK" if urls["info_ok"] else "MISMATCH")
        log.info("Exchange REST: %s  [%s]", urls["exchange_rest"], "OK" if urls["exchange_ok"] else "MISMATCH")
        log.info("Expected REST: %s", urls["expected_rest"])
        if not urls["info_ok"] or not urls["exchange_ok"]:
            log.critical("URL MISMATCH — refusing to start. Check HL_TESTNET in .env")
            raise SystemExit(1)

        # === 2. Identity ===
        log.info("=== IDENTITY ===")
        log.info("Master account:  %s", self.client.master_account)
        log.info("Agent signer:    %s", self.client.wallet.address)

        # === 3. Agent registration preflight ===
        log.info("=== AGENT PREFLIGHT (testnet) ===")
        preflight = self.client.preflight_check_agent()
        log.info("extraAgents raw: %s", json.dumps(preflight["extra_agents_raw"], indent=2))
        log.info("subAccounts raw: %s", json.dumps(preflight["sub_accounts_raw"], indent=2))

        if not preflight["agent_registered"]:
            log.critical(
                "AGENT NOT REGISTERED on testnet. Agent %s is NOT in extraAgents for master %s. "
                "Go to https://app.hyperliquid-testnet.xyz → Settings → API Wallets → approve this agent. "
                "Stopping.",
                preflight["agent_address"], self.client.master_account,
            )
            raise SystemExit(1)

        log.info("Agent %s is REGISTERED on testnet — OK", preflight["agent_address"])

        # === 4. Account state ===
        log.info("=== ACCOUNT STATE ===")
        user_state = self.client.get_user_state()
        log.info("Raw user_state (perps): %s", json.dumps(user_state, indent=2))

        spot_state = self.client.get_spot_user_state()
        log.info("Raw spot_user_state: %s", json.dumps(spot_state, indent=2))

        perps_acct_value = float(user_state.get("marginSummary", {}).get("accountValue", 0))
        spot_usdc = self.client.get_spot_usdc_balance()
        available_to_trade = self.client.get_available_to_trade()

        log.info("perps marginSummary.accountValue: $%.2f", perps_acct_value)
        log.info("spot USDC balance (total):        $%.2f", spot_usdc)
        log.info("tokenToAvailableAfterMaintenance: $%.2f", available_to_trade)

        # Unified mode: spot USDC IS the perps margin. No transfer needed.
        # Use available_to_trade as the effective equity.
        equity = available_to_trade if available_to_trade > 0 else perps_acct_value
        log.info("Effective equity (unified):       $%.2f", equity)

        self.risk_manager.update_equity(equity)
        self.risk_manager.reset_daily()

        # === 5. Leverage ===
        if equity > 0:
            try:
                self.client.set_leverage(self.coin, 5, cross=True)
                self._leverage_set = True
                log.info("Leverage set to 5x cross for %s", self.coin)
            except Exception as e:
                log.warning("Could not set leverage: %s", e)

        # === 6. Summary ===
        log.info("=== STARTUP SUMMARY ===")
        log.info("Spot USDC:          $%.2f", spot_usdc)
        log.info("Available to trade: $%.2f", available_to_trade)
        log.info("Perps acct value:   $%.2f", perps_acct_value)
        log.info("Effective equity:   $%.2f", equity)
        log.info("Leverage set:       %s", self._leverage_set)
        trading_enabled = equity > 0 and self._leverage_set
        log.info("Trading:            %s", "ENABLED" if trading_enabled else "DISABLED")

    def _subscribe_feeds(self):
        self.client.subscribe_bbo(self.coin)
        self.client.subscribe_candles(self.coin, "1m")
        self.client.subscribe_trades(self.coin)
        self.client.subscribe_fills(callback=self._on_fill)
        self.client.subscribe_order_updates(callback=self._on_order_update)
        log.info("Subscribed to WebSocket feeds for %s", self.coin)
        time.sleep(3)
        urls = self.client.audit_urls()
        ws_url = urls["ws"] or "(not yet connected)"
        log.info("WebSocket URL: %s  [%s]", ws_url, "OK" if urls["ws_ok"] else "MISMATCH")

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

        log.info("S/R levels initialized.")

        # Dry-run: show what the first order would look like
        signals = self.scalper.scan_for_signals()
        if signals:
            payload = self.scalper.build_order_payload(signals[0])
            if payload:
                log.info("=== DRY RUN — first order payload ===")
                log.info("%s", json.dumps(payload, indent=2, default=str))
            else:
                log.info("DRY RUN: signal found but risk manager blocked or size=0")
        else:
            log.info("DRY RUN: no signals at current price (will scan each tick)")

        log.info("Entering main loop.")

        while self.running:
            try:
                self._tick()
            except Exception as e:
                log.error("Tick error: %s", e, exc_info=True)
            time.sleep(1)

    def _tick(self):
        equity = self.client.get_account_value()
        self.risk_manager.update_equity(equity)

        if not self._leverage_set and equity > 0:
            try:
                self.client.set_leverage(self.coin, 5, cross=True)
                self._leverage_set = True
                log.info("Leverage set to 5x cross — equity: $%.2f — trading enabled", equity)
            except Exception as e:
                log.warning("Could not set leverage: %s", e)

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
