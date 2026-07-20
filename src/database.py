"""PostgreSQL/Supabase database module — writes to ocr_documents table."""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

from form_schema import (
    FORM_SCHEMA,
    getAllFields,
    getTableDefinitions,
    getTableHeaders,
    validateSchema,
)

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")
POOL_MIN_SIZE = int(os.getenv("DATABASE_POOL_MIN_SIZE", "2"))
POOL_MAX_SIZE = int(os.getenv("DATABASE_POOL_MAX_SIZE", "20"))
POOL_CONNECT_TIMEOUT = float(os.getenv("DATABASE_CONNECT_TIMEOUT", "10"))

_pool: Optional[asyncpg.Pool] = None

# ── Generated field label → database column mapping ──────────────────────────

def _build_field_to_column(schema) -> dict[str, str]:
    mapping = {}
    for f in getAllFields(schema):
        if f.get("db_column"):
            mapping[f["label"]] = f["db_column"]
    return mapping

FIELD_TO_COLUMN = _build_field_to_column(FORM_SCHEMA)

BOOLEAN_COLUMNS: set[str] = set()

TABLE_PARENT_COLUMNS: dict[str, str] = {
    h["label"]: h["db_column"]
    for f in getAllFields(FORM_SCHEMA)
    if f.get("type") == "table_header" and f.get("db_column")
    for h in [{"label": f["label"], "db_column": f["db_column"]}]
}

# Columns to skip in DB save when value is empty string (not None, not "No" — only "").
SKIP_IF_EMPTY_COLUMNS: set[str] = {
    "photograph_kept_at_home",
}

# =============================================================================
# NORMALIZATION HELPERS
# =============================================================================

# Table parent columns keyed by section number — handles both the datalab
# "parent — Row {n} — column" format and the LLM flat "{parent} - {column}" format.
_TABLE_BY_NUMBER: dict[str, str] = {
    "2.5": "family_members",
    "4.3.1": "other_assets_details",
    "4.4.1": "other_income_sources",
    "4.6.1": "loan_details",
}

_LEADING_NUM_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+")
_NUM_PREFIX_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)")
_NOISE_PAREN_RE = re.compile(r"\s*\(tick all that apply\)", re.IGNORECASE)
_SEG_SEP_RE = re.compile(r"\s*—\s*|\s*–\s*|\s*--\s*|\s+-\s+")
_ROW_RE = re.compile(r"^(.*?)\s*(?:—|–|--|-)\s*Row\s+(\d+)\s*(?:—|–|--|-)\s*(.*)$", re.IGNORECASE)
_STRIKE_CHARS_RE = re.compile(r"[─━═]")
_STRIKE_LINE_RE = re.compile(r"^[\s─━═\-_~xX/\\]{4,}$")

_NEG_VALUES = {
    "", "no", "false", "0", "n", "\u2717", "\u2014", "\u2013", "-", "n/a", "nil", "none",
}
_CHECKED_VALUES = {"\u2713", "1", "yes", "true", "y", "/"}


def _norm(text: str) -> str:
    """Normalize a label: drop leading section number, unify dashes, lowercase."""
    s = text or ""
    s = _LEADING_NUM_RE.sub("", s)
    s = _NOISE_PAREN_RE.sub("", s)
    s = s.replace("\u2014", " - ").replace("\u2013", " - ").replace("--", " - ")
    s = re.sub(r"\s+-\s+", " - ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.rstrip(":").strip().lower()


def _num_prefix(text: str) -> str:
    m = _NUM_PREFIX_RE.match(text or "")
    return m.group(1) if m else ""


# ── Parent-level routing dicts (built from form_schema at import time) ─────

# Single-select radio groups: normalized parent label → parent column
_SINGLE_SELECT_PARENT: dict[str, str] = {}
for _f in getAllFields(FORM_SCHEMA):
    if _f.get("db_column") and _f["db_column"] in {
        "house_ownership", "type_of_bedroom", "bathroom", "kitchen_type",
    }:
        _parts = [s for s in _SEG_SEP_RE.split(_f["label"]) if s.strip()]
        if len(_parts) >= 2:
            _SINGLE_SELECT_PARENT.setdefault(_norm(_parts[0]), _f["db_column"])
_SINGLE_SELECT_PARENT["type of home"] = "type_of_home"
_SINGLE_SELECT_PARENT["type of ceiling"] = "type_of_ceiling"

# JSONB multi-select checkbox groups: normalized parent label → parent column
_JSONB_GROUP_PARENTS: dict[str, str] = {
    "government id verified": "government_id_verified",
    "assets at home": "assets_at_home",
    "income type": "income_type",
}

# Yes/No radio pairs: normalized parent label → column
_YESNO_PARENT: dict[str, str] = {}
for _f in getAllFields(FORM_SCHEMA):
    if _f.get("is_yes_no_pair") and _f.get("db_column"):
        _col = _f["db_column"]
        if _col not in _SINGLE_SELECT_PARENT.values():
            _parts = [s for s in _SEG_SEP_RE.split(_f["label"]) if s.strip()]
            if len(_parts) >= 2:
                _YESNO_PARENT.setdefault(_norm(_parts[0]), _col)

_ALL_PARENT_COLUMNS: set[str] = (
    set(_JSONB_GROUP_PARENTS.values())
    | set(_SINGLE_SELECT_PARENT.values())
    | set(_YESNO_PARENT.values())
)

# Normalized scalar field labels → column (built from FIELD_TO_COLUMN,
# excluding any column handled by a parent-level dict or table header).
_NORM_SCALAR: dict[str, str] = {}
for _lab, _col in FIELD_TO_COLUMN.items():
    if _col not in _ALL_PARENT_COLUMNS and _col not in TABLE_PARENT_COLUMNS.values():
        _NORM_SCALAR[_norm(_lab)] = _col


def _is_checked(value: str | None) -> bool:
    return isinstance(value, str) and value.strip().lower() in _CHECKED_VALUES


def _is_strikethrough(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    cleaned = value.strip()
    if _STRIKE_CHARS_RE.search(cleaned):
        return True
    if _STRIKE_LINE_RE.match(cleaned):
        return True
    return False


def _extract_structured_fields(fields: list[dict]) -> dict[str, Any]:
    """Map the fields array from result_json into structured DB columns.

    Tolerant of both the datalab label format (em-dash separators, "— Row {n} —"
    tables, scalar group values) and the LLM label format (hyphen separators,
    "(tick all that apply)" noise, flat single-row tables, Yes/No checkbox pairs).
    """
    out: dict[str, Any] = {}
    jsonb_checked: dict[str, list[str]] = {c: [] for c in _JSONB_GROUP_PARENTS.values()}
    jsonb_specify_texts: dict[str, dict[str, str]] = {}
    single_checked: dict[str, list[str]] = {}
    yesno_val: dict[str, str] = {}
    table_rows: dict[str, dict[int, dict[str, str]]] = {}

    def _add_cell(col: str, row: int, colname: str, value: Any) -> None:
        colname = (colname or "").strip()
        if not colname:
            return
        if "|" in colname:
            colnames = [c.strip() for c in colname.split("|") if c.strip()]
            str_val = str(value or "")
            values = [v.strip() for v in str_val.split("|")]
            for i, cn in enumerate(colnames):
                if i < len(values) and values[i]:
                    v = values[i]
                else:
                    v = ""
                if _is_strikethrough(v):
                    v = ""
                table_rows.setdefault(col, {}).setdefault(row, {})[cn] = v
            return
        if isinstance(value, str):
            v = value.strip()
            if re.match(r"^[/\\]+$", v):
                value = ""
            elif re.search(r"[/\\]$", v):
                value = ""
        if _is_strikethrough(value):
            value = ""
        table_rows.setdefault(col, {}).setdefault(row, {})[colname] = value

    def _set_scalar(col: str, value: Any) -> None:
        if col not in out or (
            isinstance(value, str) and value.strip() and not str(out.get(col) or "").strip()
        ):
            out[col] = value

    def _append_jsonb(col: str, option: str, value: Any) -> None:
        if _is_checked(value):
            jsonb_checked[col].append(option)
        elif isinstance(value, str) and value.strip().lower() not in _NEG_VALUES:
            jsonb_checked[col].append(value.strip())

    for f in fields:
        label = (f.get("label") or "").strip()
        value = f.get("value", "")
        if not label:
            continue

        # 1) Table row: "parent — Row {n} — column"
        rm = _ROW_RE.match(label)
        if rm:
            tcol = _TABLE_BY_NUMBER.get(_num_prefix(rm.group(1))) or \
                TABLE_PARENT_COLUMNS.get(rm.group(1).strip())
            if tcol:
                _add_cell(tcol, int(rm.group(2)), rm.group(3), value)
            continue

        segs = [s for s in _SEG_SEP_RE.split(label) if s.strip()]

        if len(segs) >= 2:
            parent, leaf = segs[0], segs[-1].strip()

            # 2) Flat single-row table: "4.6.1 ... - column"
            num = _num_prefix(label)
            if num in _TABLE_BY_NUMBER:
                _add_cell(_TABLE_BY_NUMBER[num], 1, leaf, value)
                continue

            nparent = _norm(parent)

            # 3) JSONB multi-select checkbox group
            jcol = _JSONB_GROUP_PARENTS.get(nparent)
            if jcol is not None:
                if leaf.lower().endswith("(specify)"):
                    if isinstance(value, str) and value.strip():
                        base_opt = leaf[: -len("(specify)")].strip()
                        jsonb_specify_texts.setdefault(jcol, {})[base_opt] = value.strip()
                    continue
                _append_jsonb(jcol, leaf, value)
                continue

            # 4) Single-select radio group
            scol = _SINGLE_SELECT_PARENT.get(nparent)
            if scol is not None:
                if _is_checked(value):
                    single_checked.setdefault(scol, []).append(leaf)
                continue

            # 5) Yes/No radio pair
            ycol = _YESNO_PARENT.get(nparent)
            if ycol is not None:
                if _is_checked(value):
                    yesno_val[ycol] = leaf
                continue

        # 6) Direct scalar value (simple 1:1 field, no parent-child split)
        nlabel = _norm(label)
        col = _NORM_SCALAR.get(nlabel)
        if col is not None and value is not None:
            _set_scalar(col, value)

        # 7) Yes/No scalar fallback — LLM may emit the parent label
        #    directly (e.g. "4.4 Apart from your job...") instead of
        #    the child label (e.g. "4.4 ... — Yes"). Only applies when
        #    step 6 didn't match.
        if col is None:
            yno_col = _YESNO_PARENT.get(nlabel)
            if yno_col is not None:
                val_str = str(value or "").strip().lower()
                if val_str in ("yes", "✓", "y", "1", "true"):
                    yesno_val[yno_col] = "Yes"
                elif val_str in _NEG_VALUES:
                    yesno_val[yno_col] = "No"

    # Merge scalar notes: "{parent} — Notes" → append to parent's scalar value
    for f in fields:
        label = (f.get("label") or "").strip()
        segs = [s for s in _SEG_SEP_RE.split(label) if s.strip()]
        if len(segs) == 2 and segs[-1].strip().lower() == "notes":
            parent_col = _NORM_SCALAR.get(_norm(segs[0]))
            if parent_col:
                note_val = (f.get("value") or "").strip()
                if note_val and note_val.lower() not in _NEG_VALUES:
                    existing = out.get(parent_col)
                    if existing and str(existing).strip():
                        out[parent_col] = f"{existing}: {note_val}"
                    else:
                        out[parent_col] = note_val

    for col, opt_texts in jsonb_specify_texts.items():
        for base_opt, text in opt_texts.items():
            if not text or text.strip().lower() in _NEG_VALUES:
                continue
            checked = jsonb_checked.get(col, [])
            for bare in (base_opt, base_opt.rstrip(":"), base_opt + ":"):
                if bare in checked:
                    checked.remove(bare)
            jsonb_checked[col].append(f"{base_opt.rstrip(':')}: {text}")

    for col in _JSONB_GROUP_PARENTS.values():
        items = jsonb_checked.get(col, [])
        has_qualified = any(
            item.strip().lower().startswith("others:")
            for item in items
        )
        if has_qualified:
            jsonb_checked[col] = [
                item for item in items
                if item.strip().lower() not in ("others", "others:")
            ]

    for col in _JSONB_GROUP_PARENTS.values():
        out[col] = json.dumps(sorted(set(jsonb_checked.get(col, []))))
    for col, opts in single_checked.items():
        out[col] = ", ".join(dict.fromkeys(opts))
    for col, v in yesno_val.items():
        out[col] = v
    for col, rows in table_rows.items():
        sorted_rows = [
            {k: rows[row_num].get(k, "") for k in sorted(rows[row_num].keys())}
            for row_num in sorted(rows.keys())
        ]
        sorted_rows = [r for r in sorted_rows if any(v.strip() for v in r.values())]
        out[col] = json.dumps(sorted_rows) if sorted_rows else "[]"

    return out


async def init_pool() -> None:
    """Create the connection pool. Call once at server startup."""
    global _pool
    if _pool is not None:
        return

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to .env — get it from "
            "Supabase Dashboard → Project Settings → Database → "
            "Connection string (Transaction pooler, port 6543)."
        )

    logger.info(
        "Creating asyncpg pool (min=%d, max=%d, timeout=%gs)",
        POOL_MIN_SIZE, POOL_MAX_SIZE, POOL_CONNECT_TIMEOUT,
    )
    _pool = await asyncpg.create_pool(
        dsn=DATABASE_URL,
        min_size=POOL_MIN_SIZE,
        max_size=POOL_MAX_SIZE,
        timeout=POOL_CONNECT_TIMEOUT,
        statement_cache_size=0,
    )
    logger.info("Database pool created OK")

    async with _pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    logger.info("Database pool health check passed")


async def close_pool() -> None:
    """Close the connection pool. Call once at server shutdown."""
    global _pool
    if _pool is None:
        return
    try:
        await _pool.close()
    except Exception:
        logger.exception("Error closing database pool")
    _pool = None
    logger.info("Database pool closed")


def get_pool() -> asyncpg.Pool:
    """Return the connection pool. Raises RuntimeError if not initialized."""
    if _pool is None:
        raise RuntimeError(
            "Database pool not initialized. Call init_pool() on startup."
        )
    return _pool


async def upsert_ocr_document(
    *,
    job_id: str,
    file_name: str,
    status: str = "done",
    processing_time: Optional[float] = None,
    confidence_score: Optional[float] = None,
    num_pdfs: Optional[int] = None,
    result_json: Optional[dict] = None,
) -> str:
    """
    Upsert a row into ocr_documents keyed on job_id.
    Structured field columns are auto-populated from result_json.fields.
    Returns the row uuid as str, or "" on failure.
    """
    logger.info(
        "upsert_ocr_document: job=%s file=%r status=%s",
        job_id, file_name, status,
    )

    pool = get_pool()

    data: dict[str, Any] = {
        "job_id": job_id,
        "file_name": file_name,
        "status": status,
    }

    data["processed_at"] = datetime.now(timezone.utc)

    if processing_time is not None:
        data["processing_time"] = processing_time
    if confidence_score is not None:
        data["confidence_score"] = confidence_score
    if num_pdfs is not None:
        data["num_pdfs"] = num_pdfs
    if result_json is not None:
        rj = dict(result_json)
        rj["job_id"] = job_id
        data["result_json"] = json.dumps(rj)

        # Collect fields from both single-doc (fields) and batch (pdfs[n].fields) modes
        raw_fields: list[dict] = list(rj.get("fields", []) or [])
        if not raw_fields and isinstance(rj.get("pdfs"), list):
            for pdf in rj["pdfs"]:
                pdf_fields = pdf.get("fields", [])
                if pdf_fields:
                    raw_fields.extend(pdf_fields)
        if raw_fields:
            sample_labels = [f.get("label","")[:60] for f in raw_fields[:10]]
            logger.info(
                "upsert_ocr_document: raw_fields=%d, sample_labels=%s",
                len(raw_fields), sample_labels,
            )
            structured = _extract_structured_fields(raw_fields)
            logger.info(
                "upsert_ocr_document: extracted %d structured columns: %s",
                len(structured), list(structured.keys())[:8],
            )
            for col, val in structured.items():
                if val is not None:
                    if col in SKIP_IF_EMPTY_COLUMNS and isinstance(val, str) and not val.strip():
                        continue
                    data[col] = val

    logger.info(
        "upsert_ocr_document: payload columns=%s",
        list(data.keys()),
    )

    cols = list(data.keys())
    placeholders = [f"${i + 1}" for i in range(len(cols))]
    values = list(data.values())

    update_set = ", ".join(f"{col} = EXCLUDED.{col}" for col in cols if col != "job_id")

    sql = (
        f"INSERT INTO ocr_documents ({', '.join(cols)}) "
        f"VALUES ({', '.join(placeholders)}) "
        f"ON CONFLICT (job_id) DO UPDATE SET {update_set} "
        f"RETURNING id"
    )

    logger.debug(
        "upsert_ocr_document: upserting %d columns: %s",
        len(cols), cols,
    )
    logger.debug("upsert_ocr_document: SQL = %s", sql)

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, *values)
    except Exception as exc:
        logger.error(
            "upsert_ocr_document: FAILED for job=%s — %s",
            job_id, exc,
            exc_info=True,
        )
        return ""

    doc_id = str(row["id"]) if row else ""
    if doc_id:
        logger.info(
            "upsert_ocr_document: SUCCESS — job=%s → row id=%s",
            job_id, doc_id,
        )
    else:
        logger.warning(
            "upsert_ocr_document: INSERT returned no row for job=%s "
            "(possible conflict or constraint violation)",
            job_id,
        )
    return doc_id


async def get_result_by_job_id(job_id: str) -> Optional[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ocr_documents WHERE job_id = $1",
            job_id,
        )
        return dict(row) if row else None


async def get_last_job_id_by_pdf_id(pdf_id: str) -> Optional[str]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT job_id FROM ocr_documents WHERE id = $1::uuid",
            pdf_id,
        )
        return row["job_id"] if row else None


# ── Async job tracking (webhook-style submit/collect) ──────────────────


async def init_jobs_table() -> None:
    """Create ocr_jobs table if not exists. Call once at startup."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ocr_jobs (
                job_id TEXT PRIMARY KEY,
                file_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'submitted'
                    CHECK (status IN ('submitted','collecting','completed','failed')),
                datalab_request_id TEXT NOT NULL DEFAULT '',
                datalab_check_url TEXT NOT NULL DEFAULT '',
                file_hash TEXT NOT NULL DEFAULT '',
                file_path TEXT NOT NULL DEFAULT '',
                error_detail TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at TIMESTAMPTZ
            )
        """)


async def create_job(
    *,
    job_id: str,
    file_name: str = "",
    file_hash: str = "",
    file_path: str = "",
) -> bool:
    """Insert a new job with status='submitted'."""
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO ocr_jobs (job_id, file_name, status, file_hash, file_path)
                VALUES ($1, $2, 'submitted', $3, $4)
                ON CONFLICT (job_id) DO NOTHING
                """,
                job_id, file_name, file_hash, file_path,
            )
            if result == "DELETE 0":
                logger.warning("Job %s already exists — skipping", job_id)
        return True
    except Exception as e:
        logger.error("create_job: FAILED for job=%s — %s", job_id, e, exc_info=True)
        return False


async def update_job_status(
    *,
    job_id: str,
    status: str,
    datalab_request_id: str = "",
    datalab_check_url: str = "",
    error_detail: str = "",
) -> bool:
    """Update job status and optional metadata."""
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE ocr_jobs SET
                    status = $2,
                    datalab_request_id = COALESCE(NULLIF($3, ''), datalab_request_id),
                    datalab_check_url = COALESCE(NULLIF($4, ''), datalab_check_url),
                    error_detail = COALESCE(NULLIF($5, ''), error_detail),
                    updated_at = NOW(),
                    completed_at = CASE WHEN $2 IN ('completed','failed') THEN NOW() ELSE NULL END
                WHERE job_id = $1
                """,
                job_id, status, datalab_request_id, datalab_check_url, error_detail,
            )
        logger.info("update_job_status: job=%s → status=%s", job_id, status)
        return True
    except Exception as e:
        logger.error("update_job_status: FAILED for job=%s — %s", job_id, e, exc_info=True)
        return False


async def get_stuck_jobs(minutes: int = 15) -> list[dict]:
    """Return jobs stuck in 'submitted' or 'collecting' for longer than `minutes`."""
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT job_id, status, datalab_request_id, datalab_check_url,
                       file_name, file_path, created_at
                FROM ocr_jobs
                WHERE status IN ('submitted', 'collecting')
                  AND updated_at < NOW() - make_interval(mins => $1)
                ORDER BY updated_at ASC
                """,
                minutes,
            )
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error("get_stuck_jobs: FAILED — %s", e, exc_info=True)
        return []


async def get_incomplete_jobs() -> list[dict]:
    """Return all jobs not in 'completed' or 'failed' state (for startup reconciliation)."""
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT job_id, status, datalab_request_id, datalab_check_url,
                       file_name, file_path, created_at
                FROM ocr_jobs
                WHERE status NOT IN ('completed', 'failed')
                ORDER BY created_at ASC
                """
            )
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error("get_incomplete_jobs: FAILED — %s", e, exc_info=True)
        return []


# ── Corrections log (per-field edit audit trail) ─────────────────────────


async def init_corrections_log_table() -> None:
    """Create corrections_log table if not exists. Call once at startup."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS corrections_log (
                id BIGSERIAL PRIMARY KEY,
                job_id TEXT NOT NULL,
                field_label TEXT NOT NULL,
                original_value TEXT NOT NULL DEFAULT '',
                corrected_value TEXT NOT NULL DEFAULT '',
                pdf_name TEXT,
                edited_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_corr_log_label
            ON corrections_log (field_label)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_corr_log_time
            ON corrections_log (edited_at)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_corr_log_job
            ON corrections_log (job_id)
        """)


async def log_correction(
    *,
    job_id: str,
    field_label: str,
    original_value: str,
    corrected_value: str,
    pdf_name: str | None = None,
) -> bool:
    """Insert a row into corrections_log. Returns True on success."""
    pool = get_pool()
    if pool is None:
        logger.warning("log_correction: pool is None — skipping DB insert")
        return False
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO corrections_log
                    (job_id, field_label, original_value, corrected_value, pdf_name)
                VALUES ($1, $2, $3, $4, $5)
                """,
                job_id, field_label, original_value, corrected_value, pdf_name,
            )
        return True
    except Exception as e:
        logger.error("log_correction: FAILED — %s", e, exc_info=True)
        return False
