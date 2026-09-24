# Offline postprocessing — 0.4.3

## Inputs and defaults

`readable` consumes a raw result bundle or a publication with accessible internal records, plus the matching original PDF and adapted MinerU Content List or native page evidence. Check source hash and physical page count. Without usable evidence, use `publish` and report unavailable precision.

```text
mineru-ocr readable RESULT --source-pdf INPUT.pdf --output-dir DELIVERY --work-dir RECORDS [--name STEM] [--title TITLE] [--review-file REVIEW.json] [--edition source|reading] [--table-format auto|html]
```

All profiles default to `source + auto`. Source editions create no full-page PDF screenshots or visible per-clause/table/formula verification links; source positions stay in processing records. Only explicit reading editions add navigation, verification links and a full-page gallery. Cloud source editions archive a recognized printed TOC internally; native extraction retains its headings and printed TOC. Arbitrary layouts need review.

## Native extraction and routing

`preflight INPUT.pdf` inspects all pages without OCR, upload or screenshots. Policy `native_simple_tables_first` distinguishes blocking `reasons` from review `warnings` and reports `cloud_pages` and `warning_pages`. Short native titles, isolated bad mappings, minority hidden text and large illustrations may proceed locally. Textless nonblank pages, unusable visible text and serious corruption still block; mixed PDFs remain routed as a whole. `process --engine local` stops on blocking findings without upload; `auto` may use cloud; `cloud` bypasses native extraction. Local-only does not bypass quality checks.

Routing thresholds: fewer than 20 usable visible letters/digits (including Chinese characters) is a warning. Mapping errors block only when there are at least 3 and they constitute at least 1% of non-whitespace text. Hidden text blocks when no usable visible text exists or hidden characters account for at least 50% of traced text; invisible rendering or opacity at most 1% counts as hidden. Image union coverage at least 65% is a warning; it blocks with fewer than 20 usable visible characters, or when coverage is at least 90% and usable visible characters are fewer than 80. This prevents scans with small native headers from bypassing OCR. Blank pages do not veto other native pages. These are routing heuristics, not measured accuracy guarantees.

Table screening precedes native extraction and requires the tested PyMuPDF/PyMuPDF4LLM/Layout 1.28.2 `local` extra. It uses ruled-table geometry and the bundled image segmentation head, including table regions without selectable text. Three or more aligned multi-column raster text rows also count as suspected image tables. Merged/diagonal/overlapping grids, external/uncertain headers, image tables and model-detected regions without a reliable native grid route the whole PDF to cloud. Ordinary pictures alone do not trigger this rule. Detection is heuristic, not a complete semantic classifier; borderless tables, multi-level headers and continued tables still need spot review. All pages first receive basic text/image inspection. If these already select cloud, skip table inference. Otherwise screen table candidates only until the first blocking page; record remaining pages as skipped_document_cloud, not checked. Cloud page lists are confirmed triggers, not exhaustive table-risk inventories. The table-region score threshold is 0.7 (not a calibrated probability); weak detections may be missed.

Contents disambiguation uses visible native glyphs, never hidden or off-page text. At least three consecutive entries must have dotted leaders and aligned, ordered page references; Roman front-matter numbering may precede Arabic numbering. A heading is required unless at least 80% of entries have subsection identifiers, supporting continuation pages. Model proposals must fit entirely inside the verified contents block, including modest edge tolerance; images or ruling prevent exclusion. The original model regions remain in `visual_table_regions` and decisions appear in `non_table_regions` with block coordinates and entry counts. Missing leaders, wrapped entries and other ambiguous layouts may still route to cloud. This does not remove printed contents from extraction or exempt another table on the page.

Local OCR is disabled. Keep page chunks and preflight diagnostics internal. Basic acceptance checks all physical pages, at least 99.5% source alphanumeric retention, exact numeric tokens and technical symbols, and equality of cached simple source cells against extracted HTML. Do not rerun detection or reconstruct merged-cell matrices after extraction. Undecodable source glyphs and abnormal output still reject candidates. Suspicious long/Chinese superscripts require review. Quality rejection permits auto cloud fallback; dependencies/runtime failures stop without upload.

Postprocessing formats existing content and applies explicit source-backed corrections. It cannot restore missing cells or infer header relationships. Both engines retain review and portable-reference validation; successful cloud OCR is not an accuracy certificate.

## Image review

```text
mineru-ocr inspect-images RESULT --work-dir RECORDS
```

Inspect the returned local gallery, source pages and nearby text. The inventory includes file hashes, occurrence lines and known source locations. No automatic semantic classification or removal occurs. Re-running does not overwrite an edited review template.

Exclude only independent invalid blocks. Useful approval/source/version marks remain. Do not infer invalidity from repetition, size or page position. Do not erase marks inside useful figures. Whole source-page verification images, when explicitly requested in a reading edition, remain complete.

```json
{
  "source_sha256": "SOURCE_HASH_WHEN_KNOWN",
  "input_markdown_sha256": "EXACT_INPUT_FILE_HASH",
  "image_actions": [{
    "sha256": "EXACT_IMAGE_FILE_HASH",
    "action": "drop",
    "kind": "logo",
    "independent": true,
    "lines": [12, 89],
    "reason": "Checked against original: isolated platform decoration, no source information"
  }]
}
```

Kinds: watermark, stamp, logo, decoration. Explicit lines identify individual occurrences; stale hashes or non-independent blocks stop processing. Inline/table images, wrapped links and code examples cannot be removed by this mechanism. Unreferenced definitions may be removed; a shared download link is retained.

Use image-only reviews with `publish` or `readable`. Reviews containing text replacements or table-header confirmations require `readable`; `publish` rejects those operations instead of ignoring them. Removed original images stay in source/snapshots, but are excluded from new delivery if no reference remains. Exact-byte deduplication preserves all useful occurrences; differing compression or annotations are not merged.

## Structure and tables

- Remove repeated running headers/footers only with margin evidence; retain cover metadata and record removals.
- Normalize headings and number-only term headings with a non-whitespace invariant; protect HTML tables, display math and fenced code.
- Separate recognized body, appendix and commentary locators. Record duplicates and unknown page matches.
- Render full source pages only for an explicitly requested reading edition, at native scan resolution where identifiable. Crop figures only from unambiguous supported boxes on unrotated pages; record the original/crop relationship.
- Retain captions, legends, units, values and source formulas. Do not infer omitted content.

`auto` converts rectangular tables with at least two rows and no spans/rich/nested content, row headers, multi-row headers or explicit footer sections. Width and cell length do not imply complexity. An explicit th header, source-reviewed header or complete textual first row is accepted. The last case uses a recorded first-row header convention, not semantic inference; empty/numeric-only headers still need review. Balanced inline math and cell text round trips are required; empty body cells remain. Otherwise retain HTML. `html` preserves every HTML table. Format round trips only prove preservation of the extracted input, not original-PDF accuracy.

## Correction and header reviews

The same review JSON may contain:

```json
{
  "source_sha256": "PDF_SHA256",
  "replacements": [{
    "before": "exact OCR text",
    "after": "source-checked correction",
    "page": 11,
    "count": 1,
    "reason": "Describe source evidence"
  }],
  "table_headers": [{
    "input_sha256": "EXACT_HTML_TABLE_HASH_AFTER_REPLACEMENTS",
    "header_row": 0,
    "page": 14,
    "reason": "Source confirms this single header row"
  }]
}
```

Use `mineru_ocr.tables.table_hash`. Pages are physical PDF pages. Maintained reviews should include source SHA-256. Processing order: reviewed image exclusion, exact text replacement, conservative structure, image/location handling, table conversion, publication validation. Never put individual-document corrections into generic code. An occurrence mismatch stops publication.

## Acceptance

Delivery contains main MD plus referenced `images/`. Manifests, input ZIPs, audit JSON and three Chinese reports stay in the separate work directory. Raw inputs are never overwritten. Source editions contain only body resources and do not duplicate source PDF pages as screenshots. They do not require custom metadata readers. Keep physical-page mappings in processing records and native page comments.

Run `validate FINAL.md --work-dir RECORDS`. Check a simple table, merged/continued table, formula, figure with units and appendix boundary against originals. Record unresolved OCR, omitted labels and meaningful font distinctions. Formatting checks and successful image decoding do not establish OCR accuracy or human acceptance.

For relocated packages without records, validation covers references only. Preserve internal records for reproducibility and use raw bundles for renewed postprocessing.
