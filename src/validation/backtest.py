"""Event-driven multi-market backtest that replays the live strategy decision path.

Conventions (conservative, documented in docs/STRATEGY.md):
- Decisions use closed bars only and execute at the *next* bar open as taker
  orders with adverse slippage. Entries skip when the open gapped through the stop.
- Protective stops are exchange stop-market orders: a bar that touches the stop
  exits at the stop (or the worse open on a gap) with extra adverse slippage.
  A position opened at a bar's open is exposed to that bar's stop check.
- Funding uses supplied hourly rates (longs pay positive rates). Without a
  history, a stress rate is charged to both sides.
- The drawdown breaker mirrors live risk control: at a bar close whose equity is
  at or below ``peak * (1 - limit)`` everything is flattened, entries pause for the
  cooldown and the peak is re-based to post-flatten equity. Live checks run every
  few seconds, so live breaker exits happen earlier than this close-based model.
No result here is a fill, a forecast or proof of future profit.
"""

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from src.risk.manager import position_size
from src.strategy.library import Position, advance, tighten

HOUR_MS = 3_600_000
DAY_MS = 86_400_000


@dataclass
class Costs:
    taker_fee: float = 0.00045
    slippage: float = 0.0003
    stop_slippage: float = 0.0005
    funding_stress_per_hour: float = 0.0000125


@dataclass
class Risk:
    risk_per_trade: float = 0.005
    max_leverage: float = 3.0
    max_gross_leverage: float = 5.0
    max_positions: int = 4
    min_notional: float = 10.0
    drawdown_limit: float = 0.0
    cooldown_hours: float = 12.0


def backtest(strategy, markets, interval_ms, costs=None, risk=None, funding=None,
             initial_equity=1000.0, start_time=None, end_time=None):
    """Replay ``markets`` ({coin: Bars}) bar by bar; returns metrics and trades."""
    costs, risk, funding = costs or Costs(), risk or Risk(), funding or {}
    series = {coin: strategy.indicators(bars) for coin, bars in markets.items()}
    index = {coin: {t: i for i, t in enumerate(bars.t)} for coin, bars in markets.items()}
    timeline = sorted({t for bars in markets.values() for t in bars.t
                       if (start_time is None or t >= start_time) and (end_time is None or t < end_time)})
    state = dict(cash=float(initial_equity), peak=float(initial_equity), cooldown_until=-math.inf)
    positions, pending, last_close = {}, {}, {}
    trades, curve, skipped = [], [], {}
    trips = exposed = 0

    def skip(reason):
        skipped[reason] = skipped.get(reason, 0) + 1

    def equity():
        return state["cash"] + sum((last_close[c] - p["pos"].entry_price) * p["size"] * p["pos"].side
                                   for c, p in positions.items())

    def close(coin, price, when, reason, slip):
        held = positions.pop(coin)
        pos, size = held["pos"], held["size"]
        fill = price * (1 - pos.side * slip)
        gross = (fill - pos.entry_price) * size * pos.side
        fee = size * fill * costs.taker_fee
        state["cash"] += gross - fee
        net = gross - held["fees"] - fee - held["funding"]
        trades.append(dict(coin=coin, side=pos.side, entry_time=pos.entry_time, exit_time=when,
                           entry=pos.entry_price, exit=fill, size=size, gross=gross,
                           fees=held["fees"] + fee, funding=held["funding"], net=net,
                           r=net / held["risk"] if held["risk"] else 0.0, bars=pos.bars_held, reason=reason))

    def open_(coin, decision, price, when):
        if when < state["cooldown_until"]:
            return skip("Drawdown cooldown")
        if len(positions) >= risk.max_positions:
            return skip("Maximum positions")
        side = decision.side
        fill = price * (1 + side * costs.slippage)
        distance = (fill - decision.stop) * side
        if distance <= 0:
            return skip("Opened beyond stop")
        account = equity()
        if account <= 0:
            return skip("No equity")
        gross_open = sum(p["size"] * last_close[c] for c, p in positions.items())
        size = position_size(account, fill, decision.stop, risk.risk_per_trade, risk.max_leverage,
                             risk.max_gross_leverage, gross_open)
        if size * fill < risk.min_notional:
            return skip("Below minimum notional")
        fee = size * fill * costs.taker_fee
        state["cash"] -= fee
        positions[coin] = dict(pos=Position(side, fill, when, decision.stop, fill), size=size,
                               fees=fee, funding=0.0, risk=size * distance)

    for t in timeline:
        for coin, decision in list(pending.items()):
            i = index[coin].get(t)
            if i is None:
                continue
            del pending[coin]
            price = markets[coin].o[i]
            if decision.action in ("exit", "reverse") and coin in positions:
                close(coin, price, t, decision.reason, costs.slippage)
            if decision.action in ("enter", "reverse") and coin not in positions:
                open_(coin, decision, price, t)

        for coin in list(positions):
            i = index[coin].get(t)
            if i is None:
                continue
            bars, held = markets[coin], positions[coin]
            pos = held["pos"]
            hours = interval_ms / HOUR_MS
            rates = funding.get(coin)
            if rates is not None:
                rate = rates.get(t - t % HOUR_MS, 0.0)
                held["funding"] += held["size"] * bars.o[i] * rate * hours * pos.side
                state["cash"] -= held["size"] * bars.o[i] * rate * hours * pos.side
            else:
                cost = held["size"] * bars.o[i] * costs.funding_stress_per_hour * hours
                held["funding"] += cost
                state["cash"] -= cost
            if pos.side > 0 and bars.l[i] <= pos.stop:
                close(coin, min(pos.stop, bars.o[i]), t, "Protective stop", costs.stop_slippage)
            elif pos.side < 0 and bars.h[i] >= pos.stop:
                close(coin, max(pos.stop, bars.o[i]), t, "Protective stop", costs.stop_slippage)

        for coin, bars in markets.items():
            i = index[coin].get(t)
            if i is not None:
                last_close[coin] = bars.c[i]
        value = equity()
        state["peak"] = max(state["peak"], value)
        if risk.drawdown_limit and value <= state["peak"] * (1 - risk.drawdown_limit):
            for coin in list(positions):
                close(coin, last_close[coin], t + interval_ms, "Drawdown breaker", costs.slippage)
            pending.clear()
            trips += 1
            state["cooldown_until"] = t + interval_ms + risk.cooldown_hours * HOUR_MS
            value = equity()
            state["peak"] = value
        exposed += bool(positions)
        curve.append((t + interval_ms, value))

        if t + interval_ms < state["cooldown_until"]:
            continue
        for coin, bars in markets.items():
            i = index[coin].get(t)
            if i is None or i < strategy.warmup:
                continue
            held = positions.get(coin)
            pos = advance(held["pos"], bars, i) if held else None
            decision = strategy.decide(i, bars, series[coin], pos)
            if pos and decision.action == "hold" and decision.stop is not None:
                pos.stop = tighten(pos, decision.stop)
            elif decision.action in ("exit", "reverse") and pos:
                pending[coin] = decision
            elif decision.action == "enter" and not pos:
                pending[coin] = decision

    for coin in list(positions):
        close(coin, last_close[coin], timeline[-1] + interval_ms, "End of test window", costs.slippage)
    if curve:
        curve[-1] = (curve[-1][0], state["cash"])
    result = metrics(curve, trades, initial_equity)
    result.update(strategy=strategy.label, markets=sorted(markets), drawdown_breaker_trips=trips,
                  exposure_pct=100.0 * exposed / len(timeline) if timeline else 0.0,
                  skipped_entries=skipped, costs=asdict(costs), risk=asdict(risk),
                  funding_source={c: ("history" if c in funding else "stress") for c in sorted(markets)})
    return result, trades, curve


def metrics(curve, trades, initial_equity):
    if not curve:
        return dict(trades=0, final_equity=initial_equity, return_pct=0.0)
    final = curve[-1][1]
    days = max((curve[-1][0] - curve[0][0]) / DAY_MS, 1e-9)
    daily = {}
    for stamp, value in curve:
        daily[stamp // DAY_MS] = value
    values = [initial_equity] + [daily[d] for d in sorted(daily)]
    returns = [b / a - 1 for a, b in zip(values, values[1:]) if a > 0]
    mean = sum(returns) / len(returns) if returns else 0.0
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1) if len(returns) > 1 else 0.0
    down = [min(r, 0.0) for r in returns]
    down_dev = math.sqrt(sum(r * r for r in down) / len(down)) if down else 0.0
    peak, max_dd = initial_equity, 0.0
    for _, value in curve:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, 1 - value / peak)
    wins = [t["net"] for t in trades if t["net"] > 0]
    losses = [t["net"] for t in trades if t["net"] <= 0]
    yearly = {}
    first = initial_equity
    for stamp, value in curve:
        year = datetime.fromtimestamp(stamp / 1000, timezone.utc).year
        yearly.setdefault(year, [first, value])[1] = value
        first = value
    cagr = (final / initial_equity) ** (365 / days) - 1 if final > 0 and days >= 30 else None
    return dict(
        start=curve[0][0], end=curve[-1][0], days=round(days, 2), final_equity=final,
        return_pct=100 * (final / initial_equity - 1), cagr_pct=None if cagr is None else 100 * cagr,
        max_drawdown_pct=100 * max_dd,
        sharpe=mean / math.sqrt(var) * math.sqrt(365) if var > 0 else 0.0,
        sortino=mean / down_dev * math.sqrt(365) if down_dev > 0 else 0.0,
        calmar=(cagr / max_dd) if cagr is not None and max_dd > 0 else None,
        trades=len(trades), trades_per_day=len(trades) / days,
        win_rate_pct=100 * len(wins) / len(trades) if trades else 0.0,
        profit_factor=sum(wins) / -sum(losses) if losses and sum(losses) < 0 else None,
        expectancy_usd=sum(t["net"] for t in trades) / len(trades) if trades else 0.0,
        avg_r=sum(t["r"] for t in trades) / len(trades) if trades else 0.0,
        fees_usd=sum(t["fees"] for t in trades), funding_usd=sum(t["funding"] for t in trades),
        yearly_return_pct={y: 100 * (b / a - 1) for y, (a, b) in sorted(yearly.items()) if a > 0},
    )
