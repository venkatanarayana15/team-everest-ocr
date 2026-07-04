import base64
import json
import logging
import os
from abc import ABC, abstractmethod
from src.ratelimit import RateLimiter, call_with_retry

logger = logging.getLogger(__name__)

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


def _encode_image(path: str) -> str:
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
    def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
        ...


# ── Unified OpenAI-Compatible Provider ──────────────────────────

class OpenAICompatibleClient(ModelClient):
    def __init__(self, api_key: str, model: str, base_url: str, provider: str = ""):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key, base_url=base_url)
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
                "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"},
            })
        return content

    def _call_stream(self, content: list[dict] | str) -> str:
        extra_body = {}
        if self.provider == "nvidia" and "nemotron" in self.model_name.lower():
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
        print()
        return "".join(full_content)

    def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
        content = self._build_content(prompt, page_images)

        if self.provider == "nvidia" and "nemotron" in self.model_name.lower():
            logger.info("Calling NVIDIA NIM API (%s) stream...", self.model_name)
            text = call_with_retry(lambda: self._call_stream(content), rl=self._rl)
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

        response = call_with_retry(
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


# ── Gemini ────────────────────────────────────────────────────────

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
        logger.info("[%s] Using Gemini: %s", role, model)
        return GeminiClient(api_key=api_key, model=model)

    logger.info("[%s] Using OpenAI-Compatible Client (%s): %s", role, provider, model)
    return OpenAICompatibleClient(api_key=api_key, model=model, base_url=base_url, provider=provider)
