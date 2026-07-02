# Project State — OCR Extraction Pipeline

## Architecture
- Backend: FastAPI + uvicorn on port 8000
- Frontend: React + TypeScript + Vite on port 5173
- Python via `uv run python` (3.13.12 in `.venv`)
- OCR: Tesseract 5.5.2 static binary in `bin/`
- Database: PostgreSQL (asyncpg) with dedup + save-to-DB

## Run Commands
- Backend: `uv run uvicorn src.server:app --port 8000`
- Frontend: `cd frontend && npm run dev`
- Tests: `uv run python tests/test_backend.py`

## Pipeline
1. Preprocess (deskew, denoise, grayscale)
2. Bbox detection (Tesseract)
3. Primary extraction (LLM → JSON fields)
4. Merge fields with bboxes
5. Secondary verification (LLM corrects + adds missing)
6. Save result.json + markdown/text/html

## LLM Providers
- `.env`: `PRIMARY_PROVIDER=openai`, `PRIMARY_MODEL=gpt-4o-mini`
- `.env`: `SECONDARY_PROVIDER=openai`, `SECONDARY_MODEL=gpt-4o-mini`
- Gemini key also in `.env` (exhausted free tier)

## Key Features Implemented
- section_number (int | null) on every StructuredField
- sections array (number, name, page) in result.json
- Server-side _derive_sections() fallback from raw_text + field labels
- Frontend FieldList groups by page → section, shows N/A for empty sections
- Three-tier section fallback: API → raw_text headings → field label prefixes
- Field order sorted by Y-position (bbox[1]) to mirror PDF page layout
- Header fields: Volunteer Name, Co-Volunteer Name, Date of Visit (section=null)
- Checkbox visual rendering (✓/✗/? with colored toggle)
- Label (blue) + Value (green) bbox rendering on page image
- Table rows: "{Section} — Row {n} — {Column}"
- Conditional fields: value="N/A" when condition unmet
- Y-position indicator on field cards
- Green highlight border/bg for manually corrected fields
- Original filename preserved in `original_name.txt` per job
- PostgreSQL database with 4 tables (pdfs, extraction_results, extracted_fields, corrections_log)
- PDF hash dedup (SHA256) on upload, returns duplicate info to client
- GET /pdfs endpoint listing all uploaded documents with status
- POST /save-to-db/{job_id} saves extraction results to PostgreSQL
- Frontend UploadPage sidebar listing uploaded docs (clickable to review)
- Batch upload support (multiple files, folder upload)
- Dedup dialog when re-uploading existing PDF

## Multi-Input Support (Features 1-5)

### Feature 1 — Multiple Input Types
- **Mode A (PDF)**: `POST /upload` — single PDF, splits into pages
- **Mode B (Images)**: `POST /upload-images` — 6 images, auto-classified by content
- **Mode C (ZIP)**: `POST /upload` with .zip — extracts images, classifies pages

### Feature 2 — Batch Processing
- `POST /upload-batch` — mixed batch in single request
- `POST /process-folder` — server-side folder scan and batch process
- Each document gets independent job_id, continues on failure

### Feature 3 — Mixed Batch
- `src/input_handler.py`: `detect_input_type()`, `detect_item_type()`, `scan_folder()`
- Auto-detects PDF vs image set vs ZIP in a batch
- Routes to correct pipeline automatically

### Feature 4 — Automatic Page Classification
- `src/page_classifier.py`: `PageClassifier` class
- Content-based page numbering using OCR text + template matching
- Uses: keyword signatures, section headers, field number patterns (1.x, 2.x, etc.)
- No filename dependency — classifies purely by document layout
- Returns confidence score per page
- `resolve_order()` handles shuffled/reordered uploads

### Feature 5 — Page Validation
- Validates: exactly 6 pages, no duplicates, no missing, no blank/unreadable
- `GET /validate/{job_id}` returns full validation report
- Status "incomplete" + validation JSON when validation fails
- Pipeline continues processing remaining documents in batch
- Validation checks: duplicate pages, missing pages, blank pages, unreadable pages, low OCR confidence

## Form Template Fields (I Am The Change — Home Visit Questionnaire)

### Header (Page 1, section=null)
- Volunteer Name [text]
- Co-Volunteer Name [text]
- Date of Visit [text]

### Section 1 — Student Profile (Page 1)
- 1.1 Application ID [text]
- 1.2 Student Full Name [text]
- 1.3 Gender [radio]: Male, Female, Others

### Section 2 — Family Background (Pages 1-2)
- Page 1:
  - 2.1 Family Status [radio]: Single Parent, Parentless, Having both parents
  - 2.2 Relationship Details — Year of Death / Separation [text]
  - 2.2 Relationship Details — Reason for Death / Separation [text]
- Page 2:
  - 2.3 Is Father/Mother photograph kept at home? [radio]: Yes, No
  - 2.4 Government ID Verified [radio]: Aadhaar Card, Ration Card, Driving Licence, Voter ID, Other
  - 2.5 Family Members [table]: Name, Age, Education, Occupation, Annual Income

### Section 3 — Housing Condition (Pages 2-3)
- Page 2:
  - 3.1 House Ownership [radio]: Own, Rented
  - 3.1.1 If rented, what is the rent amount? [text]
  - 3.2 Type of Home [checkbox]: Individual, Private Apartment, Housing Board, Line House, Others
- Page 3:
  - 3.3 Type of Ceiling [checkbox]: Roof, Tiled, Asbestos, Concrete
  - 3.4 Number of Bedrooms [text]
  - 3.4.1 Type of Bedroom [radio]: Separate Bedroom, No Separate Bedroom
  - 3.5 Bathroom [radio]: Separate, Common for Apartment
  - 3.6 Kitchen Type [checkbox]: Separate Kitchen, Hall with Kitchen

### Section 4 — Financial Background (Pages 3-5)
- Page 3:
  - 4.1 Assets at Home [checkbox]: Washing Machine, Fridge, AC, LED TV, Two-Wheeler, Car, Smartphone, Separate Wi-Fi, Others
  - 4.2 Amount of Last Electricity Bill [text]
  - 4.3 Do you own any other assets...? [radio]: Yes, No
  - 4.3.1 If yes, list their properties [table]: Property Description, Owner Name, Approximate Value
- Page 4:
  - 4.4 Apart from your job...? [radio]: Yes, No
  - 4.4.1 If yes, list other sources of income [table]: Source, Amount
  - 4.5 Income Type [radio]: Monthly, Daily, Weekly, Ad-Hoc
  - 4.6 Do you have any loans? [radio]: Yes, No
  - 4.6.1 If yes, share Loan Purpose... [table]: Loan Purpose, Loan Amount Taken, Pending Loan Amount
  - 4.7 If you choose any college, how much is the college fee? [text]
- Page 5:
  - 4.8 If the college fee is higher, how will you manage it? [text]
  - 4.9 If you do not receive this scholarship, how will you pay the fees? [text]

### Section 5 — Health Information (Page 5)
- 5.1 Does the student have any health issues? [radio]: Yes, No
- 5.2 If yes, list the health issues [text] — N/A when 5.1=No

### Section 6 — Student Commitment (Page 5)
- 6.1 Will you study college for three years without any obstacle? [text]
- 6.2 If we have a training program within 15 km...? [radio]: Yes, No, Maybe
- 6.3 Are you ready to send your son/daughter...? [radio]: Yes, No

### Section 7 — Scholarship Information (Page 6)
- 7.1 Has the student received or applied for any other scholarships...? [text]

### Section 8 — Volunteer Observation (Page 6)
- 8.1 What is your opinion about the student...? [text]
- 8.2 Will you recommend this student for this scholarship? [radio]: Yes, No, Not Sure
- 8.3 Any other comments you want to share? [text]

## Relevant Files
- `src/prompt_templates.py`: Full prompt with template reference
- `src/extraction_pipeline.py`: StructuredField (section_number), PipelineResult (sections), merge/verify logic
- `src/server.py`: Checkpoint/resume, _derive_sections(), dedup upload, /save-to-db, /pdfs, image pipeline, batch endpoints
- `src/database.py`: PostgreSQL asyncpg module, 4-table schema, all CRUD functions
- `src/backends.py`: TesseractBackend with static binary path + `process_images()` method
- `src/config.py`: OCR backend = "tesseract"
- `src/input_handler.py`: Input type detection (PDF/image/ZIP/mixed), ZIP extraction, folder scanning
- `src/page_classifier.py`: PageClassifier — content-based page classification for 6-page questionnaire
- `frontend/src/types.ts`: Field, Section, JobResult types
- `frontend/src/components/FieldList.tsx`: Page→section grouping, N/A display, Y-sort
- `frontend/src/components/FieldCard.tsx`: Checkbox UI, edit, green highlight for corrected, bbox indicators
- `frontend/src/components/ImageViewer.tsx`: Label/value bbox rendering
- `frontend/src/pages/UploadPage.tsx`: Mode tabs (PDF/Images/ZIP/Mixed), sidebar, batch results, dedup dialog
- `frontend/src/pages/ReviewPage.tsx`: "Save it in DB" button, SplitPane layout
- `frontend/vite.config.ts`: Proxy routes for all endpoints
- `frontend/src/api/client.ts`: uploadPDF, uploadImages, uploadBatch, processFolder, getValidation, listPDFs, saveToDB
- `tests/test_backend.py`: 28 unit tests (bbox logic + input handler + page classifier)
- `AGENTS.md`: Full project state documentation
- `.env`: API keys and provider config
- `bin/tesseract` and `bin/eng.traineddata`: Static tesseract 5.5.2 binary + language data
