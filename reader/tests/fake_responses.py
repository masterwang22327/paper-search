#!/usr/bin/env python3
"""Small local Responses API stand-in for translation tests."""

from __future__ import annotations

import argparse
import base64
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ANSWER = {
    "translation": "Transformer 遵循这种整体架构，前向状态 h⃗_t 经过编码器和解码器，并使用自注意力层。",
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
            "translation": "模型质量对比，前向状态记为 h⃗_t。",
            "confidence": "medium",
            "bbox": None,
            "refs": ["table-1"],
            "table_data": {
                "headers": ["模型", "质量"],
                "rows": [["Base", "27.3"], ["Big", "28.4"]],
                "notes": ["数值保持原文。"],
            },
            "figure_data": None,
        },
    ],
    "glossary_updates": [{"term": "self-attention", "translation": "自注意力"}],
    "warnings": [],
}

REVISION_ANSWER = {
    "kind": "correction",
    "title": "并行能力的适用范围",
    "summary": "训练阶段可并行处理已知序列位置，但自回归生成仍受前序 token 依赖限制。",
    "markdown": r"Transformer 的并行优势主要体现在训练阶段。自回归生成时，第 \(t\) 个 token 仍依赖此前输出，因此不能把训练并行直接等同于生成并行。",
    "diagram": None,
    "visual_html": None,
    "change_note": "补充了训练与生成阶段的边界，避免原结论被过度概括。",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:
        pass

    def do_GET(self) -> None:
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/v1/responses":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        user_input = next(item for item in request["input"] if item.get("role") == "user")
        content = user_input["content"]
        image_item = next((item for item in content if item["type"] == "input_image"), None)
        image_bytes = base64.b64decode(image_item["image_url"].split(",", 1)[1]) if image_item else b""
        schema_name = request.get("text", {}).get("format", {}).get("name")
        log_path = os.environ.get("FAKE_RESPONSES_LOG")
        if log_path:
            record = {
                "authorized": self.headers.get("Authorization") == "Bearer test-translation-key",
                "model": request.get("model"),
                "reasoning": request.get("reasoning"),
                "store": request.get("store"),
                "text": request.get("text"),
                "prompt": next(item["text"] for item in content if item["type"] == "input_text"),
                "schema_name": schema_name,
                "system_prompt": next((part["text"] for item in request["input"] if item.get("role") == "system" for part in item.get("content", []) if part.get("type") == "input_text"), ""),
                "image_detail": image_item.get("detail") if image_item else None,
                "image_signature": image_bytes[:8].hex(),
                "image_size": len(image_bytes),
            }
            with Path(log_path).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        value = {
            "id": "resp-test-001",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(REVISION_ANSWER if schema_name == "reader_document_revision" else ANSWER, ensure_ascii=False)}],
                }
            ],
        }
        event = {"type": "response.completed", "response": value}
        body = ("data: " + json.dumps(event, ensure_ascii=False) + "\n\ndata: [DONE]\n\n").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
