"""Backtester execution conventions: next-open fills, gap stops, funding, breaker."""
import unittest

from src.risk.manager import position_size
from src.strategy.library import Bars, Decision, Strategy
from src.validation.backtest import Costs, Risk, backtest

HOUR = 3_600_000
T0 = 1_700_000_000_000 - 1_700_000_000_000 % HOUR


def bars(rows):
    return Bars.from_candles([dict(t=T0 + k * HOUR, o=o, h=h, l=l, c=c, v=1) for k, (o, h, l, c) in enumerate(rows)])


class Scripted(Strategy):
    """Enters on chosen bars with a fixed stop; holds otherwise."""
    name = "scripted"
    defaults = dict(plan=None)

    @property
    def warmup(self):
        return 0

    def indicators(self, bars):
        return {}

    def decide(self, i, bars, series, position):
        action = (self.params["plan"] or {}).get(i)
        if action and not position:
            return action
        if action and position and action.action in ("exit", "reverse"):
            return action
        if position:
            return Decision("hold", position.side, position.stop)
        return Decision("wait")


NO_COST = Costs(taker_fee=0, slippage=0, stop_slippage=0, funding_stress_per_hour=0)


class BacktestTests(unittest.TestCase):
    def test_decision_executes_at_next_open_never_same_bar(self):
        data = {"X": bars([(100, 101, 99, 100), (110, 111, 109, 110), (120, 121, 119, 120)])}
        s = Scripted(plan={0: Decision("enter", 1, 50.0)})
        result, trades, _ = backtest(s, data, HOUR, NO_COST, Risk(risk_per_trade=0.01, max_leverage=100,
                                                                 max_gross_leverage=100))
        self.assertEqual(trades[0]["entry"], 110)  # Bar 1 open, not bar 0 close.
        self.assertEqual(trades[0]["reason"], "End of test window")

    def test_stop_fills_at_stop_or_worse_gap_open_with_slippage(self):
        rows = [(100, 101, 99, 100), (100, 101, 96, 97), (97, 98, 97, 97.5)]
        s = Scripted(plan={0: Decision("enter", 1, 98.0)})
        costs = Costs(taker_fee=0, slippage=0, stop_slippage=0.001, funding_stress_per_hour=0)
        _, trades, _ = backtest(s, {"X": bars(rows)}, HOUR, costs, Risk(max_leverage=100, max_gross_leverage=100))
        self.assertAlmostEqual(trades[0]["exit"], 98.0 * 0.999)
        gap = [(100, 101, 99, 100), (100, 101, 99.5, 100), (90, 91, 89, 90)]
        s = Scripted(plan={0: Decision("enter", 1, 98.0)})
        _, trades, _ = backtest(s, {"X": bars(gap)}, HOUR, costs, Risk(max_leverage=100, max_gross_leverage=100))
        self.assertAlmostEqual(trades[0]["exit"], 90 * 0.999)
        self.assertEqual(trades[0]["reason"], "Protective stop")

    def test_entry_skipped_when_open_gaps_through_stop(self):
        rows = [(100, 101, 99, 100), (95, 96, 94, 95), (95, 96, 94, 95)]
        s = Scripted(plan={0: Decision("enter", 1, 97.0)})
        result, trades, _ = backtest(s, {"X": bars(rows)}, HOUR, NO_COST, Risk())
        self.assertEqual(trades, [])
        self.assertEqual(result["skipped_entries"], {"Opened beyond stop": 1})

    def test_size_matches_live_formula_and_costs_are_charged(self):
        rows = [(100, 101, 99, 100)] + [(100, 100.5, 99.5, 100)] * 3
        s = Scripted(plan={0: Decision("enter", 1, 95.0)})
        risk = Risk(risk_per_trade=0.01, max_leverage=3, max_gross_leverage=5)
        costs = Costs(taker_fee=0.0005, slippage=0.001, stop_slippage=0, funding_stress_per_hour=0.0001)
        _, trades, _ = backtest(s, {"X": bars(rows)}, HOUR, costs, risk, initial_equity=1000)
        fill = 100 * 1.001
        expected = position_size(1000, fill, 95.0, 0.01, 3, 5)
        self.assertAlmostEqual(trades[0]["size"], expected)
        self.assertGreater(trades[0]["fees"], 0)
        self.assertGreater(trades[0]["funding"], 0)
        self.assertAlmostEqual(trades[0]["net"], trades[0]["gross"] - trades[0]["fees"] - trades[0]["funding"])

    def test_funding_history_sign_longs_pay_shorts_receive(self):
        rows = [(100, 101, 99, 100)] * 4
        rates = {"X": {T0 + k * HOUR: 0.001 for k in range(4)}}
        for side, sign in ((1, 1), (-1, -1)):
            stop = 50.0 if side > 0 else 150.0
            s = Scripted(plan={0: Decision("enter", side, stop)})
            _, trades, _ = backtest(s, {"X": bars(rows)}, HOUR, NO_COST, Risk(), funding=rates)
            self.assertEqual(sign * trades[0]["funding"] > 0, True)

    def test_breaker_flattens_pauses_and_rebases_peak(self):
        rows = [(100, 101, 99, 100), (100, 100, 93, 93), (93, 94, 92, 93)] + [(93, 94, 92, 93)] * 20
        plan = {0: Decision("enter", 1, 50.0), 2: Decision("enter", 1, 50.0), 15: Decision("enter", 1, 50.0)}
        s = Scripted(plan=plan)
        risk = Risk(risk_per_trade=0.5, max_leverage=1, max_gross_leverage=1, drawdown_limit=0.05, cooldown_hours=10)
        result, trades, curve = backtest(s, {"X": bars(rows)}, HOUR, NO_COST, risk, initial_equity=1000)
        self.assertEqual(result["drawdown_breaker_trips"], 1)
        self.assertEqual(trades[0]["reason"], "Drawdown breaker")
        entries = [t["entry_time"] for t in trades]
        self.assertNotIn(T0 + 3 * HOUR, entries)  # Bar-2 signal falls inside the cooldown.
        self.assertIn(T0 + 16 * HOUR, entries)     # After cooldown trading resumes.

    def test_reverse_closes_then_opens_opposite(self):
        rows = [(100, 101, 99, 100), (101, 102, 100, 101), (102, 103, 101, 102), (101, 102, 100, 101)]
        plan = {0: Decision("enter", 1, 90.0), 1: Decision("reverse", -1, 115.0)}
        _, trades, _ = backtest(Scripted(plan=plan), {"X": bars(rows)}, HOUR, NO_COST, Risk())
        self.assertEqual([t["side"] for t in trades], [1, -1])
        self.assertEqual(trades[0]["exit"], 102)
        self.assertEqual(trades[1]["entry"], 102)


if __name__ == "__main__":
    unittest.main()
