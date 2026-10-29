import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.learning.ledger import FillLedger
from src.risk.manager import RiskManager, position_size
from src.strategy.economics import bracket_distances, viable


class RiskTests(unittest.TestCase):
    def test_breaker_trips_at_exact_limit_and_survives_restart_and_midnight(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'risk.json'
            r = RiskManager(state_file=path, cooldown_s=3600)
            r.update_equity(1000)
            r.update_equity(950)
            self.assertTrue(r.should_flatten())
            self.assertEqual(r.state.breaker_trips, 1)
            r.reset_daily()
            r.update_equity(1100)  # Equity recovering does not clear the breaker early.
            self.assertTrue(r.should_flatten())
            again = RiskManager(state_file=path, cooldown_s=3600)
            self.assertTrue(again.should_flatten())
            self.assertEqual(again.state.peak_equity, 1100)
            self.assertFalse(again.try_reset_after_cooldown(True))

    def test_breaker_auto_resets_only_after_cooldown_when_flat_and_fresh(self):
        r = RiskManager(cooldown_s=3600)
        r.update_equity(1000)
        r.update_equity(940)
        self.assertFalse(r.try_reset_after_cooldown(True))
        r.state.cooldown_until = time.time() - 1
        self.assertFalse(r.try_reset_after_cooldown(False))  # Exposure not confirmed flat.
        r.state.equity_updated_at = time.time() - 11
        self.assertFalse(r.try_reset_after_cooldown(True))  # Stale equity.
        r.update_equity(940)
        self.assertTrue(r.try_reset_after_cooldown(True))
        self.assertFalse(r.should_kill())
        self.assertEqual(r.state.peak_equity, 940)
        self.assertEqual(r.state.day_start_equity, 940)
        kinds = [e['kind'] for e in r.state.events]
        self.assertEqual(kinds[-2:], ['breaker_trip', 'breaker_reset'])
        r.update_equity(893)  # A new 5% drop from the re-based peak trips again.
        self.assertTrue(r.should_flatten())
        self.assertEqual(r.state.breaker_trips, 2)

    def test_auto_reset_can_be_disabled(self):
        r = RiskManager(auto_reset=False)
        r.update_equity(1000)
        r.update_equity(900)
        self.assertEqual(r.state.cooldown_until, 0)
        self.assertFalse(r.try_reset_after_cooldown(True))

    def test_manual_mode_halt_keeps_full_cooldown_when_auto_reset_is_enabled_later(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'risk.json'
            manual = RiskManager(state_file=path, auto_reset=False)
            manual.update_equity(1000)
            manual.update_equity(900)
            resumed = RiskManager(state_file=path, cooldown_s=3600)
            self.assertGreater(resumed.state.cooldown_until, time.time() + 3500)
            resumed.update_equity(900)
            self.assertFalse(resumed.try_reset_after_cooldown(True))

    def test_legacy_halt_without_cooldown_migrates_to_auto_reset(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'risk.json'
            path.write_text(json.dumps(dict(halted=True, halt_reason='5% equity high-water drawdown limit',
                                            peak_equity=1000, current_equity=940, equity_updated_at=time.time())))
            r = RiskManager(state_file=path)
            self.assertTrue(r.should_flatten())
            self.assertLessEqual(r.state.cooldown_until, time.time())
            self.assertEqual(r.state.events[-1]['kind'], 'legacy_halt_migrated')
            r.update_equity(940)
            self.assertTrue(r.try_reset_after_cooldown(True))

    def test_zero_equity_is_loss_not_discarded(self):
        r = RiskManager()
        r.update_equity(1000)
        r.update_equity(0)
        self.assertTrue(r.should_flatten())

    def test_stale_and_invalid_equity(self):
        r = RiskManager()
        r.update_equity(1000)
        self.assertTrue(r.can_trade(None))
        r.state.equity_updated_at = time.time() - 31
        self.assertFalse(r.can_trade(None))
        self.assertEqual(r.admission(), 'Account equity is stale')
        with self.assertRaises(ValueError):
            r.update_equity(float('nan'))

    def test_admission_reasons_are_explicit(self):
        r = RiskManager(max_open_positions=2, max_daily_trades=2, max_daily_loss_pct=0.03)
        r.update_equity(1000)
        self.assertEqual(r.admission(), '')
        r.sync_open_positions(2)
        self.assertIn('Maximum open positions', r.admission())
        r.sync_open_positions(0)
        r.record_order()
        self.assertEqual(r.admission(), '')  # Simultaneous signals on other coins are not spaced out.
        r.record_order()
        self.assertIn('Daily entry limit', r.admission())
        r.state.daily_trades = 0
        r.update_equity(965)
        self.assertIn('Daily loss limit', r.admission())

    def test_position_size_risks_fraction_of_equity_within_leverage_caps(self):
        size = position_size(1000, 100, 98, 0.01, max_leverage=100, max_gross_leverage=100)
        self.assertAlmostEqual(size * 2, 10)  # Stop-out loses exactly 1% of equity.
        capped = position_size(1000, 100, 99.9, 0.01, max_leverage=3, max_gross_leverage=5)
        self.assertAlmostEqual(capped * 100, 3000)
        gross = position_size(1000, 100, 99.9, 0.01, max_leverage=3, max_gross_leverage=5, open_notional=4500)
        self.assertAlmostEqual(gross * 100, 500)
        self.assertEqual(position_size(1000, 100, 100, 0.01, 3, 5), 0)
        self.assertEqual(position_size(0, 100, 98, 0.01, 3, 5), 0)
        self.assertEqual(position_size(float('nan'), 100, 98, 0.01, 3, 5), 0)
        r = RiskManager(risk_per_trade=0.01, max_leverage=3, max_gross_leverage=5)
        r.update_equity(1000)
        self.assertAlmostEqual(r.compute_position_size(SimpleNamespace(entry_price=100, sl_price=98)), 5)

    def test_corrupt_state_is_preserved_and_breaker_holds_until_cooldown(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'risk.json'
            p.write_text('corrupt')
            r = RiskManager(state_file=p, cooldown_s=3600)
            self.assertTrue(r.should_flatten())
            self.assertIn('unreadable', r.state.halt_reason)
            self.assertGreater(r.state.cooldown_until, time.time())
            self.assertEqual(len(list(Path(d).glob('risk.corrupt-*'))), 1)

    def test_pause_escalates_then_decays_after_quiet_hour(self):
        r = RiskManager()
        r.update_equity(1000)
        r.pause_execution('a')
        r.pause_execution('b')
        self.assertEqual(r.state.recovery_count, 2)
        self.assertGreater(r.state.pause_until - time.time(), 100)
        r.state.last_pause_at = time.time() - 3601
        r.pause_execution('c')
        self.assertEqual(r.state.recovery_count, 1)
        self.assertLessEqual(r.state.pause_until - time.time(), 61)

    def test_midnight_keeps_peak(self):
        r = RiskManager()
        r.update_equity(1000)
        r.update_equity(990)
        r.state.day_start = time.time() - 86400
        r.check_daily_reset()
        self.assertEqual(r.state.peak_equity, 1000)

    def test_economics_rejects_costs_and_crossing(self):
        s = SimpleNamespace(entry_price=100, sl_price=99.98, tp_price=100.08, side='long')
        self.assertFalse(viable(s, 100, 100.01)[0])
        s.tp_price = 101
        s.sl_price = 99.7
        self.assertTrue(viable(s, 100, 100.01)[0])
        self.assertFalse(viable(s, 99.9, 99.99)[0])
        self.assertFalse(viable(s, float('nan'), 100.01)[0])
        target, stop = bracket_distances([], 100)
        self.assertAlmostEqual(stop, 0.15)
        self.assertGreaterEqual((target - .09) / (stop + .09), 1.5 - 1e-9)

    def test_ledger_idempotency_and_fee_totals(self):
        with tempfile.TemporaryDirectory() as d:
            l = FillLedger(Path(d) / 'ledger.sqlite')
            f = dict(tid=1, coin='BTC', time=1, px='100', sz='1', closedPnl='0', fee='0.1', dir='Open Long')
            self.assertTrue(l.add(f))
            self.assertFalse(l.add(f))
            l.add(dict(f, tid=2, time=2, closedPnl='1', dir='Close Long'))
            p = l.performance()
            self.assertAlmostEqual(p['net_pnl'], 0.8)
            self.assertEqual(p['fill_count'], 2)


if __name__ == '__main__':
    unittest.main()
