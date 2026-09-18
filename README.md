# MinerU OCR

[简体中文](README_zh-CN.md) | English

Long-document OCR orchestration for the [MinerU](https://mineru.net/) Cloud API, packaged as a Python CLI and a reusable Agent Skill.

MinerU OCR is designed for local PDFs that are larger than a single API request can safely handle. It plans page ranges, uploads and monitors each part, resumes partial failures, downloads the MinerU result archives, and merges the resulting Markdown and referenced assets in source-page order.

> `process` and `submit` upload documents to MinerU Cloud. Optional `enhance` sends document text and referenced images to the configured Doubao service. `publish` and `validate` run locally without service credentials.

## What's New in 0.2.0

This release turns OCR results into traceable multimodal knowledge materials: source Markdown, an asset/provenance manifest, and optional AI-derived JSONL.

- **Checked publication.** New `publish`, `validate`, and `process --output-dir` commands deliver Markdown with validated resources. Shared assets use content hashes, document names avoid collisions, and original documents and result bundles are retained.
- **Stable identities and source evidence.** Manifests carry `doc_id`, `asset_id`, source versions, file hashes, and every resource occurrence. Compatible Content List V1 maps images to source PDF pages and bounding boxes; other cases explicitly record a page range or unknown location. Upstream layout JSON is retained in `evidence/`.
- **Structured visual understanding.** Optional AI JSONL separates visible observations from contextual interpretation, with fields for mechanical dimensions, flowchart relationships, and chart content. Dimension, unit, and tolerance strings remain unconverted. Generation metadata, per-image failures, unsupported formats, and review status remain explicit; native SVG assets are preserved.
- **Source fidelity and reliable references.** Fixes preserve empty table cells, numeric lines, HTML images, repeated references, and the correct page ranges. Full, collapsed, and shortcut references are supported; labels are isolated across merged parts so one part cannot redirect another part's image. Enhancement analyzes only the current document's images.
- **Bounded processing and safer retries.** Long lines are split without silent truncation; model input segments are bounded at 40,000 characters and retrieval text chunks at 8,000. Dotted filenames retain distinct outputs, repeated enhancement atomically replaces only its JSONL, and a failed merge can resume after downloads finish.
- **CLI and Skill consolidation.** `mineru-ocr` is the maintained entry point, with an updated Agent Skill and [knowledge-material contract](.agents/skills/mineru-ocr/references/knowledge-materials.md). Python 3.11+ is required; the previous `mineru-ocr-mcp` entry point and MCP dependency have been removed.

Publish first, then enhance the final Markdown so JSONL references use the published asset paths. An `ok` AI result has passed structural validation and still requires review; it is not a verified technical conclusion.

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
- **CLI interface** — supports shell automation and Agent Skill workflows.
- **Per-user credentials** — accepts `MINERU_API_TOKEN` or a local plaintext user configuration file without committing the token to the repository.

## When to Use Which MinerU Tool

| Scenario | Recommended tool |
| --- | --- |
| Small document, URL, image, webpage, Flash mode, or multi-format export | Official [`mineru-open-api`](https://github.com/opendatalab/MinerU-Ecosystem/tree/main/cli/mineru-open-api) / `$mineru-document-extractor` |
| PDF over 200 pages, PDF over 200 MB, resumable processing, or deterministic merge | This project: `mineru-ocr` / `$mineru-ocr` |
| Search, deep reading, or knowledge-base workflows after extraction | [MinerU Document Explorer](https://github.com/opendatalab/MinerU-Document-Explorer) |

## Architecture

```text
Agent Skill / CLI
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

- Python 3.11 or newer
- A MinerU API token from the [MinerU API management page](https://mineru.net/apiManage/docs)
- Network access to MinerU and its signed upload/download endpoints

Core dependencies are installed automatically: `httpx`, `pydantic`, `pypdf`, `platformdirs`, and `python-dotenv`.

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

The offline `publish` command implements publication into user-selected directories. `process --output-dir` invokes it automatically:

- publish `<source-stem>.md` directly in the selected directory;
- avoid overwrites using names such as `<source-stem> (1).md`;
- consolidate resources into a shared `assets/` directory and rewrite references;
- publish `<source-stem>.manifest.json` with document/asset IDs, hashes and source locations;
- retain upstream layout JSON in `evidence/` and use content hashes for shared asset filenames;
- validate references and retain the original `.mineru` result package;
- never delete or modify the original source document.

```bash
mineru-ocr process report.pdf --output-dir knowledge
mineru-ocr process report.pdf --output-dir knowledge --enhance
mineru-ocr publish report.pdf.mineru --output-dir knowledge
mineru-ocr validate knowledge/report.md
```

Publish source materials first, then enhance the published Markdown. `publish` does not migrate old AI JSONL files; earlier outputs remain in the source package. Re-running `enhance` atomically replaces only that Markdown's derived JSONL. See the [knowledge-material contract](.agents/skills/mineru-ocr/references/knowledge-materials.md) for IDs, precise/range/unknown locators, visual evidence, review status and ingestion rules.

## AI Enhancement

> The AI enhancement layer is a **separate, optional** post-processing step. It does not affect the core OCR pipeline and can be enabled per-run via the `--enhance` flag.

After MinerU extracts the raw Markdown, the optional AI enhancement layer creates one retrieval-ready JSONL file. The original Markdown remains the evidence layer and is not modified.

### Design Background and Considerations

**Why AI enhancement?** MinerU produces human-readable Markdown that preserves the document's visual layout, tables, and images. This is excellent for reading, but AI agents consuming the output benefit from explicit metadata — knowing what a chart describes, which entities appear in each section, and how sections relate to each other — without having to re-read the entire document.

**Single-model approach.** The configured Doubao model handles both images and text. Each text call receives one bounded segment; full-document context and relationships across segments are not guaranteed.

**Non-destructive by design.** The original Markdown is never touched. The AI output is written as a sibling `<source>.ai.jsonl` file. If OCR has already produced the Markdown, run `mineru-ocr enhance <markdown-or-result-dir>` directly; OCR is not repeated.

**Chunked text analysis.** Long documents are analyzed in section-aware chunks instead of being silently truncated. Coverage metadata is stored in the first JSONL metadata record.

**Per-image error tolerance.** A single corrupted or unrecognisable image does not block enhancement of the remaining images or the text analysis. Each image is processed independently, and errors are recorded in the output JSON per image.

**Evidence and interpretation.** Visible text and dimension strings remain separate from contextual interpretations. Derived records carry model/prompt versions, source identity and review status. Native SVGs remain referenced but are marked unsupported by the current vision transport. Compatible legacy Content List V1 provides page/bbox locators; other cases explicitly retain range or unknown precision.

**Credential isolation.** The Doubao API key is stored only in the local user configuration via `mineru-ocr config set-doubao-key`. It is not stored in repository files, generated Markdown, manifests, examples, or responses.

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
       <source>.ai.jsonl
```

### Output Format

The enhancement layer writes one AI consumption file beside the source Markdown:

| File | Purpose |
| ---- | ------- |
| `<source>.ai.jsonl` | One JSON object per metadata, text, or image chunk for retrieval and agent workflows. It includes normalized tables, image interpretations, image context, section paths, page ranges, and coverage metadata. |

### Usage

```bash
# One-shot: process and enhance in one step
mineru-ocr process report.pdf --enhance

# Re-run enhancement on an existing result
mineru-ocr enhance report.pdf.mineru/

# Or enhance a published Markdown file
mineru-ocr enhance report.md
```

### Configuration

Configure Doubao locally before using `--enhance`:

```bash
mineru-ocr config set-doubao-key
# Enter: 你的豆包apikey
```

Defaults are `https://ark.cn-beijing.volces.com/api/coding/v3` and `doubao-seed-2.0-lite`. `mineru-ocr config show` reports whether the key is configured without printing it. When the key is missing, the `--enhance` flag and `enhance` subcommand produce a clear error message.

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

Version 0.2.0 passed 68 offline tests on Python 3.12.2. The tests cover:

- 199/200/201/400-page planning boundaries;
- repeated full-file uploads with independent page ranges;
- simulated oversized-PDF physical splitting;
- Office size rejection;
- Markdown merge order and asset collision isolation;
- ZIP traversal protection;
- API request shape;
- credential precedence and cleanup;
- offline publication, filename collisions, missing resources, hash verification, and copy retries;
- stable IDs, source-page mapping, repeated references, and cross-part label isolation;
- table and numeric fidelity, bounded text chunks, current-document image selection, and published-output enhancement.

On restricted Windows environments, keep the explicit `--basetemp` option because the default user temporary directory may be inaccessible.

## Real-World Validation

For 0.2.0, a separate offline acceptance run published an existing 1,545,149-byte Chinese Markdown document with 17 valid resources. Test-double AI responses exercised the enhancement pipeline, producing 251 JSONL records and 18 model input segments with unique IDs. Source content was unchanged apart from published resource targets, and enhancement left the published Markdown unchanged. This verifies local processing, not live OCR or vision-model accuracy.

The workflow has been exercised on a 364-page Chinese technical standard. It completed as two logical ranges (`1-200`, `201-364`) and produced an ordered merged document with 156 headings, 327 HTML tables, and 12 image references. A comparison against the official CLI output showed approximately 99.35% visible-text similarity; the custom merge produced substantially more compact markup for one pathological table section.

## Project Layout

```text
.agents/skills/mineru-ocr/   Agent Skill and MinerU API reference
src/mineru_ocr/              CLI, API client, planner, storage, and merge logic
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
