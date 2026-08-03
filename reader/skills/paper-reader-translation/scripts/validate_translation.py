#!/usr/bin/env python3
"""Validate a cached Reader page translation without third-party packages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    value = json.loads(args.path.read_text(encoding="utf-8"))
    required = {
        "source_id", "page", "pdf_sha256", "protocol_version", "source_text_sha256",
        "translation", "glossary_updates", "warnings",
    }
    missing = sorted(required - value.keys())
    if missing:
        raise SystemExit(f"missing fields: {', '.join(missing)}")
    if not isinstance(value["page"], int) or value["page"] < 1:
        raise SystemExit("page must be a positive integer")
    if not isinstance(value["translation"], str) or not value["translation"].strip():
        raise SystemExit("translation must be non-empty")
    if value["protocol_version"] not in {"paper-reader-translation-v1", "paper-reader-translation-v2"}:
        raise SystemExit("unsupported translation protocol")
    blocks = value.get("blocks")
    if blocks is None:
        if value["protocol_version"] != "paper-reader-translation-v1":
            raise SystemExit("blocks are required for this translation protocol")
        blocks = []
    if not isinstance(blocks, list) or (value["protocol_version"] != "paper-reader-translation-v1" and not blocks):
        raise SystemExit("blocks must be a non-empty array")
    block_ids = set()
    for block in blocks:
        if not isinstance(block, dict):
            raise SystemExit("blocks must contain objects")
        required_block = {"id", "physical_page", "type", "order", "original_text", "translation", "confidence", "bbox", "refs"}
        missing_block = sorted(required_block - block.keys())
        if missing_block:
            raise SystemExit(f"block missing fields: {', '.join(missing_block)}")
        if block["id"] in block_ids or not isinstance(block["id"], str):
            raise SystemExit("block ids must be unique strings")
        block_ids.add(block["id"])
        if block["physical_page"] != value["page"]:
            raise SystemExit("block page does not match translation page")
        if not isinstance(block["translation"], str) or not block["translation"].strip():
            raise SystemExit("block translation must be non-empty")
        if block["confidence"] not in {"high", "medium", "low"}:
            raise SystemExit("block confidence is invalid")
        table_data = block.get("table_data")
        if table_data is not None:
            headers = table_data.get("headers") if isinstance(table_data, dict) else None
            rows = table_data.get("rows") if isinstance(table_data, dict) else None
            if block["type"] not in {"table", "table_row"} or not isinstance(headers, list) or not headers:
                raise SystemExit("table_data is invalid")
            if not isinstance(rows, list) or not rows or any(not isinstance(row, list) or len(row) != len(headers) for row in rows):
                raise SystemExit("table_data rows must match headers")
        figure_data = block.get("figure_data")
        if figure_data is not None:
            if (
                block["type"] != "figure"
                or not isinstance(figure_data, dict)
                or figure_data.get("kind") not in {"diagram", "chart", "illustration", "photo", "other"}
                or not isinstance(figure_data.get("summary"), str)
                or not figure_data["summary"].strip()
                or not isinstance(figure_data.get("labels"), list)
                or not isinstance(figure_data.get("flow_steps"), list)
                or not isinstance(figure_data.get("notes"), list)
            ):
                raise SystemExit("figure_data is invalid")
    if not isinstance(value["glossary_updates"], list) or not isinstance(value["warnings"], list):
        raise SystemExit("glossary_updates and warnings must be arrays")
    print("Translation cache is valid")


if __name__ == "__main__":
    main()
