"""PostgreSQL/Supabase database module — writes to ocr_documents table."""

import asyncio
import json
import logging
import os
import re
from typing import Any, Optional

import asyncpg
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

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
    "4.3.1 If yes, list their properties": "other_assets_details",
    "4.4 Apart from your job, is there any other source of income?": "has_other_income",
    "4.4.1 If yes, list other sources of income": "other_income_sources",
    "4.5 Income Type": "income_type",
    "4.6 Do you have any loans?": "has_loans",
    "4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount": "loan_details",
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
}

TABLE_PARENT_COLUMNS: dict[str, str] = {
    "2.5 Family Members": "family_members",
    "4.3.1 If yes, list their properties": "other_assets_details",
    "4.4.1 If yes, list other sources of income": "other_income_sources",
    "4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount": "loan_details",
}

_ROW_RE = re.compile(r"^(.*?)\s*—\s*Row\s+\d+\s*—\s*(.*)$")


def _extract_structured_fields(fields: list[dict]) -> dict[str, Any]:
    """Map the fields array from result_json into structured DB columns."""
    out: dict[str, Any] = {}
    label_map: dict[str, str] = {}
    table_rows: dict[str, dict[int, dict[str, str]]] = {}

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
        if val is None:
            continue
        if col in BOOLEAN_COLUMNS:
            out[col] = val.strip().lower() in ("yes", "true", "1")
        elif col in JSONB_ARRAY_COLUMNS:
            items = [x.strip() for x in val.split(",") if x.strip()]
            out[col] = json.dumps(items)
        elif col not in TABLE_PARENT_COLUMNS.values():
            out[col] = val

    for col, rows in table_rows.items():
        sorted_rows = [
            {k: rows[row_num].get(k, "") for k in sorted(rows[row_num].keys())}
            for row_num in sorted(rows.keys())
        ]
        out[col] = json.dumps(sorted_rows)

    return out



async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        # asyncpg pools are tied to the event loop they were created on.
        # If we are running in a different loop (e.g. a worker-thread loop
        # created by _save_to_db), the cached pool is unusable — recreate it.
        try:
            running = asyncio.get_running_loop()
            pool_loop = getattr(_pool, "_loop", None)
            if pool_loop is not None and pool_loop is not running:
                logger.debug("get_pool: stale pool (different event loop) — recreating")
                try:
                    await _pool.close()
                except Exception:
                    pass
                _pool = None
        except RuntimeError:
            pass  # no running loop — unusual, ignore
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is not set. Add it to .env — get it from "
                "Supabase Dashboard → Project Settings → Database → "
                "Connection string (Transaction pooler, port 6543)."
            )
        logger.info("get_pool: creating new asyncpg pool (dsn length=%d)", len(DATABASE_URL))
        _pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=1,
            max_size=5,
            statement_cache_size=0,  # required for Supabase transaction pooler
        )
        logger.info("get_pool: pool created OK")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


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
    Insert a row into ocr_documents.
    Structured field columns are auto-populated from result_json.fields.
    Returns the new row uuid as str, or "" if the insert was skipped/failed.
    """
    logger.info(
        "upsert_ocr_document: START — job=%s file=%r status=%s",
        job_id, file_name, status,
    )

    pool = await get_pool()

    data: dict[str, Any] = {
        "file_name": file_name,
        "status": status,
    }

    if processing_time is not None:
        data["processing_time"] = processing_time
    if confidence_score is not None:
        data["confidence_score"] = confidence_score
    if num_pdfs is not None:
        data["num_pdfs"] = num_pdfs
    if result_json is not None:
        # Embed job_id so get_result_by_job_id can look up this row later
        rj = dict(result_json)
        rj["job_id"] = job_id
        data["result_json"] = json.dumps(rj)

        # Populate structured columns from extracted fields
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

    cols = list(data.keys())
    placeholders = [f"${i + 1}" for i in range(len(cols))]
    values = list(data.values())

    sql = (
        f"INSERT INTO ocr_documents ({', '.join(cols)}) "
        f"VALUES ({', '.join(placeholders)}) "
        f"RETURNING id"
    )

    logger.info(
        "upsert_ocr_document: inserting %d columns: %s",
        len(cols), cols,
    )
    logger.debug("upsert_ocr_document: SQL = %s", sql)

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, *values)
    except Exception as exc:
        logger.error(
            "upsert_ocr_document: INSERT FAILED for job=%s — %s",
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


# ── Legacy shims (keep existing imports in server.py working) ────────────────

async def insert_pdf(
    filename: str, file_size: int, file_path: str
) -> str:
    logger.info("insert_pdf: file=%r size=%d", filename, file_size)
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO ocr_documents
                   (file_name, file_size, file_path, status)
                   VALUES ($1, $2, $3, 'pending')
                   RETURNING id""",
                filename, file_size, file_path,
            )
            doc_id = str(row["id"]) if row else ""
            logger.info("insert_pdf: created pending row id=%s", doc_id)
            return doc_id
    except Exception as exc:
        logger.error("insert_pdf: FAILED — %s", exc, exc_info=True)
        return ""


async def list_pdfs(limit: int = 50) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, file_name, file_size, status,
                      confidence_score, created_at, processed_at
               FROM ocr_documents
               ORDER BY created_at DESC LIMIT $1""",
            limit,
        )
        return [dict(r) for r in rows]


async def insert_extraction_result(*args, **kwargs) -> None:
    logger.debug("insert_extraction_result deprecated; use upsert_ocr_document")


async def insert_extracted_fields(*args, **kwargs) -> None:
    logger.debug("insert_extracted_fields deprecated; use upsert_ocr_document")


async def update_extraction_result(job_id: str, status: str = "done", **kwargs) -> None:
    logger.debug("update_extraction_result: job_id=%s status=%s (no-op shim)", job_id, status)


async def get_result_by_job_id(job_id: str) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ocr_documents WHERE result_json->>'job_id' = $1",
            job_id,
        )
        return dict(row) if row else None


async def get_last_job_id_by_pdf_id(pdf_id: str) -> Optional[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT result_json->>'job_id' AS job_id "
            "FROM ocr_documents WHERE id = $1::uuid",
            pdf_id,
        )
        return row["job_id"] if row else None
