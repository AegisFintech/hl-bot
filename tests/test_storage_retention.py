import logging
import tempfile
import unittest
from pathlib import Path

from src.learning.ledger import FillLedger
from src.logging_setup import file_handler
from src.research.journal import ResearchJournal


class RetentionTests(unittest.TestCase):
    def test_equity_keeps_extremes_peak_last_recent_and_fills(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = FillLedger(Path(directory) / "ledger.sqlite")
            now = 40 * 86400
            with ledger.connect() as db:
                db.executemany(
                    "INSERT INTO equity VALUES (?,?,?)",
                    [
                        (10, 100, 100),
                        (20, 90, 100),
                        (30, 95, 120),
                        (40, 110, 110),
                        (50, 105, 110),
                        (60, 103, 110),
                        (now - 1, 99, 120),
                    ],
                )
                db.execute("INSERT INTO fills VALUES ('important',1,'{}')")
            ledger.compact_equity(now)
            ledger.compact_equity(now)
            with ledger.connect() as db:
                self.assertEqual(
                    [r[0] for r in db.execute("SELECT time FROM equity ORDER BY time")],
                    [20, 30, 40, 60, now - 1],
                )
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM fills").fetchone()[0], 1
                )

    def test_observations_bounded_compact_and_learning_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = ResearchJournal(Path(directory) / "research.sqlite")
            sample = dict(
                sampled_at=1000,
                source_time=999,
                bid=99,
                ask=101,
                mid=100,
                heatmap=["large"],
                large_trades=["large"],
                walls=["large"],
            )
            journal.signal("test", 1, sample, "preserve")
            journal.wallet_changes("public", [{"coin": "BTC", "szi": "1"}], 1000)
            journal.observe(sample)
            journal.observe(dict(sample, sampled_at=1001))
            with journal.connect() as db:
                rows = db.execute("SELECT raw FROM observations").fetchall()
                self.assertEqual(len(rows), 1)
                self.assertNotIn("large", rows[0][0])
            journal.observe(dict(sample, sampled_at=1000 + 8 * 86400))
            with journal.connect() as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 1
                )
                self.assertEqual(
                    db.execute("SELECT reason FROM signals").fetchone()[0], "preserve"
                )
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM wallet_positions").fetchone()[0], 1
                )

    def test_log_handler_reopens_after_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bot.log"
            handler = file_handler(path)
            record = logging.LogRecord("test", logging.INFO, "", 0, "before", (), None)
            handler.handle(record)
            path.rename(path.with_suffix(".old"))
            record.msg = "after"
            handler.handle(record)
            handler.close()
            self.assertEqual(path.read_text().strip(), "after")
            self.assertEqual(path.with_suffix(".old").read_text().strip(), "before")
