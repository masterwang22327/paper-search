#!/usr/bin/env python3
"""Exercise Codex session, transcript, and FAQ persistence through the HTTP API."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock


READER_DIR = Path(__file__).resolve().parents[1]
TASK_ID = "paper-research-base-knowledge-about-llm-20260717"
sys.path.insert(0, str(READER_DIR))
import server as reader_server


def check_translation_api_key_policy() -> None:
    assert reader_server.DEFAULT_TRANSLATION_API_URL == "https://www.sevnx.one/v1/responses"

    with mock.patch.dict(
        os.environ,
        {
            "READER_TRANSLATION_API_KEY": "relay-test-key",
            "OPENAI_API_KEY": "openai-test-key",
        },
        clear=True,
    ):
        assert reader_server.ReaderState.load_translation_api_key(
            "https://relay.example/v1/responses"
        ) == "relay-test-key"

    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "openai-test-key"}, clear=True):
        assert reader_server.ReaderState.load_translation_api_key(
            "https://relay.example/v1/responses"
        ) is None
        assert reader_server.ReaderState.load_translation_api_key(
            "https://api.openai.com/v1/responses"
        ) == "openai-test-key"

    with tempfile.TemporaryDirectory() as temporary:
        codex_home = Path(temporary)
        (codex_home / "auth.json").write_text(
            json.dumps({"OPENAI_API_KEY": "codex-provider-key"}),
            encoding="utf-8",
        )
        (codex_home / "config.toml").write_text(
            'model_provider = "Relay"\n\n'
            '[model_providers.Relay]\n'
            'base_url = "https://relay.example/v1"\n',
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}, clear=True):
            assert reader_server.ReaderState.load_translation_api_key(
                "https://relay.example/v1/responses"
            ) == "codex-provider-key"
            assert reader_server.ReaderState.load_translation_api_key(
                "https://other.example/v1/responses"
            ) is None
            assert reader_server.ReaderState.load_translation_api_key(
                "https://relay.example/v2/responses"
            ) is None

        (codex_home / "config.toml").write_text(
            'model_provider = "OpenAI"\n\n'
            '[model_providers.OpenAI]\n'
            'base_url = "https://www.sevnx.one/v1"\n',
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}, clear=True):
            assert reader_server.ReaderState.load_translation_api_key(
                reader_server.DEFAULT_TRANSLATION_API_URL
            ) == "codex-provider-key"


def check_codex_error_messages() -> None:
    assert reader_server.ReaderState.codex_failure_message(
        "Error loading config.toml: invalid transport\nin `mcp_servers.openaiDeveloperDocs`"
    ) == "Codex CLI 配置无效：invalid transport"
    assert reader_server.ReaderState.codex_failure_message(
        "error: unexpected argument '--old-option' found"
    ) == "Codex CLI 参数不兼容：unexpected argument '--old-option' found"
    assert reader_server.ReaderState.codex_failure_message("authentication failed") == (
        "Codex 尚未登录或登录已失效，请先在终端完成登录"
    )
    assert reader_server.ReaderState.codex_failure_message("internal provider failure") == (
        "Codex 调用失败，请查看服务终端"
    )


def check_full_translation_terminal_state() -> None:
    class FakeResponse:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    state = reader_server.ReaderState.__new__(reader_server.ReaderState)
    state.lock = threading.RLock()
    state.translation_jobs = {}
    state.translation_job_stops = {}
    state.translation_job_responses = {}
    response = FakeResponse()
    state.register_translation_response("source", response)
    state.cancel_translation_responses("source")
    assert response.closed
    state.unregister_translation_response("source", response)
    assert "source" not in state.translation_job_responses

    with tempfile.TemporaryDirectory() as temporary:
        page_path = Path(temporary) / "missing.json"
        saved_states = []
        state.translation_page_path = lambda source_id, page: page_path
        state.cached_translation_page_count = lambda source_id: 0
        state.save_translation_job_state = lambda source_id, value: saved_states.append(dict(value))

        def fail_page(payload):
            raise RuntimeError("unexpected page failure")

        state.translate_page = fail_page
        job_state = {"total": 1, "concurrency": 1, "failures": 0}
        state.run_full_translation_job("source", 1, job_state, threading.Event())
        assert job_state["status"] == "partial"
        assert job_state["failures"] == 1
        assert job_state["current_started_at"] is None
        assert job_state["current_pages"] == []
        assert "unexpected page failure" in job_state["last_error"]
        assert saved_states[-1]["status"] == "partial"

    with tempfile.TemporaryDirectory() as temporary:
        job_path = Path(temporary) / "full-translation.json"
        job_path.write_text(json.dumps({
            "source_id": "source",
            "status": "partial",
            "completed": 0,
            "total": 30,
            "failures": 30,
            "last_error": "第 28 页：模型 API Key 未配置",
        }), encoding="utf-8")
        state.translation_job_path = lambda source_id: job_path
        state.cached_translation_page_count = lambda source_id: 1
        state.source_metadata = lambda source_id: {"page_count": 30}
        state.mark_manual_translation_success("source")
        recovered = json.loads(job_path.read_text(encoding="utf-8"))
        assert recovered["status"] == "idle"
        assert recovered["completed"] == 1
        assert recovered["failures"] == 0
        assert recovered["last_error"] == ""


def check_retranslation_compact_fallback() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        glossary_path = Path(temporary) / "glossary.json"
        glossary_path.write_text(
            json.dumps({
                "terms": {
                    "self-attention": {
                        "term": "self-attention",
                        "translation": "自注意力",
                        "locked": True,
                    },
                    "unused-context-term": {
                        "term": "unused-context-term",
                        "translation": "不应发送的术语",
                        "locked": False,
                    },
                }
            }),
            encoding="utf-8",
        )
        state = reader_server.ReaderState.__new__(reader_server.ReaderState)
        state.mark_manual_translation_success = lambda source_id: None
        state.translation_model = "gpt-5.6-terra"
        state.retranslation_model = "gpt-5.6-sol"
        state.retranslation_reasoning_effort = "high"
        state.validate_pdf = lambda payload: {"source_id": "paper", "page": 2}
        state.source_metadata = lambda source_id: {
            "title": "Fallback Test",
            "authors": ["Reader"],
            "pdf_sha256": "a" * 64,
            "page_count": 3,
        }
        page_text = {
            1: "PREVIOUS PAGE CONTEXT",
            2: "Current page explains self-attention.\x01FORMULA\x02",
            3: "NEXT PAGE CONTEXT",
        }
        state.pdf_page_text = lambda source_id, page: page_text[page]
        state.translation_glossary_path = lambda source_id: glossary_path
        state.translation_instructions = lambda: "FULL WORKFLOW CONTEXT"

        calls = []

        def call_translation(prompt, context, **kwargs):
            calls.append({"prompt": prompt, **kwargs})
            if len(calls) == 1:
                raise reader_server.ApiError(502, "upstream gateway failure")
            return "{}", "resp-fallback"

        saved = {}

        def save_translation(*args, **kwargs):
            saved.update(kwargs)
            saved["response_id"] = args[6]
            return dict(saved)

        state.call_translation_api = call_translation
        state.save_translation_result = save_translation
        result = state.translate_page({
            "source_id": "paper",
            "page": 2,
            "force": True,
            "model": "gpt-5.6-sol",
            "reasoning_effort": "xhigh",
        })

        assert len(calls) == 2
        full_prompt, compact_prompt = calls[0]["prompt"], calls[1]["prompt"]
        assert "FULL WORKFLOW CONTEXT" in full_prompt
        assert "PREVIOUS PAGE CONTEXT" in full_prompt
        assert "NEXT PAGE CONTEXT" in full_prompt
        assert "unused-context-term" in full_prompt
        assert "Current page explains self-attention." in compact_prompt
        assert "\x01" in full_prompt and "\x02" in full_prompt
        assert "\x01" not in compact_prompt and "\x02" not in compact_prompt
        assert "自注意力" in compact_prompt
        assert "FULL WORKFLOW CONTEXT" not in compact_prompt
        assert "PREVIOUS PAGE CONTEXT" not in compact_prompt
        assert "NEXT PAGE CONTEXT" not in compact_prompt
        assert "unused-context-term" not in compact_prompt
        assert len(compact_prompt.encode("utf-8")) < len(full_prompt.encode("utf-8"))
        assert all(call["model"] == "gpt-5.6-sol" for call in calls)
        assert all(call["reasoning_effort"] == "xhigh" for call in calls)
        assert all(call["include_image"] is True for call in calls)
        assert result["translation_fallback"] == reader_server.RETRANSLATION_FALLBACK_MODE
        assert result["response_id"] == "resp-fallback"

        calls.clear()

        def reject_request(prompt, context, **kwargs):
            calls.append({"prompt": prompt, **kwargs})
            raise reader_server.ApiError(400, "invalid request")

        state.call_translation_api = reject_request
        try:
            state.translate_page({"source_id": "paper", "page": 2, "force": True})
            raise AssertionError("non-retryable retranslation error was swallowed")
        except reader_server.ApiError as error:
            assert error.status == 400
        assert len(calls) == 1


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request(url: str, method: str = "GET", value=None, token: str | None = None, timeout: float = 30):
    data = None if value is None else json.dumps(value, ensure_ascii=False).encode("utf-8")
    headers = {"Origin": url.split("/", 3)[0] + "//" + url.split("/", 3)[2]}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-Reader-Token"] = token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def wait(url: str) -> None:
    for _ in range(100):
        try:
            request(url)
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("server did not start")


def run() -> None:
    check_translation_api_key_policy()
    check_codex_error_messages()
    check_full_translation_terminal_state()
    check_retranslation_compact_fallback()
    site_database = READER_DIR / "user-data" / TASK_ID / "site.sqlite3"
    site_store = reader_server.SiteStore(site_database, READER_DIR.parent)
    manifest = site_store.load_json("context-manifest.json", {})
    document_id = "papers/arxiv-1706.03762.md"
    document = manifest["documents"][document_id]
    block_id, block_text = next(
        (key, text) for key, text in document["blocks"].items() if "Transformer 的关键" in text
    )
    selected = "Transformer 的关键"
    start = block_text.index(selected)

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        log = root / "codex.jsonl"
        responses_log = root / "responses.jsonl"
        delayed_codex_ready = root / "delayed-codex-ready"
        port = free_port()
        responses_port = free_port()
        origin = f"http://127.0.0.1:{port}"
        env = os.environ.copy()
        env.update(
            {
                "CODEX_BIN": str(READER_DIR / "tests" / "fake_codex.py"),
                "FAKE_CODEX_LOG": str(log),
                "FAKE_CODEX_DELAY_QUESTION": "并发阅读检查",
                "FAKE_CODEX_DELAY_SECONDS": "2",
                "FAKE_CODEX_READY_FILE": str(delayed_codex_ready),
                "FAKE_RESPONSES_LOG": str(responses_log),
                "READER_USER_DATA_DIR": str(root / "user-data"),
                "READER_SITE_DATABASE": str(site_database),
                "READER_TRANSLATION_API_URL": f"http://127.0.0.1:{responses_port}/v1/responses",
                "READER_TRANSLATION_API_KEY": "test-translation-key",
                "READER_TRANSLATION_MODEL": "gpt-5.6-terra",
            }
        )
        responses_server = subprocess.Popen(
            [sys.executable, str(READER_DIR / "tests" / "fake_responses.py"), "--port", str(responses_port)],
            cwd=READER_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        server = subprocess.Popen(
            [sys.executable, str(READER_DIR / "server.py"), "--task-id", TASK_ID, "--port", str(port)],
            cwd=READER_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait(f"http://127.0.0.1:{responses_port}/health")
            wait(f"{origin}/api/bootstrap")
            bootstrap = request(f"{origin}/api/bootstrap")
            token = bootstrap["token"]
            knowledge_settings = request(
                f"{origin}/api/chat/settings",
                "POST",
                {
                    "document_id": document_id,
                    "model": "gpt-5.6-terra",
                    "effort": "ultra",
                },
                token,
            )
            assert knowledge_settings["model"] == "gpt-5.6-terra"
            assert knowledge_settings["effort"] == "ultra"
            try:
                request(
                    f"{origin}/api/chat/settings",
                    "POST",
                    {
                        "document_id": document_id,
                        "model": "gpt-5.6-unknown",
                        "effort": "ultra",
                    },
                    token,
                )
                raise AssertionError("invalid knowledge model accepted")
            except urllib.error.HTTPError as error:
                assert error.code == 400
            payload = {
                "document_id": document_id,
                "document_sha256": document["sha256"],
                "question": "解释这个设计转折",
                "contexts": [
                    {
                        "block_id": block_id,
                        "start": start,
                        "end": start + len(selected),
                        "text": selected,
                    }
                ],
                "pdf_contexts": [
                    {"source_id": "arxiv-1706.03762v7", "page": 3},
                    {"source_id": "arxiv-1706.03762v7", "page": 4},
                ],
            }
            first = request(f"{origin}/api/ask", "POST", payload, token)
            assert first["session_id"] == "11111111-2222-4333-8444-555555555555"
            assert first["thread_id"] == first["active_thread_id"]
            assert first["knowledge_settings"]["model"] == "gpt-5.6-terra"
            assert first["knowledge_settings"]["effort"] == "ultra"
            assert first["messages"][0]["contexts"][0]["text"] == selected
            assert [item["page"] for item in first["messages"][0]["pdf_contexts"]] == [3, 4]
            payload["question"] = "继续解释"
            payload["model"] = "gpt-5.6-sol"
            payload["effort"] = "xhigh"
            continued = request(f"{origin}/api/ask", "POST", payload, token)
            assert continued["knowledge_settings"]["model"] == "gpt-5.6-sol"
            assert continued["knowledge_settings"]["effort"] == "xhigh"

            state = request(f"{origin}/api/state?document_id={urllib.parse.quote(document_id)}")
            assert len([message for message in state["messages"] if message["role"] in {"user", "assistant"}]) == 4
            assert state["session"]["session_id"] == first["session_id"]
            assert state["active_thread_id"] == first["thread_id"]
            assert len(state["threads"]) == 1
            assert state["threads"][0]["message_count"] == 4
            assert state["knowledge_settings"]["model"] == "gpt-5.6-sol"
            assert state["knowledge_settings"]["effort"] == "xhigh"

            archived = request(
                f"{origin}/api/chat/archive",
                "POST",
                {"document_id": document_id, "thread_id": first["thread_id"]},
                token,
            )
            assert archived["active_thread_id"] is None
            assert archived["thread"]["status"] == "archived"
            assert len([message for message in archived["messages"] if message["role"] in {"user", "assistant"}]) == 4
            archived_payload = {**payload, "thread_id": first["thread_id"], "question": "不应继续"}
            try:
                request(f"{origin}/api/ask", "POST", archived_payload, token)
                raise AssertionError("archived thread accepted a new question")
            except urllib.error.HTTPError as error:
                assert error.code == 409

            created = request(
                f"{origin}/api/chat/new",
                "POST",
                {"document_id": document_id},
                token,
            )
            assert created["active_thread_id"] != first["thread_id"]
            assert created["messages"] == []
            assert len(created["threads"]) == 2
            new_payload = {
                **payload,
                "thread_id": created["active_thread_id"],
                "question": "这是新的独立对话",
                "pdf_contexts": [],
            }
            third = request(f"{origin}/api/ask", "POST", new_payload, token)
            assert third["thread_id"] == created["active_thread_id"]

            # A slow question must serialize only its own Codex thread. PDF
            # translation status and page cache reads stay responsive.
            delayed_result = {}
            delayed_errors = []

            def ask_slowly() -> None:
                try:
                    delayed_result.update(request(
                        f"{origin}/api/ask",
                        "POST",
                        {**new_payload, "question": "并发阅读检查"},
                        token,
                    ))
                except Exception as error:  # pragma: no cover - assertion reports the captured failure
                    delayed_errors.append(error)

            delayed_thread = threading.Thread(target=ask_slowly, daemon=True)
            delayed_thread.start()
            deadline = time.monotonic() + 3
            while not delayed_codex_ready.is_file() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert delayed_codex_ready.is_file(), "slow Codex request did not start"
            started = time.monotonic()
            concurrent_full_state = request(
                f"{origin}/api/translation/full?source_id=arxiv-1706.03762v7",
                timeout=1,
            )
            concurrent_page_state = request(
                f"{origin}/api/translation/page?source_id=arxiv-1706.03762v7&page=3",
                timeout=1,
            )
            assert time.monotonic() - started < 1
            assert concurrent_full_state["source_id"] == "arxiv-1706.03762v7"
            assert concurrent_page_state["page"] == 3
            delayed_thread.join(timeout=5)
            assert not delayed_thread.is_alive()
            assert not delayed_errors, delayed_errors
            assert delayed_result["thread_id"] == created["active_thread_id"]

            old_state = request(
                f"{origin}/api/state?document_id={urllib.parse.quote(document_id)}&thread_id={first['thread_id']}"
            )
            assert old_state["selected_thread_id"] == first["thread_id"]
            assert old_state["session"]["status"] == "archived"
            assert len([message for message in old_state["messages"] if message["role"] in {"user", "assistant"}]) == 4

            translation_state = request(
                f"{origin}/api/translation/page?source_id=arxiv-1706.03762v7&page=3"
            )
            assert translation_state["translation"] is None
            translated = request(
                f"{origin}/api/translation/page",
                "POST",
                {"source_id": "arxiv-1706.03762v7", "page": 3},
                token,
            )
            assert "自注意力" in translated["translation"]
            assert "h→_t" in translated["translation"]
            assert "⃗" not in translated["translation"]
            assert translated["protocol_version"] == "paper-reader-translation-v1"
            assert [block["id"] for block in translated["blocks"]] == ["p0003-f001", "p0003-t001"]
            assert translated["blocks"][0]["physical_page"] == 3
            assert translated["blocks"][0]["figure_data"]["flow_steps"][1].startswith("编码器表示")
            assert translated["blocks"][1]["table_data"]["headers"] == ["模型", "质量"]
            assert "h→_t" in translated["blocks"][1]["translation"]
            assert translated["visual_input"] is True
            assert translated["source_text"].startswith("Figure 1: The Transformer")
            cached = request(
                f"{origin}/api/translation/page",
                "POST",
                {"source_id": "arxiv-1706.03762v7", "page": 3},
                token,
            )
            assert cached["translated_at"] == translated["translated_at"]
            retranslated = request(
                f"{origin}/api/translation/page",
                "POST",
                {
                    "source_id": "arxiv-1706.03762v7",
                    "page": 3,
                    "force": True,
                    "model": "gpt-5.6-terra",
                    "reasoning_effort": "ultra",
                },
                token,
            )
            assert retranslated["translation_model"] == "gpt-5.6-terra"
            assert retranslated["translation_reasoning_effort"] == "ultra"
            try:
                request(
                    f"{origin}/api/translation/page",
                    "POST",
                    {
                        "source_id": "arxiv-1706.03762v7",
                        "page": 3,
                        "force": True,
                        "model": "gpt-5.6-unknown",
                        "reasoning_effort": "ultra",
                    },
                    token,
                )
                raise AssertionError("invalid retranslation model accepted")
            except urllib.error.HTTPError as error:
                assert error.code == 400
            translated_next = request(
                f"{origin}/api/translation/page",
                "POST",
                {
                    "source_id": "arxiv-1706.03762v7",
                    "page": 4,
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": "high",
                },
                token,
            )
            assert translated_next["page"] == 4
            assert translated_next["translation_model"] == "gpt-5.6-sol"
            assert translated_next["translation_reasoning_effort"] == "high"
            source_map_state = request(
                f"{origin}/api/translation/source-map?source_id=arxiv-1706.03762v7"
            )
            assert source_map_state["source_map_version"] == "paper-reader-source-map-v1"
            assert [page["physical_page"] for page in source_map_state["pages"]] == [3, 4]

            # A v1 page cache created before block output remains readable and
            # is exposed as a deterministic page-level fallback block.
            legacy_state = request(
                f"{origin}/api/translation/page?source_id=arxiv-1706.03762v7&page=6"
            )
            legacy_path = (
                root / "user-data" / TASK_ID / "translations" / "arxiv-1706.03762v7" / "pages" / "0006.json"
            )
            legacy_path.parent.mkdir(parents=True, exist_ok=True)
            legacy_path.write_text(
                json.dumps({
                    "source_id": "arxiv-1706.03762v7",
                    "page": 6,
                    "pdf_sha256": legacy_state["metadata"]["pdf_sha256"],
                    "source_text_sha256": hashlib.sha256(legacy_state["source_text"].encode()).hexdigest(),
                    "protocol_version": "paper-reader-translation-v1",
                    "source_text": legacy_state["source_text"],
                    "translation": "旧版页面译文",
                    "glossary_updates": [],
                    "warnings": [],
                    "translated_at": "2026-07-20T00:00:00+08:00",
                    "session_id": "legacy-translation-session",
                    "visual_input": True,
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            normalized_legacy = request(
                f"{origin}/api/translation/page?source_id=arxiv-1706.03762v7&page=6"
            )
            assert normalized_legacy["translation"]["translation"] == "旧版页面译文"
            assert normalized_legacy["translation"]["blocks"][0]["id"] == "p0006-b001"
            translated_bulk = request(
                f"{origin}/api/translation/page",
                "POST",
                {"source_id": "arxiv-1706.03762v7", "page": 5, "bulk": True},
                token,
            )
            assert translated_bulk["page"] == 5
            translation_store = reader_server.TranslationStore(
                root / "user-data" / TASK_ID / "translations.sqlite3"
            )
            stored_pages = translation_store.list_keys("arxiv-1706.03762v7/pages")
            assert len(stored_pages) == 3 and legacy_path.is_file()
            translation_manifest = translation_store.load_json(
                "arxiv-1706.03762v7/manifest.json", {}
            )
            assert "session_id" not in translation_manifest
            assert translation_manifest["translation_backend"] == "responses-api"
            assert translation_manifest["translation_model"] == "gpt-5.6-terra"
            assert translation_manifest["source_map_path"] == "source-map.json"
            source_map = translation_store.load_json(
                "arxiv-1706.03762v7/source-map.json", {}
            )
            assert source_map["protocol_version"] == "paper-reader-translation-v1"
            assert [page["physical_page"] for page in source_map["pages"]] == [3, 4, 5]
            assert source_map["pages"][0]["blocks"][0]["id"] == "p0003-f001"
            glossary = translation_store.load_json(
                "arxiv-1706.03762v7/glossary.json", {}
            )
            assert glossary["terms"]["self-attention"]["translation"] == "自注意力"

            saved = request(
                f"{origin}/api/faq/save-message",
                "POST",
                {
                    "document_id": document_id,
                    "message_id": first["messages"][1]["id"],
                    "question": "为什么训练并行不等于生成并行？",
                    "answer": "训练时目标已知，但自回归生成依赖前一个 token。",
                    "note": "复习生成阶段的数据依赖。",
                },
                token,
            )
            assert saved["items"][0]["question"].startswith("为什么")
            assert [item["page"] for item in saved["items"][0]["evidence"]] == [3, 4]
            faq_id = saved["items"][0]["id"]
            edited = request(
                f"{origin}/api/faq/edit",
                "POST",
                {
                    "document_id": document_id,
                    "faq_id": faq_id,
                    "question": "训练并行和生成串行的差异是什么？",
                    "answer": "训练目标序列已知；自回归生成必须等待前一个 token。",
                    "note": "重点复习生成阶段的数据依赖。",
                },
                token,
            )
            assert edited["items"][0]["note"].startswith("重点复习")
            state_after_edit = request(
                f"{origin}/api/state?document_id={urllib.parse.quote(document_id)}"
            )
            assert state_after_edit["faq"]["items"][0]["question"].startswith("训练并行")
            runtime_store = reader_server.RuntimeStore(
                root / "user-data" / TASK_ID / "state.sqlite3"
            )
            faq_markdown_key = f"faq/{hashlib.sha256(document_id.encode()).hexdigest()[:20]}.md"
            assert "重点复习" in runtime_store.read_text(faq_markdown_key, "")

            deleted = request(
                f"{origin}/api/faq/delete",
                "POST",
                {"document_id": document_id, "faq_id": faq_id},
                token,
            )
            assert deleted["items"] == []
            assert "训练并行" not in runtime_store.read_text(faq_markdown_key, "")
            history = runtime_store.read_text("faq-history.jsonl", "")
            assert '"action": "save_message"' in history
            assert '"action": "edit"' in history
            assert '"action": "delete"' in history and faq_id in history
            try:
                request(
                    f"{origin}/api/faq/delete",
                    "POST",
                    {"document_id": document_id, "faq_id": faq_id},
                    token,
                )
                raise AssertionError("already deleted FAQ was deleted twice")
            except urllib.error.HTTPError as error:
                assert error.code == 404

            deleted_thread = request(
                f"{origin}/api/chat/delete",
                "POST",
                {"document_id": document_id, "thread_id": first["thread_id"]},
                token,
            )
            assert all(thread["id"] != first["thread_id"] for thread in deleted_thread["threads"])
            try:
                request(
                    f"{origin}/api/state?document_id={urllib.parse.quote(document_id)}&thread_id={first['thread_id']}"
                )
                raise AssertionError("deleted thread remained addressable")
            except urllib.error.HTTPError as error:
                assert error.code == 404

            calls = [json.loads(line) for line in log.read_text().splitlines()]
            assert "resume" not in calls[0]["args"]
            assert not any(
                "mcp_servers.openaiDeveloperDocs" in argument
                for call in calls
                for argument in call["args"]
            )
            assert selected in calls[0]["prompt"]
            assert "Figure 1: The Transformer" not in calls[0]["prompt"]
            assert "Attention Is All You Need" in calls[0]["prompt"]
            assert "arxiv-1706.03762v7" in calls[0]["prompt"]
            assert "bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697" in calls[0]["prompt"]
            assert '"attached_physical_page": 3' in calls[0]["prompt"]
            assert '"attached_physical_page": 4' in calls[0]["prompt"]
            assert len(calls[0]["images"]) == 2
            assert all(image["exists"] for image in calls[0]["images"])
            assert all(image["png_signature"] == "89504e470d0a1a0a" for image in calls[0]["images"])
            assert all(image["size"] > 10_000 for image in calls[0]["images"])
            assert "--image" in calls[0]["args"]
            assert all(not Path(image["path"]).exists() for image in calls[0]["images"])
            assert any("resume" in call["args"] for call in calls[1:])
            assert "--image" in calls[1]["args"]
            assert [call["args"][call["args"].index("-m") + 1] for call in calls] == [
                "gpt-5.6-terra",
                "gpt-5.6-sol",
                "gpt-5.6-sol",
                "gpt-5.6-sol",
            ]
            expected_efforts = ["ultra", "xhigh", "xhigh", "xhigh"]
            assert all(
                f'model_reasoning_effort="{effort}"' in call["args"]
                for call, effort in zip(calls, expected_efforts, strict=True)
            )
            assert not any("translation-page.schema.json" in " ".join(call["args"]) for call in calls)
            responses_calls = [json.loads(line) for line in responses_log.read_text().splitlines()]
            assert len(responses_calls) == 4
            assert all(call["authorized"] for call in responses_calls)
            assert [call["model"] for call in responses_calls] == [
                "gpt-5.6-terra",
                "gpt-5.6-terra",
                "gpt-5.6-sol",
                "gpt-5.6-terra",
            ]
            assert [call["reasoning"] for call in responses_calls] == [
                {"effort": reader_server.DEFAULT_TRANSLATION_REASONING_EFFORT},
                {"effort": "ultra"},
                {"effort": "high"},
                {"effort": reader_server.DEFAULT_TRANSLATION_REASONING_EFFORT},
            ]
            assert all(call["store"] is False for call in responses_calls)
            assert all(call["text"]["format"]["type"] == "json_schema" for call in responses_calls)
            assert all(call["text"]["format"]["strict"] is True for call in responses_calls)
            assert "<current_page_text>" in responses_calls[0]["prompt"]
            assert "第二遍视觉校准" in responses_calls[0]["prompt"]
            assert "禁止输出 U+20D0-U+20FF" in responses_calls[0]["prompt"]
            assert "Figure 1: The Transformer" in responses_calls[0]["prompt"]
            assert responses_calls[0]["image_detail"] == "high"
            assert responses_calls[0]["image_signature"] == "89504e470d0a1a0a"
            assert responses_calls[0]["image_size"] > 10_000

            bad = dict(payload)
            bad["contexts"] = [{"block_id": block_id, "start": start, "end": start + 3, "text": "伪造"}]
            try:
                request(f"{origin}/api/ask", "POST", bad, token)
                raise AssertionError("forged context was accepted")
            except urllib.error.HTTPError as error:
                assert error.code == 400

            bad_page = dict(payload)
            bad_page["contexts"] = []
            bad_page["pdf_contexts"] = [{"source_id": "arxiv-1706.03762v7", "page": 16}]
            try:
                request(f"{origin}/api/ask", "POST", bad_page, token)
                raise AssertionError("out-of-range PDF page was accepted")
            except urllib.error.HTTPError as error:
                assert error.code == 400
        finally:
            server.terminate()
            responses_server.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                server.wait(timeout=5)
            with contextlib.suppress(subprocess.TimeoutExpired):
                responses_server.wait(timeout=5)
            if server.poll() is None:
                server.kill()
            if responses_server.poll() is None:
                responses_server.kill()


if __name__ == "__main__":
    run()
    print("Knowledge API persistence checks passed")
