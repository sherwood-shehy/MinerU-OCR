from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote, urlsplit

from .errors import MergeError
from .models import OCRJob, utc_now
from .provenance import build_manifest, digest_file, layout_locations
from .references import local_resource, namespace_reference_labels, references, rewrite_references


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
    replacements = {}
    for reference in references(markdown):
        raw = reference.target
        parsed = urlsplit(raw.strip("<>"))
        source = local_resource(md_path.parent, raw)
        if source is None:
            continue
        relative = source.relative_to(extract_root.resolve())
        destination = part_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        replacement = quote((Path("assets") / f"part-{part_index:04d}" / relative).as_posix(), safe='/')
        if parsed.query:
            replacement += f"?{parsed.query}"
        if parsed.fragment:
            replacement += f"#{parsed.fragment}"
        replacements[raw] = replacement
    return rewrite_references(markdown, replacements)


def _preserve_evidence(part, root: Path, staging: Path) -> tuple[list[dict], dict]:
    files, locations = [], {}
    patterns = ('content_list.json', 'content_list_v2.json', 'middle.json', 'model.json', 'layout.json')
    for source in sorted(root.rglob('*.json')):
        if not any(source.name == name or source.name.endswith('_' + name) for name in patterns):
            continue
        relative = Path('evidence') / f'part-{part.index:04d}' / source.relative_to(root)
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        files.append({'path': relative.as_posix(), 'sha256': digest_file(target), 'part_index': part.index})
        if source.name.endswith('content_list.json'):
            try:
                payload = json.loads(source.read_text(encoding='utf-8'))
            except (ValueError, UnicodeError):
                files[-1]['adapter_status'] = 'unreadable_json'
                continue
            adapted = layout_locations(payload, part, relative.as_posix())
            files[-1]['adapter_status'] = 'adapted' if adapted else 'retained_unmapped'
            for asset, entries in adapted.items():
                file = local_resource(source.parent, asset)
                if file is None:
                    continue
                destination = (Path('assets') / f'part-{part.index:04d}' / file.relative_to(root)).as_posix()
                locations.setdefault(destination, []).extend(entries)
    return files, locations


def merge_job(job: OCRJob) -> Path:
    parts = sorted(job.parts, key=lambda p: (p.page_start or p.index, p.index))
    if any(part.state != "done" or not part.full_md for part in parts):
        raise MergeError("All OCR parts must be downloaded before merging")
    staging = Path(f"{job.output_dir}.tmp-{uuid.uuid4().hex[:8]}")
    staging.mkdir(parents=True)
    assets = staging / "assets"
    sections: list[str] = []
    evidence_files, asset_locations = [], {}
    try:
        for part in parts:
            md_path = Path(part.full_md)
            extract_root = Path(part.extracted_dir or md_path.parent)
            evidence, locations = _preserve_evidence(part, extract_root, staging)
            evidence_files.extend(evidence)
            asset_locations.update(locations)
            content = md_path.read_text(encoding="utf-8").strip()
            content = namespace_reference_labels(content, f'mineru-part-{part.index:04d}-')
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
            'evidence_files': evidence_files, 'asset_locations': asset_locations,
        }
        manifest = build_manifest(staging / 'full.md', manifest)
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        destination = Path(job.output_dir)
        original = destination
        suffix = 1
        while destination.exists():
            destination = original.with_name(f'{original.name} ({suffix})')
            suffix += 1
        staging.rename(destination)
        job.output_dir = str(destination)
        return destination
    except Exception:
        if staging.resolve().parent == Path(job.output_dir).resolve().parent:
            shutil.rmtree(staging, ignore_errors=True)
        raise
