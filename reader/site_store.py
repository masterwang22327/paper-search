#!/usr/bin/env python3
"""SQLite-backed virtual filesystem for the generated Reader site."""

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
import re
import sqlite3
import tempfile
import zlib
from dataclasses import dataclass
from datetime import datetime
from email.utils import formatdate
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse


SCHEMA_VERSION = 1
RANGE_HEADER = re.compile(r"bytes=(\d*)-(\d*)$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_key(value: str | PurePosixPath) -> str:
    key = PurePosixPath(str(value).replace("\\", "/"))
    if key.is_absolute() or not key.parts or any(part in {"", ".", ".."} for part in key.parts):
        raise ValueError(f"Unsafe site storage path: {value}")
    return key.as_posix()


def canonical_pdf(path: Path, source: Path, repo_dir: Path, task_id: str) -> Path | None:
    relative = path.relative_to(source)
    if len(relative.parts) != 3 or relative.parts[0] != "sources" or relative.name != "paper.pdf":
        return None
    candidate = repo_dir / "tasks" / task_id / "sources" / relative.parts[1] / "paper.pdf"
    if not candidate.is_file() or candidate.stat().st_size != path.stat().st_size:
        return None
    if candidate.stat().st_ino == path.stat().st_ino or sha256_file(candidate) == sha256_file(path):
        return candidate.resolve()
    return None


def canonical_source_pdfs(repo_dir: Path, task_id: str):
    sources_dir = repo_dir / "tasks" / task_id / "sources"
    if not sources_dir.is_dir():
        return
    for source_dir in sorted(path for path in sources_dir.iterdir() if path.is_dir()):
        for pdf in sorted(
            path for path in source_dir.rglob("*")
            if path.is_file() and path.suffix.lower() == ".pdf"
        ):
            relative = pdf.relative_to(source_dir)
            target_name = pdf.name if pdf.parent == source_dir else "-".join(relative.parts)
            yield f"sources/{source_dir.name}/{target_name}", pdf.resolve()


@dataclass(frozen=True)
class SiteEntry:
    path: str
    storage: str
    content: bytes | None
    compression: str
    canonical_path: Path | None
    size: int
    sha256: str
    mime_type: str
    mtime_ns: int

    def read_bytes(self) -> bytes:
        if self.storage == "canonical":
            if self.canonical_path is None:
                raise ValueError(f"Canonical site target is missing: {self.path}")
            return self.canonical_path.read_bytes()
        if self.content is None:
            raise ValueError(f"Site content is missing: {self.path}")
        if self.compression == "zlib":
            return zlib.decompress(self.content)
        if self.compression != "none":
            raise ValueError(f"Unsupported site compression: {self.compression}")
        return self.content


class SiteStore:
    def __init__(self, database: Path, repo_dir: Path) -> None:
        self.database = database.resolve()
        self.repo_dir = repo_dir.resolve()
        if not self.database.is_file():
            raise FileNotFoundError(f"Reader site database is missing: {self.database}")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
        if row is None or row[0] != str(SCHEMA_VERSION):
            raise RuntimeError(f"Unsupported Reader site schema: {row[0] if row else 'missing'}")

    def _connection(self):
        return sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=30)

    def entry(self, key: str | PurePosixPath) -> SiteEntry | None:
        normalized = normalize_key(key)
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT storage, content, compression, canonical_path, size, sha256, mime_type, mtime_ns
                FROM files WHERE path = ?
                """,
                (normalized,),
            ).fetchone()
        if row is None:
            return None
        storage, content, compression, canonical_path, size, digest, mime_type, mtime_ns = row
        canonical = None
        if storage == "canonical":
            candidate = (self.repo_dir / normalize_key(str(canonical_path))).resolve()
            if not candidate.is_relative_to(self.repo_dir) or not candidate.is_file():
                raise ValueError(f"Canonical site target is missing: {canonical_path}")
            canonical = candidate
        return SiteEntry(
            path=normalized,
            storage=str(storage),
            content=bytes(content) if content is not None else None,
            compression=str(compression),
            canonical_path=canonical,
            size=int(size),
            sha256=str(digest),
            mime_type=str(mime_type),
            mtime_ns=int(mtime_ns),
        )

    def request_entry(self, url_path: str) -> SiteEntry | None:
        decoded = unquote(url_path)
        if "\x00" in decoded or "\\" in decoded:
            return None
        relative = decoded.lstrip("/")
        candidates = ["index.html"] if not relative else []
        if relative.endswith("/"):
            candidates.append(relative + "index.html")
        else:
            candidates.extend((relative, relative + "/index.html"))
        for candidate in candidates:
            try:
                entry = self.entry(candidate)
            except ValueError:
                return None
            if entry is not None:
                return entry
        return None

    def read_bytes(self, key: str | PurePosixPath) -> bytes | None:
        entry = self.entry(key)
        return entry.read_bytes() if entry is not None else None

    def load_json(self, key: str | PurePosixPath, default):
        content = self.read_bytes(key)
        if content is None:
            return default
        import json

        return json.loads(content.decode("utf-8"))

    def file_count(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM files").fetchone()[0])

    def metadata(self, key: str, default: str | None = None) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = ?", (key,)
            ).fetchone()
        return default if row is None else str(row[0])

    def quick_check(self) -> bool:
        with self._connection() as connection:
            integrity = connection.execute("PRAGMA quick_check").fetchone()
            count = int(connection.execute("SELECT COUNT(*) FROM files").fetchone()[0])
        expected = self.metadata("file_count")
        return bool(
            integrity
            and integrity[0] == "ok"
            and expected is not None
            and count == int(expected)
        )

    def verify(self) -> int:
        with self._connection() as connection:
            keys = [row[0] for row in connection.execute("SELECT path FROM files ORDER BY path")]
        for key in keys:
            entry = self.entry(str(key))
            if entry is None:
                raise ValueError(f"Site entry disappeared during verification: {key}")
            content = entry.read_bytes()
            if len(content) != entry.size or hashlib.sha256(content).hexdigest() != entry.sha256:
                raise ValueError(f"Site content verification failed: {key}")
        return len(keys)


def initialize_database(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database, timeout=30)
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute(
        "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        """
        CREATE TABLE files (
            path TEXT PRIMARY KEY,
            storage TEXT NOT NULL CHECK (storage IN ('blob', 'canonical')),
            content BLOB,
            compression TEXT NOT NULL CHECK (compression IN ('none', 'zlib')),
            canonical_path TEXT,
            size INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            mtime_ns INTEGER NOT NULL,
            CHECK (
                (storage = 'blob' AND content IS NOT NULL AND canonical_path IS NULL) OR
                (storage = 'canonical' AND content IS NULL AND canonical_path IS NOT NULL)
            )
        ) WITHOUT ROWID
        """
    )
    connection.execute(
        "INSERT INTO metadata(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    return connection


def build_site_database(
    source: Path,
    database: Path,
    repo_dir: Path,
    task_id: str,
    input_fingerprint: str | None = None,
) -> int:
    source = source.resolve()
    database = database.resolve()
    repo_dir = repo_dir.resolve()
    if not source.is_dir():
        raise ValueError(f"Generated Reader site is missing: {source}")
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=database.name + ".",
        suffix=".tmp",
        dir=database.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink()
    count = 0
    inserted: set[str] = set()
    try:
        connection = initialize_database(temporary)
        try:
            with connection:
                for path in sorted(source.rglob("*")):
                    if path.is_symlink():
                        raise ValueError(f"Reader site storage does not accept symlinks: {path}")
                    if not path.is_file():
                        continue
                    relative = path.relative_to(source).as_posix()
                    normalized = normalize_key(relative)
                    stat = path.stat()
                    digest = sha256_file(path)
                    mime_type = mimetypes.guess_type(normalized)[0] or "application/octet-stream"
                    canonical = canonical_pdf(path, source, repo_dir, task_id)
                    if canonical is not None:
                        storage = "canonical"
                        content = None
                        compression = "none"
                        canonical_path = canonical.relative_to(repo_dir).as_posix()
                    else:
                        raw = path.read_bytes()
                        compressed = zlib.compress(raw, level=9)
                        if len(compressed) < len(raw):
                            content = compressed
                            compression = "zlib"
                        else:
                            content = raw
                            compression = "none"
                        storage = "blob"
                        canonical_path = None
                    connection.execute(
                        """
                        INSERT INTO files(
                            path, storage, content, compression, canonical_path,
                            size, sha256, mime_type, mtime_ns
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            normalized,
                            storage,
                            content,
                            compression,
                            canonical_path,
                            stat.st_size,
                            digest,
                            mime_type,
                            stat.st_mtime_ns,
                        ),
                    )
                    inserted.add(normalized)
                    count += 1
                for logical_path, canonical in canonical_source_pdfs(repo_dir, task_id):
                    normalized = normalize_key(logical_path)
                    if normalized in inserted:
                        continue
                    stat = canonical.stat()
                    connection.execute(
                        """
                        INSERT INTO files(
                            path, storage, content, compression, canonical_path,
                            size, sha256, mime_type, mtime_ns
                        ) VALUES (?, 'canonical', NULL, 'none', ?, ?, ?, 'application/pdf', ?)
                        """,
                        (
                            normalized,
                            canonical.relative_to(repo_dir).as_posix(),
                            stat.st_size,
                            sha256_file(canonical),
                            stat.st_mtime_ns,
                        ),
                    )
                    inserted.add(normalized)
                    count += 1
                connection.execute(
                    "INSERT INTO metadata(key, value) VALUES ('task_id', ?)",
                    (task_id,),
                )
                connection.execute(
                    "INSERT INTO metadata(key, value) VALUES ('built_at', ?)",
                    (datetime.now().astimezone().isoformat(timespec="seconds"),),
                )
                connection.execute(
                    "INSERT INTO metadata(key, value) VALUES ('file_count', ?)",
                    (str(count),),
                )
                if input_fingerprint is not None:
                    connection.execute(
                        "INSERT INTO metadata(key, value) VALUES ('input_fingerprint', ?)",
                        (input_fingerprint,),
                    )
        finally:
            connection.close()
        os.chmod(temporary, 0o600)
        store = SiteStore(temporary, repo_dir)
        if store.verify() != count:
            raise ValueError("Reader site database file count changed during verification")
        temporary.replace(database)
        os.chmod(database, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
    return count


def parse_range(value: str, size: int) -> tuple[int, int] | None:
    match = RANGE_HEADER.fullmatch(value.strip())
    if not match:
        return None
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        return None
    if not start_text:
        length = int(end_text)
        if length <= 0:
            return None
        start = max(0, size - length)
        return start, size - 1
    start = int(start_text)
    end = int(end_text) if end_text else size - 1
    if start >= size or end < start:
        return None
    return start, min(end, size - 1)


def send_site_entry(
    handler: BaseHTTPRequestHandler,
    store: SiteStore,
    url_path: str,
    *,
    head_only: bool = False,
) -> bool:
    entry = store.request_entry(url_path)
    if entry is None:
        return False
    etag = f'"{entry.sha256}"'
    if handler.headers.get("If-None-Match") == etag and not handler.headers.get("Range"):
        handler.send_response(HTTPStatus.NOT_MODIFIED)
        handler.send_header("ETag", etag)
        handler.end_headers()
        return True
    selected = None
    range_header = handler.headers.get("Range")
    if range_header:
        selected = parse_range(range_header, entry.size)
        if selected is None:
            handler.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            handler.send_header("Content-Range", f"bytes */{entry.size}")
            handler.end_headers()
            return True
    start, end = selected or (0, entry.size - 1)
    length = max(0, end - start + 1)
    handler.send_response(HTTPStatus.PARTIAL_CONTENT if selected else HTTPStatus.OK)
    content_type = entry.mime_type
    if content_type.startswith("text/") or content_type in {
        "application/javascript",
        "application/json",
        "application/xml",
    }:
        content_type += "; charset=utf-8"
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(length))
    handler.send_header("Accept-Ranges", "bytes")
    if selected:
        handler.send_header("Content-Range", f"bytes {start}-{end}/{entry.size}")
    handler.send_header("ETag", etag)
    handler.send_header("Last-Modified", formatdate(entry.mtime_ns / 1_000_000_000, usegmt=True))
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    if head_only or length == 0:
        return True
    if entry.storage == "canonical" and entry.canonical_path is not None:
        with entry.canonical_path.open("rb") as stream:
            stream.seek(start)
            remaining = length
            while remaining:
                block = stream.read(min(1024 * 1024, remaining))
                if not block:
                    break
                handler.wfile.write(block)
                remaining -= len(block)
    else:
        handler.wfile.write(entry.read_bytes()[start : end + 1])
    return True


class StaticSiteHandler(BaseHTTPRequestHandler):
    store: SiteStore
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if not send_site_entry(self, self.store, urlparse(self.path).path):
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_HEAD(self) -> None:
        if not send_site_entry(self, self.store, urlparse(self.path).path, head_only=True):
            self.send_error(HTTPStatus.NOT_FOUND)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "verify", "serve", "stats"))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--repo-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--task-id")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.action == "build":
        if not args.task_id or args.source is None:
            parser.error("build requires --task-id and --source")
        count = build_site_database(args.source, args.database, args.repo_dir, args.task_id)
        print(f"Stored and verified {count} Reader site files in {args.database.resolve()}")
        return
    store = SiteStore(args.database, args.repo_dir)
    if args.action == "verify":
        print(f"Verified {store.verify()} Reader site files in {store.database}")
    elif args.action == "stats":
        print(f"{store.file_count()} Reader site files in {store.database}")
    else:
        StaticSiteHandler.store = store
        server = ThreadingHTTPServer(("127.0.0.1", args.port), StaticSiteHandler)
        print(f"SQLite Reader site serving on http://127.0.0.1:{args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
