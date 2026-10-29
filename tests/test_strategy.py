"""Strategy library, causal indicators and the live closed-bar engine."""
import json
import math
import random
import tempfile
import unittest
from pathlib import Path

from src.strategy import indicators as ind
from src.strategy.engine import StrategyEngine, latest_closed_open, validate
from src.strategy.library import (Bars, Decision, DonchianBreakout, EmaTrend, Position, RsiReversion,
                                  TimeSeriesMomentum, advance, build, tighten)

HOUR = 3_600_000


def candles(closes, start=1_700_000_000_000 - 1_700_000_000_000 % HOUR, spread=0.002, step=HOUR):
    out = []
    for k, close in enumerate(closes):
        open_ = closes[k - 1] if k else close
        out.append(dict(t=start + k * step, o=open_, h=max(open_, close) * (1 + spread),
                        l=min(open_, close) * (1 - spread), c=close, v=1))
    return out


class IndicatorTests(unittest.TestCase):
    def test_channels_match_brute_force_and_exclude_current_bar(self):
        rnd = random.Random(3)
        values = [rnd.random() for _ in range(200)]
        for n in (1, 5, 20):
            prior_h, prior_l = ind.prior_high(values, n), ind.prior_low(values, n)
            trail_h, trail_l = ind.trailing_high(values, n), ind.trailing_low(values, n)
            for i in range(len(values)):
                if i >= n:
                    self.assertEqual(prior_h[i], max(values[i - n:i]))
                    self.assertEqual(prior_l[i], min(values[i - n:i]))
                else:
                    self.assertTrue(math.isnan(prior_h[i]))
                if i >= n - 1:
                    self.assertEqual(trail_h[i], max(values[i - n + 1:i + 1]))
                    self.assertEqual(trail_l[i], min(values[i - n + 1:i + 1]))

    def test_indicators_are_causal(self):
        rnd = random.Random(5)
        closes = [100 * math.exp(sum(rnd.gauss(0, 0.01) for _ in range(k))) for k in range(300)]
        highs, lows = [c * 1.01 for c in closes], [c * 0.99 for c in closes]
        full = (ind.ema(closes, 20), ind.atr(highs, lows, closes, 14), ind.rsi(closes, 14),
                ind.rate_of_change(closes, 24))
        for cut in (60, 150, 299):
            part = (ind.ema(closes[:cut], 20), ind.atr(highs[:cut], lows[:cut], closes[:cut], 14),
                    ind.rsi(closes[:cut], 14), ind.rate_of_change(closes[:cut], 24))
            for whole, prefix in zip(full, part):
                self.assertEqual(whole[cut - 1], prefix[-1])

    def test_rsi_bounds_and_flat_series(self):
        self.assertEqual(ind.rsi([1.0] * 30, 2)[-1], 50.0)
        rising = ind.rsi([float(k) for k in range(1, 40)], 2)
        self.assertEqual(rising[-1], 100.0)


class StrategyTests(unittest.TestCase):
    def test_donchian_breakout_entry_stop_and_trailing_exit_channel(self):
        closes = [100.0] * 40 + [101.0, 102.5]
        bars = Bars.from_candles(candles(closes))
        s = DonchianBreakout(entry=20, exit=10, atr=14)
        series = s.indicators(bars)
        decision = s.decide(len(bars) - 1, bars, series, None)
        self.assertEqual((decision.action, decision.side), ("enter", 1))
        self.assertAlmostEqual(decision.stop, bars.c[-1] - 2.0 * series["atr"][-1])
        pos = Position(1, bars.c[-1], bars.t[-1], decision.stop, bars.c[-1])
        held = s.decide(len(bars) - 1, bars, series, pos)
        self.assertEqual(held.action, "hold")
        self.assertGreaterEqual(held.stop, decision.stop)
        self.assertEqual(held.stop, max(decision.stop, series["trail_low"][-1]))

    def test_donchian_trend_filter_and_long_only(self):
        closes = [120 - k * 0.5 for k in range(60)] + [80.0]
        bars = Bars.from_candles(candles(closes))
        filtered = DonchianBreakout(entry=20, exit=10, trend=50)
        self.assertEqual(filtered.decide(len(bars) - 1, bars, filtered.indicators(bars), None).action, "enter")
        long_only = DonchianBreakout(entry=20, exit=10, allow_short=False)
        self.assertEqual(long_only.decide(len(bars) - 1, bars, long_only.indicators(bars), None).action, "wait")

    def test_ema_trend_enters_only_on_fresh_cross_and_reverses(self):
        closes = [100 - k * 0.1 for k in range(150)] + [100 + k for k in range(1, 30)]
        bars = Bars.from_candles(candles(closes))
        s = EmaTrend(fast=5, slow=20, atr=5)
        series = s.indicators(bars)
        signals = [(i, s.decide(i, bars, series, None)) for i in range(25, len(bars))]
        entries = [i for i, d in signals if d.action == "enter" and d.side == 1]
        self.assertEqual(len(entries), 1)
        crossed = entries[0]
        self.assertGreater(series["fast"][crossed], series["slow"][crossed])
        self.assertLessEqual(series["fast"][crossed - 1], series["slow"][crossed - 1])
        short = Position(-1, 100, 0, 200, 100)
        self.assertEqual(s.decide(len(bars) - 1, bars, series, short).action, "reverse")

    def test_tsmom_follows_sign_and_flips(self):
        up = Bars.from_candles(candles([100 + k for k in range(60)]))
        s = TimeSeriesMomentum(lookback=24, atr=10)
        series = s.indicators(up)
        d = s.decide(len(up) - 1, up, series, None)
        self.assertEqual((d.action, d.side), ("enter", 1))
        short = Position(-1, 150, 0, 170, 150)
        self.assertEqual(s.decide(len(up) - 1, up, series, short).action, "reverse")
        long_only = TimeSeriesMomentum(lookback=24, atr=10, allow_short=False)
        down = Bars.from_candles(candles([200 - k for k in range(60)]))
        self.assertEqual(long_only.decide(len(down) - 1, down, long_only.indicators(down), None).action, "wait")

    def test_rsi_reversion_exits_at_mean_or_time_limit(self):
        closes = [100 + k * 0.2 for k in range(220)] + [140, 138, 135]
        bars = Bars.from_candles(candles(closes))
        s = RsiReversion(trend=200, max_bars=3)
        series = s.indicators(bars)
        d = s.decide(len(bars) - 1, bars, series, None)
        self.assertEqual((d.action, d.side), ("enter", 1))
        pos = Position(1, 135, 0, 120, 135, bars_held=3)
        self.assertEqual(s.decide(len(bars) - 1, bars, series, pos).action, "exit")

    def test_stops_only_tighten_and_advance_tracks_extremes(self):
        long = Position(1, 100, 0, 95, 100)
        self.assertEqual(tighten(long, 90), 95)
        self.assertEqual(tighten(long, 97), 97)
        self.assertEqual(tighten(long, float("nan")), 95)
        short = Position(-1, 100, 0, 105, 100)
        self.assertEqual(tighten(short, 110), 105)
        bars = Bars.from_candles(candles([100, 103, 99]))
        advance(long, bars, 1)
        advance(short, bars, 2)
        self.assertEqual(long.extreme, bars.h[1])
        self.assertEqual(short.extreme, bars.l[2])
        self.assertEqual((long.bars_held, short.bars_held), (1, 1))

    def test_build_rejects_unknown_names_and_parameters(self):
        with self.assertRaises(ValueError):
            build("martingale")
        with self.assertRaises(ValueError):
            build("donchian", lookback=5)
        self.assertIn("entry=55", build("donchian", entry=55).label)


class EngineTests(unittest.TestCase):
    def engine(self, folder, **params):
        strategy = DonchianBreakout(entry=20, exit=10, atr=14, **params)
        return StrategyEngine(strategy, ["BTC"], "1h", Path(folder) / "strategy.json", settle_s=0)

    def series(self, closes, now_ms):
        start = latest_closed_open(now_ms, HOUR) - (len(closes) - 1) * HOUR
        return candles(closes, start=start)

    def test_validate_rejects_gaps_stale_and_malformed_history(self):
        now = 1_800_000_000_000
        rows = self.series([100.0] * 60, now)
        expected = latest_closed_open(now, HOUR)
        self.assertEqual(validate(Bars.from_candles(rows), HOUR, expected, 30), "")
        self.assertIn("not yet published", validate(Bars.from_candles(rows[:-1]), HOUR, expected, 30))
        gap = rows[:40] + rows[41:]
        self.assertIn("Gap", validate(Bars.from_candles(gap), HOUR, expected, 30))
        bad = [dict(r) for r in rows]
        bad[-1]["h"] = bad[-1]["l"] * 0.5
        self.assertIn("Malformed", validate(Bars.from_candles(bad), HOUR, expected, 30))
        self.assertIn("required", validate(Bars.from_candles(rows[-10:]), HOUR, expected, 30))

    def test_due_once_per_closed_bar_and_backoff_after_failure(self):
        with tempfile.TemporaryDirectory() as d:
            e = self.engine(d)
            now = 1_800_000_000.0
            self.assertTrue(e.due("BTC", now))
            decision = e.evaluate("BTC", self.series([100.0] * 60, int(now * 1000)), None, now)
            self.assertIsInstance(decision, Decision)
            self.assertFalse(e.due("BTC", now + 60))
            self.assertTrue(e.due("BTC", now + 3600))
            self.assertIsNone(e.evaluate("BTC", self.series([100.0] * 5, int((now + 3600) * 1000)), None, now + 3600))
            self.assertFalse(e.due("BTC", now + 3601))
            self.assertTrue(e.due("BTC", now + 3610))

    def test_positions_persist_and_exchange_state_wins(self):
        with tempfile.TemporaryDirectory() as d:
            e = self.engine(d)
            e.opened("BTC", 1, 100.0, 95.0, when_ms=1)
            again = self.engine(d)
            self.assertEqual(again.position("BTC").stop, 95.0)
            self.assertIsNone(again.sync("BTC", None))
            self.assertIsNone(again.position("BTC"))
            changed = StrategyEngine(EmaTrend(), ["BTC"], "1h", Path(d) / "strategy.json")
            self.assertIsNone(changed.position("BTC"))

    def test_unknown_live_position_is_adopted_with_volatility_stop(self):
        with tempfile.TemporaryDirectory() as d:
            e = self.engine(d)
            now = 1_800_000_000.0
            rows = self.series([100.0 + (k % 3) for k in range(60)], int(now * 1000))
            e.evaluate("BTC", rows, dict(side=-1, size=1, entry_px=101.0), now)
            pos = e.position("BTC")
            self.assertEqual(pos.side, -1)
            self.assertGreater(pos.stop, 101.0)

    def test_adoption_never_loosens_an_existing_exchange_stop(self):
        with tempfile.TemporaryDirectory() as d:
            e = self.engine(d)
            now = 1_800_000_000.0
            rows = self.series([100.0 + (k % 3) for k in range(60)], int(now * 1000))
            e.evaluate("BTC", rows, dict(side=1, size=1, entry_px=100.0), now, existing_stop=108.0)
            self.assertEqual(e.position("BTC").stop, 108.0)

    def test_trailing_stop_catches_up_after_downtime(self):
        with tempfile.TemporaryDirectory() as d:
            e = self.engine(d)
            now = 1_800_000_000.0
            closes = [100.0] * 50 + [100 + k for k in range(1, 11)]
            rows = self.series(closes, int(now * 1000))
            e.state["BTC"]["last_bar"] = rows[-6]["t"]
            e.opened("BTC", 1, 100.0, 90.0, when_ms=rows[-8]["t"])
            e.evaluate("BTC", rows, dict(side=1, size=1, entry_px=100.0), now)
            pos = e.position("BTC")
            self.assertEqual(pos.bars_held, 5)
            self.assertEqual(pos.extreme, max(r["h"] for r in rows[-5:]))
            self.assertGreater(pos.stop, 90.0)
            saved = json.loads((Path(d) / "strategy.json").read_text())
            self.assertEqual(saved["coins"]["BTC"]["position"]["stop"], pos.stop)


if __name__ == "__main__":
    unittest.main()
