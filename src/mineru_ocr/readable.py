"""Conservative, offline reading editions with source-image verification links."""
from __future__ import annotations

from collections import Counter, defaultdict, deque
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from types import SimpleNamespace
import zipfile

from .errors import MinerUOCRError
from .provenance import _page_number, build_manifest, digest_file, manifest_path
from .publish import publish_output, source_for_processing
from .references import local_resource, references, rewrite_references
from .delivery import target_rules
from .records import check_work_dir
from .visuals import apply_image_review
from .locators import LocatorIndex
from .tables import convert_table, table_hash

NUMBER = r'(?:\d+(?:\.\d+)*|[A-Z](?:\.\d+)+)'
TABLE = re.compile(r'<table\b.*?</table>', re.S | re.I)
EQUATION = re.compile(r'\$\$.*?\$\$', re.S)
PROTECTED = re.compile(r'^(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^(?P=fence)[ \t]*$|<table\b.*?</table>|\$\$.*?\$\$', re.S | re.M | re.I)


def protect_blocks(text: str) -> tuple[str, list[str]]:
    blocks = []
    def replace(match):
        blocks.append(match.group(0))
        return f'\x00MINERU-PROTECTED-{len(blocks) - 1}\x00'
    return PROTECTED.sub(replace, text), blocks


def restore_blocks(text: str, blocks: list[str]) -> str:
    return re.sub(r'\x00MINERU-PROTECTED-(\d+)\x00', lambda m: blocks[int(m.group(1))], text)


def compact(text: str) -> str:
    return re.sub(r'\s+', '', text)


def plain(text: str) -> str:
    return re.sub(r'^#{1,6}\s+', '', text.strip())


def content_fingerprint(text: str) -> str:
    """Only heading markers and whitespace are excluded, never numbers or punctuation."""
    value = re.sub(r'^#{1,6}\s+', '', text, flags=re.M)
    return hashlib.sha256(compact(value).encode('utf-8')).hexdigest()


def normalize_structure(text: str, removable: set[str], preserve_first: set[str] | None = None, *,
                        preserve_headings: bool = False) -> tuple[str, dict]:
    text, protected = protect_blocks(text)
    paragraphs = re.split(r'\n\s*\n', text.strip())
    kept, removed, continuations = [], [], []
    preserve_first = set(preserve_first or ())
    join_next = False
    for index, paragraph in enumerate(paragraphs):
        key = compact(plain(paragraph))
        if key in preserve_first:
            preserve_first.remove(key)
            kept.append(paragraph)
        elif key in removable:
            removed.append(paragraph)
            if kept and index + 1 < len(paragraphs):
                previous, following = kept[-1], paragraphs[index + 1]
                join_next = (not previous.startswith(('#', '<', '!', '$')) and len(previous) >= 40
                             and '\n' not in previous and '\n' not in following
                             and bool(re.search(r'[\u4e00-\u9fff]$', previous))
                             and bool(re.match(r'^[\u4e00-\u9fff]', following))
                             and compact(plain(following)) not in removable)
        else:
            if join_next:
                continuations.append({'before': kept[-1][-40:], 'after': paragraph[:40]})
                kept[-1] += paragraph
                join_next = False
            else:
                kept.append(paragraph)
    baseline = '\n\n'.join(kept)
    output, merges = [], []
    i = 0
    while i < len(kept):
        paragraph = kept[i]
        value = plain(paragraph)
        # A number-only OCR heading followed by a short term title.
        if (paragraph.startswith('#') and re.fullmatch(NUMBER, value)
                and i + 1 < len(kept)):
            following = plain(kept[i + 1])
            if (0 < len(following) < 240 and '\n' not in following
                    and not re.match(r'(?:[<!$]|' + NUMBER + r'\s)', following)
                    and not re.search(r'[。；;：:]$', following)):
                value += ' ' + following
                merges.append(value)
                i += 1
        numbered = re.match(r'^(' + NUMBER + r')(?:\s+)(.+)$', value)
        is_heading = paragraph.startswith('#')
        if numbered and (is_heading or (not preserve_headings and len(value) < 65 and not re.search(r'[。；;：:]$', value))):
            level = min(6, numbered.group(1).count('.') + 2)
            paragraph = '#' * level + ' ' + value
        elif re.fullmatch(r'附录\s*[A-Z]', value) or compact(value) in {
                '前言', '目次', '目录', '条文说明', '标准条文说明', '规范条文说明',
                '本规范用词说明', '本标准用词说明', '引用标准名录', '参考文献'}:
            paragraph = '## ' + value
        elif is_heading and not preserve_headings:
            # Cover labels, captions and appendix subtitles remain verbatim text.
            paragraph = value
        output.append(paragraph)
        i += 1
    normalized = '\n\n'.join(output) + '\n'
    invariant = content_fingerprint(baseline) == content_fingerprint(normalized)
    if not invariant:
        raise MinerUOCRError('Structure normalization changed non-whitespace content')
    return restore_blocks(normalized, protected), {'removed_running_lines': removed, 'joined_term_headings': merges,
                        'joined_page_breaks': continuations,
                        'non_whitespace_content_preserved': invariant}


def _layout(source: Path, manifest: dict) -> list[dict]:
    result = []
    parts = {p['index']: SimpleNamespace(**p) for p in manifest.get('parts', [])}
    for entry in manifest.get('evidence_files', []):
        if entry.get('adapter') == 'pymupdf4llm_pages_v1' and entry.get('adapter_status') == 'adapted':
            file = local_resource(source.parent, entry['path'])
            data = json.loads(file.read_text(encoding='utf-8'))
            if (not isinstance(data, list) or any(not isinstance(b, dict) or type(b.get('page')) is not int
                    or not 1 <= b['page'] <= manifest.get('page_count', 0) for b in data)):
                raise MinerUOCRError('Invalid native page-layout evidence')
            result.extend({**block, '_page': block['page'], '_evidence': entry['path'] + f'#/{index}'}
                          for index, block in enumerate(data))
            continue
        if entry.get('adapter_status') != 'adapted' or entry.get('part_index') not in parts:
            continue
        file = local_resource(source.parent, entry['path'])
        data = json.loads(file.read_text(encoding='utf-8'))
        if not isinstance(data, list):
            continue
        for index, block in enumerate(data):
            if isinstance(block, dict):
                page = _page_number(block.get('page_idx'), parts[entry['part_index']])
                result.append({**block, '_page': page, '_evidence': entry['path'] + f'#/{index}'})
    return result


def _apply_review(text: str, review_file: Path | None, page_count: int) -> tuple[str, list]:
    if not review_file:
        return text, []
    review = json.loads(Path(review_file).read_text(encoding='utf-8'))
    edits = review.get('replacements', [])
    for edit in edits:
        before, after = edit['before'], edit['after']
        page, reason, count = edit.get('page'), edit.get('reason'), edit.get('count', 1)
        if (not before or not isinstance(after, str) or not reason or type(page) is not int
                or not 1 <= page <= page_count or type(count) is not int or count < 1):
            raise MinerUOCRError('Every reviewed correction needs exact text, count, source page and reason')
        if text.count(before) != count:
            raise MinerUOCRError(f'Review correction occurrence mismatch on source page {page}')
        text = text.replace(before, after)
    return text, edits


def _scale(page) -> float:
    # Keep full-page scans at their native pixel resolution; render vector pages at 144 dpi.
    for info in page.get_image_info():
        x0, y0, x1, y1 = info['bbox']
        if (x1 - x0) * (y1 - y0) >= page.rect.get_area() * .85:
            return min(4, max(.25, info['width'] / (x1 - x0)))
    return 2


def prepare_readable(path: str | Path, source_pdf: str | Path, output_dir: str | Path, *,
                     name: str | None = None, title: str | None = None,
                     review_file: Path | None = None, profile: str = 'generic',
                     edition: str | None = None, table_format: str | None = None,
                     target_project: Path | None = None, source_id: str | None = None,
                     work_dir: Path | None = None) -> dict:
    try:
        import pymupdf as fitz
    except ImportError as exc:
        raise MinerUOCRError('Reading editions require the optional PyMuPDF dependency') from exc
    if profile not in {'generic', 'gas-std-wiki'}:
        raise MinerUOCRError('Unknown delivery profile')
    edition = edition or 'source'
    table_format = table_format or 'auto'
    if edition not in {'reading', 'source'} or table_format not in {'html', 'auto'}:
        raise MinerUOCRError('Unknown edition or table format')
    rules = target_rules(target_project)
    source = source_for_processing(path, work_dir)
    metadata = build_manifest(source)
    pdf = Path(source_pdf).resolve()
    source_hash = digest_file(pdf)
    if not metadata.get('source_sha256') or metadata['source_sha256'] != source_hash:
        raise MinerUOCRError('Source PDF hash does not match the extraction manifest')
    native = metadata.get('engine') == 'pymupdf4llm'
    if native and metadata.get('native_quality_passed') is not True:
        raise MinerUOCRError('Native extraction has not passed the local quality checks')
    review_data = json.loads(Path(review_file).read_text(encoding='utf-8')) if review_file else {}
    if not isinstance(review_data, dict):
        raise MinerUOCRError('Review file must be a JSON object')
    if review_file:
        review_hash = review_data.get('source_sha256')
        if review_hash and review_hash != source_hash:
            raise MinerUOCRError('Review file source hash does not match the PDF')
    blocks = _layout(source, metadata)
    if not blocks:
        raise MinerUOCRError('Postprocessing requires adapted MinerU or native page-layout evidence')
    out = Path(output_dir).resolve()
    root = check_work_dir(out, work_dir)
    root.mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf) as doc, tempfile.TemporaryDirectory(prefix='.readable-', dir=root) as temporary:
        if metadata.get('page_count') != len(doc):
            raise MinerUOCRError('Source PDF page count does not match the OCR manifest')
        stage = Path(temporary)
        original = source.read_text(encoding='utf-8')
        for ref in references(original):
            file = local_resource(source.parent, ref.target)
            if file:
                target = stage / file.relative_to(source.parent)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, target)
        for entry in metadata.get('evidence_files', []):
            file = local_resource(source.parent, entry['path'])
            target = stage / file.relative_to(source.parent)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, target)
        filtered, image_decisions = apply_image_review(original, source.parent, metadata, review_data)
        revised, corrections = _apply_review(filtered, review_file, len(doc))
        header_reviews = review_data.get('table_headers', [])
        available_tables = {table_hash(t) for t in TABLE.findall(revised)}
        for item in header_reviews:
            if (item.get('input_sha256') not in available_tables or item.get('header_row') != 0
                    or type(item.get('page')) is not int or not 1 <= item['page'] <= len(doc)
                    or not item.get('reason')):
                raise MinerUOCRError('Table header review must identify an existing table, first row, page and reason')
        confirmed_headers = {item['input_sha256'] for item in header_reviews}
        def margin_line(block):
            box = block.get('bbox') or []
            return len(box) == 4 and ((block.get('type') == 'header' and box[3] < 100)
                                      or (block.get('type') == 'footer' and box[1] > 900))
        running = Counter(compact(b.get('text', '')) for b in blocks if margin_line(b))
        # Repetition and layout classification are both required; cover-only metadata stays.
        removable = {text for text, count in running.items() if text and count >= 3}
        cover_text = {compact(b.get('text', '')) for b in blocks if b['_page'] == 1}
        normalized, audit = normalize_structure(revised, removable, cover_text, preserve_headings=native)
        # Repeated headers may be emitted with different spacing; retain every removal in the log.
        audit.update({'schema_version': '1.0', 'source_sha256': source_hash,
                      'input_markdown_sha256': digest_file(source), 'reviewed_corrections': corrections,
                      'image_actions': image_decisions,
                      'page_count': len(doc), 'layout_block_counts': dict(Counter(b['type'] for b in blocks)),
                      'suspect_header_blocks': [{'text': b.get('text'), 'page': b['_page'], 'bbox': b.get('bbox')}
                                                for b in blocks if b.get('type') == 'header' and not margin_line(b)],
                      'tables_unchanged_from_reviewed_input': TABLE.findall(revised) == TABLE.findall(normalized),
                      'display_math_unchanged_from_reviewed_input': EQUATION.findall(revised) == EQUATION.findall(normalized),
                      'limitations': ['OCR accuracy is not measured by formatting invariants.',
                                      'Font weight and mandatory-provision formatting require source-image review.',
                                      'Existing table grouping is preserved; no additional inferred cell merging.']})
        metadata = copy.deepcopy(metadata)
        if image_decisions:
            metadata['image_review'] = {'input_markdown_sha256': digest_file(source), 'actions': image_decisions}
        locations = {}
        page_paths = {}
        (stage / 'source-images').mkdir()
        # Full-page rasters are an explicit reading-gallery feature. The default
        # material package contains only resources needed by the source body.
        for index, page in enumerate(doc if edition == 'reading' else ()):
            relative = f'source-images/page-{index + 1:03}.png'
            page.get_pixmap(matrix=fitz.Matrix(_scale(page), _scale(page)), alpha=False).save(stage / relative)
            fitz.Pixmap(str(stage / relative))  # verify the written raster can be decoded
            page_paths[index + 1] = relative
            locations[relative] = [{'precision': 'page', 'page': index + 1, 'page_range': [index + 1, index + 1],
                                    'bbox': None, 'coordinate_system': None, 'evidence_ref': None,
                                    'origin': 'source_pdf_render', 'source_sha256': source_hash, 'decode_checked': True}]
        replacements, figure_audit = {}, []
        for asset in metadata.get('assets', []):
            refs = [r for r in references(normalized) if r.image and
                    local_resource(stage, r.target) == stage / asset['path']]
            locs = asset.get('locations', [])
            if not refs or len(locs) != 1 or locs[0].get('precision') != 'page_bbox':
                continue
            loc = locs[0]
            if loc.get('coordinate_system') != 'mineru_content_list_normalized_0_1000':
                continue
            number, bbox = loc['page'], loc['bbox']
            if not 1 <= number <= len(doc) or not bbox or not (0 <= bbox[0] < bbox[2] <= 1000 and 0 <= bbox[1] < bbox[3] <= 1000):
                continue
            page = doc[number - 1]
            if page.rotation:
                # Content List boxes do not declare their rotation convention.
                continue
            # Small padding prevents fine strokes at the detector boundary being clipped.
            box = fitz.Rect(bbox[0] / 1000 * page.rect.width - 3, bbox[1] / 1000 * page.rect.height - 3,
                            bbox[2] / 1000 * page.rect.width + 3, bbox[3] / 1000 * page.rect.height + 3) & page.rect
            relative = f'source-images/figure-{len(figure_audit) + 1:03}.png'
            pixmap = page.get_pixmap(matrix=fitz.Matrix(_scale(page), _scale(page)), clip=box, alpha=False)
            pixmap.save(stage / relative)
            fitz.Pixmap(str(stage / relative))
            block = next((b for b in blocks if b['_evidence'] == loc.get('evidence_ref')), {})
            captions = block.get('image_caption', [])
            locations[relative] = [{**loc, 'origin': 'source_pdf_render', 'crop_padding_points': 3,
                                    'source_sha256': source_hash, 'decode_checked': True,
                                    'figure_captions': captions, 'original_asset_sha256': asset['sha256']}]
            for ref in refs:
                replacements[ref.target] = relative
            figure_audit.append({'original': asset['path'], 'page': number, 'bbox': bbox,
                                 'width': pixmap.width, 'height': pixmap.height, 'captions': captions,
                                 'original_sha256': asset['sha256']})
        # Match table/equation content exactly modulo whitespace; consume identical occurrences in order.
        queues = {kind: defaultdict(deque) for kind in ['table', 'equation']}
        heading_pages = defaultdict(deque)
        last_table_pages = None
        continuations = []
        for block in blocks:
            if block['_page']:
                if block['type'] in queues:
                    key = block.get('table_body' if block['type'] == 'table' else 'text', '')
                    if key:
                        for edit in corrections:
                            key = key.replace(edit['before'], edit['after'])
                        pages = [block['_page']]
                        queues[block['type']][compact(key)].append(pages)
                        if block['type'] == 'table':
                            last_table_pages = pages
                    elif (block['type'] == 'table' and last_table_pages
                          and last_table_pages[-1] <= block['_page'] <= last_table_pages[-1] + 1):
                        if block['_page'] not in last_table_pages:
                            last_table_pages.append(block['_page'])
                            continuations.append({'first_page': last_table_pages[0], 'adjacent_region_page': block['_page'],
                                                  'basis': 'adjacent empty Content List table region; source verification link only'})
                if block['type'] == 'text':
                    heading_pages[compact(block.get('text', ''))].append(block['_page'])
        # Explicitly reviewed replacements may restore a missed heading or repair a formula.
        for edit in corrections:
            for equation in EQUATION.findall(edit['after']):
                if not queues['equation'].get(compact(equation)):
                    queues['equation'][compact(equation)].append([edit['page']])
            for heading in re.findall(r'^#{1,6} (.+)$', edit['after'], re.M):
                if not heading_pages.get(compact(heading)):
                    heading_pages[compact(heading)].append(edit['page'])
        matched = Counter()
        table_decisions = []
        def page_link(number):
            target = f'#source-page-{number}' if edition == 'reading' else page_paths[number]
            return f'[第 {number} 页]({target})'
        def verified(match, kind):
            value = match.group(0)
            pages = queues[kind].get(compact(value))
            numbers = pages.popleft() if pages else []
            if kind == 'table':
                value, decision = convert_table(value, mode=table_format,
                                                header_confirmed=table_hash(value) in confirmed_headers)
                table_decisions.append({**decision, 'index': len(table_decisions) + 1, 'pages': numbers})
            if not numbers:
                return value
            matched[kind] += 1
            if edition == 'source':
                return value
            label = '表格' if kind == 'table' else '公式'
            links = '、'.join(page_link(n) for n in numbers)
            adjacent = '（含邻近续表区域）' if len(numbers) > 1 else ''
            return value + f'\n\n核对{label}原页{adjacent}：PDF {links}'
        normalized = TABLE.sub(lambda m: verified(m, 'table'), normalized)
        normalized = EQUATION.sub(lambda m: verified(m, 'equation'), normalized)
        rendered = rewrite_references(normalized, replacements)
        if native and edition == 'reading':
            rendered = re.sub(r'^<!-- PDF source page (\d+) -->$',
                              lambda m: '原文：' + page_link(int(m[1])), rendered, flags=re.M)
        labels = {path: '、'.join(locs[0].get('figure_captions', [])) or f'PDF第{locs[0]["page"]}页图像区域（图题待核实）'
                  for path, locs in locations.items() if locs[0].get('bbox')}
        rendered = re.sub(r'!\[\]\(([^)\n]+)\)',
                          lambda m: '![' + labels[m.group(1)].replace('[', '［').replace(']', '］') + '](' + m.group(1) + ')'
                          if m.group(1) in labels else m.group(0), rendered)
        # Keep the OCR table of contents, but collapse it below the navigable reading contents.
        toc_pattern = r'## (?:目次|目录)\n(.*?)\n(?=## 前言)'
        toc = re.search(toc_pattern, rendered, re.S)
        if not native and toc and len(re.findall(r'……|\.{3,}', toc.group(1))) >= 3:
            audit['original_toc_archived'] = toc.group(0)
            rendered = re.sub(toc_pattern, lambda m: '' if edition == 'source' else
                              '<details>\n<summary>原书目录（OCR）</summary>\n' + m.group(1) + '\n</details>\n\n',
                              rendered, count=1, flags=re.S)
        navigation, headings = [], []
        locator_index = LocatorIndex(source_hash)
        miscellaneous = Counter()
        def add_anchor(match):
            line = match.group(0)
            marks = re.match(r'^(#{1,6}) ', line)
            text = plain(line)
            if re.search(r'……|\.{3,}', text):
                return line  # printed table of contents, not a second clause namespace
            if not marks and not re.match(r'^' + NUMBER + r'\s', text):
                return line
            pages = heading_pages.get(compact(text))
            if not pages:
                number_only = re.match(r'^(' + NUMBER + r')\s', text)
                pages = heading_pages.get(compact(number_only.group(1))) if number_only else None
            page = pages.popleft() if pages else None
            anchor = locator_index.mark(text, page)
            if anchor is None and not marks:
                return line
            if anchor is None:
                key = 'heading-' + hashlib.sha256(text.encode()).hexdigest()[:12]
                miscellaneous[key] += 1
                anchor = key + ('-' + str(miscellaneous[key]) if miscellaneous[key] > 1 else '')
            level = len(marks.group(1)) if marks else None
            if marks:
                headings.append({'title': text, 'level': level, 'page': page, 'anchor': anchor})
            if level == 2:
                navigation.append(f'- [{text}](#{anchor})')
            location = '\n\n原文：' + page_link(page) if page and edition == 'reading' else ''
            return f'<a id="{anchor}"></a>\n\n{line}{location}'
        rendered, protected = protect_blocks(rendered)
        rendered = re.sub(r'^(?:#{1,6} .+|' + NUMBER + r'\s+[^\n]+)$', add_anchor, rendered, flags=re.M)
        rendered = restore_blocks(rendered, protected)
        document_title = title or Path(metadata.get('source_name', source.stem)).stem
        intro = (f'# {document_title}\n\n'
                 '> 阅读整理版：基于原文提取，章节、表格和图片可回看原页。'
                 '数值、公式和粗体含义请结合原页核对。\n\n'
                 '## 阅读导航\n\n' + '\n'.join(navigation) +
                 '\n- [逐页原文影像](#source-pages)\n\n---\n\n')
        gallery = ['\n\n---\n\n<a id="source-pages"></a>\n\n## 逐页原文影像\n',
                   '页码采用 PDF 文件页序；原书印刷页码可在图中查看。展开对应页面即可核对。\n']
        for number, relative in page_paths.items():
            gallery.append(f'<a id="source-page-{number}"></a>\n\n<details>\n'
                           f'<summary>PDF 第 {number} 页</summary>\n\n'
                           f'![原文 PDF 第 {number} 页]({relative})\n\n</details>\n')
        final_text = (intro + rendered + '\n'.join(gallery) if edition == 'reading' else
                      f'# {document_title}\n\n' + rendered)
        audit.update({'heading_levels': dict(Counter(h['level'] for h in headings)), 'headings': headings,
                      'adjacent_table_region_links': continuations,
                      'source_figure_crops': figure_audit, 'source_page_images': len(page_paths),
                      'clause_locators': locator_index.items, 'locator_issues': locator_index.issues,
                      'table_decisions': table_decisions, 'table_header_reviews': header_reviews,
                      'table_source_matches': matched['table'], 'display_math_source_matches': matched['equation'],
                      'table_source_links': matched['table'] if edition == 'reading' else 0,
                      'display_math_source_links': matched['equation'] if edition == 'reading' else 0,
                      'table_fragments': len(TABLE.findall(original)), 'display_math_blocks': len(EQUATION.findall(original)),
                      'tables_unchanged_from_original': TABLE.findall(original) == TABLE.findall(final_text),
                      'display_math_unchanged_from_original': EQUATION.findall(original) == EQUATION.findall(final_text),
                      'final_tables_match_reviewed_input': TABLE.findall(revised) == TABLE.findall(final_text),
                      'final_display_math_matches_reviewed_input': EQUATION.findall(revised) == EQUATION.findall(final_text)})
        # A table must be either byte-preserved HTML or a checked cell-for-cell conversion.
        preserved = [value for value, decision in zip(TABLE.findall(revised), table_decisions)
                     if decision['format'] == 'html']
        if TABLE.findall(final_text) != preserved or not audit['final_display_math_matches_reviewed_input']:
            raise MinerUOCRError('Unrecorded table or display-math changes in delivery')
        audit['table_content_verified'] = all(d['format'] == 'html' or d.get('cells_preserved') for d in table_decisions)
        metadata['postprocess'] = {'profile': profile, 'edition': edition, 'table_format': table_format,
                                  'source_id': source_id or Path(metadata.get('source_name', source.stem)).stem,
                                  'created_at': datetime.now(timezone.utc).isoformat(), 'target_rules': rules}
        snapshot = stage / 'original-input.zip'
        with zipfile.ZipFile(snapshot, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(pdf, 'input/' + pdf.name)
            archive.write(source, 'full.md')
            original_manifest = manifest_path(source)
            if not original_manifest.exists() and source.name == 'full.md':
                original_manifest = source.parent / 'manifest.json'
            archive.write(original_manifest, 'manifest.json')
            originals = {local_resource(source.parent, ref.target) for ref in references(original)}
            originals.update(local_resource(source.parent, entry['path']) for entry in metadata.get('evidence_files', []))
            for file in sorted(f for f in originals if f is not None):
                archive.write(file, file.relative_to(source.parent).as_posix())
        metadata.setdefault('evidence_files', []).append({'path': snapshot.name, 'sha256': digest_file(snapshot),
                                                         'role': 'original_input_bundle'})
        audit_file = stage / 'evidence/readability-review.json'
        audit_file.parent.mkdir(parents=True, exist_ok=True)
        audit_file.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
        metadata.setdefault('evidence_files', []).append({'path': 'evidence/readability-review.json',
                                                         'sha256': digest_file(audit_file), 'role': 'readability_audit'})
        metadata['asset_locations'] = locations
        metadata['reading_edition'] = {'processor': 'mineru_ocr.readable', 'version': '4.0',
                                      'input_markdown_sha256': digest_file(source),
                                      'reviewed_correction_count': len(corrections)}
        staged_md = stage / 'reading.md'
        staged_md.write_text(final_text, encoding='utf-8', newline='\n')
        manifest_path(staged_md).write_text(json.dumps(build_manifest(staged_md, metadata), ensure_ascii=False, indent=2), encoding='utf-8')
        suffix = '（阅读整理版）' if edition == 'reading' else '（源材料）'
        result = publish_output(staged_md, out, name=name or document_title + suffix, work_dir=root)
        result['review'] = {k: v for k, v in audit.items() if k not in {
            'headings', 'source_figure_crops', 'removed_running_lines', 'joined_term_headings',
            'clause_locators', 'original_toc_archived'}}
        result['review']['clause_locator_count'] = len(locator_index.items)
        result['review']['converted_table_count'] = sum(d['format'] == 'markdown' for d in table_decisions)
        result['review']['retained_html_table_count'] = sum(d['format'] == 'html' for d in table_decisions)
        result['review']['removed_running_line_count'] = len(audit['removed_running_lines'])
        result['review']['joined_term_heading_count'] = len(audit['joined_term_headings'])
        result['review']['source_figure_crop_count'] = len(figure_audit)
        return result
