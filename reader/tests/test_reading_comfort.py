"""Check reading reflow, saved preferences and tool access without runtime writes."""
import sys
from playwright.sync_api import sync_playwright, expect
from test_reader import CHROME_PATHS


def run(base):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(next(path for path in CHROME_PATHS if path.is_file())), headless=True)
        page = browser.new_page(viewport={'width': 1484, 'height': 960})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.route('**/api/**', lambda r: r.fulfill(json={'token': 'test'} if '/bootstrap' in r.request.url else {}))
        url = base + '/papers/reasoning-rl-reductions/#grpo'
        page.goto(url)
        page.evaluate('MathJax.startup.promise')
        article = page.locator('article.md-content__inner')
        focus = page.locator('[data-reader-focus]')
        settings = page.locator('[data-reader-appearance]')
        panel = page.locator('#reader-appearance-panel')
        launcher = page.locator('[data-reading-action="toggle"]')
        page.locator('#grpo').evaluate('e => e.scrollIntoView()')
        expect(focus).to_be_visible()
        assert article.evaluate('e=>getComputedStyle(e).fontSize') == '18px'
        assert article.bounding_box()['width'] <= 960
        page.screenshot(path='/tmp/reader-comfort-default.png')

        # A paragraph spanning the reading edge remains in view across reflow.
        anchor = page.evaluate('''() => {
            const edge=document.querySelector('.reader-section-tools').getBoundingClientRect().bottom+12;
            const el=[...document.querySelectorAll('article [data-reader-block]')].find(e=>!e.querySelector('[data-reader-block]') && e.getBoundingClientRect().bottom>edge);
            return {id:el.dataset.readerBlock};
        }''')
        focus.click()
        expect(focus).to_have_text('退出专注')
        bounds = article.bounding_box()
        assert abs(bounds['x'] + bounds['width']/2 - 742) < 2, bounds
        expect(page.locator('.md-sidebar--primary')).not_to_be_visible()
        expect(page.locator('.md-sidebar--secondary')).not_to_be_visible()
        expect(page.locator(f'[data-reader-block="{anchor["id"]}"]')).to_be_in_viewport()
        expect(launcher).to_be_visible()
        assert launcher.evaluate('e=>e.closest(".reader-tool-dock")===null')
        settings.click()
        expect(panel).to_be_visible()
        panel.locator('[data-preference="font"][data-value="20"]').click()
        panel.locator('[data-preference="width"][data-value="800"]').click()
        panel.locator('[data-preference="tone"][data-value="warm"]').click()
        assert article.evaluate('e=>getComputedStyle(e).fontSize') == '20px'
        assert article.bounding_box()['width'] <= 800
        assert abs(article.bounding_box()['x'] + article.bounding_box()['width']/2 - 742) < 2
        assert article.evaluate('e=>getComputedStyle(e).backgroundColor') == 'rgb(250, 246, 237)'
        page.keyboard.press('Escape')
        expect(panel).not_to_be_visible()
        expect(settings).to_be_focused()
        page.screenshot(path='/tmp/reader-comfort-focus.png')
        page.reload()
        page.evaluate('MathJax.startup.promise')
        expect(focus).to_have_text('退出专注')
        assert article.evaluate('e=>getComputedStyle(e).fontSize') == '20px'
        assert article.bounding_box()['width'] <= 800
        settings.click()
        panel.locator('[data-preference="tone"][data-value="dark"]').click()
        expect(page.locator('body')).to_have_attribute('data-md-color-scheme', 'slate')
        assert article.evaluate('e=>getComputedStyle(e).backgroundColor') != 'rgb(250, 246, 237)'
        page.screenshot(path='/tmp/reader-comfort-settings.png')
        page.keyboard.press('Escape')
        page.reload()
        expect(page.locator('body')).to_have_attribute('data-md-color-scheme', 'slate')
        settings.click()
        panel.get_by_role('button', name='恢复默认').click()
        expect(focus).to_have_text('专注')
        expect(page.locator('.md-sidebar--primary')).to_be_visible()
        page.keyboard.press('Escape')

        # Narrow layouts keep the memo reachable outside the hidden TOC.
        for width in (1920, 1484, 1280, 1024, 760, 390):
            page.set_viewport_size({'width': width, 'height': 960})
            page.wait_for_timeout(150)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'), width
            assert article.bounding_box()['width'] <= 960, width
            assert page.locator('.md-top').bounding_box()['height'] < 60
            expect(launcher).to_be_visible()
            if width <= 1440:
                expect(page.locator('.md-sidebar--secondary')).not_to_be_visible()
                assert launcher.evaluate('e=>e.closest(".reader-tool-dock")===null')
            launcher.click()
            memo = page.locator('[data-reading-role="panel"]')
            expect(memo).to_be_visible()
            box = memo.bounding_box()
            assert box['x'] >= 0 and box['x']+box['width'] <= width+1, (width, box)
            assert box['y'] >= 0 and box['y']+box['height'] <= 960, (width, box)
            page.locator('[data-reading-action="toggle-close"]').click()
        page.screenshot(path='/tmp/reader-comfort-mobile.png')
        # Wide formulas scroll independently and remain reachable by keyboard.
        overflow = page.locator('div.arithmatex').evaluate_all('els => els.findIndex(e => e.scrollWidth > e.clientWidth + 2)')
        assert overflow >= 0
        formula = page.locator('div.arithmatex').nth(overflow)
        formula.scroll_into_view_if_needed()
        expect(formula).to_have_attribute('tabindex', '0')
        expect(formula.locator('+ .reader-math-hint')).to_be_visible()
        formula.focus()
        page.keyboard.press('ArrowRight')
        page.wait_for_timeout(200)
        assert formula.evaluate('e => e.scrollLeft') > 0
        page.locator('.reader-nav-toggle').click()
        expect(page.locator('#__drawer')).to_be_checked()
        page.locator('.md-overlay').click(position={'x': 375, 'y': 500})
        expect(page.locator('#__drawer')).not_to_be_checked()
        page.set_viewport_size({'width': 1280, 'height': 960})
        page.goto(base + '/papers/deepseek-v2-v3-r1-lineage/')
        page.evaluate('MathJax.startup.promise')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        expect(page.locator('.reader-table-scroll').first).to_be_visible()
        assert not errors, errors
        browser.close()
        print('Reading comfort checks passed: reflow, persistence, themes, six viewport sizes and tables')


if __name__ == '__main__':
    run(sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000')
