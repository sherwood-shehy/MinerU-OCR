from __future__ import annotations

import getpass
import os
import tomllib
from pathlib import Path

from platformdirs import user_config_dir

DEFAULT_DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"
DEFAULT_DOUBAO_MODEL = "doubao-seed-2.0-lite"


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


def _write_config(data: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    sections: list[str] = []
    for section_name in sorted(data):
        values = data[section_name]
        if not isinstance(values, dict) or not values:
            continue
        lines = [f"[{section_name}]"]
        for key in sorted(values):
            value = values[key]
            if isinstance(value, str) and value:
                lines.append(f"{key} = {_toml_string(value)}")
        if len(lines) > 1:
            sections.append("\n".join(lines))
    if not sections:
        if path.exists():
            path.unlink()
        try:
            path.parent.rmdir()
        except OSError:
            pass
        return path
    temporary.write_text("\n\n".join(sections).rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def save_token(token: str) -> Path:
    token = token.strip()
    if not token:
        raise ValueError("Token cannot be empty")
    data = load_config()
    data.setdefault("mineru", {})["api_token"] = token
    return _write_config(data)


def prompt_and_save_token() -> Path:
    return save_token(getpass.getpass("MinerU Token: "))


def get_doubao_config() -> dict:
    section = load_config().get("doubao", {})
    api_key = section.get("api_key") if isinstance(section, dict) else None
    base_url = section.get("base_url") if isinstance(section, dict) else None
    model = section.get("model") if isinstance(section, dict) else None
    return {
        "api_key": api_key.strip() if isinstance(api_key, str) and api_key.strip() else None,
        "base_url": base_url.strip() if isinstance(base_url, str) and base_url.strip() else DEFAULT_DOUBAO_BASE_URL,
        "model": model.strip() if isinstance(model, str) and model.strip() else DEFAULT_DOUBAO_MODEL,
    }


def save_doubao_key(api_key: str) -> Path:
    api_key = api_key.strip()
    if not api_key:
        raise ValueError("Doubao API key cannot be empty")
    data = load_config()
    section = data.setdefault("doubao", {})
    section["api_key"] = api_key
    section.setdefault("base_url", DEFAULT_DOUBAO_BASE_URL)
    section.setdefault("model", DEFAULT_DOUBAO_MODEL)
    return _write_config(data)


def prompt_and_save_doubao_key() -> Path:
    return save_doubao_key(getpass.getpass("Doubao API Key: "))


def clear_doubao_key() -> bool:
    data = load_config()
    section = data.get("doubao")
    if not isinstance(section, dict) or "api_key" not in section:
        return False
    section.pop("api_key", None)
    section.setdefault("base_url", DEFAULT_DOUBAO_BASE_URL)
    section.setdefault("model", DEFAULT_DOUBAO_MODEL)
    _write_config(data)
    return True


def clear_token() -> bool:
    data = load_config()
    section = data.get("mineru")
    if not isinstance(section, dict) or "api_token" not in section:
        return False
    section.pop("api_token", None)
    _write_config(data)
    return True


def config_status() -> dict:
    path = config_path()
    environment_set = bool(os.environ.get("MINERU_API_TOKEN", "").strip())
    data = load_config()
    configured = bool(data.get("mineru", {}).get("api_token")) if path.is_file() else False
    doubao = get_doubao_config()
    return {
        "config_path": str(path),
        "config_token_set": configured,
        "environment_token_set": environment_set,
        "effective_source": "environment" if environment_set else "config" if configured else None,
        "doubao_key_set": bool(doubao["api_key"]),
        "doubao_base_url": doubao["base_url"],
        "doubao_model": doubao["model"],
    }
