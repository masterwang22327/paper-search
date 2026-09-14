#!/usr/bin/env python3
"""Browser regression for revisions anchored to table headers and cells."""

import subprocess
import sys

from playwright.sync_api import expect, sync_playwright
from test_reader import CHROME_PATHS, READER_DIR, TASK_ID, free_port, wait_for_server


def run(base):
    chrome = next(path for path in CHROME_PATHS if path.is_file())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
        page = browser.new_page(viewport={"width": 1524, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        state = {"revisions": {"items": []}, "faq": {"items": []}, "messages": []}

        def reply(route):
            if "/api/bootstrap" in route.request.url:
                route.fulfill(json={"token": "test", "task_id": TASK_ID})
            elif "/api/state?" in route.request.url:
                route.fulfill(json=state)
            elif "/api/revision/delete" in route.request.url:
                revision_id = route.request.post_data_json["revision_id"]
                state["revisions"]["items"] = [
                    item for item in state["revisions"]["items"] if item["id"] != revision_id
                ]
                route.fulfill(json=state["revisions"])
            else:
                route.fulfill(json={})

        # All runtime calls are mocked; user revisions are never changed.
        page.route("**/api/**", reply)
        page.goto(base + "/papers/deepseek-v2-v3-r1-lineage/")
        table = page.locator("article table:has(th[data-reader-block])").first
        expect(table.locator("tbody tr")).to_have_count(5)
        anchors = table.locator("[data-reader-block]").evaluate_all(
            "els => els.slice(0, 6).map(el => ({id: el.dataset.readerBlock, text: el.textContent}))"
        )
        prose = page.locator("article p[data-reader-block]").first.evaluate(
            "el => ({id: el.dataset.readerBlock, text: el.textContent})"
        )
        for index, anchor in enumerate([anchors[0], anchors[3], anchors[4], prose]):
            state["revisions"]["items"].append({
                "id": f"layout-{index}", "source": "ai", "title": f"修订 {index}",
                "anchor_block_id": anchor["id"], "target_blocks": [anchor["id"]],
                "target_text": anchor["text"],
                "markdown": "### 参数说明\n\n修订应显示在完整表格下方。\n\n"
                    "| 模块 | 参数 |\n| --- | --- |\n| Attention | 100 |\n\n"
                    "```python\nprint('example')\n```",
            })
        # Legacy manual revisions whose offsets no longer match use a card too.
        state["revisions"]["items"].append({
            **state["revisions"]["items"][1], "id": "layout-4", "source": "manual",
            "selection_contexts": [{"block_id": "missing", "start": 0, "end": 7, "text": "removed"}],
        })
        page.reload()
        cards = page.locator("article .reader-revision")
        expect(cards).to_have_count(5)
        expect(table.locator("tbody tr")).to_have_count(5)
        expect(table.locator("thead th")).to_have_count(3)
        expect(table.locator("tbody td")).to_have_count(15)
        expect(page.locator("table .reader-revision, .md-typeset__scrollwrap .reader-revision")).to_have_count(0)
        order = table.evaluate("""el => {
            let next = el.closest('.md-typeset__scrollwrap').nextElementSibling;
            if (next?.matches('.reader-table-hint')) next = next.nextElementSibling;
            const ids = [];
            while (next?.matches('.reader-revision')) {
                ids.push(next.dataset.revisionId); next = next.nextElementSibling;
            }
            return ids;
        }""")
        assert order == ["layout-0", "layout-1", "layout-2", "layout-4"], order
        assert page.locator('[data-revision-id="layout-3"]').evaluate(
            "el => el.previousElementSibling.dataset.readerBlock"
        ) == prose["id"]
        for width in (1524, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            assert table.bounding_box()["height"] < 650
            bounds = page.locator("article.md-content__inner").bounding_box()
            for card in cards.all():
                box = card.bounding_box()
                assert box["x"] >= bounds["x"] - 1, box
                assert box["x"] + box["width"] <= bounds["x"] + bounds["width"] + 1, box
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        first = page.locator('[data-revision-id="layout-0"]')
        first.locator(".reader-revision__toggle").click()
        expect(first.locator(".reader-revision__content")).to_be_hidden()
        page.reload()
        expect(first.locator(".reader-revision__content")).to_be_hidden()
        first.locator(".reader-revision__toggle").click()
        expect(first.locator(".reader-revision__content")).to_be_visible()
        page.once("dialog", lambda dialog: dialog.accept())
        first.get_by_role("button", name="恢复原文").click()
        expect(cards).to_have_count(4)
        expect(table.locator("tbody tr")).to_have_count(5)
        expect(page.locator("table .reader-revision")).to_have_count(0)

        # Desktop evidence mode retains the adjustable side-by-side workspace.
        page.set_viewport_size({"width": 1524, "height": 900})
        page.locator(".evidence-panel-toggle").click()
        panel = page.locator(".evidence-panel")
        expect(panel).to_be_visible()
        panel_box = panel.bounding_box()
        assert panel_box["x"] > 400, panel_box
        assert 360 < panel_box["width"] < 1000, panel_box
        expect(page.locator(".evidence-panel__resizer")).to_be_visible()
        page.locator('[data-reader-tab="assistant"]').click()
        assert page.locator(".knowledge-composer").bounding_box()["width"] > 340
        page.keyboard.press("Escape")
        expect(panel).to_be_hidden()
        expect(page.locator(".evidence-panel-toggle")).to_be_focused()

        # Selection controls stay in the viewport and the revision form behaves
        # as a keyboard-accessible modal without accidental backdrop dismissal.
        page.evaluate("""() => {
          const block = [...document.querySelectorAll('article.md-content__inner p[data-reader-block]')]
            .find(element => element.textContent.trim().length > 30);
          block.scrollIntoView({block: 'end'});
          const node = document.createTreeWalker(block, NodeFilter.SHOW_TEXT).nextNode();
          const range = document.createRange();
          range.setStart(node, 0);
          range.setEnd(node, Math.min(20, node.length));
          const selection = getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          document.dispatchEvent(new Event('selectionchange'));
        }""")
        menu = page.locator(".knowledge-selection-menu.is-visible")
        expect(menu).to_be_visible()
        menu_box = menu.bounding_box()
        assert menu_box["y"] >= 0 and menu_box["y"] + menu_box["height"] <= 900
        menu.get_by_role("button", name="AI 修订").click()
        dialog = page.locator(".reader-revision-editor__dialog")
        expect(dialog).to_have_attribute("role", "dialog")
        expect(dialog).to_have_attribute("aria-modal", "true")
        assert dialog.bounding_box()["width"] <= 760
        assert dialog.bounding_box()["x"] > 0
        assert page.locator(".md-main").evaluate("element => Boolean(element.closest('[inert]'))")
        assert dialog.locator(".reader-revision-editor__actions").evaluate(
            "element => getComputedStyle(element).position"
        ) == "sticky"
        page.locator(".reader-revision-editor").click(position={"x": 2, "y": 2})
        expect(dialog).to_be_visible()
        dialog.focus()
        page.keyboard.press("Tab")
        expect(dialog.locator('[name="model"]')).to_be_focused()
        page.keyboard.press("Shift+Tab")
        expect(dialog.locator('[type="submit"]')).to_be_focused()
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        assert not page.locator(".md-main").evaluate("element => Boolean(element.closest('[inert]'))")
        assert not page.locator("body").evaluate(
            "element => element.classList.contains('reader-modal-open')"
        )
        card = page.locator('[data-revision-id="layout-1"]')
        card.evaluate("""element => {
          let next = element.nextElementSibling;
          while (next?.matches('.reader-revision, .reader-table-hint')) next = next.nextElementSibling;
          window.__continuedToOriginal = false;
          next.scrollIntoView = () => { window.__continuedToOriginal = true; };
        }""")
        card.locator('.reader-revision__continue').click()
        assert page.evaluate("window.__continuedToOriginal")
        assert not errors, errors
        browser.close()
    print("Revision layout regression checks passed")


if __name__ == "__main__":
    port = free_port()
    server = subprocess.Popen([
        sys.executable, str(READER_DIR / "site_store.py"), "serve", "--database",
        str(READER_DIR / "user-data" / TASK_ID / "site.sqlite3"), "--port", str(port),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{port}"
        wait_for_server(base)
        run(base)
    finally:
        server.terminate()
        server.wait(timeout=10)
