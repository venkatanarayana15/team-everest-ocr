import json
import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

from src.extraction_pipeline import StructuredField

logger = logging.getLogger(__name__)

STAGE_PROGRESS: dict[str, int] = {
    "queued": 0,
    "oauth": 3,
    "downloading": 10,
    "converting": 18,
    "supabase_upload": 25,
    "pipeline_start": 30,
    "preprocessing": 35,
    "primary_extraction": 55,
    "field_mapping": 70,
    "secondary_verification": 82,
    "template_fill": 92,
    "zoho_update": 96,
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


_status_queues: dict[str, queue.Queue] = {}
_status_queues_lock = threading.Lock()


def _push_sse(job_id: str, payload: dict) -> None:
    with _status_queues_lock:
        q = _status_queues.get(job_id)
        if q:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass


_last_good_status: dict[str, dict] = {}


def _set_status(job_dir: Path, status: str, message: str = "", pages: int = 0, fields: list[dict] | None = None) -> None:
    path = job_dir / "status.json"
    existing = {"log": []}
    if path.exists():
        with open(path) as f:
            existing = json.load(f)

    log = existing.get("log", [])
    if message:
        log.append({"t": datetime.now().strftime("%H:%M:%S"), "msg": message})

    data = {
        "status": status,
        "message": message or existing.get("message", ""),
        "log": log,
        "pages": pages or existing.get("pages", 0),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    pct = STAGE_PROGRESS.get(status, 0)
    name_path = job_dir / "original_name.txt"
    pdf_name = name_path.read_text().strip() if name_path.exists() else job_dir.name

    with _progress_lock:
        existing_progress = _progress_store.get(job_dir.name, {})
        start_time = existing_progress.get("start_time")
        if not start_time:
            start_time = time.time()
        now = time.time()

        pdfs_map = existing_progress.get("pdfs", {})
        pdf_file_start = existing_progress.get("pdf_file_start", {})
        if pdf_name not in pdf_file_start:
            pdf_file_start[pdf_name] = now
        file_elapsed = round(now - pdf_file_start[pdf_name], 1)

        pdfs_map[pdf_name] = {
            "progress": pct,
            "stage": status,
            "elapsed": file_elapsed,
        }

        _progress_store[job_dir.name] = {
            "overall": pct,
            "pdfs": pdfs_map,
            "start_time": start_time,
            "pdf_file_start": pdf_file_start,
            "elapsed": round(now - start_time, 1),
        }

    sse_payload = {
        "status": status,
        "message": message or existing.get("message", ""),
        "log": log,
        "pages": pages or existing.get("pages", 0),
        "progress": {
            "overall": pct,
            "pdfs": pdfs_map,
            "start_time": start_time,
            "elapsed": round(now - start_time, 1),
        },
    }
    if fields is not None:
        sse_payload["fields"] = fields

    _push_sse(job_dir.name, sse_payload)


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


def _cleanup_intermediate(job_dir: Path) -> None:
    cp = job_dir / "checkpoint.json"
    if cp.exists():
        cp.unlink(missing_ok=True)
    ts = job_dir / "tesseract_data.json"
    if ts.exists():
        ts.unlink(missing_ok=True)
