import json
import zipfile
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
    assert len(list((out / "images").iterdir())) == 1
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
    assert not {"manifest", "work_dir", "processing_reports"} & result.keys()
    assert not list((tmp_path / "records").iterdir())
    assert (bundle / "full.md").is_file()


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
    def broken_copy(src, dst, *args):
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


@pytest.fixture
def completed_cloud(monkeypatch):
    from mineru_ocr import service

    class Client:
        def __init__(self, token):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def request_uploads(self, parts, options):
            return parts[0].data_id, ['upload'], None

        def upload(self, url, path):
            assert Path(path).is_file()

        def batch_status(self, batch):
            return {'data': {'extract_result': [{'data_id': batch, 'state': 'done', 'full_zip_url': 'result'}]}}

        def download(self, url, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('full.md', '![figure](images/figure.png)')
                archive.writestr('images/figure.png', b'shared-image')

    monkeypatch.setattr(service, 'MinerUClient', Client)
    monkeypatch.setattr(service, 'get_token', lambda: 'test-token')
    return Client


def test_cloud_process_publishes_flat_package_and_cleans_work(tmp_path, completed_cloud, capsys):
    from mineru_ocr.publish import validate_output
    sources = [tmp_path / 'first.docx', tmp_path / 'second.docx']
    for source in sources:
        source.write_bytes(b'input')
    output = tmp_path / 'delivery'
    assert cli.main(['process', *map(str, sources), '--engine', 'cloud', '--output-dir', str(output)]) == 0
    jobs = json.loads(capsys.readouterr().out)
    assert {path.name for path in output.iterdir()} == {'first.md', 'second.md', 'images'}
    assert len(list((output / 'images').iterdir())) == 1
    for job in jobs:
        markdown = Path(job['markdown'])
        assert '](images/' in markdown.read_text(encoding='utf-8')
        assert validate_output(markdown)['validation_scope'] == 'references'
        assert not {'manifest', 'work_dir', 'processing_reports', 'result_dir', 'output_dir'} & job.keys()
    assert not list(tmp_path.glob('*.mineru*'))
    assert not list((tmp_path / 'records').iterdir())


def test_cloud_timeout_preserves_job_and_resumes_into_task_work(tmp_path, monkeypatch, completed_cloud, capsys):
    from mineru_ocr import service
    source = tmp_path / 'input.docx'
    source.write_bytes(b'input')
    with monkeypatch.context() as context:
        def time_out(job_id, *, timeout_seconds):
            return {'job_id': job_id, 'state': 'pending', 'timed_out': True}
        context.setattr(service, 'wait_job', time_out)
        assert cli.main(['process', str(source), '--engine', 'cloud', '--output-dir', str(tmp_path / 'out')]) == 1
    pending = json.loads(capsys.readouterr().out)[0]
    task = Path(pending['work_dir'])
    assert task.is_dir()
    resumed = service.resume_job(pending['job_id'])
    raw = Path(resumed['result_dir'])
    assert raw.is_relative_to(task) and (raw / 'full.md').is_file()
    assert not (tmp_path / 'input.docx.mineru').exists()


def test_cloud_process_keeps_explicit_work_dir(tmp_path, completed_cloud, capsys):
    from mineru_ocr.publish import validate_output
    source = tmp_path / 'input.docx'
    source.write_bytes(b'input')
    work = tmp_path / 'review'
    assert cli.main(['process', str(source), '--engine', 'cloud', '--output-dir', str(tmp_path / 'out'),
                     '--work-dir', str(work)]) == 0
    job = json.loads(capsys.readouterr().out)[0]
    assert Path(job['result_dir']).is_relative_to(work)
    assert Path(job['manifest']).is_file() and Path(job['result_dir']).is_dir()
    assert validate_output(job['markdown'], work_dir=work)['validation_scope'] == 'recorded_hashes'


def test_cloud_download_error_reports_resumable_job(tmp_path, monkeypatch, completed_cloud, capsys):
    import httpx
    from mineru_ocr import service

    source = tmp_path / 'input.docx'
    source.write_bytes(b'input')
    with monkeypatch.context() as context:
        def interrupted(*args):
            raise httpx.ReadError('connection lost')
        context.setattr(completed_cloud, 'download', interrupted)
        assert cli.main(['process', str(source), '--engine', 'cloud', '--output-dir', str(tmp_path / 'out')]) == 1
    error = json.loads(capsys.readouterr().err)
    resumed = service.resume_job(error['job_id'])
    assert Path(resumed['result_dir']).is_relative_to(error['work_dir'])


def test_failed_publication_preserves_raw_result_for_review(tmp_path, completed_cloud, capsys):
    source = tmp_path / 'input.docx'
    source.write_bytes(b'input')
    review = tmp_path / 'review.json'
    review.write_text('{"replacements": [{}]}', encoding='utf-8')
    output = tmp_path / 'out'
    assert cli.main(['process', str(source), '--engine', 'cloud', '--output-dir', str(output),
                     '--review-file', str(review)]) == 1
    error = json.loads(capsys.readouterr().err)
    task = Path(error['work_dir'])
    assert list(task.glob('cloud/*/input.docx.mineru/full.md'))
    assert not list(output.glob('*.md'))


def test_cli_publish_avoids_names_with_legacy_records(tmp_path, capsys):
    from mineru_ocr.publish import publish_output, validate_output
    source = make_bundle(tmp_path)
    output = tmp_path / 'out'
    legacy = publish_output(source, output)
    Path(legacy['markdown']).unlink()

    assert cli.main(['publish', str(source), '--output-dir', str(output)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['markdown'] != legacy['markdown']
    assert Path(legacy['manifest']).is_file()
    assert validate_output(result['markdown'])['validation_scope'] == 'references'
