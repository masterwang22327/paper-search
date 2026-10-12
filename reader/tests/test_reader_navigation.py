"""Check the first paint and layout restoration while Reader scripts are delayed."""
import asyncio
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright, expect

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
CHROME = os.environ.get("READER_TEST_BROWSER") or next(str(p) for p in (
    Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),
    Path('/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'),
) if p.is_file())


async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=CHROME, headless=True)
        page = await browser.new_page(viewport={"width": 1600, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        # Do not change saved reading positions during this regression check.
        async def progress(route):
            if route.request.method == 'POST':
                await route.fulfill(json={})
            else:
                await route.continue_()
        await page.route('**/api/reading-progress*', progress)
        await page.add_init_script('''
            window.headerFrames = [];
            function sample() {
              const bar = document.querySelector('.reader-studio-bar');
              const header = document.querySelector('.md-header');
              if (bar && header && document.querySelector('.md-main')) {
                const box = bar.getBoundingClientRect();
                window.headerFrames.push({
                  header: getComputedStyle(header).visibility,
                  height: box.height,
                  columns: document.querySelector('[data-reader-columns][aria-pressed="true"]')?.dataset.readerColumns,
                  width: document.querySelector('.md-main').getBoundingClientRect().width
                });
              }
              requestAnimationFrame(sample);
            }
            requestAnimationFrame(sample);
        ''')
        gate = asyncio.Event()
        async def delay_reader(route):
            await gate.wait()
            await route.continue_()
        await page.route('**/javascripts/evidence-panel.js*', delay_reader)

        async def check_page(path, columns, click=False):
            gate.clear()
            target = BASE + path
            if click:
                # Use an ordinary anchor, including when navigation is hidden in split mode.
                await page.locator('.md-nav--primary a[href]').evaluate_all('(links, target) => links.find(link => link.href === target).click()', target)
                await page.wait_for_url(target, wait_until='commit')
                navigation = None
            else:
                navigation = asyncio.create_task(page.goto(target, wait_until='load'))
            await expect(page.locator('h1').first).to_be_visible()
            await expect(page.locator('.reader-studio-bar')).to_be_visible()
            await expect(page.locator(f'[data-reader-columns="{columns}"]')).to_have_attribute('aria-pressed', 'true')
            before = await page.locator('.reader-studio-bar').bounding_box()
            assert await page.locator('.md-header').evaluate('el => getComputedStyle(el).visibility') == 'hidden'
            # The script remains blocked: this must be the prerendered HTML shell.
            assert await page.locator('.evidence-panel-toggle').count() == 0
            await page.wait_for_timeout(120)
            gate.set()
            if navigation:
                await navigation
            await page.wait_for_load_state('load')
            await expect(page.locator('.evidence-panel-toggle')).to_have_count(1)
            await expect(page.locator(f'[data-reader-columns="{columns}"]')).to_have_attribute('aria-pressed', 'true')
            await page.wait_for_timeout(150)
            after = await page.locator('.reader-studio-bar').bounding_box()
            assert before == after, (before, after)
            frames = await page.evaluate('window.headerFrames')
            assert frames and all(f['header'] == 'hidden' and f['height'] > 0 and f['columns'] == str(columns) for f in frames), frames
            if columns > 1:
                assert all(abs(f['width'] - 480) < 1 for f in frames), frames
                source = await page.evaluate('() => (document.querySelector(\'a.evidence-link[data-primary="true"]\') || document.querySelector(\'a.evidence-link[data-pdf][data-page]\')).dataset.sourceId')
                assert source in await page.locator('.evidence-panel__frame').get_attribute('src')
            print(f'First paint and initialization stable: {path}, {columns} columns', flush=True)

        await check_page('/papers/arxiv-1706.03762/', 1)
        await check_page('/papers/modern-transformer-block/', 1, click=True)
        await page.locator('[data-reader-columns="2"]').click()
        await check_page('/papers/arxiv-1706.03762/', 2, click=True)
        await page.locator('[data-reader-columns="3"]').click()
        await check_page('/papers/modern-transformer-block/', 3, click=True)
        await page.goto(BASE + '/reading-guide/')
        await expect(page.locator('.md-header')).to_be_visible()
        await expect(page.locator('.reader-studio-bar')).to_be_hidden()
        await check_page('/papers/arxiv-1706.03762/', 3, click=True)
        await page.locator('[data-reader-columns="1"]').click()
        await check_page('/papers/modern-transformer-block/', 1, click=True)
        assert not errors, errors
        await browser.close()


asyncio.run(main())
