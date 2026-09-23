# Knowledge-material contract — version 2.0

## Portable delivery

- Main Markdown contains extraction or a conservative source/reading edition. Default source delivery creates no full-page PDF screenshots or repetitive verification links; full-page galleries require explicit reading editions.
- Referenced resources live under `images/` and use relative Markdown/HTML links. Images use their byte SHA-256 plus extension; native SVG is retained.
- Each valid repeated occurrence and original caption remains. Exact byte duplicates share a stored file; visually similar drawings are not automatically merged.
- Copy Markdown and its images together. No manifest, custom reader plugin or internal report is required for reading and basic downstream ingestion.
- HTML tables and source math remain when simpler representation would lose structure. Rendering depends on the consumer's support.
- External images stay external and are reported in validation; they are not automatically downloaded.

## Internal records

`--work-dir` holds source/output hashes, asset identities and positions, original-input snapshots, layout evidence, image decisions and postprocessing reports. It must be separate from delivery with neither directory nested in the other. Default is platform user cache under `mineru-ocr/deliveries`; prefer a persistent explicit location when traceability matters.

The command returns `manifest`, `work_dir` and `processing_reports` paths. These are implementation-specific auxiliary records. Consumers may opt into them but must not need them just to read or ingest source text/images.

The original PDF is included in the `readable` snapshot. Plain `publish` snapshots its available Markdown, resources and provenance; it cannot archive an original document that was not supplied.

Validation at a recorded path checks hashes and records. Relocation without records yields `validation_scope: references`, covering resource existence and generated anchors, not historical hash integrity. There is no automatic record-rebinding command for moved deliveries. Reprocess the original bundle when necessary.

## Identity and source positions

Internal `doc_id` derives from the source SHA-256, falling back to Markdown SHA-256 when original provenance is unavailable. `asset_id` binds document identity and asset bytes. Occurrences and locations remain separate from file identity.

Locations distinguish:
- `page_bbox`: reliable upstream physical page and bounding box.
- `page`: known page, no usable box.
- `page_range`: only the extraction interval is known.
- `unknown`: reliable location unavailable.

Pages are one-based physical PDF pages, not printed labels. Legacy Content List V1 uses zero-based page_idx and normalized 0–1000 boxes. Never interpret boxes as millimetres or infer technical dimensions. Ambiguous fragment mapping stays unknown/range.

`evidence_ref` points to internal retained JSON plus a pointer. Other recognized evidence formats are retained without guessing unsupported schemas.

Portable citations use document title/number, original clause or figure captions, explicit anchors where available. Source-page image links exist only in an explicitly requested reading edition. Internal identities are optional machine provenance, not universal citation syntax.

## Downstream boundary

The converter does not generate semantic descriptions, AI JSONL, embeddings, knowledge pages or graph relations. A downstream ingestion stage may interpret images and source text using its own models and review policies. Keep derived knowledge linked to source text and images; do not overwrite source evidence with interpretations.

See [postprocessing.md](postprocessing.md) for reviewed removal, corrections and table checks.
