import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from rapidfuzz import fuzz

import os
from src.datalab_schema import EXPECTED_FIELD_LABELS
from src.tesseract import WordBox, get_backend
from src.model_client import ModelClient, get_model_client

# Lazy import for checkbox_vision to avoid circular import at module level
def _load_page_images_cv(pdf_path: str) -> dict[int, np.ndarray]:
    from src.checkbox_vision import load_page_images
    return load_page_images(pdf_path, dpi=200)

@dataclass
class Config:
    render_dpi: int = 150
    deskew_max_angle: int = 5
    denoise_strength: int = 10
    binarization_block_size: int = 15
    binarization_c: int = 2
    ocr_backend: str = "tesseract"
    max_image_width: int = 1600
    bbox_render_dpi: int = 150
    tesseract_workers: int = 4
    tesseract_timeout: int = 120
    tesseract_enabled: bool = True

    def __post_init__(self):
        env_val = os.environ.get("TESSERACT_ENABLED")
        if env_val is not None:
            self.tesseract_enabled = env_val.lower() in ("1", "true", "yes")
        self.render_dpi = int(os.environ.get("RENDER_DPI", self.render_dpi))
        self.max_image_width = int(os.environ.get("MAX_IMAGE_WIDTH", self.max_image_width))


def to_grayscale(image: np.ndarray) -> np.ndarray:
    if len(image.shape) == 3:
        return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    return image


def deskew(image: np.ndarray, max_angle: int = 5) -> np.ndarray:
    h, w = image.shape[:2]
    scale = 500.0 / max(h, w)
    gray = to_grayscale(image)
    small = cv2.resize(gray, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

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
TEXT_FIELD_TIPS: dict[str, str] = {
    "Volunteer Name": "A person's name. Common misreads: 'n'↔'u', 'a'↔'o', 'l'↔'t', 'r'↔'v'. Read each character individually.",
    "Co-Volunteer Name": "A person's name. Common misreads: 'n'↔'u', 'a'↔'o', 'l'↔'t', 'r'↔'v'.",
    "Date of Visit": "A date like DD/MM/YYYY or written as text.",
    "1.1 Application ID": "An alphanumeric CODE like 'TE2024001', NOT a name. Digits that look like letters: '0'↔'O', '1'↔'l', '5'↔'S'.",
    "1.2 Student Full Name": "The student's full name. Common misreads: 'n'↔'u', 'a'↔'o'. Read each character.",
    "2.2 Relationship Details — Year of Death / Separation": "A year (e.g. '2020'). ONLY the year digits.",
    "2.2 Relationship Details — Reason for Death / Separation": "Free-text description. Capture ALL text verbatim.",
    "2.4 Government ID Verified — Other (specify)": "Short text written on the line next to 'Other', e.g. 'Pan Card'. If the 'Other' box is unchecked or nothing is written, output empty string.",
    "3.1.1 If rented, what is the rent amount?": "Rent amount. Preserve the original text as written including comma, ₹, Rs, /month. If you see '4,100', output '4,100' not '4100' or '41000'. If you see '4000/month', output '4000/month'. 'l'/'I'→'1', 'O'/'o'→'0', 'S'→'5', 'Z'→'2'.",
    "3.2 Type of Home — Others": "Free text written next to 'Others'. Capture verbatim.",
    "3.4 Number of Bedrooms": "A small number (1-5). Strip words like 'bedroom'.",
    "4.1 Assets at Home(tick all that apply) - Others:": "Free text after 'Others:'. Prefix with 'Others: ' if missing.",
    "4.2 Amount of Last Electricity Bill": "Electricity bill amount. Preserve the original text as written including units like ₹, Rs, /month. Do NOT strip non-digit characters.",
    "4.7 If you choose any college, how much is the college fee?": "College name AND fee together (e.g. 'RITE Institute - 50000'). Keep both parts.",
    "4.8 If the college fee is higher, how will you manage it?": "Free-text answer. Capture COMPLETE handwritten response verbatim.",
    "4.9 If you do not receive this scholarship, how will you pay the fees?": "Free-text answer. Capture COMPLETE handwritten response verbatim.",
    "5.2 If yes, list the health issues": "Free-text health issue descriptions. Capture verbatim.",
    "6.1 Will you study college for three years without any obstacle?": "Short answer (often 'Yes'/'No' or explanation). EXACTLY as written.",
    "7.1 Has the student received or applied for any other scholarships for their UG degree?": "Free-text. Strip prefixes like 'Applied:', 'Answer:'. Output content only.",
    "8.1 What is your opinion about the student, their family members, and their living condition?": "Long free-text. Preserve complete answer with newlines.",
    "8.3 Any other comments you want to share?": "Free-text comments. Capture verbatim.",
}

HANDWRITTEN_TEXT_LABELS: set[str] = set(TEXT_FIELD_TIPS.keys())

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
    {"label": "blank_text_below_2_1", "section_number": 2, "page": 1},
    {"label": "2.2 Relationship Details — Year of Death / Separation", "section_number": 2, "page": 1},
    {"label": "2.2 Relationship Details — Reason for Death / Separation", "section_number": 2, "page": 1},
    # ── Page 2 ──
    # Section 2 — Family Background (Page 2: 2.3-2.5)
    {"label": "2.3 Is Father/Mother photograph kept at home?", "section_number": 2, "page": 2},
    {"label": "2.4 Government ID Verified", "section_number": 2, "page": 2},
    {"label": "2.4 Government ID Verified — Aadhaar Card", "section_number": 2, "page": 2},
    {"label": "2.4 Government ID Verified — Ration Card", "section_number": 2, "page": 2},
    {"label": "2.4 Government ID Verified — Driving Licence", "section_number": 2, "page": 2},
    {"label": "2.4 Government ID Verified — Voter ID", "section_number": 2, "page": 2},
    {"label": "2.4 Government ID Verified — Other", "section_number": 2, "page": 2},
    {"label": "2.4 Government ID Verified — Other (specify)", "section_number": 2, "page": 2},
    {"label": "2.5 Family Members — Row 1 — Name", "section_number": 2, "page": 2},
    {"label": "2.5 Family Members — Row 1 — Age", "section_number": 2, "page": 2},
    {"label": "2.5 Family Members — Row 1 — Education", "section_number": 2, "page": 2},
    {"label": "2.5 Family Members — Row 1 — Occupation", "section_number": 2, "page": 2},
    {"label": "2.5 Family Members — Row 1 — Annual Income", "section_number": 2, "page": 2},
    # Section 3 — Housing Condition (Page 2: 3.1-3.2)
    {"label": "3.1 House Ownership — Own", "section_number": 3, "page": 2},
    {"label": "3.1 House Ownership — Rented", "section_number": 3, "page": 2},
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
    {"label": "3.4.1 Type of Bedroom — Separate Bedroom", "section_number": 3, "page": 3},
    {"label": "3.4.1 Type of Bedroom — No Separate Bedroom", "section_number": 3, "page": 3},
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
    {"label": "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes", "section_number": 4, "page": 3},
    {"label": "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — No", "section_number": 4, "page": 3},
    {"label": "blank_text_below_4_3", "section_number": 4, "page": 3},
    # ── Page 4 ──
    # Section 4 — Financial Background (Page 4: 4.4-4.7)
    {"label": "4.3.1 If Yes, list their properties: - Property Description", "section_number": 4, "page": 4},
     {"label": "4.3.1 If Yes, list their properties: - Owner Name", "section_number": 4, "page": 4},
      {"label": "4.3.1 If Yes, list their properties: - Approximate Value", "section_number": 4, "page": 4},
    {"label": "blank_text_below_4_3_1_table", "section_number": 4, "page": 4},
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
        missing = expected - found_labels
        if missing:
            logger.debug("Labels not in expected set: %s", sorted(found_labels - expected)[:10])
            logger.debug("Expected labels not found: %s", sorted(missing)[:10])
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
        from concurrent.futures import ThreadPoolExecutor

        pages_dir = Path(output_dir) / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)

        # Color images preserve faint checkbox/pen marks and skip the (slow,
        # lossy) grayscale+denoise step — better for a vision LLM and faster.
        use_color = os.environ.get("LLM_USE_COLOR_IMAGE", "true").lower() in ("1", "true", "yes")

        # PyMuPDF is not thread-safe per document, so render sequentially first,
        # then run the CPU-heavy deskew/resize/encode work in parallel threads.
        doc = fitz.open(pdf_path)
        num_pages = len(doc)
        rendered: dict[int, np.ndarray] = {}
        for i in range(num_pages):
            out_path = pages_dir / f"page_{i + 1}.png"
            if out_path.exists():
                continue
            mat = fitz.Matrix(self.config.render_dpi / 72, self.config.render_dpi / 72)
            pix = doc[i].get_pixmap(matrix=mat)
            rendered[i + 1] = np.array(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
        doc.close()

        max_w = self.config.max_image_width

        def _process(page_num: int, arr: np.ndarray) -> tuple[int, np.ndarray]:
            orig_path = pages_dir / f"page_{page_num}_original.png"
            out_path = pages_dir / f"page_{page_num}.png"
            if not orig_path.exists():
                Image.fromarray(arr).save(str(orig_path))

            img = deskew(arr, self.config.deskew_max_angle)

            # CLAHE contrast enhancement — makes text pop even at low resolution
            lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            l = clahe.apply(l)
            img = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2RGB)

            if not use_color:
                gray = denoise(to_grayscale(img), self.config.denoise_strength)
                img = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)

            if max_w and img.shape[1] > max_w:
                scale = max_w / img.shape[1]
                img = cv2.resize(img, (max_w, int(img.shape[0] * scale)), interpolation=cv2.INTER_AREA)

            Image.fromarray(img).save(str(out_path))
            return page_num, img

        pages: dict[int, np.ndarray] = {}

        # Load already-cached processed pages
        for page_num in range(1, num_pages + 1):
            if page_num in rendered:
                continue
            cached = cv2.imread(str(pages_dir / f"page_{page_num}.png"))
            if cached is not None:
                pages[page_num] = cv2.cvtColor(cached, cv2.COLOR_BGR2RGB)

        if rendered:
            with ThreadPoolExecutor(max_workers=min(len(rendered), 6)) as pool:
                for page_num, img in pool.map(lambda kv: _process(*kv), rendered.items()):
                    pages[page_num] = img
        logger.info("Preprocessed %d pages → %s", len(pages), pages_dir)
        return pages

    def preprocess_images(
        self, image_paths: dict[int, str], output_dir: str
    ) -> dict[int, np.ndarray]:
        """Preprocess image files (deskew, optional color, downscale)."""
        from PIL import Image

        pages_dir = Path(output_dir) / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)

        use_color = os.environ.get("LLM_USE_COLOR_IMAGE", "true").lower() in ("1", "true", "yes")
        max_w = self.config.max_image_width
        pages: dict[int, np.ndarray] = {}

        for page_num in sorted(image_paths):
            src_path = image_paths[page_num]
            out_path = pages_dir / f"page_{page_num}.png"
            orig_path = pages_dir / f"page_{page_num}_original.png"

            arr = np.array(Image.open(src_path).convert("RGB"))

            if not orig_path.exists():
                Image.fromarray(arr).save(str(orig_path))

            if out_path.exists():
                cached = cv2.imread(str(out_path))
                if cached is not None:
                    pages[page_num] = cv2.cvtColor(cached, cv2.COLOR_BGR2RGB)
                    continue

            img = deskew(arr, self.config.deskew_max_angle)

            lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            l = clahe.apply(l)
            img = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2RGB)

            if not use_color:
                gray = denoise(to_grayscale(img), self.config.denoise_strength)
                img = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)

            if max_w and img.shape[1] > max_w:
                scale = max_w / img.shape[1]
                img = cv2.resize(img, (max_w, int(img.shape[0] * scale)), interpolation=cv2.INTER_AREA)

            Image.fromarray(img).save(str(out_path))
            pages[page_num] = img

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

        def _page_handwriting_tips(page: int) -> str:
            lines = []
            for label, tip in TEXT_FIELD_TIPS.items():
                for tpl in KNOWN_TEMPLATE_FIELDS:
                    if tpl["label"] == label and tpl["page"] == page:
                        lines.append(f"  {label}: {tip}")
                        break
            return "\n".join(lines) if lines else "  (none on this page)"

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
4. Radio → exact allowed option (e.g. "Male", "Yes", "Separate"). Checkbox → "Yes" if marked, "No" if empty. NEVER use "✓" or "✗".
5. Table → count pre-printed rows first. Every cell: "{{Table}} — Row {{n}} — {{Column}}".
6. Never invent values.

-------------------------------------------------------------------------------
REASONING INSTRUCTIONS — Apply these steps for each field
-------------------------------------------------------------------------------

### Mutually exclusive checkbox pairs (exactly ONE must be "Yes"):
  For 3.1 (Own/Rented), 3.4.1 (Separate/No Separate),
  4.3 (Yes/No), 3.5 (Separate/Common):
  STEP 1: Look at BOTH checkboxes. ONE should be marked.
  STEP 2: Output "Yes" for the marked option, "No" for the unmarked one.
  STEP 3: If BOTH appear marked → pick denser mark as "Yes".
  STEP 4: If NEITHER is clearly marked → use context clues:
    - 3.1: if rent amount is filled → Rented="Yes", Own="No"
    - 3.4.1: if bedrooms > 0 → Separate="Yes"
    - 4.3: if 4.3.1 table filled → Yes="Yes"
  STEP 5: NEVER output "No" for BOTH. Exactly one "Yes".

### Multi-select checkboxes (any subset can be "Yes", others "No"):
  For 2.4 (Govt ID), 3.2 (Home Type), 3.3 (Ceiling), 3.6 (Kitchen), 4.1 (Assets):
  STEP 1: Examine EACH checkbox independently.
  STEP 2: "Yes" = dark filled mark inside box. "No" = empty/clean box.
  STEP 3: Multiple "Yes" allowed.
  STEP 4: IF ALL OPTIONS ARE "No" — RE-EXAMINE. The form is usually partially filled. Look again for any tick or slash.
  STEP 5: For "Other(s)" fields, also capture handwritten text.

### Radio buttons (exactly ONE selected — output the option TEXT):
  For 1.3, 2.1, 2.3, 4.4, 4.5, 4.6, 5.1, 6.2, 6.3, 8.2:
  STEP 1: Find the filled radio circle (●) vs empty circles (○).
  STEP 2: Output the EXACT option text (e.g. "Male", "Having both parents", "Yes").
  STEP 3: NEVER output "✓" or "✗" for radio. Output the option text itself.
  STEP 4: A circle is ONLY "Yes" if it has a clear dot (●) or tick inside. An empty circle → the OTHER option is selected.
  STEP 5: For Yes/No radios (4.4, 4.6, 5.1, 2.3, 6.3): if both appear empty, default "No". NEVER output "Yes" for an empty circle.

### Numeric fields:
  For 4.4.1 Amount, 4.6.1 Loan Amount Taken/Pending:
  STEP 1: Extract only digits and decimal point. Strip ₹, commas, Rs, words.
  STEP 2: Handwriting digit disambiguation — 'l' or 'I' is usually '1'; 'O' or 'o' is usually '0'; 'S' or 's' is usually '5'; 'Z' or 'z' is usually '2'.
  STEP 3: If value is wholly non-numeric, output "" (empty) — don't guess.

### Text fields that commonly capture wrong text:
  For 4.7 (college fee), 4.8 (manage higher fee), 4.9 (manage without scholarship):
  STEP 1: The printed question text (e.g. "If you choose any college, how much is the college fee?") is the LABEL — do NOT emit it as the value.
  STEP 2: Look at the HANDWRITTEN answer below/after the label. That is the value.
  STEP 3: For 4.7 specifically: capture the COMPLETE handwritten college name AND fee amount together (e.g. "RITE Institute Engineering College - 50000"). Do NOT drop the text portion.
  STEP 4: If the blank is empty, output "" — do not repeat nearby text.

### Table fields (count pre-printed rows, fill every cell):
  For 2.5 (Family Members), 4.3.1 (Properties), 4.4.1 (Other Income), 4.6.1 (Loans):
  STEP 1: Count ALL pre-printed rows. 2.5 usually has 5 rows.
  STEP 2: Label = "{{Table label}} — Row {{n}} — {{Column}}".
  STEP 3: Parent "No" → ALL cells = "N/A". Parent "Yes" or unclear → extract.
  STEP 4: For 4.3.1, 4.4.1, 4.6.1 — use the EXACT labels from PAGE FIELD LIST below.

### Conditional dependencies — hard rule:
  Parent field = "No" or "✗" → ALL child fields = "N/A", UNLESS child field has visible handwritten text.
  Key dependencies:
    3.1.1 rent amount → ALWAYS look for handwritten text FIRST. If text exists, extract it regardless of 3.1 selection. Only output "N/A" if the 3.1.1 blank is COMPLETELY empty AND 3.1 Own is checked.
    4.3.1 properties → depends on 4.3 Yes = ✓
    4.4.1 income → depends on 4.4 = Yes
    4.6.1 loans → depends on 4.6 = Yes
    5.2 health issues → depends on 5.1 = Yes

-------------------------------------------------------------------------------
CORE OUTPUT SCHEMA (keep output compact — do NOT add extra keys):
{{
  "sections": {json.dumps(sections_on_page)},
  "fields": [
    {{
      "label":  string  — exact label from FIELD LIST below,
      "value":  string  — "" | "N/A" | extracted text,
      "confidence": 0-100,
      "page":  {page},  "section":  int|null,  "needs_clarification": bool,
      "reason":  string|null  — ONLY when needs_clarification is true, else omit,
      "position_hint": "same_line_colon"|"right_of_label"|...
    }}
  ],
  "overall_confidence": 0-100,
  "clarification_needed": ["label1", "label2", ...],
  "raw_text": "concise transcription of this page — labels + filled values only, skip long pre-printed instructions"
}}

FIELD LIST FOR PAGE {page}:
{PAGE_FIELD_MAPPINGS.get(page, "")}

--- HANDWRITING TIPS for text fields on this page ---
{_page_handwriting_tips(page)}
'''

        # Two-stage extraction: vision model does OCR text, text model does structured JSON.
        # Only needed for local VL models that can't reliably emit JSON directly.
        # Capable vision models (e.g. gpt-4o-mini) use the faster single-stage path below.
        two_stage_mode = os.environ.get("TWO_STAGE_EXTRACTION", "auto").lower()
        primary_is_local_vl = "vl" in getattr(self.primary_client, "model_name", "").lower()
        use_two_stage = two_stage_mode == "on" or (two_stage_mode == "auto" and primary_is_local_vl)
        if num_pages == 6 and self.primary_client.needs_images and self.secondary_client is not None and use_two_stage:
            from src.prompt_templates import PRIMARY_OCR_PROMPT, TEXT_EXTRACTION_PROMPT, PAGE_FIELD_MAPPINGS

            logger.info("Stage 1 — extracting OCR text from %d pages via vision model...", num_pages)
            pages = sorted(page_images.keys())
            ocr_concurrency = max(1, int(os.environ.get("OCR_PAGE_CONCURRENCY", "1")))
            ocr_sem = asyncio.Semaphore(ocr_concurrency)

            async def _ocr_page(p: int) -> str:
                async with ocr_sem:
                    prompt = f"--- Page {p} ---\n\n{PRIMARY_OCR_PROMPT}"
                    return await self.primary_client.extract_raw_text(None, {p: page_images[p]}, prompt)

            ocr_results = await asyncio.gather(*(_ocr_page(p) for p in pages), return_exceptions=True)

            page_texts: dict[int, str] = {}
            for idx, res in enumerate(ocr_results):
                page = pages[idx]
                if isinstance(res, Exception):
                    logger.error("OCR failed for page %d: %s", page, res)
                    page_texts[page] = ""
                    continue
                page_texts[page] = str(res or "")

            combined_text = "\n\n".join(f"--- Page {p} ---\n{page_texts.get(p, '')}" for p in pages)
            logger.info("Combined OCR text: %d chars across %d pages", len(combined_text), len(page_texts))

            logger.info("Stage 2 — extracting structured fields from combined OCR text via text model...")
            section_names = {
                1: "Student Profile", 2: "Family Background", 3: "Housing Condition",
                4: "Financial Background", 5: "Health Information", 6: "Student Commitment",
                7: "Scholarship Information", 8: "Volunteer Observation",
            }
            section_pages: dict[int, set[int]] = {}
            for tpl in KNOWN_TEMPLATE_FIELDS:
                sn = tpl.get("section_number")
                if sn is None:
                    continue
                section_pages.setdefault(sn, set()).add(tpl["page"])

            extraction_prompt = (
                f"{TEXT_EXTRACTION_PROMPT}\n\n"
                f"OCR TEXT (all 6 pages):\n{combined_text}\n\n"
                f"FIELD LIST FOR PAGE 1:\n{PAGE_FIELD_MAPPINGS.get(1, '')}\n"
                f"FIELD LIST FOR PAGE 2:\n{PAGE_FIELD_MAPPINGS.get(2, '')}\n"
                f"FIELD LIST FOR PAGE 3:\n{PAGE_FIELD_MAPPINGS.get(3, '')}\n"
                f"FIELD LIST FOR PAGE 4:\n{PAGE_FIELD_MAPPINGS.get(4, '')}\n"
                f"FIELD LIST FOR PAGE 5:\n{PAGE_FIELD_MAPPINGS.get(5, '')}\n"
                f"FIELD LIST FOR PAGE 6:\n{PAGE_FIELD_MAPPINGS.get(6, '')}\n"
            )
            text_data, text_usage = await self.secondary_client.extract_structured("", {}, extraction_prompt)

            if text_data and text_data.get("fields"):
                coverage, confidence = self._compute_coverage_confidence(text_data["fields"])
                logger.info("Stage 2 OK — text model extracted %d fields (coverage=%d%%, confidence=%d%%)",
                            len(text_data["fields"]), coverage, confidence)
                text_data["sections"] = [
                    {"number": sn, "name": section_names.get(sn, f"Section {sn}"), "page": min(sp)}
                    for sn, sp in sorted(section_pages.items())
                ]
                text_data["coverage"] = coverage
                text_data["confidence"] = confidence
                text_data["overall_confidence"] = round(coverage * confidence / 100) if coverage and confidence else 0
                return text_data, text_usage

            logger.warning("Two-stage extraction produced no fields — falling through to direct extraction")

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

            section_names = {
                1: "Student Profile",
                2: "Family Background",
                3: "Housing Condition",
                4: "Financial Background",
                5: "Health Information",
                6: "Student Commitment",
                7: "Scholarship Information",
                8: "Volunteer Observation",
            }
            section_pages: dict[int, set[int]] = {}
            for tpl in KNOWN_TEMPLATE_FIELDS:
                sn = tpl.get("section_number")
                if sn is None:
                    continue
                section_pages.setdefault(sn, set()).add(tpl["page"])
            merged_data = {
                "sections": [
                    {"number": sn, "name": section_names.get(sn, f"Section {sn}"), "page": min(pages)}
                    for sn, pages in sorted(section_pages.items())
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

    async def run_combined_extraction(self, pdf_path: str, page_images: dict[int, str]) -> tuple[dict | None, dict]:
        """All pages in a single LLM call — dramatically reduces token overhead."""
        from src.prompt_templates import PAGE_FIELD_MAPPINGS

        pages = sorted(page_images.keys())
        num_pages = len(pages)
        if num_pages < 2:
            return await self.run_primary_extraction(pdf_path, page_images)

        sections_guide = {
            1: "Page 1 — Header (null) + Section 1 (Student Profile) + Section 2 (Family Background)",
            2: "Page 2 — Section 2 (Family Background cont.) + Section 3 (Housing Condition)",
            3: "Page 3 — Section 3 (Housing Condition cont.) + Section 4 (Financial Background)",
            4: "Page 4 — Section 4 (Financial Background)",
            5: "Page 5 — Section 4 (Financial Background cont.) + Section 5 (Health) + Section 6 (Student Commitment)",
            6: "Page 6 — Section 6 (Student Commitment cont.) + Section 7 (Scholarship) + Section 8 (Volunteer Observation)",
        }

        combined_field_list = ""
        for p in pages:
            guide = sections_guide.get(p, f"Page {p}")
            combined_field_list += f"\n--- {guide} ---\n"
            combined_field_list += PAGE_FIELD_MAPPINGS.get(p, "")

        section_names = {
            1: "Student Profile", 2: "Family Background", 3: "Housing Condition",
            4: "Financial Background", 5: "Health Information", 6: "Student Commitment",
            7: "Scholarship Information", 8: "Volunteer Observation",
        }
        section_pages: dict[int, set[int]] = {}
        for tpl in KNOWN_TEMPLATE_FIELDS:
            sn = tpl.get("section_number")
            if sn is None:
                continue
            section_pages.setdefault(sn, set()).add(tpl["page"])
        sections_json = [
            {"number": sn, "name": section_names.get(sn, f"Section {sn}"), "page": min(ps)}
            for sn, ps in sorted(section_pages.items())
        ]

        prompt = f'''You are a trusted form extraction engine for the complete 6-page "I Am The Change — Home Visit Questionnaire".
You will receive {num_pages} page images. Extract ALL fields from ALL pages. Never skip any field.

GROUND RULES:
1. Extract EVERY field listed in FIELD LIST BY PAGE below. Every label must appear in output, even if empty.
2. Labels MUST EXACTLY match the field list including numbers (e.g. "1.2 Student Full Name"). Do NOT alter.
3. value="" for unreadable/missing. value="N/A" when parent="No". Never "null".
 4. Checkbox → "Yes" if a tick (✓) or slash (/) is INSIDE/BESIDE the box; "No" if empty/cross/scribble/dot. If a box has BOTH tick and cross, the tick wins → "Yes". A tick/slash drawn ON TOP OF the option text is a stray annotation — ignore it (empty box = unselected); a cross under/beside the box = deselected.
5. Radio → exact option text (e.g. "Male", "Having both parents"). Never "✓" or "✗".
6. Table → "{{Table}} — Row {{n}} — {{Column}}" (e.g. "2.5 Family Members — Row 1 — Name").
7. Conditionals: parent="No" → child="N/A". Dependencies: rent→3.1, 4.3/4.4/4.6→4.3.1/4.4.1/4.6.1, health→5.1.
8. Never invent values. Only text visible on the images.

REASONING — Apply per field type:
- Mutually-exclusive pairs (Own/Rented, Separate/No Separate Bedroom, Yes/No for 4.3, Separate/Common for Bathroom): exactly ONE marked. Use context clues (filled rent→Rented=Yes, bedrooms>0→Separate=Yes).
- Multi-select (2.4 Govt ID, 3.2 Home Type, 3.3 Ceiling, 3.6 Kitchen, 4.1 Assets): each checkbox independent. Default ambiguous="No".
- Numerics (4.4.1 Amount, 4.6.1 Loan): digits+decimal only. Strip ₹, commas, Rs.
- 4.7: capture COMPLETE handwritten college name + fee amount together. Do NOT drop the text.
- Table rows: count ALL pre-printed rows (2.5 usually 5). Every cell filled.
- Other(s) fields: also capture handwritten text.

Output ONLY valid JSON. No markdown fences. No explanations. ONLY the JSON object.
{{
  "sections": {json.dumps(sections_json)},
  "fields": [
    {{"label": string, "value": string, "confidence": 0-100, "page": N, "section": int|null, "needs_clarification": bool, "reason": string|null}}
  ],
  "overall_confidence": 0-100,
  "clarification_needed": ["label1", ...],
  "raw_text": "concise per-page transcription — labels + values only, skip long pre-printed instructions"
}}

FIELD LIST BY PAGE:
{combined_field_list}
'''
        data, token_usage = await self.primary_client.extract_structured(pdf_path, page_images, prompt)
        token_usage["calls"] = 1

        if data and isinstance(data, dict):
            fields = data.get("fields", [])
            if fields:
                coverage, confidence = self._compute_coverage_confidence(fields)
                data["coverage"] = coverage
                data["confidence"] = confidence
                data["overall_confidence"] = round(coverage * confidence / 100) if coverage and confidence else data.get("overall_confidence", 0)
                data["sections"] = sections_json

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
        return label in ExtractionPipeline.CHECKBOX_LABELS

    @staticmethod
    def _fix_mutual_exclusivity(fields: list[StructuredField]) -> list[StructuredField]:
        mutual_pairs = [
            ("3.1 House Ownership — Own", "3.1 House Ownership — Rented", "3.1.1 If rented, what is the rent amount?"),
            ("3.4.1 Type of Bedroom — Separate Bedroom", "3.4.1 Type of Bedroom — No Separate Bedroom", "3.4 Number of Bedrooms"),
            ("3.5 Bathroom - Separate", "3.5 Bathroom - Common for Apartment", None),
            ("4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes",
             "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — No",
             "4.3.1 If Yes, list their properties: - Property Description"),
        ]
        fmap = {f.label: f for f in fields}
        for opt_a, opt_b, clue_label in mutual_pairs:
            f_a = fmap.get(opt_a)
            f_b = fmap.get(opt_b)
            if not f_a or not f_b:
                continue
            val_a = f_a.value.strip()
            val_b = f_b.value.strip()
            a_no = val_a in ("No", "✗", "", "N/A")
            b_no = val_b in ("No", "✗", "", "N/A")
            a_yes = val_a in ("Yes", "✓")
            b_yes = val_b in ("Yes", "✓")
            if a_yes and b_yes:
                logger.warning("Mutual exclusivity violation: both %s and %s are Yes — fixing", opt_a, opt_b)
                f_a.value = "No"
                f_a.confidence = 60
                f_a.reason = "Corrected: mutual exclusivity"
            if not a_yes and not b_yes:
                if clue_label and clue_label in fmap:
                    clue_val = fmap[clue_label].value.strip()
                    if clue_val and clue_val not in ("N/A", ""):
                        f_a.value = "No"
                        f_b.value = "Yes"
                        f_b.confidence = 65
                        f_b.reason = "Corrected: inferred from context clue"
                        continue
                logger.warning("Mutual exclusivity: neither %s nor %s is Yes — keeping as-is (both No)", opt_a, opt_b)
        return fields

    CHECKBOX_LABELS: set[str] = {
        "2.4 Government ID Verified — Aadhaar Card",
        "2.4 Government ID Verified — Ration Card",
        "2.4 Government ID Verified — Driving Licence",
        "2.4 Government ID Verified — Voter ID",
        "2.4 Government ID Verified — Other",
        "3.1 House Ownership — Own", "3.1 House Ownership — Rented",
        "3.2 Type of Home — Individual", "3.2 Type of Home — Private Apartment",
        "3.2 Type of Home — Housing Board",         "3.2 Type of Home — Line House",
        "3.3 Type of Ceiling — Roof (Kurai)", "3.3 Type of Ceiling — Tiled",
        "3.3 Type of Ceiling — Asbestos / Sheet", "3.3 Type of Ceiling — Concrete",
        "3.4.1 Type of Bedroom — Separate Bedroom", "3.4.1 Type of Bedroom — No Separate Bedroom",
        "3.5 Bathroom - Separate", "3.5 Bathroom - Common for Apartment",
        "3.6 Kitchen Type — Separate Kitchen", "3.6 Kitchen Type — Hall with Kitchen",
        "4.1 Assets at Home(tick all that apply) - Washing Machine",
        "4.1 Assets at Home(tick all that apply) - Fridge",
        "4.1 Assets at Home(tick all that apply) - AC",
        "4.1 Assets at Home(tick all that apply) - LED TV",
        "4.1 Assets at Home(tick all that apply) - Two-Wheeler",
        "4.1 Assets at Home(tick all that apply) - Car",
        "4.1 Assets at Home(tick all that apply) - Smartphone",
        "4.1 Assets at Home(tick all that apply) - Separate Wi-Fi",
        "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes",
        "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — No",
    }

    @staticmethod
    def _sanitize_checkbox_values(fields: list[StructuredField]) -> list[StructuredField]:
        valid = {"Yes", "No", "N/A", ""}
        for f in fields:
            if f.label not in ExtractionPipeline.CHECKBOX_LABELS:
                continue
            if f.value in valid:
                continue
            logger.warning("Sanitizing checkbox '%s': value '%s' → No", f.label, f.value)
            f.value = "No"
            f.confidence = max(f.confidence, 30)
            f.needs_clarification = True
            f.reason = "Corrected: raw text replaced with No"
        return fields

    @staticmethod
    def _fix_concatenated_parents(fields: list[StructuredField]) -> list[StructuredField]:
        parent_keys = {
            "2.4 Government ID Verified",
        }
        for f in fields:
            if f.label in parent_keys and len(f.value) > 10:
                logger.warning("Clearing concatenated parent '%s': value='%s'", f.label, f.value)
                f.value = ""
        return fields

    @staticmethod
    def fill_missing_template_fields(fields: list[StructuredField], pdf_path: str | None = None, provider: str = "") -> list[StructuredField]:
        fields = ExtractionPipeline._sanitize_checkbox_values(fields)
        fields = ExtractionPipeline._fix_concatenated_parents(fields)
        fields = ExtractionPipeline._detect_concatenated_parents(fields)
        if pdf_path and provider != "gemini":
            try:
                fields = ExtractionPipeline._cv_checkbox_verify(fields, pdf_path)
            except Exception as e:
                logger.warning("CV checkbox verification failed (non-fatal): %s", e)
        fields = ExtractionPipeline._fix_mutual_exclusivity(fields)
        fields = ExtractionPipeline._validate_checkbox_groups(fields)
        fields = ExtractionPipeline._clean_numeric_fields(fields)
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

    @staticmethod
    def _gemini_post_process(fields: list[StructuredField]) -> list[StructuredField]:
        for f in fields:
            label = f.label or ""
            val = (f.value or "").strip()

            # 3.1.1 rent amount: if LLM stripped currency, restore full format
            if "rent amount" in label.lower() and val and val not in ("N/A", ""):
                has_currency = any(c in val for c in ("₹", "Rs", "rs", "/-", "$"))
                if not has_currency and re.match(r'^[\d,.\s]+$', val):
                    clean = val.strip().rstrip('/').strip()
                    wrapped = f"Rs {clean}/-"
                    if wrapped != val:
                        logger.info("Gemini rent format: %r → %r", val, wrapped)
                        f.original_value = val
                        f.value = wrapped

            # Merge blank_text_below_2_1 into 2.2 Reason for Death / Separation
            if label == "blank_text_below_2_1" and val:
                reason_field = next(
                    (x for x in fields
                     if x.label == "2.2 Relationship Details — Reason for Death / Separation"),
                    None
                )
                if reason_field:
                    current = (reason_field.value or "").strip()
                    if val not in current:
                        merged = f"{current} — {val}" if current else val
                        logger.info("Gemini 2.2 merge: blank_text_below_2_1 → Reason for Death / Separation")
                        reason_field.original_value = reason_field.value
                        reason_field.value = merged
                # Clear the blank_text field since it's merged
                f.value = ""
                f.confidence = 100
                f.needs_clarification = False

            # Merge blank_text_below_4_3 / blank_text_below_4_3_1_table into
            # 4.3.1 Property Description as extra table rows.
            if label in ("blank_text_below_4_3", "blank_text_below_4_3_1_table") and val:
                ExtractionPipeline._merge_blank_into_4_3_1(fields, val)
                f.value = ""
                f.confidence = 100
                f.needs_clarification = False

        return fields

    @staticmethod
    def _merge_blank_into_4_3_1(fields: list[StructuredField], text: str) -> None:
        """Append handwritten free-text (from below 4.3 / below 4.3.1 table)
        as a new 4.3.1 table row with the text in Property Description."""
        base = "4.3.1 If Yes, list their properties:"
        max_row = 0
        has_flat = False
        for f in fields:
            if f.label.startswith("4.3.1"):
                m = re.search(r"Row\s+(\d+)", f.label)
                if m:
                    max_row = max(max_row, int(m.group(1)))
                else:
                    has_flat = True
        if has_flat:
            max_row = max(max_row, 1)
        new_row = max_row + 1
        logger.info("Gemini 4.3.1 merge: blank area → Row %d Property Description", new_row)
        for col in ("Property Description", "Owner Name", "Approximate Value"):
            fields.append(StructuredField(
                label=f"{base} — Row {new_row} — {col}",
                value=text if col == "Property Description" else "",
                confidence=80,
                page=4,
                section_number=4,
                extracted_by="gemini_post_process",
            ))

    @staticmethod
    def _cv_checkbox_verify(fields: list[StructuredField], pdf_path: str) -> list[StructuredField]:
        from src.checkbox_vision import CHECKBOX_COORDS, _crop_checkbox, _classify_checkbox_mark

        label_to_coords_key: dict[str, str] = {
            "2.4 Government ID Verified — Aadhaar Card": "govt_id_aadhaar",
            "2.4 Government ID Verified — Ration Card": "govt_id_ration",
            "2.4 Government ID Verified — Driving Licence": "govt_id_driving_licence",
            "2.4 Government ID Verified — Voter ID": "govt_id_voter",
            "2.4 Government ID Verified — Other": "govt_id_other",

            "3.1 House Ownership — Own": "house_ownership_own",
            "3.1 House Ownership — Rented": "house_ownership_rented",

            "3.2 Type of Home — Individual": "home_type_individual",
            "3.2 Type of Home — Private Apartment": "home_type_private_apartment",
            "3.2 Type of Home — Housing Board": "home_type_housing_board",
            "3.2 Type of Home — Line House": "home_type_line_house",

            "3.3 Type of Ceiling — Roof (Kurai)": "ceiling_roof",
            "3.3 Type of Ceiling — Tiled": "ceiling_tiled",
            "3.3 Type of Ceiling — Asbestos / Sheet": "ceiling_asbestos",
            "3.3 Type of Ceiling — Concrete": "ceiling_concrete",

            "4.1 Assets at Home(tick all that apply) - Washing Machine": "asset_washing_machine_checkbox",
            "4.1 Assets at Home(tick all that apply) - Fridge": "asset_fridge_checkbox",
            "4.1 Assets at Home(tick all that apply) - AC": "asset_ac_checkbox",
            "4.1 Assets at Home(tick all that apply) - LED TV": "asset_led_tv_checkbox",
            "4.1 Assets at Home(tick all that apply) - Two-Wheeler": "asset_two_wheeler_checkbox",
            "4.1 Assets at Home(tick all that apply) - Car": "asset_car_checkbox",
            "4.1 Assets at Home(tick all that apply) - Smartphone": "asset_smartphone_checkbox",
            "4.1 Assets at Home(tick all that apply) - Separate Wi-Fi": "asset_separate_wifi_checkbox",
        }

        extra_coords: dict[str, tuple[int, float, float, float, float]] = {
            "house_ownership_own": (2, 172.0, 375.0, 10.0, 13.0),
            "house_ownership_rented": (2, 277.0, 370.0, 10.0, 10.0),
        }

        page_images = _load_page_images_cv(pdf_path)
        dpi = 200
        overrides = 0

        import cv2 as _cv2
        import numpy as _np

        for f in fields:
            coords_key = label_to_coords_key.get(f.label)
            if coords_key is None:
                continue
            coords = CHECKBOX_COORDS.get(coords_key) or extra_coords.get(coords_key)
            if coords is None:
                continue
            roi = _crop_checkbox(page_images, *coords, dpi)
            if roi is None:
                continue
            # Sanity check: crop should have checkbox-level density (4-35% dark)
            # Higher density = text/form line; lower = blank/missed crop
            _, _bin = _cv2.threshold(roi, 0, 255, _cv2.THRESH_BINARY_INV + _cv2.THRESH_OTSU)
            _dark_ratio = float(_cv2.countNonZero(_bin)) / max(_bin.size, 1)
            if _dark_ratio > 0.35:
                logger.debug("CV skip %r: ROI too dense (%.2f) — likely not a checkbox", f.label, _dark_ratio)
                continue
            cv_class = _classify_checkbox_mark(roi)
            llm_val = f.value.strip()

            if cv_class == "tick" and llm_val not in ("Yes", "✓"):
                logger.info("CV override %r: LLM=%r → Yes (CV=tick)", f.label, f.value)
                f.original_value = f.value if f.value not in ("No", "N/A", "") else None
                f.value = "Yes"
                f.confidence = 85
                f.reason = "Corrected: CV detected tick mark"
                f.needs_clarification = False
                overrides += 1
            elif cv_class == "empty" and llm_val not in ("No", "N/A", ""):
                logger.info("CV override %r: LLM=%r → No (CV=empty)", f.label, f.value)
                f.original_value = f.value if f.value not in ("Yes", "✓") else None
                f.value = "No"
                f.confidence = 80
                f.reason = "Corrected: CV detected empty checkbox"
                f.needs_clarification = False
                overrides += 1
            elif cv_class in ("cross", "unknown") and llm_val not in ("No", "N/A", ""):
                logger.warning("CV flagged %r: LLM=%r but CV=%s — marking for review", f.label, f.value, cv_class)
                f.needs_clarification = True
                f.reason = "CV disagrees with LLM: detected {}".format(cv_class)

        if overrides:
            logger.info("CV checkbox verification: %d field(s) overridden", overrides)
        else:
            logger.info("CV checkbox verification: no overrides needed")
        return fields

    @staticmethod
    def _validate_checkbox_groups(fields: list[StructuredField]) -> list[StructuredField]:
        """Detect all-No or suspicious single-No multi-select checkbox groups."""
        GROUPS: list[tuple[str, str]] = [
            ("2.4 Government ID Verified", "2.4"),
            ("3.2 Type of Home", "3.2"),
            ("3.3 Type of Ceiling", "3.3"),
            ("3.6 Kitchen Type", "3.6"),
            ("4.1 Assets at Home", "4.1"),
        ]
        for group_label, prefix in GROUPS:
            group = [f for f in fields if f.label.startswith(prefix) and not f.label.startswith(prefix + ".1")]
            if not group:
                continue
            yes_count = sum(1 for f in group if f.value in ("Yes", "✓"))
            no_count = sum(1 for f in group if f.value in ("No", "", None))
            if yes_count == 0 and no_count == len(group):
                for f in group:
                    if f.confidence is None or f.confidence > 50:
                        f.confidence = max(f.confidence or 50, 50)
                    f.needs_clarification = True
                    f.reason = f"All {len(group)} checkboxes in {group_label} are No — possible missed mark"
                logger.warning("All-No group detected: %s (%d checkboxes)", group_label, len(group))
            elif yes_count >= len(group) - 2 and no_count >= 1 and len(group) >= 4:
                no_fields = [f for f in group if f.value in ("No", "", None)]
                if len(no_fields) == 1:
                    no_fields[0].needs_clarification = True
                    no_fields[0].reason = f"Suspicious No — {yes_count}/{len(group)} are Yes in {group_label}, this field likely has a missed mark"
                    no_fields[0].confidence = min(no_fields[0].confidence, 50)
                    logger.warning("Suspicious single-No in %s: %r (yes_count=%d/%d)",
                                   group_label, no_fields[0].label, yes_count, len(group))
        return fields

    @staticmethod
    def _clean_numeric_fields(fields: list[StructuredField]) -> list[StructuredField]:
        """Strip non-numeric characters from numeric-only fields, handling commas as thousands separators."""
        NUMERIC_PREFIXES = ["3.4 ", "4.4.1", "4.6.1"]
        for f in fields:
            val = f.value
            if not val or val in ("N/A", "", None):
                continue
            for prefix in NUMERIC_PREFIXES:
                if f.label.startswith(prefix):
                    raw = val.replace('₹', '').replace('Rs', '').replace('rs', '').strip()
                    if ',' in raw:
                        parts = raw.split(',')
                        if len(parts) == 2 and len(parts[1]) == 3 and parts[1].isdigit() and parts[0].replace('.', '', 1).isdigit():
                            cleaned = parts[0] + parts[1]
                        else:
                            cleaned = re.sub(r'[^\d.]', '', raw.replace(',', ''))
                    else:
                        cleaned = re.sub(r'[^\d.]', '', raw)
                    cleaned = cleaned.lstrip('.').strip()
                    if cleaned != val and cleaned:
                        f.original_value = val
                        f.value = cleaned
                        logger.info("Numeric cleanup %r: %r → %r", f.label, val, cleaned)
                    break
        return fields

    @staticmethod
    def _detect_concatenated_parents(fields: list[StructuredField]) -> list[StructuredField]:
        """Detect fields where LLM merged parent+child into single label:value."""
        PARENT_CHILD_MAP = {
            "4.3": "4.3.1 If Yes, list their properties",
            "4.4": "4.4.1 If Yes, list other sources of income",
            "4.6": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount",
        }
        for f in fields:
            val = f.value or ""
            for parent_prefix, child_prefix in PARENT_CHILD_MAP.items():
                if not f.label.startswith(parent_prefix):
                    continue
                if val.lower() in ("yes", "no") or not val:
                    continue
                if len(val) > 20 and val.lower() not in ("yes", "no"):
                    logger.info("Concatenated parent detected: %r → value=%r (splitting)", f.label, val)
                    f.original_value = val
                    f.value = "Yes"
                    f.reason = "Derived from concatenated value"
                break
        return fields

    @staticmethod
    def _find_all_no_groups(fields: list[StructuredField]) -> list[list[StructuredField]]:
        """Find checkbox groups where all fields are No (possible missed marks)."""
        GROUPS = [
            ("2.4", "2.4.1"),
            ("3.2", "3.2.1"),
            ("3.3", "3.3.1"),
            ("3.6", "3.6.1"),
            ("4.1", "4.1.1"),
        ]
        result: list[list[StructuredField]] = []
        for prefix, exclude_prefix in GROUPS:
            group = [f for f in fields if f.label.startswith(prefix) and not f.label.startswith(exclude_prefix)]
            if not group:
                continue
            if all(f.value in ("No", "", None) for f in group):
                result.append(group)
        return result

    @staticmethod
    async def _recheck_checkbox_groups(
        fields: list[StructuredField],
        pdf_path: str,
        processed_images: dict[int, str],
        client,
    ) -> list[StructuredField]:
        """Re-check all-No checkbox groups with the LLM using page images."""
        all_no_groups = ExtractionPipeline._find_all_no_groups(fields)
        field_map = {f.label: f for f in fields}

        for group in all_no_groups:
            pages = sorted({f.page for f in group if f.page})
            if not pages:
                continue
            group_pages = {p: processed_images[p] for p in pages if p in processed_images}
            if not group_pages:
                continue
            group_prefix = group[0].label.split("—")[0].strip() if "—" in group[0].label else group[0].label[:4]
            field_list = "\n".join(f"  - {f.label}" for f in group)
            prompt = (
                f"Re-examine the checkboxes on page(s) {list(group_pages.keys())} in the group '{group_prefix}'. "
                f"The following fields were all marked as 'No' but this group should have at least one 'Yes':\n"
                f"{field_list}\n\n"
                f"Answer with ONLY valid JSON: {{\"fields\": [{{\"label\": \"...\", \"value\": \"Yes|No\"}}, ...]}}"
            )
            try:
                data, _ = await client.extract_structured(pdf_path, group_pages, prompt)
                if data and "fields" in data:
                    for entry in data["fields"]:
                        label = entry.get("label", "")
                        value = entry.get("value", "")
                        if label in field_map and value in ("Yes", "No"):
                            f = field_map[label]
                            if f.value != value:
                                logger.info("Re-check override %r: %r → %r", label, f.value, value)
                                f.original_value = f.value
                                f.value = value
                                f.confidence = 75
                                f.needs_clarification = False
                                f.reason = "Corrected by LLM re-check"
            except Exception as e:
                logger.warning("Re-check failed for group on page(s) %s: %s", pages, e)

        return fields

    @staticmethod
    def _is_text_field_candidate(field: StructuredField) -> bool:
        """Check if field is a handwritten text field needing refinement."""
        label = field.label
        if label in ExtractionPipeline.CHECKBOX_LABELS:
            return False
        radio_labels = {
            "1.3 Gender", "2.1 Family Status", "2.3 Is Father/Mother photograph kept at home?",
            "3.5 Bathroom - Separate", "3.5 Bathroom - Common for Apartment",
            "4.4 Apart from your job, is there any other source of income?",
            "4.5 Income Type", "4.6 Do you have any loans?",
            "5.1 Does the student have any health issues?",
            "6.2 If we have a training program within 15 km from your home, can you come?",
            "6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)?",
            "8.2 Will you recommend this student for this scholarship?",
        }
        if label in radio_labels:
            return False
        if label in TEXT_FIELD_TIPS:
            return True
        table_text_prefixes = [
            "2.5 Family Members — Row", "4.3.1", "4.4.1", "4.6.1",
        ]
        for prefix in table_text_prefixes:
            if label.startswith(prefix):
                return True
        return False

    @staticmethod
    def _needs_refinement(field: StructuredField) -> bool:
        if not field.value or field.value in ("N/A", ""):
            return True
        if field.confidence < 70:
            return True
        if field.needs_clarification:
            return True
        return False

    @staticmethod
    async def _refine_text_fields(
        fields: list[StructuredField],
        pdf_path: str,
        processed_images: dict[int, str],
        client,
    ) -> list[StructuredField]:
        refinable = [f for f in fields if ExtractionPipeline._is_text_field_candidate(f) and ExtractionPipeline._needs_refinement(f)]
        if not refinable:
            logger.info("Text field refinement: no fields need re-reading")
            return fields

        logger.info("Text field refinement: %d field(s) need re-reading", len(refinable))
        field_map = {f.label: f for f in fields}

        fields_by_page: dict[int, list[StructuredField]] = {}
        for f in refinable:
            p = f.page or 1
            fields_by_page.setdefault(p, []).append(f)

        for page, page_fields in fields_by_page.items():
            page_images = {page: processed_images.get(page)}
            if not page_images[page]:
                continue

            field_list = "\n".join(
                f"  - {f.label}: {TEXT_FIELD_TIPS.get(f.label, 'Extract the handwritten text value accurately')}"
                for f in page_fields
            )
            current_values = "\n".join(
                f"  - {f.label}: current_value={f.value!r}"
                for f in page_fields
            )
            prompt = (
                f"Re-examine Page {page} of the Home Visit Questionnaire.\n\n"
                f"I need you to re-read ONLY the following handwritten text fields on this page. "
                f"These fields currently have missing or low-confidence values.\n\n"
                f"Fields to re-read:\n{field_list}\n\n"
                f"Current (possibly incomplete) values:\n{current_values}\n\n"
                f"HANDWRITING RULES:\n"
                f"- Read each character individually\n"
                f"- 'l'/'I'→'1', 'O'/'o'→'0', 'S'→'5', 'Z'→'2'\n"
                f"- 'n'↔'u', 'a'↔'o', 'l'↔'t', 'r'↔'v'\n"
                f"- Printed question text = LABEL, NOT the value\n"
                f"- Look at the blank AFTER the label — that is the handwritten answer\n"
                f"- For 4.7 (college fee): capture the COMPLETE handwritten answer including college name AND fee amount together (e.g. \"guru nanak college rs 30000/-per year\"). Do NOT drop any part.\n"
                f"- If truly empty → value=\"\"\n\n"
                f"Output ONLY valid JSON:\n"
                f"{{\"fields\": [{{\"label\": \"exact label from above\", \"value\": \"extracted text\"}}, ...]}}"
            )

            try:
                data, _ = await client.extract_structured(pdf_path, page_images, prompt)
                if data and "fields" in data:
                    for entry in data["fields"]:
                        label = entry.get("label", "")
                        value = entry.get("value", "")
                        if label in field_map and value:
                            f = field_map[label]
                            old_val = f.value
                            if value != old_val:
                                was_blank = not old_val or old_val in ("N/A", "")
                                logger.info("Text refinement %r: %r → %r", label, old_val, value)
                                f.original_value = old_val
                                f.value = value
                                f.confidence = max(f.confidence, 80)
                                f.needs_clarification = False
                                f.reason = "Refined by focused re-read"
            except Exception as e:
                logger.warning("Text field refinement failed for page %d: %s", page, e)

        refined_count = sum(1 for f in refinable if f.reason == "Refined by focused re-read")
        logger.info("Text field refinement: %d/%d fields updated", refined_count, len(refinable))
        return fields
