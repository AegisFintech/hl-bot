"""Reconstruct flat-to-flat episodes only when exchange position continuity is known."""

import math


def complete_trades(fills):
    active = {}
    finished = []
    for fill in sorted(fills, key=lambda f: int(f["time"])):
        try:
            coin = fill["coin"]
            start = float(fill["startPosition"])
            size = float(fill["sz"])
            price = float(fill["px"])
            fee = float(fill["fee"])
            pnl = float(fill.get("closedPnl", 0))
            if fill.get("feeToken", "USDC") != "USDC" or fill["side"] not in ("A", "B"):
                active.pop(coin, None)
                continue
            if (
                not all(math.isfinite(v) for v in (start, size, price, fee, pnl))
                or size <= 0
                or price <= 0
            ):
                active.pop(coin, None)
                continue
        except (KeyError, ValueError, TypeError):
            active.pop(fill.get("coin"), None)
            continue
        signed = size if fill["side"] == "B" else -size
        end = start + signed
        if abs(end) < 1e-9:
            end = 0.0
        episode = active.get(coin)
        if episode and not math.isclose(episode["position"], start, abs_tol=1e-8):
            active.pop(coin, None)
            episode = None
        if start == 0:
            episode = dict(
                coin=coin,
                opened_at=fill["time"],
                gross_pnl=0.0,
                fees=0.0,
                fill_count=0,
                position=0.0,
            )
            active[coin] = episode
        reversed_ = start * end < 0
        close_share = abs(start) / size if reversed_ else 1.0
        if episode:
            episode["gross_pnl"] += pnl
            episode["fees"] += fee * close_share
            episode["fill_count"] += 1
            episode["position"] = end
            if end == 0 or reversed_:
                episode["closed_at"] = fill["time"]
                episode["net_pnl"] = episode["gross_pnl"] - episode["fees"]
                finished.append(episode)
                active.pop(coin, None)
        if reversed_:
            active[coin] = dict(
                coin=coin,
                opened_at=fill["time"],
                gross_pnl=0.0,
                fees=fee * (1 - close_share),
                fill_count=1,
                position=end,
            )
    return finished
