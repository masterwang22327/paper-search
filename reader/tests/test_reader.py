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
    site_database = READER_DIR / "user-data" / TASK_ID / "site.sqlite3"
    sys.path.insert(0, str(READER_DIR))
    from runtime_store import RuntimeStore
    from site_store import SiteStore

    site_store = SiteStore(site_database, READER_DIR.parent)
    paper_routes = sorted(
        path.stem
        for path in (READER_DIR.parent / "tasks" / TASK_ID / "papers").glob("*.md")
    )
    assert len(paper_routes) == 70, paper_routes
    for filename in (
        "preln-postln-icml2020-fig1.png",
        "gqa-head-sharing-emnlp2023-fig2.png",
        "sliding-window-mistral2023-fig1.png",
    ):
        assert site_store.entry(f"images/modern-transformer-block/{filename}") is not None, filename
    port = free_port()
    server = subprocess.Popen(
        [
            sys.executable,
            str(READER_DIR / "site_store.py"),
            "serve",
            "--database",
            str(site_database),
            "--port",
            str(port),
        ],
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
            runtime_store = RuntimeStore(
                READER_DIR / "user-data" / TASK_ID / "state.sqlite3"
            )
            transformer_revisions = runtime_store.load_json(
                "document-revisions/e1a48e1b8a1ee4d8644a.json", {}
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
                      content: String.raw`# 历史回答

行内公式 \\(E\\in\\mathbb{R}^{V\\times d}\\)。

\\[
\\text{logits}=hE^\\top
\\]

` + Array.from(
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
                    knowledge_settings: {model: "gpt-5.6-terra", effort: "medium"},
                    revision_discussions: {items: []}
                  };
                  window.__knowledgeAskRequests = [];
                  window.__knowledgeSettingsRequests = [];
                  window.__knowledgeStateRequests = 0;
                  window.__translationTestState = {};
                  window.__translationPostCalls = [];
                  window.__translationFullStartCalls = [];
                  window.__translationFullState = {
                    status: "idle", completed: 0, total: 15, current_pages: [], concurrency: 16, failures: 0
                  };
                  window.__translationFullMetrics = {count: 0, active: 0, maxActive: 0, delay: 0};
                  const json = value => Promise.resolve(new Response(JSON.stringify(value), {
                    status: 200,
                    headers: {"Content-Type": "application/json"}
                  }));
                  window.fetch = (input, init) => {
                    const url = typeof input === "string" ? input : input.url;
                    if (url === "/api/bootstrap") {
                      return json({token: "test-token", task_id: "test-task"});
                    }
                    if (url.startsWith("/api/state?")) {
                      window.__knowledgeStateRequests += 1;
                      return json(window.__faqTestState);
                    }
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
                    if (url === "/api/chat/settings") {
                      const request = JSON.parse(init.body);
                      window.__knowledgeSettingsRequests.push(request);
                      window.__faqTestState.knowledge_settings = {
                        model: request.model,
                        effort: request.effort
                      };
                      return json(window.__faqTestState.knowledge_settings);
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
                      window.__knowledgeAskRequests.push(request);
                      const user = {
                        id: "asked-user",
                        role: "user",
                        content: request.question,
                        contexts: request.contexts,
                        pdf_contexts: request.pdf_contexts
                      };
                      const assistant = {
                        id: "asked-assistant",
                        role: "assistant",
                        content: String.raw`模拟回答完成。因此，这个结果的 policy 学习率就是 \\(1e\\!-\\!4\\)，而不是 LoRA 的 \\(5e\\!-\\!4\\)。`
                      };
                      return new Promise(resolve => setTimeout(() => {
                        window.__faqTestState.messages.push(user, assistant);
                        const current = window.__faqTestState.threads.find(item => item.id === request.thread_id);
                        if (current) current.message_count += 2;
                        resolve(new Response(JSON.stringify({
                          thread_id: request.thread_id,
                          active_thread_id: request.thread_id,
                          session_id: "11111111-2222-4333-8444-555555555555",
                          threads: window.__faqTestState.threads,
                          knowledge_settings: window.__faqTestState.knowledge_settings,
                          messages: [user, assistant]
                        }), {status: 200, headers: {"Content-Type": "application/json"}}));
                      }, 1_500));
                    }
                    if (url.startsWith("/api/translation/full?") && (!init || !init.method || init.method === "GET")) {
                      const metrics = window.__translationFullMetrics;
                      metrics.count += 1;
                      metrics.active += 1;
                      metrics.maxActive = Math.max(metrics.maxActive, metrics.active);
                      return new Promise(resolve => setTimeout(() => {
                        metrics.active -= 1;
                        resolve(new Response(JSON.stringify(window.__translationFullState), {
                          status: 200,
                          headers: {"Content-Type": "application/json"}
                        }));
                      }, metrics.delay));
                    }
                    if (url === "/api/translation/full/start") {
                      window.__translationFullStartCalls.push(JSON.parse(init.body));
                      const completed = Object.keys(window.__translationTestState).length;
                      window.__translationFullState = completed >= 15
                        ? {status: "completed", completed: 15, total: 15, current_pages: [], concurrency: 16, failures: 0}
                        : {status: "running", completed, total: 15, current_pages: [3], concurrency: 16, failures: 0};
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
                      window.__translationPostCalls.push(request);
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
                              bbox: [260, 350, 350, 450],
                              location_match: "visual-text-exact",
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
                                labels: [{
                                  original: "first token attention score: 0.01 (baseline, layer 21)",
                                  translation: "首个词元注意力分数：0.01（基线模型，第 21 层）"
                                }, {original: "Inputs", translation: "输入"}],
                                flow_steps: ["输入进入编码器。", "解码器生成输出。"],
                                notes: []
                              }
                            }],
                            warnings: [],
                          visual_input: true,
                          translation_model: request.model || "gpt-5.6-terra",
                          translation_reasoning_effort: request.reasoning_effort || "medium",
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

            page.goto(f"{base_url}/", wait_until="networkidle")
            current_topic = page.get_by_role(
                "link", name="进入专题精读", exact=True
            )
            expect(current_topic).to_be_visible()
            expect(page.locator("body")).to_contain_text(
                "从现成 Instruct checkpoint 出发，后训练还能把能力推多远"
            )
            current_topic.click()
            page.wait_for_url(f"{base_url}/papers/instruct-model-effective-post-training/")
            expect(page.locator("h1")).to_contain_text(
                "从现成 Instruct checkpoint 出发，后训练还能把能力推多远"
            )

            page.goto(f"{base_url}/reading-guide/", wait_until="networkidle")
            expect(page.locator(".learning-stage")).to_have_count(14)
            expect(page.locator(".learning-stage").first).to_contain_text("进入前")
            expect(page.locator(".learning-stage").first).to_contain_text("读完后")
            expect(page.locator(".learning-stage").first).to_contain_text("阶段检查")
            expect(page.locator(".learning-stage__papers > li")).to_have_count(67)

            # The Reader is a desktop-only application. Every generated paper
            # uses the same explicit disclosure control, whose fixed box must
            # remain separate from the label at the supported desktop width.
            for paper_route in paper_routes:
                page.goto(f"{base_url}/papers/{paper_route}/", wait_until="domcontentloaded")
                assert page.locator('meta[name="viewport"]').count() == 0, paper_route
                summary = page.locator(".paper-reading-card__details > summary")
                expect(summary).to_be_visible()
                expect(summary.locator(".paper-reading-card__details-icon")).to_have_count(1)
                disclosure_layout = summary.evaluate(
                    """element => {
                      const icon = element.querySelector('.paper-reading-card__details-icon');
                      const label = icon.nextElementSibling;
                      const iconRect = icon.getBoundingClientRect();
                      const labelRect = label.getBoundingClientRect();
                      return {
                        summaryPseudoDisplay: getComputedStyle(element, '::before').display,
                        iconMask: getComputedStyle(icon, '::before').maskImage,
                        iconWidth: iconRect.width,
                        iconHeight: iconRect.height,
                        iconRight: iconRect.right,
                        labelLeft: labelRect.left,
                        label: label.textContent.trim()
                      };
                    }"""
                )
                assert disclosure_layout["label"] == "查看完整导读", disclosure_layout
                assert disclosure_layout["summaryPseudoDisplay"] == "none", disclosure_layout
                assert disclosure_layout["iconMask"] != "none", disclosure_layout
                assert disclosure_layout["iconWidth"] >= 16, disclosure_layout
                assert disclosure_layout["iconHeight"] >= 16, disclosure_layout
                assert disclosure_layout["iconRight"] < disclosure_layout["labelLeft"], disclosure_layout

                callout_layouts = page.locator(
                    ".admonition > .admonition-title, "
                    "details.note > summary, details.abstract > summary, "
                    "details.info > summary, details.tip > summary, "
                    "details.success > summary, details.question > summary, "
                    "details.warning > summary, details.failure > summary, "
                    "details.danger > summary, details.bug > summary, "
                    "details.example > summary, details.quote > summary"
                ).evaluate_all(
                    """titles => titles.map(title => {
                      const before = getComputedStyle(title, '::before');
                      const titleBox = title.getBoundingClientRect();
                      const range = document.createRange();
                      range.selectNodeContents(title);
                      const textBox = range.getBoundingClientRect();
                      return {
                        text: title.textContent.trim(),
                        beforeDisplay: before.display,
                        beforeMask: before.maskImage,
                        beforeRight: titleBox.left + Number.parseFloat(before.left) +
                          Number.parseFloat(before.width),
                        textLeft: textBox.left
                      };
                    })"""
                )
                for callout_layout in callout_layouts:
                    assert callout_layout["beforeDisplay"] != "none", (
                        paper_route,
                        callout_layout,
                    )
                    assert callout_layout["beforeMask"] != "none", (
                        paper_route,
                        callout_layout,
                    )
                    assert callout_layout["beforeRight"] < callout_layout["textLeft"], (
                        paper_route,
                        callout_layout,
                    )

            page.goto(f"{base_url}/reading-guide/", wait_until="networkidle")
            post_training_link = page.get_by_role(
                "link",
                name=re.compile(r"^从现成 Instruct checkpoint 出发，后训练还能把能力推多远"),
            )
            expect(post_training_link).to_be_visible()
            post_training_link.click()
            page.wait_for_url(f"{base_url}/papers/instruct-model-effective-post-training/")
            expect(page.locator("h1")).to_contain_text(
                "从现成 Instruct checkpoint 出发，后训练还能把能力推多远"
            )

            page.goto(f"{base_url}/papers/arxiv-2608.09867/", wait_until="networkidle")
            expect(page.locator("h1")).to_contain_text("加密推理块不是保险箱")
            expect(page.locator(".paper-reading-card__route")).to_contain_text("本阶段 4/4")
            expect(page.locator(".paper-reading-card__route")).to_contain_text("全路线 38/67")
            expect(page.locator(".evidence-link")).to_have_count(14)
            first_reasoning_source = page.locator(".evidence-link").first
            expect(first_reasoning_source).to_have_attribute("data-primary", "true")
            expect(first_reasoning_source).to_have_attribute(
                "href", re.compile(r"/sources/arxiv-2608\.09867v1/paper\.pdf#page=1$")
            )
            expect(page.locator(".paper-reading-card__route nav a")).to_have_count(2)

            page.goto(f"{base_url}/papers/tokenization-data-curation/", wait_until="networkidle")
            expect(page.locator(".paper-reading-card__stage-entry")).to_be_visible()
            expect(page.locator(".reader-tool-dock > .evidence-panel-toggle")).to_be_visible()

            page.goto(f"{base_url}/papers/modern-transformer-block/", wait_until="networkidle")
            expect(page.locator("body")).to_have_class(re.compile(r"reader-modern-transformer-page"))
            qwen_source = page.locator(
                'a[href="https://github.com/huggingface/transformers/blob/v4.57.0/'
                'src/transformers/models/qwen3_next/modeling_qwen3_next.py#L330-L399"]'
            )
            expect(qwen_source).to_have_attribute("target", "_blank")
            expect(qwen_source).to_have_attribute("rel", re.compile(r"\bnoopener\b"))
            expect(qwen_source).to_have_attribute("rel", re.compile(r"\bnoreferrer\b"))
            expect(page.locator(".paper-reading-card__overview")).not_to_be_visible()
            expect(page.locator(".paper-reading-card__first-pass")).not_to_be_visible()
            expect(page.locator(".modern-block-brief__prerequisites")).to_be_visible()
            expect(page.locator("article h1")).to_contain_text("现代 Transformer Block 的演进")
            expect(page.locator(".modern-block-evolution")).to_be_visible()
            for callout_selector in (
                ".admonition.note > .admonition-title",
                ".admonition.question > .admonition-title",
                "details.example > summary",
                ".modern-block-brief__prerequisites > summary",
                ".concept-lab__boundary > summary",
                ".attention-head-lab__advanced > summary",
            ):
                callout_title = page.locator(callout_selector).first
                expect(callout_title).to_be_visible()
                callout_style = callout_title.evaluate(
                    """title => {
                      const before = getComputedStyle(title, '::before');
                      const titleBox = title.getBoundingClientRect();
                      const range = document.createRange();
                      range.selectNodeContents(title);
                      const textBox = range.getBoundingClientRect();
                      return {
                        beforeDisplay: before.display,
                        beforeMask: before.maskImage,
                        beforeRight: titleBox.left + Number.parseFloat(before.left) +
                          Number.parseFloat(before.width),
                        textLeft: textBox.left,
                        paddingLeft: Number.parseFloat(getComputedStyle(title).paddingLeft)
                      };
                    }"""
                )
                assert callout_style["beforeDisplay"] != "none", (
                    callout_selector,
                    callout_style,
                )
                assert callout_style["beforeMask"] != "none", (
                    callout_selector,
                    callout_style,
                )
                assert callout_style["beforeRight"] < callout_style["textLeft"], (
                    callout_selector,
                    callout_style,
                )
            reading_card_details = page.locator(".paper-reading-card__details")
            reading_card_icon = reading_card_details.locator(
                ".paper-reading-card__details-icon"
            )
            expect(reading_card_icon).to_be_visible()
            reading_card_details.locator(":scope > summary").click()
            expect(reading_card_details).to_have_attribute("open", "")
            audit_summary = page.locator(
                ".paper-figure-evidence > summary",
                has_text="固定模型发布物、版本身份与运行 ABI 的审计",
            )
            expect(audit_summary).to_be_visible()
            audit_summary_layout = audit_summary.evaluate(
                """summary => {
                  const box = summary.getBoundingClientRect();
                  const before = getComputedStyle(summary, '::before');
                  const after = getComputedStyle(summary, '::after');
                  const textRange = document.createRange();
                  textRange.selectNodeContents(summary);
                  const textBox = textRange.getBoundingClientRect();
                  return {
                    beforeDisplay: before.display,
                    leftInset: textBox.left - box.left,
                    rightSpace: box.right - textBox.right,
                    arrowRight: Number.parseFloat(after.right),
                    arrowWidth: Number.parseFloat(after.width),
                    boxWidth: box.width
                  };
                }"""
            )
            assert audit_summary_layout["beforeDisplay"] != "none", audit_summary_layout
            assert audit_summary_layout["leftInset"] >= 32, audit_summary_layout
            assert audit_summary_layout["rightSpace"] >= 32, audit_summary_layout
            assert audit_summary_layout["arrowRight"] >= 10, audit_summary_layout
            assert audit_summary_layout["arrowWidth"] >= 14, audit_summary_layout
            narrative_structure = page.evaluate(
                """() => {
                  const evolution = document.querySelector('.modern-block-evolution');
                  const blockMap = document.querySelector('.modern-block-map');
                  const headings = [...document.querySelectorAll('article h2, article h3')]
                    .map((heading) => ({tag: heading.tagName, text: heading.textContent.trim()}));
                  const indexOf = (needle) => headings.findIndex((heading) =>
                    heading.text.includes(needle));
                  return {
                    evolutionBeforePlugin: Boolean(
                      evolution.compareDocumentPosition(blockMap)
                        & Node.DOCUMENT_POSITION_FOLLOWING
                    ),
                    firstH2: headings.find((heading) => heading.tag === 'H2')?.text || '',
                    roleRows: document.querySelectorAll('.paper-role-table-wrap tbody tr').length,
                    shapeHeading: headings.find((heading) => heading.text.includes('固定 shape')),
                    baseline: indexOf('固定共同基线'),
                    normPath: indexOf('路径一：'),
                    ffnPath: indexOf('路径二：'),
                    positionPath: indexOf('路径三：'),
                    kvPath: indexOf('路径四：'),
                    recipe: indexOf('回到现代配方'),
                    secondPass: indexOf('第二遍选读：更大规模'),
                    residual: indexOf('Residual：'),
                    layerNorm: indexOf('LayerNorm 与 RMSNorm'),
                    preLn: indexOf('Pre-LN 与 Post-LN')
                  };
                }"""
            )
            assert narrative_structure["evolutionBeforePlugin"], narrative_structure
            assert "全篇全览" in narrative_structure["firstH2"], narrative_structure
            assert narrative_structure["roleRows"] == 9, narrative_structure
            assert narrative_structure["shapeHeading"]["tag"] == "H3", narrative_structure
            assert (
                narrative_structure["baseline"]
                < narrative_structure["normPath"]
                < narrative_structure["ffnPath"]
                < narrative_structure["positionPath"]
                < narrative_structure["kvPath"]
                < narrative_structure["recipe"]
                < narrative_structure["secondPass"]
            ), narrative_structure
            assert (
                narrative_structure["residual"]
                < narrative_structure["layerNorm"]
                < narrative_structure["preLn"]
            ), narrative_structure
            page.locator('[data-block-node="attention"]').click()
            expect(page.locator("[data-block-readout-title]")).to_contain_text("跨位置读取历史")

            attention_lab = page.locator(".attention-head-lab")
            expect(attention_lab).to_be_visible()
            expect(page.locator("[data-attention-mode-label]")).to_have_text("GQA · 8:2")
            expect(page.locator("[data-attention-cache]")).to_have_text("64 MiB")
            expect(page.locator("[data-attention-scores]")).to_have_text("32,768")
            page.locator('[data-attention-q-strip] [data-head="7"]').click()
            expect(page.locator("[data-attention-selected-map]")).to_have_text("Q7 → KV1")
            expect(page.locator("[data-attention-selected-query]")).to_have_class(
                re.compile(r"is-selected-group")
            )
            expect(page.locator("[data-attention-selected-kv]")).to_have_class(
                re.compile(r"is-selected-group")
            )
            expect(page.locator('[data-attention-q-strip] .is-group-peer')).to_have_count(4)

            page.locator('[data-attention-preset="mha"]').click()
            expect(page.locator("[data-attention-cache]")).to_have_text("256 MiB")
            expect(page.locator("[data-attention-scores]")).to_have_text("32,768")
            page.locator('[data-attention-preset="mqa"]').click()
            expect(page.locator("[data-attention-cache]")).to_have_text("32 MiB")
            expect(page.locator("[data-attention-scores]")).to_have_text("32,768")
            page.locator('[data-attention-preset="gqa"]').click()
            page.locator('[data-attention-control="query-heads"] [data-value="32"]').click()
            expect(page.locator("[data-attention-mode-label]")).to_have_text("GQA · 32:8")
            expect(page.locator('[data-attention-control="kv-heads"] button')).to_have_count(6)
            expect(page.locator("[data-attention-cache]")).to_have_text("256 MiB")
            expect(page.locator("[data-attention-scores]")).to_have_text("131,072")
            page.locator(".attention-head-lab__advanced").evaluate("element => element.open = true")
            page.locator('[data-attention-input="context-index"]').evaluate(
                """element => {
                  element.value = "4";
                  element.dispatchEvent(new Event("input", {bubbles: true}));
                }"""
            )
            expect(page.locator('[data-attention-output="context"]')).to_have_text("8,192")
            expect(page.locator("[data-attention-cache]")).to_have_text("512 MiB")

            expect(page.locator("[data-reader-widget]")).to_have_count(7)
            page.locator('[data-lifecycle-mode="train"]').click()
            expect(page.locator("[data-lifecycle-persist-label]")).to_have_text("跨 training step 保留")
            expect(page.locator("[data-lifecycle-persist]")).to_contain_text("optimizer state")
            page.locator('[data-lifecycle-mode="prefill"]').click()
            expect(page.locator("[data-lifecycle-persist-label]")).to_have_text("交给同一请求的 Decode")
            expect(page.locator("[data-lifecycle-persist]")).to_contain_text("当前请求 KV cache")
            page.locator('[data-lifecycle-mode="decode"]').click()
            expect(page.locator("[data-lifecycle-persist-label]")).to_have_text("跨生成步保留")
            expect(page.locator("[data-lifecycle-absent]")).to_contain_text("gradient")

            page.locator('[data-norm-input="shift"]').evaluate(
                """element => {
                  element.value = "0";
                  element.dispatchEvent(new Event("input", {bubbles: true}));
                }"""
            )
            expect(page.locator('[data-norm-delta="rms"]')).to_have_text("0.000")
            page.locator('[data-swiglu-input="gate"]').evaluate(
                """element => {
                  element.value = "-2";
                  element.dispatchEvent(new Event("input", {bubbles: true}));
                }"""
            )
            expect(page.locator('[data-swiglu-number="silu"]')).to_have_text("-0.238")

            rope_dot = page.locator("[data-rope-dot]").inner_text()
            page.locator('[data-rope-input="shift"]').evaluate(
                """element => {
                  element.value = "9";
                  element.dispatchEvent(new Event("input", {bubbles: true}));
                }"""
            )
            expect(page.locator("[data-rope-dot]")).to_have_text(rope_dot)
            page.locator('[data-swa-input="window"]').evaluate(
                """element => {
                  element.value = "6";
                  element.dispatchEvent(new Event("input", {bubbles: true}));
                }"""
            )
            expect(page.locator("[data-swa-summary]")).to_contain_text("直接 6")
            page.locator('[data-intervention-title^="Soft-cap"]').click()
            expect(page.locator("[data-intervention-readout-title]")).to_contain_text("Soft-cap")
            expect(page.locator('[data-intervention-title^="Soft-cap"]')).to_have_attribute("aria-pressed", "true")
            expect(page.locator(".paper-figure-evidence img")).to_have_count(3)
            expect(page.locator(".paper-figure-evidence figure > a")).to_have_count(3)

            page.locator('[data-attention-control="kv-heads"] [data-value="4"]').click()
            expect(page.locator('[data-attention-control="kv-heads"] [data-value="4"]')).to_be_focused()
            expect(page.locator('[data-attention-input="context-index"]')).to_have_attribute(
                "aria-valuetext", "8,192 tokens"
            )
            page.locator('[data-attention-control="query-heads"] [data-value="64"]').click()
            page.locator('[data-attention-preset="mha"]').click()
            page.locator('[data-attention-q-strip] [data-head="8"]').click()
            expect(page.locator('[data-attention-q-strip] .is-group-peer')).to_have_count(1)
            expect(page.locator('[data-attention-q-strip] [data-head="0"]')).not_to_have_class(
                re.compile(r"is-group-peer")
            )

            visual_state = page.evaluate(
                """() => ({
                  enhanced: [...document.querySelectorAll('[data-reader-widget]')]
                    .every(element => element.dataset.enhanced === 'true'),
                  canvases: [...document.querySelectorAll('[data-rope-canvas], [data-swa-canvas]')]
                    .map(canvas => {
                    const pixels = canvas.getContext('2d')
                      .getImageData(0, 0, canvas.width, canvas.height).data;
                    let visible = 0;
                    for (let index = 3; index < pixels.length; index += 4) {
                      if (pixels[index]) visible += 1;
                    }
                    return {width: canvas.width, height: canvas.height, visible};
                  })
                })"""
            )
            assert visual_state["enhanced"], visual_state
            assert len(visual_state["canvases"]) == 2, visual_state
            assert all(canvas["visible"] > 100 for canvas in visual_state["canvases"]), visual_state
            concept_layout = page.evaluate(
                """() => ({
                  overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                  labOverflow: document.querySelector('.attention-head-lab').scrollWidth
                    - document.querySelector('.attention-head-lab').clientWidth
                })"""
            )
            assert concept_layout["overflow"] <= 1, concept_layout
            assert concept_layout["labOverflow"] <= 1, concept_layout
            page.set_viewport_size({"width": 1600, "height": 1000})

            page.goto(
                f"{base_url}/papers/reward-verifier-policy-learning/",
                wait_until="networkidle",
            )
            reward_lab = page.locator('[data-reader-widget="reward-policy-clock"]')
            expect(reward_lab).to_be_visible()
            expect(reward_lab).to_have_attribute("data-enhanced", "true")
            expect(page.locator("[data-reward-badge]")).to_have_text("不更新 generator")
            expect(page.locator("[data-reward-verdict]")).to_contain_text("推理时选择")
            expect(page.locator("[data-reward-update-node]")).not_to_have_class(
                re.compile(r"is-updating")
            )

            reward_expectations = {
                "rs-sft": ("CE 更新 generator", "外层 online data refresh"),
                "policy-gradient": ("reward 更新 policy", "近 on-policy"),
                "dpo": ("pair loss 更新 policy", "offline preference optimization"),
                "mcts-dpo": ("内层固定，外层刷新", "outer online/on-policy refresh"),
                "ilql": ("固定日志上的 offline RL", "value-based offline RL"),
            }
            for mode, (badge, verdict) in reward_expectations.items():
                button = page.locator(f'[data-reward-mode="{mode}"]')
                button.click()
                expect(button).to_have_attribute("aria-pressed", "true")
                expect(page.locator("[data-reward-badge]")).to_have_text(badge)
                expect(page.locator("[data-reward-verdict]")).to_contain_text(verdict)
                expect(page.locator("[data-reward-update-node]")).to_have_class(
                    re.compile(r"is-updating")
                )

            expect(page.locator(".paper-figure-evidence img")).to_have_count(2)
            expect(page.locator(".paper-figure-evidence figure > a")).to_have_count(2)
            reward_layout = reward_lab.evaluate(
                """root => ({
                  pageOverflow: document.documentElement.scrollWidth
                    - document.documentElement.clientWidth,
                  labOverflow: root.scrollWidth - root.clientWidth,
                  clippedButtons: [...root.querySelectorAll('[data-reward-mode]')]
                    .filter(button => button.scrollWidth > button.clientWidth + 1).length
                })"""
            )
            assert reward_layout["pageOverflow"] <= 1, reward_layout
            assert reward_layout["labOverflow"] <= 1, reward_layout
            assert reward_layout["clippedButtons"] == 0, reward_layout

            page.goto(f"{base_url}/papers/arxiv-1706.03762/", wait_until="networkidle")

            panel = page.locator(".evidence-panel")
            expect(panel).not_to_be_visible()
            expect(page.locator(".evidence-panel-toggle")).to_be_visible()
            expect(page.locator(".reader-section-tools")).to_be_visible()
            expect(page.locator(".reader-section-tools__current small")).to_have_text(re.compile(r"1 / \d+"))
            expect(page.locator(".paper-reading-card__details")).to_be_visible()
            expect(page.locator(".paper-reading-card__route")).to_contain_text("本阶段 5/7")
            expect(page.locator(".paper-reading-card__route")).to_contain_text("全路线 5/67")
            expect(page.locator(".paper-reading-card__route")).to_contain_text("从上一篇到本篇")
            expect(page.locator(".paper-reading-card__route nav a")).to_have_count(2)
            expect(page.locator(".reading-route-footer")).to_be_visible()
            expect(page.locator(".reading-route-footer__next")).to_contain_text("现代 Transformer Block")
            expect(page.locator(".md-sidebar--primary")).to_be_visible()
            expect(page.locator(".md-sidebar--secondary")).to_be_visible()
            page.locator(".evidence-panel-toggle").click()
            expect(panel).to_be_visible()
            panel_box = panel.bounding_box()
            assert panel_box["y"] == 0, panel_box
            expect(page.locator(".md-header")).not_to_be_visible()
            expect(page.locator(".paper-reading-card__details")).not_to_be_visible()
            expect(page.locator(".md-sidebar--primary")).not_to_be_visible()
            expect(page.locator(".md-sidebar--secondary")).not_to_be_visible()
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
            expect(page.locator('[data-setting="knowledge-model"]')).to_have_value("gpt-5.6-terra")
            expect(page.locator('[data-setting="knowledge-effort"]')).to_have_value("medium")
            history_answer = page.locator('.knowledge-message[data-message-id="history-assistant"]')
            expect(history_answer.locator(".knowledge-math-inline mjx-container")).to_be_visible(timeout=5_000)
            expect(history_answer.locator(".knowledge-math-block mjx-container")).to_be_visible(timeout=5_000)
            history_math_layout = history_answer.evaluate(
                """element => [...element.querySelectorAll('.knowledge-math-inline, .knowledge-math-block')]
                  .map(math => {
                    const output = math.querySelector('mjx-container');
                    const rect = output?.getBoundingClientRect();
                    return {hasOutput: Boolean(output), width: rect?.width || 0, height: rect?.height || 0};
                  })"""
            )
            assert all(
                item["hasOutput"] and item["width"] > 0 and item["height"] > 0
                for item in history_math_layout
            ), history_math_layout
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
            expect(viewer.locator("#translation-toggle")).to_have_text("译文")
            expect(viewer.locator("#translation-toggle")).to_have_attribute("aria-pressed", "false")
            viewer.locator("#translation-toggle").click()
            expect(viewer.locator("#translation-toggle")).to_have_attribute("aria-pressed", "true")
            page.wait_for_timeout(250)
            expect(viewer.locator("#page-number")).to_have_value("2")
            expect(viewer.locator("#translate-page")).to_have_text("翻译本页")
            expect(viewer.locator("#translate-all")).to_have_text("翻译全文")
            viewer.locator("#translate-page").click()
            expect(viewer.locator("#translation-panel")).to_be_visible()
            viewport_box = viewer.locator("#viewport").bounding_box()
            translation_box = viewer.locator("#translation-panel").bounding_box()
            assert translation_box["x"] >= viewport_box["x"] + viewport_box["width"]
            assert abs(translation_box["y"] - viewport_box["y"]) < 2
            translation_content_box = viewer.locator("#translation-content").bounding_box()
            assert translation_content_box["y"] < 300, translation_content_box
            assert translation_content_box["height"] > 600, translation_content_box
            expect(viewer.locator("#translation-resizer")).to_have_attribute("aria-orientation", "vertical")
            expect(viewer.locator("#translation-state")).to_contain_text(
                re.compile(r"Codex 正在|已缓存")
            )
            expect(viewer.locator("#zoom-out")).to_be_visible()
            expect(viewer.locator("#zoom-in")).to_be_visible()
            initial_page_width = viewer.locator('.pdf-page[data-page="2"]').bounding_box()["width"]
            viewer.locator("#zoom-in").click()
            page.wait_for_timeout(250)
            assert viewer.locator('.pdf-page[data-page="2"]').bounding_box()["width"] > initial_page_width
            horizontal_range = viewer.locator("#viewport").evaluate(
                """viewport => {
                  const pdfPage = document.querySelector('.pdf-page[data-page="2"]');
                  const style = getComputedStyle(viewport);
                  const leftInset = Number.parseFloat(style.paddingLeft);
                  viewport.scrollLeft = 0;
                  const viewportRect = viewport.getBoundingClientRect();
                  const startRect = pdfPage.getBoundingClientRect();
                  const startGap = startRect.left - viewportRect.left;
                  viewport.scrollLeft = viewport.scrollWidth - viewport.clientWidth;
                  const endRect = pdfPage.getBoundingClientRect();
                  return {
                    overflow: viewport.scrollWidth - viewport.clientWidth,
                    reachedStart: Math.abs(startGap - leftInset) < 2,
                    reachedEnd: Math.abs(viewportRect.right - endRect.right) < 2
                  };
                }"""
            )
            assert horizontal_range["overflow"] > 0, horizontal_range
            assert horizontal_range["reachedStart"], horizontal_range
            assert horizontal_range["reachedEnd"], horizontal_range
            viewer.locator("#fit-width").click()
            expect(viewer.locator(".translation-target")).to_contain_text("第 2 页模拟中文译文", timeout=3_000)
            viewer.locator("body").evaluate(
                """() => {
                  window.__translationFullMetrics.count = 0;
                  window.__translationFullMetrics.active = 0;
                  window.__translationFullMetrics.maxActive = 0;
                  window.__translationFullMetrics.delay = 2300;
                }"""
            )
            page.wait_for_timeout(3100)
            full_poll_metrics = viewer.locator("body").evaluate("() => ({...window.__translationFullMetrics})")
            assert full_poll_metrics["count"] >= 1, full_poll_metrics
            assert full_poll_metrics["maxActive"] == 1, full_poll_metrics
            viewer.locator("body").evaluate("() => { window.__translationFullMetrics.delay = 0; }")
            translation_block = viewer.locator(".translation-target .translation-block[data-block-id='p0002-b001']")
            expect(translation_block.locator(".translation-block__label")).to_contain_text("p0002-b001")
            expect(translation_block.locator(".translation-block__natural")).to_have_text("正文第 1 段")
            expect(translation_block.locator(".translation-block__confidence")).to_contain_text("高置信度")
            overlay_bounds = viewer.locator('.pdf-page[data-page="2"]').evaluate(
                """pdfPage => {
                  const overlay = pdfPage.querySelector('.pdf-block-overlay');
                  const highlight = overlay.querySelector('[data-block-id="p0002-b001"]');
                  return {
                    pageWidth: pdfPage.clientWidth,
                    overlayWidth: overlay.clientWidth,
                    highlightLeft: highlight.offsetLeft,
                    highlightRight: highlight.offsetLeft + highlight.offsetWidth,
                    pageOverflow: getComputedStyle(pdfPage).overflow,
                    overlayOverflow: getComputedStyle(overlay).overflow
                  };
                }"""
            )
            assert overlay_bounds["highlightLeft"] >= 0, overlay_bounds
            assert overlay_bounds["highlightRight"] <= overlay_bounds["pageWidth"], overlay_bounds
            assert overlay_bounds["overlayWidth"] == overlay_bounds["pageWidth"], overlay_bounds
            assert overlay_bounds["pageOverflow"] == "clip", overlay_bounds
            assert overlay_bounds["overlayOverflow"] == "hidden", overlay_bounds
            expect(viewer.locator(".translation-table-data th")).to_have_text(["模型", "质量"])
            expect(viewer.locator(".translation-table-data tbody tr")).to_have_count(2)
            expect(viewer.locator(".translation-figure-data")).to_contain_text("输入经过编码器与解码器后生成输出")
            expect(viewer.locator(".translation-figure-flow li")).to_have_count(2)
            expect(viewer.locator(".translation-figure-labels")).to_contain_text("Inputs")
            figure_label_layout = viewer.locator(".translation-figure-labels").evaluate(
                """labels => {
                  const original = labels.querySelector("dt");
                  const translated = labels.querySelector("dd");
                  return {
                    labelsWidth: labels.getBoundingClientRect().width,
                    originalWidth: original.getBoundingClientRect().width,
                    translatedWidth: translated.getBoundingClientRect().width
                  };
                }"""
            )
            assert figure_label_layout["labelsWidth"] > 200, figure_label_layout
            assert figure_label_layout["originalWidth"] >= 80, figure_label_layout
            assert figure_label_layout["translatedWidth"] >= 120, figure_label_layout
            expect(viewer.locator("#retranslation-controls")).to_be_visible()
            expect(viewer.locator("#retranslation-model")).to_have_value("gpt-5.6-terra")
            expect(viewer.locator("#retranslation-effort")).to_have_value("medium")
            viewer.locator("#retranslation-model").select_option("gpt-5.6-sol")
            viewer.locator("#retranslation-effort").select_option("xhigh")
            viewer.locator("#retranslate-page").click()
            expect(viewer.locator("#retranslate-page")).to_have_text("正在重译…")
            expect(viewer.locator("#translation-state")).to_contain_text("gpt-5.6-sol / xhigh", timeout=3_000)
            expect(viewer.locator("#retranslate-page")).to_have_text("重新翻译")
            retranslation_request = viewer.locator("body").evaluate("() => window.__translationPostCalls.at(-1)")
            assert retranslation_request["force"] is True
            assert retranslation_request["model"] == "gpt-5.6-sol"
            assert retranslation_request["reasoning_effort"] == "xhigh"
            expect(viewer.locator("#show-source")).to_have_count(0)
            expect(viewer.locator(".translation-source")).to_have_count(0)

            # A translated block centers its matched PDF region in both axes,
            # including when the page is wider than the PDF viewport.
            viewer.locator("#zoom-in").click()
            viewer.locator("#zoom-in").click()
            page.wait_for_timeout(300)
            translation_block.click()
            expect(viewer.locator("#status")).to_contain_text("已通过原文匹配定位")
            page.wait_for_timeout(650)
            centered = viewer.locator("#viewport").evaluate(
                """viewport => {
                  const target = document.querySelector('.pdf-block-highlight.is-selected');
                  const viewportRect = viewport.getBoundingClientRect();
                  const targetRect = target.getBoundingClientRect();
                  return {
                    x: targetRect.left + targetRect.width / 2 - (viewportRect.left + viewport.clientWidth / 2),
                    y: targetRect.top + targetRect.height / 2 - (viewportRect.top + viewport.clientHeight / 2)
                  };
                }"""
            )
            assert abs(centered["x"]) < 6, centered
            assert abs(centered["y"]) < 6, centered

            # Dragging the enlarged PDF pans the native scroll viewport.
            pdf_viewport = viewer.locator("#viewport")
            expect(pdf_viewport).to_have_css("cursor", "grab")
            drag_box = pdf_viewport.bounding_box()
            before_drag = pdf_viewport.evaluate("viewport => ({left: viewport.scrollLeft, top: viewport.scrollTop})")
            drag_x = drag_box["x"] + drag_box["width"] * 0.35
            drag_y = drag_box["y"] + drag_box["height"] * 0.45
            page.mouse.move(drag_x, drag_y)
            page.mouse.down()
            page.mouse.move(drag_x - 80, drag_y - 60, steps=8)
            page.mouse.up()
            after_drag = pdf_viewport.evaluate("viewport => ({left: viewport.scrollLeft, top: viewport.scrollTop})")
            assert after_drag["left"] > before_drag["left"] + 60, (before_drag, after_drag)
            assert after_drag["top"] > before_drag["top"] + 40, (before_drag, after_drag)

            # Full translation is sequential, stoppable and resumes by
            # skipping pages already present in the local cache.
            viewer.locator("#translate-all").click()
            full_start_request = viewer.locator("body").evaluate("() => window.__translationFullStartCalls.at(-1)")
            assert full_start_request["model"] == "gpt-5.6-sol"
            assert full_start_request["reasoning_effort"] == "xhigh"
            assert full_start_request["concurrency"] == 16
            expect(viewer.locator("#translate-all")).to_have_text("停止全文")
            expect(viewer.locator("#translate-all")).to_have_attribute("aria-busy", "true")
            expect(viewer.locator("#full-translation-progress")).to_contain_text("/15")
            expect(viewer.locator("#full-translation-status")).to_be_visible()
            expect(viewer.locator("#full-translation-status-title")).to_contain_text("全文翻译")
            viewer.locator("#translate-all").click()
            expect(viewer.locator("#translate-all")).to_have_text("补齐全文", timeout=3_000)
            expect(viewer.locator("#full-translation-status-title")).to_contain_text("已停止")
            viewer.locator("body").evaluate("""() => {
              window.__translationFullState = {
                status: "partial",
                completed: 10,
                total: 15,
                current_pages: [],
                current_started_at: "2026-01-01T00:00:00Z",
                concurrency: 16,
                failures: 2,
                last_error: "第 8 页：模型服务调用失败（HTTP 502）"
              };
            }""")
            expect(viewer.locator("#full-translation-status-title")).to_contain_text("暂未全部完成", timeout=3_000)
            expect(viewer.locator("#full-translation-elapsed")).to_have_text("00:00")
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
            expect(viewer.locator("#translate-all")).to_have_text("全文已缓存")
            expect(viewer.locator("#translate-all")).to_be_disabled()
            expect(viewer.locator("#full-translation-status")).to_be_hidden()
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
            expect(viewer.locator('.pdf-page[data-page="7"] canvas')).to_be_visible(timeout=15_000)
            expect(viewer.locator("#page-number")).to_have_value("7", timeout=15_000)
            expect(viewer.locator('.pdf-page[data-page="2"] canvas')).not_to_be_visible(timeout=5_000)
            page.locator('[data-reader-tab="assistant"]').click()
            page.wait_for_timeout(100)
            hidden_poll_count = viewer.locator("body").evaluate("() => window.__translationFullMetrics.count")
            page.wait_for_timeout(2200)
            assert viewer.locator("body").evaluate(
                "() => window.__translationFullMetrics.count"
            ) == hidden_poll_count
            page.locator('[data-action="add-pdf"]').click()
            expect(page.locator(".knowledge-context")).to_contain_text("PDF 整页图像")
            expect(page.locator(".knowledge-context")).to_contain_text("物理页 7")
            page.locator('[data-setting="knowledge-model"]').select_option("gpt-5.6-sol")
            page.locator('[data-setting="knowledge-effort"]').select_option("xhigh")
            page.wait_for_function("() => window.__knowledgeSettingsRequests.length === 2")
            state_requests_before_duplicate_init = page.evaluate(
                "() => window.__knowledgeStateRequests"
            )
            page.evaluate(
                """() => {
                  window.__faqTestState.knowledge_settings = {
                    model: "gpt-5.6-terra",
                    effort: "medium"
                  };
                  window.dispatchEvent(new Event("reader:evidence-panel-ready"));
                  window.dispatchEvent(new Event("reader:evidence-panel-ready"));
                }"""
            )
            page.wait_for_timeout(100)
            expect(page.locator('[data-setting="knowledge-model"]')).to_have_value(
                "gpt-5.6-sol"
            )
            expect(page.locator('[data-setting="knowledge-effort"]')).to_have_value(
                "xhigh"
            )
            assert page.evaluate(
                "() => window.__knowledgeStateRequests"
            ) == state_requests_before_duplicate_init
            page.locator(".knowledge-composer textarea").fill("解释第七页图表")
            page.locator('[data-action="send"]').click()
            expect(page.locator(".knowledge-context")).to_have_count(0)
            page.wait_for_function("() => window.__knowledgeAskRequests.length === 1")
            ask_settings = page.evaluate(
                "() => { const call = window.__knowledgeAskRequests.at(-1); return {model: call.model, effort: call.effort}; }"
            )
            assert ask_settings == {"model": "gpt-5.6-sol", "effort": "xhigh"}
            pending_message = page.locator(".knowledge-message.is-pending")
            expect(pending_message).to_contain_text("解释第七页图表")
            expect(pending_message.locator(".knowledge-message__pdf")).to_contain_text("物理页 7")
            expect(page.locator(".knowledge-session")).to_have_text("回答中…")
            expect(page.locator(".knowledge-message--assistant", has_text="模拟回答完成")).to_be_visible(timeout=3_000)
            expect(page.locator(".knowledge-message.is-pending")).to_have_count(0)
            expect(page.locator(".knowledge-session")).to_have_text("11111111")
            expect(page.locator(".knowledge-context")).to_have_count(0)
            assistant = page.locator(".knowledge-message--assistant", has_text="模拟回答完成")
            inline_math = assistant.locator(".knowledge-math-inline").first
            expect(inline_math).to_have_text("1e−4")
            inline_math_layout = inline_math.evaluate(
                """element => {
                  const rect = element.getBoundingClientRect();
                  const style = getComputedStyle(element);
                  return {
                    height: rect.height,
                    lineHeight: parseFloat(getComputedStyle(element.parentElement).lineHeight),
                    overflowWrap: style.overflowWrap,
                    whiteSpace: style.whiteSpace,
                    wordBreak: style.wordBreak
                  };
                }"""
            )
            assert inline_math_layout["height"] <= inline_math_layout["lineHeight"] * 1.5, inline_math_layout
            assert inline_math_layout["overflowWrap"] == "normal", inline_math_layout
            assert inline_math_layout["whiteSpace"] == "nowrap", inline_math_layout
            assert inline_math_layout["wordBreak"] == "normal", inline_math_layout
            assistant.get_by_role("button", name="保存为 FAQ").click()
            editor = page.locator(".knowledge-faq-editor__dialog")
            expect(editor).to_be_visible()
            expect(editor.locator('[name="question"]')).to_have_value("解释第七页图表")
            expect(editor.locator('[name="answer"]')).to_have_value(
                "模拟回答完成。因此，这个结果的 policy 学习率就是 \\(1e\\!-\\!4\\)，而不是 LoRA 的 \\(5e\\!-\\!4\\)。"
            )
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
            expect(page.locator('[data-setting="knowledge-model"]')).to_be_disabled()
            expect(page.locator('[data-setting="knowledge-effort"]')).to_be_disabled()
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator('[data-action="new-thread"]').click()
            expect(page.locator('[data-action="select-thread"]')).to_contain_text("对话 2")
            expect(page.locator(".knowledge-composer textarea")).to_be_enabled()
            expect(page.locator('[data-setting="knowledge-model"]')).to_be_enabled()
            expect(page.locator('[data-setting="knowledge-effort"]')).to_be_enabled()
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
            expect(page.locator(".md-sidebar--secondary")).to_be_visible()
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
            assert page.title().startswith("09 · 从 Causal LLM 到 BERT"), page.title()
            assert "09 · 09 ·" not in page.title(), page.title()
            page.goto(f"{base_url}/papers/arxiv-1910.10683/", wait_until="networkidle")
            assert page.title().startswith("10 · 从 BERT 到 T5"), page.title()
            assert "10 · 10 ·" not in page.title(), page.title()
            page.goto(f"{base_url}/papers/arxiv-1810.04805/", wait_until="networkidle")
            expect(page.locator(".evidence-panel")).not_to_be_visible()
            page.locator(".evidence-panel-toggle").click()
            bert_viewer = page.frame_locator(".evidence-panel__frame")
            bert_src = page.locator(".evidence-panel__frame").get_attribute("src")
            bert_page = urllib.parse.parse_qs(urllib.parse.urlparse(bert_src).query)["page"][0]
            expect(bert_viewer.locator("#page-number")).to_have_value(bert_page, timeout=15_000)
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
