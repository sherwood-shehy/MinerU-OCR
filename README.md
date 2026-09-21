# MinerU OCR 0.4.1

[简体中文](README_zh-CN.md) | English

Convert original documents into **faithful, traceable, AI-readable Markdown material packages** for ordinary readers, LLM Wikis and RAG systems.

A Python CLI and Agent Skill combine local native PDF extraction, MinerU Cloud OCR, resumable jobs and conservative offline postprocessing. Knowledge synthesis, visual interpretation, embeddings and ingestion belong to downstream systems.

## Changes in 0.4.1

- `preflight` checks every physical PDF page for native text, bad mappings, hidden text, image coverage and sparse/blank pages. A selectable text layer alone is insufficient.
- `process --engine auto` (default) uses PyMuPDF4LLM for eligible PDFs; uncertain/scanned PDFs and failed native quality checks use MinerU Cloud. `--engine local` never uploads; `--engine cloud` explicitly selects the existing cloud path. Mixed PDFs are routed as a whole.
- Local extraction disables OCR, preserves raw page chunks and HTML tables, and checks page coverage, text retention, numeric tokens and detected table cells before publication. Missing dependencies and runtime failures are not silently converted into uploads.
- Both engines share source-page postprocessing, review decisions, image deduplication, portable publication and validation. Native page evidence has its own adapter; it is not labeled as MinerU Content List.
- `doctor` checks package versions/imports and provides setup guidance. Copying a skill does not install its CLI or Python dependencies.

## Changes in 0.4.0

- Portable delivery contains the main Markdown and its referenced resources under `images/`, using relative links.
- Manifests, original-input snapshots, layout evidence and review reports live in a separate processing directory. Readers and basic ingestion do not require them.
- Reviewed independent watermark, stamp, logo and decoration blocks can be excluded. Decisions bind to the input Markdown hash, image hash and exact occurrence lines. Uncertain or informative marks remain; valid image pixels are never erased.
- Byte-identical images share a file while every useful occurrence and caption remains. Similar technical drawings are not merged using perceptual similarity.
- `readable` defaults to a generic source edition and conservative automatic table conversion. `--edition reading` adds navigation and the full-page gallery.
- The extra Doubao enrichment modules, `enhance`, `--enhance`, `--enhance-best-effort` and AI JSONL generation have been removed. Existing outputs and legacy local configuration are retained. MinerU's own OCR/VLM extraction remains.
- gas-std-wiki is an optional adapter, not a mandatory consumer.

## Installation

Python 3.11+ is required. Follow the host's environment policy; use its existing Python.

```sh
python -m pip install -e ".[local]"       # Recommended: auto/local/cloud and PDF postprocessing
python -m pip install -e .                # Minimal cloud-only runtime
python -m pip install -e ".[readable]"    # Cloud plus PDF postprocessing
python -m pip install -e ".[test,local]"  # Complete offline test suite
python -m mineru_ocr.cli doctor
```

Core dependencies: httpx, pydantic, pypdf, platformdirs and python-dotenv. PDF postprocessing uses PyMuPDF. The optional `local` extra pins the tested PyMuPDF/PyMuPDF4LLM/Layout 1.28.2 family; pip resolves its transitive dependencies. No additional OCR engine, LLM service or second local table parser is required. Dependencies are installed into the existing authorized Python environment, not copied into the skill. `doctor` does not install anything; use `python -m mineru_ocr.cli` when the CLI executable is not on PATH.

## Workflow

```sh
mineru-ocr config set-token
mineru-ocr config show
mineru-ocr preflight input.pdf
mineru-ocr process input.pdf --output-dir delivery --work-dir processing
mineru-ocr process input.pdf --engine local --output-dir delivery --work-dir processing
```

`process --engine auto` may upload when cloud processing is selected; configure a token only when that branch is needed. `--engine local` fails rather than uploading an ineligible or rejected PDF. Office inputs use cloud. `submit`, `status` and `resume` remain cloud job operations. `MINERU_API_TOKEN` overrides the local plaintext user configuration; `config show` reports status only. Model/language/OCR flags apply to the cloud backend; the local backend always disables OCR and extracts tables.

With `--output-dir`, adapted PDF results receive source-page postprocessing automatically. Results without supported layout evidence receive portable publication with an explicit limitation. Use `--review-file`, `--name` and `--title` only with one input and `--output-dir`. For source-bound image review, first retain the raw result, run `inspect-images`, then use `readable` on that exact result; do not rerun extraction against an old review hash.

Reuse completed OCR for local processing, without another upload or semantic-model call:

```sh
mineru-ocr publish input.pdf.mineru --output-dir delivery --work-dir processing
mineru-ocr inspect-images input.pdf.mineru --work-dir processing
mineru-ocr readable input.pdf.mineru --source-pdf input.pdf --review-file review.json --output-dir delivery --work-dir processing
mineru-ocr validate "delivery/input（源材料）.md" --work-dir processing
```

The review file is optional. `inspect-images` returns an inventory, a local Markdown gallery and an empty review template; it never guesses removals. Review images against source pages before adding decisions. See [postprocessing and review schemas](docs/readable-workflow.md) (Chinese) or the [Skill reference](.agents/skills/mineru-ocr/references/postprocessing.md) (English).

`readable` requires the matching original PDF, recorded hash/page count and adapted MinerU Content List or native page evidence. Unsupported evidence remains available; use `publish` when precise postprocessing is unavailable. Native headings and the printed TOC are preserved; generated page links use physical PDF page numbers.

## Delivery and processing records

```text
delivery/
  document.md
  images/
    <sha256>.png

processing/
  <record keyed by absolute delivery Markdown path>/
    document.md
    document.manifest.json
    images/
    evidence/
    document.来源说明.md
    document.定位与图片清单.md
    document.校勘与缺口.md
```

The three reports are generated by `readable` and remain internal. `--work-dir` must be separate from, and not nested within or above, the delivery directory. If omitted it defaults to `mineru-ocr/deliveries` under the platform user cache. Use an explicit persistent directory for long-term provenance; commands return the actual record and report paths.

Move the Markdown and referenced `images/` together. No sidecar is required for ordinary reading or basic ingestion. Multiple documents may share the directory: existing documents are never overwritten, and identical assets are reused. A document without resources needs no empty image directory.

At its recorded location, `validate --work-dir processing` checks recorded hashes, evidence, reports, references and generated anchors. After relocation without records it reports `validation_scope: references`: existence and anchor checks only, not historical integrity verification. Automatic rebinding of relocated records is not implemented.

Source-page checks are ordinary links such as `[Page 12](images/<hash>.png)`. Figure embeds use `![Figure 1](images/<hash>.png)`. HTML tables and math still depend on reader support.

## Fidelity boundaries

Simple rectangular tables with explicit or source-reviewed headers can become GFM pipe tables after cell round-trip checks. Merged cells, multiple headers and rich content retain HTML. Use `--table-format html` to retain every HTML table.

Reviewed text corrections require exact before/after strings, expected counts, physical PDF pages and reasons. Layout-backed running-header cleanup and heading normalization protect tables, display math and fenced code. Unknown positions stay unknown.

Image removal requires the input and image hashes, explicit lines, an invalid-block kind, `independent: true` and a reason. Repetition, size or page position alone is insufficient. Informative approval/version/source marks remain. Original files and complete source-page evidence are retained. Deduplication compares bytes, not inferred meaning.

Structural validation is not a measured OCR accuracy score. Inspect representative formulas, complex/continued tables, figures with units and appendix boundaries.

## Jobs and limits

```sh
mineru-ocr submit input.pdf
mineru-ocr status JOB_ID
mineru-ocr resume JOB_ID
```

The client plans up to 200 pages per range and physically splits PDFs above its 200 MB threshold, targeting 190 MB fragments. These are configured client limits, not promises about current cloud quotas. Defaults: vlm model, ch language, OCR/tables/formulas enabled. Small Office inputs support explicit `--page-ranges`; oversized Office inputs need PDF export.

Without `process --output-dir`, cloud processing returns a raw `.mineru` bundle; local processing returns an immutable raw bundle under `--work-dir/native/<run-id>` (default: the processing cache). Rejected local candidates and their quality reports remain there for diagnosis. Retain timed-out cloud job IDs and resume; do not resubmit unnecessarily. Use `clean JOB_ID` only for intentionally discarded cloud job data.

## Development and migration

Version 0.4.1 passed **110 offline tests**, including all-page routing, no-upload local mode, dependency/runtime failures, native publication, blank-page preservation, numeric/symbol/script-formatting checks and independent merged-cell rejection. See the [0.4.1 validation record](docs/v0.4.1-validation.md).

```sh
python -m pytest
```

Version 0.4.0 passed **93 offline tests**. Reusing the 108-page GB 6932—2015 OCR produced one Markdown and 131 referenced images, with 8 GFM tables and 48 retained HTML tables. Independent GFM rendering preserved all 93 cells across the 8 conversions; relocation without records passed reference checks. See the [validation record](docs/v0.4.0-validation.md) (Chinese).

Skill source: [.agents/skills/mineru-ocr](.agents/skills/mineru-ocr/SKILL.md). Deterministic rules belong in code; the skill coordinates source review and delivery. Embedded document instructions are treated as source content.

0.3.x migration: manifests and reports are no longer public companions; `publish --image-dir` is retired in favor of fixed `images/`; extra AI enrichment commands are retired. Existing artifacts are not automatically deleted or migrated. Republish old bundles for the new package structure. See [CHANGELOG](CHANGELOG.md).
