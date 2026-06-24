from __future__ import annotations

import argparse
import asyncio

from mcp.server.fastmcp import FastMCP

from .models import OCROptions
from .service import clean_job, process_files, resume_job, status_job, submit_job


mcp = FastMCP("mineru-ocr", host="127.0.0.1")


def _options(options: dict | None) -> OCROptions:
    return OCROptions.model_validate(options or {})


@mcp.tool()
async def ocr_process(files: list[str], options: dict | None = None, timeout_seconds: int = 1800) -> list[dict]:
    """OCR local documents, wait for MinerU, and write merged Markdown beside each source."""
    return await asyncio.to_thread(process_files, files, _options(options), timeout_seconds)


@mcp.tool()
async def ocr_submit(files: list[str], options: dict | None = None) -> list[dict]:
    """Plan and submit local documents, returning resumable local job identifiers."""
    return await asyncio.to_thread(submit_job, files, _options(options))


@mcp.tool()
async def ocr_status(job_id: str) -> dict:
    """Refresh a MinerU OCR job and merge it automatically when all parts are ready."""
    return await asyncio.to_thread(status_job, job_id)


@mcp.tool()
async def ocr_resume(job_id: str, timeout_seconds: int = 1800) -> dict:
    """Retry only failed OCR parts and continue a saved job."""
    return await asyncio.to_thread(resume_job, job_id, timeout_seconds)


@mcp.tool()
async def ocr_clean(job_id: str) -> dict:
    """Remove cached files and state for an unfinished OCR job."""
    return await asyncio.to_thread(clean_job, job_id)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mineru-ocr-mcp")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--port", type=int, default=8182)
    args = parser.parse_args(argv)
    if args.transport == "streamable-http":
        mcp.settings.port = args.port
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()

