"""Explicit runtime checks; never install packages or modify environments."""
from __future__ import annotations

import importlib
from importlib import metadata
import sys

from .errors import MinerUOCRError

LOCAL_VERSION = '1.28.2'
INSTALL_LOCAL = 'From the project checkout run: python -m pip install -e ".[local]"'


def require_pdf():
    try:
        return importlib.import_module('pymupdf')
    except (ImportError, OSError) as exc:
        raise MinerUOCRError(f'PDF preflight/postprocessing requires PyMuPDF. {INSTALL_LOCAL}') from exc


def require_local():
    for package in ('PyMuPDF', 'pymupdf4llm', 'pymupdf-layout'):
        try:
            version = metadata.version(package)
        except metadata.PackageNotFoundError:
            version = None
        if version != LOCAL_VERSION:
            raise MinerUOCRError(f'Local extraction requires {package}=={LOCAL_VERSION}; found {version or "missing"}. {INSTALL_LOCAL}')
    try:
        module = importlib.import_module('pymupdf4llm')
        module.use_layout(True)
        return module
    except (ImportError, OSError, RuntimeError) as exc:
        raise MinerUOCRError(f'Cannot load the local PDF/layout runtime: {exc}. {INSTALL_LOCAL}') from exc


def doctor() -> dict:
    packages = {}
    for name in ('mineru-ocr-skill', 'PyMuPDF', 'pymupdf4llm', 'pymupdf-layout'):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    errors = {}
    for feature, check in [('pdf', require_pdf), ('local', require_local)]:
        try:
            check()
        except MinerUOCRError as exc:
            errors[feature] = str(exc)
    return {'python': sys.version.split()[0], 'executable': sys.executable, 'packages': packages,
            'pdf_ready': 'pdf' not in errors, 'local_ready': 'local' not in errors,
            'errors': errors, 'install_local': INSTALL_LOCAL,
            'scope': 'package versions and imports; conversion quality requires a document check'}
