# OCR Extraction — Architecture Plan

## Goal
Fully automated OCR extraction from PDF forms — no manual corrections needed.
Upload multiple PDFs, get structured JSON + Markdown results.

## Core Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Preprocessing parallelism | `ThreadPoolExecutor(max_workers=8)` | PyMuPDF + OpenCV release GIL during I/O and heavy ops. Simpler than processes (no pickling). |
| LLM calls | One call per PDF (sequential) | Guarantees correct file attribution, isolates failures, fits 10-page limit naturally |
| Frontend | Static HTML/JS served from FastAPI | Zero build step, survives restarts, session-persistent via localStorage |
| Model | Gemini 2.5 Flash (primary) | Fast, handles vision, API key already configured |
| Error isolation | Skip failed PDFs, return partial results | Corrupt file doesn't block the rest |
| State persistence | Disk-based (`output/<job_id>/`) | Survives server restart, browser close, session change |

## Pipeline Flow

```
User uploads 1-10 PDFs → POST /upload (multipart, multiple files)
  │
  ▼
Background thread: _run_pipeline()
  │
  ├── For each PDF (in order):
  │     ├── Render pages (PyMuPDF, 300 DPI)
  │     ├── Preprocess ALL pages in parallel (ThreadPoolExecutor)
  │     │     └── deskew + denoise (OpenCV)
  │     ├── Send pages to LLM with EXTRACTION_PROMPT
  │     └── Parse + validate response → per-PDF fields
  │
  ├── Aggregate all per-PDF results
  ├── Write result.json + result.md + result.txt + result.html
  └── Status → "done"
```

## File Layout

```
src/
├── __init__.py
├── config.py              # Config dataclass (simplified)
├── preprocessing.py       # deskew, denoise, to_grayscale (unchanged)
├── pdf_ingestion.py       # PDF → pages (unchanged)
├── model_client.py        # Gemini/OpenAI/DeepSeek clients (unchanged)
├── prompt_templates.py    # EXTRACTION_PROMPT (comprehensive one-shot)
├── pipeline.py            # Orchestrator: preprocess → extract → write
└── server.py              # FastAPI routes only (thin)
static/
├── index.html             # Upload + results viewer
├── style.css              # Styling
└── script.js              # Upload, polling, result display, downloads
```

## Removed Files
- `src/backends.py` — PaddleOCR/Tesseract not needed
- `src/extraction_pipeline.py` — Old pipeline (bbox merging, secondary verification)
- `src/gemini_ocr.py` — Standalone CLI
- `frontend/` — Replaced by `static/`

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serve static/index.html |
| GET | `/ping` | Health check |
| POST | `/upload` | Upload multiple PDFs (max 10 files) |
| GET | `/status/{job_id}` | Poll job progress |
| GET | `/result/{job_id}` | Get completed results |
| GET | `/pages/{job_id}/{page_num}` | Get page image (processed or original) |
| GET | `/page_info/{job_id}/{page_num}` | Get page metadata (source PDF, page number) |
| GET | `/download/{job_id}` | Download results (json/md/txt/html) |
| GET | `/jobs` | List all historical jobs |


