import unittest
from types import SimpleNamespace
from unittest.mock import patch
from scripts.replay import replay

class FakeScalper:
    def __init__(self,*args,**kwargs):self.diagnostics={'reason':'fixture'};self.sent=False
    def scan_for_signals(self):
        if self.sent:return []
        self.sent=True
        return [SimpleNamespace(entry_price=99.99,sl_price=99.8,tp_price=100.6,side='long')]

class ReplayTests(unittest.TestCase):
    def test_ambiguous_bar_uses_stop_and_charges_both_sides(self):
        bars=[dict(t=1792600000000+i*60000,o='100',h='100.7',l='99.7',c='100',v='1') for i in range(5)]
        with patch('scripts.replay.Scalper',FakeScalper):
            result=replay(bars,start=2)
        self.assertEqual(result['closed_trades'],1)
        self.assertLess(result['net_pnl'],0)
        self.assertGreater(result['fees'],0)
        self.assertEqual(result['diagnostics']['simulated_entries'],1)
    def test_no_fill_without_crossing_entry(self):
        bars=[dict(t=1792600000000+i*60000,o='100',h='100.7',l='100',c='100',v='1') for i in range(5)]
        with patch('scripts.replay.Scalper',FakeScalper):
            result=replay(bars,start=2)
        self.assertEqual(result['closed_trades'],0)
        self.assertEqual(result['fees'],0)
