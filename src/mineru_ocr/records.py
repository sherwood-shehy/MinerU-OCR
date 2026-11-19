"""Private processing records; portable deliveries never depend on this directory."""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
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


class DeliveryWorkspace:
    """Own only the temporary directory created for this publication."""

    def __init__(self, output_dir: Path | None, work_dir: Path | None):
        self.temporary = output_dir is not None and work_dir is None
        self.path = (check_work_dir(output_dir, work_dir) if output_dir is not None
                     else Path(work_dir or default_work_dir()).resolve())

    def __enter__(self):
        if self.temporary:
            self.path.mkdir(parents=True, exist_ok=True)
            self.path = Path(tempfile.mkdtemp(prefix='run-', dir=self.path))
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc is not None and self.temporary:
            if getattr(exc, 'job_id', None):
                exc.work_dir = str(self.path)
                return
            try:
                self.path.rmdir()
            except OSError:
                exc.work_dir = str(self.path)

    def finish(self, results: list[dict]) -> None:
        if not self.temporary:
            return
        if not all(result.get('published') for result in results):
            for result in results:
                result.setdefault('work_dir', str(self.path))
            return
        try:
            shutil.rmtree(self.path)
        except OSError as exc:
            for result in results:
                result['cleanup_error'] = str(exc)
                result['work_dir'] = str(self.path)
            return
        for result in results:
            for key in ('manifest', 'processing_reports', 'work_dir'):
                result.pop(key, None)
            for key in ('result_dir', 'output_dir'):
                if result.get(key) and Path(result[key]).is_relative_to(self.path):
                    result.pop(key)
            if result.get('local_attempt'):
                result['local_attempt'].pop('result_dir', None)
