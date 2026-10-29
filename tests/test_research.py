import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.research.microstructure import Microstructure, normalize_book, active_blocks
from src.research.journal import ResearchJournal
from src.research.service import ResearchService, divergence


def book(now=1000,bid_size=10,ask_size=1):
    return {'time':now*1000,'levels':[
        [{'px':str(100-i*.01),'sz':str(bid_size if i==0 else 1)} for i in range(20)],
        [{'px':str(100.02+i*.01),'sz':str(ask_size if i==0 else 1)} for i in range(20)]]}

class MicrostructureTests(unittest.TestCase):
    def test_stale_crossed_and_nonfinite_books_rejected(self):
        with self.assertRaises(ValueError):normalize_book(book(),1016)
        raw=book();raw['levels'][1][0]['px']='99'
        with self.assertRaises(ValueError):normalize_book(raw,1000)
        raw=book();raw['levels'][0][0]['sz']='NaN'
        with self.assertRaises(ValueError):normalize_book(raw,1000)

    def test_trade_dedup_and_signed_execution(self):
        engine=Microstructure(whale_usd=500)
        trade=dict(tid=1,time=1000000,px='100',sz='10',side='A')
        engine.ingest_trades([trade,trade],1000)
        result=engine.analyze(book(),1000)
        self.assertEqual(result['flow']['count'],1)
        self.assertEqual(result['flow']['imbalance'],-1)
        self.assertEqual(len(result['large_trades']),1)

    def test_absorption_requires_time_flow_and_persistent_wall(self):
        engine=Microstructure(whale_usd=500)
        initial=engine.analyze(book(),1000)
        self.assertIsNone(initial['absorption'])
        for now in range(1005,1051,5):
            engine.ingest_trades([dict(tid=now,time=now*1000,px='100',sz='10',side='A')],now)
            result=engine.analyze(book(now),now)
        self.assertEqual(result['absorption'],'bullish')
        self.assertGreater(result['walls'][0]['observed_refill_usd'],0)
        self.assertGreaterEqual(result['walls'][0]['persistence_s'],45)

    def test_walls_do_not_survive_observation_gaps(self):
        engine=Microstructure(whale_usd=500)
        engine.analyze(book(),1000)
        result=engine.analyze(book(1020),1020)
        self.assertEqual(result['walls'][0]['persistence_s'],0)
        with self.assertRaises(ValueError):engine.analyze(book(1020),1020)

    def test_persistence_resets_when_level_falls_below_wall_threshold(self):
        engine=Microstructure(whale_usd=500)
        engine.analyze(book(),1000)
        engine.analyze(book(1005,bid_size=1),1005)
        result=engine.analyze(book(1010),1010)
        self.assertEqual(result['walls'][0]['persistence_s'],0)

    def test_band_coverage_is_explicit(self):
        result=Microstructure().analyze(book(),1000)
        self.assertFalse(result['bands'][-1]['bid_complete'])
        self.assertFalse(result['bands'][-1]['ask_complete'])
        self.assertLess(result['symmetric_depth_bps'],25)

    def test_no_order_block_from_unclosed_candles(self):
        candles=[dict(t=1000000+i*60000,o=100,h=101,l=99,c=100,v=1) for i in range(5)]
        self.assertEqual(active_blocks(candles,1000),[])

class JournalTests(unittest.TestCase):
    def test_prospective_costs_baseline_and_idempotence(self):
        with tempfile.TemporaryDirectory() as d:
            journal=ResearchJournal(Path(d)/'r.sqlite')
            s=dict(sampled_at=1000,bid=99.99,ask=100.01,mid=100)
            self.assertTrue(journal.signal('book_flow',1,s,'test'))
            self.assertFalse(journal.signal('book_flow',1,s,'test'))
            journal.mark(dict(s,sampled_at=1009))
            self.assertEqual(journal.summary()['results'],[])
            journal.mark(dict(s,sampled_at=1010))
            journal.mark(dict(s,sampled_at=1010))
            row=journal.summary()['results'][0]
            self.assertEqual(row['n'],1)
            self.assertLess(row['mean_net_bps'],-13)
            journal.mark(dict(s,sampled_at=1100))
            self.assertEqual(journal.summary()['missed_markouts'],1)

    def test_restart_preserves_pending_events_and_long_short_controls(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'r.sqlite';j=ResearchJournal(path)
            s=dict(sampled_at=1000,bid=100,ask=100.02,mid=100.01)
            j.signal('baseline',1,s,'control');j.signal('baseline',-1,s,'control')
            restarted=ResearchJournal(path)
            restarted.mark(dict(s,sampled_at=1060,bid=101,ask=101.02,mid=101.01))
            rows=restarted.summary()['results']
            self.assertEqual(sum(r['n'] for r in rows),2)
            self.assertEqual(restarted.summary()['signal_count'],2)

class SourceTests(unittest.TestCase):
    def test_divergence_deducts_four_leg_costs_and_normalizes_fx(self):
        raw=dict(bid=100,ask=100.02)
        spot={'bids':[['99.9','2']],'asks':[['99.92','2']]}
        fx={'bids':[['.9999','2']],'asks':[['1.0001','2']]}
        result=divergence(raw,spot,fx)
        self.assertAlmostEqual(result['modeled_roundtrip_cost_bps'],137)
        self.assertLess(result['net_candidate_bps'],0)

    def test_stale_snapshot_suppresses_direction(self):
        with tempfile.TemporaryDirectory() as d:
            service=ResearchService(Path(d)/'r.sqlite',wallets=[])
            service._state['market']=dict(source_time=1000,score=90,lean='bullish')
            with patch('time.time',return_value=1016):result=service.snapshot()
            self.assertEqual(result['status'],'stale')
            self.assertIsNone(result['market']['score'])
            self.assertEqual(result['market']['lean'],'unavailable')
            self.assertNotIn('divergence',result)

    def test_wallets_only_accept_bounded_explicit_addresses(self):
        with tempfile.TemporaryDirectory() as d:
            service=ResearchService(Path(d)/'r.sqlite',wallets=['bad','0x'+'1'*40]*5)
            self.assertEqual(len(service.wallets),3)
            self.assertFalse(hasattr(service,'exchange'))

class CoverageTests(unittest.TestCase):
    def test_partial_stream_cannot_create_trade_imbalance_or_absorption(self):
        engine=Microstructure(whale_usd=500)
        engine.ingest_trades([dict(tid=1,time=1000000,px='100',sz='20',side='B')],1000)
        result=engine.analyze(book(),1000,flow_complete=False)
        self.assertIsNone(result['flow']['imbalance'])
        self.assertFalse(result['flow']['complete'])
        self.assertIsNone(result['absorption'])

    def test_auto_discovery_is_from_fresh_large_public_prints(self):
        with tempfile.TemporaryDirectory() as d:
            service=ResearchService(Path(d)/'r.sqlite',wallets=[])
            addresses=['0x'+'1'*40,'0x'+'2'*40]
            trade=dict(time=1000000,px='100',sz='1001',users=addresses)
            service._discover([dict(trade,sz='1')],1000)
            self.assertEqual(service.wallets,[])
            service._discover([trade],1000)
            self.assertEqual(service.wallets,addresses)

    def test_secondary_source_failure_retains_timestamp_and_reports_error(self):
        with tempfile.TemporaryDirectory() as d:
            service=ResearchService(Path(d)/'r.sqlite',wallets=[])
            with patch('time.time',return_value=1000):service._refresh('context',60,lambda:{'funding_hourly':.0001},1000)
            def fail():raise ValueError('test')
            with patch('time.time',return_value=1061):service._refresh('context',60,fail,1061)
            self.assertEqual(service._slow['context']['updated_at'],1000)
            self.assertIsNotNone(service._slow['context']['error'])

    def test_malformed_comparison_does_not_break_research_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            service=ResearchService(Path(d)/'r.sqlite',wallets=[])
            service._state['market']=dict(source_time=1000,score=0,lean='neutral',bid=100,ask=100.02)
            service._state['sources']={'comparison':{'value':{'spot':{'bids':[],'asks':[]}},'updated_at':1000}}
            with patch('time.time',return_value=1001):result=service.snapshot()
            self.assertNotIn('divergence',result)
            self.assertIn('suppressed',result['sources']['comparison']['error'])

    def test_wallet_size_changes_survive_restart_and_include_closed_positions(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'r.sqlite'
            first=ResearchJournal(path).wallet_changes('public-address',[{'coin':'BTC','szi':'2'}],1000)
            self.assertIsNone(first['previous_at'])
            second=ResearchJournal(path).wallet_changes('public-address',[],1120)
            self.assertEqual(second['deltas'][0]['delta_size'],-2)
            self.assertEqual(second['deltas'][0]['current_size'],0)

    def test_old_published_sentiment_is_stale_even_after_successful_fetch(self):
        with tempfile.TemporaryDirectory() as d:
            service=ResearchService(Path(d)/'r.sqlite',wallets=[])
            service._state['sources']={'sentiment':{'value':{'published_at':1,'value':50},'updated_at':200000}}
            with patch('time.time',return_value=200001):result=service.snapshot()
            self.assertTrue(result['sources']['sentiment']['stale'])


class FailureSuppressionTests(unittest.TestCase):
    def test_failed_cycle_suppresses_recent_lean_and_comparison(self):
        with tempfile.TemporaryDirectory() as d:
            service = ResearchService(Path(d)/'r.sqlite', wallets=[])
            service._state.update(status='unavailable', market=dict(source_time=1000, score=90, lean='bullish', bid=100, ask=100.02))
            service._state['sources'] = {'comparison': {'updated_at': 1000, 'value': {'spot': {'bids': [['100','1']], 'asks': [['101','1']]}}}}
            with patch('time.time', return_value=1001):
                result = service.snapshot()
            self.assertIsNone(result['market']['score'])
            self.assertNotIn('divergence', result)

    def test_failed_comparison_suppresses_cached_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            service = ResearchService(Path(d)/'r.sqlite', wallets=[])
            service._state.update(status='observing', market=dict(source_time=1000, score=0, lean='neutral', bid=100, ask=100.02))
            service._state['sources'] = {'comparison': {'updated_at': 1000, 'error': 'retry', 'value': {'spot': {'bids': [['100','1']], 'asks': [['101','1']]}}}}
            with patch('time.time', return_value=1001):
                result = service.snapshot()
            self.assertNotIn('divergence', result)


class JournalScanTests(unittest.TestCase):
    def test_first_mark_sweeps_history_then_scans_only_open_horizons(self):
        import tempfile
        from pathlib import Path
        from src.research.journal import ResearchJournal, HORIZONS
        with tempfile.TemporaryDirectory() as d:
            journal = ResearchJournal(Path(d) / 'research.sqlite')
            snap = dict(sampled_at=1_000_000.0, bid=99.0, ask=101.0, mid=100.0)
            journal.signal('old', 1, dict(snap, sampled_at=1_000.0), 'stale signal')
            journal.mark(snap)
            with journal.connect() as db:
                statuses = {r[0] for r in db.execute("SELECT status FROM outcomes")}
            self.assertEqual(statuses, {'missed'})
            journal.signal('fresh', 1, dict(snap, sampled_at=snap['sampled_at'] - 5), 'fresh signal')
            later = dict(snap, sampled_at=snap['sampled_at'] + 10)
            journal.mark(later)
            with journal.connect() as db:
                fresh = db.execute("SELECT COUNT(*) FROM outcomes o JOIN signals s ON s.id=o.signal_id "
                                   "WHERE s.kind='fresh' AND o.status='complete'").fetchone()[0]
            self.assertEqual(fresh, 1)
            self.assertGreater(max(HORIZONS), 10)
