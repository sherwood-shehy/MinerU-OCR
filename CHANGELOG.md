# Changelog

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
