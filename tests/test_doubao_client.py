import httpx
import pytest
import json

from mineru_ocr import config
from mineru_ocr.doubao_client import DoubaoClient, DoubaoError, _parse_json


def test_parse_json_tolerates_fenced_output():
    assert _parse_json('```json\n{"ok": true}\n```') == {"ok": True}


def test_doubao_client_reads_private_config(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    config.save_doubao_key("private-key")

    captured = {}

    def handler(request: httpx.Request):
        captured["authorization"] = request.headers["Authorization"]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    client = DoubaoClient()
    headers = dict(client.client.headers)
    client.client.close()
    client.client = httpx.Client(transport=httpx.MockTransport(handler), headers=headers)
    assert client.analyze_text("hello") == {"ok": True}
    assert captured["authorization"] == "Bearer private-key"
    client.close()


def test_doubao_client_requires_private_key(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.toml")
    with pytest.raises(DoubaoError, match="set-doubao-key"):
        DoubaoClient()


def test_doubao_image_prompt_includes_document_context(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setattr(config, "config_path", lambda: path)
    config.save_doubao_key("private-key")
    image = tmp_path / "figure.png"
    image.write_bytes(b"image")
    captured = {}

    def handler(request: httpx.Request):
        payload = json.loads(request.content)
        captured["prompt"] = payload["messages"][0]["content"][0]["text"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"type":"diagram","summary":"ok"}'}}]},
        )

    client = DoubaoClient()
    headers = dict(client.client.headers)
    client.client.close()
    client.client = httpx.Client(transport=httpx.MockTransport(handler), headers=headers)

    client.analyze_image(
        image,
        context={
            "caption": "图 A.0.2 爆炸危险区域等级和范围划分图",
            "section_path": ["附录 A 液化石油气供应站爆炸危险区域等级和范围划分"],
        },
    )

    assert "图 A.0.2 爆炸危险区域等级和范围划分图" in captured["prompt"]
    assert "必须优先使用图题" in captured["prompt"]
    client.close()


def test_direct_text_call_rejects_truncation_instead_of_silently_losing_tail():
    client = object.__new__(DoubaoClient)
    client._chat = lambda messages: '{"ok": true}'
    with pytest.raises(DoubaoError, match="segment|limit"):
        client.analyze_text("x" * 90_000)
