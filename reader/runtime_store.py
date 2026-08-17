#!/usr/bin/env python3
"""SQLite-backed storage and migration for Reader runtime state."""

from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath

from translation_store import TranslationStore


DATABASE_NAMES = {
    "site.sqlite3",
    "state.sqlite3",
    "translations.sqlite3",
}
EXCLUDED_ROOTS = {"translations"}


class RuntimeStore(TranslationStore):
    """Store logical user-data files without materializing a directory tree."""

    @staticmethod
    def is_database_artifact(path: Path) -> bool:
        return any(
            path.name == name or path.name.startswith(name + "-")
            for name in DATABASE_NAMES
        )

    @classmethod
    def legacy_files(cls, user_dir: Path) -> list[Path]:
        user_dir = user_dir.resolve()
        if not user_dir.exists():
            return []
        files = []
        for path in sorted(user_dir.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Runtime storage does not accept symlinks: {path}")
            relative = path.relative_to(user_dir)
            if relative.parts and relative.parts[0] in EXCLUDED_ROOTS:
                continue
            if path.is_file() and not cls.is_database_artifact(path):
                files.append(path)
        return files

    @staticmethod
    def key_for(user_dir: Path, path: Path) -> str:
        return path.resolve().relative_to(user_dir.resolve()).as_posix()

    def import_legacy(self, user_dir: Path) -> int:
        user_dir = user_dir.resolve()
        files = self.legacy_files(user_dir)
        for path in files:
            stat = path.stat()
            self.write_bytes(
                self.key_for(user_dir, path),
                path.read_bytes(),
                mode=stat.st_mode,
                mtime_ns=stat.st_mtime_ns,
                reject_conflict=True,
            )
        self.verify_legacy(user_dir, files)
        return len(files)

    def verify_legacy(self, user_dir: Path, files: list[Path] | None = None) -> None:
        user_dir = user_dir.resolve()
        for path in files if files is not None else self.legacy_files(user_dir):
            key = self.key_for(user_dir, path)
            if self.read_bytes(key) != path.read_bytes():
                raise ValueError(f"Runtime storage verification failed for {key}")

    def compact_legacy(self, user_dir: Path) -> int:
        user_dir = user_dir.resolve()
        files = self.legacy_files(user_dir)
        if not files:
            return 0
        self.import_legacy(user_dir)
        for path in files:
            path.unlink()
        directories = sorted(
            (path for path in user_dir.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in directories:
            try:
                directory.rmdir()
            except OSError:
                pass
        return len(files)

    def restore_legacy(self, user_dir: Path) -> int:
        user_dir = user_dir.resolve()
        user_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT path, content, mode, mtime_ns FROM files ORDER BY path"
            ).fetchall()
        for key, content, mode, mtime_ns in rows:
            normalized = self.normalize_key(str(key))
            path = user_dir.joinpath(*PurePosixPath(normalized).parts)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_bytes(bytes(content))
            os.chmod(temporary, int(mode) & 0o777)
            os.utime(temporary, ns=(int(mtime_ns), int(mtime_ns)))
            temporary.replace(path)
            if path.read_bytes() != bytes(content):
                raise ValueError(f"Runtime restore verification failed for {normalized}")
        return len(rows)

    def read_text(self, key: str | PurePosixPath, default: str | None = None) -> str | None:
        content = self.read_bytes(key)
        return default if content is None else content.decode("utf-8")

    def write_text(self, key: str | PurePosixPath, value: str) -> None:
        self.write_bytes(key, value.encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("compact", "restore", "verify", "stats"))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--user-dir", type=Path, required=True)
    args = parser.parse_args()

    store = RuntimeStore(args.database)
    if args.action == "compact":
        count = store.compact_legacy(args.user_dir)
        print(f"Compacted {count} runtime files into {store.database}")
    elif args.action == "restore":
        count = store.restore_legacy(args.user_dir)
        print(f"Restored {count} runtime files from {store.database}")
    elif args.action == "verify":
        store.verify_legacy(args.user_dir)
        print(f"Verified runtime files in {args.user_dir} against {store.database}")
    else:
        print(f"{store.file_count()} logical runtime files in {store.database}")


if __name__ == "__main__":
    main()
