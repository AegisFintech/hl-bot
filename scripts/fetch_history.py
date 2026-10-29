"""Download public candle and funding history for offline strategy research.

Public, unauthenticated reads only; never signs or submits anything.

Sources:
  hyperliquid  mainnet/testnet candleSnapshot (only the most recent 5000 bars per
               interval are served) and hourly fundingHistory
  binance      USD-M perpetual monthly archives from data.binance.vision (years of
               history; 8-hour funding converted to an hourly rate)

Usage:
  python3 scripts/fetch_history.py --source binance --coins BTC,ETH,SOL --interval 1h --since 2021-01
  python3 scripts/fetch_history.py --source hyperliquid --coins BTC,ETH --interval 1h --funding
Files land in data/history/<source>/ (private, git-ignored).
"""

import argparse
import csv
import io
import json
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "data" / "history"
HOUR = 3_600_000
INTERVAL_MS = {"15m": 900_000, "1h": HOUR, "4h": 4 * HOUR, "1d": 24 * HOUR}
HL_URL = {"mainnet": "https://api.hyperliquid.xyz/info", "testnet": "https://api.hyperliquid-testnet.xyz/info"}
BINANCE = "https://data.binance.vision/data/futures/um/monthly"


def _post(url, body, attempts=5):
    for attempt in range(attempts):
        try:
            response = requests.post(url, json=body, timeout=30)
            if response.status_code == 429:
                raise requests.HTTPError("rate limited")
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)


def closed_bars(bars, interval_ms, now_ms=None):
    """Sorted, de-duplicated, closed bars in Hyperliquid candle format."""
    now_ms = now_ms or int(time.time() * 1000)
    unique = {int(b["t"]): dict(t=int(b["t"]), o=float(b["o"]), h=float(b["h"]), l=float(b["l"]),
                                c=float(b["c"]), v=float(b.get("v", 0) or 0)) for b in bars}
    return [unique[t] for t in sorted(unique) if t + interval_ms <= now_ms]


def hyperliquid_candles(coin, interval, network="mainnet"):
    now = int(time.time() * 1000)
    start = now - 5000 * INTERVAL_MS[interval]
    raw = _post(HL_URL[network], {"type": "candleSnapshot",
                                  "req": {"coin": coin, "interval": interval, "startTime": start, "endTime": now}})
    return closed_bars(raw, INTERVAL_MS[interval], now)


def hyperliquid_funding(coin, since_ms, network="mainnet"):
    rates, cursor, now = {}, since_ms, int(time.time() * 1000)
    while cursor < now:
        rows = _post(HL_URL[network], {"type": "fundingHistory", "coin": coin, "startTime": cursor, "endTime": now})
        if not rows:
            break
        for row in rows:
            stamp = int(row["time"])
            rates[stamp - stamp % HOUR] = float(row["fundingRate"])
        latest = max(int(r["time"]) for r in rows)
        if latest < cursor:
            break
        cursor = latest + 1
        time.sleep(0.25)
    return rates


def _months(since, until):
    year, month = since
    while (year, month) <= until:
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _archive_rows(url):
    response = requests.get(url, timeout=60)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        with archive.open(archive.namelist()[0]) as handle:
            rows = list(csv.reader(io.TextIOWrapper(handle, "utf-8")))
    return [r for r in rows if r and r[0][:1].isdigit()]  # Some archives carry a header row.


def _last_full_month(now):
    return (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)


def binance_candles(coin, interval, since):
    symbol = coin + "USDT"
    now = datetime.now(timezone.utc)
    bars = []
    for year, month in _months(since, _last_full_month(now)):
        rows = _archive_rows(f"{BINANCE}/klines/{symbol}/{interval}/{symbol}-{interval}-{year}-{month:02d}.zip")
        bars.extend(dict(t=int(r[0]), o=r[1], h=r[2], l=r[3], c=r[4], v=r[5]) for r in rows or [])
    for day in range(1, now.day):  # The current month is only published as daily archives.
        rows = _archive_rows(f"{BINANCE.replace('/monthly', '/daily')}/klines/{symbol}/{interval}/"
                             f"{symbol}-{interval}-{now.year}-{now.month:02d}-{day:02d}.zip")
        bars.extend(dict(t=int(r[0]), o=r[1], h=r[2], l=r[3], c=r[4], v=r[5]) for r in rows or [])
    return closed_bars(bars, INTERVAL_MS[interval])


def binance_funding(coin, since):
    """Each settlement covers the preceding interval; spread it evenly over those hours."""
    symbol = coin + "USDT"
    rates = {}
    for year, month in _months(since, _last_full_month(datetime.now(timezone.utc))):
        rows = _archive_rows(f"{BINANCE}/fundingRate/{symbol}/{symbol}-fundingRate-{year}-{month:02d}.zip")
        for row in rows or []:
            stamp = int(row[0])
            stamp -= stamp % HOUR
            hours = int(float(row[1])) if row[1] else 8
            for k in range(1, hours + 1):
                rates[stamp - k * HOUR] = float(row[2]) / hours
    return rates


def save(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=["hyperliquid", "binance"], required=True)
    parser.add_argument("--network", choices=["mainnet", "testnet"], default="mainnet")
    parser.add_argument("--coins", default="BTC,ETH,SOL")
    parser.add_argument("--interval", default="1h", choices=sorted(INTERVAL_MS))
    parser.add_argument("--since", default="2021-01", help="YYYY-MM, Binance archives only")
    parser.add_argument("--funding", action="store_true", help="also fetch funding history")
    args = parser.parse_args(argv)
    since = tuple(int(x) for x in args.since.split("-"))
    folder = HISTORY / (args.source if args.source == "binance" else f"hyperliquid-{args.network}")
    for coin in [c.strip().upper() for c in args.coins.split(",") if c.strip()]:
        try:
            if args.source == "binance":
                bars = binance_candles(coin, args.interval, since)
            else:
                bars = hyperliquid_candles(coin, args.interval, args.network)
        except Exception as exc:  # Keep going: one unavailable market must not abort the batch.
            print(f"{coin}: candles unavailable ({type(exc).__name__}: {exc})", file=sys.stderr)
            continue
        path = save(folder / f"{coin}-{args.interval}.json", bars)
        span = f"{datetime.fromtimestamp(bars[0]['t'] / 1000, timezone.utc):%Y-%m-%d} → " \
               f"{datetime.fromtimestamp(bars[-1]['t'] / 1000, timezone.utc):%Y-%m-%d}" if bars else "empty"
        print(f"{coin}: {len(bars)} {args.interval} bars ({span}) → {path.relative_to(ROOT)}")
        if args.funding:
            try:
                if args.source == "binance":
                    rates = binance_funding(coin, since)
                else:
                    rates = hyperliquid_funding(coin, bars[0]["t"] if bars else int(time.time() * 1000) - 30 * 24 * HOUR,
                                                args.network)
                save(folder / f"{coin}-funding.json", {str(k): v for k, v in sorted(rates.items())})
                print(f"{coin}: {len(rates)} hourly funding rates")
            except Exception as exc:
                print(f"{coin}: funding unavailable ({type(exc).__name__}: {exc})", file=sys.stderr)


if __name__ == "__main__":
    main()
