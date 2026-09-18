from mineru_ocr.locators import LocatorIndex


def test_numbered_figure_legend_does_not_reset_appendix_partition():
    index = LocatorIndex('source')
    index.mark('1 范围', 1)
    index.mark('附录 A', 2)
    assert index.mark('1 ——被试验设备；', 3) is None
    assert index.mark('2 —供气阀；', 3) is None
    assert index.mark('A.2 要求', 3) == 'appendix-a-clause-a-2'
    assert index.items[-1]['partition'] == '附录A'


def test_body_and_commentary_repeated_numbers_have_independent_positions():
    index = LocatorIndex('source-hash')
    index.mark('1 总则', 1)
    assert index.mark('7.0.4 具体要求', 20) == 'body-clause-7-0-4'
    index.mark('条文说明', 40)
    assert index.mark('7.0.4 原因说明', 60) == 'commentary-clause-7-0-4'
    index.mark('附录 A', 70)
    assert index.mark('A.1 说明', 71) == 'commentary-appendix-a-clause-a-1'
    assert not index.issues
    assert all(x['source_sha256'] == 'source-hash' for x in index.items)


def test_duplicate_same_partition_kept_and_reported():
    index = LocatorIndex('h')
    index.mark('1 总则', 1)
    index.mark('1.1 要求', 2)
    assert index.mark('1.1 再次出现', None).endswith('-occurrence-2')
    assert len(index.issues) == 1
    assert index.items[-1]['pdf_page'] is None
