"""Full-paper extraction, verified citations, and browser navigation; no model cost."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect

READER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(READER))
import server

TASK = "paper-research-base-knowledge-about-llm-20260717"
SOURCE = "arxiv-2402.03300v3"
DOCUMENT = "papers/reasoning-rl-reductions.md"


def run():
    with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
        "READER_USER_DATA_DIR": temporary,
        "READER_SITE_DATABASE": str(READER / "user-data" / TASK / "site.sqlite3"),
    }):
        state = server.ReaderState(TASK, 0)
        directory, pages = state.exploration_corpus(SOURCE)
        assert len(pages) == state.pdf_page_count(state.source_pdf(SOURCE))
        assert (directory / f"page-{len(pages):04d}.txt").is_file()
        assert all(path.suffix == ".txt" for path in directory.iterdir())
        assert state.exploration_corpus(SOURCE)[1] == pages
        quote = " ".join(pages[2].split())[:160].rsplit(" ", 1)[0]
        citations = [{"page": 999, "quote": quote, "label": "错误页码"},
                     {"page": 3, "quote": quote, "label": "问题一 · 方法"},
                     {"page": 3, "quote": "this quote does not exist in the paper", "label": "虚构"}]
        verified = state.exploration_citations(citations, SOURCE, pages)
        assert len(verified) == 1 and verified[0]["number"] == 2
        # A 100-page paper remains completely available, including the final appendix.
        with patch.object(state, "file_sha256", return_value="synthetic-100-pages"), \
             patch.object(state, "pdf_page_count", return_value=100), \
             patch.object(server.subprocess, "run") as extract:
            extract.return_value.returncode = 0
            extract.return_value.stdout = "".join(f"Physical page {i} appendix text\f" for i in range(1, 101))
            hundred_dir, hundred_pages = state.exploration_corpus(SOURCE)
            assert len(hundred_pages) == 100
            assert "100" in (hundred_dir / "page-0100.txt").read_text()

        calls = []
        def fake(prompt, session_id, **kwargs):
            calls.append((prompt, session_id, kwargs))
            assert str(directory) in prompt and "附录" in prompt
            assert kwargs["schema"].name == "paper-exploration.schema.json"
            assert session_id is None and kwargs["ephemeral"]
            return json.dumps({"content": "问题一：论文方法见 **[证据2]**。再次引用 [证据2]。未核验 [证据1]。代码 ` [证据2] `。", "citations": citations,
                               "visualization": None, "visual_html": None}), ""
        state.run_codex = fake
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.ReaderHandler)
        httpd.state = state
        state.origin = f"http://127.0.0.1:{httpd.server_port}"
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, executable_path=os.environ.get(
                    "READER_TEST_BROWSER", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"))
                page = browser.new_page(viewport={"width": 1600, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(state.origin + "/papers/reasoning-rl-reductions/")
                page.locator(f'a.evidence-link[data-source-id="{SOURCE}"]').first.click()
                page.locator('[data-reader-tab="assistant"]').click()
                expect(page.locator("[data-knowledge-mode]")).to_have_count(0)
                expect(page.locator('[data-reader-tab="assistant"]')).to_have_text("论文问答")
                page.locator('.knowledge-composer textarea').fill("这个方法有哪些局限？请同时检查附录。")
                page.locator('[data-action="send"]').click()
                expect(page.locator('.knowledge-citation')).to_have_count(2, timeout=30000)
                expect(page.locator('.knowledge-message__body strong .knowledge-citation')).to_have_text("[证据2 · 第3页]")
                expect(page.locator('.knowledge-citation').first).to_have_attribute("title", "问题一 · 方法\n" + quote)
                expect(page.locator('.knowledge-message__body code')).to_contain_text("[证据2]")
                expect(page.locator('.knowledge-citation-references')).to_have_count(0)
                assert page.locator('.knowledge-citation').first.evaluate("el => getComputedStyle(el).display") in {"inline", "inline-block"}
                page.locator('.knowledge-citation').first.click()
                expect(page.locator('[data-reader-pane="assistant"]')).to_be_visible()
                page.wait_for_function("window.__readerPdfContext?.page === 3")
                expect(page.frame_locator(".evidence-panel__frame").locator(".pdf-citation-highlight").first).to_be_visible(timeout=15000)
                page.screenshot(path="/tmp/reader-paper-exploration.png")
                page.reload()
                page.locator('[data-reader-tab="assistant"]').click()
                expect(page.locator('.knowledge-citation')).to_have_count(2)
                assert len(calls) == 1 and not errors, errors
                history = state.chat_history(DOCUMENT, state.document_threads(DOCUMENT)["active_thread_id"])
                assert history[-1]["citations"][0]["page"] == 3
                browser.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
    print("paper exploration: PASS")


if __name__ == "__main__":
    run()
