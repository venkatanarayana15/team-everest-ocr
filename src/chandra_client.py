"""Chandra-2 OCR client — sends PDF to OCR API, parses markdown into structured fields."""

import asyncio
import json
import logging
import os
import random
import re
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

from src.model_client import ModelClient, TokenUsage

_PLACEHOLDER_SET: set[str] = {
    "enter application id",
    "enter full name",
    "enter number",
    "amount in ₹",
    "rent amount",
}

_RADIO_SEPARATOR_RE = re.compile(r'\s{2,}')

# Regex patterns for checkbox/radio selection markers in Chandra OCR text
_CHECKBOX_CHECKED_RE = re.compile(r'\[\s*[✓xX]\s*\]')
_CHECKBOX_UNCHECKED_RE = re.compile(r'\[\s*\]')
_RADIO_CHECKED_RE = re.compile(r'\(\s*[✓xX]\s*\)')
_RADIO_UNCHECKED_RE = re.compile(r'\(\s*\)')

# HTML checkbox symbols for parsing result.html if available
_HTML_CHECKED = '☑'
_HTML_UNCHECKED = '☐'

_CHECKBOX_SUFFIXES: set[str] | None = None

def _get_checkbox_suffixes() -> set[str]:
    global _CHECKBOX_SUFFIXES
    if _CHECKBOX_SUFFIXES is not None:
        return _CHECKBOX_SUFFIXES
    try:
        from src.datalab_schema import SCHEMA_KEY_MAP
        suffixes: set[str] = set()
        for meta in SCHEMA_KEY_MAP.values():
            label = meta["label"]
            parts = re.split(r'\s*[—–\-]\s+', label.lower().strip(), maxsplit=1)
            if len(parts) > 1:
                suffixes.add(parts[-1].strip())
        _CHECKBOX_SUFFIXES = suffixes
    except Exception:
        _CHECKBOX_SUFFIXES = set()
    return _CHECKBOX_SUFFIXES


def _parse_checkbox_radio_options(text: str) -> list[dict] | None:
    """
    Parse checkbox/radio options from Chandra OCR text.
    Returns list of {option: str, selected: bool} if options found, else None.
    """
    options = []
    
    # Match [✓] Option or [ ] Option patterns (square brackets = checkboxes)
    for match in re.finditer(r'\[\s*([✓xX]?)\s*\]\s*([^\n\[\]\(\)]+)', text):
        checked = bool(match.group(1).strip())
        option_text = match.group(2).strip()
        if option_text:
            options.append({"option": option_text, "selected": checked})
    
    # Match (✓) Option or ( ) Option patterns (parentheses = radio)
    for match in re.finditer(r'\(\s*([✓xX]?)\s*\)\s*([^\n\[\]\(\)]+)', text):
        checked = bool(match.group(1).strip())
        option_text = match.group(2).strip()
        if option_text:
            options.append({"option": option_text, "selected": checked})
    
    if options:
        return options
    return None


def _extract_table_from_html(html: str, table_id: str, table_config: dict) -> list[dict] | None:
    """Extract table data from OCR HTML output using BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("BeautifulSoup not available for table parsing")
        return None
    
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table')
    if not tables:
        return None
    
    table = tables[0]
    headers = []
    header_row = table.find('tr')
    if header_row:
        for th in header_row.find_all(['th', 'td']):
            headers.append(th.get_text(strip=True))
    
    col_keys = table_config.get('col_key', [])
    if len(col_keys) != len(headers):
        logger.warning(f"Table {table_id}: column key count mismatch (keys={len(col_keys)}, headers={len(headers)})")
    
    rows = []
    for row in table.find_all('tr')[1:]:
        cells = row.find_all(['td', 'th'])
        if not cells:
            continue
        row_data = {}
        for i, cell in enumerate(cells):
            key = col_keys[i] if i < len(col_keys) else f"col_{i}"
            row_data[key] = cell.get_text(strip=True)
        if row_data:
            rows.append(row_data)
    
    return rows if rows else None


def _is_all_options_line(text: str) -> bool:
    """Check if a line contains only radio/checkbox options (no clear selection)."""
    options_patterns = [
        r'^(?:male|female|others)(?:\s{2,}(?:male|female|others))*$',
        r'^(?:single parent|parentless|having both parents)(?:\s{2,}(?:single parent|parentless|having both parents))*$',
        r'^(?:yes|no|not sure)(?:\s{2,}(?:yes|no|not sure))*$',
        r'^(?:own|rented)(?:\s{2,}(?:own|rented))*$',
        r'^(?:separate bedroom|no separate bedroom)(?:\s{2,}(?:separate bedroom|no separate bedroom))*$',
        r'^(?:separate|common for apartment)(?:\s{2,}(?:separate|common for apartment))*$',
        r'^(?:yes|no)(?:\s{2,}(?:yes|no))*$',
        r'^(?:monthly|daily|weekly|ad.hoc)(?:\s{2,}(?:monthly|daily|weekly|ad.hoc))*$',
    ]
    return any(re.match(p, text) for p in options_patterns)


def _is_option_items_line(line: str) -> bool:
    """Check if a line contains multiple checkbox/radio option items (not a single value).

    Detects lines like '☐ Washing Machine   ☐ Fridge   ☐ AC' or
    'Smartphone   Separate Wi-Fi   Others: _____' where the content
    is a list of options rather than a single field value.
    """
    checkbox_symbols = sum(1 for ch in line if ch in '☐☑○●✓✗▢')
    if checkbox_symbols > 1:
        return True

    stripped = line.strip()
    segments = re.split(r'\s{2,}', stripped)
    if len(segments) >= 3:
        long_count = sum(1 for s in segments if len(s) > 40)
        if long_count <= 1:
            return True

    words = stripped.split()
    if len(words) >= 8:
        colon_idx = stripped.find(':')
        if colon_idx >= 0:
            after_colon = stripped[colon_idx + 1:].strip()
            if after_colon and not re.match(r'^[_\s—–-]+$', after_colon):
                pass
            else:
                short_count = sum(1 for w in words if len(w) <= 15)
                if short_count >= len(words) * 0.8:
                    return True
        else:
            short_count = sum(1 for w in words if len(w) <= 15)
            if short_count >= len(words) * 0.8:
                return True

    if '/' in stripped:
        slash_segments = [s.strip() for s in stripped.split('/')]
        if len(slash_segments) >= 3:
            if all(len(s) <= 40 for s in slash_segments):
                return True

    suffixes = _get_checkbox_suffixes()
    if suffixes:
        match_count = sum(1 for s in suffixes if _matches_suffix(stripped.lower(), s, ""))
        if match_count >= 2:
            return True

    return False


class ChandraOcrClient(ModelClient):
    """OCR client for the Chandra-2 API.

    Single API call like Datalab:
    1. Sends full PDF to POST /v1/ocr → gets markdown text.
    2. Parses the markdown locally into structured fields using the datalab schema.
    No secondary LLM post-processing needed.
    """

    @property
    def needs_images(self) -> bool:
        return False

    def __init__(self, api_key: str, model: str = "chandra-2", base_url: str = "https://chandra.teameverest.ngo/v1/ocr"):
        self.api_key = api_key
        self.model_name = model
        self.base_url = base_url.rstrip("/")
        self.provider = "chandra-2"

        max_concurrent = int(os.environ.get("CHANDRA_MAX_CONCURRENCY", "5"))
        self._api_semaphore = asyncio.Semaphore(max_concurrent)

        self._timeout = float(os.environ.get("CHANDRA_TIMEOUT", "180"))
        self._max_retries = int(os.environ.get("CHANDRA_MAX_RETRIES", "2"))

    async def extract_structured(self, pdf_path: str, page_images: dict[int, str], prompt: str) -> tuple[dict | None, TokenUsage]:
        pdf_data = await self._get_pdf_data(pdf_path, page_images)
        if pdf_data is None:
            return None, TokenUsage()

        async with self._api_semaphore:
            markdown = await self._call_ocr_api(pdf_data)
        if not markdown:
            logger.error("Chandra OCR returned empty text")
            raise RuntimeError("Chandra OCR returned empty text")

        logger.info("Chandra OCR: %d chars received", len(markdown))

        data = self._parse_markdown(markdown)
        data["raw_text"] = markdown
        logger.info("Chandra fields: %d (coverage=%s%%, confidence=%s%%)",
                     len(data.get("fields", [])),
                     data.get("coverage", "?"),
                     data.get("confidence", "?"))
        return data, TokenUsage()

    async def _get_pdf_data(self, pdf_path: str, page_images: dict[int, str]) -> bytes | None:
        if pdf_path and Path(pdf_path).exists():
            with open(pdf_path, "rb") as f:
                return f.read()

        if not page_images:
            logger.error("No PDF path and no page images available")
            return None

        try:
            import fitz
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp_path = tmp.name
            tmp.close()
            doc = fitz.open()
            for p in sorted(page_images):
                page = doc.new_page(width=612, height=792)
                page.insert_image(page.rect, filename=page_images[p])
            doc.save(tmp_path)
            doc.close()
            with open(tmp_path, "rb") as f:
                data = f.read()
            Path(tmp_path).unlink(missing_ok=True)
            return data
        except ImportError:
            logger.error("pymupdf required to create temp PDF from page images")
            return None
        except Exception as e:
            logger.error("Failed to create temp PDF: %s", e)
            return None

    async def _call_ocr_api(self, pdf_data: bytes) -> str:
        files = {
            "model_name": (None, self.model_name),
            "api_key": (None, self.api_key),
            "file": ("document.pdf", pdf_data, "application/pdf"),
        }

        retryable_statuses = {408, 409, 425, 429, 500, 502, 503, 504, 522, 524}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(self._max_retries):
                try:
                    resp = await client.post(self.base_url, files=files)
                    resp.raise_for_status()
                    body = resp.json()
                    return body.get("markdown", "") or ""
                except httpx.HTTPStatusError as e:
                    status = e.response.status_code
                    logger.warning(
                        "Chandra OCR API call failed (attempt %d/%d) status=%s: %s",
                        attempt + 1,
                        self._max_retries,
                        status,
                        e,
                    )
                    if status in retryable_statuses and attempt < self._max_retries - 1:
                        await asyncio.sleep(self._compute_backoff(attempt))
                        continue
                    raise RuntimeError(f"Chandra OCR API returned HTTP {status} after {attempt + 1} attempts.") from e
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    logger.warning(
                        "Chandra OCR API transport error (attempt %d/%d): %s",
                        attempt + 1,
                        self._max_retries,
                        e,
                    )
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(self._compute_backoff(attempt))
                        continue
                    raise RuntimeError("Chandra OCR API transport error after retries") from e
                except Exception as e:
                    logger.warning(
                        "Chandra OCR API unexpected failure (attempt %d/%d): %s",
                        attempt + 1,
                        self._max_retries,
                        e,
                    )
                    if attempt < self._max_retries - 1:
                        await asyncio.sleep(self._compute_backoff(attempt))
                        continue
                    raise RuntimeError("Chandra OCR API unexpected failure after retries") from e
        raise RuntimeError(f"Chandra OCR API call failed after {self._max_retries} attempts.")

    def _compute_backoff(self, attempt: int) -> float:
        base = 2 ** attempt
        jitter = random.uniform(0.2, 1.0)
        return min(base + jitter, 15.0)

    def _parse_markdown(self, markdown: str) -> dict:
        """Parse OCR markdown text into structured fields using the datalab schema."""
        from src.datalab_schema import SCHEMA_KEY_MAP, TABLE_MAP, EXPECTED_FIELD_LABELS

        fields: list[dict] = []
        found_labels: set[str] = set()

        # Parse checkbox/radio options for all labels with "—" (checkbox-style fields)
        checkbox_options: dict[str, list[dict]] = {}
        for key, meta in SCHEMA_KEY_MAP.items():
            label = meta["label"]
            if '—' in label:
                options = _parse_checkbox_radio_options(markdown)
                if options:
                    checkbox_options[label] = options

        # Parse tables from markdown (fallback - HTML tables are in separate result.html)
        table_data: dict[str, list[dict]] = {}
        # We'll parse tables if they appear in markdown, but Chandra puts them in HTML
        # For now, we'll note the table configs for frontend to use with result.html

        for key, meta in SCHEMA_KEY_MAP.items():
            label = meta["label"]
            value = self._extract_value(markdown, label)
            if value is not None:
                found_labels.add(label)
                field_data = {
                    "label": label,
                    "value": value,
                    "confidence": 80,
                    "page": meta["page"],
                    "section": meta["section"],
                }
                # Add checkbox/radio options if available
                if label in checkbox_options:
                    field_data["options"] = checkbox_options[label]
                    field_data["value_type"] = "choice"
                fields.append(field_data)

        # Add table configurations for frontend to parse from HTML
        tables_config = {}
        for table_id, config in TABLE_MAP.items():
            tables_config[table_id] = config

        sections = [
            {"number": 1, "name": "Student Profile", "page": 1},
            {"number": 2, "name": "Family Background", "page": 1},
            {"number": 3, "name": "Housing Condition", "page": 2},
            {"number": 4, "name": "Financial Background", "page": 3},
            {"number": 5, "name": "Health Information", "page": 5},
            {"number": 6, "name": "Student Commitment", "page": 5},
            {"number": 7, "name": "Scholarship Information", "page": 6},
            {"number": 8, "name": "Volunteer Observation", "page": 6},
        ]

        n = len(fields)
        confidence = round(sum(f.get("confidence", 80) for f in fields) / n) if n else 0
        coverage = round(len(found_labels & EXPECTED_FIELD_LABELS) / len(EXPECTED_FIELD_LABELS) * 100) if EXPECTED_FIELD_LABELS else 0
        overall_confidence = round(coverage * confidence / 100)

        return {
            "fields": fields,
            "sections": sections,
            "overall_confidence": overall_confidence,
            "coverage": coverage,
            "confidence": confidence,
            "raw_text": "",
            "tables_config": tables_config,
        }

    @staticmethod
    def _extract_value(markdown: str, label: str) -> str | None:
        """Extract a field value from OCR markdown by searching for the label."""
        lines = markdown.splitlines()
        label_lower = label.lower().strip()

        label_no_num = re.sub(r'^\d+\.\d+\s+', '', label_lower)
        label_no_num = re.sub(r'\s*\[.*?\]', '', label_no_num).strip()

        parts = re.split(r'\s*[—–\-]\s+', label_no_num, maxsplit=1)
        prefix = parts[0] if parts else label_no_num
        unique_suffix = parts[-1].strip() if len(parts) > 1 else ""

        best_score = 0
        best_value = None

        for i, line in enumerate(lines):
            line_s = line.strip()
            if not line_s:
                continue
            line_l = line_s.lower()

            score = 0
            if label_lower in line_l:
                score = 1000
            elif label_no_num in line_l:
                score = 800
            elif unique_suffix and len(unique_suffix) >= 2:
                if _matches_suffix(line_l, unique_suffix, prefix) and prefix in line_l:
                    score = 700

            if score > 0 and score > best_score:
                val = _extract_inline_value(line_s, label_lower)
                if val is not None:
                    best_score = score
                    best_value = val
                    continue

                next_idx = i + 1
                while next_idx < len(lines):
                    nxt = lines[next_idx].strip()
                    next_idx += 1
                    if not nxt:
                        continue
                    if nxt.lower().startswith(('section', 'page', '#', '**', '###')):
                        break
                    if re.match(r'^\d+\.\d', nxt):
                        break
                    nxt_lower = nxt.lower()
                    if nxt_lower in _PLACEHOLDER_SET:
                        continue
                    if '—' in label_lower:
                        if _is_all_options_line(nxt_lower):
                            break
                        if _is_option_items_line(nxt):
                            break
                        checkbox_suffixes = _get_checkbox_suffixes()
                        if checkbox_suffixes and score < 800:
                            colon_pos = nxt_lower.find(':')
                            if colon_pos >= 0:
                                nxt_before = nxt_lower[:colon_pos].strip()
                                nxt_after = nxt_lower[colon_pos + 1:].strip()
                                if nxt_before in checkbox_suffixes and _is_placeholder(nxt_after):
                                    continue
                            else:
                                if nxt_lower.rstrip('.') in checkbox_suffixes:
                                    continue
                    best_score = score
                    best_value = nxt
                    break

        if best_value:
            best_value = best_value.strip().rstrip('.')
            best_value = _clean_value(best_value, label_lower)
            if best_value and not _is_placeholder(best_value):
                return best_value

        return None


def _is_placeholder(value: str) -> bool:
    """Check if value is a form placeholder rather than actual filled data."""
    v = value.strip().lower().rstrip('.')
    if not v or v in ('—', '-', 'na', 'n/a', 'none'):
        return True
    if re.match(r'^[_\s—–-]+$', v):
        return True
    if re.match(r'^(?:—\s*)?na(?:\s*—)?$', v):
        return True
    if re.match(r'^(?:—\s+)?na\s+—$', v):
        return True
    if v.startswith('enter ') or v.startswith('enter your '):
        return True
    colon_pos = v.rfind(':')
    if colon_pos > 0:
        after = v[colon_pos + 1:].strip()
        if after and re.match(r'^[_\s—–-]+$', after):
            return True
    return False


def _matches_suffix(text: str, suffix: str, prefix: str) -> bool:
    """Check if suffix appears as a whole word (or hyphenated segment) in text."""
    pattern = r'(?:^|[\s\-/])' + re.escape(suffix) + r'(?:$|[\s\-/:])'
    return bool(re.search(pattern, text))


def _extract_inline_value(line: str, label_lower: str) -> str | None:
    """Extract value from a line like 'Label: value' where the label is potentially normalized."""
    if '—' in label_lower and _is_option_items_line(line):
        return None

    label_clean = re.sub(r'^\d+\.\d+\s+', '', label_lower).strip()
    label_clean = re.sub(r'\s*\[.*?\]', '', label_clean).strip()

    parts = re.split(r'\s*[—–\-]\s+', label_clean, maxsplit=1)
    unique_suffix = parts[-1].strip() if len(parts) > 1 else ""

    colon_idx = line.rfind(":")
    if colon_idx > 0:
        before = line[:colon_idx].strip().lower()
        after = line[colon_idx + 1:].strip()
        if after:
            if unique_suffix and len(unique_suffix) >= 2:
                if _matches_suffix(before, unique_suffix, ""):
                    return after
            if label_clean in before:
                return after
            if label_lower in before:
                return after

    for sep in ['—', '–', '-']:
        sep_idx = line.rfind(sep)
        if sep_idx > 0:
            before = line[:sep_idx].strip().lower()
            after = line[sep_idx + 1:].strip()
            if after and len(after) < 200:
                if label_clean in before or label_lower in before:
                    return after

    return None


def _clean_value(value: str, label_lower: str) -> str:
    """Normalize and clean an extracted value."""
    value = value.strip()
    value = re.sub(r'\s+', ' ', value)

    value_lower = value.lower().strip()

    if value_lower == label_lower:
        return ""

    for lv in [label_lower, re.sub(r'^\d+\.\d+\s+', '', label_lower), re.sub(r'\s*\[.*?\]', '', label_lower).strip()]:
        if not lv:
            continue
        if value_lower == lv:
            return ""
        if value_lower.startswith(lv):
            value = value[len(lv):].strip().lstrip(':—–- ').strip()
            value_lower = value.lower().strip()
            break

    value = re.sub(r'^\d+\.\d+\s*', '', value).strip()
    value = re.sub(r'^\s*[:—–-]\s*', '', value).strip()

    return value
