"""Real Chromium checks against the running local dashboard."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
(root/'artifacts').mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1512,'height':1100},device_scale_factor=1)
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8080',wait_until='networkidle')
    page.wait_for_function("document.getElementById('equity').textContent !== '—'",timeout=20000)
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
    page.screenshot(path=str(root/'artifacts/dashboard-mobile.png'),full_page=True)
    page.route('**/api/terminal',lambda route:route.fulfill(status=503,body='offline'))
    page.wait_for_function("document.getElementById('connection').textContent.includes('Disconnected')",timeout=20000)
    assert 'stale' in page.locator('#notice').inner_text()
    assert not errors,errors
    print(json.dumps({'browser':'Chromium','desktop':'1512x1100','mobile':'390x844','checks':['live data','candlestick and equity canvases','account tabs','search','timeframe','level toggle','fit view','CSV download','no horizontal page overflow','offline stale notice'],'page_errors':errors},indent=2))
    browser.close()
