"""Live closed-bar strategy runner: validated bars in, decisions out; never orders.

Per-coin position metadata (stop, best price since entry, bars held) persists in
``data/strategy_state.json`` so restarts continue the exact trailing-stop path the
backtester models. Exchange positions are authoritative: metadata for a flat
coin is dropped, and an unknown position is adopted with a fresh volatility stop.
"""

import json
import logging
import math
import time
from pathlib import Path

from src.strategy.library import Bars, Decision, Position, advance, tighten

log = logging.getLogger(__name__)

INTERVAL_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def latest_closed_open(now_ms, step):
    """Open time of the most recent bar that has fully closed at ``now_ms``."""
    return now_ms // step * step - step


def validate(bars, step, expected_last, need):
    """Reason the bar series is unusable, or '' when complete and fresh."""
    if len(bars) < need:
        return f"Only {len(bars)} closed bars; {need} required"
    if bars.t[-1] != expected_last:
        return "Latest closed bar not yet published"
    tail = range(len(bars) - need, len(bars))
    for i in tail:
        values = (bars.o[i], bars.h[i], bars.l[i], bars.c[i])
        if not all(math.isfinite(v) and v > 0 for v in values) or not bars.l[i] <= min(bars.o[i], bars.c[i]) \
                or not max(bars.o[i], bars.c[i]) <= bars.h[i]:
            return "Malformed bar in history"
        if i and bars.t[i] - bars.t[i - 1] != step:
            return "Gap in bar history"
    return ""


class StrategyEngine:
    def __init__(self, strategy, coins, interval, state_file=None, settle_s=5.0):
        self.strategy = strategy
        self.coins = list(coins)
        self.interval = interval
        self.step = INTERVAL_MS[interval]
        self.settle_ms = int(settle_s * 1000)
        self.state_file = Path(state_file) if state_file else None
        self.state = {coin: dict(position=None, last_bar=0, decision=None, reason="Waiting for first bar close",
                                 updated=0.0, retry_at=0.0, failures=0) for coin in self.coins}
        self._load()

    @property
    def history_bars(self):
        # Long enough that EMA seeding matches the backtester's full-history values.
        return min(5000, max(1000, self.strategy.warmup * 10))

    @property
    def max_entry_delay_ms(self):
        """Signals older than this open nothing (after outages or restarts)."""
        return min(300_000, self.step // 4)

    def _load(self):
        if not self.state_file or not self.state_file.exists():
            return
        try:
            saved = json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            log.exception("Strategy state unreadable; positions will be adopted from the exchange")
            return
        if saved.get("strategy") != self.strategy.label or saved.get("interval") != self.interval:
            log.warning("Strategy changed from %s; open positions will be re-adopted", saved.get("strategy"))
            return
        for coin, entry in saved.get("coins", {}).items():
            if coin in self.state:
                self.state[coin].update({k: entry.get(k) for k in ("last_bar", "decision", "reason", "updated")})
                if entry.get("position"):
                    self.state[coin]["position"] = Position(**entry["position"])

    def save(self):
        if not self.state_file:
            return
        coins = {}
        for coin, entry in self.state.items():
            coins[coin] = {k: entry[k] for k in ("last_bar", "decision", "reason", "updated")}
            coins[coin]["position"] = entry["position"].to_dict() if entry["position"] else None
        payload = dict(strategy=self.strategy.label, interval=self.interval, coins=coins)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_file.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2))
        temp.replace(self.state_file)

    def due(self, coin, now=None):
        now_ms = int((now or time.time()) * 1000)
        entry = self.state[coin]
        if now_ms < entry.get("retry_at", 0) * 1000:
            return False
        return latest_closed_open(now_ms - self.settle_ms, self.step) > (entry["last_bar"] or 0)

    def defer(self, coin, reason, now=None):
        """Back off after an unavailable/invalid bar fetch (5s doubling to 2 minutes)."""
        entry = self.state[coin]
        entry["failures"] = entry.get("failures", 0) + 1
        entry["retry_at"] = (now or time.time()) + min(120, 5 * 2 ** min(entry["failures"] - 1, 5))
        entry["reason"] = reason

    def position(self, coin):
        return self.state[coin]["position"]

    def stops(self):
        return {coin: e["position"].stop for coin, e in self.state.items() if e["position"]}

    def sync(self, coin, live, series=None, bars=None, existing_stop=None):
        """Align metadata with the exchange; ``live`` is None or dict(side, size, entry_px).

        An adopted position keeps the tighter of its volatility stop and any stop already
        resting on the exchange, so adoption can never loosen protection.
        """
        entry = self.state[coin]
        held = entry["position"]
        if not live:
            if held:
                log.info("%s position closed on exchange; strategy metadata cleared", coin)
            entry["position"] = None
            return None
        if held and held.side == live["side"]:
            return held
        stop = self.adoption_stop(live["side"], live["entry_px"], series, bars)
        if stop is None:
            return held if held and held.side == live["side"] else None
        adopted = Position(live["side"], live["entry_px"], int(time.time() * 1000), stop, live["entry_px"])
        if existing_stop is not None:
            adopted.stop = tighten(adopted, existing_stop)
        entry["position"] = adopted
        log.warning("Adopted %s %s position at %.6g with stop %.6g", coin,
                    "long" if live["side"] > 0 else "short", live["entry_px"], adopted.stop)
        return adopted

    def adoption_stop(self, side, price, series, bars):
        if series is None or bars is None or not len(bars):
            return None
        atr = series.get("atr", [float("nan")])[-1]
        multiple = self.strategy.params.get("stop_atr") or self.strategy.params.get("chandelier") or 2.0
        if not math.isfinite(atr) or atr <= 0:
            return None
        return price - side * multiple * atr

    def evaluate(self, coin, candles, live, now=None, existing_stop=None):
        """Run the strategy on the newest closed bar; returns a Decision or None."""
        now = now or time.time()
        try:
            bars = Bars.from_candles(candles)
        except (KeyError, TypeError, ValueError):
            self.defer(coin, "Malformed bar in history", now)
            return None
        expected = latest_closed_open(int(now * 1000) - self.settle_ms, self.step)
        problem = validate(bars, self.step, expected, self.strategy.warmup + 2)
        if problem:
            self.defer(coin, problem, now)
            return None
        series = self.strategy.indicators(bars)
        entry = self.state[coin]
        held = self.sync(coin, live, series, bars, existing_stop)
        i = len(bars) - 1
        if held:
            newer = [k for k, t in enumerate(bars.t) if t > max(entry["last_bar"] or 0, held.entry_time - self.step)]
            for k in newer or [i]:
                advance(held, bars, k)
        decision = self.strategy.decide(i, bars, series, held)
        if held and decision.action == "hold" and decision.stop is not None:
            held.stop = tighten(held, decision.stop)
            decision = Decision("hold", held.side, held.stop, decision.reason)
        late = int(now * 1000) - (bars.t[i] + self.step) > self.max_entry_delay_ms
        if late and decision.action == "enter":
            decision = Decision("wait", reason=f"{decision.reason} (signal bar closed too long ago; no late entry)")
        elif late and decision.action == "reverse":
            decision = Decision("exit", reason=f"{decision.reason} (late signal: exit only)")
        entry.update(last_bar=bars.t[i], decision=decision.to_dict(), reason=decision.reason,
                     updated=now, failures=0, retry_at=0.0, close=bars.c[i], atr=series.get("atr", [None])[-1])
        self.save()
        return decision

    def opened(self, coin, side, price, stop, when_ms=None):
        self.state[coin]["position"] = Position(side, price, when_ms or int(time.time() * 1000), stop, price)
        self.save()

    def closed(self, coin):
        self.state[coin]["position"] = None
        self.save()

    def summary(self):
        coins = {}
        for coin, entry in self.state.items():
            pos = entry["position"]
            coins[coin] = dict(last_bar=entry["last_bar"], reason=entry["reason"], decision=entry["decision"],
                               updated=entry["updated"], close=entry.get("close"), atr=entry.get("atr"),
                               position=pos.to_dict() if pos else None)
        return dict(strategy=self.strategy.label, name=self.strategy.name, params=self.strategy.params,
                    interval=self.interval, coins=coins,
                    next_bar_close=(latest_closed_open(int(time.time() * 1000), self.step) + 2 * self.step) / 1000)
