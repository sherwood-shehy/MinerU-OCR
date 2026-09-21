"""Offline publication: immutable assets, collision-free documents, checked references."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote, urlsplit

from .errors import MinerUOCRError
from .provenance import build_manifest, digest_file, manifest_path, read_manifest
from .references import local_resource, references, rewrite_references
from .records import check_work_dir, internal_markdown, records_dir


def _recorded_source(markdown: Path, work_dir: Path | None = None) -> Path:
    if manifest_path(markdown).exists() or (markdown.name == 'full.md' and (markdown.parent / 'manifest.json').exists()):
        return markdown
    internal = internal_markdown(markdown, work_dir)
    if internal.parent.exists() and (not internal.is_file() or not manifest_path(internal).is_file()):
        raise MinerUOCRError('Incomplete internal processing record; recover records or select a separate work directory for reference-only checks')
    return internal if internal.is_file() else markdown


def validate_output(path: str | Path, *, work_dir: Path | None = None) -> dict:
    markdown = source_markdown(path)
    internal = _recorded_source(markdown, work_dir)
    result = _validate_bundle(internal)
    prior = read_manifest(internal, discover=False)
    if internal != markdown:
        if digest_file(markdown) != prior['markdown_sha256']:
            raise MinerUOCRError('Markdown hash mismatch against internal processing record')
        current = build_manifest(markdown, prior)
        if {a['path'] for a in current['assets']} != {a['path'] for a in prior['assets']}:
            raise MinerUOCRError('Resource references differ from internal processing record')
    _validate_generated_anchors(markdown)
    return {**result, 'markdown': str(markdown),
            'validation_scope': 'recorded_hashes' if prior.get('markdown_sha256') else 'references',
            'records': str(internal.parent) if prior else None}


def source_for_processing(path: str | Path, work_dir: Path | None = None) -> Path:
    markdown = source_markdown(path)
    validate_output(markdown, work_dir=work_dir)
    return _recorded_source(markdown, work_dir)


def _stage_publication(source: Path, stage: Path, review_file: Path | None) -> Path:
    from .visuals import apply_image_review
    metadata = build_manifest(source)
    original = source.read_text(encoding='utf-8')
    review = json.loads(Path(review_file).read_text(encoding='utf-8')) if review_file else {}
    if isinstance(review, dict) and (review.get('replacements') or review.get('table_headers')):
        raise MinerUOCRError('publish applies image decisions only; use readable for text and table reviews')
    rendered, decisions = apply_image_review(original, source.parent, metadata, review)
    originals = {local_resource(source.parent, ref.target) for ref in references(original)}
    originals.update(local_resource(source.parent, item['path']) for item in metadata.get('evidence_files', []))
    for file in sorted(f for f in originals if f is not None):
        target = stage / file.relative_to(source.parent)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, target)
    # Keep a retrievable original even when publishing plain Markdown or filtering images.
    if decisions or not any(e.get('role') == 'original_input_bundle' for e in metadata.get('evidence_files', [])):
        snapshot = stage / '.processing-original.zip'
        with zipfile.ZipFile(snapshot, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(source, 'full.md')
            original_manifest = manifest_path(source)
            if not original_manifest.exists() and source.name == 'full.md':
                original_manifest = source.parent / 'manifest.json'
            if original_manifest.is_file():
                archive.write(original_manifest, 'manifest.json')
            else:
                archive.writestr('manifest.json', json.dumps(metadata, ensure_ascii=False, indent=2))
            for file in sorted(f for f in originals if f is not None):
                archive.write(file, file.relative_to(source.parent).as_posix())
        metadata.setdefault('evidence_files', []).append({
            'path': snapshot.name, 'sha256': digest_file(snapshot), 'role': 'original_input_bundle'})
    if decisions:
        metadata['image_review'] = {'input_markdown_sha256': digest_file(source), 'actions': decisions}
    metadata.pop('delivery_documents', None)  # reports are regenerated, never copied into delivery
    staged = stage / 'publication.md'
    staged.write_text(rendered, encoding='utf-8', newline='\n')
    manifest_path(staged).write_text(json.dumps(build_manifest(staged, metadata), ensure_ascii=False, indent=2), encoding='utf-8')
    return staged


def publish_output(path: str | Path, output_dir: str | Path, *, name: str | None = None,
                   work_dir: Path | None = None, review_file: Path | None = None) -> dict:
    source = source_for_processing(path, work_dir)
    output = Path(output_dir).expanduser().resolve()
    root = check_work_dir(output, work_dir)
    metadata = build_manifest(source)
    stem = name or Path(metadata.get('source_name') or source.name).stem
    if name and Path(name).name != name:
        raise MinerUOCRError('Publication name must be a filename stem')
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', stem).strip(' .') or 'document'
    if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', stem):
        stem = '_' + stem
    root.mkdir(parents=True, exist_ok=True)
    # Validate decisions and prepare provenance before creating a public document.
    with tempfile.TemporaryDirectory(prefix='.publish-', dir=root) as temporary:
        staged = _stage_publication(source, Path(temporary), review_file)
        output.mkdir(parents=True, exist_ok=True)
        from .delivery import REPORT_SUFFIXES
        index = 0
        while True:
            candidate = stem + (f' ({index})' if index else '')
            markdown = output / (candidate + '.md')
            record = records_dir(markdown, root)
            lock = output / ('.' + candidate + '.publish.lock')
            if record.exists() or any((output / (candidate + suffix)).exists()
                                     for suffix in ('.md', '.manifest.json', '.ai.jsonl', *REPORT_SUFFIXES)):
                index += 1
                continue
            try:
                with lock.open('x'):
                    pass
                break
            except FileExistsError:
                index += 1
        created_md = False
        try:
            # Seed canonical names from shared delivery assets before generating reports.
            for ref in references(staged.read_text(encoding='utf-8')):
                file = local_resource(staged.parent, ref.target)
                if file is not None:
                    existing = _existing_asset(output / 'images', digest_file(file))
                    if existing:
                        _store_asset(existing, record / 'images')
            result = _publish_bundle(staged, record, name=candidate)
            internal = Path(result['markdown'])
            rendered = internal.read_text(encoding='utf-8')
            for ref in references(rendered):
                file = local_resource(internal.parent, ref.target)
                if file is not None:
                    stored = _store_asset(file, output / 'images')
                    if stored.name != file.name:
                        raise MinerUOCRError('Concurrent resource naming changed; retry publication')
            with markdown.open('x', encoding='utf-8', newline='\n') as handle:
                created_md = True
                handle.write(rendered)
            validate_output(markdown, work_dir=root)
        except Exception:
            if created_md:
                markdown.unlink(missing_ok=True)
            raise
        finally:
            lock.unlink(missing_ok=True)
    reports = result.pop('delivery_documents', [])
    return {**result, 'markdown': str(markdown), 'work_dir': str(record),
            'processing_reports': reports,
            'delivery_documents': [str(markdown)],
            'image_review': read_manifest(internal).get('image_review', {})}


def source_markdown(path: str | Path) -> Path:
    source = Path(path).expanduser().resolve()
    if source.is_dir():
        source = source / 'full.md'
    if not source.is_file() or source.suffix.lower() != '.md':
        raise MinerUOCRError(f'Expected a Markdown file or result directory: {source}')
    return source


def _existing_asset(directory: Path, digest: str) -> Path | None:
    matches = sorted(file for file in directory.glob(digest + '*')
                     if file.name == digest or file.name.startswith(digest + '.'))
    if any(not file.is_file() or digest_file(file) != digest for file in matches):
        raise MinerUOCRError('Existing resource hash mismatch')
    return matches[0] if matches else None


def _store_asset(source: Path, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    digest = digest_file(source)
    existing = _existing_asset(directory, digest)
    if existing:
        return existing
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


def _validate_bundle(path: str | Path) -> dict:
    markdown = source_markdown(path)
    prior = read_manifest(markdown, discover=False)
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


def _publish_bundle(path: str | Path, output_dir: str | Path, *, name: str | None = None,
                    image_dir: str = 'images') -> dict:
    if image_dir not in {'assets', 'images'}:
        raise MinerUOCRError('Resource directory must be assets or images')
    source = source_markdown(path)
    _validate_bundle(source)
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
            _validate_bundle(markdown)
        except Exception:
            for file in reversed(created):
                file.unlink()
            raise
    finally:
        lock.unlink(missing_ok=True)
    return {'published': True, 'markdown': str(markdown), 'manifest': str(sidecar),
            'doc_id': manifest['doc_id'], 'asset_count': len(manifest['assets']),
            'delivery_documents': [str(output / entry['path']) for entry in manifest.get('delivery_documents', [])]}
