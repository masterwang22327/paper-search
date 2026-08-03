#!/usr/bin/env python3
"""Build a disposable MkDocs document tree from one read-only research task."""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
from pathlib import Path, PurePosixPath

import yaml


READER_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = READER_DIR.parent
DEFAULT_TASK_ID = "paper-research-base-knowledge-about-llm-20260717"
READING_CARDS_PATH = READER_DIR / "reading-cards.yml"
LEARNING_PATH_PATH = READER_DIR / "learning-path.yml"
READING_ADMISSION_PATH = READER_DIR / "reading-admission.yml"
READING_CARD_FIELDS = (
    "level",
    "effort",
    "background",
    "problem",
    "legacy",
    "team",
    "impact",
    "value",
    "strategy",
    "prerequisites",
)

NAV_TITLE_OVERRIDES = {
    # Keep the annotated source page byte-for-byte stable while making its
    # navigation label consistent with the reader-facing titles.
    "arxiv-1706.03762.md": "Attention Is All You Need：用自注意力替代序列递归",
}

BACKTICK_PATH = re.compile(r"`((?:papers|sources)/[^`\n]+)`")
MARKDOWN_PATH = re.compile(r"(?<=\]\()((?:papers|sources)/[^)\s]+)")
STATE_MATRIX_PATH = re.compile(r"(?<=\]\()(state/coverage-matrix-[^)\s]+)")
ADMISSION_PATH = re.compile(r"(?<=\]\()((?:(?:\.\./)+)?reader/reading-admission\.yml)")
CITATION = re.compile(r"\[([^\]\n]{0,220}\bpp?\.?\s*\d+[^\]\n]{0,180})\]", re.IGNORECASE)
PAGE = re.compile(r"\bpp?\.?\s*(\d+)", re.IGNORECASE)
CANONICAL_SOURCE = re.compile(r"^\s*PDF:([A-Za-z0-9._-]{1,128})(?=\s|$)", re.IGNORECASE)
LOCATOR = re.compile(
    r"(?:§{1,2}\s*[\w.\-]+|\b(?:sec(?:tion)?|app(?:endix)?|fig(?:ure)?|table|eq(?:uation)?|algorithm)\.?\s*[\w.()\-]+)",
    re.IGNORECASE,
)

# Only explicit, stable aliases are accepted. Ambiguous multi-paper citations are left untouched.
SOURCE_ALIASES = {
    "T17": "arxiv-1706.03762v7",
    "Transformer": "arxiv-1706.03762v7",
    "PPO": "arxiv-1707.06347v2",
    "BERT": "arxiv-1810.04805v2",
    "T5": "arxiv-1910.10683v4",
    "UL2": "arxiv-2205.05131v3",
    "G3": "arxiv-2005.14165v4",
    "GPT-3": "arxiv-2005.14165v4",
    "L22": "arxiv-2106.09685v2",
    "LoRA": "arxiv-2106.09685v2",
    "PaLM": "arxiv-2204.02311v5",
    "I22": "arxiv-2203.02155v1",
    "InstructGPT": "arxiv-2203.02155v1",
    "DPO": "neurips-2023-dpo",
    "LLaMA": "arxiv-2302.13971v1",
    "Mamba": "arxiv-2312.00752v2",
    "G15": "arxiv-2403.05530v5",
    "Gemini": "arxiv-2403.05530v5",
    "V3": "arxiv-2412.19437v2",
    "DPR": "emnlp-2020-dpr",
    "RAG": "neurips-2020-rag",
    "REALM": "icml-2020-realm",
    "RETRO": "icml-2022-retro",
    "QLoRA": "neurips-2023-qlora",
    "Adapters": "icml-2019-adapters",
    "Prefix": "acl-2021-prefix-tuning",
    "Prompt": "emnlp-2021-prompt-tuning",
    "ZeRO": "arxiv-1910.02054v3",
    "Megatron": "arxiv-1909.08053v4",
    "Switch": "arxiv-2101.03961v3",
    "S22": "arxiv-2101.03961v3",
    "M17": "arxiv-1701.06538v1",
    "Mixtral": "arxiv-2401.04088v1",
    "RMSNorm": "neurips-2019-rmsnorm",
    "Mistral": "arxiv-2310.06825v1",
    "Negative Sampling": "arxiv-1310.4546v1",
    "Mikolov 2013": "arxiv-1301.3781v3",
    "JMLR": "jmlr-2003-neural-lm",
}

PAPER_PRIMARY = {
    "arxiv-1706.03762.md": "arxiv-1706.03762v7",
    "arxiv-1707.06347.md": "arxiv-1707.06347v2",
    "arxiv-1810.04805.md": "arxiv-1810.04805v2",
    "arxiv-1910.10683.md": "arxiv-1910.10683v4",
    "arxiv-2005.14165.md": "arxiv-2005.14165v4",
    "arxiv-2106.09685.md": "arxiv-2106.09685v2",
    "arxiv-2204.02311.md": "arxiv-2204.02311v5",
    "arxiv-2302.13971.md": "arxiv-2302.13971v1",
    "arxiv-2312.00752.md": "arxiv-2312.00752v2",
    "arxiv-2403.05530.md": "arxiv-2403.05530v5",
    "arxiv-2412.19437.md": "arxiv-2412.19437v2",
    "dpr-dense-retrieval.md": "emnlp-2020-dpr",
    "neurips-2022-instructgpt.md": "arxiv-2203.02155v1",
    "neurips-2023-dpo.md": "neurips-2023-dpo",
    "process-supervision-test-time-search.md": "arxiv-2305.20050v1",
}


def load_citation_overrides() -> dict[tuple[str, str, int], tuple[str, int]]:
    config_path = READER_DIR / "citation-overrides.yml"
    if not config_path.is_file():
        return {}
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    result: dict[tuple[str, str, int], tuple[str, int]] = {}
    for item in data.get("overrides", []):
        paper = str(item["paper"])
        citation = str(item["citation"])
        occurrence = int(item.get("occurrence", 1))
        source_id = str(item["source"])
        page = int(item["page"])
        key = (paper, citation, occurrence)
        if key in result:
            raise ValueError(f"Duplicate citation override: {key}")
        result[key] = (source_id, page)
    return result


def title_of(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").title()


def abstract_bullet(text: str, label: str) -> str:
    match = re.search(rf"^\s*-\s+\*\*{re.escape(label)}\*\*[：:]\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def fallback_reading_card(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    problem = abstract_bullet(text, "解决什么") or "该专题来自本地调研任务的最新更新，Reader 尚未完成独立导读摘要。"
    legacy = abstract_bullet(text, "不要误解") or abstract_bullet(text, "遗留问题")
    if not legacy:
        legacy = "Reader 尚未完成这篇新增专题的遗留问题审计；阅读时请以正文的证据边界和反例为准。"
    return {
        "level": "候选页面 · 待编排",
        "effort": "建议先投入 20–30 分钟浏览，再决定是否精读",
        "background": "该专题由本地调研任务新近生成，尚未进入人工维护的 Reader canonical 学习路线。",
        "problem": problem,
        "legacy": legacy,
        "team": "待补充：Reader 尚未为该新增专题核对作者、机构和工作分工。",
        "impact": "待补充：Reader 尚未独立核对论文发表状态、引用影响和后续采用情况。",
        "value": "先判断它是否补充了当前任务的知识缺口；正式编排前，不把它视为既有路线的必读前置。",
        "strategy": "先读文首摘要、结论和证据边界；需要继续阅读时，再回到正文核对方法、实验和来源引用。",
        "prerequisites": "待确认；优先参考正文中的问题定义与前置概念。",
    }


def load_reading_admission(
    paper_files: list[Path], path: Path = READING_ADMISSION_PATH
) -> tuple[set[str], dict[str, dict[str, str]]]:
    """Load the explicit boundary between research inventory and Reader route."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    expected = {paper.name for paper in paper_files}
    raw_candidates = data.get("candidates", [])
    if not isinstance(raw_candidates, list):
        raise ValueError("Reading admission candidates must be a list")
    candidates: dict[str, dict[str, str]] = {}
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            raise ValueError("Reading admission candidate must be a mapping")
        filename = str(raw.get("file", "")).strip()
        reason = str(raw.get("reason", "")).strip()
        next_action = str(raw.get("next_action", "")).strip()
        if not filename or not reason or not next_action:
            raise ValueError("Every admission candidate needs file, reason and next_action")
        if filename in candidates:
            raise ValueError(f"Duplicate reading admission candidate: {filename}")
        candidates[filename] = {"reason": reason, "next_action": next_action}
    unknown = sorted(set(candidates) - expected)
    if unknown:
        raise ValueError("Admission candidates are not task papers: " + ", ".join(unknown))
    admitted = expected - set(candidates)
    declared = data.get("canonical_count")
    if declared is not None and int(declared) != len(admitted):
        raise ValueError(
            f"Reading admission canonical_count={declared} but resolved {len(admitted)} files"
        )
    return admitted, candidates


def load_reading_cards(
    paper_files: list[Path], path: Path = READING_CARDS_PATH
) -> dict[str, dict[str, str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cards = data.get("papers", {})
    expected = {path.name for path in paper_files}
    actual = set(cards)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    result = {filename: cards[filename] for filename in sorted(expected & actual)}
    for filename, card in result.items():
        missing_fields = [field for field in READING_CARD_FIELDS if not str(card.get(field, "")).strip()]
        if missing_fields:
            raise ValueError(f"Reading card {filename} is missing: {', '.join(missing_fields)}")
    paper_by_name = {paper.name: paper for paper in paper_files}
    for filename in missing:
        result[filename] = fallback_reading_card(paper_by_name[filename])
    if missing:
        print("NOTICE - Using provisional reading cards for new papers: " + ", ".join(missing))
    if extra:
        print("NOTICE - Ignoring reading cards whose task papers are absent: " + ", ".join(extra))
    return result


def load_learning_path(
    paper_files: list[Path],
    titles: dict[str, str],
    path: Path = LEARNING_PATH_PATH,
    admitted_files: set[str] | None = None,
) -> tuple[list[dict], dict[str, dict]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_stages = data.get("stages")
    if not isinstance(raw_stages, list) or not raw_stages:
        raise ValueError("Learning path must define at least one stage")

    expected = set(admitted_files) if admitted_files is not None else {paper.name for paper in paper_files}
    stages = []
    flattened = []
    stale = []
    for raw_stage_number, raw_stage in enumerate(raw_stages, start=1):
        name = str(raw_stage.get("name", "")).strip() if isinstance(raw_stage, dict) else ""
        purpose = str(raw_stage.get("purpose", "")).strip() if isinstance(raw_stage, dict) else ""
        entry = str(raw_stage.get("entry", "")).strip() if isinstance(raw_stage, dict) else ""
        outcome = str(raw_stage.get("outcome", "")).strip() if isinstance(raw_stage, dict) else ""
        checkpoint = str(raw_stage.get("checkpoint", "")).strip() if isinstance(raw_stage, dict) else ""
        route_type = str(raw_stage.get("route_type", "")).strip() if isinstance(raw_stage, dict) else ""
        raw_papers = raw_stage.get("papers") if isinstance(raw_stage, dict) else None
        if (
            not name
            or not purpose
            or not entry
            or not outcome
            or not checkpoint
            or not route_type
            or not isinstance(raw_papers, list)
            or not raw_papers
        ):
            raise ValueError(f"Learning-path stage {raw_stage_number} is incomplete")
        papers = []
        for raw_paper in raw_papers:
            filename = str(raw_paper.get("file", "")).strip() if isinstance(raw_paper, dict) else ""
            bridge = str(raw_paper.get("bridge", "")).strip() if isinstance(raw_paper, dict) else ""
            if not filename or not bridge:
                raise ValueError(f"Learning-path entry is invalid: {filename or 'missing filename'}")
            if filename not in expected:
                stale.append(filename)
                continue
            item = {
                "file": filename,
                "title": titles[filename],
                "bridge": bridge,
                "stage_name": name,
                "stage_entry": entry,
                "stage_outcome": outcome,
                "stage_checkpoint": checkpoint,
                "route_type": route_type,
                "unsequenced": False,
            }
            papers.append(item)
            flattened.append(item)
        if papers:
            stage_number = len(stages) + 1
            for stage_index, item in enumerate(papers, start=1):
                item.update(
                    stage_number=stage_number,
                    stage_index=stage_index,
                    stage_total=len(papers),
                )
            stages.append(
                {
                    "name": name,
                    "purpose": purpose,
                    "entry": entry,
                    "outcome": outcome,
                    "checkpoint": checkpoint,
                    "route_type": route_type,
                    "papers": papers,
                    "unsequenced": False,
                }
            )

    ordered = [item["file"] for item in flattened]
    actual = set(ordered)
    duplicates = sorted({filename for filename in ordered if ordered.count(filename) > 1})
    if duplicates:
        raise ValueError(f"Learning-path entries are repeated: {', '.join(duplicates)}")

    unplanned = sorted(expected - actual, key=lambda filename: titles[filename].casefold())
    if unplanned:
        stage_number = len(stages) + 1
        papers = []
        for stage_index, filename in enumerate(unplanned, start=1):
            item = {
                "file": filename,
                "title": titles[filename],
                "bridge": "这是任务中新出现的专题，尚未完成人工依赖编排；先独立浏览，不假定它与相邻新增文档存在前置关系。",
                "stage_name": "新增内容待编排",
                "stage_number": stage_number,
                "stage_index": stage_index,
                "stage_total": len(unplanned),
                "stage_entry": "这些页面尚未完成人工前置依赖审校。",
                "stage_outcome": "只做独立浏览，不据此推断与相邻页面的顺序关系。",
                "stage_checkpoint": "该页面是否已经明确独立学习问题、证据边界和正式前置依赖？",
                "route_type": "待编排",
                "unsequenced": True,
            }
            papers.append(item)
            flattened.append(item)
        stages.append(
            {
                "name": "新增内容待编排",
                "purpose": "这些专题来自任务目录的最新更新。Reader 先保证它们可发现、可阅读，再由人工确认前置依赖和正式位置。",
                "entry": "这些页面尚未完成人工前置依赖审校。",
                "outcome": "只做独立浏览，不据此推断与相邻页面的顺序关系。",
                "checkpoint": "该页面是否已经明确独立学习问题、证据边界和正式前置依赖？",
                "route_type": "待编排",
                "papers": papers,
                "unsequenced": True,
            }
        )
        print("NOTICE - Appending new papers to the unplanned inbox: " + ", ".join(unplanned))
    if stale:
        print("NOTICE - Ignoring learning-path entries whose task papers are absent: " + ", ".join(sorted(set(stale))))

    contexts = {}
    for index, item in enumerate(flattened):
        item["overall_index"] = index + 1
        previous = flattened[index - 1] if index else None
        following = flattened[index + 1] if index + 1 < len(flattened) else None
        if item["unsequenced"] or (previous and previous["unsequenced"]):
            previous = None
        if item["unsequenced"] or (following and following["unsequenced"]):
            following = None
        contexts[item["file"]] = {
            **item,
            "overall_index": item["overall_index"],
            "overall_total": len(flattened),
            "previous": previous,
            "next": following,
        }
    return stages, contexts


def reading_card(card: dict[str, str], learning: dict | None = None) -> str:
    escaped = {key: html.escape(str(value)) for key, value in card.items()}
    facts = (
        ("提出背景", "background"),
        ("遗留问题", "legacy"),
        ("团队信息", "team"),
        ("论文影响力", "impact"),
    )
    fact_html = "".join(
        '<article class="paper-reading-card__fact">'
        f'<span class="paper-reading-card__label">{label}</span><p>{escaped[key]}</p></article>'
        for label, key in facts
    )
    route_html = ""
    if learning:
        previous = learning.get("previous")
        following = learning.get("next")
        route_links = []
        if previous:
            route_links.append(
                f'<a href="../{html.escape(Path(previous["file"]).stem, quote=True)}/" rel="prev">'
                f'<small>上一篇</small><span>← {html.escape(previous["title"])}</span></a>'
            )
        if following:
            route_links.append(
                f'<a href="../{html.escape(Path(following["file"]).stem, quote=True)}/" rel="next">'
                f'<small>下一篇</small><span>{html.escape(following["title"])} →</span></a>'
            )
        stage_entry = ""
        if learning["stage_index"] == 1:
            stage_entry = (
                '<p class="paper-reading-card__stage-entry">'
                '<span class="paper-reading-card__label">阶段入口</span>'
                f'{html.escape(learning["stage_entry"])}</p>'
            )
        route_html = (
            '<div class="paper-reading-card__route">'
            '<div class="paper-reading-card__route-copy">'
            f'<span class="paper-reading-card__route-position">{html.escape(learning["route_type"])} · '
            f'阶段 {learning["stage_number"]} · '
            f'本阶段 {learning["stage_index"]}/{learning["stage_total"]}'
            f'<small>全路线 {learning["overall_index"]}/{learning["overall_total"]}</small></span>'
            f'<strong>{html.escape(learning["stage_name"])}</strong>'
            '<p><span class="paper-reading-card__label">从上一篇到本篇</span>'
            f'{html.escape(learning["bridge"])}</p>{stage_entry}</div>'
            f'<nav aria-label="相邻专题">{"".join(route_links)}</nav></div>'
        )
    return (
        '<section class="paper-reading-card" aria-label="专题阅读决策卡">'
        '<div class="paper-reading-card__topline">'
        '<span class="paper-reading-card__eyebrow">导读</span>'
        f'<span class="paper-reading-card__level">{escaped["level"]}</span>'
        f'<span class="paper-reading-card__effort">{escaped["effort"]}</span>'
        '</div>'
        '<div class="paper-reading-card__overview">'
        '<article><span class="paper-reading-card__label">这篇先回答</span>'
        f'<p>{escaped["problem"]}</p></article>'
        '<article><span class="paper-reading-card__label">按你的知识画像先补什么</span>'
        f'<p>{escaped["prerequisites"]}</p></article></div>'
        '<div class="paper-reading-card__first-pass">'
        '<span class="paper-reading-card__label">第一遍只做</span>'
        f'<p>{escaped["strategy"]}</p></div>'
        f'{route_html}'
        '<details class="paper-reading-card__details">'
        '<summary><span>查看完整导读</span>'
        '<small>背景 · 遗留问题 · 团队 · 影响力 · 阅读方法</small></summary>'
        '<div class="paper-reading-card__details-body">'
        f'<div class="paper-reading-card__facts">{fact_html}</div>'
        '<div class="paper-reading-card__actions">'
        '<article><span class="paper-reading-card__label">对你的价值</span>'
        f'<p>{escaped["value"]}</p></article></div>'
        '</div></details>'
        '</section>'
    )


def inject_reading_card(text: str, card: dict[str, str], learning: dict | None = None) -> str:
    first_line_end = text.find("\n")
    if not text.startswith("# ") or first_line_end < 0:
        raise ValueError("Paper review must start with a level-one heading")
    return text[: first_line_end + 1] + "\n" + reading_card(card, learning) + "\n\n" + text[first_line_end + 1 :]


def reading_route_footer(learning: dict | None) -> str:
    if not learning:
        return ""
    previous = learning.get("previous")
    following = learning.get("next")
    links = []
    if previous:
        links.append(
            '<a class="reading-route-footer__previous" '
            f'href="../{html.escape(Path(previous["file"]).stem, quote=True)}/" rel="prev">'
            f'<small>上一篇 · {html.escape(previous["stage_name"])}</small>'
            f'<strong>← {html.escape(previous["title"])}</strong></a>'
        )
    if following:
        links.append(
            '<a class="reading-route-footer__next" '
            f'href="../{html.escape(Path(following["file"]).stem, quote=True)}/" rel="next">'
            f'<small>下一篇 · {html.escape(following["stage_name"])}</small>'
            f'<strong>{html.escape(following["title"])} →</strong>'
            f'<span>{html.escape(following["bridge"])}</span></a>'
        )
    else:
        links.append(
            '<a class="reading-route-footer__next" href="../../reading-guide/">'
            '<small>路线终点</small><strong>返回完整阅读路线 →</strong></a>'
        )
    return (
        '<section class="reading-route-footer" aria-label="阅读路线续接">'
        '<header><span>阶段检查点</span>'
        f'<strong>{html.escape(learning["stage_name"])}</strong>'
        f'<p>{html.escape(learning["stage_checkpoint"])}</p></header>'
        f'<nav>{"".join(links)}</nav></section>'
    )


def inject_candidate_notice(text: str, metadata: dict[str, str]) -> str:
    """Mark a generated page as discoverable but outside the canonical route."""
    first_line_end = text.find("\n")
    if not text.startswith("# ") or first_line_end < 0:
        raise ValueError("Paper review must start with a level-one heading")
    notice = (
        '\n!!! warning "候选页面 · 不计入推荐路线"\n'
        f'    {metadata["reason"]}\n'
        f'    **准入前动作**：{metadata["next_action"]}\n'
    )
    return text[: first_line_end + 1] + notice + text[first_line_end + 1 :]


def relative_link(current: PurePosixPath, target: PurePosixPath) -> str:
    return os.path.relpath(str(target), str(current.parent)).replace(os.sep, "/")


def linkify(text: str, current: PurePosixPath, task_dir: Path) -> str:
    def destination(shown: str) -> str | None:
        raw_path = re.sub(r":\d+(?:--?\d+)?$", "", shown)
        path = PurePosixPath(raw_path)
        source = task_dir / path
        if path.parts[0] == "papers" and source.is_file() and path.suffix == ".md":
            target = path
        elif path.parts[0] == "sources" and len(path.parts) >= 2:
            source_id = path.parts[1]
            if source.is_file() and source.suffix.lower() == ".pdf":
                target = PurePosixPath("sources") / source_id / source.name
            elif (task_dir / "sources" / source_id).exists():
                target = PurePosixPath("sources") / source_id / "index.md"
            else:
                return None
        elif (
            path.parts[0] == "state"
            and path.name.startswith("coverage-matrix-")
            and source.is_file()
            and path.suffix == ".md"
        ):
            # State coverage matrices are task-local audit records.  Expose
            # them under the generated metadata section so links from the
            # report/status pages remain valid in the Reader copy.
            target = PurePosixPath("meta") / path.name
        elif path.as_posix().endswith("reader/reading-admission.yml") and READING_ADMISSION_PATH.is_file():
            target = PurePosixPath("meta") / "reading-admission.md"
        else:
            return None
        return relative_link(current, target)

    def replace_backtick(match: re.Match[str]) -> str:
        shown = match.group(1)
        target = destination(shown)
        return f"[`{shown}`]({target})" if target else match.group(0)

    def replace_markdown(match: re.Match[str]) -> str:
        shown = match.group(1)
        return destination(shown) or shown

    text = BACKTICK_PATH.sub(replace_backtick, text)
    text = MARKDOWN_PATH.sub(replace_markdown, text)
    text = STATE_MATRIX_PATH.sub(replace_markdown, text)
    return ADMISSION_PATH.sub(replace_markdown, text)


def matching_aliases(citation: str) -> dict[str, str]:
    matches: dict[str, str] = {}
    for alias, source_id in SOURCE_ALIASES.items():
        if re.search(rf"(?<![\w-]){re.escape(alias)}(?![\w-])", citation, re.IGNORECASE):
            matches[alias] = source_id
    return matches


def rendered_html_path(current: PurePosixPath) -> PurePosixPath:
    if current.name == "index.md":
        return current.with_suffix(".html")
    return current.parent / current.stem / "index.html"


def link_citations(
    text: str,
    current: PurePosixPath,
    task_dir: Path,
    primary_source: str | None,
    audit: dict[str, int],
    overrides: dict[tuple[str, str, int], tuple[str, int]],
) -> str:
    occurrences: dict[str, int] = {}

    def replace(match: re.Match[str]) -> str:
        citation = match.group(1)
        full_citation = match.group(0)
        occurrences[full_citation] = occurrences.get(full_citation, 0) + 1
        override = overrides.get((current.name, full_citation, occurrences[full_citation]))
        audit["found"] += 1
        if override:
            source_id, page = override
            source_label = source_id
            audit["overridden"] += 1
        else:
            canonical = CANONICAL_SOURCE.search(citation)
            if canonical:
                source_id = canonical.group(1)
                source_label = source_id
            else:
                aliases = matching_aliases(citation)
                source_ids = set(aliases.values())
                if len(source_ids) > 1:
                    audit["ambiguous"] += 1
                    return match.group(0)
                if source_ids:
                    source_id = next(iter(source_ids))
                    source_label = next(alias for alias, value in aliases.items() if value == source_id)
                elif primary_source:
                    source_id = primary_source
                    source_label = source_id
                else:
                    audit["unresolved"] += 1
                    return match.group(0)
            page_match = PAGE.search(citation)
            if not page_match:
                audit["unresolved"] += 1
                return match.group(0)
            page = int(page_match.group(1))

        source_pdf = task_dir / "sources" / source_id / "paper.pdf"
        if not source_pdf.is_file():
            audit["unresolved"] += 1
            return match.group(0)
        pdf_target = PurePosixPath("sources") / source_id / "paper.pdf"
        # Raw HTML links are not rewritten by MkDocs. Account for directory-style
        # output (`papers/name/index.html`) instead of the source Markdown path.
        rendered_page = rendered_html_path(current)
        pdf_href = relative_link(rendered_page, pdf_target)
        href = pdf_href + f"#page={page}"
        escaped = html.escape(match.group(0))
        source_title = source_label if source_label != source_id else source_id
        locator_match = LOCATOR.search(citation)
        locator = locator_match.group(0) if locator_match else ""
        audit["linked"] += 1
        return (
            f'<a class="evidence-link" href="{html.escape(href, quote=True)}" '
            f'data-pdf="{html.escape(pdf_href, quote=True)}" '
            f'data-page="{page}" data-source-id="{html.escape(source_id, quote=True)}" '
            f'data-source-title="{html.escape(source_title, quote=True)}"'
            f'{f" data-locator=\"{html.escape(locator, quote=True)}\"" if locator else ""}'
            f'{" data-primary=\"true\"" if source_id == primary_source else ""}>{escaped}</a>'
        )

    return CITATION.sub(replace, text)


def hardlink_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def source_page(source_dir: Path, destination: Path) -> None:
    files = sorted(path for path in source_dir.rglob("*") if path.is_file())
    pdfs = [path for path in files if path.suffix.lower() == ".pdf"]
    lines = [f"# 来源：{source_dir.name}", "", f"原始目录：`{source_dir}`", ""]
    if pdfs:
        lines.extend(["## 原始论文", ""])
        for pdf in pdfs:
            target_name = pdf.name if pdf.parent == source_dir else "-".join(pdf.relative_to(source_dir).parts)
            hardlink_or_copy(pdf, destination.parent / target_name)
            lines.append(f"- [{pdf.relative_to(source_dir)}]({target_name})")
        lines.append("")
    evidence = source_dir / "evidence.md"
    if evidence.is_file():
        lines.extend(["## 证据说明", "", evidence.read_text(encoding="utf-8"), ""])
    lines.extend(["## 文件清单", "", '<div class="source-inventory">', ""])
    for path in files:
        relative = path.relative_to(source_dir)
        size = path.stat().st_size
        lines.append(f"- `{html.escape(str(relative))}` · {size:,} bytes")
    lines.extend(["", "</div>", "", "!!! note", "    除上方 PDF 外，清单中的文件保留在原始任务目录，本站不会执行或改写这些工件。", ""])
    destination.write_text("\n".join(lines), encoding="utf-8")


def learning_path_markdown(
    stages: list[dict], candidate_items: list[dict[str, str]] | None = None
) -> str:
    lines = []
    overall_index = 0
    for stage_number, stage in enumerate(stages, start=1):
        lines.extend([
            f'<section class="learning-stage" id="learning-stage-{stage_number}">',
            '<header class="learning-stage__header">',
            f'<span>{html.escape(stage["route_type"])} · 阶段 {stage_number}</span><h3>{html.escape(stage["name"])}</h3>',
            f'<p>{html.escape(stage["purpose"])}</p>',
            '</header>',
            '<div class="learning-stage__contract">',
            f'<p><span>进入前</span>{html.escape(stage["entry"])}</p>',
            f'<p><span>读完后</span>{html.escape(stage["outcome"])}</p>',
            '</div>',
            f'<ol class="learning-stage__papers" start="{overall_index + 1}">',
        ])
        for item in stage["papers"]:
            overall_index += 1
            target = f'papers/{html.escape(Path(item["file"]).stem, quote=True)}/'
            level = html.escape(str(item.get("level", "专题精读")))
            effort = html.escape(str(item.get("effort", "")))
            lines.extend([
                '<li>',
                '<div class="learning-stage__paper-heading">',
                f'<a href="{target}">{html.escape(item["title"])}</a>',
                f'<span>{level}{" · " + effort if effort else ""}</span>',
                '</div>',
                f'<p>{html.escape(item["bridge"])}</p>',
                '</li>',
            ])
        lines.extend([
            '</ol>',
            '<div class="learning-stage__checkpoint">',
            f'<span>阶段检查</span><p>{html.escape(stage["checkpoint"])}</p>',
            '</div>',
            '</section>',
            '',
        ])
    if candidate_items:
        lines.extend(
            [
                "### 候选页面（不计入推荐路线）",
                "",
                "这些页面仍可打开和回查证据，但没有 canonical 阅读卡或路线位置。",
                "",
                "| 页面 | 当前边界 | 准入前动作 |",
                "|---|---|---|",
            ]
        )
        for item in candidate_items:
            target = f'papers/{Path(item["file"]).stem}.md'
            lines.append(
                f'| [{item["title"]}]({target}) | {item["reason"]} | {item["next_action"]} |'
            )
        lines.append("")
    return "\n".join(lines).rstrip()


def write_summary(
    docs_dir: Path,
    stages: list[dict],
    candidate_items: list[dict[str, str]] | None = None,
) -> None:
    lines = [
        "- [开始阅读](index.md)",
        "- [阅读指南](reading-guide.md)",
        "- [综合报告](report/index.md)",
        "- 专题精读（推荐顺序）",
    ]
    for stage_number, stage in enumerate(stages, start=1):
        lines.append(f'    - 阶段 {stage_number} · {stage["name"]}')
        for item in stage["papers"]:
            lines.append(
                f'        - [{item["overall_index"]:02d} · {item["title"]}]'
                f'(papers/{item["file"]})'
            )
    if candidate_items:
        lines.append("- 候选页面（不计入推荐路线）")
        for item in candidate_items:
            lines.append(f'    - [{item["title"]}](papers/{item["file"]})')
    lines.extend(
        [
            "- 证据与来源",
            "    - [来源总目录](sources/index.md)",
            "    - [原始来源索引](sources/catalog.md)",
            "- 任务信息",
            "    - [当前状态](meta/status.md)",
            "    - [运行历史](meta/run-history.md)",
            "    - [PDF 引用审计](meta/citation-audit.md)",
            f"    - [生成说明](meta/about.md)",
        ]
    )
    (docs_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare(task_id: str) -> None:
    task_dir = (REPO_DIR / "tasks" / task_id).resolve()
    required = [task_dir / "REPORT.md", task_dir / "SOURCES.md", task_dir / "papers", task_dir / "sources"]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("Missing task inputs:\n" + "\n".join(missing))

    docs_dir = READER_DIR / "docs"
    if docs_dir.exists():
        shutil.rmtree(docs_dir)
    shutil.copytree(READER_DIR / "content", docs_dir)
    for subdir in ("report", "papers", "sources", "meta"):
        (docs_dir / subdir).mkdir(parents=True, exist_ok=True)

    audit = {"found": 0, "linked": 0, "ambiguous": 0, "unresolved": 0, "overridden": 0}
    citation_overrides = load_citation_overrides()
    report_path = PurePosixPath("report/index.md")
    report = linkify((task_dir / "REPORT.md").read_text(encoding="utf-8"), report_path, task_dir)
    report = link_citations(report, report_path, task_dir, None, audit, citation_overrides)
    (docs_dir / "report" / "index.md").write_text(report, encoding="utf-8")

    paper_files = sorted((task_dir / "papers").glob("*.md"))
    admitted_files, candidate_metadata = load_reading_admission(paper_files)
    reading_cards = load_reading_cards(paper_files)
    titles = {path.name: NAV_TITLE_OVERRIDES.get(path.name, title_of(path)) for path in paper_files}
    candidate_items = [
        {"file": filename, "title": titles[filename], **candidate_metadata[filename]}
        for filename in sorted(candidate_metadata, key=lambda item: titles[item].casefold())
    ]
    learning_stages, learning_contexts = load_learning_path(
        paper_files, titles, admitted_files=admitted_files
    )
    for stage in learning_stages:
        for item in stage["papers"]:
            item.update(
                level=reading_cards[item["file"]]["level"],
                effort=reading_cards[item["file"]]["effort"],
            )
            learning_contexts[item["file"]].update(
                level=item["level"],
                effort=item["effort"],
            )
    guide_path = docs_dir / "reading-guide.md"
    guide = guide_path.read_text(encoding="utf-8")
    marker = "<!-- GENERATED_LEARNING_PATH -->"
    if marker not in guide:
        raise ValueError("Reading guide is missing the learning-path marker")
    guide_path.write_text(
        guide.replace(marker, learning_path_markdown(learning_stages, candidate_items)),
        encoding="utf-8",
    )
    for source in paper_files:
        current = PurePosixPath("papers") / source.name
        transformed = linkify(source.read_text(encoding="utf-8"), current, task_dir)
        transformed = link_citations(
            transformed,
            current,
            task_dir,
            PAPER_PRIMARY.get(source.name),
            audit,
            citation_overrides,
        )
        transformed = inject_reading_card(
            transformed, reading_cards[source.name], learning_contexts.get(source.name)
        )
        if source.name in candidate_metadata:
            transformed = inject_candidate_notice(transformed, candidate_metadata[source.name])
        route_footer = reading_route_footer(learning_contexts.get(source.name))
        if route_footer:
            transformed += "\n\n" + route_footer + "\n"
        (docs_dir / current).write_text(transformed, encoding="utf-8")

    catalog = linkify((task_dir / "SOURCES.md").read_text(encoding="utf-8"), PurePosixPath("sources/catalog.md"), task_dir)
    (docs_dir / "sources" / "catalog.md").write_text(catalog, encoding="utf-8")

    source_dirs = sorted(path for path in (task_dir / "sources").iterdir() if path.is_dir())
    index_lines = ["# 原始来源索引", "", f"共 {len(source_dirs)} 个稳定来源目录。每页列出原始文件，并在存在时提供浏览器可读 PDF。", ""]
    for directory in source_dirs:
        destination = docs_dir / "sources" / directory.name / "index.md"
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_page(directory, destination)
        index_lines.append(f"- [{directory.name}]({directory.name}/index.md)")
    (docs_dir / "sources" / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")

    for source_name, target_name, title in (
        ("STATUS.md", "status.md", "当前状态"),
        ("RUN_HISTORY.md", "run-history.md", "运行历史"),
    ):
        body = (task_dir / source_name).read_text(encoding="utf-8")
        body = linkify(body, PurePosixPath("meta") / target_name, task_dir)
        (docs_dir / "meta" / target_name).write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    for matrix in sorted((task_dir / "state").glob("coverage-matrix-*.md")):
        body = linkify(matrix.read_text(encoding="utf-8"), PurePosixPath("meta") / matrix.name, task_dir)
        (docs_dir / "meta" / matrix.name).write_text(body, encoding="utf-8")
    admission_copy = docs_dir / "meta" / "reading-admission.md"
    admission_copy.write_text(
        "# Reader admission 配置\n\n"
        "这是本次生成所用的只读准入配置快照。\n\n"
        "```yaml\n"
        + READING_ADMISSION_PATH.read_text(encoding="utf-8")
        + "```\n",
        encoding="utf-8",
    )
    (docs_dir / "meta" / "about.md").write_text(
        "# 生成说明\n\n"
        f"- 任务 ID：`{task_id}`\n"
        f"- 只读输入：`{task_dir}`\n"
        f"- 生成目录：`{docs_dir}`\n"
        f"- 研究文档：{len(paper_files)} 篇\n"
        f"- canonical 阅读路线：{len(admitted_files)} 篇\n"
        f"- 候选页面（不计入路线）：{len(candidate_items)} 篇\n"
        f"- 来源目录：{len(source_dirs)} 个\n\n"
        "`reader/docs/` 和 `reader/site/` 均可删除并重新生成；原始任务文件不会被修改。\n",
        encoding="utf-8",
    )
    (docs_dir / "meta" / "citation-audit.md").write_text(
        "# PDF 引用映射审计\n\n"
        "生成器只链接来源唯一、页码明确且本地固定 PDF 存在的引用。歧义引用保持原文，不进行猜测。\n\n"
        f"- 发现带页码引用：{audit['found']}\n"
        f"- 已链接到右侧 PDF：{audit['linked']}\n"
        f"- 多来源歧义：{audit['ambiguous']}\n"
        f"- 来源或 PDF 未确定：{audit['unresolved']}\n\n"
        f"- reader 人工覆盖：{audit['overridden']}\n\n"
        "多页引用打开范围的第一页；链接目标是固定 PDF 的物理页码。快捷键点击仍可在新标签页打开。\n\n"
        "## 旧文档中发现的主要问题\n\n"
        "- 同一个方括号混入多个来源，例如 `[T17 p.3; BERT p.4]`，Reader 无法安全决定点击目标。\n"
        "- 只写 `[p.6]` 或依赖专题文首的隐式主来源，引用离开该文档后便失去身份。\n"
        "- 使用 `T17`、`K20`、`R20` 等临时代号；只有生成器预先登记的少量别名可以解析。\n"
        "- 混用物理页、印刷页、章节页或 alternate-layout 页码，页面数字看似正确但实际版式不同。\n"
        "- 把多个相距很远的页段压进一个引用；Reader 只能打开第一个页码，后续位置仍需手找。\n"
        "- `§`、Figure、Table、Equation 等定位符过去只展示、不传给 PDF Viewer，因而只能跳页。\n\n"
        "## 新产出规范\n\n"
        "统一写作 `[PDF:<stable-id> p.<physical-page> <locator>]`；一个方括号只放一个 stable-id。"
        "该格式不依赖别名表，并可把章节/图表定位符传给 PDF Viewer 做页内高亮。\n",
        encoding="utf-8",
    )
    write_summary(docs_dir, learning_stages, candidate_items)
    print(
        f"Prepared {len(paper_files)} reviews and {len(source_dirs)} source pages from {task_dir}; "
        f"linked {audit['linked']}/{audit['found']} paged citations"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID)
    args = parser.parse_args()
    prepare(args.task_id)


if __name__ == "__main__":
    main()
