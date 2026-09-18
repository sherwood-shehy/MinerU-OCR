# Offline postprocessing

## Input and modes

`readable` consumes a completed result directory (`full.md` plus `manifest.json`) or published MD with its sidecar, the matching original PDF, and adapted legacy Content List evidence. It verifies source hashes and physical page counts. For unsupported evidence schemas, preserve extraction and report unavailable positioning; do not fabricate provenance.

```text
mineru-ocr readable RESULT --source-pdf INPUT.pdf --output-dir OUTPUT [--name STEM] [--title TITLE] [--review-file REVIEW.json] [--profile generic|gas-std-wiki] [--edition reading|source] [--table-format html|auto] [--target-project TARGET] [--source-id ID]
```

| Profile | Defaults | Purpose |
|---|---|---|
| `generic` | `reading`, `html` | Navigation and a collapsible gallery of all PDF pages |
| `gas-std-wiki` | `source`, `auto` | Source body with verification links and separate review records |

Explicit options override defaults. Source editions archive a detected printed TOC in the audit/raw snapshot instead of repeating it as clauses. Arbitrary layouts still need review.

## Deterministic processing

- Remove only repeated running headers/footers supported by known margin boxes. Keep cover metadata; record removals and conservative page-break joins.
- Restore heading levels and join number-only term headings. Structure cleanup preserves non-whitespace text and protects tables, display math and fenced code.
- Create recognized clause anchors in separate body, appendix and commentary namespaces. Duplicate clauses get occurrence suffixes and a recorded issue. Unknown pages stay null. Locators are version-bound, not universal across editions.
- Render identifiable full-page scans at native resolution. Crop figures only from unambiguous supported boxes on unrotated pages. Retain original crops in the snapshot and record parent hashes. Never infer engineering dimensions from boxes.
- Keep captions, units, symbols and formulas. Inspect source images for omitted labels and meaningful font distinctions; the tool does not automatically reconstruct bold mandatory provisions.

## Table policy

`html` preserves every HTML table. `auto` requires all of these:

- Rectangular, at least a header plus one data row; at most 8 columns and 240 characters per cell.
- No merged cells, nested tables, rich HTML, unsupported attributes, multiple header rows or row headers.
- First row uses `<th>` throughout, or an exact-table hash has a source-checked header confirmation.
- Balanced inline math; display math and ambiguous escaped pipes remain HTML.
- Preserve empty cells and round-trip every converted cell to original text, apart from normalized whitespace. Escape plain Markdown punctuation.

These limits are conservative readability choices; record each decision and reason. Do not manufacture `<th>` tags to pass checks. GFM has one header row and cannot represent row/column spans. HTML and pipe tables can coexist. Check target HTML/math rendering; if unsupported, preserve HTML evidence and images and design a separately reviewed representation, never silently flatten.

## Review JSON

```json
{
  "source_sha256": "PDF_SHA256",
  "replacements": [{
    "before": "exact OCR text",
    "after": "exact source-checked correction",
    "page": 11,
    "count": 1,
    "reason": "Describe what the original page actually shows"
  }],
  "table_headers": [{
    "input_sha256": "SHA256_OF_EXACT_HTML_TABLE_AFTER_REPLACEMENTS",
    "header_row": 0,
    "page": 14,
    "reason": "Agent inspected original and confirmed this single header row"
  }]
}
```

Always include the source SHA256 in maintained review files. Exact occurrence-count mismatches stop delivery. Header confirmations identify HTML after replacements and use physical PDF pages; compute hashes with `mineru_ocr.tables.table_hash`. Header confirmation does not certify all values. Keep per-document corrections out of general rules.

## Delivery and acceptance

- Main MD: source/reading edition, relative `images/` references.
- Manifest: source/output hashes, asset identities/locations, configuration, evidence and companion hashes.
- `来源说明`: identity, processing, snapshot link, target rule hashes, pending registration/status fields.
- `定位与图片清单`: clauses, readable caption/page mapping for hash-named images, crop/original relations, separate program/visual/human/extraction states.
- `校勘与缺口`: exact before/after edits, table decisions, suspect headers, duplicate locators and remaining limitations.
- Original-input ZIP: byte-preserved PDF, original MD/manifest, local referenced resources and retained evidence. Audit JSON records transformations. Remote images remain reported, never silently downloaded.

Run `mineru-ocr validate FINAL.md`. It checks resources, recorded hashes, companion files and generated explicit anchors; it does not measure OCR accuracy or guarantee rendering. Inspect a simple table, complex/continued table, formula, figure with units and appendix boundaries. Re-run from raw input with the review file for a new collision-safe edition. Use targeted renewed OCR only where source evidence warrants it.
