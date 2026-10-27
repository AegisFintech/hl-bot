"""Prospective equity bridge and bounded public testnet account-event retrieval."""
import hashlib
import json
import math
import threading
import time
from pathlib import Path
import requests
from src.storage import transaction


class AccountAudit:
    def __init__(self, path, ledger, funding_path, address):
        self.path, self.ledger, self.funding_path, self.address = Path(path), ledger, funding_path, address
        self.stop_event = threading.Event()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with transaction(self.path) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS account_baseline(id INTEGER PRIMARY KEY CHECK(id=1),time INTEGER,equity REAL,unrealized REAL);
                CREATE TABLE IF NOT EXISTS account_samples(time INTEGER PRIMARY KEY,equity REAL,unrealized REAL);
                CREATE TABLE IF NOT EXISTS account_events(id TEXT PRIMARY KEY,time INTEGER,kind TEXT,amount REAL,raw TEXT);
                CREATE TABLE IF NOT EXISTS account_coverage(kind TEXT PRIMARY KEY,start INTEGER,through INTEGER,updated REAL,error TEXT);
            ''')

    def sample(self, snapshot):
        stamp = int(snapshot['timestamp'] * 1000)
        equity, unrealized = float(snapshot['equity']), float(snapshot['unrealized_pnl'])
        if not all(math.isfinite(v) for v in (equity, unrealized)) or equity <= 0:
            raise ValueError('Untrustworthy equity bridge sample')
        with transaction(self.path) as db:
            db.execute('INSERT OR IGNORE INTO account_baseline VALUES (1,?,?,?)', (stamp,equity,unrealized))
            # One current sample per minute; never replace the permanent baseline.
            bucket = stamp // 60000 * 60000
            exists = db.execute('SELECT 1 FROM account_samples WHERE time>=? AND time<?', (bucket,bucket+60000)).fetchone()
            if not exists:
                db.execute('INSERT INTO account_samples VALUES (?,?,?)', (stamp,equity,unrealized))
            db.execute('DELETE FROM account_samples WHERE time<?', (stamp-7*86400000,))
            start = db.execute('SELECT time FROM account_baseline WHERE id=1').fetchone()[0]
            for kind in ('fills','ledger'):
                db.execute('INSERT OR IGNORE INTO account_coverage VALUES (?,?,?,0,NULL)', (kind,start,start))

    @staticmethod
    def cash_amount(delta):
        # Unsupported movements remain unknown, never silently zero.
        kind = delta.get('type')
        if kind in ('deposit','withdraw'):
            amount = float(delta['usdc'])
            if not math.isfinite(amount) or amount < 0 or delta.get('fee') not in (None,0,'0'):
                return None
            return amount if kind == 'deposit' else -amount
        return None

    def step(self, post, now):
        with transaction(self.path) as db:
            cursors = db.execute('SELECT kind,start,through FROM account_coverage').fetchall()
        for kind,start,cursor in cursors:
            end = min(int(now*1000)-30000,cursor+86400000)
            if end <= cursor:
                continue
            begin = max(start,cursor-60000)
            for _ in range(20):
                rows = post(dict(type='userFillsByTime' if kind=='fills' else 'userNonFundingLedgerUpdates',
                                 user=self.address,startTime=begin,endTime=end))
                if not isinstance(rows,list):
                    raise ValueError('Invalid account history response')
                if len(rows)<500:
                    break
                end=(begin+end)//2
                if end<=cursor:
                    raise ValueError('Account history page capacity; coverage not advanced')
            else:
                raise ValueError('Account pagination stalled')
            events=[]
            for row in rows:
                stamp=int(row['time'])
                if not begin<=stamp<=end:
                    raise ValueError('Account row outside requested interval')
                if kind=='fills':
                    values=[float(row[k]) for k in ('px','sz','fee','closedPnl')]
                    if not all(math.isfinite(v) for v in values) or values[0]<=0 or values[1]<=0 or row.get('side') not in ('A','B'):
                        raise ValueError('Malformed account fill')
                else:
                    raw=json.dumps(row,sort_keys=True)
                    events.append((hashlib.sha256(raw.encode()).hexdigest(),stamp,row['delta']['type'],self.cash_amount(row['delta']),raw))
            if kind=='fills':
                for row in rows:
                    self.ledger.add(row)  # Evidence import only; never fabricated arrival quotes.
            with transaction(self.path) as db:
                db.executemany('INSERT OR IGNORE INTO account_events VALUES (?,?,?,?,?)',events)
                db.execute('UPDATE account_coverage SET through=?,updated=?,error=NULL WHERE kind=?',(end,now,kind))

    def summary(self):
        with transaction(self.path,rows=True) as db:
            base=db.execute('SELECT * FROM account_baseline WHERE id=1').fetchone()
            cover=[dict(r) for r in db.execute('SELECT * FROM account_coverage')]
            events=[dict(r) for r in db.execute('SELECT * FROM account_events')]
        if not base:
            return dict(status='unavailable',reason='No trustworthy prospective baseline')
        with transaction(self.funding_path,rows=True) as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            fs=db.execute('SELECT * FROM funding_state WHERE id=1').fetchone() if 'funding_state' in tables else None
            funding=[dict(r) for r in db.execute('SELECT time,usdc FROM funding')] if fs else []
        cutoff=min([r['through'] for r in cover]+[fs['through_ms'] if fs else base['time']])
        with transaction(self.path,rows=True) as db:
            end=db.execute('SELECT * FROM account_samples WHERE time<=? ORDER BY time DESC LIMIT 1',(cutoff,)).fetchone()
        if not end or end['time']<=base['time']:
            return dict(status='warming_up',baseline_at=base['time'],coverage=cover,reason='Waiting for a later account sample covered by funding and fill/ledger retrieval')
        start,finish=base['time'],end['time']
        fills=[f for f in self.ledger.fills(1000000) if start<int(f['time'])<=finish]
        gross=sum(float(f.get('closedPnl',0)) for f in fills)
        fees=sum(float(f.get('fee',0)) for f in fills)
        payments=sum(r['usdc'] for r in funding if start<r['time']<=finish)
        selected=[r for r in events if start<r['time']<=finish]
        unknown=sum(r['amount'] is None for r in selected)
        cash=sum(r['amount'] for r in selected if r['amount'] is not None)
        unrealized=end['unrealized']-base['unrealized']
        actual=end['equity']-base['equity'];explained=gross-fees+payments+cash+unrealized
        reasons=[]
        if unknown: reasons.append('Unsupported account movements')
        if any(f.get('feeToken','USDC').strip()!='USDC' for f in fills): reasons.append('Non-USDC fee valuation unavailable')
        if any(r['error'] for r in cover) or not fs or fs['error']: reasons.append('History synchronization error')
        if fs and fs['start_ms']>start: reasons.append('Funding coverage starts after baseline')
        residual=actual-explained
        if abs(residual)>0.0001: reasons.append('Equity residual exceeds 0.0001 USDC tolerance')
        return dict(status='review_required' if reasons else 'within_tolerance',baseline_at=start,through=finish,
                    baseline_equity=base['equity'],equity=end['equity'],equity_change=actual,gross=gross,fees=fees,
                    funding=payments,known_cash_movements=cash,unknown_movements=unknown,unrealized_change=unrealized,
                    explained_change=explained,unexplained=residual,reasons=reasons,coverage=cover,
                    scope='Prospective bridge only; local REST completion times and (baseline,end] event timestamps are not atomic exchange snapshots. Coverage means retrieved windows, not independent proof of completeness. Unsupported movements stay unknown. Same-millisecond boundaries and reporting delays may create residuals. No risk baseline changes.')

    def start(self):
        threading.Thread(target=self._run,name='testnet-account-audit',daemon=True).start()

    def _run(self):
        with requests.Session() as session:
            def post(payload):
                r=session.post('https://api.hyperliquid-testnet.xyz/info',json=payload,timeout=10)
                r.raise_for_status();return r.json()
            while not self.stop_event.is_set():
                try:
                    self.step(post,time.time())
                    delay=60
                except Exception as exc:
                    with transaction(self.path) as db:
                        db.execute('UPDATE account_coverage SET error=?',(type(exc).__name__,))
                    delay=60
                self.stop_event.wait(delay)
