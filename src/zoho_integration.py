import asyncio
import hashlib
import http.client
import json
import logging
import os
import re
import shutil
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
_COMPLETED_ZOHO_RECORDS: set[str] = set()
_TOKEN_LOCK = threading.Lock()
_PROCESSED_RECORDS_LOCK = threading.Lock()
_PROCESSED_RECORDS_PATH = Path(__file__).resolve().parent.parent / ".processed_records.json"


def _load_completed_records() -> set[str]:
    try:
        if _PROCESSED_RECORDS_PATH.exists():
            data = json.loads(_PROCESSED_RECORDS_PATH.read_text())
            if isinstance(data, list):
                return set(data)
    except Exception as e:
        logger.warning("Failed to load processed records from %s: %s", _PROCESSED_RECORDS_PATH, e)
    return set()


def _save_completed_records() -> None:
    try:
        with _PROCESSED_RECORDS_LOCK:
            _PROCESSED_RECORDS_PATH.write_text(json.dumps(list(_COMPLETED_ZOHO_RECORDS)))
    except Exception as e:
        logger.warning("Failed to save processed records: %s", e)


_COMPLETED_ZOHO_RECORDS = _load_completed_records()
if _COMPLETED_ZOHO_RECORDS:
    logger.info("Loaded %d completed records from persistent store", len(_COMPLETED_ZOHO_RECORDS))

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


async def _start_periodic_token_refresh() -> None:
    """Background task: refresh Zoho OAuth token every 58 minutes.

    The default Zoho token expiry is 3600 s (60 min).  We refresh at 3480 s
    (58 min) to stay well within the window and avoid HTTP 400 errors from
    stale tokens on concurrent requests.
    """
    loop = asyncio.get_running_loop()
    while True:
        try:
            await loop.run_in_executor(None, _get_zoho_access_token)
            logger.info("Periodic Zoho token refreshed (next in 58m)")
        except Exception as e:
            logger.warning("Periodic Zoho token refresh failed — %s", e)
        await asyncio.sleep(58 * 60)


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
    "2.4 Government ID Verified": {"target": "Government_ID_Verified_Ration_Card_Aadhaar_Driving_Licence_Voter_ID", "type": "stringlist"},
    "3.2 Type of Home": {"target": "Type_of_Home", "type": "text"},
    "3.3 Type of Ceiling": {"target": "Type_of_Ceiling", "type": "text"},
    "3.6 Kitchen Type": {"target": "Kitchen_Type", "type": "text"},
    "4.1 Assets at Home": {"target": "Assets_at_Home_tick_all_that_apply", "type": "stringlist"},
}

# Map extracted option names to exact values expected by Zoho Creator
# LLM may extract checkbox option text with variations (e.g. "Asbestos / Sheet" vs "Asbestos")
OPTION_VALUE_REPLACEMENTS: dict[str, str] = {
    # Type of Ceiling — Zoho options: Roof (Kurai), Tiled, Asbestos, Concrete
    "Roof": "Roof (Kurai)",
    "Asbestos / Sheet": "Asbestos",
    "Asbestos sheet": "Asbestos",
    "Asbestos Sheet": "Asbestos",
    "Asbestos ": "Asbestos",
    # Type of Home — Zoho options: Individual, Private Apartment, Housing Board, Line House, Others
    # Kitchen Type — Zoho options: Separate Kitchen, Hall with Kitchen
    # Assets at Home — no mapping needed (stringlist, all options valid)
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

# Fields that accept only specific enum values — any other value is rejected to avoid Creator validation errors
ZOHO_ENUM_FIELDS: dict[str, set[str]] = {
    "Gender": {"Male", "Female", "Others"},
    "Will_you_recommend_this_student_for_this_scholarship": {"Yes", "No", "Not Sure"},
}

# Fields that expect Yes/No values — reject any non-boolean value to avoid Creator validation errors
ZOHO_BOOLEAN_FIELDS: set[str] = {
    "Is_Father_Mother_photograph_kept_at_home",
    "Apart_from_your_job_is_there_any_other_source_of_income",
    "Do_you_have_any_loans",
    "Does_the_student_have_any_health_issues",
    "If_we_have_a_training_program_within_15_km_from_your_home_can_you_come1",
    "Are_you_ready_to_send_your_son_daughter_to_weekly_skill_development_classes_on_Sundays1",
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
_FLAT_TABLE_RE = re.compile(r'^(.+?) — (.+)$')  # "Table — Column" without Row N


def _sanitize_value(value: str, zoho_field: str) -> Any:
    """Coerce an OCR-extracted string value to the Zoho Creator field type."""
    if not value or value in ("nil", "N/A", "—"):
        return ""
    cleaned = value.strip()
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
    if zoho_field in ZOHO_ENUM_FIELDS:
        valid = ZOHO_ENUM_FIELDS[zoho_field]
        # Case-insensitive match
        for v in valid:
            if cleaned.lower() == v.lower():
                return v
        logger.warning("Rejecting value for enum field %s: %r (valid: %s)", zoho_field, cleaned, sorted(valid))
        return ""
    if cleaned.lower() == "yes":
        return "Yes"
    if cleaned.lower() == "no":
        return "No"
    return cleaned


def _normalize_label(label: str) -> str:
    """Strip section number prefix and normalize whitespace for fuzzy matching."""
    text = re.sub(r'^\d+(\.\d+)*\s+', '', label)
    text = re.sub(r'\s+/\s*', '/', text)
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
        if not label or not value:
            continue
        if value in ("", "nil", "N/A", "—"):
            continue

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

        # 1b) Flat table row: "Table — Column" (no Row N — LLM sometimes omits it)
        if not m:
            fm = _FLAT_TABLE_RE.match(label)
            if fm:
                table_name = fm.group(1).strip()
                col_name = fm.group(2).strip()
                table_info = TABLE_TO_SUBFORM.get(table_name)
                if table_info:
                    sk = table_info["subform"]
                    col_map = table_info["columns"]
                    # Try direct column name match first, then fuzzy match
                    zoho_col = col_map.get(col_name)
                    if zoho_col:
                        sanitized_val = _sanitize_value(value, zoho_col)
                        subform_rows.setdefault(sk, {})
                        subform_rows[sk].setdefault(1, {})
                        if sk == "Family_Members_Table" and zoho_col == "Name":
                            subform_rows[sk][1][zoho_col] = {
                                "first_name": sanitized_val,
                                "last_name": ""
                            }
                        else:
                            subform_rows[sk][1][zoho_col] = sanitized_val
                        continue

        # 2) Aggregate: prefix with trailing " — "
        matched_agg = False
        for prefix in agg_prefixes:
            if label.startswith(prefix + " — "):
                option = label[len(prefix) + 3:].strip()
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
            if zoho_field in ZOHO_STRINGLIST_FIELDS:
                payload[zoho_field] = [_sanitize_value(value, zoho_field)]
            elif zoho_field in ZOHO_BOOLEAN_FIELDS:
                sanitized = _sanitize_value(value, zoho_field)
                if sanitized not in ("Yes", "No"):
                    logger.warning("Skipping boolean field %s: unexpected value %r", zoho_field, value)
                    continue
                payload[zoho_field] = sanitized
            else:
                payload[zoho_field] = _sanitize_value(value, zoho_field)
        else:
            # Suppress warnings for table parent labels and aggregate prefixes
            # since their values are handled by the table/aggregate flows.
            is_table_parent = any(label == tk for tk in TABLE_TO_SUBFORM)
            is_agg_parent = any(label == ap for ap in AGGREGATE_MAP)
            if not is_table_parent and not is_agg_parent:
                logger.warning("Zoho mapping: no match for label %r (value=%r)", label, value)

    # Flush aggregates
    for prefix, info in AGGREGATE_MAP.items():
      if prefix in aggregates:
        target = info["target"]
        options = aggregates[prefix]
        if info.get("type") == "stringlist":
          payload[target] = [OPTION_VALUE_REPLACEMENTS.get(opt, opt) for opt in sorted(options)]
        elif options:
          val = sorted(options)[0]
          payload[target] = OPTION_VALUE_REPLACEMENTS.get(val, val)
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
        required = SUBFORM_REQUIRED_COLUMNS.get(sk)
        if required:
            # A column might be a string or a dict (for composite Name fields)
            def has_val(r, col):
                val = r.get(col)
                if isinstance(val, dict):
                    return any(val.values())
                return bool(val)
            sorted_rows = [r for r in sorted_rows if all(has_val(r, c) for c in required)]
        if sorted_rows:
            payload[sk] = sorted_rows

    # Flush flat-to-subform rows
    for sk, cols in flat_subform_buffers.items():
        required = SUBFORM_REQUIRED_COLUMNS.get(sk)
        if required and not all(cols.get(c) for c in required):
            continue
        payload[sk] = [cols]

    return payload


def _query_numeric_app_id_from_creator(
    access_token: str,
    app_owner: str,
    app_link_name: str,
    report_link_name: str,
    zoho_record_id: str,
) -> str | None:
    """Fetch the volunteer record directly by ID to resolve the parent numeric Applications ID."""
    try:
        url = (
            f"https://www.zohoapis.com/creator/v2.1/data/{app_owner}/{app_link_name}/"
            f"report/{report_link_name}/{zoho_record_id}"
        )
        headers = {
            "Authorization": f"Zoho-oauthtoken {access_token}",
            "Content-Type": "application/json",
        }
        request = urllib.request.Request(url, headers=headers, method='GET')
        with _urlopen_with_retry(request, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            record = data.get("data") or {}
            if record:
                # The linking field may be named 'Application_ID' or 'Applicant_ID'
                # depending on the Zoho Creator report configuration.
                for key in ("Application_ID", "Applicant_ID"):
                    app_id_obj = record.get(key) or {}
                    if isinstance(app_id_obj, dict):
                        num_id = str(app_id_obj.get("ID") or "")
                        if num_id.isdigit():
                            logger.info("Resolved Application_ID via field '%s': %s", key, num_id)
                            return num_id
                # Log what we actually got to help diagnose if neither key matches
                logger.warning("Application_ID lookup: field not found; record keys=%s", list(record.keys())[:20])
    except Exception as e:
        logger.warning("Failed to query numeric app ID by record ID %s: %s", zoho_record_id, e)
    return None


def _update_zoho_creator_fields(
    access_token: str,
    req: OcrExtractRequest,
    result: dict,
) -> None:
    """POST extracted field values as a new row in Home_Visit_Questionnaire."""
    payload = _build_creator_payload(result)
    # Application_ID is a lookup field that expects the numeric record ID
    # of the parent Applications record, NOT the display Applicant_ID string.
    # The lookup relationship is already established when the questionnaire
    # record was created — only re-set it when we have a numeric ID.
    payload_app_id = payload.pop("Application_ID", None)
    app_id = req.application_id or payload_app_id or result.get("application_id", "")
    if not app_id or not app_id.isdigit():
        logger.info("Resolving numeric Application_ID from Creator report using record ID %s...", req.zoho_record_id)
        resolved_id = _query_numeric_app_id_from_creator(
            access_token,
            req.zoho_app_owner,
            req.zoho_app_link_name,
            req.zoho_report_link_name,
            req.zoho_record_id
        )
        if resolved_id:
            app_id = resolved_id
            logger.info("Successfully resolved numeric Application_ID: %s", app_id)

    if app_id and app_id.isdigit():
        payload["Application_ID"] = app_id
        logger.info("Application_ID=%s set in Creator payload | record=%s",
                     app_id, req.record_id)
    else:
        logger.warning("Application_ID=%s is non-numeric or empty — omitted from payload | record=%s",
                        app_id or "(empty)", req.record_id)
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

    print(f"\n\033[95m\033[1m┌{'─'*78}┐\033[0m")
    print(f"\033[95m\033[1m│\033[0m  \033[1mZOHO CREATOR UPDATE\033[0m  •  record={req.record_id}")
    print(f"\033[95m\033[1m│\033[0m  Target: \033[1m{req.questionnaire_report_link_name}\033[0m  •  {len(payload)} fields ({simple_count} simple, {subform_count} subform)")
    print(f"\033[95m\033[1m├{'─'*78}┤\033[0m")
    if simple_keys:
        print(f"\033[95m\033[1m│\033[0m  \033[1mSimple fields:\033[0m {', '.join(simple_keys)}")
    for name, count in table_items:
        print(f"\033[95m\033[1m│\033[0m  \033[1mTable subform:\033[0m {name} ({count} rows)")
    for name, vals in multi_items:
        display = ", ".join(str(x) for x in vals) if vals else "(empty)"
        print(f"\033[95m\033[1m│\033[0m  \033[1mMulti-select list:\033[0m {name} -> \033[92m[{display}]\033[0m")
    print(f"\033[95m\033[1m└{'─'*78}┘\033[0m")

    # ── Verbose payload dump for debugging ────────────────────────────────
    logger.info("Creator PAYLOAD | record=%s | %d fields", req.record_id, len(payload))
    for pk, pv in sorted(payload.items()):
        if isinstance(pv, list):
            if pv and isinstance(pv[0], dict):
                logger.info("  PAYLOAD  %s (=%d subform rows)", pk, len(pv))
                for ri, row in enumerate(pv):
                    logger.info("    row[%d]: %s", ri, row)
            else:
                logger.info("  PAYLOAD  %s=[%s]", pk, ", ".join(str(x) for x in pv))
        else:
            logger.info("  PAYLOAD  %s=%r", pk, pv)
    # ───────────────────────────────────────────────────────────────────────

    logger.info(
        "Writing %d fields to Home_Visit_Questionnaire | record=%s",
        len(payload), req.record_id,
    )

    _post_creator_payload(access_token, req, payload)


def _post_creator_payload(
    access_token: str,
    req: OcrExtractRequest,
    payload: dict,
) -> None:
    """POST a pre-built payload dict to the Zoho Creator questionnaire form."""
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
                # Log the response body for diagnostic purposes
                _resp_body = e.read().decode()[:500] if hasattr(e, 'read') else str(e)[:500]
                logger.warning("Creator POST retry failed | record=%s | status=%s | body=%s",
                               req.record_id, e.code, _resp_body)
                raise
        result_data = json.loads(body)
        code = result_data.get("code", 3000)
        if code not in (2000, 3000):
            err_msg = result_data.get("error", str(result_data))
            err_full = result_data.get("message", "")

            # Self-healing fallback: prune fields with invalid values and retry once more
            if code == 3001 and isinstance(err_msg, list):
                import re
                invalid_fields = []
                for msg in err_msg:
                    m = re.search(r"Invalid column value for (\w+)", str(msg))
                    if m:
                        invalid_fields.append(m.group(1))
                if invalid_fields:
                    logger.warning(
                        "Creator rejected fields: %s. Pruning and retrying | record=%s",
                        invalid_fields, req.record_id
                    )
                    print(f"  ⚠ Omitting invalid fields and retrying: {invalid_fields}")
                    for f in invalid_fields:
                        payload.pop(f, None)
                    return _post_creator_payload(access_token, req, payload)

            # Build a field-level summary from the payload to help diagnose
            field_summary = ", ".join(
                f"{k}={repr(v)[:80]}" for k, v in payload.items()
                if not k.startswith("_")
            )
            raise RuntimeError(
                f"Zoho Creator rejected fields (code={code}): {err_msg} | "
                f"message={err_full} | "
                f"payload_fields=[{field_summary}] | "
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


IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tiff', '.tif'}


async def _download_and_prepare(job_dir: Path, req: OcrExtractRequest, output_name: str = "input") -> tuple[str | None, dict]:
    """Download files from Zoho.

    Returns (access_token, input_info) where input_info has:
        input_type: "pdf" | "images"
        pdf_path: str — path to PDF file (direct copy for single PDF, merged for images)
        image_paths: dict[int, str] | None — page→path for images input
        downloaded: list[str] — paths to original downloaded files
    On failure returns (None, {}).
    """
    rid = req.record_id
    app_id = req.application_id or ""
    aid = f"  [app={app_id}]" if app_id else ""
    logger.info("Download-prepare started | record=%s | files=%d%s", rid, len(req.file_names), aid)
    await _set_status(job_dir, "oauth", f"Downloading for {rid}")

    try:
        await _set_status(job_dir, "oauth", "Zoho OAuth...")
        loop = asyncio.get_running_loop()
        access_token = await loop.run_in_executor(None, _get_zoho_access_token)
        logger.info("Zoho OAuth token acquired")

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
                    msg = (
                        f"Download failed for '{fn}' from Zoho Creator "
                        f"(record={req.record_id}, file_field={req.file_field_link_name}, "
                        f"application_id={req.application_id or 'N/A'}): {e}"
                    )
                    logger.error(msg)
                    await _set_status(job_dir, "error", msg)
                    return None, {}
        downloaded = [results_map[i] for i in sorted(results_map)]

        logger.info("All %d files downloaded", len(downloaded))
        await _set_status(job_dir, "downloading", f"Downloaded {len(downloaded)} files")

        # Classify downloaded files
        pdf_files = [f for f in downloaded if f.suffix.lower() == '.pdf']
        image_files = [f for f in downloaded if f.suffix.lower() in IMAGE_EXTENSIONS]

        output_pdf = job_dir / f"{output_name}.pdf"

        if len(pdf_files) == 1 and not image_files:
            # Single PDF — use directly, no merge
            src = pdf_files[0]
            shutil.copy2(str(src), str(output_pdf))
            input_info = {
                "input_type": "pdf",
                "pdf_path": str(output_pdf),
                "image_paths": None,
                "downloaded": [str(p) for p in downloaded],
            }
            logger.info("Single PDF input | record=%s | pdf=%s", rid, src.name)
        else:
            # Images (or mixed) — still merge to PDF for pipeline compatibility
            combined_pdf = job_dir / f".{output_name}.tmp"
            await _set_status(job_dir, "converting", "Converting to single PDF...")
            await loop.run_in_executor(None, _merge_to_pdf, downloaded, combined_pdf)
            pdf_size = combined_pdf.stat().st_size
            import fitz as _fitz
            _page_count = _fitz.open(str(combined_pdf)).page_count
            if _page_count == 0:
                raise RuntimeError(f"Merged PDF has 0 pages — all input files may be unsupported or corrupt")
            logger.info("Merged PDF created (%d pages, %.0f KB from %d files)", _page_count, pdf_size / 1024, len(downloaded))
            await _set_status(job_dir, "converting", f"PDF created ({_page_count} pages, {pdf_size/1024:.0f} KB)")
            combined_pdf.rename(output_pdf)

            image_paths = {i+1: str(p) for i, p in enumerate(image_files)} if image_files else None
            input_info = {
                "input_type": "images",
                "pdf_path": str(output_pdf),
                "image_paths": image_paths,
                "downloaded": [str(p) for p in downloaded],
            }

        await _set_status(job_dir, "ready", f"Ready: {input_info['input_type']} ({len(downloaded)} file(s))")
        logger.info("Download-prepare done | record=%s | type=%s | files=%d%s",
                    rid, input_info["input_type"], len(downloaded), aid)
        return access_token, input_info

    except Exception as e:
        logger.exception("Download-prepare failed | record=%s | app=%s | files=%d%s",
                         rid, req.application_id, len(req.file_names), aid)
        await _set_status(job_dir, "error", f"Download/prepare failed: {e}")
        print(f"  ✗ Download-prepare failed for {rid}"
              f"{' (app=' + req.application_id + ')' if req.application_id else ''}: "
              f"could not fetch {len(req.file_names)} file(s) from Zoho — {e}")
        return None, {}


async def _run_ocr_extract_pipeline(job_dir: Path, req: OcrExtractRequest) -> bool:
    """Combined wrapper used by the server endpoint.

    Calls download-prepare then pipeline-only sequentially.
    The startup poller uses the split functions directly for overlap.
    """
    rid = req.zoho_record_id
    if rid in _ACTIVE_ZOHO_RECORDS:
        logger.info("Record %s is already processing (duplicate request ignored)", rid)
        return False
    if rid in _COMPLETED_ZOHO_RECORDS:
        logger.info("Record %s was already processed (persisted completion)", rid)
        return False
    _ACTIVE_ZOHO_RECORDS.add(rid)
    try:
        token, input_info = await _download_and_prepare(job_dir, req)
        if token:
            success = await _run_pipeline_only(job_dir, req, token, input_info)
            if success:
                _COMPLETED_ZOHO_RECORDS.add(rid)
                _save_completed_records()
            return success
        return False
    finally:
        _ACTIVE_ZOHO_RECORDS.discard(rid)


async def _run_pipeline_only(job_dir: Path, req: OcrExtractRequest, access_token: str, input_info: dict) -> bool:
    """Run extraction pipeline from downloaded files, write to Creator.

    Handles both PDF and image inputs. Uploads original downloaded files
    to Supabase (not the merged PDF).

    Returns ``True`` if the pipeline completed with extraction results,
    ``False`` otherwise.  On failure ``OCR_Status`` in Creator is set to
    ``"failed"`` so the record can be retried.
    """
    t0 = time.time()
    rid = req.record_id
    app_id = req.application_id or ""
    aid = f"  [app={app_id}]" if app_id else ""
    logger.info("Pipeline-only started | record=%s | type=%s%s", rid, input_info.get("input_type", "?"), aid)

    try:
        loop = asyncio.get_running_loop()
        pdf_path = input_info.get("pdf_path", "")
        if not pdf_path or not Path(pdf_path).exists():
            logger.error("Input PDF missing at %s | record=%s%s", pdf_path, rid, aid)
            return False

        input_type = input_info.get("input_type", "pdf")
        await _set_status(job_dir, "pipeline_start", f"Starting extraction pipeline ({input_type})...")
        logger.info("Starting extraction pipeline | record=%s | type=%s%s", rid, input_type, aid)

        if input_type == "images" and input_info.get("image_paths"):
            from src.pipeline_runner import run_image_pipeline
            await run_image_pipeline(job_dir, input_info["image_paths"])
        else:
            await run_pipeline(job_dir, pdf_path)

        result_path = job_dir / "results" / "result.json"
        ocr_result = None
        if result_path.exists():
            with open(result_path) as _f:
                ocr_result = json.load(_f)
            # Use extracted application_id from OCR if not provided in request
            extracted_app_id = ""
            for f in ocr_result.get("fields", []):
                if f.get("label") == "1.1 Application ID":
                    extracted_app_id = f.get("value", "")
                    break
            ocr_result["application_id"] = req.application_id or extracted_app_id or ""
            ocr_result["record_id"] = req.record_id
            with open(result_path, "w") as _f:
                json.dump(ocr_result, _f, indent=2)

        pipeline_ok = ocr_result is not None

        if ocr_result:
            app_identifier = ocr_result.get("application_id") or rid

            # ── Step 1: POST fields to Creator questionnaire ──
            creator_fields_ok = False
            await _set_status(job_dir, "zoho_fields", "Writing fields to Home_Visit_Questionnaire...")
            try:
                await loop.run_in_executor(
                    None, _update_zoho_creator_fields, access_token, req, ocr_result,
                )
                creator_fields_ok = True
                logger.info("Home_Visit_Questionnaire fields updated | record=%s%s", rid, aid)
                print(f"  ✓ Creator form updated for {rid}{aid}")
            except Exception as e:
                logger.error("Failed to update Questionnaire_Report | record=%s | error=%s%s",
                    rid, e, aid)
                print(f"  ⚠ Creator form update failed for {rid}{aid}: {e}")
                if "Invalid column value" in str(e):
                    print(f"    └─ Hint: check extracted field values match Zoho field types "
                          f"(enum, numeric, boolean). See PAYLOAD log above for field details.")

            # ── Step 2: Upload original files to Supabase (independent of Step 1) ──
            supabase_ok = True
            safe_name = app_identifier.replace(" ", "").replace("(", "_").replace(")", "_")
            for i, orig_path_str in enumerate(input_info.get("downloaded", []), 1):
                orig_path = Path(orig_path_str)
                if not orig_path.exists():
                    logger.warning("Supabase upload: file missing | path=%s", orig_path_str)
                    supabase_ok = False
                    continue
                is_pdf = orig_path.suffix.lower() == '.pdf'
                suffix = ".pdf" if is_pdf else f".img_{i}"
                content_type = "application/pdf" if is_pdf else "image/jpeg"
                supabase_path = f"{safe_name}/{safe_name}{suffix}"
                await _set_status(job_dir, "supabase_upload", f"Uploading {orig_path.name}...")
                try:
                    await loop.run_in_executor(
                        None, _upload_to_supabase, req.bucket, supabase_path,
                        orig_path.read_bytes(), content_type,
                    )
                    logger.info("Supabase upload: %s | record=%s", supabase_path, rid)
                except Exception as sb_err:
                    supabase_ok = False
                    logger.error("Supabase upload failed | path=%s | record=%s | error=%s",
                        supabase_path, rid, sb_err)
            if supabase_ok:
                print(f"  ✓ All files uploaded to Supabase | bucket={req.bucket} | record={rid}")
            else:
                print(f"  ⚠ Some Supabase uploads failed | bucket={req.bucket} | record={rid}")

            # ── Step 3: Update OCR_Status based on combined outcome ──
            status_to_set = "updated"
            status_msg = "OCR complete — Zoho record updated"
            if not creator_fields_ok and not supabase_ok:
                status_to_set = "null"
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
    max_concurrent = int(os.environ.get("ZOHO_POLL_MAX_CONCURRENT", "5"))
    criteria = os.environ.get("ZOHO_POLL_CRITERIA",
                               '(OCR_Status=="null" || OCR_Status=="no") && OCR_Status!="updated"')

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

    # Launch background token refresh (runs every 58 min independently)
    asyncio.create_task(_start_periodic_token_refresh())

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
    in_progress: set[str] = set()
    skipped_no_id = 0
    skipped_no_file = 0
    skipped_dup = 0
    eligible_requests = []

    seq = 0
    for rec in records:
        zoho_record_id = rec.get("ID", "")
        if not zoho_record_id:
            skipped_no_id += 1
            continue
        if zoho_record_id in in_progress:
            skipped_dup += 1
            continue

        app_id_obj = rec.get("Applicant_ID") or {}
        if isinstance(app_id_obj, str):
            record_id_raw = app_id_obj
            lookup_numeric_id = app_id_obj
        else:
            record_id_raw = str(app_id_obj.get("Applicant_ID") or "")
            lookup_numeric_id = str(app_id_obj.get("ID") or "")

        record_id = (record_id_raw or rec.get("Student_Full_Name") or zoho_record_id)
        file_names = _extract_file_names(rec, file_field_link_name)
        if not file_names:
            print(f"  ⚠ SKIP  {record_id}  — no files in '{file_field_link_name}'")
            logger.info("STARTUP: skip %s — no files in field '%s'", record_id, file_field_link_name)
            skipped_no_file += 1
            continue

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
        eligible_requests.append(req)

    total_eligible = len(eligible_requests)
    print(f"\n{'='*70}")
    print(f"  ELIGIBILITY SUMMARY")
    print(f"{'─'*70}")
    print(f"  Total in report:     {total_in_report if total_in_report >= 0 else 'unknown'}")
    print(f"  Pending (criteria):  {pending_count}")
    print(f"  Skipped (no ID):     {skipped_no_id}")
    print(f"  Skipped (no file):   {skipped_no_file}")
    print(f"  Skipped (duplicate): {skipped_dup}")
    print(f"  → Eligible to process:  {total_eligible}")
    print(f"{'='*70}\n")

    if not eligible_requests:
        print(f"  Nothing to process.\n")
        return

    # Create a single batch job directory
    from datetime import datetime
    batch_job_id = f"startup_batch_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    batch_job_dir = base_dir / batch_job_id
    batch_job_dir.mkdir(parents=True, exist_ok=True)
    (batch_job_dir / "original_name.txt").write_text(f"Startup Poll Batch ({total_eligible} records)")
    await _set_status(batch_job_dir, "queued", f"Auto-processing {total_eligible} records...")

    # Download in parallel
    print(f"  Downloading files for {total_eligible} record(s) into one batch folder...\n")
    
    async def _dl_one(rec_req, seq_num):
        output_name = f"{rec_req.record_id}"
        async with dl_sem:
            token, input_info = await _download_and_prepare(batch_job_dir, rec_req, output_name)
        return rec_req, token, input_info

    dl_tasks = [
        asyncio.create_task(_dl_one(req, i + 1))
        for i, req in enumerate(eligible_requests)
    ]
    dl_results = await asyncio.gather(*dl_tasks, return_exceptions=True)

    pdfs_info = []
    succeeded = 0
    failed = 0
    for r in dl_results:
        if isinstance(r, tuple) and len(r) >= 2 and r[1] is not None:
            rec_req, token, input_info = r
            output_name = f"{rec_req.record_id}"
            pdf_path = batch_job_dir / f"{output_name}.pdf"
            pdfs_info.append({
                "path": str(pdf_path.resolve()),
                "filename": f"{output_name}.pdf",
                "input_type": input_info.get("input_type", "pdf"),
                "input_info": input_info,
                "zoho_req": {
                    "record_id": rec_req.record_id,
                    "zoho_app_owner": rec_req.zoho_app_owner,
                    "zoho_app_link_name": rec_req.zoho_app_link_name,
                    "zoho_report_link_name": rec_req.zoho_report_link_name,
                    "zoho_record_id": rec_req.zoho_record_id,
                    "file_field_link_name": rec_req.file_field_link_name,
                    "file_names": rec_req.file_names,
                    "application_id": rec_req.application_id,
                }
            })
            succeeded += 1
        else:
            failed += 1

    print(f"  ✓ Downloads complete: {succeeded} succeeded, {failed} failed\n")
    if not pdfs_info:
        await _set_status(batch_job_dir, "error", "All record downloads failed.")
        return

    # Trigger batch pipeline
    print(f"  Starting batch pipeline run for {len(pdfs_info)} record(s)...\n")
    from src.pipeline_runner import run_batch_pdfs_pipeline
    # Put it in a background task so it updates SSE and progress stores properly, but await it
    await run_batch_pdfs_pipeline(batch_job_dir, pdfs_info)

    print(f"\n{'='*70}")
    print(f"  STARTUP AUTO-PROCESSOR — COMPLETE")
    print(f"{'─'*70}")
    print(f"  Single Batch Job ID: {batch_job_id}")
    print(f"  Total processed:     {len(pdfs_info)}")
    print(f"{'='*70}\n")
    logger.info("STARTUP: batch process complete | job=%s", batch_job_id)


async def run_zoho_writeback_for_batch_item(job_dir: Path, pdf_path: Path, zoho_req_dict: dict, ocr_result: dict, input_info: dict | None = None) -> None:
    """Invoked inside the pipeline runner after each PDF in a startup batch completes extraction."""
    import asyncio
    req = OcrExtractRequest(
        record_id=zoho_req_dict["record_id"],
        zoho_app_owner=zoho_req_dict["zoho_app_owner"],
        zoho_app_link_name=zoho_req_dict["zoho_app_link_name"],
        zoho_report_link_name=zoho_req_dict["zoho_report_link_name"],
        zoho_record_id=zoho_req_dict["zoho_record_id"],
        file_field_link_name=zoho_req_dict["file_field_link_name"],
        file_names=zoho_req_dict["file_names"],
        application_id=zoho_req_dict.get("application_id"),
    )

    loop = asyncio.get_running_loop()
    try:
        access_token = await loop.run_in_executor(None, _get_zoho_access_token)
    except Exception as e:
        logger.error("Failed to obtain Zoho access token for batch item write-back: %s", e)
        return

    rid = req.record_id
    app_id = req.application_id or ""
    aid = f"  [app={app_id}]" if app_id else ""

    extracted_app_id = ""
    for f in ocr_result.get("fields", []):
        if f.get("label") == "1.1 Application ID":
            extracted_app_id = f.get("value", "")
            break
    ocr_result["application_id"] = req.application_id or extracted_app_id or ""
    ocr_result["record_id"] = req.record_id

    app_identifier = ocr_result.get("application_id") or rid
    all_ok = True

    # 1. POST fields to Creator Home_Visit_Questionnaire
    try:
        await loop.run_in_executor(
            None, _update_zoho_creator_fields, access_token, req, ocr_result,
        )
        logger.info("Batch item Zoho fields updated | record=%s%s", rid, aid)
    except Exception as e:
        all_ok = False
        logger.error("Failed to update Questionnaire for batch item | record=%s | error=%s%s", rid, e, aid)

    # 2. Upload original files to Supabase
    safe_name = app_identifier.replace(" ", "").replace("(", "_").replace(")", "_")
    downloaded = (input_info or {}).get("downloaded", [])
    if not downloaded:
        # Fallback: upload the pipeline PDF as before
        try:
            supabase_path = f"{safe_name}/{safe_name}.pdf"
            await loop.run_in_executor(
                None, _upload_to_supabase, req.bucket, supabase_path,
                pdf_path.read_bytes(), "application/pdf",
            )
            logger.info("Batch item PDF uploaded to Supabase | record=%s%s", rid, aid)
        except Exception as e:
            all_ok = False
            logger.error("Failed to upload PDF to Supabase for batch item | record=%s | error=%s%s", rid, e, aid)
    else:
        for i, orig_path_str in enumerate(downloaded, 1):
            orig_path = Path(orig_path_str)
            if not orig_path.exists():
                logger.warning("Supabase upload: file missing | path=%s", orig_path_str)
                all_ok = False
                continue
            is_pdf = orig_path.suffix.lower() == '.pdf'
            suffix = ".pdf" if is_pdf else f".img_{i}"
            content_type = "application/pdf" if is_pdf else "image/jpeg"
            supabase_path = f"{safe_name}/{safe_name}{suffix}"
            try:
                await loop.run_in_executor(
                    None, _upload_to_supabase, req.bucket, supabase_path,
                    orig_path.read_bytes(), content_type,
                )
                logger.info("Batch item uploaded: %s | record=%s", supabase_path, rid)
            except Exception as e:
                all_ok = False
                logger.error("Supabase upload failed | path=%s | record=%s | error=%s", supabase_path, rid, e)

    # 3. Update OCR_Status to yes in Creator report
    try:
        payload = {"OCR_Status": "yes"}
        await loop.run_in_executor(
            None, _update_zoho_creator_fields, access_token, req, payload,
        )
        logger.info("Batch item OCR_Status updated | record=%s%s", rid, aid)
    except Exception as e:
        all_ok = False
        logger.error("Failed to update OCR_Status for batch item | record=%s | error=%s%s", rid, e, aid)

    if all_ok:
        _COMPLETED_ZOHO_RECORDS.add(req.zoho_record_id)
        _save_completed_records()
