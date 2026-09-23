from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import __version__
from .errors import MinerUOCRError
from .config import (
    clear_token,
    config_status,
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
    parser = argparse.ArgumentParser(prog="mineru-ocr", description="Prepare faithful Markdown with local PDF extraction and MinerU Cloud")
    parser.add_argument('--version', action='version', version='%(prog)s ' + __version__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["process", "submit"]:
        item = sub.add_parser(name)
        item.add_argument("files", nargs="+")
        _add_options(item)
        if name == "process":
            item.add_argument("--timeout", type=int, default=1800)
            item.add_argument("--output-dir", type=Path, help="Publish checked Markdown and resources into this directory")
            item.add_argument("--engine", choices=["auto", "local", "cloud"], default="auto",
                              help="Auto screens PDF text and tables; risky tables, scans or failed integrity checks use cloud. Local never uploads.")
            item.add_argument("--review-file", type=Path)
            item.add_argument("--name")
            item.add_argument("--title")
            item.add_argument("--table-format", choices=["auto", "html"], default="auto")
            item.add_argument("--edition", choices=["source", "reading"], default="source")
    preflight = sub.add_parser("preflight", help="Inspect every PDF page offline and recommend an extraction engine")
    preflight.add_argument("path", type=Path)
    sub.add_parser("doctor", help="Check installed PDF dependencies without installing or uploading anything")
    status = sub.add_parser("status")
    status.add_argument("job_id")
    status.add_argument("--no-refresh", action="store_true")
    resume = sub.add_parser("resume")
    resume.add_argument("job_id")
    resume.add_argument("--timeout", type=int, default=1800)
    clean = sub.add_parser("clean")
    clean.add_argument("job_id")
    publish = sub.add_parser("publish", help="Publish existing results offline with checked references")
    publish.add_argument("path")
    publish.add_argument("--output-dir", type=Path, required=True)
    publish.add_argument("--name", help="Optional output filename stem")
    publish.add_argument("--review-file", type=Path, help="Source-bound decisions to exclude independent invalid image blocks")
    readable = sub.add_parser("readable", help="Postprocess existing extraction results with original PDF page links")
    readable.add_argument("path")
    readable.add_argument("--source-pdf", type=Path, required=True)
    readable.add_argument("--output-dir", type=Path, required=True)
    readable.add_argument("--name")
    readable.add_argument("--title")
    readable.add_argument("--review-file", type=Path, help="Explicit source-checked corrections; optional")
    readable.add_argument("--profile", choices=["generic", "gas-std-wiki"], default="generic")
    readable.add_argument("--edition", choices=["reading", "source"], help="Default: source, without page screenshots; reading explicitly adds a full-page gallery")
    readable.add_argument("--table-format", choices=["html", "auto"], help="Auto converts only safely representable tables")
    readable.add_argument("--target-project", type=Path, help="Read and fingerprint target wiki rules; never ingest automatically")
    readable.add_argument("--source-id", help="Source identifier used in Chinese delivery records")
    validate = sub.add_parser("validate", help="Check local resource references and manifest hashes offline")
    validate.add_argument("path")
    inspect = sub.add_parser("inspect-images", help="Prepare a local image inventory for source review")
    inspect.add_argument("path")
    for command in [publish, readable, validate, inspect]:
        command.add_argument("--work-dir", type=Path, help="Internal records directory outside the delivery; default: user cache")
    sub.choices["process"].add_argument("--work-dir", type=Path)
    config = sub.add_parser("config")
    config.add_argument(
        "action",
        choices=["set-token", "show", "clear-token"],
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command not in {"publish", "validate", "readable", "inspect-images", "preflight", "doctor"}:
        load_dotenv()
    try:
        if args.command == "process":
            from .workflow import process_documents
            result = process_documents(args.files, _options(args), args.timeout, engine=args.engine,
                                       output_dir=args.output_dir, work_dir=args.work_dir,
                                       review_file=args.review_file, name=args.name, title=args.title,
                                       table_format=args.table_format, edition=args.edition,
                                       cloud_process=process_files)
        elif args.command == "preflight":
            from .preflight import preflight_pdf
            result = preflight_pdf(args.path)
        elif args.command == "doctor":
            from .environment import doctor
            result = doctor()
        elif args.command == "submit":
            result = submit_job(args.files, _options(args))
        elif args.command == "status":
            result = status_job(args.job_id, refresh=not args.no_refresh)
        elif args.command == "resume":
            result = resume_job(args.job_id, args.timeout)
        elif args.command == "clean":
            result = clean_job(args.job_id)
        elif args.command == "publish":
            from .publish import publish_output
            result = publish_output(args.path, args.output_dir, name=args.name, work_dir=args.work_dir, review_file=args.review_file)
        elif args.command == "readable":
            from .readable import prepare_readable
            result = prepare_readable(args.path, args.source_pdf, args.output_dir,
                                      name=args.name, title=args.title, review_file=args.review_file,
                                      profile=args.profile, edition=args.edition, table_format=args.table_format,
                                      target_project=args.target_project, source_id=args.source_id, work_dir=args.work_dir)
        elif args.command == "validate":
            from .publish import validate_output
            result = validate_output(args.path, work_dir=args.work_dir)
        elif args.command == "inspect-images":
            from .visuals import inspect_images
            result = inspect_images(args.path, work_dir=args.work_dir)
        elif args.action == "set-token":
            result = {"saved": True, "config_path": str(prompt_and_save_token())}
        elif args.action == "clear-token":
            result = {"cleared": clear_token(), **config_status()}
        else:
            result = config_status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        jobs = result if isinstance(result, list) else [result]
        return 1 if any(job.get("state") == "failed" or job.get("timed_out")
                        or (args.command == 'doctor' and not job.get('local_ready')) for job in jobs) else 0
    except (MinerUOCRError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "code": getattr(exc, "code", None)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
