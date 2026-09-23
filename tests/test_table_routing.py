"""Real native/raster PDF regressions for pre-extraction table routing."""
from types import SimpleNamespace

import pytest

from mineru_ocr import native, preflight, table_routing, workflow
from mineru_ocr.errors import MinerUOCRError
from mineru_ocr.models import OCROptions
from mineru_ocr.preflight import preflight_pdf

fitz = pytest.importorskip('pymupdf')


def table_pdf(path, *, raster=False, merged=False, borderless=False, empty=False, rotation=0):
    with fitz.open() as doc:
        page = doc.new_page()
        if not borderless:
            for x in (40, 200, 360):
                page.draw_line((x, 130 if merged and x == 200 else 100), (x, 220))
            for y in (100, 130, 160, 190, 220):
                page.draw_line((40, y), (360, y))
        for i, row in enumerate([('Group header' if merged else 'Name', '' if merged else 'Value'),
                                 ('Pressure', '2000'), ('Length', '' if empty else '120'), ('Width', '90')]):
            for j, value in enumerate(row):
                page.insert_text((45 + j * 160, 120 + i * 30), value)
        if raster:
            image = page.get_pixmap(clip=fitz.Rect(35, 95, 365, 225), matrix=fitz.Matrix(2, 2)).tobytes('png')
            doc.delete_page(0)
            page = doc.new_page()
            page.insert_image(fitz.Rect(40, 100, 500, 290), stream=image)
        page.insert_textbox(fitz.Rect(40, 30, 540, 95),
                            'Reliable native text above this table. ' * 5, fontsize=10)
        page.set_rotation(rotation)
        doc.save(path)
    return path


@pytest.mark.parametrize('raster, merged, borderless, reason', [
    (False, True, False, 'complex_table'),
    (True, False, False, 'image_table'),
    (True, False, True, 'suspected_image_table'),
    (False, False, True, 'uncertain_table_structure'),
])
def test_risky_tables_route_before_extraction(tmp_path, monkeypatch, raster, merged, borderless, reason):
    pdf = table_pdf(tmp_path / 'table.pdf', raster=raster, merged=merged, borderless=borderless)
    report = preflight_pdf(pdf)
    assert report['recommended_engine'] == 'cloud'
    assert reason in report['pages'][0]['reasons']
    assert report['pages'][0]['visible_usable_characters'] > 80
    def unexpected(*args, **kwargs):
        pytest.fail('Risky tables must not attempt native extraction')
    monkeypatch.setattr(workflow, 'extract_native', unexpected)
    calls = []
    def cloud(files, *args):
        calls.append(files)
        return [{'state': 'done'}]
    result = workflow.process_documents([str(pdf)], OCROptions(), 1, cloud_process=cloud)[0]
    assert result['engine'] == 'cloud' and calls == [[str(pdf)]]
    with pytest.raises(MinerUOCRError, match='Local-only'):
        workflow.process_documents([str(pdf)], OCROptions(), 1, engine='local', cloud_process=cloud)
    assert len(calls) == 1


def test_one_risky_page_routes_whole_document(tmp_path):
    pdf = table_pdf(tmp_path / 'mixed.pdf', merged=True)
    with fitz.open(pdf) as doc:
        doc.new_page(pno=0).insert_text((40, 60), 'Reliable native introductory text.')
        doc.saveIncr()
    report = preflight_pdf(pdf)
    assert report['recommended_engine'] == 'cloud' and report['cloud_pages'] == [2]


@pytest.mark.parametrize('rotation', [90, 180, 270])
def test_rotated_raster_table_is_screened_in_original_coordinates(tmp_path, rotation):
    pdf = table_pdf(tmp_path / 'rotated.pdf', raster=True, rotation=rotation)
    assert 'image_table' in preflight_pdf(pdf)['pages'][0]['reasons']


def test_simple_table_with_empty_cell_is_native_and_cached(tmp_path, monkeypatch):
    pdf = table_pdf(tmp_path / 'simple.pdf', empty=True)
    report = preflight_pdf(pdf)
    assert report['recommended_engine'] == 'local'
    inspection = report['pages'][0]['tables']
    assert inspection['simple_tables'][0]['cells'][2][1] == ''
    def unexpected(*args, **kwargs):
        pytest.fail('Basic validation must reuse preflight, not rerun detection')
    monkeypatch.setattr(native, 'inspect_page_tables', unexpected)
    rows = inspection['simple_tables'][0]['cells']
    def html(values):
        return '<table>' + ''.join('<tr>' + ''.join('<td>' + c + '</td>' for c in row) + '</tr>' for row in values) + '</table>'
    with fitz.open(pdf) as doc:
        # Duplicated surrounding text deliberately isolates the table placement check.
        page = doc[0]
        assert native.check_page(page, page.get_text() + html(rows), table_inspection=inspection)['table_cells_match']
        rows[1][1], rows[3][1] = rows[3][1], rows[1][1]
        changed = html(rows)
        rows[1][1], rows[3][1] = rows[3][1], rows[1][1]
        assert not native.check_page(page, page.get_text() + changed, table_inspection=inspection)['table_cells_match']


def test_ordinary_illustration_does_not_trigger_cloud(tmp_path):
    with fitz.open() as image:
        page = image.new_page(width=300, height=300)
        page.draw_circle((150, 150), 100, color=(0, .3, .7), fill=(.3, .7, 1))
        png = page.get_pixmap().tobytes('png')
    pdf = tmp_path / 'illustration.pdf'
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 60), 'Engineering illustration in a native text document.')
        page.insert_image(fitz.Rect(40, 100, 500, 560), stream=png)
        doc.save(pdf)
    assert preflight_pdf(pdf)['recommended_engine'] == 'local'


def test_wide_native_grid_still_prefers_local(tmp_path):
    pdf = tmp_path / 'wide.pdf'
    with fitz.open() as doc:
        page = doc.new_page()
        for col in range(13):
            page.draw_line((40 + col * 40, 100), (40 + col * 40, 190))
        for y in (100, 130, 160, 190):
            page.draw_line((40, y), (520, y))
        for row in range(3):
            for col in range(12):
                page.insert_text((42 + col * 40, 120 + row * 30), f'C{col}' if row == 0 else str(row * 12 + col), fontsize=8)
        doc.save(pdf)
    report = preflight_pdf(pdf)
    assert report['recommended_engine'] == 'local'
    assert report['pages'][0]['tables']['simple_tables'][0]['columns'] == 12


def test_diagonal_header_routes_cloud(tmp_path):
    pdf = table_pdf(tmp_path / 'diagonal.pdf')
    with fitz.open(pdf) as doc:
        doc[0].draw_line((40, 100), (200, 130))
        doc.saveIncr()
    assert 'complex_table' in preflight_pdf(pdf)['pages'][0]['reasons']


def test_layout_runtime_failure_never_uploads(tmp_path, monkeypatch):
    pdf = table_pdf(tmp_path / 'table.pdf')
    def broken(*args, **kwargs):
        raise RuntimeError('test model failure')
    monkeypatch.setattr(table_routing, '_image_layout_model', lambda: SimpleNamespace(predict=broken))
    def unexpected(*args):
        pytest.fail('Runtime failure must not upload')
    with pytest.raises(MinerUOCRError, match='no cloud fallback'):
        workflow.process_documents([str(pdf)], OCROptions(), 1, cloud_process=unexpected)


def test_all_basic_pages_checked_before_unnecessary_model_work(tmp_path, monkeypatch):
    pdf = table_pdf(tmp_path / 'scan-end.pdf')
    with fitz.open(pdf) as doc:
        png = doc[0].get_pixmap().tobytes('png')
        page = doc.new_page()
        page.insert_image(page.rect, stream=png)
        doc.saveIncr()
    def unexpected(*args):
        pytest.fail('Known whole-document cloud route needs no table model')
    monkeypatch.setattr(preflight, 'inspect_page_tables', unexpected)
    report = preflight_pdf(pdf)
    assert report['page_count'] == 2 and report['cloud_pages'] == [2]
    assert report['pages'][0]['tables']['status'] == 'skipped_document_cloud'


def test_model_stops_after_first_table_block_but_all_basic_pages_remain(tmp_path, monkeypatch):
    pdf = table_pdf(tmp_path / 'merged-start.pdf', merged=True)
    with fitz.open(pdf) as doc:
        doc.new_page().insert_text((40, 60), 'Native appendix text still inspected.')
        doc.saveIncr()
    original = preflight.inspect_page_tables
    calls = []
    def counted(page, boxes):
        calls.append(page.number)
        return original(page, boxes)
    monkeypatch.setattr(preflight, 'inspect_page_tables', counted)
    report = preflight_pdf(pdf)
    assert calls == [0] and report['cloud_pages'] == [1]
    assert report['pages'][1]['visible_usable_characters'] > 0
    assert report['pages'][1]['tables']['status'] == 'skipped_document_cloud'
