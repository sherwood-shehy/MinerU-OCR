import json

from mineru_ocr.merge import merge_job
from test_merge import make_job


def test_merge_preserves_layout_evidence_and_maps_physical_page(tmp_path):
    job = make_job(tmp_path)
    part = job.parts[1]
    part.physical = True
    root = tmp_path / "extract-2"
    (root / "sample_content_list.json").write_text(json.dumps([
        {"type": "image", "img_path": "images/same.png", "page_idx": 0, "bbox": [10, 20, 300, 400]}
    ]), encoding="utf-8")
    output = merge_job(job)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    asset = next(a for a in manifest["assets"] if a["path"].startswith("assets/part-0002/"))
    location = asset["locations"][0]
    assert location["page"] == 201
    assert location["bbox"] == [10, 20, 300, 400]
    assert location["precision"] == "page_bbox"
    assert (output / location["evidence_ref"].split("#")[0]).is_file()
    first = next(a for a in manifest["assets"] if a["path"].startswith("assets/part-0001/"))
    assert first["locations"][0]["precision"] == "page_range"
    assert first["locations"][0]["page"] is None


def test_logical_page_indices_are_not_offset_twice(tmp_path):
    job = make_job(tmp_path)
    (tmp_path / "extract-2/content_list.json").write_text(json.dumps([
        {"type": "image", "img_path": "images/same.png", "page_idx": 200, "bbox": [0, 0, 1, 1]}
    ]), encoding="utf-8")
    result = merge_job(job)
    manifest = json.loads((result / "manifest.json").read_text(encoding="utf-8"))
    asset = next(a for a in manifest["assets"] if a["path"].startswith("assets/part-0002/"))
    assert asset["locations"][0]["page"] == 201


def test_merge_failure_can_be_retried_after_downloads_complete(tmp_path, monkeypatch):
    from mineru_ocr import service, storage
    job = make_job(tmp_path)
    job.work_dir = str(tmp_path / "jobs/job")
    job.state = "pending"
    for part in job.parts:
        part.batch_id = "finished-batch"
    storage.save_job(job)
    result = service.status_job("job")
    assert result["state"] == "done"
    assert (tmp_path / "source.pdf.mineru/full.md").is_file()


def test_repeated_asset_preserves_each_coarse_source_range(tmp_path):
    from mineru_ocr.provenance import build_manifest
    (tmp_path / 'image.png').write_bytes(b'image')
    source = tmp_path / 'source.md'
    source.write_text('<!-- MinerU source pages 1-200 -->\n![A](image.png)\n'
                      '<!-- MinerU source pages 201-300 -->\n![A again](image.png)\n', encoding='utf-8')
    asset = build_manifest(source)['assets'][0]
    assert [loc['page_range'] for loc in asset['locations']] == [[1, 200], [201, 300]]
