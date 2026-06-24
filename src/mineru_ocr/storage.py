from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from platformdirs import user_cache_dir

from .models import OCRJob, utc_now


APP_NAME = "mineru-ocr"


def cache_root() -> Path:
    root = Path(user_cache_dir(APP_NAME, appauthor=False)) / "jobs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def job_dir(job_id: str) -> Path:
    return cache_root() / job_id


def save_job(job: OCRJob) -> None:
    job.updated_at = utc_now()
    path = job.path
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(job.model_dump_json(indent=2), encoding="utf-8")
    temp.replace(path)


def load_job(job_id: str) -> OCRJob:
    path = job_dir(job_id) / "job.json"
    if not path.is_file():
        raise FileNotFoundError(f"OCR job not found: {job_id}")
    return OCRJob.model_validate_json(path.read_text(encoding="utf-8"))


def remove_job(job_id: str) -> None:
    path = job_dir(job_id).resolve()
    root = cache_root().resolve()
    if root not in path.parents:
        raise ValueError("Refusing to remove a path outside the OCR cache")
    shutil.rmtree(path, ignore_errors=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def public_job(job: OCRJob) -> dict:
    data = json.loads(job.model_dump_json())
    data.pop("work_dir", None)
    for part in data["parts"]:
        part.pop("full_zip_url", None)
        part.pop("local_path", None)
        part.pop("extracted_dir", None)
        part.pop("full_md", None)
    return data
