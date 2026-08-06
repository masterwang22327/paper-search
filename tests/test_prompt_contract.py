from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PromptContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.prompt = (ROOT / "VIBE_RESEARCH_PROMPT.md").read_text(encoding="utf-8")

    def test_configuration_is_explicit_and_complete(self) -> None:
        for field in (
            "TASK_ID",
            "RUN_MODE",
            "RESEARCH_QUESTION",
            "LONG_TERM_LEARNING_GOALS",
            "LEARNER_PROFILE_AND_PREFERENCES",
            "SCOPE_AND_PRIORITIES",
            "EXCLUSIONS",
            "DELIVERABLES",
            "COMPLETION_EVIDENCE",
            "HARD_DEADLINE",
            "USE_PERSISTENT_GOAL",
            "GOAL_TOKEN_BUDGET",
            "READER_REWRITE_SCOPE",
        ):
            self.assertRegex(self.prompt, rf"(?m)^{field}\s*=", field)
        self.assertIn("用户配置区：只修改这里", self.prompt)

    def test_research_is_the_safe_default(self) -> None:
        self.assertRegex(self.prompt, r'(?m)^RUN_MODE = "research"$')
        self.assertRegex(
            self.prompt,
            r'(?m)^READER_REWRITE_SCOPE = "affected-documents"$',
        )
        self.assertIn("不得根据“用户执行了本 Prompt”自行推断为全量 Reader 重构", self.prompt)
        self.assertIn("RUN_MODE=reader-rewrite", self.prompt)
        self.assertIn("READER_REWRITE_SCOPE=all-canonical-reading-documents", self.prompt)

    def test_prompt_does_not_freeze_stale_reader_counts(self) -> None:
        for stale_text in ("54/54", "i/56", "56 篇", "当前 canonical 路线为"):
            self.assertNotIn(stale_text, self.prompt)
        self.assertIn("从当前文件和用户数据重新枚举", self.prompt)

    def test_runtime_limits_are_ceilings_and_completion_is_terminal(self) -> None:
        budget_match = re.search(r"(?m)^GOAL_TOKEN_BUDGET = (\d+)$", self.prompt)
        self.assertIsNotNone(budget_match)
        self.assertLessEqual(int(budget_match.group(1)), 10_000_000)
        self.assertIn("完成验收是合法终点", self.prompt)
        self.assertIn("--reason STOP_COMPLETE", self.prompt)
        self.assertIn("STOP_DEADLINE", self.prompt)
        self.assertIn("STOP_GOAL_TOKENS", self.prompt)
        self.assertIn("STOP_USER", self.prompt)

    def test_repository_root_is_runnable_not_a_placeholder(self) -> None:
        root_match = re.search(r'(?m)^REPOSITORY_ROOT = "([^"]+)"$', self.prompt)
        self.assertIsNotNone(root_match)
        self.assertNotIn("/absolute/path", root_match.group(1))
        self.assertTrue(Path(root_match.group(1)).is_dir())

    def test_research_and_artifact_contract_is_linked(self) -> None:
        for required in (
            "docs/research-standard.md",
            "docs/learning-profile.md",
            "TASK.md",
            "TASK_HISTORY.md",
            "STATUS.md",
            "REPORT.md",
            "SOURCES.md",
            "reader/reading-cards.yml",
            "reader/learning-path.yml",
        ):
            self.assertIn(required, self.prompt)

    def test_source_and_user_data_safety_is_explicit(self) -> None:
        self.assertIn("不可信数据", self.prompt)
        self.assertIn("reader/user-data/TASK_ID 始终只读", self.prompt)
        self.assertIn("不得启动嵌套 codex/CLI", self.prompt)
        self.assertIn("一个方括号只引用一个来源", self.prompt)

    def test_prompt_keeps_one_consistent_reading_model(self) -> None:
        for layer in ("30 秒层", "5 分钟层", "深入层", "审计层"):
            self.assertIn(layer, self.prompt)
        self.assertIn("四层共享一条主线", self.prompt)
        self.assertNotIn("READER_EXPERIENCE_AND_FEEDBACK_POLICY", self.prompt)

    def test_modes_have_separate_deliverables_and_completion(self) -> None:
        self.assertIn("不把三个分支累加执行", self.prompt)
        for mode in ("research：", "discovery：", "reader-rewrite："):
            self.assertGreaterEqual(self.prompt.count(mode), 2, mode)
        self.assertIn("当前模式分支后即可收口", self.prompt)

    def test_single_paper_and_topic_contracts_are_distinct(self) -> None:
        self.assertIn("写作前先按论证功能判定文档类型", self.prompt)
        self.assertIn("单篇精读标题写成", self.prompt)
        self.assertIn("多论文专题标题直接写中心问题和范围", self.prompt)
        self.assertIn("标题与角色反向验收", self.prompt)

    def test_prompt_stays_reviewable(self) -> None:
        self.assertLessEqual(len(self.prompt.splitlines()), 350)


if __name__ == "__main__":
    unittest.main()
