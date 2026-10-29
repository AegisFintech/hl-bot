"""Turns strategy decisions into protected exchange positions.

Execution model (mirrored by src/validation/backtest.py):
- Entries are marketable IOC limit orders bounded by ``entry_slippage``; nothing
  rests on the book, so there are no stale entries to expire.
- Every position carries one reduce-only stop-market order sized to the actual
  filled position. If protection cannot be placed the position is closed.
- Stops move by placing the new stop first and cancelling the old one after, so
  the position is never unprotected. Exits close first and cancel stops after.
Ambiguous submissions are never blindly resent: they pause entries and the next
exchange snapshot decides what happened.
"""

import logging
import math

from src.exchange.hyperliquid import order_status

log = logging.getLogger(__name__)

MIN_NOTIONAL = 10.0


def live_positions(raw_positions):
    """{coin: dict(side, size, entry_px, value, unrealized)} from clearinghouse positions."""
    out = {}
    for item in raw_positions or []:
        pos = item.get("position", item)
        size = float(pos.get("szi", 0) or 0)
        if size:
            out[pos["coin"]] = dict(side=1 if size > 0 else -1, size=abs(size),
                                    entry_px=float(pos.get("entryPx") or 0),
                                    value=abs(float(pos.get("positionValue") or 0)),
                                    unrealized=float(pos.get("unrealizedPnl") or 0))
    return out


def stop_orders(orders, coin, side):
    """Reduce-only stop orders that would close a ``side`` position in ``coin``."""
    exit_side = "A" if side > 0 else "B"
    return [o for o in orders if o.get("coin") == coin and o.get("reduceOnly")
            and o.get("side") == exit_side and "Stop" in (o.get("orderType") or "")
            and float(o.get("triggerPx") or 0) > 0]


class OrderExecutor:
    def __init__(self, client, risk, entry_slippage=0.003, stop_slippage=0.03, quote_max_age=10.0):
        self.client = client
        self.risk = risk
        self.entry_slippage = entry_slippage
        self.stop_slippage = stop_slippage
        self.quote_max_age = quote_max_age
        self.changed = False  # Set whenever an order is placed or cancelled.

    # -- market data ---------------------------------------------------------

    def quote(self, coin):
        """Fresh (bid, ask): websocket BBO when recent, otherwise one REST book read."""
        bbo = self.client.get_cached_bbo(coin)
        if bbo and 0 <= self.client.bbo_age(coin) <= self.quote_max_age:
            try:
                bid, ask = float(bbo["bid"]["px"]), float(bbo["ask"]["px"])
                if 0 < bid <= ask:
                    return bid, ask
            except (KeyError, TypeError, ValueError):
                pass
        book = self.client.get_l2_snapshot(coin)
        levels = book.get("levels", [[], []])
        bid, ask = float(levels[0][0]["px"]), float(levels[1][0]["px"])
        if not 0 < bid <= ask:
            raise ValueError(f"Invalid {coin} book")
        return bid, ask

    def _size_tolerance(self, coin):
        return 0.5 * 10 ** -self.client.get_sz_decimals(coin)

    # -- entries -------------------------------------------------------------

    def enter(self, coin, side, stop, open_notional=0.0):
        """Open ``side`` exposure with a protective stop. Returns an outcome dict."""
        blocked = self.risk.admission()
        if blocked:
            return dict(status="blocked", reason=blocked)
        bid, ask = self.quote(coin)
        price = ask if side > 0 else bid
        if not math.isfinite(stop) or (price - stop) * side <= 0:
            return dict(status="skipped", reason="Price already beyond the protective stop")
        size = self.client.round_size(coin, self.risk.size_for(price, stop, open_notional))
        if size * price < MIN_NOTIONAL:
            return dict(status="skipped", reason=f"Risk-sized order below ${MIN_NOTIONAL:.0f} minimum")
        limit = price * (1 + side * self.entry_slippage)
        log.info("Entering %s %s %.6g @ <= %.6g (stop %.6g)", coin, "long" if side > 0 else "short",
                 size, limit, stop)
        try:
            result = self.client.place_ioc(coin, side > 0, size, limit)
        except Exception as exc:
            self.risk.pause_execution(f"{coin} entry outcome unknown ({type(exc).__name__}); verifying exposure")
            return dict(status="unknown", reason=type(exc).__name__)
        self.risk.record_order()
        state, detail = order_status(result)
        if state != "filled":
            return dict(status="unfilled", reason=f"IOC entry not filled: {detail}")
        # The fill report is authoritative: protect it at once (a reduce-only stop can never
        # add exposure), then let the next reconcile align the size with the live position.
        try:
            size = self.client.round_size(coin, float(detail["totalSz"]))
            fill_price = float(detail.get("avgPx") or price)
        except (KeyError, TypeError, ValueError):
            self.risk.pause_execution(f"{coin} fill report unreadable; verifying exposure")
            return dict(status="unknown", reason="Unreadable fill report")
        if self.protect(coin, side, size, stop, []):
            return dict(status="entered", size=size, price=fill_price, stop=stop, oid=detail.get("oid"))
        closed = {}
        try:
            closed = self.close(coin, "Protection could not be placed")
        except Exception:
            log.exception("Closing unprotected %s position failed", coin)
        self.risk.pause_execution(f"{coin} protective stop rejected; closing position")
        if closed.get("status") in ("closed", "flat"):
            return dict(status="closed", reason="Protective stop rejected; position closed")
        return dict(status="unknown", reason="Protective stop rejected and close incomplete; reconcile retries")

    def _live(self, coin):
        return live_positions(self.client.get_positions()).get(coin)

    # -- protection ----------------------------------------------------------

    def protect(self, coin, side, size, stop, existing):
        """Place a stop covering ``size`` at ``stop``, then cancel superseded stops."""
        self.changed = True
        try:
            result = self.client.place_stop(coin, side < 0, size, stop, self.stop_slippage)
        except Exception:
            log.exception("Protective stop submission failed for %s", coin)
            return False  # Callers pause or retry; the next reconcile sees the outcome.
        state, detail = order_status(result)
        if state == "filled":
            return True  # The trigger was already crossed and the position is closing.
        if state != "resting":
            log.error("Protective stop rejected for %s: %s", coin, detail)
            return False
        keep = detail.get("oid")
        for order in existing:
            if order.get("oid") != keep:
                try:
                    self._cancel(coin, order["oid"])
                except Exception:
                    log.warning("Could not cancel superseded stop %s for %s; next reconcile retries",
                                order.get("oid"), coin)
        return True

    def ensure_protection(self, coin, live, stop, orders):
        """True when ``live`` exposure is covered by exactly one stop at ``stop``."""
        existing = stop_orders(orders, coin, live["side"])
        tolerance = self._size_tolerance(coin)
        target = self.client.round_price(coin, stop)
        good = [o for o in existing if abs(float(o.get("sz", 0)) - live["size"]) <= tolerance
                and math.isclose(float(o["triggerPx"]), target, rel_tol=1e-6)]
        if good:
            keep = good[0]
            for order in existing:
                if order is not keep:
                    try:
                        self._cancel(coin, order["oid"])
                    except Exception:
                        log.warning("Could not cancel extra stop for %s; next reconcile retries", coin)
            return True
        log.warning("%s protection %s; placing stop %.6g for %.6g", coin,
                    "missing" if not existing else "out of date", target, live["size"])
        return self.protect(coin, live["side"], live["size"], stop, existing)

    # -- exits ---------------------------------------------------------------

    def close(self, coin, reason):
        """Reduce-only IOC close of the whole position; stops are cancelled once flat."""
        live = self._live(coin)
        if not live:
            self.cancel_coin_orders(coin)
            return dict(status="flat", reason=reason)
        bid, ask = self.quote(coin)
        price = (bid if live["side"] > 0 else ask) * (1 - live["side"] * self.entry_slippage * 2)
        log.info("Closing %s %s %.6g: %s", coin, "long" if live["side"] > 0 else "short", live["size"], reason)
        try:
            result = self.client.place_ioc(coin, live["side"] < 0, live["size"], price, reduce_only=True)
        except Exception as exc:
            log.exception("Close submission failed for %s", coin)
            return dict(status="unknown", reason=type(exc).__name__)
        state, detail = order_status(result)
        remaining = self._live(coin)
        if not remaining:
            self.cancel_coin_orders(coin)
            return dict(status="closed", reason=reason, price=float(detail.get("avgPx", price))
                        if isinstance(detail, dict) else price)
        return dict(status="partial" if state == "filled" else "unfilled",
                    reason=f"Close incomplete: {detail}")

    def _cancel(self, coin, oid):
        self.changed = True
        return self.client.cancel_order(coin, oid)

    def cancel_coin_orders(self, coin):
        self.changed = True
        try:
            self.client.cancel_all_orders(coin)
        except Exception:
            log.warning("Could not cancel remaining %s orders; next reconcile retries", coin)

    # -- account reconciliation ----------------------------------------------

    def reconcile(self, positions, orders, stops, fallback_pct=0.03):
        """Protect every position, cancel orphan/legacy orders. Returns problems found;
        ``self.changed`` tells whether any order was placed or cancelled.

        A position the strategy has not adopted yet keeps any existing stop, or gets
        a fallback stop ``fallback_pct`` from its entry so it is never unprotected.
        """
        problems = []
        self.changed = False
        for coin, live in positions.items():
            stop = stops.get(coin)
            if stop is None:
                if stop_orders(orders, coin, live["side"]):
                    continue
                stop = live["entry_px"] * (1 - live["side"] * fallback_pct)
                log.warning("%s position not yet adopted by the strategy; fallback stop %.6g", coin, stop)
            if not self.ensure_protection(coin, live, stop, orders):
                problems.append(f"{coin} protection could not be placed")
        for order in orders:
            coin = order.get("coin")
            if coin in positions and order.get("reduceOnly"):
                continue
            reason = "orphan reduce-only order" if order.get("reduceOnly") else "resting entry order"
            log.warning("Cancelling %s %s oid=%s", coin, reason, order.get("oid"))
            try:
                self._cancel(coin, order["oid"])
            except Exception:
                problems.append(f"{coin} {reason} could not be cancelled")
        return problems
