from __future__ import annotations

import json
import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .errors import MergeError
from .models import OCRJob, utc_now


MARKDOWN_LINK = re.compile(r"(?P<prefix>!?\[[^\]]*\]\()(?P<target>[^)\s]+)(?P<suffix>(?:\s+[^)]*)?\))")
HTML_LINK = re.compile(r"(?P<prefix>\b(?:src|href)\s*=\s*['\"])(?P<target>[^'\"]+)(?P<suffix>['\"])", re.I)


def safe_extract(zip_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            member = Path(info.filename.replace("\\", "/"))
            if member.is_absolute() or ".." in member.parts:
                raise MergeError(f"Unsafe path in MinerU ZIP: {info.filename}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise MergeError(f"Symlink rejected in MinerU ZIP: {info.filename}")
            target = (destination / member).resolve()
            if target != root and root not in target.parents:
                raise MergeError(f"ZIP member escapes extraction directory: {info.filename}")
        archive.extractall(destination)


def find_full_md(root: Path) -> Path:
    matches = list(root.rglob("full.md"))
    if len(matches) != 1:
        raise MergeError(f"Expected exactly one full.md in {root}, found {len(matches)}")
    return matches[0]


def _rewrite_assets(markdown: str, md_path: Path, extract_root: Path, assets_root: Path, part_index: int) -> str:
    part_root = assets_root / f"part-{part_index:04d}"

    def rewrite(match: re.Match) -> str:
        raw = match.group("target")
        parsed = urlsplit(raw.strip("<>"))
        if parsed.scheme or parsed.netloc or parsed.path.startswith("/") or raw.startswith(("#", "data:")):
            return match.group(0)
        source = (md_path.parent / unquote(parsed.path)).resolve()
        root = extract_root.resolve()
        if not source.is_file() or (source != root and root not in source.parents):
            return match.group(0)
        relative = source.relative_to(root)
        destination = part_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        replacement = (Path("assets") / f"part-{part_index:04d}" / relative).as_posix()
        if parsed.query:
            replacement += f"?{parsed.query}"
        if parsed.fragment:
            replacement += f"#{parsed.fragment}"
        return f"{match.group('prefix')}{replacement}{match.group('suffix')}"

    markdown = MARKDOWN_LINK.sub(rewrite, markdown)
    return HTML_LINK.sub(rewrite, markdown)


def merge_job(job: OCRJob) -> Path:
    parts = sorted(job.parts, key=lambda p: (p.page_start or p.index, p.index))
    if any(part.state != "done" or not part.full_md for part in parts):
        raise MergeError("All OCR parts must be downloaded before merging")
    staging = Path(f"{job.output_dir}.tmp-{uuid.uuid4().hex[:8]}")
    staging.mkdir(parents=True)
    assets = staging / "assets"
    sections: list[str] = []
    try:
        for part in parts:
            md_path = Path(part.full_md)
            extract_root = Path(part.extracted_dir or md_path.parent)
            content = md_path.read_text(encoding="utf-8").strip()
            content = _rewrite_assets(content, md_path, extract_root, assets, part.index)
            if part.page_start and part.page_end:
                sections.append(f"<!-- MinerU source pages {part.page_start}-{part.page_end} -->\n\n{content}")
            else:
                sections.append(f"<!-- MinerU source part {part.index} -->\n\n{content}")
        (staging / "full.md").write_text("\n\n".join(sections).rstrip() + "\n", encoding="utf-8")
        manifest = {
            "job_id": job.job_id, "source_name": job.source_name, "source_size": job.source_size,
            "source_sha256": job.source_sha256, "page_count": job.page_count,
            "created_at": job.created_at, "completed_at": utc_now(), "options": job.options.model_dump(),
            "parts": [{
                "index": p.index, "data_id": p.data_id, "batch_id": p.batch_id,
                "page_start": p.page_start, "page_end": p.page_end,
                "page_ranges": p.page_ranges, "physical": p.physical, "trace_id": p.trace_id,
            } for p in parts],
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        destination = Path(job.output_dir)
        backup = destination.with_name(f"{destination.name}.bak-{uuid.uuid4().hex[:8]}")
        if destination.exists():
            destination.replace(backup)
        try:
            staging.replace(destination)
        except Exception:
            if backup.exists() and not destination.exists():
                backup.replace(destination)
            raise
        shutil.rmtree(backup, ignore_errors=True)
        return destination
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

