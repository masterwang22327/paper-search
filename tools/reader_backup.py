#!/usr/bin/env python3
"""Create, publish and restore a portable, private Paper Reader backup."""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import tomllib
from datetime import datetime, timezone


REPO = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = "masterwei22327/paper_reader"
EXCLUDED_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "htmlcov",
                 ".reader-codex", ".reader-backup", ".backup-venv"}
CREDENTIAL_NAMES = {"auth.json", "credentials.json", "cookies", "git_token"}
KEY_PATTERN = re.compile(
    rb"(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}"
    rb"|github_pat_[A-Za-z0-9_]{30,}|ms-[A-Za-z0-9_-]{24,})"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (not value or "\\" in value or path.is_absolute()
            or any(part in {".", ".."} for part in value.split("/"))):
        raise ValueError(f"Unsafe backup path: {value}")
    return path


def excluded(path: Path) -> bool:
    name = path.name
    return (any(part in EXCLUDED_DIRS for part in path.parts)
            or name == ".DS_Store" or name == ".coverage"
            or (name.startswith(".env") and name != ".env.example")
            or name in CREDENTIAL_NAMES or name.startswith("credentials.")
            or name.endswith((".pyc", ".pyo", ".pem", ".key", ".p12", ".pfx", ".lock"))
            or name.endswith((".sqlite3-wal", ".sqlite3-shm", ".sqlite3-journal")))


def project_files(repo: Path):
    for directory, directories, filenames in os.walk(repo):
        base = Path(directory)
        directories[:] = sorted(d for d in directories if not excluded((base / d).relative_to(repo)))
        for name in sorted(filenames):
            path = base / name
            if excluded(path.relative_to(repo)):
                continue
            if path.is_symlink():
                raise ValueError(f"Backup does not accept symlinks: {path.relative_to(repo)}")
            if path.is_file():
                yield path


def sqlite_snapshot(source: Path, target: Path) -> None:
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as incoming:
        with closing(sqlite3.connect(target)) as outgoing:
            incoming.backup(outgoing, pages=1024)
            if outgoing.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError(f"SQLite backup failed integrity check: {source.name}")


def credential_values(repo: Path, codex_home: Path) -> list[bytes]:
    values = set()

    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if (isinstance(item, str) and len(item) >= 16
                        and any(word in key.lower() for word in ("key", "token", "secret", "password"))):
                    values.add(item.encode())
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    env = repo / ".env"
    if env.is_file():
        collect(dict(line.split("=", 1) for line in env.read_text().splitlines()
                     if "=" in line and not line.lstrip().startswith("#")))
    config = codex_home / "config.toml"
    if config.is_file():
        collect(tomllib.loads(config.read_text()))
    auth = codex_home / "auth.json"
    if auth.is_file():
        collect(json.loads(auth.read_text()))
    return sorted({value.strip().strip(b"\"'") for value in values}, key=len, reverse=True)


def check_credentials(path: Path, values: list[bytes], label: str) -> None:
    if not values:
        return
    tail = b""
    overlap = max(map(len, values))
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            content = tail + block
            if any(value in content for value in values):
                raise ValueError(f"Configured credential found in backup input: {label}")
            tail = content[-overlap:]


def referenced_sessions(repo: Path) -> set[str]:
    sessions = set()

    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"session_id", "codex_session_id"} and isinstance(item, str):
                    sessions.add(item)
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for database in (repo / "reader/user-data").glob("*/state.sqlite3"):
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            row = connection.execute("SELECT content FROM files WHERE path='sessions.json'").fetchone()
            if row:
                visit(json.loads(bytes(row[0])))
    return sessions


def portable_config(codex_home: Path) -> bytes:
    path = codex_home / "config.toml"
    if not path.is_file():
        return b"# Configure a Responses provider or run codex login on the new computer.\n"
    config = tomllib.loads(path.read_text())
    provider_id = config.get("model_provider")
    provider = config.get("model_providers", {}).get(provider_id, {})
    lines = []
    for key in ("model_provider", "model", "model_reasoning_effort", "disable_response_storage"):
        if key in config:
            lines.append(f"{key} = {json.dumps(config[key], ensure_ascii=False)}")
    if provider_id and provider:
        lines.extend(["", f"[model_providers.{json.dumps(provider_id)}]"])
        for key in ("name", "base_url", "wire_api", "requires_openai_auth"):
            if key in provider:
                lines.append(f"{key} = {json.dumps(provider[key], ensure_ascii=False)}")
        if provider.get("requires_openai_auth") is not True:
            lines.append('env_key = "READER_AI_API_KEY"')
    lines.extend(["", "# Machine-specific MCP paths and credentials are configured separately.", ""])
    return "\n".join(lines).encode()


def snapshot(repo: Path, output: Path, codex_home: Path) -> dict:
    repo, output, codex_home = repo.resolve(), output.resolve(), codex_home.resolve()
    if output.is_relative_to(repo):
        raise ValueError("Place the backup outside the repository")
    output.mkdir(parents=True, exist_ok=False)
    values = credential_values(repo, codex_home)
    groups = {name: [] for name in ("code", "research", "reader-state", "codex-sessions")}
    for path in project_files(repo):
        relative = path.relative_to(repo).as_posix()
        group = ("reader-state" if relative.startswith("reader/user-data/") else
                 "research" if relative.startswith(("tasks/", "library/", "reader/tests/artifacts/"))
                 or relative == "reader/reader-service.log" else "code")
        groups[group].append((path, "paper_search/" + relative))
    required = referenced_sessions(repo)
    found = set()
    for name in ("sessions", "archived_sessions"):
        for path in sorted((codex_home / name).rglob("*.jsonl")):
            matched = {session for session in required if session in path.name}
            if matched:
                found.update(matched)
                groups["codex-sessions"].append((path, "codex/" + path.relative_to(codex_home).as_posix()))
    if required - found:
        raise ValueError(f"Missing {len(required - found)} referenced Codex session files")
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo,
                                         stderr=subprocess.DEVNULL, text=True).strip()
    except subprocess.CalledProcessError:
        commit = None
    manifest = {"format_version": 1, "snapshot_id": output.name,
                "created_at": datetime.now(timezone.utc).isoformat(), "git_commit": commit,
                "task_ids": sorted(path.name for path in (repo / "tasks").iterdir() if path.is_dir()),
                "codex_sessions": len(found), "redacted_session_credentials": 0,
                "archives": [], "files": [],
                "exclusions": ["credentials", "virtual environments", "Git object database", "temporary caches"]}
    with tempfile.TemporaryDirectory(prefix="reader-sqlite-backup-") as temporary:
        temporary = Path(temporary)
        config = temporary / "codex-config.example.toml"
        config.write_bytes(portable_config(codex_home))
        groups["codex-sessions"].append((config, "environment/codex-config.example.toml"))
        for group, files in groups.items():
            archive = output / f"{group}.tar.gz"
            with tarfile.open(archive, "w:gz", compresslevel=6) as tar:
                for index, (source, relative) in enumerate(files):
                    stat = source.stat()
                    prepared = source
                    if source.suffix == ".sqlite3":
                        prepared = temporary / "database.sqlite3"
                        prepared.unlink(missing_ok=True)
                        sqlite_snapshot(source, prepared)
                    elif relative.startswith("codex/"):
                        content = source.read_bytes()
                        for value in values:
                            count = content.count(value)
                            manifest["redacted_session_credentials"] += count
                            content = content.replace(value, b"[REDACTED_CREDENTIAL]")
                        content, count = KEY_PATTERN.subn(b"[REDACTED_CREDENTIAL]", content)
                        manifest["redacted_session_credentials"] += count
                        prepared = temporary / "session.jsonl"
                        prepared.write_bytes(content)
                    check_credentials(prepared, values, relative)
                    size = prepared.stat().st_size
                    digest = sha256(prepared)
                    info = tar.gettarinfo(str(prepared), arcname=relative)
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mode = stat.st_mode & 0o777
                    info.mtime = stat.st_mtime
                    with prepared.open("rb") as stream:
                        tar.addfile(info, stream)
                    if prepared == source and source.stat().st_mtime_ns != stat.st_mtime_ns:
                        raise ValueError(f"File changed while backing up; retry: {relative}")
                    manifest["files"].append({"path": relative, "archive": archive.name,
                                              "size": size, "sha256": digest,
                                              "mode": info.mode, "mtime_ns": stat.st_mtime_ns})
                    if index and index % 250 == 0:
                        print(f"{group}: {index}/{len(files)} files", flush=True)
            manifest["archives"].append({"name": archive.name, "size": archive.stat().st_size,
                                          "sha256": sha256(archive)})
            print(f"{group}: {len(files)} files, {archive.stat().st_size / 2**20:.1f} MiB compressed", flush=True)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Snapshot ready: {output}", flush=True)
    return manifest


def load_manifest(folder: Path) -> dict:
    manifest = json.loads((folder / "manifest.json").read_text())
    if manifest.get("format_version") != 1:
        raise ValueError("Unsupported backup format")
    for entry in manifest["archives"]:
        if len(safe_relative(entry["name"]).parts) != 1:
            raise ValueError("Archive name must be a filename")
    for entry in manifest["files"]:
        path = safe_relative(entry["path"])
        if path.parts[0] not in {"paper_search", "codex", "environment"}:
            raise ValueError("Unknown backup root")
    return manifest


def verify(folder: Path) -> dict:
    manifest = load_manifest(folder)
    for entry in manifest["archives"]:
        archive = folder / entry["name"]
        if archive.stat().st_size != entry["size"] or sha256(archive) != entry["sha256"]:
            raise ValueError(f"Archive checksum mismatch: {entry['name']}")
    return manifest


def restore_local(folder: Path, repo: Path, codex_home: Path | None = None) -> dict:
    manifest = verify(folder)
    repo = repo.resolve()
    codex_home = (codex_home or repo / ".reader-codex").resolve()
    roots = {"paper_search": repo, "codex": codex_home, "environment": repo / ".reader-backup/environment"}
    files = {entry["path"]: entry for entry in manifest["files"]}
    if len(files) != len(manifest["files"]):
        raise ValueError("Duplicate backup entries")

    def destination(relative: str) -> Path:
        parts = safe_relative(relative).parts
        root = roots[parts[0]]
        path = root.joinpath(*parts[1:])
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"Restore target escapes its directory: {relative}")
        return path

    for relative, entry in files.items():
        target = destination(relative)
        if target.exists() and (not target.is_file() or sha256(target) != entry["sha256"]):
            raise ValueError(f"Restore would overwrite a different file: {target}")
    seen = set()
    for archive in manifest["archives"]:
        with tarfile.open(folder / archive["name"], "r:gz") as tar:
            for member in tar:
                entry = files.get(member.name)
                if (not member.isfile() or not entry or member.name in seen
                        or entry["archive"] != archive["name"] or member.size != entry["size"]):
                    raise ValueError(f"Unexpected archive entry: {member.name}")
                target = destination(member.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    incoming = tar.extractfile(member)
                    if incoming is None:
                        raise ValueError(f"Missing archive content: {member.name}")
                    with incoming:
                        shutil.copyfileobj(incoming, stream)
                try:
                    if sha256(temporary) != entry["sha256"]:
                        raise ValueError(f"File checksum mismatch: {member.name}")
                    temporary.chmod(entry["mode"] & 0o777)
                    os.utime(temporary, ns=(entry["mtime_ns"], entry["mtime_ns"]))
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
                seen.add(member.name)
    if seen != set(files):
        raise ValueError("Backup is missing manifest files")
    metadata = repo / ".reader-backup"
    metadata.mkdir(parents=True, exist_ok=True)
    shutil.copy2(folder / "manifest.json", metadata / "manifest.json")
    config = codex_home / "config.toml"
    if not config.exists():
        codex_home.mkdir(parents=True, exist_ok=True)
        shutil.copy2(metadata / "environment/codex-config.example.toml", config)
        config.chmod(0o600)
    print(f"Restored {len(seen)} files to {repo}; Codex home: {codex_home}", flush=True)
    return manifest


def hub_api():
    try:
        from modelscope_hub import HubApi
    except ImportError as error:
        raise RuntimeError("Install tools/requirements-backup.txt in an isolated environment") from error
    if not os.environ.get("REQUESTS_CA_BUNDLE") and Path("/etc/ssl/cert.pem").is_file():
        os.environ["REQUESTS_CA_BUNDLE"] = "/etc/ssl/cert.pem"
    return HubApi()


def upload(folder: Path, dataset: str) -> None:
    manifest = verify(folder)
    api = hub_api()
    metadata = api.get_repo(dataset, repo_type="dataset")
    if str(metadata.visibility).lower() not in {"private", "1"}:
        raise ValueError("Personal Reader backups require a private ModelScope dataset")
    prefix = "backups/" + safe_relative(manifest["snapshot_id"]).as_posix()
    tracker = folder.parent / ("." + folder.name + "-upload-cache")

    def progress(event):
        print(json.dumps({key: event[key] for key in
                          ("event", "committed_files", "total_files", "committed_bytes", "total_bytes")
                          if key in event}), flush=True)

    api.upload_folder(dataset, repo_type="dataset", folder_path=folder, path_in_repo=prefix,
                      use_cache=True, tracker_path=tracker, max_workers=4,
                      sync_remote_repo=False, progress_callback=progress,
                      commit_message=f"Back up Paper Reader {manifest['snapshot_id']}")
    pointer = {"snapshot_id": manifest["snapshot_id"], "prefix": prefix,
               "manifest_sha256": sha256(folder / "manifest.json"), "git_commit": manifest["git_commit"]}
    with tempfile.TemporaryDirectory(prefix="reader-backup-pointer-") as temporary:
        pointer_path = Path(temporary) / "LATEST.json"
        pointer_path.write_text(json.dumps(pointer, indent=2) + "\n")
        api.upload_file(dataset, "dataset", pointer_path, "LATEST.json",
                        commit_message=f"Select complete backup {manifest['snapshot_id']}")
    print(f"Published private snapshot: {dataset}/{prefix}", flush=True)


def download(dataset: str, folder: Path, snapshot_id: str | None = None) -> Path:
    api = hub_api()
    folder.mkdir(parents=True, exist_ok=True)
    if snapshot_id:
        prefix = "backups/" + safe_relative(snapshot_id).as_posix()
        manifest_hash = None
    else:
        pointer_path = api.download_file(dataset, "dataset", "LATEST.json", local_dir=folder, force=True)
        pointer = json.loads(Path(pointer_path).read_text())
        prefix = safe_relative(pointer["prefix"]).as_posix()
        manifest_hash = pointer["manifest_sha256"]
    manifest_path = api.download_file(dataset, "dataset", prefix + "/manifest.json", local_dir=folder,
                                      expected_sha256=manifest_hash, force=True)
    snapshot_folder = Path(manifest_path).parent
    manifest = load_manifest(snapshot_folder)
    for entry in manifest["archives"]:
        api.download_file(dataset, "dataset", prefix + "/" + entry["name"], local_dir=folder,
                          expected_sha256=entry["sha256"])
    verify(snapshot_folder)
    return snapshot_folder


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("snapshot")
    create.add_argument("--repo-dir", type=Path, default=REPO)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    publish = commands.add_parser("upload")
    publish.add_argument("--snapshot-dir", type=Path, required=True)
    publish.add_argument("--dataset", default=DEFAULT_DATASET)
    check = commands.add_parser("verify")
    check.add_argument("--snapshot-dir", type=Path, required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--repo-dir", type=Path, default=REPO)
    restore.add_argument("--dataset", default=DEFAULT_DATASET)
    restore.add_argument("--snapshot-id")
    restore.add_argument("--snapshot-dir", type=Path, help="Restore an already downloaded local snapshot")
    restore.add_argument("--download-dir", type=Path, default=Path.home() / ".cache/paper-reader-backups")
    restore.add_argument("--codex-home", type=Path)
    args = parser.parse_args()
    if args.command == "snapshot":
        snapshot(args.repo_dir, args.output, args.codex_home)
    elif args.command == "upload":
        upload(args.snapshot_dir, args.dataset)
    elif args.command == "verify":
        manifest = verify(args.snapshot_dir)
        print(f"Verified {len(manifest['files'])} files in {len(manifest['archives'])} archives")
    else:
        folder = args.snapshot_dir or download(args.dataset, args.download_dir, args.snapshot_id)
        restore_local(folder, args.repo_dir, args.codex_home)


if __name__ == "__main__":
    main()
