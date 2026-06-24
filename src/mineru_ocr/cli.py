from __future__ import annotations

import argparse
import json
import sys

from .errors import MinerUOCRError
from .config import clear_token, config_status, prompt_and_save_token
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
    status = sub.add_parser("status")
    status.add_argument("job_id")
    status.add_argument("--no-refresh", action="store_true")
    resume = sub.add_parser("resume")
    resume.add_argument("job_id")
    resume.add_argument("--timeout", type=int, default=1800)
    clean = sub.add_parser("clean")
    clean.add_argument("job_id")
    config = sub.add_parser("config")
    config.add_argument("action", choices=["set-token", "show", "clear-token"])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "process":
            result = process_files(args.files, _options(args), args.timeout)
        elif args.command == "submit":
            result = submit_job(args.files, _options(args))
        elif args.command == "status":
            result = status_job(args.job_id, refresh=not args.no_refresh)
        elif args.command == "resume":
            result = resume_job(args.job_id, args.timeout)
        elif args.command == "clean":
            result = clean_job(args.job_id)
        elif args.action == "set-token":
            result = {"saved": True, "config_path": str(prompt_and_save_token())}
        elif args.action == "clear-token":
            result = {"cleared": clear_token(), **config_status()}
        else:
            result = config_status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (MinerUOCRError, FileNotFoundError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "code": getattr(exc, "code", None)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
