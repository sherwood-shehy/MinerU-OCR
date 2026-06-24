from __future__ import annotations

import getpass
import os
import tomllib
from pathlib import Path

from platformdirs import user_config_dir


def config_path() -> Path:
    return Path(user_config_dir("mineru-ocr", appauthor=False)) / "config.toml"


def load_config() -> dict:
    path = config_path()
    if not path.is_file():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def get_token() -> str | None:
    environment = os.environ.get("MINERU_API_TOKEN", "").strip()
    if environment:
        return environment
    value = load_config().get("mineru", {}).get("api_token")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def save_token(token: str) -> Path:
    token = token.strip()
    if not token:
        raise ValueError("Token cannot be empty")
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(f"[mineru]\napi_token = {_toml_string(token)}\n", encoding="utf-8")
    temporary.replace(path)
    return path


def prompt_and_save_token() -> Path:
    return save_token(getpass.getpass("MinerU Token: "))


def clear_token() -> bool:
    path = config_path()
    if not path.exists():
        return False
    path.unlink()
    try:
        path.parent.rmdir()
    except OSError:
        pass
    return True


def config_status() -> dict:
    path = config_path()
    environment_set = bool(os.environ.get("MINERU_API_TOKEN", "").strip())
    configured = bool(load_config().get("mineru", {}).get("api_token")) if path.is_file() else False
    return {
        "config_path": str(path),
        "config_token_set": configured,
        "environment_token_set": environment_set,
        "effective_source": "environment" if environment_set else "config" if configured else None,
    }
