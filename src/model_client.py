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


TokenUsage = dict  # {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}


class ModelClient(ABC):
    @abstractmethod
    def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
        """Extract structured fields from a document.
        pdf_path: original PDF (Gemini uses this directly)
        page_images: dict of page_num -> path to preprocessed PNG
        Returns (parsed_json, token_usage_dict).
        """
        ...

    @abstractmethod
    def verify_fields(self, fields_json: list[dict], page_images: dict[int, str], prompt: str) -> tuple[list[dict] | None, TokenUsage]:
        """Verify extracted fields against their page images (batched, one call).
        Returns (verifications_list, token_usage_dict).
        """
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

    @staticmethod
    def _extract_token_usage(response) -> TokenUsage:
        usage = {}
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            usage = {
                "prompt_tokens": getattr(response.usage_metadata, 'prompt_token_count', 0) or 0,
                "completion_tokens": getattr(response.usage_metadata, 'candidates_token_count', 0) or 0,
                "total_tokens": getattr(response.usage_metadata, 'total_token_count', 0) or 0,
            }
        return usage

    def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
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

    def verify_fields(self, fields_json: list[dict], page_images: dict[int, str], prompt: str) -> tuple[list[dict] | None, TokenUsage]:
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
        token_usage = self._extract_token_usage(response)
        text = _strip_json_fence(response.text)

        try:
            return json.loads(text), token_usage
        except json.JSONDecodeError as e:
            logger.error("Failed to parse verification response: %s", e)
            logger.debug("Raw: %s", text[:300])
            return None, token_usage


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

    @staticmethod
    def _extract_token_usage(response) -> TokenUsage:
        usage = {}
        if hasattr(response, 'usage') and response.usage:
            usage = {
                "prompt_tokens": getattr(response.usage, 'prompt_tokens', 0) or 0,
                "completion_tokens": getattr(response.usage, 'completion_tokens', 0) or 0,
                "total_tokens": getattr(response.usage, 'total_tokens', 0) or 0,
            }
        return usage

    def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
        content = self._build_vision_content(prompt, page_images)

        response = call_with_retry(
            lambda: self._client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": content}],
                response_format={"type": "json_object"},
            ),
            rl=self._rl,
        )
        token_usage = self._extract_token_usage(response)
        text = response.choices[0].message.content or ""
        text = _strip_json_fence(text)

        try:
            data = json.loads(text)
            logger.info("Extracted %d fields (tokens: %s)", len(data.get("fields", [])), token_usage)
            return data, token_usage
        except json.JSONDecodeError as e:
            logger.error("Failed to parse OpenAI response: %s", e)
            logger.debug("Raw: %s", text[:500])
            return None, token_usage

    def verify_fields(self, fields_json: list[dict], page_images: dict[int, str], prompt: str) -> tuple[list[dict] | None, TokenUsage]:
        content = self._build_vision_content(prompt, page_images)

        response = call_with_retry(
            lambda: self._client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": content}],
            ),
            rl=self._rl,
        )
        token_usage = self._extract_token_usage(response)
        text = response.choices[0].message.content or ""
        text = _strip_json_fence(text)

        try:
            data = json.loads(text)
            # OpenAI may return an object wrapping the array (e.g. {"verifications": [...]})
            if isinstance(data, dict):
                for val in data.values():
                    if isinstance(val, list):
                        return val, token_usage
            return (data if isinstance(data, list) else None), token_usage
        except json.JSONDecodeError as e:
            logger.error("Failed to parse verification response: %s", e)
            logger.debug("Raw: %s", text[:300])
            return None, token_usage


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

    @staticmethod
    def _extract_token_usage(response) -> TokenUsage:
        usage = {}
        if hasattr(response, 'usage') and response.usage:
            usage = {
                "prompt_tokens": getattr(response.usage, 'prompt_tokens', 0) or 0,
                "completion_tokens": getattr(response.usage, 'completion_tokens', 0) or 0,
                "total_tokens": getattr(response.usage, 'total_tokens', 0) or 0,
            }
        return usage

    def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
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
        token_usage = self._extract_token_usage(response)
        text = response.choices[0].message.content or ""
        text = _strip_json_fence(text)

        try:
            data = json.loads(text)
            logger.info("Extracted %d fields (tokens: %s)", len(data.get("fields", [])), token_usage)
            return data, token_usage
        except json.JSONDecodeError as e:
            logger.error("Failed to parse DeepSeek response: %s", e)
            logger.debug("Raw: %s", text[:500])
            return None, token_usage

    def verify_fields(self, fields_json: list[dict], page_images: dict[int, str], prompt: str) -> tuple[list[dict] | None, TokenUsage]:
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
        token_usage = self._extract_token_usage(response)
        text = response.choices[0].message.content or ""
        text = _strip_json_fence(text)

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                for val in data.values():
                    if isinstance(val, list):
                        return val, token_usage
            return (data if isinstance(data, list) else None), token_usage
        except json.JSONDecodeError as e:
            logger.error("Failed to parse DeepSeek verification response: %s", e)
            logger.debug("Raw: %s", text[:300])
            return None, token_usage


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

    def _build_vision_content(self, prompt: str, page_images: dict[int, str]) -> list[dict] | str:
        is_vision = any(x in self.model_name.lower() for x in ["vision", "neva", "vlm", "llava", "paligemma", "molmo", "vl"])
        if not is_vision:
            return prompt

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

    @staticmethod
    def _extract_token_usage(response) -> TokenUsage:
        usage = {}
        if hasattr(response, 'usage') and response.usage:
            usage = {
                "prompt_tokens": getattr(response.usage, 'prompt_tokens', 0) or 0,
                "completion_tokens": getattr(response.usage, 'completion_tokens', 0) or 0,
                "total_tokens": getattr(response.usage, 'total_tokens', 0) or 0,
            }
        return usage

    def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
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
        token_usage = self._extract_token_usage(response)
        text = response.choices[0].message.content or ""
        text = _strip_json_fence(text)

        try:
            data = json.loads(text)
            logger.info("Extracted %d fields (tokens: %s)", len(data.get("fields", [])), token_usage)
            return data, token_usage
        except json.JSONDecodeError as e:
            logger.error("Failed to parse OpenRouter response: %s", e)
            logger.debug("Raw: %s", text[:500])
            return None, token_usage

    def verify_fields(self, fields_json: list[dict], page_images: dict[int, str], prompt: str) -> tuple[list[dict] | None, TokenUsage]:
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
        token_usage = self._extract_token_usage(response)
        text = response.choices[0].message.content or ""
        text = _strip_json_fence(text)

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                for val in data.values():
                    if isinstance(val, list):
                        return val, token_usage
            return (data if isinstance(data, list) else None), token_usage
        except json.JSONDecodeError as e:
            logger.error("Failed to parse OpenRouter verification response: %s", e)
            logger.debug("Raw: %s", text[:300])
            return None, token_usage



# ── NVIDIA NIM Client ───────────────────────────────────────────────

class NvidiaClient(ModelClient):
    """NVIDIA NIM compatible client.

    Uses the OpenAI SDK with integrate.api.nvidia.com/v1.
    """

    def __init__(self, api_key: str, model: str = "nvidia/nemotron-3-ultra-550b-a55b"):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key, base_url="https://integrate.api.nvidia.com/v1")
        self.model_name = model
        self._rl = RateLimiter()

    @staticmethod
    def _encode_image(path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _build_content(self, prompt: str, page_images: dict[int, str]) -> list[dict] | str:
        is_vision = any(x in self.model_name.lower() for x in ["vision", "neva", "vlm", "llava", "paligemma", "molmo", "vl"])
        if not is_vision:
            return prompt

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

    def _call_nvidia_stream(self, content: any) -> str:
        extra_body = {}
        if "nemotron" in self.model_name.lower():
            extra_body = {
                "chat_template_kwargs": {"enable_thinking": True},
                "reasoning_budget": 16384
            }

        response_stream = self._client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": content}],
            temperature=1,
            top_p=0.95,
            max_tokens=16384,
            extra_body=extra_body,
            stream=True
        )

        full_content = []
        for chunk in response_stream:
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
        print()  # print final newline
        return "".join(full_content)

    def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
        content = self._build_content(prompt, page_images)
        logger.info("Calling NVIDIA NIM API (%s)...", self.model_name)
        text = call_with_retry(
            lambda: self._call_nvidia_stream(content),
            rl=self._rl,
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

    def verify_fields(self, fields_json: list[dict], page_images: dict[int, str], prompt: str) -> tuple[list[dict] | None, TokenUsage]:
        content = self._build_content(prompt, page_images)
        logger.info("Calling NVIDIA NIM API for verification (%s)...", self.model_name)
        text = call_with_retry(
            lambda: self._call_nvidia_stream(content),
            rl=self._rl,
        )
        text = _strip_json_fence(text)

        try:
            data = json.loads(text) if isinstance(text, str) and text.strip().startswith(("[", "{")) else []
            if not isinstance(data, list):
                if isinstance(data, dict) and "fields" in data:
                    data = data["fields"]
                else:
                    data = []
            return data, {}
        except json.JSONDecodeError:
            import re
            m = re.search(r'\[\s*\{.*\}\s*\]', text, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(0))
                    return data, {}
                except Exception:
                    pass
            logger.error("Failed to parse NVIDIA verification response")
            return None, {}


# ── Factory ────────────────────────────────────────────────────────

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

    if provider == "nvidia":
        logger.info("[%s] Using NVIDIA NIM: %s", role, model)
        return NvidiaClient(api_key=api_key, model=model)

    logger.info("[%s] Using Gemini: %s", role, model)
    return GeminiClient(api_key=api_key, model=model)
