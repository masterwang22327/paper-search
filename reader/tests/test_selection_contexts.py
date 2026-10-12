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
        # Exercise formula selection in expanded source details as a reader would.
        page.locator('article details').evaluate_all("els => els.forEach(el => el.open = true)")
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
            expect(dialog.get_by_role('alert')).to_have_text("validation completed")
            dialog.get_by_role("button", name="关闭", exact=True).click()
            assert not failures, (block_id, mode, failures)

        for block_id in math_blocks:
            submit(block_id)
        suffix_block = page.locator("article [data-reader-block]:has(.arithmatex)").evaluate_all("""els =>
            els.find(el => {
                const range = document.createRange();
                range.selectNodeContents(el);
                range.setStartAfter(el.querySelector('.arithmatex'));
                return range.toString().trim();
            }).dataset.readerBlock
        """)
        submit(suffix_block, "suffix")
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

        page.goto(base + "/papers/reasoning-rl-reductions/#grpo", wait_until="domcontentloaded")
        page.wait_for_function("window.MathJax?.startup?.document?.math")
        page.evaluate("MathJax.startup.promise")
        page.locator('article details').evaluate_all("els => els.forEach(el => el.open = true)")
        formula = page.locator('article div.arithmatex[data-reader-math-source*="r_{it}"]').filter(
            has=page.locator('mjx-container')
        ).first
        formula.wait_for()
        formula_id = formula.get_attribute("data-reader-block")
        assert formula_id and formula_id.startswith("m")
        tex = formula.get_attribute("data-reader-math-source")
        for mode in ("formula", "partial", "cross", "backward"):
            page.evaluate("""({id, mode}) => {
                const formula = document.querySelector(`[data-reader-block="${id}"]`);
                formula.scrollIntoView({block: 'center'});
                const range = document.createRange();
                range.selectNodeContents(formula.querySelector('mjx-math'));
                if (mode === 'partial') range.selectNode(formula.querySelector('mjx-c'));
                if (mode === 'cross' || mode === 'backward') {
                    range.setStart(formula.previousElementSibling, 0);
                    let following = formula.nextElementSibling;
                    while (following && !following.hasAttribute('data-reader-block')) following = following.nextElementSibling;
                    range.setEndAfter(following);
                }
                const selection = getSelection();
                selection.removeAllRanges();
                if (mode === 'backward') selection.setBaseAndExtent(
                    range.endContainer, range.endOffset, range.startContainer, range.startOffset);
                else selection.addRange(range);
            }""", {"id": formula_id, "mode": mode})
            expect(formula).to_have_class("arithmatex reader-math-selected")
            assert formula.locator('mjx-math').evaluate(
                "el => getComputedStyle(el).backgroundColor"
            ) == "rgba(128, 128, 128, 0.28)"
            page.locator('.knowledge-selection-menu [data-action="edit"]').click()
            dialog = page.locator('.reader-revision-editor__dialog')
            expect(dialog.locator('blockquote')).to_contain_text(tex)
            expect(formula).not_to_have_class("arithmatex reader-math-selected")
            dialog.locator('[name="instruction"]').fill("Verify full formula in revision")
            dialog.locator('[type="submit"]').click()
            expect(dialog.get_by_role('alert')).to_have_text("validation completed")
            assert not failures, failures
            formula_context = next(item for item in checked[-1] if item["block_id"] == formula_id)
            assert formula_context["text"] == tex
            assert formula_context["start"] == 0 and formula_context["end"] == len(tex)
            if mode in ("cross", "backward"):
                assert len(checked[-1]) >= 3
            dialog.get_by_role("button", name="关闭", exact=True).click()

        # Selecting text immediately after an inline formula must not paint it.
        page.evaluate("""() => {
            const formula = [...document.querySelectorAll('article span.arithmatex')]
                .find(el => el.nextSibling?.nodeType === Node.TEXT_NODE && el.nextSibling.length > 1);
            const range = document.createRange();
            range.setStartAfter(formula);
            range.setEnd(formula.nextSibling, 1);
            getSelection().removeAllRanges();
            getSelection().addRange(range);
        }""")
        expect(page.locator('.reader-math-selected')).to_have_count(0)
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
