---
name: mineru-ocr
description: Convert local PDF and small Office documents with MinerU Cloud, publish Markdown with validated assets and source references, and optionally create visual-understanding JSONL for knowledge bases. Also use for offline publishing, validation, and resuming this tool's long-document jobs.
metadata:
  version: "0.2.0"
---

# MinerU OCR

Use the `mineru-ocr` CLI. This host's maintenance source is `D:\Codex-home\projects\MinerU-OCR`; global skill copies are released from its `.agents/skills/mineru-ocr` directory. Do not use the removed MCP entry points or add another wrapper skill for these same tasks.

## Prepare

- `process` and `submit` upload the selected files to MinerU Cloud. Confirm that intent only when the user's request has not already authorized it. `enhance` separately sends referenced images and document text to the configured Doubao service; run it when AI enhancement is requested.
- `publish` and `validate` operate locally and need no service credentials.
- Check `mineru-ocr --help`. If the executable is not on PATH, use `python -m mineru_ocr.cli`. If the package is missing, install from the maintenance repository using `python -m pip install -e .`, subject to the host's dependency-installation rules. Use the existing Python; do not create an environment implicitly.
- For cloud work, use `mineru-ocr config show` to inspect configuration without printing keys. Configure only when needed using the interactive `config set-token` or `config set-doubao-key` commands. Never put credentials in command arguments or artifacts.

## Choose the workflow

Basic knowledge materials:

```text
mineru-ocr process INPUT.pdf --output-dir OUTPUT
```

With requested visual understanding and text metadata:

```text
mineru-ocr process INPUT.pdf --output-dir OUTPUT --enhance
```

Existing results, without repeating OCR:

```text
mineru-ocr publish RESULT_DIRECTORY_OR_MD --output-dir OUTPUT
mineru-ocr validate PUBLISHED.md
mineru-ocr enhance PUBLISHED.md
```

The last command is optional. Enhance the final published Markdown so JSONL references match the final asset paths. `publish` publishes source materials; it does not migrate an existing AI JSONL. Keep the original result package available, including any earlier enhancement, until the user chooses to remove it.

For asynchronous work use `submit INPUT`, then `status JOB_ID`; use `resume JOB_ID` after partial failure. A timeout is not permission to resubmit. Return the existing job ID and state. Use `clean JOB_ID` only when unfinished job data should be discarded.

## Processing and delivery

- Defaults: VLM, OCR enabled, language `ch`, tables and formulas enabled. PDFs are planned in ranges of up to 200 pages; oversized PDFs use physical fragments. These are the client's configured limits, not a guarantee about current service limits.
- Small Office documents can be submitted directly. `--page-ranges` applies to Office inputs. Oversized Office files require user-provided PDF export; do not introduce LibreOffice into this workflow.
- Let the publisher implement filename collision avoidance, shared resource naming, link rewriting and validation. Do not manually flatten directories or reconstruct its manifest.
- Report the final Markdown and manifest; report AI JSONL only if generated. Basic output is `<name>.md`, `<name>.manifest.json`, optional shared `assets/` and `evidence/`. Existing document names are avoided with ` (1)` suffixes. Source documents and earlier result packages are retained.
- Re-running `enhance` atomically replaces that Markdown's derived `.ai.jsonl`; the source Markdown stays unchanged. Report image failures/unsupported formats from `image_coverage`, even when the command produced a JSONL file.

## Citation and visual interpretation

Read [references/knowledge-materials.md](references/knowledge-materials.md) when preparing knowledge-base imports, citations, or interpreting visual outputs. Its contract defines stable IDs, evidence locations, review status and the limits of exact positioning.

Use manifest IDs and locations when citing assets. Never invent a page, bbox, dimension, unit or tolerance. A page range is not an exact page. Machine interpretation remains separate from source facts, and unreviewed results must not be described as verified.

For API request fields and service errors, read [references/mineru-api.md](references/mineru-api.md). Return the affected range and error code without exposing signed URLs.
