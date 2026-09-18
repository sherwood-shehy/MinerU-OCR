import json
from pathlib import Path

import pytest

from mineru_ocr.errors import MinerUOCRError
from mineru_ocr.provenance import digest_file
from mineru_ocr.readable import _apply_review, normalize_structure, prepare_readable


def test_structure_keeps_values_tables_and_body_and_separates_levels():
    table = '<table><tr><td rowspan="2">0.003 ± 0.001</td></tr></table>'
    original = 'GB 123—2020\n\n## GB 123—2020\n\n## 3 术语\n\n## 3.1\n\n## 流量 flow\n\n定义正文。\n\n' + table + '\n\n$$x=2^{3}$$'
    text, audit = normalize_structure(original, {'GB123—2020'}, {'GB123—2020'})
    assert text.startswith('GB 123—2020\n')
    assert '## GB' not in text
    assert '### 3.1 流量 flow' in text
    assert table in text and '$$x=2^{3}$$' in text and '定义正文。' in text
    assert audit['non_whitespace_content_preserved']


def test_review_requires_exact_occurrences_and_source_page(tmp_path):
    review = tmp_path / 'review.json'
    review.write_text(json.dumps({'replacements': [{'before': 'wrong', 'after': 'right', 'page': 1, 'reason': 'source checked'}]}))
    with pytest.raises(MinerUOCRError, match='occurrence mismatch'):
        _apply_review('wrong wrong', review, 2)
    assert _apply_review('wrong', review, 2)[0] == 'right'
    with pytest.raises(MinerUOCRError, match='source page'):
        _apply_review('wrong', review, 0)


def test_join_only_confirmed_running_header_breaks():
    text, audit = normalize_structure('正文' * 25 + '开\n\n## GB 123\n\n关。\n\n完整句。\n\n## GB 123\n\n下一段。', {'GB123'})
    assert '开关。' in text
    assert '完整句。\n\n下一段。' in text
    assert len(audit['joined_page_breaks']) == 1


def test_structure_does_not_rewrite_multiline_math_tables_or_code():
    blocks = ['$$\n\n1 formula\n\n## literal\n\n$$',
              '<table>\n<tr><td>\n\n1 text\n\n## literal\n\n</td></tr></table>',
              '```text\n\n## literal\n\n1 code\n\n```']
    result, _ = normalize_structure('## 1 Scope\n\n' + '\n\n'.join(blocks), set())
    assert all(block in result for block in blocks)


def test_target_rules_are_read_only_and_missing_rules_are_explicit(tmp_path):
    from mineru_ocr.delivery import target_rules
    with pytest.raises(MinerUOCRError, match='Target project rule is missing'):
        target_rules(tmp_path)
    assert list(tmp_path.iterdir()) == []


def make_source(tmp_path):
    fitz = pytest.importorskip('pymupdf')
    pdf = tmp_path / 'scan.pdf'
    with fitz.open() as doc:
        for _ in range(2):
            page = doc.new_page(width=200, height=200)
            page.insert_text((20, 30), 'source')
        doc.save(pdf)
    bundle = tmp_path / 'bundle'
    (bundle / 'evidence').mkdir(parents=True)
    table = '<table><tr><td>1.23</td></tr></table>'
    equation = '$$x=1.23$$'
    content = [{'type': 'text', 'text': '1 Scope', 'text_level': 1, 'page_idx': 0},
               {'type': 'table', 'table_body': table, 'page_idx': 0, 'bbox': [100, 100, 500, 500]},
               {'type': 'table', 'page_idx': 1, 'bbox': [100, 100, 500, 500]},
               {'type': 'header', 'text': '单位为毫米', 'page_idx': 1, 'bbox': [800, 106, 890, 120]},
               {'type': 'equation', 'text': equation, 'page_idx': 1, 'bbox': [100, 100, 500, 500]}]
    evidence = bundle / 'evidence/content_list.json'
    evidence.write_text(json.dumps(content), encoding='utf-8')
    (bundle / 'full.md').write_text('# Demo\n\n## 1 Scope\n\n' + table + '\n\n' + equation, encoding='utf-8')
    manifest = {'source_name': 'scan.pdf', 'source_sha256': digest_file(pdf), 'page_count': 2,
                'parts': [{'index': 1, 'page_start': 1, 'page_end': 2, 'page_ranges': None, 'physical': False}],
                'evidence_files': [{'path': 'evidence/content_list.json', 'sha256': digest_file(evidence),
                                    'part_index': 1, 'adapter_status': 'adapted'}]}
    (bundle / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return pdf, bundle


def test_readable_keeps_raw_links_source_and_hashes_and_no_clobber(tmp_path):
    from mineru_ocr.publish import validate_output
    pdf, bundle = make_source(tmp_path)
    before = (bundle / 'full.md').read_bytes()
    result = prepare_readable(bundle, pdf, tmp_path / 'out')
    markdown = Path(result['markdown'])
    text = markdown.read_text(encoding='utf-8')
    assert 'images/' in text and 'source-page-2' in text
    assert result['review']['table_source_links'] == 1
    assert len(result['review']['adjacent_table_region_links']) == 1
    assert result['review']['suspect_header_blocks'][0]['text'] == '单位为毫米'
    assert result['review']['display_math_source_links'] == 1
    assert result['review']['tables_unchanged_from_original']
    assert result['review']['display_math_unchanged_from_original']
    assert (bundle / 'full.md').read_bytes() == before
    assert validate_output(markdown)['valid']
    second = prepare_readable(bundle, pdf, tmp_path / 'out')
    assert result['markdown'] != second['markdown']
    manifest = json.loads(Path(result['manifest']).read_text(encoding='utf-8'))
    assert any(x.get('role') == 'readability_audit' for x in manifest['evidence_files'])


def test_rejects_wrong_pdf_before_publication(tmp_path):
    pdf, bundle = make_source(tmp_path)
    pdf.write_bytes(pdf.read_bytes() + b'\nchanged')
    with pytest.raises(MinerUOCRError, match='hash does not match'):
        prepare_readable(bundle, pdf, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_reviewed_cell_and_formula_corrections_keep_original_page_mapping(tmp_path):
    pdf, bundle = make_source(tmp_path)
    review = tmp_path / 'review.json'
    review.write_text(json.dumps({'source_sha256': digest_file(pdf), 'replacements': [
        {'before': '1.23', 'after': '1.24', 'page': 1, 'count': 2, 'reason': 'test source check'}]}), encoding='utf-8')
    result = prepare_readable(bundle, pdf, tmp_path / 'out', review_file=review)
    assert result['review']['table_source_links'] == 1
    assert result['review']['display_math_source_links'] == 1


def test_generated_anchor_checks_ignore_code_but_reject_broken_links(tmp_path):
    from mineru_ocr.publish import _validate_generated_anchors
    md = tmp_path / 'source.md'
    md.write_text('<a id="body-clause-1"></a>\n\n[x](#body-clause-1)\n\n```html\n<a id="body-clause-1"></a>\n```', encoding='utf-8')
    _validate_generated_anchors(md)
    md.write_text('[x](#body-clause-2)', encoding='utf-8')
    with pytest.raises(MinerUOCRError, match='Broken generated source anchor'):
        _validate_generated_anchors(md)


def test_source_profile_has_traceable_reports_original_snapshot_and_no_page_gallery(tmp_path):
    import zipfile
    from mineru_ocr.publish import validate_output, publish_output
    pdf, bundle = make_source(tmp_path)
    original = (bundle / 'full.md').read_bytes()
    result = prepare_readable(bundle, pdf, tmp_path / 'out', profile='gas-std-wiki', source_id='GB-TEST')
    md = Path(result['markdown'])
    text = md.read_text(encoding='utf-8')
    assert 'id="source-pages"' not in text
    assert 'id="body-clause-1"' in text
    manifest = json.loads(Path(result['manifest']).read_text(encoding='utf-8'))
    snapshot = next(e for e in manifest['evidence_files'] if e.get('role') == 'original_input_bundle')
    with zipfile.ZipFile(md.parent / snapshot['path']) as archive:
        assert archive.read('full.md') == original
        assert archive.read('input/scan.pdf') == pdf.read_bytes()
    assert len(result['delivery_documents']) == 3
    assert validate_output(md)['valid']
    again = publish_output(md, tmp_path / 'another')
    assert validate_output(again['markdown'])['valid']
    report = Path(result['delivery_documents'][0])
    report.write_text(report.read_text(encoding='utf-8') + '\nchanged', encoding='utf-8')
    with pytest.raises(MinerUOCRError, match='Delivery document hash'):
        validate_output(md)


def test_simple_table_review_conversion_and_report_family_collision(tmp_path):
    from mineru_ocr.tables import table_hash
    pdf, bundle = make_source(tmp_path)
    original = (bundle / 'full.md').read_text(encoding='utf-8')
    table = '<table><tr><td>类别</td><td>参数</td></tr><tr><td>A</td><td>0.003</td></tr></table>'
    (bundle / 'full.md').write_text(original.replace('<table><tr><td>1.23</td></tr></table>', table), encoding='utf-8')
    review = tmp_path / 'review.json'
    review.write_text(json.dumps({'source_sha256': digest_file(pdf), 'table_headers': [
        {'input_sha256': table_hash(table), 'header_row': 0, 'page': 1, 'reason': 'source checked'}]}), encoding='utf-8')
    out = tmp_path / 'out'
    out.mkdir()
    sentinel = out / 'Case.来源说明.md'
    sentinel.write_text('existing', encoding='utf-8')
    result = prepare_readable(bundle, pdf, out, profile='gas-std-wiki', name='Case', review_file=review)
    assert Path(result['markdown']).stem == 'Case (1)'
    assert sentinel.read_text(encoding='utf-8') == 'existing'
    assert result['review']['converted_table_count'] == 1
    assert '| A | 0.003 |' in Path(result['markdown']).read_text(encoding='utf-8')
