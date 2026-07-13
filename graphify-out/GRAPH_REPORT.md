# Graph Report - new-ocr  (2026-07-13)

## Corpus Check
- 69 files · ~1,500,809 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 744 nodes · 1502 edges · 42 communities (37 shown, 5 thin omitted)
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
- load_page_images
- OpenAICompatibleClient
- RolmOcrClient

## God Nodes (most connected - your core abstractions)
1. `ExtractionPipeline` - 33 edges
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
- `main()` --calls--> `run_pipeline()`  [EXTRACTED]
  scratch/run_test.py → src/pipeline_runner.py
- `test_resolve_checkbox_marks()` --calls--> `resolve_checkbox_marks()`  [EXTRACTED]
  tests/test_backend.py → src/datalab_schema.py
- `test_resolve_single_checkbox_marks()` --calls--> `_resolve_single_checkbox_marks()`  [EXTRACTED]
  tests/test_backend.py → src/datalab_schema.py
- `test_validate_field_patterns()` --calls--> `_validate_field_patterns()`  [EXTRACTED]
  tests/test_backend.py → src/datalab_schema.py
- `TextLine` --uses--> `PageClassification`  [INFERRED]
  tests/test_backend.py → src/page_classifier.py

## Import Cycles
- None detected.

## Communities (42 total, 5 thin omitted)

### Community 0 - "server.py"
Cohesion: 0.50
Nodes (4): Wake up a waiting collect() worker when the webhook fires., signal_webhook(), Webhook endpoint called by Datalab when extraction completes.      Datalab webho, webhook_extraction_completed()

### Community 1 - "model_client.py"
Cohesion: 0.05
Nodes (35): Exception, TokenUsage, ChandraOcrClient, OCR client for the Chandra-2 API.      Single API call like Datalab:     1. Send, DatalabOcrClient, Datalab OCR client — sends PDF to Datalab /api/v1/extract for structured field e, Full submit + poll (backward compatible)., Submit PDF to Datalab and return a DatalabJob immediately (no polling). (+27 more)

### Community 2 - "zoho_integration.py"
Cohesion: 0.07
Nodes (52): BaseModel, HTTPResponse, Request, build_synthetic_result(), main(), print_summary(), Build a synthetic OCR result with all field categories and print _build_creator_, init_pool() (+44 more)

### Community 3 - "test_backend.py"
Cohesion: 0.08
Nodes (46): PageClassification, PageClassifier, Page classifier — determines page number (1-6) from image content.  Uses Tessera, Classify a page from an image file., Classify all images and return a mapping of image_index -> classification., Resolve page ordering from classifications.          Returns:           - mappin, Classifies page images into page numbers 1-6 based on OCR content., Classify a single page from its OCR text content. (+38 more)

### Community 4 - "pipeline_runner.py"
Cohesion: 0.10
Nodes (19): FastAPI, Response, _auto_cleanup_loop(), _extract_epoch_from_job_id(), _find_original_pdf(), get_page_image(), get_result(), get_status() (+11 more)

### Community 5 - "ExtractionPipeline"
Cohesion: 0.06
Nodes (38): adaptive_threshold(), Config, denoise(), deskew(), ExtractionPipeline, _load_page_images_cv(), preprocess(), ndarray (+30 more)

### Community 6 - "ChandraOcrClient"
Cohesion: 0.06
Nodes (44): _clean_value(), _extract_inline_value(), _extract_table_from_html(), _get_checkbox_suffixes(), _is_all_options_line(), _is_option_items_line(), _is_placeholder(), _matches_suffix() (+36 more)

### Community 7 - "package.json"
Cohesion: 0.07
Nodes (28): dependencies, react, react-dom, react-markdown, remark-gfm, devDependencies, @types/react, @types/react-dom (+20 more)

### Community 8 - "datalab_schema.py"
Cohesion: 0.22
Nodes (20): main(), _ensure_page_images(), _normalize_label(), pad_line(), _print_field_report(), Path, run_image_pipeline(), run_image_pipeline_from_zip() (+12 more)

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
Cohesion: 0.19
Nodes (22): _create_job_dir(), _create_task(), detect_item_type(), extract_zip(), is_image(), is_pdf(), process_folder(), Path (+14 more)

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
Cohesion: 0.29
Nodes (8): getTesseractData(), groupWordsByLine(), Props, TesseractView(), JobInfo, JobStatus, TesseractData, TesseractWord

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
Cohesion: 0.24
Nodes (12): create_job(), Upsert a row into ocr_documents keyed on job_id.     Structured field columns ar, Insert a new job with status='submitted'., upsert_ocr_document(), Async submit+collect batch pipeline with overlapped per-file workers.      Desig, run_batch_pdfs_pipeline(), run_batch_pdfs_pipeline_async(), ocr_extract() (+4 more)

### Community 37 - "database.py"
Cohesion: 0.10
Nodes (25): Pool, close_pool(), _extract_structured_fields(), get_last_job_id_by_pdf_id(), get_pool(), get_result_by_file_hash(), get_result_by_job_id(), get_stuck_jobs() (+17 more)

### Community 38 - "run_batch_pdfs_pipeline_async"
Cohesion: 0.26
Nodes (11): download_result(), _format_job_datetime(), get_job_progress(), _is_checked(), _is_option(), _push_new_job(), _push_sse(), _render_markdown() (+3 more)

### Community 39 - "load_page_images"
Cohesion: 0.22
Nodes (9): load_page_images(), Path, Render each page of a PDF as a grayscale numpy array.      Returns dict mapping, get_incomplete_jobs(), Update job status and optional metadata., Return all jobs not in 'completed' or 'failed' state (for startup reconciliation, update_job_status(), Reconcile incompleting jobs on server startup.      For jobs in 'collecting' sta (+1 more)

### Community 40 - "OpenAICompatibleClient"
Cohesion: 0.47
Nodes (4): pageImageUrl(), DocumentReview(), EditableTextViewer(), getPageText()

### Community 41 - "RolmOcrClient"
Cohesion: 0.50
Nodes (3): dependencies, @kilocode/plugin, @kilocode/plugin

## Knowledge Gaps
- **105 isolated node(s):** `@kilocode/plugin`, `type`, `name`, `private`, `version` (+100 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TokenUsage` connect `model_client.py` to `DocumentReview.tsx`?**
  _High betweenness centrality (0.212) - this node is a cross-community bridge._
- **Why does `convert_extract_response()` connect `ChandraOcrClient` to `model_client.py`, `model_client.py`, `pipeline_runner.py`, `load_page_images`, `datalab_schema.py`?**
  _High betweenness centrality (0.118) - this node is a cross-community bridge._
- **Why does `DatalabOcrClient` connect `model_client.py` to `pipeline_runner.py`, `ExtractionPipeline`?**
  _High betweenness centrality (0.091) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `ExtractionPipeline` (e.g. with `ModelClient` and `WordBox`) actually correct?**
  _`ExtractionPipeline` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `PageClassifier` (e.g. with `BeautifulColorFormatter` and `test_docstring_inference()`) actually correct?**
  _`PageClassifier` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `ModelClient` (e.g. with `ChandraOcrClient` and `DatalabOcrClient`) actually correct?**
  _`ModelClient` has 9 INFERRED edges - model-reasoned connections that need verification._
- **What connects `@kilocode/plugin`, `type`, `name` to the rest of the system?**
  _105 weakly-connected nodes found - possible documentation gaps or missing edges._