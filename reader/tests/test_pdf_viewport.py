#!/usr/bin/env python3
"""Check PDF viewport persistence against a running Reader."""

import sys
import os

from playwright.sync_api import expect, sync_playwright
from test_reader import CHROME_PATHS


def run(base):
    chrome = next(path for path in CHROME_PATHS if path.is_file())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get("READER_TEST_BROWSER") or str(chrome), headless=True)
        page = browser.new_page(viewport={"width": 1816, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/api/translation/page?*", lambda route: route.fulfill(
            json={"translation": None, "source_text": ""}
        ))
        page.route("**/api/translation/full?*", lambda route: route.fulfill(
            json={"status": "idle", "total": 30, "completed": 0}
        ))
        page.goto(base + "/papers/reasoning-rl-reductions/#1", wait_until="domcontentloaded")
        page.locator('a.evidence-link[data-source-id="arxiv-2402.03300v3"]').first.click()
        viewer = page.frame_locator(".evidence-panel__frame")
        expect(viewer.locator("canvas.is-rendered").first).to_be_visible(timeout=30000)
        viewport = viewer.locator("#viewport")

        def position():
            return viewport.evaluate("""el => ({
                top: el.scrollTop, left: el.scrollLeft,
                page: document.querySelector('#page-number').value,
                zoom: document.querySelector('#zoom-label').textContent
            })""")

        for width in (1816, 900):
            page.set_viewport_size({"width": width, "height": 1000})
            for translated in (False, True):
                pane = "translation" if translated else "pdf"
                page.evaluate("name => window.dispatchEvent(new CustomEvent('reader:set-pane', {detail:{name}}))", pane)
                for mode in ("manual", "fit"):
                    viewer.locator('#fit-width').click()
                    if mode == "manual":
                        for _ in range(9):
                            viewer.locator('#zoom-in').click()
                    viewer.locator("#page-number").fill("11")
                    viewer.locator("#page-number").press("Enter")
                    page.wait_for_timeout(500)
                    viewport.evaluate("el => { el.scrollLeft = 180; el.scrollTop += 120; }")
                    page.wait_for_timeout(150)
                    before = position()
                    if mode == "manual":
                        assert before["left"] > 0, before
                    before_anchor = viewer.locator('body').evaluate('() => window.ReaderPdf.snapshot().anchor')
                    for tab in ("assistant", "faq", "insight"):
                        page.locator(f'[data-reader-tab="{tab}"]').click()
                        page.wait_for_timeout(180)
                        page.evaluate("name => window.dispatchEvent(new CustomEvent('reader:set-pane', {detail:{name}}))", pane)
                        page.wait_for_timeout(400)
                        after_anchor = viewer.locator('body').evaluate('() => window.ReaderPdf.snapshot().anchor')
                        assert before_anchor['page'] == after_anchor['page']
                        for axis in ('x', 'y'):
                            assert abs(before_anchor[axis] - after_anchor[axis]) < .004, (width, translated, mode, tab, before_anchor, after_anchor)
                    print(f"Viewport preserved: width={width}, translation={translated}, mode={mode}", flush=True)

        viewer.locator("#page-number").fill("15")
        viewer.locator("#page-number").press("Enter")
        page.wait_for_timeout(500)
        expect(viewer.locator("#page-number")).to_have_value("15")
        offset = viewport.evaluate("""el => ({
            top: el.scrollTop - document.querySelector('.pdf-page[data-page="15"]').offsetTop,
            left: el.scrollLeft
        })""")
        assert abs(offset["top"] + 16) <= 1 and offset["left"] == 0, offset
        assert not errors, errors
        browser.close()


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000")
