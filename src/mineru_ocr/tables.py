"""Loss-aware conversion of explicitly headed, rectangular HTML tables to GFM."""
from __future__ import annotations

import hashlib
import html
from html.parser import HTMLParser
import re


def table_hash(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack = []
        self.rows = []
        self.kinds = []
        self.cell = None
        self.problem = None

    def handle_starttag(self, tag, attrs):
        allowed = {'table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th'}
        parent = self.stack[-1] if self.stack else None
        valid_parent = {'table': {None}, 'thead': {'table'}, 'tbody': {'table'}, 'tfoot': {'table'},
                        'tr': {'table', 'thead', 'tbody', 'tfoot'}, 'td': {'tr'}, 'th': {'tr'}}
        if tag not in allowed or parent not in valid_parent.get(tag, set()):
            self.problem = 'nested_or_rich_content'
        for key, value in attrs:
            if key in {'rowspan', 'colspan'} and value != '1':
                self.problem = 'merged_cells'
            elif key not in {'rowspan', 'colspan'}:
                self.problem = self.problem or 'unsupported_attributes'
        self.stack.append(tag)
        if tag == 'tr':
            self.rows.append([])
            self.kinds.append([])
        if tag in {'td', 'th'}:
            self.cell = []
            if self.kinds:
                self.kinds[-1].append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.problem = 'malformed_html'
            return
        self.stack.pop()
        if tag in {'td', 'th'} and self.cell is not None and self.rows:
            self.rows[-1].append(''.join(self.cell))
            self.cell = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
        elif data.strip():
            self.problem = self.problem or 'text_outside_cells'

    def handle_entityref(self, name):
        self.handle_data('&' + name + ';')

    def handle_charref(self, name):
        self.handle_data('&#' + name + ';')

    def handle_comment(self, data):
        self.problem = self.problem or 'html_comment'


def cell_text(value: str) -> str:
    return re.sub(r'\s+', ' ', html.unescape(value)).strip()


def encode_cell(value: str) -> str:
    value = re.sub(r'\s+', ' ', value).strip()
    # Keep LaTeX untouched. Encode plain-text Markdown punctuation so it cannot
    # become emphasis, a link, code, or a raw HTML tag in the new cell.
    parts = re.split(r'(\$[^$\n]*\$)', value)
    for index in range(0, len(parts), 2):
        parts[index] = re.sub(r'[\\`*_~\[\]<>]', lambda m: f'&#{ord(m.group(0))};', parts[index])
    return ''.join(parts).replace('|', r'\|')


def pipe_cells(line: str) -> list[str]:
    return [html.unescape(cell.strip().replace(r'\|', '|'))
            for cell in re.split(r'(?<!\\)\|', line.strip()[1:-1])]


def convert_table(value: str, *, mode: str = 'html', header_confirmed: bool = False) -> tuple[str, dict]:
    record = {'input_sha256': table_hash(value), 'format': 'html', 'reason': 'preserve_requested'}
    if mode == 'html':
        return value, record
    parser = TableParser()
    try:
        parser.feed(value)
        parser.close()
    except (ValueError, IndexError):
        parser.problem = 'malformed_html'
    reason = parser.problem
    if parser.stack:
        reason = reason or 'malformed_html'
    rows = parser.rows
    if not reason and (len(rows) < 2 or not rows[0] or any(len(row) != len(rows[0]) for row in rows)):
        reason = 'not_rectangular_or_no_body'
    if not reason and len(rows[0]) > 8:
        reason = 'wide_table'
    if not reason and any(len(cell_text(c)) > 240 for row in rows for c in row):
        reason = 'long_cells'
    if not reason and any('$' in c and (c.count('$') % 2 or '$$' in c) for row in rows for c in row):
        reason = 'complex_math'
    if not reason and any(r'\|' in c for row in rows for c in row):
        reason = 'ambiguous_pipe_escape'
    if not reason and any('th' in row for row in parser.kinds[1:]):
        reason = 'row_headers_or_multiple_header_rows'
    explicit_header = bool(parser.kinds and all(c == 'th' for c in parser.kinds[0]))
    if not reason and not (explicit_header or header_confirmed):
        reason = 'header_needs_source_review'
    if reason:
        return value, {**record, 'reason': reason}
    lines = ['| ' + ' | '.join(encode_cell(c) for c in row) + ' |' for row in rows]
    lines.insert(1, '| ' + ' | '.join('---' for _ in rows[0]) + ' |')
    restored = [pipe_cells(line) for i, line in enumerate(lines) if i != 1]
    expected = [[cell_text(c) for c in row] for row in rows]
    if restored != expected:
        return value, {**record, 'reason': 'cell_roundtrip_failed'}
    result = '\n'.join(lines)
    return result, {**record, 'format': 'markdown', 'reason': 'rectangular_verified',
                    'rows': len(rows), 'columns': len(rows[0]), 'cells_preserved': True,
                    'header_basis': 'html_th' if explicit_header else 'source_review',
                    'output_sha256': table_hash(result)}
