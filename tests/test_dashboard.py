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
