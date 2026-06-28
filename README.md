# MinerU OCR

[简体中文](README_zh-CN.md) | English

Long-document OCR orchestration for the [MinerU](https://mineru.net/) Cloud API, packaged as a Python CLI, an MCP server, and a reusable Agent Skill.

MinerU OCR is designed for local PDFs that are larger than a single API request can safely handle. It plans page ranges, uploads and monitors each part, resumes partial failures, downloads the MinerU result archives, and merges the resulting Markdown and referenced assets in source-page order.

> Documents processed by this project are uploaded to MinerU Cloud. Do not use it for data that must remain entirely on-device.

## Background

MinerU provides high-quality document parsing for PDFs, scanned pages, tables, formulas, images, and common Office formats. Its API is asynchronous and applies per-request file/page limits. Calling the API directly is straightforward for a short document, but long PDFs require additional orchestration:

- determine deterministic page ranges;
- avoid uploading an over-limit physical file;
- track several asynchronous tasks as one document;
- retry only failed parts;
- merge Markdown and assets without losing source order.

This project implements that orchestration while leaving OCR inference to MinerU. It complements—not replaces—the official [MinerU Document Extractor Skill and `mineru-open-api` CLI](https://github.com/opendatalab/MinerU-Ecosystem).

## Features

- **Long PDF planning** — groups PDFs into continuous ranges of up to 200 pages.
- **Logical page processing** — for PDFs up to 200 MB, uploads the complete source for each requested range and lets MinerU select the pages server-side.
- **Oversized PDF handling** — physically splits PDFs over 200 MB; generated parts target a conservative 190 MB maximum.
- **Resumable jobs** — persists local job metadata and can retry only failed parts.
- **Ordered Markdown merge** — combines completed parts in original page order with invisible source-page markers.
- **Asset rewriting** — safely extracts result ZIP files and rewrites relative Markdown/HTML resource links.
- **Small Office support** — directly submits DOC/DOCX, PPT/PPTX, and XLS/XLSX files within the configured limits.
- **CLI and MCP interfaces** — supports shell automation and structured Agent tool calls.
- **Per-user credentials** — accepts `MINERU_API_TOKEN` or a local plaintext user configuration file without committing the token to the repository.

## When to Use Which MinerU Tool

| Scenario | Recommended tool |
| --- | --- |
| Small document, URL, image, webpage, Flash mode, or multi-format export | Official [`mineru-open-api`](https://github.com/opendatalab/MinerU-Ecosystem/tree/main/cli/mineru-open-api) / `$mineru-document-extractor` |
| PDF over 200 pages, PDF over 200 MB, resumable processing, or deterministic merge | This project: `mineru-ocr` / `$mineru-ocr` |
| Search, deep reading, or knowledge-base workflows after extraction | [MinerU Document Explorer](https://github.com/opendatalab/MinerU-Document-Explorer) |

## Architecture

```text
Agent Skill / MCP tools / CLI
             │
             ▼
   Local planner and job store
   ├─ page-range planning
   ├─ optional physical PDF splitting
   └─ resumable composite job
             │
             ▼
      MinerU Cloud API v4
   ├─ signed file uploads
   ├─ asynchronous extraction
   └─ result ZIP downloads
             │
             ▼
    Safe extraction and merge
   ├─ ordered Markdown
   ├─ rewritten assets
   └─ provenance manifest
```

## Requirements

- Python 3.10 or newer
- A MinerU API token from the [MinerU API management page](https://mineru.net/apiManage/docs)
- Network access to MinerU and its signed upload/download endpoints

Core dependencies are installed automatically: `httpx`, `pydantic`, `pypdf`, `platformdirs`, and the Python MCP SDK.

## Installation

### 1. Clone and install

```bash
git clone git@github.com:sherwood-shehy/MinerU-OCR.git
cd MinerU-OCR
python -m pip install -e .
```

Install test dependencies when developing:

```bash
python -m pip install -e ".[test]"
```

### 2. Configure the MinerU token

Recommended interactive configuration:

```bash
mineru-ocr config set-token
mineru-ocr config show
```

The token is stored as plaintext in the platform-specific user configuration directory (for example, `%LOCALAPPDATA%\mineru-ocr\config.toml` on Windows). It is not written into this repository.

Alternatively, set an environment variable:

```bash
export MINERU_API_TOKEN="your-token"       # Linux/macOS
```

```powershell
$env:MINERU_API_TOKEN = Read-Host "MinerU Token" -MaskInput
```

Resolution order:

```text
MINERU_API_TOKEN environment variable > user config.toml
```

### 3. Install the Agent Skill

The repository already contains the Skill at `.agents/skills/mineru-ocr`, so Codex discovers it when launched in this repository.

For global use, copy it into the user Skill directory:

```bash
mkdir -p ~/.agents/skills
cp -R .agents/skills/mineru-ocr ~/.agents/skills/mineru-ocr
```

PowerShell:

```powershell
New-Item -ItemType Directory -Force "$HOME\.agents\skills" | Out-Null
Copy-Item -Recurse -Force ".agents\skills\mineru-ocr" "$HOME\.agents\skills\mineru-ocr"
```

Restart Codex or open a new thread, then invoke `$mineru-ocr` explicitly or describe a matching OCR task.

## CLI Usage

### Complete processing flow

```bash
mineru-ocr process "/path/to/document.pdf"
```

Common options:

```bash
mineru-ocr process document.pdf \
  --model vlm \
  --language ch \
  --timeout 1800
```

Defaults are VLM, OCR enabled, Chinese/English recognition, table recognition enabled, and formula recognition enabled.

### Asynchronous and resumable flow

```bash
# Submit and keep the returned local job_id
mineru-ocr submit document.pdf

# Refresh progress; completed jobs are downloaded and merged automatically
mineru-ocr status <job-id>

# Retry failed parts only
mineru-ocr resume <job-id> --timeout 1800

# Discard an unfinished job cache
mineru-ocr clean <job-id>
```

### Token management

```bash
mineru-ocr config show
mineru-ocr config set-token
mineru-ocr config clear-token
```

The `show` command reports only the configuration path and selected source; it never prints the token.

## MCP Server

The package exposes five tools:

- `ocr_process`
- `ocr_submit`
- `ocr_status`
- `ocr_resume`
- `ocr_clean`

Run over stdio:

```bash
mineru-ocr-mcp
```

Example Codex configuration in `~/.codex/config.toml`:

```toml
[mcp_servers.mineru_ocr]
command = "mineru-ocr-mcp"
args = ["--transport", "stdio"]
tool_timeout_sec = 1900
```

Or run a local Streamable HTTP endpoint:

```bash
mineru-ocr-mcp --transport streamable-http --port 8182
```

The HTTP transport binds to `127.0.0.1` by default.

## Processing Rules

### PDFs up to 200 MB

- The source PDF is not physically split.
- PDFs up to 200 pages are uploaded once.
- Longer PDFs are represented as continuous ranges such as `1-200` and `201-364`.
- The complete source is uploaded for each range, and MinerU performs server-side page selection.

### PDFs over 200 MB

- Local physical splitting is enabled.
- Each part contains at most 200 pages.
- Parts above 190 MB are recursively divided until upload-safe.
- The original PDF is never deleted or modified.

### Office files

Small DOC/DOCX, PPT/PPTX, and XLS/XLSX files are submitted directly. The project intentionally does not depend on LibreOffice. If an Office document exceeds the service limits, export it to PDF before processing.

## Output

The core CLI builds a merge bundle beside the source while the composite job completes:

```text
document.pdf.mineru/
├── full.md
├── assets/
│   ├── part-0001/
│   └── part-0002/
└── manifest.json
```

The Agent Skill additionally defines a publication policy for user-selected shared output directories:

- publish `<source-stem>.md` directly in the selected directory;
- avoid overwrites using names such as `<source-stem> (1).md`;
- consolidate resources into a shared `assets/` directory and rewrite references;
- optionally publish `<source-stem>.manifest.json`;
- remove transient `.mineru` bundles only after validating the final Markdown and resources;
- never delete or modify the original source document.

## AI Enhancement

> The AI enhancement layer is a **separate, optional** post-processing step. It does not affect the core OCR pipeline and can be enabled per-run via the `--enhance` flag.

After MinerU extracts the raw Markdown, the optional AI enhancement layer enriches the output with structured metadata: per-image descriptions, section summaries, named entities, cross-references, and tags. The result is written to `full.enhanced.md` alongside the original `full.md` without modifying it.

### Design Background and Considerations

**Why AI enhancement?** MinerU produces human-readable Markdown that preserves the document's visual layout, tables, and images. This is excellent for reading, but AI agents consuming the output benefit from explicit metadata — knowing what a chart describes, which entities appear in each section, and how sections relate to each other — without having to re-read the entire document.

**Single-model approach.** Rather than chaining a vision model for images and a separate LLM for text, the enhancement layer uses **one model** — Doubao-Seed-2.0-lite (via Volcengine Coding Plan) — for both tasks. This simplifies configuration, reduces the number of API dependencies, and ensures the model has full document context when extracting relationships.

**Non-destructive by design.** The original `full.md` is never touched. AI metadata is written to a sibling file (`full.enhanced.md`), so existing workflows that read `full.md` continue unchanged. Users decide when to use the enhanced output.

**Blockquote-separated metadata.** The AI metadata section is wrapped in Markdown blockquotes (`>`), making it visually distinct from the document body while remaining valid Markdown. This also allows downstream tools to extract the metadata block with a simple regex or parser.

**Per-image error tolerance.** A single corrupted or unrecognisable image does not block enhancement of the remaining images or the text analysis. Each image is processed independently, and errors are recorded in the output JSON per image.

**Credential isolation.** The Doubao API key lives in the project `.env` file (gitignored) or environment variables, never in the repository. This matches the existing `MINERU_API_TOKEN` pattern.

### Architecture

```text
             MinerU output
         full.md + assets/
                │
                ▼
  ┌─────────────────────────────┐
  │     Doubao-Seed-2.0-lite    │
  │                             │
  │  1. analyze_text(full.md)   │
  │     → sections, entities,   │
  │       references, tags      │
  │                             │
  │  2. analyze_image(each img) │
  │     → type, summary,        │
  │       elements, findings,   │
  │       keywords              │
  └─────────────────────────────┘
                │
                ▼
        full.enhanced.md
   (original + blockquoted
    AI metadata section)
```

### Output Format

`full.enhanced.md` contains the original document text followed by a `---` separator and a blockquoted AI metadata block:

```text
(original full.md content, unchanged)

---

> ## AI 增强元数据
>
> ### 章节摘要
> | 章节 | 摘要 |
> | ---- | ---- |
> | 一、... | ... |
>
> ### 实体与术语
> | 实体 | 类型 | 说明 |
> | ---- | ---- | ---- |
> | ... | ... | ... |
>
> ### 跨章节关系
> - 章节 A 的 XX 支撑章节 B 的 XX 分析
>
> ### 标签
> `#tag1` `#tag2`
>
> ### 图片语义
> ````json
> [
>   {
>     "file": "assets/xxx.jpg",
>     "type": "line_chart",
>     "summary": "...",
>     "elements": [...],
>     "key_findings": [...],
>     "keywords": [...]
>   }
> ]
> ````
```

### Usage

```bash
# One-shot: process and enhance in one step
mineru-ocr process report.pdf --enhance

# Re-run enhancement on an existing result
mineru-ocr enhance report.pdf.mineru/
```

### Configuration

Set these in `.env` or environment variables:

| Variable | Required | Default |
| ------ | -------- | ------- |
| `DOUBAO_API_KEY` | Yes (when using `--enhance`) | — |
| `DOUBAO_BASE_URL` | No | `https://ark.cn-beijing.volces.com/api/coding/v3` |
| `DOUBAO_MODEL` | No | `doubao-seed-2.0-lite` |

When `DOUBAO_API_KEY` is not set, the `--enhance` flag and `enhance` subcommand produce a clear error message.

### Current Scope

The enhancement layer focuses on single-document metadata extraction. It does **not** currently include:

- Cross-document knowledge graph construction
- Vector embedding or RAG pipeline integration
- Web UI or Dashboard
- Interactive Q&A over the document
- Agentic retrieval workflows

These capabilities are intentionally left to Knowhere and other specialised tools in the ecosystem.

## Reliability and Security

- API tokens are never included in job manifests or public tool responses.
- Signed upload and result URLs are removed from public job summaries.
- Result downloads require HTTPS.
- ZIP extraction rejects absolute paths, `..` traversal, and symbolic links.
- Writes use temporary files/directories and atomic replacement where possible.
- Failed composite jobs remain in the per-user cache for recovery.

## Testing

Run the offline suite:

```bash
python -m pytest --basetemp .test-tmp -p no:cacheprovider
```

The tests cover:

- 199/200/201/400-page planning boundaries;
- repeated full-file uploads with independent page ranges;
- simulated oversized-PDF physical splitting;
- Office size rejection;
- Markdown merge order and asset collision isolation;
- ZIP traversal protection;
- API request shape;
- credential precedence and cleanup.

On restricted Windows environments, keep the explicit `--basetemp` option because the default user temporary directory may be inaccessible.

## Real-World Validation

The workflow has been exercised on a 364-page Chinese technical standard. It completed as two logical ranges (`1-200`, `201-364`) and produced an ordered merged document with 156 headings, 327 HTML tables, and 12 image references. A comparison against the official CLI output showed approximately 99.35% visible-text similarity; the custom merge produced substantially more compact markup for one pathological table section.

## Project Layout

```text
.agents/skills/mineru-ocr/   Agent Skill and MinerU API reference
src/mineru_ocr/              CLI, MCP server, API client, planner, storage, and merge logic
tests/                       Offline unit tests
pyproject.toml               Package metadata, dependencies, and command entry points
```

## Limitations

- OCR is cloud-based, not offline.
- Service limits and response formats may change; consult the current [MinerU API documentation](https://mineru.net/apiManage/docs).
- Large Office documents are not split automatically.
- Physical PDF splitting cannot process a single page that remains above the safe upload threshold.
- Cross-part semantic repair (for example, reconstructing a table split exactly at a page-range boundary) is intentionally not attempted.

## Contributing

Issues and focused pull requests are welcome. Please include tests for behavior changes and run the full offline suite before submitting.

## License

No project license has been declared yet. MinerU and its API are governed by their respective upstream terms and policies.

## References

- [MinerU](https://mineru.net/)
- [MinerU API documentation](https://mineru.net/apiManage/docs)
- [MinerU open-source repository](https://github.com/opendatalab/MinerU)
- [MinerU Ecosystem and official CLI](https://github.com/opendatalab/MinerU-Ecosystem)
- [Model Context Protocol](https://modelcontextprotocol.io/)
