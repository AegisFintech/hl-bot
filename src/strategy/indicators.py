"""Causal bar indicators shared by live execution and offline backtests.

Every series has the same length as its input. A value at index ``i`` only uses
bars ``0..i`` (or ``0..i-1`` for channel levels), so replaying the same bars
bar-by-bar produces exactly the decisions the live engine makes at each close.
Undefined warm-up values are ``nan``.
"""

import math
from collections import deque

NAN = float("nan")


def ema(values, period):
    out = [NAN] * len(values)
    if period < 1 or len(values) < period:
        return out
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    for i in range(period, len(values)):
        seed = values[i] * k + seed * (1 - k)
        out[i] = seed
    return out


def true_range(highs, lows, closes):
    out = [NAN] * len(closes)
    for i in range(len(closes)):
        span = highs[i] - lows[i]
        if i:
            span = max(span, abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        out[i] = span
    return out


def atr(highs, lows, closes, period):
    """Wilder average true range."""
    out = [NAN] * len(closes)
    if period < 1 or len(closes) <= period:
        return out
    tr = true_range(highs, lows, closes)
    value = sum(tr[1:period + 1]) / period
    out[period] = value
    for i in range(period + 1, len(closes)):
        value = (value * (period - 1) + tr[i]) / period
        out[i] = value
    return out


def _rolling_extreme(values, period, better):
    """Extreme of the *previous* ``period`` values (excludes index ``i``)."""
    out = [NAN] * len(values)
    window = deque()  # Monotonic indices of the trailing window [i-period, i-1].
    for i, value in enumerate(values):
        while window and window[0] < i - period:
            window.popleft()
        if i >= period and window:
            out[i] = values[window[0]]
        while window and not better(values[window[-1]], value):
            window.pop()
        window.append(i)
    return out


def prior_high(highs, period):
    return _rolling_extreme(highs, period, lambda kept, new: kept > new)


def prior_low(lows, period):
    return _rolling_extreme(lows, period, lambda kept, new: kept < new)


def trailing_high(highs, period):
    """Highest high of the last ``period`` bars *including* bar ``i``."""
    return prior_high(list(highs) + [NAN], period)[1:]


def trailing_low(lows, period):
    """Lowest low of the last ``period`` bars *including* bar ``i``."""
    return prior_low(list(lows) + [NAN], period)[1:]


def rsi(closes, period):
    """Wilder relative strength index."""
    out = [NAN] * len(closes)
    if period < 1 or len(closes) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    gain, loss = gains / period, losses / period

    def value():
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + gain / loss)

    out[period] = value()
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        gain = (gain * (period - 1) + max(change, 0.0)) / period
        loss = (loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = value()
    return out


def rate_of_change(closes, period):
    out = [NAN] * len(closes)
    for i in range(period, len(closes)):
        if closes[i - period] > 0:
            out[i] = closes[i] / closes[i - period] - 1.0
    return out


def finite(*values):
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)
