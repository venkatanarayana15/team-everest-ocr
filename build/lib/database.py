"""PostgreSQL/Supabase database module — writes to ocr_documents table."""

import asyncio
import json
import logging
import os
from typing import Any, Optional

import asyncpg
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

_pool: Optional[asyncpg.Pool] = None


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
    file_size: Optional[int] = None,
    file_path: Optional[str] = None,
    status: str = "done",
    processing_time: Optional[float] = None,
    confidence_score: Optional[float] = None,
    num_pages: Optional[int] = None,
    raw_text: Optional[str] = None,
    result_json: Optional[dict] = None,
    primary_model: Optional[str] = None,
    secondary_model: Optional[str] = None,
    token_usage: Optional[dict] = None,
    error_message: Optional[str] = None,
) -> str:
    """
    Insert a row into ocr_documents.

    Only metadata columns (file_name, status, result_json, etc.) are written —
    these are guaranteed to exist in the table regardless of schema version.
    The full extraction result (all fields + values) lives inside result_json.
    Returns the new row uuid as str, or "" if the insert was skipped/failed.
    """
    logger.info(
        "upsert_ocr_document: START — job=%s file=%r status=%s",
        job_id, file_name, status,
    )

    pool = await get_pool()

    # ── Build the column → value dict ─────────────────────────────────────────
    data: dict[str, Any] = {
        "file_name": file_name,
        "status": status,
    }

    if file_size is not None:
        data["file_size"] = file_size
    if file_path is not None:
        data["file_path"] = file_path
    if processing_time is not None:
        data["processing_time"] = processing_time
    if confidence_score is not None:
        data["confidence_score"] = confidence_score
    if num_pages is not None:
        data["num_pages"] = num_pages
    if raw_text is not None:
        data["raw_text"] = raw_text
    if result_json is not None:
        # Embed job_id so get_result_by_job_id can look up this row later
        rj = dict(result_json)
        rj["job_id"] = job_id
        data["result_json"] = json.dumps(rj)
    if primary_model is not None:
        data["primary_model"] = primary_model
    if secondary_model is not None:
        data["secondary_model"] = secondary_model
    if token_usage is not None:
        data["token_usage"] = json.dumps(token_usage)
    if error_message is not None:
        data["error_message"] = error_message

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
