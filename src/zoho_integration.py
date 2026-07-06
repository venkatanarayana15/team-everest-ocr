import asyncio
import hashlib
import http.client
import json
import logging
import os
import re
import threading
import time
from typing import Any
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

from src.status import _set_status, _get_status
from src.pipeline_runner import run_pipeline, _print_field_report

logger = logging.getLogger(__name__)

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

ZOHO_CLIENT_ID = get_required_env("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = get_required_env("ZOHO_CLIENT_SECRET")
ZOHO_REFRESH_TOKEN = get_required_env("ZOHO_REFRESH_TOKEN")
SUPABASE_URL = get_required_env("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = get_required_env("SUPABASE_SERVICE_ROLE_KEY")

_TOKEN_CACHE: dict = {"token": None, "expires_at": 0.0}
_ACTIVE_ZOHO_RECORDS: set[str] = set()
_TOKEN_LOCK = threading.Lock()

# ── Retry helper for transient Zoho API failures ────────────────


def _urlopen_with_retry(request: urllib.request.Request, max_retries: int = 3, timeout: int | None = None) -> http.client.HTTPResponse:
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504) and attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning("HTTP %d on attempt %d/%d, retrying in %ds", e.code, attempt + 1, max_retries, wait)
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning("%s on attempt %d/%d, retrying in %ds", type(e).__name__, attempt + 1, max_retries, wait)
                time.sleep(wait)
                continue
            raise


class OcrExtractRequest(BaseModel):
    record_id: str
    zoho_app_owner: str
    zoho_app_link_name: str
    zoho_report_link_name: str
    zoho_record_id: str
    file_field_link_name: str
    file_names: list[str]
    bucket: str = "files"
    questionnaire_report_link_name: str = "Home_Visit_Questionnaire_Report"
    questionnaire_form_link_name: str = "Home_Visit_Questionnaire"
    application_id: str = ""


def _get_zoho_access_token() -> str:
    now = time.time()
    with _TOKEN_LOCK:
        if _TOKEN_CACHE["token"] and now < _TOKEN_CACHE["expires_at"] - 60:
            return _TOKEN_CACHE["token"]

        data = urllib.parse.urlencode({
            "refresh_token": ZOHO_REFRESH_TOKEN,
            "client_id": ZOHO_CLIENT_ID,
            "client_secret": ZOHO_CLIENT_SECRET,
            "grant_type": "refresh_token",
        }).encode()
        req = urllib.request.Request(
            "https://accounts.zoho.com/oauth/v2/token", data=data,
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        if "access_token" not in result:
            raise RuntimeError(f"Zoho OAuth failed: {result}")

        expires_in = result.get("expires_in", 3600)
        _TOKEN_CACHE["token"] = result["access_token"]
        _TOKEN_CACHE["expires_at"] = now + expires_in
        return result["access_token"]


def _download_zoho_file(access_token: str, req: OcrExtractRequest, file_name: str) -> bytes:
    encoded_path = urllib.parse.quote(file_name, safe='')
    owner = req.zoho_app_owner
    app = req.zoho_app_link_name
    report = req.zoho_report_link_name
    record_id = req.zoho_record_id
    field = req.file_field_link_name
    url = (f"https://www.zohoapis.com/creator/v2.1/data/{owner}/"
           f"{app}/report/{report}/"
           f"{record_id}/{field}/download?filepath={encoded_path}")
    logger.info("Download URL: owner=%s app=%s report=%s record=%s field=%s file=%s",
                owner, app, report, record_id, field, file_name)
    request = urllib.request.Request(
        url, headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
    )
    try:
        with _urlopen_with_retry(request, timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 401:
            logger.info("Got HTTP 401 downloading file; invalidating token cache and retrying...")
            with _TOKEN_LOCK:
                _TOKEN_CACHE["token"] = None
            fresh_token = _get_zoho_access_token()
            request.remove_header("Authorization")
            request.add_header("Authorization", f"Zoho-oauthtoken {fresh_token}")
            with _urlopen_with_retry(request, timeout=60) as resp:
                return resp.read()
        raise


def _upload_to_supabase(bucket: str, path: str, data: bytes, content_type: str) -> None:
    url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{path}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "x-upsert": "true",
        "Content-Type": content_type,
    }
    request = urllib.request.Request(url, data=data, headers=headers, method='PUT')
    with _urlopen_with_retry(request, timeout=30) as resp:
        resp.read()


def _update_zoho_creator(access_token: str, req: OcrExtractRequest, status: str = "updated") -> None:
    url = (f"https://www.zohoapis.com/creator/v2.1/data/{req.zoho_app_owner}/"
           f"{req.zoho_app_link_name}/report/{req.zoho_report_link_name}/"
           f"{req.zoho_record_id}")
    data = json.dumps({"data": {"OCR_Status": status}}).encode()
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }
    request = urllib.request.Request(url, data=data, headers=headers, method='PATCH')
    with _urlopen_with_retry(request, timeout=30) as resp:
        resp.read()


# ── Field mapping: extracted label → Zoho Creator field link name ──────────

FIELD_TO_ZOHO: dict[str, str] = {
    # Header
    "Volunteer Name": "Volunteer_Name",
    "Co-Volunteer Name": "Co_Volunteer_Name",
    "Date of Visit": "Date_of_Visit",
    # Section 1 — Student Profile
    "1.1 Application ID": "Application_ID",
    "1.2 Student Full Name": "Student_Full_Name",
    "1.3 Gender": "Gender",
    # Section 2 — Family Background
    "2.1 Family Status": "Family_Status",
    "2.3 Is Father/Mother photograph kept at home?": "Is_Father_Mother_photograph_kept_at_home",
    "2.4 Government ID Verified": "Government_ID_Verified_Ration_Card_Aadhaar_Driving_Licence_Voter_ID",
    # Section 3 — Housing Condition
    "3.1 House Ownership": "House_Ownership",
    "3.1.1 If rented, what is the rent amount?": "If_rented_what_is_the_rent_amount",
    "3.4 Number of Bedrooms": "Number_of_Bedrooms",
    "3.4.1 Type of Bedroom": "Type_of_Bedroom",
    "3.5 Bathroom": "Bathroom",
    # Section 4 — Financial Background
    "4.2 Amount of Last Electricity Bill": "Amount_of_Last_Electricity_Bill",
    "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student?": "Do_you_own_any_other_assets_or_properties_in_the_name_of_grandparents_parent_or_student",
    "4.4 Apart from your job, is there any other source of income?": "Apart_from_your_job_is_there_any_other_source_of_income",
    "4.5 Income Type": "Income_Type",
    "4.6 Do you have any loans?": "Do_you_have_any_loans",
    "4.7 If you choose any college, how much is the college fee?": "If_you_choose_any_college_how_much_is_the_college_fee",
    "4.8 If the college fee is higher, how will you manage it?": "If_the_college_fee_is_higher_how_will_you_manage_it",
    "4.9 If you do not receive this scholarship, how will you pay the fees?": "If_you_do_not_receive_this_scholarship_how_will_you_pay_the_fees",
    # Section 5 — Health Information
    "5.1 Does the student have any health issues?": "Does_the_student_have_any_health_issues",
    "5.2 If yes, list the health issues": "If_yes_list_the_health_issues",
    # Section 6 — Student Commitment
    "6.1 Will you study college for three years without any obstacle?": "Will_you_study_college_for_three_years_without_any_obstacle",
    "6.2 If we have a training program within 15 km from your home, can you come?": "If_we_have_a_training_program_within_15_km_from_your_home_can_you_come1",
    "6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)?": "Are_you_ready_to_send_your_son_daughter_to_weekly_skill_development_classes_on_Sundays1",
    # Section 7 — Scholarship Information
    "7.1 Has the student received or applied for any other scholarships for their UG degree?": "Has_the_student_received_or_Applied_for_any_other_scholarships_for_their_UG_degree",
    # Section 8 — Volunteer Observation
    "8.1 What is your opinion about the student, their family members, and their living condition?": "What_is_your_opinion_about_the_student_their_family_members_and_their_living_condition",
    "8.2 Will you recommend this student for this scholarship?": "Will_you_recommend_this_student_for_this_scholarship",
    "8.3 Any other comments you want to share?": "Any_other_comments_that_you_want_to_share",
}

# Multi-select checkbox groups: prefix in label → Creator field + aggregation type
# The OCR extracts each checkbox option as "{prefix} — {option}" with value "✓"/"✗"
AGGREGATE_MAP: dict[str, dict[str, str]] = {
    "3.2 Type of Home": {"target": "Type_of_Home", "type": "text"},
    "3.3 Type of Ceiling": {"target": "Type_of_Ceiling", "type": "text"},
    "3.6 Kitchen Type": {"target": "Kitchen_Type", "type": "text"},
    "4.1 Assets at Home": {"target": "Assets_at_Home_tick_all_that_apply", "type": "stringlist"},
}

# Table rows: OCR produces "{table_name} — Row {n} — {column}"
TABLE_TO_SUBFORM: dict[str, dict[str, Any]] = {
    "2.5 Family Members": {
        "subform": "Family_Members_Table",
        "columns": {
            "Name": "Name",
            "Age": "Age",
            "Education": "Education",
            "Occupation": "Occupation",
            "Annual Income": "Annual_Income",
        },
    },
    "4.3.1": {
        "subform": "If_yes_list_their_properties_share",
        "columns": {
            "Property Description": "Property_Description",
            "Owner Name": "Owner_Name",
            "Approximate Value": "Approximate_Value",
        },
    },
    "4.3.1 If yes, list their properties": {
        "subform": "If_yes_list_their_properties_share",
        "columns": {
            "Property Description": "Property_Description",
            "Owner Name": "Owner_Name",
            "Approximate Value": "Approximate_Value",
        },
    },
    "4.4.1": {
        "subform": "If_yes_list_other_sources_of_income",
        "columns": {
            "Source of Income": "Source_of_Income",
            "Amount": "Amount",
        },
    },
    "4.4.1 If yes, list other sources of income": {
        "subform": "If_yes_list_other_sources_of_income",
        "columns": {
            "Source of Income": "Source_of_Income",
            "Amount": "Amount",
        },
    },
    "4.6.1": {
        "subform": "If_yes_share_the_Loan_Purpose_Amount_Taken_and_Pending_Loan_Amount",
        "columns": {
            "Loan Purpose": "Loan_Purpose",
            "Loan Amount Taken": "Loan_Amount_Taken",
            "Pending Loan Amount": "Pending_Loan_Amount",
            "Sr. No.": "Sr_No",
        },
    },
    "4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount": {
        "subform": "If_yes_share_the_Loan_Purpose_Amount_Taken_and_Pending_Loan_Amount",
        "columns": {
            "Loan Purpose": "Loan_Purpose",
            "Loan Amount Taken": "Loan_Amount_Taken",
            "Pending Loan Amount": "Pending_Loan_Amount",
            "Sr. No.": "Sr_No",
        },
    },
}

# Flat OCR fields that should become subform rows in Creator
#   e.g. "2.2 Relationship Details — Year of Death / Separation" → Family_Background_Relationship subform
FLAT_TO_SUBFORM_MAP: dict[str, dict[str, Any]] = {
    "2.2 Relationship Details": {
        "subform": "Family_Background_Relationship",
        "columns": {
            "Year of Death / Separation": "Year_of_Death_Separation",
            "Reason for Death / Separation": "Reason_for_Death_Separation",
        },
    },
}

# Type maps for numeric coercion
ZOHO_NUMERIC_FIELDS: set[str] = {
    "Number_of_Bedrooms",
    "Year_of_Death_Separation",
    "Age",
    "Sr_No",
}

ZOHO_DECIMAL_FIELDS: set[str] = {
    "Amount_of_Last_Electricity_Bill",
    "Amount",
}

ZOHO_STRINGLIST_FIELDS: set[str] = {
    "Assets_at_Home_tick_all_that_apply",
    "Government_ID_Verified_Ration_Card_Aadhaar_Driving_Licence_Voter_ID",
}

# Fields that expect Yes/No values — reject any non-boolean value to avoid Creator validation errors
ZOHO_BOOLEAN_FIELDS: set[str] = {
    "Is_Father_Mother_photograph_kept_at_home",
    "Apart_from_your_job_is_there_any_other_source_of_income",
    "Do_you_have_any_loans",
    "Does_the_student_have_any_health_issues",
    "Will_you_study_college_for_three_years_without_any_obstacle",
    "If_we_have_a_training_program_within_15_km_from_your_home_can_you_come1",
    "Are_you_ready_to_send_your_son_daughter_to_weekly_skill_development_classes_on_Sundays1",
    "Has_the_student_received_or_Applied_for_any_other_scholarships_for_their_UG_degree",
    "Will_you_recommend_this_student_for_this_scholarship",
    "Do_you_own_any_other_assets_or_properties_in_the_name_of_grandparents_parent_or_student",
}

# Subform rows lacking these columns are dropped (Creator rejects them)
SUBFORM_REQUIRED_COLUMNS: dict[str, set[str]] = {
    "Family_Members_Table": {"Name", "Age"},
    "If_yes_list_their_properties_share": {"Property_Description"},
    "If_yes_list_other_sources_of_income": {"Source_of_Income"},
    "If_yes_share_the_Loan_Purpose_Amount_Taken_and_Pending_Loan_Amount": {"Loan_Purpose"},
    "Family_Background_Relationship": {"Year_of_Death_Separation"},
}

_SUBROW_RE = re.compile(r'^(.+?) — Row (\d+) — (.+)$')


_INLINE_CHECKBOX_RE = re.compile(r"[☐☒☑✓✗]\s*([^☐☒☑✓✗]+?)(?=\s*[☐☒☑✓✗]|\s*$)")


def _sanitize_value(value: str, zoho_field: str) -> Any:
    """Coerce an OCR-extracted string value to the Zoho Creator field type."""
    if not value:
        return ""
    if value == "N/A":
        return value
    if value.lower() in ("nil", "n/a", "na", "none", "—"):
        return ""
    cleaned = value.strip()
    # Inline checkbox fallback: "☐ Yes ☒ No" → extract the checked option
    if "☐" in cleaned or "☒" in cleaned:
        checked_match = re.search(r"☒\s*([^☐☒☑✓✗]+?)(?=\s*[☐☒☑✓✗]|\s*$)", cleaned)
        if checked_match:
            opt = checked_match.group(1).strip()
            if opt.lower() in ("yes", "no"):
                return opt.capitalize()
            if opt:
                return opt
        # Ambiguous checkbox with no ☒ — can't determine value, skip
        return ""
    if zoho_field in ZOHO_NUMERIC_FIELDS:
        m = re.search(r'[\d,]+(?:\.\d+)?', cleaned)
        if m:
            cleaned = m.group().replace(',', '')
            try:
                return int(float(cleaned))
            except (ValueError, OverflowError):
                return ""
        return ""
    if zoho_field in ZOHO_DECIMAL_FIELDS:
        m = re.search(r'[\d,]+\.?\d*', cleaned)
        if m:
            cleaned = m.group().replace(',', '')
            try:
                return float(cleaned) if cleaned else ""
            except (ValueError, OverflowError):
                return ""
        return ""
    # Strip trailing period: "No." → "No", "Yes." → "Yes"
    if cleaned.rstrip(".").lower() in ("yes", "no"):
        return cleaned.rstrip(".").capitalize()
    # Heuristic for long-text boolean answers: positive/affirmative → "Yes"
    if zoho_field in ZOHO_BOOLEAN_FIELDS and len(cleaned) > 10:
        positive_words = {"yes", "will", "determined", "commit", "sure", "of course", "definitely", "absolutely", "agree"}
        negative_words = {"no", "not", "can't", "cannot", "won't", "unable", "unlikely", "never"}
        cleaned_lower = cleaned.lower()
        pos_score = sum(1 for w in positive_words if w in cleaned_lower)
        neg_score = sum(1 for w in negative_words if w in cleaned_lower)
        if pos_score > neg_score:
            return "Yes"
    return cleaned


def _normalize_label(label: str) -> str:
    """Strip section number prefix and normalize whitespace for fuzzy matching."""
    text = re.sub(r'^\d+(\.\d+)*\s+', '', label)
    text = re.sub(r'\s*/\s*', '/', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _build_creator_payload(result: dict) -> dict:
    """Build a Zoho Creator PATCH payload from OCR result fields.

    Handles four field categories:
      1. Table rows          → subform record arrays
      2. Checkbox aggregates → STRINGLIST or comma-separated text
      3. Flat-to-subform     → single-row subform records
      4. Direct mapping      → simple field values
    """
    fields = result.get("fields", [])
    if not fields:
        return {}

    payload: dict[str, Any] = {}
    aggregates: dict[str, list[str]] = {}
    subform_rows: dict[str, dict[int, dict[str, str]]] = {}
    flat_subform_buffers: dict[str, dict[str, str]] = {}

    # Pre-build prefix list for fast aggregate matching
    agg_prefixes = sorted(AGGREGATE_MAP, key=len, reverse=True)

    for f in fields:
        label = f.get("label", "")
        value = f.get("value", "")
        if not label:
            continue
        if value in ("nil", "—"):
            value = ""

        # 1) Table row: "Table — Row N — Column"
        m = _SUBROW_RE.match(label)
        if m:
            table_name = m.group(1).strip()
            row_num = int(m.group(2))
            col_name = m.group(3).strip()
            table_info = TABLE_TO_SUBFORM.get(table_name)
            if table_info:
                sk = table_info["subform"]
                col_map = table_info["columns"]
                zoho_col = col_map.get(col_name)
                if zoho_col:
                    subform_rows.setdefault(sk, {})
                    subform_rows[sk].setdefault(row_num, {})
                    sanitized_val = _sanitize_value(value, zoho_col)
                    if sk == "Family_Members_Table" and zoho_col == "Name":
                        # If Name is composite, structure it with first_name and last_name
                        subform_rows[sk][row_num][zoho_col] = {
                            "first_name": sanitized_val,
                            "last_name": ""
                        }
                    else:
                        subform_rows[sk][row_num][zoho_col] = sanitized_val
            continue

        # 2) Aggregate: prefix with trailing " — "
        matched_agg = False
        for prefix in agg_prefixes:
            if label.startswith(prefix + " — "):
                option = label[len(prefix) + 3:]
                if option and value in ("✓", "1", "yes", "Yes", "true", "True", "Y", "y"):
                    aggregates.setdefault(prefix, []).append(option)
                matched_agg = True
                break
        if matched_agg:
            continue

        # 3) Flat-to-subform
        matched_flat = False
        for sf_prefix, sf_info in FLAT_TO_SUBFORM_MAP.items():
            if label.startswith(sf_prefix + " — "):
                col_part = label[len(sf_prefix) + 3:]
                zoho_col = sf_info["columns"].get(col_part)
                if zoho_col:
                    sk = sf_info["subform"]
                    flat_subform_buffers.setdefault(sk, {})
                    flat_subform_buffers[sk][zoho_col] = _sanitize_value(value, zoho_col)
                matched_flat = True
                break
        if matched_flat:
            continue

        # 4) Direct mapping
        zoho_field = FIELD_TO_ZOHO.get(label)
        if not zoho_field:
            normalized_label = _normalize_label(label)
            for fk, fv in FIELD_TO_ZOHO.items():
                if normalized_label == _normalize_label(fk):
                    zoho_field = fv
                    break
        if zoho_field:
            # Dedup: skip empty value if a non-empty one is already set (handles cross-page duplicates)
            sanitized = _sanitize_value(value, zoho_field)
            if not sanitized:
                existing = payload.get(zoho_field)
                if existing and existing not in ("", None, [], {}):
                    continue  # keep the non-empty value
            if zoho_field in ZOHO_STRINGLIST_FIELDS:
                if sanitized:
                    payload[zoho_field] = [sanitized]
                continue
            elif zoho_field in ZOHO_BOOLEAN_FIELDS:
                if sanitized not in ("Yes", "No"):
                    if sanitized:
                        logger.warning("Skipping boolean field %s: unexpected value %r", zoho_field, value)
                    continue
                payload[zoho_field] = sanitized
            else:
                payload[zoho_field] = sanitized
        else:
            # Suppress warning for known table parents & aggregate prefixes (they are handled structurally)
            if label not in TABLE_TO_SUBFORM and not any(label.startswith(p) for p in AGGREGATE_MAP):
                logger.warning("Zoho mapping: no match for label %r (value=%r)", label, value)

    # Flush aggregates
    for prefix, info in AGGREGATE_MAP.items():
        if prefix in aggregates:
            target = info["target"]
            options = aggregates[prefix]
            if info.get("type") == "stringlist":
                payload[target] = sorted(options)
            else:
                payload[target] = ", ".join(sorted(options))
        elif target := info.get("target"):
            # If no individual options but a flat fallback was set via direct mapping,
            # convert STRINGLIST flat value to array
            if target in ZOHO_STRINGLIST_FIELDS and target in payload:
                existing = payload[target]
                if isinstance(existing, str):
                    payload[target] = [existing]

    # Flush table subform rows
    for sk, rows in subform_rows.items():
        sorted_rows = [rows[n] for n in sorted(rows)]
        required = SUBFORM_REQUIRED_COLUMNS.get(sk, set())
        # Make required columns dynamic: only enforce columns that exist in at least one row
        populated_cols: set[str] = set()
        for r in sorted_rows:
            for c, v in r.items():
                if isinstance(v, dict):
                    if any(v.values()):
                        populated_cols.add(c)
                elif v:
                    populated_cols.add(c)
        if required:
            required = required & populated_cols  # only require what's actually populated
            def has_val(r, col):
                val = r.get(col)
                if isinstance(val, dict):
                    return any(val.values())
                return bool(val)
            sorted_rows = [r for r in sorted_rows if all(has_val(r, c) for c in required)]
        # Drop rows where all values are N/A or empty (conditional subform tables with parent="No")
        sorted_rows = [
            r for r in sorted_rows
            if any(v not in ("N/A", "", None, 0, 0.0) for v in (r.values() if isinstance(r, dict) else []))
        ]
        if sorted_rows:
            payload[sk] = sorted_rows

    # Flush flat-to-subform rows
    for sk, cols in flat_subform_buffers.items():
        required = SUBFORM_REQUIRED_COLUMNS.get(sk)
        if required and not all(cols.get(c) for c in required):
            continue
        payload[sk] = [cols]

    return payload


def _update_zoho_creator_fields(
    access_token: str,
    req: OcrExtractRequest,
    result: dict,
) -> None:
    """POST extracted field values as a new row in Home_Visit_Questionnaire."""
    payload = _build_creator_payload(result)
    # Application_ID is a lookup field — OCR extracts the display name which Zoho rejects.
    # Only set it from the request's numeric lookup ID; strip any OCR-derived value otherwise.
    payload.pop("Application_ID", None)
    if req.application_id:
        payload["Application_ID"] = req.application_id
        logger.info("application_id=%s injected into Creator payload | record=%s", req.application_id, req.record_id)
    else:
        logger.warning("No application_id on request — Application_ID omitted (lookup field) | record=%s", req.record_id)
    if not payload:
        print(f"\n{'='*80}")
        print(f"  ZOHO CREATOR UPDATE: No fields to write | record={req.record_id}")
        print(f"{'='*80}\n")
        logger.info("No fields to write to Home_Visit_Questionnaire | record=%s", req.record_id)
        return

    simple_count = sum(1 for v in payload.values() if not isinstance(v, list))
    subform_count = sum(1 for v in payload.values() if isinstance(v, list))

    simple_keys = [k for k, v in payload.items() if not isinstance(v, list)]
    table_items = [(k, len(v)) for k, v in payload.items() if isinstance(v, list) and v and isinstance(v[0], dict)]
    multi_items = [(k, v) for k, v in payload.items() if isinstance(v, list) and (not v or not isinstance(v[0], dict))]

    print(f"\n{'='*80}")
    print(f"  ZOHO CREATOR UPDATE | record={req.record_id}")
    print(f"  Target: {req.questionnaire_report_link_name}  |  {len(payload)} fields  |  {simple_count} simple + {subform_count} subform")
    print(f"{'─'*80}")
    if simple_keys:
        print(f"  Simple: {', '.join(simple_keys)}")
    for name, count in table_items:
        print(f"  Table:  {name} ({count} rows)")
    for name, vals in multi_items:
        display = ", ".join(str(x) for x in vals) if vals else "(empty)"
        print(f"  List:   {name}: [{display}]")
    print(f"{'─'*80}")

    logger.info(
        "Writing %d fields to Home_Visit_Questionnaire | record=%s",
        len(payload), req.record_id,
    )

    # Zoho Creator v2.1: POST to /form/{form_link_name} to add a record.
    # Using /report/ returns HTTP 405 — reports are read-only views.
    url = (f"https://www.zohoapis.com/creator/v2.1/data/{req.zoho_app_owner}/"
           f"{req.zoho_app_link_name}/form/{req.questionnaire_form_link_name}")
    data = json.dumps({"data": payload}).encode()
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }
    request = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        try:
            with _urlopen_with_retry(request, timeout=30) as resp:
                body = resp.read().decode()
        except urllib.error.HTTPError as e:
            if e.code == 401:
                logger.info("Got HTTP 401 on Creator POST; invalidating token cache and retrying...")
                with _TOKEN_LOCK:
                    _TOKEN_CACHE["token"] = None
                fresh_token = _get_zoho_access_token()
                request.remove_header("Authorization")
                request.add_header("Authorization", f"Zoho-oauthtoken {fresh_token}")
                with _urlopen_with_retry(request, timeout=30) as resp:
                    body = resp.read().decode()
            else:
                raise
        result = json.loads(body)
        code = result.get("code", 3000)
        if code not in (2000, 3000):
            err_msg = result.get("error", str(result))
            err_full = result.get("message", "")
            raise RuntimeError(
                f"Zoho Creator POST failed (code={code}): {err_msg} | message={err_full} | "
                f"full_body={body[:1000]}"
            )
        logger.info("Creator POST response | record=%s | status=200 | body=%s", req.record_id, body[:500])
        print(f"  ✓ POST 200 — Creator response: {body[:200]}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        logger.error("Creator POST failed | record=%s | status=%s | body=%s",
            req.record_id, e.code, body[:500])
        print(f"  ✗ POST {e.code} — {body[:200]}")
        raise
    print(f"  ✓ New row created in {req.questionnaire_form_link_name}")
    print(f"{'='*80}\n")


def _merge_to_pdf(file_paths: list[Path], output_path: Path) -> None:
    import fitz
    merged = fitz.open()
    for fp in file_paths:
        ext = fp.suffix.lower()
        try:
            if ext in ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tiff', '.tif'):
                img_doc = fitz.open(fp)
                pdfbytes = img_doc.convert_to_pdf()
                img_doc.close()
                src = fitz.open("pdf", pdfbytes)
            elif ext == '.pdf':
                src = fitz.open(fp)
            else:
                logger.warning("Skipping unsupported file: %s", fp.name)
                continue
            merged.insert_pdf(src)
            src.close()
        except Exception as e:
            logger.warning("Failed to merge %s: %s", fp.name, e)
    merged.save(str(output_path))
    merged.close()


async def _download_and_prepare(job_dir: Path, req: OcrExtractRequest) -> str | None:
    """Download, merge, and upload to Supabase.

    Returns the Zoho access token on success (for later use in
    ``_run_pipeline_only``), or ``None`` on failure.
    """
    dl_t0 = time.time()
    rid = req.record_id
    app_id = req.application_id or ""
    aid = f"  [app={app_id}]" if app_id else ""
    logger.info("Download-prepare started | record=%s | files=%d%s", rid, len(req.file_names), aid)
    await _set_status(job_dir, "oauth", f"Downloading for {rid}")

    try:
        await _set_status(job_dir, "oauth", "Zoho OAuth...")
        loop = asyncio.get_running_loop()
        access_token = await loop.run_in_executor(None, _get_zoho_access_token)
        _t_oauth = time.time() - dl_t0
        logger.info("Zoho OAuth token acquired (%.1fs)", _t_oauth)

        download_dir = job_dir / "downloads"
        download_dir.mkdir(exist_ok=True)
        downloaded: list[Path] = []

        def _download_one(idx_and_name):
            i, file_name = idx_and_name
            logger.info("Downloading file %d/%d: %s", i+1, len(req.file_names), file_name)
            file_bytes = _download_zoho_file(access_token, req, file_name)
            local_path = download_dir / f"{i}_{file_name}"
            local_path.write_bytes(file_bytes)
            logger.info("Downloaded %s (%d bytes)", file_name, len(file_bytes))
            return i, local_path

        await _set_status(job_dir, "downloading", f"Downloading {len(req.file_names)} files...")
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=min(len(req.file_names), 6)) as dl_pool:
            futures = {dl_pool.submit(_download_one, (i, fn)): fn for i, fn in enumerate(req.file_names)}
            results_map: dict[int, Path] = {}
            for future in as_completed(futures):
                fn = futures[future]
                try:
                    idx, local_path = future.result()
                    results_map[idx] = local_path
                except Exception as e:
                    msg = f"Download failed for {fn}: {e}"
                    logger.error(msg)
                    await _set_status(job_dir, "error", msg)
                    return None
        downloaded = [results_map[i] for i in sorted(results_map)]

        _t_dl = time.time() - dl_t0
        logger.info("All %d files downloaded (%.1fs)", len(downloaded), _t_dl)
        await _set_status(job_dir, "downloading", f"Downloaded {len(downloaded)} files")

        combined_pdf = job_dir / "combined.pdf"
        await _set_status(job_dir, "converting", "Converting to single PDF...")
        await loop.run_in_executor(None, _merge_to_pdf, downloaded, combined_pdf)
        pdf_size = combined_pdf.stat().st_size
        import fitz as _fitz
        _page_count = _fitz.open(str(combined_pdf)).page_count
        if _page_count == 0:
            raise RuntimeError(f"Merged PDF has 0 pages — all input files may be unsupported or corrupt")
        _t_total_dl = time.time() - dl_t0
        logger.info("Merged PDF created (%d pages, %.0f KB from %d files) [%.1fs]", _page_count, pdf_size / 1024, len(downloaded), _t_total_dl)
        await _set_status(job_dir, "converting", f"PDF created ({_page_count} pages, {pdf_size/1024:.0f} KB)")

        input_pdf = job_dir / "input.pdf"
        combined_pdf.rename(input_pdf)
        logger.info("Download-prepare done | record=%s%s (%.1fs)", rid, aid, _t_total_dl)
        return access_token

    except Exception as e:
        logger.exception("Download-prepare failed | record=%s%s", rid, aid)
        await _set_status(job_dir, "error", f"Download/prepare failed: {e}")
        print(f"  ✗ Download-prepare failed for {rid}{aid}: {e}")
        return None


async def _run_ocr_extract_pipeline(job_dir: Path, req: OcrExtractRequest) -> bool:
    """Combined wrapper used by the server endpoint.

    Calls download-prepare then pipeline-only sequentially.
    The startup poller uses the split functions directly for overlap.
    """
    rid = req.zoho_record_id
    if rid in _ACTIVE_ZOHO_RECORDS:
        logger.info("Record %s is already processing (duplicate request ignored)", rid)
        return False
    _ACTIVE_ZOHO_RECORDS.add(rid)
    try:
        token = await _download_and_prepare(job_dir, req)
        if token:
            return await _run_pipeline_only(job_dir, req, token)
        return False
    finally:
        _ACTIVE_ZOHO_RECORDS.discard(rid)


async def _run_pipeline_only(job_dir: Path, req: OcrExtractRequest, access_token: str) -> bool:
    """Run extraction pipeline from existing ``input.pdf``, write to Creator.

    Returns ``True`` if the pipeline completed with extraction results,
    ``False`` otherwise.  On failure ``OCR_Status`` in Creator is set to
    ``"failed"`` so the record can be retried.
    """
    _pt: dict[str, float] = {}
    _tick = time.time()
    t0 = _tick
    rid = req.record_id
    app_id = req.application_id or ""
    aid = f"  [app={app_id}]" if app_id else ""
    logger.info("Pipeline-only started | record=%s%s", rid, aid)

    try:
        loop = asyncio.get_running_loop()
        input_pdf = job_dir / "input.pdf"
        if not input_pdf.exists():
            logger.error("input.pdf missing | record=%s%s", rid, aid)
            return False

        await _set_status(job_dir, "pipeline_start", "Starting extraction pipeline...")
        logger.info("Starting extraction pipeline...")
        await run_pipeline(job_dir, str(input_pdf))
        _pt["pipeline"] = time.time() - _tick
        _tick = time.time()

        result_path = job_dir / "results" / "result.json"
        ocr_result = None
        if result_path.exists():
            with open(result_path) as _f:
                ocr_result = json.load(_f)
            ocr_result["application_id"] = req.application_id
            ocr_result["record_id"] = req.record_id
            with open(result_path, "w") as _f:
                json.dump(ocr_result, _f, indent=2)

        pipeline_ok = ocr_result is not None

        if ocr_result:
            # ── Steps 1 & 2: POST fields + Supabase upload (parallel I/O) ──
            creator_fields_ok = False
            supabase_ok = False
            await _set_status(job_dir, "zoho_fields", "Writing fields to Creator + Supabase upload...")

            async def _do_zoho():
                nonlocal creator_fields_ok
                _zs = time.time()
                await loop.run_in_executor(
                    None, _update_zoho_creator_fields, access_token, req, ocr_result,
                )
                creator_fields_ok = True
                _pt["zoho_fields"] = time.time() - _zs
                logger.info("Home_Visit_Questionnaire fields updated | record=%s%s (%.1fs)", rid, aid, _pt["zoho_fields"])

            async def _do_supabase():
                nonlocal supabase_ok
                _ss = time.time()
                input_pdf_bytes = input_pdf.read_bytes()
                supabase_path = f"{req.record_id}/{req.record_id}.pdf"
                await loop.run_in_executor(
                    None, _upload_to_supabase, req.bucket, supabase_path,
                    input_pdf_bytes, "application/pdf",
                )
                supabase_ok = True
                _pt["supabase"] = time.time() - _ss
                logger.info("Supabase upload complete | record=%s%s (%.1fs)", rid, aid, _pt["supabase"])

            sb_task = asyncio.create_task(_do_supabase())
            zoho_task = asyncio.create_task(_do_zoho())

            for label, task in [
                ("Zoho Creator", zoho_task),
                ("Supabase upload", sb_task),
            ]:
                try:
                    await task
                    print(f"  ✓ {label} for {rid}{aid}")
                except Exception as e:
                    logger.error("%s failed | record=%s | error=%s%s", label, rid, e, aid)
                    print(f"  ⚠ {label} failed for {rid}{aid}: {e}")

            # ── Step 3: Update OCR_Status based on combined outcome ──
            status_to_set = "updated"
            status_msg = "OCR complete — Zoho record updated"
            if not creator_fields_ok and not supabase_ok:
                status_to_set = "failed"
                status_msg = "OCR complete but both Creator and Supabase writes failed"
            elif not creator_fields_ok:
                status_msg = "OCR complete — PDF on Supabase, Creator fields POST failed"
            elif not supabase_ok:
                status_msg = "OCR complete — Creator fields written, Supabase upload failed"

            await _set_status(job_dir, "zoho_update", f"Setting OCR_Status={status_to_set}...")
            try:
                await loop.run_in_executor(
                    None, _update_zoho_creator, access_token, req, status_to_set,
                )
                _pt["ocr_status"] = time.time() - _tick
                _tick = time.time()
                logger.info("Zoho Creator OCR_Status=%s | record=%s%s",
                    status_to_set, rid, aid)
                print(f"  ✓ OCR_Status set to '{status_to_set}' for {rid}{aid}")
                await _set_status(job_dir, "done", status_msg)
            except Exception as zoho_err:
                logger.error("Zoho Creator OCR_Status update failed | record=%s | error=%s%s",
                    rid, zoho_err, aid)
                print(f"  ⚠ OCR_Status update failed for {rid}{aid}: {zoho_err}")
                await _set_status(job_dir, "done",
                    f"Pipeline done but OCR_Status update failed: {zoho_err}")
        else:
            await _set_status(job_dir, "zoho_update", "Marking record as failed...")
            try:
                await loop.run_in_executor(None, _update_zoho_creator, access_token, req, "failed")
                logger.info("Zoho Creator OCR_Status=failed | record=%s%s", rid, aid)
                print(f"  ✗ OCR_Status set to 'failed' for {rid}{aid}")
            except Exception as zoho_err:
                logger.error("Zoho Creator status=failed update error | record=%s | error=%s%s",
                    rid, zoho_err, aid)
            await _set_status(job_dir, "error", "OCR pipeline failed — status set to failed")

        logger.info(
            "PIPELINE TIMING | pipeline=%.1fs zoho_fields=%.1fs supabase=%.1fs ocr_status=%.1fs total=%.1fs  |  %s",
            _pt.get("pipeline", 0), _pt.get("zoho_fields", 0),
            _pt.get("supabase", 0), _pt.get("ocr_status", 0),
            time.time() - t0, rid,
        )

        elapsed = round(time.time() - t0, 1)

        # ── Per-PDF summary ──
        total_tokens = 0
        prompt_tokens = 0
        completion_tokens = 0
        llm_calls = 0
        fields_count = 0
        overall_conf = 0
        if ocr_result:
            tu = ocr_result.get("token_usage", {})
            total_info = tu.get("total", {})
            prompt_tokens = total_info.get("prompt_tokens", 0)
            completion_tokens = total_info.get("completion_tokens", 0)
            total_tokens = total_info.get("total_tokens", 0)
            llm_calls = ocr_result.get("llm_calls", 0)
            fields_count = len(ocr_result.get("fields", []))
            overall_conf = ocr_result.get("overall_confidence", 0)

        print(f"\n  {'='*56}")
        print(f"   SUMMARY  ─  {rid}{aid}")
        print(f"  {'─'*56}")
        print(f"   App name          : {rid}")
        print(f"   Fields extracted  : {fields_count}")
        print(f"   Overall confidence: {overall_conf}%")
        print(f"   LLM calls         : {llm_calls}")
        print(f"   Prompt tokens     : {prompt_tokens:,}")
        print(f"   Completion tokens : {completion_tokens:,}")
        print(f"   Total tokens      : {total_tokens:,}")
        print(f"   Processing time   : {elapsed}s")
        print(f"  {'='*56}\n")

        return pipeline_ok

    except Exception as e:
        logger.exception("Pipeline-only failed | record=%s%s", rid, aid)
        await _set_status(job_dir, "error", f"OCR extract failed: {e}")
        print(f"  ✗ Pipeline failed for {rid}{aid}: {e}")
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _update_zoho_creator, access_token, req, "failed")
        except Exception:
            pass
        return False
    finally:
        elapsed = round(time.time() - t0, 1)
        logger.info("Pipeline-only finished | record=%s | elapsed=%ds%s", rid, elapsed, aid)


# ── Startup poller ────────────────────────────────────────────────

def _fetch_creator_records(
    access_token: str,
    app_owner: str,
    app_link_name: str,
    report_link_name: str,
    criteria: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Fetch records from a Zoho Creator report matching criteria.

    Creator v2.1 returns up to ``limit`` records (max 200).
    Pagination via ``page`` is not supported on this endpoint,
    so a single batch is returned.
    """
    params = {"limit": str(limit)}
    if criteria:
        params["criteria"] = criteria
    url = (f"https://www.zohoapis.com/creator/v2.1/data/{app_owner}/"
           f"{app_link_name}/report/{report_link_name}?"
           + urllib.parse.urlencode(params))
    request = urllib.request.Request(
        url, headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        # Zoho Creator v2.1 returns HTTP 400 / code 9280 when no records match criteria
        if "9280" in body:
            logger.info("No records found matching criteria: %s", criteria)
            return []
        try:
            err_data = json.loads(body)
            if err_data.get("code") == 9280:
                logger.info("No records found matching criteria: %s", criteria)
                return []
        except Exception:
            pass
        logger.error("_fetch_creator_records HTTP %d: %s", e.code, body[:300])
        raise
    return result.get("data", [])


def _extract_file_names(record: dict, file_field_link_name: str) -> list[str]:
    """Safely extract sorted file names from a Creator record's file-upload field.

    Zoho Creator v2.1 report API returns file-upload entries as an array of
    download-URL strings, e.g. ``"/api/v2.1/.../download?filepath=name.pdf"``.
    This function also handles objects with ``name`` or ``download_url`` keys
    and bare filename strings.
    """
    files = record.get(file_field_link_name)
    if not isinstance(files, list):
        return []
    from urllib.parse import urlparse, parse_qs
    names: list[str] = []
    for f in files:
        if isinstance(f, dict):
            name = f.get("name")
            if isinstance(name, str) and name:
                names.append(name)
                continue
            url = f.get("download_url", "")
            if isinstance(url, str) and url:
                qs = parse_qs(urlparse(url).query)
                fp = qs.get("filepath", [None])[0]
                if fp:
                    names.append(fp)
                    continue
        elif isinstance(f, str) and f:
            qs = parse_qs(urlparse(f).query)
            fp = qs.get("filepath", [None])[0]
            if fp:
                names.append(fp)
            else:
                names.append(f)
    if not names:
        logger.warning("_extract_file_names: no names in field=%s raw=%s",
                       file_field_link_name, str(files)[:400])
    return sorted(names)


async def process_pending_on_startup(base_dir: Path) -> None:
    """One-shot on startup: fetch Creator records with OCR_Status=null and process each."""
    import uuid as _uuid

    app_owner = os.environ.get("ZOHO_POLL_APP_OWNER", "teameverest")
    app_link_name = os.environ.get("ZOHO_POLL_APP_LINK_NAME", "iatc-selection-one-app")
    report_link_name = os.environ.get("ZOHO_POLL_REPORT_LINK_NAME", "Volunteer_Home_Visited_Form_Report")
    file_field_link_name = os.environ.get("ZOHO_POLL_FILE_FIELD_LINK_NAME", "Upload_Home_Visit_Form")
    max_concurrent = int(os.environ.get("ZOHO_POLL_MAX_CONCURRENT", "10"))
    criteria = os.environ.get("ZOHO_POLL_CRITERIA",'(OCR_Status=="yes")')
                            #   '(OCR_Status==null || OCR_Status=="") && OCR_Status!="updated"')

    print(f"\n{'='*70}")
    print(f"  STARTUP AUTO-PROCESSOR")
    print(f"{'─'*70}")
    print(f"  Target:    {app_owner}/{app_link_name}")
    print(f"  Report:    {report_link_name}")
    print(f"  File field:{file_field_link_name}")
    print(f"  Criteria:  {criteria}")
    print(f"  Max conc:  {max_concurrent}")
    print(f"{'='*70}\n")
    logger.info("STARTUP: scanning for pending Creator records (criteria=%s)", criteria)

    loop = asyncio.get_running_loop()

    # 1. Authenticate
    try:
        access_token = await loop.run_in_executor(None, _get_zoho_access_token)
        print(f"  ✓ Zoho OAuth: token acquired\n")
    except Exception as e:
        print(f"  ✗ Zoho OAuth failed: {e}\n")
        logger.error("STARTUP: Zoho OAuth failed — %s", e)
        return

    # 2. Count total records in report (no filter) for context
    try:
        all_records = await loop.run_in_executor(
            None, _fetch_creator_records,
            access_token, app_owner, app_link_name, report_link_name, None,
        )
        total_in_report = len(all_records)
        print(f"  ✓ Report scan: {total_in_report} total record(s) in '{report_link_name}'")
    except Exception as e:
        print(f"  ✗ Report scan failed: {e}")
        logger.error("STARTUP: report scan failed — %s", e)
        total_in_report = -1

    # 3. Query pending records (with criteria)
    try:
        records = await loop.run_in_executor(
            None, _fetch_creator_records,
            access_token, app_owner, app_link_name, report_link_name, criteria,
        )
    except Exception as e:
        print(f"  ✗ Failed to fetch pending records: {e}\n")
        logger.error("STARTUP: failed to fetch Creator records — %s", e)
        return

    pending_count = len(records)
    print(f"  ✓ Pending query: {pending_count} record(s) with {criteria}")
    print(f"{'─'*70}\n")

    if not records:
        print(f"  No pending records to process.\n")
        logger.info("STARTUP: no pending records found")
        return

    # 4. Screen records for eligibility
    dl_sem = asyncio.Semaphore(max_concurrent)
    pipe_sem = asyncio.Semaphore(max_concurrent)
    in_progress: set[str] = set()
    tasks: list[asyncio.Task] = []
    skipped_no_id = 0
    skipped_no_file = 0
    skipped_dup = 0

    seq = 0
    for rec in records:
        zoho_record_id = rec.get("ID", "")
        if not zoho_record_id:
            skipped_no_id += 1
            continue
        if zoho_record_id in in_progress:
            skipped_dup += 1
            continue

        # Applicant_ID is a lookup field object in Creator response
        app_id_obj = rec.get("Applicant_ID") or {}
        if isinstance(app_id_obj, str):
            # Fallback if it is somehow a flat string
            record_id_raw = app_id_obj
            lookup_numeric_id = app_id_obj
        else:
            record_id_raw = str(app_id_obj.get("Applicant_ID") or "")
            lookup_numeric_id = str(app_id_obj.get("ID") or "")

        record_id = (record_id_raw
                     or rec.get("Student_Full_Name")
                     or zoho_record_id)

        file_names = _extract_file_names(rec, file_field_link_name)
        if not file_names:
            print(f"  ⚠ SKIP  {record_id}  — no files in '{file_field_link_name}'")
            logger.info("STARTUP: skip %s — no files in field '%s'",
                        record_id, file_field_link_name)
            skipped_no_file += 1
            continue

        seq += 1
        in_progress.add(zoho_record_id)

        req = OcrExtractRequest(
            record_id=str(record_id),
            zoho_app_owner=app_owner,
            zoho_app_link_name=app_link_name,
            zoho_report_link_name=report_link_name,
            zoho_record_id=zoho_record_id,
            file_field_link_name=file_field_link_name,
            file_names=file_names,
            application_id=lookup_numeric_id,
        )

        job_id = f"startup_{_uuid.uuid4().hex[:8]}"
        job_dir = base_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "original_name.txt").write_text(str(record_id))
        await _set_status(job_dir, "queued",
                          f"Auto: {record_id} ({len(file_names)} files)")

        app_str = f" [app={record_id_raw}]" if record_id_raw else ""
        print(f"  [#{seq}] ▶ QUEUE {record_id}  ({zoho_record_id})  [{len(file_names)} file(s)]{app_str}")
        logger.info("STARTUP: queued %s | zoho_id=%s | files=%d | job=%s%s",
                    record_id, zoho_record_id, len(file_names), job_id, app_str)

        async def _run_one(
            _job_dir: Path,
            _req: OcrExtractRequest,
            _dl_sem: asyncio.Semaphore,
            _pipe_sem: asyncio.Semaphore,
            _seq: int,
        ) -> None:
            _rec_id = _req.record_id
            _zoho_id = _req.zoho_record_id
            _app_id = _req.application_id or ""
            _aid_str = f" [app={_app_id}]" if _app_id else ""

            if _zoho_id in _ACTIVE_ZOHO_RECORDS:
                logger.info("Startup poller: skipping %s — already processing", _rec_id)
                print(f"  [#{_seq}] ⚠ SKIP  {_rec_id}{_aid_str} (already processing)")
                return

            _ACTIVE_ZOHO_RECORDS.add(_zoho_id)
            try:
                print(f"\n{'─'*60}")
                print(f"  [#{_seq}] START  {_rec_id}  ({len(_req.file_names)} files){_aid_str}")
                print(f"{'─'*60}")
                logger.info("STARTUP: processing %s (%d files)%s",
                            _rec_id, len(_req.file_names), _aid_str)

                # Phase 1 — download, merge, upload to Supabase (I/O bound)
                async with _dl_sem:
                    _token = await _download_and_prepare(_job_dir, _req)

                # Phase 2 — extraction pipeline, Creator fields write (CPU/LLM)
                if _token:
                    async with _pipe_sem:
                        _ok = await _run_pipeline_only(_job_dir, _req, _token)
                    if _ok:
                        print(f"  [#{_seq}] ✓ DONE  {_rec_id}{_aid_str}")
                        logger.info("STARTUP: success — %s%s", _rec_id, _aid_str)
                    else:
                        print(f"  [#{_seq}] ✗ FAIL  {_rec_id}{_aid_str}")
                        logger.warning("STARTUP: failed — %s%s", _rec_id, _aid_str)
                else:
                    print(f"  [#{_seq}] ✗ FAIL  {_rec_id}{_aid_str}  (download failed)")
                    logger.warning("STARTUP: download failed — %s%s", _rec_id, _aid_str)
            finally:
                _ACTIVE_ZOHO_RECORDS.discard(_zoho_id)

        tasks.append(asyncio.create_task(_run_one(job_dir, req, dl_sem, pipe_sem, seq)))

    # 5. Print eligibility summary
    total_eligible = len(tasks)
    print(f"\n{'='*70}")
    print(f"  ELIGIBILITY SUMMARY")
    print(f"{'─'*70}")
    print(f"  Total in report:     {total_in_report if total_in_report >= 0 else 'unknown'}")
    print(f"  Pending (criteria):  {pending_count}")
    print(f"  Skipped (no ID):     {skipped_no_id}")
    print(f"  Skipped (no file):   {skipped_no_file}")
    print(f"  Skipped (duplicate): {skipped_dup}")
    print(f"  → Eligible started:  {total_eligible}")
    print(f"{'='*70}\n")

    if not tasks:
        print(f"  Nothing to process.\n")
        return

    # 6. Wait for all to finish
    print(f"  Waiting for {len(tasks)} pipeline(s) to complete...\n")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    succeeded = sum(1 for r in results if r is None)
    failed = sum(1 for r in results if isinstance(r, Exception))

    print(f"\n{'='*70}")
    print(f"  STARTUP AUTO-PROCESSOR — COMPLETE")
    print(f"{'─'*70}")
    print(f"  Total eligible:   {total_eligible}")
    print(f"  ✓ Succeeded:      {succeeded}")
    print(f"  ✗ Failed:         {failed}")
    print(f"{'='*70}\n")
    logger.info("STARTUP: complete — %d succeeded, %d failed out of %d",
                succeeded, failed, len(tasks))
