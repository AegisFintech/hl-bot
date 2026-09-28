#!/usr/bin/env python3
"""Append a timestamped performance snapshot to data/perf_log.jsonl.
Run via cron every hour to track strategy performance over time."""
import json
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
PERF_FILE = PROJECT / "data" / "performance.json"
TRADES_FILE = PROJECT / "data" / "trades.json"
LOG_OUT = PROJECT / "data" / "perf_log.jsonl"


def main():
    perf = {}
    try:
        perf = json.loads(PERF_FILE.read_text())
    except Exception:
        pass

    recent_pnl = 0.0
    recent_trades = 0
    recent_wins = 0
    try:
        trades = json.loads(TRADES_FILE.read_text())
        cutoff = time.time() - 3600
        recent = [t for t in trades if t.get("entry_time", 0) >= cutoff]
        recent_trades = len(recent)
        recent_wins = sum(1 for t in recent if t.get("pnl", 0) > 0)
        recent_pnl = sum(t.get("pnl", 0) for t in recent)
    except Exception:
        pass

    snapshot = {
        "ts": time.time(),
        "time": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "total_trades": perf.get("total_trades", 0),
        "win_rate": perf.get("win_rate", 0),
        "total_pnl": perf.get("total_pnl", 0),
        "profit_factor": perf.get("profit_factor", 0),
        "sharpe": perf.get("sharpe_ratio", 0),
        "last_1h_trades": recent_trades,
        "last_1h_wins": recent_wins,
        "last_1h_pnl": round(recent_pnl, 6),
    }

    with open(LOG_OUT, "a") as f:
        f.write(json.dumps(snapshot) + "\n")

    print(f"[{snapshot['time']}] trades={recent_trades} wins={recent_wins} pnl={recent_pnl:+.4f} | total={perf.get('total_trades', 0)} wr={perf.get('win_rate', 0)*100:.1f}%")


if __name__ == "__main__":
    main()
