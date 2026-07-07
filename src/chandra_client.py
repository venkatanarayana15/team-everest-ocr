"""Chandra-2 OCR client — sends PDF to OCR API, then post-processes with a text-only LLM."""

import asyncio
import json
import logging
import os
import tempfile
import urllib.request
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


from src.model_client import ModelClient, TokenUsage


class ChandraOcrClient(ModelClient):
    """OCR client for the Chandra-2 API.

    1. Sends the full PDF to POST /v1/ocr → gets markdown text.
    2. Post-processes the markdown through a text-only LLM to extract structured fields.
    """

    @property
    def needs_images(self) -> bool:
        return False

    def __init__(self, api_key: str, model: str = "chandra-2", base_url: str = "https://ocr.teameverest.ngo/v1/ocr"):
        self.api_key = api_key
        self.model_name = model
        self.base_url = base_url.rstrip("/")
        self.provider = "chandra-2"

        max_concurrent = int(os.environ.get("CHANDRA_MAX_CONCURRENCY", "3"))
        self._api_semaphore = asyncio.Semaphore(max_concurrent)

        # Post-processing text LLM config
        self.text_api_key = os.environ.get("CHANDRA_TEXT_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        self.text_model = os.environ.get("CHANDRA_TEXT_MODEL", "gpt-4o-mini")
        self.text_base_url = os.environ.get("CHANDRA_TEXT_BASE_URL", "https://api.openai.com/v1")

    async def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
        if not self.text_api_key:
            logger.error("CHANDRA_TEXT_API_KEY not set — cannot post-process OCR output")
            return None, TokenUsage()

        pdf_data = await self._get_pdf_data(pdf_path, page_images)
        if pdf_data is None:
            return None, TokenUsage()

        async with self._api_semaphore:
            markdown = await self._call_ocr_api(pdf_data)
        if not markdown:
            logger.error("Chandra OCR returned empty text")
            raise RuntimeError("Chandra OCR returned empty text")

        logger.info("Chandra OCR: %d chars received", len(markdown))

        modified_prompt = (
            f"Below is OCR-extracted text from the Home Visit Questionnaire.\n"
            f"Use this text to extract the fields as instructed.\n\n"
            f"--- OCR TEXT ---\n{markdown}\n\n"
            f"--- EXTRACTION INSTRUCTIONS ---\n"
            f"{prompt}"
        )

        from src.model_client import OpenAICompatibleClient
        text_client = OpenAICompatibleClient(
            api_key=self.text_api_key,
            model=self.text_model,
            base_url=self.text_base_url,
            provider="openai",
        )

        data, token_usage = await text_client.extract_structured("", {}, modified_prompt)

        if data and isinstance(data, dict):
            data["raw_text"] = markdown

        logger.info("Post-processing complete: %d fields (tokens: %s)", len(data.get("fields", [])) if data else 0, token_usage)
        return data, token_usage

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

    async def _call_ocr_api(self, pdf_data: bytes) -> str:
        boundary = uuid.uuid4().hex

        def build_multipart() -> bytes:
            body = b""
            for name, value, filename in [
                ("model_name", self.model_name.encode(), None),
                ("api_key", self.api_key.encode(), None),
                ("file", pdf_data, "document.pdf"),
            ]:
                body += f"--{boundary}\r\n".encode()
                if filename:
                    body += f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
                    body += b"Content-Type: application/pdf\r\n"
                else:
                    body += f'Content-Disposition: form-data; name="{name}"\r\n'.encode()
                body += b"\r\n"
                body += value if isinstance(value, bytes) else value
                body += b"\r\n"
            body += f"--{boundary}--\r\n".encode()
            return body

        data = await asyncio.get_running_loop().run_in_executor(None, build_multipart)

        req = urllib.request.Request(
            self.base_url,
            data=data,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "ChandraClient/1.0"
            },
        )

        max_retries = 2
        for attempt in range(max_retries):
            try:
                resp_data = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: urllib.request.urlopen(req, timeout=300).read()
                )
                resp = json.loads(resp_data.decode())
                return resp.get("markdown", "") or ""
            except Exception as e:
                logger.warning("Chandra OCR API call failed (attempt %d/%d): %s", attempt + 1, max_retries, e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
        raise RuntimeError(f"Chandra OCR API call failed after {max_retries} attempts.")
