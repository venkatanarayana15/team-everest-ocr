import hashlib
import json
import logging
import os
import sys
import threading
import time
import uuid
from collections import Counter
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
        find_pdf_by_hash,
        insert_pdf,
        list_pdfs as db_list_pdfs,
        insert_extraction_result,
        insert_extracted_fields,
        update_extraction_result,
        get_result_by_job_id,
        get_last_job_id_by_pdf_id,
        get_pool,
        close_pool,
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
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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
_job_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_JOBS)
_JOB_SEMAPHORE_TIMEOUT = 3600  # 1 hour max wait for a slot


def _acquire_slot(job_dir: Path) -> bool:
    """Acquire a concurrency slot (waits if memory is low). Returns False if timed out."""
    # Memory throttle: wait while free memory is below threshold
    mem_wait_start = time.time()
    while time.time() - mem_wait_start < _JOB_SEMAPHORE_TIMEOUT:
        free = psutil.virtual_memory().available / (1024 * 1024)
        if free >= MIN_FREE_MEM_MB:
            break
        logger.warning("Low memory: %.0f MB free (need %d MB). Delaying job...", free, MIN_FREE_MEM_MB)
        time.sleep(5)
    else:
        _set_status(job_dir, "error",
            f"Timed out waiting for memory (>{_JOB_SEMAPHORE_TIMEOUT}s, "
            f"free={free:.0f} MB < {MIN_FREE_MEM_MB} MB). Try again later.")
        return False

    acquired = _job_semaphore.acquire(blocking=True, timeout=_JOB_SEMAPHORE_TIMEOUT)
    if not acquired:
        _set_status(job_dir, "error",
            f"Timed out waiting for a processing slot (>{_JOB_SEMAPHORE_TIMEOUT}s). "
            "Try again later.")
    return acquired


def _release_slot() -> None:
    _job_semaphore.release()


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


def _get_status(job_dir: Path) -> dict:
    path = job_dir / "status.json"
    if not path.exists():
        return {"status": "unknown", "message": "", "log": [], "pages": 0}
    with open(path) as f:
        data = json.load(f)
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
    if not _acquire_slot(job_dir):
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

            # ── Step 2: Bbox (Tesseract, CPU) ──────────────────────
            _set_status(job_dir, "primary_extraction", "Running Tesseract for bounding box detection...")
            logger.info("[%s] Tesseract: detecting text regions...", job_dir.name)
            word_boxes = pipeline.run_bbox(pdf_path)
            _set_status(job_dir, "primary_extraction",
                f"Tesseract detected {len(word_boxes)} words across {len(num_pages_pages)} pages.",
                pages=len(num_pages_pages),
            )
            # Save tesseract word boxes for frontend mapping feature
            _save_tesseract_data(job_dir, word_boxes)

            # ── Step 3a: Primary extraction ──────────────────────────
            _set_status(job_dir, "primary_extraction", f"Running primary extraction ({primary_name})...")
            logger.info("[%s] Primary extraction with %s...", job_dir.name, primary_name)
            pages_dir = job_dir / "pages"
            page_images = {
                int(p.stem.split("_")[1]): str(p)
                for p in sorted(pages_dir.glob("page_*.png")) if "_original" not in p.stem
            } if pages_dir.exists() else {}
            model_data = pipeline.run_primary_extraction(str(pdf_path), page_images)

            if model_data:
                overall_confidence = model_data.get("overall_confidence", 0)
                raw_text = model_data.get("raw_text", "")
                # Insert reliable page markers based on field page numbers
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

        # ── Step 4: Secondary verification ──────────────────────────
        _set_status(job_dir, "secondary_verification", f"Running secondary verification ({secondary_name})...")
        logger.info("[%s] Secondary verification with %s...", job_dir.name, secondary_name)
        fields = pipeline.verify_secondary(fields, pipeline.run_bbox(pdf_path), str(job_dir), prefix=secondary_name)
        verified = sum(1 for f in fields if f.is_verified)
        corrected = sum(1 for f in fields if f.original_value is not None)
        new_from_secondary = sum(1 for f in fields if f.verified_by == secondary_name and f.extracted_by is None)
        _set_status(job_dir, "secondary_verification",
            f"{secondary_name} verified {verified} fields, corrected {corrected}, added {new_from_secondary} new.",
        )

        # ── Step 5: Fill missing template fields ─────────────────────
        fields = ExtractionPipeline.fill_missing_template_fields(fields)
        _set_status(job_dir, "template_fill",
            f"Template fill: {len(fields)} total fields after adding missing positions.",
        )

        # Re-derive sections now that template fill added missing section_numbers
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

        _set_status(job_dir, "done", "Extraction complete. Results ready for download.")

    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Pipeline failed: %s\n%s", e, tb)
        _set_status(job_dir, "error", f"{type(e).__name__}: {e}")
    finally:
        _cleanup_intermediate(job_dir)
        _release_slot()


def _run_image_pipeline(job_dir: Path, image_paths: dict[int, str]) -> None:
    """Pipeline for image-based inputs (Mode B/C). image_paths maps page_num -> file path."""
    try:
        import traceback
        import time
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
        model_data = pipeline.run_primary_extraction("", processed_images)

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
        fields = pipeline.verify_secondary(fields, word_boxes, str(job_dir), prefix=secondary_name)

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

    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Image pipeline failed: %s\n%s", e, tb)
        _set_status(job_dir, "error", f"{type(e).__name__}: {e}")


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

        file_hash = hashlib.sha256(content).hexdigest()
        file_size = len(content)

        if DB_AVAILABLE:
            try:
                existing = await find_pdf_by_hash(file_hash)
                if existing:
                    existing_job_id = await get_last_job_id_by_pdf_id(existing["id"])
                    return {
                        "duplicate": True,
                        "existing_job_id": existing_job_id,
                        "pdf": {
                            "id": existing["id"],
                            "filename": existing["filename"],
                            "uploaded_at": existing["uploaded_at"].isoformat() if existing.get("uploaded_at") else None,
                        },
                        "message": f"'{existing['filename']}' was already uploaded.",
                    }
            except Exception as e:
                logger.warning("Dedup check failed: %s", e)

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

        with open(job_dir / "file_hash.txt", "w") as f:
            f.write(file_hash)
        with open(job_dir / "original_name.txt", "w") as f:
            f.write(file.filename)

        pdf_id = None
        if DB_AVAILABLE:
            try:
                pdf_id = await insert_pdf(
                    filename=file.filename,
                    file_hash=file_hash,
                    file_size=file_size,
                    file_path=str(pdf_path),
                )
            except Exception as e:
                logger.warning("Failed to insert PDF into DB: %s", e)

        _set_status(job_dir, "queued", "PDF uploaded, starting pipeline...")
        thread = threading.Thread(
            target=_run_pipeline, args=(job_dir, str(pdf_path)), daemon=True
        )
        thread.start()
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

        thread = threading.Thread(
            target=_run_image_pipeline_from_zip,
            args=(job_dir, image_paths),
            daemon=True,
        )
        thread.start()
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

    thread = threading.Thread(
        target=_run_image_pipeline_from_zip,
        args=(job_dir, saved_paths),
        daemon=True,
    )
    thread.start()

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

    for f in pdf_files:
        content = await f.read()
        file_hash = hashlib.sha256(content).hexdigest()
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        job_id = f"{str(uuid.uuid4())[:8]}_{ts}"
        job_dir = BASE_DIR / job_id
        job_dir.mkdir(parents=True)
        pdf_path = job_dir / "input.pdf"
        with open(pdf_path, "wb") as fout:
            fout.write(content)
        with open(job_dir / "file_hash.txt", "w") as fout:
            fout.write(file_hash)
        with open(job_dir / "original_name.txt", "w") as fout:
            fout.write(f.filename)

        _set_status(job_dir, "queued", f"PDF batch: {f.filename}")
        thread = threading.Thread(
            target=_run_pipeline, args=(job_dir, str(pdf_path)), daemon=True
        )
        thread.start()
        results.append({"job_id": job_id, "filename": f.filename, "type": "pdf", "status": "queued"})

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
        thread = threading.Thread(
            target=_run_image_pipeline_from_zip,
            args=(job_dir, saved_paths),
            daemon=True,
        )
        thread.start()
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
        thread = threading.Thread(
            target=_run_image_pipeline_from_zip,
            args=(job_dir, image_paths),
            daemon=True,
        )
        thread.start()
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
    if not _acquire_slot(job_dir):
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
        _release_slot()


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
                content = open(item["path"], "rb").read()
                file_hash = hashlib.sha256(content).hexdigest()
                ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
                job_id = f"{str(uuid.uuid4())[:8]}_{ts}"
                job_dir = BASE_DIR / job_id
                job_dir.mkdir(parents=True)
                pdf_path = job_dir / "input.pdf"
                with open(pdf_path, "wb") as f:
                    f.write(content)
                with open(job_dir / "file_hash.txt", "w") as f:
                    f.write(file_hash)
                with open(job_dir / "original_name.txt", "w") as f:
                    f.write(item["name"])
                _set_status(job_dir, "queued", f"Folder batch: {item['name']}")
                thread = threading.Thread(
                    target=_run_pipeline, args=(job_dir, str(pdf_path)), daemon=True
                )
                thread.start()
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
                thread = threading.Thread(
                    target=_run_image_pipeline_from_zip,
                    args=(job_dir, item["images"]),
                    daemon=True,
                )
                thread.start()
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
        thread = threading.Thread(
            target=_run_pipeline, args=(job_dir, str(pdf_path)), daemon=True
        )
        thread.start()
        return {"job_id": job_id, "status": "restarted", "input_type": "pdf"}

    if img_dir.exists():
        image_paths = sorted([
            str(f.resolve()) for f in img_dir.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
        ])
        if image_paths:
            thread = threading.Thread(
                target=_run_image_pipeline_from_zip,
                args=(job_dir, image_paths),
                daemon=True,
            )
            thread.start()
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
async def get_page_image(job_id: str, page_num: int, width: int = 0, original: int = 0):
    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    pages_dir = job_dir / "pages"
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
            if result_path.exists():
                with open(result_path) as f:
                    r = json.load(f)
                overall_confidence = r.get("overall_confidence")
                num_pages = r.get("num_pages")
                num_pdfs = r.get("num_pdfs", 1)
                pdf_names = r.get("pdf_names", [])
            jobs.append({
                "job_id": d.name,
                "status": status.get("status"),
                "filename": filename,
                "overall_confidence": overall_confidence,
                "num_pages": num_pages,
                "num_pdfs": num_pdfs,
                "pdf_names": pdf_names,
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

        hash_path = d / "file_hash.txt"
        file_hash = hash_path.read_text().strip() if hash_path.exists() else ""
        name_path = d / "original_name.txt"
        orig_name = name_path.read_text().strip() if name_path.exists() else ""
        result_path = d / "results" / "result.json"
        status_data = _get_status(d)

        input_type = "pdf" if has_pdf else "image_set"

        entry = {
            "filename": orig_name or d.name,
            "file_hash": file_hash,
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

    if DB_AVAILABLE:
        try:
            db_rows = await db_list_pdfs(limit=100)
            db_by_hash = {r["file_hash"]: r for r in db_rows if r.get("file_hash")}
            for entry in pdfs:
                if entry["file_hash"] in db_by_hash:
                    db_r = db_by_hash[entry["file_hash"]]
                    entry["overall_confidence"] = entry["overall_confidence"] or db_r.get("overall_confidence")
        except Exception as e:
            logger.warning("Failed to supplement PDFs from DB: %s", e)

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

    # Find or create PDF record
    hash_path = job_dir / "file_hash.txt"
    file_hash = hash_path.read_text().strip() if hash_path.exists() else ""
    name_path = job_dir / "original_name.txt"
    orig_name = name_path.read_text().strip() if name_path.exists() else f"job_{job_id}.pdf"

    pdf_id = None
    if file_hash:
        existing_pdf = await find_pdf_by_hash(file_hash)
        if existing_pdf:
            pdf_id = existing_pdf["id"]
        else:
            pdf_path = job_dir / "input.pdf"
            pdf_id = await insert_pdf(
                filename=orig_name,
                file_hash=file_hash,
                file_size=pdf_path.stat().st_size if pdf_path.exists() else 0,
                file_path=str(pdf_path) if pdf_path.exists() else "",
            )

    if pdf_id is None:
        raise HTTPException(500, "Could not find or create PDF record")

    existing_result = await get_result_by_job_id(job_id)

    fields: list[StructuredField] = []
    for f_data in result_data.get("fields", []):
        fields.append(StructuredField(
            label=f_data.get("label", ""),
            value=f_data.get("value", ""),
            confidence=f_data.get("confidence", 0),
            page=f_data.get("page", 1),
            section_number=f_data.get("section_number"),
            bbox=tuple(f_data["bbox"]) if f_data.get("bbox") else None,
            value_bbox=tuple(f_data["value_bbox"]) if f_data.get("value_bbox") else None,
            needs_clarification=f_data.get("needs_clarification", False),
            reason=f_data.get("reason"),
            is_verified=f_data.get("is_verified", False),
            verifier_confidence=f_data.get("verifier_confidence"),
            verification_note=f_data.get("verification_note"),
            extracted_by=f_data.get("extracted_by"),
            verified_by=f_data.get("verified_by"),
            original_value=f_data.get("original_value"),
        ))

    sections_data = result_data.get("sections", [])

    if existing_result:
        # Update existing
        result_id = existing_result["id"]
        await update_extraction_result(
            job_id=job_id,
            status="done",
            overall_confidence=result_data.get("overall_confidence"),
            processing_time=result_data.get("processing_time"),
            raw_text=result_data.get("raw_text", ""),
            result_json=result_data,
            sections_json=sections_data,
        )
        # Also update fields (delete + re-insert)
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM extracted_fields WHERE result_id = $1",
                result_id,
            )
        inserted = await insert_extracted_fields(result_id, fields)
    else:
        result_id = await insert_extraction_result(
            job_id=job_id,
            pdf_id=pdf_id,
            status="done",
            overall_confidence=result_data.get("overall_confidence", 0),
            num_pages=result_data.get("num_pages", 0),
            processing_time=result_data.get("processing_time", 0.0),
            raw_text=result_data.get("raw_text", ""),
            primary_model=result_data.get("primary_model", ""),
            secondary_model=result_data.get("secondary_model", ""),
            result_json=result_data,
            sections_json=sections_data,
        )
        inserted = await insert_extracted_fields(result_id, fields)

    return {
        "status": "saved",
        "pdf_id": pdf_id,
        "result_id": result_id,
        "fields_inserted": inserted,
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
