"""Private processing records; portable deliveries never depend on this directory."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from platformdirs import user_cache_dir

from .errors import MinerUOCRError


def default_work_dir() -> Path:
    return Path(user_cache_dir('mineru-ocr', appauthor=False)) / 'deliveries'


def records_dir(markdown: Path, work_dir: Path | None = None) -> Path:
    key = hashlib.sha256(os.path.normcase(str(markdown.resolve())).encode('utf-8')).hexdigest()
    return (Path(work_dir) if work_dir is not None else default_work_dir()).resolve() / key


def check_work_dir(output: Path, work_dir: Path | None) -> Path:
    root = (Path(work_dir) if work_dir is not None else default_work_dir()).resolve()
    output = output.resolve()
    if root == output or output in root.parents or root in output.parents:
        raise MinerUOCRError('Internal work directory and delivery directory must be separate, non-nested paths')
    return root


def internal_markdown(markdown: Path, work_dir: Path | None = None) -> Path:
    return records_dir(markdown, work_dir) / markdown.name
