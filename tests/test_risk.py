import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from src.risk.manager import RiskManager
from src.strategy.economics import viable, bracket_distances
from src.learning.ledger import FillLedger

class RiskTests(unittest.TestCase):
    def test_exact_limit_latches_across_restart_and_midnight(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'risk.json'
            r = RiskManager(state_file=path)
            r.update_equity(1000); r.update_equity(950)
            self.assertTrue(r.should_kill())
            r.reset_daily(); r.update_equity(1100)
            self.assertTrue(r.should_kill())
            self.assertEqual(RiskManager(state_file=path).state.peak_equity,1100)
            self.assertTrue(RiskManager(state_file=path).should_kill())

    def test_zero_equity_is_loss_not_discarded(self):
        r=RiskManager();r.update_equity(1000);r.update_equity(0)
        self.assertTrue(r.should_kill())

    def test_stale_and_invalid_equity(self):
        r=RiskManager();r.update_equity(1000)
        self.assertTrue(r.can_trade(None))
        r.state.equity_updated_at=time.time()-31
        self.assertFalse(r.can_trade(None))
        with self.assertRaises(ValueError):r.update_equity(float('nan'))

    def test_risk_size_accounts_for_stop_and_remaining_drawdown(self):
        r=RiskManager(order_size_usd=100000,max_position_size_usd=100000)
        r.update_equity(1000)
        s=SimpleNamespace(entry_price=100,sl_price=98)
        size=r.compute_position_size(s)
        self.assertLessEqual(size*(2+0.12),2.5+1e-9)
        r.update_equity(951)
        self.assertLess(r.compute_position_size(s),size)

    def test_corrupt_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'risk.json';p.write_text('corrupt')
            self.assertTrue(RiskManager(state_file=p).should_kill())

    def test_midnight_keeps_peak(self):
        r=RiskManager();r.update_equity(1000);r.update_equity(990)
        r.state.day_start=time.time()-86400;r.check_daily_reset()
        self.assertEqual(r.state.peak_equity,1000)

    def test_economics_rejects_costs_and_crossing(self):
        s=SimpleNamespace(entry_price=100,sl_price=99.98,tp_price=100.08,side='long')
        self.assertFalse(viable(s,100,100.01)[0])
        s.tp_price=101;s.sl_price=99.7
        self.assertTrue(viable(s,100,100.01)[0])
        self.assertFalse(viable(s,99.9,99.99)[0])
        self.assertEqual(bracket_distances([],100),(0.3,0.15))

    def test_ledger_idempotency_and_fee_totals(self):
        with tempfile.TemporaryDirectory() as d:
            l=FillLedger(Path(d)/'ledger.sqlite')
            f=dict(tid=1,coin='BTC',time=1,px='100',sz='1',closedPnl='0',fee='0.1',dir='Open Long')
            self.assertTrue(l.add(f));self.assertFalse(l.add(f))
            l.add(dict(f,tid=2,time=2,closedPnl='1',dir='Close Long'))
            p=l.performance();self.assertAlmostEqual(p['net_pnl'],0.8)
            self.assertEqual(p['fill_count'],2)
