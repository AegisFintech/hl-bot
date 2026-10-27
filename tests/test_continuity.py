import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from src.market.candles import merge_bars, coverage
from src.exchange.hyperliquid import HyperliquidClient
from src.operations import Operations


def bars(n=61):
    return [
        dict(t=(1000 + i) * 60000, o="100", h="102", l="99", c="101") for i in range(n)
    ]


class ContinuityTests(unittest.TestCase):
    def test_late_updates_merge_without_duplicate_or_reordering(self):
        rows = bars()
        update = dict(rows[-3], c="100.5")
        merged, rejected = merge_bars(rows, [update, rows[-1]])
        self.assertEqual(len(merged), 61)
        self.assertEqual(merged[-3]["c"], "100.5")
        self.assertEqual(rejected, 0)
        self.assertTrue(coverage(merged, 1061 * 60)["eligible"])

    def test_gap_staleness_and_invalid_ohlc_fail_closed(self):
        rows = bars()
        self.assertFalse(coverage(rows[:30] + rows[31:], 1061 * 60)["eligible"])
        self.assertFalse(coverage(rows, 1065 * 60)["eligible"])
        merged, n = merge_bars(rows, [dict(rows[-1], c="nan"), dict(rows[-1], l="103")])
        self.assertEqual(n, 2)
        self.assertEqual(len(merged), 61)

    def test_bounded_and_no_synthetic_bars(self):
        merged, _ = merge_bars([], bars(2200))
        self.assertEqual(len(merged), 2000)
        merged, _ = merge_bars([], bars()[:5] + bars()[6:])
        self.assertEqual(len(merged), 60)
        self.assertNotIn(bars()[5], merged)

    def client(self):
        c = HyperliquidClient.__new__(HyperliquidClient)
        c._lock = threading.Lock()
        c._candles = {}
        c._candle_health = {}
        return c

    def test_rest_cannot_overwrite_newer_forming_websocket_candle(self):
        c = self.client()
        rows = bars()
        c.merge_candles("BTC", rows)
        c.merge_candles(
            "BTC",
            [dict(rows[-1], c="99.5")],
            source="rest",
            requested_at=1060 * 60 + 30,
        )
        self.assertEqual(c.get_cached_candles("BTC")[-1]["c"], "101")

    def test_rejected_update_requires_repair_before_eligibility(self):
        c = self.client()
        rows = bars()
        c.merge_candles("BTC", rows)
        c.merge_candles("BTC", [dict(rows[-1], h="nan")])
        with patch("src.exchange.hyperliquid.time.time", return_value=1061 * 60):
            self.assertFalse(c.candle_health("BTC")["eligible"])
            c.merge_candles("BTC", rows, source="rest")
            self.assertTrue(c.candle_health("BTC")["eligible"])
            self.assertEqual(c.candle_health("BTC")["rejected_updates"], 1)

    def test_heartbeat_incident_boundaries_and_stalled_detection(self):
        with tempfile.TemporaryDirectory() as d:
            o = Operations(Path(d) / "ops.sqlite")
            o.record("running", now=1000)
            o.record("recovering", "network", now=1010)
            o.record("recovering", "network", now=1020)
            o.record("running", now=1040)
            summary = o.summary(now=1050)
            self.assertTrue(summary["responsive"])
            self.assertEqual(len(summary["incidents"]), 1)
            self.assertEqual(summary["incidents"][0]["end"], 1040)
            self.assertFalse(o.summary(now=1200)["responsive"])

    def test_restart_retains_incident_and_marks_observation_gap(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ops.sqlite"
            o = Operations(path)
            o.record("recovering", "network", now=1000)
            with patch("src.operations.time.time", return_value=1200):
                o = Operations(path)
            incidents = o.summary(now=1200)["incidents"]
            self.assertEqual(len(incidents), 2)
            self.assertEqual(incidents[0]["kind"], "observation_gap")
            o.record("running", now=1210)
            self.assertTrue(
                all(i["end"] is not None for i in o.summary(now=1210)["incidents"])
            )

    def test_integrity_is_rechecked_after_slow_account_admission(self):
        from types import SimpleNamespace
        from src.strategy.scalper import Scalper

        s = Scalper.__new__(Scalper)
        s.client = Mock()
        s.risk = Mock()
        s.coin = "BTC"
        s.diagnostics = {}
        s._is_level_on_cooldown = lambda level: False
        s._has_open_order_near = lambda price: False
        s.fee_entry = 0.0002
        s.fee_exit = 0.0005
        s.client.candle_health.side_effect = [{"eligible": True}, {"eligible": False}]
        s.client.get_cached_bbo.return_value = {
            "bid": {"px": "100"},
            "ask": {"px": "100.01"},
        }
        s.client.bbo_age.return_value = 1
        s.client.get_positions.return_value = []
        s.client.get_open_orders.return_value = []
        s.client.get_account_value.return_value = 1000
        signal = SimpleNamespace(
            sr_level=100, entry_price=100, side="long", tp_price=101, sl_price=99.7
        )
        self.assertIsNone(s.execute_signal(signal))
        s.risk.compute_position_size.assert_not_called()
        s.client.place_order_with_tpsl.assert_not_called()
        self.assertIn("expired", s.diagnostics["reason"])
