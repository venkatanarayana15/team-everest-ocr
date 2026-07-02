# OCR Extraction Pipeline — Workflow Plan

## Architecture

```
Frontend (React + Vite)  ──proxy──>  Backend (FastAPI + uvicorn)
                                            │
                                     ExtractionPipeline
                                     ├─ Stage 1: Preprocess (deskew, denoise, render)
                                     ├─ Stage 2: PaddleOCR bbox (CPU/GPU, word-level)
                                     ├─ Stage 3a: Primary model extraction (Gemini/OpenAI/DeepSeek)
                                     ├─ Stage 3b: Combined field mapping (PaddleOCR + position_hint)
                                     ├─ Stage 4: Secondary model verification (OpenAI/Gemini/DeepSeek)
                                     └─ Save results + clean raw_text transcription
```

## Pipeline Stages

### Stage 1 — Preprocess
- Open PDF with PyMuPDF
- Render each page at `config.render_dpi` (300dpi)
- Apply: grayscale → deskew (Canny edge detection) → denoise (fastNlMeans)
- Save both: `pages/page_N.png` (preprocessed) and `pages/page_N_original.png` (raw render)
- Return dict of `{page_num: np.ndarray}`

### Stage 2 — Bounding Box Detection (PaddleOCR)
- Run `PaddleBackend` (default) or `TesseractBackend` (configurable via `Config.ocr_backend`)
- PaddleOCR extracts word-level text, confidence (0-1 → scaled to 0-100), and polygon → (l,t,r,b) bbox
- Returns `list[WordBox]` — same dataclass as Tesseract, so downstream logic is unchanged
- PaddleOCR advantages: much better at handwriting, tilted text, multi-column layouts

### Stage 3a — Primary Model Extraction
- Calls PRIMARY_PROVIDER with `PRIMARY_EXTRACTION_PROMPT`
- Supported providers: `gemini`, `openai`, `deepseek`
- Model returns JSON with:
  - `fields[]`: label, value, confidence_tier (`high`/`medium`/`low`), page, needs_clarification, reason, position_hint, bbox (optional)
  - `overall_confidence`, `clarification_needed`
  - `raw_text`: clean Markdown transcription, with `--- Page {n} ---` markers between pages

### Stage 3b — Combined Field Mapping (PaddleOCR + position_hint)
- `_group_words_into_lines()`: Clusters OCR words into `TextLine` objects (y_tolerance=20px)
- `_find_bbox_line()` enhanced:
  1. Fuzzy-match label to best line (`fuzz.token_set_ratio > 65`)
  2. Use `position_hint` to narrow search (below_label → check subsequent lines; right_of_label → same line right side)
  3. Weight OCR word confidence (prefer words with confidence > 60)
  4. Within matched line, find words fuzzy-matching the value
  5. Colon fallback: words right of colon
  6. Next-line fallback: value on line below the label
  7. Full-line fallback: return entire label line bbox

### Stage 4 — Secondary Model Verification
- Calls SECONDARY_PROVIDER with `SECONDARY_VERIFICATION_PROMPT`
- Supported providers: `gemini`, `openai`, `deepseek`
- Sends: preprocessed page images + primary fields + their bboxes
- Returns corrections + `new_fields[]` for fields the primary model missed
- Merges: apply corrections to existing fields + append new fields
- New fields also go through `_find_bbox_line` for spatial assignment

### Output
- `result.json` — structured data with `raw_text`, `extracted_by`, `verified_by`, `original_value`
- `result.md` — **clean raw_text transcription** (no confidence/notes)
- `result.txt` — plain-text strip of raw_text
- Download filenames include human-readable timestamp: `result_2026-06-24_14-30-00.json`

## Modes (configurable via `.env`)

| Mode | PRIMARY_PROVIDER | SECONDARY_PROVIDER | Behavior |
|------|-----------------|-------------------|----------|
| Gemini → OpenAI | gemini | openai | Primary extraction, secondary verification |
| OpenAI → Gemini | openai | gemini | Primary extraction, secondary verification |
| Only Gemini | gemini | gemini | Both passes use Gemini with different prompts |
| Only OpenAI | openai | openai | Both passes use OpenAI with different prompts |
| DeepSeek → Gemini | deepseek | gemini | Primary with DeepSeek, secondary with Gemini |
| Any mix | gemini/openai/deepseek | gemini/openai/deepseek | Role-based factory |

## Checkpoint / Resume
- After Stage 3b (mapped), saves `checkpoint.json` with step=`"mapped"`
- `POST /retry/{job_id}` skips to Stage 4 if checkpoint exists
- Checkpoint deleted on successful completion

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/ping` | Health check |
| POST | `/upload` | Upload PDF → start pipeline |
| POST | `/retry/{job_id}` | Retry failed job from checkpoint |
| GET | `/status/{job_id}` | Poll pipeline status + live log |
| GET | `/result/{job_id}` | Get extraction result JSON |
| GET | `/pages/{job_id}/{page_num}?width=&original=` | Page image (optional resize, original toggle) |
| POST | `/correct/{job_id}` | Save human correction (preserves original_value) |
| GET | `/metrics` | Per-field accuracy from corrections |
| GET | `/jobs` | List all jobs |
| GET | `/download/{job_id}?format=json\|md\|txt` | Download result with timestamped filename |

## Frontend

### UploadPage
- Drag-drop or click-to-browse PDF upload
- **6-stage pipeline stepper**: Uploaded → Preprocessing → Primary Extraction → Field Mapping → Verification → Complete
- Model-specific stage icons and labels
- Live terminal log synced from backend `status.json`
- Page thumbnails during processing
- "Resume from Checkpoint" button on error

### ReviewPage
- **4 view tabs**: Fields | **Transcription** | Markdown | Plain Text
- **Fields tab**: Split-pane: left = FieldList, right = ImageViewer with bbox overlay
- **Transcription tab**: Split-pane: left = editable TranscriptionPane, right = ImageViewer (side-by-side cross-check)
- **Markdown tab**: full-page rendered raw_text
- **Plain Text tab**: full-page raw plain-text
- **Summary card**: field count, verified, corrected, new counts
- **Filter pills**: All | Low conf | Needs review | Corrected
- Download bar: `.json` | `.md` | `.txt`
- Keyboard shortcuts: `j`/`k` navigate fields, `Enter` edit, `Escape` cancel

### Components
- `StatusHeader`: page nav, confidence bar, field stats
- `ImageViewer`: page image toggle (preprocessed/original), zoom slider, **color-coded bbox** by confidence tier
- `TranscriptionPane`: parses raw_text per page, finds field labels, renders values as inline-editable spans; click label → highlight bbox on image; double-click value → inline edit
- `FieldCard`: label, value (editable), **provenance badge**, **correction diff** (strikethrough original), **confidence pill**, verification status, reason
- `FieldList`: scrollable list, filterable
- `SplitPane`: draggable left/right split
- `ConfidenceBar`: color-coded bar (green ≥80, yellow ≥60, red <60)

## Configuration (`.env`)
```
PRIMARY_PROVIDER=gemini
PRIMARY_MODEL=gemini-2.5-flash
PRIMARY_API_KEY=...

SECONDARY_PROVIDER=openai
SECONDARY_MODEL=gpt-4o-mini
SECONDARY_API_KEY=...

# DeepSeek example (OpenAI-compatible):
# PRIMARY_PROVIDER=deepseek
# PRIMARY_MODEL=deepseek-chat
# PRIMARY_API_KEY=sk-...
```

OCR backend defaults to PaddleOCR. Fallback to Tesseract via config change.

## Key Files

| File | Role |
|------|------|
| `src/server.py` | FastAPI server, all endpoints, checkpoint/resume, render helpers, timestamped downloads |
| `src/extraction_pipeline.py` | Pipeline orchestrator, run_dual(), enhanced mapping, verify_secondary() |
| `src/model_client.py` | ModelClient ABC + OpenAI/Gemini/DeepSeek implementations + role-based factory |
| `src/prompt_templates.py` | PRIMARY_EXTRACTION_PROMPT (page markers) + SECONDARY_VERIFICATION_PROMPT |
| `src/backends.py` | OCRBackend ABC + TesseractBackend + PaddleBackend + factory |
| `src/config.py` | Config dataclass (includes ocr_backend field) |
| `src/preprocessing.py` | Image processing: deskew, denoise, adaptive threshold |
| `frontend/src/pages/UploadPage.tsx` | Upload + 6-stage pipeline monitoring |
| `frontend/src/pages/ReviewPage.tsx` | Result review, 4 tabs, filters, shortcuts |
| `frontend/src/components/TranscriptionPane.tsx` | Editable raw_text per-page, inline field editing |
| `frontend/src/components/FieldCard.tsx` | Provenance badge, correction diff, confidence pill |
| `frontend/src/components/ImageViewer.tsx` | Original toggle, zoom slider, color bbox |
