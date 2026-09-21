"""Explicit auto/local/cloud routing and one shared publication pipeline."""
from __future__ import annotations

from pathlib import Path
import uuid

from .errors import MinerUOCRError
from .native import NativeQualityError, extract_native
from .preflight import preflight_pdf
from .provenance import read_manifest
from .publish import publish_output, source_markdown
from .readable import _layout, prepare_readable
from .records import check_work_dir, default_work_dir
from .service import process_files


def process_documents(files: list[str], options, timeout: int, *, engine: str = 'auto',
                      output_dir: Path | None = None, work_dir: Path | None = None,
                      review_file: Path | None = None, name: str | None = None,
                      title: str | None = None, table_format: str = 'auto', edition: str = 'source',
                      cloud_process=None) -> list[dict]:
    if engine not in {'auto', 'local', 'cloud'}:
        raise MinerUOCRError('Unknown extraction engine')
    if len(files) != 1 and any((review_file, name, title)):
        raise MinerUOCRError('Review, title and name options require exactly one input')
    if not output_dir and any((review_file, name, title)):
        raise MinerUOCRError('Review, title and name options require --output-dir')
    root = check_work_dir(output_dir, work_dir) if output_dir else Path(work_dir or default_work_dir()).resolve()
    cloud_process = cloud_process or process_files
    plans = []
    for file in files:
        pdf = Path(file).expanduser().resolve()
        inspection = preflight_pdf(pdf) if engine != 'cloud' and pdf.suffix.lower() == '.pdf' else None
        selected = engine if engine != 'auto' else inspection['recommended_engine'] if inspection else 'cloud'
        if selected == 'local' and (inspection is None or inspection['recommended_engine'] != 'local'):
            raise MinerUOCRError('Local-only mode requires every nonblank PDF page to pass preflight; no upload was made')
        plans.append((pdf, selected, inspection))
    # Missing local dependencies are an environment problem, never a reason to upload silently.
    if any(selected == 'local' for _, selected, _ in plans):
        from .environment import require_local
        require_local()
    results = []
    for pdf, selected, inspection in plans:
        fallback = None
        if selected == 'local':
            directory = root / 'native' / uuid.uuid4().hex
            try:
                result = extract_native(pdf, directory, preflight=inspection)
            except NativeQualityError as exc:
                if engine == 'local':
                    raise
                fallback = {'reason': 'native_quality_failed', 'result_dir': str(exc.directory), 'quality': exc.report}
                selected = 'cloud'
        if selected == 'cloud':
            result = cloud_process([str(pdf)], options, timeout)[0]
            result.update({'engine': 'cloud', 'preflight': inspection})
            if fallback:
                result['local_attempt'] = fallback
        if result.get('state') == 'done' and result.get('result_dir') and output_dir:
            markdown = source_markdown(result['result_dir'])
            metadata = read_manifest(markdown)
            if pdf.suffix.lower() == '.pdf' and _layout(markdown, metadata):
                result.update(prepare_readable(markdown, pdf, output_dir, work_dir=root,
                                               review_file=review_file, name=name, title=title,
                                               table_format=table_format, edition=edition))
                result['postprocessing'] = 'source_pages_and_review'
            else:
                result.update(publish_output(markdown, output_dir, name=name, work_dir=root, review_file=review_file))
                result['postprocessing'] = 'portable_publication'
                result['limitations'] = ['Adapted page evidence unavailable; source-page postprocessing was not performed.']
        results.append(result)
    return results
