#!/usr/bin/env python3
"""Normalize research Markdown citations to Reader's stable PDF syntax."""

from __future__ import annotations

import argparse
import importlib.util
import re
from pathlib import Path


READER_DIR = Path(__file__).resolve().parents[1]
PREPARE_PATH = READER_DIR / "scripts" / "prepare_docs.py"
SPEC = importlib.util.spec_from_file_location("prepare_docs", PREPARE_PATH)
prepare_docs = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(prepare_docs)

SOURCE_NAMES = {
    "AdamW": "arxiv-1711.05101v3", "Adam": "arxiv-1412.6980v9",
    "Bahdanau": "arxiv-1409.0473v7", "Sutskever": "neurips-2014-seq2seq",
    "GPT-1": "openai-2018-gpt1", "GPT-2": "openai-2019-gpt2",
    "RoBERTa": "arxiv-1907.11692v1", "BPE": "arxiv-1508.07909v5",
    "SentencePiece": "arxiv-1808.06226v1", "SP": "arxiv-1808.06226v1",
    "Pile": "arxiv-2101.00027v1", "Dedup": "arxiv-2107.06499v1",
    "RefinedWeb": "arxiv-2306.01116v1", "DCLM": "arxiv-2406.11794v2",
    "Kaplan": "arxiv-2001.08361v1", "K20": "arxiv-2001.08361v1",
    "Chinchilla": "arxiv-2203.15556v1", "C22": "arxiv-2203.15556v1",
    "Degeneration": "arxiv-1904.09751v2", "Length Bias": "arxiv-2212.08073v1",
    "MMLU": "arxiv-2009.03300v3", "HELM": "arxiv-2211.09110v2",
    "MT-Bench/Arena": "arxiv-2306.05685v4", "Lost in the Middle": "arxiv-2307.03172v3",
    "Lost": "arxiv-2307.03172v3", "RULER": "arxiv-2404.06654v3",
    "Emergence Mirage": "neurips-2023-emergence-mirage",
    "TruthfulQA": "arxiv-2109.07958v2", "Know-What-They-Know": "arxiv-2207.05221v4",
    "SelfCheckGPT": "arxiv-2303.08896v2", "FLAN": "arxiv-2109.01652v5",
    "CoT": "arxiv-2201.11903v6", "Self-consistency": "arxiv-2203.11171v4",
    "Transformer-XL": "acl-2019-transformer-xl", "RoFormer": "arxiv-2104.09864v5",
    "PagedAttention": "arxiv-2309.06180v1", "Orca": "osdi-2022-orca",
    "Efficient Scaling": "arxiv-2211.05102v1", "FA1": "arxiv-2205.14135v2",
    "FA2": "arxiv-2307.08691v1", "FA3": "arxiv-2407.08608v2",
    "FlashAttention": "arxiv-2205.14135v2", "Speculative Decoding": "icml-2023-speculative-decoding",
    "LLM.int8": "arxiv-2208.07339v2", "GPTQ": "arxiv-2210.17323v2",
    "SmoothQuant": "icml-2023-smoothquant", "Human Preferences": "neurips-2017-human-preferences",
    "Ziegler": "arxiv-1909.08593v2", "Reward Overoptimization": "icml-2023-reward-overoptimization",
    "RLOO": "arxiv-2402.14740v2", "DeepSeekMath": "arxiv-2402.03300v3",
    "Dr.GRPO": "arxiv-2503.20783v2", "R1": "arxiv-2501.12948v2",
    "DAPO": "arxiv-2503.14476v2", "GSPO": "arxiv-2507.18071v2",
    "SAPO": "arxiv-2511.20347v2", "GQA": "acl-2023-gqa",
    "SwiGLU": "arxiv-2002.05202v1", "DeepSeek-V2": "arxiv-2405.04434v5",
    "DeepSeek-V3": "arxiv-2412.19437v2", "Qwen3": "arxiv-2505.09388v1",
    "Llama 3": "arxiv-2407.21783v3", "Megatron": "arxiv-1909.08053v4",
    "ZeRO": "arxiv-1910.02054v3", "Mikolov 2013": "arxiv-1301.3781v3",
    "Mikolov": "arxiv-1301.3781v3", "Negative Sampling": "arxiv-1310.4546v1",
    "negative-sampling": "arxiv-1310.4546v1", "JMLR": "jmlr-2003-neural-lm",
    "RAG": "neurips-2020-rag", "R20": "neurips-2020-rag",
    "REALM": "icml-2020-realm", "RETRO": "icml-2022-retro",
    "NeurIPS 2023": "neurips-2023-data-constrained", "ICML 2024": "icml-2024-beyond-chinchilla",
}

SECTION_SOURCES = {
    "decoding.md": {2: "arxiv-1904.09751v2", 3: "arxiv-2212.08073v1"},
    "factuality-calibration-selfcheck.md": {
        2: "arxiv-2109.07958v2", 3: "arxiv-2207.05221v4", 4: "arxiv-2303.08896v2"
    },
    "instruction-cot-self-consistency.md": {
        2: "arxiv-2109.01652v5", 3: "arxiv-2201.11903v6", 4: "arxiv-2203.11171v4"
    },
    "pretransformer-gpt-lineage.md": {1: "neurips-2014-seq2seq", 2: "arxiv-1409.0473v7"},
}


def named_sources(value: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    combined = {**prepare_docs.SOURCE_ALIASES, **SOURCE_NAMES}
    for name, source_id in sorted(combined.items(), key=lambda item: len(item[0]), reverse=True):
        match = re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", value, re.IGNORECASE)
        if match and source_id not in {item[1] for item in found}:
            found.append((match.start(), source_id))
    return sorted(found)


def canonical(source_id: str, citation: str) -> str:
    body = citation[1:-1].strip()
    body = re.sub(r"^(?:作者主张|作者陈述|作者实验|来源事实(?:与机制重建|\+机制重建|\+本报告计算图重建)?|证据边界)[；;,，]\s*", "", body)
    return f"[PDF:{source_id} {body}]"


def normalize_body(body: str, primary: str | None, task_dir: Path) -> str | None:
    parts = re.split(r"\s*[；;]\s*", body)
    output: list[str] = []
    inherited = primary
    for part in parts:
        names = named_sources(part)
        sources = [source for _, source in names]
        if len(sources) > 1:
            return None
        source_id = sources[0] if sources else inherited
        if not source_id or not (task_dir / "sources" / source_id / "paper.pdf").is_file():
            return None
        inherited = source_id
        cleaned = re.sub(
            r"^(?:作者主张|作者陈述|作者实验|来源事实[^；;,，]*|证据边界)[；;,，]\s*", "", part
        ).strip()
        output.append(f"[PDF:{source_id} {cleaned}]")
    return " ".join(output)


def normalize_file(path: Path, task_dir: Path) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    primary = prepare_docs.PAPER_PRIMARY.get(path.name)
    active_source = primary
    section_sources = SECTION_SOURCES.get(path.name, {})
    changed = 0
    unresolved = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal active_source, changed, unresolved
        citation = match.group(0)
        body = match.group(1)
        existing = prepare_docs.CANONICAL_SOURCE.search(body)
        if existing:
            active_source = existing.group(1)
            return citation
        section_matches = list(re.finditer(r"(?m)^##\s+(\d+)(?:\.|\s)", text[:match.start()]))
        section = int(section_matches[-1].group(1)) if section_matches else 0
        section_source = section_sources.get(section, active_source)
        normalized = normalize_body(body, section_source, task_dir)
        if not normalized:
            unresolved += 1
            return citation
        normalized_sources = re.findall(r"\[PDF:([A-Za-z0-9._-]+)", normalized)
        if normalized_sources:
            active_source = normalized_sources[-1]
        changed += 1
        return normalized

    normalized = prepare_docs.CITATION.sub(replace, text)
    # Evidence-kind labels are prose metadata, not independently locatable PDF
    # evidence. Merge labels accidentally split from their following locator.
    label_pair = re.compile(
        r"\[PDF:([A-Za-z0-9._-]+) ((?:来源事实|作者主张|作者陈述|作者实验|证据边界)[^]]*)\] "
        r"\[PDF:\1 ([^]]*\bpp?\.?\s*\d+[^]]*)\]"
    )
    while True:
        merged = label_pair.sub(r"[PDF:\1 \2；\3]", normalized)
        if merged == normalized:
            break
        normalized = merged
    if normalized != text:
        path.write_text(normalized, encoding="utf-8")
    return changed, unresolved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_dir", type=Path)
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    files = [task_dir / "REPORT.md", *sorted((task_dir / "papers").glob("*.md"))]
    changed = unresolved = 0
    for path in files:
        file_changed, file_unresolved = normalize_file(path, task_dir)
        changed += file_changed
        unresolved += file_unresolved
    print(f"Normalized {changed} citations; {unresolved} require source-specific review")


if __name__ == "__main__":
    main()
