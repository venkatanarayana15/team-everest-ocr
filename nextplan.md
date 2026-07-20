# Next Plan: OCR Extraction Pipeline — Field Mapping Fixes & Architecture Improvements

> **Generated**: 2025-07-19  
> **Role**: Senior Software Engineer / Project Lead  
> **Status**: Ready for implementation

---

## 📋 EXECUTIVE SUMMARY

This project is a **production-grade OCR extraction pipeline** for a 6-page "Home Visit Questionnaire" form. The system processes scanned PDFs through:
- Preprocessing (deskew, denoise)
- Primary LLM extraction (Gemini/OpenAI, per-page or combined)
- Secondary verification (gap-filling)
- Template fill + hierarchy enrichment
- Supabase persistence + Zoho Creator CRM sync
- React review UI with PDF bbox highlighting

---

## 📋 EXECUTIVE SUMMARY

This project is a **production-grade OCR extraction pipeline** for a 6-page "Home Visit Questionnaire" form. The system processes scanned PDFs through:
- Preprocessing (deskew, denoise)
- Primary LLM extraction (Gemini/OpenAI, per-page or combined)
- Secondary verification (gap-filling)
- Template fill + hierarchy enrichment
- Supabase persistence + Zoho Creator CRM sync
- React review UI with PDF bbox highlighting

---

## 🚨 CRITICAL ISSUES (P0 — Fix Immediately)

### 1. Label Format Drift — Root Cause of Field Mapping Failures
| Location | Current Format | Problem |
|----------|----------------|---------|
| `prompt_templates.py:PAGE_FIELD_MAPPINGS` | `4.3.1 - Row 1 - Property Description` (hyphen) | LLM outputs this format |
| `extraction_pipeline.py:KNOWN_TEMPLATE_FIELDS` | `4.3.1 If Yes, list their properties: — Row 1 — Property Description` (em-dash + prefix) | Template expects this |
| `enrich_fields()` regex | Matches `— Row N —` | Misses hyphen format |

**Impact**: LLM outputs don't match template keys → `fill_missing_template_fields()` fails → manual review required for every form.

### 2. Frontend Heuristic Grouping — Fragile & Unmaintainable
- `ExtractedDataPanel.tsx:1047-1100` uses 150+ lines of regex to reconstruct hierarchy from flat labels
- Breaks on any label format change
- **Solution**: Backend must provide hierarchy explicitly in `StructuredField`

### 3. No Schema Validation
- LLM output parsed with `json.loads()` — no Pydantic/Zod validation
- Malformed responses cause silent failures

---

## ✅ P0 ACTION PLAN (This Week)

| # | Task | Files | Effort |
|---|------|-------|--------|
| 1 | **Unify label format** — Standardize on `parent - Row N - column` (hyphens) everywhere | `prompt_templates.py`, `extraction_pipeline.py` | 1 day |
| 2 | **Add hierarchy to LLM contract** — Extend `StructuredField` with `parent_label`, `field_type`, `group_id`, `row_index`, `column_name`; add to prompt schema; validate with Pydantic | `extraction_pipeline.py`, new `schemas.py` | 2 days |
| 3 | **Frontend consumes hierarchy** — Update `ExtractedDataPanel` to use `field_type`, `parent_label`, `group_id` directly; remove regex grouping | `ExtractedDataPanel.tsx`, `types.ts` | 2 days |
| 4 | **Add validation** — Zod on frontend, Pydantic on backend for all `Field` objects | `types.ts`, `schemas.py` | 1 day |

---

## 🔧 P1 HIGH-VALUE IMPROVEMENTS (Next 2 Weeks)

| # | Task | Files | Effort |
|---|------|-------|--------|
| 5 | **Single source of truth for field hierarchy** — Define form schema as JSON/TypeScript (sections → questions → options/columns); generate `KNOWN_TEMPLATE_FIELDS`, `PAGE_FIELD_MAPPINGS`, Zod/Pydantic schemas, Zoho mappings from it | New `form_schema.ts`, codegen script | 3 days |
| 6 | **Click-to-inspect on PDF** — Add hit-testing in `DocumentReview` (R-tree/quadtree over bboxes) | `DocumentReview.tsx` | 2 days |
| 7 | **Unified confidence colors** — Single `confidenceColor(c: number): string` utility shared across all components | New `utils/confidence.ts`, update 7 components | 0.5 days |
| 8 | **DB schema normalization** — Move sparse columns to `result_json` JSONB; keep only high-value columns indexed | `database.py`, migration | 2 days |
| 9 | **Zoho mapping from schema** — Generate `FIELD_TO_COLUMN` from single source of truth | `database.py`, codegen | 1 day |

---

## 🛠️ P2 OPERATIONAL EXCELLENCE (Month 1)

| # | Task | Effort |
|---|------|--------|
| 10 | OpenTelemetry tracing (pipeline stages, LLM calls, DB) | 2 days |
| 11 | Playwright E2E tests for critical paths (upload → review → correct → save) | 3 days |
| 12 | Dockerfile + docker-compose for production | 1 day |
| 13 | Webhook retry with exponential backoff + dead-letter queue | 1 day |
| 14 | Database migration tool (Alembic) | 1 day |

---

## 🏗️ ARCHITECTURAL DECISION NEEDED

**Hierarchy metadata in LLM output: Option A (explicit) vs Option B (computed)**

| Option | Approach | Tokens | Correctness |
|--------|----------|--------|-------------|
| **A (Recommended)** | Add `parent_label`, `field_type`, `group_id`, `row_index`, `column_name` to prompt as required fields | +200-500 tokens/page | **Explicit, validated, future-proof** |
| B | Compute in `enrich_fields()` from labels | Fewer tokens | Fragile, duplicates logic |

**Decision**: **Option A** — Token cost is negligible vs. correctness gain. Current `enrich_fields()` is already fragile.

---

## 📁 FILES TO MODIFY (Priority Order)

### Backend (Python)
```
src/extraction_pipeline.py      # StructuredField, enrich_fields, label format
src/prompt_templates.py         # PAGE_FIELD_MAPPINGS label format
src/schemas.py                  # NEW: Pydantic models for StructuredField + hierarchy
src/database.py                 # Zoho mappings, DB schema
src/model_client.py             # Add response validation
```

### Frontend (TypeScript/React)
```
frontend/src/types.ts           # Field interface + hierarchy fields
frontend/src/components/ExtractedDataPanel.tsx  # Remove regex grouping, use hierarchy
frontend/src/components/DocumentReview.tsx       # Add click-to-inspect hit-testing
frontend/src/utils/confidence.ts # NEW: unified confidence colors
frontend/src/components/QuestionGroup.tsx        # NEW: radio/checkbox group component
frontend/src/components/QuestionTable.tsx        # NEW: collapsible table component
```

### New Files
```
form_schema.ts                  # Single source of truth for form hierarchy
scripts/generate_schema.py      # Codegen from form_schema
tests/e2e/                      # Playwright tests
Dockerfile / docker-compose.yml # Production deployment
.github/workflows/ci.yml        # CI pipeline
```

---

## 🧪 VALIDATION CHECKLIST (Before Merge)

- [ ] TypeScript compiles: `npx tsc --noEmit`
- [ ] Python syntax: `python3 -c "import ast; ast.parse(open('src/extraction_pipeline.py').read())"`
- [ ] Label format consistency: grep for `—` vs `-` in prompt/template
- [ ] Hierarchy fields present in LLM response (manual test)
- [ ] Frontend renders groups/tables without regex
- [ ] Click PDF → selects field works
- [ ] Confidence colors consistent across components

---

## 📊 RISK MITIGATION

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Label format drift breaks template fill | **High** | High | P0 #1-4 |
| Frontend heuristic misses new field types | **High** | Medium | P0 #3 |
| LLM output format change breaks parsing | Medium | High | P0 #4 (Pydantic) |
| Zoho API changes break writeback | Low | High | P1 #9 |

---

## 📅 TIMELINE

| Week | Focus |
|------|-------|
| **Week 1** | P0 #1-4: Label format, hierarchy contract, frontend integration, validation |
| **Week 2** | P1 #5-9: Schema single-source, click-to-inspect, unified colors, DB/Zoho |
| **Week 3** | P2 #10-14: Observability, E2E tests, Docker, webhook retry, migrations |

---

## 🎯 SUCCESS METRICS

| Metric | Target |
|--------|--------|
| Template fill success rate | > 99% (currently ~70%) |
| Manual review time per form | < 2 min (currently ~10 min) |
| Field mapping accuracy | > 98% |
| Zero heuristic regex in frontend | ✅ |
| Single source of truth for schema | ✅ |

---

*Plan approved for implementation. Start with P0 #1 (label format unification).*