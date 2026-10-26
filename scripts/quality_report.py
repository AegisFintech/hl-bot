"""Read-only chronological challenger report; stdout JSON, optional private output."""

import argparse
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time


def report(path, since=0, until=None):
    until = time.time() if until is None else until
    if since >= until:
        raise ValueError("Report start must precede end")
    with closing(
        sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    ) as db:
        rows = db.execute(
            """SELECT s.kind,s.direction,o.horizon,s.time,o.net_bps
            FROM signals s JOIN outcomes o ON o.signal_id=s.id
            WHERE s.time>=? AND s.time<? AND o.status='complete' AND o.measured_at<=?
            ORDER BY s.time,s.id""",
            (since, until, until),
        ).fetchall()
        buckets = db.execute(
            "SELECT COUNT(*) FROM opportunities WHERE bucket>=? AND bucket<?",
            (since, until),
        ).fetchone()[0]
    groups = defaultdict(list)
    for kind, direction, horizon, stamp, net in rows:
        date = datetime.fromtimestamp(stamp, timezone.utc)
        week = date.strftime("%G-W%V")
        groups[(week, kind, direction, horizon)].append((stamp, net))
    results = []
    for (week, kind, direction, horizon), samples in sorted(groups.items()):
        selected = []
        for sample in samples:
            if not selected or sample[0] >= selected[-1][0] + horizon:
                selected.append(sample)
        results.append(
            dict(
                utc_week=week,
                kind=kind,
                direction=direction,
                horizon_s=horizon,
                n=len(samples),
                mean_net_bps=sum(s[1] for s in samples) / len(samples),
                nonoverlap_n=len(selected),
                nonoverlap_mean_net_bps=sum(s[1] for s in selected) / len(selected),
            )
        )
    return dict(
        since=since,
        until=until,
        observed_five_minute_buckets=buckets,
        results=results,
        scope="Testnet quote proxies, not fills, position sizing or portfolio returns. Only outcomes measured by cutoff included. UTC calendar-week cohorts; first/last weeks may be partial. Non-overlap does not imply independence. Incumbent candidates use a different selection schedule. No fitting, statistical significance or promotion claim.",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since", type=float, default=0, help="Inclusive epoch seconds"
    )
    parser.add_argument(
        "--until",
        type=float,
        default=None,
        help="Exclusive entry cutoff, inclusive outcome cutoff, epoch seconds",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    print(
        json.dumps(
            report(root / "data/quality.sqlite", args.since, args.until), indent=2
        )
    )
