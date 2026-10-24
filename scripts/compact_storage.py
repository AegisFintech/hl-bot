"""Offline one-time compaction. Stop hl-bot before running; backups stay private."""

from contextlib import closing
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.learning.ledger import FillLedger
from src.research.journal import compact_observation


def compact(root):
    now = time.time()
    for name in ("ledger", "research"):
        path = root / "data" / f"{name}.sqlite"
        if not path.exists():
            continue
        backup = path.with_suffix(".pre-retention.sqlite")
        with closing(sqlite3.connect(path)) as db:
            if not backup.exists():
                target = sqlite3.connect(backup)
                try:
                    db.backup(target)
                finally:
                    target.close()
            if name == "research":
                rows = db.execute(
                    "SELECT time,raw FROM observations ORDER BY time"
                ).fetchall()
                kept = {}
                for timestamp, raw in rows:
                    if timestamp >= now - 7 * 86400:
                        bucket = timestamp // 60 * 60
                        kept.setdefault(
                            bucket, json.dumps(compact_observation(json.loads(raw)))
                        )
                db.execute("DELETE FROM observations")
                db.executemany("INSERT INTO observations VALUES (?,?)", kept.items())
            db.commit()
        if name == "ledger":
            FillLedger(path).compact_equity(now)
        db = sqlite3.connect(path)
        try:
            db.execute("VACUUM")
            db.execute("PRAGMA optimize")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError(f"Integrity check failed: {name}")
        finally:
            db.close()
        print(
            f"{name}: {path.stat().st_size} bytes; integrity OK; private pre-retention backup preserved"
        )


if __name__ == "__main__":
    compact(Path(__file__).resolve().parents[1])
