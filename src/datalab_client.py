"""Datalab OCR client — sends PDF to Datalab /api/v1/extract for structured field extraction.

Now supports two modes:
1. extract_structured() — full submit + poll (backward compat)
2. submit() + collect() — split for webhook-style async

Features:
- Token-bucket rate limiter for strict RPM adherence (configurable via DATALAB_RPM)
- Separate semaphores for submit (DATALAB_SUBMIT_CONCURRENCY) and collect (DATALAB_COLLECT_CONCURRENCY)
- Adaptive polling backoff: 10s (0-30s) → 10s (30-90s) → 15s (90-180s) → 20s (180s+)
- Configurable timeout (DATALAB_COLLECT_TIMEOUT)
- 30s initial delay before first poll (typical Datalab processing time — avoids wasting RPM)
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


class TokenBucket:
    """Async token-bucket rate limiter.

    Smooths request rate to stay within a per-minute limit.
    Allows bursting up to `capacity`, then refills at `capacity / 60` tokens/sec.

    Usage:
        bucket = TokenBucket(capacity=10)  # 10 RPM, burst=10
        await bucket.acquire()             # blocks until a token is available
    """

    def __init__(self, capacity: float, refill_interval_secs: float = 60.0):
        self.capacity = capacity
        self.refill_rate = capacity / refill_interval_secs  # tokens per second
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        """Acquire *tokens* from the bucket, blocking until available."""
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
                self._last_refill = now

                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return

            # Not enough tokens — sleep until roughly enough refill time passes
            need = tokens - self._tokens
            wait = need / self.refill_rate if self.refill_rate > 0 else 1.0
            await asyncio.sleep(min(wait, 1.0))


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

        # Token-bucket rate limiter — shared across submit + collect
        def _env(key: str, default: str) -> str:
            """Read env var and strip inline comments."""
            return os.environ.get(key, default).split("#")[0].strip()

        def _int_env(key: str, default: str) -> int:
            return int(_env(key, default))

        def _float_env(key: str, default: str) -> float:
            return float(_env(key, default))

        rpm = _int_env("DATALAB_RPM", "10")
        burst = _int_env("DATALAB_BURST", str(rpm))
        self._rate_limiter = TokenBucket(capacity=burst, refill_interval_secs=60.0)
        # Override refill rate to match RPM exactly
        self._rate_limiter.refill_rate = rpm / 60.0

        # Separate semaphores for submit and collect phases
        # Defaults to 5 — matches Free tier concurrent request limit
        submit_conc = _int_env("DATALAB_SUBMIT_CONCURRENCY", "5")
        collect_conc = _int_env("DATALAB_COLLECT_CONCURRENCY", "5")
        self._submit_semaphore = asyncio.Semaphore(submit_conc)
        self._collect_semaphore = asyncio.Semaphore(collect_conc)

        # Legacy semaphore for backward compat extract_structured()
        max_concurrent = _int_env("DATALAB_MAX_CONCURRENCY", "3")
        self._api_semaphore = asyncio.Semaphore(max_concurrent)

        self._mode = _env("DATALAB_MODE", "balanced")
        self._collect_timeout = _float_env("DATALAB_COLLECT_TIMEOUT", "1200")
        self._initial_poll_delay = _float_env("DATALAB_INITIAL_POLL_DELAY", "30")

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

        Rate-limited by DATALAB_SUBMIT_CONCURRENCY (default 5) and DATALAB_RPM (default 10).
        """
        async with self._submit_semaphore:
            return await self._do_submit(pdf_data)

    async def _do_submit(self, pdf_data: bytes) -> DatalabJob | None:
        submit_url = f"{self.base_url}/extract"
        headers = {"X-API-Key": self.api_key}

        max_retries = 3
        for attempt in range(max_retries):
            try:
                await self._rate_limiter.acquire()
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
        - Rate-limited by DATALAB_COLLECT_CONCURRENCY (default 5) and DATALAB_RPM (default 10)
        - 30s initial delay (DATALAB_INITIAL_POLL_DELAY) before first poll — avoids burning RPM
        - Adaptive backoff: 10s (0-30s) → 10s (30-90s) → 15s (90-180s) → 20s (180s+)
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

        # Wait for initial processing before wasting a poll
        initial_delay = self._initial_poll_delay
        if initial_delay > 0:
            logger.debug("Datalab waiting initial %.0fs before polling %s", initial_delay, job.request_id)
            await asyncio.sleep(initial_delay)

        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                elapsed = time.monotonic() - t_start
                if elapsed >= timeout:
                    raise RuntimeError(
                        f"Datalab collect timed out after {timeout:.0f}s for {job.request_id}"
                    )

                # Adaptive polling interval — starts higher to conserve RPM
                if elapsed < 30:
                    interval = 10.0
                elif elapsed < 90:
                    interval = 10.0
                elif elapsed < 180:
                    interval = 15.0
                else:
                    interval = 20.0

                try:
                    await self._rate_limiter.acquire()
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
