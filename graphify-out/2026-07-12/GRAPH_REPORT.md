# Graph Report - new-ocr  (2026-07-12)

## Corpus Check
- 68 files · ~1,498,924 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 730 nodes · 1482 edges · 42 communities (36 shown, 6 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 58 edges (avg confidence: 0.53)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `9328292c`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- server.py
- model_client.py
- zoho_integration.py
- test_backend.py
- pipeline_runner.py
- ExtractionPipeline
- ChandraOcrClient
- package.json
- datalab_schema.py
- compilerOptions
- ExtractedDataPanel.tsx
- checkbox_vision.py
- react-dom_client.js
- tesseract.py
- client.ts
- types.ts
- compilerOptions
- Field
- DocumentReview.tsx
- FieldCard.tsx
- FieldList.tsx
- PipelineProcessingView.tsx
- StatusHeader.tsx
- dependencies
- test_batch.py
- SplitPane.tsx
- tsconfig.json
- vite-env.d.ts
- package.json
- ocr-extract
- AGENTS.md
- model_client.py
- database.py
- run_batch_pdfs_pipeline_async
- process_pending_on_startup
- OpenAICompatibleClient
- RolmOcrClient

## God Nodes (most connected - your core abstractions)
1. `ExtractionPipeline` - 32 edges
2. `PageClassifier` - 27 edges
3. `_set_status()` - 25 edges
4. `ModelClient` - 24 edges
5. `run_pipeline()` - 21 edges
6. `Field` - 20 edges
7. `DatalabOcrClient` - 20 edges
8. `StructuredField` - 20 edges
9. `run_batch_pdfs_pipeline_async()` - 19 edges
10. `OcrExtractRequest` - 19 edges

## Surprising Connections (you probably didn't know these)
- `test_is_pdf()` --calls--> `is_pdf()`  [EXTRACTED]
  tests/test_backend.py → src/server.py
- `test_is_image()` --calls--> `is_image()`  [EXTRACTED]
  tests/test_backend.py → src/server.py
- `test_detect_item_type_pdf()` --calls--> `detect_item_type()`  [EXTRACTED]
  tests/test_backend.py → src/server.py
- `test_extract_zip()` --calls--> `extract_zip()`  [EXTRACTED]
  tests/test_backend.py → src/server.py
- `test_scan_folder()` --calls--> `scan_folder()`  [EXTRACTED]
  tests/test_backend.py → src/server.py

## Import Cycles
- None detected.

## Communities (42 total, 6 thin omitted)

### Community 0 - "server.py"
Cohesion: 0.10
Nodes (16): Response, Wake up a waiting collect() worker when the webhook fires., signal_webhook(), _auto_cleanup_loop(), _extract_epoch_from_job_id(), _find_original_pdf(), get_page_image(), get_result() (+8 more)

### Community 1 - "model_client.py"
Cohesion: 0.14
Nodes (12): DatalabOcrClient, Datalab OCR client — sends PDF to Datalab /api/v1/extract for structured field e, Full submit + poll (backward compatible)., Submit PDF to Datalab and return a DatalabJob immediately (no polling)., Poll a submitted DatalabJob until complete.          Features:         - Rate-li, Single rate-limited GET to fetch extraction result (used after webhook signal)., Async token-bucket rate limiter.      Smooths request rate to stay within a per-, Acquire *tokens* from the bucket, blocking until available. (+4 more)

### Community 2 - "zoho_integration.py"
Cohesion: 0.08
Nodes (46): BaseModel, HTTPResponse, Request, build_synthetic_result(), main(), print_summary(), Build a synthetic OCR result with all field categories and print _build_creator_, test_zoho_update() (+38 more)

### Community 3 - "test_backend.py"
Cohesion: 0.07
Nodes (51): PageClassification, PageClassifier, Page classifier — determines page number (1-6) from image content.  Uses Tessera, Classify a page from an image file., Classify all images and return a mapping of image_index -> classification., Resolve page ordering from classifications.          Returns:           - mappin, Classifies page images into page numbers 1-6 based on OCR content., Classify a single page from its OCR text content. (+43 more)

### Community 4 - "pipeline_runner.py"
Cohesion: 0.06
Nodes (56): main(), adaptive_threshold(), Config, denoise(), deskew(), ExtractionPipeline, _load_page_images_cv(), preprocess() (+48 more)

### Community 5 - "ExtractionPipeline"
Cohesion: 0.21
Nodes (23): _create_job_dir(), _create_task(), detect_item_type(), extract_zip(), is_image(), is_pdf(), _log_task_exception(), ocr_extract() (+15 more)

### Community 6 - "ChandraOcrClient"
Cohesion: 0.10
Nodes (23): TokenUsage, ChandraOcrClient, _clean_value(), _extract_inline_value(), _extract_table_from_html(), _get_checkbox_suffixes(), _is_all_options_line(), _is_option_items_line() (+15 more)

### Community 7 - "package.json"
Cohesion: 0.07
Nodes (28): dependencies, react, react-dom, react-markdown, remark-gfm, devDependencies, @types/react, @types/react-dom (+20 more)

### Community 8 - "datalab_schema.py"
Cohesion: 0.10
Nodes (24): _classify_mark(), convert_extract_response(), _merge_free_text(), _merge_mark_and_fallback(), JSON schema + response mapper for Datalab /api/v1/extract.  Checkbox Mark Resolu, Strip checkbox symbols; return (clean_text, had_tick, had_cross)., Classify a mark description string into 'positive', 'negative', or 'empty'., Resolve multi-option checkbox fields from per-option mark descriptions.      For (+16 more)

### Community 9 - "compilerOptions"
Cohesion: 0.09
Nodes (22): compilerOptions, allowImportingTsExtensions, isolatedModules, jsx, lib, module, moduleDetection, moduleResolution (+14 more)

### Community 10 - "ExtractedDataPanel.tsx"
Cohesion: 0.14
Nodes (12): CHECKBOX_VALS, checkboxDisplay(), CheckboxIcon(), CheckboxItem(), confidenceColor(), confidenceLabel(), ExtractedDataPanel(), FieldValue() (+4 more)

### Community 11 - "checkbox_vision.py"
Cohesion: 0.19
Nodes (18): _classify_checkbox_mark(), _crop_checkbox(), _detect_both_marked(), _normalize_mark(), _points_to_pixels(), ndarray, CV-based checkbox mark verification using stroke-run counting.  At runtime, give, Normalize Datalab mark values to our standard terms: tick, cross, slash, empty. (+10 more)

### Community 12 - "react-dom_client.js"
Cohesion: 0.10
Nodes (4): ErrorBoundary, Props, State, "node_modules/react/cjs/react.development.js"()

### Community 13 - "tesseract.py"
Cohesion: 0.17
Nodes (16): get_backend(), _get_bbox_cache_key(), _get_tesseract_semaphore(), _load_bbox_cache(), OCRBackend, OCRResult, ABC, ndarray (+8 more)

### Community 14 - "client.ts"
Cohesion: 0.21
Nodes (8): deleteJob(), subscribeNewJobs(), View, DashboardPage(), JobEntry, Props, STATUS_COLORS, statusBadge()

### Community 15 - "types.ts"
Cohesion: 0.14
Nodes (14): getResult(), getStatus(), saveToDB(), StatusResponse, subscribeToBatch(), subscribeToJob(), FolderReviewPage(), Props (+6 more)

### Community 16 - "compilerOptions"
Cohesion: 0.11
Nodes (18): compilerOptions, allowImportingTsExtensions, isolatedModules, lib, module, moduleDetection, moduleResolution, noEmit (+10 more)

### Community 17 - "Field"
Cohesion: 0.20
Nodes (11): Props, Props, SectionGroup, Props, Props, Props, getPageText(), Props (+3 more)

### Community 18 - "DocumentReview.tsx"
Cohesion: 0.19
Nodes (12): getTesseractData(), pageImageUrl(), DocumentReview(), EditableTextViewer(), getPageText(), groupWordsByLine(), Props, TesseractView() (+4 more)

### Community 19 - "FieldCard.tsx"
Cohesion: 0.23
Nodes (10): ConfidenceBar(), confidenceColor(), Props, CHECKBOX_VALUES, confidencePill(), FieldCard(), isCheckbox(), Props (+2 more)

### Community 20 - "FieldList.tsx"
Cohesion: 0.42
Nodes (8): confidenceColor(), confidenceLabel(), effectiveSection(), fieldCompare(), FieldList(), fieldSortKey(), inferSection(), KNOWN_SECTIONS

### Community 21 - "PipelineProcessingView.tsx"
Cohesion: 0.29
Nodes (6): confidenceColor(), FieldSummary, PipelineProcessingView(), Props, STAGE_MAPPING, STAGES

### Community 22 - "StatusHeader.tsx"
Cohesion: 0.50
Nodes (4): confidenceColor(), Props, StatusHeader(), TokenDisplay

### Community 23 - "dependencies"
Cohesion: 0.50
Nodes (3): fitz, dependencies, fitz

### Community 24 - "test_batch.py"
Cohesion: 0.67
Nodes (3): generate_sample_pdf(), main(), Stress-test the /upload-batch endpoint with multiple PDFs.  Usage:     uv run py

### Community 35 - "AGENTS.md"
Cohesion: 0.07
Nodes (28): API change rules, Avoid, Batch modes, Canonical commands, Change strategy, Current pipeline, Database rules, Frontend change rules (+20 more)

### Community 36 - "model_client.py"
Cohesion: 0.18
Nodes (10): Exception, call_with_retry(), call_with_retry_async(), _call_with_retry_async_inner(), GeminiClient, _is_transient(), _load_dotenv(), RateLimiter (+2 more)

### Community 37 - "database.py"
Cohesion: 0.17
Nodes (16): Pool, create_job(), get_incomplete_jobs(), get_last_job_id_by_pdf_id(), get_pool(), get_result_by_file_hash(), get_result_by_job_id(), get_stuck_jobs() (+8 more)

### Community 38 - "run_batch_pdfs_pipeline_async"
Cohesion: 0.14
Nodes (16): load_page_images(), Path, Render each page of a PDF as a grayscale numpy array.      Returns dict mapping, _extract_structured_fields(), Any, Upsert a row into ocr_documents keyed on job_id.     Structured field columns ar, Update job status and optional metadata., Map the fields array from result_json into structured DB columns. (+8 more)

### Community 39 - "process_pending_on_startup"
Cohesion: 0.16
Nodes (14): FastAPI, close_pool(), init_pool(), Create the connection pool. Call once at server startup., Close the connection pool. Call once at server shutdown., lifespan(), Validate critical environment variables at startup.     Logs warnings for missin, _safe_startup_poller() (+6 more)

### Community 40 - "OpenAICompatibleClient"
Cohesion: 0.36
Nodes (3): _encode_image(), _extract_usage(), OpenAICompatibleClient

## Knowledge Gaps
- **104 isolated node(s):** `type`, `name`, `private`, `version`, `type` (+99 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TokenUsage` connect `ChandraOcrClient` to `model_client.py`, `DocumentReview.tsx`, `RolmOcrClient`?**
  _High betweenness centrality (0.216) - this node is a cross-community bridge._
- **Why does `convert_extract_response()` connect `datalab_schema.py` to `server.py`, `model_client.py`, `pipeline_runner.py`, `run_batch_pdfs_pipeline_async`?**
  _High betweenness centrality (0.120) - this node is a cross-community bridge._
- **Why does `DatalabOcrClient` connect `model_client.py` to `OpenAICompatibleClient`, `server.py`, `pipeline_runner.py`, `model_client.py`?**
  _High betweenness centrality (0.093) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `ExtractionPipeline` (e.g. with `ModelClient` and `WordBox`) actually correct?**
  _`ExtractionPipeline` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `PageClassifier` (e.g. with `BeautifulColorFormatter` and `test_docstring_inference()`) actually correct?**
  _`PageClassifier` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `ModelClient` (e.g. with `ChandraOcrClient` and `DatalabOcrClient`) actually correct?**
  _`ModelClient` has 9 INFERRED edges - model-reasoned connections that need verification._
- **What connects `type`, `name`, `private` to the rest of the system?**
  _104 weakly-connected nodes found - possible documentation gaps or missing edges._