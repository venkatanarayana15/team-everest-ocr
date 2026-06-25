# Project Context

## Overview
Two-model document extraction pipeline. Preprocesses scanned PDFs → detects text regions via Tesseract (CPU bbox) → primary model (Gemini/OpenAI) extracts structured fields + raw transcription → Tesseract line-level mapping with position hints → secondary model (OpenAI/Gemini) verifies and adds missed fields → final output with clean transcription.

## Why Two Models
- **Primary model**: semantic extraction, label-value pairing, handwriting recognition, position hints
- **Tesseract**: precise pixel-level word bboxes, confidence weighting
- **Secondary model**: cross-check primary's output, catch missed fields, correct errors
- Each model acts as a check on the other, improving accuracy over single-model approaches

## Why Raw Text Transcription
- `.md`/`.txt` outputs serve as clean human-readable document copies
- No confidence scores, notes, or technical metadata pollute the transcription
- Useful for quick review, sharing, or downstream processing

## Environment
- **Python**: 3.13
- **Package manager**: `uv` (uv.lock)
- **Backend**: FastAPI, uvicorn (no --reload)
- **Frontend**: React 19 + Vite 6, `npm run dev` on :5173
- **Proxy**: Vite proxies all API routes → localhost:8000
- **GPU**: NVIDIA GeForce RTX 3050 6GB (CUDA 13.1) — not used
- **Tesseract**: 5.3.4 (CPU)

## Configuration (`.env`)
```
PRIMARY_PROVIDER=gemini|openai
PRIMARY_MODEL=gemini-2.5-flash|gpt-4o-mini
PRIMARY_API_KEY=...

SECONDARY_PROVIDER=openai|gemini
SECONDARY_MODEL=gpt-4o-mini|gemini-2.5-flash
SECONDARY_API_KEY=...
```

## Pipeline Flow
```
PDF Upload
  ↓
Stage 1: Preprocess (render → deskew → denoise → save PNGs + originals)
  ↓
Stage 2: Tesseract bbox (word-level text + confidence + coordinates)
  ↓
Stage 3a: Primary model extraction (Gemini/OpenAI → fields + raw_text)
  ↓
Stage 3b: Combined field mapping (Tesseract lines + position_hint + confidence weighting)
  ↓
[Checkpoint saved]
  ↓
Stage 4: Secondary model verification (OpenAI/Gemini → corrections + new fields)
  ↓
Save results (JSON with raw_text, MD transcription, TXT transcription)
  ↓
Done
```

## File Layout
```
output/<job_id>/
├── input.pdf
├── pages/
│   ├── page_1.png        # preprocessed
│   ├── page_1_original.png  # raw render
│   └── ...
├── status.json
├── checkpoint.json
├── corrections.json
└── results/
    ├── result.json        # structured + raw_text
    ├── result.md          # clean raw_text transcription
    └── result.txt         # plain text transcription
```

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Two-model pipeline | Primary extracts, secondary verifies — cross-check improves accuracy |
| position_hint from model | Guides Tesseract line search (below_label, right_of_label, etc.) |
| Tesseract confidence weighting | Prefer high-OCR-confidence words when matching bboxes |
| raw_text in output | Clean transcription for MD/TXT download, no technical metadata |
| Save original + preprocessed | Viewer toggle for comparison |
| Configurable providers | Swap model ordering or use same model for both passes |
| Checkpoint after mapping | Expensive extraction pass not re-run on retry |

## Frontend Features

### UploadPage
- 6-stage stepper with model-specific labels
- Live log terminal synced from backend
- Page thumbnails
- Resume from checkpoint button

### ReviewPage
- 4 view tabs: Fields, Transcription, Markdown, Plain Text
- Transcription tab: rendered Markdown + copy button
- Summary card: counts of fields/verified/corrected/new
- Filter pills: All, Low conf, Needs review, Corrected
- Keyboard shortcuts: j/k navigate, Enter edit, Escape cancel

### FieldCard
- Provenance badge: "Gemini → OpenAI"
- Correction diff: `~~original~~` → `corrected`
- Confidence pill: 🟢 High / 🟡 Medium / 🔴 Low

### ImageViewer
- Toggle: preprocessed vs original
- Zoom slider (50%–200%)
- Color-coded bbox by confidence tier

## Dependencies
- `PyMuPDF`, `opencv-python`, `pillow`, `numpy` — image processing
- `pytesseract` — CPU bbox detection
- `google-generativeai` — Gemini client
- `openai` — OpenAI client
- `rapidfuzz` — fuzzy string matching
- `fastapi[standard]`, `uvicorn[standard]`, `python-multipart` — server
- Frontend: `react`, `react-dom`, `react-markdown`, `remark-gfm`, `vite`, `typescript`

## Startup Commands
```bash
# Backend (from ocr-extract/)
uv run uvicorn src.server:app --port 8000

# Frontend (from ocr-extract/frontend/)
npm run dev
```

## Constraints
- Server started from project root
- Never use `--reload` (kills background threads)
- `logging.basicConfig` AFTER imports
- `.env` and `output/` gitignored
