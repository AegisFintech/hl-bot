"""Public read-only collectors on a daemon thread, isolated from demo execution.

Only fixed public /info and market-data GET routes are reachable here. No signing
keys, exchange mutations, account transfers, or automated signal promotion.
"""
from collections import deque
import copy
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
import requests
import websocket
from .microstructure import Microstructure, active_blocks
from .journal import ResearchJournal

log=logging.getLogger(__name__)
INFO='https://api.hyperliquid.xyz/info'
KRAKEN='https://api.kraken.com/0/public/Depth'


def divergence(book,spot,fx=None,notional=100,spot_fee_bps=60):
    """Indicative two-venue, four-leg roundtrip economics; no claim of executability."""
    bid,ask=book['bid'],book['ask']
    cb_bid,cb_ask=float(spot['bids'][0][0]),float(spot['asks'][0][0])
    fx_bid,fx_ask=(float(fx['bids'][0][0]),float(fx['asks'][0][0])) if fx else (1.0,1.0)
    if not (0<cb_bid<cb_ask and 0<fx_bid<=fx_ask):
        raise ValueError('Invalid comparison quotes')
    sell_perp=(bid*fx_bid/cb_ask-1)*10000
    buy_perp=(cb_bid/(ask*fx_ask)-1)*10000
    edge=max(sell_perp,buy_perp)
    costs=2*(4.5+spot_fee_bps)+8
    return dict(direction='Buy Kraken spot / sell HL perp' if sell_perp>=buy_perp else 'Buy HL perp / sell Kraken spot',
                opening_edge_bps=edge, modeled_roundtrip_cost_bps=costs,net_candidate_bps=edge-costs,
                notional_usd=notional,spot_bid=cb_bid,spot_ask=cb_ask,fx_bid=fx_bid,fx_ask=fx_ask,
                best_quote_capacity_usd=min(float(spot['asks'][0][1])*cb_ask,float(spot['bids'][0][1])*cb_bid),
                status='Indicative only; unhedged/basis, financing, transfer and multi-leg risks remain',
                quote_basis='Kraken BTC/USDC spot vs Hyperliquid BTC perp; derivative basis risk remains',
                assumptions=f'Kraken fee assumed {spot_fee_bps}bps/leg, HL 4.5bps/leg, four legs, 2bps slippage/leg, exit basis assumed zero. No accounts funded or connected.')


class ResearchService:
    def __init__(self,path,wallets=None):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        self.journal=ResearchJournal(path)
        self.engine=Microstructure()
        raw=wallets if wallets is not None else os.environ.get('RESEARCH_WALLETS','').split(',')
        self.wallets=[a.strip() for a in raw if re.fullmatch(r'0x[0-9a-fA-F]{40}',a.strip())][:3]
        self._configured_wallets=bool(self.wallets)
        self._last_discovery=0
        self._trade_queue=deque(maxlen=50000)
        self._stream_lock=threading.Lock()
        self._stream={'connected':False,'connected_at':None,'dropped':0}
        self._ws=None
        self._ws_thread=None
        self._lock=threading.Lock()
        self._stop=threading.Event()
        self._thread=None
        self._state={'mode':'Observation only','status':'warming_up','source':'Mainnet public data; demo execution separate',
                     'wallets':{'status':'Waiting for large public prints to discover wallets','accounts':[]},
                     'liquidations':{'status':'No global liquidation feed; observed-wallet events only','events':[]}}
        self._slow={}
        self._due={}
        self._blocks=[]
        self._session=requests.Session()
        self._session.headers.update({'User-Agent':'Aegis-Research/1.0'})

    def _get(self,url,params=None):
        r=self._session.get(url,params=params,timeout=5);r.raise_for_status();return r.json()

    def _info(self,kind,**fields):
        r=self._session.post(INFO,json=dict(type=kind,**fields),timeout=5);r.raise_for_status();return r.json()

    def start(self):
        if self._thread and self._thread.is_alive():return
        self._ws_thread=threading.Thread(target=self._stream_loop,name='public-trade-stream',daemon=True)
        self._ws_thread.start()
        self._thread=threading.Thread(target=self._run,name='public-market-research',daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._ws:self._ws.close()

    def _stream_loop(self):
        def opened(ws):
            with self._stream_lock:
                self._stream.update(connected=True,connected_at=time.time())
                self._trade_queue.clear()
            ws.send(json.dumps({'method':'subscribe','subscription':{'type':'trades','coin':'BTC'}}))
        def message(ws,raw):
            try:
                payload=json.loads(raw)
                if payload.get('channel')=='trades':
                    with self._stream_lock:
                        for trade in payload['data']:
                            if len(self._trade_queue)==self._trade_queue.maxlen:
                                self._stream['dropped']+=1
                                self._stream['connected_at']=time.time()
                            self._trade_queue.append(trade)
            except (ValueError,TypeError,KeyError):
                log.warning('Invalid public trade stream message')
        def closed(ws,*args):
            with self._stream_lock:self._stream['connected']=False
        while not self._stop.is_set():
            self._ws=websocket.WebSocketApp('wss://api.hyperliquid.xyz/ws',on_open=opened,on_message=message,on_close=closed,
                                           on_error=lambda ws,error: closed(ws))
            self._ws.run_forever(ping_interval=20,ping_timeout=10)
            self._stop.wait(5)

    def _discover(self,trades,now):
        if self._configured_wallets or now-self._last_discovery<120:return
        candidates=sorted([t for t in trades if float(t['px'])*float(t['sz'])>=100000
                           and now-10<=float(t['time'])/1000<=now+2],
                          key=lambda t:float(t['px'])*float(t['sz']),reverse=True)
        addresses=[]
        for trade in candidates:
            for address in trade.get('users',[]):
                if re.fullmatch(r'0x[0-9a-fA-F]{40}',address) and int(address,16) and address not in addresses:
                    addresses.append(address)
        if addresses:
            self.wallets=addresses[:2]
            self._last_discovery=now
            self._due['wallet_watch']=0

    def _comparison(self):
        raw=self._get(KRAKEN,{'pair':'XBTUSDC','count':10})
        if raw.get('error'):raise ValueError('Kraken market unavailable')
        book=next(iter(raw['result'].values()))
        return dict(spot={'bids':book['bids'],'asks':book['asks']})

    def _refresh(self,key,interval,loader,now):
        if now < self._due.get(key,0):return
        self._due[key]=now+interval
        try:
            value=loader()
            self._slow[key]=dict(value=value,updated_at=time.time(),error=None)
        except Exception as exc:
            old=self._slow.get(key,{})
            self._slow[key]=dict(old,error=type(exc).__name__+'; retry scheduled')
            log.warning('Public research source unavailable: %s (%s)',key,type(exc).__name__)

    def _sentiment(self):
        row=self._get('https://api.alternative.me/fng/',{'limit':1})['data'][0]
        value=int(row['value'])
        if not 0<=value<=100:raise ValueError('Sentiment range')
        return dict(value=value,label=row['value_classification'],published_at=int(row['timestamp']),
                    source='Alternative.me',role='Daily regime context, not a fast entry signal',url='https://alternative.me/crypto/fear-and-greed-index/')

    def _context(self):
        meta,contexts=self._info('metaAndAssetCtxs')
        i=next(i for i,a in enumerate(meta['universe']) if a['name']=='BTC')
        c=contexts[i]
        return dict(funding_hourly=float(c['funding']),open_interest_btc=float(c['openInterest']),
                    mark=float(c['markPx']),oracle=float(c['oraclePx']),volume_24h_usd=float(c['dayNtlVlm']),
                    premium=float(c.get('premium',0)),role='Funding is variable; carry requires a funded hedge and realized-cost accounting')

    def _candles(self):
        now=int(time.time()*1000)
        bars=self._info('candleSnapshot',req=dict(coin='BTC',interval='1m',startTime=now-500*60000,endTime=now))
        self._blocks=active_blocks(sorted(bars,key=lambda c:int(c['t'])),time.time())
        return dict(active_blocks=len(self._blocks))

    def _wallets(self):
        accounts=[];liquidations=[]
        for address in self.wallets:
            state=self._info('clearinghouseState',user=address)
            positions=[p['position'] for p in state.get('assetPositions',[]) if float(p['position']['szi'])!=0]
            fills=self._info('userFills',user=address)
            recent=[f for f in fills if int(f['time'])/1000>=time.time()-3600]
            accounts.append(dict(address=address,positions=[dict(coin=p['coin'],size=float(p['szi']),
                                entry_price=float(p['entryPx']),unrealized_pnl=float(p['unrealizedPnl'])) for p in positions],
                                 recent_fills=len(recent),caveat='One public wallet only; other hedges and accounts are unknown'))
            updates=self._info('userNonFundingLedgerUpdates',user=address,startTime=int((time.time()-3600)*1000))
            for update in updates:
                if update.get('delta',{}).get('type')=='liquidation':
                    liquidations.append(dict(address=address,time=update.get('time'),basis='Confirmed wallet ledger liquidation'))
        return dict(accounts=accounts,liquidations=liquidations)

    def step(self):
        # Capture fast observations first. Slow context refreshes never relabel old quotes as fresh.
        with self._stream_lock:
            trades=list(self._trade_queue);self._trade_queue.clear()
            stream=dict(self._stream)
        self.engine.ingest_trades(trades,time.time())
        self._discover(trades,time.time())
        raw=self._info('l2Book',coin='BTC')
        now=time.time()
        complete=bool(stream['connected'] and now-(stream['connected_at'] or now)>=60)
        market=self.engine.analyze(raw,now,self._blocks,flow_complete=complete)
        market['trade_stream']=stream
        self.journal.mark(market)
        self.journal.observe(market)
        funding_source=self._slow.get('context',{})
        funding=funding_source.get('value',{}).get('funding_hourly') if now-funding_source.get('updated_at',0)<180 else None
        if market['lean']!='neutral':
            self.journal.signal('book_flow',1 if market['lean']=='bullish' else -1,market,'; '.join(market['reasons']),funding)
        if market['absorption']:
            self.journal.signal('absorption',1 if market['absorption']=='bullish' else -1,market,market['absorption']+' absorption hypothesis',funding)
        for direction,side in [(1,'B'),(-1,'A')]:
            if any(t['side']==side and now-t['time']<=10 for t in market['large_trades']):
                self.journal.signal('large_trade',direction,market,'Executed print >=100,000 USD; ownership unknown',funding)
        if any(b['wall_confluence'] for b in market['blocks']):
            for kind,direction in [('bullish',1),('bearish',-1)]:
                if any(b['wall_confluence'] and b['kind']==kind for b in market['blocks']):
                    self.journal.signal('block_wall',direction,market,'Persistent liquidity overlaps confirmed candle zone',funding)
        # Symmetric controls make raw market drift visible rather than assuming a zero benchmark.
        if int(now//60)%5==0:
            for direction in (1,-1):self.journal.signal('baseline',direction,market,'Unconditional five-minute control',funding)
        with self._lock:
            self._state.update(market=market,status='observing',updated_at=now,error=None)
        self._refresh('sentiment',3600,self._sentiment,now)
        self._refresh('context',60,self._context,now)
        self._refresh('candles',60,self._candles,now)
        self._refresh('comparison',15,self._comparison,now)
        if self.wallets:self._refresh('wallet_watch',120,self._wallets,now)
        with self._lock:
            self._state['sources']=copy.deepcopy(self._slow)

    def _run(self):
        while not self._stop.is_set():
            started=time.monotonic()
            try:self.step()
            except Exception as exc:
                log.warning('Research cycle unavailable (%s)',type(exc).__name__)
                with self._lock:
                    self._state.update(status='unavailable',error=type(exc).__name__+'; automatic retry')
            self._stop.wait(max(1,5-(time.monotonic()-started)))

    def snapshot(self):
        with self._lock:result=copy.deepcopy(self._state)
        now=time.time();market=result.get('market',{})
        age=now-market.get('source_time',0)
        result.update(mode='Observation only',age_s=age if market else None)
        if market and age>15:
            result['status']='stale'
            market.update(score=None,lean='unavailable')
        sources=result.get('sources',{})
        for key,ttl in [('sentiment',172800),('context',180),('comparison',30),('candles',180),('wallet_watch',300)]:
            if key in sources:
                sources[key]['age_s']=now-sources[key].get('updated_at',0)
                sources[key]['stale']=sources[key]['age_s']>ttl
        comparison=sources.get('comparison',{})
        if market and age<=15 and comparison.get('value') and not comparison.get('stale'):
            result['divergence']=divergence(market,**comparison['value'])
        if sources.get('wallet_watch',{}).get('value'):
            value=sources['wallet_watch']['value']
            result['wallets']=dict(status='Configured public wallets' if self._configured_wallets else 'Addresses observed in large prints; ownership/hedges unknown',accounts=value['accounts'])
            result['liquidations']=dict(status='Observed-wallet events only, last hour',events=value['liquidations'])
        result['journal']=self.journal.summary()
        return result
