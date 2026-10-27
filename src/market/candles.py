"""Deterministic closed-bar integrity shared by execution and diagnostics."""
import math


def valid_bar(bar):
    try:
        stamp = int(bar['t'])
        values = [float(bar[k]) for k in ('o', 'h', 'l', 'c')]
        o, h, l, c = values
        return (stamp > 0 and stamp % 60000 == 0
                and all(math.isfinite(x) and x > 0 for x in values)
                and l <= min(o, c) <= max(o, c) <= h)
    except (KeyError, ValueError, TypeError, OverflowError):
        return False


def merge_bars(existing, incoming, limit=2000):
    """Newest observed update per timestamp, sorted and bounded; never forward-fill."""
    merged = {int(b['t']): dict(b) for b in existing if valid_bar(b)}
    rejected = 0
    for bar in incoming:
        if valid_bar(bar):
            merged[int(bar['t'])] = dict(bar)
        else:
            rejected += 1
    return [merged[t] for t in sorted(merged)[-limit:]], rejected


def coverage(bars, now, required=60):
    closed = [b for b in bars if valid_bar(b) and int(b['t']) + 60000 <= now * 1000]
    closed = sorted({int(b['t']): b for b in closed}.values(), key=lambda b: int(b['t']))[-required:]
    gaps = sum(max(0, (int(b['t']) - int(a['t'])) // 60000 - 1) for a, b in zip(closed, closed[1:]))
    age = now - (int(closed[-1]['t']) / 1000 + 60) if closed else None
    reason = ('Insufficient closed candles' if len(closed) < required else
              'Closed candle gap' if gaps else
              'Closed candles stale' if age is None or not 0 <= age <= 120 else 'Ready')
    return dict(eligible=reason == 'Ready', reason=reason, closed_count=len(closed),
                required=required, missing_bars=gaps, latest_closed_age_s=age,
                latest_closed_at=int(closed[-1]['t']) / 1000 if closed else None)
