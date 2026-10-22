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

    def test_expiry_preserves_protection_when_position_filled_since_sync(self):
        import threading
        b=TradingBot.__new__(TradingBot);b.client=Mock()
        b.client.get_open_orders.return_value=[dict(coin='BTC',oid=1,timestamp=1,reduceOnly=False),
                                               dict(coin='BTC',oid=2,timestamp=1,reduceOnly=True)]
        b.client.get_positions.return_value=[dict(position=dict(coin='BTC',szi='1'))]
        rec=Mock();rec.coin='BTC';b._reconcilers=[rec]
        b._pending_signals_lock=threading.Lock();b._pending_signals={100:dict(coin='BTC')}
        b._expire_entries('BTC',1000)
        b.client.cancel_order.assert_called_once_with('BTC',1)
        b.client.cancel_all_orders.assert_not_called()
        rec.periodic_check.assert_called_once_with(force=True)
        self.assertEqual(b._pending_signals,{})
