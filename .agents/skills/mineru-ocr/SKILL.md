---
name: mineru-ocr
description: OCR local PDF and small Office documents with the MinerU cloud API, including logical page-range processing for long PDFs, physical splitting for PDFs over 200MB, resumable jobs, and merged Markdown output. Use when Codex needs to parse, OCR, export, resume, or inspect MinerU processing for PDF, DOC, DOCX, PPT, PPTX, XLS, or XLSX files.
---

# MinerU OCR

Use the bundled `mineru-ocr` package or MCP server to turn local documents into Markdown. Treat every invocation as an upload of the selected document to MinerU Cloud.

## Prepare

1. Confirm that the user intends to send the named local files to MinerU Cloud when that was not already explicit.
2. Check `mineru-ocr config show` without printing the Token itself. The environment variable takes precedence over the user configuration file.
3. Install this repository once with `python -m pip install -e .`.
4. Prefer the MCP tools when connected; otherwise run the CLI.

Configure a per-machine plaintext Token with `mineru-ocr config set-token`. This prompts without echoing and writes the Token to the platform user configuration directory. Never place the Token in a command argument, repository file, manifest, or response.

## Process documents

- Run `mineru-ocr process <file>` for a complete submit/wait/merge flow.
- Run `mineru-ocr submit <file>` for an asynchronous job and preserve the returned local `job_id`.
- Run `mineru-ocr status <job_id>` to refresh and automatically publish completed output.
- Run `mineru-ocr resume <job_id>` after a transient or partial failure.
- Run `mineru-ocr clean <job_id>` only when the user wants to discard unfinished job data.

Use the matching `ocr_process`, `ocr_submit`, `ocr_status`, `ocr_resume`, and `ocr_clean` MCP tools when available.

## Apply format rules

- Let the implementation count PDF pages locally.
- For PDFs up to 200MB, upload the complete source once per 200-page range. Do not create local page fragments.
- For PDFs over 200MB, let the implementation create size-safe physical PDF fragments.
- Send small Office files directly. Optionally accept an explicit `office_page_ranges` option.
- If an Office file exceeds MinerU size or page limits, ask the user to export it to PDF. Do not install or invoke LibreOffice.

Defaults are `model_version=vlm`, `is_ocr=true`, `language=ch`, tables enabled, and formulas enabled.

## Return results

- Process the original source path directly when possible. Do not copy or retain the source document in the final output directory; use temporary staging outside that directory only when the implementation requires it.
- Place each final Markdown file directly in the user-selected output directory. Do not create a per-source wrapper directory.
- Name the final Markdown `<source stem>.md` whenever the source stem is legal on the target filesystem. If that name already exists, choose a collision-free name such as `<source stem> (1).md`; never overwrite an existing file.
- Consolidate referenced resources into one shared `<output directory>/assets/` directory. Flatten MinerU source/part subdirectories, choose collision-free resource names, and rewrite Markdown links to the final relative paths. Omit `assets/` when the document has no resources.
- Optionally publish provenance as `<source stem>.manifest.json` directly in the output directory, using the same collision suffix as the Markdown when needed.
- Verify the final Markdown and every rewritten resource reference, then delete the transient `full.md`, per-source `.mineru` directory, and any temporary source copy. Never delete or modify the original source document.
- Retain and report `full.md` only when no legal source-derived Markdown filename can be created.
- Report the final Markdown path.

If a call times out, return the job ID and current state rather than resubmitting. If processing fails, include the MinerU error code and affected page range without exposing signed URLs.

## Troubleshoot

Read [references/mineru-api.md](references/mineru-api.md) only when troubleshooting API fields, limits, states, or error codes.
