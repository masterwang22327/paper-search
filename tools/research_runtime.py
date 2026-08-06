#!/usr/bin/env python3
"""Initialize and guard runs of a prompt-driven, long-lived paper research task.

This tool never starts Codex. The interactive Codex session owns the research
loop; this helper only creates the durable task workspace and returns a
machine-readable time/quota gate before each bounded work unit.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
TASKS_ROOT = ROOT / "tasks"
TOKEN_CHECKER = WORKSPACE / "check_token.py"
TOKEN_LOCK = Path(tempfile.gettempdir()) / "paper-research-token-monitor.lock"
TZ = ZoneInfo("Asia/Shanghai")
SCHEMA_VERSION = 2
TASK_ID_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?")
RUN_ID_RE = re.compile(r"run-[0-9]{8}t[0-9]{6}-[a-f0-9]{8}")
REQUIRED_FILES = ("TASK.md", "STATUS.md", "REPORT.md", "SOURCES.md", "RUN_HISTORY.md")
REQUIRED_DIRS = ("sources", "papers", "state", "state/runs", "state/handoffs")


class RuntimeError_(RuntimeError):
    """Concise, user-facing runtime error."""


def now_bjt() -> datetime:
    return datetime.now(TZ)


def iso(value: datetime) -> str:
    return value.astimezone(TZ).isoformat(timespec="seconds")


def parse_deadline(value: str) -> datetime:
    normalized = value.strip().replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise RuntimeError_(
            "deadline must be ISO-8601, for example 2026-07-20T23:00:00+08:00"
        ) from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed.astimezone(TZ)


def next_midnight_bjt(current: datetime) -> datetime:
    """Return the first Beijing midnight strictly after current."""
    local = current.astimezone(TZ)
    tomorrow = local.date() + timedelta(days=1)
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=TZ)


def validate_task_id(value: str) -> str:
    task_id = value.strip()
    if not TASK_ID_RE.fullmatch(task_id):
        raise RuntimeError_(
            "task id must use 1-64 lowercase letters, digits, or hyphens and "
            "cannot start or end with a hyphen"
        )
    return task_id


def validate_positive_int(
    name: str, value: int, minimum: int, maximum: int | None = None,
) -> int:
    if value < minimum or (maximum is not None and value > maximum):
        if maximum is None:
            raise RuntimeError_(f"{name} must be at least {minimum}")
        raise RuntimeError_(f"{name} must be between {minimum} and {maximum}")
    return value


def task_dir(task_id: str) -> Path:
    return TASKS_ROOT / validate_task_id(task_id)


def current_run_path(path: Path) -> Path:
    return path / "state" / "current-run.json"


def compatibility_runtime_path(path: Path) -> Path:
    return path / "state" / "runtime.json"


def runs_dir(path: Path) -> Path:
    return path / "state" / "runs"


def run_dir(path: Path, run_id: str) -> Path:
    if not RUN_ID_RE.fullmatch(run_id):
        raise RuntimeError_(f"invalid run id: {run_id}")
    return runs_dir(path) / run_id


def run_runtime_path(path: Path, run_id: str) -> Path:
    return run_dir(path, run_id) / "runtime.json"


def run_quota_path(path: Path, run_id: str) -> Path:
    return run_dir(path, run_id) / "quota.json"


def new_run_id(current: datetime) -> str:
    return f"run-{current.strftime('%Y%m%dt%H%M%S')}-{uuid4().hex[:8]}"


def atomic_write_text(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, payload: dict[str, Any], mode: int = 0o644) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n", mode)


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RuntimeError_(f"missing runtime file: {path}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError_(f"invalid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise RuntimeError_(f"expected a JSON object: {path}")
    return payload


def append_event(path: Path, event: dict[str, Any]) -> None:
    events = path
    events.parent.mkdir(parents=True, exist_ok=True)
    with events.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


@contextmanager
def task_lock(path: Path):
    lock_path = path / "state" / "runtime.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError_(
                f"another runtime command is active for this task: {path.name}"
            ) from error
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_compatibility_pointer(path: Path, runtime: dict[str, Any]) -> None:
    write_json(
        compatibility_runtime_path(path),
        {
            "schema_version": SCHEMA_VERSION,
            "task_id": runtime["task_id"],
            "current_run_id": runtime["run_id"],
            "runtime_path": f"state/runs/{runtime['run_id']}/runtime.json",
            "note": "compatibility pointer; runtime state is stored in the run directory",
        },
        mode=0o600,
    )


def save_current_run(path: Path, runtime: dict[str, Any]) -> None:
    run_id = str(runtime["run_id"])
    write_json(run_runtime_path(path, run_id), runtime, mode=0o600)
    write_json(
        current_run_path(path),
        {
            "schema_version": SCHEMA_VERSION,
            "task_id": runtime["task_id"],
            "run_id": run_id,
            "runtime_path": f"state/runs/{run_id}/runtime.json",
            "updated_at": runtime["updated_at"],
        },
        mode=0o600,
    )
    write_compatibility_pointer(path, runtime)


def load_current_run(path: Path) -> dict[str, Any]:
    migrate_legacy_runtime(path)
    pointer = load_json(current_run_path(path))
    if pointer.get("task_id") != path.name:
        raise RuntimeError_(f"current run belongs to another task: {current_run_path(path)}")
    run_id = str(pointer.get("run_id", ""))
    runtime = load_json(run_runtime_path(path, run_id))
    if runtime.get("task_id") != path.name or runtime.get("run_id") != run_id:
        raise RuntimeError_(f"invalid current run identity: {run_runtime_path(path, run_id)}")
    return runtime


def ensure_run_history(path: Path) -> None:
    history = path / "RUN_HISTORY.md"
    if not history.exists():
        atomic_write_text(
            history,
            "# Run History\n\n"
            "Each entry is an immutable execution contract for this long-lived research task. "
            "The canonical report, sources, and paper reviews remain task-level files.\n",
        )


def append_run_history(path: Path, runtime: dict[str, Any], action: str) -> None:
    ensure_run_history(path)
    history = path / "RUN_HISTORY.md"
    with history.open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n## {runtime['run_id']}\n\n"
            f"- Action: `{action}`\n"
            f"- Created: `{runtime['created_at']}`\n"
            f"- Deadline: `{runtime['deadline']}`\n"
            f"- Deadline mode: `{runtime.get('deadline_mode', 'legacy-unknown')}`\n"
            f"- Duration days: `{runtime.get('duration_days') if runtime.get('duration_days') is not None else 'inactive'}`\n"
            f"- Goal token budget: `{runtime['goal_token_budget']}`\n"
            f"- External quota stop: `{runtime['quota_stop_usd']} USD`\n"
            f"- Quota check interval: `{runtime['quota_check_minutes']} minutes`\n"
            f"- Work unit: `{runtime['work_unit_minutes']} minutes`\n"
            f"- Predecessor run: `{runtime.get('predecessor_run_id') or 'none'}`\n"
            f"- Runtime: `state/runs/{runtime['run_id']}/runtime.json`\n"
        )


def mark_history_terminal(path: Path, runtime: dict[str, Any]) -> None:
    marker = run_dir(path, str(runtime["run_id"])) / "history-terminal-recorded"
    if marker.exists():
        return
    with (path / "RUN_HISTORY.md").open("a", encoding="utf-8") as handle:
        handle.write(
            f"\n- Run `{runtime['run_id']}` terminated at `{runtime['updated_at']}`: "
            f"`{runtime.get('terminal_reason') or 'unknown'}`.\n"
        )
    atomic_write_text(marker, runtime["updated_at"] + "\n", mode=0o600)


def migrate_legacy_runtime(path: Path) -> dict[str, Any] | None:
    if current_run_path(path).exists():
        return None
    legacy_path = compatibility_runtime_path(path)
    if not legacy_path.exists():
        return None
    legacy = load_json(legacy_path)
    if "current_run_id" in legacy:
        run_id = str(legacy.get("current_run_id", ""))
        runtime = load_json(run_runtime_path(path, run_id))
        save_current_run(path, runtime)
        return runtime
    if legacy.get("task_id") != path.name:
        raise RuntimeError_(f"legacy runtime belongs to another task: {legacy_path}")

    created = parse_timestamp(legacy.get("created_at")) or now_bjt()
    legacy_identity = re.sub(r"[^a-f0-9]", "", str(legacy.get("run_id") or "").lower())
    stable_material = json.dumps(
        {
            "task_id": legacy.get("task_id"),
            "created_at": legacy.get("created_at"),
            "deadline": legacy.get("deadline"),
        },
        sort_keys=True,
    ).encode("utf-8")
    suffix = (legacy_identity + hashlib.sha256(stable_material).hexdigest())[:8]
    run_id = f"run-{created.strftime('%Y%m%dt%H%M%S')}-{suffix}"
    migrated = dict(legacy)
    migrated.update(
        {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "predecessor_run_id": None,
            "migrated_from": "state/runtime.json",
            "created_at": str(legacy.get("created_at") or iso(created)),
            "updated_at": str(legacy.get("updated_at") or iso(now_bjt())),
        }
    )
    target = run_dir(path, run_id)
    target.mkdir(parents=True, exist_ok=True)
    existing_target = target / "runtime.json"
    if existing_target.exists():
        partial = load_json(existing_target)
        if partial.get("task_id") != path.name or partial.get("run_id") != run_id:
            raise RuntimeError_(f"conflicting partial legacy migration: {target}")
    legacy_quota = path / "state" / "quota.json"
    if legacy_quota.exists():
        atomic_write_text(target / "quota.json", legacy_quota.read_text(encoding="utf-8"), mode=0o600)
    legacy_events = path / "state" / "events.jsonl"
    if legacy_events.exists():
        atomic_write_text(target / "events.jsonl", legacy_events.read_text(encoding="utf-8"), mode=0o600)
    save_current_run(path, migrated)
    if legacy_quota.exists():
        os.replace(legacy_quota, target / "quota.json")
    if legacy_events.exists():
        os.replace(legacy_events, target / "events.jsonl")
    append_run_history(path, migrated, "migrated legacy run")
    append_event(
        target / "events.jsonl",
        {"at": iso(now_bjt()), "event": "legacy_runtime_migrated", "run_id": run_id},
    )
    if migrated.get("terminal_reason") or migrated.get("status") == "stopped":
        mark_history_terminal(path, migrated)
    return migrated


def scaffold_texts(task_id: str, created_at: str, deadline: str) -> dict[str, str]:
    return {
        "TASK.md": (
            "# Research Task\n\n"
            f"- Task ID: `{task_id}`\n"
            f"- Created: `{created_at}`\n\n"
            "> The launch prompt must replace the sections below before research begins.\n\n"
            "## Research Question\n\nPending launch-prompt materialization.\n\n"
            "## Scope, Exclusions, Deliverables, And Completion Evidence\n\n"
            "Pending launch-prompt materialization.\n"
        ),
        "STATUS.md": (
            "# Research Status\n\n"
            "- State: `initializing`\n"
            f"- Updated: `{created_at}`\n"
            f"- Current run deadline: `{deadline}`\n"
            "- Last runtime gate: not checked\n"
            "- Last quota check: not checked\n\n"
            "## Completed Increments\n\n- None yet.\n\n"
            "## Active Queue\n\n- Materialize TASK.md from the launch prompt.\n\n"
            "## Blockers And Uncertainty\n\n- None yet.\n\n"
            "## Next Exact Action\n\n- Run the first forced runtime/quota gate.\n"
        ),
        "REPORT.md": (
            "# Research Report\n\n"
            "Build this report incrementally from saved evidence. Do not replace uncertainty "
            "with unsupported summary.\n"
        ),
        "SOURCES.md": (
            "# Source Catalog\n\n"
            "| Stable ID | Version | Type | Official URL | Retrieved | Evidence Location | Local Path | Used For |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        ),
        "RUN_HISTORY.md": (
            "# Run History\n\n"
            "Each entry is an immutable execution contract for this long-lived research task. "
            "The canonical report, sources, and paper reviews remain task-level files.\n"
        ),
    }


def build_runtime(
    *,
    task_id: str,
    run_id: str,
    current: datetime,
    deadline: datetime,
    deadline_mode: str,
    duration_days: int | None,
    args: argparse.Namespace,
    predecessor_run_id: str | None,
) -> dict[str, Any]:
    created_at = iso(current)
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "run_id": run_id,
        "predecessor_run_id": predecessor_run_id,
        "status": "active",
        "timezone": "Asia/Shanghai",
        "created_at": created_at,
        "updated_at": created_at,
        "deadline": iso(deadline),
        "deadline_mode": deadline_mode,
        "duration_days": duration_days,
        "goal_token_budget": args.goal_token_budget,
        "quota_stop_usd": args.quota_stop_usd,
        "quota_check_minutes": args.quota_check_minutes,
        "work_unit_minutes": args.work_unit_minutes,
        "last_gate_at": None,
        "last_decision": None,
        "last_quota_attempt_at": None,
        "last_quota_success_at": None,
        "last_quota_error": None,
        "resume_not_before": None,
        "wait_reason": None,
        "terminal_reason": None,
    }


def initialize(args: argparse.Namespace) -> dict[str, Any]:
    task_id = validate_task_id(args.task_id)
    current = now_bjt()
    validate_positive_int("goal token budget", args.goal_token_budget, 1_000)
    validate_positive_int("quota check minutes", args.quota_check_minutes, 1, 240)
    validate_positive_int("work unit minutes", args.work_unit_minutes, 1, 60)
    validate_positive_int("duration days", args.duration_days, 1, 365)
    if not math.isfinite(args.quota_stop_usd) or args.quota_stop_usd < 0:
        raise RuntimeError_("quota stop USD must be a finite nonnegative number")

    path = task_dir(task_id)
    deadline_mode = "auto" if args.deadline.strip().upper() == "AUTO" else "absolute"
    path.mkdir(parents=True, exist_ok=True)
    with task_lock(path):
        has_runtime = current_run_path(path).exists() or compatibility_runtime_path(path).exists()
        if has_runtime:
            existing = load_current_run(path)
            existing_deadline = parse_deadline(str(existing["deadline"]))
            terminal = bool(
                existing.get("status") == "stopped"
                or existing.get("terminal_reason")
                or current >= existing_deadline
            )
            if current >= existing_deadline and not existing.get("terminal_reason"):
                existing["status"] = "stopped"
                existing["terminal_reason"] = "STOP_DEADLINE"
                existing["last_decision"] = "STOP_DEADLINE"
                existing["updated_at"] = iso(current)
                save_current_run(path, existing)
                append_event(
                    run_dir(path, str(existing["run_id"])) / "events.jsonl",
                    {"at": iso(current), "event": "deadline_observed_during_init"},
                )
                mark_history_terminal(path, existing)

            if not terminal:
                deadline = existing_deadline if deadline_mode == "auto" else parse_deadline(args.deadline)
                requested = {
                    "deadline": iso(deadline),
                    "goal_token_budget": args.goal_token_budget,
                    "quota_stop_usd": args.quota_stop_usd,
                    "quota_check_minutes": args.quota_check_minutes,
                    "work_unit_minutes": args.work_unit_minutes,
                    "deadline_mode": deadline_mode,
                    "duration_days": args.duration_days if deadline_mode == "auto" else None,
                }
                mismatches = {
                    key: {"existing": existing.get(key), "requested": value}
                    for key, value in requested.items()
                    if existing.get(key) != value
                }
                if mismatches:
                    raise RuntimeError_(
                        "the current run is still active and its contract cannot change; "
                        f"resume with the original settings: {json.dumps(mismatches)}"
                    )
                return {
                    "status": "resumed",
                    "task_id": task_id,
                    "task_dir": str(path),
                    "run_id": existing["run_id"],
                    "runtime": existing,
                    "warning": "the active run contract was preserved",
                }

            deadline = (
                current + timedelta(days=args.duration_days)
                if deadline_mode == "auto"
                else parse_deadline(args.deadline)
            )
            if deadline <= current:
                raise RuntimeError_(
                    "the previous run is terminal; set AUTO or a new future deadline to continue "
                    "the same task without copying its canonical artifacts"
                )
            duration_days = args.duration_days if deadline_mode == "auto" else None
            run_id = new_run_id(current)
            runtime = build_runtime(
                task_id=task_id,
                run_id=run_id,
                current=current,
                deadline=deadline,
                deadline_mode=deadline_mode,
                duration_days=duration_days,
                args=args,
                predecessor_run_id=str(existing["run_id"]),
            )
            run_dir(path, run_id).mkdir(parents=True, exist_ok=False)
            save_current_run(path, runtime)
            append_run_history(path, runtime, "continued existing task")
            append_event(
                run_dir(path, run_id) / "events.jsonl",
                {
                    "at": runtime["created_at"],
                    "event": "continuation_run_initialized",
                    "predecessor_run_id": existing["run_id"],
                    "deadline": runtime["deadline"],
                },
            )
            return {
                "status": "continued",
                "task_id": task_id,
                "task_dir": str(path),
                "run_id": run_id,
                "predecessor_run_id": existing["run_id"],
                "runtime": runtime,
                "warning": "canonical task artifacts were preserved in place",
            }

        if any(path.iterdir()):
            entries = [entry.name for entry in path.iterdir() if entry.name != "state"]
            state_entries = list((path / "state").iterdir()) if (path / "state").exists() else []
            if entries or any(entry.name != "runtime.lock" for entry in state_entries):
                raise RuntimeError_(
                    f"task directory exists without a recognized runtime contract: {path}; "
                    "migrate it explicitly or use a new task id"
                )
        deadline = (
            current + timedelta(days=args.duration_days)
            if deadline_mode == "auto"
            else parse_deadline(args.deadline)
        )
        if deadline <= current:
            raise RuntimeError_("deadline must be in the future for a new task")
        duration_days = args.duration_days if deadline_mode == "auto" else None
        created_at = iso(current)
        deadline_text = iso(deadline)
        for name in REQUIRED_DIRS:
            (path / name).mkdir(parents=True, exist_ok=True)
        for name, content in scaffold_texts(task_id, created_at, deadline_text).items():
            atomic_write_text(path / name, content)
        run_id = new_run_id(current)
        runtime = build_runtime(
            task_id=task_id,
            run_id=run_id,
            current=current,
            deadline=deadline,
            deadline_mode=deadline_mode,
            duration_days=duration_days,
            args=args,
            predecessor_run_id=None,
        )
        run_dir(path, run_id).mkdir(parents=True, exist_ok=False)
        save_current_run(path, runtime)
        append_run_history(path, runtime, "created task and first run")
        append_event(
            run_dir(path, run_id) / "events.jsonl",
            {"at": created_at, "event": "initialized", "deadline": deadline_text},
        )
        return {
            "status": "created",
            "task_id": task_id,
            "task_dir": str(path),
            "run_id": run_id,
            "runtime": runtime,
        }


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(TZ)


def quota_check_due(runtime: dict[str, Any], current: datetime, force: bool) -> bool:
    if force:
        return True
    last = parse_timestamp(runtime.get("last_quota_attempt_at"))
    resume_not_before = parse_timestamp(runtime.get("resume_not_before"))
    if runtime.get("status") == "waiting_quota" and resume_not_before is not None:
        if current < resume_not_before:
            return False
        if last is None or last < resume_not_before:
            return True
    if last is None:
        return True
    normal_interval = int(runtime["quota_check_minutes"])
    retry_interval = min(5, normal_interval) if runtime.get("last_quota_error") else normal_interval
    return (current - last).total_seconds() >= retry_interval * 60


def refresh_quota(quota_file: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not TOKEN_CHECKER.is_file():
        return None, f"quota checker is unavailable: {TOKEN_CHECKER}"
    command = [
        sys.executable,
        str(TOKEN_CHECKER),
        "--state",
        str(quota_file),
        "--lock-file",
        str(TOKEN_LOCK),
        "--lock-timeout",
        "60",
        "--total-timeout",
        "50",
        "--json",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=125,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return None, f"quota command failed: {error}"
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        return None, detail[-1] if detail else f"quota checker exited {result.returncode}"
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "quota checker returned invalid JSON"
    if not isinstance(payload, dict):
        return None, "quota checker returned a non-object payload"
    return payload, None


def finite_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_optional_quota(quota_file: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(quota_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def decide(
    runtime: dict[str, Any],
    current: datetime,
    quota: dict[str, Any] | None,
) -> dict[str, Any]:
    deadline = parse_deadline(str(runtime["deadline"]))
    remaining_seconds = max(0, int((deadline - current).total_seconds()))
    daily_remaining = finite_number(quota.get("daily_remaining")) if quota else None
    quota_checked_at = parse_timestamp(quota.get("checked_at")) if quota else None
    quota_fresh = bool(
        quota_checked_at
        and not runtime.get("last_quota_error")
        and quota_checked_at.date() == current.date()
        and (current - quota_checked_at).total_seconds()
        <= max(30, int(runtime["quota_check_minutes"]) * 2) * 60
    )

    terminal_reason = runtime.get("terminal_reason")
    waiting_for_quota = bool(
        runtime.get("status") == "waiting_quota"
        or runtime.get("wait_reason") == "daily_quota_exhausted"
        or terminal_reason == "STOP_QUOTA"  # Migrate the former sticky state safely.
    )
    resume_not_before = parse_timestamp(runtime.get("resume_not_before"))
    if waiting_for_quota and resume_not_before is None:
        previous_update = parse_timestamp(runtime.get("updated_at"))
        if previous_update is not None and previous_update.date() < current.date():
            resume_not_before = current.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            resume_not_before = next_midnight_bjt(current)

    if terminal_reason == "STOP_DEADLINE" or current >= deadline:
        decision = "STOP_DEADLINE"
        reason = "hard deadline reached"
        decision_resume = None
    elif waiting_for_quota:
        if resume_not_before is not None and current < resume_not_before:
            decision = "WAIT_QUOTA"
            reason = "daily external quota is exhausted; wait for the next Beijing midnight"
            decision_resume = resume_not_before
        elif quota_fresh and daily_remaining is not None and daily_remaining > float(
            runtime["quota_stop_usd"]
        ):
            decision = "CONTINUE"
            reason = "daily external quota recovered after the scheduled reset"
            decision_resume = None
        elif quota_fresh and daily_remaining is not None:
            decision = "WAIT_QUOTA"
            reason = "daily external quota is still exhausted after a reset check"
            decision_resume = next_midnight_bjt(current)
        else:
            decision = "WAIT_QUOTA"
            reason = "quota recovery has not yet been verified; retry without ending the task"
            decision_resume = resume_not_before
    elif quota_fresh and daily_remaining is not None and daily_remaining <= float(runtime["quota_stop_usd"]):
        decision = "WAIT_QUOTA"
        reason = "fresh daily external quota reached the wait threshold"
        decision_resume = next_midnight_bjt(current)
    elif remaining_seconds <= 60:
        decision = "WAIT_DEADLINE"
        reason = "final checkpoint should be complete; poll until the hard deadline"
        decision_resume = None
    elif remaining_seconds <= int(runtime["work_unit_minutes"]) * 60:
        decision = "WRAP_UP"
        reason = "do not start a work unit that could cross the hard deadline"
        decision_resume = None
    else:
        decision = "CONTINUE"
        reason = "time and verified quota state do not require stopping"
        decision_resume = None

    return {
        "decision": decision,
        "reason": reason,
        "now": iso(current),
        "deadline": iso(deadline),
        "remaining_seconds": remaining_seconds,
        "daily_remaining_usd": daily_remaining,
        "quota_checked_at": iso(quota_checked_at) if quota_checked_at else None,
        "quota_fresh": quota_fresh,
        "resume_not_before": iso(decision_resume) if decision_resume else None,
        "wait_reason": "daily_quota_exhausted" if decision == "WAIT_QUOTA" else None,
        "goal_token_budget": runtime["goal_token_budget"],
        "recommended_max_work_seconds": max(
            0,
            min(int(runtime["work_unit_minutes"]) * 60, max(0, remaining_seconds - 60)),
        ) if decision not in {"WAIT_QUOTA", "STOP_DEADLINE"} else 0,
    }


def gate(args: argparse.Namespace) -> dict[str, Any]:
    path = task_dir(args.task_id)
    with task_lock(path):
        runtime = load_current_run(path)
        run_id = str(runtime["run_id"])
        current = now_bjt()
        deadline = parse_deadline(str(runtime["deadline"]))
        quota_file = run_quota_path(path, run_id)
        quota = load_optional_quota(quota_file)

        if current < deadline and quota_check_due(runtime, current, args.force_quota):
            runtime["last_quota_attempt_at"] = iso(current)
            refreshed, error = refresh_quota(quota_file)
            if refreshed is not None:
                quota = refreshed
                runtime["last_quota_success_at"] = str(refreshed.get("checked_at") or iso(current))
                runtime["last_quota_error"] = None
            else:
                runtime["last_quota_error"] = error

        payload = decide(runtime, current, quota)
        payload["task_id"] = args.task_id
        payload["task_dir"] = str(path)
        payload["run_id"] = run_id
        payload["run_dir"] = str(run_dir(path, run_id))
        payload["quota_error"] = runtime.get("last_quota_error")
        runtime["last_gate_at"] = payload["now"]
        runtime["last_decision"] = payload["decision"]
        runtime["updated_at"] = payload["now"]
        if payload["decision"] == "STOP_DEADLINE":
            runtime["status"] = "stopped"
            runtime["terminal_reason"] = payload["decision"]
            runtime["resume_not_before"] = None
            runtime["wait_reason"] = None
        elif payload["decision"] == "WAIT_QUOTA":
            runtime["status"] = "waiting_quota"
            runtime["terminal_reason"] = None
            runtime["resume_not_before"] = payload["resume_not_before"]
            runtime["wait_reason"] = payload["wait_reason"]
        else:
            runtime["status"] = "active"
            runtime["terminal_reason"] = None
            runtime["resume_not_before"] = None
            runtime["wait_reason"] = None
        save_current_run(path, runtime)
        append_event(
            run_dir(path, run_id) / "events.jsonl",
            {
                "at": payload["now"],
                "event": "gate",
                "decision": payload["decision"],
                "remaining_seconds": payload["remaining_seconds"],
                "daily_remaining_usd": payload["daily_remaining_usd"],
                "resume_not_before": payload["resume_not_before"],
                "quota_error": payload["quota_error"],
            },
        )
        if payload["decision"] == "STOP_DEADLINE":
            mark_history_terminal(path, runtime)
        return payload


def wait_quota(args: argparse.Namespace) -> dict[str, Any]:
    """Sleep without consuming research work until quota recovers or time expires."""
    validate_positive_int("poll seconds", args.poll_seconds, 5, 60)
    path = task_dir(args.task_id)

    while True:
        with task_lock(path):
            runtime = load_current_run(path)
            current = now_bjt()
            payload = decide(
                runtime,
                current,
                load_optional_quota(run_quota_path(path, str(runtime["run_id"]))),
            )
        if payload["decision"] == "STOP_DEADLINE":
            return gate(Namespace(task_id=args.task_id, force_quota=False))
        if payload["decision"] != "WAIT_QUOTA":
            return gate(Namespace(task_id=args.task_id, force_quota=False))

        deadline = parse_deadline(str(runtime["deadline"]))
        resume = parse_timestamp(payload.get("resume_not_before")) or current
        wake_at = min(deadline, resume)
        seconds_to_wake = (wake_at - current).total_seconds()
        if seconds_to_wake > 0:
            time.sleep(min(float(args.poll_seconds), seconds_to_wake))
            continue

        result = gate(Namespace(task_id=args.task_id, force_quota=current < deadline))
        if result["decision"] != "WAIT_QUOTA":
            return result

        next_resume = parse_timestamp(result.get("resume_not_before"))
        if next_resume is None or next_resume <= now_bjt():
            time.sleep(float(args.poll_seconds))


def status(args: argparse.Namespace) -> dict[str, Any]:
    path = task_dir(args.task_id)
    with task_lock(path):
        runtime = load_current_run(path)
        run_id = str(runtime["run_id"])
        payload = decide(runtime, now_bjt(), load_optional_quota(run_quota_path(path, run_id)))
        payload.update(
            {
                "task_id": args.task_id,
                "task_dir": str(path),
                "run_id": run_id,
                "run_dir": str(run_dir(path, run_id)),
                "runtime_status": runtime.get("status"),
                "last_gate_at": runtime.get("last_gate_at"),
                "last_decision": runtime.get("last_decision"),
                "quota_error": runtime.get("last_quota_error"),
            }
        )
        return payload


def close_run(args: argparse.Namespace) -> dict[str, Any]:
    path = task_dir(args.task_id)
    with task_lock(path):
        runtime = load_current_run(path)
        if runtime.get("status") == "stopped" or runtime.get("terminal_reason"):
            return {
                "status": "already_closed",
                "task_id": args.task_id,
                "run_id": runtime["run_id"],
                "reason": runtime.get("terminal_reason"),
            }
        current = now_bjt()
        runtime["status"] = "stopped"
        runtime["terminal_reason"] = args.reason
        runtime["last_decision"] = args.reason
        runtime["updated_at"] = iso(current)
        runtime["resume_not_before"] = None
        runtime["wait_reason"] = None
        save_current_run(path, runtime)
        append_event(
            run_dir(path, str(runtime["run_id"])) / "events.jsonl",
            {"at": iso(current), "event": "run_closed", "reason": args.reason},
        )
        mark_history_terminal(path, runtime)
        return {
            "status": "closed",
            "task_id": args.task_id,
            "task_dir": str(path),
            "run_id": runtime["run_id"],
            "reason": args.reason,
        }


def validate(args: argparse.Namespace) -> dict[str, Any]:
    path = task_dir(args.task_id)
    errors: list[str] = []
    with task_lock(path):
        try:
            runtime = load_current_run(path)
        except RuntimeError_ as error:
            runtime = {}
            errors.append(str(error))
    if runtime and runtime.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported runtime schema version")
    for name in REQUIRED_FILES:
        if not (path / name).is_file():
            errors.append(f"missing file: {name}")
    for name in REQUIRED_DIRS:
        if not (path / name).is_dir():
            errors.append(f"missing directory: {name}")
    if runtime:
        run_id = str(runtime.get("run_id", ""))
        if not RUN_ID_RE.fullmatch(run_id):
            errors.append("invalid current run id")
        elif not run_runtime_path(path, run_id).is_file():
            errors.append(f"missing current run runtime: {run_id}")
    run_records: dict[str, dict[str, Any]] = {}
    run_root = runs_dir(path)
    if run_root.is_dir():
        for entry in sorted(run_root.iterdir()):
            if not entry.is_dir():
                errors.append(f"unexpected file in state/runs: {entry.name}")
                continue
            if not RUN_ID_RE.fullmatch(entry.name):
                errors.append(f"invalid historical run directory: {entry.name}")
                continue
            record_path = entry / "runtime.json"
            try:
                record = load_json(record_path)
            except RuntimeError_ as error:
                errors.append(str(error))
                continue
            if record.get("schema_version") != SCHEMA_VERSION:
                errors.append(f"unsupported historical run schema: {entry.name}")
            if record.get("task_id") != args.task_id or record.get("run_id") != entry.name:
                errors.append(f"historical run identity mismatch: {entry.name}")
            run_records[entry.name] = record
    for run_id, record in run_records.items():
        predecessor = record.get("predecessor_run_id")
        if predecessor is not None and predecessor not in run_records:
            errors.append(f"missing predecessor {predecessor} for run {run_id}")
    if runtime and str(runtime.get("run_id")) not in run_records:
        errors.append("current run is absent from historical run records")
    task_spec = path / "TASK.md"
    if task_spec.is_file() and "Pending launch-prompt materialization" in task_spec.read_text(
        encoding="utf-8"
    ):
        errors.append("TASK.md has not been materialized from the launch prompt")
    return {
        "task_id": args.task_id,
        "run_id": runtime.get("run_id") if runtime else None,
        "valid": not errors,
        "errors": errors,
        "task_dir": str(path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init", help="create a task, resume its active run, or continue after a terminal run"
    )
    init_parser.add_argument("task_id")
    init_parser.add_argument("--deadline", required=True)
    init_parser.add_argument("--duration-days", type=int, default=3)
    init_parser.add_argument("--goal-token-budget", type=int, required=True)
    init_parser.add_argument("--quota-stop-usd", type=float, default=1.0)
    init_parser.add_argument("--quota-check-minutes", type=int, default=20)
    init_parser.add_argument("--work-unit-minutes", type=int, default=10)
    init_parser.set_defaults(handler=initialize)

    gate_parser = subparsers.add_parser("gate", help="refresh quota when due and decide the next action")
    gate_parser.add_argument("task_id")
    gate_parser.add_argument("--force-quota", action="store_true")
    gate_parser.set_defaults(handler=gate)

    wait_parser = subparsers.add_parser(
        "wait-quota", help="wait for a daily quota reset without ending the task"
    )
    wait_parser.add_argument("task_id")
    wait_parser.add_argument("--poll-seconds", type=int, default=60)
    wait_parser.set_defaults(handler=wait_quota)

    status_parser = subparsers.add_parser("status", help="show deadline and last known quota without refreshing")
    status_parser.add_argument("task_id")
    status_parser.set_defaults(handler=status)

    close_parser = subparsers.add_parser(
        "close-run", help="close the current run after a verified non-deadline terminal condition"
    )
    close_parser.add_argument("task_id")
    close_parser.add_argument(
        "--reason",
        required=True,
        choices=("STOP_COMPLETE", "STOP_GOAL_TOKENS", "STOP_USER"),
    )
    close_parser.set_defaults(handler=close_run)

    validate_parser = subparsers.add_parser("validate", help="validate task runtime artifacts")
    validate_parser.add_argument("task_id")
    validate_parser.set_defaults(handler=validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = args.handler(args)
    except (OSError, RuntimeError_, subprocess.SubprocessError, ValueError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 64
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.command == "validate" and not payload["valid"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
