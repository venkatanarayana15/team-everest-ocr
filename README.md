# OCR Extraction — Home Visit Form Processor

AI-powered OCR extraction system that processes Home Visit Forms (PDFs / scanned
images), extracts structured fields with bounding boxes, and pushes them to
Zoho Creator. Includes a side-by-side review UI with click-to-locate field
highlighting.

## Features

- **PDF / image / ZIP / folder batch** uploads with live progress via SSE
- **Gemini-based extraction** with per-field confidence, page attribution and
  bounding boxes (`bbox` / `value_bbox`) for click-to-locate review
- **Rate-limit aware**: enforces Gemini's 14 req/min + 250k tokens/min quotas
  (request + token budgets, coordinated 429 backoff, circuit breaker)
- **Side-by-side review UI** — click a field to highlight it on the PDF page
- **Per-job processing logs** viewable in the UI
- **Zoho Creator writeback**, Supabase storage, optional Postgres persistence
- Batch auto-processing from Zoho reports on startup (optional)

## Tech Stack

| Layer    | Tech |
|----------|------|
| Backend  | Python 3.13+, FastAPI, uvicorn, google-genai |
| Frontend | React 19 + Vite (SPA) |
| Storage  | Supabase Storage, optional Postgres (asyncpg) |
| Ops      | `uv` (recommended) or pip + venv |

## Prerequisites

- **Git**
- **Python 3.13+** (`python3 --version`)
- **Node.js 18+** with npm (`node --version`)
- (Optional, recommended) **uv** — `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Quick Start (one file)

After cloning, run **one file** — it installs everything (backend, frontend,
system tools) and prepares your config:

```bash
git clone <your-repo-url>
cd new-ocr
./setup.sh
```

`setup.sh` will:

1. Create `.env` from `.env.example` (never overwrites an existing `.env`)
2. Install backend Python dependencies (`uv sync`, or `python3 -m venv` + pip)
3. Install system packages on Debian/Ubuntu (`tesseract-ocr`, `poppler-utils`,
   `libgl1` — prompts for sudo if needed)
4. Install frontend dependencies (`npm install` in `frontend/`)
5. Verify the backend imports and print run instructions

## Step-by-Step Guide

### Step 1 — Clone & configure

```bash
git clone <your-repo-url>
cd new-ocr
./setup.sh
```

### Step 2 — Fill in your secrets

Edit the `.env` file created by the script and add your API keys
(see `.env.example` for the full list with comments):

| Variable | Required | Purpose |
|----------|----------|---------|
| `GEMINI_API_KEY` | Yes | Gemini model access |
| `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN` | Yes | Zoho Creator integration |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | Yes | File storage |
| `DATABASE_URL` | No | Postgres persistence (skipped if empty) |
| `WEBHOOK_SECRET` | No | Auth for webhook endpoint |

> Not using Zoho/Supabase yet? Set the `ZOHO_*` / `SUPABASE_*` values to any
> placeholder — but fill `GEMINI_API_KEY` for extraction to work.

### Step 3 — Run the backend

```bash
.venv/bin/python -m src.server
```

Starts uvicorn on `http://0.0.0.0:8000`.

### Step 4 — Run the frontend (separate terminal)

```bash
cd frontend
npm run dev
```

Vite dev server runs on `http://localhost:5173` and proxies all `/upload`,
`/status`, `/result`, `/stream` … calls to the backend on port 8000.

### Step 5 — Use the app

Open **http://localhost:5173** and:

- Upload a single PDF / image / ZIP, or process a whole folder
- Watch live progress and processing logs
- On completion, review the extracted fields side-by-side with the PDF
- Click any field to highlight its location on the page

## How It Works

1. **Upload** → job directory created under `output/<job_id>` with a
   `status.json` (live status + log array)
2. **Preprocess** → pages rendered at `RENDER_DPI`, deskewed/denoised
3. **Extract** → Gemini extracts fields per page-group (`PAGE_GROUP_SIZE`),
   returning label/value/confidence/page/`bbox`/`value_bbox`
4. **Post-process** → boolean normalization, hierarchy grouping, mutual
   exclusivity checks, secondary verification (if configured)
5. **Save** → `results/result.json` (+ markdown/text/html), optional DB write
6. **Writeback** (optional) → Zoho Creator + Supabase upload

## Configuration Reference

All settings are env vars — see `.env.example`. Key ones:

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_RATE_LIMIT_RPM` | `14` | Gemini requests/minute budget |
| `GEMINI_RATE_LIMIT_TPM` | `250000` | Gemini tokens/minute budget |
| `GEMINI_429_BACKOFF_SEC` | `30` | Global pause after a 429 quota error |
| `GEMINI_MAX_CONCURRENCY` | `12` | Max concurrent Gemini calls |
| `PAGE_GROUP_SIZE` | `2` | Pages per extraction call |
| `MAX_CONCURRENT_JOBS` | `15` | Concurrent jobs server-wide |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Allowed frontend origins |

## Troubleshooting

- **`429 RESOURCE_EXHAUSTED` (quota)** — the app now pauses all requests for
  `GEMINI_429_BACKOFF_SEC` and respects the token budget; lower
  `GEMINI_MAX_CONCURRENCY` or `GEMINI_RATE_LIMIT_TPM` if you keep hitting it.
- **`tesseract` not found** — install `tesseract-ocr` (the classifier falls
  back to vision-only if missing).
- **Import check failed during setup** — usually a missing env var; review
  `.env` (Step 2) and restart the backend.
- **Logs show "No logs available."** — logs are written to
  `output/<job_id>/result.logs` per job; re-run or retry the job after the
  fix in this repo (single-upload jobs get file logs too).

## Project Layout

```
src/                     Backend (FastAPI)
  server.py              API routes, SSE, job orchestration
  extraction_pipeline.py Gemini extraction + post-processing
  pipeline_runner.py     Single/batch pipeline execution
  model_client.py        LLM client, rate limiters, retries
  status.py              status.json, SSE push, per-job logging
  zoho_integration.py    Zoho Creator / Supabase integration
frontend/                React + Vite SPA
requirements.txt         pip-installable backend deps
pyproject.toml           Project metadata + uv deps
setup.sh                 One-file install (backend + frontend + system)
.env.example             Template for environment config
```

