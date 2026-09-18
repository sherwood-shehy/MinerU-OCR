import json
from pathlib import Path

from mineru_ocr.enhancer import enhance_output


class FakeEnhancementClient:
    def __init__(self):
        self.text_calls = []
        self.image_contexts = []

    def analyze_image(self, image_path: str | Path, *, context: dict | None = None) -> dict:
        self.image_contexts.append(context or {})
        return {
            "type": "diagram",
            "summary": f"semantic summary for {Path(image_path).name}",
            "visual_description": "visible diagram",
            "contextual_interpretation": f"context for {context.get('caption')}" if context else "",
            "elements": ["node"],
            "key_findings": ["important visual finding"],
            "context_consistency": "high",
            "uncertainty": "",
            "keywords": ["diagram"],
        }

    def analyze_text(self, markdown: str) -> dict:
        self.text_calls.append(markdown)
        return {
            "sections": [{"title": "Title", "summary": "section summary"}],
            "entities": [{"name": "Entity", "type": "term", "description": "desc"}],
            "cross_references": [],
            "tags": ["tag"],
        }


def test_enhance_directory_writes_ai_derivatives_and_legacy_file(tmp_path):
    result_dir = tmp_path / "sample.pdf.mineru"
    (result_dir / "assets").mkdir(parents=True)
    (result_dir / "assets" / "figure.png").write_bytes(b"image")
    (result_dir / "full.md").write_text(
        "<!-- MinerU source pages 1-2 -->\n\n# Title\n\n![fig](assets/figure.png)\n\n1\n",
        encoding="utf-8",
    )

    result = enhance_output(result_dir, client=FakeEnhancementClient())

    assert Path(result["ai_jsonl"]).is_file()
    assert "ai_markdown" not in result
    assert "images_json" not in result
    assert "manifest" not in result
    assert "legacy_markdown" not in result

    chunks = [
        json.loads(line)
        for line in Path(result["ai_jsonl"]).read_text(encoding="utf-8").splitlines()
    ]
    assert any(chunk["type"] == "document_metadata" for chunk in chunks)
    assert any(chunk["type"] == "text" for chunk in chunks)
    assert any(chunk["type"] == "image" for chunk in chunks)
    assert any("semantic summary for figure.png" in chunk.get("text", "") for chunk in chunks)


def test_enhance_published_markdown_uses_source_stem(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "figure.png").write_bytes(b"image")
    md = tmp_path / "report.md"
    md.write_text("# Report\n\n![fig](assets/figure.png)\n", encoding="utf-8")

    result = enhance_output(md, client=FakeEnhancementClient())

    assert Path(result["ai_jsonl"]).name == "report.ai.jsonl"
    assert "ai_markdown" not in result


def test_long_text_is_segmented_before_model_calls(tmp_path):
    md = tmp_path / "long.md"
    md.write_text("# A\n\n" + ("x" * 45_000) + "\n\n# B\n\nbody", encoding="utf-8")
    client = FakeEnhancementClient()

    result = enhance_output(md, client=client)

    assert len(client.text_calls) >= 2
    assert result["text_coverage"]["segments"] == len(client.text_calls)


def test_ai_outputs_normalize_html_tables_for_model_consumption(tmp_path):
    md = tmp_path / "table.md"
    md.write_text(
        "# Data\n\n"
        '<table><tr><td>地区等级</td><td>强度设计系数</td></tr>'
        '<tr><td>一级地区</td><td>0.72</td></tr>'
        '<tr><td>二级地区</td><td>0.60</td></tr></table>\n\n'
        "<div>说明<br>下一行</div>\n",
        encoding="utf-8",
    )

    result = enhance_output(md, client=FakeEnhancementClient())

    rows = [json.loads(line) for line in Path(result["ai_jsonl"]).read_text(encoding="utf-8").splitlines()]
    assert all("<table" not in row.get("text", "") for row in rows)
    combined = "\n".join(row.get("text", "") for row in rows)
    assert "<td>" not in combined
    assert "<div>" not in combined
    assert "表格 1:" in combined
    assert "| 地区等级 | 强度设计系数 |" in combined
    assert "| 一级地区 | 0.72 |" in combined
    assert "说明\n下一行" in combined


def test_ai_table_normalization_handles_spanning_headers(tmp_path):
    md = tmp_path / "spanning.md"
    md.write_text(
        "# Level\n\n"
        '<table><tr><td rowspan="2">级别</td><td colspan="2">储罐容积</td></tr>'
        "<tr><td>总容积</td><td>单罐容积</td></tr>"
        "<tr><td>一级</td><td>5000</td><td>1000</td></tr></table>",
        encoding="utf-8",
    )

    result = enhance_output(md, client=FakeEnhancementClient())

    rows = [json.loads(line) for line in Path(result["ai_jsonl"]).read_text(encoding="utf-8").splitlines()]
    combined = "\n".join(row.get("text", "") for row in rows)
    assert "| 级别 | 储罐容积/总容积 | 储罐容积/单罐容积 |" in combined
    assert "| 一级 | 5000 | 1000 |" in combined


def test_image_analysis_receives_document_context_and_chunks_keep_it(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "figure.png").write_bytes(b"image")
    md = tmp_path / "report.md"
    md.write_text(
        "# 附录 A 液化石油气供应站爆炸危险区域等级和范围划分\n\n"
        "A.0.2 通风良好的生产性建筑爆炸危险区域等级和范围如下。\n\n"
        "1 以释放源为中心，半径为15.0m的范围宜划分为2区。\n\n"
        "![fig](assets/figure.png)\n"
        "图 A.0.2 通风良好的生产性建筑爆炸危险区域等级和范围划分图\n"
        "1 二级释放源；2 门或窗\n",
        encoding="utf-8",
    )
    client = FakeEnhancementClient()

    result = enhance_output(md, client=client)

    context = client.image_contexts[0]
    assert context["caption"] == "图 A.0.2 通风良好的生产性建筑爆炸危险区域等级和范围划分图"
    assert context["section_path"] == ["附录 A 液化石油气供应站爆炸危险区域等级和范围划分"]
    assert "液化石油气供应工程" in context["document_hint"]
    chunks = [json.loads(line) for line in Path(result["ai_jsonl"]).read_text(encoding="utf-8").splitlines()]
    image_chunk = next(chunk for chunk in chunks if chunk["type"] == "image")
    assert image_chunk["section_path"] == context["section_path"]
    assert "图 A.0.2" in image_chunk["text"]
    assert image_chunk["metadata"]["context"]["caption"] == context["caption"]


def _run_source(tmp_path, text, name="report.md", client=None):
    source = tmp_path / name
    source.write_text(text, encoding="utf-8")
    result = enhance_output(source, client=client or FakeEnhancementClient())
    rows = [json.loads(line) for line in Path(result["ai_jsonl"]).read_text(encoding="utf-8").splitlines()]
    assert source.read_text(encoding="utf-8") == text
    return result, rows


def test_empty_table_cells_do_not_shift_values(tmp_path):
    _, rows = _run_source(tmp_path, '<table><tr><th>Item</th><th>Min</th><th>Max</th></tr>'
                          '<tr><td>A</td><td></td><td>20</td></tr></table>')
    assert "| A |  | 20 |" in "\n".join(row["text"] for row in rows)


def test_matching_header_label_does_not_swallow_first_data_row(tmp_path):
    _, rows = _run_source(tmp_path, '<table><tr><th>Type</th><th>Description</th></tr>'
                          '<tr><td>Type</td><td>value A</td></tr><tr><td>B</td><td>value B</td></tr></table>')
    assert "| Type | value A |" in "\n".join(row["text"] for row in rows)


def test_numeric_source_lines_are_preserved(tmp_path):
    _, rows = _run_source(tmp_path, "# Values\n900\n1/2\n")
    body = "\n".join(row["text"] for row in rows if row["type"] == "text")
    assert "\n900\n1/2" in body


def test_only_current_document_images_are_analyzed(tmp_path):
    (tmp_path / "assets").mkdir()
    for name in ["a.png", "b.png"]:
        (tmp_path / "assets" / name).write_bytes(name.encode())
    result, rows = _run_source(tmp_path, "# A\n![A](assets/a.png)\n")
    assert result["image_count"] == 1
    assert [row["source_ref"] for row in rows if row["type"] == "image"] == ["assets/a.png"]


def test_dotted_source_names_do_not_overwrite_each_other(tmp_path):
    first, _ = _run_source(tmp_path, "# First", "report.v1.md")
    original = Path(first["ai_jsonl"]).read_bytes()
    second, _ = _run_source(tmp_path, "# Second", "report.v2.md")
    assert Path(first["ai_jsonl"]).name == "report.v1.ai.jsonl"
    assert Path(second["ai_jsonl"]).name == "report.v2.ai.jsonl"
    assert Path(first["ai_jsonl"]).read_bytes() == original


def test_page_boundary_flushes_previous_source_range(tmp_path):
    _, rows = _run_source(tmp_path, "<!-- MinerU source pages 1-2 -->\n# First\nA\n"
                          "<!-- MinerU source pages 3-4 -->\n# Second\nB\n")
    texts = [row for row in rows if row["type"] == "text"]
    assert [row["page_range"] for row in texts] == [[1, 2], [3, 4]]


def test_html_image_keeps_reference_and_context(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/a.png").write_bytes(b"image")
    _, rows = _run_source(tmp_path, '# Image\n<img src="assets/a.png" alt="A">\n图 1 示例\n')
    assert any("assets/a.png" in row["assets"] for row in rows if row["type"] == "text")
    image = next(row for row in rows if row["type"] == "image")
    assert image["section_path"] == ["Image"]
    assert image["metadata"]["context"]["caption"] == "图 1 示例"


def test_long_single_line_reaches_model_without_truncation(tmp_path):
    from mineru_ocr.doubao_client import DoubaoClient
    client = object.__new__(DoubaoClient)
    sent = []
    def chat(messages):
        sent.append(messages[0]["content"])
        return '{"sections": [], "entities": [], "cross_references": [], "tags": []}'
    client._chat = chat
    result, rows = _run_source(tmp_path, "# Long\n" + "x" * 90_000 + "TAIL_REQUIRED", client=client)
    assert sum(message.count("x") for message in sent) == 90_000
    assert "TAIL_REQUIRED" in sent[-1]
    assert all("[…truncated…]" not in message for message in sent)
    assert max(len(row["text"]) for row in rows if row["type"] == "text") <= 8000


def test_published_enrichment_keeps_asset_identity_and_exact_locator(tmp_path):
    from mineru_ocr.publish import publish_output
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/figure.png").write_bytes(b"image")
    md = tmp_path / "source.md"
    md.write_text("# Figure\n![a](assets/figure.png)\n", encoding="utf-8")
    (tmp_path / "source.manifest.json").write_text(json.dumps({
        "source_sha256": "b" * 64,
        "asset_locations": {"assets/figure.png": [{"precision": "page_bbox", "page": 7,
          "page_range": [7, 7], "bbox": [1, 2, 30, 40], "coordinate_system": "mineru_content_list_normalized_0_1000"}]}
    }), encoding="utf-8")
    before = enhance_output(md, client=FakeEnhancementClient())
    published = publish_output(md, tmp_path / "out")
    after = enhance_output(published["markdown"], client=FakeEnhancementClient())
    def image(path):
        return next(json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if json.loads(line)["type"] == "image")
    a, b = image(before["ai_jsonl"]), image(after["ai_jsonl"])
    assert a["asset_id"] == b["asset_id"]
    assert a["id"] == b["id"]
    assert b["page_range"] == [7, 7]
    assert b["source_locations"][0]["bbox"] == [1, 2, 30, 40]
    assert b["provenance_kind"] == "ai_generated"
    assert b["review_status"] == "unreviewed"


def test_native_svg_is_preserved_and_explicitly_not_sent_as_jpeg(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/native.svg").write_text('<svg/>', encoding="utf-8")
    client = FakeEnhancementClient()
    _, rows = _run_source(tmp_path, "# Vector\n![v](assets/native.svg)", client=client)
    image = next(row for row in rows if row["type"] == "image")
    assert image["analysis_status"] == "unsupported"
    assert client.image_contexts == []
    assert image["assets"] == ["assets/native.svg"]


def test_model_cannot_override_asset_reference(tmp_path):
    class BadClient(FakeEnhancementClient):
        def analyze_image(self, path, *, context=None):
            return {**super().analyze_image(path, context=context), "file": "wrong.png", "asset_id": "wrong", "context": {}}
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/a.png").write_bytes(b"a")
    _, rows = _run_source(tmp_path, "# Source\n![a](assets/a.png)", client=BadClient())
    image = next(row for row in rows if row["type"] == "image")
    assert image["source_ref"] == "assets/a.png"
    assert image["asset_id"].startswith("asset-")


def test_visual_failure_is_exposed_in_coverage(tmp_path):
    class BrokenClient(FakeEnhancementClient):
        def analyze_image(self, path, *, context=None):
            return {"summary": ["invalid type"]}
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/a.png").write_bytes(b"a")
    result, rows = _run_source(tmp_path, "![a](assets/a.png)", client=BrokenClient())
    image = next(row for row in rows if row["type"] == "image")
    assert image["analysis_status"] == "failed"
    assert result["image_coverage"]["failed"] == 1
    assert image["review_status"] == "needs_review"


def test_reference_style_image_in_another_section_is_still_linked(tmp_path):
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets/a.png').write_bytes(b'image')
    _, rows = _run_source(tmp_path, '# Figure\n![A][figure]\n\n# Links\n[figure]: assets/a.png\n')
    assert any(row['type'] == 'text' and 'assets/a.png' in row['assets'] for row in rows)


def test_duplicate_image_content_has_unique_chunk_ids(tmp_path):
    (tmp_path / 'assets').mkdir()
    for name in ['a.png', 'b.png']:
        (tmp_path / 'assets' / name).write_bytes(b'same-image')
    _, rows = _run_source(tmp_path, '# Images\n![A](assets/a.png)\n![B](assets/b.png)\n')
    ids = [row['id'] for row in rows]
    assert len(ids) == len(set(ids))
