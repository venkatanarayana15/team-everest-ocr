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

EXTRACT_SCHEMA: dict = {
    "type": "object",
    "properties": {
    "volunteer_name": {"type": "string", "description": "Volunteer Name (header)"},
    "co_volunteer_name": {"type": "string", "description": "Co-Volunteer Name (header)"},
    "date_of_visit": {"type": "string", "description": "Date of Visit (header)"},
    "application_id": {"type": "string", "description": "1.1 Application ID"},
    "student_full_name": {"type": "string", "description": "1.2 Student Full Name"},
    "gender": {"type": "string", "description": "1.3 Gender: Male | Female | Others"},
    "family_status": {"type": "string", "description": "2.1 Family Status: Single Parent | Parentless | Having both parents"},
    "relationship_death_year": {"type": "string", "description": "2.2 Relationship Details — Year of Death / Separation"},
    "relationship_death_reason": {"type": "string", "description": "2.2 Relationship Details — Reason for Death / Separation"},
    "photograph_kept_at_home": {"type": "string", "description": "2.3 Is Father/Mother photograph kept at home?: Yes | No"},
    "govt_id_aadhaar": {"type": "boolean", "description": "2.4 Government ID Verified — Aadhaar Card (checked=true)"},
    "govt_id_ration": {"type": "boolean", "description": "2.4 Government ID Verified — Ration Card"},
    "govt_id_driving_licence": {"type": "boolean", "description": "2.4 Government ID Verified — Driving Licence"},
    "govt_id_voter": {"type": "boolean", "description": "2.4 Government ID Verified — Voter ID"},
    "govt_id_other": {"type": "boolean", "description": "2.4 Government ID Verified — Other"},
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
    "house_ownership": {"type": "string", "description": "3.1 House Ownership: Own | Rented"},
    "rent_amount": {"type": "string", "description": "3.1.1 If rented, what is the rent amount?"},
    "home_type_individual": {"type": "boolean", "description": "3.2 Type of Home — Individual"},
    "home_type_private_apartment": {"type": "boolean", "description": "3.2 Type of Home — Private Apartment"},
    "home_type_housing_board": {"type": "boolean", "description": "3.2 Type of Home — Housing Board"},
    "home_type_line_house": {"type": "boolean", "description": "3.2 Type of Home — Line House"},
    "home_type_others": {"type": "string", "description": "3.2 Type of Home — Others (return the full text including 'Others:' prefix, e.g. 'Others: living with grand parents' or 'Others: They are staying in grandmother' own house')"},
    "ceiling_roof": {"type": "boolean", "description": "3.3 Type of Ceiling — Roof (Kurai)"},
    "ceiling_tiled": {"type": "boolean", "description": "3.3 Type of Ceiling — Tiled"},
    "ceiling_asbestos": {"type": "boolean", "description": "3.3 Type of Ceiling — Asbestos / Sheet"},
    "ceiling_concrete": {"type": "boolean", "description": "3.3 Type of Ceiling — Concrete"},
    "number_of_bedrooms": {"type": "string", "description": "3.4 Number of Bedrooms"},
    "type_of_bedroom": {"type": "string", "description": "3.4.1 Type of Bedroom: Separate Bedroom | No Separate Bedroom"},
    "bathroom": {"type": "string", "description": "3.5 Bathroom: Separate | Common for Apartment"},
    "kitchen_separate": {"type": "boolean", "description": "3.6 Kitchen Type — Separate Kitchen"},
    "kitchen_hall": {"type": "boolean", "description": "3.6 Kitchen Type — Hall with Kitchen"},
    "asset_washing_machine": {"type": "boolean", "description": "4.1 Assets at Home — Washing Machine"},
    "asset_fridge": {"type": "boolean", "description": "4.1 Assets at Home — Fridge"},
    "asset_ac": {"type": "boolean", "description": "4.1 Assets at Home — AC"},
    "asset_led_tv": {"type": "boolean", "description": "4.1 Assets at Home — LED TV"},
    "asset_two_wheeler": {"type": "boolean", "description": "4.1 Assets at Home — Two-Wheeler"},
    "asset_car": {"type": "boolean", "description": "4.1 Assets at Home — Car"},
    "asset_smartphone": {"type": "boolean", "description": "4.1 Assets at Home — Smartphone"},
    "asset_separate_wifi": {"type": "boolean", "description": "4.1 Assets at Home — Separate Wi-Fi"},
    "asset_others": {"type": "boolean", "description": "4.1 Assets at Home — Others"},
    "last_electricity_bill": {"type": "string", "description": "4.2 Amount of Last Electricity Bill"},
    "owns_other_assets": {"type": "string", "description": "4.3 Do you own any other assets?: Yes | No"},
    "other_assets_table": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "property_description": {"type": "string", "description": "Property description"},
                "owner_name": {"type": "string", "description": "Owner name"},
                "approximate_value": {"type": "string", "description": "Approximate value"},
            },
        },
        "description": "4.3.1 Other assets/properties table",
    },
    "has_other_income": {"type": "string", "description": "4.4 Apart from job, other income?: Yes | No"},
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
    "income_type": {"type": "string", "description": "4.5 Income Type: Monthly | Daily | Weekly | Ad-Hoc"},
    "has_loans": {"type": "string", "description": "4.6 Do you have any loans?: Yes | No"},
    "loans_table": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
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
    "has_health_issues": {"type": "string", "description": "5.1 Does the student have any health issues?: Yes | No"},
    "health_issues_description": {"type": "string", "description": "5.2 If yes, list the health issues"},
    "study_commitment": {"type": "string", "description": "6.1 Will you study college for three years without any obstacle?"},
    "training_program_availability": {"type": "string", "description": "6.2 Training program within 15 km?: Yes | No | Maybe"},
    "ready_for_skill_classes": {"type": "string", "description": "6.3 Ready for weekly skill development classes?: Yes | No"},
    "other_scholarships": {"type": "string", "description": "7.1 Other scholarships applied/received for UG degree?"},
    "volunteer_opinion": {"type": "string", "description": "8.1 Volunteer opinion about the student and family"},
    "recommend_student": {"type": "string", "description": "8.2 Will you recommend this student?: Yes | No | Not Sure"},
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
    "kitchen_separate": {"label": "3.6 Kitchen Type — Separate Kitchen", "page": 3, "section": 3},
    "kitchen_hall": {"label": "3.6 Kitchen Type — Hall with Kitchen", "page": 3, "section": 3},
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
        "columns": ["Loan Purpose", "Loan Amount Taken", "Pending Loan Amount"],
        "col_key": ["loan_purpose", "loan_amount_taken", "pending_loan_amount"],
        "section": 4,
        "page": 4,
    },
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

    fields = []

    for key, meta in SCHEMA_KEY_MAP.items():
        raw_value = extracted.get(key)
        if raw_value is None:
            continue
        if isinstance(raw_value, bool):
            value = "\u2713" if raw_value else "\u2717"
        else:
            value = str(raw_value).strip()
            clean, had_tick, had_cross = sanitize_checkbox_text(value)
            if had_tick and not had_cross:
                value = clean if clean else "\u2713"
            elif had_tick and had_cross:
                continue
            elif clean != value:
                continue
        if key == "home_type_others" and value and value not in ("\u2713", "\u2717", ""):
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
