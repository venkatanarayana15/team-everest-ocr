import asyncio
import hashlib
import json
import logging
import os
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

import httpx

from src.extraction_pipeline import ExtractionPipeline, StructuredField, Config
from src.page_classifier import PageClassifier
from src.status import (
    _set_status, _get_status, update_progress, get_job_progress,
    _push_sse, _push_new_job, _new_job_queues,
    _status_queues, _cleanup_intermediate,
    STAGE_PROGRESS, _progress_store,
    _render_markdown, _render_text, _format_job_datetime,
)

import zipfile

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif"}
MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB


def is_pdf(file_path: str | Path) -> bool:
    return Path(file_path).suffix.lower() == ".pdf"


def _create_task(coro, name=None):
    """Wrap asyncio.create_task with exception logging for fire-and-forget tasks."""
    task = asyncio.create_task(coro, name=name)
    task.add_done_callback(_log_task_exception)
    return task

def _log_task_exception(task):
    try:
        exc = task.exception()
        if exc:
            logger.error("Background task '%s' failed: %s", task.get_name(), exc, exc_info=exc)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error("Error retrieving task result: %s", e, exc_info=True)

def is_image(file_path: str | Path) -> bool:
    return Path(file_path).suffix.lower() in IMAGE_EXTENSIONS


def is_zip(file_path: str | Path) -> bool:
    return Path(file_path).suffix.lower() == ".zip"


def detect_input_type(paths: list[str | Path]) -> str:
    if len(paths) == 1 and is_pdf(paths[0]):
        return "pdf"
    if len(paths) == 1 and is_zip(paths[0]):
        return "zip"
    image_count = sum(1 for p in paths if is_image(p))
    pdf_count = sum(1 for p in paths if is_pdf(p))
    if image_count > 0 and pdf_count == 0:
        return "image_set"
    if pdf_count > 0 and image_count == 0:
        if pdf_count == 1:
            return "pdf"
        return "pdf_set"
    if pdf_count > 0 and image_count > 0:
        return "mixed"
    return "unknown"


def detect_item_type(item_path: str | Path) -> str:
    p = Path(item_path)
    if p.is_file() and is_pdf(p):
        return "pdf"
    if p.is_dir():
        images = [f for f in p.iterdir() if f.is_file() and is_image(f)]
        if len(images) == 6:
            return "image_set"
    return "unknown"


def extract_zip(zip_path: str | Path, extract_dir: str | Path) -> list[str]:
    extract_dir = Path(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    image_paths: list[str] = []
    with zipfile.ZipFile(str(zip_path), "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            ext = Path(info.filename).suffix.lower()
            if ext in IMAGE_EXTENSIONS:
                zf.extract(info, extract_dir)
                extracted_path = extract_dir / info.filename
                if extracted_path.exists():
                    image_paths.append(str(extracted_path.resolve()))
    image_paths.sort()
    return image_paths


def scan_folder(folder_path: str | Path) -> list[dict]:
    folder = Path(folder_path)
    items: list[dict] = []
    for entry in sorted(folder.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_file() and is_pdf(entry):
            items.append({
                "path": str(entry.resolve()),
                "type": "pdf",
                "name": entry.name,
                "images": [],
            })
        elif entry.is_dir():
            images = sorted([
                str(f.resolve()) for f in entry.iterdir()
                if f.is_file() and is_image(f)
            ])
            if len(images) >= 4:
                items.append({
                    "path": str(entry.resolve()),
                    "type": "image_set",
                    "name": entry.name,
                    "images": images,
                })
    return items
from src.pipeline_runner import (
    run_pipeline, run_batch_pdfs_pipeline, run_batch_pdfs_pipeline_async,
    run_image_pipeline_from_zip,
    _validate_pdf, _validate_images,
)
from src.zoho_integration import (
    ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN,
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
    OcrExtractRequest,
    _run_ocr_extract_pipeline, _get_zoho_access_token, _update_zoho_creator,
    process_pending_on_startup,
)

logger = logging.getLogger(__name__)

try:
    from src.database import (
        init_pool,
        init_jobs_table,
        get_incomplete_jobs,
        update_job_status,
        get_pool,
        close_pool,
        upsert_ocr_document,
        get_result_by_file_hash,

    )
    DB_AVAILABLE = True
except ImportError as e:
    logger.warning("Database module not available: %s — DB save/webhook disabled", e)
    DB_AVAILABLE = False

class BeautifulColorFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[90m',     # Gray
        'INFO': '\033[94m',      # Light Blue
        'WARNING': '\033[93m',   # Yellow
        'ERROR': '\033[91m',     # Red
        'CRITICAL': '\033[1;91m' # Bold Red
    }
    RESET = '\033[0m'

    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.RESET)
        time_str = self.formatTime(record, "%H:%M:%S")
        
        name_parts = record.name.split('.')
        short_name = name_parts[-1] if name_parts else record.name
        
        msg = record.getMessage()
        if "SUCCESS" in msg:
            msg = msg.replace("SUCCESS", "\033[92mSUCCESS\033[0m")
        if "succeeded" in msg:
            msg = msg.replace("succeeded", "\033[92msucceeded\033[0m")
        if "failed" in msg:
            msg = msg.replace("failed", "\033[91mfailed\033[0m")
        if "FAILED" in msg:
            msg = msg.replace("FAILED", "\033[91mFAILED\033[0m")
        if "Skipping boolean field" in msg:
            msg = msg.replace("Skipping boolean field", "\033[93mSkipping boolean field\033[0m")
        if "No application_id" in msg:
            msg = msg.replace("No application_id", "\033[93mNo application_id\033[0m")
            
        formatted = f"\033[90m{time_str}\033[0m {log_color}[{record.levelname:<7}]{self.RESET} \033[36m{short_name:<16}\033[0m \033[90m│\033[0m {msg}"
        
        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)
        return formatted

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
for handler in list(root_logger.handlers):
    root_logger.removeHandler(handler)

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(BeautifulColorFormatter())
root_logger.addHandler(handler)

for _noisy in ("httpx", "httpcore", "google.genai", "google_genai", "google.api_core", "google.auth", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)



def _validate_env() -> None:
    """Validate critical environment variables at startup.
    Logs warnings for missing or misconfigured vars — does not crash.
    """
    provider = os.environ.get("PRIMARY_PROVIDER", "").lower().strip()
    api_key = os.environ.get("PRIMARY_API_KEY", "")

    if not provider:
        logger.warning("PRIMARY_PROVIDER not set — extraction will fail at runtime")
    elif provider == "datalab" and not api_key:
        logger.warning("PRIMARY_API_KEY not set — %s extraction will fail at runtime", provider)

    if provider == "datalab":
        base_url = os.environ.get("PRIMARY_BASE_URL", "")
        if not base_url:
            logger.warning("PRIMARY_BASE_URL not set — Datalab client will use default")
        model = os.environ.get("PRIMARY_MODEL", "")
        if not model:
            logger.warning("PRIMARY_MODEL not set — Datalab client will use default")

    if not os.environ.get("DATABASE_URL"):
        logger.warning("DATABASE_URL not set — DB features (save-to-db, webhook) disabled")

    webhook_secret = os.environ.get("WEBHOOK_SECRET", "")
    if not webhook_secret:
        logger.info("WEBHOOK_SECRET not set — webhook endpoint has no auth (set it in production)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global DB_AVAILABLE
    _validate_env()
    if DB_AVAILABLE and os.environ.get("DATABASE_URL"):
        try:
            await init_pool()
            await init_jobs_table()
            logger.info("Database pool + jobs table initialized")
        except Exception as e:
            logger.warning("Failed to init DB pool: %s — disabling DB features", e)
            DB_AVAILABLE = False
    _start_cleanup_thread()
    logger.info("Auto-cleanup thread started (every %ds, max age %ds)", CLEANUP_INTERVAL_SEC, JOB_MAX_AGE_SEC)
    _create_task(_safe_startup_poller())
    _create_task(_reconcile_stuck_jobs_on_startup())
    yield
    _stop_cleanup_thread()
    if DB_AVAILABLE:
        await close_pool()


async def _safe_startup_poller() -> None:
    try:
        await process_pending_on_startup(BASE_DIR)
    except Exception as e:
        logger.exception("Startup poller crashed: %s — will not retry", e)


async def _reconcile_stuck_jobs_on_startup() -> None:
    """Reconcile incompleting jobs on server startup.

    For jobs in 'collecting' state, attempts to poll Datalab once.
    Only marks as failed if the collect attempt confirms failure.
    """
    if not DB_AVAILABLE:
        return
    try:
        stuck = await get_incomplete_jobs()
        if not stuck:
            logger.info("Startup reconciliation: no incomplete jobs found")
            return

        logger.info("Startup reconciliation: found %d incomplete jobs — attempting recovery", len(stuck))
        from src.datalab_client import DatalabOcrClient

        recovered = 0
        failed = 0

        for job in stuck:
            job_id = job["job_id"]
            check_url = job.get("datalab_check_url", "")
            request_id = job.get("datalab_request_id", "")

            if not check_url or not request_id:
                # No Datalab tracking info — can't recover
                await update_job_status(
                    job_id=job_id,
                    status="failed",
                    error_detail="Server restarted while job was in progress (no Datalab tracking info)",
                )
                failed += 1
                continue

            # Attempt to check Datalab status once
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    api_key = os.environ.get("PRIMARY_API_KEY", "")
                    headers = {"X-API-Key": api_key}
                    resp = await client.get(check_url, headers=headers)
                    resp.raise_for_status()
                    body = resp.json()
                    status = body.get("status", "processing")

                    if status == "complete" and body.get("success"):
                        # Job completed while server was down — process results
                        from src.datalab_schema import convert_extract_response
                        extraction_data = body.get("extraction_schema_json", body)
                        if isinstance(extraction_data, str):
                            extraction_data = json.loads(extraction_data)

                        # ── CV verification on RAW extraction data (before convert_extract_response) ──
                        pdf_path = job.get("file_path", "")
                        if pdf_path and Path(pdf_path).exists():
                            from src.checkbox_vision import verify_all, load_page_images
                            try:
                                page_images = load_page_images(pdf_path)
                                extraction_data = verify_all(page_images, extraction_data)
                            except Exception as e:
                                logger.warning("CV checkbox verification failed during reconciliation for job=%s: %s — continuing without CV", job_id, e)
                        else:
                            logger.info("CV verify: no PDF for job=%s at path=%r — skipping", job_id, pdf_path)

                        data = convert_extract_response(extraction_data)

                        await upsert_ocr_document(
                            job_id=job_id,
                            file_name=job.get("file_name", ""),
                            status="done",
                            result_json=data,
                        )
                        await update_job_status(
                            job_id=job_id,
                            status="completed",
                        )
                        recovered += 1
                        logger.info("Reconciliation: recovered job=%s (completed while down)", job_id)
                    else:
                        # Still processing or failed — mark as failed
                        reason = body.get("error", "Server restarted while job was in progress")
                        await update_job_status(
                            job_id=job_id,
                            status="failed",
                            error_detail=reason,
                        )
                        failed += 1
            except Exception as e:
                logger.warning("Reconciliation: Datalab check failed for job=%s: %s", job_id, e)
                await update_job_status(
                    job_id=job_id,
                    status="failed",
                    error_detail=f"Server restart — Datalab check failed: {e}",
                )
                failed += 1

        logger.info("Startup reconciliation: %d recovered, %d failed", recovered, failed)
    except Exception as e:
        logger.exception("Startup reconciliation failed: %s", e)


app = FastAPI(title="OCR Extraction Pipeline", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174,http://localhost:5175").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_script_dir = Path(__file__).resolve().parent.parent
BASE_DIR = _script_dir / "output"
BASE_DIR.mkdir(exist_ok=True)
logger.info("Output dir: %s", BASE_DIR)

MAX_CONCURRENT_JOBS = int(os.environ.get("MAX_CONCURRENT_JOBS", "15"))
# Note: no timeout on semaphore — jobs wait indefinitely in queue
_job_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)


# ── Auto-cleanup old jobs ─────────────────────────────────────────
CLEANUP_INTERVAL_SEC = int(os.environ.get("CLEANUP_INTERVAL_SEC", "600"))
JOB_MAX_AGE_SEC = int(os.environ.get("JOB_MAX_AGE_SEC", str(7 * 86400)))
_cleanup_stop = threading.Event()


def _auto_cleanup_loop() -> None:
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


# ── Endpoints ─────────────────────────────────────────────────────

@app.get("/ping")
async def ping():
    return {"status": "ok"}


@app.get("/stream/{job_id}")
async def stream_status(job_id: str):
    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    async def event_gen():
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        _status_queues[job_id] = q
        last_payload: str | None = None
        last_heartbeat = time.time()
        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=1)
                except asyncio.TimeoutError:
                    now = time.time()
                    if now - last_heartbeat >= 10:
                        last_heartbeat = now
                        yield f"data: {json.dumps({'status': 'heartbeat'})}\n\n"
                    status = _get_status(job_dir)
                    progress = get_job_progress(job_id)
                    if not progress:
                        continue
                    data = {**status, "progress": progress}
                dumped = json.dumps(data)
                if dumped != last_payload:
                    last_payload = dumped
                    yield f"data: {dumped}\n\n"
                if data.get("status") in ("done", "error", "incomplete"):
                    yield f"data: {json.dumps({**data, '_final': True})}\n\n"
                    break
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("SSE generator error for %s", job_id)
            try:
                err_payload = json.dumps({"status": "error", "message": "Stream interrupted", "_final": True})
                yield f"data: {err_payload}\n\n"
            except Exception:
                pass
        finally:
            _status_queues.pop(job_id, None)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.get("/stream-batch")
async def stream_batch(job_ids: str):
    ids = [jid.strip() for jid in job_ids.split(",") if jid.strip()]
    if not ids:
        raise HTTPException(400, "No job_ids provided")

    job_dirs = {jid: BASE_DIR / jid for jid in ids}
    for jid, jdir in job_dirs.items():
        if not jdir.exists():
            raise HTTPException(404, f"Job not found: {jid}")

    async def event_gen():
        qs: dict[str, asyncio.Queue] = {}
        for jid in ids:
            q = asyncio.Queue(maxsize=50)
            _status_queues[jid] = q
            qs[jid] = q

        last: dict[str, str] = {}
        try:
            while True:
                all_terminal = True
                updates: list[str] = []
                for jid in ids:
                    q = qs[jid]
                    data = None
                    while not q.empty():
                        try:
                            data = q.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    if data is None:
                        status = _get_status(job_dirs[jid])
                        progress = get_job_progress(jid)
                        data = {"job_id": jid, **status, "progress": progress}
                    dumped = json.dumps(data)
                    if dumped != last.get(jid):
                        last[jid] = dumped
                        if data.get("status") in ("done", "error", "incomplete"):
                            final = {**data, "_final": True}
                            updates.append(f"data: {json.dumps(final)}\n\n")
                        else:
                            updates.append(f"data: {dumped}\n\n")
                    if data.get("status") not in ("done", "error", "incomplete"):
                        all_terminal = False
                if updates:
                    yield "".join(updates)
                if all_terminal:
                    yield f"data: {json.dumps({'_batch_complete': True, 'total': len(ids)})}\n\n"
                    break
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("SSE batch generator error")
            try:
                err_payload = json.dumps({"_batch_complete": True, "total": len(ids), "error": "Stream interrupted"})
                yield f"data: {err_payload}\n\n"
            except Exception:
                pass
        finally:
            for jid in ids:
                _status_queues.pop(jid, None)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.get("/stream-new-jobs")
async def stream_new_jobs():
    async def event_gen():
        # Send snapshot of existing jobs first
        yield f"data: {json.dumps({'snapshot': _list_jobs()})}\n\n"

        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        _new_job_queues.append(q)
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'heartbeat': True})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            try:
                _new_job_queues.remove(q)
            except ValueError:
                pass

    return StreamingResponse(event_gen(), media_type="text/event-stream")


async def _create_job_dir(original_name: str, status_msg: str, initial_stage: str = "queued", prefix: str = "") -> tuple[str, Path]:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    job_id = f"{prefix}_{ts}" if prefix else f"{str(uuid.uuid4())[:8]}_{ts}"
    job_dir = BASE_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    with open(job_dir / "original_name.txt", "w") as f:
        f.write(original_name)
    await _set_status(job_dir, initial_stage, status_msg)
    _push_new_job(job_id)
    return job_id, job_dir


async def _run_pipeline_task(job_dir: Path, pdf_path: str) -> None:
    try:
        await asyncio.wait_for(_job_semaphore.acquire(), timeout=1800)
    except asyncio.TimeoutError:
        logger.error("Job %s waited too long for semaphore", job_dir.name)
        _set_status(job_dir, "error", "Job timed out waiting in queue")
        return
    try:
        await run_pipeline(job_dir, pdf_path)
    finally:
        _job_semaphore.release()


async def _run_batch_task(job_dir: Path, pdfs_info: list[dict]) -> None:
    primary_provider = os.environ.get("PRIMARY_PROVIDER", "").lower().strip()
    if primary_provider == "datalab":
        # Async submit+collect: no semaphore needed, all PDFs submitted instantly
        await run_batch_pdfs_pipeline_async(job_dir, pdfs_info)
    else:
        try:
            await asyncio.wait_for(_job_semaphore.acquire(), timeout=1800)
        except asyncio.TimeoutError:
            logger.error("Job %s waited too long for semaphore", job_dir.name)
            _set_status(job_dir, "error", "Job timed out waiting in queue")
            return
        try:
            await run_batch_pdfs_pipeline(job_dir, pdfs_info)
        finally:
            _job_semaphore.release()


async def _run_image_task(job_dir: Path, image_paths) -> None:
    try:
        await asyncio.wait_for(_job_semaphore.acquire(), timeout=1800)
    except asyncio.TimeoutError:
        logger.error("Job %s waited too long for semaphore", job_dir.name)
        _set_status(job_dir, "error", "Job timed out waiting in queue")
        return
    try:
        await run_image_pipeline_from_zip(job_dir, image_paths)
    finally:
        _job_semaphore.release()


async def _run_ocr_extract_task(job_dir: Path, req: OcrExtractRequest) -> None:
    try:
        await asyncio.wait_for(_job_semaphore.acquire(), timeout=1800)
    except asyncio.TimeoutError:
        logger.error("Job %s waited too long for semaphore", job_dir.name)
        _set_status(job_dir, "error", "Job timed out waiting in queue")
        return
    try:
        await _run_ocr_extract_pipeline(job_dir, req)
    finally:
        _job_semaphore.release()


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    ext = Path(file.filename).suffix.lower()

    if ext == ".pdf":
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(400, "Empty file uploaded")
        if len(content) > MAX_UPLOAD_SIZE:
            raise HTTPException(413, f"File too large ({len(content)} bytes). Maximum: {MAX_UPLOAD_SIZE} bytes")

        file_hash = hashlib.sha256(content).hexdigest()
        file_size = len(content)

        if DB_AVAILABLE:
            try:
                existing = await get_result_by_file_hash(file_hash)
                if existing:
                    existing_job_id = existing.get("job_id")
                    logger.info(
                        "Dedup hit for hash=%s — returning existing job_id=%s",
                        file_hash[:12], existing_job_id,
                    )
                    return {
                        "job_id": existing_job_id,
                        "status": "duplicate",
                        "input_type": "pdf",
                        "dedup": True,
                        "message": "This file has already been processed",
                    }
            except Exception as e:
                logger.warning("Dedup check failed for hash=%s: %s — proceeding", file_hash[:12], e)

        job_id, job_dir = await _create_job_dir(file.filename, "PDF uploaded, starting pipeline...")

        pdf_path = job_dir / "input.pdf"
        with open(pdf_path, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        valid, err = _validate_pdf(str(pdf_path))
        if not valid:
            import shutil
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, f"Corrupted PDF upload: {err}")

        with open(job_dir / "file_hash.txt", "w") as f:
            f.write(file_hash)

        _create_task(_run_pipeline_task(job_dir, str(pdf_path)))
        return {"job_id": job_id, "status": "queued", "input_type": "pdf"}

    if ext in IMAGE_EXTENSIONS:
        content = await file.read()
        job_id, job_dir = await _create_job_dir(file.filename, "Image uploaded (waiting for full set)...")

        img_dir = job_dir / "input_images"
        img_dir.mkdir(exist_ok=True)
        img_path = img_dir / file.filename
        with open(img_path, "wb") as f:
            f.write(content)

        return {
            "job_id": job_id,
            "status": "awaiting_images",
            "input_type": "image_single",
            "message": "Upload 5 more images to complete the set, or use /upload-images for the full set.",
        }

    if ext == ".zip":
        content = await file.read()
        job_id, job_dir = await _create_job_dir(file.filename, "Extracting ZIP file...")

        zip_path = job_dir / "input.zip"
        with open(zip_path, "wb") as f:
            f.write(content)

        extract_dir = job_dir / "input_images"
        extract_dir.mkdir(exist_ok=True)
        image_paths = extract_zip(str(zip_path), str(extract_dir))

        if not image_paths:
            raise HTTPException(400, "No supported images found in ZIP")

        await _set_status(job_dir, "queued", f"ZIP extracted: {len(image_paths)} images. Classifying pages...")
        _create_task(_run_image_task(job_dir, image_paths))
        return {
            "job_id": job_id,
            "status": "queued",
            "input_type": "zip",
            "image_count": len(image_paths),
        }

    raise HTTPException(400, f"Unsupported file type: {ext}. Use PDF, images, or ZIP.")


@app.post("/upload-images")
async def upload_images(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "No files provided")

    image_files = [f for f in files if f.filename and Path(f.filename).suffix.lower() in IMAGE_EXTENSIONS]
    if not image_files:
        raise HTTPException(400, "No supported image files found")

    names = "+".join(f.filename for f in image_files[:3])
    if len(image_files) > 3:
        names += f" (+{len(image_files)-3} more)"

    job_id, job_dir = await _create_job_dir(names, f"{len(image_files)} images uploaded. Classifying pages...")

    img_dir = job_dir / "input_images"
    img_dir.mkdir(exist_ok=True)

    saved_paths: list[str] = []
    for f in image_files:
        content = await f.read()
        path = img_dir / f.filename
        with open(path, "wb") as fout:
            fout.write(content)
        saved_paths.append(str(path.resolve()))

    _create_task(_run_image_task(job_dir, saved_paths))

    return {
        "job_id": job_id,
        "status": "queued",
        "input_type": "image_set",
        "image_count": len(image_files),
    }


@app.post("/upload-batch")
async def upload_batch(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "No files provided")

    pdf_files = [f for f in files if f.filename and Path(f.filename).suffix.lower() == ".pdf"]
    image_files = [f for f in files if f.filename and Path(f.filename).suffix.lower() in IMAGE_EXTENSIONS]
    zip_files = [f for f in files if f.filename and Path(f.filename).suffix.lower() == ".zip"]

    results: list[dict] = []

    if pdf_files:
        names = ", ".join(f.filename for f in pdf_files[:3])
        if len(pdf_files) > 3:
            names += f" (+{len(pdf_files)-3} more)"

        prefix_id = f"batch_{str(uuid.uuid4())[:8]}"
        job_id, job_dir = await _create_job_dir(f"Batch: {names}", f"Processing PDF Batch: {names}", prefix=prefix_id)

        pdf_dir = job_dir / "pdfs"
        pdf_dir.mkdir(exist_ok=True)

        pdfs_info = []
        for f in pdf_files:
            content = await f.read()
            pdf_path = pdf_dir / f.filename
            with open(pdf_path, "wb") as fout:
                fout.write(content)
            pdfs_info.append({"filename": f.filename, "path": str(pdf_path.resolve())})

        _create_task(_run_batch_task(job_dir, pdfs_info))
        pdf_names = [f.filename for f in pdf_files]
        results.append({"job_id": job_id, "filename": f"Batch: {names}", "type": "pdf", "status": "queued", "pdf_names": pdf_names})

    if image_files:
        names = "+".join(f.filename for f in image_files[:3])
        if len(image_files) > 3:
            names += f" (+{len(image_files)-3} more)"

        job_id, job_dir = await _create_job_dir(names, f"{len(image_files)} images batch. Classifying pages...")

        img_dir = job_dir / "input_images"
        img_dir.mkdir(exist_ok=True)
        saved_paths: list[str] = []
        for f in image_files:
            content = await f.read()
            path = img_dir / f.filename
            with open(path, "wb") as fout:
                fout.write(content)
            saved_paths.append(str(path.resolve()))

        _create_task(_run_image_task(job_dir, saved_paths))
        results.append({"job_id": job_id, "filename": f"images_{len(image_files)}", "type": "image_set", "status": "queued"})

    for f in zip_files:
        content = await f.read()
        job_id, job_dir = await _create_job_dir(f.filename, f"ZIP batch: {f.filename}")

        zip_path = job_dir / "input.zip"
        with open(zip_path, "wb") as fout:
            fout.write(content)

        extract_dir = job_dir / "input_images"
        extract_dir.mkdir(exist_ok=True)
        image_paths = extract_zip(str(zip_path), str(extract_dir))

        await _set_status(job_dir, "queued", f"ZIP batch: {f.filename} ({len(image_paths)} images)")
        _create_task(_run_image_task(job_dir, image_paths))
        results.append({"job_id": job_id, "filename": f.filename, "type": "zip", "status": "queued"})

    return {
        "status": "batch_submitted",
        "total": len(results),
        "results": results,
    }


@app.get("/validate/{job_id}")
async def get_validation(job_id: str):
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
                with open(item["path"], "rb") as f:
                    content = f.read()
                file_hash = hashlib.sha256(content).hexdigest()

                job_id, job_dir = await _create_job_dir(item["name"], f"Folder batch: {item['name']}")

                pdf_path = job_dir / "input.pdf"
                with open(pdf_path, "wb") as f:
                    f.write(content)
                with open(job_dir / "file_hash.txt", "w") as f:
                    f.write(file_hash)

                _create_task(_run_pipeline_task(job_dir, str(pdf_path)))
                results.append({"job_id": job_id, "name": item["name"], "type": "pdf", "status": "queued"})

            elif item["type"] == "image_set":
                valid, err = _validate_images(item["images"])
                if not valid:
                    job_id, job_dir = await _create_job_dir(item["name"], err, initial_stage="error")
                    logger.error("[%s] %s", job_id, err)
                    results.append({"job_id": job_id, "name": item["name"], "type": "image_set", "status": "error", "error": err})
                    continue

                job_id, job_dir = await _create_job_dir(item["name"], f"Image set: {item['name']} ({len(item['images'])} images)")

                _create_task(_run_image_task(job_dir, item["images"]))
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
    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    pdf_path = job_dir / "input.pdf"
    img_dir = job_dir / "input_images"

    await _set_status(job_dir, "queued", "Retrying pipeline from last checkpoint...")

    if pdf_path.exists():
        valid, err = _validate_pdf(str(pdf_path))
        if not valid:
            raise HTTPException(400, f"Cannot retry: {err}")
        _create_task(_run_pipeline_task(job_dir, str(pdf_path)))
        return {"job_id": job_id, "status": "restarted", "input_type": "pdf"}

    if img_dir.exists():
        image_paths = sorted([
            str(f.resolve()) for f in img_dir.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
        ])
        if image_paths:
            _create_task(_run_image_task(job_dir, image_paths))
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
    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")
    path = job_dir / "tesseract_data.json"
    if not path.exists():
        raise HTTPException(404, "Tesseract data not available yet")
    with open(path) as f:
        return json.load(f)


@app.get("/pages/{job_id}/{page_num}")
async def get_page_image(job_id: str, page_num: int, width: int = 0, original: int = 0, pdf_name: str | None = None):
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
                if sub.is_dir():
                    if sub.name.startswith("pdf_"):
                        orig_path = sub / "original_name.txt"
                        if orig_path.exists() and orig_path.read_text().strip() == pdf_name:
                            pages_dir = sub / "pages"
                            break
                    elif sub.name.isdigit():
                        orig_path = sub / "original_name.txt"
                        if orig_path.exists() and orig_path.read_text().strip() == pdf_name:
                            pages_dir = sub / "pages"
                            break
        else:
            batch_pages = job_dir / str(idx) / "pages"
            if batch_pages.exists():
                pages_dir = batch_pages

        logger.info("get_page_image job=%s page=%d pdf_name=%s idx=%s pages_dir=%s",
                     job_id, page_num, pdf_name, idx, pages_dir)

    if not pages_dir.exists():
        original_pdf = _find_original_pdf(job_dir, pdf_name)
        if original_pdf:
            return _render_pdf_page(original_pdf, page_num, width, pages_dir)
        raise HTTPException(404, "Pages directory not found")

    image_path = pages_dir / (f"page_{page_num}_original.png" if original else f"page_{page_num}.png")
    if image_path.exists():
        pass
    else:
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


def _find_original_pdf(job_dir: Path, pdf_name: str | None = None) -> str | None:
    if pdf_name:
        pdf_path = job_dir / "pdfs" / pdf_name
        if pdf_path.exists():
            return str(pdf_path)
        result_path = job_dir / "results" / "result.json"
        if result_path.exists():
            try:
                with open(result_path) as f:
                    r = json.load(f)
                pdf_names = r.get("pdf_names", [])
                if pdf_name in pdf_names:
                    idx = pdf_names.index(pdf_name)
                    sub_original = job_dir / str(idx) / "original.pdf"
                    if sub_original.exists():
                        return str(sub_original)
            except Exception:
                pass
    pdf_path = job_dir / "input.pdf"
    if pdf_path.exists():
        return str(pdf_path)
    return None


def _render_pdf_page(pdf_path: str, page_num: int, width: int, pages_dir: Path) -> Response:
    import fitz
    from PIL import Image
    import io

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.error("Failed to open PDF for lazy rendering: %s", e)
        raise HTTPException(500, "Failed to open original PDF")

    if page_num < 1 or page_num > len(doc):
        doc.close()
        raise HTTPException(404, f"Page {page_num} not found (PDF has {len(doc)} pages)")

    page = doc[page_num - 1]
    # Render at ~144 DPI for good UI quality
    mat = fitz.Matrix(2.0, 2.0)
    pix = page.get_pixmap(matrix=mat)
    doc.close()

    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    # Cache to pages dir for subsequent requests
    try:
        pages_dir.mkdir(parents=True, exist_ok=True)
        cache_path = pages_dir / f"page_{page_num}.png"
        img.save(str(cache_path))
    except Exception as e:
        logger.warning("Failed to cache lazy-rendered page: %s", e)

    if width > 0:
        w, h = img.size
        new_h = int(h * (width / w))
        img = img.resize((width, new_h), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.read(), media_type="image/png")


@app.post("/correct/{job_id}")
async def correct_field(job_id: str, body: dict):
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
    tmp = corrections_path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(corrections, f, indent=2)
    os.replace(tmp, corrections_path)

    result_path = job_dir / "results" / "result.json"
    if result_path.exists():
        with open(result_path) as f:
            result_data = json.load(f)
        for field in result_data.get("fields", []):
            if field["label"] == label:
                if "original_value" not in field or not field["original_value"]:
                    field["original_value"] = field["value"]
                field["value"] = correct_value
                field["confidence"] = 100
                field["needs_clarification"] = False
                break
        tmp = result_path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(result_data, f, indent=2)
        os.replace(tmp, result_path)

    return {"status": "saved"}


@app.post("/update-raw-text/{job_id}")
async def update_raw_text(job_id: str, body: dict):
    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    new_raw_text = body.get("raw_text", "")

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


def _list_jobs():
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
            coverage = None
            confidence = None
            processing_time = None
            if result_path.exists():
                with open(result_path) as f:
                    r = json.load(f)
                overall_confidence = r.get("overall_confidence")
                coverage = r.get("coverage")
                confidence = r.get("confidence")
                num_pages = r.get("num_pages")
                num_pdfs = r.get("num_pdfs", 1)
                pdf_names = r.get("pdf_names", [])
                processing_time = r.get("processing_time")
            jobs.append({
                "job_id": d.name,
                "status": status.get("status"),
                "filename": filename,
                "overall_confidence": overall_confidence,
                "coverage": coverage,
                "confidence": confidence,
                "num_pages": num_pages,
                "num_pdfs": num_pdfs,
                "pdf_names": pdf_names,
                "processing_time": processing_time,
                "created_at": _extract_epoch_from_job_id(d.name),
            })
    jobs.sort(key=lambda j: (j["created_at"], j["job_id"]), reverse=True)
    return jobs


@app.get("/jobs")
async def list_jobs():
    return _list_jobs()


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    import shutil
    job_dir = BASE_DIR / job_id
    if job_dir.exists() and job_dir.is_dir():
        shutil.rmtree(job_dir, ignore_errors=True)
    if DB_AVAILABLE:
        try:
            pool = get_pool()
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM ocr_documents WHERE job_id = $1", job_id
                    )
                    await conn.execute(
                        "DELETE FROM ocr_jobs WHERE job_id = $1", job_id
                    )
        except Exception as e:
            logger.warning("Failed to clean up DB records for job %s: %s", job_id, e)
    if not job_dir.exists():
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Job not found")


@app.get("/pdfs")
async def list_uploaded_pdfs():
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
            "coverage": None,
            "confidence": None,
            "input_type": input_type,
        }
        if result_path.exists():
            try:
                r = json.loads(result_path.read_text())
                entry["overall_confidence"] = r.get("overall_confidence")
                entry["coverage"] = r.get("coverage")
                entry["confidence"] = r.get("confidence")
                entry["input_type"] = r.get("input_type", input_type)
            except Exception:
                pass
        pdfs.append(entry)

    return pdfs


DOWNLOAD_FORMATS = {
    "json": ("result.json", "application/json"),
    "md": ("result.md", "text/markdown; charset=utf-8"),
    "txt": ("result.txt", "text/plain; charset=utf-8"),
    "html": ("result.html", "text/html; charset=utf-8"),
}


@app.post("/save-to-db/{job_id}")
async def save_result_to_db(job_id: str):
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

    logger.info("/save-to-db: START — job=%s file=%r", job_id, orig_name)

    doc_id = await upsert_ocr_document(
        job_id=job_id,
        file_name=orig_name,
        status="done",
        processing_time=result_data.get("processing_time"),
        confidence_score=result_data.get("overall_confidence"),
        num_pdfs=result_data.get("num_pdfs"),
        result_json=result_data,
    )

    if doc_id:
        logger.info("/save-to-db: SUCCESS — job=%s doc_id=%s", job_id, doc_id)
    else:
        logger.warning("/save-to-db: upsert returned no id — job=%s", job_id)

    return {
        "status": "saved",
        "doc_id": doc_id,
    }


WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


@app.post("/api/webhooks/extraction-completed")
async def webhook_extraction_completed(payload: dict):
    """Webhook endpoint called by Datalab when extraction completes.

    Datalab webhook payload: { request_id, request_check_url, webhook_secret }
    This is just a notification — no extraction data in the body.
    We signal the waiting pipeline worker, which fetches the result via
    a single rate-limited GET to request_check_url.
    """
    auth = payload.get("auth_token", "")
    if WEBHOOK_SECRET and auth != WEBHOOK_SECRET:
        raise HTTPException(401, "Invalid auth token")

    request_id = payload.get("request_id", "")
    if not request_id:
        raise HTTPException(400, "Missing request_id")

    logger.info("Webhook received: request_id=%s", request_id)

    # Wake up the waiting pipeline worker — it fetches the result itself
    from src.datalab_client import signal_webhook
    signal_webhook(request_id)

    return {"status": "acknowledged"}


@app.get("/download/{job_id}")
async def download_result(job_id: str, format: str = "json"):
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


# ── OCR Extract (external Zoho Creator → Supabase → pipeline) ─────────

@app.post("/api/ocr/extract")
async def ocr_extract(req: OcrExtractRequest):
    if not req.file_names:
        raise HTTPException(400, "No file_names provided")
    if not ZOHO_CLIENT_ID or not ZOHO_CLIENT_SECRET or not ZOHO_REFRESH_TOKEN:
        raise HTTPException(500, "Zoho OAuth credentials not configured "
            "(ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN)")
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(500, "Supabase credentials not configured "
            "(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)")

    job_id = f"ext_{str(uuid.uuid4())[:8]}"
    job_dir = BASE_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    with open(job_dir / "original_name.txt", "w") as f:
        f.write(req.record_id)

    await _set_status(job_dir, "oauth",
        f"OCR extract queued for {req.record_id} ({len(req.file_names)} files)")
    _create_task(_run_ocr_extract_task(job_dir, req))

    return {"success": True, "status": "queued", "job_id": job_id}


@app.post("/api/ocr/test-zoho-update")
async def test_zoho_update(req: OcrExtractRequest):
    if not ZOHO_CLIENT_ID or not ZOHO_CLIENT_SECRET or not ZOHO_REFRESH_TOKEN:
        raise HTTPException(500, "Zoho OAuth credentials not configured")
    try:
        token = await asyncio.to_thread(_get_zoho_access_token)
        await asyncio.to_thread(_update_zoho_creator, token, req)
        return {"success": True, "message": f"OCR_Status=Yes set on {req.zoho_record_id}"}
    except Exception as e:
        raise HTTPException(500, f"Zoho update failed: {e}")
