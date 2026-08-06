#!/usr/bin/env python3
"""Unit checks for conservative citation mapping."""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path, PurePosixPath

import yaml


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "prepare_docs.py"
SPEC = importlib.util.spec_from_file_location("prepare_docs", MODULE_PATH)
prepare_docs = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(prepare_docs)


def audit() -> dict[str, int]:
    return {"found": 0, "linked": 0, "ambiguous": 0, "unresolved": 0, "overridden": 0}


def reading_card() -> dict[str, str]:
    return {field: f"test-{field}" for field in prepare_docs.READING_CARD_FIELDS}


def run() -> None:
    task_dir = (
        prepare_docs.REPO_DIR
        / "tasks"
        / "paper-research-base-knowledge-about-llm-20260717"
    )
    production_papers = sorted((task_dir / "papers").glob("*.md"))
    admitted, candidates = prepare_docs.load_reading_admission(production_papers)
    cards = prepare_docs.load_reading_cards(production_papers)
    explicit_cards = yaml.safe_load(prepare_docs.READING_CARDS_PATH.read_text(encoding="utf-8"))[
        "papers"
    ]
    titles = {
        paper.name: prepare_docs.NAV_TITLE_OVERRIDES.get(paper.name, prepare_docs.title_of(paper))
        for paper in production_papers
    }
    stages, route = prepare_docs.load_learning_path(
        production_papers,
        titles,
        admitted_files=admitted,
    )
    assert len(production_papers) == 67
    assert len(admitted) == len(route) == len(explicit_cards) == 64
    assert len(cards) == len(production_papers)
    assert set(candidates) == {
        "agentic-rl-next-directions.md",
        "environment-evolution-echoverse-change2task.md",
        "memory-security-skillrise.md",
    }
    assert "evaluator-judge-validity-cua.md" in admitted
    assert "async-staleness-rolloutpipe.md" in admitted
    assert sum(len(stage["papers"]) for stage in stages) == 64
    positions = {filename: context["overall_index"] for filename, context in route.items()}
    assert positions["pretransformer-gpt-lineage.md"] < positions["contextual-representations-finetuning.md"]
    assert positions["tokenization-data-curation.md"] < positions["arxiv-1810.04805.md"]
    assert positions["evaluation-effective-context.md"] < positions["evaluator-judge-validity-cua.md"]
    assert positions["dpr-dense-retrieval.md"] < positions["embedding-models-lineage-selection.md"]
    assert positions["reasoning-rl-reductions.md"] < positions["multimodal-llm-vision-language-abi.md"]
    assert positions["instruction-cot-self-consistency.md"] < positions["reward-verifier-policy-learning.md"]
    assert positions["reward-verifier-policy-learning.md"] < positions["preference-reward-overoptimization.md"]
    assert positions["multimodal-llm-vision-language-abi.md"] < positions["tool-use-function-calling-abi.md"]
    assert positions["tool-use-function-calling-abi.md"] < positions["agent-runtime-prompt-injection-security.md"]
    assert positions["scalable-oversight-control-evaluation.md"] < positions["mechanistic-interpretability-causal-intervention.md"]
    assert positions["code-embedding-retrieval.md"] < positions["code-generation-software-engineering-agents.md"]
    assert route["decoding.md"]["next"]["file"] == "tokenization-data-curation.md"
    assert route["tokenization-data-curation.md"]["previous"]["file"] == "decoding.md"
    assert all(stage["entry"] and stage["outcome"] and stage["checkpoint"] for stage in stages)
    guide_route = prepare_docs.learning_path_markdown(stages)
    assert guide_route.count('<section class="learning-stage"') == 14
    assert "主干 · 阶段" in guide_route and "选读分支 · 阶段" in guide_route
    assert "进入前" in guide_route and "读完后" in guide_route and "阶段检查" in guide_route

    with tempfile.TemporaryDirectory() as temporary:
        task = Path(temporary)
        for source in ("arxiv-1706.03762v7", "arxiv-1810.04805v2"):
            directory = task / "sources" / source
            directory.mkdir(parents=True)
            (directory / "paper.pdf").write_bytes(b"%PDF-test")

        papers = task / "papers"
        papers.mkdir()
        (papers / "example.md").write_text("# Example\n", encoding="utf-8")
        rebased = prepare_docs.linkify(
            "[专题](papers/example.md) 与 `papers/example.md`",
            PurePosixPath("report/index.md"),
            task,
        )
        assert rebased == "[专题](../papers/example.md) 与 [`papers/example.md`](../papers/example.md)"
        assert prepare_docs.linkify(
            "[缺失](papers/missing.md)", PurePosixPath("report/index.md"), task
        ) == "[缺失](papers/missing.md)"
        matrix = task / "state" / "coverage-matrix-20260802.md"
        matrix.parent.mkdir()
        matrix.write_text("# Coverage\n", encoding="utf-8")
        assert prepare_docs.linkify(
            "[覆盖矩阵](state/coverage-matrix-20260802.md)",
            PurePosixPath("report/index.md"),
            task,
        ) == "[覆盖矩阵](../meta/coverage-matrix-20260802.md)"
        assert prepare_docs.linkify(
            "[准入](../../../reader/reading-admission.yml)",
            PurePosixPath("meta/coverage-matrix-20260802.md"),
            task,
        ) == "[准入](reading-admission.md)"

        with_card = prepare_docs.inject_reading_card("# 标题\n\n正文\n", reading_card())
        assert with_card.startswith('# 标题\n\n<section class="paper-reading-card"')
        assert 'aria-label="专题阅读决策卡"' in with_card
        assert '<details class="paper-reading-card__details">' in with_card
        assert '<details class="paper-reading-card__details" open>' not in with_card
        assert "这篇先回答" in with_card
        assert "按你的知识画像先补什么" in with_card
        assert "第一遍只做" in with_card
        assert "阅读方法与前置" in with_card
        assert "test-prerequisites" in with_card
        assert "test-strategy" in with_card
        assert "test-problem" in with_card
        assert with_card.endswith("\n正文\n")

        path_file = task / "learning-path.yml"
        path_file.write_text(
            yaml.safe_dump(
                {
                    "stages": [
                        {
                            "name": "基础阶段",
                            "purpose": "先建立概念。",
                            "entry": "知道输入和输出。",
                            "outcome": "能解释最小计算。",
                            "checkpoint": "能否画出数据流？",
                            "route_type": "主干",
                            "papers": [{"file": "example.md", "bridge": "从目标函数进入计算结构。"}],
                        }
                    ]
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        stages, contexts = prepare_docs.load_learning_path(
            [papers / "example.md"], {"example.md": "Example"}, path_file
        )
        assert stages[0]["papers"][0]["file"] == "example.md"
        assert contexts["example.md"]["overall_index"] == 1
        assert contexts["example.md"]["previous"] is None
        assert contexts["example.md"]["next"] is None
        with_route = prepare_docs.inject_reading_card(
            "# 标题\n\n正文\n", reading_card(), contexts["example.md"]
        )
        assert "从上一篇到本篇" in with_route
        assert "本阶段 1/1" in with_route
        assert "全路线 1/1" in with_route
        footer = prepare_docs.reading_route_footer(contexts["example.md"])
        assert "阶段检查点" in footer
        assert "能否画出数据流？" in footer
        assert "返回完整阅读路线" in footer

        (papers / "new.md").write_text(
            "# New\n\n!!! abstract \"先读摘要\"\n    - **解决什么**：解释新增机制。\n",
            encoding="utf-8",
        )
        cards_file = task / "reading-cards.yml"
        cards_file.write_text(
            yaml.safe_dump({"papers": {"example.md": reading_card()}}, allow_unicode=True),
            encoding="utf-8",
        )
        cards = prepare_docs.load_reading_cards([papers / "example.md", papers / "new.md"], cards_file)
        assert cards["new.md"]["problem"] == "解释新增机制。"
        assert cards["new.md"]["level"] == "候选页面 · 待编排"

        admission_file = task / "reading-admission.yml"
        admission_file.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "canonical_count": 1,
                    "candidates": [
                        {
                            "file": "new.md",
                            "reason": "候选页尚未完成路线审校。",
                            "next_action": "完成依赖与证据复核。",
                        }
                    ],
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        admitted, candidate_metadata = prepare_docs.load_reading_admission(
            [papers / "example.md", papers / "new.md"], admission_file
        )
        assert admitted == {"example.md"}
        assert candidate_metadata["new.md"]["reason"] == "候选页尚未完成路线审校。"
        candidate_notice = prepare_docs.inject_candidate_notice(
            "# New\n\n正文\n", candidate_metadata["new.md"]
        )
        assert "候选页面 · 不计入推荐路线" in candidate_notice

        stages, contexts = prepare_docs.load_learning_path(
            [papers / "example.md", papers / "new.md"],
            {"example.md": "Example", "new.md": "New"},
            path_file,
            admitted_files=admitted,
        )
        assert stages[-1]["name"] == "基础阶段"
        assert list(contexts) == ["example.md"]
        assert contexts["example.md"]["overall_total"] == 1

        current = PurePosixPath("papers/arxiv-1706.03762.md")
        stats = audit()
        linked = prepare_docs.link_citations(
            "事实。[T17 p.6 Table 1]",
            current,
            task,
            "arxiv-1706.03762v7",
            stats,
            {},
        )
        assert 'data-page="6"' in linked
        assert 'data-source-id="arxiv-1706.03762v7"' in linked
        assert stats["linked"] == 1

        stats = audit()
        canonical = prepare_docs.link_citations(
            "事实。[PDF:arxiv-1810.04805v2 p.4 §3.1]",
            PurePosixPath("report/index.md"),
            task,
            None,
            stats,
            {},
        )
        assert 'data-page="4"' in canonical
        assert 'data-source-id="arxiv-1810.04805v2"' in canonical
        assert 'data-locator="§3.1"' in canonical
        assert 'href="../sources/arxiv-1810.04805v2/paper.pdf#page=4"' in canonical
        assert stats["linked"] == 1

        stats = audit()
        ambiguous = prepare_docs.link_citations(
            "对照。[T17 p.3; BERT p.4]",
            current,
            task,
            None,
            stats,
            {},
        )
        assert ambiguous == "对照。[T17 p.3; BERT p.4]"
        assert stats["ambiguous"] == 1

        stats = audit()
        citation = "[未命名 p.9]"
        overridden = prepare_docs.link_citations(
            f"校正。{citation}",
            PurePosixPath("papers/composite.md"),
            task,
            None,
            stats,
            {("composite.md", citation, 1): ("arxiv-1810.04805v2", 7)},
        )
        assert 'data-page="7"' in overridden
        assert 'data-source-id="arxiv-1810.04805v2"' in overridden
        assert stats["overridden"] == 1


if __name__ == "__main__":
    run()
    print("Citation mapping unit checks passed")
