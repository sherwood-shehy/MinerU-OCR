"""AI enhancement layer on top of MinerU output.

The original MinerU Markdown remains the evidence layer. This module writes a
single AI-oriented JSONL file beside it for retrieval and knowledge-base use.
"""

from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlsplit

from . import __version__
from .doubao_client import DoubaoClient, VISUAL_PROMPT_VERSION
from .errors import MinerUOCRError
from .provenance import build_manifest, stable_id
from .publish import validate_output
from .references import expand_image_references, references


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\((?P<target>[^)\s]+)(?:\s+[^)]*)?\)")
HEADING = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$")
SOURCE_PAGES = re.compile(r"<!--\s*MinerU source pages (?P<start>\d+)-(?P<end>\d+)\s*-->")
TEXT_ANALYSIS_CHARS = 40_000
HTML_TABLE = re.compile(r"<table\b.*?</table>", re.I | re.S)
HTML_BREAK = re.compile(r"<br\s*/?>", re.I)
HTML_BLOCK = re.compile(r"</?(?:p|div|section|article|header|footer|li|ul|ol|tbody|thead|tfoot)\b[^>]*>", re.I)


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
    validate_output(source.markdown_path)
    manifest = build_manifest(source.markdown_path)
    markdown = source.markdown_path.read_text(encoding="utf-8")
    images = [source.root / asset['path'] for asset in manifest['assets'] if asset['kind'] == 'image']

    owns_client = client is None
    if owns_client:
        client = DoubaoClient()

    clean_markdown = _clean_markdown(markdown)
    image_contexts = _extract_image_contexts(clean_markdown)
    try:
        image_results = _analyze_images(client, source, images, image_contexts, manifest)
        text_result, text_coverage = _analyze_text(client, clean_markdown, original_chars=len(markdown))
    finally:
        if owns_client and isinstance(client, DoubaoClient):
            client.close()

    chunks = _build_chunks(clean_markdown, image_results, text_result, text_coverage, source, manifest)
    generation = {'model': getattr(client, 'model', None), 'provider': type(client).__name__,
                  'prompt_version': VISUAL_PROMPT_VERSION, 'pipeline_version': __version__,
                  'generated_at': datetime.now(timezone.utc).isoformat()}
    for chunk in chunks:
        chunk['generation'] = generation
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


def _analyze_images(
    client: EnhancementClient,
    source: EnhancementSource,
    images: list[Path],
    image_contexts: dict[str, dict],
    manifest: dict,
) -> list[dict]:
    results: list[dict] = []
    assets = {asset['path']: asset for asset in manifest['assets']}
    analyzed: dict[str, dict] = {}
    for image in images:
        relative = image.relative_to(source.root).as_posix()
        context = image_contexts.get(relative) or {}
        asset = assets[relative]
        if asset['asset_id'] in analyzed:
            prior = analyzed[asset['asset_id']]
            prior['asset_paths'].append(relative)
            prior['source_references'].extend(asset['references'])
            for location in asset['locations']:
                if location not in prior['source_locations']:
                    prior['source_locations'].append(location)
            continue
        trusted = {'file': relative, 'context': context, 'asset_id': asset['asset_id'],
                   'asset_paths': [relative],
                   'source_locations': list(asset['locations']), 'source_references': list(asset['references'])}
        if image.suffix.lower() not in IMAGE_EXTENSIONS:
            results.append({**trusted, 'analysis_status': 'unsupported', 'review_status': 'needs_review',
                            'error': 'Native asset retained; this vision transport does not support its format'})
            analyzed[asset['asset_id']] = results[-1]
            continue
        try:
            semantics = _validate_visual(client.analyze_image(image, context=context))
        except Exception as exc:  # tolerate single-image failures
            results.append({
                **trusted, 'analysis_status': 'failed', 'review_status': 'needs_review',
                "error": str(exc),
            })
            analyzed[asset['asset_id']] = results[-1]
            continue
        review = 'needs_review' if semantics.get('uncertainty') or semantics.get('context_consistency') == 'low' else 'unreviewed'
        results.append({**semantics, **trusted, 'analysis_status': 'ok', 'review_status': review})
        analyzed[asset['asset_id']] = results[-1]
    return results


def _validate_visual(value: object) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get('summary'), str):
        raise EnhancementError('Visual result must be an object with a string summary')
    cleaned = {}
    for field in ['type', 'summary', 'visual_description', 'contextual_interpretation', 'context_consistency', 'uncertainty']:
        item = value.get(field, '')
        if not isinstance(item, str):
            raise EnhancementError(f'Invalid visual field: {field}')
        cleaned[field] = item
    for field in ['elements', 'key_findings', 'keywords', 'visible_text']:
        item = value.get(field, [])
        if not isinstance(item, list) or not all(isinstance(entry, str) for entry in item):
            raise EnhancementError(f'Invalid visual field: {field}')
        cleaned[field] = item
    for field, required in [('dimensions', ['label', 'value_text', 'unit_text', 'basis']),
                            ('relationships', ['from', 'to', 'relation', 'basis'])]:
        item = value.get(field, [])
        if not isinstance(item, list) or not all(isinstance(entry, dict) and all(isinstance(entry.get(key), str) for key in required) for entry in item):
            raise EnhancementError(f'Invalid visual field: {field}')
        if any(entry['basis'] not in ({'visual'} if field == 'dimensions' else {'visual', 'context'}) for entry in item):
            raise EnhancementError(f'Invalid evidence basis: {field}')
        cleaned[field] = [{key: entry[key] for key in required} for entry in item]
    return cleaned


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
    if limit < 1:
        raise ValueError("Segment limit must be positive")
    segments: list[str] = []
    current = ""
    for line in markdown.splitlines(keepends=True):
        if current and len(current) + len(line) > limit:
            segments.append(current)
            current = ""
        while len(line) > limit:
            segments.append(line[:limit])
            line = line[limit:]
        current += line
    if current:
        segments.append(current)
    return [segment for segment in segments if segment.strip()]


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
    by_line: dict[int, list] = {}
    for ref in references(markdown):
        if ref.image:
            by_line.setdefault(ref.line - 1, []).append(ref)

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

        for ref in by_line.get(index, []):
            image_index += 1
            target = Path(unquote(urlsplit(ref.target).path)).as_posix()
            caption = _find_caption(lines, index)
            before = _nearby_text(lines, index - 1, -1, -1, window)
            after = _nearby_text(lines, index + 1, len(lines), 1, window)
            context = {
                "image_index": image_index, "image_ref": target,
                "section_path": list(section_stack),
                "page_range": list(current_pages) if all(current_pages) else None,
                "caption": caption, "nearby_text_before": before, "nearby_text_after": after,
                "document_hint": _document_hint(section_stack, caption, before, after),
            }
            contexts.setdefault(target, context)
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
        self.header_rows: list[bool] = []
        self.first_row_header_depth = 0
        self._has_th = False
        self._has_td = False
        self._rowspan = 1
        self._has_colspan = False

    def handle_starttag(self, tag: str, attrs):
        name = tag.lower()
        if name == "tr":
            self._current_row = []
            self._column = 0
            self._has_th = self._has_td = self._has_colspan = False
            self._rowspan = 1
        elif name in {"td", "th"}:
            self._flush_pending_cells()
            self._current_cell = []
            attr_map = {key.lower(): value for key, value in attrs}
            self._current_colspan = _parse_span(attr_map.get("colspan"))
            self._current_rowspan = _parse_span(attr_map.get("rowspan"))
            self._has_th |= name == "th"
            self._has_td |= name == "td"
            self._has_colspan |= self._current_colspan > 1
            self._rowspan = max(self._rowspan, self._current_rowspan)
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
                if not self.rows and self._has_colspan and self._rowspan > 1:
                    self.first_row_header_depth = self._rowspan
                self.rows.append(self._current_row)
                self.header_rows.append(self._has_th and not self._has_td)
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
                    self._current_row.append("")
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

    def replace_image(match: re.Match) -> str:
        class ImageParser(HTMLParser):
            target = ""
            alt = ""
            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                self.target = values.get("src") or ""
                self.alt = values.get("alt") or ""
        parser = ImageParser()
        parser.feed(match.group(0))
        target = parser.target.replace(" ", "%20").replace("(", "%28").replace(")", "%29")
        return f"![{parser.alt.replace(']', '')}]({target})" if target else match.group(0)

    text = re.sub(r"<img\b[^>]*>", replace_image, expand_image_references(markdown), flags=re.I)
    text = HTML_TABLE.sub(replace_table, text)
    text = HTML_BREAK.sub("\n", text)
    text = HTML_BLOCK.sub("\n", text)
    return unescape(text)


def _html_table_to_ai_text(html: str, table_index: int) -> str:
    parser = _HTMLTableParser()
    parser.feed(html)
    rows = parser.rows
    rows = [row for row in rows if row]
    if not rows:
        return f"表格 {table_index}: （空表或无法解析）"

    lines = [f"表格 {table_index}:"]
    depth = 0
    for is_header in parser.header_rows:
        if not is_header:
            break
        depth += 1
    depth = depth or parser.first_row_header_depth
    depth = min(depth, len(rows))
    header = rows[0] if depth else None
    for row in rows[1:depth]:
        width = max(len(header), len(row))
        header = _merge_header_rows(_pad_row(header, width), _pad_row(row, width))
    data_start = depth
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


def _build_chunks(
    markdown: str,
    image_results: list[dict],
    text_result: dict,
    text_coverage: dict,
    source: EnhancementSource,
    manifest: dict,
) -> list[dict]:
    doc_id = manifest['doc_id']
    assets_by_path = {asset['path']: asset for asset in manifest['assets']}
    chunks: list[dict] = [{
        "id": stable_id('metadata', doc_id),
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
            'document_manifest': manifest,
        },
        'provenance_kind': 'ai_generated', 'review_status': 'unreviewed',
    }]
    section_stack: list[str] = []
    current_lines: list[str] = []
    current_pages: tuple[int | None, int | None] = (None, None)
    duplicate_counts: Counter = Counter()

    def flush() -> None:
        nonlocal current_lines
        text = "\n".join(current_lines).strip()
        if not text:
            current_lines = []
            return
        for segment in _segment_text(text, limit=8000):
            paths = _assets_in_text(segment)
            asset_ids = [assets_by_path[path]['asset_id'] for path in paths if path in assets_by_path]
            canonical = segment
            for path in sorted(assets_by_path, key=len, reverse=True):
                canonical = canonical.replace(path, assets_by_path[path]['asset_id'])
            basis = json.dumps([section_stack, current_pages, canonical], ensure_ascii=False)
            occurrence = duplicate_counts[basis]
            duplicate_counts[basis] += 1
            pages = list(current_pages) if all(current_pages) else None
            chunks.append({
                "id": stable_id('text', doc_id, basis, str(occurrence)),
                "type": "text", "section_path": list(section_stack), "page_range": pages,
                "text": segment,
                "source_ref": source.markdown_path.name,
                "assets": paths, 'asset_ids': asset_ids,
                'source_locations': [{'precision': 'page_range' if pages else 'unknown', 'page_range': pages}],
                'provenance_kind': 'source_normalized', 'review_status': 'not_applicable',
            })
        current_lines = []

    for line in markdown.splitlines():
        pages = SOURCE_PAGES.search(line)
        if pages:
            flush()
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
            str(image.get('visual_description') or ''),
            '\n'.join(image.get('visible_text') or []),
            '\n'.join(image.get('key_findings') or []),
        ]
        for field in ['dimensions', 'relationships']:
            if image.get(field):
                text_parts.append(json.dumps({field: image[field]}, ensure_ascii=False))
        locations = image['source_locations']
        pages = [location['page'] for location in locations if location.get('page')]
        chunks.append({
            "id": stable_id('visual', image['asset_id']),
            'asset_id': image['asset_id'], 'asset_ids': [image['asset_id']],
            "type": "image",
            "section_path": context.get("section_path") or [],
            "page_range": [min(pages), max(pages)] if pages and len(pages) == len(locations) else context.get("page_range"),
            'source_locations': locations,
            "text": "\n".join(part for part in text_parts if part),
            "source_ref": file,
            "assets": image['asset_paths'],
            "metadata": image,
            'analysis_status': image['analysis_status'], 'review_status': image['review_status'],
            'provenance_kind': 'ai_generated',
        })
    for chunk in chunks:
        chunk['doc_id'] = doc_id
        chunk['source_version'] = manifest['source_version']
        chunk['schema_version'] = '1.0'
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
    for ref in references(text):
        if urlsplit(ref.target).scheme or urlsplit(ref.target).netloc:
            continue
        target = Path(unquote(urlsplit(ref.target).path)).as_posix()
        if ref.image and target not in assets:
            assets.append(target)
    return assets


def _write_outputs(
    source: EnhancementSource,
    chunks: list[dict],
    image_results: list[dict],
    text_coverage: dict,
) -> dict:
    base = source.root / source.stem
    ai_jsonl = base.with_name(base.name + ".ai.jsonl")

    coverage = dict(Counter(image['analysis_status'] for image in image_results))
    coverage = {key: coverage.get(key, 0) for key in ['ok', 'failed', 'unsupported']}
    chunks[0]['metadata']['image_coverage'] = coverage
    temporary = ai_jsonl.with_name('.' + ai_jsonl.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks), encoding="utf-8")
        temporary.replace(ai_jsonl)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "enhanced": True,
        "ai_jsonl": str(ai_jsonl),
        "chunk_count": len(chunks),
        "image_count": len(image_results),
        'image_coverage': coverage,
        "text_coverage": text_coverage,
    }
