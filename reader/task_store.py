#!/usr/bin/env python3
"""SQLite storage for non-PDF research source artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from translation_store import TranslationStore


DATABASE_NAME = "artifacts.sqlite3"


@dataclass(frozen=True)
class ArtifactInfo:
    path: str
    size: int
    mtime_ns: int


class TaskArtifactStore(TranslationStore):
    def __init__(self, task_dir: Path, *, read_only: bool = False) -> None:
        self.task_dir = task_dir.resolve()
        super().__init__(self.task_dir / DATABASE_NAME, read_only=read_only)

    @staticmethod
    def database_path(task_dir: Path) -> Path:
        return task_dir.resolve() / DATABASE_NAME

    @classmethod
    def open_existing(cls, task_dir: Path) -> TaskArtifactStore | None:
        return cls(task_dir, read_only=True) if cls.database_path(task_dir).is_file() else None

    def key_for(self, path: Path) -> str:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.task_dir):
            raise ValueError(f"Task artifact is outside the task directory: {path}")
        return resolved.relative_to(self.task_dir).as_posix()

    def source_files(self) -> list[Path]:
        sources_dir = self.task_dir / "sources"
        if not sources_dir.exists():
            return []
        files = []
        for path in sorted(sources_dir.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Task artifact storage does not accept symlinks: {path}")
            if path.is_file() and path.suffix.lower() != ".pdf":
                files.append(path)
        return files

    def import_files(self, files: list[Path], *, replace: bool = False) -> int:
        with self.lock, self._connection() as connection:
            for path in files:
                key = self.key_for(path)
                content = path.read_bytes()
                digest = hashlib.sha256(content).hexdigest()
                existing = connection.execute(
                    "SELECT sha256 FROM files WHERE path = ?", (key,)
                ).fetchone()
                if not replace and existing is not None and existing[0] != digest:
                    raise ValueError(f"Task artifact storage conflict for {key}")
                stat = path.stat()
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
                    (key, content, digest, stat.st_mode & 0o777, stat.st_mtime_ns),
                )
        self.verify_sources(files)
        return len(files)

    def import_sources(self, files: list[Path] | None = None, *, replace: bool = False) -> int:
        return self.import_files(self.source_files() if files is None else files, replace=replace)

    def verify_sources(self, files: list[Path] | None = None) -> None:
        for path in self.source_files() if files is None else files:
            key = self.key_for(path)
            if self.read_bytes(key) != path.read_bytes():
                raise ValueError(f"Task artifact verification failed for {key}")

    def verify_database(self) -> int:
        with self.lock, self._connection() as connection:
            rows = connection.execute("SELECT path, content, sha256 FROM files ORDER BY path").fetchall()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise ValueError(f"Task artifact SQLite integrity check failed: {integrity}")
        for key, content, expected in rows:
            actual = hashlib.sha256(bytes(content)).hexdigest()
            if actual != expected:
                raise ValueError(f"Task artifact digest mismatch for {key}")
        return len(rows)

    def current_run_id(self) -> str | None:
        path = self.task_dir / "state" / "current-run.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        run_id = value.get("run_id") if isinstance(value, dict) else None
        return str(run_id) if run_id else None

    def state_history_files(self) -> list[Path]:
        state_dir = self.task_dir / "state"
        current_run_id = self.current_run_id()
        files = []
        for root_name in ("handoffs", "work"):
            root = state_dir / root_name
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                if path.is_symlink():
                    raise ValueError(f"Task artifact storage does not accept symlinks: {path}")
                if path.is_file():
                    files.append(path)
        runs = state_dir / "runs"
        if runs.exists():
            for path in sorted(runs.rglob("*")):
                if path.is_symlink():
                    raise ValueError(f"Task artifact storage does not accept symlinks: {path}")
                if not path.is_file():
                    continue
                relative = path.relative_to(runs)
                if relative.parts and relative.parts[0] != current_run_id:
                    files.append(path)
        return files

    def prune_empty_directories(self) -> None:
        preserved = {
            self.task_dir / "sources",
            self.task_dir / "state" / "handoffs",
            self.task_dir / "state" / "runs",
            self.task_dir / "state" / "work",
        }
        sources_dir = self.task_dir / "sources"
        if sources_dir.is_dir():
            preserved.update(path for path in sources_dir.iterdir() if path.is_dir())
        candidates = []
        for root in (sources_dir, self.task_dir / "state"):
            if root.is_dir():
                candidates.extend(path for path in root.rglob("*") if path.is_dir())
        for directory in sorted(candidates, key=lambda path: len(path.parts), reverse=True):
            if directory in preserved:
                continue
            try:
                directory.rmdir()
            except OSError:
                pass

    def compact_files(self, files: list[Path], *, replace: bool = False) -> int:
        if not files:
            self.verify_database()
            return 0
        self.import_files(files, replace=replace)
        for path in files:
            path.unlink()
        self.prune_empty_directories()
        self.verify_database()
        return len(files)

    def compact_sources(self, *, replace: bool = False) -> int:
        return self.compact_files(self.source_files(), replace=replace)

    def compact_state_history(self, *, replace: bool = False) -> int:
        return self.compact_files(self.state_history_files(), replace=replace)

    def compact_all(self, *, replace: bool = False) -> int:
        files = [*self.source_files(), *self.state_history_files()]
        return self.compact_files(files, replace=replace)

    def restore_artifacts(self, prefix: str | None = None) -> int:
        with self.lock, self._connection() as connection:
            if prefix is None:
                rows = connection.execute(
                    "SELECT path, content, mode, mtime_ns FROM files ORDER BY path"
                ).fetchall()
            else:
                normalized = self.normalize_key(prefix)
                rows = connection.execute(
                    """
                    SELECT path, content, mode, mtime_ns
                    FROM files WHERE substr(path, 1, ?) = ? ORDER BY path
                    """,
                    (len(normalized) + 1, normalized.rstrip("/") + "/"),
                ).fetchall()
        for key, content, mode, mtime_ns in rows:
            normalized = self.normalize_key(str(key))
            path = self.task_dir.joinpath(*PurePosixPath(normalized).parts)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_bytes(bytes(content))
            os.chmod(temporary, int(mode) & 0o777)
            os.utime(temporary, ns=(int(mtime_ns), int(mtime_ns)))
            temporary.replace(path)
            if path.read_bytes() != bytes(content):
                raise ValueError(f"Task artifact restore verification failed for {normalized}")
        return len(rows)

    def restore_sources(self) -> int:
        return self.restore_artifacts("sources")

    def read_path_bytes(self, path: Path) -> bytes | None:
        if path.is_file():
            return path.read_bytes()
        return self.read_bytes(self.key_for(path))

    def read_path_text(
        self,
        path: Path,
        default: str | None = None,
        *,
        errors: str = "strict",
    ) -> str | None:
        content = self.read_path_bytes(path)
        return default if content is None else content.decode("utf-8", errors=errors)

    def contains_path(self, path: Path) -> bool:
        return path.is_file() or self.contains(self.key_for(path))

    def source_ids(self) -> list[str]:
        source_ids = {
            path.name
            for path in (self.task_dir / "sources").iterdir()
            if path.is_dir()
        }
        for key in self.list_keys("sources"):
            parts = PurePosixPath(key).parts
            if len(parts) >= 3:
                source_ids.add(parts[1])
        return sorted(source_ids)

    def source_inventory(self, source_id: str) -> list[ArtifactInfo]:
        if PurePosixPath(source_id).name != source_id or source_id in {"", ".", ".."}:
            raise ValueError(f"Unsafe source ID: {source_id}")
        prefix = f"sources/{source_id}/"
        inventory: dict[str, ArtifactInfo] = {}
        with self.lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT path, LENGTH(content), mtime_ns
                FROM files WHERE path LIKE ? ORDER BY path
                """,
                (prefix + "%",),
            ).fetchall()
        for key, size, mtime_ns in rows:
            relative = str(key)[len(prefix):]
            inventory[relative] = ArtifactInfo(relative, int(size), int(mtime_ns))
        source_dir = self.task_dir / "sources" / source_id
        if source_dir.is_dir():
            for path in source_dir.rglob("*"):
                if path.is_file():
                    stat = path.stat()
                    relative = path.relative_to(source_dir).as_posix()
                    inventory[relative] = ArtifactInfo(relative, stat.st_size, stat.st_mtime_ns)
        return [inventory[key] for key in sorted(inventory)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("compact", "restore", "verify", "stats", "list", "read"))
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--key")
    args = parser.parse_args()

    store = TaskArtifactStore(args.task_dir)
    if args.action == "compact":
        count = store.compact_all(replace=args.replace)
        print(f"Compacted {count} task artifacts into {store.database}")
    elif args.action == "restore":
        count = store.restore_artifacts()
        print(f"Restored {count} task artifacts from {store.database}")
    elif args.action == "verify":
        count = store.verify_database()
        store.verify_sources()
        print(f"Verified {count} task artifacts in {store.database}")
    elif args.action == "stats":
        with store.lock, store._connection() as connection:
            count, size = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(LENGTH(content)), 0) FROM files"
            ).fetchone()
        print(f"{count} logical files, {size} bytes in {store.database}")
    elif args.action == "list":
        for key in store.list_keys(args.key or ""):
            print(key)
    else:
        if not args.key:
            parser.error("read requires --key")
        content = store.read_bytes(args.key)
        if content is None:
            raise SystemExit(f"Task artifact not found: {args.key}")
        sys.stdout.buffer.write(content)


if __name__ == "__main__":
    main()
