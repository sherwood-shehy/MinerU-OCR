from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OCROptions(BaseModel):
    model_version: Literal["pipeline", "vlm"] = "vlm"
    is_ocr: bool = True
    language: str = "ch"
    enable_table: bool = True
    enable_formula: bool = True
    extra_formats: list[Literal["docx", "html", "latex"]] = Field(default_factory=list)
    office_page_ranges: str | None = None


class JobPart(BaseModel):
    index: int
    local_path: str
    upload_name: str
    data_id: str
    page_start: int | None = None
    page_end: int | None = None
    page_ranges: str | None = None
    physical: bool = False
    batch_id: str | None = None
    state: str = "planned"
    progress: dict = Field(default_factory=dict)
    full_zip_url: str | None = None
    error_code: int | str | None = None
    error_message: str | None = None
    trace_id: str | None = None
    full_md: str | None = None
    extracted_dir: str | None = None


class OCRJob(BaseModel):
    job_id: str
    source_path: str
    source_name: str
    source_size: int
    source_sha256: str
    source_type: Literal["pdf", "office"]
    page_count: int | None = None
    output_dir: str
    work_dir: str
    options: OCROptions
    parts: list[JobPart]
    state: str = "planned"
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    completed_at: str | None = None

    @property
    def path(self) -> Path:
        return Path(self.work_dir) / "job.json"

