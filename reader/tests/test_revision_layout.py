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
        token = "test"
        proposal_requests = []
        proposal_error = False
        pending_proposals = []

        def finish_proposal(route):
            route.fulfill(json={
                "id": "discussion-test", "target_text": "original",
                "turns": [{"instruction": route.request.post_data_json["instruction"], "candidate": {
                    "candidate_id": "candidate-test", "title": "Token recovery",
                    "markdown": "Recovered preview", "summary": "test",
                }}],
            })

        def reply(route):
            if "/api/bootstrap" in route.request.url:
                route.fulfill(json={"token": token, "task_id": TASK_ID})
            elif "/api/state?" in route.request.url:
                route.fulfill(json=state)
            elif "/api/revision/delete" in route.request.url:
                revision_id = route.request.post_data_json["revision_id"]
                state["revisions"]["items"] = [
                    item for item in state["revisions"]["items"] if item["id"] != revision_id
                ]
                route.fulfill(json=state["revisions"])
            elif "/api/revision/propose" in route.request.url:
                proposal_requests.append(route.request.post_data_json)
                if route.request.headers.get("x-reader-token") != token:
                    route.fulfill(status=403, json={"error": "expired", "code": "invalid_token"})
                elif proposal_error:
                    route.fulfill(status=400, content_type="text/html", body="<!DOCTYPE html><title>Bad Request</title>")
                else:
                    pending_proposals.append(route)
            else:
                route.fulfill(json={})

        # All runtime calls are mocked; user revisions are never changed.
        page.route("**/api/**", reply)
        page.goto(base + "/papers/deepseek-v2-v3-r1-lineage/")
        table = page.locator("article table:has(th[data-reader-block])").first
        row_count = table.locator("tbody tr").count()
        cell_count = table.locator("tbody td").count()
        assert row_count >= 5 and cell_count == row_count * 3
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
        expect(table.locator("tbody tr")).to_have_count(row_count)
        expect(table.locator("thead th")).to_have_count(3)
        expect(table.locator("tbody td")).to_have_count(cell_count)
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
        expect(table.locator("tbody tr")).to_have_count(row_count)
        expect(page.locator("table .reader-revision")).to_have_count(0)

        # Use the current studio's single-column control for document reading.
        page.set_viewport_size({"width": 1524, "height": 900})
        page.locator('[data-reader-columns="1"]').click()

        # Selection controls stay in the viewport and the revision form behaves
        # as a non-modal side panel while the document remains usable.
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
        expect(dialog).to_have_attribute("aria-modal", "false")
        assert dialog.bounding_box()["width"] <= 464
        box = dialog.bounding_box()
        assert abs(box["y"] + box["height"] - 900) < 1, box
        assert dialog.bounding_box()["x"] > 1000
        assert not page.locator(".md-main").evaluate("element => Boolean(element.closest('[inert]'))")
        assert dialog.locator(".reader-revision-editor__actions").evaluate(
            "element => getComputedStyle(element).position"
        ) == "sticky"
        page.locator(".reader-revision-editor").click(position={"x": 2, "y": 2})
        expect(dialog).to_be_visible()
        dialog.focus()
        page.keyboard.press("Tab")
        expect(dialog.get_by_role("button", name="收起", exact=True)).to_be_focused()
        page.keyboard.press("Shift+Tab")
        assert not dialog.locator('[type="submit"]').evaluate("element => element === document.activeElement")
        token = "rotated-token"
        dialog.locator('[name="instruction"]').fill("Keep this instruction after restart")
        dialog.locator('[type="submit"]').click()
        expect(dialog.get_by_role("status")).to_contain_text("正在生成")
        expect(dialog.locator('[type="submit"]')).to_be_disabled()
        # A real wheel event must reach the original document during generation.
        page.mouse.move(500, 500)
        before_scroll = page.evaluate("window.scrollY")
        page.mouse.wheel(0, 500)
        page.wait_for_function("before => window.scrollY > before", arg=before_scroll)
        dialog.get_by_role("button", name="收起", exact=True).click()
        expect(dialog.locator('[name="instruction"]')).to_be_hidden()
        expect(dialog.get_by_role("status")).to_contain_text("正在生成")
        article = page.locator("article.md-content__inner")
        article.evaluate("element => { element.tabIndex = -1; element.focus({preventScroll: true}); }")
        reading_scroll = page.evaluate("window.scrollY")
        assert len(pending_proposals) == 1
        finish_proposal(pending_proposals.pop())
        expect(dialog.get_by_role("status")).to_contain_text("候选已生成")
        expect(article).to_be_focused()
        assert abs(page.evaluate("window.scrollY") - reading_scroll) < 2
        expect(dialog.locator('[name="instruction"]')).to_be_hidden()
        dialog.get_by_role("button", name="展开", exact=True).click()
        expect(dialog.locator(".reader-revision-turn")).to_contain_text("Recovered preview")
        assert len(proposal_requests) == 2, proposal_requests
        assert proposal_requests[0] == proposal_requests[1]
        proposal_error = True
        dialog.locator('[name="instruction"]').fill("Keep this follow-up on error")
        dialog.locator('[type="submit"]').click()
        expect(dialog.get_by_role("alert")).to_contain_text("HTTP 400")
        expect(dialog.locator(".reader-revision-turn")).to_contain_text("Recovered preview")
        expect(dialog.locator('[name="instruction"]')).to_have_value("Keep this follow-up on error")
        expect(dialog.locator('[type="submit"]')).to_be_enabled()
        assert len(proposal_requests) == 3
        dialog.locator('[name="instruction"]').focus()
        page.keyboard.press("Escape")
        expect(dialog.locator('[name="instruction"]')).to_be_hidden()
        dialog.get_by_role("button", name="展开", exact=True).click()
        for width in (952, 390):
            page.set_viewport_size({"width": width, "height": 800})
            box = dialog.bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= width
            assert box["height"] <= 776
        page.set_viewport_size({"width": 1524, "height": 900})
        dialog.get_by_role("button", name="关闭", exact=True).click()
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
        # The shared mounting helper still keeps manual editing modal.
        page.evaluate("""() => {
          const block = document.querySelector('article p[data-reader-block]');
          block.scrollIntoView({block: 'center'});
          const range = document.createRange(); range.selectNodeContents(block);
          getSelection().removeAllRanges(); getSelection().addRange(range);
          document.dispatchEvent(new Event('selectionchange'));
        }""")
        page.get_by_role("button", name="手动修改", exact=True).click()
        expect(dialog).to_have_attribute("aria-modal", "true")
        assert page.locator(".md-main").evaluate("element => Boolean(element.closest('[inert]'))")
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        assert not page.locator(".md-main").evaluate("element => Boolean(element.closest('[inert]'))")
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
