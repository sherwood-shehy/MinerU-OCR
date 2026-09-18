# gas-std-wiki source preparation

The priority target on this host is `D:\Codex-home\projects\gas-std-wiki`. Read the actual target checkout's current rules; this host path must not be embedded in portable delivered content.

## Read before preparation

Read `AGENTS.md`, `知识库说明.md`, `通用使用指南.md`, rules for ingestion, visual assets, tags/metadata, corrections, review/acceptance, and `rules/templates/来源页模板.md`. Later authorized ingestion has additional index/template/foreign-source requirements. Do not duplicate the target's maintained business rules in this skill.

`--profile gas-std-wiki --target-project TARGET` records these nine file hashes. Missing files are explicit errors. This option reads files and records a baseline; it does not write the target or establish compliance by itself.

## Source preparation

1. Use a source edition and conservative `auto` tables. Reuse completed OCR and keep original evidence.
2. Separate main text, appendices and commentary. Use version-bound clause/page locators; log uncertain boundaries, omissions, unusual tables and unresolved values.
3. Deliver Chinese companion records and relative links. Map hash-named images to readable titles/pages. Source registration may add descriptive names through validated publishing.
4. Distinguish original PDF/OCR snapshots from processed output. Same-edition transcription correction is not standard revision.
5. Leave effect/date/authority/channel pending unless actually verified. Never auto-fill human approval or acceptance.

Domestic sources ultimately belong in `sources/domestic/`, with `sources/domestic/images/`; foreign sources use the corresponding foreign directories. When ingestion is authorized, keep the entire delivered file family and referenced evidence. Relocating just the main MD breaks the package. Source registration and index updates belong to the target ingestion workflow.

## Images and knowledge

Images currently prioritize human reference. File existence, program decoding, agent visual inspection, human checking and technical extraction are separate states. Retain captions, legends, units and pages. Leave unreadable content unresolved.

Do not run `enhance` merely because the destination is an LLM Wiki. This optional external step needs relevant authorization. Visual descriptions and OCR corrections do not automatically become authoritative requirements. The skill prepares sources; topic pages, cross-document synthesis, controlled metadata, indexes and acceptance follow target rules during authorized ingestion.
