import json
from pathlib import Path

import pytest

from mineru_ocr.enhancer import enhance_output
from mineru_ocr.merge import merge_job
from mineru_ocr.provenance import build_manifest
from mineru_ocr.publish import publish_output, validate_output
from mineru_ocr.references import local_resource, references, rewrite_references
from test_enhancer import FakeEnhancementClient
from test_merge import make_job


REPEATED_IMAGE = (
    '<!-- MinerU source pages 1-200 -->\n'
    '![First][figure]\n'
    '<!-- MinerU source pages 201-300 -->\n'
    '![Second][figure]\n'
    '\n'
    '[figure]: image.png "Shared figure"\n'
)


def test_reference_label_retains_each_occurrence_and_its_kind():
    markdown = '[Download][f]\n![View][f]\n![f][]\n[f]: image.png\n'
    refs = references(markdown)
    assert [(ref.line, ref.image, ref.target) for ref in refs] == [
        (1, False, 'image.png'), (2, True, 'image.png'), (3, True, 'image.png'),
    ]


@pytest.mark.parametrize('target', ['x.png', 'assets/a-much-longer-resource-name.png'])
def test_repeated_reference_definition_is_rewritten_only_once(target):
    assert rewrite_references(REPEATED_IMAGE, {'image.png': target}) == (
        '<!-- MinerU source pages 1-200 -->\n'
        '![First][figure]\n'
        '<!-- MinerU source pages 201-300 -->\n'
        '![Second][figure]\n'
        '\n'
        f'[figure]: {target} "Shared figure"\n'
    )


@pytest.mark.parametrize('second_use', ['![Second][figure]', '![figure][]', '![figure]'])
def test_repeated_reference_image_keeps_all_source_ranges(tmp_path, second_use):
    (tmp_path / 'image.png').write_bytes(b'image')
    markdown = tmp_path / 'source.md'
    markdown.write_text(REPEATED_IMAGE.replace('![Second][figure]', second_use), encoding='utf-8')
    asset = build_manifest(markdown)['assets'][0]
    assert [item['line'] for item in asset['references']] == [2, 4]
    assert [item['page_range'] for item in asset['locations']] == [[1, 200], [201, 300]]


def test_link_before_image_does_not_hide_an_extensionless_image(tmp_path):
    (tmp_path / 'figure').write_bytes(b'image')
    markdown = tmp_path / 'source.md'
    markdown.write_text('[Download][f]\n![View][f]\n[f]: figure\n', encoding='utf-8')
    assert build_manifest(markdown)['assets'][0]['kind'] == 'image'


@pytest.mark.parametrize('second_use', ['![Second][figure]', '![figure][]', '![figure]'])
def test_repeated_reference_locations_survive_publish_and_enhance(tmp_path, second_use):
    (tmp_path / 'image.png').write_bytes(b'image')
    markdown = tmp_path / 'source.md'
    original = REPEATED_IMAGE.replace('![Second][figure]', second_use)
    markdown.write_text(original, encoding='utf-8')
    published = publish_output(markdown, tmp_path / 'out')
    assert validate_output(published['markdown'])['valid']
    result = enhance_output(published['markdown'], client=FakeEnhancementClient())
    records = [json.loads(line) for line in Path(result['ai_jsonl']).read_text(encoding='utf-8').splitlines()]
    image = next(record for record in records if record['type'] == 'image')
    assert [item['line'] for item in image['metadata']['source_references']] == [2, 4]
    assert [item['page_range'] for item in image['source_locations']] == [[1, 200], [201, 300]]
    assert markdown.read_text(encoding='utf-8') == original
    text_chunks = [record for record in records if record['type'] == 'text']
    assert any(image['asset_id'] in record['asset_ids'] for record in text_chunks
               if record['page_range'] == [201, 300])


@pytest.mark.parametrize('uses', ['![Figure][f]\n[Download][f]', '![f][]\n[f][]', '![f]\n[f]'])
def test_merge_keeps_same_label_in_different_parts_independent(tmp_path, uses):
    job = make_job(tmp_path)
    source = uses + '\n[f]: images/same.png "Original [f] title"\n\n`![Example][f]`\n[f](https://example.invalid/)\n'
    for part in job.parts:
        Path(part.full_md).write_text(source, encoding='utf-8')
    output = merge_job(job)
    merged = (output / 'full.md').read_text(encoding='utf-8')
    assert [resource.read_bytes() for ref in references(merged)
            if (resource := local_resource(output, ref.target)) is not None] == [
        b'image-1', b'image-1', b'image-2', b'image-2',
    ]
    assets = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))['assets']
    assert [asset['locations'][0]['page_range'] for asset in assets] == [[1, 200], [201, 201]]
    assert merged.count('"Original [f] title"') == 2
    assert merged.count('`![Example][f]`') == 2
    assert merged.count('[f](https://example.invalid/)') == 2
    assert all(Path(part.full_md).read_text(encoding='utf-8') == source for part in job.parts)
