"""Page-to-conversation navigation with isolated transcripts; no model requests."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
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
        document = "papers/reasoning-rl-reductions.md"
        source = "arxiv-2402.03300v3"
        old = state.create_chat_thread(document)["thread"]["id"]

        def message(thread, identity, content, **fields):
            state.append_chat(document, thread, {"id": identity, "role": "user", "content": content,
                "created_at": "2026-09-17T10:00:00+08:00", **fields})

        message(old, "old-question", "旧问题：PPO 的 token 优势是什么？", pdf_context={"source_id": source, "page": 11})
        state.append_chat(document, old, {"id": "old-answer", "role": "assistant", "content": "用于指导每个 token 的策略更新。"})
        message(old, "followup", "后续追问：为什么还需要 clip？", pdf_contexts=[])
        for i in range(205):
            state.append_chat(document, old, {"id": f"system-{i}", "role": "system", "content": "历史状态"})
        state.archive_chat_thread({"document_id": document, "thread_id": old})
        active = state.create_chat_thread(document)["thread"]["id"]
        message(active, "unrelated", "没有关联页面的问题", pdf_contexts=[])
        message(active, "multi", "两页对照问题 <img src=x onerror=alert(1)>", pdf_contexts=[
            {"source_id": source, "page": 12}, {"source_id": source, "page": 11},
            {"source_id": source, "page": 11}])
        message(active, "reading", "在第十三页提问", reading_pdf_context={"source_id": source, "page": 13})
        message(active, "closed", "关闭 PDF 后提问", reading_pdf_context=None)
        message(active, "different-source", "另一本论文", pdf_contexts=[{"source_id": "arxiv-1707.06347v2", "page": 11}])
        items = state.pdf_questions(document)["items"]
        assert len([item for item in items if item["source_id"] == source and item["page"] == 11]) == 2
        assert not any(item["message_id"] in {"closed", "unrelated", "followup", "reading"} for item in items)
        assert "old-question" not in [m["id"] for m in state.page_state(document, old)["messages"]]
        assert state.page_state(document, old, "old-question")["messages"][0]["id"] == "old-question"

        httpd = reader.ThreadingHTTPServer(("127.0.0.1", 0), reader.ReaderHandler)
        state.origin = f"http://127.0.0.1:{httpd.server_port}"
        httpd.state = state
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        calls = []

        def fake_codex(*args, **kwargs):
            calls.append(kwargs)
            return json.dumps({"content": "这是测试回答。", "visualization": None, "visual_html": None}), "12345678-1234-1234-1234-123456789abc"

        state.run_codex = fake_codex
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=str(next(path for path in CHROME_PATHS if path.is_file())), headless=True)
                page = browser.new_page(viewport={"width": 1600, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(state.origin + "/papers/reasoning-rl-reductions/#11")
                page.locator(f'a.evidence-link[data-source-id="{source}"]').first.click()
                f = page.frame_locator(".evidence-panel__frame")
                expect(f.locator("canvas.is-rendered").first).to_be_visible(timeout=30000)
                f.locator("body").evaluate("async () => { await ReaderPdf.ready; await ReaderPdf.navigate({page:11}); }")
                summary = f.locator(".pdf-questions summary")
                expect(summary).to_have_text("本页问过 · 2")
                summary.click()
                expect(f.locator(".pdf-questions__item")).to_have_count(2)
                expect(f.locator(".pdf-questions__list img")).to_have_count(0)
                page.screenshot(path="/tmp/reader-pdf-questions.png")
                f.get_by_role("button", name="旧问题：PPO").click()
                target = page.locator('[data-message-id="old-question"]')
                expect(target).to_be_visible()
                expect(target).to_have_class("knowledge-message knowledge-message--user is-question-target")
                expect(page.locator(".knowledge-composer textarea")).to_be_disabled()
                expect(page.locator('[data-message-id="old-answer"]')).to_be_visible()
                assert f.locator("body").evaluate("ReaderPdf.snapshot().page") == 11
                assert not calls
                # Page dropdown, no-question page, reload, then a new question.
                f.get_by_label("跳到有问题的 PDF 页").select_option("12")
                expect(summary).to_have_text("本页问过 · 1")
                f.locator("body").evaluate("ReaderPdf.navigate({page:14})")
                expect(summary).to_have_text("本页问过 · 0")
                page.reload()
                page.locator(f'a.evidence-link[data-source-id="{source}"]').first.click()
                expect(f.locator("canvas.is-rendered").first).to_be_visible(timeout=30000)
                f.locator("body").evaluate("async () => { await ReaderPdf.ready; await ReaderPdf.navigate({page:11}); }")
                expect(summary).to_have_text("本页问过 · 2")
                if page.locator('[data-reader-pane="assistant"]').is_hidden():
                    page.locator('[data-reader-tab="assistant"]').click()
                page.locator(".knowledge-composer textarea").fill("新问题：此页的公式如何理解？")
                page.locator('[data-action="send"]').click()
                expect(page.locator(".knowledge-message--assistant").last).to_contain_text("这是测试回答", timeout=15000)
                expect(summary).to_have_text("本页问过 · 2")
                assert calls[-1]["pdf_contexts"] == []
                saved = state.chat_history(document, active)
                plain = next(m for m in saved if m.get("content", "").startswith("新问题："))
                assert not any(item["message_id"] == plain["id"] for item in state.pdf_questions(document)["items"])
                page.locator('[data-action="add-pdf"]').click()
                page.locator(".knowledge-composer textarea").fill("附图问题：请解释公式")
                page.locator('[data-action="send"]').click()
                expect(summary).to_have_text("本页问过 · 3", timeout=15000)
                assert calls[-1]["pdf_contexts"] == [{"source_id": source, "page": 11}]
                # Deletion removes archived links on refresh; source identity stays isolated.
                state.delete_chat_thread({"document_id": document, "thread_id": old})
                page.evaluate("window.dispatchEvent(new Event('focus'))")
                expect(summary).to_have_text("本页问过 · 2")
                assert not errors, errors
                browser.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
    print("PDF question associations and browser navigation passed")


if __name__ == "__main__":
    run()
