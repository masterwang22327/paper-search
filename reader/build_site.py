#!/usr/bin/env python3
"""Build MkDocs in a temporary workspace and persist it into SQLite."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from site_store import SiteStore, build_site_database


READER_DIR = Path(__file__).resolve().parent
REPO_DIR = READER_DIR.parent


def site_input_fingerprint(task_id: str) -> str:
    task_dir = REPO_DIR / "tasks" / task_id
    files: set[Path] = set()
    for name in ("REPORT.md", "SOURCES.md", "STATUS.md", "RUN_HISTORY.md", "artifacts.sqlite3"):
        path = task_dir / name
        if path.is_file():
            files.add(path)
    for pattern in ("papers/*.md", "state/coverage-matrix-*.md", "sources/**/*"):
        files.update(path for path in task_dir.glob(pattern) if path.is_file())
    for name in (
        "mkdocs.yml",
        "learning-path.yml",
        "reading-cards.yml",
        "reading-admission.yml",
        "citation-overrides.yml",
        "requirements.txt",
        "build_site.py",
        "site_store.py",
        "task_store.py",
        "scripts/prepare_docs.py",
    ):
        path = READER_DIR / name
        if path.is_file():
            files.add(path)
    files.update(path for path in (READER_DIR / "content").rglob("*") if path.is_file())

    digest = hashlib.sha256()
    sources_dir = task_dir / "sources"
    if sources_dir.is_dir():
        for source_dir in sorted(path for path in sources_dir.iterdir() if path.is_dir()):
            digest.update(b"D\0")
            digest.update(source_dir.name.encode("utf-8"))
            digest.update(b"\0")
    for path in sorted(files):
        if path.is_symlink():
            raise ValueError(f"Reader build fingerprint does not accept symlinks: {path}")
        stat = path.stat()
        digest.update(b"F\0")
        digest.update(path.relative_to(REPO_DIR).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def site_database_is_current(task_id: str, database: Path) -> bool:
    try:
        store = SiteStore(database, REPO_DIR)
        return bool(
            store.quick_check()
            and store.metadata("task_id") == task_id
            and store.metadata("input_fingerprint") == site_input_fingerprint(task_id)
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return False


def build(task_id: str, database: Path) -> int:
    database = database.resolve()
    fingerprint = site_input_fingerprint(task_id)
    with tempfile.TemporaryDirectory(prefix="paper-reader-build-") as temporary:
        build_root = Path(temporary)
        docs_dir = build_root / "docs"
        site_dir = build_root / "site"
        subprocess.run(
            [
                sys.executable,
                str(READER_DIR / "scripts" / "prepare_docs.py"),
                "--task-id",
                task_id,
                "--output-dir",
                str(docs_dir),
                "--virtual-site",
            ],
            cwd=READER_DIR,
            check=True,
        )
        environment = os.environ.copy()
        environment.update(
            READER_DOCS_DIR=str(docs_dir),
            READER_SITE_DIR=str(site_dir),
        )
        subprocess.run(
            [
                str(READER_DIR / ".venv" / "bin" / "mkdocs"),
                "build",
                "--clean",
                "--strict",
                "--config-file",
                str(READER_DIR / "mkdocs.yml"),
            ],
            cwd=READER_DIR,
            env=environment,
            check=True,
        )
        sources_dir = site_dir / "sources"
        if sources_dir.is_dir():
            for pdf in sources_dir.rglob("*.pdf"):
                pdf.unlink()
        if site_input_fingerprint(task_id) != fingerprint:
            raise RuntimeError("Reader inputs changed during the site build")
        return build_site_database(
            site_dir,
            database,
            REPO_DIR,
            task_id,
            input_fingerprint=fingerprint,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    database = args.database or (
        READER_DIR / "user-data" / args.task_id / "site.sqlite3"
    )
    if args.check:
        if site_database_is_current(args.task_id, database):
            print(f"Reader site database is current: {database.resolve()}")
            return
        raise SystemExit(1)
    count = build(args.task_id, database)
    print(f"Built and verified {count} virtual site files in {database.resolve()}")


if __name__ == "__main__":
    main()
