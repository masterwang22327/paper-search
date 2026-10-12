"""Check portable backup integrity, live SQLite state, and restore boundaries."""

import contextlib
from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tools import reader_backup as backup


class ReaderBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "source"
        self.codex = self.root / "codex"
        self.repo.mkdir()
        (self.repo / "tasks/example/papers").mkdir(parents=True)
        (self.repo / "tasks/example/papers/paper.md").write_text("# Research\n")
        (self.repo / "reader/user-data/example").mkdir(parents=True)
        self.database = self.repo / "reader/user-data/example/state.sqlite3"
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("CREATE TABLE files(path TEXT PRIMARY KEY, content BLOB)")
            connection.execute("INSERT INTO files VALUES ('sessions.json', ?)", (b'{}',))
        self.codex.mkdir()
        (self.codex / "config.toml").write_text(
            'model_provider = "custom"\nmodel = "example-model"\n'
            '[model_providers.custom]\nname = "Example"\n'
            'base_url = "https://example.com"\nwire_api = "responses"\n'
            'experimental_bearer_token = "sk-' + "x" * 40 + '"\n'
        )

    def make_snapshot(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return backup.snapshot(self.repo, self.root / "backup", self.codex)

    def restore(self, destination):
        with contextlib.redirect_stdout(io.StringIO()):
            return backup.restore_local(self.root / "backup", destination)

    def test_live_wal_records_and_metadata_survive_without_credentials(self):
        # The newest question is in a live WAL, rather than the main database file.
        with closing(sqlite3.connect(self.database)) as live, live:
            live.execute("PRAGMA journal_mode=WAL")
            live.execute("INSERT INTO files VALUES ('chats/question.jsonl', ?)",
                         ('{"role":"user","content":"历史问题"}'.encode(),))
            live.commit()
            self.assertTrue(Path(str(self.database) + "-wal").exists())
            (self.repo / ".env").write_text('MODELSCOPE_API_TOKEN="ms-' + "y" * 40 + '"')
            (self.repo / "reader/.venv").mkdir()
            (self.repo / "reader/.venv/ignored").write_text("local executable")
            original = self.repo / "tasks/example/papers/paper.md"
            original.chmod(0o640)
            manifest = self.make_snapshot()
        destination = self.root / "restored"
        self.restore(destination)
        with closing(sqlite3.connect(destination / "reader/user-data/example/state.sqlite3")) as connection:
            self.assertIn("历史问题", bytes(connection.execute(
                "SELECT content FROM files WHERE path='chats/question.jsonl'"
            ).fetchone()[0]).decode())
        restored = destination / "tasks/example/papers/paper.md"
        self.assertEqual(restored.stat().st_mtime_ns, original.stat().st_mtime_ns)
        self.assertEqual(restored.stat().st_mode & 0o777, 0o640)
        self.assertFalse((destination / ".env").exists())
        self.assertFalse((destination / "reader/.venv").exists())
        config = (destination / ".reader-codex/config.toml").read_text()
        self.assertNotIn("sk-", config)
        self.assertIn('env_key = "READER_AI_API_KEY"', config)
        self.assertEqual(manifest["task_ids"], ["example"])

    def test_corruption_is_rejected_before_restore(self):
        self.make_snapshot()
        archive = self.root / "backup/research.tar.gz"
        archive.write_bytes(archive.read_bytes() + b"corrupt")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.restore(self.root / "destination")
        self.assertFalse((self.root / "destination").exists())

    def test_referenced_sessions_are_restored_with_credentials_redacted(self):
        session_id = "11111111-2222-4333-8444-555555555555"
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("UPDATE files SET content=? WHERE path='sessions.json'",
                               (json.dumps({"thread": {"session_id": session_id}}).encode(),))
        rollout = self.codex / "sessions/2026/10/12" / ("rollout-" + session_id + ".jsonl")
        rollout.parent.mkdir(parents=True)
        rollout.write_text(json.dumps({"type": "event", "content": "sk-" + "x" * 40}) + "\n")
        manifest = self.make_snapshot()
        destination = self.root / "restored"
        self.restore(destination)
        restored = destination / ".reader-codex" / rollout.relative_to(self.codex)
        self.assertEqual(json.loads(restored.read_text())["content"], "[REDACTED_CREDENTIAL]")
        self.assertEqual(manifest["codex_sessions"], 1)
        self.assertEqual(manifest["redacted_session_credentials"], 1)

    def test_existing_different_notes_are_not_overwritten(self):
        self.make_snapshot()
        destination = self.root / "destination"
        paper = destination / "tasks/example/papers/paper.md"
        paper.parent.mkdir(parents=True)
        paper.write_text("newer personal research")
        with self.assertRaisesRegex(ValueError, "overwrite"):
            self.restore(destination)
        self.assertEqual(paper.read_text(), "newer personal research")

    def test_path_escape_in_manifest_is_rejected(self):
        self.make_snapshot()
        path = self.root / "backup/manifest.json"
        manifest = json.loads(path.read_text())
        manifest["files"][0]["path"] = "paper_search/../../escape"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.restore(self.root / "destination")


if __name__ == "__main__":
    unittest.main()
