"""JSON schema + response mapper for Datalab /api/v1/extract."""

import json
import re
from dataclasses import dataclass

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

# Datalab may return booleans for yes/no fields even when schema says "type": "string".
# Map true/false to "Yes"/"No". Multi-option fields (kitchen_type, house_ownership,
# etc.) are NOT included — if Datalab returns a boolean for them we can't know
# which option is correct, so the field stays null.
BOOLEAN_FALLBACK_MAP: dict[str, tuple[str, str]] = {
    "photograph_kept_at_home": ("Yes", "No"),
    "owns_other_assets": ("Yes", "No"),
    "has_other_income": ("Yes", "No"),
    "has_health_issues": ("Yes", "No"),
    "has_loans": ("Yes", "No"),
    "ready_for_skill_classes": ("Yes", "No"),
}

EXTRACT_SCHEMA: dict = {
    "type": "object",
    "properties": {
    "volunteer_name": {"type": "string", "description": "Volunteer Name (header row, far left, labeled 'Volunteer Name:'). A person's name — read each letter carefully. Common handwriting misreads: 'n' vs 'u', 'a' vs 'o', 'l' vs 't', 'r' vs 'v'. Double-check every character."},
    "co_volunteer_name": {"type": "string", "description": "Co-Volunteer Name (header row, center, labeled 'Co-Volunteer Name:', between Volunteer Name and Date of Visit). A person's name. Common handwriting misreads: 'n' vs 'u', 'a' vs 'o', 'l' vs 't', 'r' vs 'v'."},
    "date_of_visit": {"type": "string", "description": "Date of Visit (header row, far right, labeled 'Date:' or 'Date of Visit:'). A date like DD/MM/YYYY or written as text."},
    "application_id": {"type": "string", "description": "1.1 Application ID (Section 1 — Student Profile, FIRST field below the header row, labeled '1.1 Application ID' or '1.1. Application ID'). An alphanumeric CODE (e.g. 'TE2024001'), NOT a person's name. Check for digits that look like letters — e.g. '0' vs 'O', '1' vs 'l', '5' vs 'S'."},
    "student_full_name": {"type": "string", "description": "1.2 Student Full Name (Section 1 — Student Profile, below Application ID, labeled '1.2 Student Full Name' or '1.2. Student Full Name'). The student's full name. Common handwriting misreads: 'n' vs 'u', 'a' vs 'o', 'l' vs 't', 'r' vs 'v'. Read each character individually."},
    "gender": {"type": "string", "description": "1.3 Gender: Male | Female | Others"},
    "family_status": {"type": "string", "description": "2.1 Family Status: Three checkboxes — 'Single Parent', 'Parentless', 'Having both parents'. ONLY a tick (✓), forward-slash (/) or a circle/square border around the text counts as SELECTED. A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — ignore all marks that are not a clear ✓ or /. If none has ✓ or /, return empty string ''. If multiple have ✓ or /, return the one with ✓. Return the EXACT option text: 'Single Parent', 'Parentless', or 'Having both parents'. If any additional notes are written below these checkbox options, capture them in the 'Relationship Details — Reason for Death / Separation' field (2.2)."},
    "relationship_death_year": {"type": "string", "description": "2.2 Relationship Details — Year of Death / Separation"},
    "relationship_death_reason": {"type": "string", "description": "2.2 Relationship Details — Reason for Death / Separation. FIRST: look at the 'Reason for Death / Separation' section and capture the boxed/underlined text. SECOND (CRITICAL): look at the blank space BELOW the 2.1 Family Status checkbox options — if there is any handwritten text in that area (e.g. 'Mother passed away in 2020, father is daily wage laborer'), capture it here verbatim. Combine both parts with ' — ' separator if both exist."},
    "photograph_kept_at_home": {"type": "string", "description": "2.3 Is Father/Mother photograph kept at home?: Two checkboxes — 'Yes' and 'No'. ONLY a tick (✓), forward-slash (/) or a circle/square border around the text counts as SELECTED. A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — ignore all marks that are not a clear ✓ or /. If neither has ✓ or /, return empty string ''. Return ONLY 'Yes' or 'No'."},
    "govt_id_aadhaar": {"type": "boolean", "description": "2.4 Government ID Verified — Aadhaar Card. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false."},
    "govt_id_ration": {"type": "boolean", "description": "2.4 Government ID Verified — Ration Card. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false."},
    "govt_id_driving_licence": {"type": "boolean", "description": "2.4 Government ID Verified — Driving Licence. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false."},
    "govt_id_voter": {"type": "boolean", "description": "2.4 Government ID Verified — Voter ID. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false."},
    "govt_id_other": {"type": "boolean", "description": "2.4 Government ID Verified — Other. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false."},
    "govt_id_other_text": {"type": "string", "description": "2.4 Government ID Verified — Other (text written on the blank line next to Other checkbox, e.g. 'Pan Card', 'Senior Citizen ID')"},
    "family_members": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Family member name"},
                "age": {"type": "string", "description": "Age"},
                "education": {"type": "string", "description": "Education"},
                "occupation": {"type": "string", "description": "Occupation"},
                "annual_income": {"type": "string", "description": "Annual Income"},
            },
        },
        "description": "2.5 Family Members table",
    },
    "house_ownership": {"type": "string", "description": "3.1 House Ownership: Two checkboxes — 'Own' and 'Rented'. ONLY a tick (✓), forward-slash (/) or a circle/square border around the text counts as SELECTED. A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — ignore all marks that are not a clear ✓ or /. If neither has ✓ or /, return empty string ''. Return the EXACT option text: 'Own' or 'Rented'."},
    "rent_amount": {"type": "string", "description": "3.1.1 Rent amount or ownership notes (capture any text written, even if Own is selected)"},
    "home_type_individual": {"type": "boolean", "description": "3.2 Type of Home — Individual. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false."},
    "home_type_private_apartment": {"type": "boolean", "description": "3.2 Type of Home — Private Apartment. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false."},
    "home_type_housing_board": {"type": "boolean", "description": "3.2 Type of Home — Housing Board. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false."},
    "home_type_line_house": {"type": "boolean", "description": "3.2 Type of Home — Line House. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false."},
    "home_type_others": {"type": "string", "description": "3.2 Type of Home — Others. Return the full text written on the blank line next to 'Others', e.g. 'Others: living with grand parents'. Prefix with 'Others: ' if not already present."},
    "ceiling_roof": {"type": "boolean", "description": "3.3 Type of Ceiling — Roof (Kurai). Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false."},
    "ceiling_tiled": {"type": "boolean", "description": "3.3 Type of Ceiling — Tiled. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false."},
    "ceiling_asbestos": {"type": "boolean", "description": "3.3 Type of Ceiling — Asbestos / Sheet. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false."},
    "ceiling_concrete": {"type": "boolean", "description": "3.3 Type of Ceiling — Concrete. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false."},
    "number_of_bedrooms": {"type": "string", "description": "3.4 Number of Bedrooms"},
    "type_of_bedroom": {"type": "string", "description": "3.4.1 Type of Bedroom: Two checkboxes — 'Separate Bedroom' and 'No Separate Bedroom'. ONLY a tick (✓), forward-slash (/) or a circle/square border around the text counts as SELECTED. A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — ignore all marks that are not a clear ✓ or /. If neither has ✓ or /, return empty string ''. Return the EXACT option text: 'Separate Bedroom' or 'No Separate Bedroom'."},
    "bathroom": {"type": "string", "description": "3.5 Bathroom: Two checkboxes — 'Separate' and 'Common for Apartment'. ONLY a tick (✓), forward-slash (/) or a circle/square border around the text counts as SELECTED. A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — ignore all marks that are not a clear ✓ or /. If neither has ✓ or /, return empty string ''. Return the EXACT option text: 'Separate' or 'Common for Apartment'."},
    "kitchen_type": {"type": "string", "description": "3.6 Kitchen Type: Two checkboxes — 'Separate Kitchen' and 'Hall with Kitchen'. ONLY a tick (✓), forward-slash (/) or a circle/square border around the text counts as SELECTED. A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — ignore all marks that are not a clear ✓ or /. If neither has ✓ or /, return empty string ''. Return the EXACT option text: 'Separate Kitchen' or 'Hall with Kitchen'."},
    "asset_washing_machine": {"type": "boolean", "description": "4.1 Assets at Home — Washing Machine. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false. Omit if blank."},
    "asset_fridge": {"type": "boolean", "description": "4.1 Assets at Home — Fridge. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false. Omit if blank."},
    "asset_ac": {"type": "boolean", "description": "4.1 Assets at Home — AC. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false. Omit if blank."},
    "asset_led_tv": {"type": "boolean", "description": "4.1 Assets at Home — LED TV. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false. Omit if blank."},
    "asset_two_wheeler": {"type": "boolean", "description": "4.1 Assets at Home — Two-Wheeler. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false. Omit if blank."},
    "asset_car": {"type": "boolean", "description": "4.1 Assets at Home — Car. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false. Omit if blank."},
    "asset_smartphone": {"type": "boolean", "description": "4.1 Assets at Home — Smartphone. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false. Omit if blank."},
    "asset_separate_wifi": {"type": "boolean", "description": "4.1 Assets at Home — Separate Wi-Fi. Return true ONLY if the checkbox has a clear tick (✓) or forward-slash (/). A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — return false. Omit if blank."},
    "asset_others": {"type": "string", "description": "4.1 Assets at Home — Others. CRITICAL: Always return any text written on the blank line after 'Others' even if the checkbox is not ticked. Prefix it with 'Others: ' — e.g. 'Others: normal tv'. If the checkbox has a mark with no text, return '✓' for tick, 'x' or '✗' for cross."},
    "last_electricity_bill": {"type": "string", "description": "4.2 Last Electricity Bill Amount — extract the monthly electricity bill amount written on the form (e.g. '700', 'Rs.700/-', '700/-'). This is a handwritten amount in the electricity bill field — ignore any other numbers printed on the page."},
    "owns_other_assets": {"type": "string", "description": "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student?: Two checkboxes — 'Yes' and 'No'. ONLY a tick (✓), forward-slash (/) or a circle/square border around the text counts as SELECTED. A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — ignore all marks that are not a clear ✓ or /. If neither has ✓ or /, return empty string ''. Return ONLY 'Yes' or 'No'."},
    "other_assets_table": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "property_description": {"type": "string", "description": "Property description. ALSO capture any handwritten notes from TWO locations: (1) the blank space below the 4.3 checkbox on page 3, and (2) the blank space below the 4.3.1 table rows before the 4.4 question on page 4. Include each note as a separate row in the 'property_description' field with owner_name and approximate_value left blank."},
                "owner_name": {"type": "string", "description": "Owner name"},
                "approximate_value": {"type": "string", "description": "Approximate value"},
            },
        },
        "description": "4.3.1 Other assets/properties table. The table typically has 1-2 structured rows. ALSO look for handwritten notes in TWO locations: (a) the blank space below the '4.3 Do you own any other assets/properties...' checkbox on page 3, and (b) the blank space below the table rows before the 4.4 question on page 4. Include each note as an extra row with the text in 'property_description' and leave owner_name and approximate_value blank.",
    },
    "has_other_income": {"type": "string", "description": "4.4 Apart from your job, is there any other source of income?: Two checkboxes — 'Yes' and 'No'. ONLY a tick (✓), forward-slash (/) or a circle/square border around the text counts as SELECTED. A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — ignore all marks that are not a clear ✓ or /. If neither has ✓ or /, return empty string ''. Return ONLY 'Yes' or 'No'."},
    "other_income_table": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source of income"},
                "amount": {"type": "string", "description": "Amount"},
            },
        },
        "description": "4.4.1 Other income sources table",
    },
    "income_type": {"type": "string", "description": "4.5 Income Type: Four checkboxes — 'Monthly', 'Daily', 'Weekly', 'Ad-Hoc'. ONLY a tick (✓), forward-slash (/) or a circle/square border around the text counts as SELECTED. A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — ignore all marks that are not a clear ✓ or /. If none has ✓ or /, return empty string ''. If multiple have ✓ or /, return the one with ✓. Return the EXACT option text: 'Monthly', 'Daily', 'Weekly', or 'Ad-Hoc'."},
    "has_loans": {"type": "string", "description": "4.6 Do you have any loans?: Two checkboxes — 'Yes' and 'No'. ONLY a tick (✓), forward-slash (/) or a circle/square border around the text counts as SELECTED. A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — ignore all marks that are not a clear ✓ or /. If neither has ✓ or /, return empty string ''. Return ONLY 'Yes' or 'No'."},
    "loans_table": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "serial_number": {"type": "string", "description": "S.No"},
                "loan_purpose": {"type": "string", "description": "Loan purpose"},
                "loan_amount_taken": {"type": "string", "description": "Loan amount taken"},
                "pending_loan_amount": {"type": "string", "description": "Pending loan amount"},
            },
        },
        "description": "4.6.1 Loans table",
    },
    "college_fee": {"type": "string", "description": "4.7 If you choose college, how much is the college fee?"},
    "manage_higher_fee": {"type": "string", "description": "4.8 If the college fee is higher, how will you manage it?"},
    "manage_without_scholarship": {"type": "string", "description": "4.9 If you do not receive this scholarship, how will you pay the fees?"},
    "has_health_issues": {"type": "string", "description": "5.1 Does the student have any health issues?: Two checkboxes — 'Yes' and 'No'. ONLY a tick (✓), forward-slash (/) or a circle/square border around the text counts as SELECTED. A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — ignore all marks that are not a clear ✓ or /. If neither has ✓ or /, return empty string ''. Return ONLY 'Yes' or 'No'."},
    "health_issues_description": {"type": "string", "description": "5.2 If yes, list the health issues"},
    "study_commitment": {"type": "string", "description": "6.1 Will you study college for three years without any obstacle?"},
    "training_program_availability": {"type": "string", "description": "6.2 If we have a training program within 15 km from your home, can you come?: Three checkboxes — 'Yes', 'No', 'Maybe'. ONLY a tick (✓), forward-slash (/) or a circle/square border around the text counts as SELECTED. A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — ignore all marks that are not a clear ✓ or /. If none has ✓ or /, return empty string ''. If multiple have ✓ or /, return the one with ✓. Return the EXACT option text: 'Yes', 'No', or 'Maybe'."},
    "ready_for_skill_classes": {"type": "string", "description": "6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)?: Two checkboxes — 'Yes' and 'No'. ONLY a tick (✓), forward-slash (/) or a circle/square border around the text counts as SELECTED. A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — ignore all marks that are not a clear ✓ or /. If neither has ✓ or /, return empty string ''. Return ONLY 'Yes' or 'No'."},
    "other_scholarships": {"type": "string", "description": "7.1 Other scholarships applied/received for UG degree?"},
    "volunteer_opinion": {"type": "string", "description": "8.1 Volunteer opinion about the student and family"},
    "recommend_student": {"type": "string", "description": "8.2 Will you recommend this student for this scholarship?: Three checkboxes — 'Yes', 'No', 'Not Sure'. ONLY a tick (✓), forward-slash (/) or a circle/square border around the text counts as SELECTED. A cross (✗), scribble, correction mark, dot or any other mark means NOT SELECTED — ignore all marks that are not a clear ✓ or /. If none has ✓ or /, return empty string ''. If multiple have ✓ or /, return the one with ✓. Return the EXACT option text: 'Yes', 'No', or 'Not Sure'."},
    "volunteer_comments": {"type": "string", "description": "8.3 Other comments"},
    },
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


def convert_extract_response(response: dict) -> dict:
    raw = response.get("extraction_schema_json", response)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    if not isinstance(raw, dict):
        return {}

    extracted = {k: v for k, v in raw.items() if not k.endswith("_citations") and not k.endswith("_meta")}

    import logging
    _logger = logging.getLogger(__name__)
    _asset_raw = {k: extracted.get(k) for k in extracted if k.startswith("asset_") if k != "asset_others"}
    _logger.info("DEBUG raw asset values from extraction_schema_json: %s", _asset_raw)

    fields = []

    for key, meta in SCHEMA_KEY_MAP.items():
        raw_value = extracted.get(key)
        if raw_value is None:
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
        elif key == "asset_others":
            if value and value not in ("\u2713", "\u2717", ""):
                if not value.lower().startswith("others"):
                    value = f"Others: {value}"

        fields.append({
            "label": meta["label"],
            "value": value,
            "confidence": 90,
            "page": meta["page"],
            "section": meta["section"],
        })

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

    confidence = round(sum(f.get("confidence", 90) for f in fields) / len(fields)) if fields else 100

    found_labels = {f.get("label") for f in fields}
    coverage = round(len(found_labels & EXPECTED_FIELD_LABELS) / len(EXPECTED_FIELD_LABELS) * 100) if EXPECTED_FIELD_LABELS else 100

    overall_confidence = round(coverage * confidence / 100)

    return {
        "fields": fields,
        "sections": sections,
        "overall_confidence": overall_confidence,
        "coverage": coverage,
        "confidence": confidence,
        "raw_text": "",
    }
