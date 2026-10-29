import time
import threading
import unittest
from unittest.mock import Mock, patch

from src.exchange import hyperliquid
from src.exchange.hyperliquid import HyperliquidClient, WeightBudget, info_weight, order_status, retrying_post


class ExchangeTests(unittest.TestCase):
    def client(self):
        c = HyperliquidClient.__new__(HyperliquidClient)
        c.exchange = Mock()
        c.round_size = lambda coin, size: size
        c.round_price = lambda coin, p: p
        c.execution_journal = None
        return c

    def test_stop_is_reduce_only_market_with_slippage_budget(self):
        c = self.client()
        c.place_order_with_tpsl('BTC', True, 1, 100, 102, 99, tif='Alo')
        orders = c.exchange.bulk_orders.call_args.args[0]
        self.assertTrue(orders[2]['order_type']['trigger']['isMarket'])
        self.assertTrue(orders[2]['reduce_only'])
        self.assertLess(orders[2]['limit_px'], 99)
        self.assertEqual(orders[0]['order_type']['limit']['tif'], 'Alo')
        c.place_trigger_orders('BTC', True, 1, 98, 101)
        stop = c.exchange.bulk_orders.call_args.args[0][1]
        self.assertGreater(stop['limit_px'], 101)
        self.assertTrue(stop['order_type']['trigger']['isMarket'])

    def test_protective_stop_and_ioc_payloads(self):
        c = self.client()
        c.place_stop('ETH', False, 2, 3000, slippage=0.03)
        args, kwargs = c.exchange.order.call_args
        self.assertEqual(args[:3], ('ETH', False, 2))
        self.assertAlmostEqual(args[3], 3000 * 0.97)
        self.assertEqual(args[4], {'trigger': {'triggerPx': 3000, 'isMarket': True, 'tpsl': 'sl'}})
        self.assertTrue(kwargs['reduce_only'])
        c.place_ioc('ETH', True, 1, 3010)
        args, kwargs = c.exchange.order.call_args
        self.assertEqual(args[4], {'limit': {'tif': 'Ioc'}})
        self.assertFalse(kwargs['reduce_only'])

    def test_unified_equity_uses_total_plus_unrealized_not_available_margin(self):
        c = self.client()
        c._abstraction = 'unifiedAccount'
        c.get_user_state = lambda: dict(marginSummary=dict(accountValue='10', totalMarginUsed='5'),
                                        assetPositions=[dict(position=dict(unrealizedPnl='-2'))])
        c.get_spot_user_state = lambda: dict(balances=[dict(coin='USDC', total='1000')],
                                             tokenToAvailableAfterMaintenance=[[0, '900']])
        self.assertEqual(c.get_account_snapshot()['equity'], 998)

    def test_size_rounding_never_increases_risk(self):
        c = self.client()
        c.get_sz_decimals = lambda coin: 5
        self.assertEqual(HyperliquidClient.round_size(c, 'BTC', 0.0002999), 0.00029)

    def test_price_rounding_follows_significant_figure_and_decimal_rules(self):
        c = HyperliquidClient.__new__(HyperliquidClient)
        decimals = {'BTC': 5, 'ETH': 4, 'SOL': 2, 'DOGE': 0}
        c.get_sz_decimals = lambda coin: decimals[coin]
        self.assertEqual(c.round_price('BTC', 112345.67), 112346.0)  # Integers always valid.
        self.assertEqual(c.round_price('BTC', 98765.43), 98765.0)    # Five significant figures.
        self.assertEqual(c.round_price('ETH', 3456.789), 3456.8)
        self.assertEqual(c.round_price('SOL', 187.6543), 187.65)
        self.assertEqual(c.round_price('DOGE', 0.1234567), 0.12346)
        for bad in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                c.round_price('BTC', bad)

    def test_order_status_handles_fills_rests_and_account_level_errors(self):
        filled = dict(status='ok', response=dict(data=dict(statuses=[dict(filled=dict(totalSz='1', avgPx='10', oid=5))])))
        self.assertEqual(order_status(filled), ('filled', dict(totalSz='1', avgPx='10', oid=5)))
        resting = dict(status='ok', response=dict(data=dict(statuses=[dict(resting=dict(oid=7))])))
        self.assertEqual(order_status(resting)[0], 'resting')
        self.assertEqual(order_status(dict(status='ok', response=dict(data=dict(statuses=[dict(error='Post only')]))))
                         , ('error', 'Post only'))
        self.assertEqual(order_status(dict(status='err', response='User or API Wallet does not exist.'))[0], 'error')
        self.assertEqual(order_status(None)[0], 'error')
        self.assertEqual(order_status(dict(status='ok', response=dict(data=dict(statuses=['waitingForFill']))))[0],
                         'error')

    def test_info_reads_retry_transient_failures_but_not_bad_requests(self):
        class Rejected(Exception):
            def __init__(self, status):
                self.status_code = status
        budget = WeightBudget(per_minute=10_000)
        calls = []

        def flaky(path, payload):
            calls.append(payload)
            if len(calls) < 3:
                raise (Rejected(429) if len(calls) == 1 else ConnectionError())
            return {'ok': True}
        with patch.object(hyperliquid.time, 'sleep'):
            self.assertEqual(retrying_post(flaky, budget)('/info', {'type': 'meta'}), {'ok': True})
            self.assertEqual(len(calls), 3)
            bad = Mock(side_effect=Rejected(422))
            with self.assertRaises(Rejected):
                retrying_post(bad, budget)('/info', {'type': 'meta'})
            self.assertEqual(bad.call_count, 1)
            dead = Mock(side_effect=ConnectionError())
            with self.assertRaises(ConnectionError):
                retrying_post(dead, budget, attempts=2)('/info', {'type': 'meta'})

    def test_weight_budget_and_request_weights(self):
        self.assertEqual(info_weight({'type': 'clearinghouseState'}), 2)
        self.assertEqual(info_weight({'type': 'frontendOpenOrders'}), 20)
        self.assertEqual(info_weight({'type': 'userRole'}), 60)
        budget = WeightBudget(per_minute=60)
        start = time.monotonic()
        budget.acquire(60)
        self.assertLess(time.monotonic() - start, 0.5)
        with patch.object(hyperliquid.time, 'sleep') as sleep:
            sleep.side_effect = lambda s: setattr(budget, 'tokens', budget.capacity)
            budget.acquire(30)
            sleep.assert_called()

    def test_preflight_rejects_missing_or_expired_api_wallet(self):
        c = HyperliquidClient.__new__(HyperliquidClient)
        c.master_account = '0xmaster'
        c.wallet = Mock(address='0xAgent')
        c.info = Mock()
        c.info.query_sub_accounts.return_value = []
        c.info.extra_agents.return_value = [dict(address='0xagent', validUntil=int(time.time() * 1000) + 86_400_000)]
        self.assertTrue(c.preflight_check_agent()['agent_registered'])
        c.info.extra_agents.return_value = [dict(address='0xagent', validUntil=int(time.time() * 1000) - 1)]
        self.assertFalse(c.preflight_check_agent()['agent_registered'])
        c.info.extra_agents.return_value = []
        self.assertFalse(c.preflight_check_agent()['agent_registered'])

    def ws_client(self):
        c = HyperliquidClient.__new__(HyperliquidClient)
        c._ws_info, c._ws_subscriptions, c._ws_monitor = None, [], None
        c._lock = threading.Lock()
        c._bbo_times = {}
        c._start_ws_monitor = Mock()
        return c

    def test_subscriptions_are_recorded_once_and_replayed_on_connect(self):
        c = self.ws_client()
        infos = []

        class FakeInfo:
            def __init__(self, *args, **kwargs):
                self.subs = []
                infos.append(self)

            def subscribe(self, sub, handler):
                self.subs.append(sub)
        c.base_url = 'https://api.hyperliquid-testnet.xyz'
        with patch.object(hyperliquid, 'Info', FakeInfo):
            c._subscribe({'type': 'bbo', 'coin': 'BTC'}, Mock())
            c._subscribe({'type': 'orderUpdates', 'user': 'u'}, Mock())
            c._subscribe({'type': 'orderUpdates', 'user': 'u'}, Mock())  # Retry must not double-subscribe.
            self.assertEqual(len(infos), 1)
            self.assertEqual(len(infos[0].subs), 2)
            c._connect_ws()
            self.assertEqual(infos[-1].subs, [{'type': 'bbo', 'coin': 'BTC'}, {'type': 'orderUpdates', 'user': 'u'}])

    def test_websocket_watchdog_detects_dead_socket_and_silent_quotes(self):
        c = self.ws_client()
        manager = Mock()
        manager.ws.keep_running = True
        manager.is_alive.return_value = True
        c._ws_info = Mock(ws_manager=manager)
        c._ws_subscriptions = [({'type': 'bbo', 'coin': 'BTC'}, None), ({'type': 'bbo', 'coin': 'ETH'}, None)]
        c._ws_started_at = time.time() - 300
        c._bbo_times = {'BTC': time.time(), 'ETH': time.time() - 600}
        self.assertEqual(c._ws_problem(), '')  # Only the liquid primary market is watched.
        c._bbo_times['BTC'] = time.time() - 120
        self.assertIn('BTC quotes silent', c._ws_problem())
        c._bbo_times['BTC'] = time.time()
        manager.is_alive.return_value = False
        self.assertEqual(c._ws_problem(), 'disconnected')


if __name__ == '__main__':
    unittest.main()
