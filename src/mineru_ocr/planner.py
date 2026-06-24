from __future__ import annotations

import re
import uuid
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .errors import PlanningError
from .models import OCRJob, OCROptions, JobPart
from .storage import job_dir, save_job, sha256_file


MAX_UPLOAD_BYTES = 200 * 1024 * 1024
TARGET_PART_BYTES = 190 * 1024 * 1024
MAX_PAGES = 200
PDF_EXTENSIONS = {".pdf"}
OFFICE_EXTENSIONS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}


def _safe_stem(name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(name).stem).strip("-.")
    return value[:70] or "document"


def _part_data_id(job_id: str, index: int, start: int | None, end: int | None) -> str:
    suffix = f"p{start:04d}-{end:04d}" if start and end else f"part-{index:04d}"
    return f"{job_id}.{suffix}"


def _write_pdf_range(reader: PdfReader, start: int, end: int, destination: Path) -> None:
    writer = PdfWriter()
    for page_index in range(start - 1, end):
        writer.add_page(reader.pages[page_index])
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        writer.write(handle)


def _split_range_to_size(
    reader: PdfReader, source_stem: str, start: int, end: int, split_dir: Path, results: list[tuple[int, int, Path]]
) -> None:
    destination = split_dir / f"{source_stem}.p{start:04d}-{end:04d}.pdf"
    _write_pdf_range(reader, start, end, destination)
    if destination.stat().st_size <= TARGET_PART_BYTES:
        results.append((start, end, destination))
        return
    destination.unlink(missing_ok=True)
    if start == end:
        raise PlanningError(f"PDF page {start} exceeds the 190MB safe upload threshold by itself")
    midpoint = (start + end) // 2
    _split_range_to_size(reader, source_stem, start, midpoint, split_dir, results)
    _split_range_to_size(reader, source_stem, midpoint + 1, end, split_dir, results)


def plan_job(source: str | Path, options: OCROptions | None = None) -> OCRJob:
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise PlanningError(f"Input file does not exist: {path}")
    if path.stat().st_size == 0:
        raise PlanningError(f"Input file is empty: {path}")
    suffix = path.suffix.lower()
    if suffix not in PDF_EXTENSIONS | OFFICE_EXTENSIONS:
        raise PlanningError(f"Unsupported input type: {suffix or '(no extension)'}")

    options = options or OCROptions()
    job_id = uuid.uuid4().hex
    work = job_dir(job_id)
    work.mkdir(parents=True, exist_ok=False)
    output_dir = path.with_name(f"{path.name}.mineru")
    parts: list[JobPart] = []
    page_count: int | None = None
    source_type = "pdf" if suffix == ".pdf" else "office"

    if source_type == "office":
        if path.stat().st_size > MAX_UPLOAD_BYTES:
            raise PlanningError("Office file exceeds 200MB; export it to PDF before using mineru-ocr")
        parts.append(JobPart(
            index=1, local_path=str(path), upload_name=path.name,
            data_id=_part_data_id(job_id, 1, None, None), page_ranges=options.office_page_ranges,
        ))
    else:
        try:
            reader = PdfReader(str(path))
            page_count = len(reader.pages)
        except Exception as exc:
            raise PlanningError(f"Unable to read PDF page structure: {exc}") from exc
        if page_count < 1:
            raise PlanningError("PDF contains no pages")
        ranges = [(start, min(start + MAX_PAGES - 1, page_count)) for start in range(1, page_count + 1, MAX_PAGES)]
        if path.stat().st_size <= MAX_UPLOAD_BYTES:
            for index, (start, end) in enumerate(ranges, 1):
                page_ranges = f"{start}-{end}" if page_count > MAX_PAGES else None
                upload_name = f"{_safe_stem(path.name)}.p{start:04d}-{end:04d}.pdf" if page_ranges else path.name
                parts.append(JobPart(
                    index=index, local_path=str(path), upload_name=upload_name,
                    data_id=_part_data_id(job_id, index, start, end),
                    page_start=start, page_end=end, page_ranges=page_ranges,
                ))
        else:
            split_results: list[tuple[int, int, Path]] = []
            for start, end in ranges:
                _split_range_to_size(reader, _safe_stem(path.name), start, end, work / "splits", split_results)
            for index, (start, end, split_path) in enumerate(sorted(split_results), 1):
                parts.append(JobPart(
                    index=index, local_path=str(split_path), upload_name=split_path.name,
                    data_id=_part_data_id(job_id, index, start, end),
                    page_start=start, page_end=end, physical=True,
                ))

    job = OCRJob(
        job_id=job_id, source_path=str(path), source_name=path.name,
        source_size=path.stat().st_size, source_sha256=sha256_file(path), source_type=source_type,
        page_count=page_count, output_dir=str(output_dir), work_dir=str(work), options=options, parts=parts,
    )
    save_job(job)
    return job

