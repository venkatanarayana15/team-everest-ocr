import asyncio
import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from src.extraction_pipeline import StructuredField

logger = logging.getLogger(__name__)

# Per-file locks to serialize concurrent status.json writes from concurrent
# download workers (startup batch) or any other concurrent pipeline runners.
_status_locks: dict[str, threading.Lock] = {}
_status_locks_lock = threading.Lock()

# ─── Status & Progress Tracking ───────────────────────────────────

STAGE_PROGRESS: dict[str, int] = {
    "queued": 0,
    "submitted": 5,
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
_status_queues: dict[str, asyncio.Queue] = {}
_new_job_queues: list[asyncio.Queue] = []
_last_good_status: dict[str, dict] = {}


def update_progress(job_id: str, data: dict) -> None:
    _progress_store[job_id] = data


def get_job_progress(job_id: str) -> dict:
    return _progress_store.get(job_id, {})


def _push_sse(job_id: str, payload: dict) -> None:
    q = _status_queues.get(job_id)
    if q:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


def _push_new_job(job_id: str) -> None:
    payload = json.dumps({"job_id": job_id})
    dead: list[int] = []
    for i, q in enumerate(_new_job_queues):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(i)
    for i in reversed(dead):
        _new_job_queues.pop(i)


async def _set_status(job_dir: Path, status: str, message: str = "", pages: int = 0, fields: list[dict] | None = None) -> None:
    path = job_dir / "status.json"
    loop = asyncio.get_running_loop()

    def _write_status() -> dict:
        path_str = str(path.resolve())
        with _status_locks_lock:
            lock = _status_locks.setdefault(path_str, threading.Lock())

        with lock:
            existing = {"log": []}
            if path.exists():
                try:
                    raw = path.read_text()
                    if raw.strip():
                        existing = json.loads(raw)
                except (json.JSONDecodeError, OSError):
                    existing = {"log": []}

            log = existing.get("log", [])
            if message:
                log.append({"t": datetime.now().strftime("%H:%M:%S"), "msg": message})

            data = {
                "status": status,
                "message": message or existing.get("message", ""),
                "log": log,
                "pages": pages or existing.get("pages", 0),
            }
            tmp = path.with_name(f".{path.name}.tmp")
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)
        return data

    data = await loop.run_in_executor(None, _write_status)
    stored_message = data.get("message", message or "")
    stored_log = data.get("log", [])
    stored_pages = data.get("pages", pages or 0)

    pct = STAGE_PROGRESS.get(status, 0)
    name_path = job_dir / "original_name.txt"
    pdf_name = name_path.read_text().strip() if name_path.exists() else job_dir.name

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
        "message": stored_message,
        "log": stored_log,
        "pages": stored_pages,
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


def _save_checkpoint(job_dir: Path, step: str, fields: list[StructuredField], overall_confidence: float, raw_text: str = "", sections: list[dict] | None = None, *, coverage: int | None = None, confidence: int | None = None) -> None:
    path = job_dir / "checkpoint.json"
    data = {
        "step": step,
        "overall_confidence": overall_confidence,
        "coverage": coverage,
        "confidence": confidence,
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
    tmp = job_dir / ".status.json.tmp"
    if tmp.exists():
        tmp.unlink(missing_ok=True)


# ─── Report Rendering Logic ───────────────────────────────────────

_TABLE_ROW_RE = re.compile(r"(.+?) — Row (\d+) — (.+)")
_OPTION_CHARS = {"✓", "✗", "●", "○"}
_CHECKED = {"✓", "●"}
_CHECK_MARK = "\u2611"
_UNCHECK_MARK = "\u2610"

SECTION_TITLES: dict[int | None, str] = {
    None: "Header Information",
    1: "Section 1 — Student Profile",
    2: "Section 2 — Family Background",
    3: "Section 3 — Housing Condition",
    4: "Section 4 — Financial Background",
    5: "Section 5 — Health Information",
    6: "Section 6 — Student Commitment",
    7: "Section 7 — Scholarship Information",
    8: "Section 8 — Volunteer Observation",
}


def _format_job_datetime(job_id: str) -> str:
    parts = job_id.split("_")
    if len(parts) >= 3:
        date_str = parts[-2]
        time_str = parts[-1].replace("-", ":")
        return f"{date_str} {time_str}"
    return "Unknown"


def _is_option(value: str) -> bool:
    return value in _OPTION_CHARS


def _is_checked(value: str) -> bool:
    return value in _CHECKED


def _render_section_fields(lines: list[str], fields: list[dict]) -> None:
    regular: list[dict] = []
    checkbox_groups: dict[str, list[tuple[str, str]]] = {}
    table_groups: dict[str, dict[int, dict[str, str]]] = {}

    for f in fields:
        label = f["label"]
        value = f.get("value") or ""

        table_match = _TABLE_ROW_RE.match(label)
        if table_match:
            group_key = table_match.group(1).strip()
            row_num = int(table_match.group(2))
            col_name = table_match.group(3).strip()
            table_groups.setdefault(group_key, {})
            table_groups[group_key].setdefault(row_num, {})
            table_groups[group_key][row_num][col_name] = value
            continue

        last_dash = label.rfind(" — ")
        if last_dash > 0 and _is_option(value):
            group_key = label[:last_dash].strip()
            option = label[last_dash + 3:].strip()
            checkbox_groups.setdefault(group_key, [])
            checkbox_groups[group_key].append((option, value))
            continue

        regular.append(f)

    if checkbox_groups:
        lines.append("")
    for group_key, options in checkbox_groups.items():
        for option, val in options:
            symbol = _CHECK_MARK if _is_checked(val) else _UNCHECK_MARK
            lines.append(f"{symbol} **{option}**")
        lines.append("")

    if table_groups:
        lines.append("")
    for group_key, rows in table_groups.items():
        sorted_row_nums = sorted(rows.keys())
        all_cols: list[str] = []
        seen = set()
        for rn in sorted_row_nums:
            for col in rows[rn]:
                if col not in seen:
                    all_cols.append(col)
                    seen.add(col)
        if not all_cols:
            continue
        header = "| # | " + " | ".join(f"**{c}**" for c in all_cols) + " |"
        sep = "|---|" + "|".join(["---"] * len(all_cols)) + "|"
        lines.append(header)
        lines.append(sep)
        for rn in sorted_row_nums:
            row_data = rows[rn]
            cells = " | ".join(row_data.get(col, "") or "—" for col in all_cols)
            lines.append(f"| {rn} | {cells} |")
        lines.append("")

    if regular:
        lines.append("")
    for f in regular:
        label = f["label"]
        value = f.get("value") or ""
        lines.append(f"- **{label}:** {value}")
    if regular:
        lines.append("")


def _render_markdown(data: dict, job_id: str) -> str:
    lines = []
    dt = _format_job_datetime(job_id)
    num_pages = data.get("num_pages", "?")
    lines.append("# OCR Extraction Results — Home Visit Questionnaire")
    lines.append("")
    lines.append(f"**Job:** `{job_id}`  ·  **Date:** {dt}  ·  **Pages:** {num_pages}")
    lines.append("")
    lines.append("---")
    lines.append("")

    fields = data.get("fields", [])
    if not fields:
        lines.append("_No fields extracted._")
        lines.append("")
        return "\n".join(lines)

    pages: dict[int, list[dict]] = {}
    for f in fields:
        pages.setdefault(f["page"], []).append(f)

    for page_num in sorted(pages):
        page_fields = pages[page_num]
        lines.append(f"## Page {page_num}")
        lines.append("")

        section_fields: dict[int | None, list[dict]] = {}
        for f in page_fields:
            section_fields.setdefault(f.get("section_number"), []).append(f)

        section_keys = sorted(section_fields.keys(), key=lambda x: -1 if x is None else (x if x is not None else 0))

        for sec_num in section_keys:
            sec_fields = section_fields[sec_num]
            sec_title = SECTION_TITLES.get(sec_num, f"Section {sec_num}")
            lines.append(f"### {sec_title}")
            _render_section_fields(lines, sec_fields)

    return "\n".join(lines)


def _render_text(data: dict, job_id: str) -> str:
    lines = [
        "OCR EXTRACTION RESULTS",
        "======================",
        f"Job ID: {job_id}",
        f"Date Created: {_format_job_datetime(job_id)}",
        f"Coverage: {data.get('coverage', '?')}%    Confidence: {data.get('confidence', '?')}%    Overall: {data.get('overall_confidence', '?')}%",
        f"Processing Time: {data.get('processing_time', '?')}s",
        f"Number of Pages: {data.get('num_pages', '?')}",
        "",
        "=" * 60,
        "",
    ]

    fields = data.get("fields", [])
    if not fields:
        return "\n".join(lines)

    pages: dict[int, list[dict]] = {}
    for f in fields:
        pages.setdefault(f["page"], []).append(f)

    for page_num in sorted(pages):
        page_fields = pages[page_num]
        lines.append(f"Page {page_num}:")
        lines.append("-" * 40)

        section_fields: dict[int | None, list[dict]] = {}
        for f in page_fields:
            section_fields.setdefault(f.get("section_number"), []).append(f)

        section_keys = sorted(section_fields.keys(), key=lambda x: -1 if x is None else (x if x is not None else 0))

        for sec_num in section_keys:
            sec_fields = section_fields[sec_num]
            sec_title = SECTION_TITLES.get(sec_num, f"Section {sec_num}")
            lines.append(f"  [{sec_title}]")
            for f in sec_fields:
                label = f["label"]
                value = f.get("value") or "(empty)"
                conf = f["confidence"]
                badges = []
                if f.get("needs_clarification"):
                    badges.append("needs clarification")
                if f.get("is_verified"):
                    badges.append("verified")
                badge_str = f" ({', '.join(badges)})" if badges else ""
                lines.append(f"    {label}: {value} (conf: {conf}%){badge_str}")
                if f.get("reason"):
                    lines.append(f"      Reason: {f['reason']}")
                if f.get("verification_note") and f["verification_note"] != "High confidence, auto-accepted":
                    lines.append(f"      Note: {f['verification_note']}")
            lines.append("")

    return "\n".join(lines)
