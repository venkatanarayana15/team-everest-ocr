"""Shared section definitions derived from KNOWN_TEMPLATE_FIELDS.

Avoids hardcoding section-to-page mappings in multiple files.
Uses lazy import to avoid circular dependency with extraction_pipeline/datalab_schema.
"""

SECTION_NAMES = {
    1: "Student Profile",
    2: "Family Background",
    3: "Housing Condition",
    4: "Financial Background",
    5: "Health Information",
    6: "Student Commitment",
    7: "Scholarship Information",
    8: "Volunteer Observation",
}


def compute_sections() -> list[dict]:
    """Compute sections list dynamically from KNOWN_TEMPLATE_FIELDS."""
    from src.extraction_pipeline import KNOWN_TEMPLATE_FIELDS
    section_pages: dict[int, set[int]] = {}
    for tpl in KNOWN_TEMPLATE_FIELDS:
        sn = tpl.get("section_number")
        if sn is None:
            continue
        section_pages.setdefault(sn, set()).add(tpl["page"])
    return [
        {"number": sn, "name": SECTION_NAMES.get(sn, f"Section {sn}"), "page": min(pages)}
        for sn, pages in sorted(section_pages.items())
    ]
