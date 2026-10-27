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
from src.learning.ledger import FillLedger
from src.learning.quality import QualityAudit, candle_context
from src.learning.funding import FundingSync
from src.research.service import ResearchService
from src.reconciler import PositionReconciler
from src.dashboard.app import set_bot_reference, run_dashboard

log = logging.getLogger(__name__)


class TradingBot:

    def __init__(self, client: HyperliquidClient, coin: str = "BTC", coins: list | None = None,
                 tp_pips: int = 30, sl_pips: int = 15, sr_lookback: int = 100,
                 order_size_usd: float = 100, dashboard_port: int = 8080,
                 trades_file=None, performance_file=None,
                 auto_transfer_spot: bool = False, proximity_pct: float = 0.003):
        self.client = client
        ALLOWED_COINS = {"BTC"}
        requested = coins or [coin]
        self.coins = [c for c in requested if c in ALLOWED_COINS] or ["BTC"]
        if set(requested) != set(self.coins):
            log.warning("Filtered coins %s → %s (only %s allowed)", requested, self.coins, ALLOWED_COINS)
        self.coin = self.coins[0]
        self.running = False
        self.start_time = None
        self.auto_transfer_spot = auto_transfer_spot

        self.risk_manager = RiskManager(
            order_size_usd=order_size_usd,
            max_position_size_usd=order_size_usd,
            max_open_positions=len(self.coins),
            state_file=Path(__file__).resolve().parents[1] / "data/risk_state.json",
        )
        self.evaluator = Evaluator(trades_file=trades_file, performance_file=performance_file)

        self.ledger = FillLedger(Path(__file__).resolve().parents[1] / "data/ledger.sqlite")
        self.research = ResearchService(Path(__file__).resolve().parents[1] / "data/research.sqlite")
        self.quality = QualityAudit(Path(__file__).resolve().parents[1] / "data/quality.sqlite")
        self.funding_sync = None
        self._audit_thread = None
        self._audit_stop = threading.Event()
        self.account_snapshot = {}
        self._halt_cleanup_at = 0.0
        self.halt_cleanup_status = "Not required"
        self._last_order_maintenance = 0.0
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
        self._active_signals: dict[str, list[dict]] = {}
        self._processed_fill_ids: set[str] = set()
        self._exit_fill_buffer: dict[str, list] = {}
        self._exit_fill_buffer_time: dict[str, float] = {}
        self._exit_fill_lock = threading.Lock()
        self._learning_interval = 300
        self._last_learning = 0.0
        self._leverage_set: set[str] = set()
        self._last_equity_fetch = 0.0
        self._equity_fetch_interval = 5.0
        self._tuning_file = Path(__file__).parent.parent / "data" / "tuning.json"
        self._tuning_mtime = 0.0
        self._last_tuning_check = 0.0
        self._tuning_check_interval = 60.0

    def start(self):
        log.info("Starting HL-Bot on %s (%s)", self.coins,
                 "testnet" if self.client.testnet else "MAINNET")

        if not self.client.testnet:
            raise RuntimeError("Only testnet trading is authorized")
        self._init_exchange()
        self._subscribe_feeds()
        self.research.start()
        first = self.ledger.performance().get('first_time') or int(time.time()*1000)
        self.funding_sync = FundingSync(self.quality.path, self.client.address, first)
        self.funding_sync.start()
        self._audit_thread = threading.Thread(target=self._audit_loop, name='testnet-quality', daemon=True)
        self._audit_thread.start()
        self._start_dashboard()

        self.running = True
        self.start_time = time.time()
        log.info("Bot is live. Dashboard at http://localhost:%d", self._dashboard_port)

        try:
            self._run_loop()
        except KeyboardInterrupt:
            log.info("Shutting down...")
        finally:
            self._audit_stop.set()
            if self.funding_sync:
                self.funding_sync.stop_event.set()
            self.research.stop()
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

        fees = self.client.info.user_fees(self.client.address)
        for scalper in self._scalpers:
            scalper.fee_entry = float(fees['userAddRate'])
            scalper.fee_exit = float(fees['userCrossRate'])

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

        self.account_snapshot = self.client.get_account_snapshot()
        equity = self.account_snapshot["equity"]
        log.info("Effective equity (unified):       $%.2f", equity)

        self.risk_manager.update_equity(equity)
        self.risk_manager.check_daily_reset()
        self.ledger.sample_equity(equity, self.risk_manager.state.peak_equity)
        for fill in self.client.get_fills(2000):
            self.ledger.add(fill)
        self._processed_fill_ids = {self.ledger.identity(f) for f in self.ledger.fills(2000)}

        if equity > 0:
            for c in self.coins:
                try:
                    self.client.set_leverage(c, 5, cross=True)
                    self._leverage_set.add(c)
                    log.info("Leverage set to 5x cross for %s", c)
                except Exception as e:
                    log.warning("Could not set leverage for %s: %s", c, e)

        if self.risk_manager.should_kill():
            self._emergency_flatten()
            return

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
                self.risk_manager.pause_execution("Startup reconciliation failed: " + type(e).__name__)
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

    def _audit_quote(self, coin):
        bbo, received_at = self.client.get_audit_bbo(coin)
        now = time.time()
        return self.quality.quote(bbo, now-received_at, now)

    def _audit_loop(self):
        while not self._audit_stop.is_set():
            try:
                quote = self._audit_quote(self.coin)
                self.quality.tick(quote, self.client.get_cached_candles(self.coin), self.coin)
            except (ValueError, TypeError, KeyError):
                pass  # Missing data is never replaced with invented observations.
            except Exception:
                log.exception('Observation-only quality audit failed')
            self._audit_stop.wait(1)

    def _subscribe_feeds(self):
        for c in self.coins:
            self.client.subscribe_bbo(c)
            self.client.subscribe_l2(c)
            history = self.client.get_candles(c, '1m', 2000*60000)
            with self.client._lock:
                self.client._candles[f'{c}_1m'] = sorted(history, key=lambda b: int(b['t']))[-2000:]
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

    def _emergency_flatten(self):
        # Keep dashboard and retry loop alive until exchange confirms flat, even after restart.
        if time.time() - self._halt_cleanup_at < 5:
            return
        self._halt_cleanup_at = time.time()
        cleanup_coins = set(self.coins)
        try:
            cleanup_coins.update(p['position']['coin'] for p in self.client.get_positions())
            cleanup_coins.update(o['coin'] for o in self.client.get_open_orders())
        except Exception:
            log.exception('Unable to enumerate full account exposure; cleaning known instruments')
        for coin in cleanup_coins:
            # Cancellation failures must not prevent attempting to close exposure.
            for action in (lambda: self.client.cancel_all_orders(coin),
                           lambda: self.client.close_position(coin),
                           lambda: self.client.cancel_all_orders(coin)):
                try:
                    action()
                except Exception:
                    log.exception('Emergency action failed for %s; retrying', coin)
        try:
            positions = self.client.get_positions()
            orders = self.client.get_open_orders()
            flat = not positions
            clear = not orders
            self.halt_cleanup_status = 'Confirmed flat; no orders' if flat and clear else 'Exposure/orders remain; retrying'
            self.risk_manager.sync_open_positions(len(positions))
            self.account_snapshot = self.client.get_account_snapshot()
            self.risk_manager.update_equity(self.account_snapshot['equity'])
            self.ledger.sample_equity(self.risk_manager.state.current_equity, self.risk_manager.state.peak_equity)
            # Three independent successful checks, at least 15s apart, while flat.
            healthy = (flat and clear and all(0 <= self.client.bbo_age(c) <= 10 for c in self.coins)
                       and self.account_snapshot['equity'] > 0)
            now = time.time()
            if not healthy:
                self._recovery_checks = 0
                self._recovery_check_at = 0
            elif now - getattr(self, '_recovery_check_at', 0) >= 15:
                self._recovery_checks = getattr(self, '_recovery_checks', 0) + 1
                self._recovery_check_at = now
            state = self.risk_manager.state
            if (getattr(state, 'execution_paused', False) and not state.halted
                    and getattr(self, '_recovery_checks', 0) >= 3):
                if self.risk_manager.resume_execution():
                    self._recovery_checks = 0
                    for rec in self._reconcilers:
                        rec.position_count = 0
                    self.risk_manager.state.open_order_count = 0
                    self.halt_cleanup_status = 'Operational recovery verified; execution resumed'
        except Exception:
            self._recovery_checks = 0
            self._recovery_check_at = 0
            self.halt_cleanup_status = 'Unable to confirm flat; retrying'
            log.exception('Emergency confirmation failed')

    def _tick(self):
        if self.risk_manager.should_kill():
            self._emergency_flatten()
            return
        for rec in self._reconcilers:
            try:
                rec.periodic_check()
            except Exception as e:
                log.warning("Periodic reconciliation failed [%s]: %s", rec.coin, e)

        total_positions = sum(r.position_count for r in self._reconcilers)
        self.risk_manager.sync_open_positions(total_positions)

        self._flush_exit_buffers()

        self.risk_manager.check_daily_reset()
        # Unvalidated runtime tuning is intentionally disabled.

        now = time.time()
        if now - self._last_equity_fetch > self._equity_fetch_interval:
            try:
                self.account_snapshot = self.client.get_account_snapshot()
                equity = self.account_snapshot["equity"]
                self.risk_manager.update_equity(equity)
                self.ledger.sample_equity(equity, self.risk_manager.state.peak_equity)
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
            log.critical("Risk halt latched — flattening and preserving dashboard")
            self._emergency_flatten()
            return

        cutoff = now - 3600
        with self._pending_signals_lock:
            stale = [p for p, s in self._pending_signals.items() if s.get("timestamp", now) < cutoff]
            for p in stale:
                self._pending_signals.pop(p, None)

        maintain_orders = now - self._last_order_maintenance > 15
        if maintain_orders:
            self._last_order_maintenance = now
        for scalper in self._scalpers:
            if scalper.coin not in self._leverage_set:
                continue
            if maintain_orders:
                self._expire_entries(scalper.coin, now)
            cutoff = time.time() - scalper._signal_cooldown
            scalper._recent_entries = {k: v for k, v in scalper._recent_entries.items() if v > cutoff}

            signals = scalper.scan_for_signals()
            for signal in signals[:1]:
                signal_dict = signal.to_dict()
                with self._pending_signals_lock:
                    if signal.entry_price in self._pending_signals:
                        continue
                audit_id = None
                try:
                    quote = self._audit_quote(scalper.coin)
                    try:
                        context = candle_context(self.client.get_cached_candles(scalper.coin), time.time())
                    except (ValueError, KeyError, TypeError):
                        context = {'regime': 'unknown'}
                    audit_id = self.quality.decision(signal_dict, context, quote, scalper.diagnostics)
                    self.quality.journal.signal('incumbent_candidate_v1', 1 if signal.side == 'long' else -1,
                                                quote, 'Actual candidate before execution admission; unequal selection versus five-minute challengers',
                                                regime=context['regime'])
                except Exception:
                    log.exception('Could not persist candidate audit')
                result = scalper.execute_signal(signal)
                if audit_id:
                    try:
                        self.quality.result(audit_id, result, scalper.diagnostics.get('reason', 'unknown'))
                    except Exception:
                        log.exception('Could not persist candidate result')
                if result:
                    with self._pending_signals_lock:
                        self._pending_signals[signal.entry_price] = signal_dict
                    self._cancel_stale_entries(scalper.coin, signal.entry_price)

        if now - self._last_learning > self._learning_interval:
            # Report only: never fit strategy parameters to the live evaluation window.
            self.evaluator.get_performance()
            self._last_learning = now

    def _expire_entries(self, coin, now):
        orders = self.client.get_open_orders()
        expired = [o for o in orders if o['coin'] == coin and not o.get('reduceOnly')
                   and now*1000 - int(o.get('timestamp', now*1000)) > 300000]
        if not expired:
            return
        # Cancel only parents first: a fill may have arrived since cached position sync.
        for order in expired:
            self.client.cancel_order(coin, order['oid'])
        for rec in self._reconcilers:
            if rec.coin == coin:
                rec._grace_until = 0
                rec.periodic_check(force=True)
        # With parent cancellation acknowledged, no further entry can fill.
        # Only confirmed-flat accounts may have their orphaned children removed.
        if not any(p['position']['coin'] == coin for p in self.client.get_positions()):
            self.client.cancel_all_orders(coin)
        with self._pending_signals_lock:
            for price in list(self._pending_signals):
                if self._pending_signals[price].get('coin') == coin:
                    self._pending_signals.pop(price)

    def _on_fill(self, fills: list):
        for fill in fills:
            fid = self.ledger.identity(fill)
            if fid in self._processed_fill_ids:
                continue
            if not self.ledger.add(fill):
                continue
            try:
                quote = self._audit_quote(fill.get('coin'))
            except Exception:
                quote = None
            self._processed_fill_ids.add(fid)
            if len(self._processed_fill_ids) > 1000:
                self._processed_fill_ids = set(list(self._processed_fill_ids)[-500:])

            log.info("Fill: %s %s %s @ %s", fill.get("side"), fill.get("coin"),
                     fill.get("sz"), fill.get("px"))

            fill_coin = fill.get("coin")
            closed_pnl = float(fill.get("closedPnl", 0) or 0)

            is_close = "Close" in fill.get("dir", "") or closed_pnl != 0
            self.risk_manager.record_fill(closed_pnl - float(fill.get("fee", 0)))
            try:
                self.quality.fill(fill, quote)
            except Exception:
                log.exception('Could not persist prospective fill audit')
            if is_close:
                exit_price = float(fill["px"])
                fill_size = float(fill["sz"])

                with self._pending_signals_lock:
                    signal = self._match_active_signal(fill_coin, fill)

                if not signal:
                    fill_side = fill.get("side")
                    if fill_side == "A":
                        side = "long"
                        implied_entry = exit_price - closed_pnl / fill_size if fill_size > 0 else exit_price
                    else:
                        side = "short"
                        implied_entry = exit_price + closed_pnl / fill_size if fill_size > 0 else exit_price
                    signal = {
                        "coin": fill_coin, "side": side,
                        "entry_price": implied_entry,
                        "tp_price": 0, "sl_price": 0,
                        "sr_level": implied_entry, "sr_kind": "unknown",
                        "sr_strength": 0, "ob_zone": None,
                        "timestamp": time.time(),
                    }
                    log.warning("No active signal for %s exit — using synthetic (entry=%.2f)",
                                fill_coin, implied_entry)

                exit_reason = self._classify_exit(signal, exit_price, closed_pnl)
                with self._exit_fill_lock:
                    self._exit_fill_buffer.setdefault(fill_coin, []).append({
                        "signal": signal,
                        "exit_price": exit_price,
                        "size": fill_size,
                        "pnl": closed_pnl,
                        "exit_reason": exit_reason,
                    })
                    if fill_coin not in self._exit_fill_buffer_time:
                        self._exit_fill_buffer_time[fill_coin] = time.time()
            else:
                matched = self._match_fill_to_signal(fill)
                if matched:
                    with self._pending_signals_lock:
                        self._active_signals.setdefault(fill_coin, []).append(matched)

            for rec in self._reconcilers:
                if rec.coin == fill_coin:
                    fill_time = int(fill.get("time", 0))
                    if fill_time > rec._last_fill_time:
                        rec._last_fill_time = fill_time
                    if fid:
                        rec._processed_fill_ids.add(fid)
                    try:
                        if is_close:
                            rec._grace_until = time.time() + 60
                        else:
                            rec._grace_until = time.time() + 30
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

    def _match_active_signal(self, coin: str, fill: dict) -> dict | None:
        """Match fill to active signal without removing it (partial fills reuse the signal)."""
        signals = self._active_signals.get(coin, [])
        if not signals:
            return None
        if len(signals) == 1:
            return signals[0]

        exit_px = float(fill["px"])
        pnl = float(fill.get("closedPnl", 0) or 0)
        size = float(fill.get("sz", 0) or 0)
        fill_side = fill.get("side")

        if size > 0 and pnl != 0:
            if fill_side == "A":
                implied_entry = exit_px - pnl / size
            else:
                implied_entry = exit_px + pnl / size

            best_idx = 0
            best_dist = float("inf")
            for i, sig in enumerate(signals):
                dist = abs(sig["entry_price"] - implied_entry)
                if dist < best_dist:
                    best_dist = dist
                    best_idx = i
            return signals[best_idx]

        expected_side = "long" if fill_side == "A" else "short"
        for i, sig in enumerate(signals):
            if sig["side"] == expected_side:
                return signals[i]
        return signals[0]

    def _match_fill_to_signal(self, fill: dict) -> dict | None:
        fill_coin = fill.get("coin")
        fill_px = float(fill.get("px", 0))
        with self._pending_signals_lock:
            best_key = None
            best_dist = float("inf")
            for price, signal in self._pending_signals.items():
                if signal["coin"] != fill_coin:
                    continue
                dist = abs(fill_px - signal["entry_price"])
                if dist < best_dist:
                    best_dist = dist
                    best_key = price
            if best_key is not None:
                return self._pending_signals.pop(best_key)
        return None

    @staticmethod
    def _classify_exit(signal: dict, exit_price: float, pnl: float) -> str:
        tp = signal.get("tp_price", 0)
        sl = signal.get("sl_price", 0)
        if tp and sl:
            dist_tp = abs(exit_price - tp)
            dist_sl = abs(exit_price - sl)
            near_tp = dist_tp <= dist_sl
            if near_tp and pnl >= 0:
                return "tp"
            if not near_tp and pnl < 0:
                return "sl"
        return "tp" if pnl > 0 else "sl"

    def _flush_exit_buffers(self):
        now = time.time()
        coins_to_flush = []
        with self._exit_fill_lock:
            for coin, start_time in list(self._exit_fill_buffer_time.items()):
                position_open = any(
                    r.position_count > 0 for r in self._reconcilers if r.coin == coin
                )
                if not position_open or now - start_time > 300:
                    coins_to_flush.append(coin)

        for coin in coins_to_flush:
            with self._exit_fill_lock:
                fills = self._exit_fill_buffer.pop(coin, [])
                self._exit_fill_buffer_time.pop(coin, None)
            if not fills:
                continue

            total_pnl = sum(f["pnl"] for f in fills)
            total_size = sum(f["size"] for f in fills)
            if total_size > 0:
                avg_exit = sum(f["exit_price"] * f["size"] for f in fills) / total_size
            else:
                avg_exit = fills[0]["exit_price"]

            signal = fills[0]["signal"]
            exit_reason = self._classify_exit(signal, avg_exit, total_pnl)

            self.evaluator.record_trade(
                signal_dict=signal, exit_price=avg_exit,
                size=total_size, pnl=total_pnl, exit_reason=exit_reason,
            )

            if total_pnl < 0 and "sr_level" in signal:
                for scalper in self._scalpers:
                    if scalper.coin == coin:
                        scalper.blacklist_level(signal["sr_level"])
                        break

            position_closed = not any(
                r.position_count > 0 for r in self._reconcilers if r.coin == coin
            )
            if position_closed:
                with self._pending_signals_lock:
                    self._active_signals.pop(coin, None)

            log.info("Aggregated %d partial fills for %s: pnl=%.6f sz=%.5f reason=%s closed=%s",
                     len(fills), coin, total_pnl, total_size, exit_reason, position_closed)

    def _cancel_stale_entries(self, coin, keep_price):
        # Entry admission now allows only one pending bracket per coin.
        return

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
            for scalper in self._scalpers:
                scalper.sr.apply_adjustments(adjustments)
                if "signal_cooldown" in adjustments:
                    scalper._signal_cooldown = float(adjustments["signal_cooldown"])

        perf = self.evaluator.get_performance()
        log.info("Performance — Win rate: %.1f%%, PF: %.2f, Sharpe: %.2f, Trades: %d",
                 perf.get("win_rate", 0) * 100, perf.get("profit_factor", 0),
                 perf.get("sharpe_ratio", 0), perf.get("total_trades", 0))
