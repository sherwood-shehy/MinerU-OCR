from pathlib import Path

from pypdf import PdfWriter

from mineru_ocr.models import OCROptions
from mineru_ocr.errors import PlanningError
from mineru_ocr import planner
from mineru_ocr.planner import plan_job


def make_pdf(path: Path, pages: int) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as handle:
        writer.write(handle)


def test_200_pages_uploads_original_once(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    source = tmp_path / "two-hundred.pdf"
    make_pdf(source, 200)
    job = plan_job(source)
    assert job.page_count == 200
    assert len(job.parts) == 1
    assert job.parts[0].local_path == str(source.resolve())
    assert job.parts[0].page_ranges is None
    assert not job.parts[0].physical


def test_199_pages_uploads_original_once(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    source = tmp_path / "one-nine-nine.pdf"
    make_pdf(source, 199)
    job = plan_job(source)
    assert len(job.parts) == 1 and job.parts[0].page_ranges is None


def test_201_pages_uploads_complete_file_twice(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    source = tmp_path / "two-oh-one.pdf"
    make_pdf(source, 201)
    job = plan_job(source)
    assert [part.page_ranges for part in job.parts] == ["1-200", "201-201"]
    assert {part.local_path for part in job.parts} == {str(source.resolve())}
    assert len({part.data_id for part in job.parts}) == 2


def test_400_pages_has_two_complete_file_uploads(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    source = tmp_path / "four-hundred.pdf"
    make_pdf(source, 400)
    job = plan_job(source)
    assert [part.page_ranges for part in job.parts] == ["1-200", "201-400"]


def test_small_office_is_direct_and_accepts_explicit_range(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    source = tmp_path / "notes.docx"
    source.write_bytes(b"placeholder")
    job = plan_job(source, OCROptions(office_page_ranges="1-20"))
    assert job.source_type == "office"
    assert len(job.parts) == 1
    assert job.parts[0].page_ranges == "1-20"


def test_size_limit_causes_physical_pdf_parts(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    source = tmp_path / "large.pdf"
    make_pdf(source, 3)
    monkeypatch.setattr(planner, "MAX_UPLOAD_BYTES", 1)
    monkeypatch.setattr(planner, "TARGET_PART_BYTES", 10_000_000)
    job = plan_job(source)
    assert all(part.physical for part in job.parts)
    assert all(Path(part.local_path) != source for part in job.parts)


def test_oversized_office_requires_pdf(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    source = tmp_path / "large.docx"
    source.write_bytes(b"123")
    monkeypatch.setattr(planner, "MAX_UPLOAD_BYTES", 1)
    try:
        plan_job(source)
    except PlanningError as exc:
        assert "export it to PDF" in str(exc)
    else:
        raise AssertionError("Expected an oversized Office file to be rejected")
