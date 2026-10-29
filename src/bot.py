"""Trading engine lifecycle: resilient startup, risk enforcement, strategy cycle, fills.

One main thread owns every order decision. Websocket callbacks only record
fills/order events and mark the exchange snapshot dirty; the dashboard reads the
cached snapshot instead of calling the exchange itself.
"""

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from src.dashboard.app import run_dashboard, set_bot_reference
from src.exchange.hyperliquid import HyperliquidClient
from src.executor import OrderExecutor, live_positions, stop_orders
from src.learning.accounting import AccountAudit
from src.learning.evaluator import Evaluator
from src.learning.execution import ExecutionJournal
from src.learning.funding import FundingSync
from src.learning.ledger import FillLedger
from src.learning.quality import QualityAudit, candle_context
from src.operations import Operations
from src.research.service import ResearchService
from src.risk.manager import RiskManager
from src.settings import Settings
from src.strategy.engine import StrategyEngine
from src.strategy.library import Bars, build

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class StartupBlocked(Exception):
    """A condition only the operator can fix (wrong network URL, unapproved API wallet)."""


class Throttle:
    """Log a repeating condition at most once per ``every`` seconds."""

    def __init__(self, every=60.0):
        self.every, self.last = every, {}

    def ready(self, key):
        now = time.time()
        if now - self.last.get(key, 0) >= self.every:
            self.last[key] = now
            return True
        return False


def utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ts else "—"


class TradingBot:

    def __init__(self, client: HyperliquidClient, settings: Settings | None = None,
                 trades_file=None, performance_file=None, data_dir=DATA_DIR):
        self.client = client
        self.settings = (settings or Settings()).validate()
        s = self.settings
        self.coins = list(s.coins)
        self.coin = self.coins[0]
        self.running = False
        self.start_time = None
        self.startup_status = "Starting"
        data_dir = Path(data_dir)

        self.risk_manager = RiskManager(
            max_daily_loss_pct=s.daily_loss_limit, max_drawdown_pct=s.drawdown_limit,
            max_open_positions=s.max_positions, max_daily_trades=s.max_daily_entries,
            state_file=data_dir / "risk_state.json", risk_per_trade=s.risk_per_trade,
            cooldown_s=s.cooldown_hours * 3600, max_leverage=s.max_leverage,
            max_gross_leverage=s.max_gross_leverage, auto_reset=s.auto_reset)
        self.strategy = build(s.strategy, **s.strategy_params)
        self.engine = StrategyEngine(self.strategy, self.coins, s.interval, data_dir / "strategy_state.json")
        self.executor = OrderExecutor(client, self.risk_manager, s.entry_slippage, s.stop_slippage)
        self.evaluator = Evaluator(trades_file=Path(trades_file or data_dir / "trades.json"),
                                   performance_file=Path(performance_file or data_dir / "performance.json"))

        self.ledger = FillLedger(data_dir / "ledger.sqlite")
        self.research = ResearchService(data_dir / "research.sqlite")
        self.quality = QualityAudit(data_dir / "quality.sqlite")
        self.execution = ExecutionJournal(data_dir / "execution.sqlite")
        self.client.execution_journal = self.execution
        self.account_audit = AccountAudit(self.execution.path, self.ledger, self.quality.path, self.client.address)
        self.operations = Operations(data_dir / "operations.sqlite")
        self.funding_sync = None
        self._audit_stop = threading.Event()
        self._data_repair_requested = threading.Event()
        self._threads = {}

        self.fee_entry, self.fee_exit = 0.00015, 0.00045
        self.account_snapshot = {}
        self.exchange_snapshot = dict(positions=[], orders=[], time=0.0, ok=False)
        self._positions, self._orders = {}, []
        self._snapshot_dirty = True
        self._last_equity_fetch = 0.0
        self._last_reconcile = 0.0
        self._reconcile_problems = []
        self._protection_failures = {}
        self._halt_cleanup_at = 0.0
        self.halt_cleanup_status = "Not required"
        self._recovery_checks = 0
        self._recovery_check_at = 0.0
        self._leverage_set = set()
        self._last_leverage_attempt = 0.0
        self._processed_fill_ids = set()
        self._processed_order = deque()
        self._fill_lock = threading.Lock()
        self._pending_signals = {}  # Entries are immediate-or-cancel; nothing rests.
        self._log = Throttle()

    # -- lifecycle -----------------------------------------------------------

    def start(self):
        log.info("Starting HL-Bot %s on %s bars for %s (%s)", self.strategy.label, self.settings.interval,
                 self.coins, "testnet" if self.client.testnet else "MAINNET")
        if not self.client.testnet:
            raise RuntimeError("Only testnet trading is authorized")
        set_bot_reference(self)
        self._spawn("dashboard", run_dashboard, port=self.settings.dashboard_port)
        self.running = True
        self.start_time = time.time()
        self._startup()
        self._spawn("candle-repair", self._data_loop)
        self._spawn("testnet-quality", self._audit_loop)
        self._start_observers()
        log.info("Bot is live. Dashboard at http://localhost:%d", self.settings.dashboard_port)
        try:
            self._run_loop()
        except KeyboardInterrupt:
            log.info("Shutting down...")
        finally:
            self._audit_stop.set()
            self.account_audit.stop_event.set()
            if self.funding_sync:
                self.funding_sync.stop_event.set()
            self.research.stop()
            self.running = False

    def _spawn(self, name, target, **kwargs):
        thread = threading.Thread(target=target, kwargs=kwargs, name=name, daemon=True)
        thread.start()
        self._threads[name] = thread
        return thread

    def _start_observers(self):
        for name, start in (("research", self.research.start), ("account-audit", self.account_audit.start)):
            try:
                start()
            except Exception:
                log.exception("%s observer failed to start; trading continues without it", name)
        try:
            first = self.ledger.performance().get("first_time") or int(time.time() * 1000)
            self.funding_sync = FundingSync(self.quality.path, self.client.address, first)
            self.funding_sync.start()
        except Exception:
            log.exception("Funding observer failed to start; trading continues without it")

    def _startup(self):
        """Retry exchange initialisation until it succeeds; never exit on a transient error."""
        delay = 5
        while self.running:
            try:
                self._init_exchange()
                self._subscribe_feeds()
                self.startup_status = "Ready"
                return
            except StartupBlocked as exc:
                self.startup_status = f"Blocked: {exc}"
                log.critical("Startup blocked: %s. Retrying in 60s.", exc)
                time.sleep(60)
            except Exception as exc:
                self.startup_status = f"Exchange initialisation failed ({type(exc).__name__}); retrying in {delay}s"
                log.error("Exchange initialisation failed: %s; retrying in %ds", exc, delay, exc_info=True)
                time.sleep(delay)
                delay = min(delay * 2, 300)

    def _init_exchange(self):
        urls = self.client.audit_urls()
        log.info("Info REST %s [%s]; exchange REST %s [%s]", urls["info_rest"], "OK" if urls["info_ok"] else "MISMATCH",
                 urls["exchange_rest"], "OK" if urls["exchange_ok"] else "MISMATCH")
        if not urls["info_ok"] or not urls["exchange_ok"]:
            raise StartupBlocked("Exchange URL mismatch; check HL_TESTNET in .env")
        log.info("Master account %s; API signer %s", self.client.master_account, self.client.wallet.address)
        preflight = self.client.preflight_check_agent()
        if not preflight["agent_registered"]:
            raise StartupBlocked(
                f"API wallet {preflight['agent_address']} is not approved (or has expired) for "
                f"{self.client.master_account}; approve it at app.hyperliquid-testnet.xyz → API")
        expiry = preflight.get("valid_until")
        if expiry and expiry / 1000 - time.time() < 7 * 86400:
            log.warning("API wallet approval expires %s; renew it to avoid a trading stop", utc(expiry / 1000))

        try:
            fees = self.client.info.user_fees(self.client.address)
            self.fee_entry, self.fee_exit = float(fees["userAddRate"]), float(fees["userCrossRate"])
        except Exception:
            log.warning("Fee rates unavailable; using %.4f%% maker / %.4f%% taker", self.fee_entry * 100,
                        self.fee_exit * 100)

        tradable = [c for c in self.coins if self.client.tradable(c)]
        if not tradable:
            raise StartupBlocked(f"None of {self.coins} is listed on this network")
        if tradable != self.coins:
            log.warning("Not listed on this network and skipped: %s", sorted(set(self.coins) - set(tradable)))
            self.coins = tradable
            self.engine.coins = tradable
            self.coin = tradable[0]

        self._refresh_equity(time.time())
        if not self.account_snapshot:
            raise RuntimeError("Account equity unavailable")
        try:
            known = {self.ledger.identity(f) for f in self.ledger.fills(2000)}
            for fill in self.client.get_fills(2000):
                if self.ledger.identity(fill) not in known:
                    self.ledger.add(fill)
            self._remember_fills(self.ledger.identity(f) for f in self.ledger.fills(2000))
        except Exception:
            log.exception("Fill history import failed; the account audit will retry")
        self._set_leverage()
        self._refresh_exchange(time.time())
        if not self.exchange_snapshot["ok"]:
            raise RuntimeError("Positions/orders unavailable")
        self._adopt_positions()
        log.info("Startup: equity %.2f, %d positions, %d open orders, risk admission: %s",
                 self.account_snapshot.get("equity", 0), len(self._positions), len(self._orders),
                 self.risk_manager.admission() or "open")

    def _existing_stop(self, coin, live):
        """Tightest resting stop protecting ``live`` exposure, if any."""
        if not live:
            return None
        triggers = [float(o["triggerPx"]) for o in stop_orders(self._orders, coin, live["side"])]
        if not triggers:
            return None
        return max(triggers) if live["side"] > 0 else min(triggers)

    def _adopt_positions(self):
        """Give positions opened before this start (or by hand) a strategy stop."""
        for coin, live in self._positions.items():
            if coin not in self.coins or self.engine.position(coin):
                continue
            try:
                bars = Bars.from_candles(self.client.get_closed_bars(coin, self.settings.interval,
                                                                     self.engine.history_bars))
                self.engine.sync(coin, live, self.strategy.indicators(bars), bars, self._existing_stop(coin, live))
                self.engine.save()
            except Exception:
                log.exception("Could not adopt %s position yet; fallback protection applies", coin)

    def _set_leverage(self):
        self._last_leverage_attempt = time.time()
        for coin in self.coins:
            if coin in self._leverage_set:
                continue
            try:
                leverage = max(1, min(self.settings.exchange_leverage, self.client.max_leverage(coin)))
                self.client.set_leverage(coin, leverage, cross=True)
                self._leverage_set.add(coin)
                log.info("Leverage set to %dx cross for %s", leverage, coin)
            except Exception as exc:
                log.warning("Could not set leverage for %s (%s); exchange default applies", coin, exc)

    def _subscribe_feeds(self):
        for coin in self.coins:
            self.client.subscribe_bbo(coin)
        primary = self.coin
        self.client.subscribe_l2(primary)
        try:
            history = self.client.get_candles(primary, "1m", 500 * 60000)
            self.client.merge_candles(primary, history, source="rest", requested_at=time.time())
        except Exception:
            log.warning("Initial chart candles unavailable; background repair will retry")
        self.client.subscribe_candles(primary, "1m")
        self.client.subscribe_trades(primary)
        self.client.subscribe_fills(callback=self._on_fill)
        self.client.subscribe_order_updates(callback=self._on_order_update)
        self.client.set_reconnect_callback(self._on_ws_reconnect)
        log.info("Subscribed to websocket feeds for %s", self.coins)

    # -- background loops ------------------------------------------------------

    def _audit_quote(self, coin):
        """Quote evidence for audits, or None when no valid quote has arrived yet."""
        bbo, received_at = self.client.get_audit_bbo(coin)
        if not bbo:
            return None
        now = time.time()
        try:
            return self.quality.quote(bbo, now - received_at, now)
        except (KeyError, TypeError, ValueError):
            return None

    def _audit_loop(self):
        while not self._audit_stop.is_set():
            try:
                quote = self._audit_quote(self.coin)
                if quote is None:
                    raise ValueError("No valid quote yet")
                self.quality.tick(quote, self.client.get_cached_candles(self.coin), self.coin)
            except (ValueError, TypeError, KeyError):
                pass  # Missing data is never replaced with invented observations.
            except Exception:
                if self._log.ready("quality-audit"):
                    log.exception("Observation-only quality audit failed")
            self._audit_stop.wait(1)

    def _data_loop(self):
        """Keep the primary market's 1m chart history complete (display only)."""
        coin, failures, next_attempt = self.coin, 0, 0.0
        while not self._audit_stop.is_set():
            forced = self._data_repair_requested.is_set()
            self._data_repair_requested.clear()
            now = time.time()
            health = self.client.candle_health(coin)
            if now >= next_attempt and (forced or not health["eligible"] or now - health.get("last_repair_at", 0) >= 300):
                try:
                    bars = self.client.get_candles(coin, "1m", 130 * 60000)
                    if not bars:
                        raise ValueError("Empty candle repair response")
                    self.client.merge_candles(coin, bars, source="rest", requested_at=now)
                    failures, next_attempt = 0, now + 30
                except Exception as exc:
                    failures += 1
                    next_attempt = time.time() + min(300, 30 * 2 ** min(failures - 1, 4))
                    with self.client._lock:
                        self.client._candle_health.setdefault(f"{coin}_1m", {}).update(
                            repair_error=type(exc).__name__, next_repair_at=next_attempt)
                    if self._log.ready("candle-repair"):
                        log.warning("Chart candle repair deferred [%s]: %s", coin, type(exc).__name__)
            self._audit_stop.wait(5)

    # -- main loop ---------------------------------------------------------------

    def _run_loop(self):
        log.info("Entering main loop.")
        while self.running:
            failure = ""
            try:
                self._tick()
            except Exception as exc:
                failure = type(exc).__name__
                if self._log.ready("tick:" + failure):
                    log.error("Tick error: %s", exc, exc_info=True)
            finally:
                state = self.risk_manager.state
                phase = ("halted" if state.halted else "recovering" if state.execution_paused
                         else "error" if failure else "running")
                reason = state.halt_reason if state.halted else state.pause_reason if state.execution_paused else failure
                try:
                    self.operations.record(phase, reason)
                except Exception:
                    if self._log.ready("heartbeat"):
                        log.exception("Operational heartbeat could not be persisted")
            time.sleep(1)

    def _tick(self):
        now = time.time()
        risk = self.risk_manager
        risk.check_daily_reset()
        if now - self._last_equity_fetch >= 5:
            self._refresh_equity(now)
        if risk.state.halted:
            self._breaker_cycle(now)
            return
        if self._snapshot_dirty or now - self.exchange_snapshot["time"] >= 15:
            self._refresh_exchange(now)
        if self.exchange_snapshot["ok"] and now - self._last_reconcile >= 15:
            self._reconcile(now)
        if risk.state.execution_paused:
            self._recovery_cycle(now)
        self._strategy_cycle(now)
        if len(self._leverage_set) < len(self.coins) and now - self._last_leverage_attempt > 300:
            self._set_leverage()

    def _refresh_equity(self, now):
        self._last_equity_fetch = now  # Failures retry on the normal cadence, not every second.
        try:
            snapshot = self.client.get_account_snapshot()
            self.risk_manager.update_equity(snapshot["equity"])
        except Exception as exc:
            if self._log.ready("equity"):
                log.warning("Equity refresh failed: %s", exc)
            return
        self.account_snapshot = snapshot
        for name, sink in (("ledger", lambda: self.ledger.sample_equity(snapshot["equity"],
                                                                         self.risk_manager.state.peak_equity)),
                           ("bridge", lambda: self.account_audit.sample(snapshot))):
            try:
                sink()
            except Exception as exc:
                if self._log.ready("sample:" + name):
                    log.warning("Equity %s sample skipped: %s", name, exc)

    def _refresh_exchange(self, now):
        # Clear first so a callback arriving mid-read marks the next tick dirty again. Orders
        # are read before positions: a stop that fires in between then looks like an orphan
        # (harmless to cancel) rather than a live position missing its stop.
        self._snapshot_dirty = False
        try:
            orders = self.client.get_open_orders()
            raw_positions = self.client.get_positions()
        except Exception as exc:
            self._snapshot_dirty = True
            self.exchange_snapshot["ok"] = False
            if self._log.ready("snapshot"):
                log.warning("Exchange snapshot failed: %s", exc)
            return False
        self.exchange_snapshot = dict(positions=raw_positions, orders=orders, time=now, ok=True)
        self._positions, self._orders = live_positions(raw_positions), orders
        self.risk_manager.sync_open_positions(len(self._positions))
        self.risk_manager.state.open_order_count = sum(1 for o in orders if not o.get("reduceOnly"))
        for coin in self.coins:
            if coin not in self._positions and self.engine.position(coin):
                self.engine.sync(coin, None)
                self.engine.save()
        return True

    def _reconcile(self, now):
        self._last_reconcile = now
        problems = self.executor.reconcile(self._positions, self._orders, self.engine.stops())
        self._reconcile_problems = problems
        failing = {p.split()[0] for p in problems if "protection" in p}
        for coin in list(self._protection_failures):
            if coin not in failing:
                self._protection_failures.pop(coin)
        for coin in failing:
            self._protection_failures[coin] = self._protection_failures.get(coin, 0) + 1
            if self._protection_failures[coin] >= 2:
                log.critical("%s position could not be protected twice; closing it", coin)
                self.executor.close(coin, "Unprotectable position")
                self.engine.closed(coin)
                self.risk_manager.pause_execution(f"{coin} protection failed; position closed")
                self.executor.changed = True
        if self.executor.changed:
            self._snapshot_dirty = True

    def _recovery_cycle(self, now):
        """Operational pause: protected positions stay; resume after three healthy checks."""
        incident = self.risk_manager.state.last_pause_at
        if incident != getattr(self, "_recovery_incident", None):
            self._recovery_incident = incident  # A new pause restarts the healthy-check sequence.
            self._recovery_checks, self._recovery_check_at = 0, 0.0
        primary_fresh = 0 <= self.client.bbo_age(self.coin) <= 10
        healthy = (self.exchange_snapshot["ok"] and now - self.exchange_snapshot["time"] <= 20
                   and now - self.risk_manager.state.equity_updated_at <= 10 and primary_fresh
                   and not self._reconcile_problems and self.account_snapshot.get("equity", 0) > 0)
        if not healthy:
            self._recovery_checks, self._recovery_check_at = 0, 0.0
            self.halt_cleanup_status = "Waiting for healthy exchange, account and quote reads"
            return
        if now - self._recovery_check_at >= 15:
            self._recovery_checks += 1
            self._recovery_check_at = now
        self.halt_cleanup_status = f"Healthy checks {self._recovery_checks}/3; resume after {utc(self.risk_manager.state.pause_until)}"
        if self._recovery_checks >= 3 and self.risk_manager.resume_execution():
            self._recovery_checks = 0
            self.halt_cleanup_status = "Operational recovery verified; execution resumed"

    def _breaker_cycle(self, now):
        """Drawdown breaker: flatten, confirm, then re-base and resume after the cooldown."""
        if now - self._halt_cleanup_at < 10:
            return
        self._halt_cleanup_at = now
        flat = self._flatten_all()
        state = self.risk_manager.state
        if flat and self.risk_manager.try_reset_after_cooldown(True):
            self.halt_cleanup_status = "Breaker cooldown complete; peak re-based and trading resumed"
            self._snapshot_dirty = True
        elif flat:
            resume = f"auto-resume after {utc(state.cooldown_until)}" if state.cooldown_until else "manual review"
            self.halt_cleanup_status = f"Confirmed flat; no orders; {resume}"
        else:
            self.halt_cleanup_status = "Exposure or orders remain; retrying flatten"

    def _flatten_all(self):
        try:
            positions = live_positions(self.client.get_positions())
            orders = self.client.get_open_orders()
        except Exception:
            log.exception("Unable to enumerate exposure for the breaker flatten")
            return False
        # Stops stay in place until a coin is confirmed flat: a failed close must never
        # leave exposure unprotected. Entries and orders on flat coins go first.
        for order in orders:
            if order.get("coin") not in positions or not order.get("reduceOnly"):
                try:
                    self.client.cancel_order(order["coin"], order["oid"])
                except Exception:
                    log.exception("Breaker cancel failed for %s; still closing exposure", order.get("coin"))
        for coin in positions:
            outcome = {}
            try:
                outcome = self.executor.close(coin, "Drawdown breaker")
            except Exception:
                log.exception("Breaker close failed for %s; trying market close", coin)
            if outcome.get("status") not in ("closed", "flat"):
                try:
                    self.client.close_position(coin)  # Wider-slippage market close fallback.
                except Exception:
                    log.exception("Breaker market close failed for %s; retrying", coin)
        try:
            raw = self.client.get_positions()
            orders = self.client.get_open_orders()
        except Exception:
            log.exception("Breaker flatten confirmation failed")
            return False
        positions = live_positions(raw)
        self.exchange_snapshot = dict(positions=raw, orders=orders, time=time.time(), ok=True)
        self._positions, self._orders = positions, orders
        self.risk_manager.sync_open_positions(len(positions))
        if not positions:
            for coin in self.coins:
                if self.engine.position(coin):
                    self.engine.closed(coin)
        return not positions and not orders

    # -- strategy ------------------------------------------------------------------

    def _strategy_cycle(self, now):
        due = [coin for coin in self.coins if self.engine.due(coin, now)]
        if not due:
            return
        if not self._refresh_exchange(now):
            for coin in due:
                self.engine.defer(coin, "Exchange snapshot unavailable", now)
            return
        for coin in due:
            try:
                candles = self.client.get_closed_bars(coin, self.settings.interval, self.engine.history_bars)
            except Exception as exc:
                self.engine.defer(coin, f"Bar history unavailable ({type(exc).__name__})", now)
                continue
            try:
                live = self._positions.get(coin)
                decision = self.engine.evaluate(coin, candles, live, now, self._existing_stop(coin, live))
                if decision is None:
                    continue
                outcome = self._act(coin, decision, live, candles)
            except Exception as exc:  # One coin's failure must not stall the others.
                log.exception("Strategy cycle failed for %s", coin)
                self.engine.defer(coin, f"Strategy evaluation failed ({type(exc).__name__})", now)
                continue
            if outcome.get("status") in ("entered", "closed", "partial", "unknown", "error"):
                # Later coins in this cycle must see the new exposure for position/leverage caps.
                self._refresh_exchange(time.time())

    def _act(self, coin, decision, live, candles):
        audit = self._audit_decision(coin, decision, candles)
        outcome = dict(status="none", reason=decision.reason)
        try:
            can_enter = True
            if decision.action in ("exit", "reverse") and live:
                outcome = self.executor.close(coin, decision.reason)
                if outcome["status"] in ("closed", "flat"):
                    self.engine.closed(coin)
                    live = None
                    # The closed position must leave the counts before the opposite entry.
                    if decision.action == "reverse" and not self._refresh_exchange(time.time()):
                        can_enter = False
                        outcome = dict(status="closed", reason="Reversal entry skipped: exposure unverified")
            if decision.action in ("enter", "reverse") and not live and can_enter:
                open_notional = sum(p["value"] for p in self._positions.values() if p is not None)
                outcome = self.executor.enter(coin, decision.side, decision.stop, open_notional)
                if outcome["status"] == "entered":
                    self.engine.opened(coin, decision.side, outcome["price"], decision.stop)
            elif decision.action == "hold" and live and decision.stop is not None:
                ok = self.executor.ensure_protection(coin, live, decision.stop, self._orders)
                outcome = dict(status="protected" if ok else "unprotected", reason=decision.reason)
        except Exception as exc:
            log.exception("Acting on %s %s failed", coin, decision.action)
            outcome = dict(status="error", reason=type(exc).__name__)
        if outcome.get("status") not in ("none", "protected"):
            self.engine.state[coin]["reason"] = f"{decision.reason} → {outcome['status']}: {outcome.get('reason', '')}".strip(": ")
            self.engine.save()
            log.info("%s %s: %s", coin, decision.action, self.engine.state[coin]["reason"])
        self._snapshot_dirty = True
        if audit:
            try:
                self.quality.result(audit, outcome, outcome.get("reason", ""))
            except Exception:
                log.exception("Could not persist decision result")
        return outcome

    def _audit_decision(self, coin, decision, candles):
        if decision.action not in ("enter", "exit", "reverse"):
            return None
        try:
            quote = self._audit_quote(coin)
            try:
                context = candle_context(self.client.get_cached_candles(coin), time.time()) if coin == self.coin \
                    else {"regime": "unknown"}
            except (ValueError, KeyError, TypeError):
                context = {"regime": "unknown"}
            signal = dict(coin=coin, side="long" if decision.side > 0 else "short", action=decision.action,
                          entry_price=float(candles[-1]["c"]), sl_price=decision.stop, tp_price=None,
                          strategy=self.strategy.label, interval=self.settings.interval, reason=decision.reason)
            return self.quality.decision(signal, context, quote, dict(reason=decision.reason))
        except Exception:
            log.exception("Could not persist decision audit")
            return None

    # -- exchange callbacks (websocket thread) --------------------------------------

    def _remember_fills(self, identities):
        with self._fill_lock:
            for ident in identities:
                if ident not in self._processed_fill_ids:
                    self._processed_fill_ids.add(ident)
                    self._processed_order.append(ident)
            while len(self._processed_order) > 5000:
                self._processed_fill_ids.discard(self._processed_order.popleft())

    def _on_fill(self, fills: list):
        for fill in fills:
            try:
                ident = self.ledger.identity(fill)
            except Exception:
                continue
            with self._fill_lock:
                if ident in self._processed_fill_ids:
                    continue
            self._remember_fills([ident])
            try:
                self.ledger.add(fill)  # Idempotent; the account audit may have imported it already.
            except Exception:
                log.exception("Fill could not be written to the ledger")
            try:
                self.risk_manager.record_fill(float(fill.get("closedPnl", 0) or 0) - float(fill.get("fee", 0) or 0))
            except Exception:
                log.exception("Fill P&L could not be recorded")
            try:
                self.quality.fill(fill, self._audit_quote(fill.get("coin")))
            except Exception:
                if self._log.ready("quality-fill"):
                    log.exception("Could not persist prospective fill audit")
            log.info("Fill: %s %s %s @ %s (%s)", fill.get("side"), fill.get("coin"), fill.get("sz"),
                     fill.get("px"), fill.get("dir", ""))
        self._snapshot_dirty = True

    def _on_order_update(self, updates: list):
        for update in updates if isinstance(updates, list) else [updates]:
            try:
                self.execution.event(update)
            except Exception:
                if self._log.ready("order-event"):
                    log.exception("Order lifecycle event could not be persisted")
            status = update.get("status") if isinstance(update, dict) else None
            if status and status != "open":
                self._snapshot_dirty = True

    def _on_ws_reconnect(self):
        self._data_repair_requested.set()
        self._snapshot_dirty = True
        log.info("Websocket reconnected: backfilling fills and scheduling chart repair")
        try:
            self._on_fill(self.client.get_fills(100))
        except Exception as exc:
            log.error("Post-reconnect fill backfill failed: %s", exc)

    # -- dashboard views -------------------------------------------------------------

    def strategy_status(self):
        summary = self.engine.summary()
        primary = summary["coins"].get(self.coin, {})
        risk = self.risk_manager
        admission = risk.admission()
        position = primary.get("position") or {}
        atr = primary.get("atr")
        return dict(
            reason=admission or primary.get("reason") or "Waiting for first bar close",
            mode=f"{self.strategy.name} · {self.settings.interval} bars · {len(self.coins)} markets",
            trend=(primary.get("decision") or {}).get("action", "—"),
            maker_fee_bps=self.fee_entry * 10000, taker_fee_bps=self.fee_exit * 10000,
            stop_distance=abs(primary["close"] - position["stop"]) if position and primary.get("close") else None,
            target_distance=atr, target_status="Unverified; simulated research only",
            startup=self.startup_status, settings=self.settings.to_dict(), engine=summary,
            reconcile_problems=self._reconcile_problems, pending_signals=0,
            candidates=sum(1 for c in summary["coins"].values()
                           if (c.get("decision") or {}).get("action") in ("enter", "reverse")))

    def chart_levels(self):
        position = self.engine.position(self.coin)
        return [dict(price=position.stop, kind="stop", score=1.0)] if position else []
