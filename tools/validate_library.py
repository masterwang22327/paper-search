#!/usr/bin/env python3
"""Validate the repository's paper metadata against its lightweight schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "library"
SCHEMA_PATH = ROOT / "schemas" / "paper.schema.json"
ALLOWED_ARTIFACT_STATUSES = {
    "verified",
    "author_linked",
    "author_claimed",
    "community_implementation",
    "not_found",
    "not_released",
    "not_checked",
    "not_applicable",
}
ALLOWED_PAPER_STATUSES = {
    "preprint", "conference_paper", "journal_article", "technical_report", "other",
}
ALLOWED_READING_STATUSES = {"candidate", "screened", "reading", "reviewed", "archived"}


class MetadataError(ValueError):
    """A concise validation error for one paper metadata record."""


def load_yaml(path: Path) -> dict[str, Any]:
    """Use PyYAML when available; emit a direct install hint otherwise."""
    try:
        import yaml
    except ImportError as error:
        raise MetadataError("PyYAML is required: install with `python3 -m pip install PyYAML`") from error
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise MetadataError(f"invalid YAML: {error}") from error
    if not isinstance(data, dict):
        raise MetadataError("metadata must be a YAML mapping")
    return data


def validate_record(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("id", "title", "year", "status", "reading_status", "source"):
        if field not in data:
            errors.append(f"missing required field: {field}")
    if not isinstance(data.get("id"), str) or not data.get("id", "").strip():
        errors.append("id must be a non-empty string")
    if not isinstance(data.get("title"), str) or not data.get("title", "").strip():
        errors.append("title must be a non-empty string")
    if not isinstance(data.get("year"), int) or isinstance(data.get("year"), bool):
        errors.append("year must be an integer")
    if data.get("status") not in ALLOWED_PAPER_STATUSES:
        errors.append(f"invalid status: {data.get('status')}")
    if data.get("reading_status") not in ALLOWED_READING_STATUSES:
        errors.append(f"invalid reading_status: {data.get('reading_status')}")
    source = data.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("official"), bool):
        errors.append("source.official must be a boolean")
    artifacts = data.get("artifacts", {})
    if artifacts is not None and not isinstance(artifacts, dict):
        errors.append("artifacts must be a mapping")
    elif isinstance(artifacts, dict):
        for name, artifact in artifacts.items():
            if name in {"checked_at", "community_reproductions", "license"}:
                continue
            if not isinstance(artifact, dict):
                errors.append(f"artifacts.{name} must be a mapping")
                continue
            status = artifact.get("status")
            if status is not None and status not in ALLOWED_ARTIFACT_STATUSES:
                errors.append(f"artifacts.{name}.status is invalid: {status}")
    return errors


def schema_errors(data: dict[str, Any]) -> list[str]:
    """Apply the published JSON Schema when jsonschema is installed."""
    try:
        import jsonschema
    except ImportError as error:
        raise MetadataError(
            "jsonschema is required: install with `python3 -m pip install jsonschema`"
        ) from error
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MetadataError(f"invalid schema: {error}") from error
    errors = sorted(
        jsonschema.Draft202012Validator(schema).iter_errors(data),
        key=lambda item: list(item.absolute_path),
    )
    return [
        f"schema {'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in errors
    ]


def validate_path(path: Path) -> list[str]:
    """Return all semantic and schema errors for one metadata file."""
    data = load_yaml(path)
    return validate_record(data) + schema_errors(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="metadata.yml file(s); defaults to library")
    args = parser.parse_args(argv)
    paths = args.paths or sorted(LIBRARY.rglob("metadata.yml"))
    if not paths:
        print("no metadata files found")
        return 0
    invalid = 0
    for path in paths:
        try:
            errors = validate_path(path)
        except (OSError, MetadataError) as error:
            errors = [str(error)]
        if errors:
            invalid += 1
            print(f"{path}: invalid", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
        else:
            print(f"{path}: ok")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
