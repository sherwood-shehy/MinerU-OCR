"""AI enhancement layer on top of MinerU output.

After ``mineru-ocr process`` finishes, this module optionally enriches the
merged result directory with a sibling ``full.enhanced.md`` that contains the
original Markdown plus an AI metadata block (section summaries, entities,
cross references, tags, and per-image semantics) produced by Doubao.
"""

from __future__ import annotations

import json
from pathlib import Path

from .doubao_client import DoubaoClient
from .errors import MinerUOCRError


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


class EnhancementError(MinerUOCRError):
    """Raised when the enhancement layer cannot produce a usable output."""


def enhance_output(result_dir: str | Path, *, client: DoubaoClient | None = None) -> Path:
    """Enhance a MinerU result directory and write ``full.enhanced.md``.

    Parameters
    ----------
    result_dir : path
        A directory produced by ``mineru-ocr process`` containing ``full.md``
        (and optionally ``assets/``).
    client : DoubaoClient, optional
        Pre-configured client; one will be constructed from environment
        variables when omitted.

    Returns
    -------
    Path
        The absolute path of the written ``full.enhanced.md``.
    """
    directory = Path(result_dir).resolve()
    full_md = directory / "full.md"
    if not full_md.is_file():
        raise EnhancementError(f"full.md not found in {directory}")

    markdown = full_md.read_text(encoding="utf-8")
    images = _collect_images(directory)

    owns_client = client is None
    if owns_client:
        client = DoubaoClient()

    try:
        image_results = _analyze_images(client, directory, images)
        text_result = client.analyze_text(markdown)
    finally:
        if owns_client:
            client.close()

    enhanced = _assemble(markdown, text_result, image_results)
    destination = directory / "full.enhanced.md"
    destination.write_text(enhanced, encoding="utf-8")
    return destination


# ---------- collection ----------

def _collect_images(directory: Path) -> list[Path]:
    assets = directory / "assets"
    if not assets.is_dir():
        return []
    return sorted(
        path for path in assets.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def _analyze_images(client: DoubaoClient, root: Path, images: list[Path]) -> list[dict]:
    results: list[dict] = []
    for image in images:
        relative = image.relative_to(root).as_posix()
        try:
            semantics = client.analyze_image(image)
        except Exception as exc:  # tolerate single-image failures
            results.append({
                "file": relative,
                "error": str(exc),
            })
            continue
        results.append({"file": relative, **semantics})
    return results


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
