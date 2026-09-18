import json
from pathlib import Path

import pytest

from mineru_ocr import cli
from mineru_ocr.errors import MinerUOCRError


def make_bundle(tmp_path):
    bundle = tmp_path / "input.pdf.mineru"
    (bundle / "assets/part-0001").mkdir(parents=True)
    (bundle / "assets/part-0001/图 (1).png").write_bytes(b"first-image")
    (bundle / "full.md").write_text(
        '# 标题\n![图](<assets/part-0001/图 (1).png>)\n<img src="assets/part-0001/图%20%281%29.png">\n', encoding="utf-8")
    (bundle / "manifest.json").write_text(json.dumps({"source_name": "技术标准.v1.pdf", "source_sha256": "a" * 64}), encoding="utf-8")
    return bundle


def test_publish_flattens_links_and_preserves_document_identity(tmp_path):
    from mineru_ocr.publish import publish_output, validate_output
    source = make_bundle(tmp_path)
    original = (source / "full.md").read_bytes()
    out = tmp_path / "out"
    first = publish_output(source, out)
    second = publish_output(source, out)
    assert Path(first["markdown"]).name == "技术标准.v1.md"
    assert Path(second["markdown"]).name == "技术标准.v1 (1).md"
    assert (source / "full.md").read_bytes() == original
    a = json.loads(Path(first["manifest"]).read_text(encoding="utf-8"))
    b = json.loads(Path(second["manifest"]).read_text(encoding="utf-8"))
    assert a["doc_id"] == b["doc_id"]
    assert a["assets"][0]["asset_id"] == b["assets"][0]["asset_id"]
    assert len(a["assets"]) == 1
    assert len(list((out / "assets").iterdir())) == 1
    assert "part-0001" not in Path(first["markdown"]).read_text(encoding="utf-8")
    assert validate_output(first["markdown"])["valid"]


def test_publish_rejects_missing_resource_without_final_output(tmp_path):
    from mineru_ocr.publish import publish_output
    source = make_bundle(tmp_path)
    (source / "full.md").write_text("![missing](assets/missing.png)", encoding="utf-8")
    with pytest.raises(MinerUOCRError, match="missing|Missing"):
        publish_output(source, tmp_path / "out")
    assert not list((tmp_path / "out").glob("*.md"))


def test_publish_rejects_paths_outside_source_root(tmp_path):
    from mineru_ocr.publish import publish_output
    source = make_bundle(tmp_path)
    (tmp_path / "private.png").write_bytes(b"not-this-document")
    (source / "full.md").write_text("![bad](../private.png)", encoding="utf-8")
    with pytest.raises(MinerUOCRError, match="outside|escapes"):
        publish_output(source, tmp_path / "out")


def test_publish_supports_reference_images_and_retains_svg(tmp_path):
    from mineru_ocr.publish import publish_output, validate_output
    source = make_bundle(tmp_path)
    (source / "assets/native.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    (source / "full.md").write_text('![Vector][v]\n\n[v]: assets/native.svg\n', encoding="utf-8")
    result = publish_output(source, tmp_path / "out")
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["assets"][0]["media_type"] == "image/svg+xml"
    assert validate_output(result["markdown"])["valid"]


def test_validate_detects_changed_asset_bytes(tmp_path):
    from mineru_ocr.publish import publish_output, validate_output
    result = publish_output(make_bundle(tmp_path), tmp_path / "out")
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    asset = Path(result["markdown"]).parent / manifest["assets"][0]["path"]
    asset.write_bytes(b"corruption")
    with pytest.raises(MinerUOCRError, match="hash|Hash"):
        validate_output(result["markdown"])


def test_cli_publish_is_an_offline_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    bundle = make_bundle(tmp_path)
    assert cli.main(["publish", str(bundle), "--output-dir", str(tmp_path / "out")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert Path(result["markdown"]).is_file()


def test_same_image_bytes_have_one_asset_record_after_publish(tmp_path):
    from mineru_ocr.publish import publish_output
    source = make_bundle(tmp_path)
    (source / "assets/copy.png").write_bytes(b"first-image")
    with (source / "full.md").open('a', encoding='utf-8') as file:
        file.write('\n![copy](assets/copy.png)')
    result = publish_output(source, tmp_path / 'out')
    manifest = json.loads(Path(result['manifest']).read_text(encoding='utf-8'))
    assert len(manifest['assets']) == 1
    assert len(manifest['assets'][0]['references']) == 3


def test_resource_copy_failure_can_be_retried(tmp_path, monkeypatch):
    import shutil
    from mineru_ocr.publish import publish_output
    source = make_bundle(tmp_path)
    original = shutil.copyfileobj
    def broken_copy(src, dst):
        dst.write(b'partial')
        raise OSError('simulated disk failure')
    monkeypatch.setattr(shutil, 'copyfileobj', broken_copy)
    with pytest.raises(OSError, match='disk failure'):
        publish_output(source, tmp_path / 'out')
    monkeypatch.setattr(shutil, 'copyfileobj', original)
    assert publish_output(source, tmp_path / 'out')['published']


def test_standalone_markdown_version_survives_publication(tmp_path):
    from mineru_ocr.provenance import build_manifest
    from mineru_ocr.publish import publish_output
    (tmp_path / 'image.png').write_bytes(b'image')
    md = tmp_path / 'standalone.md'
    md.write_text('![a](image.png)', encoding='utf-8')
    before = build_manifest(md)
    result = publish_output(md, tmp_path / 'out')
    after = build_manifest(Path(result['markdown']))
    assert after['source_version'] == before['source_version']
    assert after['doc_id'] == before['doc_id']


def test_offline_publish_does_not_load_environment_credentials(tmp_path, monkeypatch):
    def forbidden():
        raise AssertionError('Local publication does not need dotenv')
    monkeypatch.setattr(cli, 'load_dotenv', forbidden)
    assert cli.main(['publish', str(make_bundle(tmp_path)), '--output-dir', str(tmp_path / 'out')]) == 0


def test_process_publishes_before_enhancing_final_references(tmp_path, monkeypatch, capsys):
    from mineru_ocr import enhancer
    from test_enhancer import FakeEnhancementClient
    source = make_bundle(tmp_path)
    monkeypatch.setattr(cli, 'load_dotenv', lambda: None)
    monkeypatch.setattr(cli, 'process_files', lambda *args: [{'state': 'done', 'result_dir': str(source)}])
    enhance = enhancer.enhance_output
    monkeypatch.setattr(enhancer, 'enhance_output', lambda path: enhance(path, client=FakeEnhancementClient()))
    assert cli.main(['process', 'unused.pdf', '--output-dir', str(tmp_path / 'out'), '--enhance']) == 0
    job = json.loads(capsys.readouterr().out)[0]
    ai = Path(job['ai_enhancement']['ai_jsonl'])
    assert ai.parent == tmp_path / 'out'
    rows = [json.loads(line) for line in ai.read_text(encoding='utf-8').splitlines()]
    image = next(row for row in rows if row['type'] == 'image')
    assert (ai.parent / image['source_ref']).is_file()
    assert 'part-0001' not in image['source_ref']
