"""Datalab OCR client — sends PDF to Datalab /api/v1/extract for structured field extraction."""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

import httpx

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

        max_concurrent = int(os.environ.get("DATALAB_MAX_CONCURRENCY", "3"))
        self._api_semaphore = asyncio.Semaphore(max_concurrent)
        self._mode = os.environ.get("DATALAB_MODE", "balanced")

        from src.datalab_schema import EXTRACT_SCHEMA
        self._schema = EXTRACT_SCHEMA

    async def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
        pdf_data = await self._get_pdf_data(pdf_path, page_images)
        if pdf_data is None:
            return None, TokenUsage()

        async with self._api_semaphore:
            result = await self._call_extract_api(pdf_data)

        if not result:
            raise RuntimeError("Datalab extract returned empty result")

        from src.datalab_schema import convert_extract_response
        data = convert_extract_response(result)
        logger.info("Datalab extract: %d fields", len(data.get("fields", [])))
        return data, TokenUsage()

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

    async def _call_extract_api(self, pdf_data: bytes) -> dict | None:
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

                return await self._poll_result(check_url, headers)

            except Exception as e:
                logger.warning("Datalab API call failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        raise RuntimeError(f"Datalab API call failed after {max_retries} attempts.")

    async def _poll_result(self, check_url: str, headers: dict) -> dict | None:
        poll_interval = float(os.environ.get("DATALAB_POLL_INTERVAL", "2.0"))
        max_polls = int(os.environ.get("DATALAB_MAX_POLLS", "300"))

        async with httpx.AsyncClient(timeout=30.0) as client:
            for _ in range(max_polls):
                try:
                    resp = await client.get(check_url, headers=headers)
                    resp.raise_for_status()
                    body = resp.json()

                    status = body.get("status", "processing")
                    if status == "complete":
                        if body.get("success"):
                            return body
                        else:
                            raise RuntimeError(f"Datalab processing failed: {body.get('error', 'unknown')}")
                    elif status == "failed":
                        raise RuntimeError(f"Datalab processing failed: {body.get('error', 'unknown')}")

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        logger.warning("Datalab rate limited during poll, waiting 5s...")
                        await asyncio.sleep(5)
                        continue
                    raise

                await asyncio.sleep(poll_interval)

        raise RuntimeError(f"Datalab polling timed out after {max_polls * poll_interval:.0f}s")
