import json
from pathlib import Path
import shutil
import zipfile

import pytest

from mineru_ocr import cli, environment, native, workflow
from mineru_ocr.errors import MinerUOCRError
from mineru_ocr.models import OCROptions
from mineru_ocr.preflight import preflight_pdf, _union_area
from mineru_ocr.publish import validate_output

fitz = pytest.importorskip('pymupdf')


def make_pdf(path, *, scanned=False, hidden=False, mixed=False, table=False, image=False):
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 60), '1 Scope of the native document', fontsize=17)
        page.insert_text((40, 95), 'The design pressure is 2000 Pa and the length is 120 mm.', fontsize=11)
        page.insert_text((40, 120), '中文文字层与原页核对测试', fontname='china-s', fontsize=11)
        if table:
            xs, ys = [40, 210, 360], [150, 180, 210, 240]
            for x in xs:
                page.draw_line((x, ys[0]), (x, ys[-1]))
            for y in ys:
                page.draw_line((xs[0], y), (xs[-1], y))
            for i, row in enumerate([('Parameter', 'Value'), ('Pressure', '2000'), ('Length', '120')]):
                for j, value in enumerate(row):
                    page.insert_text((xs[j] + 5, ys[i] + 20), value, fontsize=11)
        raster = page.get_pixmap().tobytes('png')
        if image:
            page.insert_text((40, 290), 'Figure 1: original image', fontsize=12)
            page.insert_image(fitz.Rect(40, 310, 220, 565), stream=raster)
        if mixed:
            scan = doc.new_page()
            scan.insert_image(scan.rect, stream=raster)
        if scanned:
            doc.delete_page(0)
            page = doc.new_page()
            page.insert_image(page.rect, stream=raster)
        if hidden:
            page.insert_text((40, 620), 'Old invisible OCR text of unknown quality', render_mode=3)
        doc.save(path)
    return path


def test_preflight_inspects_all_pages_and_detects_old_ocr(tmp_path):
    normal = preflight_pdf(make_pdf(tmp_path / 'native.pdf'))
    assert normal['recommended_engine'] == 'local'
    for mode, reason in [('scanned', 'no_text_layer'), ('mixed', 'no_text_layer')]:
        result = preflight_pdf(make_pdf(tmp_path / (mode + '.pdf'), **{mode: True}))
        assert result['recommended_engine'] == 'cloud'
        assert reason in result['pages'][-1]['reasons']
    assert len(result['pages']) == 2 and result['cloud_pages'] == [2]
    hidden = preflight_pdf(make_pdf(tmp_path / 'hidden.pdf', hidden=True))
    assert hidden['recommended_engine'] == 'local'
    assert 'hidden_text_present' in hidden['pages'][0]['warnings']


def test_preflight_bad_input_and_encryption(tmp_path):
    invalid = tmp_path / 'bad.pdf'
    invalid.write_bytes(b'not a PDF')
    with pytest.raises(MinerUOCRError, match='Cannot inspect PDF'):
        preflight_pdf(invalid)
    encrypted = tmp_path / 'locked.pdf'
    with fitz.open() as doc:
        doc.new_page()
        doc.save(encrypted, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw='test-only')
    with pytest.raises(MinerUOCRError, match='Encrypted'):
        preflight_pdf(encrypted)


def test_overlapping_images_are_not_double_counted():
    assert _union_area([(0, 0, 10, 10), (5, 0, 15, 10)]) == 150


def test_local_only_scan_never_uploads(tmp_path):
    source = make_pdf(tmp_path / 'scan.pdf', scanned=True)
    def unexpected(*args):
        pytest.fail('local-only mode must not upload')
    with pytest.raises(MinerUOCRError, match='Local-only'):
        workflow.process_documents([str(source)], OCROptions(), 1, engine='local', cloud_process=unexpected)


def test_cloud_route_bypasses_local_dependencies(tmp_path, monkeypatch):
    def missing():
        raise AssertionError('cloud mode must not load the local backend')
    monkeypatch.setattr(environment, 'require_local', missing)
    calls = []
    def cloud(files, options, timeout):
        calls.extend(files)
        return [{'state': 'done'}]
    source = make_pdf(tmp_path / 'native.pdf')
    results = workflow.process_documents([str(source)], OCROptions(), 1, engine='cloud', cloud_process=cloud)
    assert calls == [str(source)] and results[0]['engine'] == 'cloud'


def test_auto_scan_routes_once_and_missing_local_is_not_cloud_fallback(tmp_path, monkeypatch):
    calls = []
    def cloud(files, options, timeout):
        calls.extend(files)
        return [{'state': 'done'}]
    scan = make_pdf(tmp_path / 'scan.pdf', scanned=True)
    result = workflow.process_documents([str(scan)], OCROptions(), 1, cloud_process=cloud)
    assert result[0]['engine'] == 'cloud' and calls == [str(scan)]
    def missing():
        raise MinerUOCRError('missing local dependency')
    monkeypatch.setattr(environment, 'require_local', missing)
    source = make_pdf(tmp_path / 'native.pdf')
    with pytest.raises(MinerUOCRError, match='missing local dependency'):
        workflow.process_documents([str(source)], OCROptions(), 1, cloud_process=cloud)
    assert calls == [str(scan)]


def test_numeric_loss_rejects_otherwise_similar_page(tmp_path):
    source = make_pdf(tmp_path / 'native.pdf')
    with fitz.open(source) as doc:
        result = native.check_page(doc[0], doc[0].get_text().replace('2000', '2001'))
    assert not result['passed'] and result['missing_numbers'] == {'2000': 1}
    assert result['added_numbers'] == {'2001': 1}
    assert native._numbers('压力2000Pa，型号GB6932，偏差-0.2mm') == {'2000': 1, '6932': 1, '-0.2': 1}


def test_quality_failure_falls_back_only_in_auto(tmp_path, monkeypatch):
    source = make_pdf(tmp_path / 'native.pdf')
    monkeypatch.setattr(environment, 'require_local', lambda: None)
    def failed(pdf, directory, **kwargs):
        raise native.NativeQualityError({'passed': False}, directory)
    monkeypatch.setattr(workflow, 'extract_native', failed)
    calls = []
    def cloud(files, options, timeout):
        calls.extend(files)
        return [{'state': 'done'}]
    result = workflow.process_documents([str(source)], OCROptions(), 1, cloud_process=cloud)
    assert result[0]['local_attempt']['reason'] == 'native_quality_failed'
    with pytest.raises(native.NativeQualityError):
        workflow.process_documents([str(source)], OCROptions(), 1, engine='local', cloud_process=cloud)
    assert len(calls) == 1


def test_local_end_to_end_preserves_evidence_and_portable_package(tmp_path):
    pytest.importorskip('pymupdf4llm')
    source = make_pdf(tmp_path / '中文 native sample.pdf', table=True, image=True)
    before = source.read_bytes()
    def unexpected(*args):
        pytest.fail('native document should not need cloud')
    result = workflow.process_documents([str(source)], OCROptions(), 1, engine='local',
                                        output_dir=tmp_path / 'delivery', work_dir=tmp_path / 'records',
                                        cloud_process=unexpected)[0]
    assert result['engine'] == 'local' and result['quality']['passed']
    markdown = Path(result['markdown'])
    text = markdown.read_text(encoding='utf-8')
    assert '中文文字层与原页核对测试' in text and '2000' in text
    assert '核对表格原页' not in text and 'images/' in text
    assert '<!-- PDF source page 1 -->' in text
    assert result['review']['source_page_images'] == 0
    assert set(p.name for p in markdown.parent.iterdir()) == {markdown.name, 'images'}
    assert source.read_bytes() == before
    assert validate_output(markdown, work_dir=tmp_path / 'records')['valid']
    manifest = json.loads(Path(result['manifest']).read_text(encoding='utf-8'))
    assert manifest['engine'] == 'pymupdf4llm' and manifest['ocr_used'] is False
    assert all(e['adapter'] == 'pymupdf4llm_pages_v1' for e in manifest['evidence_files'] if e.get('adapter'))
    snapshot = next(e for e in manifest['evidence_files'] if e.get('role') == 'original_input_bundle')
    with zipfile.ZipFile(Path(result['work_dir']) / snapshot['path']) as archive:
        assert archive.read('input/' + source.name) == before
    relocated = tmp_path / 'relocated'
    shutil.copytree(markdown.parent, relocated)
    assert validate_output(relocated / markdown.name, work_dir=tmp_path / 'empty-records')['validation_scope'] == 'references'


def test_cli_preflight_and_doctor_return_json(tmp_path, capsys):
    source = make_pdf(tmp_path / 'native.pdf')
    assert cli.main(['preflight', str(source)]) == 0
    assert json.loads(capsys.readouterr().out)['recommended_engine'] == 'local'
    pytest.importorskip('pymupdf4llm')
    assert cli.main(['doctor']) == 0
    assert json.loads(capsys.readouterr().out)['local_ready']


def test_table_spans_cannot_be_flattened_without_rejection(tmp_path):
    source = make_pdf(tmp_path / 'merged.pdf')
    with fitz.open(source) as doc:
        page = doc[0]
        page.draw_rect(fitz.Rect(40, 160, 360, 250))
        for y in (190, 220):
            page.draw_line((40, y), (360, y))
        page.draw_line((200, 190), (200, 250))
        for point, text in [((45, 180), 'Merged header'), ((45, 210), 'Parameter'),
                            ((205, 210), 'Value'), ((45, 240), 'Pressure'), ((205, 240), '2000')]:
            page.insert_text(point, text, fontsize=11)
        doc.saveIncr()
    pytest.importorskip('pymupdf4llm')
    # Reject before extraction, rather than repairing/validating spans later.
    assert 'complex_table' in preflight_pdf(source)['pages'][0]['reasons']
    with pytest.raises(MinerUOCRError, match='Local-only'):
        workflow.process_documents([str(source)], OCROptions(), 1, engine='local',
                                   output_dir=tmp_path / 'delivery', work_dir=tmp_path / 'records')
    assert not list((tmp_path / 'delivery').glob('*.md'))


def test_blank_physical_page_is_retained_without_a_screenshot(tmp_path):
    pytest.importorskip('pymupdf4llm')
    source = make_pdf(tmp_path / 'blank-end.pdf')
    with fitz.open(source) as doc:
        doc.new_page()
        doc.saveIncr()
    inspection = preflight_pdf(source)
    assert inspection['pages'][1]['classification'] == 'blank'
    result = workflow.process_documents([str(source)], OCROptions(), 1, engine='local',
                                        output_dir=tmp_path / 'delivery', work_dir=tmp_path / 'records')[0]
    assert len(result['quality']['pages']) == 2
    text = Path(result['markdown']).read_text(encoding='utf-8')
    assert '<!-- PDF source page 2 -->' in text
    assert 'images/' not in text


def test_runtime_error_is_reported_without_cloud_fallback(tmp_path, monkeypatch):
    from types import SimpleNamespace
    source = make_pdf(tmp_path / 'native.pdf')
    def broken(*args, **kwargs):
        raise RuntimeError('test-only model runtime failure')
    monkeypatch.setattr(environment, 'require_local', lambda: None)
    monkeypatch.setattr(native, 'require_local', lambda: SimpleNamespace(to_markdown=broken))
    def unexpected(*args):
        pytest.fail('runtime errors must not upload')
    with pytest.raises(MinerUOCRError, match='no cloud fallback'):
        workflow.process_documents([str(source)], OCROptions(), 1, work_dir=tmp_path / 'records', cloud_process=unexpected)
    assert list((tmp_path / 'records').glob('native/*/evidence/runtime-error.json'))


def test_doctor_reports_missing_dependency_without_installing(monkeypatch):
    original = environment.metadata.version
    def version(name):
        if name == 'pymupdf4llm':
            raise environment.metadata.PackageNotFoundError(name)
        return original(name)
    monkeypatch.setattr(environment.metadata, 'version', version)
    report = environment.doctor()
    assert not report['local_ready'] and report['packages']['pymupdf4llm'] is None
    assert '[local]' in report['errors']['local']


def test_same_line_font_fragments_do_not_look_like_numeric_changes():
    with fitz.open() as doc:
        page = doc.new_page()
        prefix = 'Pressure 0.'
        page.insert_text((40, 60), prefix, fontsize=12)
        page.insert_text((40 + fitz.get_text_length(prefix, fontsize=12), 60), '01 MPa', fontsize=12, fontname='hebo')
        result = native.check_page(page, 'Pressure 0.01 MPa')
        assert result['passed'] and not result['missing_numbers'] and not result['added_numbers']


def test_technical_comparison_and_negative_sign_changes_are_rejected():
    assert native._numbers('−10 °C') == {'-10': 1}
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 60), '压力≤2000Pa', fontname='china-s', fontsize=12)
        result = native.check_page(page, '压力≥2000Pa')
        assert 'technical_symbol_change' in result['issues']


def test_spurious_chinese_superscripts_require_review_even_without_text_loss():
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 60), '规范性引用文件', fontname='china-s', fontsize=12)
        result = native.check_page(page, '<sup>规范性引用文件</sup>')
        assert result['character_retention'] == 1
        assert 'script_formatting_needs_review' in result['issues']
