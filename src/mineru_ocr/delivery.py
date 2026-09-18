"""Human-readable, source-bound delivery records for downstream wiki ingestion."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from .errors import MinerUOCRError
from .provenance import digest_file

REPORT_SUFFIXES = ('.来源说明.md', '.定位与图片清单.md', '.校勘与缺口.md')


def target_rules(path: Path | None) -> list[dict]:
    if path is None:
        return []
    root = Path(path).resolve()
    names = ['AGENTS.md', '知识库说明.md', '通用使用指南.md', 'rules/摄入规则.md',
             'rules/视觉资产规则.md', 'rules/标签与元数据规则.md', 'rules/更新与纠错规则.md',
             'rules/审核与验收规则.md', 'rules/templates/来源页模板.md']
    result = []
    for name in names:
        file = root / name
        if not file.is_file():
            raise MinerUOCRError(f'Target project rule is missing: {name}')
        result.append({'path': name, 'sha256': digest_file(file)})
    return result


def cell(value) -> str:
    return str(value if value is not None else '待核实').replace('|', r'\|').replace('\n', ' ')


def link(label, target) -> str:
    return f'[{str(label).replace("[", "（").replace("]", "）")}]({quote(target, safe="/#-._")})'


def report_documents(manifest: dict, audit: dict) -> dict[str, str]:
    config = manifest['postprocess']
    markdown = manifest['markdown']
    main = link('整理正文', markdown)
    source_info = [f'# {config["source_id"]} 来源与交付说明\n', main + '\n',
                   '| 字段 | 内容 |\n|---|---|']
    values = {
        '来源编号': config['source_id'], '原始文件名称': manifest.get('source_name'),
        '交付配置': config['profile'], '输入PDF指纹': manifest['source_sha256'],
        '原始OCR文本指纹': audit['input_markdown_sha256'], '整理正文指纹': manifest['markdown_sha256'],
        'PDF物理页数': manifest.get('page_count'), '生成时间': config['created_at'],
        '发布机构／发布与实施日期': '待按原文核实', '效力核实状态／依据／日期': '待核实',
        '原始取得渠道／公开条件': '待使用者补充', '资料类型／地域／业务主题': '摄入时按目标项目受控词表登记',
        '变化类型': '同版转写整理；不是发布机构的标准修订',
        '完整性': '保留输入正文；OCR是否遗漏内容仍须对照原件核实',
        '实际处理': f'结构整理、{len(audit["reviewed_corrections"])}项有记录替换、图片与条款定位、表格格式判定',
        '人工审核／行业验收': '未完成；程序检查和Agent抽查不能代填人工通过',
    }
    source_info += [f'| {key} | {cell(value)} |' for key, value in values.items()]
    source_info += ['\n## 输入与证据\n']
    for item in manifest.get('evidence_files', []):
        if item.get('role') in {'original_input_bundle', 'readability_audit'}:
            source_info.append('- ' + link('原始输入快照' if item['role'] == 'original_input_bundle' else '处理审计JSON', item['path']) +
                               f'；SHA256：`{item["sha256"]}`')
    source_info += ['\n原始输入快照保留源PDF、OCR文本、图片与布局证据。正文与本说明属于处理成果。'
                    '源文件名与文内名称不一致时，需在正式来源登记中记录差异。',
                    '\n## 目标规则基线\n',
                    '此清单记录交付时读取的规则指纹，不替代摄入时实际阅读项目规则。']
    source_info += [f'- `{entry["path"]}`：`{entry["sha256"]}`' for entry in config.get('target_rules', [])]
    if not config.get('target_rules'):
        source_info.append('- 未指定目标项目，尚未绑定目标规则快照。')

    locators = [f'# {config["source_id"]} 定位与图片清单\n', main + '\n',
                f'定位绑定整理正文 SHA256：`{manifest["markdown_sha256"]}`。PDF页码为物理页序。',
                '\n## 条款与分区\n', '| 分区 | 条款或标题 | PDF页 | 正文定位 |\n|---|---|---|---|']
    for item in audit.get('clause_locators', []):
        locators.append(f'| {cell(item["partition"])} | {cell(item["title"])} | {cell(item["pdf_page"])} | '
                        + link('定位', markdown + '#' + item['anchor']) + ' |')
    locators += ['\n## 图片\n',
                 '下列“程序可解码”只证明文件可读，不代表Agent或人工实际看过图片。'
                 '图片当前供人工参考；未核对的尺寸、单位和关系不生成技术结论。\n',
                 '| 图片 | 来源页／图题 | 文件SHA256 | 文件检查 | 可读性／视觉检查 | 人工核对 | 知识提取 |\n|---|---|---|---|---|---|---|']
    for asset in manifest['assets']:
        if asset['kind'] != 'image':
            continue
        locations = asset.get('locations', [])
        pages = sorted({x['page'] for x in locations if x.get('page')})
        captions = list(dict.fromkeys(c for x in locations for c in x.get('figure_captions', [])))
        description = '、'.join(captions) or ('原页影像' if any(x.get('origin') == 'source_pdf_render' and not x.get('bbox') for x in locations) else '图号／图题待核实')
        checked = any(x.get('decode_checked') for x in locations)
        locators.append('| ' + link(description, asset['path']) + f' | {cell(pages or None)}；{cell(description)} | '
                        f'`{asset["sha256"]}` | 存在、指纹与引用已检查 | '
                        + ('程序可解码；未登记视觉检查' if checked else '未登记解码或视觉检查')
                        + ' | 未核对 | 未执行 |')
    locators += ['\n## 裁切与原页关联\n', '| 图片 | 原页 | 原OCR图片指纹 |\n|---|---|---|']
    page_assets = {loc['page']: a['path'] for a in manifest['assets'] for loc in a.get('locations', [])
                   if loc.get('page') and loc.get('origin') == 'source_pdf_render' and not loc.get('bbox')}
    for asset in manifest['assets']:
        for loc in asset.get('locations', []):
            if loc.get('crop_padding_points') is not None:
                page = loc['page']
                page_link = link(f'PDF第{page}页', page_assets[page]) if page in page_assets else f'PDF第{page}页（见输入快照）'
                locators.append('| ' + link('裁切图', asset['path']) + ' | ' + page_link + f' | `{loc.get("original_asset_sha256", "待核实")}` |')

    quality = [f'# {config["source_id"]} 校勘与待核实事项\n', main + '\n',
               '核对状态：程序检查完成；记录的替换具有复核说明；全文未逐字逐格人工验收。'
               '格式转换通过不能证明OCR准确率。\n', '## 表格处理\n',
               '| 序号 | 格式 | 判断原因 | 表头依据 | PDF页 |\n|---|---|---|---|---|']
    reasons = {'preserve_requested': '按选项保留HTML', 'merged_cells': '含合并单元格',
               'nested_or_rich_content': '含嵌套或富内容', 'unsupported_attributes': '有需保留的属性',
               'malformed_html': 'HTML结构异常', 'not_rectangular_or_no_body': '非矩形或无数据行',
               'wide_table': '列数较多', 'long_cells': '单元格长段落', 'complex_math': '复杂公式',
               'ambiguous_pipe_escape': '竖线转义待核实', 'row_headers_or_multiple_header_rows': '行标题或多层表头',
               'header_needs_source_review': '首行是否表头尚待核对', 'cell_roundtrip_failed': '单元格往返校验未通过',
               'rectangular_verified': '规则二维表，单元格往返一致'}
    for item in audit.get('table_decisions', []):
        basis = {'html_th': '原HTML的th标签', 'source_review': '原页核对记录'}.get(item.get('header_basis'), '未作转换确认')
        pages = '、'.join(link(f'第{page}页', page_assets[page]) if page in page_assets else f'第{page}页'
                         for page in item.get('pages', [])) or '待核实'
        quality.append(f'| {item["index"]} | {item["format"]} | {cell(reasons.get(item["reason"], item["reason"]))} | {basis} | {pages} |')
    quality += ['\n## 定点修正\n']
    for index, correction in enumerate(audit['reviewed_corrections'], 1):
        quality += [f'### {index}. PDF第{correction["page"]}页\n', str(correction['reason']),
                    '\n修改前：\n', fenced(correction['before']), '\n修改后：\n', fenced(correction['after'])]
    if not audit['reviewed_corrections']:
        quality.append('没有应用文字纠错；不表示输入没有识别错误。')
    quality += ['\n## 结构疑点\n']
    for item in audit.get('suspect_header_blocks', []):
        quality.append(f'- PDF第{item["page"]}页：异常位置的页眉 `{cell(item.get("text"))}`，需结合校勘记录及原页检查。')
    for item in audit.get('locator_issues', []):
        quality.append('- 定位疑点：' + cell(item))
    for item in audit.get('clause_locators', []):
        if item.get('pdf_page') is None:
            quality.append('- PDF页码未可靠匹配：' + cell(item['partition']) + '，'
                           + link(item['title'], markdown + '#' + item['anchor']) + '。')
    quality += ['\n## 尚未完成的核对\n',
                '- 全文OCR完整性、逐格数值和单位、图示技术含义、粗体等原版含义。',
                '- 标准当前效力、后续修订、取得渠道和公开条件。',
                '- 行业人员验收；不能依据本报告自动解除目标Wiki中已有缺口。']
    for target in manifest.get('external_images', []):
        quality.append('- 外链图片未下载、未验证：' + cell(target))
    return dict(zip(REPORT_SUFFIXES, ('\n'.join(source_info) + '\n', '\n'.join(locators) + '\n', '\n'.join(quality) + '\n')))


def fenced(value: str) -> str:
    import re
    fence = '`' * max(3, 1 + max((len(x) for x in re.findall(r'`+', value)), default=0))
    return fence + '\n' + value + '\n' + fence + '\n'
