# Offline postprocessing — 0.4.1

## Inputs and defaults

`readable` consumes a raw result bundle or a publication with accessible internal records, plus the matching original PDF and adapted MinerU Content List or native page evidence. Check source hash and physical page count. Without usable evidence, use `publish` and report unavailable precision.

```text
mineru-ocr readable RESULT --source-pdf INPUT.pdf --output-dir DELIVERY --work-dir RECORDS [--name STEM] [--title TITLE] [--review-file REVIEW.json] [--edition source|reading] [--table-format auto|html]
```

All profiles default to `source + auto`. The reading edition adds navigation and a full-page gallery. Cloud source editions retain verification links and archive a recognized printed TOC internally; native extraction retains its headings and printed TOC. Arbitrary layouts need review.

## Native extraction and routing

`preflight INPUT.pdf` inspects all pages without OCR or upload. Hidden text, unreliable character mapping, sparse text, image-dominated or textless nonblank pages require cloud/review. Mixed PDFs are routed as a whole. `process --engine local` rejects these files without upload; `auto` may use cloud; `cloud` bypasses native extraction. Local-only does not bypass quality checks.

The single local backend is the tested PyMuPDF4LLM/PyMuPDF/Layout 1.28.2 family, installed through the project `local` extra. Local OCR is explicitly disabled. Raw page chunks and native adapter evidence stay internal. Before publication, check all physical pages, at least 99.5% retention of source alphanumeric characters, exact numeric-token counts, and detected table cell/span matrices against HTML. A failed quality gate preserves the candidate/report and permits auto cloud fallback; missing dependencies or runtime failures stop with an actionable error.

These checks do not establish semantic correctness, reading-order accuracy or the table detector's accuracy. Native and cloud results use the same image review, conservative table conversion, source-page links and validation. Do not add another local OCR engine, parser or AI enrichment service as an implicit fallback.

Compare table grids with `find_tables(use_layout=False)`, so the layout model does not validate its own flattening errors. Technical comparison symbols and numeric signs must remain consistent. Superscript/subscript spans with multiple Chinese characters or more than 12 characters require review; do not erase formatting to make a rejected candidate pass.

## Image review

```text
mineru-ocr inspect-images RESULT --work-dir RECORDS
```

Inspect the returned local gallery, source pages and nearby text. The inventory includes file hashes, occurrence lines and known source locations. No automatic semantic classification or removal occurs. Re-running does not overwrite an edited review template.

Exclude only independent invalid blocks. Useful approval/source/version marks remain. Do not infer invalidity from repetition, size or page position. Do not erase marks inside useful figures. Whole source-page verification images remain complete.

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
- Render source pages at native scan resolution where identifiable. Crop figures only from unambiguous supported boxes on unrotated pages; record the original/crop relationship.
- Retain captions, legends, units, values and source formulas. Do not infer omitted content.

`auto` converts only rectangular tables with at least two rows, at most eight columns and 240 characters per cell, no spans/rich/nested content or multi-row headers. A header must be explicit th or source-reviewed. Balanced inline math and cell-by-cell text round trips are required; empty cells remain. Otherwise retain HTML. `html` preserves every HTML table.

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

Delivery contains main MD plus referenced `images/`. Manifests, input ZIPs, audit JSON and three Chinese reports stay in the separate work directory. Raw inputs are never overwritten. Source editions link directly to original-page images; they do not require custom metadata readers.

Run `validate FINAL.md --work-dir RECORDS`. Check a simple table, merged/continued table, formula, figure with units and appendix boundary against originals. Record unresolved OCR, omitted labels and meaningful font distinctions. Formatting checks and successful image decoding do not establish OCR accuracy or human acceptance.

For relocated packages without records, validation covers references only. Preserve internal records for reproducibility and use raw bundles for renewed postprocessing.
