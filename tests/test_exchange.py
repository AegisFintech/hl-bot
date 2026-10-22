import threading
import unittest
from unittest.mock import Mock
from src.exchange.hyperliquid import HyperliquidClient

class ExchangeTests(unittest.TestCase):
    def client(self):
        c=HyperliquidClient.__new__(HyperliquidClient)
        c.exchange=Mock();c.round_size=lambda coin,size:size;c.round_price=lambda coin,p:p
        return c
    def test_stop_is_reduce_only_market_with_slippage_budget(self):
        c=self.client();c.place_order_with_tpsl('BTC',True,1,100,102,99,tif='Alo')
        orders=c.exchange.bulk_orders.call_args.args[0]
        self.assertTrue(orders[2]['order_type']['trigger']['isMarket'])
        self.assertTrue(orders[2]['reduce_only'])
        self.assertLess(orders[2]['limit_px'],99)
        self.assertEqual(orders[0]['order_type']['limit']['tif'],'Alo')
        c.place_trigger_orders('BTC',True,1,98,101)
        stop=c.exchange.bulk_orders.call_args.args[0][1]
        self.assertGreater(stop['limit_px'],101)
        self.assertTrue(stop['order_type']['trigger']['isMarket'])
    def test_unified_equity_uses_total_plus_unrealized_not_available_margin(self):
        c=self.client();c._abstraction='unifiedAccount'
        c.get_user_state=lambda:dict(marginSummary=dict(accountValue='10',totalMarginUsed='5'),assetPositions=[dict(position=dict(unrealizedPnl='-2'))])
        c.get_spot_user_state=lambda:dict(balances=[dict(coin='USDC',total='1000')],tokenToAvailableAfterMaintenance=[[0,'900']])
        self.assertEqual(c.get_account_snapshot()['equity'],998)
    def test_size_rounding_never_increases_risk(self):
        c=self.client();c.get_sz_decimals=lambda coin:5
        self.assertEqual(HyperliquidClient.round_size(c,'BTC',0.0002999),0.00029)
