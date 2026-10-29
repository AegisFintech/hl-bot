"""Read-only review of an account's exchange history (fills, orders, funding, equity).

Public info endpoints only: no keys, signing or orders. Testnet by default.

Usage:
  python3 scripts/account_history.py 0xMASTER [--network testnet] [--days 120] [--out artifacts/account-history.json]
"""

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.fetch_history import HL_URL, _post  # noqa: E402
from src.learning.trades import complete_trades  # noqa: E402

DAY = 86_400_000


def paged(url, body, key="time", limit_hint=2000, max_pages=200):
    """Walk a time-ranged info endpoint forward until it stops returning new rows."""
    rows, seen, cursor = [], set(), body["startTime"]
    for _ in range(max_pages):
        page = _post(url, dict(body, startTime=cursor))
        fresh = [r for r in page if json.dumps(r, sort_keys=True) not in seen]
        if not fresh:
            break
        for row in fresh:
            seen.add(json.dumps(row, sort_keys=True))
        rows.extend(fresh)
        cursor = max(int(r[key]) for r in fresh) + 1
        if len(page) < limit_hint:  # A short page is the end of the available range.
            break
        time.sleep(0.3)
    return rows


def utc(ms):
    return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


def summarize(fills, orders, funding, state):
    by_oid = {}
    for row in orders:
        order = row.get("order", {})
        by_oid[order.get("oid")] = dict(type=order.get("orderType"), status=row.get("status"),
                                        reduce_only=order.get("reduceOnly"), tif=order.get("tif"))
    gross = sum(float(f.get("closedPnl", 0) or 0) for f in fills)
    fees = sum(float(f.get("fee", 0) or 0) for f in fills)
    paid = sum(float(r.get("delta", {}).get("usdc", 0) or 0) for r in funding)
    exits = Counter()
    exit_pnl = defaultdict(float)
    for fill in fills:
        if float(fill.get("closedPnl", 0) or 0) == 0 and "Close" not in fill.get("dir", ""):
            continue
        kind = by_oid.get(fill.get("oid"), {}).get("type") or "unknown (outside retrieved orders)"
        exits[kind] += 1
        exit_pnl[kind] += float(fill.get("closedPnl", 0) or 0) - float(fill.get("fee", 0) or 0)
    episodes = complete_trades(fills)
    wins = [e for e in episodes if e["net_pnl"] > 0]
    losses = [e for e in episodes if e["net_pnl"] <= 0]
    holds = sorted((int(e["closed_at"]) - int(e["opened_at"])) / 60000 for e in episodes)
    hourly = defaultdict(lambda: [0, 0.0])
    for e in episodes:
        hour = datetime.fromtimestamp(int(e["opened_at"]) / 1000, timezone.utc).hour
        hourly[hour][0] += 1
        hourly[hour][1] += e["net_pnl"]
    daily = defaultdict(float)
    for f in fills:
        daily[utc(f["time"])[:10]] += float(f.get("closedPnl", 0) or 0) - float(f.get("fee", 0) or 0)
    statuses = Counter(row.get("status") for row in orders)
    types = Counter(row.get("order", {}).get("orderType") for row in orders)
    return dict(
        window=dict(first_fill=utc(min(int(f["time"]) for f in fills)) if fills else None,
                    last_fill=utc(max(int(f["time"]) for f in fills)) if fills else None,
                    fills=len(fills), orders=len(orders), funding_rows=len(funding)),
        fills=dict(gross_closed_pnl=gross, fees=fees, net_before_funding=gross - fees,
                   funding=paid, net_after_funding=gross - fees + paid,
                   fees_as_pct_of_abs_gross=100 * fees / abs(gross) if gross else None,
                   by_coin={c: sum(float(f.get("closedPnl", 0) or 0) - float(f.get("fee", 0) or 0)
                                   for f in fills if f["coin"] == c) for c in sorted({f["coin"] for f in fills})}),
        round_trips=dict(count=len(episodes), wins=len(wins), losses=len(losses),
                         win_rate_pct=100 * len(wins) / len(episodes) if episodes else None,
                         avg_win=sum(e["net_pnl"] for e in wins) / len(wins) if wins else None,
                         avg_loss=sum(e["net_pnl"] for e in losses) / len(losses) if losses else None,
                         profit_factor=(sum(e["net_pnl"] for e in wins) / -sum(e["net_pnl"] for e in losses))
                         if losses and sum(e["net_pnl"] for e in losses) < 0 else None,
                         median_hold_minutes=holds[len(holds) // 2] if holds else None,
                         by_entry_hour_utc={h: dict(trades=n, net=round(v, 4)) for h, (n, v) in sorted(hourly.items())}),
        exits_by_order_type={k: dict(fills=v, net=round(exit_pnl[k], 4)) for k, v in exits.most_common()},
        order_statuses=dict(statuses.most_common()),
        order_types=dict(types.most_common()),
        worst_days=sorted(((d, round(v, 4)) for d, v in daily.items()), key=lambda x: x[1])[:10],
        best_days=sorted(((d, round(v, 4)) for d, v in daily.items()), key=lambda x: -x[1])[:10],
        current=dict(account_value=state.get("marginSummary", {}).get("accountValue"),
                     positions=[p["position"] for p in state.get("assetPositions", [])]),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("address")
    parser.add_argument("--network", choices=["mainnet", "testnet"], default="testnet")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "account-history.json"))
    args = parser.parse_args(argv)
    url, user = HL_URL[args.network], args.address
    start = int(time.time() * 1000) - args.days * DAY
    fills = paged(url, {"type": "userFillsByTime", "user": user, "startTime": start, "aggregateByTime": False})
    if not fills:
        fills = _post(url, {"type": "userFills", "user": user})
    orders = _post(url, {"type": "historicalOrders", "user": user})
    funding = paged(url, {"type": "userFunding", "user": user, "startTime": start}, limit_hint=500)
    state = _post(url, {"type": "clearinghouseState", "user": user})
    report = summarize(fills, orders, funding, state)
    raw = Path(args.out).with_suffix(".raw.json")
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(json.dumps(dict(fills=fills, orders=orders, funding=funding, state=state)))
    Path(args.out).write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
