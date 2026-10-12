"""Exercise the single-toolbar reading studio without issuing model requests."""
import copy
import os
import sys
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, expect
from test_page_insight import ANSWER
from test_reader import CHROME_PATHS

base = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get('READER_TEST_BROWSER') or str(next(path for path in CHROME_PATHS if path.is_file())), headless=True)
    page = browser.new_page(viewport={'width': 1600, 'height': 1000}, color_scheme='light')
    errors = []
    posts = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def choose_columns(count):
        page.locator(f'[data-reader-columns="{count}"]').click()

    def insight(route):
        if route.request.method != 'GET':
            posts.append(route.request.url)
        query = parse_qs(urlparse(route.request.url).query)
        value = copy.deepcopy(ANSWER)
        value['main_point'] = '组内相对优势：让奖励成为策略更新的方向。'
        value['sections'] = value['sections'] * 6
        route.fulfill(json={'insight': {'page': int(query.get('page', ['11'])[0]), 'model': 'gpt-6-astra', 'reasoning_effort': 'high', 'content': value}, 'cached': True})
    page.route('**/api/pdf/page-insight*', insight)
    page.goto(base + '/papers/reasoning-rl-reductions/#1', wait_until='domcontentloaded')
    link = page.locator('a.evidence-link[data-source-id="arxiv-2402.03300v3"]').first
    link.scroll_into_view_if_needed()
    before_article = page.evaluate('scrollY')
    link.click()
    f = page.frame_locator('.evidence-panel__frame')
    expect(f.locator('canvas.is-rendered').first).to_be_visible(timeout=30000)
    f.locator('body').evaluate('async () => await window.ReaderPdf.ready')
    expect(f.locator('#translation-panel')).to_be_visible()
    layout = page.locator('.reader-layout-control')
    assert layout.bounding_box()['x'] >= page.locator('.evidence-panel__tabs').bounding_box()['x']
    for count in (1, 2, 3):
        expect(page.locator(f'[data-reader-columns="{count}"]')).to_be_visible()
    page.screenshot(path='/tmp/reader-layout-direct.png')
    expect(page.locator('.md-main')).to_be_visible()
    assert page.locator('.md-main').bounding_box()['width'] == 480
    assert page.locator('.evidence-panel__frame').bounding_box()['x'] == 480
    assert page.locator('.md-main').evaluate('el => el.scrollTop') > 100
    expect(link).to_be_in_viewport()
    page.screenshot(path='/tmp/reader-three-columns.png')
    page.locator('[data-reader-tab="insight"]').click()
    assert page.locator('.evidence-panel__layout,.evidence-panel__external,[data-reader-tab="pdf"]').count() == 0
    expect(f.locator('.pdf-column .toolbar')).to_be_visible()
    assert page.locator('.reader-studio-bar [data-pdf-command]').count() == 0
    f.locator('#page-number').fill('11')
    f.locator('#page-number').press('Enter')
    page.wait_for_timeout(500)
    for _ in range(3): f.locator('#zoom-in').click()
    page.wait_for_timeout(500)
    f.locator('#viewport').evaluate('el => {el.scrollTop += 140;el.scrollLeft=100}')
    page.wait_for_timeout(100)
    def snapshot(): return f.locator('body').evaluate('() => window.ReaderPdf.snapshot()')
    initial = snapshot()
    for name in ('translation', 'assistant', 'faq', 'insight'):
        page.locator(f'[data-reader-tab="{name}"]').click()
        page.wait_for_timeout(550)
        now = snapshot()
        print(name, initial['anchor'], now['anchor'], flush=True)
        assert now['anchor']['page'] == initial['anchor']['page']
        assert abs(now['anchor']['y'] - initial['anchor']['y']) < .004
        assert abs(now['anchor']['x'] - initial['anchor']['x']) < .004
        expect(f.locator('#viewport')).to_be_visible()
        if name in ('insight', 'translation'):
            expect(f.locator(f'#{name}-panel')).to_be_visible()
        else: expect(page.locator(f'[data-reader-pane="{name}"]')).to_be_visible()
        page.screenshot(path=f'/tmp/reader-studio-{name}.png')
    # Translation also retains its independent reading position.
    page.locator('[data-reader-tab="translation"]').click()
    expect(f.locator('.translation-block').first).to_be_visible()
    f.locator('#translation-content').evaluate('el=>el.scrollTop=260')
    page.wait_for_timeout(150)
    page.locator('[data-reader-tab="faq"]').click()
    page.locator('.knowledge-faq-search input').fill('保留搜索词')
    page.locator('[data-reader-tab="translation"]').click()
    page.wait_for_timeout(300)
    assert abs(f.locator('#translation-content').evaluate('el=>el.scrollTop') - 260) < 2
    page.locator('[data-reader-tab="faq"]').click()
    expect(page.locator('.knowledge-faq-search input')).to_have_value('保留搜索词')
    page.locator('[data-reader-tab="insight"]').click()
    # Re-clicking the current tool gives the whole workspace to the paper.
    page.locator('[data-reader-tab="insight"]').click()
    expect(f.locator('#insight-panel')).to_be_hidden()
    assert f.locator('#viewport').bounding_box()['width'] > 1100
    page.locator('[data-reader-tab="insight"]').click()
    expect(f.locator('#insight-content .insight-section').first).to_be_visible()
    expect(f.locator('.insight-claim-type').first).to_have_text('方法设计')
    explanation = f.locator('.insight-explanation').first
    assert not explanation.evaluate('el => el.open')
    explanation.locator('summary').first.click()
    assert explanation.evaluate('el => el.open')
    expect(explanation.locator('p').first).to_be_visible()
    explanation.locator('summary').first.click()
    expect(f.locator('.insight-modern h3')).to_have_text('放到今天怎么看')
    expect(f.locator('.insight-freshness')).to_contain_text('未核验最新进展')
    f.locator('#insight-content').evaluate('el=>el.scrollTop=340')
    page.wait_for_timeout(100)
    page.locator('[data-reader-tab="assistant"]').click()
    composer = page.locator('.knowledge-composer textarea')
    composer.fill('保留这段尚未发送的问题')
    page.locator('.knowledge-messages').evaluate('el=>el.scrollTop=300')
    chat_top = page.locator('.knowledge-messages').evaluate('el=>el.scrollTop')
    page.locator('[data-reader-tab="insight"]').click()
    page.wait_for_timeout(500)
    assert abs(f.locator('#insight-content').evaluate('el=>el.scrollTop') - 340) < 2
    page.locator('[data-reader-tab="assistant"]').click()
    page.wait_for_timeout(300)
    expect(composer).to_have_value('保留这段尚未发送的问题')
    assert abs(page.locator('.knowledge-messages').evaluate('el=>el.scrollTop') - chat_top) < 2
    # PDF commands stay inside the PDF column; settings occupy normal space at the top.
    tools = f.locator('.toolbar').bounding_box()
    viewport = f.locator('#viewport').bounding_box()
    assert abs(tools['x'] - viewport['x']) < 2
    assert abs(tools['width'] - viewport['width']) < 2
    assert tools['y'] + tools['height'] <= viewport['y'] + 1
    page.route('**/api/chat/settings', lambda route: route.fulfill(json=route.request.post_data_json) if route.request.method == 'POST' else route.continue_())
    settings = page.locator('.knowledge-options')
    settings.locator('summary').click()
    settings_box = settings.bounding_box()
    messages_box = page.locator('.knowledge-messages').bounding_box()
    assert settings_box['y'] + settings_box['height'] <= messages_box['y']
    page.locator('[data-setting="knowledge-model"]').select_option('gpt-6-astra')
    expect(settings).to_have_attribute('open', '')
    page.locator('[data-setting="knowledge-effort"]').select_option('high')
    expect(settings).to_have_attribute('open', '')
    settings.locator('summary').click()
    expect(settings).not_to_have_attribute('open', '')
    expect(composer).to_have_value('保留这段尚未发送的问题')
    f.locator('#search-toggle').click()
    expect(f.locator('#search-query')).to_be_visible()
    f.locator('#search-query').fill('reinforcement')
    f.locator('#search-query').press('Enter')
    expect(f.locator('#search-status')).to_contain_text(' / ', timeout=15000)
    f.locator('#search-close').click()
    saved_view = snapshot()
    choose_columns(1)
    expect(page.locator('.evidence-panel__panes')).to_be_hidden()
    expect(page.locator('[data-reader-columns="1"]')).to_have_attribute('aria-pressed', 'true')
    page.wait_for_timeout(200)
    assert abs(page.evaluate('scrollY')-before_article)<2
    page.screenshot(path='/tmp/reader-one-column.png')
    choose_columns(2)
    expect(page.locator('.reader-studio')).to_have_attribute('data-reader-active-pane', 'pdf')
    expect(page.locator('[data-reader-columns="2"]')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('[data-reader-pane="assistant"]')).to_be_hidden()
    page.screenshot(path='/tmp/reader-two-columns.png')
    choose_columns(3)
    expect(page.locator('.reader-studio')).to_have_attribute('data-reader-active-pane', 'assistant')
    expect(page.locator('[data-reader-columns="3"]')).to_have_attribute('aria-pressed', 'true')
    page.wait_for_timeout(400)
    assert snapshot()['anchor']['page'] == saved_view['anchor']['page']
    assert abs(snapshot()['anchor']['y'] - saved_view['anchor']['y']) < .004
    page.locator('[data-reader-tab="assistant"]').click()
    expect(page.locator('[data-reader-columns="2"]')).to_have_attribute('aria-pressed', 'true')
    choose_columns(1)
    page.locator('[data-reader-tab="assistant"]').click()
    expect(page.locator('[data-reader-columns="3"]')).to_have_attribute('aria-pressed', 'true')
    expect(composer).to_have_value('保留这段尚未发送的问题')
    for width in (1280,900):
        page.set_viewport_size({'width':width,'height':900})
        for name in ('translation','assistant','faq','insight'):
            page.locator(f'[data-reader-tab="{name}"]').click()
            page.wait_for_timeout(200)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert f.locator('#viewport').bounding_box()['width'] > 180
        page.screenshot(path=f'/tmp/reader-studio-{width}.png')
    # Common splitter keeps both kinds of companion pane at the same width.
    page.set_viewport_size({'width': 1600, 'height': 1000})
    page.locator('.reader-splitter').focus()
    page.locator('.reader-splitter').press('ArrowRight')
    page.wait_for_timeout(300)
    inside_width = f.locator('#viewport').bounding_box()['width']
    page.locator('[data-reader-tab="assistant"]').click()
    page.wait_for_timeout(300)
    assert abs(f.locator('#viewport').bounding_box()['width'] - inside_width) < 2
    page.locator('.reader-splitter').dblclick()
    # Drag both boundaries in viewport coordinates, retaining the PDF anchor.
    initial = snapshot()
    divider = page.locator('.reader-document-splitter').bounding_box()
    page.mouse.move(divider['x'] + 4, divider['y'] + 80)
    page.mouse.down()
    page.mouse.move(560, divider['y'] + 80, steps=8)
    page.mouse.up()
    page.wait_for_timeout(400)
    assert abs(page.locator('.md-main').bounding_box()['width'] - 560) < 2
    assert page.evaluate("localStorage.getItem('reader-document-share')") == '35'
    assert abs(snapshot()['anchor']['y'] - initial['anchor']['y']) < .005
    divider = page.locator('.reader-splitter').bounding_box()
    page.mouse.move(divider['x'] + 4, divider['y'] + 80)
    page.mouse.down()
    page.mouse.move(1100, divider['y'] + 80, steps=8)
    page.mouse.up()
    page.wait_for_timeout(400)
    assert abs(f.locator('#viewport').bounding_box()['width'] - 540) < 3
    # The document remains interactive, and its independent scrolling does not move the PDF.
    initial = snapshot()
    article_top = page.locator('.md-main').evaluate('el => el.scrollTop')
    page.locator('.md-main').evaluate('el => el.scrollTop += 400')
    page.wait_for_timeout(200)
    assert page.locator('.md-main').evaluate('el => el.scrollTop') > article_top + 390
    assert snapshot()['anchor'] == initial['anchor']
    page.locator('.md-main').evaluate('''el => {
      const edge = el.getBoundingClientRect().top;
      window.documentProbe = [...el.querySelectorAll('.md-content__inner :is(p,a,h2,h3)')].find(p => {
        const b = p.getBoundingClientRect(); return b.top > edge + 30 && b.bottom < innerHeight;
      });
    }''')
    page.screenshot(path='/tmp/reader-three-columns-resized.png')
    choose_columns(1)
    assert page.evaluate('documentProbe.getBoundingClientRect().bottom > 0 && documentProbe.getBoundingClientRect().top < innerHeight')
    choose_columns(3)
    assert abs(page.locator('.md-main').bounding_box()['width'] - 560) < 2
    page.locator('.reader-document-splitter').dblclick()
    page.locator('.reader-splitter').dblclick()
    # Toggle the real site setting while the OS remains light; embedded panels
    # must follow the selected site theme, including manual overrides.
    choose_columns(1)
    page.locator('#__palette_1').evaluate('el => el.click()')
    expect(page.locator('body')).to_have_attribute('data-md-color-scheme', 'slate')
    choose_columns(3)
    page.wait_for_timeout(300)
    expect(f.locator('html')).to_have_attribute('data-reader-theme', 'dark')
    assert page.locator('.reader-studio').evaluate("el => getComputedStyle(el).getPropertyValue('--studio-surface').trim()") == '#232e3d'
    for name in ('translation','faq','assistant','insight'):
        page.locator(f'[data-reader-tab="{name}"]').click()
        page.wait_for_timeout(200)
        page.screenshot(path=f'/tmp/reader-studio-dark-{name}.png')
    assert not posts, posts
    assert not errors, errors
    print('Studio controls, four modes, anchors, scroll/draft restoration, return position and responsive layout passed.', flush=True)
    browser.close()
