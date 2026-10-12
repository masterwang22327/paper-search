"""Guard against raw concept-lab HTML escaping the Markdown article container."""
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
CHROME = os.environ.get('READER_TEST_BROWSER') or next(str(p) for p in (
    Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),
    Path('/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'),
) if p.is_file())


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=CHROME, headless=True)
        page = browser.new_page(viewport={'width': 1848, 'height': 900})
        # Preserve user reading progress; this test never calls a model.
        page.route('**/api/reading-progress*', lambda route: route.fulfill(json={})
                   if route.request.method == 'POST' else route.continue_())
        page.goto(BASE + '/papers/knowledge-distillation-autoregressive/')
        article = page.locator('article.md-content__inner')
        expect(article).to_be_visible()
        assert page.locator('[data-reader-block]').evaluate_all(
            "els => els.every(el => !!el.closest('article.md-content__inner'))"
        ), 'Document blocks escaped the article into the outer flex layout'
        expect(article.locator('.distillation-policy-lab__flow > article')).to_have_count(4)
        expect(article.locator('.distillation-policy-lab__readout > section')).to_have_count(3)
        expect(article.locator('.kl-intuition-lab__metrics > section')).to_have_count(4)
        assert not article.locator('pre').evaluate_all(
            "els => els.some(el => /data-kl-metric|data-distillation-metric/.test(el.textContent))"
        ), 'Raw widget HTML was rendered as a code block'
        for columns in (1, 2, 3, 1):
            page.locator(f'[data-reader-columns="{columns}"]').click()
            expect(page.locator(f'[data-reader-columns="{columns}"]')).to_have_attribute('aria-pressed', 'true')
            assert article.locator('h1').bounding_box()['width'] > 200
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
        page.locator('details').evaluate_all('els => els.forEach(el => el.open = true)')
        page.locator('[data-distillation-preset="gkd"]').click()
        expect(page.locator('[data-distillation-preset="gkd"]')).to_have_attribute('aria-pressed', 'true')
        slider = page.locator('[data-kl-focus]')
        slider.fill('70')
        slider.dispatch_event('input')
        expect(page.locator('[data-kl-output]')).to_have_text('0.70')
        page.locator('details').evaluate_all('els => els.forEach(el => el.open = false)')
        page.locator('h1').scroll_into_view_if_needed()
        page.screenshot(path='/tmp/opd-layout-fixed.png')
        browser.close()
        print('PASS: article containment, widget structure/interactions, and 1/2/3-column layouts')


if __name__ == '__main__':
    main()
