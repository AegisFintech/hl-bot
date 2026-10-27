"""Durable submission intent and exchange-ID lifecycle evidence, never price inference."""
import hashlib
import json
import time
import uuid
from pathlib import Path
from src.storage import transaction


class ExecutionJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with transaction(self.path) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS submissions(id TEXT PRIMARY KEY,time REAL,kind TEXT,coin TEXT,request TEXT,result TEXT,error TEXT);
                CREATE TABLE IF NOT EXISTS order_links(coin TEXT,oid TEXT,role TEXT,submission TEXT,PRIMARY KEY(coin,oid));
                CREATE TABLE IF NOT EXISTS order_events(id TEXT PRIMARY KEY,received REAL,event_time REAL,coin TEXT,oid TEXT,status TEXT,raw TEXT);
                CREATE INDEX IF NOT EXISTS submission_time ON submissions(time);
                CREATE INDEX IF NOT EXISTS order_event_time ON order_events(received);
            ''')

    def begin(self, kind, coin, request):
        ident = uuid.uuid4().hex
        with transaction(self.path) as db:
            db.execute('INSERT INTO submissions VALUES (?,?,?,?,?,NULL,NULL)',
                       (ident, time.time(), kind, coin, json.dumps(request)))
        return ident

    def finish(self, ident, coin, result, roles):
        statuses = (result or {}).get('response', {}).get('data', {}).get('statuses', [])
        with transaction(self.path) as db:
            db.execute('UPDATE submissions SET result=? WHERE id=?', (json.dumps(result), ident))
            for role, status in zip(roles, statuses):
                if not isinstance(status, dict):
                    continue
                detail = status.get('resting') or status.get('filled') or {}
                if detail.get('oid') is not None:
                    db.execute('INSERT OR IGNORE INTO order_links VALUES (?,?,?,?)',
                               (coin, str(detail['oid']), role, ident))

    def fail(self, ident, error):
        with transaction(self.path) as db:
            db.execute('UPDATE submissions SET error=? WHERE id=?', (type(error).__name__, ident))

    def event(self, update):
        order = update.get('order', update)
        coin, oid = order.get('coin'), order.get('oid')
        if not coin or oid is None or not update.get('status'):
            return False
        raw = json.dumps(update, sort_keys=True)
        ident = hashlib.sha256(raw.encode()).hexdigest()
        with transaction(self.path) as db:
            result = db.execute('INSERT OR IGNORE INTO order_events VALUES (?,?,?,?,?,?,?)',
                                (ident, time.time(), update.get('statusTimestamp'), coin,
                                 str(oid), update['status'], raw))
            return result.rowcount == 1

    def links(self):
        with transaction(self.path, rows=True) as db:
            return [dict(r) for r in db.execute('SELECT * FROM order_links')]

    def summary(self):
        with transaction(self.path, rows=True) as db:
            submissions = [dict(r) for r in db.execute('SELECT id,time,kind,coin,error,result FROM submissions ORDER BY time DESC LIMIT 20')]
            counts = dict(db.execute('SELECT kind,COUNT(*) FROM submissions GROUP BY kind').fetchall())
            unresolved = db.execute('SELECT COUNT(*) FROM submissions WHERE result IS NULL').fetchone()[0]
            events = [dict(r) for r in db.execute('SELECT received,event_time,coin,oid,status FROM order_events ORDER BY received DESC LIMIT 20')]
        return dict(counts=counts, unresolved_submissions=unresolved,
                    recent=[dict(time=r['time'],kind=r['kind'],coin=r['coin'],outcome=r['error'] or ('response recorded' if r['result'] is not None else 'outcome unknown')) for r in submissions],
                    events=events, scope='Submission intents precede requests; responses are not fills. Exact coin/order-ID links only. Unknown outcomes remain explicit; no automatic order resubmission.')
