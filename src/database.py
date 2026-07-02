"""PostgreSQL database module for OCR extraction results."""

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

import asyncpg
from dotenv import load_dotenv

from src.extraction_pipeline import StructuredField

logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        kwargs = {
            "host": os.getenv("PGHOST", "localhost"),
            "port": os.getenv("PGPORT", "5432"),
            "database": "ocr_extract",
            "user": os.getenv("PGUSER", "priya"),
            "password": os.getenv("PGPASSWORD", ""),
            "min_size": 2,
            "max_size": 10,
        }
        if DATABASE_URL:
            kwargs["dsn"] = DATABASE_URL
        _pool = await asyncpg.create_pool(**kwargs)
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def compute_file_hash(file_path: str) -> str:
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha.update(chunk)
    return sha.hexdigest()


async def find_pdf_by_hash(file_hash: str) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, filename, file_path, uploaded_at FROM pdfs WHERE file_hash = $1",
            file_hash,
        )
        return dict(row) if row else None


async def insert_pdf(
    filename: str, file_hash: str, file_size: int, file_path: str
) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO pdfs (filename, file_hash, file_size, file_path) "
            "VALUES ($1, $2, $3, $4) RETURNING id",
            filename, file_hash, file_size, file_path,
        )
        return row["id"]


async def insert_extraction_result(
    job_id: str,
    pdf_id: int,
    status: str,
    overall_confidence: int = 0,
    num_pages: int = 0,
    processing_time: float = 0.0,
    raw_text: str = "",
    primary_model: str = "",
    secondary_model: str = "",
    result_json: Optional[dict] = None,
    sections_json: Optional[list] = None,
) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO extraction_results
               (job_id, pdf_id, status, overall_confidence, num_pages,
                processing_time, raw_text, primary_model, secondary_model,
                result_json, sections_json)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
               RETURNING id""",
            job_id, pdf_id, status, overall_confidence, num_pages,
            processing_time, raw_text, primary_model, secondary_model,
            json.dumps(result_json) if result_json else None,
            json.dumps(sections_json) if sections_json else None,
        )
        return row["id"]


async def insert_extracted_fields(
    result_id: int, fields: list[StructuredField]
) -> int:
    pool = await get_pool()
    count = 0
    async with pool.acquire() as conn:
        for f in fields:
            await conn.execute(
                """INSERT INTO extracted_fields
                   (result_id, label, value, confidence, page, section_number,
                    bbox, value_bbox, needs_clarification, reason,
                    is_verified, extracted_by, verified_by, original_value)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)""",
                result_id, f.label, f.value, f.confidence, f.page,
                f.section_number,
                json.dumps(list(f.bbox)) if f.bbox else None,
                json.dumps(list(f.value_bbox)) if f.value_bbox else None,
                f.needs_clarification, f.reason,
                f.is_verified, f.extracted_by, f.verified_by,
                f.original_value,
            )
            count += 1
    return count


async def log_correction(
    result_id: int, label: str, original_value: str, corrected_value: str
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO corrections_log
               (result_id, label, original_value, corrected_value)
               VALUES ($1,$2,$3,$4)""",
            result_id, label, original_value, corrected_value,
        )
        await conn.execute(
            """UPDATE extracted_fields SET
               corrected_manually = TRUE,
               correction_count = correction_count + 1,
               original_value = $3,
               value = $4
               WHERE result_id = $1 AND label = $2""",
            result_id, label, original_value, corrected_value,
        )


async def list_pdfs(limit: int = 50) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT p.id, p.filename, p.file_hash, p.file_size,
                      p.uploaded_at,
                      e.job_id, e.status, e.overall_confidence
               FROM pdfs p
               LEFT JOIN LATERAL (
                   SELECT job_id, status, overall_confidence
                   FROM extraction_results
                   WHERE pdf_id = p.id
                   ORDER BY created_at DESC LIMIT 1
               ) e ON true
               ORDER BY p.uploaded_at DESC LIMIT $1""",
            limit,
        )
        return [dict(r) for r in rows]


async def get_pdf_by_id(pdf_id: int) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, filename, file_hash, file_size, file_path, uploaded_at "
            "FROM pdfs WHERE id = $1",
            pdf_id,
        )
        return dict(row) if row else None


async def get_last_job_id_by_pdf_id(pdf_id: int) -> Optional[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchval(
            "SELECT job_id FROM extraction_results WHERE pdf_id = $1 ORDER BY created_at DESC LIMIT 1",
            pdf_id,
        )
        return row


async def get_result_by_job_id(job_id: str) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT er.*, p.filename as pdf_filename
               FROM extraction_results er
               JOIN pdfs p ON p.id = er.pdf_id
               WHERE er.job_id = $1""",
            job_id,
        )
        return dict(row) if row else None


async def update_extraction_result(
    job_id: str,
    status: str = "done",
    overall_confidence: Optional[int] = None,
    processing_time: Optional[float] = None,
    raw_text: Optional[str] = None,
    result_json: Optional[dict] = None,
    sections_json: Optional[list] = None,
):
    pool = await get_pool()
    sets = ["status = $2", "updated_at = NOW()"]
    values = [job_id, status]
    idx = 3
    if overall_confidence is not None:
        sets.append(f"overall_confidence = ${idx}")
        values.append(overall_confidence)
        idx += 1
    if processing_time is not None:
        sets.append(f"processing_time = ${idx}")
        values.append(processing_time)
        idx += 1
    if raw_text is not None:
        sets.append(f"raw_text = ${idx}")
        values.append(raw_text)
        idx += 1
    if result_json is not None:
        sets.append(f"result_json = ${idx}")
        values.append(json.dumps(result_json))
        idx += 1
    if sections_json is not None:
        sets.append(f"sections_json = ${idx}")
        values.append(json.dumps(sections_json))
        idx += 1
    sets_str = ", ".join(sets)
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE extraction_results SET {sets_str} WHERE job_id = $1",
            *values,
        )
