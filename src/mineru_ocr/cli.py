from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from .errors import MinerUOCRError
from .config import (
    clear_doubao_key,
    clear_token,
    config_status,
    prompt_and_save_doubao_key,
    prompt_and_save_token,
)
from .models import OCROptions
from .service import clean_job, process_files, resume_job, status_job, submit_job


def _options(args) -> OCROptions:
    return OCROptions(
        model_version=args.model, is_ocr=not args.no_ocr, language=args.language,
        enable_table=not args.no_table, enable_formula=not args.no_formula,
        office_page_ranges=getattr(args, "page_ranges", None),
    )


def _add_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", choices=["pipeline", "vlm"], default="vlm")
    parser.add_argument("--language", default="ch")
    parser.add_argument("--no-ocr", action="store_true")
    parser.add_argument("--no-table", action="store_true")
    parser.add_argument("--no-formula", action="store_true")
    parser.add_argument("--page-ranges", help="Explicit page_ranges for a small Office file")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mineru-ocr", description="OCR local documents with MinerU")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["process", "submit"]:
        item = sub.add_parser(name)
        item.add_argument("files", nargs="+")
        _add_options(item)
        if name == "process":
            item.add_argument("--timeout", type=int, default=1800)
            item.add_argument("--output-dir", type=Path, help="Publish checked Markdown and resources into this directory")
            item.add_argument(
                "--enhance", action="store_true",
                help="After OCR, generate an AI-oriented JSONL file via Doubao",
            )
            item.add_argument(
                "--enhance-best-effort", action="store_true",
                help="Do not fail the process command if AI enhancement fails",
            )
    status = sub.add_parser("status")
    status.add_argument("job_id")
    status.add_argument("--no-refresh", action="store_true")
    resume = sub.add_parser("resume")
    resume.add_argument("job_id")
    resume.add_argument("--timeout", type=int, default=1800)
    clean = sub.add_parser("clean")
    clean.add_argument("job_id")
    enhance = sub.add_parser(
        "enhance",
        help="Generate an AI-oriented JSONL file for an existing MinerU result",
    )
    enhance.add_argument("result_dir", help="Path to a *.mineru directory or a published Markdown file")
    publish = sub.add_parser("publish", help="Publish existing results offline with checked references")
    publish.add_argument("path")
    publish.add_argument("--output-dir", type=Path, required=True)
    publish.add_argument("--name", help="Optional output filename stem")
    publish.add_argument("--image-dir", choices=["assets", "images"], default="assets")
    readable = sub.add_parser("readable", help="Prepare a traceable reading edition locally from existing OCR results")
    readable.add_argument("path")
    readable.add_argument("--source-pdf", type=Path, required=True)
    readable.add_argument("--output-dir", type=Path, required=True)
    readable.add_argument("--name")
    readable.add_argument("--title")
    readable.add_argument("--review-file", type=Path, help="Explicit source-checked corrections; optional")
    readable.add_argument("--profile", choices=["generic", "gas-std-wiki"], default="generic")
    readable.add_argument("--edition", choices=["reading", "source"], help="Default: reading; gas-std-wiki defaults to source")
    readable.add_argument("--table-format", choices=["html", "auto"], help="Auto converts only safely representable tables")
    readable.add_argument("--target-project", type=Path, help="Read and fingerprint target wiki rules; never ingest automatically")
    readable.add_argument("--source-id", help="Source identifier used in Chinese delivery records")
    validate = sub.add_parser("validate", help="Check local resource references and manifest hashes offline")
    validate.add_argument("path")
    config = sub.add_parser("config")
    config.add_argument(
        "action",
        choices=["set-token", "show", "clear-token", "set-doubao-key", "clear-doubao-key"],
    )
    return parser


def _enhance_results(results: list[dict], *, best_effort: bool = False) -> None:
    """Run the AI enhancement layer for each completed process result in-place."""
    from .enhancer import enhance_output  # local import to avoid pulling httpx/etc when unused
    for result in results:
        result_dir = result.get("markdown") or result.get("result_dir")
        if not result_dir:
            result["enhanced"] = False
            result["enhance_error"] = "Skipped: no result_dir on this job"
            continue
        try:
            result["ai_enhancement"] = enhance_output(result_dir)
            result["enhanced"] = True
        except Exception as exc:
            result["enhanced"] = False
            result["enhance_error"] = str(exc)
            if not best_effort:
                raise


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command not in {"publish", "validate", "readable"}:
        load_dotenv()
    try:
        if args.command == "process":
            result = process_files(args.files, _options(args), args.timeout)
            if args.output_dir:
                from .publish import publish_output
                for job in result:
                    if job.get("result_dir"):
                        job.update(publish_output(job["result_dir"], args.output_dir))
            if getattr(args, "enhance", False):
                _enhance_results(result, best_effort=getattr(args, "enhance_best_effort", False))
        elif args.command == "submit":
            result = submit_job(args.files, _options(args))
        elif args.command == "status":
            result = status_job(args.job_id, refresh=not args.no_refresh)
        elif args.command == "resume":
            result = resume_job(args.job_id, args.timeout)
        elif args.command == "clean":
            result = clean_job(args.job_id)
        elif args.command == "enhance":
            from .enhancer import enhance_output
            result = enhance_output(args.result_dir)
        elif args.command == "publish":
            from .publish import publish_output
            result = publish_output(args.path, args.output_dir, name=args.name, image_dir=args.image_dir)
        elif args.command == "readable":
            from .readable import prepare_readable
            result = prepare_readable(args.path, args.source_pdf, args.output_dir,
                                      name=args.name, title=args.title, review_file=args.review_file,
                                      profile=args.profile, edition=args.edition, table_format=args.table_format,
                                      target_project=args.target_project, source_id=args.source_id)
        elif args.command == "validate":
            from .publish import validate_output
            result = validate_output(args.path)
        elif args.action == "set-token":
            result = {"saved": True, "config_path": str(prompt_and_save_token())}
        elif args.action == "set-doubao-key":
            result = {"saved": True, "config_path": str(prompt_and_save_doubao_key())}
        elif args.action == "clear-token":
            result = {"cleared": clear_token(), **config_status()}
        elif args.action == "clear-doubao-key":
            result = {"cleared": clear_doubao_key(), **config_status()}
        else:
            result = config_status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        jobs = result if isinstance(result, list) else [result]
        return 1 if any(job.get("state") == "failed" or job.get("timed_out") for job in jobs) else 0
    except (MinerUOCRError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "code": getattr(exc, "code", None)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
