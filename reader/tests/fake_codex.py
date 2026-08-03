#!/usr/bin/env python3
"""Small codex CLI stand-in for persistence/API tests; never calls a model."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


SESSION_ID = "11111111-2222-4333-8444-555555555555"
TRANSLATION_SESSION_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
args = sys.argv[1:]
prompt = sys.stdin.read()
log_path = os.environ.get("FAKE_CODEX_LOG")
if log_path:
    images = []
    for index, value in enumerate(args):
        if value in {"-i", "--image"} and index + 1 < len(args):
            image = Path(args[index + 1])
            images.append(
                {
                    "path": str(image),
                    "exists": image.is_file(),
                    "size": image.stat().st_size if image.is_file() else 0,
                    "png_signature": image.read_bytes()[:8].hex() if image.is_file() else "",
                }
            )
    with Path(log_path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"args": args, "prompt": prompt, "images": images}, ensure_ascii=False) + "\n")

output_path = None
for index, value in enumerate(args):
    if value in {"-o", "--output-last-message"} and index + 1 < len(args):
        output_path = Path(args[index + 1])
        break
if output_path is None:
    raise SystemExit(2)

schema_name = ""
if "--output-schema" in args:
    schema_index = args.index("--output-schema")
    if schema_index + 1 < len(args):
        schema_name = Path(args[schema_index + 1]).name

if schema_name == "faq.schema.json":
    answer = json.dumps(
        {
            "items": [
                {
                    "question": "为什么训练并行不等于生成并行？",
                    "answer": "训练时目标序列已知，可并行计算各位置损失；自回归生成必须等待前一 token。",
                    "knowledge_type": "mixed",
                    "evidence": [{"source_id": "arxiv-1706.03762v7", "page": 3}],
                }
            ]
        },
        ensure_ascii=False,
    )
elif schema_name == "translation-page.schema.json":
    answer = json.dumps(
        {
            "translation": "Transformer 遵循这种整体架构，编码器和解码器均使用堆叠的自注意力层。",
            "blocks": [
                {
                    "type": "figure",
                    "original_text": "Figure 1: The Transformer; Inputs; Outputs",
                    "translation": "图 1 展示 Transformer 的编码器—解码器流程。",
                    "confidence": "high",
                    "bbox": None,
                    "refs": ["figure-1"],
                    "table_data": None,
                    "figure_data": {
                        "kind": "diagram",
                        "summary": "输入经过编码器形成表示，解码器结合已生成输出逐步产生最终结果。",
                        "labels": [
                            {"original": "Inputs", "translation": "输入"},
                            {"original": "Outputs", "translation": "输出"},
                        ],
                        "flow_steps": ["输入进入编码器。", "编码器表示传给解码器。", "解码器逐步生成输出。"],
                        "notes": [],
                    },
                },
                {
                    "type": "table",
                    "original_text": "Model Quality Base 27.3 Big 28.4",
                    "translation": "模型质量对比。",
                    "confidence": "medium",
                    "bbox": None,
                    "refs": ["table-1"],
                    "figure_data": None,
                    "table_data": {
                        "headers": ["模型", "质量"],
                        "rows": [["Base", "27.3"], ["Big", "28.4"]],
                        "notes": ["数值保持原文。"],
                    },
                },
            ],
            "glossary_updates": [
                {"term": "self-attention", "translation": "自注意力"}
            ],
            "warnings": [],
        },
        ensure_ascii=False,
    )
else:
    answer = "这是 fake Codex 的测试回答，已验证正文选区与固定 PDF 上下文。"

output_path.write_text(answer, encoding="utf-8")
thread_id = TRANSLATION_SESSION_ID if schema_name == "translation-page.schema.json" else SESSION_ID
print(json.dumps({"type": "thread.started", "thread_id": thread_id}))
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": answer}}, ensure_ascii=False))
