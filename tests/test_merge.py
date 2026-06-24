import json
import zipfile
from pathlib import Path

import pytest

from mineru_ocr.errors import MergeError
from mineru_ocr.merge import merge_job, safe_extract
from mineru_ocr.models import JobPart, OCRJob, OCROptions


def make_job(tmp_path: Path) -> OCRJob:
    parts = []
    for index, pages in [(1, (1, 200)), (2, (201, 201))]:
        root = tmp_path / f"extract-{index}"
        (root / "images").mkdir(parents=True)
        (root / "images" / "same.png").write_bytes(f"image-{index}".encode())
        md = root / "full.md"
        md.write_text(f"# Part {index}\n\n![figure](images/same.png)\n", encoding="utf-8")
        parts.append(JobPart(
            index=index, local_path="source.pdf", upload_name=f"part-{index}.pdf",
            data_id=f"job.p{index}", page_start=pages[0], page_end=pages[1], state="done",
            full_md=str(md), extracted_dir=str(root),
        ))
    return OCRJob(
        job_id="job", source_path=str(tmp_path / "source.pdf"), source_name="source.pdf",
        source_size=10, source_sha256="abc", source_type="pdf", page_count=201,
        output_dir=str(tmp_path / "source.pdf.mineru"), work_dir=str(tmp_path / "work"),
        options=OCROptions(), parts=parts,
    )


def test_merge_orders_parts_and_namespaces_assets(tmp_path):
    output = merge_job(make_job(tmp_path))
    text = (output / "full.md").read_text(encoding="utf-8")
    assert text.index("Part 1") < text.index("Part 2")
    assert "assets/part-0001/images/same.png" in text
    assert "assets/part-0002/images/same.png" in text
    assert (output / "assets/part-0001/images/same.png").is_file()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert "full_zip_url" not in json.dumps(manifest)


def test_safe_extract_rejects_zip_slip(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape.txt", "bad")
    with pytest.raises(MergeError):
        safe_extract(archive, tmp_path / "out")

