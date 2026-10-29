import unittest
from types import SimpleNamespace
from src.dashboard import app as dashboard

class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.previous=dashboard._bot_ref
        self.client=dashboard.app.test_client()
        dashboard.set_bot_reference(None)
    def tearDown(self):dashboard.set_bot_reference(self.previous)
    def test_disconnected_terminal_is_explicit(self):
        r=self.client.get('/api/terminal')
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json['status']['status'],'not_connected')
        self.assertTrue(r.json['errors'])
    def test_dashboard_serves_local_assets_and_headers(self):
        r=self.client.get('/')
        self.assertIn(b'Command center',r.data)
        self.assertIn(b'/static/terminal.js',r.data)
        self.assertEqual(r.headers['X-Content-Type-Options'],'nosniff')
        for path in ['/static/terminal.js','/static/terminal.css']:
            result=self.client.get(path)
            self.assertEqual(result.status_code,200)
            result.close()
    def test_csv_is_downloadable_without_bot(self):
        r=self.client.get('/api/export/fills.csv')
        self.assertIn('attachment',r.headers['Content-Disposition'])
        self.assertIn(b'closedPnl',r.data)
    def test_export_neutralizes_formula_in_text_fields(self):
        dashboard.set_bot_reference(SimpleNamespace(ledger=SimpleNamespace(fills=lambda n:[dict(coin='=HYPERLINK(1)',dir='+bad',time=1)])))
        r=self.client.get('/api/export/fills.csv')
        self.assertIn(b"'=HYPERLINK",r.data)

    def test_research_disconnected_is_explicit(self):
        r=self.client.get('/api/research')
        self.assertEqual(r.status_code,503)
        self.assertEqual(r.json['mode'],'Observation only')

    def test_research_api_is_read_only_and_exposes_observer_snapshot(self):
        snapshot={'mode':'Observation only','status':'observing','source':'Mainnet public data'}
        dashboard.set_bot_reference(SimpleNamespace(research=SimpleNamespace(snapshot=lambda:snapshot)))
        self.assertEqual(self.client.get('/api/research').json,snapshot)
        self.assertEqual(self.client.post('/api/research').status_code,405)

    def test_development_registry_is_read_only_and_preserves_gates(self):
        r=self.client.get('/api/development')
        self.assertEqual(r.status_code,200)
        self.assertFalse(r.json['automatic_promotion'])
        self.assertEqual(len(r.json['milestones']),10)
        self.assertTrue(any(h['status'].startswith('blocked') for h in r.json['hypotheses']))
        self.assertEqual(self.client.post('/api/development').status_code,405)


class TerminalSnapshotTests(unittest.TestCase):
    """The terminal must never multiply exchange reads or fail as a whole."""

    def setUp(self):
        from unittest.mock import Mock
        import time
        self.previous = dashboard._bot_ref
        dashboard._terminal_cache, dashboard._terminal_at = {}, 0.0
        dashboard._slow_cache.clear()
        bot = Mock()
        bot.running, bot.start_time, bot.coin, bot.coins = True, time.time(), 'BTC', ['BTC']
        bot.client.testnet = True
        bot.client.get_cached_bbo.return_value = None
        bot.client.get_cached_candles.return_value = []
        bot.client.get_cached_trades.return_value = []
        bot.client.get_cached_orderbook.return_value = {}
        bot.client.bbo_age.return_value = 1.0
        bot.client.candle_health.return_value = {'eligible': True}
        bot.risk_manager.get_state_dict.return_value = {'halted': False}
        bot.account_snapshot = {'timestamp': time.time(), 'equity': 1000}
        bot.exchange_snapshot = {'positions': [{'position': {'coin': 'BTC'}}], 'orders': [], 'time': time.time()}
        bot.ledger.performance.return_value = {}
        bot.ledger.equity.return_value = []
        bot.ledger.fills.return_value = []
        bot.quality.summary.side_effect = RuntimeError('database is locked')
        bot.execution.summary.return_value = {}
        bot.account_audit.summary.return_value = {}
        bot.operations.summary.return_value = {'responsive': True}
        bot.research.snapshot.return_value = {'mode': 'Observation only'}
        bot.strategy_status.return_value = {'reason': 'Inside channel'}
        bot.chart_levels.return_value = []
        bot.strategy.label, bot.settings.interval = 'donchian(entry=20)', '1h'
        bot.halt_cleanup_status, bot.startup_status = 'Not required', 'Ready'
        self.bot = bot
        dashboard.set_bot_reference(bot)
        self.client = dashboard.app.test_client()

    def tearDown(self):
        dashboard.set_bot_reference(self.previous)
        dashboard._terminal_cache, dashboard._terminal_at = {}, 0.0

    def test_terminal_uses_cached_snapshot_and_isolates_failing_sections(self):
        r = self.client.get('/api/terminal')
        self.assertEqual(r.status_code, 200)
        body = r.json
        self.assertEqual(body['positions'], [{'position': {'coin': 'BTC'}}])
        self.bot.client.get_positions.assert_not_called()
        self.bot.client.get_open_orders.assert_not_called()
        self.assertEqual(body['quality'], {'status': 'unavailable'})
        self.assertIn('quality unavailable', body['errors'])
        self.assertEqual(body['strategy'], {'reason': 'Inside channel'})
        self.assertEqual(body['status']['strategy'], 'donchian(entry=20)')

    def test_slow_summaries_are_cached_between_rebuilds(self):
        self.bot.quality.summary.side_effect = None
        self.bot.quality.summary.return_value = {'decisions': 1}
        self.client.get('/api/terminal')
        dashboard._terminal_at = 0.0
        self.client.get('/api/terminal')
        self.assertEqual(self.bot.quality.summary.call_count, 1)
        self.assertEqual(self.bot.ledger.performance.call_count, 2)

    def test_positions_orders_and_account_endpoints_never_call_exchange(self):
        self.assertEqual(self.client.get('/api/positions').json, [{'position': {'coin': 'BTC'}}])
        self.assertEqual(self.client.get('/api/orders').json, [])
        self.bot.client.master_account, self.bot.client.wallet.address = '0xm', '0xa'
        self.assertEqual(self.client.get('/api/account').json['master_account'], '0xm')
        self.client.get('/api/fills')
        self.bot.client.info.user_fills.assert_not_called()
        self.bot.client.get_positions.assert_not_called()
