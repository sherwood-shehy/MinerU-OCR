"""Conservative, page-by-page native PDF eligibility checks without OCR."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import unicodedata

from .environment import require_pdf
from .errors import MinerUOCRError
from .provenance import digest_file


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
    source_hash = digest_file(pdf)
    try:
        with fitz.open(pdf) as doc:
            if doc.needs_pass:
                raise MinerUOCRError('Encrypted PDF requires an unlocked input copy')
            if not len(doc):
                raise MinerUOCRError('PDF contains no pages')
            for page in doc:
                text = page.get_text()
                chars = [c for c in text if not c.isspace()]
                bad = sum(c == '\ufffd' or unicodedata.category(c) in {'Co', 'Cs', 'Cc'} for c in chars)
                traces = page.get_texttrace()
                hidden = sum(len(t['chars']) for t in traces if t.get('type') == 3 or t.get('opacity', 1) <= .01)
                boxes = []
                # Image/text coordinates are unrotated; compare in that same frame.
                bounds = page.rect * page.derotation_matrix
                for image in page.get_image_info():
                    box = fitz.Rect(image['bbox']) & bounds
                    if not box.is_empty:
                        boxes.append(tuple(box))
                coverage = min(1, _union_area(boxes) / max(1, bounds.get_area()))
                drawings = len(page.get_drawings())
                blank = not chars and not boxes and not drawings
                reasons = []
                if not blank:
                    if not chars:
                        reasons.append('no_text_layer')
                    elif len(chars) < 20:
                        reasons.append('sparse_text_needs_review')
                    if bad:
                        reasons.append('unreliable_character_mapping')
                    if hidden:
                        reasons.append('hidden_text_or_old_ocr')
                    if coverage >= .65:
                        reasons.append('image_dominated_page')
                pages.append({'page': page.number + 1, 'text_characters': len(chars),
                              'bad_characters': bad, 'hidden_characters': hidden,
                              'image_coverage': round(coverage, 4), 'image_count': len(boxes),
                              'drawing_count': drawings, 'rotation': page.rotation,
                              'classification': 'blank' if blank else 'cloud' if reasons else 'native_candidate',
                              'reasons': reasons})
    except MinerUOCRError:
        raise
    except Exception as exc:
        raise MinerUOCRError(f'Cannot inspect PDF: {exc}') from exc
    if digest_file(pdf) != source_hash:
        raise MinerUOCRError('PDF changed during preflight')
    cloud_pages = [p['page'] for p in pages if p['classification'] == 'cloud']
    native_pages = [p['page'] for p in pages if p['classification'] == 'native_candidate']
    return {'schema_version': '1.0', 'source_name': pdf.name, 'source_sha256': source_hash,
            'page_count': len(pages), 'recommended_engine': 'local' if native_pages and not cloud_pages else 'cloud',
            'classification_counts': dict(Counter(p['classification'] for p in pages)),
            'cloud_pages': cloud_pages, 'pages': pages,
            'limitations': ['Heuristic eligibility, not an OCR accuracy or completeness score.',
                            'Any uncertain page routes the whole PDF to cloud; pages are not silently omitted.',
                            'Local extraction must also pass per-page text, numeric-token and table checks.']}
