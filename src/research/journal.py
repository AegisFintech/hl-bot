"""Persistent prospective markouts. These are quote-based research, not filled trades."""
import json
import sqlite3

HORIZONS = (10,60,300,900)

class ResearchJournal:
    def __init__(self,path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS observations(time INTEGER PRIMARY KEY, raw TEXT);
                CREATE TABLE IF NOT EXISTS wallet_positions(address TEXT PRIMARY KEY,time REAL,raw TEXT);
                CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE,
                    time REAL, kind TEXT, direction INTEGER, bid REAL, ask REAL, mid REAL,
                    funding REAL, reason TEXT, favorable REAL DEFAULT 0, adverse REAL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS outcomes(signal_id INTEGER, horizon INTEGER, measured_at REAL,
                    status TEXT, gross_bps REAL, net_bps REAL, favorable_bps REAL, adverse_bps REAL,
                    PRIMARY KEY(signal_id,horizon));
            ''')

    def connect(self):
        db=sqlite3.connect(self.path,timeout=5)
        db.row_factory=sqlite3.Row
        return db

    def observe(self,snapshot):
        trimmed={k:v for k,v in snapshot.items() if k not in ('heatmap',)}
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO observations VALUES (?,?)',(int(snapshot['sampled_at']//15)*15,json.dumps(trimmed)))
            db.execute('DELETE FROM observations WHERE time < ?',(snapshot['sampled_at']-7*86400,))

    def signal(self,kind,direction,snapshot,reason,funding=None):
        now=snapshot['sampled_at']
        fingerprint=f'{kind}:{direction}:{int(now//60)}'
        with self.connect() as db:
            cursor=db.execute('INSERT OR IGNORE INTO signals(fingerprint,time,kind,direction,bid,ask,mid,funding,reason) VALUES (?,?,?,?,?,?,?,?,?)',
                (fingerprint,now,kind,direction,snapshot['bid'],snapshot['ask'],snapshot['mid'],funding,reason))
            return cursor.rowcount==1

    def mark(self,snapshot):
        now=snapshot['sampled_at']
        with self.connect() as db:
            pending=db.execute('SELECT * FROM signals WHERE id IN (SELECT s.id FROM signals s LEFT JOIN outcomes o ON s.id=o.signal_id GROUP BY s.id HAVING COUNT(o.horizon)<4)').fetchall()
            for signal in pending:
                elapsed=now-signal['time']
                if elapsed<0:
                    continue
                mid_return=signal['direction']*(snapshot['mid']/signal['mid']-1)*10000
                favorable=max(signal['favorable'],mid_return)
                adverse=min(signal['adverse'],mid_return)
                db.execute('UPDATE signals SET favorable=?,adverse=? WHERE id=?',(favorable,adverse,signal['id']))
                for horizon in HORIZONS:
                    if elapsed<horizon:
                        continue
                    if elapsed>horizon+15:
                        values=(signal['id'],horizon,now,'missed',None,None,None,None)
                    else:
                        entry=signal['ask'] if signal['direction']==1 else signal['bid']
                        exit_price=snapshot['bid'] if signal['direction']==1 else snapshot['ask']
                        gross=signal['direction']*(exit_price/entry-1)*10000
                        # 4.5bps taker + 2bps slippage on each leg. Funding is a frozen-rate debit stress.
                        funding=abs(signal['funding'] or 0)*10000*elapsed/3600
                        net=gross-13-funding
                        values=(signal['id'],horizon,now,'complete',mid_return,net,favorable,adverse)
                    db.execute('INSERT OR IGNORE INTO outcomes VALUES (?,?,?,?,?,?,?,?)',values)

    def wallet_changes(self,address,positions,now):
        current={p['coin']:float(p['szi']) for p in positions}
        with self.connect() as db:
            row=db.execute('SELECT time,raw FROM wallet_positions WHERE address=?',(address,)).fetchone()
            db.execute('INSERT OR REPLACE INTO wallet_positions VALUES (?,?,?)',(address,now,json.dumps(current)))
        if row is None:return dict(previous_at=None,deltas=[])
        previous=json.loads(row['raw'])
        return dict(previous_at=row['time'],deltas=[dict(coin=coin,previous_size=previous.get(coin,0),
                    current_size=current.get(coin,0),delta_size=current.get(coin,0)-previous.get(coin,0))
                    for coin in sorted(set(previous)|set(current)) if current.get(coin,0)!=previous.get(coin,0)])

    def summary(self):
        with self.connect() as db:
            counts=db.execute('SELECT COUNT(*) n,MIN(time) first,MAX(time) last FROM signals').fetchone()
            rows=db.execute('''SELECT s.kind,s.direction,o.horizon,COUNT(*) n,AVG(o.net_bps) mean_net_bps,
                AVG(CASE WHEN o.net_bps>0 THEN 1.0 ELSE 0 END) positive_rate,
                AVG(o.favorable_bps) mean_favorable_bps,AVG(o.adverse_bps) mean_adverse_bps
                FROM outcomes o JOIN signals s ON s.id=o.signal_id WHERE o.status='complete'
                GROUP BY s.kind,s.direction,o.horizon ORDER BY s.kind,s.direction,o.horizon''').fetchall()
            missed=db.execute("SELECT COUNT(*) FROM outcomes WHERE status='missed'").fetchone()[0]
            recent=db.execute('SELECT id,time,kind,direction,reason FROM signals ORDER BY id DESC LIMIT 30').fetchall()
            recent_outcomes=db.execute('SELECT * FROM outcomes WHERE signal_id IN (SELECT id FROM signals ORDER BY id DESC LIMIT 30)').fetchall()
        return dict(signal_count=counts['n'],first_signal_at=counts['first'],last_signal_at=counts['last'],
                    missed_markouts=missed,results=[dict(r) for r in rows],recent=[dict(r,outcomes=[dict(o) for o in recent_outcomes if o['signal_id']==r['id']]) for r in recent],
                    horizons_s=HORIZONS,model='Quote-based markouts: bid/ask spread + 9bps fees + 4bps slippage + frozen hourly funding debit stress when available. Not fills or realized P&L.',
                    limitations='Signals overlap and are correlated. MFE/MAE are sampled mid-price changes, not intrabar extremes. No calibrated probability or profitability claim.')
