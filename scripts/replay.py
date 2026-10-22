"""Chronological research replay of live signal rules; never submits orders.

Usage: python3 scripts/replay.py --fetch
Caveats: OHLC cannot establish maker fills/queue priority. Assumes a 1bp spread,
1.5bp entry fee, 4.5bp exit fee, 2bp adverse exit slippage and 1bp/hour funding
stress. Orders rest for five minutes. A touched entry is not assumed filled until the bar crosses it. Stop wins
when both barriers touch. Gap exits use the worse opening price. No optimization.
"""
from collections import Counter
import argparse
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import requests
from src.strategy.scalper import Scalper
from src.strategy.sr_detector import SRDetector
from src.strategy.economics import viable
from src.risk.manager import RiskManager

ROOT=Path(__file__).resolve().parents[1]
class Tape:
    def __init__(self):self.bars=[];self.now=0
    def get_cached_candles(self,*args):return self.bars
    def get_candles(self,*args):return self.bars
    def get_mid_price(self,*args):return float(self.bars[-1]['c'])
    def get_cached_bbo(self,*args):
        mid=self.get_mid_price();return {'bid':{'px':mid*.99995},'ask':{'px':mid*1.00005}}
    def bbo_age(self,*args):return 0
    def round_price(self,coin,p):return round(p)
    def round_size(self,coin,s):return int(s*1e5)/1e5


def replay(bars,capital=981.069527,start=200):
    tape=Tape()
    with patch('time.time', return_value=int(bars[start]['t'])/1000):
        risk=RiskManager();risk.update_equity(capital)
    s=Scalper(tape,SRDetector(lookback=2000),risk,'BTC',proximity_pct=.0015)
    counts=Counter()
    cash=capital;peak=capital;max_dd=0;position=None;pending=None;trades=[];halted=False;equity=[]
    for i in range(start,len(bars)):
        bar=bars[i];now=int(bar['t'])/1000
        tape.bars=bars[max(0,i-2000):i];tape.now=now
        with patch('time.time',return_value=now):
            risk.check_daily_reset()
            if pending:
                sig,size,placed=pending
                if now - placed > 300:
                    counts['expired_entries']+=1
                    pending=None
                elif float(bar['l']) < sig.entry_price < float(bar['h']):
                    position=(sig,size,now)
                    cash -= sig.entry_price * size * .00015
                    pending=None
                    counts['simulated_entries']+=1
            if position:
                sig,size,opened=position;long=sig.side=='long';op=float(bar['o']);hi=float(bar['h']);lo=float(bar['l'])
                stop_hit=lo<=sig.sl_price if long else hi>=sig.sl_price
                tp_hit=hi>=sig.tp_price if long else lo<=sig.tp_price
                exit_px=None;reason=''
                if stop_hit:
                    exit_px=min(op,sig.sl_price) if long else max(op,sig.sl_price);reason='stop'
                elif tp_hit:exit_px=sig.tp_price;reason='target'
                elif i==len(bars)-1:exit_px=float(bar['c']);reason='end_of_window'
                if exit_px is not None:
                    exit_px*=.9998 if long else 1.0002
                    gross=(exit_px-sig.entry_price)*size*(1 if long else -1)
                    fees=(sig.entry_price*.00015+exit_px*.00045)*size
                    funding=sig.entry_price*size*.0001*max(0,now-opened)/3600
                    net=gross-fees-funding;cash+=gross-exit_px*size*.00045-funding
                    trades.append(dict(time=now,net=net,gross=gross,fees=fees,funding_stress=funding,reason=reason))
                    position=None;risk.record_fill(net)
            mark=cash
            if position:
                sig,size,opened=position
                mark+=(float(bar['c'])-sig.entry_price)*size*(1 if sig.side=='long' else -1)
            peak=max(peak,mark);dd=max(0,1-mark/peak);max_dd=max(max_dd,dd)
            risk.update_equity(mark)
            equity.append(dict(time=now,equity=mark))
            if risk.should_kill():
                halted=True
                if position:
                    sig,size,opened=position;px=float(bar['c'])*(.9998 if sig.side=='long' else 1.0002)
                    gross=(px-sig.entry_price)*size*(1 if sig.side=='long' else -1)
                    fees=(sig.entry_price*.00015+px*.00045)*size
                    funding=sig.entry_price*size*.0001*max(0,now-opened)/3600
                    net=gross-fees-funding;cash+=gross-px*size*.00045-funding;position=None
                    trades.append(dict(time=now,net=net,gross=gross,fees=fees,funding_stress=funding,reason='risk_halt'))
                break
            if position or pending or i==len(bars)-1:continue
            signals=s.scan_for_signals()
            if not signals:
                counts[s.diagnostics.get("reason", "No candidate")]+=1
                continue
            counts["signal_candidates"]+=len(signals)
            sig=signals[0];bbo=tape.get_cached_bbo()
            eligible,reason=viable(sig,bbo['bid']['px'],bbo['ask']['px'])
            if not eligible:
                counts[reason]+=1
                continue
            if not risk.can_trade(sig):
                counts['risk_admission']+=1
                continue
            size=tape.round_size('BTC',risk.compute_position_size(sig))
            if size*sig.entry_price<10:
                counts['below_minimum_notional']+=1
                continue
            # Order is first eligible on the next iteration; no same-bar lookahead.
            pending=(sig,size,now)
            risk.record_order(sig,size)
    gains=sum(t['net'] for t in trades if t['net']>0);losses=-sum(t['net'] for t in trades if t['net']<0)
    return dict(start_time=bars[start]['t'],end_time=bars[-1]['t'],closed_trades=len(trades),
                initial_equity=capital,ending_equity=cash,net_pnl=cash-capital,return_pct=(cash/capital-1)*100,
                max_drawdown_pct=max_dd*100,halted=halted,profit_factor=gains/losses if losses else None,
                fees=sum(t['fees'] for t in trades),funding_stress=sum(t['funding_stress'] for t in trades),
                expectancy=sum(t['net'] for t in trades)/len(trades) if trades else None, diagnostics=dict(counts))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--fetch',action='store_true');args=parser.parse_args()
    path=ROOT/'data/replay_candles.json'
    if args.fetch:
        import time
        now=int(time.time()*1000)
        r=requests.post('https://api.hyperliquid-testnet.xyz/info',json={'type':'candleSnapshot','req':{'coin':'BTC','interval':'1m','startTime':now-5000*60000,'endTime':now}},timeout=30)
        r.raise_for_status();bars=r.json();bars=sorted({int(b['t']):b for b in bars if int(b['t'])+60000<=now}.values(),key=lambda b:int(b['t']))
        path.write_text(json.dumps(bars))
    bars=json.loads(path.read_text())
    if len(bars)<500:raise RuntimeError('Insufficient chronological data')
    split=int(len(bars)*.7)
    report=dict(data_source='Hyperliquid testnet BTC 1m',bars=len(bars),configuration='Fixed live signal rules; no parameter search. Cost-floor geometry corrected after initial diagnostic; initial result preserved, so this is not a pristine holdout.',
                assumptions=__doc__,development=replay(bars[:split]),holdout=replay(bars, start=split),
                conclusion='Short OHLC replay is a diagnostic, not profitability proof. Require 30 days / 100 forward closed trades net of fees and actual funding. 10% daily target remains unverified.')
    (ROOT/'docs/replay-results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
