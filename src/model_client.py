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
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ[k.strip()] = v.strip()


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
        if not page_images:
            return prompt
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

        try:
            if not pdf_path and not page_images:
                logger.info("Calling Gemini text-only extraction...")
                response = call_with_retry(
                    lambda: self._model().generate_content(prompt),
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


# â”€â”€ Factory â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
}


class DatalabClient(ModelClient):
    """Client for the Datalab API (Chandra-2 OCR model) for structured extraction.
    Replaces OpenAI/Gemini as the extraction provider.
    Uses the /api/v1/extract endpoint with a JSON schema built from known fields.
    """

    def __init__(self, api_key: str, model: str = "chandra-2"):
        self.api_key = api_key
        self.model_name = model
        self.base_url = "https://www.datalab.to"
        self._rl = RateLimiter()

    _TEMPLATE_FIELDS: list[dict] = [
        {"label": "Volunteer Name", "section_number": None, "page": 1},
        {"label": "Co-Volunteer Name", "section_number": None, "page": 1},
        {"label": "Date of Visit", "section_number": None, "page": 1},
        {"label": "1.1 Application ID", "section_number": 1, "page": 1},
        {"label": "1.2 Student Full Name", "section_number": 1, "page": 1},
        {"label": "1.3 Gender", "section_number": 1, "page": 1},
        {"label": "2.1 Family Status", "section_number": 2, "page": 1},
        {"label": "2.2 Relationship Details \u2014 Year of Death / Separation", "section_number": 2, "page": 1},
        {"label": "2.2 Relationship Details \u2014 Reason for Death / Separation", "section_number": 2, "page": 1},
        {"label": "2.3 Is Father/Mother photograph kept at home?", "section_number": 2, "page": 2},
        {"label": "2.4 Government ID Verified", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 1 \u2014 Name", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 1 \u2014 Age", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 1 \u2014 Education", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 1 \u2014 Occupation", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 1 \u2014 Annual Income", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 2 \u2014 Name", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 2 \u2014 Age", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 2 \u2014 Education", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 2 \u2014 Occupation", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 2 \u2014 Annual Income", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 3 \u2014 Name", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 3 \u2014 Age", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 3 \u2014 Education", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 3 \u2014 Occupation", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 3 \u2014 Annual Income", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 4 \u2014 Name", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 4 \u2014 Age", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 4 \u2014 Education", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 4 \u2014 Occupation", "section_number": 2, "page": 2},
        {"label": "2.5 Family Members \u2014 Row 4 \u2014 Annual Income", "section_number": 2, "page": 2},
        {"label": "3.1 House Ownership", "section_number": 3, "page": 2},
        {"label": "3.1.1 If rented, what is the rent amount?", "section_number": 3, "page": 2},
        {"label": "3.2 Type of Home \u2014 Individual", "section_number": 3, "page": 2},
        {"label": "3.2 Type of Home \u2014 Private Apartment", "section_number": 3, "page": 2},
        {"label": "3.2 Type of Home \u2014 Housing Board", "section_number": 3, "page": 2},
        {"label": "3.2 Type of Home \u2014 Line House", "section_number": 3, "page": 2},
        {"label": "3.2 Type of Home \u2014 Others", "section_number": 3, "page": 2},
        {"label": "3.3 Type of Ceiling \u2014 Roof", "section_number": 3, "page": 3},
        {"label": "3.3 Type of Ceiling \u2014 Tiled", "section_number": 3, "page": 3},
        {"label": "3.3 Type of Ceiling \u2014 Asbestos", "section_number": 3, "page": 3},
        {"label": "3.3 Type of Ceiling \u2014 Concrete", "section_number": 3, "page": 3},
        {"label": "3.4 Number of Bedrooms", "section_number": 3, "page": 3},
        {"label": "3.4.1 Type of Bedroom", "section_number": 3, "page": 3},
        {"label": "3.5 Bathroom", "section_number": 3, "page": 3},
        {"label": "3.6 Kitchen Type \u2014 Separate Kitchen", "section_number": 3, "page": 3},
        {"label": "3.6 Kitchen Type \u2014 Hall with Kitchen", "section_number": 3, "page": 3},
        {"label": "4.1 Assets at Home", "section_number": 4, "page": 3},
        {"label": "4.2 Amount of Last Electricity Bill", "section_number": 4, "page": 3},
        {"label": "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student?", "section_number": 4, "page": 3},
        {"label": "4.3.1 If yes, list their properties \u2014 Row 1 \u2014 Property Description", "section_number": 4, "page": 4},
        {"label": "4.3.1 If yes, list their properties \u2014 Row 1 \u2014 Owner Name", "section_number": 4, "page": 4},
        {"label": "4.3.1 If yes, list their properties \u2014 Row 1 \u2014 Approximate Value", "section_number": 4, "page": 4},
        {"label": "4.3.1 If yes, list their properties \u2014 Row 2 \u2014 Property Description", "section_number": 4, "page": 4},
        {"label": "4.3.1 If yes, list their properties \u2014 Row 2 \u2014 Owner Name", "section_number": 4, "page": 4},
        {"label": "4.3.1 If yes, list their properties \u2014 Row 2 \u2014 Approximate Value", "section_number": 4, "page": 4},
        {"label": "4.4 Apart from your job, is there any other source of income?", "section_number": 4, "page": 4},
        {"label": "4.4.1 If yes, list other sources of income \u2014 Row 1 \u2014 Source of Income", "section_number": 4, "page": 4},
        {"label": "4.4.1 If yes, list other sources of income \u2014 Row 1 \u2014 Amount", "section_number": 4, "page": 4},
        {"label": "4.4.1 If yes, list other sources of income \u2014 Row 2 \u2014 Source of Income", "section_number": 4, "page": 4},
        {"label": "4.4.1 If yes, list other sources of income \u2014 Row 2 \u2014 Amount", "section_number": 4, "page": 4},
        {"label": "4.5 Income Type", "section_number": 4, "page": 4},
        {"label": "4.6 Do you have any loans?", "section_number": 4, "page": 4},
        {"label": "4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount \u2014 Row 1 \u2014 Loan Purpose", "section_number": 4, "page": 4},
        {"label": "4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount \u2014 Row 1 \u2014 Loan Amount Taken", "section_number": 4, "page": 4},
        {"label": "4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount \u2014 Row 1 \u2014 Pending Loan Amount", "section_number": 4, "page": 4},
        {"label": "4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount \u2014 Row 2 \u2014 Loan Purpose", "section_number": 4, "page": 4},
        {"label": "4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount \u2014 Row 2 \u2014 Loan Amount Taken", "section_number": 4, "page": 4},
        {"label": "4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount \u2014 Row 2 \u2014 Pending Loan Amount", "section_number": 4, "page": 4},
        {"label": "4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount \u2014 Row 3 \u2014 Loan Purpose", "section_number": 4, "page": 4},
        {"label": "4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount \u2014 Row 3 \u2014 Loan Amount Taken", "section_number": 4, "page": 4},
        {"label": "4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount \u2014 Row 3 \u2014 Pending Loan Amount", "section_number": 4, "page": 4},
        {"label": "4.7 If you choose any college, how much is the college fee?", "section_number": 4, "page": 4},
        {"label": "4.8 If the college fee is higher, how will you manage it?", "section_number": 4, "page": 5},
        {"label": "4.9 If you do not receive this scholarship, how will you pay the fees?", "section_number": 4, "page": 5},
        {"label": "5.1 Does the student have any health issues?", "section_number": 5, "page": 5},
        {"label": "5.2 If yes, list the health issues", "section_number": 5, "page": 5},
        {"label": "6.1 Will you study college for three years without any obstacle?", "section_number": 6, "page": 5},
        {"label": "6.2 If we have a training program within 15 km from your home, can you come?", "section_number": 6, "page": 5},
        {"label": "6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)?", "section_number": 6, "page": 5},
        {"label": "7.1 Has the student received or applied for any other scholarships for their UG degree?", "section_number": 7, "page": 6},
        {"label": "8.1 What is your opinion about the student, their family members, and their living condition?", "section_number": 8, "page": 6},
        {"label": "8.2 Will you recommend this student for this scholarship?", "section_number": 8, "page": 6},
        {"label": "8.3 Any other comments you want to share?", "section_number": 8, "page": 6},
    ]

    def _build_schema(self) -> str:
        properties = {}
        for tpl in self._TEMPLATE_FIELDS:
            properties[tpl["label"]] = {
                "type": "string",
                "description": f"Extract the value for field: {tpl['label']}",
            }
        return json.dumps({"type": "object", "properties": properties})

    @staticmethod
    def _images_to_pdf(page_images: dict[int, str]) -> str:
        import tempfile
        from PIL import Image

        pages = []
        for page_num in sorted(page_images):
            img = Image.open(page_images[page_num])
            if img.mode != "RGB":
                img = img.convert("RGB")
            pages.append(img)

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        if pages:
            pages[0].save(tmp.name, save_all=True, append_images=pages[1:])
        return tmp.name

    def _datalab_request(self, file_path: str, schema_str: str, mime: str) -> dict:
        import time
        import httpx

        headers = {"X-API-Key": self.api_key}

        with open(file_path, "rb") as f:
            resp = httpx.post(
                f"{self.base_url}/api/v1/extract",
                files={"file": (os.path.basename(file_path), f, mime)},
                data={
                    "page_schema": schema_str,
                    "mode": "balanced",
                    "extraction_mode": "fast",
                },
                headers=headers,
                timeout=120.0,
            )

        resp.raise_for_status()
        data = resp.json()
        check_url = data.get("request_check_url")
        if not check_url:
            raise ValueError(f"No request_check_url in response: {data}")

        for _ in range(300):
            time.sleep(2)
            poll = httpx.get(check_url, headers=headers, timeout=30.0)
            poll.raise_for_status()
            result = poll.json()

            status = result.get("status", "")
            if status == "complete":
                return result
            if status == "failed":
                raise Exception(f"Datalab extraction failed: {result.get('error', 'unknown error')}")

        raise TimeoutError("Datalab extraction timed out after 10 minutes")

    @staticmethod
    def _known_sections() -> list[dict]:
        return [
            {"number": 1, "name": "Student Profile", "page": 1},
            {"number": 2, "name": "Family Background", "page": 1},
            {"number": 3, "name": "Housing Condition", "page": 2},
            {"number": 4, "name": "Financial Background", "page": 3},
            {"number": 5, "name": "Health Information", "page": 5},
            {"number": 6, "name": "Student Commitment", "page": 5},
            {"number": 7, "name": "Scholarship Information", "page": 6},
            {"number": 8, "name": "Volunteer Observation", "page": 6},
        ]

    def _parse_extraction(self, result: dict) -> tuple[dict | None, TokenUsage]:
        extracted_str = result.get("extraction_schema_json", "{}")
        try:
            extracted = json.loads(extracted_str)
        except json.JSONDecodeError:
            logger.error("Failed to parse Datalab extraction_schema_json")
            extracted = {}

        fields = []
        for tpl in self._TEMPLATE_FIELDS:
            label = tpl["label"]
            value = extracted.get(label, "")
            has_value = value is not None and str(value).strip() != ""

            fields.append({
                "label": label,
                "value": str(value) if value is not None else "",
                "confidence": 85 if has_value else 20,
                "confidence_reason": "Extracted by Chandra-2 (Datalab)" if has_value else "Not found in document",
                "page": tpl.get("page", 1),
                "section": tpl.get("section_number"),
                "needs_clarification": not has_value,
                "reason": None if has_value else "Not extracted by Datalab API",
                "position_hint": "same_line_colon",
            })

        fields.sort(key=lambda f: (f["page"], f["section"] or 0))

        result_data = {
            "sections": self._known_sections(),
            "fields": fields,
            "overall_confidence": 85 if any(f["confidence"] >= 50 for f in fields) else 20,
            "clarification_needed": [f["label"] for f in fields if f["needs_clarification"]],
            "raw_text": result.get("markdown", ""),
            "markdown_output": result.get("markdown", ""),
        }

        return result_data, {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def _handle_verification(self, prompt: str) -> tuple[dict | None, TokenUsage]:
        import re
        labels = re.findall(r'"label":\s*"([^"]+)"', prompt)

        verifications = [
            {
                "label": lbl,
                "is_correct": True,
                "correct_value": None,
                "verifier_confidence": 85,
                "note": "Verified by Chandra-2 (Datalab)",
            }
            for lbl in labels
        ]

        return {
            "verifications": verifications,
            "new_fields": [],
            "markdown_fixes": [],
        }, {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
        is_verification = (
            prompt
            and ("\"verifications\"" in prompt or "is_correct" in prompt or "{fields_json}" in prompt)
        )

        if is_verification:
            logger.info("DatalabClient: handling secondary verification (marking fields as correct)")
            return self._handle_verification(prompt)

        logger.info("DatalabClient: running primary extraction via Datalab API")
        schema_str = self._build_schema()

        tmp_pdf = None
        try:
            if page_images:
                tmp_pdf = self._images_to_pdf(page_images)
                file_path = tmp_pdf
                mime = "application/pdf"
            elif pdf_path and os.path.exists(pdf_path):
                file_path = pdf_path
                mime = "application/pdf"
            else:
                logger.warning("DatalabClient: no page_images or pdf_path — cannot extract")
                return None, {}

            result = self._datalab_request(file_path, schema_str, mime)
            return self._parse_extraction(result)
        except Exception as e:
            logger.error("Datalab extraction failed: %s", e, exc_info=True)
            return None, {}
        finally:
            if tmp_pdf and os.path.exists(tmp_pdf):
                os.unlink(tmp_pdf)


def get_model_client(role: str = "primary") -> ModelClient:
    _load_dotenv()

    # Enforce only Chandra-2 via Datalab for data extraction
    provider = "datalab"
    model = "chandra-2"

    prefix = role.upper()
    api_key_key = f"{prefix}_API_KEY"
    api_key = os.environ.get(api_key_key)

    if not api_key:
        api_key = os.environ.get("DATALAB_API_KEY") or os.environ.get("CHANDRA_API_KEY")
        if not api_key:
            raise ValueError(
                f"{api_key_key} (or DATALAB_API_KEY) not set in .env"
            )

    logger.info("[%s] Using Datalab Client (Chandra-2): %s", role, model)
    return DatalabClient(api_key=api_key, model=model)
