import json
import logging
import os
import sys
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import psutil

import asyncio

from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from src.config import Config
from src.extraction_pipeline import ExtractionPipeline, StructuredField
from src.pipeline import run_batch
from src.input_handler import (
    detect_input_type, detect_item_type, extract_zip,
    scan_folder, is_image, is_pdf, IMAGE_EXTENSIONS,
)
from src.page_classifier import PageClassifier

try:
    from src.database import (
        insert_pdf,
        list_pdfs as db_list_pdfs,
        insert_extraction_result,
        insert_extracted_fields,
        update_extraction_result,
        get_result_by_job_id,
        get_last_job_id_by_pdf_id,
        get_pool,
        close_pool,
        upsert_ocr_document,
    )
    DB_AVAILABLE = True
except ImportError as e:
    DB_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("Database module not available (%s). Dedup + DB features disabled.", e)

# Ensure logs are visible in terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

app = FastAPI(title="OCR Extraction Pipeline")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
        "http://localhost:5175", "http://127.0.0.1:5175"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Use absolute path so it works regardless of where uvicorn is started
_script_dir = Path(__file__).resolve().parent.parent
BASE_DIR = _script_dir / "output"
BASE_DIR.mkdir(exist_ok=True)
logger.info("Output dir: %s", BASE_DIR)

# ── Concurrency & memory limiter ───────────────────────────────────
# Prevents WSL OOM kills by limiting how many jobs run in parallel,
# and by refusing new jobs when free memory drops too low.
MAX_CONCURRENT_JOBS = int(os.environ.get("MAX_CONCURRENT_JOBS", "3"))
MIN_FREE_MEM_MB = int(os.environ.get("MIN_FREE_MEM_MB", "512"))
_JOB_TIMEOUT = 3600  # 1 hour max wait for memory
_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS, thread_name_prefix="ocr")


def _wait_for_memory(job_dir: Path) -> bool:
    """Block until free memory is above threshold. Returns False on timeout."""
    start = time.time()
    while time.time() - start < _JOB_TIMEOUT:
        free = psutil.virtual_memory().available / (1024 * 1024)
        if free >= MIN_FREE_MEM_MB:
            return True
        logger.warning("Low memory: %.0f MB free (need %d MB). Delaying job...", free, MIN_FREE_MEM_MB)
        time.sleep(5)
    _set_status(job_dir, "error",
        f"Timed out waiting for memory (>{_JOB_TIMEOUT}s, "
        f"free={free:.0f} MB < {MIN_FREE_MEM_MB} MB). Try again later.")
    return False


# ── Progress store (for SSE streaming) ────────────────────────────────

STAGE_PROGRESS: dict[str, int] = {
    "queued": 0,
    "preprocessing": 15,
    "primary_extraction": 40,
    "field_mapping": 55,
    "secondary_verification": 75,
    "template_fill": 90,
    "done": 100,
    "error": 100,
}

_progress_store: dict[str, dict] = {}
_progress_lock = threading.Lock()


def update_progress(job_id: str, data: dict) -> None:
    with _progress_lock:
        _progress_store[job_id] = data


def get_job_progress(job_id: str) -> dict:
    with _progress_lock:
        return _progress_store.get(job_id, {})


# ── Auto-cleanup old jobs ─────────────────────────────────────────
CLEANUP_INTERVAL_SEC = int(os.environ.get("CLEANUP_INTERVAL_SEC", "600"))   # 10 min
JOB_MAX_AGE_SEC = int(os.environ.get("JOB_MAX_AGE_SEC", str(7 * 86400)))     # 7 days
_cleanup_stop = threading.Event()


def _auto_cleanup_loop() -> None:
    """Background thread: delete old completed/failed job dirs periodically."""
    while not _cleanup_stop.is_set():
        _cleanup_stop.wait(CLEANUP_INTERVAL_SEC)
        if _cleanup_stop.is_set():
            break
        now = time.time()
        purged = 0
        for entry in list(BASE_DIR.iterdir()):
            if not entry.is_dir():
                continue
            status_path = entry / "status.json"
            if not status_path.exists():
                continue
            try:
                with open(status_path) as f:
                    data = json.load(f)
                s = data.get("status", "")
                if s not in ("done", "error"):
                    continue
                mtime = status_path.stat().st_mtime
                if now - mtime > JOB_MAX_AGE_SEC:
                    import shutil
                    shutil.rmtree(entry, ignore_errors=True)
                    purged += 1
            except Exception:
                pass
        if purged:
            logger.info("Auto-cleanup: removed %d old job dirs", purged)


def _start_cleanup_thread() -> None:
    t = threading.Thread(target=_auto_cleanup_loop, daemon=True)
    t.start()


def _stop_cleanup_thread() -> None:
    _cleanup_stop.set()


def _cleanup_intermediate(job_dir: Path) -> None:
    """Remove intermediate files (checkpoints, tesseract data).
    Does NOT delete pages/ — those are needed by the frontend for bbox rendering."""
    cp = job_dir / "checkpoint.json"
    if cp.exists():
        cp.unlink(missing_ok=True)
    ts = job_dir / "tesseract_data.json"
    if ts.exists():
        ts.unlink(missing_ok=True)


@app.on_event("startup")
async def startup():
    global DB_AVAILABLE
    if DB_AVAILABLE:
        try:
            await get_pool()
            logger.info("Database pool initialized")
        except Exception as e:
            logger.warning("Failed to init DB pool: %s — disabling DB features", e)
            DB_AVAILABLE = False
    _start_cleanup_thread()
    logger.info("Auto-cleanup thread started (every %ds, max age %ds)", CLEANUP_INTERVAL_SEC, JOB_MAX_AGE_SEC)


@app.on_event("shutdown")
async def shutdown():
    _stop_cleanup_thread()
    if DB_AVAILABLE:
        await close_pool()


def _set_status(job_dir: Path, status: str, message: str = "", pages: int = 0) -> None:
    path = job_dir / "status.json"
    existing = {"log": []}
    if path.exists():
        with open(path) as f:
            existing = json.load(f)

    log = existing.get("log", [])
    if message:
        from datetime import datetime
        log.append({"t": datetime.now().strftime("%H:%M:%S"), "msg": message})

    data = {
        "status": status,
        "message": message or existing.get("message", ""),
        "log": log,
        "pages": pages or existing.get("pages", 0),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    # Also emit progress for SSE consumers
    pct = STAGE_PROGRESS.get(status, 0)
    name_path = job_dir / "original_name.txt"
    pdf_name = name_path.read_text().strip() if name_path.exists() else job_dir.name

    with _progress_lock:
        existing_progress = _progress_store.get(job_dir.name, {})
        start_time = existing_progress.get("start_time")
        if not start_time:
            start_time = time.time()
        elapsed = round(time.time() - start_time, 1)

        pdfs_map = existing_progress.get("pdfs", {})
        pdfs_map[pdf_name] = {
            "progress": pct,
            "stage": status,
            "elapsed": elapsed,
        }

        _progress_store[job_dir.name] = {
            "overall": pct,
            "pdfs": pdfs_map,
            "start_time": start_time,
            "elapsed": elapsed,
        }


_last_good_status: dict[str, dict] = {}


def _save_to_db(
    job_id: str,
    file_name: str,
    result_dict: dict,
    status: str = "done",
) -> None:
    """Run upsert_ocr_document from a sync worker thread.

    asyncpg pools are bound to the event loop they were created on.  The
    pipeline threads run outside FastAPI's main loop, so we must ensure the
    call runs on a *fresh* event loop with its own pool.  We reset the module-
    level pool reference before each call; get_pool() recreates it on the
    current loop automatically.
    """
    if not DB_AVAILABLE:
        logger.warning("_save_to_db: DB not available — skipping (job=%s)", job_id)
        return

    logger.info("_save_to_db: called — job=%s file=%r status=%s", job_id, file_name, status)

    import src.database as _db_mod  # reset cached pool so asyncpg recreates it

    async def _run():
        _db_mod._pool = None  # force fresh pool for this loop
        try:
            doc_id = await upsert_ocr_document(
                job_id=job_id,
                file_name=file_name,
                status=status,
                processing_time=result_dict.get("processing_time"),
                confidence_score=result_dict.get("overall_confidence"),
                num_pdfs=result_dict.get("num_pdfs"),
                result_json=result_dict,
            )
            if doc_id:
                logger.info("_save_to_db: row saved — job=%s doc_id=%s", job_id, doc_id)
            else:
                logger.warning("_save_to_db: upsert returned no id — job=%s", job_id)
        finally:
            # Close this thread's pool so connections aren't leaked
            if _db_mod._pool:
                try:
                    await _db_mod._pool.close()
                except Exception:
                    pass
                _db_mod._pool = None

    try:
        asyncio.run(_run())
    except Exception as exc:
        import traceback as _tb
        logger.error("_save_to_db FAILED for job=%s: %s\n%s", job_id, exc, _tb.format_exc())


def _get_status(job_dir: Path) -> dict:
    path = job_dir / "status.json"
    if not path.exists():
        return {"status": "unknown", "message": "", "log": [], "pages": 0}
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _last_good_status.get(job_dir.name, {
            "status": "unknown", "message": "", "log": [], "pages": 0,
        })
    _last_good_status[job_dir.name] = data
    name_path = job_dir / "original_name.txt"
    if name_path.exists():
        data["original_name"] = name_path.read_text().strip()
    return data


def _save_checkpoint(job_dir: Path, step: str, fields: list[StructuredField], overall_confidence: float, raw_text: str = "", sections: list[dict] | None = None) -> None:
    path = job_dir / "checkpoint.json"
    data = {
        "step": step,
        "overall_confidence": overall_confidence,
        "raw_text": raw_text,
        "fields": [
            {
                "label": f.label,
                "value": f.value,
                "confidence": f.confidence,
                "page": f.page,
                "section_number": f.section_number,
                "bbox": list(f.bbox) if f.bbox else None,
                "value_bbox": list(f.value_bbox) if f.value_bbox else None,
                "needs_clarification": f.needs_clarification,
                "reason": f.reason,
                "extracted_by": f.extracted_by,
                "verified_by": f.verified_by,
                "original_value": f.original_value,
            }
            for f in fields
        ],
    }
    if sections is not None:
        data["sections"] = sections
    with open(path, "w") as fp:
        json.dump(data, fp, indent=2)


def _load_checkpoint(job_dir: Path) -> tuple[str, list[StructuredField], float, str, list[dict] | None] | None:
    path = job_dir / "checkpoint.json"
    if not path.exists():
        return None
    with open(path) as fp:
        cp = json.load(fp)
    fields = [StructuredField(**f) for f in cp["fields"]]
    return cp["step"], fields, cp["overall_confidence"], cp.get("raw_text", ""), cp.get("sections")


def _validate_pdf(path: str) -> tuple[bool, str]:
    """Validate that a file is a readable PDF by attempting to open it with fitz."""
    p = Path(path)
    if not p.exists():
        return False, f"File not found: {path}"
    if p.stat().st_size == 0:
        return False, f"Empty file: {path}"
    try:
        import fitz
        doc = fitz.open(path)
        num_pages = len(doc)
        doc.close()
        if num_pages == 0:
            return False, f"PDF has no pages: {path}"
    except Exception as e:
        return False, f"Invalid/corrupted PDF: {e}"
    return True, ""


def _emit_progress(job_dir: Path, status: str, pdf_name: str = "") -> None:
    """Push progress update to the in-memory store (consumed by SSE stream)."""
    pct = STAGE_PROGRESS.get(status, 0)
    data: dict = {
        "overall": pct,
        "pdfs": {
            pdf_name or job_dir.name: {
                "progress": pct,
                "stage": status,
            }
        },
    }
    update_progress(job_dir.name, data)


def _run_pipeline(job_dir: Path, pdf_path: str) -> None:
    if not _wait_for_memory(job_dir):
        return
    try:
        import traceback
        from src.model_client import get_model_client

        t0 = time.time()
        name_path = job_dir / "original_name.txt"
        pdf_name = name_path.read_text().strip() if name_path.exists() else Path(pdf_path).name

        # ── Validate PDF before starting ──────────────────────────
        valid, err_msg = _validate_pdf(pdf_path)
        if not valid:
            _set_status(job_dir, "error", err_msg)
            logger.error("[%s] %s", job_dir.name, err_msg)
            return

        config = Config(output_dir=str(job_dir / "output"))
        primary = get_model_client("primary")
        secondary = get_model_client("secondary")
        primary_name = type(primary).__name__.replace("Client", "")
        secondary_name = type(secondary).__name__.replace("Client", "")
        pipeline = ExtractionPipeline(config, primary_client=primary, secondary_client=secondary)

        # ── Check for checkpoint (resume support) ──────────────────
        fields: list[StructuredField] = []
        overall_confidence = 0.0
        num_pages_pages: list[int] = []
        raw_text = ""
        sections_data: list[dict] | None = None
        model_data: dict | None = None
        checkpoint = _load_checkpoint(job_dir)

        if checkpoint:
            step, fields, overall_confidence, raw_text, sections_data = checkpoint
            logger.info("[%s] Resuming from checkpoint (step=%s, %d fields)", job_dir.name, step, len(fields))

        if not fields:
            # ── Step 1: Preprocess ─────────────────────────────────
            _set_status(job_dir, "preprocessing", "Rendering and enhancing pages...")
            pages = pipeline.preprocess(str(pdf_path), str(job_dir))
            num_pages_pages = list(pages.keys())
            _set_status(job_dir, "preprocessing", f"Preprocessing done. {len(pages)} pages ready.", pages=len(pages))

            pages_dir = job_dir / "pages"
            page_images = {
                int(p.stem.split("_")[1]): str(p)
                for p in sorted(pages_dir.glob("page_*.png")) if "_original" not in p.stem
            } if pages_dir.exists() else {}

            # ── Step 2+3a: Parallel Tesseract + Primary LLM ─────────
            _set_status(job_dir, "primary_extraction",
                "Running Tesseract (CPU) and primary extraction (LLM) in parallel...")
            bbox_cache = job_dir / "bbox_cache.pkl"
            from concurrent.futures import ThreadPoolExecutor as _TempPool
            with _TempPool(max_workers=2) as _pool:
                _bbox_fut = _pool.submit(pipeline.run_bbox, pdf_path)
                _primary_fut = _pool.submit(
                    pipeline.run_primary_extraction, str(pdf_path), page_images
                )
                word_boxes = _bbox_fut.result()
                model_data, primary_token_usage = _primary_fut.result()

            # Cache bboxes so Step 4 doesn't re-run Tesseract
            import pickle
            with open(bbox_cache, "wb") as f:
                pickle.dump(word_boxes, f)

            _set_status(job_dir, "primary_extraction",
                f"Tesseract detected {len(word_boxes)} words across {len(num_pages_pages)} pages.",
                pages=len(num_pages_pages),
            )
            _save_tesseract_data(job_dir, word_boxes)

            if model_data:
                overall_confidence = model_data.get("overall_confidence", 0)
                raw_text = model_data.get("raw_text", "")
                raw_text = _insert_page_markers(raw_text, model_data.get("fields", []))
                num_model = len(model_data.get("fields", []))
                _set_status(job_dir, "extracting",
                    f"{primary_name} extracted {num_model} fields (confidence: {overall_confidence}%). "
                    f"Merging with bounding boxes...",
                )

                # ── Step 3b: Merge ─────────────────────────────────
                fields = pipeline.merge_fields(model_data, word_boxes, prefix=primary_name)
                _set_status(job_dir, "field_mapping",
                    f"Merged {len(fields)} fields with Tesseract bboxes.",
                )
            else:
                _set_status(job_dir, "field_mapping",
                    f"{primary_name} extraction failed — falling back to Tesseract words.",
                )
                overall_confidence = 0
                fields = [
                    StructuredField(
                        label=wb.text,
                        value=wb.text,
                        confidence=int(wb.confidence),
                        page=wb.page_num,
                        bbox=wb.bbox,
                        extracted_by=primary_name,
                    )
                    for wb in word_boxes
                ]

            model_sections = (model_data or {}).get("sections")
            derived_sections = _derive_sections(fields, raw_text) if fields else []
            if model_sections:
                existing_nums = {s["number"] for s in model_sections}
                for ds in derived_sections:
                    if ds["number"] not in existing_nums:
                        model_sections.append(ds)
                model_sections.sort(key=lambda s: s["number"])
            else:
                model_sections = derived_sections
            sections_data = model_sections
            _save_checkpoint(job_dir, "mapped", fields, overall_confidence, raw_text, sections=model_sections)
        else:
            # Resuming — reload page count and raw_text from pages
            pages_dir = job_dir / "pages"
            num_pages_pages = sorted(
                int(p.stem.split("_")[1])
                for p in pages_dir.glob("page_*.png") if "_original" not in p.stem
            ) if pages_dir.exists() else []
            raw_text = ""
            result_path = job_dir / "results" / "result.json"
            if result_path.exists():
                with open(result_path) as f:
                    prev = json.load(f)
                raw_text = prev.get("raw_text", "")

        # ── Step 4a: Fill missing template fields (before secondary) ──
        _set_status(job_dir, "template_fill",
            "Filling missing template fields before verification...")
        fields = ExtractionPipeline.fill_missing_template_fields(fields)

        # ── Step 4b: Load cached bboxes for secondary ────────────────
        bbox_cache = job_dir / "bbox_cache.pkl"
        if bbox_cache.exists():
            import pickle
            with open(bbox_cache, "rb") as f:
                word_boxes = pickle.load(f)
        else:
            word_boxes = pipeline.run_bbox(pdf_path)

        # Determine whether secondary is needed
        skip_secondary = (
            overall_confidence >= 95
            and model_data
            and not model_data.get("clarification_needed")
        )

        if skip_secondary:
            logger.info("[%s] High confidence (≥95%%), skipping secondary verification.", job_dir.name)
            _set_status(job_dir, "secondary_verification",
                f"{primary_name} confidence {overall_confidence}% ≥ 95% — skipping verification.",
            )
            secondary_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            for f in fields:
                f.is_verified = True
                f.verified_by = primary_name
        else:
            # ── Step 5: Secondary verification ──────────────────────────
            _set_status(job_dir, "secondary_verification", f"Running secondary verification ({secondary_name})...")
            logger.info("[%s] Secondary verification with %s...", job_dir.name, secondary_name)
            fields, secondary_token_usage = pipeline.verify_secondary(fields, word_boxes, str(job_dir), prefix=secondary_name)
            verified = sum(1 for f in fields if f.is_verified)
            corrected = sum(1 for f in fields if f.original_value is not None)
            new_from_secondary = sum(1 for f in fields if f.verified_by == secondary_name and f.extracted_by is None)
            _set_status(job_dir, "secondary_verification",
                f"{secondary_name} verified {verified} fields, corrected {corrected}, added {new_from_secondary} new.",
            )

        # Accumulate token usage
        token_usage = {
            "primary": primary_token_usage,
            "secondary": secondary_token_usage,
            "total": {
                "prompt_tokens": (primary_token_usage.get("prompt_tokens", 0) or 0) + (secondary_token_usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": (primary_token_usage.get("completion_tokens", 0) or 0) + (secondary_token_usage.get("completion_tokens", 0) or 0),
                "total_tokens": (primary_token_usage.get("total_tokens", 0) or 0) + (secondary_token_usage.get("total_tokens", 0) or 0),
            },
        }
        logger.info("Token usage: primary=%s secondary=%s total=%s",
                     primary_token_usage, secondary_token_usage, token_usage["total"])

        # Re-derive sections (template_fill already ran)
        sections_data = _derive_sections(fields, raw_text or "")

        # ── Save results ───────────────────────────────────────────
        elapsed = time.time() - t0
        _set_status(job_dir, "secondary_verification", "Saving results...")

        results_dir = job_dir / "results"
        results_dir.mkdir(exist_ok=True)

        result_dict = {
            "overall_confidence": overall_confidence,
            "num_pages": len(num_pages_pages),
            "processing_time": round(elapsed, 2),
            "raw_text": raw_text or "",
            "primary_model": primary_name,
            "secondary_model": secondary_name,
            "token_usage": token_usage,
            "sections": sections_data or [],
            "pdf_names": [pdf_name],
            "fields": [
                {
                    "label": f.label,
                    "value": f.value,
                    "confidence": f.confidence,
                    "page": f.page,
                    "section_number": f.section_number,
                    "bbox": list(f.bbox) if f.bbox else None,
                    "value_bbox": list(f.value_bbox) if f.value_bbox else None,
                    "needs_clarification": f.needs_clarification,
                    "reason": f.reason,
                    "is_verified": f.is_verified,
                    "verifier_confidence": f.verifier_confidence,
                    "verification_note": f.verification_note,
                    "extracted_by": f.extracted_by,
                    "verified_by": f.verified_by,
                    "original_value": f.original_value,
                    "file": getattr(f, "file", None) or pdf_name,
                }
                for f in fields
            ],
        }

        with open(results_dir / "result.json", "w") as f:
            json.dump(result_dict, f, indent=2)

        # Write raw_text as result.md
        md_content = raw_text
        if not md_content:
            md_lines = [
                "# OCR Extraction Results",
                "",
                f"- **Job ID:** {job_dir.name}",
                f"- **Date Created:** {_format_job_datetime(job_dir.name)}",
                f"- **Overall Confidence:** {result_dict['overall_confidence']}%",
                f"- **Processing Time:** {result_dict['processing_time']}s",
                f"- **Number of Pages:** {result_dict['num_pages']}",
                "",
            ]
            pages_out: dict[int, list[dict]] = {}
            for f in result_dict["fields"]:
                pages_out.setdefault(f["page"], []).append(f)
            for page_num in sorted(pages_out):
                md_lines.append(f"## Page {page_num}")
                md_lines.append("")
                for f in pages_out[page_num]:
                    md_lines.append(f"- **{f['label']}:** {f['value'] or '(empty)'}")
                md_lines.append("")
            md_content = "\n".join(md_lines)

        with open(results_dir / "result.md", "w") as f:
            f.write(md_content)

        # Plain-text version (strip markdown)
        import re
        txt = md_content
        txt = re.sub(r'#{1,6}\s+', '', txt)
        txt = re.sub(r'\*\*(.+?)\*\*', r'\1', txt)
        txt = re.sub(r'\*(.+?)\*', r'\1', txt)
        txt = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', txt)
        txt = re.sub(r'\|.*?\|', '', txt)
        txt = re.sub(r'[-]{2,}', '', txt)
        txt = re.sub(r'\n{3,}', '\n\n', txt)
        with open(results_dir / "result.txt", "w") as f:
            f.write(txt.strip())

        # HTML version (render Markdown → HTML)
        try:
            import markdown
            html_body = markdown.markdown(md_content, extensions=['tables', 'fenced_code'])
        except ImportError:
            html_body = f"<pre>{md_content}</pre>"
        html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>OCR Extraction — {job_dir.name}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 800px; margin: 2em auto; padding: 0 1em; line-height: 1.6; color: #1e293b; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #cbd5e1; padding: 6px 10px; text-align: left; }}
  th {{ background: #f8fafc; font-weight: 600; }}
  pre {{ background: #f1f5f9; padding: 1em; border-radius: 6px; overflow-x: auto; }}
  code {{ background: #f1f5f9; padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""
        with open(results_dir / "result.html", "w") as f:
            f.write(html_page)
        # Clean up checkpoint on success
        cp = job_dir / "checkpoint.json"
        if cp.exists():
            cp.unlink()

        token_log_msg = f"Extraction complete. Token Consumption -> Primary ({primary_name}): Prompt={primary_token_usage.get('prompt_tokens', 0)}, Completion={primary_token_usage.get('completion_tokens', 0)}"
        if secondary_token_usage:
            token_log_msg += f" | Secondary ({secondary_name}): Prompt={secondary_token_usage.get('prompt_tokens', 0)}, Completion={secondary_token_usage.get('completion_tokens', 0)}"
        token_log_msg += f" | Total={token_usage['total'].get('total_tokens', 0)}"
        _set_status(job_dir, "done", token_log_msg)

        # ── Persist to Supabase ────────────────────────────────────────
        _save_to_db(
            job_id=job_dir.name,
            file_name=pdf_name,
            result_dict=result_dict,
        )

    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Pipeline failed: %s\n%s", e, tb)
        _set_status(job_dir, "error", f"{type(e).__name__}: {e}")
        _save_to_db(
            job_id=job_dir.name,
            file_name=job_dir.name,
            result_dict={},
            status="failed",
        )
    finally:
        _cleanup_intermediate(job_dir)


def _set_batch_pdf_status(job_dir: Path, pdf_name: str, status: str, pct: int, message: str = "") -> None:
    path = job_dir / "status.json"
    existing = {}
    if path.exists():
        try:
            with open(path) as f:
                existing = json.load(f)
        except Exception:
            pass

    log = existing.get("log", [])
    if message:
        from datetime import datetime
        log.append({"t": datetime.now().strftime("%H:%M:%S"), "msg": f"[{pdf_name}] {message}"})

    data = {
        "status": "processing",
        "message": f"Processing {pdf_name}: {message}" if message else existing.get("message", ""),
        "log": log,
        "pages": existing.get("pages", 0),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    with _progress_lock:
        existing_progress = _progress_store.get(job_dir.name, {})
        start_time = existing_progress.get("start_time")
        if not start_time:
            start_time = time.time()
        elapsed = round(time.time() - start_time, 1)

        pdfs_map = existing_progress.get("pdfs", {})
        pdfs_map[pdf_name] = {
            "progress": pct,
            "stage": status,
            "elapsed": elapsed,
        }

        total_pct = sum(item["progress"] for item in pdfs_map.values())
        overall_pct = round(total_pct / len(pdfs_map)) if pdfs_map else 0

        _progress_store[job_dir.name] = {
            "overall": overall_pct,
            "pdfs": pdfs_map,
            "start_time": start_time,
            "elapsed": elapsed,
        }


def _run_batch_pdfs_pipeline(job_dir: Path, pdfs_info: list[dict]) -> None:
    t0 = time.time()
    try:
        # pyrefly: ignore [missing-import]
        from src.model_client import get_model_client
        config = Config(output_dir=str(job_dir / "output"))
        primary = get_model_client("primary")
        secondary = get_model_client("secondary")
        primary_name = type(primary).__name__.replace("Client", "").lower()
        secondary_name = type(secondary).__name__.replace("Client", "").lower()

        # pyrefly: ignore [missing-import]
        from src.extraction_pipeline import ExtractionPipeline
        pipeline = ExtractionPipeline(config, primary_client=primary, secondary_client=secondary)

        all_fields = []
        all_raw_text = []
        total_pages = 0
        confidences = []

        total_primary_prompt = 0
        total_primary_completion = 0
        total_secondary_prompt = 0
        total_secondary_completion = 0

        # Initialize progress for all PDFs
        for item in pdfs_info:
            _set_batch_pdf_status(job_dir, item["filename"], "queued", 0, "Queued in batch")

        pdf_times = {}

        for idx, item in enumerate(pdfs_info):
            filename = item["filename"]
            pdf_path = Path(item["path"])
            pdf_t0 = time.time()
            
            _set_batch_pdf_status(job_dir, filename, "preprocessing", 10, "Rendering pages...")
            
            sub_dir = job_dir / f"pdf_{idx}"
            sub_dir.mkdir(exist_ok=True)
            
            pages = pipeline.preprocess(str(pdf_path), str(sub_dir))
            page_images = {
                int(p.stem.split("_")[1]): str(p)
                for p in sorted((sub_dir / "pages").glob("page_*.png")) if "_original" not in p.stem
            } if (sub_dir / "pages").exists() else {}
            
            _set_batch_pdf_status(job_dir, filename, "primary_extraction", 30, "Extracting fields with primary AI...")
            
            word_boxes = pipeline.run_bbox(str(pdf_path))
            model_data, primary_token_usage = pipeline.run_primary_extraction(str(pdf_path), page_images)
            
            total_primary_prompt += primary_token_usage.get("prompt_tokens", 0) or 0
            total_primary_completion += primary_token_usage.get("completion_tokens", 0) or 0

            _set_batch_pdf_status(job_dir, filename, "field_mapping", 60, "Mapping fields to bounding boxes...")
            
            fields = []
            pdf_raw_text = ""
            if model_data:
                pdf_raw_text = model_data.get("raw_text", "")
                pdf_raw_text = _insert_page_markers(pdf_raw_text, model_data.get("fields", []))
                fields = pipeline.merge_fields(model_data, word_boxes, prefix=primary_name)
            else:
                fields = [
                    StructuredField(label=wb.text, value=wb.text, confidence=int(wb.confidence), page=wb.page_num, bbox=wb.bbox, extracted_by=primary_name)
                    for wb in word_boxes
                ]
                
            fields = ExtractionPipeline.fill_missing_template_fields(fields)
            
            overall_confidence = model_data.get("overall_confidence", 0) if model_data else 0
            secondary_token_usage = {}
            if overall_confidence < 95:
                _set_batch_pdf_status(job_dir, filename, "secondary_verification", 80, "Running secondary verification...")
                fields, secondary_token_usage = pipeline.verify_secondary(fields, word_boxes, str(sub_dir), prefix=secondary_name)
                total_secondary_prompt += secondary_token_usage.get("prompt_tokens", 0) or 0
                total_secondary_completion += secondary_token_usage.get("completion_tokens", 0) or 0
                
            pdf_times[filename] = round(time.time() - pdf_t0, 1)
            _set_batch_pdf_status(job_dir, filename, "done", 100, "Done")

            # Save each PDF as its own DB row
            pdf_result = {
                "overall_confidence": overall_confidence,
                "num_pages": len(pages),
                "num_pdfs": 1,
                "processing_time": pdf_times[filename],
                "raw_text": pdf_raw_text,
                "primary_model": primary_name,
                "secondary_model": secondary_name,
                "sections": [],
                "pdf_names": [filename],
                "fields": [
                    {
                        "label": f.label,
                        "value": f.value,
                        "confidence": f.confidence,
                        "page": f.page,
                        "section_number": f.section_number,
                        "bbox": list(f.bbox) if f.bbox else None,
                        "value_bbox": list(f.value_bbox) if f.value_bbox else None,
                        "needs_clarification": f.needs_clarification,
                        "reason": f.reason,
                        "is_verified": f.is_verified,
                        "extracted_by": f.extracted_by,
                        "verified_by": f.verified_by,
                        "original_value": f.original_value,
                        "file": filename,
                    }
                    for f in fields
                ],
            }
            _save_to_db(
                job_id=f"{job_dir.name}_{filename}",
                file_name=filename,
                result_dict=pdf_result,
            )

        elapsed = time.time() - t0
        overall_conf = round(sum(confidences) / len(confidences)) if confidences else 0
        
        results_dir = job_dir / "results"
        results_dir.mkdir(exist_ok=True)
        
        path = job_dir / "status.json"
        existing = {}
        if path.exists():
            with open(path) as f:
                existing = json.load(f)
        existing["status"] = "done"
        
        token_log_msg = f"Batch complete. Total Tokens -> Primary ({primary_name}): Prompt={total_primary_prompt}, Completion={total_primary_completion}"
        if total_secondary_prompt > 0 or total_secondary_completion > 0:
            token_log_msg += f" | Secondary ({secondary_name}): Prompt={total_secondary_prompt}, Completion={total_secondary_completion}"
        token_log_msg += f" | Grand Total={total_primary_prompt + total_primary_completion + total_secondary_prompt + total_secondary_completion}"
        existing["message"] = token_log_msg
        with open(path, "w") as f:
            json.dump(existing, f, indent=2)

    except Exception as e:
        logger.exception("Batch pipeline failed")
        _set_status(job_dir, "error", f"Pipeline failed: {str(e)}")


def _run_image_pipeline(job_dir: Path, image_paths: dict[int, str]) -> None:
    """Pipeline for image-based inputs (Mode B/C). image_paths maps page_num -> file path."""
    try:
        import traceback
        import time
        # pyrefly: ignore [missing-import]
        from src.model_client import get_model_client

        t0 = time.time()
        config = Config(output_dir=str(job_dir / "output"))
        primary = get_model_client("primary")
        secondary = get_model_client("secondary")
        primary_name = type(primary).__name__.replace("Client", "")
        secondary_name = type(secondary).__name__.replace("Client", "")
        pipeline = ExtractionPipeline(config, primary_client=primary, secondary_client=secondary)

        _set_status(job_dir, "preprocessing", "Preprocessing page images...")
        pages = pipeline.preprocess_images(image_paths, str(job_dir))
        num_pages_pages = sorted(pages.keys())
        _set_status(job_dir, "preprocessing", f"Preprocessing done. {len(pages)} pages ready.", pages=len(pages))

        _set_status(job_dir, "primary_extraction", "Running Tesseract for bounding box detection...")
        pages_dir = job_dir / "pages"
        processed_images = {
            int(p.stem.split("_")[1]): str(p)
            for p in sorted(pages_dir.glob("page_*.png")) if "_original" not in p.stem
        } if pages_dir.exists() else {}
        word_boxes = pipeline.run_bbox_images(processed_images)
        _save_tesseract_data(job_dir, word_boxes)

        _set_status(job_dir, "primary_extraction", f"Running primary extraction ({primary_name})...")
        model_data, primary_token_usage = pipeline.run_primary_extraction("", processed_images)

        fields: list[StructuredField] = []
        overall_confidence = 0.0
        raw_text = ""

        if model_data:
            overall_confidence = model_data.get("overall_confidence", 0)
            raw_text = model_data.get("raw_text", "")
            raw_text = _insert_page_markers(raw_text, model_data.get("fields", []))
            fields = pipeline.merge_fields(model_data, word_boxes, prefix=primary_name)
            _set_status(job_dir, "field_mapping",
                f"Merged {len(fields)} fields with Tesseract bboxes.",
            )
        else:
            _set_status(job_dir, "field_mapping", "Primary extraction failed — using Tesseract words.")
            overall_confidence = 0
            fields = [
                StructuredField(
                    label=wb.text, value=wb.text,
                    confidence=int(wb.confidence), page=wb.page_num,
                    bbox=wb.bbox, extracted_by=primary_name,
                )
                for wb in word_boxes
            ]

        model_sections = (model_data or {}).get("sections")
        derived_sections = _derive_sections(fields, raw_text) if fields else []
        if model_sections:
            existing_nums = {s["number"] for s in model_sections}
            for ds in derived_sections:
                if ds["number"] not in existing_nums:
                    model_sections.append(ds)
            model_sections.sort(key=lambda s: s["number"])
        else:
            model_sections = derived_sections
        sections_data = model_sections
        _save_checkpoint(job_dir, "mapped", fields, overall_confidence, raw_text, sections=model_sections)

        _set_status(job_dir, "secondary_verification", f"Running secondary verification ({secondary_name})...")
        fields, secondary_token_usage = pipeline.verify_secondary(fields, word_boxes, str(job_dir), prefix=secondary_name)

        token_usage = {
            "primary": primary_token_usage,
            "secondary": secondary_token_usage,
            "total": {
                "prompt_tokens": (primary_token_usage.get("prompt_tokens", 0) or 0) + (secondary_token_usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": (primary_token_usage.get("completion_tokens", 0) or 0) + (secondary_token_usage.get("completion_tokens", 0) or 0),
                "total_tokens": (primary_token_usage.get("total_tokens", 0) or 0) + (secondary_token_usage.get("total_tokens", 0) or 0),
            },
        }
        logger.info("Token usage: primary=%s secondary=%s total=%s",
                     primary_token_usage, secondary_token_usage, token_usage["total"])

        fields = ExtractionPipeline.fill_missing_template_fields(fields)
        sections_data = _derive_sections(fields, raw_text or "")

        elapsed = time.time() - t0
        _set_status(job_dir, "secondary_verification", "Saving results...")

        results_dir = job_dir / "results"
        results_dir.mkdir(exist_ok=True)

        result_dict = {
            "overall_confidence": overall_confidence,
            "num_pages": len(num_pages_pages),
            "processing_time": round(elapsed, 2),
            "raw_text": raw_text or "",
            "primary_model": primary_name,
            "secondary_model": secondary_name,
            "token_usage": token_usage,
            "sections": sections_data or [],
            "fields": [
                {
                    "label": f.label, "value": f.value, "confidence": f.confidence,
                    "page": f.page, "section_number": f.section_number,
                    "bbox": list(f.bbox) if f.bbox else None,
                    "value_bbox": list(f.value_bbox) if f.value_bbox else None,
                    "needs_clarification": f.needs_clarification, "reason": f.reason,
                    "is_verified": f.is_verified, "verifier_confidence": f.verifier_confidence,
                    "verification_note": f.verification_note,
                    "extracted_by": f.extracted_by, "verified_by": f.verified_by,
                    "original_value": f.original_value,
                }
                for f in fields
            ],
            "input_type": "image_set",
        }

        with open(results_dir / "result.json", "w") as f:
            json.dump(result_dict, f, indent=2)

        md_content = _render_markdown(result_dict, job_dir.name)
        with open(results_dir / "result.md", "w") as f:
            f.write(md_content)

        import re
        txt = md_content
        txt = re.sub(r'#{1,6}\s+', '', txt)
        txt = re.sub(r'\*\*(.+?)\*\*', r'\1', txt)
        txt = re.sub(r'\*(.+?)\*', r'\1', txt)
        txt = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', txt)
        txt = re.sub(r'\|.*?\|', '', txt)
        txt = re.sub(r'[-]{2,}', '', txt)
        txt = re.sub(r'\n{3,}', '\n\n', txt)
        with open(results_dir / "result.txt", "w") as f:
            f.write(txt.strip())

        try:
            import markdown
            html_body = markdown.markdown(md_content, extensions=['tables', 'fenced_code'])
        except ImportError:
            html_body = f"<pre>{md_content}</pre>"
        html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>OCR Extraction — {job_dir.name}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 800px; margin: 2em auto; padding: 0 1em; line-height: 1.6; color: #1e293b; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #cbd5e1; padding: 6px 10px; text-align: left; }}
  th {{ background: #f8fafc; font-weight: 600; }}
  pre {{ background: #f1f5f9; padding: 1em; border-radius: 6px; overflow-x: auto; }}
  code {{ background: #f1f5f9; padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""
        with open(results_dir / "result.html", "w") as f:
            f.write(html_page)

        cp = job_dir / "checkpoint.json"
        if cp.exists():
            cp.unlink()

        _set_status(job_dir, "done", "Extraction complete. Results ready for download.")

        # ── Persist image pipeline result to Supabase ─────────────────
        img_name = (
            (job_dir / "original_name.txt").read_text().strip()
            if (job_dir / "original_name.txt").exists()
            else job_dir.name
        )
        _save_to_db(
            job_id=job_dir.name,
            file_name=img_name,
            result_dict=result_dict,
        )

    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Image pipeline failed: %s\n%s", e, tb)
        _set_status(job_dir, "error", f"{type(e).__name__}: {e}")
        _save_to_db(
            job_id=job_dir.name,
            file_name=job_dir.name,
            result_dict={},
            status="failed",
        )


def _save_tesseract_data(job_dir: Path, word_boxes: list) -> None:
    """Save tesseract word boxes grouped by page for frontend mapping."""
    pages_data: dict[int, list[dict]] = {}
    for wb in word_boxes:
        p = wb.page_num
        if p not in pages_data:
            pages_data[p] = []
        pages_data[p].append({
            "text": wb.text,
            "page": p,
            "bbox": list(wb.bbox),
            "confidence": wb.confidence,
        })
    data = {"pages": {str(k): v for k, v in pages_data.items()}}
    path = job_dir / "tesseract_data.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info("Saved tesseract data for %d pages (%d total words)", len(pages_data), len(word_boxes))


@app.get("/ping")
async def ping():
    return {"status": "ok"}


@app.get("/stream/{job_id}")
async def stream_status(job_id: str):
    """SSE endpoint: pushes real-time status + progress updates.
    Replaces the frontend's 3-second polling of /status/{id}."""
    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    async def event_gen():
        last_payload: str | None = None
        try:
            while True:
                status = _get_status(job_dir)
                progress = get_job_progress(job_id)
                payload = {**status, "progress": progress}
                dumped = json.dumps(payload)
                # Only send if something changed
                if dumped != last_payload:
                    last_payload = dumped
                    yield f"data: {dumped}\n\n"
                if status["status"] in ("done", "error", "incomplete"):
                    yield f"data: {json.dumps({**payload, '_final': True})}\n\n"
                    break
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("SSE generator error for %s", job_id)
            try:
                err_payload = json.dumps({"status": "error", "message": "Stream interrupted", "_final": True})
                yield f"data: {err_payload}\n\n"
            except Exception:
                pass

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.get("/stream-batch")
async def stream_batch(job_ids: str):
    """SSE endpoint: streams status updates for multiple jobs simultaneously.
    Accepts comma-separated job_ids. Pushes per-job events and a final _batch_complete event."""
    ids = [jid.strip() for jid in job_ids.split(",") if jid.strip()]
    if not ids:
        raise HTTPException(400, "No job_ids provided")

    job_dirs = {jid: BASE_DIR / jid for jid in ids}
    for jid, jdir in job_dirs.items():
        if not jdir.exists():
            raise HTTPException(404, f"Job not found: {jid}")

    async def event_gen():
        last: dict[str, str] = {}  # jid -> json dump of last status payload
        try:
            while True:
                all_terminal = True
                updates: list[str] = []
                for jid, jdir in job_dirs.items():
                    status = _get_status(jdir)
                    progress = get_job_progress(jid)
                    payload = {"job_id": jid, **status, "progress": progress}
                    dumped = json.dumps(payload)
                    if dumped != last.get(jid):
                        last[jid] = dumped
                        if status["status"] in ("done", "error", "incomplete"):
                            final = {**payload, "_final": True}
                            updates.append(f"data: {json.dumps(final)}\n\n")
                        else:
                            updates.append(f"data: {dumped}\n\n")
                    if status["status"] not in ("done", "error", "incomplete"):
                        all_terminal = False
                if updates:
                    yield "".join(updates)
                if all_terminal:
                    yield f"data: {json.dumps({'_batch_complete': True, 'total': len(ids)})}\n\n"
                    break
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("SSE batch generator error")
            try:
                err_payload = json.dumps({"_batch_complete": True, "total": len(ids), "error": "Stream interrupted"})
                yield f"data: {err_payload}\n\n"
            except Exception:
                pass

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    """Upload a PDF (Mode A) or a single image (will start image pipeline)."""
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    ext = Path(file.filename).suffix.lower()

    if ext == ".pdf":
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(400, "Empty file uploaded")

        file_size = len(content)

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        job_id = f"{str(uuid.uuid4())[:8]}_{ts}"
        job_dir = BASE_DIR / job_id
        job_dir.mkdir(parents=True)

        pdf_path = job_dir / "input.pdf"
        with open(pdf_path, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        # Validate the saved file is a valid PDF
        valid, err = _validate_pdf(str(pdf_path))
        if not valid:
            import shutil
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, f"Corrupted PDF upload: {err}")

        with open(job_dir / "original_name.txt", "w") as f:
            f.write(file.filename)

        pdf_id = None
        if DB_AVAILABLE:
            try:
                pdf_id = await insert_pdf(
                    filename=file.filename,
                    file_size=file_size,
                    file_path=str(pdf_path),
                )
            except Exception as e:
                logger.warning("Failed to insert PDF into DB: %s", e)

        _set_status(job_dir, "queued", "PDF uploaded, starting pipeline...")
        _executor.submit(_run_pipeline, job_dir, str(pdf_path))
        return {"job_id": job_id, "status": "queued", "pdf_id": pdf_id, "input_type": "pdf"}

    if ext in IMAGE_EXTENSIONS:
        content = await file.read()
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        job_id = f"{str(uuid.uuid4())[:8]}_{ts}"
        job_dir = BASE_DIR / job_id
        job_dir.mkdir(parents=True)

        img_dir = job_dir / "input_images"
        img_dir.mkdir(exist_ok=True)
        img_path = img_dir / file.filename
        with open(img_path, "wb") as f:
            f.write(content)

        with open(job_dir / "original_name.txt", "w") as f:
            f.write(file.filename)

        _set_status(job_dir, "queued", "Image uploaded (waiting for full set)...")
        return {
            "job_id": job_id,
            "status": "awaiting_images",
            "input_type": "image_single",
            "message": "Upload 5 more images to complete the set, or use /upload-images for the full set.",
        }

    if ext == ".zip":
        content = await file.read()
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        job_id = f"{str(uuid.uuid4())[:8]}_{ts}"
        job_dir = BASE_DIR / job_id
        job_dir.mkdir(parents=True)

        zip_path = job_dir / "input.zip"
        with open(zip_path, "wb") as f:
            f.write(content)

        with open(job_dir / "original_name.txt", "w") as f:
            f.write(file.filename)

        _set_status(job_dir, "queued", "Extracting ZIP file...")

        extract_dir = job_dir / "input_images"
        extract_dir.mkdir(exist_ok=True)
        image_paths = extract_zip(str(zip_path), str(extract_dir))

        if not image_paths:
            raise HTTPException(400, "No supported images found in ZIP")

        _set_status(job_dir, "queued",
            f"ZIP extracted: {len(image_paths)} images. Classifying pages...")

        _executor.submit(_run_image_pipeline_from_zip, job_dir, image_paths)
        return {
            "job_id": job_id,
            "status": "queued",
            "input_type": "zip",
            "image_count": len(image_paths),
        }

    raise HTTPException(400, f"Unsupported file type: {ext}. Use PDF, images, or ZIP.")


@app.post("/upload-images")
async def upload_images(files: list[UploadFile] = File(...)):
    """Upload multiple images (Mode B). Classifies and orders pages automatically."""
    if not files:
        raise HTTPException(400, "No files provided")

    image_files = [f for f in files if f.filename and Path(f.filename).suffix.lower() in IMAGE_EXTENSIONS]
    if not image_files:
        raise HTTPException(400, "No supported image files found")

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    job_id = f"{str(uuid.uuid4())[:8]}_{ts}"
    job_dir = BASE_DIR / job_id
    job_dir.mkdir(parents=True)

    img_dir = job_dir / "input_images"
    img_dir.mkdir(exist_ok=True)

    saved_paths: list[str] = []
    for f in image_files:
        content = await f.read()
        path = img_dir / f.filename
        with open(path, "wb") as fout:
            fout.write(content)
        saved_paths.append(str(path.resolve()))

    names = "+".join(f.filename for f in image_files[:3])
    if len(image_files) > 3:
        names += f" (+{len(image_files)-3} more)"
    with open(job_dir / "original_name.txt", "w") as f:
        f.write(names)

    _set_status(job_dir, "queued",
        f"{len(image_files)} images uploaded. Classifying pages...")

    _executor.submit(_run_image_pipeline_from_zip, job_dir, saved_paths)

    return {
        "job_id": job_id,
        "status": "queued",
        "input_type": "image_set",
        "image_count": len(image_files),
    }


@app.post("/upload-batch")
async def upload_batch(files: list[UploadFile] = File(...)):
    """Upload a batch of mixed files (PDFs + images). Auto-detects and routes each."""
    if not files:
        raise HTTPException(400, "No files provided")

    pdf_files = [f for f in files if f.filename and Path(f.filename).suffix.lower() == ".pdf"]
    image_files = [f for f in files if f.filename and Path(f.filename).suffix.lower() in IMAGE_EXTENSIONS]
    zip_files = [f for f in files if f.filename and Path(f.filename).suffix.lower() == ".zip"]

    results: list[dict] = []

    if pdf_files:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        job_id = f"batch_{str(uuid.uuid4())[:8]}_{ts}"
        job_dir = BASE_DIR / job_id
        job_dir.mkdir(parents=True)
        
        pdf_dir = job_dir / "pdfs"
        pdf_dir.mkdir(exist_ok=True)
        
        pdfs_info = []
        for f in pdf_files:
            content = await f.read()
            pdf_path = pdf_dir / f.filename
            with open(pdf_path, "wb") as fout:
                fout.write(content)
            pdfs_info.append({"filename": f.filename, "path": str(pdf_path.resolve())})
            
        names = ", ".join(f.filename for f in pdf_files[:3])
        if len(pdf_files) > 3:
            names += f" (+{len(pdf_files)-3} more)"
            
        with open(job_dir / "original_name.txt", "w") as fout:
            fout.write(f"Batch: {names}")
            
        _set_status(job_dir, "queued", f"Processing PDF Batch: {names}")
        _executor.submit(_run_batch_pdfs_pipeline, job_dir, pdfs_info)
        results.append({"job_id": job_id, "filename": f"Batch: {names}", "type": "pdf", "status": "queued"})

    if image_files:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        job_id = f"{str(uuid.uuid4())[:8]}_{ts}"
        job_dir = BASE_DIR / job_id
        job_dir.mkdir(parents=True)
        img_dir = job_dir / "input_images"
        img_dir.mkdir(exist_ok=True)
        saved_paths: list[str] = []
        for f in image_files:
            content = await f.read()
            path = img_dir / f.filename
            with open(path, "wb") as fout:
                fout.write(content)
            saved_paths.append(str(path.resolve()))
        names = "+".join(f.filename for f in image_files[:3])
        if len(image_files) > 3:
            names += f" (+{len(image_files)-3} more)"
        with open(job_dir / "original_name.txt", "w") as fout:
            fout.write(names)
        _set_status(job_dir, "queued",
            f"{len(image_files)} images batch. Classifying pages...")
        _executor.submit(_run_image_pipeline_from_zip, job_dir, saved_paths)
        results.append({"job_id": job_id, "filename": f"images_{len(image_files)}", "type": "image_set", "status": "queued"})

    for f in zip_files:
        content = await f.read()
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        job_id = f"{str(uuid.uuid4())[:8]}_{ts}"
        job_dir = BASE_DIR / job_id
        job_dir.mkdir(parents=True)
        zip_path = job_dir / "input.zip"
        with open(zip_path, "wb") as fout:
            fout.write(content)
        with open(job_dir / "original_name.txt", "w") as fout:
            fout.write(f.filename)
        extract_dir = job_dir / "input_images"
        extract_dir.mkdir(exist_ok=True)
        image_paths = extract_zip(str(zip_path), str(extract_dir))
        _set_status(job_dir, "queued",
            f"ZIP batch: {f.filename} ({len(image_paths)} images)")
        _executor.submit(_run_image_pipeline_from_zip, job_dir, image_paths)
        results.append({"job_id": job_id, "filename": f.filename, "type": "zip", "status": "queued"})

    return {
        "status": "batch_submitted",
        "total": len(results),
        "results": results,
    }


def _validate_images(image_paths: list[str]) -> tuple[bool, str]:
    """Validate that all image paths exist and are non-empty."""
    for p in image_paths:
        path = Path(p)
        if not path.exists():
            return False, f"Image not found: {p}"
        if path.stat().st_size == 0:
            return False, f"Empty image: {p}"
    return True, ""


def _run_image_pipeline_from_zip(job_dir: Path, image_paths: list[str]) -> None:
    """Classify images, reorder, then run image pipeline."""
    if not _wait_for_memory(job_dir):
        return
    try:
        import traceback
        t0 = time.time()

        # Validate images before processing
        valid, err = _validate_images(image_paths)
        if not valid:
            _set_status(job_dir, "error", err)
            logger.error("[%s] %s", job_dir.name, err)
            return

        _set_status(job_dir, "preprocessing",
            f"Classifying {len(image_paths)} pages by content...")

        classifier = PageClassifier()
        classifications = classifier.classify_all(image_paths)
        page_map, validation = classifier.resolve_order(classifications)

        with open(job_dir / "page_validation.json", "w") as f:
            json.dump(validation, f, indent=2)

        is_valid = (
            not validation.get("has_missing", False)
            and not validation.get("has_duplicates", False)
            and not validation.get("has_blank_pages", False)
            and not validation.get("has_unreadable_pages", False)
            and len(page_map) == 6
        )

        if not is_valid:
            logger.warning("Page validation failed for %s: %s", job_dir.name, validation)
            _set_status(job_dir, "incomplete",
                f"Page validation failed. {validation.get('total_images_received', 0)} images, "
                f"missing: {validation.get('missing_pages', [])}, "
                f"duplicates: {validation.get('duplicate_pages', [])}. "
                f"See page_validation.json for details.")
            return

        reordered: dict[int, str] = {}
        for page_num, img_idx in page_map.items():
            reordered[page_num] = image_paths[img_idx]

        _set_status(job_dir, "preprocessing",
            f"Pages classified and reordered. Running pipeline...",
            pages=len(reordered))

        _run_image_pipeline(job_dir, reordered)

    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Image pipeline from zip failed: %s\n%s", e, tb)
        _set_status(job_dir, "error", f"{type(e).__name__}: {e}")
    finally:
        _cleanup_intermediate(job_dir)


@app.get("/validate/{job_id}")
async def get_validation(job_id: str):
    """Get page validation report for a job."""
    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")
    path = job_dir / "page_validation.json"
    if not path.exists():
        return {"status": "not_available", "message": "No validation data. PDF jobs skip validation."}
    with open(path) as f:
        return json.load(f)


@app.post("/process-folder")
async def process_folder(data: dict):
    """Process a folder path on the server. For server-side batch processing (Feature 2/3)."""
    folder_path = data.get("folder_path", "")
    if not folder_path:
        raise HTTPException(400, "folder_path required")

    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(400, f"Folder not found: {folder_path}")

    items = scan_folder(str(folder))
    if not items:
        raise HTTPException(400, "No PDFs or image sets found in folder")

    results: list[dict] = []
    for item in items:
        try:
            if item["type"] == "pdf":
                ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
                job_id = f"{str(uuid.uuid4())[:8]}_{ts}"
                job_dir = BASE_DIR / job_id
                job_dir.mkdir(parents=True)
                pdf_path = job_dir / "input.pdf"
                content = open(item["path"], "rb").read()
                with open(pdf_path, "wb") as f:
                    f.write(content)
                with open(job_dir / "original_name.txt", "w") as f:
                    f.write(item["name"])
                _set_status(job_dir, "queued", f"Folder batch: {item['name']}")
                _executor.submit(_run_pipeline, job_dir, str(pdf_path))
                results.append({"job_id": job_id, "name": item["name"], "type": "pdf", "status": "queued"})

            elif item["type"] == "image_set":
                ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
                job_id = f"{str(uuid.uuid4())[:8]}_{ts}"
                job_dir = BASE_DIR / job_id
                job_dir.mkdir(parents=True)
                with open(job_dir / "original_name.txt", "w") as f:
                    f.write(item["name"])
                # Validate images exist
                valid, err = _validate_images(item["images"])
                if not valid:
                    logger.error("[%s] %s", job_id, err)
                    results.append({"job_id": job_id, "name": item["name"], "type": "image_set", "status": "error", "error": err})
                    continue
                _set_status(job_dir, "queued",
                    f"Image set: {item['name']} ({len(item['images'])} images)")
                _executor.submit(_run_image_pipeline_from_zip, job_dir, item["images"])
                results.append({"job_id": job_id, "name": item["name"], "type": "image_set", "status": "queued"})

        except Exception as e:
            logger.error("Failed to process %s: %s", item.get("name", "?"), e)
            results.append({"name": item.get("name", "?"), "type": item.get("type", "?"), "status": "error", "error": str(e)})

    return {
        "status": "batch_submitted",
        "total": len(results),
        "results": results,
    }


@app.post("/retry/{job_id}")
async def retry_job(job_id: str):
    """Retry a failed pipeline from the last checkpoint (skips completed steps)."""
    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    pdf_path = job_dir / "input.pdf"
    img_dir = job_dir / "input_images"

    _set_status(job_dir, "queued", "Retrying pipeline from last checkpoint...")

    if pdf_path.exists():
        valid, err = _validate_pdf(str(pdf_path))
        if not valid:
            raise HTTPException(400, f"Cannot retry: {err}")
        _executor.submit(_run_pipeline, job_dir, str(pdf_path))
        return {"job_id": job_id, "status": "restarted", "input_type": "pdf"}

    if img_dir.exists():
        image_paths = sorted([
            str(f.resolve()) for f in img_dir.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
        ])
        if image_paths:
            _executor.submit(_run_image_pipeline_from_zip, job_dir, image_paths)
            return {"job_id": job_id, "status": "restarted", "input_type": "image_set"}

    raise HTTPException(400, "No input files found for this job")


@app.get("/status/{job_id}")
async def get_status(job_id: str):
    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")
    return _get_status(job_dir)


@app.get("/result/{job_id}")
async def get_result(job_id: str):
    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    status = _get_status(job_dir)
    if status.get("status") != "done":
        return {"status": status.get("status"), "message": status.get("message", "")}

    result_path = job_dir / "results" / "result.json"
    if not result_path.exists():
        raise HTTPException(500, "Result not found")

    with open(result_path) as f:
        result = json.load(f)

    return {"status": "done", "result": result}


@app.get("/tesseract-data/{job_id}")
async def get_tesseract_data(job_id: str):
    """Return tesseract word boxes grouped by page for frontend mapping."""
    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")
    path = job_dir / "tesseract_data.json"
    if not path.exists():
        raise HTTPException(404, "Tesseract data not available yet")
    with open(path) as f:
        return json.load(f)


@app.get("/pages/{job_id}/{page_num}")
async def get_page_image(job_id: str, page_num: int, width: int = 0, original: int = 0, pdf_name: str = None):
    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    pages_dir = job_dir / "pages"
    if pdf_name:
        result_path = job_dir / "results" / "result.json"
        idx = -1
        if result_path.exists():
            try:
                with open(result_path) as f:
                    r = json.load(f)
                pdf_names = r.get("pdf_names", [])
                if pdf_name in pdf_names:
                    idx = pdf_names.index(pdf_name)
            except Exception:
                pass
        
        if idx == -1:
            for sub in job_dir.iterdir():
                if sub.is_dir() and sub.name.startswith("pdf_"):
                    orig_path = sub / "original_name.txt"
                    if orig_path.exists() and orig_path.read_text().strip() == pdf_name:
                        pages_dir = sub / "pages"
                        break
        else:
            pages_dir = job_dir / f"pdf_{idx}" / "pages"

    if not pages_dir.exists():
        raise HTTPException(404, "Pages directory not found")

    # Try canonical naming first: page_{n}.png
    image_path = pages_dir / (f"page_{page_num}_original.png" if original else f"page_{page_num}.png")
    if image_path.exists():
        pass
    else:
        # Fallback: scan pages dir, sort files, pick the nth PNG
        png_files = sorted(
            p for p in pages_dir.iterdir()
            if p.suffix == ".png" and ("_original" in p.stem) == bool(original) and "_ocr" not in p.stem
        )
        if 0 <= page_num - 1 < len(png_files):
            image_path = png_files[page_num - 1]
        else:
            raise HTTPException(404, f"Page {page_num} not found")

    if width > 0:
        from PIL import Image
        import io
        img = Image.open(str(image_path))
        w, h = img.size
        new_h = int(h * (width / w))
        img = img.resize((width, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return Response(content=buf.read(), media_type="image/png")

    return FileResponse(str(image_path), media_type="image/png")


@app.post("/correct/{job_id}")
async def correct_field(job_id: str, body: dict):
    """Save a human correction for a field. Stores to corrections.json for accuracy tracking."""
    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    label = body.get("label", "")
    correct_value = body.get("correct_value", "")
    if not label:
        raise HTTPException(400, "label is required")

    corrections_path = job_dir / "corrections.json"
    corrections = []
    if corrections_path.exists():
        with open(corrections_path) as f:
            corrections = json.load(f)

    corrections.append({"label": label, "correct_value": correct_value})
    with open(corrections_path, "w") as f:
        json.dump(corrections, f, indent=2)

    # Also update the result.json in-memory to reflect the correction
    result_path = job_dir / "results" / "result.json"
    if result_path.exists():
        with open(result_path) as f:
            result_data = json.load(f)
        for field in result_data.get("fields", []):
            if field["label"] == label:
                if "original_value" not in field or not field["original_value"]:
                    field["original_value"] = field["value"]
                field["value"] = correct_value
                field["confidence"] = 100  # Human override → max confidence
                field["needs_clarification"] = False
                break
        with open(result_path, "w") as f:
            json.dump(result_data, f, indent=2)

    return {"status": "saved"}


@app.post("/update-raw-text/{job_id}")
async def update_raw_text(job_id: str, body: dict):
    """Update the raw transcription text for a job."""
    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    new_raw_text = body.get("raw_text", "")
    
    # Update result.json
    result_path = job_dir / "results" / "result.json"
    if result_path.exists():
        try:
            with open(result_path) as f:
                result_data = json.load(f)
            result_data["raw_text"] = new_raw_text
            with open(result_path, "w") as f:
                json.dump(result_data, f, indent=2)
        except Exception as e:
            logger.error("Failed to update raw_text in result.json: %s", e)

    # Update result.md
    md_path = job_dir / "results" / "result.md"
    try:
        md_path.parent.mkdir(exist_ok=True)
        with open(md_path, "w") as f:
            f.write(new_raw_text)
    except Exception as e:
        logger.error("Failed to update result.md: %s", e)

    return {"status": "saved"}


@app.get("/metrics")
async def get_metrics():
    """Compute per-field accuracy from human corrections across all jobs."""
    all_corrections: list[dict] = []
    for d in BASE_DIR.iterdir():
        if not d.is_dir():
            continue
        corr_path = d / "corrections.json"
        if corr_path.exists():
            with open(corr_path) as f:
                corr = json.load(f)
            result_path = d / "results" / "result.json"
            if result_path.exists():
                with open(result_path) as f:
                    res = json.load(f)
                for c in corr:
                    original = next(
                        (f["value"] for f in res.get("fields", []) if f["label"] == c["label"]),
                        None
                    )
                    c["original_value"] = original
            all_corrections.extend(corr)

    if not all_corrections:
        return {"total_corrections": 0, "message": "No human corrections recorded yet"}

    # Group by label to get per-field accuracy
    from collections import Counter
    field_corrections: dict[str, list[dict]] = {}
    for c in all_corrections:
        field_corrections.setdefault(c["label"], []).append(c)

    per_field = {}
    for label, corrs in sorted(field_corrections.items()):
        total = len(corrs)
        changed = sum(1 for c in corrs if c.get("original_value", c["correct_value"]) != c["correct_value"])
        per_field[label] = {
            "total_corrections": total,
            "times_changed": changed,
            "stability_pct": round((1 - changed / total) * 100),
        }

    return {
        "total_corrections": len(all_corrections),
        "per_field": per_field,
    }


def _extract_epoch_from_job_id(job_id: str) -> float:
    parts = job_id.split("_")
    if len(parts) >= 3:
        try:
            from datetime import datetime
            date_str = parts[-2]
            time_str = parts[-1]
            dt = datetime.strptime(f"{date_str}_{time_str}", "%Y-%m-%d_%H-%M")
            return dt.timestamp()
        except Exception:
            pass
    try:
        job_dir = BASE_DIR / job_id
        if job_dir.exists():
            return job_dir.stat().st_mtime
    except Exception:
        pass
    return 0.0


@app.get("/jobs")
async def list_jobs():
    jobs = []
    for d in BASE_DIR.iterdir():
        if d.is_dir():
            status = _get_status(d)
            result_path = d / "results" / "result.json"
            name_path = d / "original_name.txt"
            filename = name_path.read_text().strip() if name_path.exists() else d.name
            num_pages = None
            num_pdfs = None
            pdf_names = []
            overall_confidence = None
            processing_time = None
            if result_path.exists():
                with open(result_path) as f:
                    r = json.load(f)
                overall_confidence = r.get("overall_confidence")
                num_pages = r.get("num_pages")
                num_pdfs = r.get("num_pdfs", 1)
                pdf_names = r.get("pdf_names", [])
                processing_time = r.get("processing_time")
            jobs.append({
                "job_id": d.name,
                "status": status.get("status"),
                "filename": filename,
                "overall_confidence": overall_confidence,
                "num_pages": num_pages,
                "num_pdfs": num_pdfs,
                "pdf_names": pdf_names,
                "processing_time": processing_time,
                "created_at": _extract_epoch_from_job_id(d.name),
            })
    jobs.sort(key=lambda j: (j["created_at"], j["job_id"]), reverse=True)
    return jobs


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    import shutil
    job_dir = BASE_DIR / job_id
    if job_dir.exists() and job_dir.is_dir():
        shutil.rmtree(job_dir, ignore_errors=True)
        if DB_AVAILABLE:
            try:
                pool = await get_pool()
                async with pool.acquire() as conn:
                    row = await conn.fetchrow("SELECT id FROM extraction_results WHERE job_id = $1", job_id)
                    if row:
                        result_id = row["id"]
                        await conn.execute("DELETE FROM extracted_fields WHERE result_id = $1", result_id)
                        await conn.execute("DELETE FROM extraction_results WHERE id = $1", result_id)
            except Exception as e:
                logger.error(f"Error deleting job database record: {e}")
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Job not found")


@app.get("/pdfs")
async def list_uploaded_pdfs():
    """List all uploaded documents for the sidebar. Supports PDFs + image sets."""
    pdfs = []
    for d in sorted(BASE_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        pdf_path = d / "input.pdf"
        img_dir = d / "input_images"
        has_pdf = pdf_path.exists()
        has_images = img_dir.exists() and any(img_dir.iterdir())

        if not has_pdf and not has_images:
            continue

        name_path = d / "original_name.txt"
        orig_name = name_path.read_text().strip() if name_path.exists() else ""
        result_path = d / "results" / "result.json"
        status_data = _get_status(d)

        input_type = "pdf" if has_pdf else "image_set"

        entry = {
            "filename": orig_name or d.name,
            "job_id": d.name,
            "status": status_data.get("status"),
            "uploaded_at": d.stat().st_mtime,
            "overall_confidence": None,
            "input_type": input_type,
        }
        if result_path.exists():
            try:
                r = json.loads(result_path.read_text())
                entry["overall_confidence"] = r.get("overall_confidence")
                entry["input_type"] = r.get("input_type", input_type)
            except Exception:
                pass
        pdfs.append(entry)

    return pdfs


@app.post("/save-to-db/{job_id}")
async def save_result_to_db(job_id: str):
    """Save extraction results to PostgreSQL."""
    if not DB_AVAILABLE:
        raise HTTPException(503, "Database not available")

    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    result_path = job_dir / "results" / "result.json"
    if not result_path.exists():
        raise HTTPException(400, "No results yet for this job")

    with open(result_path) as f:
        result_data = json.load(f)

    name_path = job_dir / "original_name.txt"
    orig_name = name_path.read_text().strip() if name_path.exists() else f"job_{job_id}.pdf"
    pdf_path = job_dir / "input.pdf"

    logger.info("/save-to-db: START — job=%s file=%r", job_id, orig_name)

    doc_id = await upsert_ocr_document(
        job_id=job_id,
        file_name=orig_name,
        file_size=pdf_path.stat().st_size if pdf_path.exists() else None,
        file_path=str(pdf_path) if pdf_path.exists() else None,
        status="done",
        processing_time=result_data.get("processing_time"),
        confidence_score=result_data.get("overall_confidence"),
        num_pages=result_data.get("num_pages"),
        raw_text=result_data.get("raw_text"),
        result_json=result_data,
        primary_model=result_data.get("primary_model"),
        secondary_model=result_data.get("secondary_model"),
        token_usage=result_data.get("token_usage"),
    )

    if doc_id:
        logger.info("/save-to-db: SUCCESS — job=%s doc_id=%s", job_id, doc_id)
    else:
        logger.warning("/save-to-db: upsert returned no id — job=%s (check DB logs above)", job_id)

    return {
        "status": "saved",
        "doc_id": doc_id,
    }


# ── Section derivation fallback ─────────────────────────────────────

KNOWN_SECTIONS: list[dict] = [
    {"number": 1, "name": "Student Profile", "page": 1},
    {"number": 2, "name": "Family Background", "page": 1},
    {"number": 3, "name": "Housing Condition", "page": 2},
    {"number": 4, "name": "Financial Background", "page": 3},
    {"number": 5, "name": "Health Information", "page": 5},
    {"number": 6, "name": "Student Commitment", "page": 5},
    {"number": 7, "name": "Scholarship Information", "page": 6},
    {"number": 8, "name": "Volunteer Observation", "page": 6},
]


def _derive_sections(fields: list[StructuredField], raw_text: str) -> list[dict]:
    """Derive sections from raw_text headings + field data when LLM doesn't provide sections array.
    Always includes KNOWN_SECTIONS as a fallback."""
    import re
    name_map: dict[int, str] = {}
    page_map: dict[int, int] = {}

    for ks in KNOWN_SECTIONS:
        name_map.setdefault(ks["number"], ks["name"])
        page_map.setdefault(ks["number"], ks["page"])

    for match in re.finditer(
        r"(?:##\s*)?Section\s+(\d+)\s*[—–\-:.]\s*(.+?)(?:\n|$)",
        raw_text,
    ):
        num = int(match.group(1))
        name = match.group(2).strip()
        name_map[num] = name

    for f in fields:
        if f.section_number is not None:
            if f.section_number not in page_map:
                page_map[f.section_number] = f.page

    all_nums = sorted(set(name_map.keys()) | set(page_map.keys()))
    return [
        {
            "number": num,
            "name": name_map.get(num, f"Section {num}"),
            "page": page_map.get(num, 1),
        }
        for num in all_nums
    ]


# ── Page marker injection ───────────────────────────────────────────

def _insert_page_markers(raw_text: str, fields: list[dict]) -> str:
    """Insert --- Page N --- markers into raw_text based on field page numbers.
    This ensures the frontend can split transcription per-page reliably."""
    if not raw_text:
        return raw_text

    sorted_fields = sorted(fields, key=lambda f: f.get("page", 1))
    current_page = sorted_fields[0].get("page", 1) if sorted_fields else 1

    result = raw_text
    insertions = 0
    offset = 0

    for f in sorted_fields:
        page = f.get("page", 1)
        if page != current_page:
            label = f.get("label", "")
            if label:
                # Find this field's label in the text after the last insertion
                idx = result.find(label, offset)
                if idx >= 0:
                    marker = f"\n\n--- Page {page} ---\n\n"
                    result = result[:idx] + marker + result[idx:]
                    offset = idx + len(marker)
                    current_page = page
                    insertions += 1

    if insertions == 0 and len(sorted_fields) > 1:
        # Fallback: no markers inserted — base it on first field's page
        first_page = sorted_fields[0].get("page", 1)
        if first_page > 1:
            result = f"--- Page {first_page} ---\n\n{raw_text}"
            insertions = 1

    logger.info("Inserted %d page markers into raw_text", insertions)
    return result


# ── Render helpers for download ────────────────────────────────────

def _format_job_datetime(job_id: str) -> str:
    # Try parsing from job_id name (format: uuid_YYYY-MM-DD_HH-MM)
    parts = job_id.split("_")
    if len(parts) >= 3:
        date_str = parts[-2]
        time_str = parts[-1].replace("-", ":")
        return f"{date_str} {time_str}"
    try:
        from datetime import datetime
        job_dir = BASE_DIR / job_id
        if job_dir.exists():
            return datetime.fromtimestamp(job_dir.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return "Unknown"


def _render_markdown(data: dict, job_id: str) -> str:
    lines = [
        "# OCR Extraction Results",
        "",
        f"- **Job ID:** {job_id}",
        f"- **Date Created:** {_format_job_datetime(job_id)}",
        f"- **Overall Confidence:** {data.get('overall_confidence', '?')}%",
        f"- **Processing Time:** {data.get('processing_time', '?')}s",
        f"- **Number of Pages:** {data.get('num_pages', '?')}",
        "",
        "---",
        "",
    ]
    pages: dict[int, list[dict]] = {}
    for f in data.get("fields", []):
        pages.setdefault(f["page"], []).append(f)

    for page_num in sorted(pages):
        page_fields = pages[page_num]
        lines.append(f"## Page {page_num}")
        lines.append("")
        for f in page_fields:
            label = f["label"]
            value = f["value"] or "(empty)"
            conf = f["confidence"]
            badges = []
            if f.get("needs_clarification"):
                badges.append("needs clarification")
            if f.get("is_verified"):
                badges.append("verified")
            badge_str = f" ({', '.join(badges)})" if badges else ""
            lines.append(f"- **{label}:** {value} (confidence: {conf}%){badge_str}")
            if f.get("reason"):
                lines.append(f"  - ⚠ *Reason:* {f['reason']}")
            if f.get("verification_note") and f["verification_note"] != "High confidence, auto-accepted":
                lines.append(f"  - *Note:* {f['verification_note']}")
        lines.append("")
    return "\n".join(lines)


def _render_text(data: dict, job_id: str) -> str:
    lines = [
        "OCR EXTRACTION RESULTS",
        "======================",
        f"Job ID: {job_id}",
        f"Date Created: {_format_job_datetime(job_id)}",
        f"Overall Confidence: {data.get('overall_confidence', '?')}%",
        f"Processing Time: {data.get('processing_time', '?')}s",
        f"Number of Pages: {data.get('num_pages', '?')}",
        "",
        "=" * 60,
        "",
    ]
    pages: dict[int, list[dict]] = {}
    for f in data.get("fields", []):
        pages.setdefault(f["page"], []).append(f)

    for page_num in sorted(pages):
        page_fields = pages[page_num]
        lines.append(f"Page {page_num}:")
        lines.append("-" * 40)
        for f in page_fields:
            label = f["label"]
            value = f["value"] or "(empty)"
            conf = f["confidence"]
            badges = []
            if f.get("needs_clarification"):
                badges.append("needs clarification")
            if f.get("is_verified"):
                badges.append("verified")
            badge_str = f" ({', '.join(badges)})" if badges else ""
            lines.append(f"  {label}: {value} (conf: {conf}%){badge_str}")
            if f.get("reason"):
                lines.append(f"    Reason: {f['reason']}")
            if f.get("verification_note") and f["verification_note"] != "High confidence, auto-accepted":
                lines.append(f"    Note: {f['verification_note']}")
        lines.append("")
    return "\n".join(lines)


DOWNLOAD_FORMATS = {
    "json": ("result.json", "application/json"),
    "md": ("result.md", "text/markdown; charset=utf-8"),
    "txt": ("result.txt", "text/plain; charset=utf-8"),
    "html": ("result.html", "text/html; charset=utf-8"),
}


@app.get("/download/{job_id}")
async def download_result(job_id: str, format: str = "json"):
    """Download extraction result in json, md, or txt format.
    Generates md/txt on-the-fly from result.json if needed."""
    if format not in DOWNLOAD_FORMATS:
        raise HTTPException(400, f"Unsupported format. Choose from: {', '.join(DOWNLOAD_FORMATS)}")
    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    result_path = job_dir / "results" / "result.json"
    if not result_path.exists():
        raise HTTPException(404, "No results for this job")

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    if format in ("json", "html"):
        fmt_name, media_type = DOWNLOAD_FORMATS[format]
        file_path = job_dir / "results" / fmt_name
        if not file_path.exists():
            raise HTTPException(404, f"{format} result not available")
        return FileResponse(
            str(file_path), media_type=media_type,
            filename=f"result_{ts}.{format}",
        )

    # Generate md or txt on-the-fly from result.json
    with open(result_path) as f:
        data = json.load(f)

    if format == "md":
        content = _render_markdown(data, job_id)
        media_type = "text/markdown; charset=utf-8"
    else:
        content = _render_text(data, job_id)
        media_type = "text/plain; charset=utf-8"

    return Response(content=content, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="result_{ts}.{format}"',
    })
