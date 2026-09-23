"""Table risk screening before extraction; no OCR or semantic reconstruction."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from threading import Lock

from .environment import require_local, require_pdf
from .errors import MinerUOCRError

_MODEL_LOCK = Lock()


@lru_cache(maxsize=1)
def _image_layout_model():
    # This narrow adapter is tied to the tested Layout 1.28.2 extra. Its image
    # segmentation head sees raster tables that the selectable-text GNN omits.
    require_local()
    import pymupdf.layout as layout
    from pymupdf.layout.onnx.ImageFeatureExtractorV1 import ImageFeatureExtractorV1
    from pymupdf.layout.onnx.common_util import make_session
    session = make_session(str(Path(layout.__file__).parent / 'resources/onnx/feature_imf1.onnx'))
    return ImageFeatureExtractorV1(session)


def visual_table_regions(page, image_boxes=()) -> list[dict]:
    """Return model table regions in unrotated PDF coordinates, in memory only."""
    try:
        model = _image_layout_model()
        import numpy as np  # already a dependency of the pinned Layout runtime
        from pymupdf.layout.onnx.ImageFeatureExtractorV1 import _CLASS_NAMES
        from pymupdf.layout.common_util import extract_bboxes_from_segmentation_numpy
        fitz = require_pdf()
        scale = min(1, 1200 / max(page.rect.width, page.rect.height))
        bounds = page.rect * page.derotation_matrix
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale).prerotate(-page.rotation), alpha=False)
        with _MODEL_LOCK:
            model.predict(np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n))
            logits = model.get_class_logits()
            height, width = logits.shape[-2:]
            detections = extract_bboxes_from_segmentation_numpy(
                logits, _CLASS_NAMES, target_class=['table', 'text'], min_component_area=10)
        result, text_boxes = [], []
        for item in detections:
            if item['score'] < (.7 if item['class'] == 'table' else .2):
                continue
            x0, y0, x1, y1 = item['bbox']
            box = fitz.Rect(x0 * bounds.width / width, y0 * bounds.height / height,
                            x1 * bounds.width / width, y1 * bounds.height / height)
            if item['class'] == 'table':
                result.append({'bbox': list(box), 'score': round(item['score'], 4)})
            else:
                text_boxes.append(box)
        # Borderless raster tables may be labelled as separate text regions.
        # Repeated aligned columns are a suspicion, not a semantic table claim.
        for image in image_boxes:
            rect = fitz.Rect(image)
            boxes = sorted((b for b in text_boxes if (b & rect).get_area() >= b.get_area() * .8),
                           key=lambda b: (b.y0 + b.y1, b.x0))
            rows = []
            for box in boxes:
                if rows and abs((box.y0 + box.y1) / 2 - rows[-1][0]) <= max(5, box.height / 2):
                    rows[-1][1].append(box.x0)
                else:
                    rows.append(((box.y0 + box.y1) / 2, [box.x0]))
            paired = [sorted(xs) for _, xs in rows if len(xs) >= 2]
            if any(sum(len(other) == len(xs) and all(abs(a - b) <= max(5, rect.width * .05)
                       for a, b in zip(xs, other)) for other in paired) >= 3 for xs in paired):
                result.append({'bbox': list(rect), 'suspected': True,
                               'basis': 'aligned_raster_text_rows'})
        return result
    except MinerUOCRError:
        raise
    except Exception as exc:
        raise MinerUOCRError(f'Table preflight layout runtime failed; no cloud fallback: {exc}') from exc


def _overlap(first, second) -> float:
    fitz = require_pdf()
    a, b = fitz.Rect(first), fitz.Rect(second)
    return (a & b).get_area() / max(1, min(a.get_area(), b.get_area()))


def _image_overlap(table, image) -> float:
    fitz = require_pdf()
    region = fitz.Rect(table)
    return (region & fitz.Rect(image)).get_area() / max(1, region.get_area())


def inspect_page_tables(page, image_boxes=None) -> dict:
    """Accept clear ruled grids; route merged, raster and uncertain tables away.

    Cache simple source cells once for a small post-extraction equality check.
    A model region without a verifiable grid is uncertain, not certified simple.
    """
    if image_boxes is None:
        image_boxes = [i['bbox'] for i in page.get_image_info()]
    drawings = page.get_drawings()
    tables = list(page.find_tables(paths=drawings, use_layout=False).tables)
    regions = visual_table_regions(page, image_boxes)
    findings, simple = [], []
    for table in tables:
        cells = table.extract()
        problems = []
        if table.row_count < 2 or table.col_count < 2:
            problems.append('uncertain_table_structure')
        elif any(cell is None for row in table.rows for cell in row.cells):
            problems.append('complex_table')
        elif any(len(row) != table.col_count for row in cells):
            problems.append('uncertain_table_structure')
        # An external header cannot be certified by the table body alone.
        if table.header.external:
            problems.append('uncertain_table_structure')
        rect = require_pdf().Rect(table.bbox)
        for path in drawings:
            if any(item[0] == 'l' and abs(item[1].x - item[2].x) > 2
                   and abs(item[1].y - item[2].y) > 2
                   and item[1] in rect and item[2] in rect for item in path['items']):
                problems.append('complex_table')  # diagonal / irregular cell borders
                break
        if any(_image_overlap(table.bbox, image) >= .2 for image in image_boxes):
            problems.append('image_table')
        if problems:
            findings.append({'bbox': list(table.bbox), 'reasons': sorted(set(problems))})
        else:
            simple.append({'bbox': list(table.bbox), 'rows': table.row_count, 'columns': table.col_count,
                           'cells': [[''.join((c or '').split()) for c in row] for row in cells]})
    for region in regions:
        if any(_image_overlap(region['bbox'], table.bbox) >= .5 for table in tables):
            continue
        reason = ('suspected_image_table' if region.get('suspected') else
                  'image_table' if any(_image_overlap(region['bbox'], image) >= .2 for image in image_boxes)
                  else 'uncertain_table_structure')
        findings.append({**region, 'reasons': [reason]})
    # Nested/overlapping grids cannot be treated as independent simple tables.
    for i, first in enumerate(tables):
        if any(_overlap(first.bbox, second.bbox) > .2 for second in tables[i + 1:]):
            findings.append({'bbox': list(first.bbox), 'reasons': ['complex_table']})
    return {'status': 'checked', 'simple_tables': simple, 'findings': findings,
            'visual_table_regions': regions,
            'reasons': sorted({reason for item in findings for reason in item['reasons']})}
