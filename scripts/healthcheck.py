"""Read-only local deployment check; returns nonzero on halt or stale data."""
import sys
import requests

def main():
    try:
        r=requests.get('http://127.0.0.1:8080/api/terminal',timeout=15)
        r.raise_for_status();d=r.json();s=d['status'];risk=s.get('risk',{})
    except (requests.RequestException, ValueError, KeyError):
        print('FAIL dashboard unavailable or response invalid')
        return 1
    ok=(s.get('status')=='running' and s.get('network')=='testnet' and not risk.get('halted',True) and not risk.get('execution_paused',False)
        and d.get('operations',{}).get('responsive',False) and d.get('market_data',{}).get('eligible',False)
        and risk.get('equity_age_s',999)<=30 and d.get('bbo_age_s',999)<=10 and not d.get('errors'))
    print('PASS' if ok else 'FAIL', 'network='+s.get('network','unknown'),
          'halted='+str(risk.get('halted')), 'recovering='+str(risk.get('execution_paused',False)), 'equity_age='+str(risk.get('equity_age_s')),
          'quote_age='+str(round(d.get('bbo_age_s',999),1)), 'errors='+str(d.get('errors')))
    return 0 if ok else 1
if __name__=='__main__':sys.exit(main())
