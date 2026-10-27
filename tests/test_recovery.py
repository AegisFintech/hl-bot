"""Operational failures recover without ever unlatching drawdown risk."""
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.bot import TradingBot
from src.exchange.hyperliquid import HyperliquidClient
from src.reconciler import PositionReconciler
from src.risk.manager import RiskManager


class RecoveryTests(unittest.TestCase):
    def test_exact_lot_size_survives_repeated_rounding(self):
        c = HyperliquidClient.__new__(HyperliquidClient)
        c.get_sz_decimals = lambda coin: 5
        for size in [0.00007, 0.00029, 0.00123]:
            self.assertEqual(c.round_size('BTC', size), size)
            self.assertEqual(c.round_size('BTC', c.round_size('BTC', size)), size)
        self.assertEqual(c.round_size('BTC', 0.00007999), 0.00007)
        for bad in [-1, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                c.round_size('BTC', bad)

    def test_pause_survives_restart_and_midnight_with_backoff(self):
        with tempfile.TemporaryDirectory() as d:
            r = RiskManager(state_file=Path(d) / 'risk.json')
            r.update_equity(1000)
            r.pause_execution('maintenance')
            deadline = r.state.pause_until
            r = RiskManager(state_file=r.state_file)
            r.reset_daily()
            self.assertTrue(r.should_kill())
            self.assertFalse(r.state.halted)
            self.assertEqual(r.state.pause_until, deadline)
            self.assertFalse(r.can_trade(None))
            self.assertFalse(r.resume_execution())
            r.pause_execution('again')
            self.assertGreater(r.state.pause_until, deadline + 50)

    def test_drawdown_never_auto_resumes(self):
        r = RiskManager()
        r.update_equity(1000)
        r.pause_execution('network')
        r.update_equity(950)
        r.state.pause_until = 0
        self.assertFalse(r.resume_execution())
        r.update_equity(1001)
        self.assertFalse(r.resume_execution())
        with self.assertRaises(ValueError):
            r.review_legacy_protection_halt()
        self.assertTrue(r.state.halted)

    def test_resume_requires_fresh_positive_equity_and_retains_peak(self):
        r = RiskManager()
        r.update_equity(1000)
        r.update_equity(990)
        r.pause_execution('network')
        r.state.pause_until = 0
        r.state.equity_updated_at = time.time() - 11
        self.assertFalse(r.resume_execution())
        r.update_equity(990)
        self.assertTrue(r.resume_execution())
        self.assertEqual(r.state.peak_equity, 1000)
        self.assertFalse(r.should_kill())

    def test_explicit_review_only_migrates_specific_operational_halt(self):
        r = RiskManager()
        r.update_equity(1000)
        r.halt('Unrecognized operator halt')
        with self.assertRaises(ValueError):
            r.review_legacy_protection_halt()
        r.halt('Protective order recovery failed')
        r.review_legacy_protection_halt()
        self.assertTrue(r.should_kill())
        self.assertFalse(r.state.halted)
        self.assertTrue(r.state.execution_paused)
        self.assertEqual(r.state.peak_equity, 1000)

    def test_exchange_upgrade_rejection_activates_operational_pause(self):
        r = RiskManager()
        r.update_equity(1000)
        c = Mock()
        c.get_positions.return_value = [dict(position=dict(coin='BTC', entryPx='80000', szi='0.00007'))]
        c.get_cached_candles.return_value = []
        c.round_price.side_effect = lambda coin, px: px
        c.place_trigger_orders.return_value = dict(status='ok', response=dict(data=dict(
            statuses=[dict(error='Only post-only orders allowed immediately after network upgrade')])))
        rec = PositionReconciler(c, r, 'BTC')
        rec._place_recovery_tpsl(dict(position=dict(entryPx='80000', szi='0.00007')))
        self.assertTrue(r.state.execution_paused)
        self.assertFalse(r.state.halted)

    def test_position_closed_during_cancellation_does_not_recreate_orders(self):
        r = RiskManager()
        c = Mock()
        c.get_positions.return_value = []
        rec = PositionReconciler(c, r, 'BTC')
        rec._place_recovery_tpsl(dict(position=dict(coin='BTC', entryPx='80000', szi='0.00007')))
        c.place_trigger_orders.assert_not_called()
        self.assertEqual(rec.position_count, 0)

    def test_cancel_failure_initiates_flatten_path(self):
        r = RiskManager()
        c = Mock()
        c.cancel_order.side_effect = TimeoutError()
        rec = PositionReconciler(c, r, 'BTC')
        with self.assertRaises(TimeoutError):
            rec._cancel_for_recovery(123)
        self.assertTrue(r.should_kill())

    def bot(self):
        b = TradingBot.__new__(TradingBot)
        b._halt_cleanup_at = 0
        b.coins = ['BTC']
        b.client = Mock()
        b.client.get_positions.return_value = []
        b.client.get_open_orders.return_value = []
        b.client.get_account_snapshot.return_value = {'equity': 990}
        b.client.bbo_age.return_value = 1
        b.risk_manager = RiskManager()
        b.risk_manager.update_equity(1000)
        b.risk_manager.pause_execution('network')
        b.ledger = Mock()
        b._reconcilers = []
        return b

    def check(self, b):
        b._halt_cleanup_at = 0
        b._recovery_check_at = 0
        b._emergency_flatten()

    def test_three_healthy_checks_required_before_resume(self):
        b = self.bot()
        b.risk_manager.state.pause_until = 0
        for _ in range(2):
            self.check(b)
            self.assertTrue(b.risk_manager.state.execution_paused)
        self.check(b)
        self.assertFalse(b.risk_manager.should_kill())
        self.assertEqual(b.risk_manager.state.peak_equity, 1000)

    def test_stale_quote_or_exposure_resets_success_sequence(self):
        b = self.bot()
        b.risk_manager.state.pause_until = 0
        self.check(b)
        b.client.bbo_age.return_value = 30
        self.check(b)
        self.assertEqual(b._recovery_checks, 0)
        b.client.bbo_age.return_value = 1
        b.client.get_open_orders.return_value = [dict(coin='BTC')]
        self.check(b)
        self.assertEqual(b._recovery_checks, 0)
        self.assertTrue(b.risk_manager.should_kill())

    def test_confirmation_failure_never_resumes(self):
        b = self.bot()
        b._recovery_checks = 5
        b.client.get_account_snapshot.side_effect = TimeoutError()
        with self.assertLogs('src.bot', level='ERROR'):
            self.check(b)
        self.assertEqual(b._recovery_checks, 0)
        self.assertTrue(b.risk_manager.should_kill())
