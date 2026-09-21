import json
import time
import logging
import threading
from pathlib import Path

from src.exchange.hyperliquid import HyperliquidClient
from src.strategy.sr_detector import SRDetector
from src.strategy.scalper import Scalper
from src.risk.manager import RiskManager
from src.learning.evaluator import Evaluator
from src.reconciler import PositionReconciler
from src.dashboard.app import set_bot_reference, run_dashboard

log = logging.getLogger(__name__)


class TradingBot:

    def __init__(self, client: HyperliquidClient, coin: str = "BTC", coins: list | None = None,
                 tp_pips: int = 5, sl_pips: int = 10, sr_lookback: int = 100,
                 order_size_usd: float = 100, dashboard_port: int = 8080,
                 trades_file=None, performance_file=None,
                 auto_transfer_spot: bool = False, proximity_pct: float = 0.003):
        self.client = client
        self.coins = coins or [coin]
        self.coin = self.coins[0]
        self.running = False
        self.start_time = None
        self.auto_transfer_spot = auto_transfer_spot

        self.risk_manager = RiskManager(
            order_size_usd=order_size_usd,
            max_position_size_usd=order_size_usd,
            max_open_positions=len(self.coins),
        )
        self.evaluator = Evaluator(trades_file=trades_file, performance_file=performance_file)

        self._scalpers: list[Scalper] = []
        self._reconcilers: list[PositionReconciler] = []
        for c in self.coins:
            sr_det = SRDetector(lookback=sr_lookback)
            self._scalpers.append(Scalper(
                client=client, sr_detector=sr_det, risk_manager=self.risk_manager,
                coin=c, tp_pips=tp_pips, sl_pips=sl_pips, proximity_pct=proximity_pct,
            ))
            self._reconcilers.append(PositionReconciler(
                client=client, risk_manager=self.risk_manager,
                coin=c, tp_pips=tp_pips, sl_pips=sl_pips,
            ))

        # Primary-coin aliases for dashboard / learning
        self.sr_detector = self._scalpers[0].sr
        self.scalper = self._scalpers[0]
        self.reconciler = self._reconcilers[0]

        self._dashboard_port = dashboard_port
        self._pending_signals: dict = {}
        self._pending_signals_lock = threading.Lock()
        self._learning_interval = 300
        self._last_learning = 0.0
        self._leverage_set: set[str] = set()
        self._last_equity_fetch = 0.0
        self._equity_fetch_interval = 30.0
        self._tuning_file = Path(__file__).parent.parent / "data" / "tuning.json"
        self._tuning_mtime = 0.0
        self._last_tuning_check = 0.0
        self._tuning_check_interval = 60.0

    def start(self):
        log.info("Starting HL-Bot on %s (%s)", self.coins,
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
        urls = self.client.audit_urls()
        log.info("=== URL AUDIT ===")
        log.info("Info REST:     %s  [%s]", urls["info_rest"], "OK" if urls["info_ok"] else "MISMATCH")
        log.info("Exchange REST: %s  [%s]", urls["exchange_rest"], "OK" if urls["exchange_ok"] else "MISMATCH")
        log.info("Expected REST: %s", urls["expected_rest"])
        if not urls["info_ok"] or not urls["exchange_ok"]:
            log.critical("URL MISMATCH — refusing to start. Check HL_TESTNET in .env")
            raise SystemExit(1)

        log.info("=== IDENTITY ===")
        log.info("Master account:  %s", self.client.master_account)
        log.info("Agent signer:    %s", self.client.wallet.address)

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

        equity = available_to_trade if available_to_trade > 0 else perps_acct_value
        log.info("Effective equity (unified):       $%.2f", equity)

        self.risk_manager.update_equity(equity)
        self.risk_manager.reset_daily()

        if equity > 0:
            for c in self.coins:
                try:
                    self.client.set_leverage(c, 5, cross=True)
                    self._leverage_set.add(c)
                    log.info("Leverage set to 5x cross for %s", c)
                except Exception as e:
                    log.warning("Could not set leverage for %s: %s", c, e)

        log.info("=== POSITION RECONCILIATION ===")
        for rec in self._reconcilers:
            try:
                sync_result = rec.startup_sync()
                log.info("Reconciliation result [%s]: %s", rec.coin, sync_result)
                unrecorded = sync_result.get("unrecorded_fills", [])
                if unrecorded:
                    log.warning("Processing %d unrecorded fills from previous session [%s]",
                                len(unrecorded), rec.coin)
                    self._on_fill(unrecorded)
            except Exception as e:
                log.error("Startup reconciliation failed for %s: %s", rec.coin, e, exc_info=True)

        total_positions = sum(r.position_count for r in self._reconcilers)
        self.risk_manager.sync_open_positions(total_positions)

        log.info("=== STARTUP SUMMARY ===")
        log.info("Coins:              %s", self.coins)
        log.info("Spot USDC:          $%.2f", spot_usdc)
        log.info("Available to trade: $%.2f", available_to_trade)
        log.info("Perps acct value:   $%.2f", perps_acct_value)
        log.info("Effective equity:   $%.2f", equity)
        log.info("Leverage set:       %s", sorted(self._leverage_set))
        trading_enabled = equity > 0 and bool(self._leverage_set)
        log.info("Trading:            %s", "ENABLED" if trading_enabled else "DISABLED")

    def _subscribe_feeds(self):
        for c in self.coins:
            self.client.subscribe_bbo(c)
            self.client.subscribe_candles(c, "1m")
            self.client.subscribe_trades(c)
        self.client.subscribe_fills(callback=self._on_fill)
        self.client.subscribe_order_updates(callback=self._on_order_update)
        self.client.set_reconnect_callback(self._on_ws_reconnect)
        log.info("Subscribed to WebSocket feeds for %s", self.coins)
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
            counts = [len(self.client.get_cached_candles(c)) for c in self.coins]
            if all(n >= 20 for n in counts):
                break
            time.sleep(2)

        for scalper in self._scalpers:
            candles = self.client.get_cached_candles(scalper.coin)
            if len(candles) < 20:
                lookback_ms = max(scalper.sr.lookback, 1000) * 60 * 1000
                candles = self.client.get_candles(scalper.coin, "1m", lookback_ms)
                scalper.update_sr_levels(candles)
            else:
                scalper.update_sr_levels()

        log.info("S/R levels initialized for all coins.")
        log.info("Entering main loop.")

        while self.running:
            try:
                self._tick()
            except Exception as e:
                log.error("Tick error: %s", e, exc_info=True)
            time.sleep(1)

    def _tick(self):
        for rec in self._reconcilers:
            try:
                rec.periodic_check()
            except Exception as e:
                log.warning("Periodic reconciliation failed [%s]: %s", rec.coin, e)

        total_positions = sum(r.position_count for r in self._reconcilers)
        self.risk_manager.sync_open_positions(total_positions)

        self.risk_manager.check_daily_reset()
        self._check_tuning()

        now = time.time()
        if now - self._last_equity_fetch > self._equity_fetch_interval:
            try:
                equity = self.client.get_account_value()
                self.risk_manager.update_equity(equity)
                self._last_equity_fetch = now
            except Exception as e:
                log.warning("Equity fetch failed: %s", e)

        equity = self.risk_manager.state.current_equity

        for c in self.coins:
            if c not in self._leverage_set and equity > 0:
                try:
                    self.client.set_leverage(c, 5, cross=True)
                    self._leverage_set.add(c)
                    log.info("Leverage set to 5x cross for %s — equity: $%.2f", c, equity)
                except Exception as e:
                    log.warning("Could not set leverage for %s: %s", c, e)

        if self.risk_manager.should_kill():
            log.critical("Risk kill switch triggered — stopping bot")
            self.running = False
            return

        cutoff = now - 600
        with self._pending_signals_lock:
            stale = [p for p, s in self._pending_signals.items() if s.get("timestamp", now) < cutoff]
            for p in stale:
                self._pending_signals.pop(p, None)

        for scalper in self._scalpers:
            results = scalper.tick()
            with self._pending_signals_lock:
                for r in results:
                    signal = r["signal"]
                    self._pending_signals[signal["entry_price"]] = signal

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
                    if pnl < 0 and "sr_level" in matched_signal:
                        fill_coin = fill.get("coin")
                        for scalper in self._scalpers:
                            if scalper.coin == fill_coin:
                                scalper.blacklist_level(matched_signal["sr_level"])
                                break

                fill_coin = fill.get("coin")
                for rec in self._reconcilers:
                    if rec.coin == fill_coin:
                        try:
                            rec.periodic_check(force=True)
                        except Exception as e:
                            log.warning("Post-fill reconciliation failed [%s]: %s", fill_coin, e)
                        break

        total_positions = sum(r.position_count for r in self._reconcilers)
        self.risk_manager.sync_open_positions(total_positions)

    def _on_order_update(self, updates: list):
        for update in updates:
            status = update.get("status")
            if status in ("canceled", "rejected"):
                log.info("Order %s: %s %s oid=%s", status, update.get("coin"),
                         update.get("side"), update.get("oid"))
                update_coin = update.get("coin")
                for rec in self._reconcilers:
                    if rec.coin == update_coin:
                        try:
                            rec.periodic_check()
                        except Exception as e:
                            log.warning("Reconciliation after %s failed [%s]: %s",
                                        status, update_coin, e)
                        break

    def _on_ws_reconnect(self):
        log.info("WebSocket reconnected — backfilling missed fills")
        for rec in self._reconcilers:
            try:
                missed = rec.backfill_missed_fills()
                if missed:
                    log.info("Processing %d missed fills from WS gap [%s]", len(missed), rec.coin)
                    self._on_fill(missed)
                rec.periodic_check()
            except Exception as e:
                log.error("Post-reconnect backfill failed for %s: %s", rec.coin, e, exc_info=True)

        total_positions = sum(r.position_count for r in self._reconcilers)
        self.risk_manager.sync_open_positions(total_positions)

    def _match_fill_to_signal(self, fill: dict) -> dict | None:
        with self._pending_signals_lock:
            for price, signal in list(self._pending_signals.items()):
                if signal["coin"] == fill.get("coin"):
                    self._pending_signals.pop(price, None)
                    return signal
        return None

    def _check_tuning(self):
        now = time.time()
        if now - self._last_tuning_check < self._tuning_check_interval:
            return
        self._last_tuning_check = now

        if not self._tuning_file.exists():
            return

        try:
            mtime = self._tuning_file.stat().st_mtime
        except OSError:
            return

        if mtime <= self._tuning_mtime:
            return

        try:
            overrides = json.loads(self._tuning_file.read_text())
        except (json.JSONDecodeError, OSError):
            return

        self._tuning_mtime = mtime
        applied = []

        for scalper in self._scalpers:
            if "tp_pips" in overrides:
                scalper.tp_pips = int(overrides["tp_pips"])
                applied.append("tp_pips")
            if "sl_pips" in overrides:
                scalper.sl_pips = int(overrides["sl_pips"])
                applied.append("sl_pips")
            if "proximity_pct" in overrides:
                scalper.proximity_pct = float(overrides["proximity_pct"])
                applied.append("proximity_pct")
            if "signal_cooldown" in overrides:
                scalper._signal_cooldown = float(overrides["signal_cooldown"])
                applied.append("signal_cooldown")
            if "sr_lookback" in overrides:
                scalper.sr.lookback = int(overrides["sr_lookback"])
                applied.append("sr_lookback")
            if "min_touches" in overrides:
                scalper.sr.min_touches = int(overrides["min_touches"])
                applied.append("min_touches")

        if "order_size_usd" in overrides:
            self.risk_manager.order_size_usd = float(overrides["order_size_usd"])
            self.risk_manager.max_position_size_usd = float(overrides["order_size_usd"])
            applied.append("order_size_usd")

        if applied:
            unique = sorted(set(applied))
            log.info("Tuning overlay applied: %s", unique)

    def _run_learning(self):
        if len(self.evaluator.trades) < 10:
            return

        adjustments = self.evaluator.suggest_adjustments()
        if adjustments:
            log.info("Learning adjustments: %s", adjustments)
            # Apply to all coins' SR detectors
            for scalper in self._scalpers:
                scalper.sr.apply_adjustments(adjustments)

        perf = self.evaluator.get_performance()
        log.info("Performance — Win rate: %.1f%%, PF: %.2f, Sharpe: %.2f, Trades: %d",
                 perf.get("win_rate", 0) * 100, perf.get("profit_factor", 0),
                 perf.get("sharpe_ratio", 0), perf.get("total_trades", 0))
