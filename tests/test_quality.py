import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.learning.quality import QualityAudit, candle_context, challenger
from src.learning.funding import FundingSync
from src.storage import transaction


def bars():
    return [
        dict(
            t=i * 60000,
            o=100 + i * 0.05,
            h=100.1 + i * 0.05,
            l=99.9 + i * 0.05,
            c=100.05 + i * 0.05,
        )
        for i in range(60)
    ]


def quote(now, source=None, mid=100):
    return dict(
        sampled_at=now,
        source_time=now if source is None else source,
        bid=mid - 0.01,
        ask=mid + 0.01,
        mid=mid,
    )


def fill(stamp, side, start, oid, price=100, pnl=0):
    return dict(
        time=stamp,
        coin="BTC",
        side=side,
        startPosition=str(start),
        sz="1",
        px=str(price),
        fee=".01",
        feeToken="USDC",
        closedPnl=str(pnl),
        oid=oid,
        tid=oid,
        crossed=False,
    )


class QualityTests(unittest.TestCase):
    def test_only_closed_contiguous_finite_candles(self):
        source = bars()
        self.assertEqual(candle_context(source, 3600)["regime"], "trend_up")
        # Future/forming bar never changes the closed context.
        self.assertEqual(
            candle_context(source + [dict(t=3600000, o=1, h=1, l=1, c=1)], 3600),
            candle_context(source, 3600),
        )
        for bad, now in [
            (source, 4000),
            (source[:-1], 3600),
            (source[:30] + source[31:], 3600),
            ([*source[:-1], dict(source[-1], c="NaN")], 3600),
        ]:
            with self.assertRaises(ValueError):
                candle_context(bad, now)

    def test_frozen_challenger_trend_range_and_cost_abstention(self):
        context = candle_context(bars(), 3600)
        self.assertEqual(challenger(context, 102.99, 103.01)[0], ("shadow_trend_v1", 1))
        context = dict(context, change_20m_bps=15)
        self.assertIsNone(challenger(context, 102.99, 103.01)[0])
        context = dict(regime="range", range_low=98, range_high=102)
        self.assertEqual(challenger(context, 98.49, 98.51)[0], ("shadow_range_v1", 1))
        self.assertIsNone(challenger(context, 99.99, 100.01)[0])
        self.assertIsNone(challenger(context, 97.79, 97.81)[0])
        self.assertIsNone(challenger(context, 98, 99)[0])

    def test_invalid_and_stale_quotes_rejected(self):
        for bid, ask, age in [
            ("NaN", "101", 1),
            ("101", "100", 1),
            ("100", "101", 11),
            ("100", "101", -1),
        ]:
            with self.assertRaises(ValueError):
                QualityAudit.quote(dict(bid={"px": bid}, ask={"px": ask}), age, 1000)

    def test_five_minute_opportunities_survive_restart_without_duplicate_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.sqlite"
            audit = QualityAudit(path)
            audit.tick(quote(3600, mid=103), bars())
            audit.tick(quote(3601, mid=103), bars())
            restarted = QualityAudit(path)
            restarted.tick(quote(3602, mid=103), bars())
            with audit.connect() as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0], 1
                )
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 3
                )
                self.assertEqual(
                    db.execute("SELECT DISTINCT regime FROM signals").fetchone()[0],
                    "trend_up",
                )

    def test_cached_quote_cannot_complete_future_fill_horizon_and_late_is_missed(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = QualityAudit(Path(directory) / "audit.sqlite")
            audit.fill(fill(1000000, "B", 0, 1))
            audit.tick(quote(1010, source=1009, mid=102), [])
            with audit.connect() as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM fill_marks").fetchone()[0], 0
                )
            audit.tick(quote(1011, mid=102), [])
            restarted = QualityAudit(audit.path)
            restarted.tick(quote(1075, mid=103), [])
            with audit.connect() as db:
                rows = db.execute(
                    "SELECT horizon,status,bps,source_time FROM fill_marks ORDER BY horizon"
                ).fetchall()
                self.assertEqual(
                    tuple(rows[0]), (10, "complete", 200.00000000000017, 1011)
                )
                self.assertEqual(tuple(rows[1]), (60, "missed", None, 1075))

    def test_exact_order_ids_attribution_cost_and_separate_funding(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = QualityAudit(Path(directory) / "audit.sqlite")
            signal = dict(coin="BTC", side="long", entry_price=100, sr_kind="support")
            ident = audit.decision(signal, {"regime": "range"}, quote(999), {})
            audit.result(
                ident,
                {
                    "response": {
                        "data": {
                            "statuses": [{"resting": {"oid": n}} for n in [1, 2, 3]]
                        }
                    }
                },
                "accepted",
            )
            rows = [fill(1000000, "B", 0, 1), fill(1060000, "A", 1, 3, 102, 2)]
            audit.fill(rows[0])
            audit.fill(rows[1])
            sync = FundingSync(audit.path, "public", 0)
            sync.step(
                lambda payload: [
                    dict(
                        time=1030000,
                        hash="x",
                        delta=dict(type="funding", coin="BTC", usdc=".5"),
                    )
                ],
                2000,
            )
            summary = audit.summary(rows)
            self.assertEqual(summary["groups"][0]["regime"], "range")
            self.assertEqual(summary["groups"][0]["exit_reason"], "stop_loss_order")
            self.assertEqual(summary["parents_with_any_fill"], 1)
            self.assertEqual(summary["execution"]["requested_deviation_bps"], 0)
            self.assertAlmostEqual(summary["recent"][0]["net_after_funding"], 2.48)
            self.assertEqual(summary["recent"][0]["funding_usdc"], 0.5)
            rows[0]["oid"] = 99
            self.assertEqual(audit.summary(rows)["groups"][0]["regime"], "unknown")

    def test_missing_funding_never_becomes_zero_or_historical_context_invented(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = QualityAudit(Path(directory) / "audit.sqlite")
            summary = audit.summary(
                [fill(1000000, "B", 0, 1), fill(1060000, "A", 1, 3, 102, 2)]
            )
            self.assertIsNone(summary["recent"][0]["funding_usdc"])
            self.assertEqual(summary["recent"][0]["regime"], "unknown")
            self.assertIsNone(summary["execution"]["decision_mid_cost_bps"])

    def test_invalid_context_abstains_and_invalid_fills_are_not_marked(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = QualityAudit(Path(directory) / "audit.sqlite")
            audit.tick(quote(3600), [])
            with audit.connect() as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 0
                )
                self.assertEqual(
                    db.execute("SELECT regime FROM opportunities").fetchone()[0],
                    "unavailable",
                )
            for price in ("NaN", "0"):
                with self.assertRaises(ValueError):
                    audit.fill(fill(1000000, "B", 0, 1, price=price))
            with audit.connect() as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM audit_fills").fetchone()[0], 0
                )

    def test_rejected_decisions_never_count_as_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = QualityAudit(Path(directory) / "audit.sqlite")
            ident = audit.decision(
                dict(coin="BTC", side="long", entry_price=100), None, quote(1000), {}
            )
            audit.result(ident, None, "Spread exceeds limit")
            summary = audit.summary([])
            self.assertEqual(summary["admitted"], 0)
            self.assertEqual(
                summary["recent_decisions"][0]["reason"], "Spread exceeds limit"
            )


class FundingTests(unittest.TestCase):
    def test_idempotent_funding_and_persistent_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.sqlite"
            sync = FundingSync(path, "public", 0)
            row = dict(
                time=1000,
                hash="abc",
                delta=dict(type="funding", coin="BTC", usdc="-.1"),
            )
            sync.step(lambda payload: [row], 100)
            FundingSync(path, "public", 999).step(lambda payload: [row], 200)
            with transaction(path) as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM funding").fetchone()[0], 1
                )
                self.assertEqual(
                    db.execute(
                        "SELECT start_ms,through_ms FROM funding_state"
                    ).fetchone(),
                    (0, 170000),
                )

    def test_malformed_funding_does_not_advance_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            sync = FundingSync(Path(directory) / "audit.sqlite", "public", 0)
            with self.assertRaises(ValueError):
                sync.step(
                    lambda payload: [
                        dict(
                            time=1000,
                            delta=dict(type="funding", coin="BTC", usdc="NaN"),
                        )
                    ],
                    100,
                )
            with transaction(sync.path) as db:
                self.assertEqual(
                    db.execute("SELECT through_ms FROM funding_state").fetchone()[0], 0
                )

    def test_capped_windows_split_without_timestamp_skips(self):
        with tempfile.TemporaryDirectory() as directory:
            sync = FundingSync(Path(directory) / "audit.sqlite", "public", 0)
            requests = []

            def post(payload):
                requests.append(payload)
                return [{}] * 500 if payload["endTime"] > 50000 else []

            sync.step(post, 100)
            self.assertEqual(len(requests), 2)
            self.assertEqual(requests[0]["startTime"], requests[1]["startTime"])
            with transaction(sync.path) as db:
                self.assertEqual(
                    db.execute("SELECT through_ms FROM funding_state").fetchone()[0],
                    35000,
                )


class ChronologicalReportTests(unittest.TestCase):
    def test_report_excludes_outcomes_after_cutoff_and_does_not_write(self):
        from scripts.quality_report import report

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.sqlite"
            audit = QualityAudit(path)
            audit.journal.signal("shadow_trend_v1", 1, quote(1000), "fixed")
            audit.journal.mark(quote(1010, mid=101))
            self.assertEqual(report(path, 0, 1009)["results"], [])
            results = report(path, 0, 1011)["results"]
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["n"], 1)
            self.assertIn("utc_week", results[0])
            missing = Path(directory) / "missing.sqlite"
            with self.assertRaises(Exception):
                report(missing)
            self.assertFalse(missing.exists())
