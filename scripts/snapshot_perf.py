#!/usr/bin/env python3
"""Append cost-inclusive exchange ledger and risk snapshots; safe for hourly cron."""
import json
import sys
import time
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from src.learning.ledger import FillLedger

def main():
    ledger=FillLedger(PROJECT/'data/ledger.sqlite')
    risk_path=PROJECT/'data/risk_state.json'
    risk=json.loads(risk_path.read_text()) if risk_path.exists() else {}
    fills=ledger.fills(1000000)
    recent=[f for f in fills if int(f['time'])/1000>=time.time()-3600]
    net=sum(float(f.get('closedPnl',0))-float(f.get('fee',0)) for f in recent)
    snapshot=dict(ts=time.time(),basis='exchange fills net of actual fees; funding excluded',
                  performance=ledger.performance(),risk=risk,last_1h_fills=len(recent),last_1h_net_pnl=net)
    with (PROJECT/'data/perf_log.jsonl').open('a') as f:f.write(json.dumps(snapshot)+'\n')
    print(f"Ledger fills={snapshot['performance']['fill_count']} net={snapshot['performance']['net_pnl']:+.6f}; last hour={net:+.6f}; funding excluded")

if __name__=='__main__':main()
