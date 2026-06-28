"""Doubao client for the AI enhancement layer.

Talks to the Volcengine Coding Plan endpoint (OpenAI-compatible) and exposes
two high-level helpers: :func:`DoubaoClient.analyze_image` for vision and
:func:`DoubaoClient.analyze_text` for text-only metadata extraction.
"""

from __future__ import annotations

import base64
import json
import os
import random
import re
import time
from pathlib import Path

import httpx

from .errors import MinerUOCRError


DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"
DEFAULT_MODEL = "doubao-seed-2.0-lite"

# Conservative cap to keep prompt payloads under model context window. Long
# Markdown is truncated at this many characters before being sent. Doubao-Seed
# advertises a generous window but the lite tier has lower practical limits.
DEFAULT_TEXT_TRUNCATE_CHARS = 80_000


class DoubaoError(MinerUOCRError):
    """Raised when Doubao returns a non-success response or response parsing fails."""


def _strip_code_fences(text: str) -> str:
    """Remove ```json ... ``` style fences and return the inner JSON body."""
    stripped = text.strip()
    if not stripped:
        return stripped
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    return match.group(1) if match else stripped


def _parse_json(text: str) -> dict:
    """Parse Doubao JSON output, tolerating fenced blocks and leading prose."""
    candidate = _strip_code_fences(text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Fall back to extracting the first balanced { ... } block.
        match = re.search(r"\{.*\}", candidate, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                raise DoubaoError(f"Doubao returned malformed JSON: {exc}") from exc
        raise DoubaoError("Doubao response did not contain JSON")


_IMAGE_PROMPT = """你是文档图片分析专家。分析这张从文档中提取的图片，并仅输出 JSON：

{
  "type": "图片类型",
  "summary": "一句话概括图片核心内容",
  "elements": ["图片中的关键视觉元素，3-8 个"],
  "key_findings": ["从图片中能得出的关键结论，1-5 条；若是纯装饰图请返回空数组"],
  "keywords": ["可用于检索的关键词，5-10 个"]
}

type 取值：line_chart（折线图）| bar_chart（柱状图）| pie_chart（饼图）| table（表格截图）| diagram（流程/示意图）| photo（实物照片）| screenshot（界面截图）| other（其他）

要求：
1. 仅输出 JSON，不要任何额外文字、不要解释、不要 Markdown 围栏
2. 如果该图片仅是 logo 或装饰，summary 用"装饰性图片"，key_findings 留空数组
"""


_TEXT_PROMPT = """你是文档分析专家。请基于下列文档原文，提取结构化元数据。仅输出 JSON：

{
  "sections": [
    {"title": "章节标题（保持原文用词）", "summary": "该章节核心内容一句话摘要"}
  ],
  "entities": [
    {"name": "实体名称", "type": "organization|person|location|metric|concept|term", "description": "简要说明"}
  ],
  "cross_references": [
    "用一句话描述章节之间的内容关联，若无明显关联返回空数组"
  ],
  "tags": ["3-8 个文档标签，例如 #燃气行业 #2025 #统计数据"]
}

要求：
1. 仅输出 JSON，不要任何额外文字、不要 Markdown 围栏
2. 不要重写或润色原文；只提取客观存在的信息
3. 不要编造未在原文中出现的实体或关系
4. sections 按文档顺序排列

文档原文：
---
{markdown}
---
"""


class DoubaoClient:
    """Thin wrapper around the Volcengine Coding Plan chat-completion endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ):
        api_key = (api_key or os.environ.get("DOUBAO_API_KEY", "")).strip()
        if not api_key:
            raise DoubaoError(
                "DOUBAO_API_KEY is required. Set it in the environment or project .env file."
            )
        self.base_url = (base_url or os.environ.get("DOUBAO_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("DOUBAO_MODEL") or DEFAULT_MODEL
        self.client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=20.0),
            follow_redirects=True,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ---------- public helpers ----------

    def analyze_image(self, image_path: str | Path) -> dict:
        """Send a local image to Doubao and return its structured semantics."""
        path = Path(image_path)
        if not path.is_file():
            raise DoubaoError(f"Image not found: {path}")
        mime = _guess_mime(path)
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        content = [
            {"type": "text", "text": _IMAGE_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
        ]
        raw = self._chat([{"role": "user", "content": content}])
        return _parse_json(raw)

    def analyze_text(self, markdown: str, *, truncate_chars: int = DEFAULT_TEXT_TRUNCATE_CHARS) -> dict:
        """Send the document Markdown to Doubao and return structured metadata."""
        body = markdown.strip()
        if not body:
            raise DoubaoError("Cannot analyze empty Markdown")
        if len(body) > truncate_chars:
            body = body[:truncate_chars] + "\n\n[…truncated…]"
        prompt = _TEXT_PROMPT.replace("{markdown}", body)
        raw = self._chat([{"role": "user", "content": prompt}])
        return _parse_json(raw)

    # ---------- transport ----------

    def _chat(self, messages: list[dict]) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {"model": self.model, "messages": messages, "temperature": 0.2}
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                response = self.client.post(url, json=payload)
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                data = response.json()
                return _extract_content(data)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(min(2 ** attempt, 8) + random.random() * 0.25)
        raise DoubaoError(f"Doubao request failed after retries: {last_error}") from last_error


def _guess_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(suffix, "image/jpeg")


def _extract_content(data: dict) -> str:
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DoubaoError(f"Doubao response missing choices: {data}") from exc
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # Some OpenAI-compatible servers return [{type:'text', text:'...'}].
        parts = [item.get("text", "") for item in content if isinstance(item, dict)]
        return "".join(parts)
    raise DoubaoError(f"Doubao response content is not a string: {content!r}")
