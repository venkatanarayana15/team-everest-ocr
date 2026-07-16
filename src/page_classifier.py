"""Page classifier — determines page number (1-6) from image content.

Uses Tesseract OCR + template matching to identify which page of the
"I Am The Change" questionnaire a given image represents, without
relying on filenames.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)


PAGE_SIGNATURES: dict[int, list[str]] = {
    1: [
        "Volunteer Name", "Co-Volunteer Name", "Date of Visit",
        "Application ID", "Student Full Name", "Gender",
        "Family Status",
    ],
    2: [
        "photograph kept at home", "Government ID",
        "Family Members", "House Ownership", "rent amount",
        "Type of Home",
    ],
    3: [
        "Type of Ceiling", "Number of Bedrooms", "Bedroom",
        "Bathroom", "Kitchen Type", "Assets at Home",
        "Electricity Bill", "own any other assets",
    ],
    4: [
        "source of income", "Income Type",
        "loans", "Loan Purpose", "college fee",
        "Monthly", "Daily", "Weekly",
    ],
    5: [
        "health issues", "college fee is higher",
        "do not receive this scholarship",
        "study college for three years",
        "training program", "skill development",
    ],
    6: [
        "other scholarships", "opinion about the student",
        "recommend this student", "Volunteer Observation",
        "comments",
    ],
}

SECTION_HEADERS: dict[int, list[str]] = {
    1: ["Student Profile"],
    2: ["Family Background"],
    3: ["Housing Condition"],
    4: ["Financial Background"],
    5: ["Health Information", "Student Commitment"],
    6: ["Scholarship Information", "Volunteer Observation"],
}

FIELD_NUMBER_PATTERNS: dict[int, list[re.Pattern]] = {
    1: [re.compile(r"^\s*1\.\d")],
    2: [re.compile(r"^\s*2\.\d"), re.compile(r"^\s*3\.\d")],
    3: [re.compile(r"^\s*3\.\d"), re.compile(r"^\s*4\.\d")],
    4: [re.compile(r"^\s*4\.\d")],
    5: [re.compile(r"^\s*4\.\d"), re.compile(r"^\s*5\.\d"), re.compile(r"^\s*6\.\d")],
    6: [re.compile(r"^\s*7\.\d"), re.compile(r"^\s*8\.\d")],
}


@dataclass
class PageClassification:
    page_number: int
    confidence: float
    matched_keywords: list[str]
    matched_sections: list[str]
    blank: bool = False
    unreadable: bool = False
    ocr_confidence: float = 0.0


class PageClassifier:
    """Classifies page images into page numbers 1-6 based on OCR content."""

    def __init__(self):
        pass

    def classify_from_text(self, text: str) -> PageClassification:
        """Classify a single page from its OCR text content."""
        text_lower = text.lower().strip()
        if not text_lower:
            return PageClassification(0, 0.0, [], [], blank=True)

        scores: dict[int, float] = {p: 0.0 for p in range(1, 7)}
        matched_keywords: dict[int, list[str]] = {p: [] for p in range(1, 7)}
        matched_sections: dict[int, list[str]] = {p: [] for p in range(1, 7)}

        for page_num, keywords in PAGE_SIGNATURES.items():
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in text_lower:
                    scores[page_num] += 15.0
                    matched_keywords[page_num].append(kw)
                elif fuzz.partial_ratio(kw_lower, text_lower) > 80:
                    scores[page_num] += 8.0
                    matched_keywords[page_num].append(f"{kw} (fuzzy)")

        for page_num, headers in SECTION_HEADERS.items():
            for h in headers:
                h_lower = h.lower()
                if h_lower in text_lower:
                    scores[page_num] += 30.0
                    matched_sections[page_num].append(h)
                elif fuzz.partial_ratio(h_lower, text_lower) > 85:
                    scores[page_num] += 15.0
                    matched_sections[page_num].append(f"{h} (fuzzy)")

        for page_num, patterns in FIELD_NUMBER_PATTERNS.items():
            for pat in patterns:
                matches = pat.findall(text)
                if matches:
                    scores[page_num] += min(10.0 * len(matches), 30.0)

        words = text_lower.split()
        word_count = len(words)
        if word_count > 0:
            for p in range(1, 7):
                if scores[p] > 0:
                    scores[p] += min(word_count * 0.5, 10.0)

        best_page = max(range(1, 7), key=lambda p: scores[p])
        best_score = scores[best_page]
        second_score = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0

        if best_score <= 0:
            return PageClassification(0, 0.0, [], [], unreadable=True, ocr_confidence=0.0)

        confidence = min(100.0, best_score)
        if second_score > 0 and best_score > 0:
            margin = (best_score - second_score) / best_score * 100
        else:
            margin = 100.0
        confidence = min(confidence, 50.0 + margin * 0.5)
        confidence = max(10.0, min(99.0, confidence))

        return PageClassification(
            page_number=best_page,
            confidence=round(confidence, 1),
            matched_keywords=matched_keywords[best_page],
            matched_sections=matched_sections[best_page],
            ocr_confidence=confidence,
        )

    def classify_image(self, image_path: str, ocr_text: str | None = None) -> PageClassification:
        """Classify a page from an image file. Requires ocr_text to be provided."""
        if not ocr_text:
            return PageClassification(0, 0.0, [], [], unreadable=True)
        return self.classify_from_text(ocr_text)

    def classify_all(
        self, image_paths: list[str], ocr_texts: dict[int, str] | None = None
    ) -> dict[int, PageClassification]:
        """Classify all images and return a mapping of image_index -> classification."""
        results: dict[int, PageClassification] = {}
        for i, path in enumerate(image_paths):
            text = ocr_texts.get(i) if ocr_texts else None
            results[i] = self.classify_image(path, text)
        return results

    def resolve_order(
        self, classifications: dict[int, PageClassification]
    ) -> tuple[dict[int, int], dict]:
        """Resolve page ordering from classifications.

        Returns:
          - mapping of page_number (1-6) -> image_index
          - validation info dict
        """
        image_count = len(classifications)
        page_map: dict[int, int] = {}
        used_indices: set[int] = set()
        conflicts: list[dict] = []
        detection_details: list[dict] = []

        for idx, cf in sorted(classifications.items()):
            detection_details.append({
                "image_index": idx,
                "detected_page": cf.page_number,
                "confidence": cf.confidence,
                "blank": cf.blank,
                "unreadable": cf.unreadable,
                "matched_keywords": cf.matched_keywords[:5],
                "matched_sections": cf.matched_sections[:5],
            })

        sorted_indices = sorted(
            classifications.keys(),
            key=lambda i: classifications[i].confidence,
            reverse=True,
        )

        for idx in sorted_indices:
            cf = classifications[idx]
            if cf.blank or cf.unreadable or cf.page_number == 0:
                continue
            pn = cf.page_number
            if pn not in page_map and pn not in used_indices:
                page_map[pn] = idx
                used_indices.add(idx)

        unassigned = [i for i in classifications if i not in used_indices]

        if unassigned:
            for pn in range(1, 7):
                if pn not in page_map and unassigned:
                    idx = unassigned.pop(0)
                    page_map[pn] = idx
                    used_indices.add(idx)

        remaining_unassigned = classifications.keys() - used_indices
        for idx in remaining_unassigned:
            cf = classifications[idx]
            if cf.blank or cf.unreadable:
                logger.info("Skipping blank/unreadable image index %d", idx)
                continue
            assigned_pages = set(page_map.keys())
            best_pn = max(
                [p for p in range(1, 7) if p not in assigned_pages] or [0],
                key=lambda p: (
                    cf.confidence if cf.page_number == p else 0
                ) if p > 0 else -1,
            )
            if best_pn > 0:
                page_map[best_pn] = idx

        num_expected = 6
        num_detected = image_count
        assigned_pages = sorted(page_map.keys())
        all_pages = set(range(1, 7))
        missing_pages = sorted(all_pages - set(page_map.keys()))
        extra_pages = [p for p in page_map if p not in range(1, 7)]

        page_numbers_detected = [cf.page_number for cf in classifications.values()
                                  if not cf.blank and not cf.unreadable and cf.page_number > 0]
        duplicates = [
            p for p in set(page_numbers_detected)
            if page_numbers_detected.count(p) > 1
        ]

        validation = {
            "total_images_received": image_count,
            "total_pages_expected": num_expected,
            "total_pages_detected": num_detected,
            "has_duplicates": len(duplicates) > 0,
            "duplicate_pages": duplicates,
            "has_missing": len(missing_pages) > 0,
            "missing_pages": missing_pages,
            "has_blank_pages": any(cf.blank for cf in classifications.values()),
            "blank_pages": [i for i, cf in classifications.items() if cf.blank],
            "has_unreadable_pages": any(cf.unreadable for cf in classifications.values()),
            "unreadable_pages": [i for i, cf in classifications.items() if cf.unreadable],
            "page_classification": detection_details,
            "resolved_page_map": {str(k): v for k, v in sorted(page_map.items())},
        }

        return page_map, validation
