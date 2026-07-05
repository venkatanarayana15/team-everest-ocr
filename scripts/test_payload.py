"""Build a synthetic OCR result with all field categories and print _build_creator_payload output.

Usage:
  uv run python scripts/test_payload.py          # dry-run only
  uv run python scripts/test_payload.py --live   # dry-run + POST to Zoho Creator
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.zoho_integration import _build_creator_payload


def build_synthetic_result() -> dict:
    return {
        "fields": [
            # ── Header (direct map) ──
            {"label": "Volunteer Name", "value": "R. Kumar"},
            {"label": "Co-Volunteer Name", "value": "S. Priya"},
            {"label": "Date of Visit", "value": "2026-06-15"},

            # ── Section 1 — Student Profile (direct map) ──
            {"label": "1.2 Student Full Name", "value": "Lakshmi Narayani"},
            {"label": "1.3 Gender", "value": "Female"},

            # ── Section 2 — Family Background ──
            {"label": "2.1 Family Status", "value": "Having both parents"},
            {"label": "2.3 Is Father/Mother photograph kept at home?", "value": "yes"},
            {"label": "2.4 Government ID Verified", "value": "Aadhaar Card"},

            # Flat subform: 2.2 Relationship Details -> Family_Background_Relationship
            {"label": "2.2 Relationship Details — Year of Death / Separation", "value": "2020"},
            {"label": "2.2 Relationship Details — Reason for Death / Separation", "value": "Illness"},

            # Table: 2.5 Family Members -> Family_Members_Table
            {"label": "2.5 Family Members — Row 1 — Name", "value": "V. Tanjabalam"},
            {"label": "2.5 Family Members — Row 1 — Age", "value": "47"},
            {"label": "2.5 Family Members — Row 1 — Education", "value": "10th"},
            {"label": "2.5 Family Members — Row 1 — Occupation", "value": "Farmer"},
            {"label": "2.5 Family Members — Row 1 — Annual Income", "value": "1,20,000"},
            {"label": "2.5 Family Members — Row 2 — Name", "value": "L. Vikram"},
            {"label": "2.5 Family Members — Row 3 — Name", "value": "V. Pooja"},
            {"label": "2.5 Family Members — Row 3 — Age", "value": "19"},

            # ── Section 3 — Housing Condition ──
            {"label": "3.1 House Ownership", "value": "Own"},
            {"label": "3.1.1 If rented, what is the rent amount?", "value": "N/A"},
            {"label": "3.4 Number of Bedrooms", "value": "2"},
            {"label": "3.4.1 Type of Bedroom", "value": "Separate Bedroom"},
            {"label": "3.5 Bathroom", "value": "Separate"},

            # Aggregates (text type)
            {"label": "3.2 Type of Home — Individual", "value": "✓"},
            {"label": "3.2 Type of Home — Private Apartment", "value": "✗"},
            {"label": "3.2 Type of Home — Housing Board", "value": "✓"},
            {"label": "3.3 Type of Ceiling — Concrete", "value": "✓"},
            {"label": "3.3 Type of Ceiling — Tiled", "value": "✗"},
            {"label": "3.6 Kitchen Type — Separate Kitchen", "value": "✓"},
            {"label": "3.6 Kitchen Type — Hall with Kitchen", "value": "✗"},

            # ── Section 4 — Financial Background ──
            {"label": "4.2 Amount of Last Electricity Bill", "value": "₹ 1,200.50"},
            {"label": "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student?", "value": "Yes"},
            {"label": "4.4 Apart from your job, is there any other source of income?", "value": "Yes"},
            {"label": "4.5 Income Type", "value": "Monthly"},
            {"label": "4.6 Do you have any loans?", "value": "Yes"},
            {"label": "4.7 If you choose any college, how much is the college fee?", "value": "1,50,000"},
            {"label": "4.8 If the college fee is higher, how will you manage it?", "value": "Education loan"},
            {"label": "4.9 If you do not receive this scholarship, how will you pay the fees?", "value": "Family support"},

            # Aggregate (stringlist type)
            {"label": "4.1 Assets at Home — Fridge", "value": "✓"},
            {"label": "4.1 Assets at Home — LED TV", "value": "✓"},
            {"label": "4.1 Assets at Home — Smartphone", "value": "✗"},

            # Table: 4.3.1 -> If_yes_list_their_properties_share
            {"label": "4.3.1 — Row 1 — Property Description", "value": "Agricultural land"},
            {"label": "4.3.1 — Row 1 — Owner Name", "value": "Grandfather"},
            {"label": "4.3.1 — Row 1 — Approximate Value", "value": "5,00,000"},

            # Table: 4.4.1 -> If_yes_list_other_sources_of_income
            {"label": "4.4.1 — Row 1 — Source of Income", "value": "Tailoring"},
            {"label": "4.4.1 — Row 1 — Amount", "value": "5,000"},
            {"label": "4.4.1 — Row 2 — Source of Income", "value": "Catering"},
            {"label": "4.4.1 — Row 2 — Amount", "value": "3,000"},

            # Table: 4.6.1 -> If_yes_share_the_Loan_Purpose_Amount_Taken_and_Pending_Loan_Amount
            {"label": "4.6.1 — Row 1 — Loan Purpose", "value": "Education"},
            {"label": "4.6.1 — Row 1 — Loan Amount Taken", "value": "2,00,000"},
            {"label": "4.6.1 — Row 1 — Pending Loan Amount", "value": "1,20,000"},
            {"label": "4.6.1 — Row 1 — Sr. No.", "value": "1"},

            # ── Section 5 — Health Information ──
            {"label": "5.1 Does the student have any health issues?", "value": "No"},
            {"label": "5.2 If yes, list the health issues", "value": "N/A"},

            # ── Section 6 — Student Commitment ──
            {"label": "6.1 Will you study college for three years without any obstacle?", "value": "Yes"},
            {"label": "6.2 If we have a training program within 15 km from your home, can you come?", "value": "yes"},
            {"label": "6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)?", "value": "Yes"},

            # ── Section 7 — Scholarship Information ──
            {"label": "7.1 Has the student received or applied for any other scholarships for their UG degree?", "value": "No"},

            # ── Section 8 — Volunteer Observation ──
            {"label": "8.1 What is your opinion about the student, their family members, and their living condition?", "value": "Good family, supportive"},
            {"label": "8.2 Will you recommend this student for this scholarship?", "value": "Yes"},
            {"label": "8.3 Any other comments you want to share?", "value": "Deserving student"},
        ]
    }


def print_summary(payload: dict) -> None:
    simple = sum(1 for v in payload.values() if not isinstance(v, list))
    subform_arrays = sum(1 for v in payload.values() if isinstance(v, list))
    print(f"\n─── SUMMARY ───")
    print(f"Total payload keys: {len(payload)}")
    print(f"  Simple fields: {simple}")
    print(f"  Subform/table arrays: {subform_arrays}")
    for k, v in payload.items():
        if isinstance(v, list):
            print(f"    {k}: {len(v)} row(s)")
    print(f"───────────────\n")


def main():
    parser = argparse.ArgumentParser(description="Test _build_creator_payload with synthetic data")
    parser.add_argument("--live", action="store_true", help="POST payload to Zoho Creator")
    args = parser.parse_args()

    result = build_synthetic_result()
    payload = _build_creator_payload(result)

    print(json.dumps(payload, indent=2, default=str))
    print_summary(payload)

    if args.live:
        from src.zoho_integration import (
            _get_zoho_access_token, _update_zoho_creator_fields, OcrExtractRequest,
        )

        req = OcrExtractRequest(
            record_id="TEMP-2026-8859",
            zoho_app_owner="teameverest",
            zoho_app_link_name="iatc-selection-one-app",
            zoho_report_link_name="Volunteer_Home_Visited_Form_Report",
            zoho_record_id="1782815779510802",
            file_field_link_name="Upload_Home_Visit_Form",
            file_names=[],
            applicat_id="TEMP-2026-8859",
        )
        token = _get_zoho_access_token()
        _update_zoho_creator_fields(token, req, result)


if __name__ == "__main__":
    main()
