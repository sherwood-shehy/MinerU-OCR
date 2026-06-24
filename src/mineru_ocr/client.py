from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Iterable

import httpx

from .errors import MinerUAPIError
from .models import JobPart, OCROptions


TRANSIENT_CODES = {-10001, -60001, -60007, -60008, -60009, -60010, -60020, -60021, -60022}


class MinerUClient:
    def __init__(self, token: str, *, base_url: str = "https://mineru.net/api/v4", timeout: float = 60.0):
        if not token:
            raise MinerUAPIError("MINERU_API_TOKEN is required")
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=20.0), follow_redirects=True,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _request(self, method: str, url: str, *, attempts: int = 5, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                response = self.client.request(method, url, headers=headers, **kwargs)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt + 1 < attempts:
                        retry_after = response.headers.get("Retry-After")
                        delay = float(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 15)
                        time.sleep(delay + random.random() * 0.25)
                        continue
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    break
                time.sleep(min(2 ** attempt, 15) + random.random() * 0.25)
        raise MinerUAPIError(f"MinerU HTTP request failed: {last_error}") from last_error

    def _call_json(self, method: str, url: str, **kwargs) -> dict:
        for attempt in range(4):
            try:
                return self._json(self._request(method, url, **kwargs))
            except MinerUAPIError as exc:
                if exc.code not in TRANSIENT_CODES or attempt == 3:
                    raise
                time.sleep(min(2 ** attempt, 10) + random.random() * 0.25)
        raise AssertionError("unreachable")

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        try:
            result = response.json()
        except ValueError as exc:
            raise MinerUAPIError("MinerU returned a non-JSON response") from exc
        if result.get("code") != 0:
            code = result.get("code")
            message = result.get("msg") or "MinerU API error"
            if code in {-60005, -60006}:
                message += "; for Office files, export to PDF before retrying"
            raise MinerUAPIError(message, code=code, trace_id=result.get("trace_id"))
        return result

    def request_uploads(self, parts: list[JobPart], options: OCROptions) -> tuple[str, list[str], str | None]:
        files = []
        for part in parts:
            item: dict = {"name": part.upload_name, "data_id": part.data_id, "is_ocr": options.is_ocr}
            if part.page_ranges:
                item["page_ranges"] = part.page_ranges
            files.append(item)
        payload = {
            "files": files, "model_version": options.model_version, "language": options.language,
            "enable_table": options.enable_table, "enable_formula": options.enable_formula,
        }
        if options.extra_formats:
            payload["extra_formats"] = options.extra_formats
        result = self._call_json("POST", f"{self.base_url}/file-urls/batch", json=payload)
        return result["data"]["batch_id"], result["data"]["file_urls"], result.get("trace_id")

    def upload(self, signed_url: str, path: str | Path) -> None:
        last_error: Exception | None = None
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=20.0), follow_redirects=True) as upload_client:
            for attempt in range(4):
                try:
                    with Path(path).open("rb") as handle:
                        response = upload_client.put(signed_url, content=handle)
                    if response.status_code in {200, 201, 204}:
                        return
                    response.raise_for_status()
                except (httpx.HTTPError, OSError) as exc:
                    last_error = exc
                    if attempt < 3:
                        time.sleep(min(2 ** attempt, 8) + random.random() * 0.25)
            raise MinerUAPIError(f"Signed upload failed: {last_error}") from last_error

    def batch_status(self, batch_id: str) -> dict:
        return self._call_json("GET", f"{self.base_url}/extract-results/batch/{batch_id}")

    def download(self, url: str, destination: Path) -> None:
        if not url.lower().startswith("https://"):
            raise MinerUAPIError("Refusing a non-HTTPS result URL")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=120.0, follow_redirects=True) as download_client:
            with download_client.stream("GET", url) as response:
                response.raise_for_status()
                with destination.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
