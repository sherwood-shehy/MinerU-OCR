"""Offline publication: immutable assets, collision-free documents, checked references."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
from pathlib import Path
from urllib.parse import quote, urlsplit

from .errors import MinerUOCRError
from .provenance import build_manifest, digest_file, manifest_path, read_manifest
from .references import local_resource, references, rewrite_references


def source_markdown(path: str | Path) -> Path:
    source = Path(path).expanduser().resolve()
    if source.is_dir():
        source = source / 'full.md'
    if not source.is_file() or source.suffix.lower() != '.md':
        raise MinerUOCRError(f'Expected a Markdown file or result directory: {source}')
    return source


def _store_asset(source: Path, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    digest = digest_file(source)
    destination = directory / (digest + source.suffix.lower())
    created = False
    try:
        with destination.open('xb') as output:
            created = True
            with source.open('rb') as input_file:
                shutil.copyfileobj(input_file, output)
    except FileExistsError:
        if not destination.is_file() or digest_file(destination) != digest:
            raise MinerUOCRError(f'Existing resource hash mismatch: {destination.name}')
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return destination


def validate_output(path: str | Path) -> dict:
    markdown = source_markdown(path)
    prior = read_manifest(markdown)
    if prior.get('markdown_sha256') and prior['markdown_sha256'] != digest_file(markdown):
        raise MinerUOCRError('Markdown hash mismatch; regenerate the manifest after intentional edits')
    current = build_manifest(markdown, prior)
    if prior.get('schema_version') and {a['path'] for a in prior.get('assets', [])} != {a['path'] for a in current['assets']}:
        raise MinerUOCRError('Manifest resource references do not match Markdown')
    for item in prior.get('evidence_files', []):
        file = local_resource(markdown.parent, item['path'])
        if file is None or digest_file(file) != item['sha256']:
            raise MinerUOCRError('Evidence file hash mismatch')
    for item in prior.get('delivery_documents', []):
        file = local_resource(markdown.parent, item['path'])
        if file is None or digest_file(file) != item['sha256']:
            raise MinerUOCRError('Delivery document hash mismatch')
        for ref in references(file.read_text(encoding='utf-8')):
            local_resource(file.parent, ref.target)
    if prior.get('postprocess'):
        for file in [markdown, *[markdown.parent / item['path'] for item in prior.get('delivery_documents', [])]]:
            _validate_generated_anchors(file)
    return {'valid': True, 'markdown': str(markdown), 'asset_count': len(current['assets']),
            'doc_id': current['doc_id'], 'external_images': current['external_images']}


def _validate_generated_anchors(markdown: Path) -> None:
    from urllib.parse import unquote
    from .references import _without_code
    text = _without_code(markdown.read_text(encoding='utf-8'))
    ids = re.findall(r'<a\s+id=["\x27]([^"\x27]+)', text)
    if len(ids) != len(set(ids)):
        raise MinerUOCRError('Duplicate explicit anchors in delivery')
    cache = {markdown: set(ids)}
    for ref in references(text):
        parsed = urlsplit(ref.target)
        if parsed.scheme or not parsed.fragment.startswith(('body-', 'commentary', 'appendix-', 'heading-', 'source-page', 'supplement-')):
            continue
        target = local_resource(markdown.parent, ref.target) if parsed.path else markdown
        if target and target.suffix.lower() == '.md':
            if target not in cache:
                cache[target] = set(re.findall(r'<a\s+id=["\x27]([^"\x27]+)',
                                              _without_code(target.read_text(encoding='utf-8'))))
            if unquote(parsed.fragment) not in cache[target]:
                raise MinerUOCRError('Broken generated source anchor')


def publish_output(path: str | Path, output_dir: str | Path, *, name: str | None = None,
                   image_dir: str = 'assets') -> dict:
    if image_dir not in {'assets', 'images'}:
        raise MinerUOCRError('Resource directory must be assets or images')
    source = source_markdown(path)
    validate_output(source)
    manifest = build_manifest(source)
    manifest.pop('delivery_documents', None)  # regenerated for the destination publication
    report_suffixes = ()
    if manifest.get('postprocess'):
        from .delivery import REPORT_SUFFIXES
        report_suffixes = REPORT_SUFFIXES
    text = source.read_text(encoding='utf-8')
    resources = {ref.target: local_resource(source.parent, ref.target) for ref in references(text)}
    evidence = [(entry, local_resource(source.parent, entry['path'])) for entry in manifest.get('evidence_files', [])]
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    stem = name or Path(manifest.get('source_name') or source.name).stem
    if name and Path(name).name != name:
        raise MinerUOCRError('Publication name must be a filename stem')
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', stem).strip(' .') or 'document'
    if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', stem):
        stem = '_' + stem
    replacements, paths = {}, {}
    for target, file in resources.items():
        if file is None:
            continue
        stored = _store_asset(file, output / image_dir)
        relative = stored.relative_to(output).as_posix()
        paths[file.relative_to(source.parent).as_posix()] = relative
        parsed = urlsplit(target)
        replacements[target] = quote(relative, safe='/') + (('?' + parsed.query) if parsed.query else '') + (('#' + parsed.fragment) if parsed.fragment else '')
    evidence_paths = {}
    for entry, file in evidence:
        if file is None:
            raise MinerUOCRError('Evidence must be a local file')
        stored = _store_asset(file, output / 'evidence')
        evidence_paths[entry['path']] = stored.relative_to(output).as_posix()
    manifest = copy.deepcopy(manifest)
    for item in manifest.get('evidence_files', []):
        item['path'] = evidence_paths[item['path']]
    for asset in manifest['assets']:
        asset['path'] = paths[asset['path']]
        for location in asset['locations']:
            ref = location.get('evidence_ref')
            if ref:
                base, separator, pointer = ref.partition('#')
                if base in evidence_paths:
                    location['evidence_ref'] = evidence_paths[base] + separator + pointer
    unique_assets = {}
    for asset in manifest['assets']:
        if asset['path'] in unique_assets:
            prior = unique_assets[asset['path']]
            for location in asset['locations']:
                if location not in prior['locations']:
                    prior['locations'].append(location)
        else:
            unique_assets[asset['path']] = asset
    manifest['assets'] = list(unique_assets.values())
    rendered = rewrite_references(text, replacements)
    # Reserve a family of names. The lock serializes concurrent publishers of this stem.
    index = 0
    while True:
        candidate = stem + (f' ({index})' if index else '')
        markdown = output / (candidate + '.md')
        sidecar = manifest_path(markdown)
        lock = output / ('.' + candidate + '.publish.lock')
        if any(file.exists() for file in [markdown, sidecar, output / (candidate + '.ai.jsonl'),
                                         *[output / (candidate + suffix) for suffix in report_suffixes]]):
            index += 1
            continue
        try:
            handle = lock.open('x', encoding='utf-8')
            handle.close()
            break
        except FileExistsError:
            index += 1
    try:
        manifest['markdown'] = markdown.name
        manifest['markdown_sha256'] = hashlib.sha256(rendered.encode('utf-8')).hexdigest()
        for asset in manifest['assets']:
            asset['references'] = []
        by_path = {a['path']: a for a in manifest['assets']}
        for ref in references(rendered):
            file = local_resource(output, ref.target)
            if file:
                by_path[file.relative_to(output).as_posix()]['references'].append({'markdown': markdown.name, 'line': ref.line})
        # Only newly-created files are removed if this transaction fails.
        created = []
        try:
            reports = {}
            if report_suffixes:
                from .delivery import report_documents
                audit_entry = next(e for e in manifest['evidence_files'] if e.get('role') == 'readability_audit')
                audit = json.loads((output / audit_entry['path']).read_text(encoding='utf-8'))
                reports = report_documents(manifest, audit)
                manifest['delivery_documents'] = []
                for suffix, content in reports.items():
                    report = output / (candidate + suffix)
                    with report.open('x', encoding='utf-8', newline='\n') as handle:
                        created.append(report)
                        handle.write(content)
                    manifest['delivery_documents'].append({'path': report.name, 'sha256': digest_file(report)})
            with sidecar.open('x', encoding='utf-8', newline='\n') as handle:
                created.append(sidecar)
                json.dump(manifest, handle, ensure_ascii=False, indent=2)
            with markdown.open('x', encoding='utf-8', newline='\n') as handle:
                created.append(markdown)
                handle.write(rendered)
            validate_output(markdown)
        except Exception:
            for file in reversed(created):
                file.unlink()
            raise
    finally:
        lock.unlink(missing_ok=True)
    return {'published': True, 'markdown': str(markdown), 'manifest': str(sidecar),
            'doc_id': manifest['doc_id'], 'asset_count': len(manifest['assets']),
            'delivery_documents': [str(output / entry['path']) for entry in manifest.get('delivery_documents', [])]}
