"""Shared Markdown/HTML resource references, used by merge, publication and image review."""
from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .errors import MinerUOCRError


INLINE = re.compile(r'(?P<image>!?)\[[^\]\n]*\]\(\s*(?P<target><[^>\n]+>|(?:[^\s()]|\([^()]*\))+)(?:\s+["\'][^\n]*?["\'])?\s*\)')
DEFINITION = re.compile(r'^ {0,3}\[(?P<key>[^\]\n]+)\]:\s*(?P<target><[^>\n]+>|\S+)', re.M)
REFERENCE = re.compile(r'(?P<image>!?)\[(?P<label>[^\]\n]+)\]\[(?P<key>[^\]\n]*)\]')
SHORTCUT = re.compile(r'(?P<image>!?)\[(?P<label>[^\]\n]+)\]')
HTML = re.compile(r'<(?P<tag>img|a|source)\b[^>]*>', re.I)
ATTRIBUTE = re.compile(r'\b(?:src|href)\s*=\s*(?:"(?P<double>[^"]*)"|\x27(?P<single>[^\x27]*)\x27)', re.I)
PAGE_RANGE = re.compile(r'<!--\s*MinerU source pages (\d+)-(\d+)\s*-->')


@dataclass(frozen=True)
class Reference:
    start: int
    end: int
    target: str
    image: bool
    line: int


def _without_code(text: str) -> str:
    # Keep offsets and newlines so replacements and source lines remain valid.
    return re.sub(r'(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?^\s*\1\s*$|`[^`\n]+`',
                  lambda m: ''.join('\n' if c == '\n' else ' ' for c in m[0]), text)


def _reference_uses(visible: str) -> list[re.Match]:
    """Locate full, collapsed and shortcut uses, excluding definitions and code."""
    uses = list(REFERENCE.finditer(visible))
    definitions = list(DEFINITION.finditer(visible))
    labels = {match['key'].casefold() for match in definitions}
    occupied = [match.span() for pattern in (INLINE, HTML) for match in pattern.finditer(visible)]
    occupied.extend(match.span() for match in uses)
    for match in definitions:
        line_end = visible.find('\n', match.end())
        occupied.append((match.start(), line_end if line_end >= 0 else len(visible)))
    for match in SHORTCUT.finditer(visible):
        if match['label'].casefold() in labels and not any(
            start <= match.start() < end for start, end in occupied
        ):
            uses.append(match)
    return sorted(uses, key=lambda match: match.start())


def references(markdown: str) -> list[Reference]:
    visible = _without_code(markdown)
    refs: list[Reference] = []
    def add(start, end, target, image, line_offset=None):
        refs.append(Reference(start, end, unescape(target.strip('<>')), image,
                              markdown.count('\n', 0, start if line_offset is None else line_offset) + 1))
    matched_images = set()
    for match in INLINE.finditer(visible):
        add(*match.span('target'), match['target'], bool(match['image']))
        if match['image']:
            matched_images.add(match.start())
    for match in re.finditer(r'!\[[^\]\n]*\]\(', visible):
        if match.start() not in matched_images:
            raise MinerUOCRError('Unsupported or malformed inline image reference')
    definitions = {m['key'].casefold(): m for m in DEFINITION.finditer(visible)}
    for match in _reference_uses(visible):
        key = (match.groupdict().get('key') or match['label']).casefold()
        if key not in definitions:
            if match['image']:
                raise MinerUOCRError(f'Unresolved image reference: {key}')
            continue
        definition = definitions[key]
        # Each use has its own source line, even when the editable target is shared.
        add(*definition.span('target'), definition['target'], bool(match['image']), match.start())
    for tag in HTML.finditer(visible):
        for attr in ATTRIBUTE.finditer(tag[0]):
            group = 'double' if attr['double'] is not None else 'single'
            start, end = attr.span(group)
            add(tag.start() + start, tag.start() + end, attr[group], tag['tag'].lower() != 'a')
    return sorted(refs, key=lambda item: item.start)


def expand_image_references(markdown: str) -> str:
    visible = _without_code(markdown)
    definitions = {m['key'].casefold(): m['target'] for m in DEFINITION.finditer(visible)}
    for match in reversed(_reference_uses(visible)):
        key = (match.groupdict().get('key') or match['label']).casefold()
        if match['image'] and key in definitions:
            replacement = f"![{match['label']}]({definitions[key]})"
            markdown = markdown[:match.start()] + replacement + markdown[match.end():]
    return markdown


def namespace_reference_labels(markdown: str, namespace: str) -> str:
    """Keep labels local to a part when independently extracted Markdown is joined."""
    visible = _without_code(markdown)
    definitions = list(DEFINITION.finditer(visible))
    labels = {match['key'].casefold(): namespace + match['key'] for match in definitions}
    edits = [(*match.span('key'), labels[match['key'].casefold()]) for match in definitions]
    for match in _reference_uses(visible):
        key = (match.groupdict().get('key') or match['label']).casefold()
        if key in labels:
            if 'key' in match.groupdict():
                edits.append((*match.span('key'), labels[key]))
            else:
                edits.append((match.end(), match.end(), f'[{labels[key]}]'))
    for start, end, label in sorted(edits, reverse=True):
        markdown = markdown[:start] + label + markdown[end:]
    return markdown


def local_resource(root: Path, target: str) -> Path | None:
    parsed = urlsplit(target)
    if parsed.scheme.lower() in {'http', 'https', 'mailto', 'tel', 'data'} or parsed.netloc:
        return None
    if not parsed.path:
        return None
    if parsed.scheme:
        raise MinerUOCRError(f'Unsupported local resource scheme: {parsed.scheme}')
    path = (root / unquote(parsed.path).replace('\\', '/')).resolve()
    if root.resolve() not in path.parents:
        raise MinerUOCRError('Resource reference escapes the document directory')
    if not path.is_file():
        raise MinerUOCRError(f'Referenced resource is missing: {parsed.path}')
    return path


def rewrite_references(markdown: str, replacements: dict[str, str]) -> str:
    rewritten: set[tuple[int, int]] = set()
    for ref in reversed(references(markdown)):
        span = (ref.start, ref.end)
        if ref.target in replacements and span not in rewritten:
            markdown = markdown[:ref.start] + replacements[ref.target] + markdown[ref.end:]
            rewritten.add(span)
    return markdown


def range_at(markdown: str, line: int) -> list[int] | None:
    found = None
    for current in markdown.splitlines()[:line]:
        match = PAGE_RANGE.search(current)
        if match:
            found = [int(match[1]), int(match[2])]
    return found
