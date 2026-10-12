"""Browser regression for reading anchors, layouts, PDF text, math and failed asks.

Run against a running Reader; all question submissions are mocked.
"""
from playwright.sync_api import sync_playwright, expect
from test_reader import CHROME_PATHS
import sys
import os
import re
base = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get('READER_TEST_BROWSER') or str(next(path for path in CHROME_PATHS if path.is_file())), headless=True)
    page = b.new_page(viewport={'width': 1600, 'height': 1000})
    errors = []
    page.on('pageerror', lambda e: (errors.append(str(e)), print('Browser error:', e, flush=True)))
    page.goto(base + '/papers/reasoning-rl-reductions/#1', wait_until='domcontentloaded')
    link = page.locator('a.evidence-link[data-source-id="arxiv-2402.03300v3"]').first
    link.click()
    f = page.frame_locator('.evidence-panel__frame')
    try:
        f.locator('canvas.is-rendered').first.wait_for(timeout=30000)
    except Exception:
        print(f.locator('body').evaluate('''() => ({status:document.querySelector('#status')?.textContent, pages:document.querySelectorAll('.pdf-page').length, canvases:document.querySelectorAll('canvas.is-rendered').length, viewport:document.querySelector('#viewport')?.getBoundingClientRect().toJSON()})'''), flush=True)
        raise
    f.locator('body').evaluate('async()=>await window.ReaderPdf.ready')
    print('ready', flush=True)
    f.locator('#page-number').fill('11')
    f.locator('#page-number').press('Enter')
    page.wait_for_timeout(500)
    for _ in range(4):
        f.locator('#zoom-in').click()
    page.wait_for_timeout(500)
    f.locator('#viewport').evaluate('el=>{el.scrollLeft=150;el.scrollTop+=300}')
    page.wait_for_timeout(100)

    def snap():
        return f.locator('body').evaluate('()=>window.ReaderPdf.snapshot()')
    before = snap()
    f.locator('#zoom-in').click()
    page.wait_for_timeout(500)
    after = snap()
    print('zoom', before, after, flush=True)
    assert before['anchor']['page'] == after['anchor']['page']
    assert abs(before['anchor']['y'] - after['anchor']['y']) < 0.003
    before = snap()
    page.locator('[data-reader-tab="translation"]').click()
    page.wait_for_timeout(600)
    after = snap()
    print('translation', before, after, flush=True)
    assert abs(before['anchor']['y'] - after['anchor']['y']) < 0.003
    page.locator('[data-reader-tab="assistant"]').click()
    expect(page.locator('.reader-studio')).to_have_attribute('data-reader-active-pane', 'assistant')
    expect(page.locator('[data-reader-pane="pdf"]')).to_be_visible()
    expect(page.locator('[data-reader-pane="assistant"]')).to_be_visible()
    page.wait_for_timeout(500)
    assert snap()['anchor']['page'] == after['anchor']['page']
    assert abs(snap()['anchor']['y'] - after['anchor']['y']) < 0.003
    page.locator('[data-reader-columns="1"]').click()
    link.click()
    page.wait_for_timeout(600)
    assert page.locator('[data-reader-pane="pdf"]').is_visible()
    print('navigation', snap(), flush=True)
    assert snap()['manualScale'] == after['manualScale']
    page.evaluate("window.dispatchEvent(new CustomEvent('reader:set-pane', {detail:{name:'assistant'}}))")
    page.wait_for_timeout(500)
    assert page.locator('[data-reader-pane="pdf"]').is_visible() and page.locator('[data-reader-pane="assistant"]').is_visible()
    print('split', page.locator('.evidence-panel').bounding_box(), flush=True)
    f.locator('#search-toggle').click()
    f.locator('#search-query').fill('reinforcement')
    f.locator('#pdf-search button[type="submit"]').click()
    expect(f.locator('#search-status')).to_contain_text(' / ', timeout=20000)
    expect(f.locator('.pdf-search-match').first).to_be_visible()
    print('search', f.locator('#search-status').inner_text(), flush=True)
    f.locator('#search-close').click()
    f.locator('#text-mode').click()
    f.locator('.textLayer span').filter(has_text='reinforcement').first.evaluate('el=>{const r=document.createRange();r.selectNodeContents(el);const s=window.getSelection();s.removeAllRanges();s.addRange(r)}')
    f.locator('#ask-selection').click()
    expect(page.locator('.knowledge-composer textarea')).to_have_value(re.compile('reinforcement', re.I))
    print('selection passed', flush=True)
    page.evaluate("window.dispatchEvent(new CustomEvent('reader:set-pane', {detail:{name:'translation'}}))")
    page.wait_for_timeout(500)
    assert f.locator('#translation-panel').is_visible()
    print('layout', f.locator('#viewport').bounding_box(), flush=True)
    page.screenshot(path='/tmp/reader-new-ui.png')
    f.locator('#page-number').fill('11')
    f.locator('#page-number').press('Enter')
    page.wait_for_timeout(500)
    f.locator('#viewport').evaluate('el=>{el.scrollTop+=180}')
    page.wait_for_timeout(100)
    saved = snap()
    other = page.locator('a.evidence-link[data-source-id="arxiv-2501.12948v2"]').first
    page.locator('[data-reader-columns="1"]').click()
    page.wait_for_timeout(400)
    other.click()
    page.wait_for_function("document.querySelector('.evidence-panel__frame').contentWindow.ReaderPdf?.sourceId === 'arxiv-2501.12948v2'")
    f.locator('body').evaluate('async()=>await window.ReaderPdf.ready')
    page.wait_for_timeout(300)
    page.locator('[data-reader-columns="1"]').click()
    link.click()
    page.wait_for_function("document.querySelector('.evidence-panel__frame').contentWindow.ReaderPdf?.sourceId === 'arxiv-2402.03300v3'")
    f.locator('body').evaluate('async()=>await window.ReaderPdf.ready')
    page.wait_for_timeout(700)
    restored = snap()
    print('restore', saved, restored, flush=True)
    assert restored['page'] == saved['page'] and restored['scaleMode'] == saved['scaleMode']
    assert abs(restored['anchor']['y'] - saved['anchor']['y']) < 0.01
    f.locator('body').evaluate('async()=>{\n   const {renderTranslationMath}=await import(\'./translation-math.mjs\');\n   const e=document.createElement(\'div\');e.id=\'math-test\';document.body.append(e);\n   renderTranslationMath(e, String.raw`公式 $\\pi_{\\theta}(o_t)$。\n\n\\[\\sum_{t=1}^{T} \\log p_t\\]\n\nπ_{θ_old}(o_t) = Σ_{t=1}^{T} A_t\n\n<img src=x onerror="window.badMath=true">`);\n }')
    expect(f.locator('#math-test mjx-container').first).to_be_attached(timeout=15000)
    assert f.locator('#math-test mjx-container').count() >= 3
    assert f.locator('#math-test img').count() == 0
    assert f.locator('#math-test mjx-merror').count() == 0
    f.locator('#math-test').evaluate('el=>el.remove()')
    print('math passed', flush=True)
    page.evaluate("window.dispatchEvent(new CustomEvent('reader:set-pane', {detail:{name:'assistant'}}))")
    page.wait_for_timeout(300)
    asks = []

    def fail_ask(route):
        asks.append(route.request.post_data_json)
        route.fulfill(status=502, json={'error': '模拟暂时失败'})
    page.route('**/api/ask', fail_ask)
    composer = page.locator('.knowledge-composer textarea')
    composer.fill('测试失败恢复')
    page.locator('[data-action="add-pdf"]').click()
    page.locator('[data-action="send"]').click()
    expect(page.locator('.knowledge-send-failure')).to_be_visible()
    composer.fill('正在写的新草稿')
    page.locator('.knowledge-send-failure button').filter(has_text='重试本轮').click()
    expect(page.locator('.knowledge-send-failure')).to_be_visible()
    assert len(asks) == 2 and asks[0] == asks[1]
    assert composer.input_value() == '正在写的新草稿'
    page.locator('.knowledge-send-failure button').filter(has_text='恢复到输入框').click()
    assert '测试失败恢复' in composer.input_value() and '正在写的新草稿' in composer.input_value()
    assert page.locator('.knowledge-context').count() >= 1
    page.screenshot(path='/tmp/reader-new-chat.png')
    print('retry passed', flush=True)
    for width in (900, 700):
        page.set_viewport_size({'width': width, 'height': 1000})
        page.wait_for_timeout(400)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('[data-reader-pane="pdf"]').is_visible()
        assert page.locator('[data-reader-pane="assistant"]').is_visible()
    print('errors', errors, flush=True)
    assert not errors
    b.close()
