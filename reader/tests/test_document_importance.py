#!/usr/bin/env python3
"""Verify durable personal ratings and sidebar interaction using isolated user data."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from playwright.sync_api import expect, sync_playwright

READER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(READER_DIR))
import server as reader
from test_reader import CHROME_PATHS, TASK_ID


def run():
    with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
        "READER_USER_DATA_DIR": temporary,
        "READER_SITE_DATABASE": str(READER_DIR / "user-data" / TASK_ID / "site.sqlite3"),
    }):
        state = reader.ReaderState(TASK_ID, 0)
        server = reader.ThreadingHTTPServer(("127.0.0.1", 0), reader.ReaderHandler)
        state.origin = f"http://127.0.0.1:{server.server_port}"
        server.state = state
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(payload=None, token=True):
            headers = {"Origin": state.origin, "Content-Type": "application/json"}
            if token:
                headers["X-Reader-Token"] = state.csrf_token
            req = urllib.request.Request(
                state.origin + "/api/document-importance",
                data=json.dumps(payload).encode() if payload is not None else None,
                headers=headers,
            )
            try:
                with urllib.request.urlopen(req) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as error:
                return error.code, json.load(error)

        try:
            doc = "papers/20260911-translation.md"
            other = "papers/formula-reading-bridge.md"
            assert request()[1] == {"ratings": {}}
            assert request({"document_id": doc, "score": 5}, token=False)[0] == 403
            for score in (True, -1, 6, 1.5, "5", None):
                assert request({"document_id": doc, "score": score})[0] == 400
            assert request({"document_id": "papers/../REPORT.md", "score": 5})[0] == 400
            assert request({"document_id": "papers/missing.md", "score": 5})[0] == 404
            with ThreadPoolExecutor() as pool:
                results = list(pool.map(request, [
                    {"document_id": doc, "score": 5}, {"document_id": other, "score": 3},
                ]))
            assert all(status == 200 for status, _ in results)
            assert request()[1]["ratings"] == {doc: 5, other: 3}
            # A fresh runtime state reads the same persisted scores.
            assert reader.ReaderState(TASK_ID, 0).document_importance()["ratings"] == {doc: 5, other: 3}
            with patch.dict(os.environ, {"READER_USER_DATA_DIR": str(Path(temporary) / "separate")}):
                assert reader.ReaderState(TASK_ID, 0).document_importance()["ratings"] == {}

            chrome = next(path for path in CHROME_PATHS if path.is_file())
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(state.origin + "/papers/20260911-translation/")
                button = page.locator(f'.reader-importance-button[data-document-id="{doc}"]')
                expect(button).to_have_text("★5")
                page.locator("#reader-importance-filter").select_option("high")
                expect(page.locator(".reader-importance-item:not(.reader-importance-hidden)")).to_have_count(1)
                expect(button).to_be_visible()
                await_url = page.url
                button.click()
                panel = page.locator(".reader-importance-dialog")
                expect(panel).to_be_visible()
                # Simulate a service restart after this page cached its token.
                state.csrf_token = "rotated-token"
                panel.get_by_role("button", name="4 分：重点掌握", exact=True).click()
                expect(panel).to_have_count(0)
                expect(button).to_have_text("★4")
                assert page.url == await_url
                assert request()[1]["ratings"][doc] == 4
                page.reload()
                expect(button).to_have_text("★4")
                page.locator("#reader-importance-filter").select_option("rated")
                expect(page.locator(".reader-importance-item:not(.reader-importance-hidden)")).to_have_count(2)
                # Instant navigation keeps the controls and filter without duplicating them.
                page.locator(f'.reader-importance-item:has(button[data-document-id="{other}"]) > a').click()
                page.wait_for_url("**/papers/formula-reading-bridge/")
                expect(page.locator(".reader-importance-toolbar")).to_have_count(1)
                expect(page.locator("#reader-importance-filter")).to_have_value("rated")
                expect(button).to_have_text("★4")
                button.click()
                panel.get_by_role("button", name="清除评分", exact=True).click()
                expect(panel).to_have_count(0)
                expect(page.locator(".reader-importance-item:not(.reader-importance-hidden)")).to_have_count(1)
                assert doc not in request()[1]["ratings"]
                page.locator("#reader-importance-filter").select_option("high")
                expect(page.locator("[data-importance-status]")).to_contain_text("暂无匹配")
                page.locator("#reader-importance-filter").select_option("rated")
                other_button = page.locator(f'.reader-importance-button[data-document-id="{other}"]')
                # A failed save must keep the previous score and offer retry.
                def fail_save(route):
                    if route.request.method == "POST":
                        route.fulfill(status=500, json={"error": "测试保存失败"})
                    else:
                        route.continue_()
                page.route("**/api/document-importance", fail_save)
                other_button.click()
                panel.get_by_role("button", name="5 分：优先复习", exact=True).click()
                expect(panel.locator("[data-result]")).to_contain_text("保存失败")
                expect(other_button).to_have_text("★3")
                page.keyboard.press("Escape")
                expect(panel).to_have_count(0)
                page.unroute("**/api/document-importance", fail_save)
                # Keyboard interaction and both color schemes, including a narrower sidebar.
                for width in (1440, 1220):
                    page.set_viewport_size({"width": width, "height": 1000})
                    for scheme in ("default", "slate"):
                        page.locator("body").evaluate("(el, scheme) => el.dataset.mdColorScheme = scheme", scheme)
                        other_button.focus()
                        page.keyboard.press("Enter")
                        expect(panel).to_be_visible()
                        bounds = panel.bounding_box()
                        assert 0 <= bounds["x"] and bounds["x"] + bounds["width"] <= width
                        assert bounds["y"] + bounds["height"] <= 1000
                        page.keyboard.press("Escape")
                        row = other_button.locator("..").bounding_box()
                        star = other_button.bounding_box()
                        title = other_button.locator("..").locator(":scope > a .md-ellipsis").bounding_box()
                        assert star["x"] + star["width"] <= title["x"] + 1
                        assert title["x"] + title["width"] <= row["x"] + row["width"] + 1
                assert not errors, errors
                browser.close()
            assert not (state.user_dir / "document-importance.json").exists()
            print("Document importance: persistence, validation, concurrent edits, filtering, navigation, failure recovery, keyboard and layout passed.")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    run()
