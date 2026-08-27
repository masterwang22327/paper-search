#!/usr/bin/env python3
"""Regression checks for compact Reader storage."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path


READER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(READER_DIR))

import server as reader_server
import build_site as reader_build
from site_store import SiteStore, build_site_database, parse_range
from runtime_store import RuntimeStore
from task_store import TaskArtifactStore
from translation_store import TranslationStore


def check_translation_store() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        legacy = root / "translations"
        page = legacy / "source-a" / "pages" / "0001.json"
        page.parent.mkdir(parents=True)
        page.write_text(json.dumps({"page": 1, "translation": "译文"}), encoding="utf-8")
        history = legacy / "source-a" / "history.jsonl"
        history.write_text('{"action":"translate"}\n', encoding="utf-8")
        original = {
            path.relative_to(legacy).as_posix(): path.read_bytes()
            for path in legacy.rglob("*")
            if path.is_file()
        }

        store = TranslationStore(root / "translations.sqlite3")
        assert store.compact_tree(legacy) == 2
        assert not legacy.exists()
        assert store.file_count() == 2
        assert store.load_json("source-a/pages/0001.json", {})["translation"] == "译文"
        store.append_jsonl("source-a/history.jsonl", {"action": "retry"})

        restored = root / "restored"
        assert store.restore_tree(restored) == 2
        assert (restored / "source-a" / "pages" / "0001.json").read_bytes() == original[
            "source-a/pages/0001.json"
        ]
        assert '"action": "retry"' in (restored / "source-a" / "history.jsonl").read_text()

        try:
            store.write_bytes("../escape", b"bad")
            raise AssertionError("unsafe translation path accepted")
        except ValueError:
            pass

        with sqlite3.connect(store.database) as connection:
            connection.execute(
                "UPDATE metadata SET value = '999' WHERE key = 'schema_version'"
            )
        try:
            TranslationStore(store.database)
            raise AssertionError("unsupported translation schema accepted")
        except RuntimeError:
            pass


def check_legacy_history_migration() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        legacy = root / "translations" / "source-a"
        legacy.mkdir(parents=True)
        history = legacy / "history.jsonl"
        history.write_text('{"action":"old"}\n', encoding="utf-8")

        state = reader_server.ReaderState.__new__(reader_server.ReaderState)
        state.user_dir = root
        state.translation_store = TranslationStore(root / "translations.sqlite3")
        state.translation_dir = lambda source_id: root / "translations" / source_id
        state.append_translation_history("source-a", {"action": "new"})

        restored = root / "restored"
        state.translation_store.restore_tree(restored)
        lines = (restored / "source-a" / "history.jsonl").read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["action"] for line in lines] == ["old", "new"]


def check_runtime_store() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        user_dir = root / "user-data" / "task-a"
        chat = user_dir / "chats" / "doc-a.jsonl"
        chat.parent.mkdir(parents=True)
        chat.write_text('{"role":"user","content":"old"}\n', encoding="utf-8")
        (user_dir / "sessions.json").write_text('{"doc-a":{}}', encoding="utf-8")
        (user_dir / "server.log").write_text("preserved log\n", encoding="utf-8")
        temporary_image = user_dir / "tmp-old" / "page.png"
        temporary_image.parent.mkdir()
        temporary_image.write_bytes(b"\x89PNG\r\n\x1a\nold")
        legacy_translation = user_dir / "translations" / "source-a" / "manifest.json"
        legacy_translation.parent.mkdir(parents=True)
        legacy_translation.write_text('{"source_id":"source-a"}', encoding="utf-8")
        (user_dir / "site.sqlite3").write_bytes(b"site database placeholder")

        store = RuntimeStore(user_dir / "state.sqlite3")
        assert store.compact_legacy(user_dir) == 4
        assert store.file_count() == 4
        assert not chat.exists()
        assert not (user_dir / "chats").exists()
        assert legacy_translation.is_file()
        assert (user_dir / "site.sqlite3").is_file()
        assert store.load_json("sessions.json", {}) == {"doc-a": {}}
        assert store.read_text("server.log") == "preserved log\n"

        store.append_jsonl("chats/doc-a.jsonl", {"role": "assistant", "content": "new"})
        restored = root / "restored"
        assert store.restore_legacy(restored) == 4
        messages = [
            json.loads(line)
            for line in (restored / "chats" / "doc-a.jsonl").read_text().splitlines()
        ]
        assert [message["content"] for message in messages] == ["old", "new"]
        assert (restored / "tmp-old" / "page.png").read_bytes().startswith(b"\x89PNG")


def check_runtime_state_helpers() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        state = reader_server.ReaderState.__new__(reader_server.ReaderState)
        state.user_dir = root
        state.runtime_store = RuntimeStore(root / "state.sqlite3")
        path = root / "faq" / "doc-a.json"
        state.save_runtime_json(path, {"items": [{"id": "one"}]})
        assert not path.exists()
        assert state.load_runtime_json(path, {})["items"][0]["id"] == "one"
        history = root / "faq-history.jsonl"
        state.append_runtime_jsonl(history, {"action": "save"})
        assert not history.exists()
        assert '"action": "save"' in state.read_runtime_text(history)
        assert state.delete_runtime(path)
        assert not state.runtime_exists(path)


def check_reading_progress() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        task = root / "tasks" / "task-a"
        (task / "papers").mkdir(parents=True)
        (task / "papers" / "paper.md").write_text("# Paper\n\n正文\n", encoding="utf-8")
        source = task / "sources" / "source-a"
        source.mkdir(parents=True)
        (source / "paper.pdf").write_bytes(b"%PDF-1.7\nplaceholder\n")

        state = reader_server.ReaderState.__new__(reader_server.ReaderState)
        state.task_dir = task
        state.user_dir = root / "user-data"
        state.user_dir.mkdir()
        state.runtime_store = RuntimeStore(state.user_dir / "state.sqlite3")
        state.site_manifest = {
            "documents": {
                "papers/paper.md": {
                    "sha256": "document-sha-a",
                    "blocks": {"b00001": "正文"},
                }
            }
        }
        state.lock = threading.RLock()
        state.source_metadata = lambda source_id: {
            "source_id": source_id,
            "pdf_sha256": "pdf-sha-a",
            "page_count": 3,
        }

        initial = state.get_reading_progress(document_id="papers/paper.md")
        assert initial["checkpoint"] is None
        assert initial["resume_position"] is None
        assert initial["note"] is None

        position = {
            "block_id": "b00001",
            "heading_id": "method",
            "heading_title": "方法",
            "section_index": 1,
            "offset_ratio": 0.4,
            "scroll_ratio": 0.52,
            "text_hint": "正文",
        }
        saved = state.save_reading_progress({
            "kind": "document",
            "action": "checkpoint",
            "document_id": "papers/paper.md",
            "document_sha256": "document-sha-a",
            "position": position,
        })
        assert saved["checkpoint"]["block_id"] == "b00001"
        assert saved["checkpoint"]["offset_ratio"] == 0.4
        assert saved["checkpoint"]["updated_at"]
        assert saved["resume_position"]["scroll_ratio"] == 0.52

        furthest = state.save_reading_progress({
            "kind": "document",
            "action": "checkpoint",
            "document_id": "papers/paper.md",
            "document_sha256": "document-sha-a",
            "position": {**position, "scroll_ratio": 0.72, "offset_ratio": 0.2},
        })
        furthest_timestamp = furthest["checkpoint"]["updated_at"]
        assert furthest["checkpoint"]["scroll_ratio"] == 0.72

        after_backtrack = state.save_reading_progress({
            "kind": "document",
            "action": "checkpoint",
            "document_id": "papers/paper.md",
            "document_sha256": "document-sha-a",
            "position": {**position, "scroll_ratio": 0.31, "offset_ratio": 0.9},
        })
        assert after_backtrack["checkpoint"]["scroll_ratio"] == 0.72
        assert after_backtrack["checkpoint"]["updated_at"] == furthest_timestamp

        manually_positioned = state.save_reading_progress({
            "kind": "document",
            "action": "set_position",
            "document_id": "papers/paper.md",
            "document_sha256": "document-sha-a",
            "position": {**position, "scroll_ratio": 0.31, "offset_ratio": 0.9},
        })
        assert manually_positioned["checkpoint"]["scroll_ratio"] == 0.72
        assert manually_positioned["resume_position"]["scroll_ratio"] == 0.31

        noted = state.save_reading_progress({
            "kind": "document",
            "action": "note",
            "document_id": "papers/paper.md",
            "document_sha256": "document-sha-a",
            "text": "这里需要回看定义。",
            "position": position,
        })
        assert noted["note"]["text"] == "这里需要回看定义。"
        assert noted["note"]["position"]["heading_id"] == "method"

        deleted = state.save_reading_progress({
            "kind": "document",
            "action": "delete_note",
            "document_id": "papers/paper.md",
            "document_sha256": "document-sha-a",
        })
        assert deleted["note"] is None

        try:
            state.save_reading_progress({
                "kind": "document",
                "action": "checkpoint",
                "document_id": "papers/paper.md",
                "document_sha256": "document-sha-a",
                "position": {**position, "block_id": "missing"},
            })
            raise AssertionError("invalid reading block accepted")
        except reader_server.ApiError as error:
            assert error.status == 400

        try:
            state.save_reading_progress({
                "kind": "document",
                "action": "checkpoint",
                "document_id": "papers/paper.md",
                "document_sha256": "old-sha",
                "position": position,
            })
            raise AssertionError("stale document checkpoint accepted")
        except reader_server.ApiError as error:
            assert error.status == 409

def check_task_artifact_store() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        task = Path(temporary) / "tasks" / "task-a"
        source = task / "sources" / "source-a"
        source.mkdir(parents=True)
        pdf = source / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.7\ncanonical\n")
        evidence = source / "evidence.md"
        evidence.write_text("# Source A Evidence\n", encoding="utf-8")
        metadata = source / "arxiv-api.xml"
        metadata.write_text("<feed><title>Source A</title></feed>\n", encoding="utf-8")
        repository_file = source / "repository" / "README.md"
        repository_file.parent.mkdir()
        repository_file.write_text("repository snapshot\n", encoding="utf-8")

        assert TaskArtifactStore.open_existing(task) is None
        store = TaskArtifactStore(task)
        assert store.compact_sources() == 3
        assert TaskArtifactStore.open_existing(task) is not None
        assert store.file_count() == 3
        assert pdf.is_file()
        assert source.is_dir()
        assert not evidence.exists()
        assert not repository_file.parent.exists()
        assert store.read_path_text(evidence) == "# Source A Evidence\n"
        inventory = store.source_inventory("source-a")
        assert [item.path for item in inventory] == [
            "arxiv-api.xml",
            "evidence.md",
            "paper.pdf",
            "repository/README.md",
        ]
        assert store.verify_database() == 3

        assert store.restore_sources() == 3
        assert evidence.read_text() == "# Source A Evidence\n"
        evidence.write_text("# Updated Evidence\n", encoding="utf-8")
        try:
            store.compact_sources()
            raise AssertionError("conflicting task artifact replacement was accepted")
        except ValueError:
            pass
        assert evidence.is_file()
        assert store.compact_sources(replace=True) == 3
        assert store.read_path_text(evidence) == "# Updated Evidence\n"

        current_run = "run-20260817t120000-aaaaaaaa"
        old_run = "run-20260816t120000-bbbbbbbb"
        state_dir = task / "state"
        (state_dir / "handoffs").mkdir(parents=True)
        (state_dir / "handoffs" / "audit.md").write_text("historical handoff\n")
        (state_dir / "work").mkdir()
        (state_dir / "work" / "scratch.txt").write_text("completed work\n")
        (state_dir / "current-run.json").write_text(
            json.dumps({"run_id": current_run}), encoding="utf-8"
        )
        old_run_dir = state_dir / "runs" / old_run
        old_run_dir.mkdir(parents=True)
        (old_run_dir / "runtime.json").write_text(
            json.dumps({"run_id": old_run}), encoding="utf-8"
        )
        (old_run_dir / "events.jsonl").write_text('{"event":"closed"}\n')
        current_run_dir = state_dir / "runs" / current_run
        current_run_dir.mkdir()
        (current_run_dir / "runtime.json").write_text(
            json.dumps({"run_id": current_run}), encoding="utf-8"
        )

        assert store.compact_state_history() == 4
        assert not old_run_dir.exists()
        assert current_run_dir.is_dir()
        assert (current_run_dir / "runtime.json").is_file()
        assert (state_dir / "handoffs").is_dir()
        assert not (state_dir / "handoffs" / "audit.md").exists()
        assert store.contains(f"state/runs/{old_run}/runtime.json")
        assert store.restore_artifacts() == 7
        assert (old_run_dir / "events.jsonl").is_file()
        assert (state_dir / "handoffs" / "audit.md").read_text() == "historical handoff\n"


def check_site_store() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        repo = Path(temporary) / "repo"
        task_id = "task-a"
        canonical = repo / "tasks" / task_id / "sources" / "source-a" / "paper.pdf"
        canonical.parent.mkdir(parents=True)
        canonical.write_bytes(b"%PDF-1.7\ncanonical-pdf\n")
        supplement = canonical.parent / "appendices" / "supplement.pdf"
        supplement.parent.mkdir()
        supplement.write_bytes(b"%PDF-1.7\nsupplement\n")

        generated = repo / "reader" / "site"
        generated.mkdir(parents=True)
        (generated / "index.html").write_text("<h1>Reader</h1>", encoding="utf-8")
        (generated / "assets").mkdir()
        (generated / "assets" / "app.js").write_text("reader();\n" * 200, encoding="utf-8")

        database = repo / "reader" / "user-data" / task_id / "site.sqlite3"
        assert build_site_database(
            generated, database, repo, task_id, input_fingerprint="fingerprint-a"
        ) == 4
        assert database.is_file()
        assert not database.with_name(database.name + "-journal").exists()

        store = SiteStore(database, repo)
        assert store.file_count() == 4
        assert store.quick_check()
        assert store.metadata("input_fingerprint") == "fingerprint-a"
        assert store.verify() == 4
        assert store.read_bytes("index.html") == b"<h1>Reader</h1>"
        assert store.entry("assets/app.js").compression == "zlib"
        assert store.entry("sources/source-a/paper.pdf").read_bytes() == canonical.read_bytes()
        assert (
            store.entry("sources/source-a/appendices-supplement.pdf").read_bytes()
            == supplement.read_bytes()
        )
        assert store.request_entry("/").path == "index.html"
        assert store.request_entry("/../escape") is None
        assert parse_range("bytes=2-5", 10) == (2, 5)
        assert parse_range("bytes=-3", 10) == (7, 9)


def check_site_fingerprint() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        repo = Path(temporary) / "repo"
        reader_dir = repo / "reader"
        task = repo / "tasks" / "task-a"
        (reader_dir / "content").mkdir(parents=True)
        (reader_dir / "content" / "index.md").write_text("# Reader\n")
        (reader_dir / "mkdocs.yml").write_text("site_name: Reader\n")
        (task / "papers").mkdir(parents=True)
        (task / "papers" / "paper.md").write_text("# Paper\n")
        (task / "sources" / "source-a").mkdir(parents=True)
        (task / "sources" / "source-a" / "paper.pdf").write_bytes(b"%PDF-test\n")
        (task / "REPORT.md").write_text("# Report\n")

        previous_repo = reader_build.REPO_DIR
        previous_reader = reader_build.READER_DIR
        reader_build.REPO_DIR = repo
        reader_build.READER_DIR = reader_dir
        try:
            fingerprint = reader_build.site_input_fingerprint("task-a")
            generated = repo / "generated"
            generated.mkdir()
            (generated / "index.html").write_text("<h1>Reader</h1>")
            database = repo / "site.sqlite3"
            build_site_database(
                generated,
                database,
                repo,
                "task-a",
                input_fingerprint=fingerprint,
            )
            assert reader_build.site_database_is_current("task-a", database)
            (task / "REPORT.md").write_text("# Changed report\n")
            assert not reader_build.site_database_is_current("task-a", database)
        finally:
            reader_build.REPO_DIR = previous_repo
            reader_build.READER_DIR = previous_reader


def main() -> None:
    check_translation_store()
    check_legacy_history_migration()
    check_runtime_store()
    check_runtime_state_helpers()
    check_reading_progress()
    check_task_artifact_store()
    check_site_store()
    check_site_fingerprint()
    print("Compact storage checks passed")


if __name__ == "__main__":
    main()
