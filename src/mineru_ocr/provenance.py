"""Versioned document/asset identities and conservative source locators."""
from __future__ import annotations

import hashlib
import json
import mimetypes
from pathlib import Path

from .errors import MinerUOCRError
from .references import local_resource, range_at, references

SCHEMA_VERSION = '1.0'


def digest_file(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def stable_id(kind: str, *values: str) -> str:
    return kind + '-' + hashlib.sha256('\0'.join(values).encode('utf-8')).hexdigest()


def manifest_path(markdown: Path) -> Path:
    return markdown.with_name(markdown.stem + '.manifest.json')


def read_manifest(markdown: Path, work_dir: Path | None = None, *, discover: bool = True) -> dict:
    path = manifest_path(markdown)
    if not path.exists() and markdown.name == 'full.md':
        path = markdown.parent / 'manifest.json'
    if not path.exists() and discover:
        from .records import internal_markdown
        path = manifest_path(internal_markdown(markdown, work_dir))
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError) as exc:
        raise MinerUOCRError(f'Cannot read source manifest: {path.name}') from exc
    if not isinstance(value, dict):
        raise MinerUOCRError('Source manifest must be an object')
    return value


def build_manifest(markdown: Path, metadata: dict | None = None) -> dict:
    metadata = dict(read_manifest(markdown) if metadata is None else metadata)
    text = markdown.read_text(encoding='utf-8')
    md_hash = digest_file(markdown)
    version = metadata.get('source_version') or metadata.get('source_sha256') or md_hash
    identity_basis = metadata.get('identity_basis') or ('source_sha256' if metadata.get('source_sha256') else 'markdown_sha256')
    doc_id = metadata.get('doc_id') or stable_id('doc', str(version))
    prior = {a['path']: a for a in metadata.get('assets', [])}
    assets: dict[str, dict] = {}
    positioned: set[str] = set()
    external: list[str] = []
    for ref in references(text):
        file = local_resource(markdown.parent, ref.target)
        if file is None:
            if ref.image and ref.target not in external:
                external.append(ref.target)
            continue
        relative = file.relative_to(markdown.parent).as_posix()
        if relative not in assets:
            content_hash = digest_file(file)
            old = prior.get(relative, {})
            if old.get('sha256') and old['sha256'] != content_hash:
                raise MinerUOCRError(f'Asset hash mismatch: {relative}')
            media_type = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
            locations = old.get('locations') or metadata.get('asset_locations', {}).get(relative) or []
            if locations:
                positioned.add(relative)
            assets[relative] = {
                'asset_id': stable_id('asset', doc_id, content_hash), 'path': relative,
                'sha256': content_hash, 'media_type': media_type,
                'kind': 'image' if ref.image or media_type.startswith('image/') else 'attachment',
                'locations': list(locations), 'references': [],
            }
        asset = assets[relative]
        if ref.image:
            asset['kind'] = 'image'
        asset['references'].append({'markdown': markdown.name, 'line': ref.line})
        if relative not in positioned:
            pages = range_at(text, ref.line)
            location = {'precision': 'page_range' if pages else 'unknown',
                        'page': None, 'page_range': pages, 'bbox': None,
                        'coordinate_system': None, 'evidence_ref': None}
            if location not in asset['locations']:
                asset['locations'].append(location)
    metadata.pop('asset_locations', None)
    return {**metadata, 'schema_version': SCHEMA_VERSION, 'doc_id': doc_id,
            'identity_basis': identity_basis, 'source_version': version,
            'markdown': markdown.name, 'markdown_sha256': md_hash,
            'assets': list(assets.values()), 'external_images': external}


def _page_number(index: object, part) -> int | None:
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        return None
    start, end = part.page_start, part.page_end
    if not start or not end:
        return index + 1 if not part.page_ranges else None
    candidates = set()
    if index < end - start + 1:
        candidates.add(start + index)
    if not part.physical and start <= index + 1 <= end:
        candidates.add(index + 1)
    return next(iter(candidates)) if len(candidates) == 1 else None


def layout_locations(payload: object, part, evidence_ref: str) -> dict[str, list[dict]]:
    """Adapt legacy Content List V1. Unknown schemas are retained as raw evidence."""
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        return {}
    result: dict[str, list[dict]] = {}
    for index, block in enumerate(payload):
        image = block.get('img_path')
        if not isinstance(image, str) or not image:
            continue
        page = _page_number(block.get('page_idx'), part)
        bbox = block.get('bbox')
        valid_bbox = (isinstance(bbox, list) and len(bbox) == 4
                      and all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in bbox)
                      and 0 <= bbox[0] <= bbox[2] <= 1000 and 0 <= bbox[1] <= bbox[3] <= 1000)
        location = {
            'precision': 'page_bbox' if page and valid_bbox else 'page' if page else 'page_range' if part.page_start else 'unknown',
            'page': page, 'page_range': [page, page] if page else [part.page_start, part.page_end] if part.page_start else None,
            'bbox': bbox if page and valid_bbox else None,
            'coordinate_system': 'mineru_content_list_normalized_0_1000' if page and valid_bbox else None,
            'raw_page_idx': block.get('page_idx'), 'raw_bbox': bbox,
            'evidence_ref': f'{evidence_ref}#/{index}', 'adapter': 'mineru_content_list_v1',
        }
        result.setdefault(image.replace('\\', '/'), []).append(location)
    return result
