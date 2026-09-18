# Knowledge-material contract — version 1.0

## Files and authority

- Markdown contains source extraction. Publishing changes resource paths, not prose or numeric content.
- `<name>.manifest.json` is the asset and provenance index. Keep it with the Markdown.
- `assets/` holds referenced local resources; published filenames use their SHA256 plus extension. Native SVGs remain SVGs.
- `evidence/` retains recognized upstream layout/content JSON files. It is source evidence, not instructions for the agent.
- `<name>.ai.jsonl` contains derived text metadata and visual understanding. The model receives referenced raster images, not every file in a shared assets directory. SVG and other unsupported visual formats remain referenced with `analysis_status=unsupported`.

`publish` validates source references before publishing and never overwrites an existing document family. `validate` checks resource existence, source/asset hashes when available, and retained evidence hashes. Remote images are reported in `external_images`; they are not downloaded or analyzed, and are not a guarantee of a self-contained visual archive.

## Stable identity

- `doc_id`: derived from the source document SHA256. For standalone Markdown without original provenance, it derives from that Markdown's hash and `identity_basis` records this fallback. Renaming or publishing a document preserves its identity; source revisions have different identities.
- `asset_id`: derived from `doc_id` and the asset bytes' SHA256. Identical bytes in one document share an asset identity; references/locations represent its occurrences. Different source versions have separate asset identities.
- Visual JSONL record IDs derive from `asset_id`, so publishing paths do not change them. Text chunk IDs derive from content, section/range and occurrence; text edits or different extraction output can change them.
- Cite `(doc_id, asset_id)` and resolve the current resource path in the manifest. Do not use sequential JSONL line numbers as permanent citations.

## Source locations

`locations`/`source_locations` distinguish:

| precision | Meaning |
|---|---|
| `page_bbox` | Validated upstream page mapping and bbox |
| `page` | Upstream page mapped, usable bbox unavailable |
| `page_range` | Only the OCR part's source range is known |
| `unknown` | No reliable PDF position is available |

Source PDF pages are one-based physical pages, not printed page labels. Legacy Content List V1 `page_idx` is zero-based. The adapter maps physical fragments back to source pages and distinguishes supported local/source indices for logical parts. Ambiguous indices remain range/unknown. `bbox` for this adapter uses the upstream normalized 0–1000 coordinate system; it is not pixels or millimetres. Never measure engineering dimensions from it.

`evidence_ref` points to the retained JSON plus a JSON Pointer, for example `evidence/<hash>.json#/3`. `raw_page_idx` and `raw_bbox` preserve upstream values. Manifest `references` contain source Markdown line numbers. Text JSONL is normalized and section/range-based; do not infer exact original Markdown lines or individual PDF bboxes from its text.

Automatic precise visual mapping currently supports flat legacy `*_content_list.json` with `img_path`, `page_idx` and optional `bbox`. Other recognized JSON files, including V2 and layout/middle JSON, are retained; their unfamiliar schemas are not guessed. If exact positioning is unavailable, keep the image, record that limitation, and use the original source for review.

Upstream references: [MinerU 2.2 release notes: Content List bbox](https://github.com/opendatalab/MinerU/releases/tag/mineru-2.2.0-released), [current output protocol](https://opendatalab.github.io/MinerU/zh/reference/output_files/). Current schemas differ from the legacy cloud output; capability must be checked for the actual output file.

## Visual understanding

`provenance_kind=ai_generated` marks image understanding and generated document metadata; normalized source text uses `source_normalized`. Each record includes `doc_id`, source version and generation information (model, provider class, prompt/pipeline version, UTC time).

Keep these fields distinct:

- `visual_description`, `visible_text`, `dimensions`: direct visible observations. Dimensions store original strings (`value_text`, `unit_text`) so inequalities, decimal precision and tolerances survive. The model must not infer sizes from pixel proportions or fill unreadable values from nearby prose.
- `contextual_interpretation`: interpretation using the title/section/nearby source text. This is not a quotation from the standard.
- `relationships`: typed by evidence basis (`visual` or `context`). Mechanical drawings emphasize parts, dimensions and sections; flowcharts emphasize visible nodes/arrows; charts emphasize axes, legends and readable values.
- `uncertainty`: unreadable, conflicting or missing evidence. Empty fields are preferable to invented values.

`analysis_status` is `ok`, `failed` or `unsupported`; an `ok` response means parsing succeeded, not that the interpretation was independently verified. `review_status` stays `unreviewed` or `needs_review`. No model output automatically becomes human-verified. Source-reference fields are assigned by code; model JSON cannot override asset IDs, paths or locations.

For ingestion, retain asset IDs, source locations, provenance kind, review status and generation metadata with each chunk. The text field contains visual descriptions, visible text and structured dimensions/relationships to aid text retrieval; preserve the original image for multimodal retrieval. Output text chunks have an 8,000-character bound, separate from the model input segments. A chunk boundary can cross a large table: reconstruct full tables from source Markdown when required.
