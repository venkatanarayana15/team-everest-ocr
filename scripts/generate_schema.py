"""
Form Schema Definition - Python Version
Single source of truth for the 6-page Home Visit Questionnaire form.
All downstream artifacts (prompts, templates, Zoho mappings, DB columns, 
frontend types, validation schemas) are generated from this definition.
"""

import json
import os
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Optional

# ============================================================================
# TYPE DEFINITIONS
# ============================================================================

class FieldType(str, Enum):
    TEXT = "text"
    RADIO = "radio"
    CHECKBOX = "checkbox"
    TABLE_ROW = "table_row"
    TABLE_HEADER = "table_header"
    SPECIFY = "specify"

@dataclass
class FieldOption:
    label: str
    value: str

@dataclass
class TableColumn:
    name: str
    type: Literal["text", "numeric", "enum"] = "text"
    enum_values: List[str] = field(default_factory=list)

@dataclass
class TableDefinition:
    header_label: str
    columns: List[TableColumn]
    row_count: int
    blank_area_pages: List[int] = field(default_factory=list)

@dataclass
class FieldDefinition:
    label: str
    type: FieldType
    page: int
    section: Optional[int]
    
    # For radio/checkbox fields
    options: List[Dict[str, str]] = field(default_factory=list)
    mutually_exclusive_with: List[str] = field(default_factory=list)
    
    # For table rows
    table_header_label: Optional[str] = None
    row_index: Optional[int] = None
    column_name: Optional[str] = None
    
    # For specify fields
    is_specify: bool = False
    parent_option_label: Optional[str] = None
    parent_label: Optional[str] = None
    
    # Conditional logic
    conditional_parent: Optional[str] = None
    conditional_value: Optional[str] = None
    
    # Validation
    required: bool = False
    numeric_only: bool = False
    allowed_values: List[str] = field(default_factory=list)
    
    # Zoho/DB mapping
    zoho_column: Optional[str] = None
    db_column: Optional[str] = None
    is_jsonb_array: bool = False
    is_single_select: bool = False
    is_yes_no_pair: bool = False
    skip_if_empty: bool = False
    
    # Internal
    parent_label: Optional[str] = None  # For hierarchy (same as parent_label)


@dataclass
class SectionDefinition:
    number: Optional[int]
    name: str
    pages: List[int]
    fields: List[FieldDefinition] = field(default_factory=list)
    tables: List[TableDefinition] = field(default_factory=list)


# ============================================================================
# FORM SCHEMA DEFINITION
# ============================================================================

# Helper to create radio options
def radio_opts(*values: str) -> List[Dict[str, str]]:
    return [{"label": v, "value": v} for v in values]

def checkbox_opt(label: str, value: str) -> Dict[str, str]:
    return {"label": label, "value": value}

# ============================================================================
# FORM SCHEMA DEFINITION
# ============================================================================

FORM_SCHEMA: Dict[str, Any] = {
    "version": "1.0.0",
    "form_name": "I Am The Change — Home Visit Questionnaire",
    "total_pages": 6,
    "sections": [
        # ========================================================================
        # HEADER (Page 1, section = null)
        # ========================================================================
        {
            "number": None,
            "name": "Header",
            "pages": [1],
            "fields": [
                {"label": "Volunteer Name", "type": "text", "page": 1, "section": None, 
                 "zoho_column": "volunteer_name", "db_column": "volunteer_name"},
                {"label": "Co-Volunteer Name", "type": "text", "page": 1, "section": None,
                 "zoho_column": "co_volunteer_name", "db_column": "co_volunteer_name"},
                {"label": "Date of Visit", "type": "text", "page": 1, "section": None,
                 "zoho_column": "date_of_visit", "db_column": "date_of_visit"},
            ],
            "tables": [],
        },
        
        # ========================================================================
        # SECTION 1: Student Profile (Page 1)
        # ========================================================================
        {
            "number": 1,
            "name": "Student Profile",
            "pages": [1],
            "fields": [
                {"label": "1.1 Application ID", "type": "text", "page": 1, "section": 1, "required": True,
                 "zoho_column": "application_id", "db_column": "application_id"},
                {"label": "1.2 Student Full Name", "type": "text", "page": 1, "section": 1, "required": True,
                 "zoho_column": "student_full_name", "db_column": "student_full_name"},
                {"label": "1.3 Gender", "type": "radio", "page": 1, "section": 1, "required": True,
                 "options": radio_opts("Male", "Female", "Others"),
                 "zoho_column": "gender", "db_column": "gender"},
            ],
            "tables": [],
        },

        # ========================================================================
        # SECTION 2: Family Background (Pages 1-2)
        # ========================================================================
        {
            "number": 2,
            "name": "Family Background",
            "pages": [1, 2],
            "fields": [
                {"label": "2.1 Family Status", "type": "radio", "page": 1, "section": 2, "required": True,
                 "options": radio_opts("Having both parents", "Single Parent", "Parentless"),
                 "zoho_column": "family_status", "db_column": "family_status"},
                
                {"label": "2.2 Relationship Details — Year of Death / Separation", 
                 "type": "text", "page": 1, "section": 2, "numeric_only": True,
                 "zoho_column": "relationship_death_year", "db_column": "relationship_death_year"},
                {"label": "2.2 Relationship Details — Reason for Death / Separation",
                 "type": "text", "page": 1, "section": 2,
                 "zoho_column": "relationship_death_reason", "db_column": "relationship_death_reason"},
                
                {"label": "2.3 Is Father/Mother photograph kept at home?",
                 "type": "radio", "page": 2, "section": 2, "required": True,
                 "options": radio_opts("Yes", "No"),
                 "zoho_column": "photograph_kept_at_home", "db_column": "photograph_kept_at_home"},
                {"label": "2.3 Is Father/Mother photograph kept at home? — Notes",
                 "type": "text", "page": 2, "section": 2,
                 "zoho_column": "photograph_notes", "db_column": "photograph_notes"},
                
                # Government ID Verified - parent
                {"label": "2.4 Government ID Verified", "type": "checkbox", "page": 2, "section": 2, "options": []},
                {"label": "2.4 Government ID Verified — Aadhaar Card",
                 "type": "checkbox", "page": 2, "section": 2, "parent_label": "2.4 Government ID Verified",
                 "zoho_column": "gov_id_aadhaar", "db_column": "gov_id_aadhaar", "is_jsonb_array": True},
                {"label": "2.4 Government ID Verified — Ration Card",
                 "type": "checkbox", "page": 2, "section": 2, "parent_label": "2.4 Government ID Verified",
                 "zoho_column": "gov_id_ration", "db_column": "gov_id_ration", "is_jsonb_array": True},
                {"label": "2.4 Government ID Verified — Driving Licence",
                 "type": "checkbox", "page": 2, "section": 2, "parent_label": "2.4 Government ID Verified",
                 "zoho_column": "gov_id_driving", "db_column": "gov_id_driving", "is_jsonb_array": True},
                {"label": "2.4 Government ID Verified — Voter ID",
                 "type": "checkbox", "page": 2, "section": 2, "parent_label": "2.4 Government ID Verified",
                 "zoho_column": "gov_id_voter", "db_column": "gov_id_voter", "is_jsonb_array": True},
                {"label": "2.4 Government ID Verified — Other",
                 "type": "checkbox", "page": 2, "section": 2, "parent_label": "2.4 Government ID Verified",
                 "zoho_column": "gov_id_other", "db_column": "gov_id_other", "is_jsonb_array": True},
                {"label": "2.4 Government ID Verified — Other (specify)",
                 "type": "specify", "page": 2, "section": 2,
                 "parent_option_label": "Other", "parent_label": "2.4 Government ID Verified",
                 "zoho_column": "gov_id_other_specify", "db_column": "gov_id_other_specify"},
                
                # Family Members Table
                {"label": "2.5 Family Members", "type": "table_header", "page": 2, "section": 2,
                 "table_header_label": "2.5 Family Members"},
            ],
            "tables": [{
                "header_label": "2.5 Family Members",
                "columns": [
                    {"name": "Name", "type": "text"},
                    {"name": "Age", "type": "numeric"},
                    {"name": "Education", "type": "text"},
                    {"name": "Occupation", "type": "text"},
                    {"name": "Annual Income", "type": "numeric"},
                ],
                "row_count": 5,
                "blank_area_pages": [2],
            }],
        },

        # ========================================================================
        # SECTION 3: Housing Condition (Pages 2-3)
        # ========================================================================
        {
            "number": 3,
            "name": "Housing Condition",
            "pages": [2, 3],
            "fields": [
                # House Ownership (mutually exclusive pair)
                {"label": "3.1 House Ownership — Own", "type": "radio", "page": 2, "section": 3,
                 "mutually_exclusive_with": ["3.1 House Ownership — Rented"],
                 "zoho_column": "house_ownership", "db_column": "house_ownership", "is_yes_no_pair": True},
                {"label": "3.1 House Ownership — Rented", "type": "radio", "page": 2, "section": 3,
                 "mutually_exclusive_with": ["3.1 House Ownership — Own"],
                 "is_yes_no_pair": True},
                {"label": "3.1.1 If rented, what is the rent amount?", "type": "text", "page": 2, "section": 3,
                 "conditional_parent": "3.1 House Ownership — Rented", "conditional_value": "Yes",
                 "zoho_column": "rent_amount", "db_column": "rent_amount"},
                
                # Type of Home (multi-select)
                {"label": "3.2 Type of Home", "type": "checkbox", "page": 2, "section": 3, "options": []},
                {"label": "3.2 Type of Home — Individual", "type": "checkbox", "page": 2, "section": 3,
                 "parent_label": "3.2 Type of Home", "zoho_column": "home_type_individual", 
                 "db_column": "home_type_individual", "is_jsonb_array": True},
                {"label": "3.2 Type of Home — Private Apartment",
                 "type": "checkbox", "page": 2, "section": 3, "parent_label": "3.2 Type of Home",
                 "zoho_column": "home_type_apartment", "db_column": "home_type_apartment", "is_jsonb_array": True},
                {"label": "3.2 Type of Home — Housing Board",
                 "type": "checkbox", "page": 2, "section": 3, "parent_label": "3.2 Type of Home",
                 "zoho_column": "home_type_housing_board", "db_column": "home_type_housing_board", "is_jsonb_array": True},
                {"label": "3.2 Type of Home — Line House",
                 "type": "checkbox", "page": 2, "section": 3, "parent_label": "3.2 Type of Home",
                 "zoho_column": "home_type_line_house", "db_column": "home_type_line_house", "is_jsonb_array": True},
                {"label": "3.2 Type of Home — Others",
                 "type": "checkbox", "page": 2, "section": 3, "parent_label": "3.2 Type of Home",
                 "zoho_column": "home_type_others", "db_column": "home_type_others", "is_jsonb_array": True},
                {"label": "3.2 Type of Home — Others (specify)",
                 "type": "specify", "page": 2, "section": 3,
                 "parent_option_label": "Others", "parent_label": "3.2 Type of Home",
                 "zoho_column": "home_type_others_specify", "db_column": "home_type_others_specify"},
                
                # Type of Ceiling
                {"label": "3.3 Type of Ceiling", "type": "checkbox", "page": 3, "section": 3, "options": []},
                {"label": "3.3 Type of Ceiling — Roof (Kurai)", "type": "checkbox", "page": 3, "section": 3,
                 "parent_label": "3.3 Type of Ceiling", "zoho_column": "ceiling_roof", 
                 "db_column": "ceiling_roof", "is_jsonb_array": True},
                {"label": "3.3 Type of Ceiling — Tiled",
                 "type": "checkbox", "page": 3, "section": 3, "parent_label": "3.3 Type of Ceiling",
                 "zoho_column": "ceiling_tiled", "db_column": "ceiling_tiled", "is_jsonb_array": True},
                {"label": "3.3 Type of Ceiling — Asbestos / Sheet",
                 "type": "checkbox", "page": 3, "section": 3, "parent_label": "3.3 Type of Ceiling",
                 "zoho_column": "ceiling_asbestos", "db_column": "ceiling_asbestos", "is_jsonb_array": True},
                {"label": "3.3 Type of Ceiling — Concrete",
                 "type": "checkbox", "page": 3, "section": 3, "parent_label": "3.3 Type of Ceiling",
                 "zoho_column": "ceiling_concrete", "db_column": "ceiling_concrete", "is_jsonb_array": True},
                
                # Number of Bedrooms
                {"label": "3.4 Number of Bedrooms", "type": "text", "page": 3, "section": 3, "numeric_only": True,
                 "zoho_column": "number_of_bedrooms", "db_column": "number_of_bedrooms"},
                
                # Type of Bedroom (mutually exclusive)
                {"label": "3.4.1 Type of Bedroom — Separate Bedroom", "type": "radio", "page": 3, "section": 3,
                 "mutually_exclusive_with": ["3.4.1 Type of Bedroom — No Separate Bedroom"],
                 "zoho_column": "type_of_bedroom", "db_column": "type_of_bedroom", "is_yes_no_pair": True},
                {"label": "3.4.1 Type of Bedroom — No Separate Bedroom", "type": "radio", "page": 3, "section": 3,
                 "mutually_exclusive_with": ["3.4.1 Type of Bedroom — Separate Bedroom"]},
                
                # Bathroom (mutually exclusive)
                {"label": "3.5 Bathroom - Separate", "type": "radio", "page": 3, "section": 3,
                 "mutually_exclusive_with": ["3.5 Bathroom - Common for Apartment"],
                 "zoho_column": "bathroom", "db_column": "bathroom", "is_yes_no_pair": True},
                {"label": "3.5 Bathroom - Common for Apartment", "type": "radio", "page": 3, "section": 3,
                 "mutually_exclusive_with": ["3.5 Bathroom - Separate"]},
                
                # Kitchen Type
                {"label": "3.6 Kitchen Type — Separate Kitchen", "type": "radio", "page": 3, "section": 3,
                 "mutually_exclusive_with": ["3.6 Kitchen Type — Hall with Kitchen"],
                 "zoho_column": "kitchen_type", "db_column": "kitchen_type"},
                {"label": "3.6 Kitchen Type — Hall with Kitchen", "type": "radio", "page": 3, "section": 3,
                 "mutually_exclusive_with": ["3.6 Kitchen Type — Separate Kitchen"]},
            ],
            "tables": [],
        },

        # ========================================================================
        # SECTION 4: Financial Background (Pages 3-5)
        # ========================================================================
        {
            "number": 4,
            "name": "Financial Background",
            "pages": [3, 4, 5],
            "fields": [
                # Assets at Home (multi-select with specify)
                {"label": "4.1 Assets at Home", "type": "checkbox", "page": 3, "section": 4, "options": []},
                {"label": "4.1 Assets at Home(tick all that apply) - Washing Machine",
                 "type": "checkbox", "page": 3, "section": 4, "parent_label": "4.1 Assets at Home",
                 "zoho_column": "assets_washing_machine", "db_column": "assets_washing_machine", "is_jsonb_array": True},
                {"label": "4.1 Assets at Home(tick all that apply) - Fridge",
                 "type": "checkbox", "page": 3, "section": 4, "parent_label": "4.1 Assets at Home",
                 "zoho_column": "assets_fridge", "db_column": "assets_fridge", "is_jsonb_array": True},
                {"label": "4.1 Assets at Home(tick all that apply) - AC",
                 "type": "checkbox", "page": 3, "section": 4, "parent_label": "4.1 Assets at Home",
                 "zoho_column": "assets_ac", "db_column": "assets_ac", "is_jsonb_array": True},
                {"label": "4.1 Assets at Home(tick all that apply) - LED TV",
                 "type": "checkbox", "page": 3, "section": 4, "parent_label": "4.1 Assets at Home",
                 "zoho_column": "assets_led_tv", "db_column": "assets_led_tv", "is_jsonb_array": True},
                {"label": "4.1 Assets at Home(tick all that apply) - Two-Wheeler",
                 "type": "checkbox", "page": 3, "section": 4, "parent_label": "4.1 Assets at Home",
                 "zoho_column": "assets_two_wheeler", "db_column": "assets_two_wheeler", "is_jsonb_array": True},
                {"label": "4.1 Assets at Home(tick all that apply) - Car",
                 "type": "checkbox", "page": 3, "section": 4, "parent_label": "4.1 Assets at Home",
                 "zoho_column": "assets_car", "db_column": "assets_car", "is_jsonb_array": True},
                {"label": "4.1 Assets at Home(tick all that apply) - Smartphone",
                 "type": "checkbox", "page": 3, "section": 4, "parent_label": "4.1 Assets at Home",
                 "zoho_column": "assets_smartphone", "db_column": "assets_smartphone", "is_jsonb_array": True},
                {"label": "4.1 Assets at Home(tick all that apply) - Separate Wi-Fi",
                 "type": "checkbox", "page": 3, "section": 4, "parent_label": "4.1 Assets at Home",
                 "zoho_column": "assets_wifi", "db_column": "assets_wifi", "is_jsonb_array": True},
                {"label": "4.1 Assets at Home(tick all that apply) - Others:",
                 "type": "checkbox", "page": 3, "section": 4, "parent_label": "4.1 Assets at Home",
                 "zoho_column": "assets_others", "db_column": "assets_others", "is_jsonb_array": True},
                {"label": "4.1 Assets at Home(tick all that apply) - Others (specify):",
                 "type": "specify", "page": 3, "section": 4,
                 "parent_option_label": "Others:", "parent_label": "4.1 Assets at Home",
                 "zoho_column": "assets_others_specify", "db_column": "assets_others_specify"},
                
                # Electricity Bill
                {"label": "4.2 Amount of Last Electricity Bill", "type": "text", "page": 3, "section": 4,
                 "zoho_column": "electricity_bill_amount", "db_column": "electricity_bill_amount"},
                
                # Own Other Assets (mutually exclusive)
                {"label": "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes",
                 "type": "radio", "page": 3, "section": 4,
                 "mutually_exclusive_with": ["4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — No"],
                 "is_yes_no_pair": True,
                 "zoho_column": "owns_other_assets", "db_column": "owns_other_assets"},
                {"label": "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — No",
                 "type": "radio", "page": 3, "section": 4,
                 "mutually_exclusive_with": ["4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes"]},
                
                # 4.3.1 Table (conditional)
                {"label": "4.3.1 If Yes, list their properties:", "type": "table_header", "page": 3, "section": 4,
                 "table_header_label": "4.3.1 If Yes, list their properties:",
                 "conditional_parent": "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes",
                 "conditional_value": "Yes"},
                
                # 4.4 Other Income Source (mutually exclusive)
                {"label": "4.4 Apart from your job, is there any other source of income? — Yes",
                 "type": "radio", "page": 4, "section": 4,
                 "mutually_exclusive_with": ["4.4 Apart from your job, is there any other source of income? — No"],
                 "is_yes_no_pair": True, "zoho_column": "has_other_income", "db_column": "has_other_income"},
                {"label": "4.4 Apart from your job, is there any other source of income? — No",
                 "type": "radio", "page": 4, "section": 4,
                 "mutually_exclusive_with": ["4.4 Apart from your job, is there any other source of income? — Yes"]},
                
                # 4.4.1 Table (conditional)
                {"label": "4.4.1 If Yes, list other sources of income:", "type": "table_header", "page": 4, "section": 4,
                 "table_header_label": "4.4.1 If Yes, list other sources of income:",
                 "conditional_parent": "4.4 Apart from your job, is there any other source of income? — Yes",
                 "conditional_value": "Yes"},
                
                # Income Type (multi-select with specify)
                {"label": "4.5 Income Type", "type": "checkbox", "page": 4, "section": 4, "options": []},
                {"label": "4.5 Income Type — Monthly", "type": "checkbox", "page": 4, "section": 4,
                 "parent_label": "4.5 Income Type", "zoho_column": "income_type_monthly",
                 "db_column": "income_type_monthly", "is_jsonb_array": True},
                {"label": "4.5 Income Type — Monthly (specify)", "type": "specify", "page": 4, "section": 4,
                 "parent_option_label": "Monthly", "parent_label": "4.5 Income Type",
                 "zoho_column": "income_type_monthly_specify", "db_column": "income_type_monthly_specify"},
                {"label": "4.5 Income Type — Daily", "type": "checkbox", "page": 4, "section": 4,
                 "parent_label": "4.5 Income Type", "zoho_column": "income_type_daily",
                 "db_column": "income_type_daily", "is_jsonb_array": True},
                {"label": "4.5 Income Type — Daily (specify)", "type": "specify", "page": 4, "section": 4,
                 "parent_option_label": "Daily", "parent_label": "4.5 Income Type",
                 "zoho_column": "income_type_daily_specify", "db_column": "income_type_daily_specify"},
                {"label": "4.5 Income Type — Weekly", "type": "checkbox", "page": 4, "section": 4,
                 "parent_label": "4.5 Income Type", "zoho_column": "income_type_weekly",
                 "db_column": "income_type_weekly", "is_jsonb_array": True},
                {"label": "4.5 Income Type — Weekly (specify)", "type": "specify", "page": 4, "section": 4,
                 "parent_option_label": "Weekly", "parent_label": "4.5 Income Type",
                 "zoho_column": "income_type_weekly_specify", "db_column": "income_type_weekly_specify"},
                {"label": "4.5 Income Type — Ad-Hoc", "type": "checkbox", "page": 4, "section": 4,
                 "parent_label": "4.5 Income Type", "zoho_column": "income_type_adhoc",
                 "db_column": "income_type_adhoc", "is_jsonb_array": True},
                {"label": "4.5 Income Type — Ad-Hoc (specify)", "type": "specify", "page": 4, "section": 4,
                 "parent_option_label": "Ad-Hoc", "parent_label": "4.5 Income Type",
                 "zoho_column": "income_type_adhoc_specify", "db_column": "income_type_adhoc_specify"},
                
                # Loans (mutually exclusive)
                {"label": "4.6 Do you have any loans? — Yes", "type": "radio", "page": 4, "section": 4,
                 "mutually_exclusive_with": ["4.6 Do you have any loans? — No"],
                 "is_yes_no_pair": True, "zoho_column": "has_loans", "db_column": "has_loans"},
                {"label": "4.6 Do you have any loans? — No", "type": "radio", "page": 4, "section": 4,
                 "mutually_exclusive_with": ["4.6 Do you have any loans? — Yes"]},
                
                # 4.6.1 Table (conditional)
                {"label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
                 "type": "table_header", "page": 4, "section": 4,
                 "table_header_label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
                 "conditional_parent": "4.6 Do you have any loans? — Yes", "conditional_value": "Yes"},
                
                # College Fee
                {"label": "4.7 If you choose any college, how much is the college fee?",
                 "type": "text", "page": 5, "section": 4,
                 "zoho_column": "college_fee", "db_column": "college_fee"},
                {"label": "4.8 If the college fee is higher, how will you manage it?",
                 "type": "text", "page": 5, "section": 4,
                 "zoho_column": "manage_higher_fee", "db_column": "manage_higher_fee"},
                {"label": "4.9 If you do not receive this scholarship, how will you pay the fees?",
                 "type": "text", "page": 5, "section": 4,
                 "zoho_column": "manage_without_scholarship", "db_column": "manage_without_scholarship"},
            ],
            "tables": [
                {
                    "header_label": "4.3.1 If Yes, list their properties:",
                    "columns": [
                        {"name": "Property Description", "type": "text"},
                        {"name": "Owner Name", "type": "text"},
                        {"name": "Approximate Value", "type": "numeric"},
                    ],
                    "row_count": 4,
                    "blank_area_pages": [3, 4],
                },
                {
                    "header_label": "4.4.1 If Yes, list other sources of income:",
                    "columns": [
                        {"name": "Source of Income", "type": "text"},
                        {"name": "Amount", "type": "numeric"},
                    ],
                    "row_count": 2,
                },
                {
                    "header_label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
                    "columns": [
                        {"name": "Sr.No.", "type": "numeric"},
                        {"name": "Loan Purpose", "type": "text"},
                        {"name": "Loan Amount Taken", "type": "numeric"},
                        {"name": "Pending Loan Amount", "type": "numeric"},
                    ],
                    "row_count": 3,
                },
            ],
        },

        # ========================================================================
        # SECTION 5: Health Information (Page 5)
        # ========================================================================
        {
            "number": 5,
            "name": "Health Information",
            "pages": [5],
            "fields": [
                {"label": "5.1 Does the student have any health issues? — Yes",
                 "type": "radio", "page": 5, "section": 5,
                 "mutually_exclusive_with": ["5.1 Does the student have any health issues? — No"],
                 "is_yes_no_pair": True,
                 "zoho_column": "has_health_issues", "db_column": "has_health_issues"},
                {"label": "5.1 Does the student have any health issues? — No",
                 "type": "radio", "page": 5, "section": 5,
                 "mutually_exclusive_with": ["5.1 Does the student have any health issues? — Yes"]},
                {"label": "5.2 If yes, list the health issues", "type": "text", "page": 5, "section": 5,
                 "conditional_parent": "5.1 Does the student have any health issues? — Yes",
                 "conditional_value": "Yes",
                 "zoho_column": "health_issues_description", "db_column": "health_issues_description"},
            ],
            "tables": [],
        },

        # ========================================================================
        # SECTION 6: Student Commitment (Pages 5-6)
        # ========================================================================
        {
            "number": 6,
            "name": "Student Commitment",
            "pages": [5, 6],
            "fields": [
                {"label": "6.1 Will you study college for three years without any obstacle?",
                 "type": "text", "page": 5, "section": 6,
                 "zoho_column": "study_commitment", "db_column": "study_commitment"},
                {"label": "6.2 If we have a training program within 15 km from your home, can you come?",
                 "type": "radio", "page": 5, "section": 6,
                 "options": radio_opts("Yes", "No", "Maybe"),
                 "zoho_column": "training_program_availability", "db_column": "training_program_availability"},
                {"label": "6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)?",
                 "type": "radio", "page": 6, "section": 6,
                 "options": radio_opts("Yes", "No"),
                 "zoho_column": "ready_for_skill_classes", "db_column": "ready_for_skill_classes"},
            ],
            "tables": [],
        },

        # ========================================================================
        # SECTION 7: Scholarship Information (Page 6)
        # ========================================================================
        {
            "number": 7,
            "name": "Scholarship Information",
            "pages": [6],
            "fields": [
                {"label": "7.1 Has the student received or applied for any other scholarships for their UG degree?",
                 "type": "text", "page": 6, "section": 7,
                 "zoho_column": "other_scholarships", "db_column": "other_scholarships"},
            ],
            "tables": [],
        },

        # ========================================================================
        # SECTION 8: Volunteer Observation (Page 6)
        # ========================================================================
        {
            "number": 8,
            "name": "Volunteer Observation",
            "pages": [6],
            "fields": [
                {"label": "8.1 What is your opinion about the student, their family members, and their living condition?",
                 "type": "text", "page": 6, "section": 8,
                 "zoho_column": "volunteer_opinion", "db_column": "volunteer_opinion"},
                {"label": "8.2 Will you recommend this student for this scholarship?",
                 "type": "radio", "page": 6, "section": 8,
                 "options": radio_opts("Yes", "No", "Not Sure"),
                 "zoho_column": "recommend_student", "db_column": "recommend_student"},
                {"label": "8.3 Any other comments you want to share?",
                 "type": "text", "page": 6, "section": 8,
                 "zoho_column": "volunteer_comments", "db_column": "volunteer_comments"},
],
            "tables": [],
        },
    ]
}
# ============================================================================
# POST-PROCESS: Add table row fields to schema
# ============================================================================

def _expand_table_rows(schema: Dict) -> Dict:
    """Add table_row fields for each table definition.
    Uses the table header field's page for each row; falls back to blank_area_pages.
    """
    for section in schema["sections"]:
        existing_labels = {f["label"] for f in section["fields"]}
        for table in section.get("tables", []):
            header_label = table["header_label"]
            # Find the table header field to get its page
            header_field = next((f for f in section["fields"] if f.get("label") == header_label), None)
            header_page = header_field["page"] if header_field else section["pages"][0]
            for row_idx in range(1, table["row_count"] + 1):
                for col in table["columns"]:
                    row_label = f"{header_label} \u2014 Row {row_idx} \u2014 {col['name']}"
                    if row_label in existing_labels:
                        continue
                    # If blank_area_pages defined, use first page for initial assignment
                    blank_pages = table.get("blank_area_pages", [])
                    page = blank_pages[0] if blank_pages else header_page
                    section["fields"].append({
                        "label": row_label,
                        "type": "table_row",
                        "page": page,
                        "section": section["number"],
                        "table_header_label": header_label,
                        "row_index": row_idx,
                        "column_name": col["name"],
                    })
    return schema


FORM_SCHEMA = _expand_table_rows(FORM_SCHEMA)
# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def radio_opts(*values: str) -> List[Dict[str, str]]:
    return [{"label": v, "value": v} for v in values]

def checkbox_opt(label: str, value: str) -> Dict[str, str]:
    return {"label": label, "value": value}

def getAllFields(schema: Dict[str, Any]) -> List[Dict]:
    return [f for s in schema["sections"] for f in s["fields"]]

def getTableHeaders(schema: Dict[str, Any]) -> List[Dict]:
    return [f for s in schema["sections"] for f in s["fields"] if f["type"] == "table_header"]

def getTableDefinitions(schema: Dict[str, Any]) -> List[Dict]:
    return [t for s in schema["sections"] for t in s["tables"]]

def validateSchema(schema: Dict[str, Any]) -> tuple:
    errors = []
    labels = set()
    
    for field in getAllFields(FORM_SCHEMA):
        if field["label"] in labels:
            errors.append(f"Duplicate field label: {field['label']}")
        labels.add(field["label"])
        
        if field.get("mutually_exclusive_with"):
            for other in field["mutually_exclusive_with"]:
                if not any(f["label"] == other for f in getAllFields(FORM_SCHEMA)):
                    errors.append(f"Mutually exclusive reference not found: {field['label']} -> {other}")
        
        if field.get("conditional_parent"):
            if not any(f["label"] == field["conditional_parent"] for f in getAllFields(FORM_SCHEMA)):
                errors.append(f"Conditional parent not found: {field['conditional_parent']} for {field['label']}")
        
        if field.get("type") == "table_header":
            table = next((t for s in FORM_SCHEMA["sections"] for t in s["tables"] 
                         if t["header_label"] == field.get("table_header_label")), None)
            if not table:
                errors.append(f"Table header references non-existent table: {field.get('table_header_label')}")
    
    return len(errors) == 0, errors


def getAllFields(schema: Dict) -> List[Dict]:
    return [f for s in schema["sections"] for f in s["fields"]]

def getTableHeaders(schema: Dict) -> List[Dict]:
    return [f for s in schema["sections"] for f in s["fields"] if f["type"] == "table_header"]

def getTableDefinitions(schema: Dict) -> List[Dict]:
    return [t for s in schema["sections"] for t in s["tables"]]

def validateSchema(schema: Dict) -> tuple:
    errors = []
    labels = set()
    
    for field in getAllFields(schema):
        if field["label"] in labels:
            errors.append(f"Duplicate field label: {field['label']}")
        labels.add(field["label"])
        
        if field.get("mutually_exclusive_with"):
            for other in field["mutually_exclusive_with"]:
                if not any(f["label"] == other for f in getAllFields(schema)):
                    errors.append(f"Mutually exclusive reference not found: {field['label']} -> {other}")
        
        if field.get("conditional_parent"):
            if not any(f["label"] == field["conditional_parent"] for f in getAllFields(schema)):
                errors.append(f"Conditional parent not found: {field['conditional_parent']} for {field['label']}")
        
        if field.get("type") == "table_header":
            table = next((t for s in schema["sections"] for t in s["tables"] 
                         if t["header_label"] == field.get("table_header_label")), None)
            if not table:
                errors.append(f"Table header references non-existent table: {field.get('table_header_label')}")
    
    return len(errors) == 0, errors


# ============================================================================
# GENERATOR FUNCTIONS
# ============================================================================

def generate_known_template_fields(schema: Dict) -> List[Dict[str, Any]]:
    """Generate KNOWN_TEMPLATE_FIELDS for extraction_pipeline.py"""
    fields = []
    for f in getAllFields(FORM_SCHEMA):
        if f["type"] == "specify":
            continue
        field_data = {
            "label": f["label"],
            "section_number": f["section"],
            "page": f["page"],
            "field_type": f["type"],
            "zoho_column": f.get("zoho_column"),
            "db_column": f.get("db_column"),
        }
        # Add table row metadata
        if f["type"] == "table_row":
            field_data["table_header_label"] = f.get("table_header_label")
            field_data["row_index"] = f.get("row_index")
            field_data["column_name"] = f.get("column_name")
        fields.append(field_data)
    return fields


def generate_page_field_mappings(schema: Dict) -> Dict[int, str]:
    """Generate PAGE_FIELD_MAPPINGS for prompt_templates.py"""
    mappings = {}
    
    for page_num in range(1, 8):  # Pages 1-6 + header
        page_fields = [f for f in getAllFields(FORM_SCHEMA) if f["page"] == page_num]
        if not page_fields:
            continue
        
        sections = {}
        for f in page_fields:
            sec = f["section"]
            if sec not in sections:
                sections[sec] = []
            sections[sec].append(f)
        
        lines = []
        for sec_num in sorted([s for s in sections.keys() if s is not None]):
            sec_fields = sections[sec_num]
            section_names = {
                1: "Student Profile", 2: "Family Background", 3: "Housing Condition",
                4: "Financial Background", 5: "Health Information", 6: "Student Commitment",
                7: "Scholarship Information", 8: "Volunteer Observation",
            }
            sec_name = section_names.get(sec_num, f"Section {sec_num}")
            lines.append(f"--- Section {sec_num} — {sec_name} (Page {page_num}) — {len(sec_fields)} fields ---")
            
            for f in sec_fields:
                if f["type"] == "table_header":
                    continue
                field_type = ""
                if f["type"] == "radio":
                    opts = " | ".join([o["value"] for o in (f.get("options") or [])])
                    field_type = f"[radio → {opts}]"
                elif f["type"] == "checkbox":
                    field_type = f"[checkbox — ✓ if checked, ✗ if empty]"
                elif f["type"] == "specify":
                    field_type = "[text — free-text next to parent checkbox]"
                elif f["type"] == "table_header":
                    continue
                else:
                    field_type = "[text]"
                
                cond = ""
                if f.get("conditionalParent"):
                    cond = f"  // CONDITIONAL: only if '{f['conditionalParent']}' = '{f['conditionalValue']}'"
                
                lines.append(f"  {f['label']}  {field_type}{cond}")
            
            # Tables
            for section in FORM_SCHEMA["sections"]:
                if section["number"] == sec_num:
                    for table in section["tables"]:
                        lines.append(f"  {table['header_label']} [table_header]")
                        for col in table["columns"]:
                            for row in range(1, table["row_count"] + 1):
                                lines.append(f"    {table['header_label']} - Row {row} - {col['name']} [text]")
                        lines.append("")
        
        # Header fields (section = null)
        header_fields = [f for f in page_fields if f["section"] is None]
        if header_fields:
            lines.insert(0, f"--- Header (Page 1, section=null) — {len(header_fields)} fields ---")
            for f in header_fields:
                lines.append(f"  {f['label']}  [text]")
        
        mappings[page_num] = "\n".join(lines)
    
    return mappings


def generate_known_template_fields_ts(schema) -> str:
    """Generate KNOWN_TEMPLATE_FIELDS for frontend/types.ts"""
    lines = []
    for f in getAllFields(FORM_SCHEMA):
        if f["type"] == "specify":
            continue
        section_str = f'"{f["section"]}"' if f["section"] is not None else "null"
        lines.append(f'  {{"label": "{f["label"]}", "section_number": {section_str}, "page": {f["page"]}}},')
    return "\n".join(lines)


def generate_types_ts(schema: Dict) -> str:
    """Generate frontend types.ts from schema"""
    return """// Generated from form_schema.py - DO NOT EDIT MANUALLY
export interface Field {
  label: string;
  value: string | null;
  confidence: number;
  page: number;
  section_number: number | null;
  bbox: [number, number, number, number] | null;
  value_bbox: [number, number, number, number] | null;
  needs_clarification: boolean;
  reason: string | null;
  is_verified: boolean;
  verifier_confidence: number | null;
  verification_note: string | null;
  extracted_by: string | null;
  verified_by: string | null;
  original_value: string | null;
  is_edited?: boolean;
  position_hint?: string;
  // Hierarchy fields (populated by backend enrich_fields)
  parent_label?: string | null;
  field_type?: string | null;
  group_id?: string | null;
  row_index?: number | null;
  column_name?: string | null;
}

export interface Section {
  number: number;
  name: string;
  page: number;
}

export interface JobResult {
  overall_confidence: number;
  coverage?: number;
  confidence?: number;
  num_pages: number;
  processing_time?: number;
  fields: Field[];
  sections: Section[];
  raw_text: string;
  primary_model: string;
  secondary_model: string;
  token_usage?: {
    primary: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
    secondary: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
    total: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  };
  pdf_times?: Record<string, number>;
  batch?: boolean;
  num_pdfs?: number;
  pdf_names?: string[];
}
"""


def write_output_files():
    """Write all generated files"""
    output_dir = Path(__file__).parent.parent
    
    # Validate schema first
    valid, errors = validateSchema(FORM_SCHEMA)
    if not valid:
        print("Schema validation failed:")
        for e in errors:
            print(f"  ERROR: {e}")
        return False
    
    print("Schema validation passed!")
    
    # 1. Generate form_schema.py (single source of truth Python file)
    form_schema_path = output_dir / "src" / "form_schema.py"
    with open(form_schema_path, "w") as f:
        f.write('"""Form schema - single source of truth."""\n\n')
        f.write("import json\nimport os\nimport re\nimport sys\nfrom pathlib import Path\n")
        f.write("from typing import Any, Dict, List, Optional\n\n")
        f.write("FORM_SCHEMA = ")
        schema_json = json.dumps(FORM_SCHEMA, indent=2, ensure_ascii=False)
        # Convert JSON null/true/false to Python None/True/False (only JSON value literals)
        import re
        schema_json = re.sub(r'(?<=: )null(?=[\s,\]}])', 'None', schema_json)
        schema_json = re.sub(r'(?<=: )true(?=[\s,\]}])', 'True', schema_json)
        schema_json = re.sub(r'(?<=: )false(?=[\s,\]}])', 'False', schema_json)
        f.write(schema_json + "\n\n")
        f.write('def radio_opts(*values: str) -> List[Dict[str, str]]:\n')
        f.write('    return [{"label": v, "value": v} for v in values]\n\n')
        f.write('def checkbox_opt(label: str, value: str) -> Dict[str, str]:\n')
        f.write('    return {"label": label, "value": value}\n\n')
        f.write('def getAllFields(schema: Dict[str, Any]) -> List[Dict]:\n')
        f.write('    return [f for s in schema["sections"] for f in s["fields"]]\n\n')
        f.write('def getTableHeaders(schema: Dict) -> List[Dict]:\n')
        f.write('    return [f for s in schema["sections"] for f in s["fields"] if f["type"] == "table_header"]\n\n')
        f.write('def getTableDefinitions(schema: Dict) -> List[Dict]:\n')
        f.write('    return [t for s in schema["sections"] for t in s["tables"]]\n\n')
        f.write('def validateSchema(schema: Dict[str, Any]) -> tuple:\n')
        f.write('    errors = []\n')
        f.write('    labels = set()\n')
        f.write('    for field in getAllFields(FORM_SCHEMA):\n')
        f.write('        if field["label"] in labels:\n')
        f.write('            errors.append(f"Duplicate field label: {field[\'label\']}")\n')
        f.write('        labels.add(field["label"])\n')
        f.write('        if field.get("mutually_exclusive_with"):\n')
        f.write('            for other in field["mutually_exclusive_with"]:\n')
        f.write('                if not any(f["label"] == other for f in getAllFields(FORM_SCHEMA)):\n')
        f.write('                    errors.append(f"Mutually exclusive reference not found: {field[\'label\']} -> {other}")\n')
        f.write('        if field.get("conditional_parent"):\n')
        f.write('            if not any(f["label"] == field["conditional_parent"] for f in getAllFields(FORM_SCHEMA)):\n')
        f.write('                errors.append(f"Conditional parent not found: {field[\'conditional_parent\']} for {field[\'label\']}")\n')
        f.write('        if field.get("type") == "table_header":\n')
        f.write('            table = next((t for s in FORM_SCHEMA["sections"] for t in s["tables"] if t["header_label"] == field.get("table_header_label")), None)\n')
        f.write('            if not table:\n')
        f.write('                errors.append(f"Table header references non-existent table: {field.get(\'table_header_label\')}")\n')
        f.write('    return len(errors) == 0, errors\n')
    print(f"Wrote {form_schema_path}")

    # 2. Generate KNOWN_TEMPLATE_FIELDS output (for extraction_pipeline.py)
    template_fields = generate_known_template_fields(FORM_SCHEMA)
    print(f"Generated {len(template_fields)} template fields")
    
    # 3. Generate PAGE_FIELD_MAPPINGS for prompt_templates.py
    page_mappings = generate_page_field_mappings(FORM_SCHEMA)
    print(f"Generated mappings for {len(page_mappings)} pages")
    
    # 4. Zoho mappings
    zoho_mapping = {f["label"]: f["zoho_column"] for f in getAllFields(FORM_SCHEMA) if f.get("zoho_column")}
    print(f"Generated {len(zoho_mapping)} Zoho field mappings")
    
    # 5. Frontend types.ts
    types_ts = generate_types_ts(FORM_SCHEMA)
    print("Generated frontend types.ts")
    
    print("\nAll artifacts generated successfully!")
    return True


if __name__ == "__main__":
    success = write_output_files()
    sys.exit(0 if success else 1)