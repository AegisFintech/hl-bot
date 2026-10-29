#!/usr/bin/env python3
"""
HL-Bot Performance Monitor

Usage:
  python3 scripts/monitor.py              # Full dashboard
  python3 scripts/monitor.py --since 1h   # Trades in last 1h/6h/24h
  python3 scripts/monitor.py --live       # Tail log for signals and fills
"""
import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
TRADES_FILE = PROJECT / "data" / "trades.json"
PERF_FILE = PROJECT / "data" / "performance.json"
LOG_FILE = PROJECT / "bot.log"


def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def parse_duration(s: str) -> timedelta:
    m = re.match(r"(\d+)\s*(h|m|d)", s.strip().lower())
    if not m:
        return timedelta(hours=1)
    val, unit = int(m.group(1)), m.group(2)
    if unit == "m":
        return timedelta(minutes=val)
    if unit == "d":
        return timedelta(days=val)
    return timedelta(hours=val)


def bot_status() -> str:
    try:
        r = subprocess.run(["systemctl", "is-active", "hl-bot"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return "unknown"


def print_header():
    status = bot_status()
    status_icon = "RUNNING" if status == "active" else f"DOWN ({status})"
    print(f"{'='*60}")
    print("  HL-Bot Performance Monitor")
    print(f"  Status: {status_icon}  |  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")


def print_overall_stats():
    sys.path.insert(0, str(PROJECT))
    from src.learning.ledger import FillLedger
    perf = FillLedger(PROJECT / 'data/ledger.sqlite').performance()
    print("\n  EXCHANGE LEDGER (funding excluded)")
    print(f"  Imported fills: {perf['fill_count']} | closing fills: {perf['closing_fills']}")
    print(f"  Gross realized: ${perf['gross_pnl']:+.6f} | Fees: ${perf['fees']:.6f}")
    print(f"  Net realized: ${perf['net_pnl']:+.6f}")
    print("  Partial fills are not complete trades. Legacy journal below is gross.")


def print_recent_trades(since: timedelta | None = None):
    trades = load_json(TRADES_FILE)
    if not trades:
        print("\n  No trades recorded.")
        return

    if since:
        cutoff = time.time() - since.total_seconds()
        recent = [t for t in trades if t.get("entry_time", 0) >= cutoff]
        label = f"TRADES (last {int(since.total_seconds()/3600)}h)" if since.total_seconds() >= 3600 else f"TRADES (last {int(since.total_seconds()/60)}m)"
    else:
        recent = trades[-20:]
        label = "LAST 20 TRADES"

    if not recent:
        print(f"\n  {label}: none")
        return

    wins = sum(1 for t in recent if t.get("pnl", 0) > 0)
    total_pnl = sum(t.get("pnl", 0) for t in recent)
    wr = (wins / len(recent) * 100) if recent else 0

    print(f"\n  {label}  ({len(recent)} trades, {wr:.0f}% WR, ${total_pnl:+.4f})")
    print(f"  {'─'*56}")
    print(f"  {'Time':<18} {'Side':<6} {'Entry':>10} {'Exit':>10} {'PnL':>10} {'Reason':<6}")
    print(f"  {'─'*56}")

    for t in recent[-20:]:
        entry_t = datetime.fromtimestamp(t.get("entry_time", 0), tz=timezone.utc).strftime("%m-%d %H:%M")
        side = t.get("side", "?")
        entry_p = t.get("entry_price", 0)
        exit_p = t.get("exit_price", 0)
        pnl = t.get("pnl", 0)
        reason = t.get("exit_reason", "?")
        pnl_str = f"${pnl:+.4f}"
        print(f"  {entry_t:<18} {side:<6} {entry_p:>10.1f} {exit_p:>10.1f} {pnl_str:>10} {reason:<6}")


def print_signal_stats():
    """Parse recent log for signal/filter stats."""
    if not LOG_FILE.exists():
        return

    lines = LOG_FILE.read_text().splitlines()[-2000:]

    trends = {"up": 0, "down": 0, "neutral": 0}
    signals_placed = 0
    signals_blocked_trend = 0
    fills = 0
    scores = []

    for line in lines:
        if "trend=" in line:
            m = re.search(r"trend=(\w+)", line)
            if m and m.group(1) in trends:
                trends[m.group(1)] += 1

        if "Placing" in line and "score=" in line:
            signals_placed += 1
            m = re.search(r"score=([\d.]+)", line)
            if m:
                scores.append(float(m.group(1)))

        if "neutral → skip" in line.lower() or "counter-trend" in line.lower():
            signals_blocked_trend += 1

        if "Fill:" in line or "fill" in line.lower() and "filled" in line.lower():
            fills += 1

    print("\n  SIGNAL ANALYSIS (last ~2000 log lines)")
    print(f"  {'─'*40}")
    print(f"  Trend readings: up={trends['up']}  down={trends['down']}  neutral={trends['neutral']}")
    print(f"  Orders placed: {signals_placed}")
    if scores:
        print(f"  Score range: {min(scores):.2f} – {max(scores):.2f}  (avg {sum(scores)/len(scores):.2f})")
    print(f"  Fills detected: {fills}")


def live_tail():
    """Tail the log for key events."""
    print("\n  Live monitoring (Ctrl+C to stop)...\n")
    keywords = ["Placing", "Fill:", "ERROR", "Learning adjustments", "Performance", "kill switch", "trend="]
    try:
        proc = subprocess.Popen(
            ["tail", "-f", str(LOG_FILE)],
            stdout=subprocess.PIPE, text=True
        )
        for line in proc.stdout:
            line = line.strip()
            if any(k in line for k in keywords):
                print(f"  {line}")
    except KeyboardInterrupt:
        proc.kill()
        print("\n  Stopped.")


def main():
    parser = argparse.ArgumentParser(description="HL-Bot Performance Monitor")
    parser.add_argument("--since", help="Show trades since (e.g. 1h, 6h, 24h, 30m)")
    parser.add_argument("--live", action="store_true", help="Tail log for signals/fills")
    args = parser.parse_args()

    if args.live:
        print_header()
        live_tail()
        return

    print_header()
    print_overall_stats()

    since = parse_duration(args.since) if args.since else None
    print_recent_trades(since)
    print_signal_stats()
    print()


if __name__ == "__main__":
    main()
