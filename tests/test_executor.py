"""Order executor: protected entries, stop maintenance, exits and reconciliation."""
import unittest
from unittest.mock import Mock

from src.executor import OrderExecutor, live_positions, stop_orders
from src.risk.manager import RiskManager

FILLED = dict(status='ok', response=dict(data=dict(statuses=[dict(filled=dict(totalSz='0.01', avgPx='100000', oid=1))])))
RESTING = dict(status='ok', response=dict(data=dict(statuses=[dict(resting=dict(oid=9))])))
REJECTED = dict(status='ok', response=dict(data=dict(statuses=[dict(error='Order could not immediately match')])))


def position(coin='BTC', szi='0.01', entry='100000'):
    return dict(position=dict(coin=coin, szi=szi, entryPx=entry, positionValue='1000', unrealizedPnl='0'))


def stop(oid, trigger, size='0.01', side='A', coin='BTC'):
    return dict(coin=coin, oid=oid, side=side, sz=size, triggerPx=str(trigger), reduceOnly=True, orderType='Stop Market')


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.get_cached_bbo.return_value = {'bid': {'px': '99990'}, 'ask': {'px': '100010'}}
        self.client.bbo_age.return_value = 1
        self.client.round_size.side_effect = lambda coin, size: round(size, 5)
        self.client.round_price.side_effect = lambda coin, px: round(px)
        self.client.get_sz_decimals.return_value = 5
        self.risk = RiskManager(risk_per_trade=0.01, max_open_positions=3)
        self.risk.update_equity(1000)
        self.ex = OrderExecutor(self.client, self.risk)

    def test_entry_is_ioc_sized_by_risk_and_immediately_protected(self):
        self.client.place_ioc.return_value = FILLED
        self.client.get_positions.return_value = [position()]
        self.client.place_stop.return_value = RESTING
        outcome = self.ex.enter('BTC', 1, 98000.0)
        self.assertEqual(outcome['status'], 'entered')
        coin, is_buy, size, limit = self.client.place_ioc.call_args.args
        self.assertTrue(is_buy)
        self.assertAlmostEqual(size, round(1000 * 0.01 / (100010 - 98000), 5))
        self.assertAlmostEqual(limit, 100010 * 1.003)
        self.client.place_stop.assert_called_once_with('BTC', False, 0.01, 98000.0, 0.03)
        self.assertEqual(self.risk.state.daily_trades, 1)

    def test_entry_blocked_with_explicit_reason_and_skips_invalid_stop(self):
        self.risk.pause_execution('network')
        self.assertIn('Execution paused', self.ex.enter('BTC', 1, 98000.0)['reason'])
        self.client.place_ioc.assert_not_called()
        risk = RiskManager(risk_per_trade=0.01)
        risk.update_equity(1000)
        ex = OrderExecutor(self.client, risk)
        self.assertEqual(ex.enter('BTC', 1, 100500.0)['status'], 'skipped')
        tiny = RiskManager(risk_per_trade=0.00001)
        tiny.update_equity(1000)
        self.assertIn('minimum', OrderExecutor(self.client, tiny).enter('BTC', 1, 98000.0)['reason'])

    def test_rejected_protection_closes_position_and_pauses_once(self):
        self.client.place_ioc.side_effect = [FILLED, FILLED]
        self.client.get_positions.side_effect = [[position()], []]
        self.client.place_stop.return_value = dict(status='err', response='Only post-only orders allowed')
        outcome = self.ex.enter('BTC', 1, 98000.0)
        self.assertEqual(outcome['status'], 'closed')
        close = self.client.place_ioc.call_args_list[1]
        self.assertTrue(close.kwargs['reduce_only'])
        self.assertTrue(self.risk.state.execution_paused)
        self.assertEqual(self.risk.state.recovery_count, 1)

    def test_fill_is_protected_from_the_fill_report_even_if_position_read_lags(self):
        self.client.place_ioc.return_value = FILLED
        self.client.get_positions.side_effect = AssertionError('position read must not gate protection')
        self.client.place_stop.return_value = RESTING
        self.assertEqual(self.ex.enter('BTC', 1, 98000.0)['status'], 'entered')
        self.client.place_stop.assert_called_once_with('BTC', False, 0.01, 98000.0, 0.03)

    def test_failed_close_after_rejected_stop_is_not_reported_closed(self):
        self.client.place_ioc.side_effect = [FILLED, RuntimeError('exchange down')]
        self.client.get_positions.return_value = [position()]
        self.client.place_stop.side_effect = TimeoutError()
        outcome = self.ex.enter('BTC', 1, 98000.0)
        self.assertEqual(outcome['status'], 'unknown')
        self.assertTrue(self.risk.state.execution_paused)

    def test_unknown_submission_outcome_pauses_without_resending(self):
        self.client.place_ioc.side_effect = TimeoutError()
        self.assertEqual(self.ex.enter('BTC', 1, 98000.0)['status'], 'unknown')
        self.assertEqual(self.client.place_ioc.call_count, 1)
        self.assertTrue(self.risk.state.execution_paused)

    def test_unfilled_ioc_leaves_no_exposure(self):
        self.client.place_ioc.return_value = REJECTED
        self.assertEqual(self.ex.enter('BTC', 1, 98000.0)['status'], 'unfilled')
        self.client.place_stop.assert_not_called()

    def test_stop_moves_by_placing_new_before_cancelling_old(self):
        live = live_positions([position()])['BTC']
        self.client.place_stop.return_value = RESTING
        calls = []
        self.client.place_stop.side_effect = lambda *a: calls.append('place') or RESTING
        self.client.cancel_order.side_effect = lambda *a: calls.append('cancel')
        self.assertTrue(self.ex.ensure_protection('BTC', live, 99000.0, [stop(5, 98000)]))
        self.assertEqual(calls, ['place', 'cancel'])
        self.client.cancel_order.assert_called_with('BTC', 5)

    def test_matching_stop_is_kept_and_duplicates_cancelled(self):
        live = live_positions([position()])['BTC']
        self.assertTrue(self.ex.ensure_protection('BTC', live, 98000.0, [stop(5, 98000)]))
        self.client.place_stop.assert_not_called()
        self.client.cancel_order.assert_not_called()
        self.assertTrue(self.ex.ensure_protection('BTC', live, 98000.0, [stop(5, 98000), stop(6, 98000)]))
        self.client.place_stop.assert_not_called()
        self.client.cancel_order.assert_called_once_with('BTC', 6)

    def test_undersized_stop_is_replaced(self):
        live = live_positions([position(szi='0.02')])['BTC']
        self.client.place_stop.return_value = RESTING
        self.assertTrue(self.ex.ensure_protection('BTC', live, 98000.0, [stop(5, 98000, size='0.01')]))
        self.client.place_stop.assert_called_once_with('BTC', False, 0.02, 98000.0, 0.03)

    def test_close_keeps_stops_until_flat(self):
        self.client.get_positions.side_effect = [[position()], [position(szi='0.004')]]
        self.client.place_ioc.return_value = FILLED
        outcome = self.ex.close('BTC', 'Exit signal')
        self.assertEqual(outcome['status'], 'partial')
        self.client.cancel_all_orders.assert_not_called()
        self.client.get_positions.side_effect = [[position()], []]
        self.assertEqual(self.ex.close('BTC', 'Exit signal')['status'], 'closed')
        self.client.cancel_all_orders.assert_called_once_with('BTC')

    def test_reconcile_protects_unadopted_positions_and_cancels_orphans(self):
        self.client.place_stop.return_value = RESTING
        positions = live_positions([position(), position('ETH', '-1', '3000')])
        orders = [stop(1, 98000, size='0.01'),
                  dict(coin='SOL', oid=2, reduceOnly=True, side='A', sz='1', orderType='Stop Market', triggerPx='1'),
                  dict(coin='BTC', oid=3, reduceOnly=False, side='B', sz='0.01', orderType='Limit')]
        problems = self.ex.reconcile(positions, orders, {})
        self.assertEqual(problems, [])
        placed = self.client.place_stop.call_args.args
        self.assertEqual(placed[:3], ('ETH', True, 1.0))
        self.assertAlmostEqual(placed[3], 3000 * 1.03)  # Fallback stop until the strategy adopts it.
        cancelled = {c.args[1] for c in self.client.cancel_order.call_args_list}
        self.assertEqual(cancelled, {2, 3})

    def test_stop_order_filter_requires_reduce_only_trigger_on_exit_side(self):
        orders = [stop(1, 98000), dict(stop(2, 98000), side='B'), dict(stop(3, 98000), reduceOnly=False),
                  dict(stop(4, 98000), orderType='Take Profit Market'), dict(stop(5, 0))]
        self.assertEqual([o['oid'] for o in stop_orders(orders, 'BTC', 1)], [1])


if __name__ == '__main__':
    unittest.main()
