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


def test_td_text_header_convention_and_html_mode_is_immutable():
    raw = '<table><tr><td>类别</td><td>值</td></tr><tr><td>A</td><td>2</td></tr></table>'
    assert convert_table(raw, mode='auto')[1]['header_basis'] == 'textual_first_row_convention'
    assert convert_table(raw, mode='auto', header_confirmed=True)[1]['format'] == 'markdown'
    assert convert_table(raw, mode='html', header_confirmed=True)[0] == raw


def test_user_fire_risk_table_converts_without_th_or_review():
    rows = [
        ['危险因素 危险等级', '使用性质', '人员密集程度', '用电用火设备', '可燃物数量', '火灾蔓延速度', '扑救难度'],
        ['严重危险级', '重要', '密集', '多', '多', '迅速', '大'],
        ['中危险级', '较重要', '较密集', '较多', '较多', '较迅速', '较大'],
        ['轻危险级', '一般', '不密集', '较少', '较少', '较缓慢', '较小'],
    ]
    raw = '<table>' + ''.join('<tr>' + ''.join('<td>' + c + '</td>' for c in row) + '</tr>' for row in rows) + '</table>'
    text, record = convert_table(raw, mode='auto')
    assert record['format'] == 'markdown'
    assert [pipe_cells(line) for n, line in enumerate(text.splitlines()) if n != 1] == rows


def test_width_and_cell_length_are_not_structural_complexity():
    raw = '<table><tr>' + '<td>Label</td>' * 12 + '</tr><tr>' + ('<td>' + '正文' * 200 + '</td>') * 12 + '</tr></table>'
    result, record = convert_table(raw, mode='auto')
    assert record['format'] == 'markdown' and record['columns'] == 12
    assert pipe_cells(result.splitlines()[2]) == ['正文' * 200] * 12


@pytest.mark.parametrize('first_row', ['<td>1</td><td>2</td>', '<td></td><td>Value</td>'])
def test_ambiguous_first_row_keeps_html_until_reviewed(first_row):
    raw = '<table><tr>' + first_row + '</tr><tr><td>A</td><td>3</td></tr></table>'
    assert convert_table(raw, mode='auto')[1]['reason'] == 'header_needs_source_review'
    assert convert_table(raw, mode='auto', header_confirmed=True)[1]['format'] == 'markdown'


def test_multilevel_thead_using_td_is_preserved():
    raw = '<table><thead><tr><td>A</td></tr><tr><td>B</td></tr></thead><tbody><tr><td>C</td></tr></tbody></table>'
    assert convert_table(raw, mode='auto')[0] == raw
