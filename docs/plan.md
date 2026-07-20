# OCR Extraction — Architecture Plan
- 6.2 → page 5
- 6.3 → page 6
▣  Build · Big Pickle · 13.8s
for key in ("Application_ID", "Applicant_ID"):
                    app_id_obj = record.get(key) or {}
                    if isinstance(app_id_obj, dict):
                        num_id = str(app_id_obj.get("ID") or "")
                        if num_id.isdigit():
                            logger.info("Resolved Application_ID via field '%s': %s", key, num_id)
                            return num_id
                # Log what we actually got to help diagnose if neither key matches
                logger.warning("Application_ID lookup: field not found; record keys=%s", list(record.keys())[:20]) 

use this lines it will upload with correct application id
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




create table public.ocr_documents (
  id uuid not null default extensions.uuid_generate_v4 (),
  file_name text not null,
  status text not null default 'pending'::text,
  job_id text null,
  processing_time double precision null,
  confidence_score double precision null,
  num_pdfs integer null,
  result_json jsonb null,
  volunteer_name text null,
  co_volunteer_name text null,
  date_of_visit text null,
  application_id text null,
  student_full_name text null,
  gender text null,
  family_status text null,
  relationship_death_year text null,
  relationship_death_reason text null,
  photograph_kept_at_home text null,
  government_id_verified text null,
  family_members jsonb null,
  house_ownership text null,
  rent_amount text null,
  type_of_home text null,
  type_of_ceiling text null,
  number_of_bedrooms text null,
  type_of_bedroom text null,
  bathroom text null,
  kitchen_type text null,
  assets_at_home jsonb null,
  owns_other_assets text null,
  other_assets_details jsonb null,
  has_other_income text null,
  other_income_sources jsonb null,
  income_type text null,
  has_loans text null,
  loan_details jsonb null,
  college_fee text null,
  manage_higher_fee text null,
  manage_without_scholarship text null,
  has_health_issues text null,
  health_issues_description text null,
  study_commitment text null,
  training_program_availability text null,
  ready_for_skill_classes text null,
  other_scholarships text null,
  volunteer_opinion text null,
  recommend_student text null,
  volunteer_comments text null,
  created_at timestamp with time zone not null default now(),
  updated_at timestamp with time zone not null default now(),
  processed_at timestamp with time zone null,
  
  electricity_bill_amount text null,
  file_hash text null,
  photograph_notes text null,
  assets_ac text null,
  assets_car text null,
  assets_fridge text null,
  assets_led_tv text null,
  assets_others text null,
  assets_others_specify text null,
  assets_smartphone text null,
  assets_two_wheeler text null,
  assets_washing_machine text null,
  assets_wifi text null,
  ceiling_asbestos text null,
  ceiling_concrete text null,
  ceiling_roof text null,
  ceiling_tiled text null,
  gov_id_aadhaar text null,
  gov_id_driving text null,
  gov_id_other text null,
  gov_id_other_specify text null,
  gov_id_ration text null,
  gov_id_voter text null,
  home_type_apartment text null,
  home_type_housing_board text null,
  home_type_individual text null,
  home_type_line_house text null,
  home_type_others text null,
  home_type_others_specify text null,
  income_type_adhoc text null,
  income_type_adhoc_specify text null,
  income_type_daily text null,
  income_type_daily_specify text null,
  income_type_monthly text null,
  income_type_monthly_specify text null,
  income_type_weekly text null,
  income_type_weekly_specify text null,
  constraint ocr_documents_pkey primary key (id),
  constraint uq_ocr_documents_job_id unique (job_id)
) TABLESPACE pg_default;

create index IF not exists idx_ocr_documents_result_json_job_id on public.ocr_documents using btree (((result_json ->> 'job_id'::text))) TABLESPACE pg_default;

create trigger trg_ocr_documents_updated_at BEFORE
update on ocr_documents for EACH row
execute FUNCTION update_updated_at_column ();