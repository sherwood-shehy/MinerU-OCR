# MinerU API reference used by this skill

Source: <https://mineru.net/apiManage/docs>

## Local credential

Run `mineru-ocr config set-token` to save a per-user plaintext Token. Use `mineru-ocr config show` to display only its location and presence. `MINERU_API_TOKEN` overrides the file when set.

## Local upload workflow

1. Request signed upload URLs with `POST https://mineru.net/api/v4/file-urls/batch`.
2. Include `Authorization: Bearer <token>` only in MinerU API calls.
3. PUT file bytes to each signed URL without an Authorization or Content-Type header.
4. Poll `GET https://mineru.net/api/v4/extract-results/batch/{batch_id}`.
5. On `done`, download and unpack `full_zip_url`.

One upload-link request accepts at most 50 files. Each file supports at most 200MB and 200 selected pages. Signed upload URLs are valid for 24 hours.

## Fields and states

- Batch fields: `model_version`, `language`, `enable_table`, `enable_formula`, `extra_formats`.
- File fields: `name`, `data_id`, `is_ocr`, `page_ranges`.
- Models: `pipeline`, `vlm`; this skill does not handle HTML/MinerU-HTML.
- States: `waiting-file`, `pending`, `running`, `converting`, `done`, `failed`.

## Relevant failures

- `A0202`: invalid Token; `A0211`: expired Token.
- `-60005`: file exceeds 200MB; `-60006`: page limit exceeded.
- `-60007`, `-60009`, `-60010`: temporary model, queue, or parsing failure.
- `-60012`: task not found; `-60013`: task permission denied.

For Office `-60005` or `-60006`, ask the user to export the source to PDF. Retry transient service and queue errors with bounded exponential backoff.
