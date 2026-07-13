"""JSON schema + response mapper for Datalab /api/v1/extract.

Checkbox Mark Resolution (v3):
    Multi-option checkbox fields are extracted as per-option mark descriptions
    (e.g. "tick", "cross", "slash", "empty") instead of asking Datalab to choose
    the correct option.  Deterministic Python post-processing then resolves
    which option is SELECTED.

    Single-checkbox fields (4.1 assets, 3.2 home type, 3.3 ceiling, 2.4 govt IDs)
    use the same mark-description approach: a "tick" or "slash" mark is resolved to
    "✓"; a "cross", "dot", "scribble", or "empty" mark is resolved to None (skipped).

    This sidesteps Datalab's inability to distinguish ✗ from ✓ at the pixel
    level — it only needs to describe the mark shape, not reason about it.
"""

import json
import logging
import re
from dataclasses import dataclass
from src.sections import compute_sections

_logger = logging.getLogger(__name__)

_CHECKBOX_SYMBOLS = re.compile(r"[\u2713\u2714\u2717\u2718\u271A\u2611\u2612\u274C\u274E\u2705\u2716\u00D7\u2A09\u2A02\u2A2F]")
_TICK_SYMBOLS = re.compile(r"[\u2713\u2714\u2611\u2705]")
_CROSS_SYMBOLS = re.compile(r"[\u2717\u2718\u2612\u274C\u2716\u00D7]")

def sanitize_checkbox_text(value: str) -> tuple[str, bool, bool]:
    """Strip checkbox symbols; return (clean_text, had_tick, had_cross)."""
    had_tick = bool(_TICK_SYMBOLS.search(value))
    had_cross = bool(_CROSS_SYMBOLS.search(value))
    clean = _CHECKBOX_SYMBOLS.sub("", value).strip()
    return clean, had_tick, had_cross


@dataclass
class DatalabJob:
    """Represents a submitted Datalab extraction job."""
    request_id: str
    check_url: str
    status: str = "submitted"

# ── Multi-option checkbox field configuration ────────────────────────────
#
# Each entry maps a resolved field name to its per-option mark keys and labels.
# The mark keys correspond to EXTRACT_SCHEMA properties that ask Datalab to
# describe the mark shape inside each checkbox.

MULTI_OPTION_FIELDS: dict[str, dict] = {
    "house_ownership": {
        "options": {"own": "Own", "rented": "Rented"},
        "mark_keys": {
            "own": "house_ownership_own_mark",
            "rented": "house_ownership_rented_mark",
        },
        "page": 2, "section": 3,
    },
    "type_of_bedroom": {
        "options": {"separate": "Separate Bedroom", "no_separate": "No Separate Bedroom"},
        "mark_keys": {
            "separate": "type_of_bedroom_separate_mark",
            "no_separate": "type_of_bedroom_no_separate_mark",
        },
        "page": 3, "section": 3,
    },
    "bathroom": {
        "options": {"separate": "Separate", "common": "Common for Apartment"},
        "mark_keys": {
            "separate": "bathroom_separate_mark",
            "common": "bathroom_common_mark",
        },
        "page": 3, "section": 3,
    },
    "kitchen_type": {
        "options": {"separate": "Separate Kitchen", "hall": "Hall with Kitchen"},
        "mark_keys": {
            "separate": "kitchen_type_separate_mark",
            "hall": "kitchen_type_hall_mark",
        },
        "page": 3, "section": 3,
    },
    "family_status": {
        "options": {
            "single_parent": "Single Parent",
            "parentless": "Parentless",
            "both_parents": "Having both parents",
        },
        "mark_keys": {
            "single_parent": "family_status_single_parent_mark",
            "parentless": "family_status_parentless_mark",
            "both_parents": "family_status_both_parents_mark",
        },
        "page": 1, "section": 2,
    },
    "income_type": {
        "options": {"monthly": "Monthly", "daily": "Daily", "weekly": "Weekly", "adhoc": "Ad-Hoc"},
        "mark_keys": {
            "monthly": "income_type_monthly_mark",
            "daily": "income_type_daily_mark",
            "weekly": "income_type_weekly_mark",
            "adhoc": "income_type_adhoc_mark",
        },
        "page": 4, "section": 4,
    },
    "recommend_student": {
        "options": {"yes": "Yes", "no": "No", "not_sure": "Not Sure"},
        "mark_keys": {
            "yes": "recommend_student_yes_mark",
            "no": "recommend_student_no_mark",
            "not_sure": "recommend_student_not_sure_mark",
        },
        "page": 6, "section": 8,
    },
    "training_program_availability": {
        "options": {"yes": "Yes", "no": "No", "maybe": "Maybe"},
        "mark_keys": {
            "yes": "training_program_yes_mark",
            "no": "training_program_no_mark",
            "maybe": "training_program_maybe_mark",
        },
        "page": 5, "section": 6,
    },
    "gender": {
        "options": {"male": "Male", "female": "Female", "others": "Others"},
        "mark_keys": {
            "male": "gender_male_mark",
            "female": "gender_female_mark",
            "others": "gender_others_mark",
        },
        "page": 1, "section": 1,
    },
    "photograph_kept_at_home": {
        "options": {"yes": "Yes", "no": "No"},
        "mark_keys": {
            "yes": "photograph_yes_mark",
            "no": "photograph_no_mark",
        },
        "page": 2, "section": 2,
    },
    "owns_other_assets": {
        "options": {"yes": "Yes", "no": "No"},
        "mark_keys": {
            "yes": "owns_other_assets_yes_mark",
            "no": "owns_other_assets_no_mark",
        },
        "page": 4, "section": 4,
    },
    "has_other_income": {
        "options": {"yes": "Yes", "no": "No"},
        "mark_keys": {
            "yes": "has_other_income_yes_mark",
            "no": "has_other_income_no_mark",
        },
        "page": 4, "section": 4,
    },
    "has_health_issues": {
        "options": {"yes": "Yes", "no": "No"},
        "mark_keys": {
            "yes": "has_health_issues_yes_mark",
            "no": "has_health_issues_no_mark",
        },
        "page": 5, "section": 5,
    },
    "has_loans": {
        "options": {"yes": "Yes", "no": "No"},
        "mark_keys": {
            "yes": "has_loans_yes_mark",
            "no": "has_loans_no_mark",
        },
        "page": 4, "section": 4,
    },
    "ready_for_skill_classes": {
        "options": {"yes": "Yes", "no": "No"},
        "mark_keys": {
            "yes": "ready_for_skill_classes_yes_mark",
            "no": "ready_for_skill_classes_no_mark",
        },
        "page": 6, "section": 6,
    },
}

# Sets for mark classification
POSITIVE_MARKS = {"tick", "slash", "check", "checkmark", "forward-slash", "forward slash", "checked", "/", "✓", "✔"}
NEGATIVE_MARKS = {"cross", "x", "✗", "✘", "reject", "rejected", "×", "scribble", "dot", "correction"}
EMPTY_MARKS = {"empty", "blank", "none", "nothing", "unmarked", "no mark", ""}

# Datalab may return booleans for yes/no fields even when schema says "type": "string".
# Map true/false to "Yes"/"No".  Multi-option fields are resolved via mark descriptions
# now, but this fallback remains for defensive coverage when Datalab ignores the mark
# description schema and returns a boolean directly.
BOOLEAN_FALLBACK_MAP: dict[str, tuple[str, str]] = {
    "photograph_kept_at_home": ("Yes", "No"),
    "owns_other_assets": ("Yes", "No"),
    "has_other_income": ("Yes", "No"),
    "has_health_issues": ("Yes", "No"),
    "has_loans": ("Yes", "No"),
    "ready_for_skill_classes": ("Yes", "No"),
}

# ── Mark-description prompt template ────────────────────────────────────
_MARK_DESC = (
    "Analyze the ink inside this specific checkbox. "
    "Do NOT tell me if it is selected. Just tell me the shape of the ink. "
    "If the ink forms two intersecting diagonal lines (X), you must output exactly 'cross'. "
    "If the ink forms a checkmark (✓), you must output exactly 'tick'. "
    "If it is completely blank, output exactly 'empty'. "
    "If it is a circle, output 'circle'. "
    "Output ONLY the single word describing the shape."
)

_DIGIT_HINT = " Digit '4' is often misread as '3' or '6' in Indian handwriting — if a number seems off, '3' or '6' may actually be '4'."

EXTRACT_SCHEMA: dict = {
    "type": "object",
    "properties": {
    # ── Header fields ──
    "volunteer_name": {"type": "string", "description": "Volunteer Name (header row, far left, labeled 'Volunteer Name:'). A person's name — read each letter carefully. Common handwriting misreads: 'n' vs 'u', 'a' vs 'o', 'l' vs 't', 'r' vs 'v', 'r' vs 'ei', 'e' vs 'a', 'h' vs 'lh', 'i' vs 'e'. Double-check every character."},
    "co_volunteer_name": {"type": "string", "description": "Co-Volunteer Name (header row, center, labeled 'Co-Volunteer Name:', between Volunteer Name and Date of Visit). A person's name. Common handwriting misreads: 'n' vs 'u', 'a' vs 'o', 'l' vs 't', 'r' vs 'v', 'r' vs 'ei', 'e' vs 'a', 'h' vs 'lh', 'i' vs 'e'. If a word has consecutive ambiguous letters, consider the most common Indian name. Double-check every character."},
    "date_of_visit": {"type": "string", "description": "Date of Visit (header row, far right, labeled 'Date:' or 'Date of Visit:'). A date like DD/MM/YYYY or written as text."},

    # ── Section 1 ──
    "application_id": {"type": "string", "description": "1.1 Application ID (Section 1 — Student Profile, FIRST field below the header row, labeled '1.1 Application ID' or '1.1. Application ID'). An alphanumeric CODE (e.g. 'TE2024001'), NOT a person's name. Check for digits that look like letters — e.g. '0' vs 'O', '1' vs 'l', '5' vs 'S'. CRITICAL: Digit '4' is often misread as '3' in handwriting — if you see '3' in a position where '4' is expected (e.g. last digit), consider it might be '4'. Likewise '7' vs '1', '9' vs '4', '8' vs '6'."},
    "student_full_name": {"type": "string", "description": "1.2 Student Full Name (Section 1 — Student Profile, below Application ID, labeled '1.2 Student Full Name' or '1.2. Student Full Name'). The student's full name. Common handwriting misreads: 'n' vs 'u', 'a' vs 'o', 'l' vs 't', 'r' vs 'v'. Read each character individually."},

    # 1.3 Gender — per-option mark descriptions
    "gender_male_mark": {"type": "string", "description": f"1.3 Gender — 'Male' checkbox. {_MARK_DESC}"},
    "gender_female_mark": {"type": "string", "description": f"1.3 Gender — 'Female' checkbox. {_MARK_DESC}"},
    "gender_others_mark": {"type": "string", "description": f"1.3 Gender — 'Others' checkbox. {_MARK_DESC}"},
    # Keep original as fallback — Datalab might return the label directly
    "gender": {"type": "string", "description": "1.3 Gender: Male | Female | Others. Return the SELECTED option text. If unsure, return empty string."},

    # ── Section 2 ──
    # 2.1 Family Status — per-option mark descriptions
    "family_status_single_parent_mark": {"type": "string", "description": f"2.1 Family Status — 'Single Parent' checkbox. {_MARK_DESC}"},
    "family_status_parentless_mark": {"type": "string", "description": f"2.1 Family Status — 'Parentless' checkbox. {_MARK_DESC}"},
    "family_status_both_parents_mark": {"type": "string", "description": f"2.1 Family Status — 'Having both parents' checkbox. {_MARK_DESC}"},
    "family_status": {"type": "string", "description": "2.1 Family Status: Three checkboxes — 'Single Parent', 'Parentless', 'Having both parents'. ONLY a tick (✓), forward-slash (/) or a circle/square border around the text counts as SELECTED. A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — ignore all marks that are not a clear ✓ or /. If none has ✓ or /, return empty string ''. If multiple have ✓ or /, return the one with ✓. Return the EXACT option text: 'Single Parent', 'Parentless', or 'Having both parents'. If any additional notes are written below these checkbox options, capture them in the 'Relationship Details — Reason for Death / Separation' field (2.2)."},
  
    "relationship_death_year": {"type": "string", "description": f"2.2 Relationship Details — Year of Death / Separation.{_DIGIT_HINT}"},
    "relationship_death_reason": {"type": "string", "description": "2.2 Relationship Details — Reason for Death / Separation. FIRST: look at the 'Reason for Death / Separation' section and capture the boxed/underlined text. SECOND (CRITICAL): look at the blank space BELOW the 2.1 Family Status checkbox options — if there is any handwritten text in that area (e.g. 'Mother passed away in 2020, father is daily wage laborer'), capture it here verbatim. Combine both parts with ' — ' separator if both exist."},

    # 2.3 Photograph — per-option mark descriptions
    "photograph_yes_mark": {"type": "string", "description": f"2.3 Is Father/Mother photograph kept at home? — 'Yes' checkbox. {_MARK_DESC}"},
    "photograph_no_mark": {"type": "string", "description": f"2.3 Is Father/Mother photograph kept at home? — 'No' checkbox. {_MARK_DESC}"},
    "photograph_kept_at_home": {"type": "string", "description": "2.3 Is Father/Mother photograph kept at home? Return 'Yes' or 'No'. If unsure, return empty string."},

    # 2.4 Government IDs — per-option mark descriptions (multi-select, not mutually exclusive)
    "govt_id_aadhaar": {"type": "string", "description": f"2.4 Government ID Verified — 'Aadhaar Card' checkbox. {_MARK_DESC}"},
    "govt_id_ration": {"type": "string", "description": f"2.4 Government ID Verified — 'Ration Card' checkbox. {_MARK_DESC}"},
    "govt_id_driving_licence": {"type": "string", "description": f"2.4 Government ID Verified — 'Driving Licence' checkbox. {_MARK_DESC}"},
    "govt_id_voter": {"type": "string", "description": f"2.4 Government ID Verified — 'Voter ID' checkbox. {_MARK_DESC}"},
    "govt_id_other": {"type": "string", "description": f"2.4 Government ID Verified — 'Other' checkbox. {_MARK_DESC}"},
    "govt_id_other_text": {"type": "string", "description": "2.4 Government ID Verified — Other (text written on the blank line next to Other checkbox, e.g. 'Pan Card', 'Senior Citizen ID')"},

    # 2.5 Family Members table
    "family_members": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Family member name"},
                "age": {"type": "string", "description": f"Age.{_DIGIT_HINT}"},
                "education": {"type": "string", "description": "Education"},
                "occupation": {"type": "string", "description": "Occupation"},
                "annual_income": {"type": "string", "description": f"Annual Income.{_DIGIT_HINT}"},
            },
        },
        "description": "2.5 Family Members table",
    },

    # ── Section 3 ──
    # 3.1 House Ownership — per-option mark descriptions
    "house_ownership_own_mark": {"type": "string", "description": f"3.1 House Ownership — 'Own' checkbox. {_MARK_DESC}"},
    "house_ownership_rented_mark": {"type": "string", "description": f"3.1 House Ownership — 'Rented' checkbox. {_MARK_DESC}"},
    "house_ownership": {"type": "string", "description": "3.1 House Ownership. Return 'Own' or 'Rented'. If unsure, return empty string."},

    "rent_amount": {"type": "string", "description": f"3.1.1 Rent amount or ownership notes (capture any text written, even if Own is selected).{_DIGIT_HINT}"},

    # 3.2 Type of Home — per-option mark descriptions (multi-select possible)
    "home_type_individual": {"type": "string", "description": f"3.2 Type of Home — 'Individual' checkbox. {_MARK_DESC}"},
    "home_type_private_apartment": {"type": "string", "description": f"3.2 Type of Home — 'Private Apartment' checkbox. {_MARK_DESC}"},
    "home_type_housing_board": {"type": "string", "description": f"3.2 Type of Home — 'Housing Board' checkbox. {_MARK_DESC}"},
    "home_type_line_house": {"type": "string", "description": f"3.2 Type of Home — 'Line House' checkbox. {_MARK_DESC}"},
    "home_type_others": {"type": "string", "description": "3.2 Type of Home — Others. Return the full text written on the blank line next to 'Others', e.g. 'Others: living with grand parents'. Prefix with 'Others: ' if not already present."},

    # 3.3 Type of Ceiling — per-option mark descriptions (multi-select possible)
    "ceiling_roof": {"type": "string", "description": f"3.3 Type of Ceiling — 'Roof (Kurai)' checkbox. {_MARK_DESC}"},
    "ceiling_tiled": {"type": "string", "description": f"3.3 Type of Ceiling — 'Tiled' checkbox. {_MARK_DESC}"},
    "ceiling_asbestos": {"type": "string", "description": f"3.3 Type of Ceiling — 'Asbestos / Sheet' checkbox. {_MARK_DESC}"},
    "ceiling_concrete": {"type": "string", "description": f"3.3 Type of Ceiling — 'Concrete' checkbox. {_MARK_DESC}"},

    "number_of_bedrooms": {"type": "string", "description": f"3.4 Number of Bedrooms.{_DIGIT_HINT}"},

    # 3.4.1 Type of Bedroom — per-option mark descriptions
    "type_of_bedroom_separate_mark": {"type": "string", "description": f"3.4.1 Type of Bedroom — 'Separate Bedroom' checkbox. {_MARK_DESC}"},
    "type_of_bedroom_no_separate_mark": {"type": "string", "description": f"3.4.1 Type of Bedroom — 'No Separate Bedroom' checkbox. {_MARK_DESC}"},
    "type_of_bedroom": {"type": "string", "description": "3.4.1 Type of Bedroom. Return 'Separate Bedroom' or 'No Separate Bedroom'. If unsure, return empty string."},

    # 3.5 Bathroom — per-option mark descriptions
    "bathroom_separate_mark": {"type": "string", "description": f"3.5 Bathroom — 'Separate' checkbox. {_MARK_DESC}"},
    "bathroom_common_mark": {"type": "string", "description": f"3.5 Bathroom — 'Common for Apartment' checkbox. {_MARK_DESC}"},
    "bathroom": {"type": "string", "description": "3.5 Bathroom. Return 'Separate' or 'Common for Apartment'. If unsure, return empty string."},

    # 3.6 Kitchen Type — per-option mark descriptions
    "kitchen_type_separate_mark": {"type": "string", "description": f"3.6 Kitchen Type — 'Separate Kitchen' checkbox. {_MARK_DESC}"},
    "kitchen_type_hall_mark": {"type": "string", "description": f"3.6 Kitchen Type — 'Hall with Kitchen' checkbox. {_MARK_DESC}"},
    "kitchen_type": {"type": "string", "description": "3.6 Kitchen Type. Return 'Separate Kitchen' or 'Hall with Kitchen'. If unsure, return empty string."},

    # 4.1 Assets — array extraction to provide context
    "asset_washing_machine": {"type": "boolean", "description": "4.1 Assets at Home — Washing Machine. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false. Omit if blank."},
    "asset_fridge": {"type": "boolean", "description": "4.1 Assets at Home — Fridge. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false. Omit if blank."},
    "asset_ac": {"type": "boolean", "description": "4.1 Assets at Home — AC. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false. Omit if blank."},
    "asset_led_tv": {"type": "boolean", "description": "4.1 Assets at Home — LED TV. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false. Omit if blank."},
    "asset_two_wheeler": {"type": "boolean", "description": "4.1 Assets at Home — Two-Wheeler. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false. Omit if blank."},
    "asset_car": {"type": "boolean", "description": "4.1 Assets at Home — Car. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false. Omit if blank."},
    "asset_smartphone": {"type": "boolean", "description": "4.1 Assets at Home — Smartphone. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false. Omit if blank."},
    "asset_separate_wifi": {"type": "boolean", "description": "4.1 Assets at Home — Separate Wi-Fi. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false. Omit if blank."},
    "asset_others": {"type": "string", "description": "4.1 Assets at Home — Others. CRITICAL: Always return any text written on the blank line after 'Others' even if the checkbox is not ticked. Prefix it with 'Others: ' — e.g. 'Others: normal tv'. If the checkbox has a mark with no text, return '✓' for tick, 'x' or '✗' for cross."},
  
    "last_electricity_bill": {"type": "string", "description": f"4.2 Last Electricity Bill Amount — extract the monthly electricity bill amount written on the form (e.g. '700', 'Rs.700/-', '700/-'). This is a handwritten amount in the electricity bill field — ignore any other numbers printed on the page.{_DIGIT_HINT}"},

    # 4.3 Other assets — per-option mark descriptions
    "owns_other_assets_yes_mark": {"type": "string", "description": f"4.3 Do you own any other assets/properties? — 'Yes' checkbox. {_MARK_DESC}"},
    "owns_other_assets_no_mark": {"type": "string", "description": f"4.3 Do you own any other assets/properties? — 'No' checkbox. {_MARK_DESC}"},
    "owns_other_assets": {"type": "string", "description": "4.3 Do you own any other assets/properties? Return 'Yes' or 'No'. If unsure, return empty string."},

    "other_assets_table": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "property_description": {"type": "string", "description": "Property description. ALSO capture any handwritten notes from TWO locations: (1) the blank space below the 4.3 checkbox on page 3, and (2) the blank space below the 4.3.1 table rows before the 4.4 question on page 4. Include each note as a separate row in the 'property_description' field with owner_name and approximate_value left blank."},
                "owner_name": {"type": "string", "description": "Owner name"},
                "approximate_value": {"type": "string", "description": f"Approximate value.{_DIGIT_HINT}"},
            },
        },
        "description": "4.3.1 Other assets/properties table. The table typically has 1-2 structured rows. ALSO look for handwritten notes in TWO locations: (a) the blank space below the '4.3 Do you own any other assets/properties...' checkbox on page 3, and (b) the blank space below the table rows before the 4.4 question on page 4. Include each note as an extra row with the text in 'property_description' and leave owner_name and approximate_value blank.",
    },

    # 4.4 Other income — per-option mark descriptions
    "has_other_income_yes_mark": {"type": "string", "description": f"4.4 Apart from your job, is there any other source of income? — 'Yes' checkbox. {_MARK_DESC}"},
    "has_other_income_no_mark": {"type": "string", "description": f"4.4 Apart from your job, is there any other source of income? — 'No' checkbox. {_MARK_DESC}"},
    "has_other_income": {"type": "string", "description": "4.4 Apart from your job, is there any other source of income? Return 'Yes' or 'No'. If unsure, return empty string."},

    "other_income_table": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source of income"},
                "amount": {"type": "string", "description": f"Amount.{_DIGIT_HINT}"},
            },
        },
        "description": "CRITICAL — ALWAYS extract this table regardless of the 4.4 answer. Even if 4.4 says 'No', check if there are handwritten entries in the 4.4.1 income sources table. If there is ANY text in the source or amount columns, include it as a row. The table typically has 1-3 rows with columns for source and amount. Do NOT skip this just because 4.4 seems negative.",
    },

    # 4.5 Income Type — per-option mark descriptions
    "income_type_monthly_mark": {"type": "string", "description": f"4.5 Income Type — 'Monthly' checkbox. {_MARK_DESC}"},
    "income_type_daily_mark": {"type": "string", "description": f"4.5 Income Type — 'Daily' checkbox. {_MARK_DESC}"},
    "income_type_weekly_mark": {"type": "string", "description": f"4.5 Income Type — 'Weekly' checkbox. {_MARK_DESC}"},
    "income_type_adhoc_mark": {"type": "string", "description": f"4.5 Income Type — 'Ad-Hoc' checkbox. {_MARK_DESC}"},
    "income_type": {"type": "string", "description": "4.5 Income Type. Return 'Monthly', 'Daily', 'Weekly', or 'Ad-Hoc'. If unsure, return empty string."},

    # 4.6 Loans — per-option mark descriptions
    "has_loans_yes_mark": {"type": "string", "description": f"4.6 Do you have any loans? — 'Yes' checkbox. {_MARK_DESC}"},
    "has_loans_no_mark": {"type": "string", "description": f"4.6 Do you have any loans? — 'No' checkbox. {_MARK_DESC}"},
    "has_loans": {"type": "string", "description": "4.6 Do you have any loans? Return 'Yes' or 'No'. If unsure, return empty string."},

    "loans_table": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "serial_number": {"type": "string", "description": f"S.No.{_DIGIT_HINT}"},
                "loan_purpose": {"type": "string", "description": "Loan purpose"},
                "loan_amount_taken": {"type": "string", "description": f"Loan amount taken.{_DIGIT_HINT}"},
                "pending_loan_amount": {"type": "string", "description": f"Pending loan amount.{_DIGIT_HINT}"},
            },
        },
        "description": "4.6.1 Loans table",
    },

    # ── Section 4 continued (page 5) ──
    "college_fee": {"type": "string", "description": f"4.7 If you choose college, how much is the college fee?{_DIGIT_HINT}"},
    "manage_higher_fee": {"type": "string", "description": f"4.8 If the college fee is higher, how will you manage it?{_DIGIT_HINT}"},
    "manage_without_scholarship": {"type": "string", "description": f"4.9 If you do not receive this scholarship, how will you pay the fees?{_DIGIT_HINT}"},

    # ── Section 5 ──
    # 5.1 Health issues — per-option mark descriptions
    "has_health_issues_yes_mark": {"type": "string", "description": f"5.1 Does the student have any health issues? — 'Yes' checkbox. {_MARK_DESC}"},
    "has_health_issues_no_mark": {"type": "string", "description": f"5.1 Does the student have any health issues? — 'No' checkbox. {_MARK_DESC}"},
    "has_health_issues": {"type": "string", "description": "5.1 Does the student have any health issues? Return 'Yes' or 'No'. If unsure, return empty string."},

    "health_issues_description": {"type": "string", "description": "5.2 If yes, list the health issues"},

    # ── Section 6 ──
    "study_commitment": {"type": "string", "description": "6.1 Will you study college for three years without any obstacle?"},

    # 6.2 Training program — per-option mark descriptions
    "training_program_yes_mark": {"type": "string", "description": f"6.2 If we have a training program within 15 km from your home, can you come? — 'Yes' checkbox. {_MARK_DESC}"},
    "training_program_no_mark": {"type": "string", "description": f"6.2 If we have a training program within 15 km from your home, can you come? — 'No' checkbox. {_MARK_DESC}"},
    "training_program_maybe_mark": {"type": "string", "description": f"6.2 If we have a training program within 15 km from your home, can you come? — 'Maybe' checkbox. {_MARK_DESC}"},
    "training_program_availability": {"type": "string", "description": "6.2 If we have a training program within 15 km from your home, can you come? Return 'Yes', 'No', or 'Maybe'. If unsure, return empty string."},

    # 6.3 Skill classes — per-option mark descriptions
    "ready_for_skill_classes_yes_mark": {"type": "string", "description": f"6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays? — 'Yes' checkbox. {_MARK_DESC}"},
    "ready_for_skill_classes_no_mark": {"type": "string", "description": f"6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays? — 'No' checkbox. {_MARK_DESC}"},
    "ready_for_skill_classes": {"type": "string", "description": "6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)? Return 'Yes' or 'No'. If unsure, return empty string."},

    # ── Section 7 ──
    "other_scholarships": {"type": "string", "description": "7.1 Other scholarships applied/received for UG degree?"},

    # ── Section 8 ──
    "volunteer_opinion": {"type": "string", "description": "8.1 Volunteer opinion about the student and family"},

    # 8.2 Recommend — per-option mark descriptions
    "recommend_student_yes_mark": {"type": "string", "description": f"8.2 Will you recommend this student for this scholarship? — 'Yes' checkbox. {_MARK_DESC}"},
    "recommend_student_no_mark": {"type": "string", "description": f"8.2 Will you recommend this student for this scholarship? — 'No' checkbox. {_MARK_DESC}"},
    "recommend_student_not_sure_mark": {"type": "string", "description": f"8.2 Will you recommend this student for this scholarship? — 'Not Sure' checkbox. {_MARK_DESC}"},
    "recommend_student": {"type": "string", "description": "8.2 Will you recommend this student for this scholarship? Return 'Yes', 'No', or 'Not Sure'. If unsure, return empty string."},

    "volunteer_comments": {"type": "string", "description": "8.3 Other comments"},

    # ── Free-text blank-space fields (Problem 2) ──
    "blank_text_below_2_1": {"type": "string", "description": "CRITICAL — OFTEN MISSED: There is frequently handwritten text in the blank space BETWEEN the 2.1 Family Status checkbox options and the 2.2 Relationship Details section header on page 1. Examples: '(step-parent-father)', 'Mother passed away in 2020', 'father is daily wage laborer'. Look VERY carefully at this region — the text is small and easily overlooked. If ANY handwriting exists (including parentheses, annotations, notes), transcribe it verbatim. Return empty string ONLY if the region is genuinely blank."},
    "blank_text_below_4_3": {"type": "string", "description": "FREE TEXT AREA: Look at the blank space BELOW the 4.3 checkbox on page 3 and ABOVE the 4.3.1 table header. If there is ANY handwritten text, transcribe it verbatim. Return empty string if blank."},
    "blank_text_below_4_3_1_table": {"type": "string", "description": "FREE TEXT AREA: Look at the blank space BELOW the last row of the 4.3.1 assets table on page 4 and ABOVE the 4.4 question. If there is ANY handwritten text, transcribe it verbatim. Return empty string if blank."},
    },
}

# Collect all mark-description keys — these are intermediate fields that should
# NOT be emitted as output fields or mapped to DB columns.
_MARK_DESCRIPTION_KEYS: set[str] = set()
for _cfg in MULTI_OPTION_FIELDS.values():
    _MARK_DESCRIPTION_KEYS.update(_cfg["mark_keys"].values())

# Also exclude the free-text blank-space fields from direct output
_FREE_TEXT_KEYS: set[str] = {"blank_text_below_2_1", "blank_text_below_4_3", "blank_text_below_4_3_1_table"}

# Single-checkbox boolean-like fields that use mark descriptions.
# These are independent yes/no checkboxes (not mutually exclusive multi-option fields).
# Each gets resolved from mark description → "✓" or None in _resolve_single_checkbox_marks().
_SINGLE_CHECKBOX_KEYS: set[str] = {
    # 2.4 Government IDs
    "govt_id_aadhaar", "govt_id_ration", "govt_id_driving_licence", "govt_id_voter", "govt_id_other",
    # 3.2 Type of Home
    "home_type_individual", "home_type_private_apartment", "home_type_housing_board", "home_type_line_house",
    # 3.3 Type of Ceiling
    "ceiling_roof", "ceiling_tiled", "ceiling_asbestos", "ceiling_concrete",
    # 4.1 Assets
    "asset_washing_machine", "asset_fridge", "asset_ac", "asset_led_tv",
    "asset_two_wheeler", "asset_car", "asset_smartphone", "asset_separate_wifi",
}

SCHEMA_KEY_MAP = {
    "volunteer_name": {"label": "Volunteer Name", "page": 1, "section": None},
    "co_volunteer_name": {"label": "Co-Volunteer Name", "page": 1, "section": None},
    "date_of_visit": {"label": "Date of Visit", "page": 1, "section": None},
    "application_id": {"label": "1.1 Application ID", "page": 1, "section": 1},
    "student_full_name": {"label": "1.2 Student Full Name", "page": 1, "section": 1},
    "gender": {"label": "1.3 Gender", "page": 1, "section": 1},
    "family_status": {"label": "2.1 Family Status", "page": 1, "section": 2},
    "relationship_death_year": {"label": "2.2 Relationship Details — Year of Death / Separation", "page": 1, "section": 2},
    "relationship_death_reason": {"label": "2.2 Relationship Details — Reason for Death / Separation", "page": 1, "section": 2},
    "photograph_kept_at_home": {"label": "2.3 Is Father/Mother photograph kept at home?", "page": 2, "section": 2},
    "govt_id_aadhaar": {"label": "2.4 Government ID Verified — Aadhaar Card", "page": 2, "section": 2},
    "govt_id_ration": {"label": "2.4 Government ID Verified — Ration Card", "page": 2, "section": 2},
    "govt_id_driving_licence": {"label": "2.4 Government ID Verified — Driving Licence", "page": 2, "section": 2},
    "govt_id_voter": {"label": "2.4 Government ID Verified — Voter ID", "page": 2, "section": 2},
    "govt_id_other": {"label": "2.4 Government ID Verified — Other", "page": 2, "section": 2},
    "govt_id_other_text": {"label": "2.4 Government ID Verified — Other (specify)", "page": 2, "section": 2},
    "house_ownership": {"label": "3.1 House Ownership", "page": 2, "section": 3},
    "rent_amount": {"label": "3.1.1 If rented, what is the rent amount?", "page": 2, "section": 3},
    "home_type_individual": {"label": "3.2 Type of Home — Individual", "page": 2, "section": 3},
    "home_type_private_apartment": {"label": "3.2 Type of Home — Private Apartment", "page": 2, "section": 3},
    "home_type_housing_board": {"label": "3.2 Type of Home — Housing Board", "page": 2, "section": 3},
    "home_type_line_house": {"label": "3.2 Type of Home — Line House", "page": 2, "section": 3},
    "home_type_others": {"label": "3.2 Type of Home — Others", "page": 2, "section": 3},
    "ceiling_roof": {"label": "3.3 Type of Ceiling — Roof (Kurai)", "page": 3, "section": 3},
    "ceiling_tiled": {"label": "3.3 Type of Ceiling — Tiled", "page": 3, "section": 3},
    "ceiling_asbestos": {"label": "3.3 Type of Ceiling — Asbestos / Sheet", "page": 3, "section": 3},
    "ceiling_concrete": {"label": "3.3 Type of Ceiling — Concrete", "page": 3, "section": 3},
    "number_of_bedrooms": {"label": "3.4 Number of Bedrooms", "page": 3, "section": 3},
    "type_of_bedroom": {"label": "3.4.1 Type of Bedroom", "page": 3, "section": 3},
    "bathroom": {"label": "3.5 Bathroom", "page": 3, "section": 3},
    "kitchen_type": {"label": "3.6 Kitchen Type", "page": 3, "section": 3},
    "asset_washing_machine": {"label": "4.1 Assets at Home — Washing Machine", "page": 3, "section": 4},
    "asset_fridge": {"label": "4.1 Assets at Home — Fridge", "page": 3, "section": 4},
    "asset_ac": {"label": "4.1 Assets at Home — AC", "page": 3, "section": 4},
    "asset_led_tv": {"label": "4.1 Assets at Home — LED TV", "page": 3, "section": 4},
    "asset_two_wheeler": {"label": "4.1 Assets at Home — Two-Wheeler", "page": 3, "section": 4},
    "asset_car": {"label": "4.1 Assets at Home — Car", "page": 3, "section": 4},
    "asset_smartphone": {"label": "4.1 Assets at Home — Smartphone", "page": 3, "section": 4},
    "asset_separate_wifi": {"label": "4.1 Assets at Home — Separate Wi-Fi", "page": 3, "section": 4},
    "asset_others": {"label": "4.1 Assets at Home — Others", "page": 3, "section": 4},
    "last_electricity_bill": {"label": "4.2 Amount of Last Electricity Bill", "page": 4, "section": 4},
    "owns_other_assets": {"label": "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student?", "page": 4, "section": 4},
    "has_other_income": {"label": "4.4 Apart from your job, is there any other source of income?", "page": 4, "section": 4},
    "income_type": {"label": "4.5 Income Type", "page": 4, "section": 4},
    "has_loans": {"label": "4.6 Do you have any loans?", "page": 4, "section": 4},
    "college_fee": {"label": "4.7 If you choose any college, how much is the college fee?", "page": 5, "section": 4},
    "manage_higher_fee": {"label": "4.8 If the college fee is higher, how will you manage it?", "page": 5, "section": 4},
    "manage_without_scholarship": {"label": "4.9 If you do not receive this scholarship, how will you pay the fees?", "page": 5, "section": 4},
    "has_health_issues": {"label": "5.1 Does the student have any health issues?", "page": 5, "section": 5},
    "health_issues_description": {"label": "5.2 If yes, list the health issues", "page": 5, "section": 5},
    "study_commitment": {"label": "6.1 Will you study college for three years without any obstacle?", "page": 5, "section": 6},
    "training_program_availability": {"label": "6.2 If we have a training program within 15 km from your home, can you come?", "page": 5, "section": 6},
    "ready_for_skill_classes": {"label": "6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)?", "page": 6, "section": 6},
    "other_scholarships": {"label": "7.1 Has the student received or applied for any other scholarships for their UG degree?", "page": 6, "section": 7},
    "volunteer_opinion": {"label": "8.1 What is your opinion about the student, their family members, and their living condition?", "page": 6, "section": 8},
    "recommend_student": {"label": "8.2 Will you recommend this student for this scholarship?", "page": 6, "section": 8},
    "volunteer_comments": {"label": "8.3 Any other comments you want to share?", "page": 6, "section": 8},
}

EXPECTED_FIELD_LABELS: set[str] = {meta["label"] for meta in SCHEMA_KEY_MAP.values()}

TABLE_MAP = {
    "family_members": {
        "label_prefix": "2.5 Family Members",
        "columns": ["Name", "Age", "Education", "Occupation", "Annual Income"],
        "col_key": ["name", "age", "education", "occupation", "annual_income"],
        "section": 2,
        "page": 2,
    },
    "other_assets_table": {
        "label_prefix": "4.3.1",
        "columns": ["Property Description", "Owner Name", "Approximate Value"],
        "col_key": ["property_description", "owner_name", "approximate_value"],
        "section": 4,
        "page": 4,
    },
    "other_income_table": {
        "label_prefix": "4.4.1",
        "columns": ["Source of Income", "Amount"],
        "col_key": ["source", "amount"],
        "section": 4,
        "page": 4,
    },
    "loans_table": {
        "label_prefix": "4.6.1",
        "columns": ["Sr. No.", "Loan Purpose", "Loan Amount Taken", "Pending Loan Amount"],
        "col_key": ["serial_number", "loan_purpose", "loan_amount_taken", "pending_loan_amount"],
        "section": 4,
        "page": 4,
    },
}

# Pre-compute set of keys whose EXTRACT_SCHEMA type is "boolean".
# When Datalab returns a boolean for a string-typed field (e.g. govt_id_other_text),
# we must NOT blindly turn it into "✓".
_BOOLEAN_KEYS: set[str] = {
    k for k, v in EXTRACT_SCHEMA["properties"].items()
    if isinstance(v, dict) and v.get("type") == "boolean"
}


# ── Checkbox Mark Resolution (Problem 1) ─────────────────────────────────

def _classify_mark(mark_text: str) -> str:
    """Classify a mark description string into 'positive', 'negative', or 'empty'.

    Returns one of: 'positive', 'negative', 'empty', 'unknown'.
    """
    norm = mark_text.strip().lower() if mark_text else ""
    if not norm or norm in EMPTY_MARKS:
        return "empty"
    if norm in POSITIVE_MARKS:
        return "positive"
    if norm in NEGATIVE_MARKS:
        return "negative"
    # Fuzzy match: check if any positive/negative keyword is a substring
    for pos in POSITIVE_MARKS:
        if pos in norm:
            return "positive"
    for neg in NEGATIVE_MARKS:
        if neg in norm:
            return "negative"
    return "unknown"


def resolve_checkbox_marks(extracted: dict) -> tuple[dict, dict]:
    """Resolve multi-option checkbox fields from per-option mark descriptions.

    For each field in MULTI_OPTION_FIELDS, reads the mark-description values
    from `extracted`, classifies each mark, and applies resolution rules:
      - Exactly 1 positive mark → select that option
      - 0 positives, 1+ negatives → ambiguous (all rejected)
      - Multiple positives → ambiguous (can't decide)
      - Marks agree with fallback value → use mark-resolved value
      - Marks disagree with fallback → prefer mark-resolved value, flag discrepancy

    Returns:
        resolved: dict mapping field_name → resolved label string (or None)
        ambiguous: dict mapping field_name → reason string (for human review)
    """
    resolved: dict[str, str | None] = {}
    ambiguous: dict[str, str] = {}

    for field_name, config in MULTI_OPTION_FIELDS.items():
        mark_results: dict[str, tuple[str, str]] = {}  # opt_key → (label, classification)

        has_any_mark_key = False
        for opt_key, mark_key in config["mark_keys"].items():
            mark_val = extracted.get(mark_key)
            if mark_val is not None:
                has_any_mark_key = True
            label = config["options"][opt_key]
            classification = _classify_mark(mark_val)
            mark_results[opt_key] = (label, classification)

        if not has_any_mark_key:
            # Datalab didn't return any mark descriptions for this field —
            # fall back to the original field value (no mark resolution)
            continue

        positives = [(label, opt_key) for opt_key, (label, cls) in mark_results.items() if cls == "positive"]
        negatives = [(label, opt_key) for opt_key, (label, cls) in mark_results.items() if cls == "negative"]
        unknowns = [(label, opt_key) for opt_key, (label, cls) in mark_results.items() if cls == "unknown"]

        if len(positives) == 1:
            resolved[field_name] = positives[0][0]
        elif len(positives) == 0:
            if len(unknowns) == 1 and len(negatives) >= 1:
                resolved[field_name] = unknowns[0][0]
                ambiguous[field_name] = f"inferred_from_unknown: {unknowns[0][0]}"
            elif len(unknowns) == 0 and len(negatives) >= 1:
                ambiguous[field_name] = f"all_negative_or_empty"
                resolved[field_name] = None
            else:
                resolved[field_name] = None
        elif len(positives) > 1:
            ambiguous[field_name] = f"multiple_positive: {[l for l, _ in positives]}"
            resolved[field_name] = None
        else:
            resolved[field_name] = None

    if resolved:
        _logger.info("Mark resolution: resolved=%s ambiguous=%s", list(resolved.keys()), list(ambiguous.keys()))
    return resolved, ambiguous


def _merge_mark_and_fallback(extracted: dict, mark_resolved: dict, ambiguous: dict) -> dict:
    """Merge mark-resolved values with fallback values from Datalab's direct extraction.

    Priority:
    1. Mark-resolved value (if unambiguous)
    2. Fallback value from Datalab's direct string extraction (if marks were ambiguous)
    3. None (if neither source has a value)

    Also cross-validates: if both sources return values and they disagree, logs a
    warning and flags the discrepancy.
    """
    merged = dict(extracted)

    for field_name in MULTI_OPTION_FIELDS:
        mark_val = mark_resolved.get(field_name)
        fallback_val = extracted.get(field_name)

        # Normalize fallback — if Datalab returned a boolean, use BOOLEAN_FALLBACK_MAP
        if isinstance(fallback_val, bool):
            fb = BOOLEAN_FALLBACK_MAP.get(field_name)
            if fb:
                fallback_val = fb[0] if fallback_val else fb[1]
            else:
                fallback_val = None

        if isinstance(fallback_val, str):
            fallback_val = fallback_val.strip() or None

        if mark_val is not None:
            if fallback_val and fallback_val != mark_val:
                _logger.warning(
                    "MARK vs FALLBACK disagreement for %s: mark='%s' fallback='%s' → using mark value",
                    field_name, mark_val, fallback_val,
                )
                ambiguous.setdefault(field_name, "")
                ambiguous[field_name] += f"; mark_fallback_disagree: mark='{mark_val}' fallback='{fallback_val}'"
            merged[field_name] = mark_val
        elif field_name in ambiguous and fallback_val:
            # Marks were ambiguous but Datalab's direct extraction has a value — use it
            _logger.info(
                "Using fallback for ambiguous %s: '%s' (marks were: %s)",
                field_name, fallback_val, ambiguous[field_name],
            )
            merged[field_name] = fallback_val
            ambiguous[field_name] += f"; used_fallback='{fallback_val}'"
        # else: keep whatever extracted already has

    return merged


def _resolve_single_checkbox_marks(extracted: dict) -> None:
    """Resolve single-checkbox fields from mark descriptions.

    For each key in _SINGLE_CHECKBOX_KEYS, classifies the mark description
    returned by Datalab:
      - 'positive' → set value to "✓"
      - 'negative' / 'empty' → set value to None (skipped in field loop)
      - 'unknown' → leave as-is (will be treated as a regular string)
    """
    checked = []
    cleared = []
    for key in _SINGLE_CHECKBOX_KEYS:
        mark_val = extracted.get(key)
        if mark_val is None:
            continue
        classification = _classify_mark(str(mark_val))
        if classification == "positive":
            extracted[key] = "\u2713"
            checked.append(key)
        elif classification in ("negative", "empty"):
            extracted[key] = None
            cleared.append(key)
    if checked or cleared:
        _logger.info("Single-checkbox resolution: %d checked, %d cleared", len(checked), len(cleared))


# ── Field Pattern Validation (Problem 3) ─────────────────────────────────

_APP_ID_PATTERN = re.compile(r'^[A-Z]{2,4}[-\s]?\d{4}[-\s]?\d{1,5}$', re.IGNORECASE)


def _validate_field_patterns(extracted: dict) -> dict:
    """Cross-check extracted values against expected patterns.

    Detects and corrects header-vs-section field confusion (Problem 3).
    """
    vol_name = extracted.get("volunteer_name", "")
    app_id = extracted.get("application_id", "")

    if vol_name and app_id:
        vol_looks_like_id = bool(_APP_ID_PATTERN.match(vol_name))
        id_looks_like_name = app_id and not any(c.isdigit() for c in app_id) and " " in app_id

        if vol_looks_like_id and not _APP_ID_PATTERN.match(app_id):
            _logger.warning(
                "SWAP volunteer_name ↔ application_id: vol='%s' looks like ID, app='%s' looks like name",
                vol_name, app_id,
            )
            extracted["volunteer_name"], extracted["application_id"] = app_id, vol_name
        elif id_looks_like_name:
            _logger.warning(
                "application_id '%s' looks like a person's name — possible field confusion",
                app_id,
            )

    return extracted


# ── Free-Text Merge (Problem 2) ──────────────────────────────────────────

_STRIKE_CHARS_RE = re.compile(r"[─━═]")
_STRIKE_LINE_RE = re.compile(r"^[\s─━═\-_~xX]{4,}$")


def _is_text_strikethrough(value: str) -> bool:
    if not value or not value.strip():
        return True
    cleaned = value.strip()
    if _STRIKE_CHARS_RE.search(cleaned):
        return True
    if _STRIKE_LINE_RE.match(cleaned):
        return True
    return False


def _merge_free_text(extracted: dict, fields: list) -> list:
    """Merge dedicated free-text fields into their parent fields."""

    # Merge blank_text_below_2_1 into relationship_death_reason and relationship_death_year
    blank_2_1 = (extracted.get("blank_text_below_2_1") or "").strip()
    if blank_2_1 and not _is_text_strikethrough(blank_2_1):
        # Merge into relationship_death_reason
        found_reason = False
        for f in fields:
            if f["label"] == "2.2 Relationship Details — Reason for Death / Separation":
                existing = f["value"].strip()
                if existing and existing != "—":
                    if blank_2_1 not in existing:
                        f["value"] = f"{existing} — {blank_2_1}"
                else:
                    f["value"] = blank_2_1
                found_reason = True
                break
        if not found_reason:
            fields.append({
                "label": "2.2 Relationship Details — Reason for Death / Separation",
                "value": blank_2_1,
                "confidence": 80,
                "page": 1,
                "section": 2,
            })

        # Also populate relationship_death_year if the existing value is empty/missing
        found_year = False
        for f in fields:
            if f["label"] == "2.2 Relationship Details — Year of Death / Separation":
                if not f["value"] or f["value"].strip() in ("", "—"):
                    f["value"] = blank_2_1
                found_year = True
                break
        if not found_year:
            fields.append({
                "label": "2.2 Relationship Details — Year of Death / Separation",
                "value": blank_2_1,
                "confidence": 80,
                "page": 1,
                "section": 2,
            })

    # Merge blank_text_below_4_3 and blank_text_below_4_3_1_table into other_assets_table rows
    for blank_key, page in [("blank_text_below_4_3", 3), ("blank_text_below_4_3_1_table", 4)]:
        blank_text = (extracted.get(blank_key) or "").strip()
        if blank_text and not _is_text_strikethrough(blank_text):
            # Find the highest row number for 4.3.1 and add a new row
            max_row = 0
            for f in fields:
                if f["label"].startswith("4.3.1") and "Row" in f["label"]:
                    import re as _re
                    m = _re.search(r"Row\s+(\d+)", f["label"])
                    if m:
                        max_row = max(max_row, int(m.group(1)))
            new_row = max_row + 1
            fields.append({
                "label": f"4.3.1 If Yes, list their properties: — Row {new_row} — Property Description",
                "value": blank_text,
                "confidence": 80,
                "page": page,
                "section": 4,
            })
            for col in ["Owner Name", "Approximate Value"]:
                fields.append({
                    "label": f"4.3.1 If Yes, list their properties: — Row {new_row} — {col}",
                    "value": "",
                    "confidence": 80,
                    "page": page,
                    "section": 4,
                })

    return fields


# ── Main Conversion ──────────────────────────────────────────────────────

def convert_extract_response(response: dict) -> dict:
    """Convert raw Datalab extraction response to structured fields.

    Pipeline:
    1. Parse extraction_schema_json from Datalab response
    2. Resolve multi-option checkbox marks (Problem 1)
    3. Resolve single-checkbox marks (4.1, 3.2, 3.3, 2.4)
    4. Merge mark-resolved values with Datalab's direct extraction
    5. Validate field patterns (Problem 3)
    6. Build output fields list
    7. Merge free-text blank-space fields (Problem 2)
    """
    raw = response.get("extraction_schema_json", response)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    if not isinstance(raw, dict):
        return {}

    extracted = {k: v for k, v in raw.items() if not k.endswith("_citations") and not k.endswith("_meta")}

    _verified_asset_names: set[str] = set()
    if "assets_at_home_list" in extracted:
        assets_list = extracted.pop("assets_at_home_list")
        _logger.info("DEBUG assets_at_home_list: %s", assets_list)
        if isinstance(assets_list, list):
            asset_map = {
                "washing machine": "asset_washing_machine",
                "fridge": "asset_fridge",
                "ac": "asset_ac",
                "led tv": "asset_led_tv",
                "two-wheeler": "asset_two_wheeler",
                "car": "asset_car",
                "smartphone": "asset_smartphone",
                "separate wi-fi": "asset_separate_wifi"
            }
            _verified_asset_names = {v for v in (asset_map.get(val.strip().lower()) for val in assets_list if isinstance(val, str)) if v}
            for val in assets_list:
                if isinstance(val, str):
                    key = asset_map.get(val.strip().lower())
                    if key:
                        extracted[key] = "\u2713"

    # ── Step 1: Resolve checkbox marks ──
    mark_resolved, ambiguous = resolve_checkbox_marks(extracted)

    # ── Step 1.5: Resolve single-checkbox marks (4.1, 3.2, 3.3, 2.4) ──
    _resolve_single_checkbox_marks(extracted)

    # ── Step 2: Merge mark results with fallback values ──
    extracted = _merge_mark_and_fallback(extracted, mark_resolved, ambiguous)

    # ── Step 3: Validate field patterns (header vs section confusion) ──
    extracted = _validate_field_patterns(extracted)

    # ── Step 4: Build output fields ──
    fields = []

    for key, meta in SCHEMA_KEY_MAP.items():
        raw_value = extracted.get(key)
        if raw_value is None:
            continue

        # Skip mark-description intermediate keys (they are NOT output fields)
        if key in _MARK_DESCRIPTION_KEYS or key in _FREE_TEXT_KEYS:
            continue

        if isinstance(raw_value, bool):
            fallback = BOOLEAN_FALLBACK_MAP.get(key)
            if fallback:
                _logger.info("Boolean fallback for %s: raw=%s → '%s'", key, raw_value, fallback[0] if raw_value else fallback[1])
                value = fallback[0] if raw_value else fallback[1]
            elif raw_value and key in _BOOLEAN_KEYS:
                value = "\u2713"
            else:
                _logger.info("Datalab returned %s for %s (in _BOOLEAN_KEYS=%s) — skipping", raw_value, key, key in _BOOLEAN_KEYS)
                continue
        else:
            value = str(raw_value).strip()
            clean, had_tick, had_cross = sanitize_checkbox_text(value)
            if had_tick and not had_cross:
                value = clean if clean else "\u2713"
            elif had_tick and had_cross:
                continue
            elif clean != value:
                continue

        if key.startswith("asset_") and key != "asset_others":
            norm = value.strip().lower()
            if norm in ("\u2713", "/", "1", "yes", "y", "true"):
                value = "\u2713"
            else:
                continue
            # Extra guard: only emit asset if it was in the (CV-verified) assets_at_home_list
            if _verified_asset_names and key not in _verified_asset_names:
                continue
        elif key == "asset_others":
            if value and value not in ("\u2713", "\u2717", ""):
                if not value.lower().startswith("others"):
                    value = f"Others: {value}"

        # Adjust confidence for ambiguous fields
        confidence = 90
        if key in ambiguous:
            confidence = 60
            _logger.info("Field %s is ambiguous (%s) — confidence reduced to %d", key, ambiguous[key], confidence)

        fields.append({
            "label": meta["label"],
            "value": value,
            "confidence": confidence,
            "page": meta["page"],
            "section": meta["section"],
        })

    # ── Step 5: Process tables ──
    for key, tmeta in TABLE_MAP.items():
        rows = extracted.get(key)
        if not isinstance(rows, list):
            if isinstance(rows, dict):
                rows = [rows]
            else:
                continue
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            row_data = {k: v for k, v in row.items() if not k.endswith("_citations") and not k.endswith("_meta")}
            for col_name, col_key in zip(tmeta["columns"], tmeta["col_key"]):
                cell_value = row_data.get(col_key)
                if cell_value is None:
                    cell_value = ""
                cell_value = str(cell_value).strip()
                fields.append({
                    "label": f"{tmeta['label_prefix']} — Row {i + 1} — {col_name}",
                    "value": cell_value,
                    "confidence": 90,
                    "page": tmeta["page"],
                    "section": tmeta["section"],
                })

    # ── Step 5.5: Derive has_other_income from table presence ──
    # If Datalab says "No" for 4.4 but the 4.4.1 table has data, auto-correct to "Yes".
    # This handles cases where mark resolution fails or Datalab misreads the checkbox.
    other_income_rows = extracted.get("other_income_table")
    if other_income_rows and isinstance(other_income_rows, list):
        has_data = any(
            isinstance(r, dict) and any(str(v).strip() for v in r.values())
            for r in other_income_rows
        )
        if has_data:
            for f in fields:
                if f["label"] == "4.4 Apart from your job, is there any other source of income?":
                    current = f.get("value", "").strip().lower()
                    if current in ("", "no"):
                        f["value"] = "Yes"
                        f["confidence"] = max(f.get("confidence", 90), 80)
                        _logger.info("Auto-derived has_other_income=Yes from table presence (was '%s')", current)

    # ── Step 6: Merge free-text fields ──
    fields = _merge_free_text(extracted, fields)

    sections = compute_sections()

    confidence = round(sum(f.get("confidence", 90) for f in fields) / len(fields)) if fields else 100

    found_labels = {f.get("label") for f in fields}
    coverage = round(len(found_labels & EXPECTED_FIELD_LABELS) / len(EXPECTED_FIELD_LABELS) * 100) if EXPECTED_FIELD_LABELS else 100

    overall_confidence = round(coverage * confidence / 100)

    result = {
        "fields": fields,
        "sections": sections,
        "overall_confidence": overall_confidence,
        "coverage": coverage,
        "confidence": confidence,
        "raw_text": "",
    }

    # Attach ambiguity data for downstream consumers (database, UI)
    if ambiguous:
        result["_ambiguous_fields"] = ambiguous
        _logger.info("Ambiguous fields requiring review: %s", ambiguous)

    return result
