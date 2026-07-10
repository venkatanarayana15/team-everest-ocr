"""PostgreSQL/Supabase database module — writes to ocr_documents table."""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")
POOL_MIN_SIZE = int(os.getenv("DATABASE_POOL_MIN_SIZE", "2"))
POOL_MAX_SIZE = int(os.getenv("DATABASE_POOL_MAX_SIZE", "10"))
POOL_CONNECT_TIMEOUT = float(os.getenv("DATABASE_CONNECT_TIMEOUT", "10"))

_pool: Optional[asyncpg.Pool] = None

# ── Field label → database column mapping ──────────────────────────────────

FIELD_TO_COLUMN: dict[str, str] = {
    "Volunteer Name": "volunteer_name",
    "Co-Volunteer Name": "co_volunteer_name",
    "Date of Visit": "date_of_visit",
    "1.1 Application ID": "application_id",
    "1.2 Student Full Name": "student_full_name",
    "1.3 Gender": "gender",
    "2.1 Family Status": "family_status",
    "2.2 Relationship Details — Year of Death / Separation": "relationship_death_year",
    "2.2 Relationship Details — Reason for Death / Separation": "relationship_death_reason",
    "2.3 Is Father/Mother photograph kept at home?": "photograph_kept_at_home",
    "2.4 Government ID Verified": "government_id_verified",
    "3.1 House Ownership": "house_ownership",
    "3.1.1 If rented, what is the rent amount?": "rent_amount",
    "3.2 Type of Home": "type_of_home",
    "3.3 Type of Ceiling": "type_of_ceiling",
    "3.4 Number of Bedrooms": "number_of_bedrooms",
    "3.4.1 Type of Bedroom": "type_of_bedroom",
    "3.5 Bathroom": "bathroom",
    "3.6 Kitchen Type": "kitchen_type",
    "4.1 Assets at Home": "assets_at_home",
    "4.2 Amount of Last Electricity Bill": "last_electricity_bill_amount",
    "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student?": "owns_other_assets",
    "4.3.1": "other_assets_details",
    "4.4 Apart from your job, is there any other source of income?": "has_other_income",
    "4.4.1": "other_income_sources",
    "4.5 Income Type": "income_type",
    "4.6 Do you have any loans?": "has_loans",
    "4.6.1": "loan_details",
    "4.7 If you choose any college, how much is the college fee?": "college_fee",
    "4.8 If the college fee is higher, how will you manage it?": "manage_higher_fee",
    "4.9 If you do not receive this scholarship, how will you pay the fees?": "manage_without_scholarship",
    "5.1 Does the student have any health issues?": "has_health_issues",
    "5.2 If yes, list the health issues": "health_issues_description",
    "6.1 Will you study college for three years without any obstacle?": "study_commitment",
    "6.2 If we have a training program within 15 km from your home, can you come?": "training_program_availability",
    "6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)?": "ready_for_skill_classes",
    "7.1 Has the student received or applied for any other scholarships for their UG degree?": "other_scholarships",
    "8.1 What is your opinion about the student, their family members, and their living condition?": "volunteer_opinion",
    "8.2 Will you recommend this student for this scholarship?": "recommend_student",
    "8.3 Any other comments you want to share?": "volunteer_comments",
}

BOOLEAN_COLUMNS: set[str] = {
    "photograph_kept_at_home",
    "owns_other_assets",
    "has_other_income",
    "has_loans",
    "has_health_issues",
    "ready_for_skill_classes",
}

JSONB_ARRAY_COLUMNS: set[str] = {
    "type_of_home",
    "type_of_ceiling",
    "kitchen_type",
    "assets_at_home",
    "government_id_verified",
}

TABLE_PARENT_COLUMNS: dict[str, str] = {
    "2.5 Family Members": "family_members",
    "4.3.1": "other_assets_details",
    "4.4.1": "other_income_sources",
    "4.6.1": "loan_details",
}

_ROW_RE = re.compile(r"^(.*?)\s*—\s*Row\s+\d+\s*—\s*(.*)$")


def _extract_structured_fields(fields: list[dict]) -> dict[str, Any]:
    """Map the fields array from result_json into structured DB columns."""
    out: dict[str, Any] = {}
    label_map: dict[str, str] = {}
    table_rows: dict[str, dict[int, dict[str, str]]] = {}

    def _is_checked(value: str | None) -> bool:
        if not isinstance(value, str):
            return False
        return value.strip().lower() in ("\u2713", "1", "yes", "true", "y")

    for f in fields:
        label = f.get("label", "")
        value = f.get("value", "")
        label_map[label] = value

        row_match = _ROW_RE.match(label)
        if row_match:
            parent_label = row_match.group(1).strip()
            column_name = row_match.group(2).strip()
            if parent_label in TABLE_PARENT_COLUMNS:
                table_col = TABLE_PARENT_COLUMNS[parent_label]
                table_rows.setdefault(table_col, {})
                row_num_match = re.search(r"Row\s+(\d+)", label)
                if row_num_match:
                    row_num = int(row_num_match.group(1))
                    table_rows[table_col].setdefault(row_num, {})
                    table_rows[table_col][row_num][column_name] = value

    for label, col in FIELD_TO_COLUMN.items():
        val = label_map.get(label)

        if col in JSONB_ARRAY_COLUMNS:
            prefix = label + " \u2014 "
            checked = []
            for flabel, fval in label_map.items():
                if flabel.startswith(prefix):
                    option = flabel[len(prefix):]
                    if option and fval.strip():
                        lower_val = fval.strip().lower()
                        if lower_val in ("\u2713", "1", "yes", "true", "y"):
                            checked.append(option)
                        elif lower_val not in (
                            "\u2717", "no", "false", "0", "", "n/a", "\u2014", "-", "nil", "none",
                        ):
                            checked.append(fval.strip())
            if checked:
                out[col] = json.dumps(sorted(checked))
            elif val is not None:
                items = [x.strip() for x in val.split(",") if x.strip()]
                out[col] = json.dumps(items)
            else:
                out[col] = json.dumps([])
            continue

        if val is None:
            continue
        if col in BOOLEAN_COLUMNS:
            norm = val.strip().lower()
            if not norm:
                continue
            out[col] = norm in ("yes", "true", "1", "y")
        elif col not in TABLE_PARENT_COLUMNS.values():
            out[col] = val

    for col, rows in table_rows.items():
        sorted_rows = [
            {k: rows[row_num].get(k, "") for k in sorted(rows[row_num].keys())}
            for row_num in sorted(rows.keys())
        ]
        out[col] = json.dumps(sorted_rows)

    # Derive House Ownership from split checkbox fields (3.1)
    own_label = "3.1 House Ownership — Own"
    rent_label = "3.1 House Ownership — Rented"
    own_checked = _is_checked(label_map.get(own_label))
    rent_checked = _is_checked(label_map.get(rent_label))
    if "house_ownership" not in out:
        if own_checked ^ rent_checked:
            out["house_ownership"] = "Own" if own_checked else "Rented"
        elif own_checked and rent_checked:
            out["house_ownership"] = "Own"

    # Derive Type of Bedroom from split checkbox fields (3.4.1)
    bed_sep_label = "3.4.1 Type of Bedroom — Separate Bedroom"
    bed_no_label = "3.4.1 Type of Bedroom — No Separate Bedroom"
    bed_sep_checked = _is_checked(label_map.get(bed_sep_label))
    bed_no_checked = _is_checked(label_map.get(bed_no_label))
    if "type_of_bedroom" not in out:
        if bed_sep_checked ^ bed_no_checked:
            out["type_of_bedroom"] = "Separate Bedroom" if bed_sep_checked else "No Separate Bedroom"
        elif bed_sep_checked and bed_no_checked:
            out["type_of_bedroom"] = "Separate Bedroom"

    # Derive bathroom string from split checkbox fields (3.5)
    bath_sep_label = "3.5 Bathroom — Separate"
    bath_common_label = "3.5 Bathroom — Common for Apartment"
    bath_sep_checked = _is_checked(label_map.get(bath_sep_label))
    bath_common_checked = _is_checked(label_map.get(bath_common_label))
    if "bathroom" not in out:
        if bath_sep_checked ^ bath_common_checked:
            out["bathroom"] = "Separate" if bath_sep_checked else "Common for Apartment"
        elif bath_sep_checked and bath_common_checked:
            out["bathroom"] = "Separate"

    # Derive photograph_kept_at_home boolean from split checkbox fields (2.3)
    photo_yes_label = "2.3 Is Father/Mother photograph kept at home? — Yes"
    photo_no_label = "2.3 Is Father/Mother photograph kept at home? — No"
    photo_yes_checked = _is_checked(label_map.get(photo_yes_label))
    photo_no_checked = _is_checked(label_map.get(photo_no_label))
    if "photograph_kept_at_home" not in out:
        if photo_yes_checked ^ photo_no_checked:
            out["photograph_kept_at_home"] = photo_yes_checked
        elif photo_yes_checked and photo_no_checked:
            out["photograph_kept_at_home"] = True

    # Derive owns_other_assets boolean from split checkbox fields (4.3)
    assets_yes_label = (
        "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes"
    )
    assets_no_label = (
        "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — No"
    )
    assets_yes_checked = _is_checked(label_map.get(assets_yes_label))
    assets_no_checked = _is_checked(label_map.get(assets_no_label))
    if "owns_other_assets" not in out:
        if assets_yes_checked ^ assets_no_checked:
            out["owns_other_assets"] = assets_yes_checked
        elif assets_yes_checked and assets_no_checked:
            out["owns_other_assets"] = True

    # Derive has_other_income boolean from split checkbox fields (4.4)
    income_yes_label = "4.4 Apart from your job, is there any other source of income? — Yes"
    income_no_label = "4.4 Apart from your job, is there any other source of income? — No"
    income_yes_checked = _is_checked(label_map.get(income_yes_label))
    income_no_checked = _is_checked(label_map.get(income_no_label))
    if "has_other_income" not in out:
        if income_yes_checked ^ income_no_checked:
            out["has_other_income"] = income_yes_checked
        elif income_yes_checked and income_no_checked:
            out["has_other_income"] = True

    # Derive has_health_issues boolean from split checkbox fields (5.1)
    health_yes_label = "5.1 Does the student have any health issues? — Yes"
    health_no_label = "5.1 Does the student have any health issues? — No"
    health_yes_checked = _is_checked(label_map.get(health_yes_label))
    health_no_checked = _is_checked(label_map.get(health_no_label))
    if "has_health_issues" not in out:
        if health_yes_checked ^ health_no_checked:
            out["has_health_issues"] = health_yes_checked
        elif health_yes_checked and health_no_checked:
            out["has_health_issues"] = True

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
    file_hash: Optional[str] = None,
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

    if file_hash is not None:
        data["file_hash"] = file_hash
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

        raw_fields = rj.get("fields", [])
        if raw_fields:
            structured = _extract_structured_fields(raw_fields)
            for col, val in structured.items():
                if val is not None:
                    data[col] = val
            logger.info(
                "upsert_ocr_document: mapped %d structured columns from %d fields",
                len(structured), len(raw_fields),
            )

    logger.debug(
        "Upsert payload columns: %s (values omitted for PII safety)",
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

    logger.info(
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


async def get_result_by_file_hash(file_hash: str) -> Optional[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ocr_documents WHERE file_hash = $1",
            file_hash,
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
            await conn.execute(
                """
                INSERT INTO ocr_jobs (job_id, file_name, status, file_hash, file_path)
                VALUES ($1, $2, 'submitted', $3, $4)
                ON CONFLICT (job_id) DO NOTHING
                """,
                job_id, file_name, file_hash, file_path,
            )
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
