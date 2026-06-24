import json

import httpx

from mineru_ocr.client import MinerUClient
from mineru_ocr.models import JobPart, OCROptions


def test_upload_request_shape_and_unique_page_ranges():
    captured = {}

    def handler(request: httpx.Request):
        captured["request"] = request
        return httpx.Response(200, json={
            "code": 0, "msg": "ok", "trace_id": "trace",
            "data": {"batch_id": "batch", "file_urls": ["https://upload/1", "https://upload/2"]},
        })

    client = MinerUClient("secret")
    client.client.close()
    client.client = httpx.Client(transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer secret"})
    parts = [
        JobPart(index=1, local_path="a.pdf", upload_name="a.p1.pdf", data_id="a.1", page_ranges="1-200"),
        JobPart(index=2, local_path="a.pdf", upload_name="a.p2.pdf", data_id="a.2", page_ranges="201-400"),
    ]
    batch, _, trace = client.request_uploads(parts, OCROptions())
    payload = json.loads(captured["request"].content)
    assert batch == "batch" and trace == "trace"
    assert [item["page_ranges"] for item in payload["files"]] == ["1-200", "201-400"]
    assert payload["model_version"] == "vlm"
    client.close()

