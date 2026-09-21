import time
import logging
import threading

from src.exchange.hyperliquid import HyperliquidClient
from src.risk.manager import RiskManager

log = logging.getLogger(__name__)


class PositionReconciler:

    def __init__(self, client: HyperliquidClient, risk_manager: RiskManager,
                 coin: str, tp_pips: int = 5, sl_pips: int = 10,
                 pip_size: float = 1.0):
        self.client = client
        self.risk = risk_manager
        self.coin = coin
        self.tp_pips = tp_pips
        self.sl_pips = sl_pips
        self.pip_size = pip_size
        self._last_reconcile = 0.0
        self._reconcile_interval = 15.0
        self._last_fill_time = 0
        self._lock = threading.Lock()
        self._processed_fill_ids: set[str] = set()
        self.position_count: int = 0

    def startup_sync(self) -> dict:
        with self._lock:
            return self._do_sync()

    def _do_sync(self) -> dict:
        positions = self.client.get_positions()
        coin_pos = [p for p in positions if p["position"]["coin"] == self.coin]
        orders = self.client.get_open_orders()
        coin_orders = [o for o in orders if o["coin"] == self.coin]
        reduce_only = [o for o in coin_orders if o.get("reduceOnly")]
        entry_orders = [o for o in coin_orders if not o.get("reduceOnly")]

        has_position = len(coin_pos) > 0
        self.position_count = 1 if has_position else 0

        fills = self.client.get_fills(50)
        coin_fills = [f for f in fills if f.get("coin") == self.coin]
        if coin_fills:
            self._last_fill_time = max(int(f.get("time", 0)) for f in coin_fills)
            for f in coin_fills:
                fid = f.get("tid") or f.get("oid") or str(f.get("time", ""))
                self._processed_fill_ids.add(fid)

        self._last_reconcile = time.time()

        if has_position and reduce_only:
            pos = coin_pos[0]["position"]
            szi = float(pos["szi"])
            pos_size = abs(szi)
            entry_px = float(pos["entryPx"])
            is_long = szi > 0

            count_ok = len(reduce_only) >= 2
            size_ok = all(abs(float(o["sz"]) - pos_size) < 1e-8 for o in reduce_only)

            prices_ok = True
            pip = self._get_pip_size()
            expected_tp = entry_px + (pip * self.tp_pips * (1 if is_long else -1))
            expected_sl = entry_px - (pip * self.sl_pips * (1 if is_long else -1))
            max_drift = pip * self.sl_pips * 2
            for o in reduce_only:
                px = float(o["limitPx"])
                if abs(px - expected_tp) > max_drift and abs(px - expected_sl) > max_drift:
                    prices_ok = False
                    log.warning("TP/SL price %.2f too far from entry %.2f", px, entry_px)

            if not count_ok or not size_ok or not prices_ok:
                reason = "missing_tpsl" if not count_ok else (
                    "size_mismatch" if not size_ok else "price_mismatch")
                log.warning("TP/SL %s — replacing all orders", reason)
                for o in coin_orders:
                    self.client.cancel_order(self.coin, o["oid"])
                self._place_recovery_tpsl(coin_pos[0])
                return {"status": f"recovered_{reason}", "position": pos["szi"],
                        "entry": pos["entryPx"]}

            log.info("Position OK: %s %.5f @ %s with %d TP/SL orders",
                     self.coin, szi, pos["entryPx"], len(reduce_only))
            if entry_orders:
                log.info("Cancelling %d stale entry orders", len(entry_orders))
                for o in entry_orders:
                    self.client.cancel_order(self.coin, o["oid"])
            return {"status": "healthy", "position": pos["szi"],
                    "entry": pos["entryPx"], "orders": len(reduce_only)}

        elif has_position and not reduce_only:
            pos = coin_pos[0]["position"]
            log.warning("Position has NO TP/SL — placing recovery orders")
            if entry_orders:
                log.info("Cancelling %d orphaned entry orders", len(entry_orders))
                for o in entry_orders:
                    self.client.cancel_order(self.coin, o["oid"])
            self._place_recovery_tpsl(coin_pos[0])
            return {"status": "recovered", "position": pos["szi"],
                    "entry": pos["entryPx"]}

        elif not has_position and coin_orders:
            log.warning("No position but %d orphaned orders — cancelling all", len(coin_orders))
            self.client.cancel_all_orders(self.coin)
            unrecorded = self._get_unrecorded_closing_fills(coin_fills)
            if unrecorded:
                log.warning("Found %d unrecorded closing fills from previous session", len(unrecorded))
            return {"status": "cleaned_orphans", "cancelled": len(coin_orders),
                    "unrecorded_fills": unrecorded}

        else:
            log.info("Clean slate — no positions, no orders for %s", self.coin)
            unrecorded = self._get_unrecorded_closing_fills(coin_fills)
            if unrecorded:
                log.warning("Found %d unrecorded closing fills from previous session", len(unrecorded))
                return {"status": "clean_with_missed_fills", "unrecorded_fills": unrecorded}
            return {"status": "clean"}

    def periodic_check(self, force: bool = False) -> bool:
        now = time.time()
        if not force and now - self._last_reconcile < self._reconcile_interval:
            return False

        if not self._lock.acquire(blocking=False):
            return False
        try:
            self._last_reconcile = time.time()
            return self._do_periodic()
        finally:
            self._lock.release()

    def _do_periodic(self) -> bool:
        try:
            positions = self.client.get_positions()
        except Exception as e:
            log.warning("Reconciliation query failed: %s", e)
            return True

        coin_pos = [p for p in positions if p["position"]["coin"] == self.coin]
        actual = len(coin_pos)
        expected = self.risk.state.open_positions

        self.position_count = actual

        if actual > 0:
            orders = self.client.get_open_orders()
            reduce_only = [o for o in orders
                           if o["coin"] == self.coin and o.get("reduceOnly")]
            needs_recovery = False
            if len(reduce_only) < 2:
                log.warning("Periodic: position has %d TP/SL (need 2) — recovering",
                            len(reduce_only))
                needs_recovery = True
            else:
                pos_size = abs(float(coin_pos[0]["position"]["szi"]))
                if not all(abs(float(o["sz"]) - pos_size) < 1e-8
                           for o in reduce_only):
                    log.warning("Periodic: TP/SL size mismatch — replacing")
                    needs_recovery = True

            if needs_recovery:
                for o in [o for o in orders if o["coin"] == self.coin]:
                    self.client.cancel_order(self.coin, o["oid"])
                self._place_recovery_tpsl(coin_pos[0])

        elif actual == 0 and expected > 0:
            orders = self.client.get_open_orders()
            coin_orders = [o for o in orders if o["coin"] == self.coin]
            if coin_orders:
                log.info("Periodic: position closed, cancelling %d leftover orders",
                         len(coin_orders))
                self.client.cancel_all_orders(self.coin)

        return True

    def _get_unrecorded_closing_fills(self, coin_fills: list) -> list:
        """Return fills that closed a position but weren't processed this session."""
        unrecorded = []
        for f in coin_fills:
            pnl = float(f.get("closedPnl", 0) or 0)
            if pnl == 0:
                continue
            fid = f.get("tid") or f.get("oid") or str(f.get("time", ""))
            if fid not in self._processed_fill_ids:
                unrecorded.append(f)
        return unrecorded

    def backfill_missed_fills(self) -> list:
        try:
            fills = self.client.get_fills(50)
        except Exception as e:
            log.warning("Backfill query failed: %s", e)
            return []

        coin_fills = [f for f in fills if f.get("coin") == self.coin]
        missed = []

        with self._lock:
            for f in coin_fills:
                fid = f.get("tid") or f.get("oid") or str(f.get("time", ""))
                if int(f.get("time", 0)) > self._last_fill_time and fid not in self._processed_fill_ids:
                    missed.append(f)
                    self._processed_fill_ids.add(fid)

            if coin_fills:
                self._last_fill_time = max(int(f.get("time", 0)) for f in coin_fills)

            if len(self._processed_fill_ids) > 500:
                recent_fids = {f.get("tid") or f.get("oid") or str(f.get("time", "")) for f in fills[-200:]}
                self._processed_fill_ids = recent_fids

        if missed:
            log.info("Backfilled %d missed fills from WS gap", len(missed))
        return missed

    def _get_pip_size(self) -> float:
        try:
            mid = self.client.get_mid_price(self.coin)
            if mid > 10000:
                return 1.0
            elif mid > 1000:
                return 0.1
            elif mid > 100:
                return 0.01
            else:
                return 0.001
        except Exception:
            return self.pip_size

    def _place_recovery_tpsl(self, position_data: dict):
        pos = position_data["position"]
        entry = float(pos["entryPx"])
        szi = float(pos["szi"])
        size = abs(szi)
        is_long = szi > 0

        pip = self._get_pip_size()
        if is_long:
            tp = self.client.round_price(self.coin, entry + pip * self.tp_pips)
            sl = self.client.round_price(self.coin, entry - pip * self.sl_pips)
        else:
            tp = self.client.round_price(self.coin, entry - pip * self.tp_pips)
            sl = self.client.round_price(self.coin, entry + pip * self.sl_pips)

        exit_is_buy = not is_long
        log.info("Placing recovery TP/SL: %s %.5f entry=%.2f tp=%.2f sl=%.2f",
                 "LONG" if is_long else "SHORT", size, entry, tp, sl)

        try:
            result = self.client.place_trigger_orders(
                self.coin, exit_is_buy, size, tp, sl)
            statuses = result.get("response", {}).get("data", {}).get("statuses", [])
            log.info("Recovery TP/SL result: %s", statuses)
        except Exception as e:
            log.error("Failed to place recovery TP/SL: %s", e, exc_info=True)
