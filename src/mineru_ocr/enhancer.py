"""AI enhancement layer on top of MinerU output.

The original MinerU Markdown remains the evidence layer. This module writes a
single AI-oriented JSONL file beside it for retrieval and knowledge-base use.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol

from .doubao_client import DoubaoClient
from .errors import MinerUOCRError


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\((?P<target>[^)\s]+)(?:\s+[^)]*)?\)")
HEADING = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$")
SOURCE_PAGES = re.compile(r"<!--\s*MinerU source pages (?P<start>\d+)-(?P<end>\d+)\s*-->")
TEXT_ANALYSIS_CHARS = 40_000
HTML_TABLE = re.compile(r"<table\b.*?</table>", re.I | re.S)
HTML_BREAK = re.compile(r"<br\s*/?>", re.I)
HTML_BLOCK = re.compile(r"</?(?:p|div|section|article|header|footer|li|ul|ol|tbody|thead|tfoot)\b[^>]*>", re.I)
HTML_TAG = re.compile(r"</?[a-zA-Z][^>]*>")


class EnhancementError(MinerUOCRError):
    """Raised when the enhancement layer cannot produce a usable output."""


class EnhancementClient(Protocol):
    def analyze_image(self, image_path: str | Path, *, context: dict | None = None) -> dict: ...
    def analyze_text(self, markdown: str) -> dict: ...


@dataclass(frozen=True)
class EnhancementSource:
    root: Path
    markdown_path: Path
    assets_dir: Path | None
    stem: str
    manifest_path: Path | None = None


def enhance_output(
    path: str | Path,
    *,
    client: EnhancementClient | None = None,
) -> dict:
    """Enhance MinerU Markdown output and write an AI JSONL file.

    Parameters
    ----------
    path : path
        A ``*.mineru`` directory containing ``full.md`` or a published Markdown
        file with a sibling ``assets/`` directory.
    client : DoubaoClient, optional
        Pre-configured client; one will be constructed from environment
        variables when omitted.

    Returns
    -------
    dict
        Path and coverage metadata for the generated JSONL file.
    """
    source = _resolve_source(path)
    markdown = source.markdown_path.read_text(encoding="utf-8")
    images = _collect_images(source)

    owns_client = client is None
    if owns_client:
        client = DoubaoClient()

    clean_markdown = _clean_markdown(markdown)
    image_contexts = _extract_image_contexts(clean_markdown)
    try:
        image_results = _analyze_images(client, source, images, image_contexts)
        text_result, text_coverage = _analyze_text(client, clean_markdown, original_chars=len(markdown))
    finally:
        if owns_client and isinstance(client, DoubaoClient):
            client.close()

    chunks = _build_chunks(clean_markdown, image_results, text_result, text_coverage, source)
    return _write_outputs(source, chunks, image_results, text_coverage)


# ---------- collection ----------


def _resolve_source(raw_path: str | Path) -> EnhancementSource:
    path = Path(raw_path).resolve()
    if path.is_dir():
        full_md = path / "full.md"
        if not full_md.is_file():
            raise EnhancementError(f"full.md not found in {path}")
        manifest = path / "manifest.json"
        return EnhancementSource(
            root=path,
            markdown_path=full_md,
            assets_dir=path / "assets" if (path / "assets").is_dir() else None,
            stem="full",
            manifest_path=manifest if manifest.is_file() else None,
        )
    if path.is_file() and path.suffix.lower() == ".md":
        manifest = path.with_suffix(".manifest.json")
        return EnhancementSource(
            root=path.parent,
            markdown_path=path,
            assets_dir=path.parent / "assets" if (path.parent / "assets").is_dir() else None,
            stem=path.stem,
            manifest_path=manifest if manifest.is_file() else None,
        )
    raise EnhancementError(f"Expected a MinerU result directory or Markdown file: {path}")


def _collect_images(source: EnhancementSource) -> list[Path]:
    if source.assets_dir is None:
        return []
    return sorted(
        path for path in source.assets_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def _analyze_images(
    client: EnhancementClient,
    source: EnhancementSource,
    images: list[Path],
    image_contexts: dict[str, dict],
) -> list[dict]:
    results: list[dict] = []
    for image in images:
        relative = image.relative_to(source.root).as_posix()
        context = image_contexts.get(relative) or image_contexts.get(Path(relative).name) or {}
        try:
            semantics = client.analyze_image(image, context=context)
        except Exception as exc:  # tolerate single-image failures
            results.append({
                "file": relative,
                "context": context,
                "error": str(exc),
            })
            continue
        results.append({"file": relative, "context": context, **semantics})
    return results


def _analyze_text(client: EnhancementClient, markdown: str, *, original_chars: int | None = None) -> tuple[dict, dict]:
    segments = _segment_text(markdown)
    partials = [client.analyze_text(segment) for segment in segments]
    return _merge_text_results(partials), {
        "segments": len(segments),
        "input_chars": original_chars if original_chars is not None else len(markdown),
        "normalized_chars": len(markdown),
        "analyzed_chars": sum(len(segment) for segment in segments),
        "strategy": "html-normalized section-aware chunks",
    }


def _segment_text(markdown: str, limit: int = TEXT_ANALYSIS_CHARS) -> list[str]:
    lines = markdown.splitlines()
    segments: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        is_heading = bool(HEADING.match(line))
        if current and current_len + len(line) + 1 > limit and is_heading:
            segments.append("\n".join(current).strip())
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
        if current_len >= int(limit * 1.25):
            segments.append("\n".join(current).strip())
            current = []
            current_len = 0
    if current:
        segments.append("\n".join(current).strip())
    return [segment for segment in segments if segment]


def _merge_text_results(results: list[dict]) -> dict:
    merged = {"sections": [], "entities": [], "cross_references": [], "tags": []}
    entity_keys: set[tuple[str, str]] = set()
    tags: set[str] = set()
    for result in results:
        for section in result.get("sections") or []:
            if section.get("title") or section.get("summary"):
                merged["sections"].append(section)
        for entity in result.get("entities") or []:
            key = (str(entity.get("name", "")).strip(), str(entity.get("type", "")).strip())
            if key[0] and key not in entity_keys:
                entity_keys.add(key)
                merged["entities"].append(entity)
        for reference in result.get("cross_references") or []:
            text = str(reference).strip()
            if text and text not in merged["cross_references"]:
                merged["cross_references"].append(text)
        for tag in result.get("tags") or []:
            text = str(tag).strip()
            if text and text not in tags:
                tags.add(text)
                merged["tags"].append(text)
    return merged


# ---------- image context ----------


def _extract_image_contexts(markdown: str, *, window: int = 8) -> dict[str, dict]:
    lines = markdown.splitlines()
    section_stack: list[str] = []
    current_pages: tuple[int | None, int | None] = (None, None)
    contexts: dict[str, dict] = {}
    image_index = 0

    for index, line in enumerate(lines):
        pages = SOURCE_PAGES.search(line)
        if pages:
            current_pages = (int(pages.group("start")), int(pages.group("end")))
            continue
        heading = HEADING.match(line)
        if heading:
            level = len(heading.group("marks"))
            title = heading.group("title").strip()
            section_stack = section_stack[: level - 1] + [title]

        match = MARKDOWN_IMAGE.search(line)
        if not match:
            continue
        image_index += 1
        target = match.group("target").strip("<>")
        caption = _find_caption(lines, index)
        before = _nearby_text(lines, index - 1, -1, -1, window)
        after = _nearby_text(lines, index + 1, len(lines), 1, window)
        context = {
            "image_index": image_index,
            "image_ref": target,
            "section_path": list(section_stack),
            "page_range": list(current_pages) if all(current_pages) else None,
            "caption": caption,
            "nearby_text_before": before,
            "nearby_text_after": after,
            "document_hint": _document_hint(section_stack, caption, before, after),
        }
        contexts[target] = context
        contexts[Path(target).name] = context
    return contexts


def _find_caption(lines: list[str], image_line_index: int) -> str | None:
    candidates: list[str] = []
    for offset in range(1, 5):
        probe = image_line_index + offset
        if probe >= len(lines):
            break
        text = lines[probe].strip()
        if not text or MARKDOWN_IMAGE.search(text):
            continue
        candidates.append(text)
        if re.search(r"^(图|表)\s*[A-Za-z0-9一二三四五六七八九十.．-]+", text) or text.startswith(("(", "（")):
            return text
    for offset in range(1, 4):
        probe = image_line_index - offset
        if probe < 0:
            break
        text = lines[probe].strip()
        if text and not MARKDOWN_IMAGE.search(text):
            if re.search(r"^(图|表)\s*[A-Za-z0-9一二三四五六七八九十.．-]+", text):
                return text
    return candidates[0] if candidates else None


def _nearby_text(lines: list[str], start: int, stop: int, step: int, limit: int) -> list[str]:
    collected: list[str] = []
    index = start
    while index != stop and len(collected) < limit:
        text = lines[index].strip()
        if text and not MARKDOWN_IMAGE.search(text) and not SOURCE_PAGES.search(text):
            collected.append(text)
        index += step
    if step < 0:
        collected.reverse()
    return collected


def _document_hint(
    section_stack: list[str],
    caption: str | None,
    before: list[str],
    after: list[str],
) -> str:
    joined = " ".join(section_stack + ([caption] if caption else []) + before[-3:] + after[:3])
    hints: list[str] = []
    if any(term in joined for term in ["液化石油气", "储罐", "灌瓶", "烃泵", "槽车", "爆炸危险"]):
        hints.append("液化石油气供应工程")
    if "爆炸危险区域" in joined or "1区" in joined or "2区" in joined:
        hints.append("爆炸危险区域等级和范围划分")
    if any(term in joined for term in ["图 A.", "图A.", "附录 A", "附录A"]):
        hints.append("规范附录示意图")
    return "；".join(hints)


# ---------- AI-oriented outputs ----------


def _clean_markdown(markdown: str) -> str:
    markdown = _normalize_html(markdown)
    lines: list[str] = []
    blank = False
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if _is_noise_line(line):
            continue
        if not line:
            if not blank:
                lines.append("")
            blank = True
            continue
        lines.append(line)
        blank = False
    return "\n".join(lines).strip() + "\n"


class _HTMLTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._current_colspan = 1
        self._current_rowspan = 1
        self._column = 0
        self._pending_rowspans: dict[int, tuple[int, str]] = {}

    def handle_starttag(self, tag: str, attrs):
        name = tag.lower()
        if name == "tr":
            self._current_row = []
            self._column = 0
        elif name in {"td", "th"}:
            self._flush_pending_cells()
            self._current_cell = []
            attr_map = {key.lower(): value for key, value in attrs}
            self._current_colspan = _parse_span(attr_map.get("colspan"))
            self._current_rowspan = _parse_span(attr_map.get("rowspan"))
        elif name == "br" and self._current_cell is not None:
            self._current_cell.append(" ")

    def handle_endtag(self, tag: str):
        name = tag.lower()
        if name in {"td", "th"} and self._current_cell is not None:
            cell = _compact_inline_text("".join(self._current_cell))
            if self._current_row is not None:
                for _ in range(self._current_colspan):
                    self._current_row.append(cell)
                    if self._current_rowspan > 1:
                        self._pending_rowspans[self._column] = (self._current_rowspan - 1, cell)
                    self._column += 1
            self._current_cell = None
            self._current_colspan = 1
            self._current_rowspan = 1
        elif name == "tr" and self._current_row is not None:
            self._flush_pending_cells(to_end=True)
            if any(cell for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None

    def handle_data(self, data: str):
        if self._current_cell is not None:
            self._current_cell.append(data)

    def _flush_pending_cells(self, *, to_end: bool = False) -> None:
        if self._current_row is None:
            return
        while self._column in self._pending_rowspans:
            remaining, text = self._pending_rowspans.pop(self._column)
            self._current_row.append(text)
            if remaining > 1:
                self._pending_rowspans[self._column] = (remaining - 1, text)
            self._column += 1
        if to_end:
            for column in sorted(col for col in self._pending_rowspans if col >= self._column):
                while self._column < column:
                    self._column += 1
                if column in self._pending_rowspans:
                    remaining, text = self._pending_rowspans.pop(column)
                    self._current_row.append(text)
                    if remaining > 1:
                        self._pending_rowspans[column] = (remaining - 1, text)
                    self._column += 1


def _normalize_html(markdown: str) -> str:
    table_index = 0

    def replace_table(match: re.Match) -> str:
        nonlocal table_index
        table_index += 1
        return "\n\n" + _html_table_to_ai_text(match.group(0), table_index) + "\n\n"

    text = HTML_TABLE.sub(replace_table, markdown)
    text = HTML_BREAK.sub("\n", text)
    text = HTML_BLOCK.sub("\n", text)
    text = HTML_TAG.sub("", text)
    return unescape(text)


def _html_table_to_ai_text(html: str, table_index: int) -> str:
    parser = _HTMLTableParser()
    parser.feed(html)
    rows = [[cell for cell in row if cell] for row in parser.rows]
    rows = [row for row in rows if row]
    if not rows:
        return f"表格 {table_index}: （空表或无法解析）"

    lines = [f"表格 {table_index}:"]
    header, data_start = _choose_table_header(rows)
    data_rows = rows[data_start:] if header else rows
    width = max([len(header or [])] + [len(row) for row in data_rows])
    if not header:
        header = [f"列{index}" for index in range(1, width + 1)]
    header = _pad_row(header, width)
    lines.append("| " + " | ".join(_escape_markdown_table_cell(cell) for cell in header) + " |")
    lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
    for row in data_rows:
        padded = _pad_row(row, width)
        lines.append("| " + " | ".join(_escape_markdown_table_cell(cell) for cell in padded) + " |")
    return "\n".join(lines)


def _choose_table_header(rows: list[list[str]]) -> tuple[list[str] | None, int]:
    if len(rows) < 2:
        return None, 0
    first = rows[0]
    second = rows[1]
    if len(first) == len(second):
        if len(set(first)) < len(first) or any(upper == lower for upper, lower in zip(first, second)):
            merged = _merge_header_rows(first, second)
            return [_dedupe_header(cell, index) for index, cell in enumerate(merged, start=1)], 2
        return [_dedupe_header(cell, index) for index, cell in enumerate(first, start=1)], 1
    if len(second) > len(first):
        return [_dedupe_header(cell, index) for index, cell in enumerate(second, start=1)], 2
    return [_dedupe_header(cell, index) for index, cell in enumerate(first, start=1)], 1


def _merge_header_rows(first: list[str], second: list[str]) -> list[str]:
    merged: list[str] = []
    for upper, lower in zip(first, second):
        if not upper:
            merged.append(lower)
        elif not lower or upper == lower:
            merged.append(upper)
        else:
            merged.append(f"{upper}/{lower}")
    return merged


def _dedupe_header(value: str, index: int) -> str:
    return value.strip() or f"列{index}"


def _compact_inline_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _parse_span(value: str | None) -> int:
    try:
        parsed = int(value or "1")
    except ValueError:
        return 1
    return max(parsed, 1)


def _pad_row(row: list[str], width: int) -> list[str]:
    return row + [""] * max(width - len(row), 0)


def _escape_markdown_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _is_noise_line(line: str) -> bool:
    text = line.strip()
    if not text:
        return False
    if re.fullmatch(r"[-_=.·\s]{6,}", text):
        return True
    if re.fullmatch(r"\d+\s*/\s*\d+|\d+", text):
        return True
    return bool(re.search(r"\.{5,}\s*\d+\s*$", text))


def _image_results_by_target(image_results: list[dict]) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for result in image_results:
        file = str(result.get("file", "")).strip()
        if file:
            lookup[file] = result
            lookup[Path(file).name] = result
    return lookup


def _insert_image_semantics(markdown: str, image_by_target: dict[str, dict]) -> str:
    output: list[str] = []
    for line in markdown.splitlines():
        output.append(line)
        match = MARKDOWN_IMAGE.search(line)
        if not match:
            continue
        target = match.group("target").strip("<>")
        result = image_by_target.get(target) or image_by_target.get(Path(target).name)
        if not result:
            continue
        if result.get("error"):
            output.append(f"> AI image note: analysis failed for `{result.get('file')}`.")
            continue
        summary = str(result.get("summary", "")).strip()
        contextual = str(result.get("contextual_interpretation", "")).strip()
        findings = [str(item).strip() for item in result.get("key_findings", []) if str(item).strip()]
        if summary:
            output.append(f"> AI image summary: {summary}")
        if contextual and contextual != summary:
            output.append(f"> AI image context: {contextual}")
        for finding in findings:
            output.append(f"> AI image finding: {finding}")
    return "\n".join(output).strip() + "\n"


def _build_chunks(
    markdown: str,
    image_results: list[dict],
    text_result: dict,
    text_coverage: dict,
    source: EnhancementSource,
) -> list[dict]:
    chunks: list[dict] = [{
        "id": "metadata-0000",
        "type": "document_metadata",
        "section_path": [],
        "page_range": None,
        "text": _document_metadata_text(text_result),
        "source_ref": source.markdown_path.name,
        "assets": [],
        "metadata": {
            "source_markdown": str(source.markdown_path),
            "source_manifest": str(source.manifest_path) if source.manifest_path else None,
            "text_analysis": text_result,
            "text_coverage": text_coverage,
            "image_count": len(image_results),
        },
    }]
    section_stack: list[str] = []
    current_lines: list[str] = []
    current_pages: tuple[int | None, int | None] = (None, None)

    def flush() -> None:
        nonlocal current_lines
        text = "\n".join(current_lines).strip()
        if not text:
            current_lines = []
            return
        chunks.append({
            "id": f"text-{len(chunks):04d}",
            "type": "text",
            "section_path": list(section_stack),
            "page_range": list(current_pages) if all(current_pages) else None,
            "text": text,
            "source_ref": str(Path("markdown")),
            "assets": _assets_in_text(text),
        })
        current_lines = []

    for line in markdown.splitlines():
        pages = SOURCE_PAGES.search(line)
        if pages:
            current_pages = (int(pages.group("start")), int(pages.group("end")))
            continue
        heading = HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group("marks"))
            title = heading.group("title").strip()
            section_stack = section_stack[: level - 1] + [title]
        current_lines.append(line)
    flush()

    for image in image_results:
        file = image.get("file")
        context = image.get("context") if isinstance(image.get("context"), dict) else {}
        text_parts = [
            str(context.get("caption") or "").strip(),
            str(image.get("summary") or image.get("error") or "").strip(),
            str(image.get("contextual_interpretation") or "").strip(),
        ]
        chunks.append({
            "id": f"image-{len(chunks):04d}",
            "type": "image",
            "section_path": context.get("section_path") or [],
            "page_range": context.get("page_range"),
            "text": "\n".join(part for part in text_parts if part),
            "source_ref": file,
            "assets": [file] if file else [],
            "metadata": image,
        })
    return chunks


def _document_metadata_text(text_result: dict) -> str:
    parts: list[str] = []
    sections = text_result.get("sections") or []
    if sections:
        parts.append("章节摘要:")
        for item in sections:
            title = str(item.get("title", "")).strip()
            summary = str(item.get("summary", "")).strip()
            if title or summary:
                parts.append(f"- {title}: {summary}".strip())
    entities = text_result.get("entities") or []
    if entities:
        parts.append("实体与术语:")
        for item in entities:
            name = str(item.get("name", "")).strip()
            etype = str(item.get("type", "")).strip()
            desc = str(item.get("description", "")).strip()
            if name:
                parts.append(f"- {name} ({etype}): {desc}".strip())
    tags = [str(tag).strip() for tag in text_result.get("tags") or [] if str(tag).strip()]
    if tags:
        parts.append("标签: " + " ".join(tags))
    references = [str(ref).strip() for ref in text_result.get("cross_references") or [] if str(ref).strip()]
    if references:
        parts.append("跨章节关系:")
        parts.extend(f"- {ref}" for ref in references)
    return "\n".join(parts).strip()


def _assets_in_text(text: str) -> list[str]:
    assets: list[str] = []
    for match in MARKDOWN_IMAGE.finditer(text):
        target = match.group("target").strip("<>")
        if target not in assets:
            assets.append(target)
    return assets


def _write_outputs(
    source: EnhancementSource,
    chunks: list[dict],
    image_results: list[dict],
    text_coverage: dict,
) -> dict:
    base = source.root / source.stem
    ai_jsonl = base.with_suffix(".ai.jsonl")

    ai_jsonl.write_text(
        "".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks),
        encoding="utf-8",
    )
    return {
        "enhanced": True,
        "ai_jsonl": str(ai_jsonl),
        "chunk_count": len(chunks),
        "image_count": len(image_results),
        "text_coverage": text_coverage,
    }


# ---------- assembly ----------

def _assemble(original: str, text_result: dict, image_results: list[dict]) -> str:
    parts: list[str] = [original.rstrip(), "", "---", "", "> ## AI 增强元数据", ">"]

    sections = text_result.get("sections") or []
    if sections:
        parts.append("> ### 章节摘要")
        parts.append(">")
        parts.append("> | 章节 | 摘要 |")
        parts.append("> | ---- | ---- |")
        for item in sections:
            title = _escape_pipe(item.get("title", "").strip())
            summary = _escape_pipe(item.get("summary", "").strip())
            parts.append(f"> | {title} | {summary} |")
        parts.append(">")

    entities = text_result.get("entities") or []
    if entities:
        parts.append("> ### 实体与术语")
        parts.append(">")
        parts.append("> | 实体 | 类型 | 说明 |")
        parts.append("> | ---- | ---- | ---- |")
        for item in entities:
            name = _escape_pipe(item.get("name", "").strip())
            etype = _escape_pipe(item.get("type", "").strip())
            description = _escape_pipe(item.get("description", "").strip())
            parts.append(f"> | {name} | {etype} | {description} |")
        parts.append(">")

    references = text_result.get("cross_references") or []
    if references:
        parts.append("> ### 跨章节关系")
        parts.append(">")
        for line in references:
            text = str(line).strip()
            if text:
                parts.append(f"> - {text}")
        parts.append(">")

    tags = text_result.get("tags") or []
    if tags:
        parts.append("> ### 标签")
        parts.append(">")
        rendered = " ".join(f"`#{str(tag).lstrip('#').strip()}`" for tag in tags if str(tag).strip())
        parts.append(f"> {rendered}")
        parts.append(">")

    if image_results:
        parts.append("> ### 图片语义")
        parts.append(">")
        # Quadruple backticks so the inner ```json is preserved verbatim
        # inside the blockquote.
        parts.append("> ````json")
        json_text = json.dumps(image_results, ensure_ascii=False, indent=2)
        for line in json_text.splitlines():
            parts.append(f"> {line}")
        parts.append("> ````")

    return "\n".join(parts).rstrip() + "\n"


def _escape_pipe(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
