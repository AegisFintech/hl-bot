import unittest
from src.learning.trades import complete_trades


def fill(time, start, side, size, fee=1, pnl=0, **extra):
    return (
        dict(
            time=time,
            coin="BTC",
            startPosition=str(start),
            side=side,
            sz=str(size),
            px="100",
            fee=str(fee),
            closedPnl=str(pnl),
        )
        | extra
    )


class TradeEpisodeTests(unittest.TestCase):
    def test_partial_fills_form_one_trade_with_all_entry_exit_fees(self):
        rows = [
            fill(1, 0, "B", 2),
            fill(2, 2, "A", 1, pnl=3),
            fill(3, 1, "A", 1, pnl=-1),
        ]
        trades = complete_trades(rows)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["gross_pnl"], 2)
        self.assertEqual(trades[0]["fees"], 3)
        self.assertEqual(trades[0]["net_pnl"], -1)

    def test_unknown_initial_position_and_gaps_are_excluded(self):
        self.assertEqual(complete_trades([fill(1, 2, "A", 2, pnl=4)]), [])
        self.assertEqual(complete_trades([fill(1, 0, "B", 2), fill(2, 1, "A", 1)]), [])

    def test_reversal_splits_fee_and_starts_a_new_episode(self):
        rows = [
            fill(1, 0, "B", 1),
            fill(2, 1, "A", 2, fee=2, pnl=3),
            fill(3, -1, "B", 1, pnl=4),
        ]
        trades = complete_trades(rows)
        self.assertEqual(len(trades), 2)
        self.assertEqual([t["fees"] for t in trades], [2, 2])
        self.assertEqual([t["net_pnl"] for t in trades], [1, 2])

    def test_nonfinite_or_non_usdc_fees_break_continuity(self):
        for extra in ({"fee": "NaN"}, {"feeToken": "HYPE"}):
            self.assertEqual(
                complete_trades([fill(1, 0, "B", 1), fill(2, 1, "A", 1, **extra)]), []
            )
