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
    assert not errors,errors
    print(json.dumps({'browser':'Chromium','desktop':'1512x1100','mobile':'390x844','checks':['live data','candlestick and equity canvases','account tabs','search','timeframe','level toggle','fit view','CSV download','no horizontal page overflow','offline stale notice','mainnet research separation','depth band controls','outcome horizon controls','liquidity canvas','stale research suppresses directional score and divergence'],'page_errors':errors},indent=2))
    browser.close()
