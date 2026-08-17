from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import research_runtime as runtime


class DeadlineTests(unittest.TestCase):
    def test_naive_deadline_is_interpreted_as_beijing_time(self) -> None:
        parsed = runtime.parse_deadline("2026-07-20 23:00:00")
        self.assertEqual(parsed.isoformat(), "2026-07-20T23:00:00+08:00")

    def test_invalid_deadline_is_rejected(self) -> None:
        with self.assertRaisesRegex(runtime.RuntimeError_, "ISO-8601"):
            runtime.parse_deadline("tomorrow night")


class DecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 17, 12, 0, tzinfo=runtime.TZ)
        self.control = {
            "deadline": (self.now + timedelta(hours=2)).isoformat(),
            "goal_token_budget": 100_000,
            "quota_stop_usd": 1.0,
            "quota_check_minutes": 20,
            "work_unit_minutes": 10,
        }

    def test_deadline_stops_before_quota_access_matters(self) -> None:
        control = {**self.control, "deadline": self.now.isoformat()}
        result = runtime.decide(control, self.now, None)
        self.assertEqual(result["decision"], "STOP_DEADLINE")

    def test_fresh_exhausted_quota_waits_until_next_beijing_midnight(self) -> None:
        quota = {"checked_at": self.now.isoformat(), "daily_remaining": 0.5}
        result = runtime.decide(self.control, self.now, quota)
        self.assertEqual(result["decision"], "WAIT_QUOTA")
        self.assertEqual(result["resume_not_before"], "2026-07-18T00:00:00+08:00")
        self.assertEqual(result["recommended_max_work_seconds"], 0)

    def test_stale_quota_does_not_create_a_false_stop(self) -> None:
        quota = {
            "checked_at": (self.now - timedelta(hours=3)).isoformat(),
            "daily_remaining": 0,
        }
        result = runtime.decide(self.control, self.now, quota)
        self.assertEqual(result["decision"], "CONTINUE")

    def test_failed_refresh_invalidates_an_old_low_quota_snapshot(self) -> None:
        control = {**self.control, "last_quota_error": "monitor unavailable"}
        quota = {"checked_at": self.now.isoformat(), "daily_remaining": 0}
        result = runtime.decide(control, self.now, quota)
        self.assertEqual(result["decision"], "CONTINUE")

    def test_former_terminal_quota_state_can_recover_after_midnight(self) -> None:
        control = {
            **self.control,
            "terminal_reason": "STOP_QUOTA",
            "updated_at": (self.now - timedelta(days=1)).isoformat(),
        }
        quota = {"checked_at": self.now.isoformat(), "daily_remaining": 200}
        result = runtime.decide(control, self.now, quota)
        self.assertEqual(result["decision"], "CONTINUE")

    def test_deadline_wins_while_waiting_for_quota(self) -> None:
        control = {
            **self.control,
            "deadline": self.now.isoformat(),
            "status": "waiting_quota",
            "resume_not_before": (self.now + timedelta(hours=12)).isoformat(),
        }
        result = runtime.decide(control, self.now, None)
        self.assertEqual(result["decision"], "STOP_DEADLINE")

    def test_near_deadline_wraps_up(self) -> None:
        control = {**self.control, "deadline": (self.now + timedelta(minutes=5)).isoformat()}
        result = runtime.decide(control, self.now, None)
        self.assertEqual(result["decision"], "WRAP_UP")


class ScaffoldTests(unittest.TestCase):
    def test_initialize_creates_minimal_durable_workspace_and_is_idempotent(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current = datetime(2026, 7, 17, 12, 0, tzinfo=runtime.TZ)
            args = Namespace(
                task_id="ppo-lineage",
                deadline="AUTO",
                duration_days=3,
                goal_token_budget=100_000,
                quota_stop_usd=1.0,
                quota_check_minutes=20,
                work_unit_minutes=10,
            )
            with patch.object(runtime, "TASKS_ROOT", root / "tasks"), patch.object(
                runtime, "now_bjt", return_value=current
            ):
                created = runtime.initialize(args)
                resumed = runtime.initialize(args)

            task = root / "tasks" / "ppo-lineage"
            self.assertEqual(created["status"], "created")
            self.assertEqual(resumed["status"], "resumed")
            self.assertTrue(all((task / name).is_file() for name in runtime.REQUIRED_FILES))
            self.assertTrue((task / "state" / "handoffs").is_dir())
            pointer = json.loads((task / "state" / "current-run.json").read_text(encoding="utf-8"))
            control = runtime.load_json(task / pointer["runtime_path"])
            self.assertEqual(control["goal_token_budget"], 100_000)
            self.assertEqual(control["deadline"], "2026-07-20T12:00:00+08:00")
            self.assertEqual(control["deadline_mode"], "auto")

    def test_existing_runtime_rejects_changed_limits(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current = datetime(2026, 7, 17, 12, 0, tzinfo=runtime.TZ)
            args = Namespace(
                task_id="topic",
                deadline="2026-07-20T23:00:00+08:00",
                duration_days=3,
                goal_token_budget=50_000,
                quota_stop_usd=1.0,
                quota_check_minutes=20,
                work_unit_minutes=10,
            )
            with patch.object(runtime, "TASKS_ROOT", root / "tasks"), patch.object(
                runtime, "now_bjt", return_value=current
            ):
                runtime.initialize(args)
                args.goal_token_budget = 60_000
                with self.assertRaisesRegex(runtime.RuntimeError_, "contract cannot change"):
                    runtime.initialize(args)

    def test_auto_deadline_resume_does_not_extend_the_task(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            before = datetime(2026, 7, 17, 12, 0, tzinfo=runtime.TZ)
            after = datetime(2026, 7, 18, 12, 0, tzinfo=runtime.TZ)
            args = Namespace(
                task_id="topic",
                deadline="AUTO",
                duration_days=3,
                goal_token_budget=50_000,
                quota_stop_usd=1.0,
                quota_check_minutes=20,
                work_unit_minutes=10,
            )
            with patch.object(runtime, "TASKS_ROOT", root / "tasks"), patch.object(
                runtime, "now_bjt", return_value=before
            ):
                created = runtime.initialize(args)
            with patch.object(runtime, "TASKS_ROOT", root / "tasks"), patch.object(
                runtime, "now_bjt", return_value=after
            ):
                resumed = runtime.initialize(args)

            self.assertEqual(created["runtime"]["deadline"], "2026-07-20T12:00:00+08:00")
            self.assertEqual(resumed["runtime"]["deadline"], created["runtime"]["deadline"])

    def test_validate_reports_complete_scaffold(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current = datetime(2026, 7, 17, 12, 0, tzinfo=runtime.TZ)
            init_args = Namespace(
                task_id="topic",
                deadline="2026-07-20T23:00:00+08:00",
                duration_days=3,
                goal_token_budget=50_000,
                quota_stop_usd=1.0,
                quota_check_minutes=20,
                work_unit_minutes=10,
            )
            with patch.object(runtime, "TASKS_ROOT", root / "tasks"), patch.object(
                runtime, "now_bjt", return_value=current
            ):
                runtime.initialize(init_args)
                (root / "tasks" / "topic" / "TASK.md").write_text(
                    "# Research Task\n\n## Research Question\n\nA materialized question.\n",
                    encoding="utf-8",
                )
                result = runtime.validate(Namespace(task_id="topic"))

            self.assertTrue(result["valid"], result)

    def test_validate_reads_compacted_historical_runs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            before = datetime(2026, 7, 17, 12, 0, tzinfo=runtime.TZ)
            after = datetime(2026, 7, 18, 12, 0, tzinfo=runtime.TZ)
            args = Namespace(
                task_id="topic",
                deadline="2026-07-20T23:00:00+08:00",
                duration_days=3,
                goal_token_budget=50_000,
                quota_stop_usd=1.0,
                quota_check_minutes=20,
                work_unit_minutes=10,
            )
            with patch.object(runtime, "TASKS_ROOT", root / "tasks"), patch.object(
                runtime, "now_bjt", return_value=before
            ):
                first = runtime.initialize(args)
                runtime.close_run(Namespace(task_id="topic", reason="STOP_COMPLETE"))
            args.deadline = "2026-07-22T23:00:00+08:00"
            with patch.object(runtime, "TASKS_ROOT", root / "tasks"), patch.object(
                runtime, "now_bjt", return_value=after
            ):
                runtime.initialize(args)
                task = root / "tasks" / "topic"
                (task / "TASK.md").write_text(
                    "# Research Task\n\n## Research Question\n\nA materialized question.\n",
                    encoding="utf-8",
                )
                store = runtime.TaskArtifactStore(task)
                self.assertGreater(store.compact_state_history(), 0)
                self.assertFalse((task / "state" / "runs" / first["run_id"]).exists())
                runtime._ARTIFACT_STORES.clear()
                result = runtime.validate(Namespace(task_id="topic"))

            self.assertTrue(result["valid"], result)

    def test_validate_rejects_an_unmaterialized_task(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current = datetime(2026, 7, 17, 12, 0, tzinfo=runtime.TZ)
            init_args = Namespace(
                task_id="topic",
                deadline="2026-07-20T23:00:00+08:00",
                duration_days=3,
                goal_token_budget=50_000,
                quota_stop_usd=1.0,
                quota_check_minutes=20,
                work_unit_minutes=10,
            )
            with patch.object(runtime, "TASKS_ROOT", root / "tasks"), patch.object(
                runtime, "now_bjt", return_value=current
            ):
                runtime.initialize(init_args)
                result = runtime.validate(Namespace(task_id="topic"))

            self.assertFalse(result["valid"])
            self.assertIn("TASK.md has not been materialized from the launch prompt", result["errors"])

    def test_completed_run_can_close_before_its_resource_limits(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current = datetime(2026, 7, 17, 12, 0, tzinfo=runtime.TZ)
            init_args = Namespace(
                task_id="topic",
                deadline="2026-07-20T23:00:00+08:00",
                duration_days=3,
                goal_token_budget=50_000,
                quota_stop_usd=1.0,
                quota_check_minutes=20,
                work_unit_minutes=10,
            )
            with patch.object(runtime, "TASKS_ROOT", root / "tasks"), patch.object(
                runtime, "now_bjt", return_value=current
            ):
                runtime.initialize(init_args)
                result = runtime.close_run(Namespace(task_id="topic", reason="STOP_COMPLETE"))
                saved = runtime.load_current_run(root / "tasks" / "topic")

            self.assertEqual(result["status"], "closed")
            self.assertEqual(saved["status"], "stopped")
            self.assertEqual(saved["terminal_reason"], "STOP_COMPLETE")

    def test_legacy_runtime_is_migrated_without_touching_canonical_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / "tasks" / "topic"
            (task / "state").mkdir(parents=True)
            (task / "REPORT.md").write_text("# Existing report\n", encoding="utf-8")
            legacy = {
                "schema_version": 1,
                "task_id": "topic",
                "run_id": "12345678-1234-1234-1234-123456789abc",
                "status": "stopped",
                "created_at": "2026-07-17T12:00:00+08:00",
                "updated_at": "2026-07-18T00:00:00+08:00",
                "deadline": "2026-07-18T00:00:00+08:00",
                "deadline_mode": "absolute",
                "duration_days": None,
                "goal_token_budget": 50_000,
                "quota_stop_usd": 1.0,
                "quota_check_minutes": 20,
                "work_unit_minutes": 10,
                "terminal_reason": "STOP_DEADLINE",
            }
            runtime.write_json(task / "state" / "runtime.json", legacy)
            (task / "state" / "events.jsonl").write_text("{}\n", encoding="utf-8")
            (task / "state" / "quota.json").write_text("{}\n", encoding="utf-8")

            with patch.object(runtime, "TASKS_ROOT", root / "tasks"):
                migrated = runtime.load_current_run(task)

            run = task / "state" / "runs" / migrated["run_id"]
            self.assertEqual(migrated["schema_version"], runtime.SCHEMA_VERSION)
            self.assertTrue((run / "events.jsonl").is_file())
            self.assertTrue((run / "quota.json").is_file())
            self.assertEqual((task / "REPORT.md").read_text(encoding="utf-8"), "# Existing report\n")
            self.assertIn("current_run_id", runtime.load_json(task / "state" / "runtime.json"))

    def test_validate_rejects_a_broken_predecessor_chain(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            current = datetime(2026, 7, 17, 12, 0, tzinfo=runtime.TZ)
            args = Namespace(
                task_id="topic",
                deadline="2026-07-20T23:00:00+08:00",
                duration_days=3,
                goal_token_budget=50_000,
                quota_stop_usd=1.0,
                quota_check_minutes=20,
                work_unit_minutes=10,
            )
            with patch.object(runtime, "TASKS_ROOT", root / "tasks"), patch.object(
                runtime, "now_bjt", return_value=current
            ):
                created = runtime.initialize(args)
                task = root / "tasks" / "topic"
                (task / "TASK.md").write_text("# Research Task\n\nMaterialized.\n", encoding="utf-8")
                record_path = runtime.run_runtime_path(task, created["run_id"])
                record = runtime.load_json(record_path)
                record["predecessor_run_id"] = "run-20260101t000000-deadbeef"
                runtime.write_json(record_path, record)
                result = runtime.validate(Namespace(task_id="topic"))

            self.assertFalse(result["valid"])
            self.assertTrue(any("missing predecessor" in error for error in result["errors"]))

    def test_terminal_run_requires_a_new_future_deadline(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            before = datetime(2026, 7, 17, 12, 0, tzinfo=runtime.TZ)
            after = datetime(2026, 7, 21, 12, 0, tzinfo=runtime.TZ)
            args = Namespace(
                task_id="topic",
                deadline="2026-07-20T23:00:00+08:00",
                duration_days=3,
                goal_token_budget=50_000,
                quota_stop_usd=1.0,
                quota_check_minutes=20,
                work_unit_minutes=10,
            )
            with patch.object(runtime, "TASKS_ROOT", root / "tasks"), patch.object(
                runtime, "now_bjt", return_value=before
            ):
                runtime.initialize(args)
            with patch.object(runtime, "TASKS_ROOT", root / "tasks"), patch.object(
                runtime, "now_bjt", return_value=after
            ):
                with self.assertRaisesRegex(runtime.RuntimeError_, "new future deadline"):
                    runtime.initialize(args)

    def test_terminal_run_continues_in_same_task_without_copying_artifacts(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            before = datetime(2026, 7, 17, 12, 0, tzinfo=runtime.TZ)
            after = datetime(2026, 7, 21, 12, 0, tzinfo=runtime.TZ)
            args = Namespace(
                task_id="topic",
                deadline="2026-07-20T23:00:00+08:00",
                duration_days=3,
                goal_token_budget=50_000,
                quota_stop_usd=1.0,
                quota_check_minutes=20,
                work_unit_minutes=10,
            )
            with patch.object(runtime, "TASKS_ROOT", root / "tasks"), patch.object(
                runtime, "now_bjt", return_value=before
            ):
                first = runtime.initialize(args)
            task = root / "tasks" / "topic"
            (task / "REPORT.md").write_text("# Canonical report\n\nEvidence.\n", encoding="utf-8")
            args.deadline = "2026-07-24T23:00:00+08:00"
            args.goal_token_budget = 75_000
            with patch.object(runtime, "TASKS_ROOT", root / "tasks"), patch.object(
                runtime, "now_bjt", return_value=after
            ):
                continued = runtime.initialize(args)

            self.assertEqual(continued["status"], "continued")
            self.assertEqual(continued["predecessor_run_id"], first["run_id"])
            self.assertNotEqual(continued["run_id"], first["run_id"])
            self.assertEqual((task / "REPORT.md").read_text(encoding="utf-8"), "# Canonical report\n\nEvidence.\n")
            self.assertEqual(len(list((task / "state" / "runs").iterdir())), 2)
            self.assertIn(first["run_id"], (task / "RUN_HISTORY.md").read_text(encoding="utf-8"))
            self.assertIn(continued["run_id"], (task / "RUN_HISTORY.md").read_text(encoding="utf-8"))


class QuotaWaitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.midnight = datetime(2026, 7, 18, 0, 0, tzinfo=runtime.TZ)

    def test_waiting_quota_is_not_checked_before_resume_time(self) -> None:
        control = {
            "status": "waiting_quota",
            "resume_not_before": self.midnight.isoformat(),
            "last_quota_attempt_at": (self.midnight - timedelta(hours=1)).isoformat(),
            "quota_check_minutes": 20,
            "last_quota_error": None,
        }
        self.assertFalse(
            runtime.quota_check_due(control, self.midnight - timedelta(minutes=1), False)
        )
        self.assertTrue(runtime.quota_check_due(control, self.midnight, False))

    def test_midnight_refresh_recovers_without_force_flag(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / "tasks" / "topic"
            (task / "state").mkdir(parents=True)
            control = {
                "schema_version": runtime.SCHEMA_VERSION,
                "task_id": "topic",
                "status": "waiting_quota",
                "deadline": (self.midnight + timedelta(days=1)).isoformat(),
                "goal_token_budget": 100_000,
                "quota_stop_usd": 1.0,
                "quota_check_minutes": 20,
                "work_unit_minutes": 10,
                "last_quota_attempt_at": (self.midnight - timedelta(hours=1)).isoformat(),
                "last_quota_error": None,
                "resume_not_before": self.midnight.isoformat(),
                "wait_reason": "daily_quota_exhausted",
                "terminal_reason": None,
            }
            runtime.write_json(task / "state" / "runtime.json", control)
            refreshed = {
                "checked_at": self.midnight.isoformat(),
                "daily_remaining": 200,
            }

            with patch.object(runtime, "TASKS_ROOT", root / "tasks"), patch.object(
                runtime, "now_bjt", return_value=self.midnight
            ), patch.object(runtime, "refresh_quota", return_value=(refreshed, None)) as refresh:
                result = runtime.gate(Namespace(task_id="topic", force_quota=False))

            saved = runtime.load_current_run(task)
            refresh.assert_called_once()
            self.assertEqual(result["decision"], "CONTINUE")
            self.assertEqual(saved["status"], "active")
            self.assertIsNone(saved["terminal_reason"])
            self.assertIsNone(saved["resume_not_before"])

    def test_exhausted_quota_is_saved_as_nonterminal_wait_state(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / "tasks" / "topic"
            (task / "state").mkdir(parents=True)
            control = {
                "schema_version": runtime.SCHEMA_VERSION,
                "task_id": "topic",
                "status": "active",
                "deadline": (self.midnight + timedelta(days=1)).isoformat(),
                "goal_token_budget": 100_000,
                "quota_stop_usd": 1.0,
                "quota_check_minutes": 20,
                "work_unit_minutes": 10,
                "last_quota_attempt_at": None,
                "last_quota_error": None,
                "resume_not_before": None,
                "wait_reason": None,
                "terminal_reason": None,
            }
            runtime.write_json(task / "state" / "runtime.json", control)
            exhausted = {
                "checked_at": self.midnight.isoformat(),
                "daily_remaining": 0.5,
            }

            with patch.object(runtime, "TASKS_ROOT", root / "tasks"), patch.object(
                runtime, "now_bjt", return_value=self.midnight
            ), patch.object(runtime, "refresh_quota", return_value=(exhausted, None)):
                result = runtime.gate(Namespace(task_id="topic", force_quota=True))

            saved = runtime.load_current_run(task)
            self.assertEqual(result["decision"], "WAIT_QUOTA")
            self.assertEqual(saved["status"], "waiting_quota")
            self.assertIsNone(saved["terminal_reason"])
            self.assertEqual(saved["resume_not_before"], "2026-07-19T00:00:00+08:00")

    def test_failed_midnight_refresh_keeps_the_task_waiting_not_stopped(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            task = root / "tasks" / "topic"
            (task / "state").mkdir(parents=True)
            control = {
                "schema_version": runtime.SCHEMA_VERSION,
                "task_id": "topic",
                "status": "waiting_quota",
                "deadline": (self.midnight + timedelta(days=1)).isoformat(),
                "goal_token_budget": 100_000,
                "quota_stop_usd": 1.0,
                "quota_check_minutes": 20,
                "work_unit_minutes": 10,
                "last_quota_attempt_at": (self.midnight - timedelta(hours=1)).isoformat(),
                "last_quota_error": None,
                "resume_not_before": self.midnight.isoformat(),
                "wait_reason": "daily_quota_exhausted",
                "terminal_reason": None,
            }
            runtime.write_json(task / "state" / "runtime.json", control)

            with patch.object(runtime, "TASKS_ROOT", root / "tasks"), patch.object(
                runtime, "now_bjt", return_value=self.midnight
            ), patch.object(
                runtime, "refresh_quota", return_value=(None, "monitor unavailable")
            ):
                result = runtime.gate(Namespace(task_id="topic", force_quota=False))

            saved = runtime.load_current_run(task)
            self.assertEqual(result["decision"], "WAIT_QUOTA")
            self.assertEqual(result["quota_error"], "monitor unavailable")
            self.assertEqual(saved["status"], "waiting_quota")
            self.assertIsNone(saved["terminal_reason"])

    def test_low_quota_after_midnight_waits_for_the_following_midnight(self) -> None:
        control = {
            "status": "waiting_quota",
            "deadline": (self.midnight + timedelta(days=2)).isoformat(),
            "goal_token_budget": 100_000,
            "quota_stop_usd": 1.0,
            "quota_check_minutes": 20,
            "work_unit_minutes": 10,
            "last_quota_error": None,
            "resume_not_before": self.midnight.isoformat(),
            "wait_reason": "daily_quota_exhausted",
        }
        quota = {"checked_at": self.midnight.isoformat(), "daily_remaining": 0.5}
        result = runtime.decide(control, self.midnight, quota)
        self.assertEqual(result["decision"], "WAIT_QUOTA")
        self.assertEqual(result["resume_not_before"], "2026-07-19T00:00:00+08:00")


if __name__ == "__main__":
    unittest.main()
