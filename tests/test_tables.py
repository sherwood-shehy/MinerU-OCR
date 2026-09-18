import pytest

from mineru_ocr.tables import convert_table, pipe_cells


def test_roundtrip_preserves_empty_cells_pipes_signs_units_math_and_literal_markup():
    raw = r'<table><tr><th>项目</th><th>值</th><th>单位</th></tr><tr><td>A|B</td><td>≤0.003 ± 0.001</td><td></td></tr><tr><td>*原文*</td><td>$\Phi_1 &lt; 0.3$</td><td>m3/h &amp; kW</td></tr></table>'
    text, record = convert_table(raw, mode='auto')
    assert record['format'] == 'markdown' and record['cells_preserved']
    assert pipe_cells(text.splitlines()[2]) == ['A|B', '≤0.003 ± 0.001', '']
    assert pipe_cells(text.splitlines()[3]) == ['*原文*', r'$\Phi_1 < 0.3$', 'm3/h & kW']
    assert '&#42;' in text


@pytest.mark.parametrize('body', [
    '<tr><th>A</th><th>B</th></tr><tr><td colspan="2">1</td></tr>',
    '<tr><th>A</th><th>B</th></tr><tr><td>1</td></tr>',
    '<tr><th>A</th></tr><tr><td><table><tr><td>1</td></tr></table></td></tr>',
    '<tr><th>A</th></tr><tr><td>1<br>2</td></tr>',
    '<tr><th>A</th></tr><tr><th>row header</th></tr>',
    '<tr><th>A</th></tr><tr><td><sup>2</sup></td></tr>',
    '<tr><th>A</th></tr><tr><td>$$x=2$$</td></tr>',
    '<tr><th>A</th></tr><tr><td>1</tr>',
])
def test_complex_or_malformed_table_keeps_exact_html(body):
    raw = '<table>' + body + '</table>'
    text, record = convert_table(raw, mode='auto', header_confirmed=True)
    assert text == raw and record['format'] == 'html'


def test_td_header_needs_explicit_source_review_and_html_mode_is_immutable():
    raw = '<table><tr><td>类别</td><td>值</td></tr><tr><td>A</td><td>2</td></tr></table>'
    assert convert_table(raw, mode='auto')[1]['reason'] == 'header_needs_source_review'
    assert convert_table(raw, mode='auto', header_confirmed=True)[1]['format'] == 'markdown'
    assert convert_table(raw, mode='html', header_confirmed=True)[0] == raw
