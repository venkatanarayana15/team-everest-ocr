# AGENTS.md

This repository contains a production-oriented OCR extraction pipeline for a fixed 6-page questionnaire, with FastAPI backend, React frontend, Tesseract OCR, LLM-based structured extraction and verification, validation, deduplication, and PostgreSQL persistence.

## Working model
- Act like a senior/staff engineer: optimize for reliability, debuggability, maintainability, safe failure modes, and clear rollback paths.
- Prefer small, reviewable changes over broad refactors unless the task explicitly requires architectural work.
- Preserve existing behavior unless the task explicitly asks to change product behavior.
- When a requirement is ambiguous, choose the safer and more observable implementation.

## Stack
- Backend: FastAPI + uvicorn
- Frontend: React + TypeScript + Vite
- Python runner: `uv run python`
- OCR: local static Tesseract binary in `bin/`
- Database: PostgreSQL via `asyncpg`
- Tests: Python test script in `tests/test_backend.py`

## Canonical commands
- Start backend: `uv run uvicorn src.server:app --port 8000`
- Start frontend: `cd frontend && npm run dev`
- Run tests: `uv run python tests/test_backend.py`

## Repository map
- `src/server.py`: API endpoints, upload flows, checkpoint/resume, section derivation fallback, dedup, DB save, validation endpoints
- `src/extraction_pipeline.py`: core pipeline models and orchestration, including `StructuredField`, `PipelineResult`, merge logic, verify logic
- `src/prompt_templates.py`: LLM prompts and questionnaire template grounding
- `src/database.py`: PostgreSQL schema and CRUD logic for `pdfs`, `extraction_results`, `extracted_fields`, `corrections_log`
- `src/backends.py`: OCR backend integration, including static Tesseract path handling and `process_images()`
- `src/input_handler.py`: input-type detection, ZIP extraction, folder scanning, mixed-batch routing
- `src/page_classifier.py`: 6-page content-based page classification and ordering
- `frontend/src/pages/UploadPage.tsx`: upload modes, sidebar, dedup dialog, batch UI
- `frontend/src/pages/ReviewPage.tsx`: extraction review and DB save action
- `frontend/src/components/FieldList.tsx`: page-to-section grouping, empty section rendering, Y-order display
- `frontend/src/components/FieldCard.tsx`: field rendering, checkbox UI, edit state, corrected highlighting
- `frontend/src/components/ImageViewer.tsx`: label/value bbox overlays on page image
- `frontend/src/api/client.ts`: frontend API client bindings
- `frontend/src/types.ts`: shared frontend types
- `tests/test_backend.py`: unit tests covering bbox logic, input handling, and page classification
- `bin/tesseract`, `bin/eng.traineddata`: pinned OCR runtime assets
- `.env`: provider configuration and secrets; never hardcode or echo secret values

## Product constraints
- Primary target document is the “I Am The Change — Home Visit Questionnaire”.
- The classifier and validation logic assume exactly 6 logical pages.
- Header fields are global metadata and should remain `section_number = null`.
- Field order in review UI must continue to mirror page layout using `bbox[1]` Y-position sorting.
- Section grouping has a three-tier fallback: API sections, raw-text heading derivation, then field-label prefixes.
- Conditional fields may intentionally resolve to `N/A`; do not treat this as missing data.
- Table row field labels use the format `{Section} — Row {n} — {Column}`; preserve this convention unless the task explicitly migrates it everywhere.

## Current pipeline
1. Preprocess input pages: deskew, denoise, grayscale.
2. Detect bounding boxes with Tesseract.
3. Run primary LLM extraction into JSON fields.
4. Merge extracted fields with bbox data.
5. Run secondary LLM verification/correction and fill missing values.
6. Persist artifacts such as `result.json` plus markdown/text/html outputs.

## Supported inputs
### Mode A: PDF
- `POST /upload` accepts a single PDF and splits it into pages.

### Mode B: Images
- `POST /upload-images` accepts six images and classifies them by content.

### Mode C: ZIP
- `POST /upload` also accepts ZIP files containing page images.

### Batch modes
- `POST /upload-batch` accepts mixed items in one request.
- `POST /process-folder` scans a server-side folder and processes items independently.
- Batch processing should isolate failures per document; one bad item must not abort the full batch.

## Validation rules
- Validation expects exactly 6 pages.
- Detect duplicates, missing pages, blank pages, unreadable pages, and low OCR confidence.
- `GET /validate/{job_id}` should return a full validation report.
- Invalid documents may be marked `incomplete`, but the system should still preserve enough diagnostics for debugging and UI review.

## LLM provider rules
- Provider and model selection come from `.env`.
- Current defaults are OpenAI for both primary and secondary stages, typically `gpt-4o-mini`.
- Gemini credentials may exist but free-tier capacity can be exhausted; never assume Gemini availability.
- Any provider-specific change must preserve a clean fallback path and useful error messages.
- LLM responses must be treated as untrusted input: validate shape, coerce carefully, and fail closed with diagnostics.

## Database rules
- PostgreSQL is the source of truth for persisted uploads and extraction results.
- PDF dedup uses SHA256 on upload; preserve idempotent behavior for re-uploads.
- Keep DB writes explicit and transactional where multi-table consistency matters.
- Do not silently swallow DB failures; log enough context to debug without exposing secrets or raw credentials.
- Schema changes must include migration planning, backward compatibility notes, and impact on `/pdfs` and `/save-to-db/{job_id}`.

## OCR runtime rules
- Prefer the repository-pinned Tesseract binary in `bin/` over system-installed variants.
- Any change to OCR invocation must consider binary path resolution, traineddata availability, platform differences, and subprocess error handling.
- Timeouts, missing binaries, malformed images, and empty OCR output must all degrade gracefully.

## API change rules
- Keep request and response contracts stable unless explicitly asked to version or break them.
- If an endpoint changes shape, update backend models, frontend client types, and consuming UI in the same change.
- For long-running endpoints, preserve resumability and user-visible status reporting.
- Return structured errors with actionable detail; avoid opaque 500s where validation or dependency failures can be surfaced safely.

## Frontend change rules
- Keep TypeScript types aligned with backend response models.
- Handle partial data, missing sections, duplicate uploads, validation failures, and long-running jobs without crashing the UI.
- Preserve current review affordances: checkbox rendering, corrected-field highlighting, page/section grouping, Y-position display, and bbox overlays.
- Do not hide backend uncertainty; surface incomplete or fallback-derived data clearly.

## Testing expectations
- At minimum, run `uv run python tests/test_backend.py` after backend logic changes.
- Add or update tests whenever changing bbox merge logic, section derivation, input detection, classification, validation, deduplication, or DB persistence behavior.
- Prefer deterministic tests over network-dependent tests.
- For bug fixes, add a regression test that fails before the fix and passes after it.

## Reliability checklist
Before finishing any meaningful change, verify the following where relevant:
- Happy path still works for PDF, image-set, ZIP, and mixed batch inputs.
- Failure in one batch item does not stop sibling jobs.
- Duplicate upload behavior remains idempotent and user-visible.
- Missing or malformed OCR/LLM output does not crash the pipeline.
- Section fallback behavior still produces sensible groupings.
- Save-to-DB path does not create partial or duplicated records unexpectedly.
- Logs and error payloads are useful but do not leak secrets or sensitive raw config.

## Observability and debugging
- Prefer explicit logs around stage transitions: ingest, preprocess, OCR, extraction, verification, validation, artifact write, DB save.
- Include stable identifiers such as `job_id`, page number, and provider name in logs where possible.
- When catching exceptions, preserve root cause details in logs while returning sanitized API errors.
- Avoid noisy logs for normal control flow; log for diagnosis, not narration.

## Security and safety
- Never commit `.env`, API keys, database URLs, or derived secrets.
- Do not print secret values in logs, test output, or debugging scripts.
- Treat uploaded files, ZIP contents, OCR text, and LLM output as untrusted input.
- Defend against path traversal, unsafe ZIP extraction, malformed PDFs/images, and oversized uploads.

## Change strategy
- Prefer targeted fixes first.
- Refactor only after behavior is covered by tests or when the current structure blocks a safe fix.
- When touching multiple layers, update in this order unless the task dictates otherwise: contract, backend, tests, frontend, docs.
- Keep docs synchronized with behavior; stale AGENTS.md or project-state docs create operational risk.

## Good change examples
- Add validation for malformed provider responses before model parsing.
- Preserve existing response schema while adding optional fields.
- Add regression tests for shuffled image ordering in `PageClassifier`.
- Improve DB save idempotency with explicit conflict handling.
- Surface `incomplete` validation details in the UI instead of generic failure messages.

## Avoid
- Quick fixes that bypass validation or silently coerce bad data.
- Hardcoded absolute machine-specific paths when a repo-relative path is required.
- Backend response changes without matching frontend type and UI updates.
- Catch-all `except Exception` blocks that discard context.
- Hidden retries, duplicate writes, or implicit fallback logic without logging.
- Reordering fields in a way that breaks page-layout mirroring.

## When adding new docs
- Keep root `AGENTS.md` concise but operational.
- Put deep implementation details in focused docs and link them here if the repository grows further.
- If this project splits into subprojects, add nested `AGENTS.md` files near the relevant code so local rules override root guidance.