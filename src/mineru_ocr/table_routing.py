"""Table risk screening before extraction; no OCR or semantic reconstruction."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from threading import Lock
import unicodedata

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


def _visible_text_rows(page) -> list[list[tuple]]:
    """Reassemble visible glyphs by baseline, not PDF stream/fragment order."""
    fitz = require_pdf()
    bounds = page.rect * page.derotation_matrix
    glyphs = set()
    for span in page.get_texttrace():
        if span.get('type') == 3 or span.get('opacity', 1) <= .01 or span['dir'][0] < .99:
            continue
        for codepoint, _, origin, bbox in span['chars']:
            if (0 <= codepoint <= 0x10ffff and not chr(codepoint).isspace()
                    and not (fitz.Rect(bbox) & bounds).is_empty):
                glyphs.add((origin[0], origin[1], chr(codepoint), tuple(bbox)))
    rows = []
    for glyph in sorted(glyphs, key=lambda g: (g[1], g[0])):
        # Dots and page numbers can have a slightly different font baseline.
        if not rows or glyph[1] - rows[-1][0][1] > 2.5:
            rows.append([])
        rows[-1].append(glyph)
    return [sorted(row) for row in rows]


def _contents_regions(rows, drawings, image_boxes) -> list[dict]:
    """Find native dotted contents blocks independently of model fragments.

    Require aligned, ordered page references on every row. Without a heading,
    continuation pages additionally need predominantly subsection identifiers.
    Only proposals contained in a verified block may later be exempted.
    """
    fitz = require_pdf()
    titles = {'目次', '目录', '目錄', 'contents', 'tableofcontents'}
    title_baselines, runs, run = [], [], []
    for row in rows:
        value = unicodedata.normalize('NFKC', ''.join(g[2] for g in row))
        if value.lower() in titles:
            title_baselines.append(row[0][1])
        match = re.fullmatch(r'(.+?)[.·⋯]{3,}([0-9]{1,4}|[IVXLCDMivxlcdm]+)', value)
        entry = None
        if (match and sum(c.isalpha() for c in match[1]) >= 2
                and not re.search(r'[.·⋯]{3,}', match[1])):
            label, number = match.groups()
            if number.isdigit():
                ordinal = (1, int(number))
            else:
                number = number.upper()
                if re.fullmatch(r'M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})', number):
                    values = [dict(I=1, V=5, X=10, L=50, C=100, D=500, M=1000)[c] for c in number]
                    ordinal = (0, sum(-n if i + 1 < len(values) and n < values[i + 1] else n
                                      for i, n in enumerate(values)))
                else:
                    ordinal = None
            if ordinal is not None:
                entry = (row, label, ordinal)
        if run and (entry is None or row[0][1] - run[-1][0][0][1] > 40):
            runs.append(run)
            run = []
        if entry:
            run.append(entry)
    if run:
        runs.append(run)
    result = []
    for run in runs:
        if len(run) < 3:
            continue
        glyphs = [g for row, _, _ in run for g in row]
        box = fitz.Rect(min(g[3][0] for g in glyphs), min(g[3][1] for g in glyphs),
                        max(g[3][2] for g in glyphs), max(g[3][3] for g in glyphs))
        entries = [ordinal for _, _, ordinal in run]
        right_edges = [row[-1][3][2] for row, _, _ in run]
        titled = any(box.y0 - 120 <= y < run[0][0][0][1] for y in title_baselines)
        subsections = sum(bool(re.match(r'^\d+(?:\.\d+)+[^\d.]', label)) for _, label, _ in run)
        if (entries != sorted(entries) or (not titled and subsections < len(run) * .8)
                or min(right_edges) < box.x0 + box.width * .75
                or max(right_edges) - min(right_edges) > max(6, box.width * .02)):
            continue
        # Modest model-edge tolerance cannot include images or table ruling.
        box += (-8, -8, 8, 8)
        if any((box & fitz.Rect(image)).get_area() > 0 for image in image_boxes):
            continue
        if any('s' in path['type'] and box.intersects(path['rect'] + (-1, -1, 1, 1))
               and max(path['rect'].width, path['rect'].height) > 10 for path in drawings):
            continue
        result.append({'kind': 'table_of_contents', 'basis': 'native_leaders_and_ordered_page_references',
                       'entry_count': len(run), 'heading_present': titled, 'contents_bbox': list(box)})
    return result


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
    findings, simple, non_tables = [], [], []
    contents_regions = None
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
        if reason == 'uncertain_table_structure':
            if contents_regions is None:
                contents_regions = _contents_regions(_visible_text_rows(page), drawings, image_boxes)
            contents = next((c for c in contents_regions
                             if require_pdf().Rect(c['contents_bbox']).contains(region['bbox'])), None)
            if contents:
                non_tables.append({**region, **contents})
                continue
        findings.append({**region, 'reasons': [reason]})
    # Nested/overlapping grids cannot be treated as independent simple tables.
    for i, first in enumerate(tables):
        if any(_overlap(first.bbox, second.bbox) > .2 for second in tables[i + 1:]):
            findings.append({'bbox': list(first.bbox), 'reasons': ['complex_table']})
    return {'status': 'checked', 'simple_tables': simple, 'findings': findings,
            'visual_table_regions': regions, 'non_table_regions': non_tables,
            'reasons': sorted({reason for item in findings for reason in item['reasons']})}
