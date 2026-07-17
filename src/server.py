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
from datetime import datetime, timezone
from pathlib import Path
import re

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse as _StreamingResponse


class SafeSSEResponse(_StreamingResponse):
    """StreamingResponse that catches CancelledError on shutdown.
    starlette 1.3.1 doesn't handle CancelledError (which is a BaseException
    in Python 3.13+), so Ctrl+C during an active SSE connection logs a
    spurious ERROR trace from uvicorn. This subclass suppresses it.
    """
    async def __call__(self, scope, receive, send):
        try:
            return await super().__call__(scope, receive, send)
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        except Exception:
            pass


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
    run_pipeline, run_batch_pdfs_pipeline,
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
        init_corrections_log_table,
        get_incomplete_jobs,
        update_job_status,
        get_pool,
        close_pool,
        upsert_ocr_document,
        get_result_by_file_hash,
        log_correction,

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

# Suppress uvicorn's "Exception in ASGI application" tracebacks on Ctrl+C
# CancelledError during shutdown is normal, not actionable
logging.getLogger("uvicorn.protocols.http.httptools_impl").setLevel(logging.CRITICAL)



def _validate_env() -> None:
    """Validate critical environment variables at startup.
    Logs warnings for missing or misconfigured vars — does not crash.
    """
    if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("PRIMARY_API_KEY"):
        logger.warning("GEMINI_API_KEY not set — extraction will fail at runtime")

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
            await init_corrections_log_table()
            logger.info("Database pool + jobs table + corrections_log table initialized")
        except Exception as e:
            logger.warning("Failed to init DB pool: %s — disabling DB features", e)
            DB_AVAILABLE = False
    _start_cleanup_thread()
    logger.info("Auto-cleanup thread started (every %ds, max age %ds)", CLEANUP_INTERVAL_SEC, JOB_MAX_AGE_SEC)
    _create_task(_safe_startup_poller())
    _create_task(_reconcile_stuck_jobs_on_startup())
    try:
        yield
    except asyncio.CancelledError:
        pass
    finally:
        _stop_cleanup_thread()
        if DB_AVAILABLE:
            try:
                await close_pool()
            except Exception:
                pass


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
        if stuck:
            logger.info("Startup reconciliation: found %d incomplete jobs — marking as failed", len(stuck))
            for job in stuck:
                await update_job_status(
                    job_id=job["job_id"],
                    status="failed",
                    error_detail="Server restarted while job was in progress",
                )
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

    return SafeSSEResponse(event_gen(), media_type="text/event-stream")


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

    return SafeSSEResponse(event_gen(), media_type="text/event-stream")


@app.get("/stream-new-jobs")
async def stream_new_jobs():
    async def event_gen():
        try:
            # Send snapshot of existing jobs first
            jobs_snapshot = await asyncio.to_thread(_list_jobs)
            yield f"data: {json.dumps({'snapshot': jobs_snapshot})}\n\n"

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
        except asyncio.CancelledError:
            pass

    return SafeSSEResponse(event_gen(), media_type="text/event-stream")


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
                    cached_result = None
                    result_path = BASE_DIR / existing_job_id / "results" / "result.json"
                    if result_path.exists():
                        try:
                            cached_result = json.loads(result_path.read_text())
                        except Exception:
                            pass
                    logger.info(
                        "Dedup hit for hash=%s — returning existing job_id=%s",
                        file_hash[:12], existing_job_id,
                    )
                    return {
                        "job_id": existing_job_id,
                        "status": "cached" if cached_result else "duplicate",
                        "input_type": "pdf",
                        "dedup": True,
                        "result": cached_result,
                        "message": "Cached result returned" if cached_result else "This file has already been processed",
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


_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3}\s+\w+\s+(.*)$")

def _parse_log_line(line: str) -> dict | None:
    m = _TS_RE.match(line)
    if m:
        ts = m.group(1)
        parts = ts.split(" ")
        t = parts[1] if len(parts) >= 2 else ts
        return {"t": t, "msg": m.group(2)}
    return None


@app.get("/logs/{job_id}")
async def get_logs(job_id: str, lines: int = 200):
    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")
    log_path = job_dir / "result.logs"
    if not log_path.exists():
        return {"log": [], "total": 0}
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
        all_lines = content.splitlines()
        parsed = []
        for line in all_lines[-lines:]:
            entry = _parse_log_line(line)
            if entry:
                parsed.append(entry)
        return {"log": parsed, "total": len(all_lines)}
    except Exception as e:
        logger.error("GET /logs/%s: failed to read — %s", job_id, e)
        raise HTTPException(500, "Failed to read logs")


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


@app.get("/pages/{job_id}/{page_num}")
async def get_page_image(job_id: str, page_num: int, width: int = 0, original: int = 0, pdf_name: str | None = None):
    if page_num < 1 or page_num > 6:
        raise HTTPException(422, f"Page number {page_num} out of range (1-6)")
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

        if idx >= 0:
            pages_dir = job_dir / str(idx) / "pages"
        else:
            for sub in job_dir.iterdir():
                if sub.is_dir():
                    if sub.name.startswith("pdf_"):
                        orig_path = sub / "original_name.txt"
                        if orig_path.exists() and orig_path.read_text().strip() == pdf_name:
                            pages_dir = sub / "pages"
                            pages_dir.mkdir(parents=True, exist_ok=True)
                            break
                    elif sub.name.isdigit():
                        orig_path = sub / "original_name.txt"
                        if orig_path.exists() and orig_path.read_text().strip() == pdf_name:
                            pages_dir = sub / "pages"
                            pages_dir.mkdir(parents=True, exist_ok=True)
                            break

        logger.info("get_page_image job=%s page=%d pdf_name=%s idx=%s pages_dir=%s",
                     job_id, page_num, pdf_name, idx, pages_dir)

    image_path = pages_dir / (f"page_{page_num}_original.png" if original else f"page_{page_num}.png")
    if not image_path.exists():
        original_pdf = _find_original_pdf(job_dir, pdf_name)
        if original_pdf:
            pages_dir.mkdir(parents=True, exist_ok=True)
            return _render_pdf_page(original_pdf, page_num, width, pages_dir)
        if pages_dir.exists():
            png_files = sorted(
                p for p in pages_dir.iterdir()
                if p.suffix == ".png" and ("_original" in p.stem) == bool(original) and "_ocr" not in p.stem
            )
            if 0 <= page_num - 1 < len(png_files):
                image_path = png_files[page_num - 1]
            else:
                raise HTTPException(404, f"Page {page_num} not found")
        else:
            raise HTTPException(404, "Pages directory not found and original PDF not available")

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
        return Response(content=buf.read(), media_type="image/png",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

    return FileResponse(str(image_path), media_type="image/png",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


def _find_original_pdf(job_dir: Path, pdf_name: str | None = None) -> str | None:
    if pdf_name:
        pdf_path = job_dir / "pdfs" / pdf_name
        if pdf_path.exists():
            logger.info("_find_original_pdf: found %s in pdfs/", pdf_name)
            return str(pdf_path)
        logger.info("_find_original_pdf: %s not in pdfs/, checking result.json...", pdf_name)
        result_path = job_dir / "results" / "result.json"
        if result_path.exists():
            try:
                with open(result_path) as f:
                    r = json.load(f)
                pdf_names = r.get("pdf_names", [])
                if pdf_name in pdf_names:
                    idx = pdf_names.index(pdf_name)
                    sub_original = job_dir / str(idx) / pdf_name
                    if sub_original.exists():
                        logger.info("_find_original_pdf: found %s at idx=%s", pdf_name, idx)
                        return str(sub_original)
                    logger.warning("_find_original_pdf: idx=%d but %s missing at %s", idx, pdf_name, sub_original)
                else:
                    logger.warning("_find_original_pdf: pdf_name=%s not in pdf_names=%s", pdf_name, pdf_names)
            except Exception as e:
                logger.warning("_find_original_pdf: error reading %s: %s", result_path, e)
    pdf_path = job_dir / "input.pdf"
    if pdf_path.exists():
        logger.info("_find_original_pdf: falling back to input.pdf")
        return str(pdf_path)
    logger.warning("_find_original_pdf: no original PDF found for pdf_name=%s in %s", pdf_name, job_dir)
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
    return Response(content=buf.read(), media_type="image/png",
                    headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.post("/correct/{job_id}")
async def correct_field(job_id: str, body: dict):
    job_dir = BASE_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(404, "Job not found")

    label = body.get("label", "")
    correct_value = body.get("correct_value", "")
    pdf_name = body.get("pdf_name")  # optional, for batch disambiguation
    if not label:
        raise HTTPException(400, "label is required")

    logger.info(
        "/correct: job=%s pdf_name=%r label=%r correct_value=%r",
        job_id, pdf_name, label, correct_value,
    )

    found = False
    original_value = ""
    result_path = job_dir / "results" / "result.json"
    result_data = None
    if result_path.exists():
        with open(result_path) as f:
            result_data = json.load(f)

    # Find original value from current state (before patch)
    def _lookup_original(fields_list: list[dict]) -> str:
        for field in fields_list:
            if field["label"] == label:
                return field.get("original_value", "") or field.get("value", "")
        return ""

    if pdf_name and result_data and isinstance(result_data.get("pdfs"), list):
        for pdf in result_data["pdfs"]:
            pdf_file = pdf.get("pdf_name") or pdf.get("filename") or pdf.get("name", "")
            if pdf_file == pdf_name and isinstance(pdf.get("fields"), list):
                original_value = _lookup_original(pdf["fields"])
                break
    elif result_data:
        original_value = _lookup_original(result_data.get("fields", []))
        if not original_value and isinstance(result_data.get("pdfs"), list):
            for pdf in result_data["pdfs"]:
                if isinstance(pdf.get("fields"), list):
                    original_value = _lookup_original(pdf["fields"])
                    if original_value:
                        break

    now = datetime.now(timezone.utc)
    corrections_path = job_dir / "corrections.json"
    corrections = []
    if corrections_path.exists():
        with open(corrections_path) as f:
            corrections = json.load(f)

    corrections.append({
        "label": label,
        "original_value": original_value,
        "correct_value": correct_value,
        "pdf_name": pdf_name or None,
        "timestamp": now.isoformat(),
    })
    tmp = corrections_path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(corrections, f, indent=2)
    os.replace(tmp, corrections_path)

    if DB_AVAILABLE:
        await log_correction(
            job_id=job_id,
            field_label=label,
            original_value=original_value,
            corrected_value=correct_value,
            pdf_name=pdf_name or None,
        )

    # Apply correction to result.json
    if result_data:

        def _apply_correction(fields: list[dict]) -> bool:
            for field in fields:
                if field["label"] == label:
                    old_val = field.get("value", "")
                    if "original_value" not in field or not field.get("original_value"):
                        field["original_value"] = field.get("value", "")
                    field["value"] = correct_value
                    field["confidence"] = 100
                    field["needs_clarification"] = False
                    logger.info(
                        "/correct: APPLIED — label=%r old=%r new=%r",
                        label, old_val, correct_value,
                    )
                    return True
            logger.warning("/correct: label %r not found in fields list (len=%d)", label, len(fields))
            return False

        # If pdf_name provided, only search that PDF's fields
        if pdf_name and isinstance(result_data.get("pdfs"), list):
            for pdf in result_data["pdfs"]:
                pdf_file = pdf.get("pdf_name") or pdf.get("filename") or pdf.get("name", "")
                if pdf_file == pdf_name and isinstance(pdf.get("fields"), list):
                    logger.info("/correct: searching PDF pdf_name=%r (matched %r)", pdf_name, pdf_file)
                    found = _apply_correction(pdf["fields"])
                    break
                else:
                    logger.info("/correct: skipping PDF pdf_name=%r (got %r)", pdf_name, pdf_file)
        else:
            found = _apply_correction(result_data.get("fields", []))
            if not found and isinstance(result_data.get("pdfs"), list):
                for pdf in result_data["pdfs"]:
                    if isinstance(pdf.get("fields"), list):
                        if _apply_correction(pdf["fields"]):
                            found = True
                            break

        if found:
            tmp = result_path.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(result_data, f, indent=2)
            os.replace(tmp, result_path)
            logger.info("/correct: written result.json for job=%s", job_id)
        else:
            logger.warning("/correct: field %r not found — will raise 404", label)

    if not found:
        raise HTTPException(404, f"Field with label {label!r} not found in job {job_id}")

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


_SECTION_RE = re.compile(r"^(?:Section\s+)?(\d+)")

def _extract_section_from_label(label: str) -> str | None:
    """Extract section number from a field label, e.g. 'Section 2 — Name' → '2'."""
    m = _SECTION_RE.search(label)
    if m:
        return m.group(1)
    return None


def _compute_metrics(top: int | None = None, since: str | None = None) -> dict:
    since_ts: float | None = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            since_ts = since_dt.timestamp()
        except Exception:
            pass

    all_corrections: list[dict] = []
    for d in BASE_DIR.iterdir():
        if not d.is_dir():
            continue
        corr_path = d / "corrections.json"
        if not corr_path.exists():
            continue
        with open(corr_path) as f:
            corr_list = json.load(f)
        for c in corr_list:
            # Filter by timestamp
            if since_ts:
                ts = c.get("timestamp")
                if ts:
                    try:
                        c_ts = datetime.fromisoformat(ts).timestamp()
                        if c_ts < since_ts:
                            continue
                    except Exception:
                        pass  # old entry without parseable timestamp: include
            # Backfill original_value for old entries that don't have it
            if "original_value" not in c or not c.get("original_value"):
                result_path = d / "results" / "result.json"
                if result_path.exists():
                    try:
                        with open(result_path) as f:
                            res = json.load(f)
                        original = next(
                            (f["value"] for f in res.get("fields", []) if f["label"] == c["label"]),
                            None
                        )
                        c["original_value"] = original or ""
                    except Exception:
                        c["original_value"] = ""
                else:
                    c["original_value"] = ""
            all_corrections.append(c)

    if not all_corrections:
        return {"total_corrections": 0, "message": "No human corrections recorded yet"}

    field_corrections: dict[str, list[dict]] = {}
    page_corrections: dict[str, list[dict]] = {}
    for c in all_corrections:
        label = c.get("label", "")
        field_corrections.setdefault(label, []).append(c)
        sec = _extract_section_from_label(label)
        page_corrections.setdefault(sec or "0", []).append(c)

    per_field = {}
    for label, corrs in sorted(field_corrections.items()):
        total = len(corrs)
        changed = sum(1 for c in corrs if c.get("original_value", "") != c.get("correct_value", ""))
        per_field[label] = {
            "total_corrections": total,
            "times_changed": changed,
            "stability_pct": round((1 - changed / total) * 100) if total else 0,
        }

    per_page = {}
    for sec, corrs in sorted(page_corrections.items()):
        per_page[sec] = {
            "total_corrections": len(corrs),
            "fields": sorted(set(c.get("label", "") for c in corrs)),
        }

    result = {
        "total_corrections": len(all_corrections),
        "per_field": per_field,
        "per_page": per_page,
    }

    if top and top > 0:
        sorted_fields = sorted(per_field.items(), key=lambda x: x[1]["total_corrections"], reverse=True)
        result["per_field"] = dict(sorted_fields[:top])

    return result


@app.get("/metrics")
async def get_metrics(top: int | None = None, since: str | None = None):
    return await asyncio.to_thread(_compute_metrics, top=top, since=since)


@app.get("/analytics/frequently-edited")
async def get_frequently_edited(limit: int = 20, days: int | None = None):
    if not DB_AVAILABLE:
        raise HTTPException(503, "Database not available")
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            if days:
                rows = await conn.fetch(
                    """
                    SELECT field_label,
                           COUNT(*) AS edit_count,
                           MAX(edited_at) AS last_edited
                    FROM corrections_log
                    WHERE edited_at > NOW() - $2::interval
                    GROUP BY field_label
                    ORDER BY edit_count DESC
                    LIMIT $1
                    """,
                    limit, f"{days} days",
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT field_label,
                           COUNT(*) AS edit_count,
                           MAX(edited_at) AS last_edited
                    FROM corrections_log
                    GROUP BY field_label
                    ORDER BY edit_count DESC
                    LIMIT $1
                    """,
                    limit,
                )
        result = [dict(r) for r in rows]
        return {"frequently_edited": result, "total_fields": len(result)}
    except Exception as e:
        logger.error("GET /analytics/frequently-edited: FAILED — %s", e, exc_info=True)
        raise HTTPException(500, "Failed to query corrections_log")


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
    return await asyncio.to_thread(_list_jobs)


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
                    await conn.execute(
                        "DELETE FROM corrections_log WHERE job_id = $1", job_id
                    )
        except Exception as e:
            logger.warning("Failed to clean up DB records for job %s: %s", job_id, e)
    if not job_dir.exists():
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Job not found")


def _list_uploaded_pdfs() -> list[dict]:
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


@app.get("/pdfs")
async def list_uploaded_pdfs():
    return await asyncio.to_thread(_list_uploaded_pdfs)


DOWNLOAD_FORMATS = {
    "json": ("result.json", "application/json"),
    "md": ("result.md", "text/markdown; charset=utf-8"),
    "txt": ("result.txt", "text/plain; charset=utf-8"),
    "html": ("result.html", "text/html; charset=utf-8"),
}


@app.post("/save-to-db/{job_id}")
async def save_result_to_db(job_id: str, body: dict = {}):
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

    logger.info("/save-to-db: read result.json — top keys=%s, has_fields=%s, has_pdfs=%s, pdfs_count=%d",
        list(result_data.keys()),
        "fields" in result_data,
        "pdfs" in result_data,
        len(result_data.get("pdfs", [])),
    )

    # Apply optional corrections from body as safety net
    corrections = body.get("corrections", [])
    logger.info("/save-to-db: %d corrections in body", len(corrections))
    if corrections:
        def _apply(fields_list: list[dict], label: str, correct_value: str) -> bool:
            for field in fields_list:
                if field["label"] == label:
                    old_val = field.get("value", "")
                    if "original_value" not in field or not field.get("original_value"):
                        field["original_value"] = field.get("value", "")
                    field["value"] = correct_value
                    field["confidence"] = 100
                    field["needs_clarification"] = False
                    logger.info(
                        "/save-to-db: APPLIED — label=%r old=%r new=%r",
                        label, old_val, correct_value,
                    )
                    return True
            return False

        applied_count = 0
        for c in corrections:
            lbl = c.get("label", "")
            val = c.get("correct_value", "")
            pdf_name = c.get("pdf_name", "")
            if not lbl:
                continue
            found = False
            if pdf_name and isinstance(result_data.get("pdfs"), list):
                # Only search the named PDF's fields
                for pdf in result_data["pdfs"]:
                    pdf_file = pdf.get("pdf_name") or pdf.get("filename") or pdf.get("name", "")
                    if pdf_file == pdf_name and isinstance(pdf.get("fields"), list):
                        found = _apply(pdf["fields"], lbl, val)
                        break
            else:
                found = _apply(result_data.get("fields", []), lbl, val)
                if not found and isinstance(result_data.get("pdfs"), list):
                    for pdf in result_data["pdfs"]:
                        if isinstance(pdf.get("fields"), list):
                            if _apply(pdf["fields"], lbl, val):
                                found = True
                                break
            if found:
                applied_count += 1
            else:
                logger.warning("/save-to-db: correction not found — label=%r", lbl)

        logger.info("/save-to-db: applied %d/%d corrections in-memory", applied_count, len(corrections))

        tmp = result_path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(result_data, f, indent=2)
        os.replace(tmp, result_path)
        logger.info("/save-to-db: written result.json after in-memory corrections")

    name_path = job_dir / "original_name.txt"
    orig_name = name_path.read_text().strip() if name_path.exists() else f"job_{job_id}.pdf"

    logger.info("/save-to-db: START — job=%s file=%r", job_id, orig_name)

    is_batch = isinstance(result_data.get("pdfs"), list)
    doc_id = ""

    if is_batch:
        for i, pdf_data in enumerate(result_data["pdfs"]):
            if "error" in pdf_data or not isinstance(pdf_data.get("fields"), list):
                continue
            pdf_job_id = f"{job_id}_{i}"
            pdf_file_name = pdf_data.get("pdf_name") or pdf_data.get("name", f"file_{i}")
            pdf_fields = pdf_data["fields"]
            if any(f.get("value") for f in pdf_fields):
                logger.info("/save-to-db: upserting PDF row %s (file=%s fields=%d)", pdf_job_id, pdf_file_name, len(pdf_fields))
                pdf_doc_id = await upsert_ocr_document(
                    job_id=pdf_job_id,
                    file_name=pdf_file_name,
                    status="done",
                    processing_time=result_data.get("processing_time"),
                    confidence_score=pdf_data.get("overall_confidence"),
                    num_pdfs=None,
                    result_json=pdf_data,
                )
                if pdf_doc_id:
                    logger.info("/save-to-db: PDF row SUCCESS — %s doc_id=%s", pdf_job_id, pdf_doc_id)
                    if not doc_id:
                        doc_id = pdf_doc_id
                else:
                    logger.warning("/save-to-db: PDF row FAILED — %s", pdf_job_id)
    else:
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

        def _clear_sync_markers(fields_list: list[dict]):
            for f in fields_list:
                f.pop("original_value", None)
                f["is_verified"] = True

        if isinstance(result_data.get("pdfs"), list):
            for pdf in result_data["pdfs"]:
                if isinstance(pdf.get("fields"), list):
                    _clear_sync_markers(pdf["fields"])
        elif isinstance(result_data.get("fields"), list):
            _clear_sync_markers(result_data["fields"])

        with open(result_path, "w") as f:
            json.dump(result_data, f, indent=2, ensure_ascii=False)
        logger.info("/save-to-db: final result.json written back (markers cleared)")
    else:
        logger.warning("/save-to-db: upsert returned no id — job=%s", job_id)

    return {
        "status": "saved",
        "doc_id": doc_id,
    }


WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


@app.post("/api/webhooks/extraction-completed")
async def webhook_extraction_completed(payload: dict):
    """Webhook endpoint called when extraction completes."""
    auth = payload.get("auth_token", "")
    if WEBHOOK_SECRET and auth != WEBHOOK_SECRET:
        raise HTTPException(401, "Invalid auth token")

    request_id = payload.get("request_id", "")
    if not request_id:
        raise HTTPException(400, "Missing request_id")

    logger.info("Webhook received: request_id=%s", request_id)

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
        content = await asyncio.to_thread(_render_markdown, data, job_id)
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


def main():
    import atexit

    atexit.register(lambda: print("Server stopped.", flush=True))

    import uvicorn

    try:
        uvicorn.run("src.server:app", host="0.0.0.0", port=8000, reload=True)
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
