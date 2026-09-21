"""Source-reviewed removal of independent image blocks, without semantic enrichment."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .errors import MinerUOCRError
from .provenance import build_manifest, digest_file
from .references import DEFINITION, HTML, INLINE, _reference_uses, _without_code, local_resource, references


def apply_image_review(text: str, directory: Path, metadata: dict, review: dict) -> tuple[str, list[dict]]:
    if not isinstance(review, dict):
        raise MinerUOCRError('Image review must be a JSON object')
    actions = review.get('image_actions', [])
    if not isinstance(actions, list):
        raise MinerUOCRError('image_actions must be a list')
    if not actions:
        return text, []
    if review.get('input_markdown_sha256') != (metadata.get('markdown_sha256') or hashlib.sha256(text.encode('utf-8')).hexdigest()):
        raise MinerUOCRError('Image review input Markdown hash mismatch')
    if metadata.get('source_sha256') and review.get('source_sha256') != metadata['source_sha256']:
        raise MinerUOCRError('Image review source hash mismatch')
    visible = _without_code(text)
    lines = text.splitlines(keepends=True)
    refs = references(text)
    spans = [m.span() for m in re.finditer(r'<table\b.*?</table>', visible, re.I | re.S)]
    candidates = [m for m in INLINE.finditer(visible) if m['image']]
    candidates += [m for m in _reference_uses(visible) if m['image']]
    candidates += [m for m in HTML.finditer(visible) if m['tag'].lower() == 'img']
    standalone = set()
    for match in candidates:
        start, end = match.span()
        line = text.count('\n', 0, start) + 1
        line_start = text.rfind('\n', 0, start) + 1
        line_end = text.find('\n', end)
        line_end = len(text) if line_end < 0 else line_end
        if (not text[line_start:start].strip() and not text[end:line_end].strip()
                and '\n' not in text[start:end]
                and not any(a <= start < b for a, b in spans)):
            standalone.add(line)
    removed, decisions = set(), []
    for action in actions:
        if (not isinstance(action, dict) or action.get('action') != 'drop'
                or action.get('kind') not in {'watermark', 'stamp', 'logo', 'decoration'}
                or action.get('independent') is not True
                or not isinstance(action.get('reason'), str) or not action['reason'].strip()
                or not isinstance(action.get('sha256'), str)
                or not re.fullmatch(r'[0-9a-f]{64}', action['sha256'])):
            raise MinerUOCRError('Image removal needs a hash, invalid-block kind, independent=true and review reason')
        selected = action.get('lines')
        if not isinstance(selected, list) or not selected or any(type(n) is not int or n < 1 for n in selected):
            raise MinerUOCRError('Image removal needs explicit reference lines')
        if len(set(selected)) != len(selected) or removed.intersection(selected):
            raise MinerUOCRError('Duplicate or conflicting image review lines')
        for number in selected:
            matches = [ref for ref in refs if ref.line == number and ref.image]
            if number not in standalone or len(matches) != 1:
                raise MinerUOCRError(f'Only independent image blocks can be removed: line {number}')
            resource = local_resource(directory, matches[0].target)
            if resource is None or digest_file(resource) != action['sha256']:
                raise MinerUOCRError(f'Image review resource hash mismatch: line {number}')
        removed.update(selected)
        decisions.append(dict(action))
    rendered = ''.join(line for number, line in enumerate(lines, 1) if number not in removed)
    # Drop only now-unused image definitions; keep any shared ordinary download link.
    new_visible = _without_code(rendered)
    used = {(m.groupdict().get('key') or m['label']).casefold() for m in _reference_uses(new_visible)}
    original_definitions = {m['key'].casefold(): m for m in DEFINITION.finditer(visible)}
    removed_keys = {(m.groupdict().get('key') or m['label']).casefold()
                    for m in _reference_uses(visible)
                    if m['image'] and text.count('\n', 0, m.start()) + 1 in removed}
    for match in reversed(list(DEFINITION.finditer(new_visible))):
        key = match['key'].casefold()
        if key in removed_keys and key in original_definitions and key not in used:
            end = rendered.find('\n', match.end())
            end = len(rendered) if end < 0 else end + 1
            rendered = rendered[:match.start()] + rendered[end:]
    return rendered, decisions


def inspect_images(path: str | Path, *, work_dir: Path | None = None) -> dict:
    from .publish import _store_asset, source_for_processing, source_markdown
    from .records import check_work_dir, records_dir
    requested = source_markdown(path)
    source = source_for_processing(requested, work_dir)
    root = check_work_dir(requested.parent, work_dir)
    metadata = build_manifest(source)
    text = source.read_text(encoding='utf-8')
    text_hash = digest_file(source)
    directory = root / 'image-reviews' / records_dir(requested, root).name / text_hash
    directory.mkdir(parents=True, exist_ok=True)
    images = [a for a in metadata['assets'] if a['kind'] == 'image']
    inventory, gallery = [], ['# 图片核对清单', '', '重复、尺寸及页边位置仅供核对，不自动判定无效。', '']
    groups = {}
    for asset in images:
        saved = _store_asset(source.parent / asset['path'], directory / 'images')
        record = {**asset, 'preview': saved.relative_to(directory).as_posix()}
        groups.setdefault(asset['sha256'], []).append(asset['path'])
        inventory.append(record)
        gallery += [f"## {asset['path']}", '', f"SHA-256: `{asset['sha256']}`", '',
                    '引用行：' + ', '.join(str(r['line']) for r in asset['references']), '',
                    f"![原图]({record['preview']})", '']
    payload = {'input_markdown': str(requested), 'input_markdown_sha256': text_hash,
               'source_sha256': metadata.get('source_sha256'), 'images': inventory,
               'exact_duplicate_groups': {key: paths for key, paths in groups.items() if len(paths) > 1}}
    inventory_path = directory / 'inventory.json'
    inventory_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    (directory / 'images.md').write_text('\n'.join(gallery), encoding='utf-8')
    template = directory / 'review.json'
    if not template.exists():
        template.write_text(json.dumps({'source_sha256': metadata.get('source_sha256'),
                                       'input_markdown_sha256': text_hash, 'image_actions': []},
                                      ensure_ascii=False, indent=2), encoding='utf-8')
    return {'inventory': str(inventory_path), 'gallery': str(directory / 'images.md'),
            'review_file': str(template), 'image_count': len(images),
            'unique_image_count': len(groups), 'automatic_removals': 0}
