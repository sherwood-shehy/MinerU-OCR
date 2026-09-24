"""Native PDF geometry disambiguates a model's contents/table proposals."""
import pytest

from mineru_ocr import table_routing
from mineru_ocr.preflight import preflight_pdf

fitz = pytest.importorskip('pymupdf')


def contents_page(doc, *, heading='Contents', continued=False, leaders=True,
                  values=None, hidden=False):
    page = doc.new_page()
    if heading:
        page.insert_text((210, 65), heading, fontname='china-s' if heading == '目  次' else 'helv')
    labels = (['6.1 Selection', '6.2 Performance', '6.3 Structure', '6.4 Arrangement']
              if continued else ['Foreword', '1 Scope', '2 References', '3 Terms'])
    values = values or (['3', '3', '4', '4'] if continued else ['III', '1', '1', '2'])
    for i, (label, value) in enumerate(zip(labels, values)):
        y = 110 + i * 25
        # Deliberately emit the page number before the leader, like the real PDF.
        page.insert_text((60, y), label, render_mode=3 if hidden else 0)
        page.insert_text((500 - fitz.get_text_length(value, fontsize=11), y), value)
        if leaders:
            page.insert_text((210, y - 1.5), '.' * 85, fontsize=11)
    return page


CONTENTS_BOX = [55, 95, 505, 190]


@pytest.mark.parametrize('heading,continued,rotation', [
    ('Contents', False, 0), ('目  次', False, 0), ('', True, 0),
    ('Contents', False, 90), ('Contents', False, 180), ('Contents', False, 270),
])
def test_contents_candidate_is_not_a_table(tmp_path, monkeypatch, heading, continued, rotation):
    pdf = tmp_path / 'contents.pdf'
    with fitz.open() as doc:
        contents_page(doc, heading=heading, continued=continued).set_rotation(rotation)
        doc.save(pdf)
    monkeypatch.setattr(table_routing, 'visual_table_regions',
                        lambda *args: [{'bbox': CONTENTS_BOX, 'score': .98}])
    result = preflight_pdf(pdf)
    assert result['recommended_engine'] == 'local'
    inspection = result['pages'][0]['tables']
    assert inspection['findings'] == [] and inspection['simple_tables'] == []
    assert inspection['non_table_regions'][0]['kind'] == 'table_of_contents'
    assert inspection['non_table_regions'][0]['entry_count'] == 4
    assert inspection['visual_table_regions']  # Keep the original model evidence.


@pytest.mark.parametrize('options', [
    {'leaders': False},  # Title and numeric column alone do not prove contents.
    {'values': ['12', '3', '25', '4']},  # Numeric data, not ordered page references.
    {'heading': ''},  # Unnumbered rows without a contents heading remain ambiguous.
    {'hidden': True},  # Invisible labels must not exempt a visible data region.
])
def test_ambiguous_native_rows_remain_cloud(tmp_path, monkeypatch, options):
    pdf = tmp_path / 'ambiguous.pdf'
    with fitz.open() as doc:
        contents_page(doc, **options)
        doc.save(pdf)
    monkeypatch.setattr(table_routing, 'visual_table_regions',
                        lambda *args: [{'bbox': CONTENTS_BOX, 'score': .98}])
    result = preflight_pdf(pdf)
    assert result['recommended_engine'] == 'cloud'
    assert 'uncertain_table_structure' in result['pages'][0]['reasons']


@pytest.mark.parametrize('raster', [False, True])
def test_contents_does_not_exempt_another_table_on_same_page(tmp_path, monkeypatch, raster):
    pdf = tmp_path / 'mixed.pdf'
    with fitz.open() as doc:
        page = contents_page(doc)
        if raster:
            with fitz.open() as image:
                p = image.new_page(width=400, height=150)
                p.insert_text((20, 50), 'Name    Limit    Class')
                png = p.get_pixmap().tobytes('png')
            page.insert_image(fitz.Rect(60, 300, 500, 430), stream=png)
        else:
            for x in (60, 280, 500):
                page.draw_line((x, 330 if x == 280 else 300), (x, 420))
            for y in (300, 330, 360, 390, 420):
                page.draw_line((60, y), (500, y))
            page.insert_text((70, 320), 'Merged limits header')
            for i in range(3):
                page.insert_text((70, 350 + 30 * i), f'Parameter {i}')
                page.insert_text((290, 350 + 30 * i), str(100 + i))
        doc.save(pdf)
    monkeypatch.setattr(table_routing, 'visual_table_regions', lambda *args: [
        {'bbox': CONTENTS_BOX, 'score': .98}, {'bbox': [60, 300, 500, 430], 'score': .98}])
    result = preflight_pdf(pdf)
    assert result['recommended_engine'] == 'cloud'
    assert ('image_table' if raster else 'complex_table') in result['pages'][0]['reasons']
    assert result['pages'][0]['tables']['non_table_regions'][0]['kind'] == 'table_of_contents'


def test_contents_like_rows_with_table_ruling_are_not_exempt(tmp_path, monkeypatch):
    pdf = tmp_path / 'ruled.pdf'
    with fitz.open() as doc:
        page = contents_page(doc)
        # An incomplete ruling need not be recognized as a native grid.
        page.draw_line((55, 125), (505, 125))
        doc.save(pdf)
    monkeypatch.setattr(table_routing, 'visual_table_regions',
                        lambda *args: [{'bbox': CONTENTS_BOX, 'score': .98}])
    result = preflight_pdf(pdf)
    assert result['recommended_engine'] == 'cloud'


def test_contents_region_with_extra_data_rows_remains_uncertain(tmp_path, monkeypatch):
    pdf = tmp_path / 'combined-proposal.pdf'
    with fitz.open() as doc:
        page = contents_page(doc)
        page.insert_text((60, 225), 'Operating limit')
        page.insert_text((400, 225), '500 Pa')
        doc.save(pdf)
    monkeypatch.setattr(table_routing, 'visual_table_regions',
                        lambda *args: [{'bbox': [55, 95, 505, 235], 'score': .98}])
    assert preflight_pdf(pdf)['recommended_engine'] == 'cloud'


def test_native_contents_cannot_exempt_a_small_embedded_image(tmp_path, monkeypatch):
    pdf = tmp_path / 'image-in-proposal.pdf'
    with fitz.open() as doc:
        page = contents_page(doc)
        with fitz.open() as image:
            p = image.new_page(width=80, height=30)
            p.insert_text((2, 15), 'a | b | c', fontsize=8)
            png = p.get_pixmap().tobytes('png')
        # Less than the normal 20% raster-table threshold, within the same proposal.
        page.insert_image(fitz.Rect(300, 125, 380, 155), stream=png)
        doc.save(pdf)
    monkeypatch.setattr(table_routing, 'visual_table_regions',
                        lambda *args: [{'bbox': CONTENTS_BOX, 'score': .98}])
    result = preflight_pdf(pdf)
    assert result['recommended_engine'] == 'cloud'
    assert 'uncertain_table_structure' in result['pages'][0]['reasons']


def test_contents_title_below_data_does_not_exempt_it(tmp_path, monkeypatch):
    pdf = tmp_path / 'late-title.pdf'
    with fitz.open() as doc:
        page = contents_page(doc, heading='')
        page.insert_text((210, 220), 'Contents')
        doc.save(pdf)
    monkeypatch.setattr(table_routing, 'visual_table_regions',
                        lambda *args: [{'bbox': [55, 95, 505, 230], 'score': .98}])
    assert preflight_pdf(pdf)['recommended_engine'] == 'cloud'


def test_off_page_contents_title_does_not_exempt_rows(tmp_path, monkeypatch):
    pdf = tmp_path / 'off-page-title.pdf'
    with fitz.open() as doc:
        page = contents_page(doc, heading='')
        page.insert_text((-200, 65), 'Contents')
        doc.save(pdf)
    monkeypatch.setattr(table_routing, 'visual_table_regions',
                        lambda *args: [{'bbox': CONTENTS_BOX, 'score': .98}])
    assert preflight_pdf(pdf)['recommended_engine'] == 'cloud'


@pytest.mark.parametrize('heading,continued', [('Contents', False), ('', True)])
def test_real_model_fragmented_contents_proposals_stay_local(tmp_path, heading, continued):
    pdf = tmp_path / 'model-contents.pdf'
    with fitz.open() as doc:
        contents_page(doc, heading=heading, continued=continued)
        doc.save(pdf)
    # The pinned model can split leaders, titles and page numbers into separate
    # table proposals. Verify the actual model, not only an ideal full TOC box.
    report = preflight_pdf(pdf)
    inspection = report['pages'][0]['tables']
    assert inspection['visual_table_regions']
    assert report['recommended_engine'] == 'local'
    assert len(inspection['non_table_regions']) == len(inspection['visual_table_regions'])
