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


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request(url: str, method: str = "GET", value=None, token: str | None = None):
    data = None if value is None else json.dumps(value, ensure_ascii=False).encode("utf-8")
    headers = {"Origin": url.split("/", 3)[0] + "//" + url.split("/", 3)[2]}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-Reader-Token"] = token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:
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
    manifest = json.loads((READER_DIR / "site" / "context-manifest.json").read_text())
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
        port = free_port()
        responses_port = free_port()
        origin = f"http://127.0.0.1:{port}"
        env = os.environ.copy()
        env.update(
            {
                "CODEX_BIN": str(READER_DIR / "tests" / "fake_codex.py"),
                "FAKE_CODEX_LOG": str(log),
                "FAKE_RESPONSES_LOG": str(responses_log),
                "READER_USER_DATA_DIR": str(root / "user-data"),
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
            assert first["messages"][0]["contexts"][0]["text"] == selected
            assert [item["page"] for item in first["messages"][0]["pdf_contexts"]] == [3, 4]
            payload["question"] = "继续解释"
            request(f"{origin}/api/ask", "POST", payload, token)

            state = request(f"{origin}/api/state?document_id={urllib.parse.quote(document_id)}")
            assert len([message for message in state["messages"] if message["role"] in {"user", "assistant"}]) == 4
            assert state["session"]["session_id"] == first["session_id"]
            assert state["active_thread_id"] == first["thread_id"]
            assert len(state["threads"]) == 1
            assert state["threads"][0]["message_count"] == 4

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
                {"source_id": "arxiv-1706.03762v7", "page": 3, "force": True},
                token,
            )
            assert retranslated["translation_model"] == reader_server.DEFAULT_RETRANSLATION_MODEL
            assert (
                retranslated["translation_reasoning_effort"]
                == reader_server.DEFAULT_RETRANSLATION_REASONING_EFFORT
            )
            translated_next = request(
                f"{origin}/api/translation/page",
                "POST",
                {"source_id": "arxiv-1706.03762v7", "page": 4},
                token,
            )
            assert translated_next["page"] == 4
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
            translation_files = list(
                (root / "user-data" / TASK_ID / "translations" / "arxiv-1706.03762v7" / "pages").glob("*.json")
            )
            assert len(translation_files) == 4
            translation_manifest = json.loads(
                (root / "user-data" / TASK_ID / "translations" / "arxiv-1706.03762v7" / "manifest.json").read_text()
            )
            assert "session_id" not in translation_manifest
            assert translation_manifest["translation_backend"] == "responses-api"
            assert translation_manifest["translation_model"] == "gpt-5.6-terra"
            assert translation_manifest["source_map_path"] == "source-map.json"
            source_map = json.loads(
                (root / "user-data" / TASK_ID / "translations" / "arxiv-1706.03762v7" / "source-map.json").read_text()
            )
            assert source_map["protocol_version"] == "paper-reader-translation-v1"
            assert [page["physical_page"] for page in source_map["pages"]] == [3, 4, 5]
            assert source_map["pages"][0]["blocks"][0]["id"] == "p0003-f001"
            glossary = json.loads(
                (root / "user-data" / TASK_ID / "translations" / "arxiv-1706.03762v7" / "glossary.json").read_text()
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
            markdown_files = list((root / "user-data" / TASK_ID / "faq").glob("*.md"))
            assert len(markdown_files) == 1 and "重点复习" in markdown_files[0].read_text()

            deleted = request(
                f"{origin}/api/faq/delete",
                "POST",
                {"document_id": document_id, "faq_id": faq_id},
                token,
            )
            assert deleted["items"] == []
            assert "训练并行" not in markdown_files[0].read_text()
            history = (root / "user-data" / TASK_ID / "faq-history.jsonl").read_text()
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

            calls = [json.loads(line) for line in log.read_text().splitlines()]
            assert "resume" not in calls[0]["args"]
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
            assert not any("translation-page.schema.json" in " ".join(call["args"]) for call in calls)
            responses_calls = [json.loads(line) for line in responses_log.read_text().splitlines()]
            assert len(responses_calls) == 4
            assert all(call["authorized"] for call in responses_calls)
            assert [call["model"] for call in responses_calls] == [
                "gpt-5.6-terra",
                "gpt-5.6-sol",
                "gpt-5.6-terra",
                "gpt-5.6-terra",
            ]
            assert [call["reasoning"] for call in responses_calls] == [
                {"effort": reader_server.DEFAULT_TRANSLATION_REASONING_EFFORT},
                {"effort": reader_server.DEFAULT_RETRANSLATION_REASONING_EFFORT},
                {"effort": reader_server.DEFAULT_TRANSLATION_REASONING_EFFORT},
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
