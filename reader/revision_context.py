"""Complete, server-owned article context for research revisions."""

from __future__ import annotations

import hashlib
import re




def reading_context(document: dict, markdown: str, selected_ids: list[str]) -> dict:
    outline = document.get("outline", [])
    headings = {item["block_id"]: item for item in outline}
    paths = document.get("block_sections", {})
    locations = [
        {"block_id": block_id, "heading_path": [headings[key] for key in paths.get(block_id, []) if key in headings]}
        for block_id in selected_ids
    ]
    # Include the entire enclosing H2, not just the last two nearby cells of a
    # table. Cross-section selections can have more than one enclosing section.
    roots = set()
    for location in locations:
        path = location["heading_path"]
        root = next((heading for heading in path if heading["level"] == 2), path[0] if path else None)
        if root:
            roots.add(root["block_id"])
    blocks = document.get("semantic_blocks", [])
    selected = set(selected_ids)
    selected_positions = [i for i, block in enumerate(blocks) if selected.intersection(block.get("member_block_ids", [block["id"]]))]
    candidates = [
        i for i, block in enumerate(blocks)
        if any(roots.intersection(paths.get(key, [])) for key in block.get("member_block_ids", [block["id"]]))
    ]
    if not candidates:
        candidates = sorted({i for pos in selected_positions for i in range(max(0, pos - 2), min(len(blocks), pos + 3))})
    included = {
        index: {**blocks[index], "selected": index in selected_positions, "truncated": False}
        for index in candidates
    }
    return {
        "outline": outline,
        "selection_locations": locations,
        "selected_section_blocks": [included[i] for i in sorted(included)],
        "article_markdown": markdown,
        "source_markdown_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        "rendered_content_sha256": document.get("sha256"),
        "usage": {
            "article_characters": len(markdown),
            "included_article_characters": len(markdown),
            "article_truncated": False,
            "section_candidate_blocks": len(candidates),
            "section_included_blocks": len(included),
            "section_truncated": len(included) < len(candidates) or any(b["truncated"] for b in included.values()),
            "heading_metadata_available": bool(outline),
        },
    }


def source_ids(text: str) -> list[str]:
    """Discover source identifiers, never browser-supplied filesystem paths."""
    return list(dict.fromkeys(re.findall(r"(?:\[PDF:|sources/)([A-Za-z0-9][A-Za-z0-9._-]{0,127})(?=[\s/\]])", text)))
