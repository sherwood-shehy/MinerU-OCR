# MinerU OCR 0.4.3

[简体中文](README_zh-CN.md) | English

Convert original documents into **faithful, traceable, AI-readable Markdown material packages** for ordinary readers, LLM Wikis and RAG systems.

A Python CLI and Agent Skill combine local native PDF extraction, MinerU Cloud OCR, resumable jobs and conservative offline postprocessing. Knowledge synthesis, visual interpretation, embeddings and ingestion belong to downstream systems.

## Changes in 0.4.3

- Distinguish native dotted contents from uncertain tables using visible entries, aligned page numbers and their order. Recognize continuation pages and model proposals covering only a fragment of a verified contents block.
- Apply exclusions only inside that block and record the evidence in preflight diagnostics. Images, ruling and other tables on the same page retain their existing routing. No new dependencies or OCR service calls.
- The 19-page GB/T 33349—2016 sample now passes its two contents pages and correctly routes to cloud at the merged table on physical page 8. See the [0.4.3 validation record](docs/v0.4.3-validation.md).

## Changes in 0.4.2

- Screen native-text PDFs for table risks before extraction. Merged/irregular tables, raster tables and uncertain structures route the whole PDF to MinerU Cloud; clear native text and simple ruled tables prefer local extraction. Ordinary illustrations alone do not force cloud.
- Reuse the pinned Layout image model and source grid geometry, without adding dependencies or local OCR. Suspected borderless raster tables also route to cloud. Preflight remains offline; missing runtime components stop rather than silently uploading.
- Simplify local acceptance: reuse simple table cells cached by preflight instead of repeating detection and rebuilding complex span matrices. Keep page coverage, text, numeric and technical-symbol checks, and auto fallback on basic integrity failure. Local-only never uploads.
- Convert simple all-td tables using a recorded textual-first-row header convention; column count and cell length no longer prevent Markdown. Merged/multi-header/rich tables remain HTML. Ambiguous empty or numeric-only headers still require review.
- Default delivery contains Markdown and body images only, with relative links and exact-byte deduplication. Full-page PDF screenshots and repetitive verification links require an explicit reading edition.
- Both engines share conservative formatting and reviewed corrections. Detection and validation are not semantic accuracy guarantees; inspect representative complex tables and formulas.

## Changes in 0.4.0

- Portable delivery contains the main Markdown and its referenced resources under `images/`, using relative links.
- Manifests, original-input snapshots, layout evidence and review reports live in a separate processing directory. Readers and basic ingestion do not require them.
- Reviewed independent watermark, stamp, logo and decoration blocks can be excluded. Decisions bind to the input Markdown hash, image hash and exact occurrence lines. Uncertain or informative marks remain; valid image pixels are never erased.
- Byte-identical images share a file while every useful occurrence and caption remains. Similar technical drawings are not merged using perceptual similarity.
- `readable` defaults to a generic source edition and conservative automatic table conversion. It generates no full-page screenshots or per-clause verification links; `images/` contains body resources. Explicit `--edition reading` adds navigation, source links and the full-page gallery.
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

Core dependencies: httpx, pydantic, pypdf, platformdirs and python-dotenv. PDF postprocessing uses PyMuPDF. Full table-aware preflight and automatic routing require the `local` extra. The optional `local` extra pins the tested PyMuPDF/PyMuPDF4LLM/Layout 1.28.2 family; pip resolves its transitive dependencies. No additional OCR engine, LLM service or second local table parser is required. Dependencies are installed into the existing authorized Python environment, not copied into the skill. `doctor` does not install anything; use `python -m mineru_ocr.cli` when the CLI executable is not on PATH.

## Workflow

```sh
mineru-ocr config set-token
mineru-ocr config show
mineru-ocr preflight input.pdf
mineru-ocr process input.pdf --output-dir delivery --work-dir processing
mineru-ocr process input.pdf --engine local --output-dir delivery --work-dir processing
```

`process --engine auto` may upload when cloud processing is selected; configure a token only when that branch is needed. `--engine local` fails rather than uploading an ineligible or rejected PDF. Office inputs use cloud. `submit`, `status` and `resume` remain cloud job operations. `MINERU_API_TOKEN` overrides the local plaintext user configuration; `config show` reports status only. Model/language/OCR flags apply to the cloud backend; the local backend always disables OCR and extracts tables.

Preflight distinguishes native dotted contents blocks from table proposals using visible entries and aligned, ordered page numbers. It also handles continuation pages and model boxes covering only part of a verified contents block. Exclusions are recorded in `tables.non_table_regions`; they do not exempt other tables on that page. Missing leaders, ambiguous rows, images or ruling keep the conservative route. See the [routing details](docs/readable-workflow.md) (Chinese).

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

Figure embeds use `![Figure 1](images/<hash>.png)`. Source-page mappings stay in the processing records; default delivery does not duplicate PDF pages as images. Only explicit `--edition reading` renders the full-page verification gallery. HTML tables and math still depend on reader support.

## Fidelity boundaries

Simple rectangular tables with explicit headers, source-reviewed headers or a complete textual first row can become GFM pipe tables after cell round-trip checks. For all-td tables, the first textual row is conventionally treated as a header and this basis is recorded; it is not semantic header recognition. Column count and text length alone do not prevent conversion. Merged cells, multiple headers and rich content retain HTML. Use `--table-format html` to retain every HTML table.

Reviewed text corrections require exact before/after strings, expected counts, physical PDF pages and reasons. Layout-backed running-header cleanup and heading normalization protect tables, display math and fenced code. Unknown positions stay unknown.

Image removal requires the input and image hashes, explicit lines, an invalid-block kind, `independent: true` and a reason. Repetition, size or page position alone is insufficient. Informative approval/version/source marks remain. Original files and complete source-page evidence are retained. Deduplication compares bytes, not inferred meaning.

Structural validation is not a measured OCR accuracy score. Inspect representative formulas, complex/continued tables, figures with units and appendix boundaries.

Preflight warnings do not bypass publication checks. Undecodable source glyphs cannot be silently dropped to pass; unresolved characters still reject the native candidate. See the [exact preflight thresholds](docs/readable-workflow.md) (Chinese).

## Jobs and limits

```sh
mineru-ocr submit input.pdf
mineru-ocr status JOB_ID
mineru-ocr resume JOB_ID
```

The client plans up to 200 pages per range and physically splits PDFs above its 200 MB threshold, targeting 190 MB fragments. These are configured client limits, not promises about current cloud quotas. Defaults: vlm model, ch language, OCR/tables/formulas enabled. Small Office inputs support explicit `--page-ranges`; oversized Office inputs need PDF export.

Without `process --output-dir`, cloud processing returns a raw `.mineru` bundle; local processing returns an immutable raw bundle under `--work-dir/native/<run-id>` (default: the processing cache). Rejected local candidates and their quality reports remain there for diagnosis. Retain timed-out cloud job IDs and resume; do not resubmit unnecessarily. Use `clean JOB_ID` only for intentionally discarded cloud job data.

## Development and migration

Version 0.4.3 passed **166 offline tests**, including 19 new contents regressions and checks using the pinned layout model. The real PDF retest used local preflight only. See the [0.4.3 validation record](docs/v0.4.3-validation.md).

Version 0.4.2 passed **147 offline tests** and screened 10 real PDFs (400 pages). One eligible native sample was subsequently rejected for formatting/symbol issues; no live cloud OCR was run. Details and limits are in the [0.4.2 validation record](docs/v0.4.2-validation.md).

Version 0.4.1 passed **110 offline tests**, including all-page routing, no-upload local mode, dependency/runtime failures, native publication, blank-page preservation, numeric/symbol/script-formatting checks and independent merged-cell rejection. See the [0.4.1 validation record](docs/v0.4.1-validation.md).

```sh
python -m pytest
```

Version 0.4.0 passed **93 offline tests**. Reusing the 108-page GB 6932—2015 OCR produced one Markdown and 131 referenced images, with 8 GFM tables and 48 retained HTML tables. Independent GFM rendering preserved all 93 cells across the 8 conversions; relocation without records passed reference checks. See the [validation record](docs/v0.4.0-validation.md) (Chinese).

Skill source: [.agents/skills/mineru-ocr](.agents/skills/mineru-ocr/SKILL.md). Deterministic rules belong in code; the skill coordinates source review and delivery. Embedded document instructions are treated as source content.

0.3.x migration: manifests and reports are no longer public companions; `publish --image-dir` is retired in favor of fixed `images/`; extra AI enrichment commands are retired. Existing artifacts are not automatically deleted or migrated. Republish old bundles for the new package structure. See [CHANGELOG](CHANGELOG.md).
