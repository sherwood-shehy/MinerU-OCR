"""Routing regressions using actual PDF text, images and font mappings."""
from pathlib import Path

import pytest

from mineru_ocr.models import OCROptions
from mineru_ocr.preflight import preflight_pdf
from mineru_ocr import native, workflow
from mineru_ocr.publish import validate_output

fitz = pytest.importorskip('pymupdf')


def mapped_text_pdf(path, text, mapping):
    """A real ToUnicode mapping reproduces bad glyphs without mocking the inspector."""
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(30, 30, 550, 780), text, fontsize=11)
        font = page.get_fonts()[0][0]
        cmap = doc.get_new_xref()
        doc.update_object(cmap, '<<>>')
        pairs = '\n'.join(f'<{n:02X}> <{mapping.get(chr(n), n):04X}>' for n in range(32, 127))
        doc.update_stream(cmap, ('/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n'
            '/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n'
            '/CMapName /Test def\n/CMapType 2 def\n1 begincodespacerange\n<00> <FF>\n'
            'endcodespacerange\n95 beginbfchar\n' + pairs + '\nendbfchar\nendcmap\n'
            'CMapName currentdict /CMap defineresource pop\nend\nend').encode())
        doc.xref_set_key(font, 'ToUnicode', f'{cmap} 0 R')
        doc.save(path)
    return path


def illustrated_pdf(path, caption, *, full_page=False, hidden=False):
    with fitz.open() as image_doc:
        page = image_doc.new_page(width=500, height=700)
        page.insert_text((30, 60), 'Raster content requiring OCR', fontsize=14)
        raster = page.get_pixmap().tobytes('png')
    with fitz.open() as doc:
        page = doc.new_page(width=500, height=700)
        rect = page.rect if full_page else fitz.Rect(0, 120, 500, 700)
        page.insert_image(rect, stream=raster, keep_proportion=False)
        page.insert_textbox(fitz.Rect(25, 20, 475, 115), caption, fontsize=11,
                            render_mode=3 if hidden else 0)
        doc.save(path)
    return path


def test_short_cover_and_large_illustration_do_not_veto_text_document(tmp_path):
    pdf = illustrated_pdf(tmp_path / 'illustrated.pdf', 'Figure 1: the original engineering drawing')
    with fitz.open(pdf) as doc:
        doc.new_page(pno=0).insert_text((40, 60), 'Cover')
        doc.new_page().insert_text((40, 60), 'A normal text page with enough content for local extraction.')
        doc.saveIncr()
    result = preflight_pdf(pdf)
    assert result['recommended_engine'] == 'local'
    assert result['cloud_pages'] == []
    assert result['warning_pages'] == [1, 2]
    assert result['pages'][0]['warnings'] == ['sparse_text']
    assert 'image_dominated_page' in result['pages'][1]['warnings']
    assert not result['pages'][1]['reasons']


@pytest.mark.parametrize('count, expected', [(1, 'local'), (2, 'local'), (3, 'cloud')])
def test_mapping_defects_use_count_and_ratio(tmp_path, count, expected):
    pdf = mapped_text_pdf(tmp_path / 'mapping.pdf', 'A' * count + ' reliable text ' * 5, {'A': 0xE000})
    result = preflight_pdf(pdf)
    page = result['pages'][0]
    assert page['bad_characters'] == count
    assert result['recommended_engine'] == expected
    if expected == 'local':
        assert 'suspect_character_mapping' in page['warnings']
    else:
        assert 'unreliable_character_mapping' in page['reasons']


def test_low_mapping_error_ratio_allows_local_attempt(tmp_path):
    pdf = mapped_text_pdf(tmp_path / 'mapping.pdf', 'AAA ' + 'Reliable native content. ' * 20, {'A': 0xE000})
    result = preflight_pdf(pdf)
    assert result['pages'][0]['bad_characters'] == 3
    assert result['pages'][0]['bad_character_ratio'] < .01
    assert result['recommended_engine'] == 'local'


def test_allowed_mapping_warning_cannot_hide_a_dropped_unknown_glyph(tmp_path):
    pdf = mapped_text_pdf(tmp_path / 'mapping.pdf', 'A reliable native pressure value 2000 Pa.', {'A': 0xE000})
    assert preflight_pdf(pdf)['recommended_engine'] == 'local'
    with fitz.open(pdf) as doc:
        assert '\ue000' in doc[0].get_text()
        missing = doc[0].get_text().replace('\ue000', '')
        result = native.check_page(doc[0], missing)
    assert not result['passed']
    assert 'unresolved_source_characters' in result['issues']


@pytest.mark.parametrize('character', ['\ufffd', '\x7f'])
def test_native_quality_rejects_bad_characters_in_output(character):
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 60), 'Pressure 2000 Pa.')
        result = native.check_page(page, 'Pressure 2000 Pa.' + character)
    assert not result['passed']
    assert 'unreliable_extracted_characters' in result['issues']


@pytest.mark.parametrize('hidden_text, expected', [('Invisible note', 'local'), ('Invisible text ' * 15, 'cloud')])
def test_hidden_text_is_evaluated_against_visible_text(tmp_path, hidden_text, expected):
    pdf = tmp_path / 'hidden.pdf'
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 60), 'Visible native text remains the primary content of this page.')
        page.insert_textbox(fitz.Rect(40, 90, 500, 500), hidden_text, render_mode=3)
        doc.save(pdf)
    result = preflight_pdf(pdf)
    assert result['recommended_engine'] == expected
    page = result['pages'][0]
    if expected == 'local':
        assert 'hidden_text_present' in page['warnings'] and not page['reasons']
    else:
        assert 'hidden_text_or_old_ocr' in page['reasons']


def test_full_page_image_with_only_header_still_needs_ocr(tmp_path):
    pdf = illustrated_pdf(tmp_path / 'scan-header.pdf', 'Downloaded standard - page 1', full_page=True)
    result = preflight_pdf(pdf)
    assert result['recommended_engine'] == 'cloud'
    assert 'image_with_sparse_native_text' in result['pages'][0]['reasons']


def test_off_page_text_cannot_turn_a_scan_into_native_text(tmp_path):
    pdf = illustrated_pdf(tmp_path / 'outside.pdf', 'Downloaded standard - page 1', full_page=True)
    with fitz.open(pdf) as doc:
        doc[0].insert_text((-2000, -100), 'Text outside the visible page. ' * 6)
        doc.saveIncr()
    result = preflight_pdf(pdf)
    assert result['recommended_engine'] == 'cloud'
    assert result['pages'][0]['visible_usable_characters'] < 80


def test_repeated_painting_of_one_header_does_not_count_as_body_text(tmp_path):
    caption = 'Downloaded standard header with a reference number 1234'
    pdf = illustrated_pdf(tmp_path / 'overpaint.pdf', '', full_page=True)
    with fitz.open(pdf) as doc:
        for _ in range(3):
            doc[0].insert_text((25, 50), caption, fontsize=11, render_mode=2)
        doc.saveIncr()
    result = preflight_pdf(pdf)
    assert result['recommended_engine'] == 'cloud'
    assert result['pages'][0]['visible_usable_characters'] < 80


def test_large_image_does_not_override_substantial_visible_text(tmp_path):
    pdf = illustrated_pdf(tmp_path / 'background.pdf',
                          'This page has a substantial native text layer. ' * 4, full_page=True)
    result = preflight_pdf(pdf)
    assert result['recommended_engine'] == 'local'
    assert 'image_dominated_page' in result['pages'][0]['warnings']


def test_hidden_ocr_over_full_page_scan_stays_cloud(tmp_path):
    pdf = illustrated_pdf(tmp_path / 'old-ocr.pdf', 'Old hidden OCR text. ' * 4, full_page=True, hidden=True)
    result = preflight_pdf(pdf)
    assert result['recommended_engine'] == 'cloud'
    assert result['pages'][0]['visible_usable_characters'] == 0
    assert 'hidden_text_or_old_ocr' in result['pages'][0]['reasons']


def test_sparse_native_cover_succeeds_end_to_end_without_cloud(tmp_path):
    pytest.importorskip('pymupdf4llm')
    pdf = tmp_path / 'short-cover.pdf'
    with fitz.open() as doc:
        doc.new_page().insert_text((40, 60), 'Scope')
        doc.new_page().insert_text((40, 60), 'Original text with a pressure of 2000 Pa.')
        doc.save(pdf)
    def unexpected_upload(*args):
        pytest.fail('Sparse native cover must not trigger upload')
    result = workflow.process_documents([str(pdf)], OCROptions(), 1, output_dir=tmp_path / 'delivery',
                work_dir=tmp_path / 'records', cloud_process=unexpected_upload)[0]
    assert result['engine'] == 'local' and result['quality']['passed']
    text = Path(result['markdown']).read_text(encoding='utf-8')
    assert 'Scope' in text and '2000 Pa' in text
    assert 'images/' not in text
    assert validate_output(result['markdown'], work_dir=tmp_path / 'records')['valid']
