"""Read-only local deployment check; returns nonzero unless the bot can trade.

A drawdown-breaker cooldown or operational recovery is reported with its resume
time; both still return nonzero because new entries are blocked.
"""
import sys
from datetime import datetime, timezone

import requests


def when(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ts else "unknown"


def main(url="http://127.0.0.1:8080/api/terminal"):
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        d = r.json()
        s = d["status"]
        risk = s.get("risk", {})
    except (requests.RequestException, ValueError, KeyError):
        print("FAIL dashboard unavailable or response invalid")
        return 1
    checks = dict(
        running=s.get("status") == "running",
        testnet=s.get("network") == "testnet",
        started=s.get("startup", "Ready") == "Ready",
        not_halted=not risk.get("halted", True),
        not_recovering=not risk.get("execution_paused", False),
        loop_responsive=d.get("operations", {}).get("responsive", False),
        equity_fresh=risk.get("equity_age_s", 999) <= 30,
        quotes_fresh=d.get("bbo_age_s", 999) <= 10,
        no_errors=not d.get("errors"),
    )
    ok = all(checks.values())
    detail = []
    if risk.get("halted"):
        detail.append(f"breaker={risk.get('halt_reason')} resumes={when(risk.get('cooldown_until'))}")
    if risk.get("execution_paused"):
        detail.append(f"recovery={risk.get('pause_reason')} retry={when(risk.get('pause_until'))}")
    if not checks["started"]:
        detail.append(f"startup={s.get('startup')}")
    print("PASS" if ok else "FAIL", f"network={s.get('network', 'unknown')}",
          f"strategy={s.get('strategy')}", f"equity_age={risk.get('equity_age_s')}",
          f"quote_age={round(d.get('bbo_age_s', 999), 1)}",
          "failed=" + ",".join(k for k, v in checks.items() if not v) if not ok else "",
          *detail, f"errors={d.get('errors')}" if d.get("errors") else "")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
