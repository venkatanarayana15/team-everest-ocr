import asyncio
import base64
import json
import logging
import os
from abc import ABC, abstractmethod
import time
import random

logger = logging.getLogger(__name__)

# Global semaphore that caps total concurrent LLM calls across ALL pipelines.
# This prevents LLM API overload regardless of how many pipelines are active.
_global_llm_semaphore = asyncio.Semaphore(
    int(os.environ.get("GLOBAL_LLM_MAX_CONCURRENCY", "6"))
)


class RateLimiter:
    """Sliding-window rate limiter with both sync and async wait."""

    def __init__(self, rpm: int | None = None, max_concurrency: int | None = None):
        self.rpm = rpm or int(os.environ.get("LLM_RATE_LIMIT_RPM", "30"))
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
            wait = (2**attempt) + random.uniform(0, 1)
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
    async with _global_llm_semaphore:
        if rl:
            async with rl._semaphore:
                await rl.wait_async()
                return await _call_with_retry_async_inner(fn, max_retries)
        else:
            return await _call_with_retry_async_inner(fn, max_retries)


async def _call_with_retry_async_inner(fn, max_retries: int | None = None):
    max_retries = max_retries if max_retries is not None else int(os.environ.get("LLM_MAX_RETRIES", "5"))
    for attempt in range(max_retries):
        try:
            return await fn()
        except Exception as e:
            if not _is_transient(e):
                raise
            if attempt == max_retries - 1:
                raise
            wait = (2**attempt) + random.uniform(0, 1)
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
    if not os.environ.get("DOTENV_LOADED") and os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
        os.environ["DOTENV_LOADED"] = "1"


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return text


def _encode_image(path: str, max_dim: int = 1024) -> str:
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


def _extract_usage(response) -> TokenUsage:
    usage = {}
    if hasattr(response, 'usage') and response.usage:
        usage = {
            "prompt_tokens": getattr(response.usage, 'prompt_tokens', 0) or 0,
            "completion_tokens": getattr(response.usage, 'completion_tokens', 0) or 0,
            "total_tokens": getattr(response.usage, 'total_tokens', 0) or 0,
        }
    return usage


class ModelClient(ABC):
    @abstractmethod
    async def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
        ...


# ── Unified OpenAI-Compatible Provider ──────────────────────────

class OpenAICompatibleClient(ModelClient):
    def __init__(self, api_key: str, model: str, base_url: str, provider: str = ""):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model_name = model
        self.provider = provider.lower().strip()
        self._rl = RateLimiter()

    def _use_response_format(self) -> bool:
        if self.provider == "deepseek":
            return self.model_name == "deepseek-chat"
        return True

    def _extra_headers(self) -> dict | None:
        if self.provider == "openrouter":
            return {
                "HTTP-Referer": "https://github.com/anomalyco/opencode",
                "X-Title": "OCR Extraction Pipeline",
            }
        return None

    def _build_content(self, prompt: str, page_images: dict[int, str]) -> list[dict] | str:
        vision_keywords = ("vision", "neva", "vlm", "llava", "paligemma", "molmo", "vl", "gpt-4o", "gpt-4-turbo", "claude-3")
        is_vision = self.provider in ("openai", "gemini") or any(x in self.model_name.lower() for x in vision_keywords)
        if not is_vision:
            return prompt
        content: list[dict] = [{"type": "text", "text": prompt}]
        for page_num in sorted(page_images):
            b64 = _encode_image(page_images[page_num])
            content.append({"type": "text", "text": f"\n[Page {page_num}:]"})
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"},
            })
        return content

    async def _call_stream(self, content: list[dict] | str) -> str:
        extra_body = {}
        if self.provider == "nvidia" and "nemotron" in self.model_name.lower():
            extra_body = {
                "chat_template_kwargs": {"enable_thinking": True},
                "reasoning_budget": 16384
            }

        response_stream = await self._client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": content}],
            temperature=1,
            top_p=0.95,
            max_tokens=16384,
            extra_body=extra_body,
            stream=True
        )

        full_content = []
        async for chunk in response_stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                print(reasoning, end="", flush=True)
            if getattr(delta, "content", None) is not None:
                content_text = delta.content
                print(content_text, end="", flush=True)
                full_content.append(content_text)
        print()
        return "".join(full_content)

    async def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
        content = self._build_content(prompt, page_images)

        if self.provider == "nvidia" and "nemotron" in self.model_name.lower():
            logger.info("Calling NVIDIA NIM API (%s) stream...", self.model_name)
            loop = asyncio.get_running_loop()
            text = await loop.run_in_executor(
                None,
                lambda: call_with_retry(lambda: asyncio.run(self._call_stream(content)), rl=self._rl),
            )
            text = _strip_json_fence(text)
            try:
                data = json.loads(text)
                logger.info("Extracted %d fields", len(data.get("fields", [])))
                return data, {}
            except json.JSONDecodeError as e:
                logger.error("Failed to parse NVIDIA response: %s", e)
                logger.debug("Raw: %s", text[:500])
                return None, {}

        kwargs = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": content}],
        }
        if self._use_response_format():
            kwargs["response_format"] = {"type": "json_object"}
        headers = self._extra_headers()
        if headers:
            kwargs["extra_headers"] = headers

        response = await call_with_retry_async(
            lambda: self._client.chat.completions.create(**kwargs),
            rl=self._rl,
        )
        usage = _extract_usage(response)
        text = _strip_json_fence(response.choices[0].message.content or "")
        try:
            data = json.loads(text)
            logger.info("Extracted %d fields (tokens: %s)", len(data.get("fields", [])), usage)
            return data, usage
        except json.JSONDecodeError as e:
            logger.error("Failed to parse response: %s", e)
            logger.debug("Raw: %s", text[:500])
            return None, usage


# ── Gemini (google.genai) ──────────────────────────────────────────

class GeminiClient(ModelClient):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", base_url: str | None = None):
        from google import genai as _genai
        http_options = {}
        if base_url:
            http_options["base_url"] = base_url
        self._client = _genai.Client(api_key=api_key, http_options=http_options or None)
        self._genai = _genai
        self.model_name = model
        self._rl = RateLimiter()

    @staticmethod
    def _extract_token_usage(response) -> TokenUsage:
        usage = {}
        metadata = getattr(response, "usage_metadata", None)
        if metadata is not None:
            usage = {
                "prompt_tokens": getattr(metadata, "prompt_token_count", 0) or 0,
                "completion_tokens": getattr(metadata, "response_token_count", 0) or 0,
                "total_tokens": getattr(metadata, "total_token_count", 0) or 0,
            }
        return usage

    async def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
        from PIL import Image

        logger.info("Uploading PDF to Gemini...")

        try:
            sample_file = await call_with_retry_async(
                lambda: self._client.aio.files.upload(
                    file=pdf_path,
                    config={"mime_type": "application/pdf"},
                ),
                rl=self._rl,
            )
            logger.info("Uploaded: %s", sample_file.name)
            response = await call_with_retry_async(
                lambda: self._client.aio.models.generate_content(
                    model=self.model_name,
                    contents=[sample_file, prompt],
                    config=self._genai.types.GenerateContentConfig(
                        response_mime_type="application/json",
                    ),
                ),
                rl=self._rl,
            )
        except Exception as e:
            logger.warning("Gemini PDF upload failed (%s), falling back to page images", e)
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
                    ),
                ),
                rl=self._rl,
            )

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

_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
}


def get_model_client(role: str = "primary") -> ModelClient:
    _load_dotenv()

    prefix = role.upper()
    provider_key = f"{prefix}_PROVIDER"
    model_key = f"{prefix}_MODEL"
    api_key_key = f"{prefix}_API_KEY"
    base_url_key = f"{prefix}_BASE_URL"

    provider = os.environ.get(provider_key, "gemini").lower().strip()
    model = os.environ.get(model_key, "gemini-2.5-flash" if provider == "gemini" else "gpt-4o-mini")
    api_key = os.environ.get(api_key_key)

    if not api_key:
        legacy_key = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
        api_key = os.environ.get(legacy_key)
        if not api_key:
            raise ValueError(
                f"{api_key_key} (or {legacy_key}) not set in .env"
            )

    base_url = os.environ.get(base_url_key) or _BASE_URLS.get(provider)

    if provider == "gemini":
        logger.info("[%s] Using Gemini: %s  base_url=%s", role, model, base_url)
        return GeminiClient(api_key=api_key, model=model, base_url=base_url)

    logger.info("[%s] Using OpenAI-Compatible Client (%s): %s", role, provider, model)
    return OpenAICompatibleClient(api_key=api_key, model=model, base_url=base_url, provider=provider)
