from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PromptContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.prompt = (ROOT / "VIBE_RESEARCH_PROMPT.md").read_text(encoding="utf-8")

    def test_editable_configuration_is_obvious_and_complete(self) -> None:
        for field in (
            "TASK_ID",
            "RESEARCH_QUESTION",
            "LONG_TERM_LEARNING_GOALS",
            "LEARNER_PROFILE_AND_PREFERENCES",
            "SCOPE_AND_PRIORITIES",
            "EXCLUSIONS",
            "DELIVERABLES",
            "COMPLETION_EVIDENCE",
            "HARD_DEADLINE",
            "GOAL_TOKEN_BUDGET",
        ):
            self.assertIn(field, self.prompt)
        self.assertIn("用户配置区：只修改这里", self.prompt)

    def test_frequent_fields_are_grouped_at_the_top(self) -> None:
        quick_start = self.prompt.index("快速配置区：启动前优先检查")
        detail_start = self.prompt.index("详细配置区：新课题或有需要时修改")
        quick_config = self.prompt[quick_start:detail_start]
        for field in (
            "TASK_ID",
            "RESEARCH_QUESTION",
            "HARD_DEADLINE",
            "RUN_DURATION_DAYS",
            "GOAL_TOKEN_BUDGET",
        ):
            self.assertRegex(quick_config, rf"(?m)^{field}\s*=", field)

    def test_goal_and_runtime_controls_are_mandatory(self) -> None:
        self.assertIn("create_goal", self.prompt)
        self.assertIn("get_goal", self.prompt)
        self.assertIn("update_goal", self.prompt)
        self.assertIn("research_runtime.py\" gate", self.prompt)
        self.assertIn("STOP_DEADLINE", self.prompt)
        self.assertIn("WAIT_QUOTA", self.prompt)
        self.assertNotIn("STOP_QUOTA", self.prompt)
        self.assertLess(self.prompt.index("get_goal"), self.prompt.index("create_goal"))
        self.assertIn("CURRENT_RUN_ID", self.prompt)
        self.assertIn("RUN_HISTORY.md", self.prompt)
        self.assertIn("close-run", self.prompt)
        self.assertIn("`continued`", self.prompt)

    def test_same_task_continuation_keeps_one_canonical_artifact_tree(self) -> None:
        self.assertIn("只有用户显式修改 TASK_ID 才表示新知识库", self.prompt)
        self.assertIn("当前关注领域即使明显变化，也一律视为同一长期知识库的新配置版本", self.prompt)
        self.assertIn("不得复制或", self.prompt)
        self.assertIn("重置 TASK.md、REPORT.md、SOURCES.md、papers、sources、STATUS.md", self.prompt)
        self.assertIn("state/runs/<CURRENT_RUN_ID>/runtime.json", self.prompt)

    def test_each_run_has_its_own_goal_and_only_declared_auto_limits(self) -> None:
        self.assertIn("一个 run 对应一个 Goal", self.prompt)
        self.assertRegex(self.prompt, r"一个\s+Goal 必须且只能绑定一个 CURRENT_RUN_ID")
        self.assertIn("`continued` 总是创建新的 Goal", self.prompt)
        self.assertRegex(self.prompt, r"自动终止阈值只有本次声明的绝对截止时间\s*和产品 Goal Token 预算")
        self.assertIn("外部每日额度不足只暂停，不终止", self.prompt)

    def test_long_term_learning_and_reader_feedback_are_durable_inputs(self) -> None:
        self.assertIn("LONG_TERM_LEARNING_GOALS =", self.prompt)
        self.assertIn("LEARNER_PROFILE_AND_PREFERENCES =", self.prompt)
        self.assertIn("长期目标和画像", self.prompt)
        self.assertIn("Reader 中反复出现", self.prompt)
        self.assertIn("reader/reading-cards.yml", self.prompt)
        self.assertIn("reader/learning-path.yml", self.prompt)

    def test_all_user_fields_have_values_and_edit_guidance(self) -> None:
        self.assertNotIn("[必填", self.prompt)
        self.assertIn("只有你决定是否新建知识库", self.prompt)
        self.assertIn("通常按课题改", self.prompt)
        self.assertIn("通常不用改", self.prompt)
        self.assertRegex(
            self.prompt,
            r'HARD_DEADLINE = "(?:AUTO|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2})"',
        )
        self.assertRegex(self.prompt, r"RUN_DURATION_DAYS = [1-9]\d*")
        self.assertRegex(self.prompt, r"GOAL_TOKEN_BUDGET = [1-9]\d*")

    def test_every_editable_variable_explains_use_and_interactions(self) -> None:
        variables = (
            "TASK_ID",
            "RESEARCH_QUESTION",
            "LONG_TERM_LEARNING_GOALS",
            "LEARNER_PROFILE_AND_PREFERENCES",
            "SCOPE_AND_PRIORITIES",
            "EXCLUSIONS",
            "DELIVERABLES",
            "COMPLETION_EVIDENCE",
            "SEED_SOURCES",
            "REPOSITORY_ROOT",
            "OUTPUT_LANGUAGE",
            "RESEARCH_DEPTH",
            "PARALLELISM",
            "HARD_DEADLINE",
            "RUN_DURATION_DAYS",
            "GOAL_TOKEN_BUDGET",
            "EXTERNAL_QUOTA_STOP_USD",
            "QUOTA_CHECK_INTERVAL_MINUTES",
            "QUOTA_WAIT_POLL_SECONDS",
            "WORK_UNIT_MINUTES",
        )
        config = self.prompt.split("==================== 执行协议区", 1)[0]
        for variable in variables:
            assignment = re.search(rf"(?m)^{variable}\s*=", config)
            self.assertIsNotNone(assignment, variable)
            comment_block = config[max(0, assignment.start() - 500):assignment.start()]
            self.assertIn("# 作用：", comment_block, variable)
            self.assertIn("# 协同/冲突：", comment_block, variable)

    def test_daily_quota_wait_is_resumable(self) -> None:
        self.assertIn("https://cc.nf.video/claude/web/points", self.prompt)
        self.assertIn("wait-quota", self.prompt)
        self.assertIn("resume_not_before", self.prompt)
        self.assertIn("北京时间次日 00:00", self.prompt)
        self.assertIn("QUOTA_WAIT_POLL_SECONDS = 60", self.prompt)
        self.assertIn("不得调用 update_goal complete/blocked", self.prompt)

    def test_research_and_artifact_contract_is_linked(self) -> None:
        self.assertIn("docs/research-standard.md", self.prompt)
        self.assertIn("docs/learning-profile.md", self.prompt)
        for artifact in ("TASK.md", "STATUS.md", "REPORT.md", "SOURCES.md"):
            self.assertIn(artifact, self.prompt)

    def test_prompt_forbids_nested_codex_and_source_instructions(self) -> None:
        self.assertRegex(self.prompt, r"不得启动\s+嵌套 `codex`")
        self.assertIn("不可信数据", self.prompt)


if __name__ == "__main__":
    unittest.main()
