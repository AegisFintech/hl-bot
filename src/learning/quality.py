"""Prospective testnet audit and fixed quote challengers. No exchange access or orders."""

from bisect import bisect_left, bisect_right
import json
import math
import time
import uuid
from pathlib import Path

from src.learning.trades import complete_trades
from src.research.journal import ResearchJournal
from src.storage import transaction

VERSION = "quality-v1"


def candle_context(candles, now):
    """Closed, contiguous one-minute bars only; thresholds frozen before collection."""
    bars = sorted(
        {int(c["t"]): c for c in candles if int(c["t"]) + 60000 <= now * 1000}.values(),
        key=lambda c: int(c["t"]),
    )[-60:]
    if len(bars) < 60 or not 0 <= now - (int(bars[-1]["t"]) / 1000 + 60) <= 120:
        raise ValueError("Closed candles stale or insufficient")
    if any(int(b["t"]) - int(a["t"]) != 60000 for a, b in zip(bars, bars[1:])):
        raise ValueError("Candle gap")
    for b in bars:
        o, h, l, c = [float(b[k]) for k in ("o", "h", "l", "c")]
        if (
            not all(math.isfinite(v) and v > 0 for v in (o, h, l, c))
            or not l <= min(o, c) <= max(o, c) <= h
        ):
            raise ValueError("Malformed candle")
    closes = [float(b["c"]) for b in bars[-21:]]
    displacement = closes[-1] - closes[0]
    path = sum(abs(b - a) for a, b in zip(closes, closes[1:]))
    efficiency = abs(displacement) / path if path else 0
    change = displacement / closes[0] * 10000
    prior = bars[-21:-1]
    low, high = min(float(b["l"]) for b in prior), max(float(b["h"]) for b in prior)
    width = (high - low) / closes[-1] * 10000
    regime = (
        ("trend_up" if change > 0 else "trend_down")
        if efficiency >= 0.35 and abs(change) >= 10
        else "range" if efficiency <= 0.20 and width >= 20 else "transition"
    )
    return dict(
        regime=regime,
        efficiency=efficiency,
        change_20m_bps=change,
        range_low=low,
        range_high=high,
        range_width_bps=width,
        last_close=closes[-1],
        last_open=float(bars[-1]["o"]),
        candle_time=int(bars[-1]["t"]) / 1000,
    )


def challenger(context, bid, ask):
    """V1 heuristic movement budget is NOT a fitted expected return."""
    mid = (bid + ask) / 2
    spread = (ask - bid) / mid * 10000
    if spread > 5:
        return None, "Spread exceeds 5bps", None
    regime = context["regime"]
    direction = 0
    if regime.startswith("trend_"):
        direction = 1 if regime == "trend_up" else -1
        if direction * (context["last_close"] - context["last_open"]) <= 0:
            return None, "Trend candle has no continuation confirmation", None
        budget = abs(context["change_20m_bps"])
        kind = "shadow_trend_v1"
    elif regime == "range":
        width = context["range_high"] - context["range_low"]
        location = (mid - context["range_low"]) / width if width else 0.5
        if not 0 <= location <= 1:
            return None, "Price outside trailing range", None
        direction = 1 if location <= 0.2 else -1 if location >= 0.8 else 0
        if not direction:
            return None, "Price away from range edges", None
        budget = (
            abs((context["range_high"] + context["range_low"]) / 2 - mid) / mid * 10000
        )
        kind = "shadow_range_v1"
    else:
        return None, "Transition regime", None
    if budget < 2 * (13 + spread):
        return None, "Heuristic movement budget below twice assumed costs", budget
    return (kind, direction), "Quote hypothesis admitted; no order", budget


class QualityAudit:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.journal = ResearchJournal(path)
        self.last_bucket = None
        self._last_mark = None
        self.last_quote_at = None
        with self.connect() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY,time REAL,coin TEXT,raw TEXT,result TEXT);
              CREATE TABLE IF NOT EXISTS audit_fills(id TEXT PRIMARY KEY,time REAL,coin TEXT,raw TEXT,arrival_quote TEXT);
              CREATE TABLE IF NOT EXISTS fill_marks(fill_id TEXT,horizon INTEGER,status TEXT,measured_at REAL,bps REAL,source_time REAL,PRIMARY KEY(fill_id,horizon));
              CREATE TABLE IF NOT EXISTS opportunities(bucket INTEGER PRIMARY KEY,regime TEXT,reason TEXT,budget REAL);
              CREATE TABLE IF NOT EXISTS audit_meta(key TEXT PRIMARY KEY,value TEXT);
              CREATE INDEX IF NOT EXISTS audit_fill_time ON audit_fills(time);
            """)
            columns = {r[1] for r in db.execute("PRAGMA table_info(fill_marks)")}
            if "source_time" not in columns:
                db.execute("ALTER TABLE fill_marks ADD COLUMN source_time REAL")
            db.execute(
                "INSERT OR IGNORE INTO audit_meta VALUES (?,?)",
                ("started_at", str(time.time())),
            )

    def connect(self):
        return transaction(self.path, rows=True)

    @staticmethod
    def quote(bbo, age, now):
        bid, ask = float(bbo["bid"]["px"]), float(bbo["ask"]["px"])
        if (
            not all(math.isfinite(v) for v in (bid, ask, age, now))
            or not 0 <= age <= 10
            or not 0 < bid < ask
        ):
            raise ValueError("Stale or malformed quote")
        return dict(
            sampled_at=now,
            source_time=now - age,
            time_basis="local_ws_receipt",
            bid=bid,
            ask=ask,
            mid=(bid + ask) / 2,
        )

    def decision(self, signal, context, quote, diagnostics):
        ident = uuid.uuid4().hex
        raw = dict(
            version=VERSION,
            signal=signal,
            context=context,
            quote=quote,
            diagnostics=dict(diagnostics),
        )
        with self.connect() as db:
            db.execute(
                "INSERT INTO decisions VALUES (?,?,?,?,NULL)",
                (ident, time.time(), signal["coin"], json.dumps(raw)),
            )
        return ident

    def result(self, ident, result, reason):
        with self.connect() as db:
            db.execute(
                "UPDATE decisions SET result=? WHERE id=?",
                (json.dumps(dict(response=result, reason=reason)), ident),
            )

    def fill(self, fill, quote=None):
        # Called only for newly received fills; historical imports never receive fabricated quotes.
        from .ledger import FillLedger

        price = float(fill["px"])
        if (
            not math.isfinite(price)
            or price <= 0
            or fill["side"] not in ("A", "B")
            or int(fill["time"]) <= 0
        ):
            raise ValueError("Malformed audit fill")
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO audit_fills VALUES (?,?,?,?,?)",
                (
                    FillLedger.identity(fill),
                    int(fill["time"]) / 1000,
                    fill["coin"],
                    json.dumps(fill),
                    json.dumps(quote) if quote else None,
                ),
            )

    def tick(self, quote, candles, coin="BTC"):
        now = quote["sampled_at"]
        # One observation per received quote, at most once a second. Reused cache is not new evidence.
        if self._last_mark is not None and quote["source_time"] <= self._last_mark:
            return
        self._last_mark = quote["source_time"]
        # Horizon completion uses local websocket receipt time, not cache-read time.
        self.journal.mark(dict(quote, sampled_at=quote["source_time"]))
        with self.connect() as db:
            rows = db.execute(
                """SELECT f.* FROM audit_fills f WHERE
                (SELECT COUNT(*) FROM fill_marks m WHERE m.fill_id=f.id)<3"""
            ).fetchall()
            for row in rows:
                fill = json.loads(row["raw"])
                direction = 1 if fill["side"] == "B" else -1
                for horizon in (10, 60, 300):
                    elapsed = now - row["time"]
                    if elapsed < horizon:
                        continue
                    # A cached pre-horizon quote must never stand in for a forward observation.
                    late = (
                        elapsed > horizon + 10
                        or quote["source_time"] < row["time"] + horizon
                    )
                    if (
                        quote["source_time"] < row["time"] + horizon
                        and elapsed <= horizon + 10
                    ):
                        continue
                    value = (
                        None
                        if late
                        else direction * (quote["mid"] / float(fill["px"]) - 1) * 10000
                    )
                    db.execute(
                        "INSERT OR IGNORE INTO fill_marks VALUES (?,?,?,?,?,?)",
                        (
                            row["id"],
                            horizon,
                            "missed" if late else "complete",
                            now,
                            value,
                            quote["source_time"],
                        ),
                    )
        self.last_quote_at = now
        bucket = int(now // 300) * 300
        if bucket == self.last_bucket:
            return
        try:
            context = candle_context(candles, now)
            event, reason, budget = challenger(context, quote["bid"], quote["ask"])
        except (ValueError, TypeError, KeyError, OverflowError):
            context = dict(regime="unavailable")
            event, reason, budget = None, "Closed candle context unavailable", None
        # Immutable opportunity denominator; no re-evaluation inside a five-minute window/restart.
        with self.connect() as db:
            inserted = db.execute(
                "INSERT OR IGNORE INTO opportunities VALUES (?,?,?,?)",
                (bucket, context["regime"], reason, budget),
            ).rowcount
        self.last_bucket = bucket
        if not inserted or context["regime"] == "unavailable":
            return
        snapshot = dict(quote)
        for direction in (1, -1):
            self.journal.signal(
                "baseline",
                direction,
                snapshot,
                "Fixed five-minute testnet control; " + VERSION,
                regime=context["regime"],
            )
        if event:
            self.journal.signal(
                event[0],
                event[1],
                snapshot,
                f"{VERSION}; {context['regime']}; heuristic budget {budget:.2f}bps, not expected return",
                regime=context["regime"],
            )

    @staticmethod
    def order_ids(result):
        statuses = (
            (result or {}).get("response", {}).get("data", {}).get("statuses", [])
        )
        ids = []
        for status in statuses:
            value = (
                status.get("resting", status.get("filled", {}))
                if isinstance(status, dict)
                else {}
            )
            ids.append(str(value["oid"]) if "oid" in value else None)
        return ids

    def summary(self, ledger_fills, order_links=()):
        with self.connect() as db:
            decisions = [
                dict(r) for r in db.execute("SELECT * FROM decisions ORDER BY time")
            ]
            marks = [dict(r) for r in db.execute("SELECT * FROM fill_marks")]
            fill_rows = {
                r["id"]: dict(r) for r in db.execute("SELECT * FROM audit_fills")
            }
            opportunities = [
                dict(r)
                for r in db.execute(
                    "SELECT regime,reason,COUNT(*) n FROM opportunities GROUP BY regime,reason"
                )
            ]
            funding = []
            funding_state = None
            if db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='funding_state'"
            ).fetchone():
                row = db.execute("SELECT * FROM funding_state WHERE id=1").fetchone()
                funding_state = dict(row) if row else None
                funding = [
                    dict(r) for r in db.execute("SELECT time,coin,usdc FROM funding")
                ]
            started = float(
                db.execute(
                    "SELECT value FROM audit_meta WHERE key='started_at'"
                ).fetchone()[0]
            )
        by_order = {}
        admitted = 0
        for decision in decisions:
            decision["raw"] = json.loads(decision["raw"])
            decision["result"] = (
                json.loads(decision["result"]) if decision["result"] else {}
            )
            ids = self.order_ids(decision["result"].get("response"))
            if len(ids) == 3 and ids[0]:
                admitted += 1
                for index, oid in enumerate(ids):
                    if oid:
                        by_order[(decision["coin"], oid)] = (
                            decision,
                            ("entry", "take_profit_order", "stop_loss_order")[index],
                        )
        # Recovered/emergency exits have their own exact returned IDs; never infer a parent.
        for link in order_links:
            by_order.setdefault((link['coin'], str(link['oid'])),
                                ({'raw': {'signal': {}, 'context': {}}}, link['role']))
        # Every fill joins by exchange order ID; never nearest price or inferred exit geometry.
        grouped = {}
        recent = []
        coin_fills = {}
        for fill in sorted(ledger_fills, key=lambda f: int(f["time"])):
            coin_fills.setdefault(fill["coin"], []).append(fill)
        times = {
            coin: [int(f["time"]) for f in rows] for coin, rows in coin_fills.items()
        }
        for trade in complete_trades(ledger_fills):
            stamps = times[trade["coin"]]
            fills = coin_fills[trade["coin"]][
                bisect_left(stamps, trade["opened_at"]) : bisect_right(
                    stamps, trade["closed_at"]
                )
            ]
            first, last = fills[0], fills[-1]
            match = by_order.get((first["coin"], str(first.get("oid"))))
            exit_match = by_order.get((last["coin"], str(last.get("oid"))))
            context = (match[0]["raw"].get("context") or {}) if match else {}
            regime = context.get("regime", "unknown")
            setup = (
                ("long" if first.get("side") == "B" else "short")
                + " / "
                + (
                    match[0]["raw"]["signal"].get("sr_kind", "unknown")
                    if match
                    else "unknown"
                )
            )
            exit_reason = (
                exit_match[1]
                if exit_match and exit_match[1] != "entry"
                else "unattributed"
            )
            key = (regime, setup, exit_reason)
            group = grouped.setdefault(
                key,
                dict(
                    regime=regime,
                    setup=setup,
                    exit_reason=exit_reason,
                    count=0,
                    gross_pnl=0,
                    fees=0,
                    net_pnl=0,
                ),
            )
            for field in ("gross_pnl", "fees", "net_pnl"):
                group[field] += trade[field]
            group["count"] += 1
            covered = bool(
                funding_state
                and funding_state["start_ms"] <= trade["opened_at"]
                and funding_state["through_ms"] >= trade["closed_at"]
            )
            payment = (
                sum(
                    f["usdc"]
                    for f in funding
                    if f["coin"] == trade["coin"]
                    and trade["opened_at"] <= f["time"] < trade["closed_at"]
                )
                if covered
                else None
            )
            recent.append(
                dict(
                    trade,
                    regime=regime,
                    setup=setup,
                    exit_reason=exit_reason,
                    funding_usdc=payment,
                    net_after_funding=(
                        trade["net_pnl"] + payment if payment is not None else None
                    ),
                )
            )
        mark_summary = []
        for horizon in (10, 60, 300):
            for role in ("entry", "exit", "unattributed"):
                selected = []
                missed = 0
                for mark in marks:
                    if mark["horizon"] != horizon:
                        continue
                    fill = json.loads(fill_rows[mark["fill_id"]]["raw"])
                    link = by_order.get((fill["coin"], str(fill.get("oid"))))
                    actual_role = (
                        ("entry" if link[1] == "entry" else "exit")
                        if link
                        else "unattributed"
                    )
                    if role != actual_role:
                        continue
                    if mark["status"] == "complete":
                        selected.append(mark["bps"])
                    else:
                        missed += 1
                mark_summary.append(
                    dict(
                        horizon=horizon,
                        role=role,
                        n=len(selected),
                        missed=missed,
                        mean_bps=sum(selected) / len(selected) if selected else None,
                    )
                )
        execution = []
        for fill in ledger_fills:
            match = by_order.get((fill["coin"], str(fill.get("oid"))))
            if not match or match[1] != "entry":
                continue
            decision = match[0]["raw"]
            quote = decision.get("quote")
            if not quote:
                continue
            if quote["sampled_at"] * 1000 > int(fill["time"]):
                continue
            direction = 1 if fill["side"] == "B" else -1
            execution.append(
                dict(
                    requested_deviation_bps=direction
                    * (float(fill["px"]) / float(decision["signal"]["entry_price"]) - 1)
                    * 10000,
                    decision_mid_cost_bps=direction
                    * (float(fill["px"]) / quote["mid"] - 1)
                    * 10000,
                    maker=fill.get("crossed") is False,
                )
            )
        execution_summary = dict(
            n=len(execution),
            maker_fills=sum(e["maker"] for e in execution),
            requested_deviation_bps=(
                sum(e["requested_deviation_bps"] for e in execution) / len(execution)
                if execution
                else None
            ),
            decision_mid_cost_bps=(
                sum(e["decision_mid_cost_bps"] for e in execution) / len(execution)
                if execution
                else None
            ),
        )
        filled_ids = {str(f.get("oid")) for f in ledger_fills}
        filled_parents = sum(
            bool(
                self.order_ids(d["result"].get("response"))
                and self.order_ids(d["result"].get("response"))[0] in filled_ids
            )
            for d in decisions
        )
        journal = self.journal.summary()
        journal["model"] = (
            "Testnet bid/ask quote markouts minus 9bps round-trip taker fees and 4bps slippage; funding omitted. Not fills or portfolio returns."
        )
        journal["baseline_note"] = (
            "Descriptive same-UTC-hour, direction and frozen trend/range regime controls. Pools may be reused and include later observations; no causal claim. Non-overlapping windows are not independent."
        )
        return dict(
            status=(
                "observing"
                if self.last_quote_at and time.time() - self.last_quote_at <= 15
                else "stale"
            ),
            quote_age_s=(
                time.time() - self.last_quote_at if self.last_quote_at else None
            ),
            version=VERSION,
            network="testnet",
            started_at=started,
            decisions=len(decisions),
            admitted=admitted,
            parents_with_any_fill=filled_parents,
            groups=list(grouped.values()),
            recent=recent[-20:],
            markouts=mark_summary,
            opportunities=opportunities,
            challenger=journal,
            execution=execution_summary,
            funding_state=funding_state,
            funding_usdc=sum(f["usdc"] for f in funding),
            recent_decisions=[
                dict(
                    time=d["time"],
                    reason=d["result"].get("reason", "Result unavailable"),
                    regime=(d["raw"].get("context") or {}).get("regime", "unknown"),
                    side=d["raw"]["signal"]["side"],
                )
                for d in decisions[-10:]
            ],
            scope="Prospective testnet audit. Historical setup/regime/exit attribution remains unknown. Order-ID joins only. Fill markouts are signed mid vs fill price, not P&L; entry and exit fills separated. Partial fills are correlated. Episode net excludes funding; separate net-after-funding requires complete synchronized coverage. Funding uses [open,close) timestamps; same-millisecond fill/funding ordering is unresolved. Decision-mid cost includes price movement during queue wait; it is not pure slippage. Challenger quotes assume 13bps round-trip fees/slippage plus quoted spread, funding omitted; not passive fills. Timestamps use local websocket receipt, not guaranteed exchange event ordering. No promotion or fitting.",
        )
