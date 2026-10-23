"""Sampled L2/trade hypotheses. Scores are heuristics, never probabilities."""
import math
import statistics
from collections import deque
from src.strategy.sr_detector import SRDetector


def finite(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('Non-finite market value')
    return value


def normalize_book(raw, now):
    sides = []
    for side in raw['levels']:
        levels = [(finite(l['px']), finite(l['sz'])) for l in side]
        if not levels or any(p <= 0 or q <= 0 for p, q in levels):
            raise ValueError('Empty or invalid book')
        sides.append(levels)
    if len(sides) != 2:
        raise ValueError('Book requires two sides')
    bids, asks = sorted(sides[0], reverse=True), sorted(sides[1])
    if bids[0][0] >= asks[0][0]:
        raise ValueError('Crossed book')
    timestamp = finite(raw['time'])/1000
    if timestamp > now+2 or now-timestamp > 15:
        raise ValueError('Stale book')
    return bids, asks, timestamp


def active_blocks(candles, now):
    closed = [c for c in candles if int(c['t'])+60000 <= now*1000]
    detector = SRDetector(lookback=500)
    result = []
    for block in detector.detect_order_blocks(closed):
        confirmed = int(closed[block.idx+1]['t'])/1000+60
        if now-confirmed > 21600:
            continue
        later = closed[block.idx+2:]
        invalid = any(float(c['c']) < block.price_low if block.kind == 'bullish'
                      else float(c['c']) > block.price_high for c in later)
        if not invalid:
            result.append(dict(low=block.price_low, high=block.price_high, kind=block.kind,
                               confirmed_at=confirmed, basis='Closed-candle pattern; not proof of institutional orders'))
    return result[-30:]


class Microstructure:
    def __init__(self, whale_usd=100000):
        self.whale_usd = whale_usd
        self.trades = deque(maxlen=20000)
        self.ids = set()
        self.previous = {}
        self.wall_since = {}
        self.history = deque(maxlen=240)
        self.heatmap = deque(maxlen=60)
        self.last_trade_timestamp = None

    def ingest_trades(self, trades, now):
        for trade in sorted(trades, key=lambda t: int(t['time'])):
            ts = finite(trade['time'])/1000
            if ts > now+2 or ts < now-120:
                continue
            key = str(trade.get('tid', trade.get('hash', ''))) + ':' + str(trade['time'])
            if key in self.ids:
                continue
            px, sz = finite(trade['px']), finite(trade['sz'])
            if px <= 0 or sz <= 0 or trade['side'] not in ('B','A'):
                continue
            if len(self.trades) == self.trades.maxlen:
                self.ids.discard(self.trades[0]['id'])
            self.ids.add(key)
            self.trades.append(dict(id=key, time=ts, price=px, usd=px*sz, side=trade['side']))
            self.last_trade_timestamp = max(ts, self.last_trade_timestamp or ts)
        while self.trades and self.trades[0]['time'] < now-120:
            self.ids.discard(self.trades.popleft()['id'])

    def analyze(self, raw, now, blocks=None, flow_complete=True):
        bids, asks, ts = normalize_book(raw, now)
        if self.history and ts <= self.history[-1]['source_time']:
            raise ValueError('Duplicate or out-of-order book snapshot')
        mid = (bids[0][0]+asks[0][0])/2
        bands = []
        for bps in (5,10,25):
            bid_sum = sum(p*q for p,q in bids if p >= mid*(1-bps/10000))
            ask_sum = sum(p*q for p,q in asks if p <= mid*(1+bps/10000))
            bands.append(dict(bps=bps, bid_usd=bid_sum, ask_usd=ask_sum,
                              imbalance=(bid_sum-ask_sum)/(bid_sum+ask_sum) if bid_sum+ask_sum else 0,
                              bid_complete=bids[-1][0] <= mid*(1-bps/10000),
                              ask_complete=asks[-1][0] >= mid*(1+bps/10000)))
        flow = [t for t in self.trades if now-60 <= t['time'] <= now]
        buys = sum(t['usd'] for t in flow if t['side']=='B')
        sells = sum(t['usd'] for t in flow if t['side']=='A')
        flow_complete = flow_complete and not (len(self.trades)==self.trades.maxlen and self.trades[0]['time']>now-60)
        imbalance = (buys-sells)/(buys+sells) if buys+sells and flow_complete else None
        current = {}
        walls = []
        for side, levels in [('bid',bids),('ask',asks)]:
            typical = statistics.median(p*q for p,q in levels)
            for price, size in levels:
                key = (side,price)
                usd = price*size
                old = self.previous.get(key)
                nearby = abs(price/mid-1) <= .0025
                is_wall = nearby and usd >= max(self.whale_usd, typical*3)
                if is_wall:
                    start, last = self.wall_since.get(key,(now,now))
                    if now-last > 15:
                        start = now
                    self.wall_since[key] = (start,now)
                    executed = sum(t['usd'] for t in flow if t['time'] > (old['time'] if old else now)
                                   and t['side'] == ('A' if side=='bid' else 'B') and abs(t['price']-price)<.001)
                    refill = max(0, usd-old['usd']+executed) if old and now-old['time']<=15 else None
                    walls.append(dict(side=side, price=price, usd=usd, multiple=usd/typical,
                                      persistence_s=now-start, observed_refill_usd=refill,
                                      traded_at_level_usd=executed))
                current[key] = dict(usd=usd,time=now,is_wall=is_wall)
        disappeared = [dict(side=k[0],price=k[1],usd=v['usd']) for k,v in self.previous.items()
                       if v.get('is_wall') and k not in current and now-v['time']<=15
                       and bids[-1][0] <= k[1] <= asks[-1][0]]
        self.wall_since = {k:v for k,v in self.wall_since.items() if k in current and now-v[1]<=15}
        self.previous = current
        baseline = next((h for h in self.history if h['time'] >= now-60),None)
        change = (mid/baseline['mid']-1)*10000 if baseline and now-baseline['time']>=45 else None
        bid_wall = any(w['side']=='bid' and w['persistence_s']>=15 for w in walls)
        ask_wall = any(w['side']=='ask' and w['persistence_s']>=15 for w in walls)
        absorption = None
        if change is not None and imbalance is not None:
            if sells >= self.whale_usd and imbalance < -.25 and change >= -2 and bid_wall:
                absorption='bullish'
            elif buys >= self.whale_usd and imbalance > .25 and change <= 2 and ask_wall:
                absorption='bearish'
        zones = []
        for block in blocks or []:
            distance = max(block['low']-mid,mid-block['high'],0)/mid*10000
            if distance <= 10:
                matching = any(w['persistence_s']>=15 and block['low']<=w['price']<=block['high']
                               and w['side']==('bid' if block['kind']=='bullish' else 'ask') for w in walls)
                zones.append(dict(block,distance_bps=distance,wall_confluence=matching))
        # Compare only symmetrically observed depth. Incomplete 10bps bands are informational.
        symmetric_bps = min((mid-bids[-1][0])/mid,(asks[-1][0]-mid)/mid)*10000
        near_bids=sum(p*q for p,q in bids if p>=mid*(1-symmetric_bps/10000))
        near_asks=sum(p*q for p,q in asks if p<=mid*(1+symmetric_bps/10000))
        depth_lean=(near_bids-near_asks)/(near_bids+near_asks) if near_bids+near_asks else 0
        score = 40*depth_lean + 35*(imbalance or 0) + (25 if absorption=='bullish' else -25 if absorption=='bearish' else 0)
        reasons = [f'Symmetric visible depth imbalance {depth_lean:+.2f} across {symmetric_bps:.1f}bps']
        reasons.append(f'Executed 60s flow imbalance {imbalance:+.2f}' if imbalance is not None else 'No recent executed trade evidence')
        if absorption:
            reasons.append(absorption.title()+' absorption hypothesis: pressure without price progress and persistent wall')
        if any(z['wall_confluence'] for z in zones):
            reasons.append('Persistent wall overlaps a closed-candle order block')
        lean = 'bullish' if score>=25 else 'bearish' if score<=-25 else 'neutral'
        self.history.append(dict(time=now,source_time=ts,mid=mid))
        self.heatmap.append(dict(time=now,levels=[[p,p*q,'bid'] for p,q in bids]+[[p,p*q,'ask'] for p,q in asks]))
        return dict(source='Hyperliquid mainnet public BTC', sampled_at=now, source_time=ts,
                    bid=bids[0][0], ask=asks[0][0], mid=mid, spread_bps=(asks[0][0]-bids[0][0])/mid*10000,
                    score=round(score,1), lean=lean, reasons=reasons, bands=bands,
                    symmetric_depth_bps=symmetric_bps, depth_imbalance=depth_lean,
                    flow=dict(buy_usd=buys,sell_usd=sells,imbalance=imbalance,count=len(flow),
                              window_s=60,complete=flow_complete,latest_trade_time=self.last_trade_timestamp),
                    walls=sorted(walls,key=lambda w:w['usd'],reverse=True)[:10],
                    disappeared_walls=disappeared[:10], absorption=absorption, change_60s_bps=change,
                    blocks=zones, large_trades=[t for t in reversed(flow) if t['usd']>=self.whale_usd][:20],
                    heatmap=list(self.heatmap), invalidation='Lean invalidates when confirming flow/walls disappear or price breaks the supporting zone',
                    interpretation='Unvalidated directional score, not a probability; aggregate sampled L2 cannot identify spoofing or whale ownership')
