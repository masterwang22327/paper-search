#!/usr/bin/env python3
"""SQLite-backed storage for Reader translation artifacts."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path, PurePosixPath


SCHEMA_VERSION = 1


class TranslationStore:
    def __init__(self, database: Path, *, read_only: bool = False) -> None:
        self.database = database.resolve()
        self.read_only = read_only
        if read_only:
            if not self.database.is_file():
                raise FileNotFoundError(f"SQLite storage database is missing: {self.database}")
        else:
            self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        with self._connection() as connection:
            if not read_only:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS files (
                        path TEXT PRIMARY KEY,
                        content BLOB NOT NULL,
                        sha256 TEXT NOT NULL,
                        mode INTEGER NOT NULL,
                        mtime_ns INTEGER NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT OR IGNORE INTO metadata(key, value) VALUES ('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            stored_version = connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            if stored_version is None or stored_version[0] != str(SCHEMA_VERSION):
                raise RuntimeError(
                    f"Unsupported translation database schema: "
                    f"{stored_version[0] if stored_version else 'missing'}"
                )
        if not read_only:
            os.chmod(self.database, 0o600)

    @contextlib.contextmanager
    def _connection(self):
        if self.read_only:
            connection = sqlite3.connect(
                self.database.as_uri() + "?mode=ro", uri=True, timeout=30
            )
        else:
            connection = sqlite3.connect(self.database, timeout=30)
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def normalize_key(value: str | PurePosixPath) -> str:
        key = PurePosixPath(str(value).replace("\\", "/"))
        if key.is_absolute() or not key.parts or any(part in {"", ".", ".."} for part in key.parts):
            raise ValueError(f"Unsafe translation storage path: {value}")
        return key.as_posix()

    def contains(self, key: str | PurePosixPath) -> bool:
        normalized = self.normalize_key(key)
        with self.lock, self._connection() as connection:
            return connection.execute(
                "SELECT 1 FROM files WHERE path = ?", (normalized,)
            ).fetchone() is not None

    def read_bytes(self, key: str | PurePosixPath) -> bytes | None:
        normalized = self.normalize_key(key)
        with self.lock, self._connection() as connection:
            row = connection.execute(
                "SELECT content FROM files WHERE path = ?", (normalized,)
            ).fetchone()
        return bytes(row[0]) if row is not None else None

    def write_bytes(
        self,
        key: str | PurePosixPath,
        content: bytes,
        *,
        mode: int = 0o600,
        mtime_ns: int | None = None,
        reject_conflict: bool = False,
    ) -> None:
        normalized = self.normalize_key(key)
        digest = hashlib.sha256(content).hexdigest()
        timestamp = time.time_ns() if mtime_ns is None else int(mtime_ns)
        with self.lock, self._connection() as connection:
            existing = connection.execute(
                "SELECT sha256 FROM files WHERE path = ?", (normalized,)
            ).fetchone()
            if reject_conflict and existing is not None and existing[0] != digest:
                raise ValueError(f"Translation storage conflict for {normalized}")
            connection.execute(
                """
                INSERT INTO files(path, content, sha256, mode, mtime_ns)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    content = excluded.content,
                    sha256 = excluded.sha256,
                    mode = excluded.mode,
                    mtime_ns = excluded.mtime_ns
                """,
                (normalized, content, digest, int(mode) & 0o777, timestamp),
            )

    def delete(self, key: str | PurePosixPath) -> bool:
        normalized = self.normalize_key(key)
        with self.lock, self._connection() as connection:
            cursor = connection.execute("DELETE FROM files WHERE path = ?", (normalized,))
            return cursor.rowcount > 0

    def load_json(self, key: str | PurePosixPath, default):
        content = self.read_bytes(key)
        if content is None:
            return default
        return json.loads(content.decode("utf-8"))

    def write_json(self, key: str | PurePosixPath, value: object) -> None:
        content = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        self.write_bytes(key, content)

    def append_jsonl(self, key: str | PurePosixPath, value: object) -> None:
        normalized = self.normalize_key(key)
        line = (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
        with self.lock, self._connection() as connection:
            row = connection.execute(
                "SELECT content, mode FROM files WHERE path = ?", (normalized,)
            ).fetchone()
            content = (bytes(row[0]) if row else b"") + line
            mode = int(row[1]) if row else 0o600
            connection.execute(
                """
                INSERT INTO files(path, content, sha256, mode, mtime_ns)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    content = excluded.content,
                    sha256 = excluded.sha256,
                    mode = excluded.mode,
                    mtime_ns = excluded.mtime_ns
                """,
                (normalized, content, hashlib.sha256(content).hexdigest(), mode, time.time_ns()),
            )

    def list_keys(self, prefix: str = "") -> list[str]:
        normalized = self.normalize_key(prefix) if prefix else ""
        pattern = normalized.rstrip("/") + "/%" if normalized else "%"
        with self.lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT path FROM files WHERE path LIKE ? ORDER BY path", (pattern,)
            ).fetchall()
        return [str(row[0]) for row in rows]

    def file_count(self) -> int:
        with self.lock, self._connection() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM files").fetchone()[0])

    def import_tree(self, source: Path) -> int:
        source = source.resolve()
        if not source.exists():
            return 0
        if not source.is_dir():
            raise ValueError(f"Translation source is not a directory: {source}")
        imported = 0
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Translation storage does not accept symlinks: {path}")
            if not path.is_file():
                continue
            stat = path.stat()
            self.write_bytes(
                path.relative_to(source).as_posix(),
                path.read_bytes(),
                mode=stat.st_mode,
                mtime_ns=stat.st_mtime_ns,
                reject_conflict=True,
            )
            imported += 1
        self.verify_tree(source)
        return imported

    def verify_tree(self, source: Path) -> None:
        source = source.resolve()
        for path in sorted(source.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            key = path.relative_to(source).as_posix()
            stored = self.read_bytes(key)
            if stored != path.read_bytes():
                raise ValueError(f"Translation verification failed for {key}")

    def compact_tree(self, source: Path) -> int:
        source = source.resolve()
        imported = self.import_tree(source)
        if source.exists():
            shutil.rmtree(source)
        return imported

    def restore_tree(self, destination: Path) -> int:
        destination = destination.resolve()
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        restored = 0
        with self.lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT path, content, mode, mtime_ns FROM files ORDER BY path"
            ).fetchall()
        for key, content, mode, mtime_ns in rows:
            normalized = self.normalize_key(str(key))
            path = destination.joinpath(*PurePosixPath(normalized).parts)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_bytes(bytes(content))
            os.chmod(temporary, int(mode) & 0o777)
            os.utime(temporary, ns=(int(mtime_ns), int(mtime_ns)))
            temporary.replace(path)
            restored += 1
        self.verify_tree(destination)
        return restored


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("compact", "restore", "verify"))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    store = TranslationStore(args.database)
    if args.action == "compact":
        count = store.compact_tree(args.directory)
        print(f"Compacted {count} translation files into {store.database}")
    elif args.action == "restore":
        count = store.restore_tree(args.directory)
        print(f"Restored {count} translation files from {store.database}")
    else:
        store.verify_tree(args.directory)
        print(f"Verified {args.directory} against {store.database}")


if __name__ == "__main__":
    main()
