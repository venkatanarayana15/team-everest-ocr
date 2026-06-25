# OCR Extraction Pipeline — Session 3 Plan

## GPU Acceleration (PaddleOCR + Torch)

### WSL2 NVIDIA GPU Setup
- **Problem**: `nvidia-smi` failed with "GPU access blocked by the operating system"; `cuInit(0)` returned error 100
- **Fix**: Windows host had RTX 3050 with driver 592.27 — needed `wsl --update && wsl --shutdown` to enable GPU-P forwarding
- **Verify**: `nvidia-smi` in WSL2 now shows RTX 3050 6GB, CUDA 13.1

### PaddlePaddle GPU
- **Package**: `paddlepaddle-gpu==3.3.1` from `https://www.paddlepaddle.org.cn/packages/stable/cu126/`
- **Config**: `pyproject.toml` changed `paddlepaddle` → `paddlepaddle-gpu==3.3.1`, added `[[tool.uv.index]]` for paddle-cu126 with `index-strategy = "unsafe-best-match"`
- **NCCL fix**: `nvidia-nccl-cu12==2.25.1` lacked `ncclCommResume` symbol needed by torch 2.12.1. Reinstalled `nvidia-nccl-cu13==2.29.7` which overwrites the same `nvidia/nccl/lib/libnccl.so.2` path
- **Config flag**: `src/config.py`: `paddle_use_gpu: bool = True`
- **Verify**: `paddle.is_compiled_with_cuda()` = True, `device_count()` = 1, `PaddleOCR(use_gpu=True)` succeeds

### NCCL Conflict Resolution
- Both `nvidia-nccl-cu12` and `nvidia-nccl-cu13` install to `nvidia/nccl/lib/libnccl.so.2`
- Torch 2.12.1 calls `ncclCommResume` (NCCL ≥2.29)
- `nvidia-nccl-cu12==2.25.1` doesn't have it → import error
- Fix: reinstall `nvidia-nccl-cu13==2.29.7` (has the symbol, overwrites the same file path)

## Transcription UI — Scroll-Based Image Navigation

### Motivation
- Page flip buttons in transcription view were cumbersome
- User wanted to scroll through all page images freely while editing text

### Changes
- **`TranscriptionPane.tsx`**: Removed `currentPage`, `onFieldClick`, `fields` props. Single textarea shows all pages' combined raw_text with page markers visible. User edits the full document in one view.
- **`ReviewPage.tsx`** (transcription view): Right pane now renders all page images stacked vertically in a scrollable `overflow: auto` container — each image shows "Page N" label. Left pane is the full-text TranscriptionPane. SplitPane keeps them side-by-side.

## Output Format Regeneration

### Problem
- After secondary model corrected field values, `raw_text` still had old primary model values
- All output formats (md/txt/html) are generated from `raw_text`, so corrections weren't reflected

### Fix — `_rebuild_outputs()` (server.py)
- Consolidated 3 duplicate output-writing blocks into one shared function
- Writes `result.json` (from data dict), `result.md` (raw_text), `result.txt` (strip markdown), `result.html` (markdown→HTML)
- Called from: `_run_pipeline`, `/save_transcription`, `/correct`

### Fix — `raw_text` rebuild after verification
- After `verify_secondary()` completes, `raw_text` is rebuilt from final corrected fields
- Each field → `**{label}:** {value}` grouped by page with `--- Page N ---` markers
- Includes corrected values, new secondary fields, and needs_clarification notes

## DeepSeek 413 Request Entity Too Large

### Problem
- DeepSeek API rejected requests with HTTP 413 when sending 6 pages of 4500×6000px base64 PNGs
- DeepSeek doesn't support the `detail` parameter (OpenAI-specific), so `detail: "high"` was silently ignored but images were still full resolution

### Fix — Image Resizing
- Added `_resize_encode_image()` in `model_client.py`
- Resizes images to max 1200px on the longest side (LANCZOS) before base64 encoding
- 4500×6000 → ~1200×1600 = ~14× fewer pixels, payload fits DeepSeek's limit
- Removed `"detail": "high"` from DeepSeek's `_build_vision_content` (parameter not supported)

## Prompt Caching (Gemini)

### Motivation
- If same model is used for both primary and secondary, the PDF upload can be reused
- Saves ~2-3s re-upload time per call

### Implementation
- `_gemini_upload_cache: dict[str, object]` — module-level cache in `model_client.py`
- Keyed by `(model_name, pdf_path)`
- `GeminiClient._cached_upload(pdf_path)` — returns cached upload or uploads + caches
- `verify_secondary()` now accepts optional `pdf_path` parameter and forwards it to `secondary_client.extract_structured(pdf_path, ...)`
- Both call sites (`server.py` line 216, `extraction_pipeline.py` line 497) pass `pdf_path`
- **Active only when both primary and secondary use Gemini**
- **Verified**: Test with Gemini primary + Gemini secondary showed `Reusing cached upload for gemini-2.5-flash:...` in server log

## Provider Change

### Primary: DeepSeek → Gemini
- DeepSeek API doesn't support vision (rejected `image_url` content type)
- Gemini 2.5 Flash accepts PDFs natively, has best document vision
- `.env`: uncommented Gemini primary config, commented out DeepSeek

### Current `.env` config
```
PRIMARY_PROVIDER=gemini
PRIMARY_MODEL=gemini-2.5-flash
PRIMARY_API_KEY=AIzaSyBw12f-vGS274wACgksXFms0Lov7X6Mr2M

SECONDARY_PROVIDER=openai
SECONDARY_MODEL=gpt-5
SECONDARY_API_KEY=sk-proj-...
```

## Current Server Architecture
- **Start**: `uv run uvicorn src.server:app --port 8000` (no `--reload` — kills background threads)
- **Must use `setsid`** to detach: `setsid uv run uvicorn src.server:app --port 8000 > /tmp/server.log 2>&1 &`
- **CWD**: `ocr-extract/` (so `output/` resolves correctly)
- **GPU**: RTX 3050 6GB active for both PaddleOCR and torch
- **Outputs**: `output/<job_id_ts>/results/result.{json,md,txt,html}`
- **Page images**: `output/<job_id_ts>/pages/page_{N}.png` (preprocessed) and `page_{N}_original.png`

---

# Session 4 — Frontend Priority Field Cards (2026-06-24)

## FieldCard Redesign

### Problem
- Low-confidence fields had a yellow border, hard to spot
- Corrected/verified fields looked the same as untouched ones
- No visual urgency for items needing manual correction

### Changes
- **Priority system**: Every field gets a `Priority` type: `'high'` | `'corrected'` | `'verified'`
  - `high`: confidence < 80 OR `needs_clarification` OR has `reason` → needs human attention
  - `corrected`: `original_value` exists AND confidence ≥ 80 → already fixed by user
  - `verified`: everything else → high confidence, auto-verified

### Visual Design
| Priority | Border | Background | Tag |
|----------|--------|------------|-----|
| **high** | Red (`#fca5a5` / `#dc2626`) | Light red (`#fef2f2`) | "Needs correction" red pill |
| **corrected** | Green (`#86efac`/`#16a34a`) | Light green (`#f0fdf4`) | "✓ Corrected" green pill |
| **verified** | Default gray (`#e2e8f0`) | White (`#fff`) | "✓ Verified" green pill |

- Label (question) at top with priority tag + page number
- Thin divider below label
- Value (answer) below divider in bold with Edit button
- Strikethrough `original_value` shown when corrected
- `ConfidenceBar` remains visible for all fields
- Only shows reason / verification note if not auto-accepted

### FieldList Changes
- **Sort**: High-priority fields first → corrected → verified (all on one page)
- **Summary line**: `● N needs correction ● N corrected` at top of list
- **Local state update**: After Save, the field immediately gets `confidence=100`, `original_value` set, `needs_clarification=false` → instantly turns green without server refresh

### Files Changed
- `frontend/src/components/FieldCard.tsx` — full rewrite of styling, priority logic
- `frontend/src/components/FieldList.tsx` — sorting, summary counts, corrected callback updated

---

# Session 5 — Integration Testing & Verification (2026-06-24)

## Issues Found & Fixed

### DeepSeek Does Not Support Vision
- **Error**: `unknown variant 'image_url', expected 'text'` — DeepSeek API rejects `image_url` content type entirely
- **Impact**: DeepSeek cannot function as primary (needs to see document) or secondary (needs to verify against images)
- **Fix**: Ensure DeepSeek is only used as a text-only fallback option, commented out in `.env`
- **DeepSeek still works for**: text-only tasks via OpenAI-compatible `base_url="https://api.deepseek.com/v1"`

### Server Process Management
- **Problem**: `pkill -f "uvicorn"` timed out without killing; `nohup ... &` processes died when Bash tool timed out
- **Root cause**: Bash tool kills the shell session on timeout, which sends SIGHUP to background child processes
- **Fix**: Use `setsid` to detach the server process from the shell session
  ```bash
  setsid uv run uvicorn src.server:app --port 8000 > /tmp/server.log 2>&1 &
  ```

### Stale Server Config
- **Problem**: Server was running with old `.env` (DeepSeek primary), `_load_dotenv()` uses `os.environ.setdefault()` so config changes don't take effect without restart
- **Impact**: Pipeline failed with DeepSeek errors even after `.env` was updated
- **Fix**: Kill old server and start fresh with `setsid`

## Verification Results

### Run 1: Gemini primary + OpenAI secondary
| Detail | Value |
|--------|-------|
| Preprocessing | 6 pages, ~80s |
| Tesseract bboxes | 184 words, ~20s |
| Gemini extraction | 110 fields at 90% confidence, ~102s |
| OpenAI verification | 110 verified, 5 corrected, 0 new, ~167s |
| Total | ~6 min |

### Run 2: Gemini primary + OpenAI secondary (reproducibility check)
| Detail | Value |
|--------|-------|
| Gemini extraction | 107 fields at 92% confidence |
| OpenAI verification | 107 verified, 13 corrected |
| Total | ~5 min |

### Run 3: Gemini primary + Gemini secondary (prompt caching test)
| Detail | Value |
|--------|-------|
| Gemini extraction | 106 fields at 85% confidence |
| **Prompt cache** | **Reused cached upload for gemini-2.5-flash:...** ✅ |
| Gemini verification | 106 verified, 9 corrected |
| Total | ~5.5 min |

### `/save_transcription` test
- Sent modified `raw_text` via `POST /save_transcription/{job_id}`
- All 4 output files (result.json, result.md, result.txt, result.html) regenerated with new content
- Markdown stripped correctly in `.txt` format

### Prompt Caching — Verified
- Server log confirms:
  1. `Uploading PDF to Gemini` (primary) → `Cached upload: files/seg98ku3xhc3`
  2. `Reusing cached upload for gemini-2.5-flash:` (secondary, ~2 min later)
- Cache key: `(model_name, pdf_path)` → `gemini-2.5-flash:/path/to/input.pdf`
- Cache scope: module-level dict in `model_client.py`, persists across pipeline stages within same process

## Frontend — Verified
- `tsc --noEmit` passes cleanly
- Frontend dev server running on `localhost:5173`
- `TranscriptionPane.tsx`: scrollable single textarea with Save button, no per-page switching
- `ReviewPage.tsx` transcription view: right pane renders all page images stacked vertically with Page N labels
- Both frontend and backend servers running

## Current `.env` (final, working)
```
PRIMARY_PROVIDER=gemini
PRIMARY_MODEL=gemini-2.5-flash
PRIMARY_API_KEY=AIzaSyBw12f-...

SECONDARY_PROVIDER=openai
SECONDARY_MODEL=gpt-5
SECONDARY_API_KEY=sk-proj-...

# DeepSeek (text-only, no vision support — not for extraction/verification)
# SECONDARY_PROVIDER=deepseek
# SECONDARY_MODEL=deepseek-v4-flash
```

## Key Decisions
- **DeepSeek is text-only**: It does NOT support `image_url` content type. Cannot be used for extraction (needs to see document) or verification (needs to compare against page images). Keep it as a documented text-only alternative.
- **`setsid` required**: To prevent server from dying when shell session ends
- **OpenAI as secondary**: Only production-viable secondary (Gemini works but costs 2x; DeepSeek can't verify against images)
