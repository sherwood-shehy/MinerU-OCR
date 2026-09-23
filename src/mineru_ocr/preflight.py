"""Prefer usable native text; separate review hints from pages requiring OCR."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import unicodedata

from .environment import require_pdf
from .errors import MinerUOCRError
from .provenance import digest_file
from .table_routing import inspect_page_tables


def _bad_character(value: str) -> bool:
    return value == '\ufffd' or unicodedata.category(value) in {'Co', 'Cs', 'Cc'}


def _union_area(rectangles: list[tuple]) -> float:
    xs = sorted({x for r in rectangles for x in (r[0], r[2])})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        spans = sorted((r[1], r[3]) for r in rectangles if r[0] < right and r[2] > left)
        length, end = 0.0, float('-inf')
        for y0, y1 in spans:
            length += max(0, y1 - max(y0, end))
            end = max(end, y1)
        area += (right - left) * length
    return area


def preflight_pdf(path: str | Path) -> dict:
    pdf = Path(path).expanduser().resolve()
    if not pdf.is_file() or pdf.suffix.lower() != '.pdf' or pdf.stat().st_size == 0:
        raise MinerUOCRError('Preflight requires a nonempty local PDF file')
    fitz = require_pdf()
    pages = []
    table_candidates = []
    source_hash = digest_file(pdf)
    try:
        with fitz.open(pdf) as doc:
            if doc.needs_pass:
                raise MinerUOCRError('Encrypted PDF requires an unlocked input copy')
            if not len(doc):
                raise MinerUOCRError('PDF contains no pages')
            for page in doc:
                # Text/image coordinates share the unrotated page frame.
                bounds = page.rect * page.derotation_matrix
                text = page.get_text()
                chars = [c for c in text if not c.isspace()]
                bad = sum(_bad_character(c) for c in chars)
                bad_ratio = bad / max(1, len(chars))
                traces = page.get_texttrace()
                visible_chars, hidden = [], 0
                painted = {False: set(), True: set()}
                for trace in traces:
                    invisible = trace.get('type') == 3 or trace.get('opacity', 1) <= .01
                    values = []
                    for codepoint, _, _, bbox in trace['chars']:
                        glyph = (codepoint, tuple(bbox))
                        if glyph in painted[invisible] or (fitz.Rect(bbox) & bounds).is_empty:
                            continue
                        painted[invisible].add(glyph)
                        value = chr(codepoint) if 0 <= codepoint <= 0x10ffff else '\ufffd'
                        if not value.isspace():
                            values.append(value)
                    if invisible:
                        hidden += len(values)
                    else:
                        visible_chars.extend(values)
                visible_usable = sum(c.isalnum() and not _bad_character(c) for c in visible_chars)
                hidden_ratio = hidden / max(1, hidden + len(visible_chars))
                boxes = []
                for image in page.get_image_info():
                    box = fitz.Rect(image['bbox']) & bounds
                    if not box.is_empty:
                        boxes.append(tuple(box))
                coverage = min(1, _union_area(boxes) / max(1, bounds.get_area()))
                drawings = len(page.get_drawings())
                blank = not chars and not boxes and not drawings
                reasons, warnings = [], []
                if not blank:
                    if not chars:
                        reasons.append('no_text_layer')
                    elif not visible_usable:
                        reasons.append('no_usable_visible_text')
                    elif visible_usable < 20:
                        warnings.append('sparse_text')
                    if bad:
                        # Isolated unusual glyphs are a reason to inspect the
                        # native candidate, not to upload before trying it.
                        if bad >= 3 and bad_ratio >= .01:
                            reasons.append('unreliable_character_mapping')
                        else:
                            warnings.append('suspect_character_mapping')
                    if hidden:
                        if not visible_usable or hidden_ratio >= .5:
                            reasons.append('hidden_text_or_old_ocr')
                        else:
                            warnings.append('hidden_text_present')
                    if coverage >= .65:
                        warnings.append('image_dominated_page')
                        # A scan plus a page number/header is not a native-text
                        # page. Use union coverage so tiled scans count too.
                        if visible_usable < 20 or (coverage >= .9 and visible_usable < 80):
                            reasons.append('image_with_sparse_native_text')
                table_inspection = {'status': 'skipped_blank' if blank else 'skipped_blocked'}
                if not blank and not reasons:
                    table_inspection = {'status': 'pending'}
                    table_candidates.append((page.number, boxes))
                pages.append({'page': page.number + 1, 'text_characters': len(chars),
                              'bad_characters': bad, 'hidden_characters': hidden,
                              'visible_characters': len(visible_chars), 'visible_usable_characters': visible_usable,
                              'bad_character_ratio': round(bad_ratio, 6),
                              'hidden_text_ratio': round(hidden_ratio, 6),
                              'image_coverage': round(coverage, 4), 'image_count': len(boxes),
                              'drawing_count': drawings, 'rotation': page.rotation,
                              'classification': 'blank' if blank else 'cloud' if reasons else 'native_candidate',
                              'reasons': reasons, 'warnings': warnings, 'tables': table_inspection})
            # Inspect basic text/image signals on every page first. Once the
            # whole file already needs cloud, further model inference cannot
            # change its route. Report skipped screening instead of guessing.
            blocked = any(p['reasons'] for p in pages)
            for index, boxes in table_candidates:
                record = pages[index]
                if blocked:
                    record['tables'] = {'status': 'skipped_document_cloud'}
                    continue
                record['tables'] = inspect_page_tables(doc[index], boxes)
                record['reasons'].extend(record['tables']['reasons'])
                if record['reasons']:
                    record['classification'] = 'cloud'
                    blocked = True
    except MinerUOCRError:
        raise
    except Exception as exc:
        raise MinerUOCRError(f'Cannot inspect PDF: {exc}') from exc
    if digest_file(pdf) != source_hash:
        raise MinerUOCRError('PDF changed during preflight')
    cloud_pages = [p['page'] for p in pages if p['classification'] == 'cloud']
    native_pages = [p['page'] for p in pages if p['classification'] == 'native_candidate']
    return {'schema_version': '1.2', 'policy': 'native_simple_tables_first',
            'source_name': pdf.name, 'source_sha256': source_hash,
            'page_count': len(pages), 'recommended_engine': 'local' if native_pages and not cloud_pages else 'cloud',
            'classification_counts': dict(Counter(p['classification'] for p in pages)),
            'cloud_pages': cloud_pages, 'warning_pages': [p['page'] for p in pages if p['warnings']], 'pages': pages,
            'limitations': ['Heuristic eligibility, not an OCR accuracy or completeness score.',
                            'Warnings permit a local attempt; a blocking page still routes the whole PDF to cloud.',
                            'Textless illustrated pages still need OCR/review; pages are never silently omitted.',
                            'Table screening is heuristic; undetected tables and semantic header ambiguity still require spot review.',
                            'Every page receives basic inspection; model screening stops once the whole document requires cloud.',
                            'Image-table screening uses the pinned local layout model without OCR or saved screenshots.',
                            'Local extraction still checks page coverage, text, numbers and cached simple table cells.']}
