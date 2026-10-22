import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from src.bot import TradingBot

class EmergencyTests(unittest.TestCase):
    def test_cancel_failure_still_closes_and_confirms(self):
        b=TradingBot.__new__(TradingBot);b._halt_cleanup_at=0;b.coins=['BTC']
        b.client=Mock();b.client.cancel_all_orders.side_effect=[RuntimeError('network'),[]]
        b.client.get_positions.return_value=[];b.client.get_open_orders.return_value=[]
        b.client.get_account_snapshot.return_value={'equity':950}
        b.risk_manager=Mock();b.risk_manager.state=SimpleNamespace(current_equity=950,peak_equity=1000)
        b.ledger=Mock()
        with self.assertLogs('src.bot',level='ERROR'):
            b._emergency_flatten()
        b.client.close_position.assert_called_once_with('BTC')
        self.assertEqual(b.halt_cleanup_status,'Confirmed flat; no orders')
        b.risk_manager.update_equity.assert_called_once_with(950)
        b._emergency_flatten()
        self.assertEqual(b.client.close_position.call_count,1)
    def test_halted_tick_never_reconciles_or_scans(self):
        b=TradingBot.__new__(TradingBot);b.risk_manager=Mock();b.risk_manager.should_kill.return_value=True
        b._emergency_flatten=Mock();b._tick()
        b._emergency_flatten.assert_called_once()
