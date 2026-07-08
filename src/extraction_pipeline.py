import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from rapidfuzz import fuzz

import os
from src.datalab_schema import EXPECTED_FIELD_LABELS
from src.tesseract import WordBox, get_backend
from src.model_client import ModelClient, get_model_client

@dataclass
class Config:
    render_dpi: int = 150
    deskew_max_angle: int = 5
    denoise_strength: int = 10
    binarization_block_size: int = 15
    binarization_c: int = 2
    ocr_backend: str = "tesseract"
    max_image_width: int = 1200
    bbox_render_dpi: int = 150
    tesseract_workers: int = 4
    tesseract_timeout: int = 120
    tesseract_enabled: bool = True

    def __post_init__(self):
        env_val = os.environ.get("TESSERACT_ENABLED")
        if env_val is not None:
            self.tesseract_enabled = env_val.lower() in ("1", "true", "yes")


def to_grayscale(image: np.ndarray) -> np.ndarray:
    if len(image.shape) == 3:
        return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    return image


def deskew(image: np.ndarray, max_angle: int = 5) -> np.ndarray:
    h, w = image.shape[:2]
    scale = 500.0 / max(h, w)
    small = cv2.resize(image, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    edges = cv2.Canny(small, 50, 150, apertureSize=3)
    coords = np.column_stack(np.where(edges > 0))
    if len(coords) < 50:
        return image
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = 90 + angle
    if abs(angle) > max_angle or abs(angle) < 0.5:
        return image
    
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def denoise(image: np.ndarray, h: int = 10) -> np.ndarray:
    return cv2.medianBlur(image, 3)


def adaptive_threshold(image: np.ndarray, block_size: int = 15, c: int = 2) -> np.ndarray:
    if block_size % 2 == 0:
        block_size += 1
    return cv2.adaptiveThreshold(
        image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block_size, c
    )


def preprocess(image: np.ndarray, config: Config, is_digital: bool = False) -> np.ndarray:
    gray = to_grayscale(image)
    gray = deskew(gray, config.deskew_max_angle)
    if not is_digital:
        gray = denoise(gray, config.denoise_strength)
    return adaptive_threshold(gray, config.binarization_block_size, config.binarization_c)


logger = logging.getLogger(__name__)

# ── Known template fields ──────────────────────────────────────
KNOWN_TEMPLATE_FIELDS: list[dict] = [
    # ── Page 1 ──
    # Header (section = null)
    {"label": "Volunteer Name", "section_number": None, "page": 1},
    {"label": "Co-Volunteer Name", "section_number": None, "page": 1},
    {"label": "Date of Visit", "section_number": None, "page": 1},
    # Section 1 — Student Profile
    {"label": "1.1 Application ID", "section_number": 1, "page": 1},
    {"label": "1.2 Student Full Name", "section_number": 1, "page": 1},
    {"label": "1.3 Gender", "section_number": 1, "page": 1},
    # Section 2 — Family Background (Page 1: 2.1-2.2)
    {"label": "2.1 Family Status", "section_number": 2, "page": 1},
    {"label": "2.2 Relationship Details — Year of Death / Separation", "section_number": 2, "page": 1},
    {"label": "2.2 Relationship Details — Reason for Death / Separation", "section_number": 2, "page": 1},
    # ── Page 2 ──
    # Section 2 — Family Background (Page 2: 2.3-2.5)
    {"label": "2.3 Is Father/Mother photograph kept at home?", "section_number": 2, "page": 2},
    {"label": "2.4 Government ID Verified", "section_number": 2, "page": 2},
    {"label": "2.5 Family Members — Row 1 — Name", "section_number": 2, "page": 2},
    {"label": "2.5 Family Members — Row 1 — Age", "section_number": 2, "page": 2},
    {"label": "2.5 Family Members — Row 1 — Education", "section_number": 2, "page": 2},
    {"label": "2.5 Family Members — Row 1 — Occupation", "section_number": 2, "page": 2},
    {"label": "2.5 Family Members — Row 1 — AnnualIncome", "section_number": 2, "page": 2},
    # Section 3 — Housing Condition (Page 2: 3.1-3.2)
    {"label": "3.1 House Ownership", "section_number": 3, "page": 2},
    {"label": "3.1.1 If rented, what is the rent amount?", "section_number": 3, "page": 2},
    {"label": "3.2 Type of Home — Individual", "section_number": 3, "page": 2},
    {"label": "3.2 Type of Home — Private Apartment", "section_number": 3, "page": 2},
    {"label": "3.2 Type of Home — Housing Board", "section_number": 3, "page": 2},
    {"label": "3.2 Type of Home — Line House", "section_number": 3, "page": 2},
    {"label": "3.2 Type of Home — Others", "section_number": 3, "page": 2},
    # ── Page 3 ──
    # Section 3 — Housing Condition (Page 3: 3.3-3.6)
    {"label": "3.3 Type of Ceiling — Roof (Kurai)", "section_number": 3, "page": 3},
    {"label": "3.3 Type of Ceiling — Tiled", "section_number": 3, "page": 3},
    {"label": "3.3 Type of Ceiling — Asbestos / Sheet", "section_number": 3, "page": 3},
    {"label": "3.3 Type of Ceiling — Concrete", "section_number": 3, "page": 3},
    {"label": "3.4 Number of Bedrooms", "section_number": 3, "page": 3},
    {"label": "3.4.1 Type of Bedroom - Separate Bedroom", "section_number": 3, "page": 3},
    {"label": "3.4.1 Type of Bedroom - No Separate Bedroom", "section_number": 3, "page": 3},
    {"label": "3.5 Bathroom - Separate", "section_number": 3, "page": 3},
    {"label": "3.5 Bathroom - Common for Apartment", "section_number": 3, "page": 3},
    {"label": "3.6 Kitchen Type — Separate Kitchen", "section_number": 3, "page": 3},
    {"label": "3.6 Kitchen Type — Hall with Kitchen", "section_number": 3, "page": 3},
    # Section 4 — Financial Background (Page 3: 4.1-4.3)
    {"label": "4.1 Assets at Home(tick all that apply) - Washing Machine", "section_number": 4, "page": 3},
    {"label": "4.1 Assets at Home(tick all that apply) - Fridge", "section_number": 4, "page": 3},
    {"label": "4.1 Assets at Home(tick all that apply) - AC", "section_number": 4, "page": 3},
    {"label": "4.1 Assets at Home(tick all that apply) - LED TV", "section_number": 4, "page": 3},
    {"label": "4.1 Assets at Home(tick all that apply) - Two-Wheeler", "section_number": 4, "page": 3},
    {"label": "4.1 Assets at Home(tick all that apply) - Car", "section_number": 4, "page": 3},
    {"label": "4.1 Assets at Home(tick all that apply) - Smartphone", "section_number": 4, "page": 3},
    {"label": "4.1 Assets at Home(tick all that apply) - Separate Wi-Fi", "section_number": 4, "page": 3},
    {"label": "4.1 Assets at Home(tick all that apply) - Others:", "section_number": 4, "page": 3},
    {"label": "4.2 Amount of Last Electricity Bill", "section_number": 4, "page": 3},
    {"label": "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student?", "section_number": 4, "page": 3},
    # ── Page 4 ──
    # Section 4 — Financial Background (Page 4: 4.4-4.7)
    {"label": "4.3.1 If Yes, list their properties: - Property Description", "section_number": 4, "page": 4},
     {"label": "4.3.1 If Yes, list their properties: - Owner Name", "section_number": 4, "page": 4},
      {"label": "4.3.1 If Yes, list their properties: - Approximate Value", "section_number": 4, "page": 4},
    {"label": "4.4 Apart from your job, is there any other source of income?", "section_number": 4, "page": 4},
     {"label": "4.4.1 If Yes, list other sources of income: - Source of Income", "section_number": 4, "page": 4},
          {"label": "4.4.1 If Yes, list other sources of income: - Amount", "section_number": 4, "page": 4},
    {"label": "4.5 Income Type", "section_number": 4, "page": 4},
    {"label": "4.6 Do you have any loans?", "section_number": 4, "page": 4},
         {"label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount - Sr.No.", "section_number": 4, "page": 4},
         {"label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount - Loan Purpose", "section_number": 4, "page": 4},
         {"label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount - Loan Amount Taken", "section_number": 4, "page": 4},
         {"label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount - Pending Loan Amount", "section_number": 4, "page": 4},
    
    # ── Page 5 ──
    # Section 4 — Financial Background (Page 5: 4.7-4.9)
    {"label": "4.7 If you choose any college, how much is the college fee?", "section_number": 4, "page": 5},
    {"label": "4.8 If the college fee is higher, how will you manage it?", "section_number": 4, "page": 5},
    {"label": "4.9 If you do not receive this scholarship, how will you pay the fees?", "section_number": 4, "page": 5},
    # Section 5 — Health Information
    {"label": "5.1 Does the student have any health issues?", "section_number": 5, "page": 5},
    {"label": "5.2 If yes, list the health issues", "section_number": 5, "page": 5},
    # Section 6 — Student Commitment
    {"label": "6.1 Will you study college for three years without any obstacle?", "section_number": 6, "page": 5},
    {"label": "6.2 If we have a training program within 15 km from your home, can you come?", "section_number": 6, "page": 5},
    
    # ── Page 6 ──
    {"label": "6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)?", "section_number": 6, "page": 6},
    # Section 7 — Scholarship Information
    {"label": "7.1 Has the student received or applied for any other scholarships for their UG degree?", "section_number": 7, "page": 6},
    # Section 8 — Volunteer Observation
    {"label": "8.1 What is your opinion about the student, their family members, and their living condition?", "section_number": 8, "page": 6},
    {"label": "8.2 Will you recommend this student for this scholarship?", "section_number": 8, "page": 6},
    {"label": "8.3 Any other comments you want to share?", "section_number": 8, "page": 6},
]


@dataclass
class StructuredField:
    label: str = ""
    value: str = ""
    confidence: int = 0
    page: int = 1
    section_number: int | None = None
    bbox: tuple[int, int, int, int] | None = None
    value_bbox: tuple[int, int, int, int] | None = None
    needs_clarification: bool = False
    reason: str | None = None
    is_verified: bool = False
    verifier_confidence: int | None = None
    verification_note: str | None = None
    extracted_by: str | None = None
    verified_by: str | None = None
    original_value: str | None = None


@dataclass
class TextLine:
    text: str
    bbox: tuple[int, int, int, int]
    page: int
    words: list[WordBox]


class ExtractionPipeline:
    def __init__(
        self,
        config: Config | None = None,
        primary_client: ModelClient | None = None,
        secondary_client: ModelClient | None = None,
    ):
        self.config = config or Config()
        self.primary_client = primary_client or get_model_client("primary")
        self.secondary_client = secondary_client
        if self.secondary_client is None:
            try:
                self.secondary_client = get_model_client("secondary")
            except ValueError:
                self.secondary_client = None

    @staticmethod
    def _parse_confidence(field_dict: dict) -> int:
        raw = field_dict.get("confidence")
        if isinstance(raw, (int, float)) and 0 <= raw <= 100:
            return int(raw)
        tier = field_dict.get("confidence_tier", "medium")
        if tier == "high":
            return 85
        elif tier == "medium":
            return 65
        return 30

    @staticmethod
    def _compute_coverage_confidence(fields: list) -> tuple[int, int]:
        fields = [f for f in fields if isinstance(f, dict)]
        non_empty = [f for f in fields if f.get("value") and f.get("value") not in ("", "N/A")]
        found_labels = {f.get("label") for f in fields if f.get("label")}
        expected = EXPECTED_FIELD_LABELS
        coverage = round(len(found_labels & expected) / len(expected) * 100) if expected else 100
        confidence = round(sum(f.get("confidence", 0) for f in non_empty) / len(non_empty)) if non_empty else 0
        return coverage, confidence

    @staticmethod
    def _infer_section_from_label(label: str) -> int | None:
        m = __import__('re').match(r"^(\d+)\.", label)
        return int(m.group(1)) if m else None

    # ── Stage 1: Preprocess ──────────────────────────────────────

    def preprocess(self, pdf_path: str, output_dir: str) -> dict[int, np.ndarray]:
        import fitz
        from PIL import Image

        pages_dir = Path(output_dir) / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(pdf_path)
        pages: dict[int, np.ndarray] = {}

        for i in range(len(doc)):
            page_num = i + 1
            out_path = pages_dir / f"page_{page_num}.png"
            orig_path = pages_dir / f"page_{page_num}_original.png"

            page = doc[i]
            mat = fitz.Matrix(self.config.render_dpi / 72, self.config.render_dpi / 72)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            arr = np.array(img)

            # Save original (raw render) before preprocessing
            if not orig_path.exists():
                Image.fromarray(arr).save(str(orig_path))

            if out_path.exists():
                cached = cv2.imread(str(out_path))
                if cached is not None:
                    pages[page_num] = cv2.cvtColor(cached, cv2.COLOR_BGR2RGB)
                    continue

            gray = to_grayscale(arr)
            gray = deskew(gray, self.config.deskew_max_angle)
            gray = denoise(gray, self.config.denoise_strength)
            rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)

            # Downscale wide images for faster LLM inference
            max_w = self.config.max_image_width
            if max_w and rgb.shape[1] > max_w:
                scale = max_w / rgb.shape[1]
                new_w = max_w
                new_h = int(rgb.shape[0] * scale)
                rgb = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)

            Image.fromarray(rgb).save(str(out_path))
            pages[page_num] = rgb

        doc.close()
        logger.info("Preprocessed %d pages → %s", len(pages), pages_dir)
        return pages

    def preprocess_images(
        self, image_paths: dict[int, str], output_dir: str
    ) -> dict[int, np.ndarray]:
        """Preprocess image files (same deskew/denoise pipeline)."""
        from PIL import Image

        pages_dir = Path(output_dir) / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)

        pages: dict[int, np.ndarray] = {}

        for page_num in sorted(image_paths):
            src_path = image_paths[page_num]
            out_path = pages_dir / f"page_{page_num}.png"
            orig_path = pages_dir / f"page_{page_num}_original.png"

            img = Image.open(src_path)
            arr = np.array(img)

            if not orig_path.exists():
                Image.fromarray(arr).save(str(orig_path))

            if out_path.exists():
                cached = cv2.imread(str(out_path))
                if cached is not None:
                    pages[page_num] = cv2.cvtColor(cached, cv2.COLOR_BGR2RGB)
                    continue

            gray = to_grayscale(arr)
            gray = deskew(gray, self.config.deskew_max_angle)
            gray = denoise(gray, self.config.denoise_strength)
            rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)

            # Downscale wide images for faster LLM inference
            max_w = self.config.max_image_width
            if max_w and rgb.shape[1] > max_w:
                scale = max_w / rgb.shape[1]
                new_w = max_w
                new_h = int(rgb.shape[0] * scale)
                rgb = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)

            Image.fromarray(rgb).save(str(out_path))
            pages[page_num] = rgb

        logger.info("Preprocessed %d image pages → %s", len(pages), pages_dir)
        return pages

    # ── Stage 2: Bounding box detection (Tesseract, CPU) ─────────

    def run_bbox(self, pdf_path: str) -> list[WordBox]:
        backend = get_backend(self.config.ocr_backend)
        result = backend.process(pdf_path, self.config)
        return result.word_boxes

    def run_bbox_images(self, page_images: dict[int, str]) -> list[WordBox]:
        """Run Tesseract bbox on pre-rendered images instead of PDF."""
        backend = get_backend(self.config.ocr_backend)
        result = backend.process_images(page_images, self.config)
        return result.word_boxes

    # ── Stage 3a: Primary model extraction ───────────────────────

    async def run_primary_extraction(self, pdf_path: str, page_images: dict[int, str]) -> tuple[dict | None, dict]:
        from src.prompt_templates import PRIMARY_EXTRACTION_PROMPT, PAGE_FIELD_MAPPINGS

        num_pages = len(page_images)
        if not num_pages and pdf_path:
            import fitz
            try:
                doc = fitz.open(pdf_path)
                num_pages = len(doc)
                doc.close()
            except Exception:
                num_pages = 0

        def build_page_prompt(page: int) -> str:
            sections_on_page = {
                1: [{"number": 1, "name": "Student Profile", "page": 1}, {"number": 2, "name": "Family Background", "page": 1}],
                2: [{"number": 2, "name": "Family Background", "page": 2}, {"number": 3, "name": "Housing Condition", "page": 2}],
                3: [{"number": 3, "name": "Housing Condition", "page": 3}, {"number": 4, "name": "Financial Background", "page": 3}],
                4: [{"number": 4, "name": "Financial Background", "page": 4}],
                5: [{"number": 4, "name": "Financial Background", "page": 5}, {"number": 5, "name": "Health Information", "page": 5}, {"number": 6, "name": "Student Commitment", "page": 5}],
                6: [{"number": 6, "name": "Student Commitment", "page": 6}, {"number": 7, "name": "Scholarship Information", "page": 6}, {"number": 8, "name": "Volunteer Observation", "page": 6}]
            }.get(page, [])

            return f'''You are a trusted form extraction engine for Page {page} of the "I Am The Change — Home Visit Questionnaire".
Output ONLY valid JSON. No markdown fences. No explanations. No commentary. ONLY the JSON object.

GROUND RULES:
1. Extract ONLY the fields that physically appear on Page {page}. Do NOT output fields that belong to other pages.
2. The labels in the output JSON MUST EXACTLY match the labels listed in the FIELD LIST below (including their numbers, e.g. "2.3 Is Father/Mother photograph kept at home?", "3.1 House Ownership", "2.5 Family Members — Row 1 — Name"). Do NOT strip the numbers or alter the labels under any circumstances!
3. value="" for unreadable/blanks. value="N/A" for conditionals when parent="No". Never "null".
4. Radio → exact allowed option. Checkbox → ✓/✗ with label "{{Group}} — {{Option}}".
5. Table → count pre-printed rows first. Every cell: "{{Table}} — Row {{n}} — {{Column}}".
6. Never invent values.

CORE OUTPUT SCHEMA:
{{
  "sections": {json.dumps(sections_on_page)},
  "fields": [
    {{
      "label":  string  — exact label from FIELD LIST below,
      "value":  string  — "" | "N/A" | extracted text,
      "confidence": 0-100,
      "confidence_reason": string,
      "page":  {page},  "section":  int|null,  "needs_clarification": bool,
      "reason":  string|null,  "position_hint": "same_line_colon"|"right_of_label"|...
    }}
  ],
  "overall_confidence": 0-100,
  "clarification_needed": ["label1", "label2", ...],
  "raw_text": "...",
  "markdown_output": "..."
}}

FIELD LIST FOR PAGE {page}:
{PAGE_FIELD_MAPPINGS.get(page, "")}
'''

        def clean_labels(fields: list[dict]) -> list[dict]:
            cleaned = []
            for f in fields:
                label = f.get("label", "")
                if " [" in label:
                    label = label.split(" [")[0].strip()
                elif "[" in label:
                    label = label.split("[")[0].strip()
                f["label"] = label
                cleaned.append(f)
            return cleaned

        # Three-way dispatch:
        #   6 pages + vision provider → parallel per-page extraction (fast, accurate)
        #   non-6 pages              → sequential all-pages prompt (handles any page count/order)
        #   1 page or text-only      → single prompt
        if num_pages == 6 and self.primary_client.needs_images and getattr(self.primary_client, 'provider', '') != "gemini":
            logger.info("Starting page-by-page parallel LLM extraction for %d pages...", num_pages)
            tasks = []
            pages = sorted(page_images.keys())
            for p in pages:
                single_page_images = {p: page_images[p]}
                prompt = build_page_prompt(p)
                tasks.append(self.primary_client.extract_structured(None, single_page_images, prompt))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            merged_data = {
                "sections": [
                    {"number": 1, "name": "Student Profile", "page": 1},
                    {"number": 2, "name": "Family Background", "page": 1},
                    {"number": 3, "name": "Housing Condition", "page": 2},
                    {"number": 4, "name": "Financial Background", "page": 3},
                    {"number": 5, "name": "Health Information", "page": 5},
                    {"number": 6, "name": "Student Commitment", "page": 5},
                    {"number": 7, "name": "Scholarship Information", "page": 6},
                    {"number": 8, "name": "Volunteer Observation", "page": 6}
                ],
                "fields": [],
                "overall_confidence": 0,
                "clarification_needed": [],
                "raw_text": "",
                "markdown_output": ""
            }

            total_prompt_tokens = 0
            total_completion_tokens = 0
            merged_fields: dict[str, dict] = {}
            raw_text_parts: list[str] = []
            markdown_parts: list[str] = []
            clarifications: set[str] = set()

            for idx, res in enumerate(results):
                page = pages[idx]
                if isinstance(res, Exception):
                    logger.error("Parallel extraction failed for page %d: %s", page, res)
                    continue
                if not res or not res[0]:
                    logger.warning("Parallel extraction returned no data for page %d", page)
                    continue
                data, token_usage = res
                total_prompt_tokens += token_usage.get("prompt_tokens", 0) or 0
                total_completion_tokens += token_usage.get("completion_tokens", 0) or 0

                cleaned_fields = clean_labels(data.get("fields", []))
                for f in cleaned_fields:
                    label = f.get("label")
                    if not label:
                        continue
                    existing = merged_fields.get(label)
                    if not existing:
                        merged_fields[label] = f
                    else:
                        existing_conf = existing.get("confidence", 0) or 0
                        new_conf = f.get("confidence", 0) or 0
                        if new_conf > existing_conf or (new_conf == existing_conf and f.get("value") and not existing.get("value")):
                            merged_fields[label] = f

                if data.get("raw_text"):
                    raw_text_parts.append(data["raw_text"])
                if data.get("markdown_output"):
                    markdown_parts.append(data["markdown_output"])
                for clar in data.get("clarification_needed", []):
                    if " [" in clar:
                        clar = clar.split(" [")[0].strip()
                    elif "[" in clar:
                        clar = clar.split("[")[0].strip()
                    clarifications.add(clar)

            merged_data["fields"] = list(merged_fields.values())
            merged_data["clarification_needed"] = list(clarifications)
            merged_data["raw_text"] = "\n\n".join(raw_text_parts)
            merged_data["markdown_output"] = "\n\n".join(markdown_parts)

            coverage, confidence = self._compute_coverage_confidence(merged_data["fields"])
            merged_data["coverage"] = coverage
            merged_data["confidence"] = confidence
            merged_data["overall_confidence"] = round(coverage * confidence / 100) if coverage and confidence else 0

            token_usage = {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens,
                "calls": len(tasks)
            }
            logger.info("Parallel extraction merged: %d fields (coverage=%d%%, confidence=%d%%, tokens=%s)",
                        len(merged_data["fields"]), coverage, confidence, token_usage)
            return merged_data, token_usage

        # Sequential all-pages extraction for non-standard page counts/orders
        if num_pages > 1:
            prompt = (
                f"You are examining all {num_pages} pages of the Home Visit Questionnaire. "
                f"Each image below is labeled with its page number.\n\n"
                f"RULES:\n"
                f"1. Extract ALL fields visible across ALL pages.\n"
                f"2. Set the 'page' field to the page number where each field physically appears.\n"
                f"3. If a field is NOT visible (cropped/blank/hidden), output value=\"\" with 0 confidence.\n\n"
                f"{PRIMARY_EXTRACTION_PROMPT}"
            )
        else:
            prompt = PRIMARY_EXTRACTION_PROMPT

        data, token_usage = await self.primary_client.extract_structured(
            pdf_path, page_images, prompt
        )
        token_usage["calls"] = 1
        if data and isinstance(data, dict):
            fields = data.get("fields", [])
            if fields:
                coverage, confidence = self._compute_coverage_confidence(fields)
                data["coverage"] = coverage
                data["confidence"] = confidence
                data["overall_confidence"] = round(coverage * confidence / 100) if coverage and confidence else data.get("overall_confidence", 0)
        return data, token_usage

    # ── Stage 3b: Merge (enhanced with position_hint + confidence weighting) ──

    def _group_words_into_lines(self, word_boxes: list[WordBox], page: int, y_tolerance: int = 20) -> list[TextLine]:
        page_words = sorted(
            [wb for wb in word_boxes if wb.page_num == page],
            key=lambda w: (w.bbox[1], w.bbox[0]),
        )
        if not page_words:
            return []

        lines: list[list[WordBox]] = [[page_words[0]]]
        for wb in page_words[1:]:
            prev_top = lines[-1][-1].bbox[1]
            if abs(wb.bbox[1] - prev_top) < y_tolerance:
                lines[-1].append(wb)
            else:
                lines.append([wb])

        result: list[TextLine] = []
        for group in lines:
            result.append(TextLine(
                text=" ".join(w.text for w in group),
                bbox=self._words_bbox(group),
                page=page,
                words=group,
            ))
        return result

    @staticmethod
    def _words_bbox(words: list[WordBox]) -> tuple[int, int, int, int]:
        xs = [w.bbox[0] for w in words]
        ys = [w.bbox[1] for w in words]
        xe = [w.bbox[2] for w in words]
        ye = [w.bbox[3] for w in words]
        return (min(xs), min(ys), max(xe), max(ye))

    def merge_fields(
        self,
        model_data: dict,
        word_boxes: list[WordBox],
        prefix: str = "",
    ) -> list[StructuredField]:
        fields: list[StructuredField] = []
        raw_fields = [f for f in model_data.get("fields", []) if isinstance(f, dict)]

        pages_in_fields = sorted({gf.get("page", 1) for gf in raw_fields})
        lines_by_page: dict[int, list[TextLine]] = {
            p: self._group_words_into_lines(word_boxes, p) for p in pages_in_fields
        }

        for gf in raw_fields:
            fields.append(self._create_structured_field(gf, lines_by_page, prefix))

        return fields

    def _create_structured_field(
        self,
        gf: dict,
        lines_by_page: dict[int, list[TextLine]],
        prefix: str = "",
    ) -> StructuredField:
        label = gf.get("label", "")
        value = gf.get("value", "")
        confidence = self._parse_confidence(gf)
        page = gf.get("page", 1)
        section_number = gf.get("section")
        if section_number is None:
            section_number = self._infer_section_from_label(label)
        needs_clarification = gf.get("needs_clarification", False)
        position_hint = gf.get("position_hint")
        label_bbox, value_bbox = self._find_field_bboxes(
            value, label, page, lines_by_page.get(page, []),
            position_hint=position_hint,
        )

        return StructuredField(
            label=label,
            value=value,
            confidence=confidence,
            page=page,
            section_number=section_number,
            bbox=label_bbox,
            value_bbox=value_bbox,
            needs_clarification=needs_clarification,
            reason=gf.get("reason"),
            extracted_by=prefix or None,
        )

    def _find_field_bboxes(
        self, value: str, label: str, page: int, lines: list[TextLine],
        position_hint: str | None = None,
    ) -> tuple[tuple[int, int, int, int] | None, tuple[int, int, int, int] | None]:
        """Returns (label_bbox, value_bbox)."""
        if not lines:
            return None, None

        # For composite labels (checkbox options, table rows, sub-questions),
        # match the main label part (before " — ") against Tesseract lines.
        main_label = label.split(" — ")[0] if " — " in label else label
        option_part = label[len(main_label) + 3:].strip() if " — " in label else ""

        label_lower = label.lower().strip()
        main_label_lower = main_label.lower().strip()

        best: tuple[float, TextLine] | None = None
        # Prefer matching the main label over the full composite label
        for text, candidate in [(main_label_lower, main_label), (label_lower, label)]:
            for line in lines:
                ratio = fuzz.token_set_ratio(text, line.text.lower())
                if ratio > 65 and (best is None or ratio > best[0]):
                    best = (ratio, line)

        if best is None:
            # Fallback: match just the leading number (e.g. "4.1")
            m = __import__('re').match(r"(\d+(?:\.\d+)*)", label)
            if m:
                num_prefix = m.group(1)
                for line in lines:
                    if num_prefix in line.text:
                        if best is None or len(line.text) < len(best[1].text):
                            best = (90.0, line)

        if best is None:
            return None, None

        _, best_line = best
        label_bbox = best_line.bbox
        value_lower = value.lower().strip()

        value_bbox = self._find_value_bbox(
            value_lower, best_line, lines, position_hint,
            option_text=option_part,
        )

        return label_bbox, value_bbox

    def _find_value_bbox(
        self, value_lower: str, best_line: TextLine, lines: list[TextLine],
        position_hint: str | None = None,
        option_text: str = "",
    ) -> tuple[int, int, int, int] | None:
        """Find the bounding box for the value text, given the label line."""

        # ── Composite label (checkbox / table row): find the option text ──
        if option_text:
            best_idx = lines.index(best_line)
            opt_lower = option_text.lower().strip()
            search_region = lines[max(0, best_idx - 3):best_idx + 6]
            best_opt: tuple[float, TextLine] | None = None
            for candidate in search_region:
                r = fuzz.token_set_ratio(opt_lower, candidate.text.lower())
                if r > 65 and (best_opt is None or r > best_opt[0]):
                    best_opt = (r, candidate)
            if best_opt:
                _, opt_line = best_opt
                # Value is likely to the right of the option text (checkbox ✓/✗)
                # or on the same line (table cell value after colon)
                if value_lower:
                    for wb in opt_line.words:
                        wl = wb.text.lower()
                        if fuzz.partial_ratio(value_lower, wl) > 75:
                            return wb.bbox
                # Return the option text bbox as the value location
                return opt_line.bbox

        # ── Position hint strategies ──────────────────────────────────
        if position_hint == "above_label":
            best_idx = lines.index(best_line)
            for candidate in reversed(lines[:best_idx]):
                if best_line.bbox[1] - candidate.bbox[3] > 40:
                    break
                if value_lower and fuzz.partial_ratio(value_lower, candidate.text.lower()) > 50:
                    return candidate.bbox
                return candidate.bbox
            return best_line.bbox

        if position_hint == "below_label":
            best_idx = lines.index(best_line)
            for candidate in lines[best_idx + 1:]:
                if candidate.bbox[1] - best_line.bbox[3] > 40:
                    break
                if value_lower and fuzz.partial_ratio(value_lower, candidate.text.lower()) > 50:
                    return candidate.bbox
                return candidate.bbox
            return best_line.bbox

        if position_hint in ("same_line_colon", "right_of_label"):
            colon_idx = best_line.text.find(":")
            if colon_idx >= 0:
                colon_word = None
                char_count = 0
                for wb in best_line.words:
                    word_end = char_count + len(wb.text)
                    if char_count <= colon_idx < word_end:
                        colon_word = wb
                        break
                    char_count = word_end + 1
                if colon_word and len(best_line.words) > 1:
                    right_words = [wb for wb in best_line.words if wb.bbox[0] > colon_word.bbox[0]]
                    if right_words:
                        return self._words_bbox(right_words)

            if value_lower:
                mid_x = (best_line.bbox[0] + best_line.bbox[2]) / 2
                right_words = [wb for wb in best_line.words if wb.bbox[0] > mid_x]
                if right_words:
                    return self._words_bbox(right_words)
            return best_line.bbox

        # ── No position_hint — try all strategies in order ────────────

        # Strategy 1: Find value words within the same line
        if value_lower:
            value_words: list[tuple[float, WordBox]] = []
            for wb in best_line.words:
                wl = wb.text.lower()
                if fuzz.partial_ratio(value_lower, wl) > 75 or fuzz.partial_ratio(wl, value_lower) > 75:
                    weight = wb.confidence / 100.0 if wb.confidence > 60 else 0.5
                    value_words.append((weight, wb))
            if value_words:
                value_words.sort(key=lambda x: x[0], reverse=True)
                chosen = [vw[1] for vw in value_words[:3]]
                return self._words_bbox(chosen)

        # Strategy 2: Colon split — words to the right of colon
        colon_idx = best_line.text.find(":")
        if colon_idx >= 0:
            colon_word = None
            char_count = 0
            for wb in best_line.words:
                word_end = char_count + len(wb.text)
                if char_count <= colon_idx < word_end:
                    colon_word = wb
                    break
                char_count = word_end + 1
            if colon_word and len(best_line.words) > 1:
                right_words = [wb for wb in best_line.words if wb.bbox[0] > colon_word.bbox[0]]
                if right_words:
                    return self._words_bbox(right_words)

        # Strategy 3: Next line below
        best_idx = lines.index(best_line)
        for candidate in lines[best_idx + 1:]:
            if candidate.bbox[1] - best_line.bbox[3] > 40:
                break
            if value_lower and fuzz.partial_ratio(value_lower, candidate.text.lower()) > 50:
                return candidate.bbox
            return candidate.bbox

        # Fallback: value is on the same line as the label
        return best_line.bbox

    # ── Stage 4: Secondary model verification ───────────────────────

    async def verify_secondary(
        self,
        fields: list[StructuredField],
        word_boxes: list[WordBox],
        output_dir: str,
        prefix: str = "",
    ) -> tuple[list[StructuredField], dict]:
        from src.prompt_templates import SECONDARY_VERIFICATION_PROMPT

        if self.secondary_client is None:
            logger.info("No secondary model configured — auto-accepting all fields")
            for f in fields:
                f.is_verified = True
                f.verified_by = prefix or None
            return fields, {}

        # Only send low-confidence fields to secondary — skip high-confidence ones
        low_conf = [f for f in fields if f.confidence < 90 or f.needs_clarification]
        high_conf = [f for f in fields if f.confidence >= 90 and not f.needs_clarification]

        for f in high_conf:
            f.is_verified = True
            f.verifier_confidence = f.confidence
            f.verification_note = "High confidence, auto-accepted"
            f.verified_by = prefix or None

        if not low_conf:
            logger.info("All %d fields have high confidence — skipping secondary verification", len(fields))
            return fields, {}

        pages_dir = Path(output_dir) / "pages"
        affected_pages = sorted(set(f.page for f in low_conf))
        page_images: dict[int, str] = {}
        for p in affected_pages:
            img_path = str(pages_dir / f"page_{p}.png")
            if Path(img_path).exists():
                page_images[p] = img_path

        if not page_images:
            logger.warning("No page images found for secondary verification")
            for f in low_conf:
                f.is_verified = True
                f.verified_by = prefix or None
            return fields, {}

        fields_json = [
            {
                "label": f.label,
                "value": f.value,
                "confidence": f.confidence,
                "page": f.page,
                "reason": f.reason,
                "position_hint": None,
            }
            for f in low_conf
        ]

        prompt = SECONDARY_VERIFICATION_PROMPT.replace(
            "{fields_json}", json.dumps(fields_json, indent=2)
        )

        # Secondary verification is text-only: it verifies field labels/values
        # and finds gaps in the extraction. It does not need to re-read the
        # document images (which would cost ~225k tokens and ~90s latency).
        raw_result, secondary_token_usage = await self.secondary_client.extract_structured("", {}, prompt)

        if raw_result is None:
            logger.warning("Secondary verification failed — keeping primary results")
            for f in low_conf:
                f.is_verified = True
                f.verified_by = prefix or None
            return fields, secondary_token_usage

        # Process verifications
        verif_map: dict[str, dict] = {}
        for v in raw_result.get("verifications", []):
            if isinstance(v, dict):
                verif_map[v.get("label", "")] = v

        for f in low_conf:
            v = verif_map.get(f.label, {})
            is_correct = v.get("is_correct", True)
            v_conf = v.get("verifier_confidence")
            note = v.get("note")

            f.is_verified = True
            f.verifier_confidence = v_conf
            f.verification_note = note
            f.verified_by = prefix or None

            if not is_correct and v.get("correct_value"):
                f.original_value = f.value
                f.value = v["correct_value"]
                f.confidence = min(f.confidence, v_conf or 50)

        # Process new fields from secondary
        new_fields_data = raw_result.get("new_fields", [])
        if new_fields_data:
            pages_in_new = sorted({nf.get("page", 1) for nf in new_fields_data})
            lines_by_page: dict[int, list[TextLine]] = {}
            for p in pages_in_new:
                lines_by_page[p] = self._group_words_into_lines(word_boxes, p)

            for nf in new_fields_data:
                field_obj = self._create_structured_field(nf, lines_by_page, prefix)
                field_obj.is_verified = True
                field_obj.verifier_confidence = field_obj.confidence
                field_obj.verification_note = "Added by secondary model"
                fields.append(field_obj)

            logger.info("Secondary model added %d new fields", len(new_fields_data))

        return fields, secondary_token_usage

    @staticmethod
    def _checkbox_sub_option(label: str) -> bool:
        return "\u2014" in label

    @staticmethod
    def fill_missing_template_fields(fields: list[StructuredField]) -> list[StructuredField]:
        existing_labels = {f.label for f in fields}
        for tpl in KNOWN_TEMPLATE_FIELDS:
            if tpl["label"] in existing_labels:
                continue
            if ExtractionPipeline._checkbox_sub_option(tpl["label"]):
                continue
            fields.append(StructuredField(
                label=tpl["label"],
                value="",
                confidence=0,
                page=tpl["page"],
                section_number=tpl["section_number"],
                needs_clarification=True,
                reason="Not extracted by LLM",
                extracted_by="template_fill",
            ))
        return fields


