"""One local backend, with immutable page evidence and conservative quality gates."""
from __future__ import annotations

from collections import Counter
from contextlib import redirect_stdout
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import quote, unquote

from .environment import LOCAL_VERSION, require_local, require_pdf
from .errors import MinerUOCRError
from .preflight import preflight_pdf
from .provenance import build_manifest, digest_file
from .references import references, rewrite_references

TABLE = re.compile(r'<table\b.*?</table>', re.S | re.I)
EQUATION = re.compile(r'\$\$.*?\$\$', re.S)


class NativeQualityError(MinerUOCRError):
    def __init__(self, report: dict, directory: Path):
        self.report, self.directory = report, directory
        super().__init__(f'Local PDF quality checks failed; inspect {directory / "evidence/quality.json"}')


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def visible_text(markdown: str) -> str:
    value = re.sub(r'!\[[^\]]*\]\([^\n]*?\)', '', markdown)
    value = re.sub(r'\[([^\]]*)\]\([^\n]*?\)', r'\1', value)
    parser = _Text()
    parser.feed(value)
    return unicodedata.normalize('NFKC', html.unescape(' '.join(parser.parts)))


def _characters(text: str) -> Counter:
    return Counter(c for c in unicodedata.normalize('NFKC', text) if c.isalnum())


def _numbers(text: str) -> Counter:
    # Numeric tokens retain signs and decimal separators; markup and URL digits cannot mask losses.
    text = text.replace('\u2212', '-')
    return Counter(re.findall(r'(?<![\d.])[+-]?\d+(?:[.,]\d+)*(?:[eE][+-]?\d+)?', text))


class _Cells(_Text):
    def __init__(self):
        super().__init__()
        self.cells, self.current = [], None
        self.grid, self.row, self.column, self.anchor = {}, -1, 0, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row += 1
            self.column = 0
        elif tag in {'td', 'th'}:
            attributes = dict(attrs)
            rowspan, colspan = int(attributes.get('rowspan', 1)), int(attributes.get('colspan', 1))
            if self.row < 0 or not 1 <= rowspan <= 1000 or not 1 <= colspan <= 1000:
                raise ValueError('Invalid table span')
            while (self.row, self.column) in self.grid:
                self.column += 1
            self.anchor = (self.row, self.column)
            for row in range(self.row, self.row + rowspan):
                for col in range(self.column, self.column + colspan):
                    if (row, col) in self.grid:
                        raise ValueError('Overlapping table span')
                    self.grid[row, col] = None
            self.current = []
        elif tag == 'br' and self.current is not None:
            self.current.append(' ')

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag in {'td', 'th'} and self.current is not None:
            value = ''.join(''.join(self.current).split())
            self.cells.append(value)
            self.grid[self.anchor] = value
            self.current = None

    def matrix(self):
        if not self.grid:
            return []
        height = max(r for r, _ in self.grid) + 1
        width = max(c for _, c in self.grid) + 1
        return [[self.grid.get((r, c), '') for c in range(width)] for r in range(height)]


def check_page(page, markdown: str) -> dict:
    # Sorted text rejoins same-line font fragments (e.g. "0.\n01") by their
    # physical positions, without guessing across separate lines or cells.
    source, extracted = page.get_text(sort=True), visible_text(markdown)
    expected, actual = _characters(source), _characters(extracted)
    retained = sum((expected & actual).values()) / max(1, sum(expected.values()))
    missing_numbers = _numbers(unicodedata.normalize('NFKC', source)) - _numbers(extracted)
    added_numbers = _numbers(extracted) - _numbers(unicodedata.normalize('NFKC', source))
    # Do not validate the layout model against its own inferred grids: a merged
    # cell can be flattened identically in both calls. Check source ruling lines.
    original_tables = page.find_tables(use_layout=False).tables
    extracted_tables = TABLE.findall(markdown)
    table_cells_match = len(original_tables) == len(extracted_tables)
    for original, converted in zip(original_tables, extracted_tables):
        parser = _Cells()
        try:
            parser.feed(converted)
        except (ValueError, TypeError):
            table_cells_match = False
            continue
        before = [[None if cell is None else ''.join(cell.split()) for cell in row] for row in original.extract()]
        if before != parser.matrix():
            table_cells_match = False
    issues = []
    if expected and retained < .995:
        issues.append('text_content_loss')
    if missing_numbers:
        issues.append('numeric_token_loss')
    if added_numbers:
        issues.append('numeric_token_addition')
    important = set('≤≥<>±≠=×÷%‰°')
    expected_symbols = Counter(c for c in unicodedata.normalize('NFKC', source) if c in important)
    actual_symbols = Counter(c for c in extracted if c in important)
    if expected_symbols != actual_symbols:
        issues.append('technical_symbol_change')
    if any(c == '\ufffd' or unicodedata.category(c) in {'Co', 'Cs'} for c in extracted):
        issues.append('unreliable_extracted_characters')
    suspect_scripts = []
    for match in re.finditer(r'<(sup|sub)\b[^>]*>(.*?)</\1>', markdown, re.S | re.I):
        value = visible_text(match[2]).strip()
        if len(re.findall(r'[\u4e00-\u9fff]', value)) >= 2 or len(value) > 12:
            suspect_scripts.append(value[:120])
    if suspect_scripts:
        issues.append('script_formatting_needs_review')
    if not table_cells_match:
        issues.append('table_cells_or_count_mismatch')
    return {'page': page.number + 1, 'passed': not issues, 'issues': issues,
            'character_retention': round(retained, 6), 'missing_numbers': dict(missing_numbers),
            'added_numbers': dict(added_numbers),
            'technical_symbols_preserved': expected_symbols == actual_symbols,
            'suspect_script_spans': suspect_scripts,
            'source_tables': len(original_tables), 'extracted_tables': len(extracted_tables),
            'table_cells_match': table_cells_match}


def extract_native(pdf: str | Path, directory: Path, *, preflight: dict | None = None) -> dict:
    pdf = Path(pdf).resolve()
    inspection = preflight or preflight_pdf(pdf)
    if inspection['source_sha256'] != digest_file(pdf):
        raise MinerUOCRError('PDF changed after preflight')
    if inspection['recommended_engine'] != 'local':
        raise MinerUOCRError('PDF is not eligible for loss-checked local extraction; inspect preflight or use --engine cloud')
    backend = require_local()
    fitz = require_pdf()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'evidence').mkdir()
    def evidence(name, payload):
        file = directory / 'evidence' / name
        file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'path': 'evidence/' + name, 'sha256': digest_file(file)}
    files = [{**evidence('preflight.json', inspection), 'role': 'pdf_preflight'}]
    try:
        with redirect_stdout(sys.stderr):
            chunks = backend.to_markdown(str(pdf), page_chunks=True, use_ocr=False, force_ocr=False,
                                         write_images=True, embed_images=False, image_format='png',
                                         image_path=str(directory / 'images'), table_output='html',
                                         header=True, footer=True, show_progress=False)
    except Exception as exc:
        evidence('runtime-error.json', {'error': str(exc), 'type': type(exc).__name__})
        raise MinerUOCRError(f'Local PDF runtime failed; no cloud fallback. Evidence: {directory}: {exc}') from exc
    files.append({**evidence('pymupdf4llm-pages.json', chunks), 'role': 'native_page_evidence'})
    if (not isinstance(chunks, list) or len(chunks) != inspection['page_count']
            or any(not isinstance(c, dict) or not isinstance(c.get('text'), str)
                   or not isinstance(c.get('metadata'), dict) for c in chunks)
            or [c.get('metadata', {}).get('page_number') for c in chunks] != list(range(1, len(chunks) + 1))):
        raise MinerUOCRError('Native backend did not return every physical PDF page in order')
    texts, blocks, locations, quality = [], [], {}, []
    with fitz.open(pdf) as doc:
        for number, chunk in enumerate(chunks, 1):
            text = chunk['text']
            replacements = {}
            for ref in references(text):
                if not ref.image:
                    continue
                image = Path(unquote(ref.target)).resolve()
                if directory / 'images' not in image.parents or not image.is_file():
                    raise MinerUOCRError('Local backend returned an image outside its output directory')
                relative = image.relative_to(directory).as_posix()
                replacements[ref.target] = quote(relative, safe='/')
                fitz.Pixmap(str(image))
                locations.setdefault(relative, []).append({
                    'precision': 'page', 'page': number, 'page_range': [number, number],
                    'bbox': None, 'coordinate_system': None, 'origin': 'pymupdf4llm',
                    'decode_checked': True, 'evidence_ref': f'evidence/pymupdf4llm-pages.json#/{number - 1}'})
            text = rewrite_references(text, replacements)
            quality.append(check_page(doc[number - 1], text))
            # Source markers are internal evidence, converted to ordinary page links in readable.
            texts.append(f'<!-- PDF source page {number} -->\n\n' + text.strip())
            blocks.append({'type': 'page', 'page': number})
            for table in TABLE.findall(text):
                blocks.append({'type': 'table', 'page': number, 'table_body': table})
            for equation in EQUATION.findall(text):
                blocks.append({'type': 'equation', 'page': number, 'text': equation})
            for line in text.splitlines():
                if line.strip() and not line.lstrip().startswith(('<', '!', '|')):
                    blocks.append({'type': 'text', 'page': number, 'text': re.sub(r'^#{1,6}\s+', '', line.strip())})
    report = {'passed': all(p['passed'] for p in quality), 'pages': quality,
              'limitations': ['Checks compare extraction results; they do not certify reading order, table-detector accuracy or semantic correctness.']}
    files += [{**evidence('quality.json', report), 'role': 'native_quality'},
              {**evidence('layout.json', blocks), 'role': 'normalized_layout',
               'adapter': 'pymupdf4llm_pages_v1', 'adapter_status': 'adapted'}]
    markdown = directory / 'full.md'
    markdown.write_text('\n\n'.join(texts) + '\n', encoding='utf-8')
    metadata = {'source_name': pdf.name, 'source_sha256': inspection['source_sha256'],
                'page_count': inspection['page_count'], 'engine': 'pymupdf4llm',
                'engine_version': LOCAL_VERSION, 'ocr_used': False,
                'native_quality_passed': report['passed'], 'evidence_files': files, 'asset_locations': locations}
    manifest = build_manifest(markdown, metadata)
    (directory / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    if digest_file(pdf) != inspection['source_sha256']:
        raise MinerUOCRError('PDF changed during local extraction')
    if not report['passed']:
        raise NativeQualityError(report, directory)
    return {'state': 'done', 'engine': 'local', 'result_dir': str(directory),
            'preflight': inspection, 'quality': report}
