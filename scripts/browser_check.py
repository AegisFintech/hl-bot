"""Real Chromium checks against the running local dashboard."""
import json
import time
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
(root/'artifacts').mkdir(exist_ok=True)
deadline=time.monotonic()+30
while True:
    try:
        response=requests.get('http://127.0.0.1:8080/api/status',timeout=2)
        if response.ok and response.json().get('risk'):break
    except requests.RequestException:
        pass
    if time.monotonic()>deadline:raise RuntimeError('Dashboard did not become ready within 30s')
    time.sleep(.5)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1512,'height':1100},device_scale_factor=1)
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8080',wait_until='networkidle')
    page.wait_for_function("document.getElementById('equity').textContent !== '—'",timeout=20000)
    page.wait_for_function("document.getElementById('research-health').textContent.includes('MAINNET')",timeout=20000)
    assert page.locator('#research').is_visible()
    assert 'OBSERVATION ONLY' in page.locator('#research').inner_text()
    assert 'Mainnet public BTC data' in page.locator('#research').inner_text()
    page.locator('[data-depth-band="25"]').click()
    assert 'Truncated' in page.locator('#depth-coverage').inner_text() or 'Full' in page.locator('#depth-coverage').inner_text()
    assert page.locator('.experiment-card').count()==9
    page.locator('.experiment-card summary').first.click()
    assert 'Rule:' in page.locator('.experiment-card').first.inner_text()
    assert 'DATA REQUIRED' in page.locator('#experiment-catalog').inner_text()
    page.locator('#research-horizon').select_option('14400')
    assert 'No measured outcomes' in page.locator('#research-results').inner_text() or page.locator('#research-results tr').count()>0
    assert page.locator('#complete-count').inner_text()!='—'
    page.wait_for_function("document.getElementById('quality-decisions').textContent !== '—'",timeout=20000)
    assert 'TESTNET ONLY' in page.locator('#quality').inner_text()
    assert 'unknown' in page.locator('#quality-attribution').inner_text()
    page.locator('#quality-horizon').select_option('14400')
    page.locator('#quality-horizon').select_option('3600')
    page.locator('#research-horizon').select_option('900')
    page.locator('#research-horizon').select_option('60')
    assert page.locator('#depth-heatmap').evaluate('(canvas) => canvas.width > 0 && canvas.height > 0')
    page.evaluate('window.scrollTo(0,0)')
    page.screenshot(path=str(root/'artifacts/dashboard-desktop.png'),full_page=True)
    assert page.locator('#price-chart canvas').count()>0
    assert page.locator('#equity-chart canvas').count()>0
    page.locator('[data-tab="fills"]').click()
    assert page.locator('#table-body tr').count()>1
    page.locator('#table-search').fill('NO_MATCH_123')
    assert 'No matching records' in page.locator('#table-body').inner_text()
    page.locator('#table-search').fill('')
    page.locator('[data-tab="orders"]').click()
    page.locator('[data-timeframe="5"]').click()
    page.locator('#levels-toggle').uncheck()
    page.locator('#fit-chart').click()
    with page.expect_download() as download:
        page.locator('a[download]').click()
    path=download.value.path();assert 'closedPnl' in Path(path).read_text()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.set_viewport_size({'width':390,'height':844})
    page.locator('[data-tab="fills"]').click()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.evaluate('window.scrollTo(0,0)')
    page.screenshot(path=str(root/'artifacts/dashboard-mobile.png'),full_page=True)
    payload=requests.get('http://127.0.0.1:8080/api/terminal',timeout=15).json()
    payload['quality']['markouts']=[dict(role='entry',horizon=60,n=2,missed=1,mean_bps=-3.25)]
    payload['quality']['challenger']['results']=[dict(kind='shadow_trend_v1',direction=1,horizon=3600,n=4,nonoverlap_n=1,mean_net_bps=-5,nonoverlap_mean_net_bps=-6,review_status='insufficient evidence')]
    payload['quality']['recent_decisions']=[dict(time=payload['timestamp'],side='long',regime='range',reason='<img src=x onerror=alert(1)>')]
    payload['quality']['recent']=[dict(closed_at=payload['timestamp']*1000,regime='unknown',net_pnl=-.1,funding_usdc=None,net_after_funding=None)]
    page.route('**/api/terminal',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps(payload)))
    page.wait_for_function("document.getElementById('quality-markouts').textContent.includes('-3.25')",timeout=15000)
    assert 'Trend continuation v1' in page.locator('#quality-challengers').inner_text()
    page.locator('#quality details').last.locator('summary').click()
    assert '—' in page.locator('#quality-episodes').inner_text()
    assert page.locator('#quality-reasons img').count()==0
    payload['status']['risk'].update(halted=False, execution_paused=True, pause_reason='Exchange maintenance', pause_until=time.time()+60)
    payload['status']['halt_cleanup']='Confirmed flat; no orders'
    page.wait_for_function("document.getElementById('engine').textContent === 'RECOVERING'",timeout=15000)
    assert 'Automatic checks active' in page.locator('#notice').inner_text()
    assert 'Confirmed flat; no orders' in page.locator('#notice').inner_text()
    assert 'operator review required' not in page.locator('#notice').inner_text().lower()
    payload['status']['risk'].update(halted=True, halt_reason='5% equity high-water drawdown limit')
    page.wait_for_function("document.getElementById('engine').textContent === 'HALTED'",timeout=15000)
    assert 'Operator review required' in page.locator('#notice').inner_text()
    payload['status']['risk'].update(halted=False, execution_paused=False)
    page.wait_for_function("document.getElementById('engine').textContent === 'RUNNING'",timeout=15000)
    page.unroute('**/api/terminal')
    payload['research']['status']='stale'
    page.route('**/api/terminal',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps(payload)))
    page.wait_for_function("document.getElementById('research-lean').textContent === 'Unavailable'",timeout=15000)
    assert page.locator('#research-score').inner_text() == '—'
    assert page.locator('#divergence-net').inner_text() == '—'
    assert 'stale' in page.locator('#research-notice').inner_text()
    page.unroute('**/api/terminal')
    page.route('**/api/terminal',lambda route:route.fulfill(status=503,body='offline'))
    page.wait_for_function("document.getElementById('connection').textContent.includes('Disconnected')",timeout=20000)
    assert 'stale' in page.locator('#notice').inner_text()
    page.wait_for_function("document.getElementById('quality-status').textContent.includes('STALE')",timeout=10000)
    assert not errors,errors
    print(json.dumps({'browser':'Chromium','desktop':'1512x1100','mobile':'390x844','checks':['live data','candlestick and equity canvases','account tabs','search','timeframe','level toggle','fit view','CSV download','no horizontal page overflow','offline stale notice','mainnet research separation','depth band controls','outcome horizon controls','liquidity canvas','experiment catalog and prerequisites','4h horizon','complete trade accounting','testnet quality attribution and horizon controls','quality outcome fixtures and missing funding','safe text rendering','quality stale handling','stale research suppresses directional score and divergence'],'page_errors':errors},indent=2))
    browser.close()
