"""Read-only testnet funding synchronization, outside the trading/risk loop."""

import json
import math
import threading
import time
import requests
from src.storage import transaction


class FundingSync:
    def __init__(self, path, address, start_ms):
        self.path, self.address, self.start_ms = path, address, int(start_ms)
        self.stop_event = threading.Event()
        with transaction(path) as db:
            db.executescript(
                """CREATE TABLE IF NOT EXISTS funding(id TEXT PRIMARY KEY,time INTEGER,coin TEXT,usdc REAL,raw TEXT);
                CREATE TABLE IF NOT EXISTS funding_state(id INTEGER PRIMARY KEY,start_ms INTEGER,through_ms INTEGER,updated REAL,error TEXT);"""
            )
            db.execute(
                "INSERT OR IGNORE INTO funding_state VALUES (1,?,?,0,NULL)",
                (self.start_ms, self.start_ms),
            )

    def step(self, post, now):
        with transaction(self.path) as db:
            start, cursor = db.execute(
                "SELECT start_ms,through_ms FROM funding_state WHERE id=1"
            ).fetchone()
        end = min(int(now * 1000) - 30000, cursor + 86400000)
        if end <= cursor:
            return
        begin = max(start, cursor - 3600000)
        # Split capped windows rather than skipping other coins at a shared timestamp.
        for _ in range(20):
            rows = post(
                dict(
                    type="userFunding", user=self.address, startTime=begin, endTime=end
                )
            )
            if not isinstance(rows, list):
                raise ValueError("Malformed funding response")
            if len(rows) < 500:
                break
            end = (begin + end) // 2
            if end <= begin:
                raise ValueError("Funding timestamp exceeds response capacity")
        else:
            raise ValueError("Funding page capacity exceeded")
        if end <= cursor:
            raise ValueError("Funding pagination stalled; coverage not advanced")
        validated = []
        for row in rows:
            delta = row["delta"]
            stamp = int(row["time"])
            amount = float(delta["usdc"])
            if (
                delta["type"] != "funding"
                or not begin <= stamp <= end
                or not math.isfinite(amount)
            ):
                raise ValueError("Invalid funding row")
            ident = f"{stamp}:{delta['coin']}:{row.get('hash','')}"
            validated.append((ident, stamp, delta["coin"], amount, json.dumps(row)))
        with transaction(self.path) as db:
            db.executemany(
                "INSERT OR IGNORE INTO funding VALUES (?,?,?,?,?)", validated
            )
            db.execute(
                "UPDATE funding_state SET through_ms=?,updated=?,error=NULL WHERE id=1",
                (end, now),
            )

    def start(self):
        threading.Thread(
            target=self._run, name="testnet-funding-audit", daemon=True
        ).start()

    def _run(self):
        with requests.Session() as session:

            def post(payload):
                response = session.post(
                    "https://api.hyperliquid-testnet.xyz/info", json=payload, timeout=10
                )
                response.raise_for_status()
                return response.json()

            while not self.stop_event.is_set():
                try:
                    self.step(post, time.time())
                    with transaction(self.path) as db:
                        through = db.execute(
                            "SELECT through_ms FROM funding_state WHERE id=1"
                        ).fetchone()[0]
                    delay = 1 if through < time.time() * 1000 - 60000 else 300
                except Exception as exc:
                    with transaction(self.path) as db:
                        db.execute(
                            "UPDATE funding_state SET error=? WHERE id=1",
                            (type(exc).__name__,),
                        )
                    delay = 60
                self.stop_event.wait(delay)
