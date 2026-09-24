# Changelog

## 0.4.3 — 2026-09-24

- Exclude native dotted table-of-contents blocks from uncertain-table findings, including continuation pages and fragmented model proposals. Verify visible text, ordered/aligned page references and a heading or subsection identifiers; keep original model boxes and the exclusion evidence in preflight diagnostics.
- Limit exclusions to contained regions without images or ruling. Other tables on the same page retain their normal routing; ambiguous contents layouts remain conservative cloud candidates. No new dependency or OCR call.

## 0.4.2 — 2026-09-23

- Route complex/irregular, image-based and uncertain tables to cloud during preflight. Reuse the pinned Layout image model, source ruling geometry and aligned raster-text hints; no new dependency, local OCR or semantic enrichment service.
- Complete basic checks on every page, but skip remaining model inference once a whole-document cloud route is established; report skipped table checks explicitly.
- Cache simple source table cells for basic acceptance; remove repeated post-extraction detection and general span-matrix reconstruction. Retain page, text, numeric, symbol and abnormal-character safeguards.
- Convert simple all-td tables using a recorded textual-first-row header convention. Remove width/cell-length cutoffs; preserve merged/multi-header/rich tables and ambiguous headers as HTML.
- Update the reusable/global skill, bilingual documentation and regression fixtures. Record real-file routing checks and known heuristic limitations.

- Prefer native-text PDF attempts by separating preflight warnings from blocking findings. Allow short titles, isolated mapping defects, minority hidden text and illustrated native pages; retain scan/header and serious-corruption safeguards. Report visible text, mapping/hidden ratios and warning pages without adding dependencies.
- Ignore off-page glyphs and duplicate overpainting in visible-text counts so a repeatedly painted scan header cannot masquerade as a native body.
- Reject native candidates that silently drop unresolved source glyphs, and check non-whitespace control characters in extracted output. Local-only and dependency/runtime failure paths still never upload.
- Fix default source editions copying full-page PDF screenshots into delivery and inserting repetitive verification links. Keep only body resources in `images/`; preserve source hashes, page mappings and the original input in separate processing records. Full-page images require explicit `--edition reading`.
- Retain native physical-page markers without rasterizing blank pages; record table/formula source matches separately from optional visible links.

## 0.4.1 — 2026-09-21

- Add offline all-page PDF preflight and `doctor` runtime checks with actionable installation guidance.
- Default `process` to `--engine auto`; select one PyMuPDF4LLM local backend for eligible PDFs, or existing MinerU Cloud for scanned/uncertain documents. Keep explicit local-only and cloud modes, and cloud-only submit/resume semantics.
- Disable native OCR, preserve raw page chunks and HTML tables, and reject page omissions, numeric/technical-symbol changes, substantial text loss, suspicious script formatting and mismatched table span matrices before publication. Verify ruled tables independently with Layout disabled. Only quality rejection permits automatic cloud fallback; dependency and runtime failures do not.
- Adapt native physical-page evidence without claiming MinerU provenance. Share source-page review, conservative tables, image handling and portable validation with cloud results; retain native headings and TOC.
- Pin the tested 1.28.2 local backend family in one optional dependency group. Keep the existing minimal cloud and readable extras; add no second parser, local OCR engine or semantic enrichment service.
- Update reusable skill instructions, Chinese/English documentation and regression coverage. Existing 0.4.0 deliveries remain readable without migration.

## 0.4.0 — 2026-09-21

The project now prepares faithful, traceable Markdown material packages for independent downstream readers and knowledge systems.

- Deliver the main Markdown and relative `images/` resources; keep manifests, snapshots, audit evidence and postprocessing reports in separate `--work-dir` records.
- Add offline `inspect-images` and source-bound, occurrence-specific exclusion of reviewed independent invalid image blocks. Preserve original inputs and useful body references.
- Deduplicate byte-identical resources, including aliases with different suffixes; retain distinct drawings and repeated useful occurrences.
- Default to generic source editions with conservative automatic simple-table conversion; retain complex HTML tables and original formulas.
- Remove the extra semantic AI enrichment modules, AI JSONL generation and related CLI/configuration commands. Keep MinerU extraction and existing user artifacts/configuration.
- Decouple normal preparation from gas-std-wiki; retain it as an optional rule-fingerprint adapter.
- Distinguish record-backed hash validation from portable reference-only validation.
- Update the CLI, reusable skill, Chinese/English documentation and offline regression coverage.

Breaking interfaces: `enhance`, `process --enhance`, `--enhance-best-effort`, Doubao configuration commands and `publish --image-dir` are removed. Consumers should use returned internal record paths only when they need processing provenance; a manifest is not required for basic ingestion.

## 0.3.0

Introduced conservative offline postprocessing, selective GFM table conversion, source-page links, clause locators and source-bound correction records. Its manifest and companion-report delivery layout is superseded by 0.4.0.

## 0.2.0

Introduced checked publication and provenance identities. Its optional AI enrichment functionality is retired in 0.4.0.
