"""CV-based checkbox mark verification using stroke-run counting.

At runtime, given page images (grayscale numpy arrays), crops each checkbox
region (excluding the square border via 25% center-crop margin) and
classifies the interior mark by counting dark runs per row.

Key insight:
  A tick (✓) has 2-run rows concentrated at the TOP (V arms separate) with
  a narrow vertical span.  A cross (✗) has 2-run rows CENTERED vertically
  with a wide span (the two strokes cross through the middle).
  An empty checkbox has negligible interior dark pixels.

Checkbox positions are defined in A4 point coordinates (595 × 842 pts)
Checkbox positions are defined in A4 point coordinates (595 x 842 pts)
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ── Reference checkbox positions (A4 point coordinates) ───────────────────
#
# Coordinates: (x_pt, y_pt, w_pt, h_pt) in A4 points (595 × 842).
# These are derived from a reference scan at 200 DPI by locating the printed
# checkbox square contour to the left of the field label.  The size includes
# a small margin around the checkbox border.
#
# To convert to pixel coords at runtime:
#   x_px = round(x_pt * dpi / 72)
#   y_px = round(y_pt * dpi / 72)
#
# Keys match either:
#   - mark-description keys in extraction_schema_json (multi-option): e.g. "gender_male_mark"
#   - base field keys (single-checkbox in EXTRACT_SCHEMA): e.g. "ceiling_roof", "govt_id_aadhaar"
#   - suffix "_checkbox" keys used by verify_asset_list(): e.g. "asset_washing_machine_checkbox"
#
# NOTE: 4.1 asset entries use "_checkbox" suffix (not "_mark") because the
# per-asset mark descriptions don't exist in EXTRACT_SCHEMA — Datalab returns
# assets_at_home_list and we verify each entry at the pixel level.

CHECKBOX_COORDS: dict[str, tuple[int, float, float, float, float]] = {
    # ── Page 2 — 2.4 Government IDs ──────────────────────────────────
    # Labels from scan: Aadhaar(y~630), Ration, Driving Licence, Voter ID, Other
    # Checkbox sizes are approximate (8×8 pts ≈ 22×22 px at 200 DPI)
    "govt_id_aadhaar": (2, 120.0, 200.0, 8.0, 8.0),
    "govt_id_ration": (2, 120.0, 220.0, 8.0, 8.0),
    "govt_id_driving_licence": (2, 120.0, 240.0, 8.0, 8.0),
    "govt_id_voter": (2, 120.0, 260.0, 8.0, 8.0),
    "govt_id_other": (2, 120.0, 280.0, 8.0, 8.0),

    # ── Page 2 — 3.2 Type of Home ────────────────────────────────────
    "home_type_individual": (2, 150.0, 550.0, 8.0, 8.0),
    "home_type_private_apartment": (2, 150.0, 570.0, 8.0, 8.0),
    "home_type_housing_board": (2, 150.0, 590.0, 8.0, 8.0),
    "home_type_line_house": (2, 150.0, 610.0, 8.0, 8.0),

    # ── Page 3 — 3.3 Type of Ceiling ─────────────────────────────────
    "ceiling_roof": (3, 80.0, 63.0, 8.0, 8.0),
    "ceiling_tiled": (3, 170.0, 63.0, 8.0, 8.0),
    "ceiling_asbestos": (3, 240.0, 63.0, 8.0, 8.0),
    "ceiling_concrete": (3, 360.0, 63.0, 8.0, 8.0),

    # ── Page 3 — 4.1 Assets at Home (used by verify_asset_list) ──────
    # Pixel-level checkbox sizes from reference scan (200 DPI):
    #   AC: 24×24, Two-Wheeler: 16×20, Car: 13×18,
    #   Washing Machine: 17×16, Fridge: 22×21
    # Converted to points via pt = px * 72/200
    "asset_washing_machine_checkbox": (3, 59.0, 452.5, 6.1, 5.8),
    "asset_fridge_checkbox": (3, 199.4, 450.7, 7.9, 7.6),
    "asset_ac_checkbox": (3, 280.4, 449.3, 8.6, 8.6),
    "asset_led_tv_checkbox": (3, 360.0, 448.0, 8.0, 8.0),
    "asset_two_wheeler_checkbox": (3, 429.5, 448.6, 5.8, 7.2),
    "asset_car_checkbox": (3, 530.3, 447.5, 4.7, 6.5),
    "asset_smartphone_checkbox": (3, 60.0, 486.0, 7.0, 7.0),
    "asset_separate_wifi_checkbox": (3, 168.0, 486.0, 7.0, 7.0),
}

# ── Asset name → checkbox coordinate key mapping ─────────────────────────
_ASSET_NAME_TO_CHECKBOX_KEY: dict[str, str] = {
    "washing machine": "asset_washing_machine_checkbox",
    "fridge": "asset_fridge_checkbox",
    "ac": "asset_ac_checkbox",
    "led tv": "asset_led_tv_checkbox",
    "two-wheeler": "asset_two_wheeler_checkbox",
    "car": "asset_car_checkbox",
    "smartphone": "asset_smartphone_checkbox",
    "separate wi-fi": "asset_separate_wifi_checkbox",
}

_ALL_ASSET_CHECKBOX_KEYS: set[str] = set(_ASSET_NAME_TO_CHECKBOX_KEY.values())

_UNICODE_TO_MARK: dict[str, str] = {
    "✓": "tick", "✔": "tick", "☑": "tick", "🗸": "tick",
    "✗": "cross", "✘": "cross",
}

_CHECKBOX_CHAR_MARKS: dict[str, str] = {
    "x": "cross",
    "/": "slash",
}


def _normalize_mark(val: str) -> str:
    """Normalize Datalab mark values to our standard terms: tick, cross, slash, empty."""
    raw = str(val).strip().lower()
    if raw in ("", "none", "empty", "null"):
        return "empty"
    mapped = _UNICODE_TO_MARK.get(raw)
    if mapped:
        return mapped
    mapped = _CHECKBOX_CHAR_MARKS.get(raw)
    if mapped:
        return mapped
    return raw


# ── Analysis thresholds ───────────────────────────────────────────────────

_CENTER_DARK_THRESHOLD = 0.05
_MULTI_STROKE_RATIO_THRESHOLD = 0.35  # ≥35% of occupied rows have ≥2 runs → cross (secondary check)

# Spatial distribution: a cross has 2-run rows centered vertically with wide span,
# while a tick has them concentrated at the top with narrow span.
_MULTI_SPAN_THRESHOLD = 0.40       # min fractional height of 2-run zone for cross
_MULTI_COM_LOW = 0.35               # min normalized center-of-mass for cross
_MULTI_COM_HIGH = 0.65              # max normalized center-of-mass for cross


# ── Functions ─────────────────────────────────────────────────────────────

def _points_to_pixels(pt_val: float, dpi: int) -> int:
    return int(round(pt_val * dpi / 72.0))


def _classify_checkbox_mark(roi: np.ndarray) -> str:
    """Classify the mark inside a checkbox region using stroke-run analysis.

    For each occupied row in the center crop, counts how many distinct
    dark runs (contiguous ink segments) exist.  A cross (two strokes) creates
    2+ runs per row through the intersection zone.  A tick (single stroke)
    creates 1 run per row.  This geometric property holds for both printed
    and handwritten marks — it measures stroke *count*, not glyph shape.

    Returns one of: ``"tick"``, ``"cross"``, ``"empty"``, ``"unknown"``
    """
    if roi.size == 0:
        return "unknown"

    _, binary = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    h_r, w_r = binary.shape
    margin_y = max(1, h_r // 4)
    margin_x = max(1, w_r // 4)
    center = binary[margin_y : h_r - margin_y, margin_x : w_r - margin_x]

    if center.size == 0:
        return "unknown"

    center_dark = cv2.countNonZero(center)
    center_ratio = center_dark / center.size

    if center_ratio < _CENTER_DARK_THRESHOLD:
        return "empty"

    # ── Spatial distribution of multi-run rows ──
    # A tick (✓) has its V arms at the TOP (2-run rows concentrated high,
    # narrow vertical span).  A cross (✗) has its two strokes crossing in
    # the CENTER (2-run rows spread vertically with midpoint near center).
    # This spatial heuristic holds for handwritten marks of any size.
    ch, cw = center.shape
    runs_per_row: list[int] = []
    for row_idx in range(ch):
        row_data = center[row_idx, :] > 0
        if not np.any(row_data):
            runs_per_row.append(0)
            continue
        transitions = np.diff(row_data.astype(int))
        runs = int(np.sum(transitions == 1))
        if row_data[0]:
            runs += 1
        runs_per_row.append(runs)

    multi_rows = [i for i, r in enumerate(runs_per_row) if r >= 2]
    total_occupied_rows = sum(1 for r in runs_per_row if r > 0)

    if multi_rows:
        span = (multi_rows[-1] - multi_rows[0] + 1) / ch
        com = (multi_rows[0] + multi_rows[-1]) / 2.0 / ch
    else:
        span = 0.0
        com = 0.0

    # Overall multi-stroke ratio (secondary check)
    rows_with_2_runs = len(multi_rows)
    multi_stroke_ratio = rows_with_2_runs / max(total_occupied_rows, 1)

    # Spatial rule: cross if multi-run zone has wide span AND is centered
    is_cross_by_span = (
        span >= _MULTI_SPAN_THRESHOLD
        and _MULTI_COM_LOW <= com <= _MULTI_COM_HIGH
    )
    # Fallback: overall ratio (catches dense crosses with narrow span)
    is_cross_by_ratio = multi_stroke_ratio > _MULTI_STROKE_RATIO_THRESHOLD

    is_cross = is_cross_by_span or is_cross_by_ratio

    logger.debug(
        "CV checkbox: dark=%d/%d (%.2f) span=%.2f com=%.2f multi=%d/%d (%.2f) → %s",
        center_dark, center.size, center_ratio,
        span, com, rows_with_2_runs, total_occupied_rows, multi_stroke_ratio,
        "cross" if is_cross else "tick",
    )

    if is_cross:
        return "cross"

    return "tick"


def _is_roi_blank(roi: np.ndarray, threshold: float = 0.005) -> bool:
    """Check if an ROI is essentially blank (no visible content)."""
    if roi.size < 16:
        return True
    _, binary = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    dark_ratio = cv2.countNonZero(binary) / binary.size
    return dark_ratio < threshold


_CALIBRATION_ACCEPT_THRESHOLD = 2.0
"""Minimum border_score (x10⁴ to avoid fp) to accept a calibrated position.
A real checkbox border at correct position produces min_side ≈ 20-80 avg dark
pixels per band and avg_side ≈ 30-60 → min*avg/100 ≈ 6.0-48.0.
Text, form lines, or noise rarely exceed 1.0."""


def _search_checkbox_window(
    img: np.ndarray,
    pt_x: float,
    pt_y: float,
    pt_w: float,
    pt_h: float,
    dpi: int,
    search_pt: float = 15.0,
) -> tuple[float, float] | None:
    """Search for the actual checkbox position when the expected position is blank.
    
    Only activates when the original crop is essentially blank (no dark content),
    indicating the coordinates miss the checkbox entirely.  Searches a grid
    around the expected location and picks the position with the strongest
    four-sided border structure (checkbox outline).
    
    Returns (calibrated_pt_x, calibrated_pt_y) or None if no improvement.
    """
    cx = _points_to_pixels(pt_x, dpi)
    cy = _points_to_pixels(pt_y, dpi)
    pw = max(_points_to_pixels(pt_w, dpi), 4)
    ph = max(_points_to_pixels(pt_h, dpi), 4)
    margin = _points_to_pixels(4.0, dpi)
    search_px = _points_to_pixels(search_pt, dpi)

    def _get_roi(nx: int, ny: int) -> np.ndarray | None:
        x1 = max(0, nx - margin)
        y1 = max(0, ny - margin)
        x2 = min(img.shape[1], nx + pw + margin)
        y2 = min(img.shape[0], ny + ph + margin)
        if x2 - x1 < 4 or y2 - y1 < 4:
            return None
        roi = img[y1:y2, x1:x2]
        return roi if roi.size >= 16 else None

    def _border_score(roi: np.ndarray) -> float:
        """Score how well the INNER checkbox border area has dark pixels.
        
        The checkbox occupies the center pw×ph of the ROI (surrounded by
        margin).  Bands are drawn just INSIDE the checkbox outline — this
        captures the printed border rather than the blank margin.  Returns
        min_side * avg_side * 100 (scaled for readability).
        """
        _, binary = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        h, w = binary.shape
        # Checkbox starts at (margin, margin) in ROI coords
        mx = (w - pw) // 2
        my = (h - ph) // 2
        if mx <= 0 or my <= 0:
            return 0.0
        band_h = max(2, ph // 6)
        band_w = max(2, pw // 6)
        # Bands along the checkbox edge (margin+1 → margin+band)
        top_band = binary[my : my + band_h, mx : mx + pw]
        bottom_band = binary[my + ph - band_h : my + ph, mx : mx + pw]
        left_band = binary[my : my + ph, mx : mx + band_w]
        right_band = binary[my : my + ph, mx + pw - band_w : mx + pw]
        
        def band_dark(band: np.ndarray) -> float:
            return float(cv2.countNonZero(band))
        
        top = band_dark(top_band)
        bottom = band_dark(bottom_band)
        left = band_dark(left_band)
        right = band_dark(right_band)
        min_side = min(top, bottom, left, right)
        avg_side = (top + bottom + left + right) / 4.0
        return min_side * avg_side / 100.0

    def _is_checkbox_candidate(roi: np.ndarray) -> bool:
        """Verify the ROI looks like a real checkbox (border + reasonable interior)."""
        _, binary = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        total_fill = cv2.countNonZero(binary) / binary.size
        if total_fill > 0.55:
            return False
        h_r, w_r = binary.shape
        margin_y = max(1, h_r // 4)
        margin_x = max(1, w_r // 4)
        center = binary[margin_y : h_r - margin_y, margin_x : w_r - margin_x]
        if center.size == 0:
            return False
        center_dark = cv2.countNonZero(center) / center.size
        if center_dark > 0.50:
            return False
        return True

    # Check if original position already contains a checkbox candidate
    orig_roi = _get_roi(cx, cy)
    if orig_roi is not None and not _is_roi_blank(orig_roi) and _is_checkbox_candidate(orig_roi):
        return None

    # Search for best checkbox outline
    best_score = -1.0
    best_pos = (cx, cy)
    step = max(2, search_px // 10)

    for dy in range(-search_px, search_px + 1, step):
        for dx in range(-search_px, search_px + 1, step):
            nx, ny = cx + dx, cy + dy
            roi = _get_roi(nx, ny)
            if roi is None:
                continue
            if _is_roi_blank(roi):
                continue
            if not _is_checkbox_candidate(roi):
                continue
            score = _border_score(roi)
            if score > best_score:
                best_score = score
                best_pos = (nx, ny)

    if best_score > _CALIBRATION_ACCEPT_THRESHOLD and best_pos != (cx, cy):
        cal_pt_x = best_pos[0] * 72.0 / dpi
        cal_pt_y = best_pos[1] * 72.0 / dpi
        logger.info(
            "CV calibration: (%.0f,%.0f)→(%.1f,%.1f) score=%.4f",
            pt_x, pt_y, cal_pt_x, cal_pt_y, best_score,
        )
        return (cal_pt_x, cal_pt_y)

    return None


def _crop_checkbox(
    page_images: dict[int, np.ndarray],
    page_num: int,
    pt_x: float,
    pt_y: float,
    pt_w: float,
    pt_h: float,
    dpi: int,
) -> np.ndarray | None:
    """Crop a checkbox region from a page image, with auto-calibration."""
    img = page_images.get(page_num)
    if img is None:
        return None

    # Auto-calibrate: search for actual checkbox if expected position misses
    calibrated = _search_checkbox_window(img, pt_x, pt_y, pt_w, pt_h, dpi)
    if calibrated is not None:
        pt_x, pt_y = calibrated

    px = _points_to_pixels(pt_x, dpi)
    py = _points_to_pixels(pt_y, dpi)
    pw = _points_to_pixels(pt_w, dpi)
    ph = _points_to_pixels(pt_h, dpi)
    margin = _points_to_pixels(4.0, dpi)

    x1 = max(0, px - margin)
    y1 = max(0, py - margin)
    x2 = min(img.shape[1], px + pw + margin)
    y2 = min(img.shape[0], py + ph + margin)

    roi = img[y1:y2, x1:x2]
    if roi.size == 0:
        return None
    return roi


# ── Asset list verification (4.1 Assets at Home) ──────────────────────────

def verify_asset_list(
    page_images: dict[int, np.ndarray],
    extracted: dict,
    dpi: int = 200,
) -> dict:
    """Verify assets_at_home_list entries against pixel-level CV analysis.

    For each asset name Datalab reported in ``assets_at_home_list``, analyzes
    the corresponding checkbox on the page image.  Removes entries where CV
    detects a cross or empty mark (false positive).

    Also checks all 4.1 checkboxes that Datalab did NOT list — if CV finds
    a tick mark on an unlisted asset, it is added to the list (false negative).

    Returns the (possibly modified) extraction dict.
    """
    assets_list = extracted.get("assets_at_home_list")
    if not isinstance(assets_list, list) or not page_images:
        return extracted

    if 3 not in page_images:
        logger.warning("CV verify_asset_list: page 3 image not available")
        return extracted

    # ── Phase 1: verify listed assets (remove false positives) ──
    verified_names: list[str] = []
    removed_names: list[str] = []

    for asset_name in assets_list:
        if not isinstance(asset_name, str):
            verified_names.append(asset_name)
            continue

        key = _ASSET_NAME_TO_CHECKBOX_KEY.get(asset_name.strip().lower())
        if key is None:
            verified_names.append(asset_name)
            continue

        coords = CHECKBOX_COORDS.get(key)
        if coords is None:
            verified_names.append(asset_name)
            continue

        roi = _crop_checkbox(page_images, *coords, dpi)
        if roi is None:
            verified_names.append(asset_name)
            continue

        cv_class = _classify_checkbox_mark(roi)
        if cv_class == "cross":
            removed_names.append(asset_name)
            logger.info(
                "CV asset verification: removing '%s' (Datalab listed but CV=%s)",
                asset_name, cv_class,
            )
        elif cv_class == "empty":
            # Only trust "empty" if the ROI actually looks like a checkbox (has a border).
            # If the crop is blank, coordinates might be off — keep Datalab's verdict.
            _, binary = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            border_dark = cv2.countNonZero(binary) / binary.size
            if border_dark > 0.02:
                removed_names.append(asset_name)
                logger.info(
                    "CV asset verification: removing '%s' (Datalab listed but CV=empty, border present)",
                    asset_name,
                )
            else:
                verified_names.append(asset_name)
                logger.info(
                    "CV asset verification: keeping '%s' (Datalab listed, CV=empty but no border found — coordinates may be off)",
                    asset_name,
                )
        else:
            verified_names.append(asset_name)

    # ── Phase 2: check unlisted assets (add false negatives) ──
    listed_lower = {n.strip().lower() for n in assets_list if isinstance(n, str)}
    added_names: list[str] = []

    for asset_name, checkbox_key in _ASSET_NAME_TO_CHECKBOX_KEY.items():
        if asset_name in listed_lower:
            continue

        coords = CHECKBOX_COORDS.get(checkbox_key)
        if coords is None:
            continue

        roi = _crop_checkbox(page_images, *coords, dpi)
        if roi is None:
            continue

        cv_class = _classify_checkbox_mark(roi)
        if cv_class == "tick":
            # Restore the user-visible asset name
            display_name = asset_name.title()
            verified_names.append(display_name)
            added_names.append(asset_name)
            logger.info(
                "CV asset verification: adding '%s' (Datalab missed but CV=%s)",
                asset_name, cv_class,
            )

    extracted["assets_at_home_list"] = verified_names

    if removed_names or added_names:
        logger.info(
            "CV asset verification complete: removed=%s added=%s",
            removed_names, added_names,
        )

    return extracted


# ── Mark-description verification (single-checkbox and multi-option) ──────

def verify_marks(
    page_images: dict[int, np.ndarray],
    extracted: dict,
    dpi: int = 200,
) -> dict:
    """Verify Datalab mark descriptions against pixel-level CV analysis.

    Processes individual mark-description keys in ``extracted`` (e.g.
    ``ceiling_roof``, ``govt_id_aadhaar``, ``gender_male_mark``).

    For each key that has a known checkbox position, crops the region,
    runs :func:`_classify_checkbox_mark`, and overrides the description
    if CV disagrees with Datalab.

    Returns the (possibly modified) extraction dict.
    """
    if not page_images or not extracted:
        return extracted

    overrides: list[tuple[str, str, str]] = []
    checked = 0

    for key, mark_val in list(extracted.items()):
        if mark_val is None:
            continue

        if key not in CHECKBOX_COORDS:
            continue
        if key in _ALL_ASSET_CHECKBOX_KEYS or key.endswith("_checkbox"):
            continue

        coords = CHECKBOX_COORDS[key]
        roi = _crop_checkbox(page_images, *coords, dpi)
        if roi is None:
            continue

        cv_class = _classify_checkbox_mark(roi)
        datalab_norm = _normalize_mark(mark_val)
        checked += 1

        # Datalab's text/symbol reading ("Yes", "tick", "✓") is more reliable
        # than CV finding nothing inside the box for any checkbox key.  Never
        # downgrade a Datalab positive — only allow positive-direction overrides
        # (empty→tick, cross→tick).
        if datalab_norm in ("tick", "slash", "yes"):
            pass  # trust Datalab — do not override
        elif cv_class == "empty" and datalab_norm not in ("empty", ""):
            overrides.append((key, str(mark_val), "empty"))
            extracted[key] = "empty"
        elif cv_class == "cross" and datalab_norm in ("tick", "slash"):
            overrides.append((key, str(mark_val), "cross"))
            extracted[key] = "cross"
        elif cv_class == "tick" and datalab_norm in ("cross",):
            overrides.append((key, str(mark_val), "tick"))
            extracted[key] = "tick"

    if overrides:
        logger.info("CV mark verification: %d override(s) of %d checked: %s",
                     len(overrides), checked, overrides)
    else:
        logger.info("CV mark verification: %d checked, no overrides needed", checked)

    return extracted


# ── Both-marked detection (Problem 2) ──────────────────────────────────────

def _detect_both_marked(extracted: dict) -> list[str]:
    """Detect multi-option groups where two or more options have non-empty marks.

    When both Yes and No (or any pair) in a group have marks, Datalab picks
    one by preference instead of flagging ambiguity.  This function finds those
    cases and returns the field names to flag for manual review.

    Returns:
        List of field names (e.g. ``['house_ownership']``) that are ambiguous.
    """
    from src.datalab_schema import MULTI_OPTION_FIELDS

    ambiguous: list[str] = []
    for field_name, config in MULTI_OPTION_FIELDS.items():
        non_empty = 0
        for opt_key, mark_key in config["mark_keys"].items():
            mark_val = extracted.get(mark_key)
            if mark_val is not None and _normalize_mark(mark_val) not in ("empty",):
                non_empty += 1
        if non_empty >= 2:
            ambiguous.append(field_name)
            logger.info("CV both-marked: '%s' has %d non-empty marks — flagging ambiguous", field_name, non_empty)
    return ambiguous


# ── Strike-through (CV) for free-text areas ─────────────────────────────

# Approximate A4 point coordinates (595 × 842 pts) for free-text areas where
# handwritten notes appear.  Used to detect strike-through lines via Hough
# Transform so struck-through text gets cleared before merge.
_FREE_TEXT_REGIONS: dict[str, tuple[int, float, float, float, float]] = {
    # (page, x_pt, y_pt, w_pt, h_pt) — generous bounding box covering the blank
    # space where users write notes; tune if strike-through detection is noisy.
    "blank_text_below_4_3":         (3, 30.0, 580.0, 535.0, 200.0),
    "blank_text_below_4_3_1_table": (4, 30.0, 250.0, 535.0, 200.0),
    "blank_text_below_2_1":         (1, 30.0, 400.0, 535.0, 150.0),
}


def _crop_region(
    page_images: dict[int, np.ndarray],
    page: int, x_pt: float, y_pt: float, w_pt: float, h_pt: float,
    dpi: int,
) -> np.ndarray | None:
    """Crop a rectangular region from a page image.

    Coordinates are in A4 points (72 pt/in), converted to pixels at *dpi*.
    Returns grayscale ROI or None if out of bounds.
    """
    img = page_images.get(page)
    if img is None:
        return None
    x = _points_to_pixels(x_pt, dpi)
    y = _points_to_pixels(y_pt, dpi)
    w = max(_points_to_pixels(w_pt, dpi), 4)
    h = max(_points_to_pixels(h_pt, dpi), 4)
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(img.shape[1], x + w)
    y2 = min(img.shape[0], y + h)
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None
    return img[y1:y2, x1:x2]


def _has_strikethrough_line(roi: np.ndarray) -> bool:
    """Check if an image region contains horizontal line(s) spanning it.

    Uses probabilistic Hough Line Transform.  A strike-through is a thin
    near-horizontal line crossing most of the region width.
    """
    if roi is None or roi.size < 64:
        return False

    _, binary = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h, w = binary.shape

    # Dilate to connect broken line segments
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 3))
    dilated = cv2.dilate(binary, kernel, iterations=1)

    lines = cv2.HoughLinesP(
        dilated,
        rho=1,
        theta=np.pi / 180,
        threshold=max(20, h // 10),
        minLineLength=w // 2,
        maxLineGap=5,
    )
    if lines is None:
        return False

    for line in lines:
        x1, y1, x2, y2 = line[0]
        length = np.hypot(x2 - x1, y2 - y1)
        angle = abs(np.rad2deg(np.arctan2(y2 - y1, x2 - x1)))
        # Horizontal line spanning ≥ half the region width, angle ≤ 20°
        if length >= w * 0.5 and angle <= 20.0:
            return True

    return False


def verify_strikethrough(
    page_images: dict[int, np.ndarray],
    extracted: dict,
    dpi: int = 200,
) -> dict:
    """Clear free-text fields whose region contains strike-through lines.

    CV-based: crops the approximate text region for each free-text key
    defined in ``_FREE_TEXT_REGIONS`` and runs Hough line detection.
    If a long horizontal line is found, the text is considered struck through
    and the extraction value is set to empty string.
    """
    if not page_images or not extracted:
        return extracted

    cleared: list[str] = []
    for key, (page, x_pt, y_pt, w_pt, h_pt) in _FREE_TEXT_REGIONS.items():
        val = extracted.get(key)
        if not val or not str(val).strip():
            continue

        roi = _crop_region(page_images, page, x_pt, y_pt, w_pt, h_pt, dpi)
        if roi is None:
            continue

        if _has_strikethrough_line(roi):
            extracted[key] = ""
            cleared.append(key)

    if cleared:
        logger.info("CV strikethrough: cleared %d field(s): %s", len(cleared), cleared)

    return extracted


# ── High-level helper ─────────────────────────────────────────────────────

def verify_all(
    page_images: dict[int, np.ndarray],
    extracted: dict,
    dpi: int = 200,
) -> dict:
    """Run all CV verification on a Datalab extraction dict.

    Combines :func:`verify_marks`, :func:`verify_asset_list`, and
    :func:`_detect_both_marked`.

    Returns the (possibly modified) extraction dict with ``_ambiguous_fields``
    populated if both-marked groups were detected.
    """
    n_pages = len(page_images)
    logger.info("CV verify_all: starting on %d page(s)", n_pages)
    extracted = verify_marks(page_images, extracted, dpi)
    extracted = verify_asset_list(page_images, extracted, dpi)
    extracted = verify_strikethrough(page_images, extracted, dpi)

    both_marked = _detect_both_marked(extracted)
    if both_marked:
        existing = extracted.get("_ambiguous_fields", [])
        if isinstance(existing, list):
            for f in both_marked:
                if f not in existing:
                    existing.append(f)
        extracted["_ambiguous_fields"] = existing
        logger.info("CV verify_all: both-marked ambiguous fields: %s", both_marked)

    logger.info("CV verify_all: done")
    return extracted


def load_page_images(
    pdf_path: str | Path,
    dpi: int = 200,
) -> dict[int, np.ndarray]:
    """Render each page of a PDF as a grayscale numpy array.

    Returns dict mapping 1-indexed page number → grayscale image.
    """
    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    images: dict[int, np.ndarray] = {}
    try:
        for pn in range(len(doc)):
            page = doc[pn]
            pix = page.get_pixmap(dpi=dpi)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, 3
            )
            images[pn + 1] = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    finally:
        doc.close()

    return images
