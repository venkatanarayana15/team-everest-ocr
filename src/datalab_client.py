"""Datalab OCR client — sends PDF to Datalab /api/v1/extract for structured field extraction.

Now supports two modes:
1. extract_structured() — full submit + poll (backward compat)
2. submit() + collect() — split for webhook-style async

Features:
- Separate semaphores for submit (DATALAB_SUBMIT_CONCURRENCY) and collect (DATALAB_COLLECT_CONCURRENCY)
- Adaptive polling backoff: 2s → 5s → 10s → 15s based on elapsed time
- Configurable timeout (DATALAB_COLLECT_TIMEOUT)
- Reduced log noise: only logs state changes or every 30s
"""

import asyncio
import json
import logging
import os
import time
import tempfile
from pathlib import Path

import httpx

from src.datalab_schema import DatalabJob
from src.model_client import ModelClient, TokenUsage

logger = logging.getLogger(__name__)


class DatalabOcrClient(ModelClient):
    """OCR client for the Datalab API.

    Sends the PDF to POST /api/v1/extract with a predefined questionnaire schema
    and returns structured fields directly — no text LLM post-processing needed.
    """

    @property
    def needs_images(self) -> bool:
        return False

    def __init__(self, api_key: str, model: str = "chandra-ocr-2", base_url: str = "https://www.datalab.to/api/v1"):
        self.api_key = api_key
        self.model_name = model
        self.base_url = base_url.rstrip("/")
        self.provider = "datalab"

        # Separate semaphores for submit and collect phases
        submit_conc = int(os.environ.get("DATALAB_SUBMIT_CONCURRENCY", "10"))
        collect_conc = int(os.environ.get("DATALAB_COLLECT_CONCURRENCY", "10"))
        self._submit_semaphore = asyncio.Semaphore(submit_conc)
        self._collect_semaphore = asyncio.Semaphore(collect_conc)

        # Legacy semaphore for backward compat extract_structured()
        max_concurrent = int(os.environ.get("DATALAB_MAX_CONCURRENCY", "3"))
        self._api_semaphore = asyncio.Semaphore(max_concurrent)

        self._mode = os.environ.get("DATALAB_MODE", "balanced")
        self._collect_timeout = float(os.environ.get("DATALAB_COLLECT_TIMEOUT", "1200"))  # 20 min default

        from src.datalab_schema import EXTRACT_SCHEMA
        self._schema = EXTRACT_SCHEMA

    async def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
        """Full submit + poll (backward compatible)."""
        pdf_data = await self._get_pdf_data(pdf_path, page_images)
        if pdf_data is None:
            return None, TokenUsage()

        async with self._api_semaphore:
            job = await self.submit(pdf_data)
            if job is None:
                raise RuntimeError("Datalab submit failed")
            result = await self.collect(job)

        if not result:
            raise RuntimeError("Datalab extract returned empty result")

        from src.datalab_schema import convert_extract_response
        data = convert_extract_response(result)
        logger.info("Datalab extract: %d fields", len(data.get("fields", [])))
        return data, TokenUsage()

    async def submit(self, pdf_data: bytes) -> DatalabJob | None:
        """Submit PDF to Datalab and return a DatalabJob immediately (no polling).

        Rate-limited by DATALAB_SUBMIT_CONCURRENCY (default 10).
        """
        async with self._submit_semaphore:
            return await self._do_submit(pdf_data)

    async def _do_submit(self, pdf_data: bytes) -> DatalabJob | None:
        submit_url = f"{self.base_url}/extract"
        headers = {"X-API-Key": self.api_key}

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(
                        submit_url,
                        headers=headers,
                        files={"file": ("document.pdf", pdf_data, "application/pdf")},
                        data={
                            "page_schema": json.dumps(self._schema),
                            "mode": self._mode,
                        },
                        timeout=120.0,
                    )
                    resp.raise_for_status()
                    body = resp.json()

                if not body.get("success"):
                    raise RuntimeError(f"Datalab submit failed: {body}")

                request_id = body["request_id"]
                check_url = body.get("request_check_url") or f"{submit_url}/{request_id}"

                logger.info("Datalab submit OK: request_id=%s", request_id)
                return DatalabJob(request_id=request_id, check_url=check_url)

            except Exception as e:
                logger.warning("Datalab submit failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        logger.error("Datalab submit failed after %d attempts", max_retries)
        return None

    async def collect(self, job: DatalabJob) -> dict | None:
        """Poll a submitted DatalabJob until complete.

        Features:
        - Rate-limited by DATALAB_COLLECT_CONCURRENCY (default 10)
        - Adaptive backoff: 2s (0-30s) → 5s (30-90s) → 10s (90-180s) → 15s (180s+)
        - Timeout = DATALAB_COLLECT_TIMEOUT (default 1200s / 20 min)
        - Logs only state changes or every 30s during long polls
        """
        async with self._collect_semaphore:
            return await self._do_collect(job)

    async def _do_collect(self, job: DatalabJob) -> dict | None:
        headers = {"X-API-Key": self.api_key}
        timeout = self._collect_timeout
        t_start = time.monotonic()
        last_log_ts = 0.0
        log_interval = 30.0

        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                elapsed = time.monotonic() - t_start
                if elapsed >= timeout:
                    raise RuntimeError(
                        f"Datalab collect timed out after {timeout:.0f}s for {job.request_id}"
                    )

                # Adaptive polling interval based on elapsed time
                if elapsed < 30:
                    interval = 2.0
                elif elapsed < 90:
                    interval = 5.0
                elif elapsed < 180:
                    interval = 10.0
                else:
                    interval = 15.0

                try:
                    resp = await client.get(job.check_url, headers=headers)
                    resp.raise_for_status()
                    body = resp.json()

                    status = body.get("status", "processing")

                    if status == "complete":
                        if body.get("success"):
                            logger.info("Datalab collect OK: request_id=%s (elapsed=%.1fs)", job.request_id, elapsed)
                            return body
                        else:
                            raise RuntimeError(f"Datalab processing failed: {body.get('error', 'unknown')}")
                    elif status == "failed":
                        raise RuntimeError(f"Datalab processing failed: {body.get('error', 'unknown')}")

                    # Log periodically during long polls
                    if elapsed - last_log_ts >= log_interval:
                        logger.info("Datalab collecting: request_id=%s elapsed=%.1fs interval=%.0fs", job.request_id, elapsed, interval)
                        last_log_ts = elapsed

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        logger.warning("Datalab rate limited during poll for %s, waiting 5s", job.request_id)
                        await asyncio.sleep(5)
                        continue
                    raise

                await asyncio.sleep(interval)

    async def _get_pdf_data(self, pdf_path: str, page_images: dict[int, str]) -> bytes | None:
        if pdf_path and Path(pdf_path).exists():
            with open(pdf_path, "rb") as f:
                return f.read()

        if not page_images:
            logger.error("No PDF path and no page images available")
            return None

        try:
            import fitz
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp_path = tmp.name
            tmp.close()
            doc = fitz.open()
            for p in sorted(page_images):
                page = doc.new_page(width=612, height=792)
                page.insert_image(page.rect, filename=page_images[p])
            doc.save(tmp_path)
            doc.close()
            with open(tmp_path, "rb") as f:
                data = f.read()
            Path(tmp_path).unlink(missing_ok=True)
            return data
        except ImportError:
            logger.error("pymupdf required to create temp PDF from page images")
            return None
        except Exception as e:
            logger.error("Failed to create temp PDF: %s", e)
            return None
