import re

_TABLE_ROW_RE = re.compile(r"(.+?) — Row (\d+) — (.+)")

_OPTION_CHARS = {"✓", "✗", "●", "○"}
_CHECKED = {"✓", "●"}

_CHECK_MARK = "\u2611"
_UNCHECK_MARK = "\u2610"


def _format_job_datetime(job_id: str) -> str:
    parts = job_id.split("_")
    if len(parts) >= 3:
        date_str = parts[-2]
        time_str = parts[-1].replace("-", ":")
        return f"{date_str} {time_str}"
    return "Unknown"


def _is_option(value: str) -> bool:
    return value in _OPTION_CHARS


def _is_checked(value: str) -> bool:
    return value in _CHECKED


def _render_markdown(data: dict, job_id: str) -> str:
    lines = []

    dt = _format_job_datetime(job_id)
    num_pages = data.get("num_pages", "?")
    lines.append("# OCR Extraction Results — Home Visit Questionnaire")
    lines.append("")
    lines.append(f"**Job:** `{job_id}`  ·  **Date:** {dt}  ·  **Pages:** {num_pages}")
    lines.append("")
    lines.append("---")
    lines.append("")

    fields = data.get("fields", [])
    if not fields:
        lines.append("_No fields extracted._")
        lines.append("")
        return "\n".join(lines)

    pages: dict[int, list[dict]] = {}
    for f in fields:
        pages.setdefault(f["page"], []).append(f)

    for page_num in sorted(pages):
        page_fields = pages[page_num]
        lines.append(f"## Page {page_num}")
        lines.append("")

        regular: list[dict] = []
        checkbox_groups: dict[str, list[tuple[str, str]]] = {}
        table_groups: dict[str, dict[int, dict[str, str]]] = {}

        for f in page_fields:
            label = f["label"]
            value = f["value"] or ""

            table_match = _TABLE_ROW_RE.match(label)
            if table_match:
                group_key = table_match.group(1).strip()
                row_num = int(table_match.group(2))
                col_name = table_match.group(3).strip()
                table_groups.setdefault(group_key, {})
                table_groups[group_key].setdefault(row_num, {})
                table_groups[group_key][row_num][col_name] = value
                continue

            last_dash = label.rfind(" — ")
            if last_dash > 0 and _is_option(value):
                group_key = label[:last_dash].strip()
                option = label[last_dash + 3:].strip()
                checkbox_groups.setdefault(group_key, [])
                checkbox_groups[group_key].append((option, value))
                continue

            regular.append(f)

        for group_key, options in checkbox_groups.items():
            lines.append(f"### {group_key}")
            lines.append("")
            for option, val in options:
                symbol = _CHECK_MARK if _is_checked(val) else _UNCHECK_MARK
                lines.append(f"{symbol} **{option}**")
            lines.append("")

        for group_key, rows in table_groups.items():
            lines.append(f"### {group_key}")
            lines.append("")
            sorted_row_nums = sorted(rows.keys())
            all_cols: list[str] = []
            seen = set()
            for rn in sorted_row_nums:
                for col in rows[rn]:
                    if col not in seen:
                        all_cols.append(col)
                        seen.add(col)

            if not all_cols:
                continue

            header = "| # | " + " | ".join(f"**{c}**" for c in all_cols) + " |"
            sep = "|---|" + "|".join(["---"] * len(all_cols)) + "|"
            lines.append(header)
            lines.append(sep)
            for rn in sorted_row_nums:
                row_data = rows[rn]
                cells = " | ".join(row_data.get(col, "") or "—" for col in all_cols)
                lines.append(f"| {rn} | {cells} |")
            lines.append("")

        if regular:
            for f in regular:
                label = f["label"]
                value = f["value"] or ""
                lines.append(f"- **{label}:** {value}")
            lines.append("")

    return "\n".join(lines)


def _render_text(data: dict, job_id: str) -> str:
    lines = [
        "OCR EXTRACTION RESULTS",
        "======================",
        f"Job ID: {job_id}",
        f"Date Created: {_format_job_datetime(job_id)}",
        f"Overall Confidence: {data.get('overall_confidence', '?')}%",
        f"Processing Time: {data.get('processing_time', '?')}s",
        f"Number of Pages: {data.get('num_pages', '?')}",
        "",
        "=" * 60,
        "",
    ]
    pages: dict[int, list[dict]] = {}
    for f in data.get("fields", []):
        pages.setdefault(f["page"], []).append(f)
    for page_num in sorted(pages):
        page_fields = pages[page_num]
        lines.append(f"Page {page_num}:")
        lines.append("-" * 40)
        for f in page_fields:
            label = f["label"]
            value = f["value"] or "(empty)"
            conf = f["confidence"]
            badges = []
            if f.get("needs_clarification"):
                badges.append("needs clarification")
            if f.get("is_verified"):
                badges.append("verified")
            badge_str = f" ({', '.join(badges)})" if badges else ""
            lines.append(f"  {label}: {value} (conf: {conf}%){badge_str}")
            if f.get("reason"):
                lines.append(f"    Reason: {f['reason']}")
            if f.get("verification_note") and f["verification_note"] != "High confidence, auto-accepted":
                lines.append(f"    Note: {f['verification_note']}")
        lines.append("")
    return "\n".join(lines)
