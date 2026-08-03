#!/usr/bin/env python3
"""Browser-level regression checks for the generated research reader."""

from __future__ import annotations

import contextlib
import json
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


READER_DIR = Path(__file__).resolve().parents[1]
TASK_ID = "paper-research-base-knowledge-about-llm-20260717"
CHROME_PATHS = (
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_server(url: str, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.15)
    raise RuntimeError(f"Reader server did not start: {url}")


def run() -> None:
    chrome = next((path for path in CHROME_PATHS if path.is_file()), None)
    if chrome is None:
        raise RuntimeError("Google Chrome or Microsoft Edge is required for the UI test")

    subprocess.run([str(READER_DIR / "build.sh"), TASK_ID], cwd=READER_DIR, check=True)
    port = free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", "site"],
        cwd=READER_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        wait_for_server(base_url)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(chrome))
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            transformer_revisions = json.loads(
                (
                    READER_DIR
                    / "user-data"
                    / TASK_ID
                    / "document-revisions"
                    / "e1a48e1b8a1ee4d8644a.json"
                ).read_text(encoding="utf-8")
            ).get("items", [])
            page.add_init_script(
                """(() => {
                  const nativeFetch = window.fetch.bind(window);
                  window.__faqTestState = {
                    session: {id: "thread-history", status: "open", session_id: "11111111-2222-4333-8444-555555555555"},
                    active_thread_id: "thread-history",
                    selected_thread_id: "thread-history",
                    threads: [{
                      id: "thread-history",
                      title: "历史问题",
                      status: "open",
                      session_id: "11111111-2222-4333-8444-555555555555",
                      message_count: 2
                    }],
                    messages: [{
                      id: "history-user",
                      role: "user",
                      content: "历史问题",
                      pdf_context: {source_id: "arxiv-1706.03762v7", page: 3}
                    }, {
                      id: "history-assistant",
                      role: "assistant",
                      content: "# 历史回答\\n\\n" + Array.from(
                        {length: 80},
                        (_, index) => `第 ${index + 1} 节用于模拟真实的长篇模型回复，确保切换标签后直接显示回答开头。`
                      ).join("\\n\\n")
                    }],
                    faq: {items: [{
                      id: "faq-test",
                      question: "哪条知识可以删除？",
                      answer: "这是一条用于验证删除交互的已固化知识。",
                      knowledge_type: "mixed",
                      evidence: []
                    }]},
                    revisions: {items: __REVISION_ITEMS__},
                    revision_settings: {model: "gpt-5.6-terra", effort: "medium"},
                    revision_discussions: {items: []}
                  };
                  window.__translationTestState = {};
                  window.__translationPostCalls = [];
                  window.__translationFullState = {
                    status: "idle", completed: 0, total: 15, current_pages: [], concurrency: 8, failures: 0
                  };
                  const json = value => Promise.resolve(new Response(JSON.stringify(value), {
                    status: 200,
                    headers: {"Content-Type": "application/json"}
                  }));
                  window.fetch = (input, init) => {
                    const url = typeof input === "string" ? input : input.url;
                    if (url === "/api/bootstrap") {
                      return json({token: "test-token", task_id: "test-task"});
                    }
                    if (url.startsWith("/api/state?")) return json(window.__faqTestState);
                    if (url === "/api/chat/archive") {
                      window.__faqTestState.active_thread_id = null;
                      window.__faqTestState.session.status = "archived";
                      window.__faqTestState.threads[0].status = "archived";
                      return json({
                        active_thread_id: null,
                        selected_thread_id: "thread-history",
                        thread: window.__faqTestState.session,
                        threads: window.__faqTestState.threads,
                        messages: window.__faqTestState.messages
                      });
                    }
                    if (url === "/api/chat/new") {
                      window.__faqTestState.threads[0].status = "archived";
                      window.__faqTestState.threads.unshift({
                        id: "thread-new", title: "对话 2", status: "open", session_id: null, message_count: 0
                      });
                      window.__faqTestState.active_thread_id = "thread-new";
                      window.__faqTestState.selected_thread_id = "thread-new";
                      window.__faqTestState.session = {id: "thread-new", status: "open", session_id: null};
                      window.__faqTestState.messages = [];
                      return json({
                        active_thread_id: "thread-new",
                        selected_thread_id: "thread-new",
                        thread: window.__faqTestState.session,
                        threads: window.__faqTestState.threads,
                        messages: []
                      });
                    }
                    if (url === "/api/faq/delete") {
                      window.__faqTestState.faq = {items: []};
                      return json(window.__faqTestState.faq);
                    }
                    if (url === "/api/faq/save-message") {
                      const request = JSON.parse(init.body);
                      window.__faqTestState.faq = {items: [{
                        id: "faq-saved",
                        question: request.question,
                        answer: request.answer,
                        note: request.note,
                        source_message_id: request.message_id,
                        knowledge_type: "mixed",
                        evidence: [{source_id: "arxiv-1706.03762v7", page: 7}]
                      }]};
                      return json(window.__faqTestState.faq);
                    }
                    if (url === "/api/faq/edit") {
                      const request = JSON.parse(init.body);
                      Object.assign(window.__faqTestState.faq.items[0], {
                        question: request.question,
                        answer: request.answer,
                        note: request.note
                      });
                      return json(window.__faqTestState.faq);
                    }
                    if (url === "/api/ask") {
                      const request = JSON.parse(init.body);
                      const user = {
                        id: "asked-user",
                        role: "user",
                        content: request.question,
                        contexts: request.contexts,
                        pdf_contexts: request.pdf_contexts
                      };
                      const assistant = {id: "asked-assistant", role: "assistant", content: "模拟回答完成"};
                      return new Promise(resolve => setTimeout(() => {
                        window.__faqTestState.messages.push(user, assistant);
                        const current = window.__faqTestState.threads.find(item => item.id === request.thread_id);
                        if (current) current.message_count += 2;
                        resolve(new Response(JSON.stringify({
                          thread_id: request.thread_id,
                          active_thread_id: request.thread_id,
                          session_id: "11111111-2222-4333-8444-555555555555",
                          threads: window.__faqTestState.threads,
                          messages: [user, assistant]
                        }), {status: 200, headers: {"Content-Type": "application/json"}}));
                      }, 1_500));
                    }
                    if (url.startsWith("/api/translation/full?") && (!init || !init.method || init.method === "GET")) {
                      return json(window.__translationFullState);
                    }
                    if (url === "/api/translation/full/start") {
                      const completed = Object.keys(window.__translationTestState).length;
                      window.__translationFullState = completed >= 15
                        ? {status: "completed", completed: 15, total: 15, current_pages: [], concurrency: 8, failures: 0}
                        : {status: "running", completed, total: 15, current_pages: [3], concurrency: 8, failures: 0};
                      return json(window.__translationFullState);
                    }
                    if (url === "/api/translation/full/stop") {
                      window.__translationFullState = {
                        ...window.__translationFullState, status: "stopped", current_pages: []
                      };
                      return json(window.__translationFullState);
                    }
                    if (url.startsWith("/api/translation/page?") && (!init || !init.method || init.method === "GET")) {
                      const parsed = new URL(url, window.location.origin);
                      const page = Number(parsed.searchParams.get("page"));
                      return json({
                        source_id: "arxiv-1706.03762v7",
                        page,
                        source_text: `Source text for page ${page}`,
                        translation: window.__translationTestState[page] || null,
                        metadata: {page_count: 15}
                      });
                    }
                    if (url === "/api/translation/page") {
                      const request = JSON.parse(init.body);
                      window.__translationPostCalls.push(request.page);
                        return new Promise(resolve => setTimeout(() => {
                          const translated = {
                          source_id: request.source_id,
                          page: request.page,
                          source_text: `Source text for page ${request.page}`,
                            translation: `第 ${request.page} 页模拟中文译文`,
                            blocks: [{
                              id: `p${String(request.page).padStart(4, "0")}-b001`,
                              physical_page: request.page,
                              type: "paragraph",
                              order: 1,
                              original_text: `Source text for page ${request.page}`,
                              translation: `第 ${request.page} 页模拟中文译文`,
                              confidence: "high",
                              bbox: null,
                              refs: []
                            }, {
                              id: `p${String(request.page).padStart(4, "0")}-t001`,
                              physical_page: request.page,
                              type: "table",
                              order: 2,
                              original_text: "Model Quality Base 27.3 Big 28.4",
                              translation: "模型质量对比。",
                              confidence: "medium",
                              bbox: null,
                              refs: ["table-1"],
                              table_data: {
                                headers: ["模型", "质量"],
                                rows: [["Base", "27.3"], ["Big", "28.4"]],
                                notes: ["数值保持原文。"]
                              }
                            }, {
                              id: `p${String(request.page).padStart(4, "0")}-f001`,
                              physical_page: request.page,
                              type: "figure",
                              order: 3,
                              original_text: "Inputs Outputs",
                              translation: "输入到输出的流程图。",
                              confidence: "high",
                              bbox: null,
                              refs: ["figure-1"],
                              figure_data: {
                                kind: "diagram",
                                summary: "输入经过编码器与解码器后生成输出。",
                                labels: [{original: "Inputs", translation: "输入"}],
                                flow_steps: ["输入进入编码器。", "解码器生成输出。"],
                                notes: []
                              }
                            }],
                            warnings: [],
                          visual_input: true,
                          translated_at: "2026-07-20T00:00:00+08:00"
                        };
                        window.__translationTestState[request.page] = translated;
                        resolve(new Response(JSON.stringify(translated), {
                          status: 200,
                          headers: {"Content-Type": "application/json"}
                        }));
                      }, 700));
                    }
                    return nativeFetch(input, init);
                  };
                })();""".replace(
                    "__REVISION_ITEMS__",
                    json.dumps(transformer_revisions, ensure_ascii=True),
                )
            )

            page.goto(f"{base_url}/reading-guide/", wait_until="networkidle")
            expect(page.locator(".learning-stage")).to_have_count(11)
            expect(page.locator(".learning-stage").first).to_contain_text("进入前")
            expect(page.locator(".learning-stage").first).to_contain_text("读完后")
            expect(page.locator(".learning-stage").first).to_contain_text("阶段检查")
            expect(page.locator(".learning-stage__papers > li")).to_have_count(56)

            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(f"{base_url}/papers/tokenization-data-curation/", wait_until="networkidle")
            expect(page.locator(".paper-reading-card__stage-entry")).to_be_visible()
            expect(page.locator(".paper-reading-card__topline > .evidence-panel-toggle")).to_be_visible()
            mobile_layout = page.evaluate(
                """() => {
                  const rect = selector => document.querySelector(selector).getBoundingClientRect();
                  const copy = rect('.paper-reading-card__route-copy');
                  const nav = rect('.paper-reading-card__route nav');
                  const card = rect('.paper-reading-card');
                  const footerNav = rect('.reading-route-footer nav');
                  const pdfToggle = rect('.paper-reading-card__topline > .evidence-panel-toggle');
                  const details = rect('.paper-reading-card__details');
                  return {
                    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                    cardWidth: card.width,
                    copyWidth: copy.width,
                    navWidth: nav.width,
                    navBelowCopy: nav.top >= copy.bottom - 1,
                    footerWidth: footerNav.width,
                    pdfDoesNotCoverDetails: pdfToggle.bottom <= details.top
                  };
                }"""
            )
            assert mobile_layout["overflow"] <= 1, mobile_layout
            assert mobile_layout["copyWidth"] >= mobile_layout["cardWidth"] * 0.85, mobile_layout
            assert mobile_layout["navWidth"] >= mobile_layout["cardWidth"] * 0.85, mobile_layout
            assert mobile_layout["footerWidth"] >= mobile_layout["cardWidth"] * 0.85, mobile_layout
            assert mobile_layout["navBelowCopy"], mobile_layout
            assert mobile_layout["pdfDoesNotCoverDetails"], mobile_layout
            page.set_viewport_size({"width": 1600, "height": 1000})

            page.goto(f"{base_url}/papers/arxiv-1706.03762/", wait_until="networkidle")

            panel = page.locator(".evidence-panel")
            expect(panel).not_to_be_visible()
            expect(page.locator(".evidence-panel-toggle")).to_be_visible()
            expect(page.locator(".reader-section-tools")).to_be_visible()
            expect(page.locator(".reader-section-tools__current small")).to_have_text(re.compile(r"1 / \d+"))
            expect(page.locator(".paper-reading-card__details")).to_be_visible()
            expect(page.locator(".paper-reading-card__route")).to_contain_text("本阶段 5/7")
            expect(page.locator(".paper-reading-card__route")).to_contain_text("全路线 5/56")
            expect(page.locator(".paper-reading-card__route")).to_contain_text("从上一篇到本篇")
            expect(page.locator(".paper-reading-card__route nav a")).to_have_count(2)
            expect(page.locator(".reading-route-footer")).to_be_visible()
            expect(page.locator(".reading-route-footer__next")).to_contain_text("现代 Transformer Block")
            expect(page.locator(".md-sidebar--primary")).to_be_visible()
            page.locator(".evidence-panel-toggle").click()
            expect(panel).to_be_visible()
            expect(page.locator(".paper-reading-card__details")).not_to_be_visible()
            expect(page.locator(".md-sidebar--primary")).not_to_be_visible()
            body_block = page.locator(
                "p[data-reader-block]",
                has_text="Transformer 的关键不只是“使用了注意力”",
            ).first
            expect(body_block).to_be_visible()
            expect(page.locator(".reader-revision")).to_have_count(8)
            expect(page.locator(".reader-revision", has_text="Encoder shape 转换流程")).to_be_visible()
            expect(page.locator(".reader-revision", has_text="缩放点积注意力：最简摘要")).to_be_visible()
            migrated_manual = page.locator(".reader-revision", has_text="对[B,h,S_query,S_key] 的S_key 维")
            expect(migrated_manual).to_be_visible()
            expect(migrated_manual.locator("xpath=preceding::*[@data-reader-block][1]")).to_contain_text("QK^T")
            expect(page.locator('[data-reader-tab="assistant"]')).to_be_visible()
            expect(page.locator('[data-reader-tab="faq"]')).to_be_visible()
            expect(page.locator('[data-action="add-pdf"]')).to_have_text("加入当前 PDF 页图像")
            page.locator('[data-reader-tab="assistant"]').click()
            expect(page.locator('[data-action="select-thread"]')).to_contain_text("历史问题")
            expect(page.locator('[data-action="archive-thread"]')).to_be_enabled()
            expect(page.locator('[data-action="new-thread"]')).to_be_enabled()
            expect(page.locator('.knowledge-message[data-message-id="history-user"] .knowledge-message__pdf')).to_be_visible()
            expect(page.locator('.knowledge-message[data-message-id="history-user"] canvas[data-rendered="true"]')).to_be_visible(timeout=15_000)
            layout = page.locator(".knowledge-assistant").evaluate(
                """root => {
                  const rect = selector => root.querySelector(selector).getBoundingClientRect();
                  const messages = root.querySelector(".knowledge-messages");
                  const lastMessage = root.querySelector(".knowledge-message:last-child");
                  return {
                    threadbarHeight: rect(".knowledge-threadbar").height,
                    composerHeight: rect(".knowledge-composer").height,
                    textareaHeight: rect(".knowledge-composer textarea").height,
                    messageScrollTop: messages.scrollTop,
                    messageOverflow: messages.scrollWidth - messages.clientWidth,
                    lastMessageOffset: lastMessage.getBoundingClientRect().top - messages.getBoundingClientRect().top
                  };
                }"""
            )
            assert layout["messageScrollTop"] > 0
            assert 0 <= layout["lastMessageOffset"] <= 20
            assert layout["messageOverflow"] <= 0
            assert layout["threadbarHeight"] < 50
            assert layout["composerHeight"] < 160
            assert layout["textareaHeight"] < 85
            page.locator('[data-reader-tab="pdf"]').click()
            viewer = page.frame_locator(".evidence-panel__frame")
            expect(viewer.locator('.pdf-page[data-page="2"] canvas')).to_be_visible(timeout=15_000)
            expect(viewer.locator("#page-number")).to_have_value("2")
            expect(viewer.locator("#page-count")).to_have_text("15")
            expect(viewer.locator("#translate-page")).to_have_text("翻译当前页")
            expect(viewer.locator("#translate-all")).to_have_text("翻译全文")
            viewer.locator("#translate-page").click()
            expect(viewer.locator("#translation-panel")).to_be_visible()
            viewport_box = viewer.locator("#viewport").bounding_box()
            translation_box = viewer.locator("#translation-panel").bounding_box()
            assert translation_box["x"] >= viewport_box["x"] + viewport_box["width"]
            assert abs(translation_box["y"] - viewport_box["y"]) < 2
            expect(viewer.locator("#translation-resizer")).to_have_attribute("aria-orientation", "vertical")
            expect(viewer.locator("#translation-state")).to_contain_text("Codex 正在")
            expect(viewer.locator("#zoom-out")).to_be_visible()
            expect(viewer.locator("#zoom-in")).to_be_visible()
            initial_page_width = viewer.locator('.pdf-page[data-page="2"]').bounding_box()["width"]
            viewer.locator("#zoom-in").click()
            page.wait_for_timeout(250)
            assert viewer.locator('.pdf-page[data-page="2"]').bounding_box()["width"] > initial_page_width
            viewer.locator("#fit-width").click()
            expect(viewer.locator(".translation-target")).to_contain_text("第 2 页模拟中文译文", timeout=3_000)
            expect(viewer.locator(".translation-target .translation-block[data-block-id='p0002-b001'] .translation-block__label")).to_contain_text("p0002-b001")
            expect(viewer.locator(".translation-target .translation-block[data-block-id='p0002-b001'] .translation-block__natural")).to_have_text("正文第 1 段")
            expect(viewer.locator(".translation-target .translation-block[data-block-id='p0002-b001'] .translation-block__confidence")).to_contain_text("高置信度")
            expect(viewer.locator(".translation-table-data th")).to_have_text(["模型", "质量"])
            expect(viewer.locator(".translation-table-data tbody tr")).to_have_count(2)
            expect(viewer.locator(".translation-figure-data")).to_contain_text("输入经过编码器与解码器后生成输出")
            expect(viewer.locator(".translation-figure-flow li")).to_have_count(2)
            expect(viewer.locator(".translation-figure-labels")).to_contain_text("Inputs")
            viewer.locator(".translation-target .translation-block[data-block-id='p0002-b001']").click()
            expect(viewer.locator("#status")).to_contain_text("已定位到第 2 页")
            viewer.locator("#show-source").check()
            expect(viewer.locator(".translation-source")).to_be_visible()
            expect(viewer.locator(".translation-source")).to_contain_text("Source text for page 2")

            # Full translation is sequential, stoppable and resumes by
            # skipping pages already present in the local cache.
            viewer.locator("#translate-all").click()
            expect(viewer.locator("#translate-all")).to_have_text("停止全文")
            expect(viewer.locator("#translate-all")).to_have_attribute("aria-busy", "true")
            expect(viewer.locator("#full-translation-progress")).to_contain_text("/15")
            expect(viewer.locator("#full-translation-status")).to_be_visible()
            expect(viewer.locator("#full-translation-status-title")).to_contain_text("全文翻译")
            viewer.locator("#translate-all").click()
            expect(viewer.locator("#translate-all")).to_have_text("继续全文", timeout=3_000)
            expect(viewer.locator("#full-translation-status-title")).to_contain_text("已停止")
            viewer.locator("body").evaluate("""() => {
              for (let page = 1; page <= 15; page += 1) {
                window.__translationTestState[page] ||= {
                  source_id: "arxiv-1706.03762v7",
                  page,
                  source_text: `Source text for page ${page}`,
                  translation: `第 ${page} 页模拟中文译文`,
                  warnings: [],
                  visual_input: true
                };
              }
            }""")
            post_calls_before_resume = viewer.locator("body").evaluate("() => window.__translationPostCalls.length")
            viewer.locator("#translate-all").click()
            expect(viewer.locator("#full-translation-progress")).to_have_text("已完成 15/15", timeout=3_000)
            expect(viewer.locator("#full-translation-status-title")).to_have_text("全文翻译完成")
            post_calls_after_resume = viewer.locator("body").evaluate("() => window.__translationPostCalls.length")
            assert post_calls_after_resume == post_calls_before_resume

            page.locator('a.evidence-link[data-page="6"]').first.click()
            expect(viewer.locator("#page-number")).to_have_value("6", timeout=15_000)
            expect(page.locator(".evidence-panel__meta")).to_contain_text("PDF 第 6 页")
            expect(viewer.locator("#translation-title")).to_contain_text("PDF 第 6 页")

            page.wait_for_timeout(300)
            viewer.locator('.pdf-page[data-page="7"]').evaluate(
                "element => element.scrollIntoView({block: 'center'})"
            )
            expect(viewer.locator("#page-number")).to_have_value("7", timeout=5_000)
            expect(viewer.locator('.pdf-page[data-page="7"] canvas')).to_be_visible(timeout=15_000)
            expect(viewer.locator('.pdf-page[data-page="2"] canvas')).not_to_be_visible(timeout=5_000)
            page.locator('[data-reader-tab="assistant"]').click()
            page.locator('[data-action="add-pdf"]').click()
            expect(page.locator(".knowledge-context")).to_contain_text("PDF 整页图像")
            expect(page.locator(".knowledge-context")).to_contain_text("物理页 7")
            page.locator(".knowledge-composer textarea").fill("解释第七页图表")
            page.locator('[data-action="send"]').click()
            expect(page.locator(".knowledge-context")).to_have_count(0)
            pending_message = page.locator(".knowledge-message.is-pending")
            expect(pending_message).to_contain_text("解释第七页图表")
            expect(pending_message.locator(".knowledge-message__pdf")).to_contain_text("物理页 7")
            expect(page.locator(".knowledge-session")).to_have_text("回答中…")
            expect(page.locator(".knowledge-message--assistant", has_text="模拟回答完成")).to_be_visible(timeout=3_000)
            expect(page.locator(".knowledge-message.is-pending")).to_have_count(0)
            expect(page.locator(".knowledge-session")).to_have_text("11111111")
            expect(page.locator(".knowledge-context")).to_have_count(0)
            assistant = page.locator(".knowledge-message--assistant", has_text="模拟回答完成")
            assistant.get_by_role("button", name="保存为 FAQ").click()
            editor = page.locator(".knowledge-faq-editor__dialog")
            expect(editor).to_be_visible()
            expect(editor.locator('[name="question"]')).to_have_value("解释第七页图表")
            expect(editor.locator('[name="answer"]')).to_have_value("模拟回答完成")
            editor.locator('[name="question"]').fill("第七页图表说明了什么？")
            editor.locator('[name="note"]').fill("复习生成阶段的数据依赖。")
            editor.get_by_role("button", name="保存", exact=True).click()
            faq_item = page.locator(".knowledge-faq-item", has_text="第七页图表说明了什么？")
            expect(faq_item).to_be_visible()
            faq_item.locator("summary").click()
            expect(faq_item).to_contain_text("复习生成阶段的数据依赖。")
            expect(page.locator("#reader-personal-faq")).to_contain_text("第七页图表说明了什么？")
            faq_item.get_by_role("button", name="编辑").click()
            editor = page.locator(".knowledge-faq-editor__dialog")
            editor.locator('[name="note"]').fill("重点复习生成阶段的数据依赖。")
            editor.get_by_role("button", name="保存", exact=True).click()
            faq_item = page.locator(".knowledge-faq-item", has_text="第七页图表说明了什么？")
            faq_item.locator("summary").click()
            expect(faq_item).to_contain_text("重点复习生成阶段的数据依赖。")
            page.once("dialog", lambda dialog: dialog.accept())
            faq_item.get_by_role("button", name="删除这条 FAQ").click()
            expect(page.locator(".knowledge-faq__delete")).to_have_count(0)
            expect(page.locator("#reader-personal-faq")).to_have_count(0)

            page.locator('[data-reader-tab="assistant"]').click()
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator('[data-action="archive-thread"]').click()
            expect(page.locator(".knowledge-session")).to_have_text("只读")
            expect(page.locator(".knowledge-composer textarea")).to_be_disabled()
            expect(page.locator('[data-action="send"]')).to_be_disabled()
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator('[data-action="new-thread"]').click()
            expect(page.locator('[data-action="select-thread"]')).to_contain_text("对话 2")
            expect(page.locator(".knowledge-composer textarea")).to_be_enabled()
            expect(page.locator(".knowledge-messages .knowledge-empty")).to_be_visible()

            body_block_id = body_block.get_attribute("data-reader-block")
            body_block.evaluate(
                """element => {
                  const textNode = Array.from(element.childNodes).find(node => node.nodeType === Node.TEXT_NODE && node.textContent.length > 12);
                  const range = document.createRange();
                  range.setStart(textNode, 0);
                  range.setEnd(textNode, 10);
                  const selection = window.getSelection();
                  selection.removeAllRanges();
                  selection.addRange(range);
                  document.dispatchEvent(new Event('selectionchange'));
                }"""
            )
            expect(page.locator(".knowledge-selection-menu")).to_be_visible(timeout=3_000)
            page.locator('.knowledge-selection-menu [data-action="context"]').click()
            expect(page.locator(".knowledge-context", has_text=f"正文 {body_block_id}")).to_be_visible()
            expect(page.locator('[data-reader-pane="assistant"]')).to_have_class(re.compile("is-active"))

            page.evaluate(
                """() => {
                  const blocks = Array.from(document.querySelectorAll('.md-content__inner [data-reader-block]'))
                    .filter(block => !block.querySelector('[data-reader-block]'));
                  const first = blocks[5];
                  const last = blocks[7];
                  const range = document.createRange();
                  range.setStart(first, 0);
                  range.setEnd(last, last.childNodes.length);
                  const selection = window.getSelection();
                  selection.removeAllRanges();
                  selection.addRange(range);
                  document.dispatchEvent(new Event('selectionchange'));
                }"""
            )
            expect(page.locator(".knowledge-selection-menu")).to_be_visible(timeout=3_000)
            page.locator('.knowledge-selection-menu [data-action="context"]').click()
            assert page.locator(".knowledge-context").count() >= 4

            initial_width = panel.bounding_box()["width"]
            resizer = page.locator(".evidence-panel__resizer")
            box = resizer.bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 120)
            page.mouse.down()
            page.mouse.move(box["x"] - 120, box["y"] + 120, steps=8)
            page.mouse.up()
            resized_width = panel.bounding_box()["width"]
            assert resized_width > initial_width + 80, (initial_width, resized_width)

            saved_width = page.evaluate("localStorage.getItem('research-reader-evidence-width-v2')")
            assert saved_width is not None
            page.reload(wait_until="networkidle")
            expect(page.locator(".evidence-panel")).not_to_be_visible()
            page.locator(".evidence-panel-toggle").click()
            restored_width = page.locator(".evidence-panel").bounding_box()["width"]
            assert abs(restored_width - resized_width) < 3, (resized_width, restored_width)

            # Browser zoom presents as a narrower CSS viewport. The outer
            # article/paper divider must remain visible and movable there.
            page.set_viewport_size({"width": 900, "height": 900})
            expect(resizer).to_be_visible()
            narrow_width = panel.bounding_box()["width"]
            narrow_box = resizer.bounding_box()
            page.mouse.move(narrow_box["x"] + narrow_box["width"] / 2, narrow_box["y"] + 120)
            page.mouse.down()
            page.mouse.move(narrow_box["x"] + 100, narrow_box["y"] + 120, steps=8)
            page.mouse.up()
            narrowed_width = panel.bounding_box()["width"]
            assert narrowed_width < narrow_width - 70, (narrow_width, narrowed_width)
            page.set_viewport_size({"width": 1600, "height": 1000})

            nav_toggle = page.locator(".reader-nav-toggle")
            expect(nav_toggle).to_be_visible()
            nav_toggle.click()
            expect(page.locator("body")).to_have_class(re.compile("reader-nav-collapsed"))
            expect(page.locator(".md-sidebar--primary")).not_to_be_visible()
            page.reload(wait_until="networkidle")
            expect(page.locator("body")).to_have_class(re.compile("reader-nav-collapsed"))

            remote_requests = []
            page.on("request", lambda request: remote_requests.append(request.url) if not request.url.startswith(base_url) else None)
            page.goto(f"{base_url}/papers/arxiv-1810.04805/", wait_until="networkidle")
            expect(page.locator(".evidence-panel")).not_to_be_visible()
            page.locator(".evidence-panel-toggle").click()
            bert_viewer = page.frame_locator(".evidence-panel__frame")
            bert_page = bert_viewer.locator("#page-number").input_value(timeout=15_000)
            expect(bert_viewer.locator(f'.pdf-page[data-page="{bert_page}"] canvas')).to_be_visible(timeout=15_000)
            assert not remote_requests, remote_requests

            page.close()
            browser.close()
    finally:
        server.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            server.wait(timeout=5)
        if server.poll() is None:
            server.kill()


if __name__ == "__main__":
    run()
    print("Reader browser regression checks passed")
