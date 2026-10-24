"""Durable exchange-fill journal; actual costs, no inferred round trips."""

import json
from src.storage import transaction
from .trades import complete_trades
import time
from pathlib import Path


class FillLedger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS fills (id TEXT PRIMARY KEY, time INTEGER, raw TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS equity (time INTEGER PRIMARY KEY, value REAL, peak REAL)"
            )

    def connect(self):
        return transaction(self.path, timeout=10)

    @staticmethod
    def identity(fill):
        return f"{fill.get('coin')}:{fill.get('tid', str(fill.get('oid')) + ':' + str(fill.get('time')) + ':' + str(fill.get('sz')))}"

    def add(self, fill):
        with self.connect() as db:
            result = db.execute(
                "INSERT OR IGNORE INTO fills VALUES (?, ?, ?)",
                (self.identity(fill), int(fill["time"]), json.dumps(fill)),
            )
            return result.rowcount == 1

    def fills(self, limit=2000):
        with self.connect() as db:
            rows = db.execute(
                "SELECT raw FROM fills ORDER BY time DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def sample_equity(self, value, peak):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO equity VALUES (?, ?, ?)",
                (int(time.time()), value, peak),
            )

    def equity(self, limit=3000):
        with self.connect() as db:
            rows = db.execute(
                "SELECT time,value,peak FROM equity ORDER BY time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            dict(
                time=t, value=v, peak=p, drawdown=max(0, (1 - v / p) * 100) if p else 0
            )
            for t, v, p in reversed(rows)
        ]

    def performance(self):
        # All ledger rows, not just the latest display window.
        with self.connect() as db:
            fills = [
                json.loads(r[0])
                for r in db.execute("SELECT raw FROM fills ORDER BY time")
            ]
        completed = complete_trades(fills)
        gross = sum(float(f.get("closedPnl", 0)) for f in fills)
        fees = sum(float(f.get("fee", 0)) for f in fills)
        exits = [
            f
            for f in fills
            if "Close" in f.get("dir", "") or float(f.get("closedPnl", 0)) != 0
        ]
        net_exits = [
            float(f.get("closedPnl", 0)) - float(f.get("fee", 0)) for f in exits
        ]
        wins = [p for p in net_exits if p > 0]
        losses = [p for p in net_exits if p < 0]
        return dict(
            complete_trades=dict(
                count=len(completed),
                gross_pnl=sum(t["gross_pnl"] for t in completed),
                fees=sum(t["fees"] for t in completed),
                net_pnl=sum(t["net_pnl"] for t in completed),
                expectancy=(
                    sum(t["net_pnl"] for t in completed) / len(completed)
                    if completed
                    else None
                ),
                recent=completed[-20:],
                scope="Only position-continuous flat-to-flat episodes; USDC fees included, funding excluded. Incomplete history excluded.",
            ),
            fill_count=len(fills),
            closing_fills=len(exits),
            gross_pnl=gross,
            fees=fees,
            net_pnl=gross - fees,
            funding_included=False,
            win_rate=len(wins) / len(exits) if exits else None,
            profit_factor=sum(wins) / abs(sum(losses)) if losses else None,
            expectancy=(gross - fees) / len(exits) if exits else None,
            notional=sum(float(f.get("px", 0)) * float(f.get("sz", 0)) for f in fills),
            first_time=fills[0]["time"] if fills else None,
            last_time=fills[-1]["time"] if fills else None,
            scope="Fill ledger since earliest imported exchange fill; partial fills are not trades",
        )
