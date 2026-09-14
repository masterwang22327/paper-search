#!/usr/bin/env python3
"""Validate browser selections against source text after MathJax rendering."""

import json
import subprocess
import sys
import urllib.request

from playwright.sync_api import expect, sync_playwright
from test_reader import CHROME_PATHS, READER_DIR, TASK_ID, free_port, wait_for_server

sys.path.insert(0, str(READER_DIR))
from server import ApiError, ReaderState


def run(base):
    with urllib.request.urlopen(base + "/context-manifest.json") as response:
        manifest = json.load(response)
    validator = ReaderState.__new__(ReaderState)
    validator.site_manifest = manifest
    document_id = "papers/20260911-translation.md"
    document = manifest["documents"][document_id]
    checked = []
    failures = []
    with sync_playwright() as playwright:
        chrome = next(path for path in CHROME_PATHS if path.is_file())
        browser = playwright.chromium.launch(executable_path=str(chrome), headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        def reply(route):
            if "/api/bootstrap" in route.request.url:
                route.fulfill(json={"token": "test", "task_id": TASK_ID})
            elif "/api/revision/propose" in route.request.url:
                payload = route.request.post_data_json
                try:
                    checked.append(validator.validate_contexts(
                        payload["document_id"], payload["document_sha256"], payload["contexts"]
                    ))
                except ApiError as error:
                    failures.append(str(error))
                # Stop after real validation, without model calls or stored edits.
                route.fulfill(status=400, json={"error": "validation completed"})
            else:
                route.fulfill(json={})

        page.route("**/api/**", reply)
        page.goto(base + "/papers/20260911-translation/", wait_until="domcontentloaded")
        page.wait_for_function("window.MathJax?.startup?.document?.math")
        page.evaluate("MathJax.startup.promise")
        math_blocks = page.locator("article [data-reader-block]:has(.arithmatex)").evaluate_all(
            "els => els.map(el => el.dataset.readerBlock)"
        )
        assert math_blocks
        document["blocks"]["unicode-test"] = "\U0001f600 prefix \U0001d465 selected text"
        page.evaluate("""text => {
            const block = document.createElement('p');
            block.dataset.readerBlock = 'unicode-test';
            block.textContent = text;
            document.querySelector('article.md-content__inner').append(block);
        }""", document["blocks"]["unicode-test"])

        def submit(block_id, mode="whole"):
            page.evaluate("""({blockId, mode}) => {
                const block = document.querySelector(`[data-reader-block="${blockId}"]`);
                block.scrollIntoView({block: 'center'});
                const range = document.createRange();
                range.selectNodeContents(block);
                if (mode === 'suffix') {
                    const math = block.querySelector('.arithmatex');
                    range.setStartAfter(math);
                } else if (mode === 'formula') {
                    range.selectNodeContents(block.querySelector('mjx-math'));
                } else if (mode === 'unicode') {
                    range.setStart(block.firstChild, block.textContent.indexOf('selected'));
                }
                getSelection().removeAllRanges();
                getSelection().addRange(range);
                document.dispatchEvent(new Event('selectionchange'));
            }""", {"blockId": block_id, "mode": mode})
            page.locator('.knowledge-selection-menu [data-action="edit"]').click()
            dialog = page.locator('.reader-revision-editor__dialog')
            dialog.locator('[name="instruction"]').fill("Verify selection")
            dialog.locator('[type="submit"]').click()
            expect(dialog.locator('.reader-revision-editor__preview')).to_have_text("validation completed")
            dialog.get_by_role("button", name="取消", exact=True).click()
            assert not failures, (block_id, mode, failures)

        for block_id in math_blocks:
            submit(block_id)
        submit(math_blocks[0], "suffix")
        submit(math_blocks[0], "formula")
        assert checked[-1][0]["text"].startswith("\\(")
        submit("unicode-test", "unicode")
        assert checked[-1][0]["text"] == "selected text"
        tampered = [{**checked[-1][0], "text": "forged"}]
        try:
            validator.validate_contexts(document_id, document["sha256"], tampered)
        except ApiError:
            pass
        else:
            raise AssertionError("Tampered selection was accepted")
        browser.close()
    print(f"Selection context checks passed: {len(checked)} browser selections")


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
