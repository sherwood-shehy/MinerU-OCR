from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path

from .client import MinerUClient
from .config import get_token
from .errors import MinerUAPIError, MinerUOCRError
from .merge import find_full_md, merge_job, safe_extract
from .models import OCRJob, OCROptions, utc_now
from .planner import plan_job
from .storage import load_job, public_job, remove_job, save_job


TERMINAL = {"done", "failed"}


def _token() -> str:
    token = get_token() or ""
    if not token:
        raise MinerUOCRError("Configure a Token with 'mineru-ocr config set-token' or MINERU_API_TOKEN")
    return token


def _chunks(items: list, size: int = 50):
    for index in range(0, len(items), size):
        yield items[index:index + size]


def submit_job(files: list[str], options: OCROptions | None = None) -> list[dict]:
    jobs = [plan_job(file, options) for file in files]
    with MinerUClient(_token()) as client:
        for job in jobs:
            try:
                pending = [part for part in job.parts if part.state in {"planned", "failed"}]
                for group in _chunks(pending):
                    batch_id, urls, trace_id = client.request_uploads(group, job.options)
                    if len(urls) != len(group):
                        raise MinerUAPIError("MinerU returned an unexpected number of upload URLs", trace_id=trace_id)
                    for part, url in zip(group, urls):
                        part.batch_id = batch_id
                        part.trace_id = trace_id
                        part.state = "uploading"
                        save_job(job)
                        client.upload(url, part.local_path)
                        part.state = "waiting-file"
                        save_job(job)
                job.state = "submitted"
                save_job(job)
            except Exception as exc:
                job.state = "failed"
                for part in job.parts:
                    if part.state in {"planned", "uploading", "waiting-file"}:
                        part.state = "failed"
                        part.error_code = getattr(exc, "code", None)
                        part.error_message = str(exc)
                save_job(job)
                raise
    return [public_job(job) for job in jobs]


def refresh_job(job: OCRJob, client: MinerUClient) -> OCRJob:
    by_batch: dict[str, list] = defaultdict(list)
    for part in job.parts:
        if part.batch_id and not (part.state == "done" and part.full_md):
            by_batch[part.batch_id].append(part)
    for batch_id, parts in by_batch.items():
        result = client.batch_status(batch_id)
        trace_id = result.get("trace_id")
        rows = result.get("data", {}).get("extract_result", [])
        by_data_id = {row.get("data_id"): row for row in rows if row.get("data_id")}
        by_name = {row.get("file_name"): row for row in rows if row.get("file_name")}
        for part in parts:
            row = by_data_id.get(part.data_id) or by_name.get(part.upload_name)
            if not row:
                continue
            part.trace_id = trace_id or part.trace_id
            part.state = row.get("state", part.state)
            part.progress = row.get("extract_progress") or {}
            part.full_zip_url = row.get("full_zip_url")
            part.error_message = row.get("err_msg") or None
            part.error_code = row.get("err_code")
    states = {part.state for part in job.parts}
    if states == {"done"} and all(part.full_md for part in job.parts):
        job.state = "done"
    elif "failed" in states:
        job.state = "failed"
    elif states & {"running", "converting"}:
        job.state = "running"
    else:
        job.state = "pending"
    save_job(job)
    return job


def download_ready(job: OCRJob, client: MinerUClient) -> None:
    for part in job.parts:
        if part.state != "done" or part.full_md:
            continue
        if not part.full_zip_url:
            raise MinerUOCRError(f"Part {part.index} is done but has no result URL")
        part_dir = Path(job.work_dir) / "results" / f"part-{part.index:04d}"
        zip_path = part_dir / "result.zip"
        extract_dir = part_dir / "extracted"
        client.download(part.full_zip_url, zip_path)
        safe_extract(zip_path, extract_dir)
        full_md = find_full_md(extract_dir)
        part.extracted_dir = str(extract_dir)
        part.full_md = str(full_md)
        save_job(job)


def status_job(job_id: str, *, refresh: bool = True) -> dict:
    job = load_job(job_id)
    if refresh and any(part.batch_id and not part.full_md for part in job.parts):
        with MinerUClient(_token()) as client:
            refresh_job(job, client)
            download_ready(job, client)
            if all(part.state == "done" and part.full_md for part in job.parts):
                output = merge_job(job)
                job.state = "done"
                job.completed_at = utc_now()
                save_job(job)
                result = public_job(job)
                result["result_dir"] = str(output)
                remove_job(job.job_id)
                return result
    return public_job(job)


def wait_job(job_id: str, timeout_seconds: int = 1800, interval_seconds: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while True:
        result = status_job(job_id)
        if result["state"] in TERMINAL:
            return result
        if time.monotonic() >= deadline:
            result["timed_out"] = True
            return result
        time.sleep(interval_seconds)


def process_files(files: list[str], options: OCROptions | None = None, timeout_seconds: int = 1800) -> list[dict]:
    submitted = submit_job(files, options)
    return [wait_job(job["job_id"], timeout_seconds=timeout_seconds) for job in submitted]


def resume_job(job_id: str, timeout_seconds: int = 1800) -> dict:
    job = load_job(job_id)
    failed = [part for part in job.parts if part.state == "failed"]
    if failed:
        for part in failed:
            part.state = "planned"
            part.batch_id = None
            part.error_code = None
            part.error_message = None
        save_job(job)
        with MinerUClient(_token()) as client:
            for group in _chunks(failed):
                batch_id, urls, trace_id = client.request_uploads(group, job.options)
                for part, url in zip(group, urls):
                    part.batch_id = batch_id
                    part.trace_id = trace_id
                    client.upload(url, part.local_path)
                    part.state = "waiting-file"
                    save_job(job)
    return wait_job(job_id, timeout_seconds=timeout_seconds)


def clean_job(job_id: str) -> dict:
    load_job(job_id)
    remove_job(job_id)
    return {"job_id": job_id, "cleaned": True}
