"""Add stable block identities and a verification manifest to research pages."""

from __future__ import annotations

import hashlib
import html
import json
from html import escape
from html.parser import HTMLParser
from pathlib import Path


BLOCK_TAGS = {"p", "pre", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6"}
MANIFEST: dict[str, dict] = {}


class BlockAnnotator(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.blocks: list[dict] = []
        self.open_blocks: list[dict] = []
        self.counter = 0
        self.list_counter = 0
        self.semantic_counter = 0
        self.list_stack: list[dict] = []
        self.semantic_order: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        raw = self.get_starttag_text()
        if tag in {"ol", "ul"}:
            self.semantic_counter += 1
            group = {"id": f"sl{self.semantic_counter:05d}", "tag": tag, "item_ids": []}
            self.list_stack.append(group)
            self.semantic_order.append({"kind": "list", "value": group})
        if tag in BLOCK_TAGS or tag == "li":
            if tag == "li":
                self.list_counter += 1
                block_id = f"l{self.list_counter:05d}"
            else:
                self.counter += 1
                block_id = f"b{self.counter:05d}"
            block = {"id": block_id, "tag": tag, "text": []}
            if tag == "li" and self.list_stack:
                block["semantic_id"] = self.list_stack[-1]["id"]
                self.list_stack[-1]["item_ids"].append(block_id)
            else:
                block["semantic_id"] = block_id
                self.semantic_order.append({"kind": "block", "value": block})
            self.blocks.append(block)
            self.open_blocks.append(block)
            raw = raw[:-1] + f' data-reader-block="{block["id"]}">'
        self.parts.append(raw)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(f"</{tag}>")
        for index in range(len(self.open_blocks) - 1, -1, -1):
            if self.open_blocks[index]["tag"] == tag:
                self.open_blocks.pop(index)
                break
        if tag in {"ol", "ul"} and self.list_stack:
            self.list_stack.pop()

    def handle_data(self, data: str) -> None:
        self.parts.append(html.escape(data, quote=False))
        for block in self.open_blocks:
            block["text"].append(data)

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self.parts.append(f"<!{decl}>")


def on_pre_build(**kwargs) -> None:
    MANIFEST.clear()


def on_page_content(html: str, page, **kwargs) -> str:
    document_id = page.file.src_uri
    if not (document_id.startswith("papers/") or document_id == "report/index.md"):
        return html
    annotator = BlockAnnotator()
    annotator.feed(html)
    annotator.close()
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()
    MANIFEST[document_id] = {
        "sha256": digest,
        "blocks": {block["id"]: "".join(block["text"]) for block in annotator.blocks},
        "block_to_semantic": {block["id"]: block["semantic_id"] for block in annotator.blocks},
        "semantic_blocks": [
            {
                "id": entry["value"]["id"],
                "kind": entry["kind"],
                "text": (
                    "\n".join(
                        f'{index}. {next(("".join(block["text"]) for block in annotator.blocks if block["id"] == item_id), "")}'
                        if entry["value"]["tag"] == "ol"
                        else f'- {next(("".join(block["text"]) for block in annotator.blocks if block["id"] == item_id), "")}'
                        for index, item_id in enumerate(entry["value"]["item_ids"], start=1)
                    )
                    if entry["kind"] == "list"
                    else "".join(entry["value"]["text"])
                ),
                "member_block_ids": entry["value"].get("item_ids", [entry["value"]["id"]]),
            }
            for entry in annotator.semantic_order
            if entry["kind"] != "list" or entry["value"]["item_ids"]
        ],
    }
    marker = (
        '<div class="reader-document-meta" hidden '
        f'data-document-id="{escape(document_id, quote=True)}" '
        f'data-document-sha256="{digest}"></div>'
    )
    return marker + "".join(annotator.parts)


def on_post_build(config, **kwargs) -> None:
    destination = Path(config.site_dir) / "context-manifest.json"
    destination.write_text(
        json.dumps({"schema_version": 1, "documents": MANIFEST}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
