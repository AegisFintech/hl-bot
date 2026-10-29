"""Closed-bar strategies shared verbatim by live trading and offline backtests.

A strategy never sizes orders or talks to an exchange. At each closed bar it
returns a :class:`Decision`: enter/exit/reverse at the next price, or hold with a
protective stop that may only tighten. Execution, sizing and risk limits are the
caller's job, so the backtester and the live engine share one decision path.
"""

from dataclasses import asdict, dataclass, field

from src.strategy import indicators as ind


@dataclass
class Bars:
    t: list = field(default_factory=list)  # bar open time, ms
    o: list = field(default_factory=list)
    h: list = field(default_factory=list)
    l: list = field(default_factory=list)
    c: list = field(default_factory=list)
    v: list = field(default_factory=list)

    @classmethod
    def from_candles(cls, candles):
        bars = cls()
        for candle in sorted(candles, key=lambda b: int(b["t"])):
            bars.t.append(int(candle["t"]))
            bars.o.append(float(candle["o"]))
            bars.h.append(float(candle["h"]))
            bars.l.append(float(candle["l"]))
            bars.c.append(float(candle["c"]))
            bars.v.append(float(candle.get("v", 0) or 0))
        return bars

    def __len__(self):
        return len(self.t)


@dataclass
class Position:
    side: int  # +1 long, -1 short
    entry_price: float
    entry_time: int
    stop: float
    extreme: float  # most favourable price since entry
    bars_held: int = 0

    def to_dict(self):
        return asdict(self)


@dataclass
class Decision:
    action: str  # enter | exit | reverse | hold | wait
    side: int = 0
    stop: float | None = None
    reason: str = ""

    def to_dict(self):
        return asdict(self)


def advance(position, bars, i):
    """Fold closed bar ``i`` into the open position before deciding on it."""
    if position.side > 0:
        position.extreme = max(position.extreme, bars.h[i])
    else:
        position.extreme = min(position.extreme, bars.l[i])
    position.bars_held += 1
    return position


def tighten(position, proposed):
    """Stops only ever move in the position's favour."""
    if not ind.finite(proposed):
        return position.stop
    if position.side > 0:
        return max(position.stop, proposed)
    return min(position.stop, proposed)


class Strategy:
    name = "base"
    defaults: dict = {}

    def __init__(self, **params):
        unknown = set(params) - set(self.defaults)
        if unknown:
            raise ValueError(f"Unknown {self.name} parameters: {sorted(unknown)}")
        self.params = {**self.defaults, **params}

    @property
    def label(self):
        return self.name + "(" + ",".join(f"{k}={v}" for k, v in sorted(self.params.items())) + ")"

    @property
    def warmup(self):
        raise NotImplementedError

    def indicators(self, bars):
        raise NotImplementedError

    def decide(self, i, bars, series, position):
        raise NotImplementedError

    def entry(self, side, price, atr_value, multiple, reason):
        if not ind.finite(price, atr_value) or atr_value <= 0:
            return Decision("wait", reason="Indicator warm-up")
        return Decision("enter", side, price - side * multiple * atr_value, reason)


class DonchianBreakout(Strategy):
    """Turtle-style channel breakout; the exit channel trails the stop."""

    name = "donchian"
    defaults = dict(entry=20, exit=10, atr=20, stop_atr=2.0, trend=0, allow_short=True)

    @property
    def warmup(self):
        p = self.params
        return max(p["entry"], p["exit"], p["atr"], p["trend"]) + 2

    def indicators(self, bars):
        p = self.params
        series = dict(
            upper=ind.prior_high(bars.h, p["entry"]),
            lower=ind.prior_low(bars.l, p["entry"]),
            trail_low=ind.trailing_low(bars.l, p["exit"]),
            trail_high=ind.trailing_high(bars.h, p["exit"]),
            atr=ind.atr(bars.h, bars.l, bars.c, p["atr"]),
        )
        if p["trend"]:
            series["trend"] = ind.ema(bars.c, p["trend"])
        return series

    def decide(self, i, bars, s, position):
        p, close = self.params, bars.c[i]
        if position:
            trail = s["trail_low"][i] if position.side > 0 else s["trail_high"][i]
            return Decision("hold", position.side, tighten(position, trail), "Trailing exit channel")
        upper, lower = s["upper"][i], s["lower"][i]
        if not ind.finite(upper, lower):
            return Decision("wait", reason="Indicator warm-up")
        trend = s.get("trend")
        up_ok = not trend or (ind.finite(trend[i]) and close > trend[i])
        down_ok = not trend or (ind.finite(trend[i]) and close < trend[i])
        if close > upper and up_ok:
            return self.entry(1, close, s["atr"][i], p["stop_atr"], f"Close above {p['entry']}-bar high")
        if close < lower and down_ok and p["allow_short"]:
            return self.entry(-1, close, s["atr"][i], p["stop_atr"], f"Close below {p['entry']}-bar low")
        return Decision("wait", reason="Inside channel")


class EmaTrend(Strategy):
    """Moving-average regime with a chandelier trailing stop and reversals."""

    name = "ema_trend"
    defaults = dict(fast=20, slow=100, atr=14, chandelier=3.0, allow_short=True)

    @property
    def warmup(self):
        return max(self.params["slow"], self.params["atr"]) + 2

    def indicators(self, bars):
        p = self.params
        return dict(fast=ind.ema(bars.c, p["fast"]), slow=ind.ema(bars.c, p["slow"]),
                    atr=ind.atr(bars.h, bars.l, bars.c, p["atr"]))

    def _regime(self, s, i):
        fast, slow = s["fast"][i], s["slow"][i]
        if not ind.finite(fast, slow):
            return 0
        return 1 if fast > slow else -1 if fast < slow else 0

    def decide(self, i, bars, s, position):
        p, close, atr_value = self.params, bars.c[i], s["atr"][i]
        regime = self._regime(s, i)
        if position:
            if regime == -position.side:
                if p["allow_short"] or regime > 0:
                    entry = self.entry(regime, close, atr_value, p["chandelier"], "Moving-average reversal")
                    if entry.action == "enter":
                        return Decision("reverse", regime, entry.stop, entry.reason)
                return Decision("exit", reason="Moving-average regime ended")
            trail = position.extreme - position.side * p["chandelier"] * atr_value
            return Decision("hold", position.side, tighten(position, trail), "Chandelier trailing stop")
        if not regime or i < 1:
            return Decision("wait", reason="No moving-average regime")
        crossed = self._regime(s, i - 1) != regime
        if crossed and (regime > 0 or p["allow_short"]):
            return self.entry(regime, close, atr_value, p["chandelier"], "Moving-average cross")
        return Decision("wait", reason="Waiting for a fresh cross")


class TimeSeriesMomentum(Strategy):
    """Hold the sign of the trailing return with a wide volatility stop."""

    name = "tsmom"
    defaults = dict(lookback=168, atr=24, stop_atr=4.0, allow_short=True)

    @property
    def warmup(self):
        return max(self.params["lookback"], self.params["atr"]) + 2

    def indicators(self, bars):
        p = self.params
        return dict(momentum=ind.rate_of_change(bars.c, p["lookback"]),
                    atr=ind.atr(bars.h, bars.l, bars.c, p["atr"]))

    def decide(self, i, bars, s, position):
        p, close, atr_value = self.params, bars.c[i], s["atr"][i]
        momentum = s["momentum"][i]
        signal = 0
        if ind.finite(momentum) and momentum:
            signal = 1 if momentum > 0 else -1
        if signal < 0 and not p["allow_short"]:
            signal = 0
        if position:
            if signal == -position.side:
                entry = self.entry(signal, close, atr_value, p["stop_atr"], "Momentum sign flipped")
                if entry.action == "enter":
                    return Decision("reverse", signal, entry.stop, entry.reason)
                return Decision("exit", reason="Momentum sign flipped")
            if not signal and momentum == momentum:  # finite zero momentum
                return Decision("exit", reason="Momentum flat")
            trail = position.extreme - position.side * p["stop_atr"] * atr_value
            return Decision("hold", position.side, tighten(position, trail), "Volatility trailing stop")
        if not signal:
            return Decision("wait", reason="No momentum signal")
        return self.entry(signal, close, atr_value, p["stop_atr"], f"{p['lookback']}-bar momentum")


class RsiReversion(Strategy):
    """Connors-style short-horizon RSI reversion in the direction of the trend."""

    name = "rsi_reversion"
    defaults = dict(rsi=2, low=10.0, high=90.0, trend=200, exit_ema=5, max_bars=12,
                    atr=14, stop_atr=2.5, allow_short=True)

    @property
    def warmup(self):
        p = self.params
        return max(p["trend"], p["atr"], p["exit_ema"], p["rsi"]) + 2

    def indicators(self, bars):
        p = self.params
        return dict(rsi=ind.rsi(bars.c, p["rsi"]), trend=ind.ema(bars.c, p["trend"]),
                    exit=ind.ema(bars.c, p["exit_ema"]), atr=ind.atr(bars.h, bars.l, bars.c, p["atr"]))

    def decide(self, i, bars, s, position):
        p, close = self.params, bars.c[i]
        if position:
            mean = s["exit"][i]
            if ind.finite(mean) and (close - mean) * position.side > 0:
                return Decision("exit", reason="Reverted to short-term mean")
            if position.bars_held >= p["max_bars"]:
                return Decision("exit", reason="Maximum holding period")
            return Decision("hold", position.side, position.stop, "Fixed volatility stop")
        value, trend = s["rsi"][i], s["trend"][i]
        if not ind.finite(value, trend):
            return Decision("wait", reason="Indicator warm-up")
        if close > trend and value < p["low"]:
            return self.entry(1, close, s["atr"][i], p["stop_atr"], "Oversold within uptrend")
        if close < trend and value > p["high"] and p["allow_short"]:
            return self.entry(-1, close, s["atr"][i], p["stop_atr"], "Overbought within downtrend")
        return Decision("wait", reason="No stretched move with the trend")


STRATEGIES = {cls.name: cls for cls in (DonchianBreakout, EmaTrend, TimeSeriesMomentum, RsiReversion)}


def build(name, **params):
    try:
        return STRATEGIES[name](**params)
    except KeyError:
        raise ValueError(f"Unknown strategy {name!r}; choose from {sorted(STRATEGIES)}") from None
