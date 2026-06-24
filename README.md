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
