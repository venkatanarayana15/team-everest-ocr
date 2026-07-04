# OCR Extraction Pipeline — Context

## Project Purpose

Extract structured data from a **fixed 6-page "I Am The Change — Home Visit Questionnaire"** using Tesseract OCR + LLM extraction + LLM verification. Results are rendered as JSON/MD/TXT/HTML, persisted to PostgreSQL, and optionally synced back to Zoho Creator.

---

## Architecture Overview

```
  Upload (PDF/Images/ZIP/Batch)
         │
         ▼
  server.py (FastAPI) ─── SSE streaming ───→ Frontend (React)
         │
         ├──→ pipeline_runner.py (orchestration)
         │         ├──→ extraction_pipeline.py (ExtractionPipeline class)
         │         │         ├──→ backends.py (Tesseract bbox detection)
         │         │         ├──→ model_client.py (LLM providers)
         │         │         ├──→ preprocessing.py (image cleanup)
         │         │         └──→ prompt_templates.py (LLM prompts)
         │         ├──→ page_classifier.py (page ordering)
         │         ├──→ renderers.py (output formatting)
         │         └──→ status.py (progress tracking + SSE)
         │
         ├──→ zoho_integration.py (Zoho Creator ↔ Supabase ↔ pipeline)
         │
         └──→ database.py (PostgreSQL persistence)
```

---

## File-by-File Responsibilities

| File | Lines | Role |
|---|---|---|
| `server.py` | 1188 | FastAPI app, 18 endpoints, upload flows, SSE, dedup, cleanup, validation |
| `pipeline_runner.py` | 701 | 4 pipeline orchestration functions + 10 infrastructure helpers |
| `extraction_pipeline.py` | 651 | `ExtractionPipeline` class — preprocessing, bbox, LLM extraction, merge, verification |
| `model_client.py` | 326 | 5 LLM providers (Gemini, OpenAI, DeepSeek, OpenRouter, NVIDIA) + factory |
| `page_classifier.py` | 283 | 6-page content-based classification + page ordering |
| `prompt_templates.py` | 240 | Primary extraction prompt (~185 lines) + secondary verification prompt (~55 lines) |
| `database.py` | 208 | PostgreSQL async CRUD — pdfs, extraction_results, extracted_fields |
| `status.py` | 194 | SSE push queues, progress store, checkpoint save/load |
| `zoho_integration.py` | 179 | Zoho OAuth → file download → Supabase upload → pipeline → Creator PATCH |
| `backends.py` | 166 | TesseractBackend — repo-pinned binary, parallel image_to_data |
| `input_handler.py` | 134 | Input type detection (PDF/image/ZIP/mixed), ZIP extraction, folder scanning |
| `renderers.py` | 85 | Markdown and plain-text output formatting for download endpoint |
| `ratelimit.py` | 70 | Sliding-window rate limiter + retry with exponential backoff |
| `preprocessing.py` | 48 | Grayscale → deskew → denoise → adaptive threshold |
| `config.py` | 12 | 8 configurable pipeline parameters (DPI, preprocessing settings) |

---

## Pipeline Flow (Detailed)

### Input Type Detection

`/upload` routes by file extension:
- **`.pdf`** → single PDF pipeline
- **`.jpg/.jpeg/.png/.tiff/.tif`** → single image, waits for 5 more (mode B)
- **`.zip`** → extract images, run image-set pipeline
- **Mixed list** → `/upload-batch` routes each type independently
- **Server folder** → `/process-folder` scans and creates per-item jobs

### Pipeline Stages (run_pipeline for PDFs)

```
1. _wait_for_memory()       — ensure ≥512MB free RAM (psutil, 5s poll, 1hr timeout)
2. _validate_pdf()          — exists, non-empty, openable by PyMuPDF
3. pipeline.preprocess()    — render PDF pages at config.render_dpi (300 DPI)
                             → grayscale → deskew (≤5°) → denoise → binarize
                             → save page_N.png + page_N_original.png
4. Stage 1 (parallel):
   ├── pipeline.run_bbox()  — Tesseract image_to_data at 150 DPI, 6-thread pool
   └── pipeline.run_primary_extraction() — LLM call with PRIMARY_EXTRACTION_PROMPT
5. pipeline.merge_fields()  — assign bbox coordinates to each extracted field
                             → _group_words_into_lines() — Y-tolerance grouping
                             → _find_field_bboxes() — fuzzy label matching (rapidfuzz)
                             → _find_value_bbox() — 4-strategy value location
6. _derive_sections()       — 3-tier fallback: hardcoded → regex raw-text → field prefixes
7. _save_checkpoint()       — resumability
8. Stage 2 (conditional):
   If confidence ≥95% AND no clarification_needed:
     → skip verification
   Else:
     → pipeline.verify_secondary() — LLM call with SECONDARY_VERIFICATION_PROMPT
9. pipeline.fill_missing_template_fields() — inject 37 known fields if LLM missed them
10. _save_results()         — result.json + result.md + result.txt + result.html
11. _cleanup_intermediate() — remove checkpoint.json, tesseract_data.json
```

### Image-Set Pipeline (run_image_pipeline_from_zip)

```
1. _wait_for_memory()
2. _validate_images()       — each path exists, non-empty
3. PageClassifier.classify_all() — classify each image → page number (1-6)
4. PageClassifier.resolve_order() — assign images to pages, detect issues
5. Save page_validation.json
6. If validation fails (missing/duplicate/blank/unreadable/not 6 pages):
   → set status "incomplete", stop
7. Call run_image_pipeline() with ordered page mapping
   → same stages as PDF pipeline (preprocess_images → bbox → LLM → merge → verify)
```

### Batch PDF Pipeline (run_batch_pdfs_pipeline)

- Each PDF goes through the full pipeline independently
- Errors are caught per-PDF — one bad PDF doesn't block the batch
- Combined result.json with `{"batch": True, "num_pdfs": N, "pdfs": [...]}`

---

## API Endpoints

### Upload
| Route | Method | Input | Description |
|---|---|---|---|
| `/upload` | POST | single file (PDF/image/ZIP) | Routes by extension; handles dedup for PDFs |
| `/upload-images` | POST | multiple image files | Creates image-set job |
| `/upload-batch` | POST | mixed file list | Routes each file type independently |
| `/process-folder` | POST | `{"folder_path": "..."}` | Scans server folder, creates per-item jobs |

### Results
| Route | Method | Description |
|---|---|---|
| `/result/{job_id}` | GET | Full result.json (only when status="done") |
| `/tesseract-data/{job_id}` | GET | Per-page Tesseract word-level bbox data |
| `/download/{job_id}` | GET | Format: json/md/txt/html — file download |
| `/correct/{job_id}` | POST | Human correction — appends to corrections.json, updates result.json |
| `/update-raw-text/{job_id}` | POST | Overwrite raw_text in result.json + result.md |

### Status & Streaming
| Route | Method | Description |
|---|---|---|
| `/status/{job_id}` | GET | Current job status (from status.json) |
| `/stream/{job_id}` | GET | SSE per-job — status updates with progress % |
| `/stream-batch` | GET | SSE for multiple job_ids — polls all every 200ms |

### Validation & Management
| Route | Method | Description |
|---|---|---|
| `/validate/{job_id}` | GET | Page validation report (image jobs only) |
| `/retry/{job_id}` | POST | Re-runs from last checkpoint |
| `/delete/{job_id}` | DELETE | Removes job dir + DB records |
| `/metrics` | GET | Human correction stats across all jobs |
| `/jobs` | GET | List all jobs with status, confidence, processing time |
| `/pdfs` | GET | List all uploaded items with dedup info |

### Persistence
| Route | Method | Description |
|---|---|---|
| `/save-to-db/{job_id}` | POST | Upsert to PostgreSQL — pdfs + extraction_results + extracted_fields |

### Zoho Integration
| Route | Method | Description |
|---|---|---|
| `/api/ocr/extract` | POST | Full Zoho pipeline — OAuth → download → Supabase → OCR → Creator PATCH |
| `/api/ocr/test-zoho-update` | POST | Tests Zoho Creator connectivity (PATCH OCR_Status) |

---

## Key Algorithms

### Page Classification (page_classifier.py)

Each image is scored against 6 pages using three feature sets:
1. **PAGE_SIGNATURES** (15-25 keywords/page) — exact match = 15pts, fuzzy (>80% rapidfuzz) = 8pts
2. **SECTION_HEADERS** (1-2/page) — exact = 30pts, fuzzy (>85%) = 15pts
3. **FIELD_NUMBER_PATTERNS** (regex per page) — each match = 10pts
4. Word-count bonus (up to 10pts)

Confidence = min(100, best_score), adjusted by margin over second-best, clamped to [10, 99].

### Bbox Merging (extraction_pipeline.py)

1. Group Tesseract words into lines by Y-position (20px tolerance)
2. Match each LLM-extracted field label to nearest text line using rapidfuzz
3. For composite labels (containing ` — `), split and match first component
4. Find value bbox via 4 strategies:
   - **Same line, colon split**: label and value separated by `:`
   - **Below label**: first word in the line immediately below
   - **Right of label**: horizontal position after label ends
   - **Fallback**: same line as label

### Section Derivation (pipeline_runner.py)

Three-tier fallback — each tier only used if previous yields nothing:
1. **KNOWN_SECTIONS** — hardcoded 8-section mapping (Student Profile p1 → Volunteer Observation p6)
2. **Regex raw-text parsing** — match `Section {n} — {Name}` patterns
3. **Field label prefix** — extract leading number from `"n.n Label"`

### Deduplication

- SHA256 hash computed on upload
- PostgreSQL lookup via `find_pdf_by_hash()`
- On duplicate: returns `duplicate: True` with `existing_job_id` to frontend
- Frontend shows dialog allowing user to proceed or cancel
- Image sets and ZIPs do NOT have hash-based dedup

### Save-to-DB

- Creates/retrieves `pdfs` row by file_hash
- Upserts `extraction_results` row by job_id
- Deletes + re-inserts `extracted_fields` to handle corrections
- All operations are explicit (no ORM)

---

## Data Flow by Input Type

### PDF Upload
```
Client → POST /upload (PDF)
  → server.py: SHA256 hash → DB dedup check
  → Save to job_dir/input.pdf → write file_hash.txt
  → ThreadPool: run_pipeline(job_dir, pdf_path)
  → SSE: /stream/{job_id} streams progress
```

### Image Set Upload
```
Client → POST /upload-images (6 files)
  → server.py: save to job_dir/input_images/
  → ThreadPool: run_image_pipeline_from_zip(job_dir, image_paths)
  → Page classifier → validation → pipeline
```

### ZIP Upload
```
Client → POST /upload (ZIP)
  → server.py: extract_zip() → save images to input_images/
  → Same as image-set from here
```

### Zoho Integration Flow
```
Deluge (Zoho) → POST /api/ocr/extract
  → _run_ocr_extract_pipeline():
    1. _get_zoho_access_token() — OAuth v2 refresh
    2. _download_zoho_file() — download each file from Creator
    3. _merge_to_pdf() — combine images/PDFs to single PDF
    4. _upload_to_supabase() — upload merged PDF to Supabase Storage
    5. Rename merged PDF → input.pdf
    6. run_pipeline() — full OCR extraction
    7. _update_zoho_creator() — PATCH OCR_Status="updated"
```

---

## Error Handling Patterns

- **Batch isolation**: try/except per item in batch — one failure doesn't abort others
- **Checkpoint/resume**: serialized pipeline state in checkpoint.json — /retry reloads it
- **SSE heartbeat**: 10s keepalive for long pipelines
- **Status fallback**: corrupt status.json falls back to in-memory `_last_good_status`
- **LLM parse failures**: JSON decode errors caught and logged — returns `(None, usage)` instead of crashing
- **DB graceful degradation**: if PostgreSQL unavailable, uploads and pipeline still work — only /save-to-db and dedup are affected
- **Memory guard**: _wait_for_memory() blocks pipeline until ≥512MB RAM free (1hr timeout)
- **Zoho token refresh**: OAuth token fetched fresh per request

---

## LLM Provider Configuration

Read from `.env` using prefixes:
- `PRIMARY_PROVIDER`, `PRIMARY_MODEL`, `PRIMARY_API_KEY`, `PRIMARY_BASE_URL`
- `SECONDARY_PROVIDER`, `SECONDARY_MODEL`, `SECONDARY_API_KEY`, `SECONDARY_BASE_URL`

Supported providers: `gemini` (default), `openai`, `deepseek`, `openrouter`, `nvidia`.

Provider-specific behaviors:
- **Gemini**: tries PDF upload first, falls back to page images
- **OpenAI**: always vision, always `response_format: json_object`
- **DeepSeek**: `response_format` only for `deepseek-chat` model
- **OpenRouter**: vision detected by model name keywords, sends HTTP-Referer + X-Title headers
- **NVIDIA**: streaming API, Nemotron models get thinking/reasoning budget

Default: `gpt-4o-mini` for primary and secondary.

---

## Frontend Context (React + TypeScript + Vite)

### Pages
- **UploadPage.tsx** — upload modes (PDF/image/ZIP/batch), sidebar, dedup dialog, batch UI
- **ReviewPage.tsx** — extraction review + save-to-db action

### Components
- **FieldList.tsx** — page-to-section grouping, empty section rendering, Y-order display
- **FieldCard.tsx** — field rendering, checkbox UI, edit state, corrected-field highlighting
- **ImageViewer.tsx** — label/value bbox overlays on page image
- **api/client.ts** — API client bindings
- **types.ts** — shared TypeScript types

---

## Testing

`tests/test_backend.py` — 32 tests covering:
- Bbox merge logic (group_words_into_lines, find_field_bboxes, find_value_bbox)
- StructuredField JSON roundtrip
- Input detection (is_pdf, is_image, is_zip, detect_input_type, detect_item_type)
- ZIP extraction (extract_zip)
- Folder scanning (scan_folder)
- Page classification (all 6 pages, blank, gibberish)
- Page ordering (simple, shuffled, missing page)

Run: `uv run python tests/test_backend.py`
