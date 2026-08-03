#!/usr/bin/env python3
"""Translate every PDF cited by the task's review papers, one PDF at a time."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml


READER_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = READER_DIR.parent
DEFAULT_TASK_ID = "paper-research-base-knowledge-about-llm-20260717"
PDF_CITATION = re.compile(r"\[PDF:([A-Za-z0-9._-]+)\s+p", re.IGNORECASE)
TERMINAL_STATUSES = {"completed", "partial", "failed", "stopped", "interrupted", "idle"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ordered_review_files(task_dir: Path) -> list[Path]:
    available = {path.name: path for path in (task_dir / "papers").glob("*.md")}
    config = yaml.safe_load((READER_DIR / "learning-path.yml").read_text(encoding="utf-8")) or {}
    ordered = []
    for stage in config.get("stages", []):
        for item in stage.get("papers", []):
            filename = str(item.get("file", ""))
            if filename in available:
                ordered.append(available.pop(filename))
    ordered.extend(sorted(available.values()))
    return ordered


def target_sources(task_dir: Path) -> list[str]:
    sources = []
    seen = set()
    for paper in ordered_review_files(task_dir):
        for source_id in PDF_CITATION.findall(paper.read_text(encoding="utf-8")):
            if source_id not in seen:
                seen.add(source_id)
                sources.append(source_id)
    missing = [
        source_id
        for source_id in sources
        if not (task_dir / "sources" / source_id / "paper.pdf").is_file()
    ]
    if missing:
        raise RuntimeError("Missing cited PDFs: " + ", ".join(missing))
    return sources


class ReaderApi:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.origin = self.base_url
        self.token = str(self.request("/api/bootstrap")["token"])

    def request(self, path: str, value: dict | None = None) -> dict:
        data = None if value is None else json.dumps(value).encode("utf-8")
        headers = {"Origin": self.origin}
        if data is not None:
            headers.update({"Content-Type": "application/json", "X-Reader-Token": self.token})
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method="POST" if data is not None else "GET",
        )
        last_error = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return json.load(response)
            except (OSError, urllib.error.HTTPError) as error:
                last_error = error
                if attempt < 4:
                    time.sleep(min(2 ** attempt, 10))
        raise RuntimeError(f"Reader API request failed: {path}: {last_error}")

    def status(self, source_id: str) -> dict:
        query = urllib.parse.urlencode({"source_id": source_id})
        return self.request(f"/api/translation/full?{query}")

    def start(self, source_id: str, concurrency: int = 8) -> dict:
        return self.request(
            "/api/translation/full/start",
            {"source_id": source_id, "page": 1, "concurrency": concurrency},
        )

    def stop(self, source_id: str) -> dict:
        return self.request("/api/translation/full/stop", {"source_id": source_id})

    def translate_text_only(self, source_id: str, page: int, mask_literals: bool = False) -> dict:
        return self.request(
            "/api/translation/page",
            {
                "source_id": source_id,
                "page": page,
                "text_only": True,
                "mask_literals": mask_literals,
            },
        )


def save_queue(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(args: argparse.Namespace) -> None:
    task_dir = (REPO_DIR / "tasks" / args.task_id).resolve()
    sources = target_sources(task_dir)
    api = ReaderApi(args.base_url)
    queue_path = READER_DIR / "user-data" / args.task_id / "translation-queue.json"
    queue = {
        "task_id": args.task_id,
        "status": "running",
        "sources": sources,
        "total_sources": len(sources),
        "started_at": now_iso(),
        "updated_at": now_iso(),
    }
    save_queue(queue_path, queue)

    current_source = None
    try:
        for source_index, source_id in enumerate(sources, start=1):
            current_source = source_id
            status = api.status(source_id)
            total = int(status["total"])
            completed = int(status["completed"])
            if completed < total and "content_filter" in str(status.get("last_error", "")):
                pages_dir = READER_DIR / "user-data" / args.task_id / "translations" / source_id / "pages"
                missing_pages = [
                    page for page in range(1, total + 1)
                    if not (pages_dir / f"{page:04d}.json").is_file()
                ]
                print(
                    f"[{source_index}/{len(sources)}] resume text-only fallback {source_id}: "
                    f"pages={','.join(map(str, missing_pages))}",
                    flush=True,
                )
                for page in missing_pages:
                    api.translate_text_only(source_id, page, mask_literals=True)
                status = api.status(source_id)
                completed = int(status["completed"])
            if completed >= total:
                print(f"[{source_index}/{len(sources)}] skip {source_id}: cached {completed}/{total}", flush=True)
                continue

            no_progress_rounds = 0
            # Repeated page failures are usually complex tables or a slow upstream
            # response. Resume those PDFs conservatively while keeping the global cap.
            concurrency = 4 if int(status.get("failures", 0)) >= 3 else 8
            while completed < total:
                before = completed
                status = api.start(source_id, concurrency)
                print(
                    f"[{source_index}/{len(sources)}] start {source_id}: {completed}/{total}, "
                    f"concurrency={status.get('concurrency', 8)}",
                    flush=True,
                )
                last_report = 0.0
                while True:
                    time.sleep(args.poll_seconds)
                    status = api.status(source_id)
                    completed = int(status["completed"])
                    total = int(status["total"])
                    now = time.monotonic()
                    if now - last_report >= args.report_seconds or status.get("status") in TERMINAL_STATUSES:
                        active = ",".join(str(page) for page in status.get("current_pages", [])) or "-"
                        print(
                            f"[{source_index}/{len(sources)}] {source_id}: {completed}/{total} "
                            f"status={status.get('status')} active={active} failures={status.get('failures', 0)}",
                            flush=True,
                        )
                        last_report = now
                    queue.update(
                        current_source=source_id,
                        source_index=source_index,
                        completed_pages=completed,
                        total_pages=total,
                        source_status=status.get("status"),
                        updated_at=now_iso(),
                    )
                    save_queue(queue_path, queue)
                    if status.get("status") in TERMINAL_STATUSES:
                        break

                if completed >= total:
                    break
                no_progress_rounds = no_progress_rounds + 1 if completed <= before else 0
                if completed <= before and concurrency > 1:
                    concurrency = max(1, concurrency // 2)
                    print(
                        f"[{source_index}/{len(sources)}] reduce concurrency {source_id}: {concurrency}",
                        flush=True,
                    )
                if no_progress_rounds >= args.max_no_progress_rounds:
                    last_error = str(status.get("last_error", ""))
                    if "content_filter" in last_error:
                        pages_dir = READER_DIR / "user-data" / args.task_id / "translations" / source_id / "pages"
                        missing_pages = [
                            page for page in range(1, total + 1)
                            if not (pages_dir / f"{page:04d}.json").is_file()
                        ]
                        print(
                            f"[{source_index}/{len(sources)}] text-only fallback {source_id}: "
                            f"pages={','.join(map(str, missing_pages))}",
                            flush=True,
                        )
                        for page in missing_pages:
                            api.translate_text_only(source_id, page, mask_literals=True)
                        status = api.status(source_id)
                        completed = int(status["completed"])
                        if completed >= total:
                            break
                    raise RuntimeError(
                        f"{source_id} made no progress after {no_progress_rounds} retry rounds: "
                        f"{completed}/{total}; {last_error}"
                    )
                print(
                    f"[{source_index}/{len(sources)}] retry {source_id}: {completed}/{total}; "
                    f"{status.get('last_error', '')}",
                    flush=True,
                )

        queue.update(status="completed", current_source=None, finished_at=now_iso(), updated_at=now_iso())
        save_queue(queue_path, queue)
        print(f"Translation queue completed: {len(sources)} sources", flush=True)
    except KeyboardInterrupt:
        if current_source:
            api.stop(current_source)
        queue.update(status="stopped", current_source=current_source, updated_at=now_iso())
        save_queue(queue_path, queue)
        raise
    except Exception as error:
        queue.update(status="failed", current_source=current_source, error=str(error), updated_at=now_iso())
        save_queue(queue_path, queue)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument("--report-seconds", type=float, default=15.0)
    parser.add_argument("--max-no-progress-rounds", type=int, default=3)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
