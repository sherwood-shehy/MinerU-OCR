import json
from pathlib import Path
import shutil
import zipfile

import pytest

from mineru_ocr import cli
from mineru_ocr.errors import MinerUOCRError
from mineru_ocr.provenance import digest_file
from mineru_ocr.publish import publish_output, validate_output
from mineru_ocr.visuals import inspect_images


def source_with_images(tmp_path, text='![logo](logo.png)\n\n正文。\n\n![图 1](figure.png)\n'):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'logo.png').write_bytes(b'logo')
    (source / 'figure.png').write_bytes(b'technical-figure')
    md = source / 'input.md'
    md.write_text(text, encoding='utf-8')
    return md


def write_review(md, lines, *, sha=None):
    review = md.parent / 'review.json'
    review.write_text(json.dumps({'input_markdown_sha256': digest_file(md), 'image_actions': [{
        'sha256': sha or digest_file(md.parent / 'logo.png'), 'action': 'drop', 'kind': 'logo',
        'independent': True, 'reason': 'Source checked: isolated publisher decoration; no document information.',
        'lines': lines}]}), encoding='utf-8')
    return review


def test_delivery_can_move_without_internal_metadata(tmp_path):
    md = source_with_images(tmp_path)
    result = publish_output(md, tmp_path / 'delivery', work_dir=tmp_path / 'private')
    assert {p.name for p in (tmp_path / 'delivery').iterdir()} == {'input.md', 'images'}
    assert validate_output(result['markdown'], work_dir=tmp_path / 'private')['validation_scope'] == 'recorded_hashes'
    shutil.copytree(tmp_path / 'delivery', tmp_path / 'relocated')
    moved = tmp_path / 'relocated/input.md'
    assert validate_output(moved)['validation_scope'] == 'references'
    next((moved.parent / 'images').iterdir()).unlink()
    with pytest.raises(MinerUOCRError, match='missing'):
        validate_output(moved)


@pytest.mark.parametrize('relative', ['delivery', 'delivery/internal', '.'])
def test_rejects_nested_work_and_delivery_before_writing(tmp_path, relative):
    md = source_with_images(tmp_path)
    with pytest.raises(MinerUOCRError, match='separate'):
        publish_output(md, tmp_path / 'delivery', work_dir=tmp_path / relative)
    assert not (tmp_path / 'delivery').exists()


def test_custom_records_detect_markdown_and_evidence_tampering(tmp_path):
    md = source_with_images(tmp_path)
    result = publish_output(md, tmp_path / 'delivery', work_dir=tmp_path / 'private')
    manifest = json.loads(Path(result['manifest']).read_text(encoding='utf-8'))
    evidence = Path(result['work_dir']) / manifest['evidence_files'][0]['path']
    evidence.write_bytes(b'tampered')
    with pytest.raises(MinerUOCRError, match='Evidence file hash'):
        validate_output(result['markdown'], work_dir=tmp_path / 'private')


def test_explicit_empty_record_store_does_not_load_default_records(tmp_path):
    result = publish_output(source_with_images(tmp_path), tmp_path / 'out')
    assert validate_output(result['markdown'], work_dir=tmp_path / 'empty')['validation_scope'] == 'references'
    Path(result['manifest']).unlink()
    with pytest.raises(MinerUOCRError, match='Incomplete internal'):
        validate_output(result['markdown'])


def test_publish_does_not_silently_ignore_text_review(tmp_path):
    md = source_with_images(tmp_path)
    review = write_review(md, [1])
    data = json.loads(review.read_text(encoding='utf-8'))
    data['replacements'] = [{'before': '正文', 'after': '改文'}]
    review.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(MinerUOCRError, match='use readable'):
        publish_output(md, tmp_path / 'out', review_file=review)


def test_review_excludes_only_selected_occurrence_preserves_original(tmp_path):
    md = source_with_images(tmp_path, '![logo](logo.png)\n![useful reproduction](logo.png)\n![图](figure.png)\n')
    raw_manifest = b'{"source_name":"original.pdf"}\n'
    (md.parent / 'input.manifest.json').write_bytes(raw_manifest)
    original = md.read_bytes()
    result = publish_output(md, tmp_path / 'out', review_file=write_review(md, [1]))
    text = Path(result['markdown']).read_text(encoding='utf-8')
    assert '![logo]' not in text and '![useful reproduction]' in text and '![图]' in text
    assert len(list((tmp_path / 'out/images').iterdir())) == 2
    assert md.read_bytes() == original
    manifest = json.loads(Path(result['manifest']).read_text(encoding='utf-8'))
    snapshot = next(e for e in manifest['evidence_files'] if e['role'] == 'original_input_bundle')
    with zipfile.ZipFile(Path(result['work_dir']) / snapshot['path']) as archive:
        assert archive.read('full.md') == original
        assert archive.read('logo.png') == b'logo'
        assert archive.read('manifest.json') == raw_manifest
    assert manifest['image_review']['actions'][0]['lines'] == [1]


@pytest.mark.parametrize('use', ['![Logo][x]', '![x][]', '![x]', '<img src="logo.png">'])
def test_standalone_reference_or_html_image_can_be_excluded(tmp_path, use):
    md = source_with_images(tmp_path, use + '\n\n[x]: logo.png\n\n![图](figure.png)\n')
    result = publish_output(md, tmp_path / 'out', review_file=write_review(md, [1]))
    text = Path(result['markdown']).read_text(encoding='utf-8')
    assert use not in text and '![图]' in text
    assert len(list((tmp_path / 'out/images').iterdir())) == 1


def test_shared_definition_keeps_download_link(tmp_path):
    md = source_with_images(tmp_path, '![Logo][x]\n[下载原图][x]\n[x]: logo.png\n')
    result = publish_output(md, tmp_path / 'out', review_file=write_review(md, [1]))
    text = Path(result['markdown']).read_text(encoding='utf-8')
    assert '[下载原图][x]' in text and '[x]: images/' in text
    assert validate_output(result['markdown'])['valid']


@pytest.mark.parametrize('text,line', [
    ('正文 ![Logo](logo.png) 不得删除。\n', 1),
    ('<table>\n<img src="logo.png">\n</table>', 2),
    ('[![Logo](logo.png)](https://example.invalid)', 1),
    ('```md\n![Logo](logo.png)\n```', 2),
])
def test_review_cannot_remove_inline_table_link_or_code(tmp_path, text, line):
    md = source_with_images(tmp_path, text)
    with pytest.raises(MinerUOCRError, match='independent|Unsupported'):
        publish_output(md, tmp_path / 'out', review_file=write_review(md, [line]))
    assert not list((tmp_path / 'out').glob('*.md'))


def test_stale_review_and_wrong_image_hash_fail_closed(tmp_path):
    md = source_with_images(tmp_path)
    review = write_review(md, [1], sha='0' * 64)
    with pytest.raises(MinerUOCRError, match='resource hash'):
        publish_output(md, tmp_path / 'out', review_file=review)
    md.write_text(md.read_text(encoding='utf-8') + '\nadditional text', encoding='utf-8')
    with pytest.raises(MinerUOCRError, match='Markdown hash'):
        publish_output(md, tmp_path / 'out', review_file=review)


def test_exact_duplicates_share_file_but_similar_images_remain(tmp_path):
    md = source_with_images(tmp_path, '![A](logo.png)\n![B](copy.jpeg)\n![C](figure.png)\n')
    (md.parent / 'copy.jpeg').write_bytes(b'logo')
    (md.parent / 'figure.png').write_bytes(b'logo-different-label')
    result = publish_output(md, tmp_path / 'out')
    manifest = json.loads(Path(result['manifest']).read_text(encoding='utf-8'))
    assert len(list((tmp_path / 'out/images').iterdir())) == 2
    assert sorted(len(a['references']) for a in manifest['assets']) == [1, 2]
    text = Path(result['markdown']).read_text(encoding='utf-8')
    assert all(f'![{label}]' in text for label in 'ABC')


def test_inspection_never_guesses_removals_or_overwrites_review(tmp_path):
    md = source_with_images(tmp_path)
    result = inspect_images(md)
    template = Path(result['review_file'])
    assert result['automatic_removals'] == 0
    assert json.loads(template.read_text())['image_actions'] == []
    template.write_text('{"user": "unfinished review"}')
    inspect_images(md)
    assert template.read_text() == '{"user": "unfinished review"}'


def test_separate_publications_share_canonical_resource_extension(tmp_path):
    md = source_with_images(tmp_path, '![A](logo.png)\n')
    first = publish_output(md, tmp_path / 'out', name='one')
    (md.parent / 'logo.jpeg').write_bytes(b'logo')
    md.write_text('![B](logo.jpeg)\n', encoding='utf-8')
    second = publish_output(md, tmp_path / 'out', name='two')
    assert len(list((tmp_path / 'out/images').iterdir())) == 1
    assert '.png)' in Path(second['markdown']).read_text(encoding='utf-8')
    assert validate_output(first['markdown'])['valid']
    assert validate_output(second['markdown'])['valid']


def test_pdf_postprocessing_applies_review_before_cropping(tmp_path):
    from mineru_ocr.readable import prepare_readable
    from test_readable import make_source
    pdf, bundle = make_source(tmp_path)
    md = bundle / 'full.md'
    (bundle / 'logo.png').write_bytes(b'logo')
    md.write_text('![logo](logo.png)\n\n' + md.read_text(encoding='utf-8'), encoding='utf-8')
    review = write_review(md, [1])
    data = json.loads(review.read_text(encoding='utf-8'))
    data['source_sha256'] = digest_file(pdf)
    review.write_text(json.dumps(data), encoding='utf-8')
    result = prepare_readable(bundle, pdf, tmp_path / 'out', review_file=review)
    assert result['review']['image_actions'][0]['lines'] == [1]
    assert '![logo]' not in Path(result['markdown']).read_text(encoding='utf-8')
    assert not any(digest_file(p) == digest_file(bundle / 'logo.png') for p in (tmp_path / 'out/images').iterdir())


@pytest.mark.parametrize('args', [['enhance', 'input.md'], ['process', 'input.pdf', '--enhance'],
                                 ['config', 'set-doubao-key'], ['publish', 'x', '--output-dir', 'y', '--image-dir', 'assets']])
def test_retired_cli_interfaces_fail_before_network(args):
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2
