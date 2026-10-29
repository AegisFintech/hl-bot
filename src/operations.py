"""Durable incident boundaries and bounded heartbeat state; no exchange actions."""

import time
from pathlib import Path
from src.storage import transaction


class Operations:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._last_write = 0
        with transaction(self.path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS heartbeat(id INTEGER PRIMARY KEY CHECK(id=1),time REAL,state TEXT,reason TEXT);
                CREATE TABLE IF NOT EXISTS incidents(id INTEGER PRIMARY KEY,start REAL,end REAL,kind TEXT,reason TEXT);
                CREATE INDEX IF NOT EXISTS incident_start ON incidents(start);
            """)
            previous = db.execute("SELECT time FROM heartbeat WHERE id=1").fetchone()
            now = time.time()
            if previous and now - previous[0] > 120:
                db.execute(
                    "INSERT INTO incidents(start,end,kind,reason) VALUES (?,?,?,?)",
                    (
                        previous[0],
                        now,
                        "observation_gap",
                        "No persisted loop heartbeat; duration is an observation gap, not measured downtime",
                    ),
                )

    def record(self, state, reason="", now=None):
        now = time.time() if now is None else now
        with transaction(self.path) as db:
            old = db.execute("SELECT state,reason FROM heartbeat WHERE id=1").fetchone()
            changed = old != (state, reason)
            if changed:
                db.execute(
                    "UPDATE incidents SET end=? WHERE end IS NULL AND kind='engine'",
                    (now,),
                )
                if state != "running":
                    db.execute(
                        "INSERT INTO incidents(start,kind,reason) VALUES (?,?,?)",
                        (now, "engine", state + ": " + reason),
                    )
            if changed or now - self._last_write >= 15:
                db.execute(
                    "INSERT OR REPLACE INTO heartbeat VALUES (1,?,?,?)",
                    (now, state, reason),
                )
                self._last_write = now

    def summary(self, now=None):
        now = time.time() if now is None else now
        with transaction(self.path, rows=True) as db:
            row = db.execute("SELECT * FROM heartbeat WHERE id=1").fetchone()
            incidents = [
                dict(r)
                for r in db.execute("SELECT * FROM incidents ORDER BY id DESC LIMIT 20")
            ]
        heartbeat = dict(row) if row else {}
        age = now - heartbeat["time"] if heartbeat else None
        return dict(
            heartbeat_age_s=age,
            responsive=age is not None and 0 <= age <= 120,
            heartbeat=heartbeat,
            incidents=incidents,
            scope="Persisted loop completion heartbeat; HTTP availability alone does not prove execution progress. Observation gaps are not exact outage durations.",
        )
