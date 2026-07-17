import asyncio
import base64
import functools
import json
import logging
import os
import time
import random
from abc import ABC, abstractmethod



logger = logging.getLogger(__name__)

# Global semaphore that caps total concurrent LLM calls across ALL pipelines.
# This prevents LLM API overload regardless of how many pipelines are active.
_global_llm_semaphore = asyncio.Semaphore(
    int(os.environ.get("GLOBAL_LLM_MAX_CONCURRENCY", "24"))
)


class RateLimiter:
    """Sliding-window rate limiter with both sync and async wait."""

    def __init__(self, rpm: int | None = None, max_concurrency: int | None = None):
        self.rpm = rpm or int(os.environ.get("LLM_RATE_LIMIT_RPM", "15"))
        self.max_concurrency = max_concurrency or int(os.environ.get("LLM_MAX_CONCURRENCY", "2"))
        self._timestamps: list[float] = []
        self._semaphore = asyncio.Semaphore(self.max_concurrency)

    def wait(self) -> None:
        now = time.time()
        self._timestamps = [t for t in self._timestamps if now - t < 60]
        if len(self._timestamps) >= self.rpm:
            sleep_for = self._timestamps[0] + 60 - now
            if sleep_for > 0:
                logger.debug("Rate limit: sleeping %.1fs", sleep_for)
                time.sleep(sleep_for)
        self._timestamps.append(time.time())

    async def wait_async(self) -> None:
        now = time.time()
        self._timestamps = [t for t in self._timestamps if now - t < 60]
        if len(self._timestamps) >= self.rpm:
            sleep_for = self._timestamps[0] + 60 - now
            if sleep_for > 0:
                logger.debug("Rate limit: sleeping %.1fs", sleep_for)
                await asyncio.sleep(sleep_for)
        self._timestamps.append(time.time())


def _is_transient(e: Exception) -> bool:
    msg = str(e).lower()
    if hasattr(e, "status_code"):
        code = e.status_code
        if code == 429 or (500 <= code < 600):
            return True
    if hasattr(e, "code"):
        code = e.code
        if code == 429 or (isinstance(code, int) and 500 <= code < 600):
            return True
    if "429" in msg or "too many requests" in msg:
        return True
    if "rate_limit" in msg or "rate limit" in msg:
        return True
    if isinstance(e, (TimeoutError, ConnectionError)):
        return True
    if "timeout" in msg or "connection refused" in msg or "connection reset" in msg:
        return True
    return False


def call_with_retry(fn, max_retries: int | None = None, rl: RateLimiter | None = None):
    if rl:
        rl.wait()
    max_retries = max_retries if max_retries is not None else int(os.environ.get("LLM_MAX_RETRIES", "5"))
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if not _is_transient(e):
                raise
            if attempt == max_retries - 1:
                raise
            wait = (2**attempt) + random.uniform(0, 5)
            logger.warning(
                "Transient error (%s) attempt %d/%d. Waiting %.1fs...",
                type(e).__name__,
                attempt + 1,
                max_retries,
                wait,
            )
            time.sleep(wait)
    return None


async def call_with_retry_async(fn, max_retries: int | None = None, rl: RateLimiter | None = None):
    max_retries = max_retries if max_retries is not None else int(os.environ.get("LLM_MAX_RETRIES", "5"))
    for attempt in range(max_retries):
        try:
            async with _global_llm_semaphore:
                if rl:
                    async with rl._semaphore:
                        await rl.wait_async()
                        return await fn()
                else:
                    return await fn()
        except Exception as e:
            if not _is_transient(e):
                raise
            if attempt == max_retries - 1:
                raise
            wait = (2**attempt) + random.uniform(0, 5)
            logger.warning(
                "Transient error (%s) attempt %d/%d. Waiting %.1fs...",
                type(e).__name__,
                attempt + 1,
                max_retries,
                wait,
            )
            await asyncio.sleep(wait)
    return None

TokenUsage = dict


def _load_dotenv(path: str = None) -> None:
    if path is None:
        from pathlib import Path
        path = str(Path(__file__).resolve().parent.parent / ".env")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                if k not in os.environ:
                    os.environ[k] = v.strip()


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return text


@functools.lru_cache(maxsize=32)
def _encode_image(path: str, max_dim: int = 2048) -> str:
    import cv2
    img = cv2.imread(path)
    if img is not None:
        h, w = img.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        success, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if success:
            return base64.b64encode(buf.tobytes()).decode("utf-8")
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


class ModelClient(ABC):
    @property
    def needs_images(self) -> bool:
        return True

    @abstractmethod
    async def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
        ...


# ── Gemini (google.genai) ──────────────────────────────────────────

class GeminiClient(ModelClient):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", base_url: str | None = None):
        from google import genai as _genai
        http_options = {"timeout": 120000}
        if base_url:
            http_options["base_url"] = base_url
        self._client = _genai.Client(api_key=api_key, http_options=http_options)
        self._genai = _genai
        self.model_name = model
        self.provider = "gemini"
        _gemini_conc = int(os.environ.get("GEMINI_MAX_CONCURRENCY", "12"))
        _gemini_rpm = int(os.environ.get("GEMINI_RATE_LIMIT_RPM", "14"))
        self._rl = RateLimiter(rpm=_gemini_rpm, max_concurrency=_gemini_conc)

    @staticmethod
    def _extract_token_usage(response) -> TokenUsage:
        usage = {}
        metadata = getattr(response, "usage_metadata", None)
        if metadata is not None:
            prompt_tokens = getattr(metadata, "prompt_token_count", 0) or 0
            completion_tokens = getattr(metadata, "response_token_count", 0) or 0
            total_tokens = getattr(metadata, "total_token_count", 0) or 0
            if completion_tokens == 0 and prompt_tokens > 0:
                text = getattr(response, "text", "") or ""
                completion_tokens = max(len(text.split()) * 4 // 3, 1)
                total_tokens = prompt_tokens + completion_tokens
            usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            }
        return usage

    async def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
        from PIL import Image

        if page_images:
            pages = sorted(page_images.keys())
            contents: list = [prompt]
            for p in pages:
                img = Image.open(page_images[p])
                contents.append(img)
            response = await call_with_retry_async(
                lambda: self._client.aio.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=self._genai.types.GenerateContentConfig(
                        response_mime_type="application/json",
                        max_output_tokens=16384,
                    ),
                ),
                rl=self._rl,
            )
        elif pdf_path:
            logger.debug("Uploading PDF to Gemini...")
            try:
                sample_file = await call_with_retry_async(
                    lambda: self._client.aio.files.upload(
                        file=pdf_path,
                        config={"mime_type": "application/pdf"},
                    ),
                    rl=self._rl,
                )
                logger.debug("Uploaded: %s", sample_file.name)
                response = await call_with_retry_async(
                    lambda: self._client.aio.models.generate_content(
                        model=self.model_name,
                        contents=[sample_file, prompt],
                        config=self._genai.types.GenerateContentConfig(
                            response_mime_type="application/json",
                            max_output_tokens=16384,
                        ),
                    ),
                    rl=self._rl,
                )
            except Exception as e:
                logger.warning("Gemini PDF generation failed (%s)", e)
                return None, {}
        else:
            logger.warning("Gemini extract_structured called with no PDF and no page images")
            return None, {}

        token_usage = self._extract_token_usage(response)
        text = _strip_json_fence(response.text)

        try:
            data = json.loads(text)
            logger.info("Extracted %d fields (tokens: %s)", len(data.get("fields", [])), token_usage)
            return data, token_usage
        except json.JSONDecodeError as e:
            logger.error("Failed to parse Gemini response: %s", e)
            logger.debug("Raw: %s", text[:500])
            return None, token_usage


# ── Factory ───────────────────────────────────────────────────────

def get_model_client(role: str = "primary") -> ModelClient:
    _load_dotenv()

    prefix = role.upper()
    model_key = f"{prefix}_MODEL"
    api_key_key = f"{prefix}_API_KEY"
    base_url_key = f"{prefix}_BASE_URL"

    model = os.environ.get(model_key, "gemini-2.5-flash")
    api_key = os.environ.get(api_key_key) or os.environ.get("GEMINI_API_KEY")
    base_url = os.environ.get(base_url_key)

    if not api_key:
        raise ValueError(f"{api_key_key} (or GEMINI_API_KEY) not set in .env")

    logger.info("[%s] Using Gemini: %s  base_url=%s", role, model, base_url)
    return GeminiClient(api_key=api_key, model=model, base_url=base_url)
