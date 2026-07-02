# Plan 3: Dashboard + Rate Limiting + SSE + Parallel Pipeline

## Overview
Full rewrite of the backend pipeline with:
- Dashboard page for browsing completed batches
- Rate limiting to avoid 429s from LLM APIs
- Server-Sent Events (SSE) instead of 3s polling
- ThreadPoolExecutor for parallel PDF processing
- Per-PDF and overall progress tracking

## Files Changed

### New files
| File | Purpose |
|------|---------|
| `src/ratelimit.py` | RateLimiter (sliding window) + 429 retry + jitter |
| `src/pipeline.py` | ThreadPoolExecutor orchestrator with per-PDF progress callbacks |
| `frontend/src/pages/DashboardPage.tsx` | Folder-grid dashboard of completed batches |
| `frontend/src/pages/FolderReviewPage.tsx` | Sidebar + DocumentReview for selected batch |
| `docs/plan3.md` | This document |

### Modified files
| File | Change |
|------|--------|
| `src/model_client.py` | Each client uses RateLimiter + `call_with_retry` |
| `src/server.py` | SSE `/stream/{id}` endpoint, in-memory progress store, integrate pipeline |
| `frontend/src/api/client.ts` | Add `subscribeToJob()` SSE helper |
| `frontend/src/pages/UploadPage.tsx` | Replace polling with SSE, add progress bars to sidebar |
| `frontend/src/App.tsx` | Three-view routing: dashboard / upload / review |

## Architecture

### Rate Limiting (`src/ratelimit.py`)
- **RateLimiter**: sliding window (60s), configurable RPM via `LLM_RATE_LIMIT_RPM`
- **`call_with_retry`**: wraps any callable, detects 429 across OpenAI/Gemini/DeepSeek/OpenRouter, retries with `(2^attempt + jitter)` backoff
- **`is_rate_limited`**: checks `status_code`, `code`, and string patterns

### SSE (`/stream/{job_id}`)
Backend pushes real-time updates:
```json
{
  "status": "primary_extraction",
  "message": "Extracting fields...",
  "log": [...],
  "progress": {
    "overall": 45,
    "pdfs": {
      "file1.pdf": { "progress": 80, "stage": "secondary_verification" },
      "file2.pdf": { "progress": 30, "stage": "preprocessing" }
    }
  }
}
```
Clients subscribe via native `EventSource`, no libraries needed.

### ThreadPoolExecutor (`src/pipeline.py`)
- `run_batch(pdf_paths, job_dir, progress_cb)` — up to 8 PDFs concurrently
- Each PDF goes through: preprocess → tesseract → primary → verify → save
- Progress callback invoked on every stage change

### Progress Display (UploadPage sidebar)
- **Top**: overall progress bar (all PDFs averaged) with percentage
- **Each PDF**: individual progress bar with stage label and percentage
- Green gradient bar fills as progress increases

## Dashboard (folder grid view)
- `DashboardPage` fetches `/jobs` → shows card grid
- Each card: filename, page/pdf count, confidence, status
- "+ New Batch" navigates to upload
- Click card → `FolderReviewPage`

## Folder Review (sidebar + DocumentReview)
- Left sidebar lists PDFs within the batch
- Main area reuses `DocumentReview` exactly (image 55% + ExtractedDataPanel 45%)
- "Back" → Dashboard

## Progress Granularity (per PDF)
| Range | Stage |
|-------|-------|
| 0-10% | Queued / loading |
| 10-30% | Preprocessing (per page increment) |
| 30-45% | Tesseract bbox |
| 45-65% | Primary extraction |
| 65-75% | Field mapping |
| 75-90% | Secondary verification |
| 90-100% | Saving / Done |

## Env Config
| Key | Default | Description |
|-----|---------|-------------|
| `LLM_RATE_LIMIT_RPM` | `30` | Max requests per minute per model client |
| `LLM_MAX_RETRIES` | `5` | Max retries on 429 |
| `MAX_CONCURRENT_JOBS` | `3` | Global job semaphore |
| `MIN_FREE_MEM_MB` | `512` | Memory throttle threshold |
