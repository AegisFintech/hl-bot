"""Prospective confirmation, missing-data gates and upgrade compatibility."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.research.experiments import ExperimentEngine, EXPERIMENTS
from src.research.journal import ResearchJournal, HORIZONS


def market(now=1000, mid=100, **extra):
    return (
        dict(
            sampled_at=now,
            source_time=now,
            mid=mid,
            bid=mid - 0.01,
            ask=mid + 0.01,
            flow={"complete": True},
            walls=[],
            large_trades=[],
            absorption=None,
        )
        | extra
    )


class ExperimentTests(unittest.TestCase):
    def test_failed_aggression_requires_later_reversal_and_deduplicates_print(self):
        engine = ExperimentEngine()
        print_ = dict(id="1", side="B", time=1000)
        self.assertEqual(
            engine.evaluate(market(absorption="bearish", large_trades=[print_])), []
        )
        events = engine.evaluate(
            market(1005, 99.97, absorption="bearish", large_trades=[print_])
        )
        self.assertEqual(
            [(e["kind"], e["direction"]) for e in events], [("failed_aggression", -1)]
        )
        self.assertEqual(engine.evaluate(market(1010, 99.96)), [])

    def test_gap_or_incomplete_flow_discards_armed_event(self):
        for next_market in (
            market(1020, 99.97),
            market(1005, 99.97, flow={"complete": False}),
        ):
            engine = ExperimentEngine()
            engine.evaluate(
                market(
                    absorption="bearish",
                    large_trades=[dict(id="1", side="B", time=1000)],
                )
            )
            self.assertEqual(engine.evaluate(next_market), [])

    def test_wall_defense_requires_execution_refill_and_remaining_wall(self):
        wall = dict(
            side="bid",
            price=99.99,
            persistence_s=30,
            traded_at_level_usd=25000,
            observed_refill_usd=12500,
        )
        engine = ExperimentEngine()
        self.assertEqual(engine.evaluate(market(walls=[wall])), [])
        events = engine.evaluate(market(1005, 100.03, walls=[wall]))
        self.assertEqual(events[0]["kind"], "wall_defense")
        engine = ExperimentEngine()
        engine.evaluate(market(walls=[wall]))
        self.assertEqual(engine.evaluate(market(1005, 100.03)), [])

    def test_expiry_and_nonconfirmation_never_emit(self):
        engine = ExperimentEngine()
        engine.evaluate(
            market(
                absorption="bearish", large_trades=[dict(id="1", side="B", time=1000)]
            )
        )
        for now in range(1005, 1131, 5):
            self.assertEqual(engine.evaluate(market(now, 100.01)), [])
        self.assertFalse(engine.pending)

    def test_crowded_failure_requires_oi_growth_excursion_and_later_failure(self):
        engine = ExperimentEngine()

        def context(now, oi):
            return dict(
                updated_at=now, value=dict(funding_hourly=0.0002, open_interest_btc=oi)
            )

        engine.evaluate(market(), context(1000, 100))
        for now in range(1005, 1301, 5):
            engine.evaluate(market(now), context(now, 100))
        self.assertEqual(engine.evaluate(market(1305, 100.06), context(1305, 101)), [])
        events = engine.evaluate(market(1310, 99.99), context(1310, 101))
        self.assertEqual(events[0]["kind"], "crowded_failure")
        self.assertEqual(events[0]["direction"], -1)

    def test_catalog_discloses_unavailable_dependencies(self):
        self.assertEqual(len(EXPERIMENTS), 9)
        self.assertIn(
            "blocked",
            next(e for e in EXPERIMENTS if e["id"] == "liquidation_aftershock")[
                "status"
            ],
        )


class JournalUpgradeTests(unittest.TestCase):
    def test_legacy_horizons_preserved_and_new_events_get_long_horizons(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research.sqlite"
            with sqlite3.connect(path) as db:
                db.execute(
                    """CREATE TABLE signals(id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE,
                    time REAL, kind TEXT, direction INTEGER, bid REAL, ask REAL, mid REAL,
                    funding REAL, reason TEXT, favorable REAL DEFAULT 0, adverse REAL DEFAULT 0)"""
                )
                db.execute(
                    "INSERT INTO signals(fingerprint,time,kind,direction,bid,ask,mid) VALUES ('old',1000,'baseline',1,99.99,100.01,100)"
                )
            journal = ResearchJournal(path)
            journal.signal("book_flow", 1, market(1005), "new")
            with journal.connect() as db:
                rows = db.execute("SELECT horizons FROM signals ORDER BY id").fetchall()
            self.assertEqual(json.loads(rows[0][0]), [10, 60, 300, 900])
            self.assertEqual(tuple(json.loads(rows[1][0])), HORIZONS)
            journal.mark(market(15405))
            with journal.connect() as db:
                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM outcomes WHERE signal_id=1"
                    ).fetchone()[0],
                    4,
                )
                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM outcomes WHERE signal_id=2"
                    ).fetchone()[0],
                    7,
                )

    def test_cost_attribution_nonoverlap_and_no_automatic_promotion(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = ResearchJournal(Path(directory) / "research.sqlite")
            for now in (1000, 1060, 1120):
                journal.signal("book_flow", 1, market(now), "test")
                journal.mark(market(now + 10))
            rows = journal.summary()["results"]
            row = next(r for r in rows if r["horizon"] == 10)
            self.assertEqual(row["n"], 3)
            self.assertEqual(row["nonoverlap_n"], 3)
            self.assertGreater(row["mean_cost_drag_bps"], 13)
            self.assertEqual(row["review_status"], "insufficient evidence")
            self.assertIsNone(row["unconditional_delta_bps"])

    def test_matched_comparison_requires_same_hour_regime_and_direction(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = ResearchJournal(Path(directory) / "research.sqlite")
            sample = market(1000, change_60s_bps=3)
            journal.signal("baseline", 1, sample, "control", funding=0.0002)
            journal.signal("book_flow", 1, sample, "candidate", funding=0.0002)
            journal.signal("wall_defense", -1, sample, "opposite", funding=0.0002)
            journal.mark(market(1010, 100.1))
            results = journal.summary()["results"]
            candidate = next(r for r in results if r["kind"] == "book_flow")
            self.assertEqual(candidate["matched_n"], 1)
            self.assertAlmostEqual(candidate["matched_delta_bps"], 0)
            opposite = next(r for r in results if r["kind"] == "wall_defense")
            self.assertEqual(opposite["matched_n"], 0)
            self.assertIsNone(opposite["matched_delta_bps"])

    def test_nonoverlapping_count_does_not_count_every_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = ResearchJournal(Path(directory) / "research.sqlite")
            journal.signal("book_flow", 1, market(1000), "one")
            journal.signal("book_flow", 1, market(1060), "two")
            journal.mark(market(1300))
            journal.mark(market(1360))
            row = next(r for r in journal.summary()["results"] if r["horizon"] == 300)
            self.assertEqual(row["n"], 2)
            self.assertEqual(row["nonoverlap_n"], 1)


if __name__ == "__main__":
    unittest.main()
