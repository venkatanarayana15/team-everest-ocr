import base64
import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path

from src.ratelimit import RateLimiter, call_with_retry

logger = logging.getLogger(__name__)


def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return text


class ModelClient(ABC):
    @abstractmethod
    def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> dict | None:
        """Extract structured fields from a document.
        pdf_path: original PDF (Gemini uses this directly)
        page_images: dict of page_num -> path to preprocessed PNG
        """
        ...

    @abstractmethod
    def verify_fields(self, fields_json: list[dict], page_images: dict[int, str], prompt: str) -> list[dict] | None:
        """Verify extracted fields against their page images (batched, one call)."""
        ...


# ── Gemini Client ──────────────────────────────────────────────────

class GeminiClient(ModelClient):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self.model_name = model
        self._genai = genai
        self._rl = RateLimiter()

    def _model(self):
        return self._genai.GenerativeModel(self.model_name)

    def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> dict | None:
        from PIL import Image

        logger.info("Uploading PDF to Gemini...")
        try:
            sample_file = self._genai.upload_file(path=pdf_path, mime_type="application/pdf")
            logger.info("Uploaded: %s", sample_file.name)
            response = call_with_retry(
                lambda: self._model().generate_content([sample_file, prompt]),
                rl=self._rl,
            )
        except Exception as e:
            logger.warning("Gemini PDF upload failed (%s), falling back to page images", e)
            pages = sorted(page_images.keys())
            content: list = [prompt]
            for p in pages:
                img = Image.open(page_images[p])
                content.append(img)
            response = call_with_retry(
                lambda: self._model().generate_content(content),
                rl=self._rl,
            )

        text = _strip_json_fence(response.text)

        try:
            data = json.loads(text)
            logger.info("Extracted %d fields", len(data.get("fields", [])))
            return data
        except json.JSONDecodeError as e:
            logger.error("Failed to parse Gemini response: %s", e)
            logger.debug("Raw: %s", text[:500])
            return None

    def verify_fields(self, fields_json: list[dict], page_images: dict[int, str], prompt: str) -> list[dict] | None:
        from PIL import Image

        pages = sorted(page_images.keys())
        content: list = [prompt]
        for p in pages:
            img = Image.open(page_images[p])
            content.append(img)

        response = call_with_retry(
            lambda: self._model().generate_content(content),
            rl=self._rl,
        )
        text = _strip_json_fence(response.text)

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse verification response: %s", e)
            logger.debug("Raw: %s", text[:300])
            return None


# ── OpenAI Client ──────────────────────────────────────────────────

class OpenAIClient(ModelClient):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key)
        self.model_name = model
        self._rl = RateLimiter()

    @staticmethod
    def _encode_image(path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _build_vision_content(self, prompt: str, page_images: dict[int, str]) -> list[dict]:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for page_num in sorted(page_images):
            b64 = self._encode_image(page_images[page_num])
            content.append({
                "type": "text",
                "text": f"\n[Page {page_num}:]",
            })
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64}",
                    "detail": "high",
                },
            })
        return content

    def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> dict | None:
        content = self._build_vision_content(prompt, page_images)

        response = call_with_retry(
            lambda: self._client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": content}],
                response_format={"type": "json_object"},
            ),
            rl=self._rl,
        )
        text = response.choices[0].message.content or ""
        text = _strip_json_fence(text)

        try:
            data = json.loads(text)
            logger.info("Extracted %d fields", len(data.get("fields", [])))
            return data
        except json.JSONDecodeError as e:
            logger.error("Failed to parse OpenAI response: %s", e)
            logger.debug("Raw: %s", text[:500])
            return None

    def verify_fields(self, fields_json: list[dict], page_images: dict[int, str], prompt: str) -> list[dict] | None:
        content = self._build_vision_content(prompt, page_images)

        response = call_with_retry(
            lambda: self._client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": content}],
            ),
            rl=self._rl,
        )
        text = response.choices[0].message.content or ""
        text = _strip_json_fence(text)

        try:
            data = json.loads(text)
            # OpenAI may return an object wrapping the array (e.g. {"verifications": [...]})
            if isinstance(data, dict):
                for val in data.values():
                    if isinstance(val, list):
                        return val
            return data if isinstance(data, list) else None
        except json.JSONDecodeError as e:
            logger.error("Failed to parse verification response: %s", e)
            logger.debug("Raw: %s", text[:300])
            return None


# ── DeepSeek Client ─────────────────────────────────────────────────

class DeepSeekClient(ModelClient):
    """OpenAI-compatible client for DeepSeek API (deepseek-chat / deepseek-reasoner)."""

    def __init__(self, api_key: str, model: str = "deepseek-chat"):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
        self.model_name = model
        self._rl = RateLimiter()

    @staticmethod
    def _encode_image(path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _build_vision_content(self, prompt: str, page_images: dict[int, str]) -> list[dict]:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for page_num in sorted(page_images):
            b64 = self._encode_image(page_images[page_num])
            content.append({
                "type": "text",
                "text": f"\n[Page {page_num}:]",
            })
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64}",
                    "detail": "high",
                },
            })
        return content

    def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> dict | None:
        content = self._build_vision_content(prompt, page_images)

        kwargs = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": content}],
        }
        # deepseek-chat supports JSON mode; deepseek-reasoner does not
        if self.model_name == "deepseek-chat":
            kwargs["response_format"] = {"type": "json_object"}

        response = call_with_retry(
            lambda: self._client.chat.completions.create(**kwargs),
            rl=self._rl,
        )
        text = response.choices[0].message.content or ""
        text = _strip_json_fence(text)

        try:
            data = json.loads(text)
            logger.info("Extracted %d fields", len(data.get("fields", [])))
            return data
        except json.JSONDecodeError as e:
            logger.error("Failed to parse DeepSeek response: %s", e)
            logger.debug("Raw: %s", text[:500])
            return None

    def verify_fields(self, fields_json: list[dict], page_images: dict[int, str], prompt: str) -> list[dict] | None:
        content = self._build_vision_content(prompt, page_images)

        kwargs = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": content}],
        }
        if self.model_name == "deepseek-chat":
            kwargs["response_format"] = {"type": "json_object"}

        response = call_with_retry(
            lambda: self._client.chat.completions.create(**kwargs),
            rl=self._rl,
        )
        text = response.choices[0].message.content or ""
        text = _strip_json_fence(text)

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                for val in data.values():
                    if isinstance(val, list):
                        return val
            return data if isinstance(data, list) else None
        except json.JSONDecodeError as e:
            logger.error("Failed to parse DeepSeek verification response: %s", e)
            logger.debug("Raw: %s", text[:300])
            return None


# ── OpenRouter Client ───────────────────────────────────────────────

class OpenRouterClient(ModelClient):
    """OpenAI-compatible client for OpenRouter API.

    Uses the same OpenAI SDK with OpenRouter's base URL.
    Supports any model available on OpenRouter (Qwen, DeepSeek, etc.).
    """

    def __init__(self, api_key: str, model: str = "qwen/qwen-2.5-14b-instruct"):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
        self.model_name = model
        self._rl = RateLimiter()

    @staticmethod
    def _encode_image(path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _build_vision_content(self, prompt: str, page_images: dict[int, str]) -> list[dict]:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for page_num in sorted(page_images):
            b64 = self._encode_image(page_images[page_num])
            content.append({
                "type": "text",
                "text": f"\n[Page {page_num}:]",
            })
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64}",
                    "detail": "high",
                },
            })
        return content

    def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> dict | None:
        content = self._build_vision_content(prompt, page_images)

        response = call_with_retry(
            lambda: self._client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": content}],
                response_format={"type": "json_object"},
                extra_headers={
                    "HTTP-Referer": "https://github.com/anomalyco/opencode",
                    "X-Title": "OCR Extraction Pipeline",
                },
            ),
            rl=self._rl,
        )
        text = response.choices[0].message.content or ""
        text = _strip_json_fence(text)

        try:
            data = json.loads(text)
            logger.info("Extracted %d fields", len(data.get("fields", [])))
            return data
        except json.JSONDecodeError as e:
            logger.error("Failed to parse OpenRouter response: %s", e)
            logger.debug("Raw: %s", text[:500])
            return None

    def verify_fields(self, fields_json: list[dict], page_images: dict[int, str], prompt: str) -> list[dict] | None:
        content = self._build_vision_content(prompt, page_images)

        response = call_with_retry(
            lambda: self._client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": content}],
                extra_headers={
                    "HTTP-Referer": "https://github.com/anomalyco/opencode",
                    "X-Title": "OCR Extraction Pipeline",
                },
            ),
            rl=self._rl,
        )
        text = response.choices[0].message.content or ""
        text = _strip_json_fence(text)

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                for val in data.values():
                    if isinstance(val, list):
                        return val
            return data if isinstance(data, list) else None
        except json.JSONDecodeError as e:
            logger.error("Failed to parse OpenRouter verification response: %s", e)
            logger.debug("Raw: %s", text[:300])
            return None


# ── Factory ────────────────────────────────────────────────────────

_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
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
        # Fallback to old single-provider env vars
        legacy_key = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
        api_key = os.environ.get(legacy_key)
        if not api_key:
            raise ValueError(
                f"{api_key_key} (or {legacy_key}) not set in .env"
            )

    # Override base URL if set via env (e.g. SECONDARY_BASE_URL)
    base_url = os.environ.get(base_url_key) or _BASE_URLS.get(provider)

    if provider == "openai":
        logger.info("[%s] Using OpenAI: %s", role, model)
        return OpenAIClient(api_key=api_key, model=model)

    if provider == "deepseek":
        logger.info("[%s] Using DeepSeek: %s", role, model)
        return DeepSeekClient(api_key=api_key, model=model)

    if provider == "openrouter":
        logger.info("[%s] Using OpenRouter: %s", role, model)
        return OpenRouterClient(api_key=api_key, model=model)

    logger.info("[%s] Using Gemini: %s", role, model)
    return GeminiClient(api_key=api_key, model=model)
