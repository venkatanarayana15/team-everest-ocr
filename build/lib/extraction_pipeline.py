import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from rapidfuzz import fuzz

from src.backends import WordBox, get_backend
from src.config import Config
from src.model_client import ModelClient, get_model_client
from src.preprocessing import deskew, denoise, to_grayscale

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
    {"label": "3.3 Type of Ceiling — Roof", "section_number": 3, "page": 3},
    {"label": "3.3 Type of Ceiling — Tiled", "section_number": 3, "page": 3},
    {"label": "3.3 Type of Ceiling — Asbestos", "section_number": 3, "page": 3},
    {"label": "3.3 Type of Ceiling — Concrete", "section_number": 3, "page": 3},
    {"label": "3.4 Number of Bedrooms", "section_number": 3, "page": 3},
    {"label": "3.4.1 Type of Bedroom", "section_number": 3, "page": 3},
    {"label": "3.5 Bathroom", "section_number": 3, "page": 3},
    {"label": "3.6 Kitchen Type — Separate Kitchen", "section_number": 3, "page": 3},
    {"label": "3.6 Kitchen Type — Hall with Kitchen", "section_number": 3, "page": 3},
    # Section 4 — Financial Background (Page 3: 4.1-4.3)
    {"label": "4.1 Assets at Home", "section_number": 4, "page": 3},
    {"label": "4.2 Amount of Last Electricity Bill", "section_number": 4, "page": 3},
    {"label": "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student?", "section_number": 4, "page": 3},
    # ── Page 4 ──
    # Section 4 — Financial Background (Page 4: 4.4-4.7)
    {"label": "4.4 Apart from your job, is there any other source of income?", "section_number": 4, "page": 4},
    {"label": "4.5 Income Type", "section_number": 4, "page": 4},
    {"label": "4.6 Do you have any loans?", "section_number": 4, "page": 4},
    {"label": "4.7 If you choose any college, how much is the college fee?", "section_number": 4, "page": 4},
    # ── Page 5 ──
    # Section 4 — Financial Background (Page 5: 4.8-4.9)
    {"label": "4.8 If the college fee is higher, how will you manage it?", "section_number": 4, "page": 5},
    {"label": "4.9 If you do not receive this scholarship, how will you pay the fees?", "section_number": 4, "page": 5},
    # Section 5 — Health Information
    {"label": "5.1 Does the student have any health issues?", "section_number": 5, "page": 5},
    {"label": "5.2 If yes, list the health issues", "section_number": 5, "page": 5},
    # Section 6 — Student Commitment
    {"label": "6.1 Will you study college for three years without any obstacle?", "section_number": 6, "page": 5},
    {"label": "6.2 If we have a training program within 15 km from your home, can you come?", "section_number": 6, "page": 5},
    {"label": "6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)?", "section_number": 6, "page": 5},
    # ── Page 6 ──
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
class PipelineResult:
    overall_confidence: int
    fields: list[StructuredField] | None = None
    num_pages: int = 1
    processing_time: float = 0.0
    per_stage_timing: dict[str, float] | None = None
    token_usage: dict | None = None
    raw_model_json: dict | None = None
    raw_text: str = ""
    sections: list[dict] | None = None


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
        self.secondary_client = secondary_client or get_model_client("secondary")

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

    def run_primary_extraction(self, pdf_path: str, page_images: dict[int, str]) -> tuple[dict | None, dict]:
        from src.prompt_templates import PRIMARY_EXTRACTION_PROMPT

        data, token_usage = self.primary_client.extract_structured(pdf_path, page_images, PRIMARY_EXTRACTION_PROMPT)
        return data, token_usage

    # ── Stage 3b: Merge (enhanced with position_hint + confidence weighting) ──

    @staticmethod
    def _group_words_into_lines(word_boxes: list[WordBox], page: int, y_tolerance: int = 20) -> list[TextLine]:
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
            xs = [w.bbox[0] for w in group]
            ys = [w.bbox[1] for w in group]
            xe = [w.bbox[2] for w in group]
            ye = [w.bbox[3] for w in group]
            result.append(TextLine(
                text=" ".join(w.text for w in group),
                bbox=(min(xs), min(ys), max(xe), max(ye)),
                page=page,
                words=group,
            ))
        return result

    def merge_fields(
        self,
        model_data: dict,
        word_boxes: list[WordBox],
        prefix: str = "",
    ) -> list[StructuredField]:
        fields: list[StructuredField] = []
        raw_fields = model_data.get("fields", [])

        pages_in_fields = sorted({gf.get("page", 1) for gf in raw_fields})
        lines_by_page: dict[int, list[TextLine]] = {
            p: self._group_words_into_lines(word_boxes, p) for p in pages_in_fields
        }

        for gf in raw_fields:
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

            fields.append(StructuredField(
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
            ))

        return fields

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
                        xs = [w.bbox[0] for w in right_words]
                        ys = [w.bbox[1] for w in right_words]
                        xe = [w.bbox[2] for w in right_words]
                        ye = [w.bbox[3] for w in right_words]
                        return (min(xs), min(ys), max(xe), max(ye))

            if value_lower:
                mid_x = (best_line.bbox[0] + best_line.bbox[2]) / 2
                right_words = [wb for wb in best_line.words if wb.bbox[0] > mid_x]
                if right_words:
                    xs = [w.bbox[0] for w in right_words]
                    ys = [w.bbox[1] for w in right_words]
                    xe = [w.bbox[2] for w in right_words]
                    ye = [w.bbox[3] for w in right_words]
                    return (min(xs), min(ys), max(xe), max(ye))
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
                xs = [w.bbox[0] for w in chosen]
                ys = [w.bbox[1] for w in chosen]
                xe = [w.bbox[2] for w in chosen]
                ye = [w.bbox[3] for w in chosen]
                return (min(xs), min(ys), max(xe), max(ye))

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
                    xs = [w.bbox[0] for w in right_words]
                    ys = [w.bbox[1] for w in right_words]
                    xe = [w.bbox[2] for w in right_words]
                    ye = [w.bbox[3] for w in right_words]
                    return (min(xs), min(ys), max(xe), max(ye))

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

    def verify_secondary(
        self,
        fields: list[StructuredField],
        word_boxes: list[WordBox],
        output_dir: str,
        prefix: str = "",
    ) -> tuple[list[StructuredField], dict]:
        from src.prompt_templates import SECONDARY_VERIFICATION_PROMPT

        pages_dir = Path(output_dir) / "pages"
        affected_pages = sorted(set(f.page for f in fields))
        page_images: dict[int, str] = {}
        for p in affected_pages:
            img_path = str(pages_dir / f"page_{p}.png")
            if Path(img_path).exists():
                page_images[p] = img_path

        if not page_images:
            logger.warning("No page images found for secondary verification")
            for f in fields:
                f.is_verified = True
                f.verified_by = prefix or None
            return fields

        fields_json = [
            {
                "label": f.label,
                "value": f.value,
                "confidence": f.confidence,
                "page": f.page,
                "reason": f.reason,
                "position_hint": None,
            }
            for f in fields
        ]

        prompt = SECONDARY_VERIFICATION_PROMPT.replace(
            "{fields_json}", json.dumps(fields_json, indent=2)
        )

        raw_result, secondary_token_usage = self.secondary_client.extract_structured("", page_images, prompt)

        if raw_result is None:
            logger.warning("Secondary verification failed — keeping primary results")
            for f in fields:
                f.is_verified = True
                f.verified_by = prefix or None
            return fields, secondary_token_usage

        # Process verifications
        verif_map: dict[str, dict] = {}
        for v in raw_result.get("verifications", []):
            if isinstance(v, dict):
                verif_map[v.get("label", "")] = v

        for f in fields:
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
                label = nf.get("label", "")
                value = nf.get("value", "")
                confidence = self._parse_confidence(nf)
                page = nf.get("page", 1)
                section_number = nf.get("section")
                if section_number is None:
                    section_number = self._infer_section_from_label(label)
                needs_clarification = nf.get("needs_clarification", False)
                position_hint = nf.get("position_hint")
                label_bbox, value_bbox = self._find_field_bboxes(
                    value, label, page, lines_by_page.get(page, []),
                    position_hint=position_hint,
                )
                fields.append(StructuredField(
                    label=label,
                    value=value,
                    confidence=confidence,
                    page=page,
                    section_number=section_number,
                    bbox=label_bbox,
                    value_bbox=value_bbox,
                    needs_clarification=needs_clarification,
                    reason=nf.get("reason"),
                    is_verified=True,
                    verifier_confidence=confidence,
                    verification_note="Added by secondary model",
                    verified_by=prefix or None,
                ))

            logger.info("Secondary model added %d new fields", len(new_fields_data))

        return fields, secondary_token_usage

    @staticmethod
    @staticmethod
    def _checkbox_sub_option(label: str) -> bool:
        return "\u2014" in label

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

    # ── Dual-model pipeline ────────────────────────────────────────

    def run_dual(self, pdf_path: str, job_dir: str) -> PipelineResult:
        t0 = time.time()
        os.makedirs(job_dir, exist_ok=True)

        primary_name = type(self.primary_client).__name__.replace("Client", "")
        secondary_name = type(self.secondary_client).__name__.replace("Client", "")

        logger.info("=== Dual pipeline: %s → Tesseract → %s ===", primary_name, secondary_name)

        per_stage = {}
        token_usage: dict = {
            "primary": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "secondary": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

        # ── Stage 1: Preprocess ─────────────────────────────────────
        t1 = time.time()
        self.preprocess(pdf_path, job_dir)
        per_stage["preprocessing"] = time.time() - t1

        # ── Stage 2: Bbox detection ─────────────────────────────────
        t1 = time.time()
        word_boxes = self.run_bbox(pdf_path)
        per_stage["bbox"] = time.time() - t1
        num_pages = max({wb.page_num for wb in word_boxes}, default=1)

        pages_dir = Path(job_dir) / "pages"
        page_images = {
            int(p.stem.split("_")[1]): str(p)
            for p in sorted(pages_dir.glob("page_*.png"))
            if "_original" not in p.stem
        }

        # ── Stage 3a: Primary extraction ──────────────────────────
        logger.info("[%s] Primary extraction with %s...", primary_name, primary_name)
        t1 = time.time()
        model_data, primary_token_usage = self.run_primary_extraction(pdf_path, page_images)
        per_stage["primary_extraction"] = time.time() - t1
        token_usage["primary"] = primary_token_usage

        llm_fields: list[StructuredField] = []
        overall_confidence = 0
        raw_text = ""

        if model_data:
            overall_confidence = model_data.get("overall_confidence", 0)
            raw_text = model_data.get("raw_text", "")

            # ── Stage 3b: Merge (LLM → StructuredField) ──────────
            t1 = time.time()
            llm_fields = self.merge_fields(model_data, word_boxes, prefix=primary_name)
            per_stage["merge"] = time.time() - t1
            logger.info("Primary: %d fields from LLM", len(llm_fields))
        else:
            logger.warning("Primary extraction failed")
            overall_confidence = 0
            t1 = time.time()
            llm_fields = [
                StructuredField(
                    label=wb.text,
                    value=wb.text,
                    confidence=int(wb.confidence),
                    page=wb.page_num,
                    bbox=wb.bbox,
                    extracted_by=primary_name,
                )
                for wb in word_boxes
            ]
            per_stage["merge"] = time.time() - t1

        # ── Stage 4: Secondary verification ──────────────────────
        logger.info("[%s] Secondary verification with %s...", secondary_name, secondary_name)
        t1 = time.time()
        llm_fields, secondary_usage = self.verify_secondary(llm_fields, word_boxes, job_dir, prefix=secondary_name)
        per_stage["secondary_verification"] = time.time() - t1
        token_usage["secondary"] = secondary_usage
        logger.info("After secondary: %d fields total", len(llm_fields))

        # Compute aggregate token usage
        total_prompt = (primary_token_usage.get("prompt_tokens", 0) or 0) + (secondary_usage.get("prompt_tokens", 0) or 0)
        total_completion = (primary_token_usage.get("completion_tokens", 0) or 0) + (secondary_usage.get("completion_tokens", 0) or 0)
        total_total = (primary_token_usage.get("total_tokens", 0) or 0) + (secondary_usage.get("total_tokens", 0) or 0)
        token_usage["total"] = {
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_total,
        }
        logger.info("Token usage: primary=%s secondary=%s total=%s",
                     primary_token_usage, secondary_usage, token_usage["total"])

        # ── Stage 5: Fill missing template fields ────────────────
        t1 = time.time()
        llm_fields = self.fill_missing_template_fields(llm_fields)
        per_stage["template_fill"] = time.time() - t1

        elapsed = time.time() - t0
        per_stage["total"] = elapsed
        return PipelineResult(
            overall_confidence=overall_confidence,
            fields=llm_fields,
            num_pages=num_pages,
            processing_time=elapsed,
            per_stage_timing=per_stage,
            token_usage=token_usage,
            raw_model_json=model_data,
            raw_text=raw_text,
            sections=(model_data or {}).get("sections"),
        )
