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
