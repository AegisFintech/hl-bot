"""Conservative passive-entry/fixed-horizon model; trade volume is not queue proof."""

import math

VERSION = "passive-horizon-v1"


def finite(value, name, minimum=None):
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError("Invalid " + name)
    return result


def simulate(order, events, assumptions):
    """Events are ordered local receipts, with explicit aggressive trade side/identity.

    This does NOT model strategy TP/SL, mark triggers, hidden queue or liquidation.
    Funding is a signed supplied cost assumption, not an actual account payment.
    """
    if len(events) > 200000:
        raise ValueError("Trace exceeds bounded offline capacity")
    stamps = [finite(e["time"], "event time", 0) for e in events]
    if any(b < a for a, b in zip(stamps, stamps[1:])):
        raise ValueError("Trace is out of receipt order")
    direction = order["direction"]
    if direction not in (-1, 1):
        raise ValueError("Invalid direction")
    started = finite(order["time"], "time", 0)
    price = finite(order["limit"], "limit", 1e-12)
    size = finite(order["size"], "size", 1e-12)
    ttl = finite(order["entry_ttl_s"], "TTL", 0.001)
    horizon = finite(order["holding_s"], "holding horizon", 0.001)
    latency = finite(assumptions["latency_s"], "latency", 0)
    queue = finite(assumptions["queue_ahead"], "assumed queue", 0)
    participation = finite(assumptions["participation"], "participation", 0.000001)
    if participation > 1:
        raise ValueError("Participation exceeds available observed volume")
    max_age = finite(assumptions["max_quote_gap_s"], "quote gap", 0.001)
    maker = finite(assumptions["maker_fee_bps"], "maker fee")
    taker = finite(assumptions["taker_fee_bps"], "taker fee", 0)
    slip = finite(assumptions["exit_slippage_bps"], "slippage", 0)
    funding = finite(assumptions["funding_cost_bps_hour"], "signed funding cost")
    if slip >= 10000:
        raise ValueError("Slippage outside model domain")
    activation, deadline = started + latency, started + latency + ttl
    last_time = -float("inf")
    quote = None
    first_quote = None
    seen = set()
    filled = 0.0
    first_fill = None
    entry_checked = False
    fills = []
    exit_quote = None
    exit_due = deadline + horizon + latency
    invalid = None
    for event in events:
        stamp = finite(event["time"], "event time", 0)
        if stamp < last_time:
            raise ValueError("Trace is out of receipt order")
        last_time = stamp
        if stamp > exit_due + max_age:
            break
        if event["type"] == "quote":
            bid, ask = finite(event["bid"], "bid", 1e-12), finite(
                event["ask"], "ask", 1e-12
            )
            if bid >= ask:
                raise ValueError("Crossed/equal quote")
            if quote and quote["time"] >= started and stamp - quote["time"] > max_age:
                invalid = "Quote gap during simulation; execution path unknown"
                break
            quote = dict(time=stamp, bid=bid, ask=ask)
            if stamp <= activation:
                first_quote = quote
        elif event["type"] == "trade":
            if event["side"] not in ("buy", "sell") or event.get("id") is None:
                raise ValueError("Trade requires explicit aggressor side and identity")
            px, quantity = finite(event["price"], "trade price", 1e-12), finite(
                event["size"], "trade size", 0
            )
            ident = str(event["id"])
            if ident in seen:
                continue
            seen.add(ident)
            if activation <= stamp <= deadline:
                if not entry_checked:
                    if (
                        not first_quote
                        or not 0 <= activation - first_quote["time"] <= max_age
                    ):
                        invalid = "Fresh arrival quote unavailable"
                        break
                    entry_checked = True
                    if (direction == 1 and price >= first_quote["ask"]) or (
                        direction == -1 and price <= first_quote["bid"]
                    ):
                        return dict(
                            version=VERSION, status="post_only_rejected", filled_size=0
                        )
                if not quote or not 0 <= stamp - quote["time"] <= max_age:
                    invalid = "Fresh quote unavailable at possible fill"
                    break
                opposing = event["side"] == ("sell" if direction == 1 else "buy")
                reaches = px <= price if direction == 1 else px >= price
                if opposing and reaches and filled < size:
                    volume = quantity * participation
                    consumed = min(queue, volume)
                    queue -= consumed
                    volume -= consumed
                    fill = min(size - filled, volume)
                    if fill > 0:
                        filled += fill
                        first_fill = stamp if first_fill is None else first_fill
                        fills.append(dict(time=stamp, size=fill, price=price))
        else:
            raise ValueError("Unknown event type")
        if event["type"] == "quote" and stamp >= exit_due:
            exit_quote = quote
            break
    if invalid:
        return dict(
            version=VERSION, status="unavailable", reason=invalid, filled_size=filled
        )
    if not entry_checked:
        return dict(
            version=VERSION,
            status="unavailable",
            reason="No eligible post-arrival trade; fill unknown",
            filled_size=0,
        )
    if filled == 0:
        return dict(version=VERSION, status="unfilled", filled_size=0)
    if not exit_quote or exit_quote["time"] - exit_due > max_age:
        return dict(
            version=VERSION,
            status="unavailable",
            reason="Fixed-horizon executable exit quote unavailable",
            filled_size=filled,
        )
    exit_price = (
        exit_quote["bid"] * (1 - slip / 10000)
        if direction == 1
        else exit_quote["ask"] * (1 + slip / 10000)
    )
    gross = direction * (exit_price - price) * filled
    fees = price * filled * maker / 10000 + exit_price * filled * taker / 10000
    funding_usd = sum(
        price * f["size"] * funding / 10000 * (exit_quote["time"] - f["time"]) / 3600
        for f in fills
    )
    net = gross - fees - funding_usd
    return dict(
        version=VERSION,
        status="simulated",
        filled_size=filled,
        fill_fraction=filled / size,
        first_fill_at=first_fill,
        closed_at=exit_quote["time"],
        entry_price=price,
        exit_price=exit_price,
        gross_usd=gross,
        fees_usd=fees,
        funding_assumption_usd=funding_usd,
        net_usd=net,
        net_bps=net / (price * filled) * 10000,
        fills=fills,
        assumptions=dict(assumptions),
        scope="Hypothetical passive entry and fixed-horizon aggressive exit. Queue/participation/latency are supplied assumptions, not calibrated fills. TTL-bound entry cancellation is idealized; cancel races/TP/SL/mark triggers and hidden liquidity are not modeled. Not actual profit or a strategy backtest.",
    )
