"""Rule-based markdown parser for Chandra OCR output.

Replaces the NVIDIA LLM extraction call with a deterministic parser.
Operates on Chandra's markdown transcription of the fixed 6-page questionnaire.
"""

import logging
import re

from src.extraction_pipeline import KNOWN_TEMPLATE_FIELDS

logger = logging.getLogger(__name__)

# ── Helper regexes ──────────────────────────────────────────────────────

# Matches "**Label:** value" (colon inside bold) or "**Label:** value" (colon after bold)
# or "**Label** Value" (no colon) or "Label: value" (plain)
_BOLD_COLON_INSIDE_RE = re.compile(r"\*\*(.+?):\*\*\s*(.*)")  # "**Label:** Value"
_BOLD_LABEL_RE = re.compile(r"\*\*(.+?)\*\*\s*:\s*(.*)")     # "**Label:** Value"
_BOLD_NC_RE = re.compile(r"\*\*(.+?)\*\*\s+(.*)")            # "**Label** Value" no colon
_LABEL_COLON_RE = re.compile(r"^(.+?):\s*(.*)$")             # "Label: value"

# ✓ / ✗ detection
_CHECK_MARK = re.compile(r"[✓✔☑✅]")
_CROSS_MARK = re.compile(r"[✗✘☒❌]")

# Table row detection in markdown tables: | cell | cell | cell |
_TABLE_CELL_RE = re.compile(r"\|\s*([^|]+?)\s*\|")

# N/A detection (conditional field sentinel)
_NA_RE = re.compile(r"\bN\s*/\s*A\b", re.IGNORECASE)

# Placeholder text patterns — Chandra sometimes extracts form labels as field values
_PLACEHOLDER_PATTERNS: list[re.Pattern] = [
    re.compile(r"^Amount\s+in\s*", re.IGNORECASE),
    re.compile(r"^Describe\s+", re.IGNORECASE),
    re.compile(r"^##?[#,#.\s]*[₹$£€]?$"),
    re.compile(r"^-?\s*Select\s*-?$", re.IGNORECASE),
    re.compile(r"^If\s+others", re.IGNORECASE),
    re.compile(r"^\s*[-–—]+\s*$"),
]

# Detect single lines that look like unchecked options: "☐ Option" or "- [ ] Option"
_UNCHECKED_BOX = re.compile(r"[☐❑⧠]|-\s*\[\s*\]")

# Detect content after a checkbox: "- [✓] Option" or "✓ Option"
_CHECKBOX_VALUE = re.compile(r"[-\s]*\[([✓✗])\]\s*(.*)|([✓✗])\s+(.*)")

# Strip markdown formatting
_MD_BOLD_RE = re.compile(r"\*\*(.*?)\*\*")
_MD_ITALIC_RE = re.compile(r"\*(.*?)\*")

def _clean(text: str) -> str:
    return _MD_BOLD_RE.sub(r"\1", _MD_ITALIC_RE.sub(r"\1", text)).strip()

def _is_yes(val: str) -> bool:
    return val.strip().lower() in ("yes", "y", "true", "1", "✓", "✔", "☑")

def _is_no(val: str) -> bool:
    return val.strip().lower() in ("no", "n", "false", "0", "✗", "✘")

def _is_na(val: str) -> bool:
    return bool(_NA_RE.search(val))

# Inline checkbox pattern: "☐ Yes ☒ No" or "☒ Yes ☐ No ☐ Maybe"
_INLINE_CHECKBOX_RE = re.compile(r"(?:☐|☒|☑|✓|✗)\s*([^☐☒☑✓✗]+?)(?=\s*(?:☐|☒|☑|✓|✗|$))")


def _extract_inline_checkbox(value: str) -> str | None:
    """Extract the checked option from inline checkboxes like '☐ Yes ☒ No' → 'No'.

    Searches for ☒ (checked) and returns the option text after it.
    Falls back to ☑ or ✓ if no ☒ is found.
    """
    if not value:
        return None
    if "☐" not in value and "☒" not in value:
        return None
    # Find all checkbox-option pairs in order
    pairs = _INLINE_CHECKBOX_RE.findall(value)
    if not pairs:
        return None
    # Scan value for checked markers in order
    positions: list[tuple[int, str, str]] = []
    for m in re.finditer(r"[☒☑✓]|(?<=☐)✗", value):
        # Get the option text after this marker
        start = m.end()
        next_m = re.search(r"[☐☒☑✓✗]", value[start:])
        end = start + next_m.start() if next_m else len(value)
        option = _clean(value[start:end])
        if option:
            positions.append((m.start(), m.group(), option))
    # Return first non-empty checked option
    for _, marker, option in positions:
        if marker in ("☒", "☑", "✓"):
            return option
    return None


def _score_value(value: str) -> int:
    """Assign a confidence score to an extracted value."""
    if not value:
        return 0
    v = value.strip()
    if not v:
        return 0
    if v == "N/A":
        return 90  # intentional "not applicable"
    if v in ("✓", "✗", "Yes", "No"):
        return 95
    if len(v) >= 3 and any(c.isalpha() for c in v):
        return 90
    if v.replace(",", "").replace(".", "").replace(" ", "").isdigit():
        return 85
    return 70

# ── Page assignment per known label (from KNOWN_TEMPLATE_FIELDS) ───────

_PAGE_MAP: dict[str, int] = {}
_SECTION_MAP: dict[str, int | None] = {}
for tpl in KNOWN_TEMPLATE_FIELDS:
    _PAGE_MAP[tpl["label"]] = tpl["page"]
    _SECTION_MAP[tpl["label"]] = tpl["section_number"]

# Build reverse lookup: label prefixes for checkbox groups
_CHECKBOX_PREFIXES: dict[str, list[str]] = {}
for label in _PAGE_MAP:
    if " — " in label:
        base = label.split(" — ")[0]
        _CHECKBOX_PREFIXES.setdefault(base, []).append(label)

# Table row fields: "Label — Row N — Column"
_ROW_RE = re.compile(r"^(.+?)\s*—\s*Row\s+(\d+)\s*—\s*(.+)$")

_TABLE_PARENTS: dict[str, str] = {
    "2.5 Family Members": "family_members",
    "4.3.1 If yes, list their properties": "other_assets_details",
    "4.4.1 If yes, list other sources of income": "other_income_sources",
    "4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount": "loan_details",
}

# Conditional subfields: parent → children
_CONDITIONAL_FIELDS: dict[str, list[str]] = {
    "3.1 House Ownership": ["3.1.1 If rented, what is the rent amount?"],
    "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student?":
        ["4.3.1 If yes, list their properties"],
    "4.4 Apart from your job, is there any other source of income?":
        ["4.4.1 If yes, list other sources of income"],
    "4.6 Do you have any loans?":
        ["4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount"],
    "5.1 Does the student have any health issues?":
        ["5.2 If yes, list the health issues"],
    "2.1 Family Status": [
        "2.2 Relationship Details — Year of Death / Separation",
        "2.2 Relationship Details — Reason for Death / Separation",
    ],
}


def _normalize_label(label: str) -> str:
    """Strip section number prefix for fuzzy matching."""
    text = re.sub(r"^\d+(\.\d+)*\s+", "", label)
    text = text.replace("/", " / ").strip()
    return re.sub(r"\s+", " ", text).lower()


def _extract_markdown_lines(md: str) -> list[str]:
    """Split markdown into non-empty, non-header-only lines."""
    lines = []
    for line in md.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue  # skip section headers
        # Skip separator lines
        if re.match(r"^[-|=]{3,}$", stripped):
            continue
        lines.append(stripped)
    return lines


def _match_label_in_line(label: str, line: str) -> bool:
    """Check if a cleaned markdown line contains the given label as a distinct phrase."""
    label_lower = _normalize_label(label)
    line_lower = line.lower()
    # Use leading word-boundary to avoid matching "volunteer name" inside "co-volunteer name"
    def _safe_match(needle: str, haystack: str) -> bool:
        # Word boundary at start ensures no prefix overlap
        m = re.search(r'(?<!\w)' + re.escape(needle), haystack)
        if not m:
            return False
        # After the match, ensure the label isn't followed by more word chars
        # (e.g., "income" matched in "income." is ok, but "income" in "incometax" is not)
        end = m.end()
        if end < len(haystack) and haystack[end].isalnum():
            return False
        return True

    if _safe_match(label_lower, line_lower):
        return True
    # Try matching without section prefix
    label_clean = re.sub(r"^\d+(\.\d+)*\s+", "", label_lower).strip()
    if label_clean and _safe_match(label_clean, line_lower):
        return True
    # Try matching with compaction (no space around / etc.)
    label_compact = re.sub(r"\s*/\s*", "/", label_lower)
    if label_compact != label_lower and label_compact in line_lower:
        return True
    label_clean_compact = re.sub(r"\s*/\s*", "/", label_clean)
    if label_clean_compact and label_clean_compact != label_clean and label_clean_compact in line_lower:
        return True
    return False


def _labels_match(extracted_label: str, known_label: str) -> bool:
    """Check if an extracted label matches a known label (fuzzy comparison)."""
    norm_ext = _normalize_label(extracted_label).rstrip(":")
    norm_known = _normalize_label(known_label).rstrip(":")
    if norm_ext == norm_known:
        return True
    # Allow prefix-number stripping: "1.2 student full name" == "student full name"
    clean_ext = re.sub(r"^\d+(\.\d+)*\s+", "", norm_ext).strip()
    clean_known = re.sub(r"^\d+(\.\d+)*\s+", "", norm_known).strip()
    if clean_ext == clean_known:
        return True
    return False


def _extract_value_after_colon(line: str, label: str) -> str | None:
    """Extract value from a line like '**Label:** Value' or 'Label: value'."""
    # 1) **Label:** Value  (colon inside bold — Chandra's format)
    m = _BOLD_COLON_INSIDE_RE.search(line)
    if m:
        ltext = _clean(m.group(1))
        rtext = _clean(m.group(2))
        if _labels_match(ltext, label):
            if rtext:
                return rtext
            return None  # empty string = value not found, fall through to next line

    # 2) **Label:** value  (colon after bold)
    m = _BOLD_LABEL_RE.search(line)
    if m:
        ltext = _clean(m.group(1))
        rtext = _clean(m.group(2))
        if _labels_match(ltext, label) and rtext:
            return rtext

    # 3) **Label** Value  (bold without colon)
    m = _BOLD_NC_RE.search(line)
    if m:
        ltext = _clean(m.group(1)).rstrip(":")
        rtext = _clean(m.group(2))
        if _labels_match(ltext, label):
            if rtext and not rtext.startswith("**"):
                return rtext

    # 4) Label: value  (plain colon)
    m = _LABEL_COLON_RE.search(line)
    if m:
        ltext = _clean(m.group(1))
        rtext = _clean(m.group(2))
        if rtext and _labels_match(ltext, label):
            return rtext

    return None


def _find_value_in_lines(label: str, lines: list[str], start_idx: int = 0) -> tuple[str | None, int]:
    """Search lines for label followed by a value. Returns (value, line_idx)."""
    for i, line in enumerate(lines[start_idx:], start=start_idx):
        if not _match_label_in_line(label, line):
            continue
        # Check colon-separated value on same line
        val = _extract_value_after_colon(line, label)
        if val is not None:
            return val, i
        # Check next line for the value
        if i + 1 < len(lines):
            next_line = lines[i + 1]
            # Value line shouldn't be another field — skip if it looks like a label
            if next_line and not re.match(r'^-?\s*\*\*|^\d+\.\d+\s', next_line):
                # Also skip if next line contains a known template label
                next_lower = next_line.lower()
                is_known_label = any(
                    _normalize_label(kl) in next_lower
                    for kl in _PAGE_MAP
                )
                if not is_known_label:
                    return _clean(next_line), i
        # If line itself contains the label and something else, try extracting from the remainder
        if ":" not in line:
            label_lower = _normalize_label(label)
            line_lower = line.lower()
            idx = line_lower.find(label_lower)
            if idx < 0:
                label_lower = re.sub(r"\s*/\s*", "/", label_lower)
                idx = line_lower.find(label_lower)
            if idx >= 0:
                rest = line[idx + len(label_lower):].strip()
                if rest:
                    return _clean(rest), i
    return None, -1


def _extract_checkbox_list(label: str, lines: list[str]) -> list[tuple[str, str]]:
    """Extract checkbox options for a group like '3.2 Type of Home'.

    Returns list of (option_text, value) where value is ✓ or ✗.
    """
    results: list[tuple[str, str]] = []
    label_lower = _normalize_label(label)
    in_section = False

    for line in lines:
        line_stripped = line.strip()
        line_lower = line_stripped.lower()
        norm_label = _normalize_label(label)
        norm_label_compact = re.sub(r"\s*/\s*", "/", norm_label)

        # Detect section boundary
        if (norm_label in line_lower or norm_label_compact in line_lower) and not _CHECK_MARK.search(line) and not _CROSS_MARK.search(line):
            in_section = True
            continue

        if not in_section:
            continue

        # Another known top-level label means we left this checkbox section
        if any(_normalize_label(l) == line_lower for l in _PAGE_MAP if " — " not in l and l != label):
            break

        # Check for ✓/✗ patterns
        checked = _CHECK_MARK.search(line_stripped)
        unchecked = _CROSS_MARK.search(line_stripped)
        if checked or unchecked:
            value = "✓" if checked else "✗"
            # Extract option text (remove checkbox symbol)
            parts = re.split(r"[✓✔✗✘☑☒]|\|", line_stripped, maxsplit=1)
            option = _clean(parts[0] if parts else line_stripped).strip(" -:") or _clean(parts[1] if len(parts) > 1 else "").strip(" -:")
            if option and len(option) < 50:  # plausibly an option, not a sentence
                results.append((option, value))

    return results


def _extract_table(md: str) -> list[dict]:
    """Parse markdown tables and return row data.

    Each table returns: {"table_name": str, "rows": [{"col": "val", ...}]}
    """
    tables: list[dict] = []
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Detect markdown table: line with | separator
        if line.startswith("|") and line.endswith("|") and line.count("|") >= 2:
            rows: list[list[str]] = []
            # Check next line is separator
            if i + 1 < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1]):
                headers = [_clean(h) for h in _TABLE_CELL_RE.findall(line)]
                i += 2  # skip header + separator
                while i < len(lines):
                    rline = lines[i].strip()
                    if not rline.startswith("|"):
                        break
                    cells = [c.strip() for c in _TABLE_CELL_RE.findall(rline)]
                    if cells and not all(c == "" or c == "-" or c == "—" for c in cells):
                        rows.append(cells)
                    i += 1
                if headers and rows:
                    # Determine table name from context (find the heading before this table)
                    table_name = ""
                    for j in range(max(0, i - 10 - len(rows)), i - len(rows)):
                        prev = lines[j].strip()
                        if prev.startswith("##") or prev.startswith("#"):
                            table_name = _clean(prev.lstrip("#").strip())
                            break
                        if prev and not prev.startswith("|") and len(prev) < 60:
                            table_name = _clean(prev)
                    tables.append({
                        "table_name": table_name,
                        "headers": headers,
                        "rows": [{headers[k]: v for k, v in enumerate(row[:len(headers)])} for row in rows],
                    })
                continue
        i += 1
    return tables


def parse_markdown(md: str) -> dict:
    """Parse Chandra markdown and return structured field data.

    Args:
        md: Chandra-2 markdown output
        tesseract_texts: Optional dict of page_num → Tesseract OCR raw text
                         (used as fallback for fields Chandra couldn't read)

    Returns:
        {
            "fields": [{"label": "...", "value": "...", "confidence": int, "page": int,
                        "needs_clarification": bool, "section": int | None, "reason": str | None}, ...],
            "overall_confidence": int,
            "raw_text": str,  # original markdown
            "sections": [...],
        }
    """
    lines = _extract_markdown_lines(md)

    # ── Pass 1: Direct label→value extraction ──────────────────────
    field_map: dict[str, dict] = {}
    for label in _PAGE_MAP:
        value, idx = _find_value_in_lines(label, lines)
        if value is not None:
            field_map[label] = _make_field(label, value)

    # ── Pass 1b: Inline checkbox resolution ─────────────────────────
    # Chandra often renders Yes/No/checkbox fields as inline text like
    # "☐ Yes ☒ No" instead of a clean "No". Extract the checked option.
    for label, field in field_map.items():
        raw_val = field.get("value", "")
        checked = _extract_inline_checkbox(raw_val)
        if checked is not None:
            sanitized = checked.strip()
            if sanitized and not any(
                c in sanitized for c in ("☐", "☒", "☑", "✓", "✗")
            ):
                field["value"] = sanitized
                field["confidence"] = _score_value(sanitized)

    # ── Pass 2: Checkbox groups ────────────────────────────────────
    for base, child_labels in _CHECKBOX_PREFIXES.items():
        options = _extract_checkbox_list(base, lines)
        matched_options: set[str] = set()
        for option, val in options:
            for cl in child_labels:
                cl_option = cl.split(" — ", 1)[1] if " — " in cl else ""
                if cl_option and _normalize_label(cl_option) == _normalize_label(option):
                    field_map[cl] = _make_field(cl, val)
                    matched_options.add(option)
                    break
                elif _normalize_label(cl_option) in _normalize_label(option) or _normalize_label(option) in _normalize_label(cl_option):
                    field_map[cl] = _make_field(cl, val)
                    matched_options.add(option)
                    break

    # ── Pass 3: Tables → row fields ────────────────────────────────
    tables = _extract_table(md)
    for table_info in tables:
        table_name = table_info["table_name"]
        headers = table_info["headers"]
        rows = table_info["rows"]

        # Try to match table name to KNOWN_TEMPLATE_FIELDS patterns
        matched_parent = None
        for parent_label in _TABLE_PARENTS:
            if _normalize_label(parent_label) in _normalize_label(table_name) or \
               _normalize_label(table_name) in _normalize_label(parent_label):
                matched_parent = parent_label
                break

        if not matched_parent:
            # Try matching by header content
            header_text = " ".join(headers).lower()
            if "name" in header_text and "age" in header_text:
                matched_parent = "2.5 Family Members"

        if matched_parent and headers:
            # Map Chandra table headers to known column names
            col_map = _infer_table_columns(matched_parent, headers)
            for row_idx, row_data in enumerate(rows):
                row_num = row_idx + 1
                for chandra_col, known_col in col_map.items():
                    if chandra_col in row_data:
                        label = f"{matched_parent} — Row {row_num} — {known_col}"
                        val = row_data[chandra_col]
                        if val and val not in ("", "-", "—"):
                            field_map[label] = _make_field(label, val)

    # ── Pass 4: Conditional fields ─────────────────────────────────
    for parent_label, child_labels in _CONDITIONAL_FIELDS.items():
        parent_field = field_map.get(parent_label)
        if parent_field:
            parent_val = parent_field["value"]
            if _is_no(parent_val):
                # Parent is "No" → children are "N/A"
                for cl in child_labels:
                    # Only set N/A if field has no real value (empty or placeholder-rejected)
                    existing = field_map.get(cl, {})
                    existing_val = existing.get("value", "")
                    if not existing_val:
                        field_map[cl] = _make_field(cl, "N/A", section=_SECTION_MAP.get(cl))
            elif _is_na(parent_val):
                # The parent itself might be N/A if not applicable
                pass

    # ── Pass 4c: Fix header fields from Volunteer Name HTML ──────
    # Chandra often embeds all header values in the Volunteer Name line:
    #   "<br><u>HARINATH ARON</u> | Co-Volunteer Name:<br><u></u> | Date of Visit:<br><u>28/6/26.</u> |"
    # Meanwhile Co-Volunteer Name and Date of Visit show wrong placeholder "Application ID".
    vol_field = field_map.get("Volunteer Name", {})
    vol_val = vol_field.get("value", "")
    if vol_val and ("| Co-Volunteer Name:" in vol_val or "| Date of Visit:" in vol_val):
        # Extract values from the concatenated HTML string
        vol_match = re.search(r"<u>([^<]*)</u>\s*\|", vol_val)
        if vol_match:
            vol_field["value"] = vol_match.group(1).strip() or ""
        cov_match = re.search(r"Co-Volunteer Name:?\s*<br><u>([^<]*)</u>", vol_val)
        if cov_match:
            cov_val = cov_match.group(1).strip()
            if cov_val:
                field_map.setdefault("Co-Volunteer Name", {}).update({"value": cov_val})
            else:
                # Remove placeholder "Application ID" from Co-Volunteer Name
                cov_field = field_map.get("Co-Volunteer Name", {})
                if cov_field.get("value") in ("Application ID", ""):
                    field_map["Co-Volunteer Name"] = _make_field("Co-Volunteer Name", "")
        dov_match = re.search(r"Date of Visit:?\s*<br><u>([^<]*)</u>", vol_val)
        if dov_match:
            dov_val = dov_match.group(1).strip()
            if dov_val:
                field_map.setdefault("Date of Visit", {}).update({"value": dov_val})
            else:
                dov_field = field_map.get("Date of Visit", {})
                if dov_field.get("value") in ("Application ID", ""):
                    field_map["Date of Visit"] = _make_field("Date of Visit", "")

    # ── Pass 5: Fill missing known template fields ─────────────────
    for tpl in KNOWN_TEMPLATE_FIELDS:
        label = tpl["label"]
        if label not in field_map:
            # Check if this is a table row field (should be generated by table parser)
            row_match = _ROW_RE.match(label)
            if row_match:
                table_parent = row_match.group(1).strip()
                if _TABLE_PARENTS.get(table_parent) and _TABLE_PARENTS.get(table_parent):
                    continue
            # Checkbox child that wasn't matched
            if " — " in label and not _ROW_RE.match(label):
                base = label.split(" — ")[0]
                # If we're in the checkbox group but this option wasn't found, set as unchecked
                if base in _CHECKBOX_PREFIXES and any(
                    _normalize_label(base) in _normalize_label(k) for k in field_map
                ):
                    field_map[label] = _make_field(label, "✗")
                    continue

    # ── Build output ────────────────────────────────────────────────
    fields = list(field_map.values())
    fields.sort(key=lambda f: (f["page"], f["label"]))

    # Compute overall confidence
    confs = [f["confidence"] for f in fields if f["confidence"] > 0]
    overall_confidence = int(sum(confs) / len(confs)) if confs else 70

    # Build sections from KNOWN_TEMPLATE_FIELDS
    seen_sections = set()
    sections = []
    for tpl in KNOWN_TEMPLATE_FIELDS:
        sn = tpl["section_number"]
        if sn is not None and sn not in seen_sections:
            seen_sections.add(sn)
            sections.append({"number": sn, "name": ""})
    sections.sort(key=lambda s: s["number"])

    return {
        "fields": fields,
        "overall_confidence": overall_confidence,
        "raw_text": md,
        "sections": sections,
    }


def _is_placeholder(value: str) -> bool:
    """Check if a value matches known form placeholder text patterns."""
    stripped = value.strip()
    if not stripped:
        return False
    for pattern in _PLACEHOLDER_PATTERNS:
        if pattern.search(stripped):
            return True
    return False


def _make_field(
    label: str,
    value: str,
    confidence: int | None = None,
    section: int | None = None,
) -> dict:
    # Reject placeholder text extracted as field values
    if value and _is_placeholder(value):
        value = ""
        confidence = 0
    return {
        "label": label,
        "value": value,
        "confidence": confidence if confidence is not None else _score_value(value),
        "page": _PAGE_MAP.get(label, 1),
        "needs_clarification": value in ("", "N/A") or _is_na(value),
        "reason": None,
        "section": section if section is not None else _SECTION_MAP.get(label),
    }


def _infer_table_columns(parent_label: str, chandra_headers: list[str]) -> dict[str, str]:
    """Map Chandra table header names to known column names for this table."""
    # Define expected column names per table
    expected: dict[str, list[str]] = {
        "2.5 Family Members": ["Name", "Age", "Education", "Occupation", "Annual Income"],
        "4.3.1 If yes, list their properties": ["Property Description", "Owner Name", "Approximate Value"],
        "4.4.1 If yes, list other sources of income": ["Source of Income", "Amount"],
        "4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount":
            ["Loan Purpose", "Loan Amount Taken", "Pending Loan Amount"],
    }

    cols = expected.get(parent_label, [])
    used: set[str] = set()
    result: dict[str, str] = {}
    # First pass: fuzzy match but skip already-mapped columns and #/Sr.No headers
    for i, ch in enumerate(chandra_headers):
        ch_clean = _clean(ch)
        if ch_clean.lower() in ("#", "sr", "sr.", "sr. no.", "sr no", "no", "s.no"):
            continue
        best = None
        best_score = 0
        for c in cols:
            if c in used:
                continue
            score = len(set(ch_clean.lower().split()) & set(c.lower().split()))
            if score > best_score:
                best_score = score
                best = c
        if best and best_score > 0:
            result[ch_clean] = best
            used.add(best)
    # Second pass: positional fallback for any unmapped Chandra headers
    remaining_ch = [(i, _clean(ch)) for i, ch in enumerate(chandra_headers)
                    if _clean(ch) not in result and _clean(ch).lower() not in ("#", "sr", "sr.", "sr. no.", "sr no", "no", "s.no")]
    for i, ch_clean in remaining_ch:
        for j, c in enumerate(cols):
            if c not in used and j < len(chandra_headers) and abs(j - i) <= 1:
                result[ch_clean] = c
                used.add(c)
                break
        else:
            # Last resort: assign first unused column
            for c in cols:
                if c not in used:
                    result[ch_clean] = c
                    used.add(c)
                    break
    return result
