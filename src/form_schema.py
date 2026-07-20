"""Form schema - single source of truth."""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

FORM_SCHEMA = {
  "version": "1.0.0",
  "form_name": "I Am The Change — Home Visit Questionnaire",
  "total_pages": 6,
  "sections": [
    {
      "number": None,
      "name": "Header",
      "pages": [
        1
      ],
      "fields": [
        {
          "label": "Volunteer Name",
          "type": "text",
          "page": 1,
          "section": None,
          "zoho_column": "volunteer_name",
          "db_column": "volunteer_name"
        },
        {
          "label": "Co-Volunteer Name",
          "type": "text",
          "page": 1,
          "section": None,
          "zoho_column": "co_volunteer_name",
          "db_column": "co_volunteer_name"
        },
        {
          "label": "Date of Visit",
          "type": "text",
          "page": 1,
          "section": None,
          "zoho_column": "date_of_visit",
          "db_column": "date_of_visit"
        }
      ],
      "tables": []
    },
    {
      "number": 1,
      "name": "Student Profile",
      "pages": [
        1
      ],
      "fields": [
        {
          "label": "1.1 Application ID",
          "type": "text",
          "page": 1,
          "section": 1,
          "required": True,
          "zoho_column": "application_id",
          "db_column": "application_id"
        },
        {
          "label": "1.2 Student Full Name",
          "type": "text",
          "page": 1,
          "section": 1,
          "required": True,
          "zoho_column": "student_full_name",
          "db_column": "student_full_name"
        },
        {
          "label": "1.3 Gender",
          "type": "radio",
          "page": 1,
          "section": 1,
          "required": True,
          "options": [
            {
              "label": "Male",
              "value": "Male"
            },
            {
              "label": "Female",
              "value": "Female"
            },
            {
              "label": "Others",
              "value": "Others"
            }
          ],
          "zoho_column": "gender",
          "db_column": "gender"
        }
      ],
      "tables": []
    },
    {
      "number": 2,
      "name": "Family Background",
      "pages": [
        1,
        2
      ],
      "fields": [
        {
          "label": "2.1 Family Status",
          "type": "radio",
          "page": 1,
          "section": 2,
          "required": True,
          "options": [
            {
              "label": "Having both parents",
              "value": "Having both parents"
            },
            {
              "label": "Single Parent",
              "value": "Single Parent"
            },
            {
              "label": "Parentless",
              "value": "Parentless"
            }
          ],
          "zoho_column": "family_status",
          "db_column": "family_status"
        },
        {
          "label": "2.2 Relationship Details — Year of Death / Separation",
          "type": "text",
          "page": 1,
          "section": 2,
          "numeric_only": True,
          "zoho_column": "relationship_death_year",
          "db_column": "relationship_death_year"
        },
        {
          "label": "2.2 Relationship Details — Reason for Death / Separation",
          "type": "text",
          "page": 1,
          "section": 2,
          "zoho_column": "relationship_death_reason",
          "db_column": "relationship_death_reason"
        },
        {
          "label": "2.3 Is Father/Mother photograph kept at home?",
          "type": "radio",
          "page": 2,
          "section": 2,
          "required": True,
          "options": [
            {
              "label": "Yes",
              "value": "Yes"
            },
            {
              "label": "No",
              "value": "No"
            }
          ],
          "zoho_column": "photograph_kept_at_home",
          "db_column": "photograph_kept_at_home"
        },
        {
          "label": "2.3 Is Father/Mother photograph kept at home? — Notes",
          "type": "text",
          "page": 2,
          "section": 2,
          "zoho_column": "photograph_notes",
          "db_column": "photograph_notes"
        },
        {
          "label": "2.4 Government ID Verified",
          "type": "checkbox",
          "page": 2,
          "section": 2,
          "options": []
        },
        {
          "label": "2.4 Government ID Verified — Aadhaar Card",
          "type": "checkbox",
          "page": 2,
          "section": 2,
          "parent_label": "2.4 Government ID Verified",
          "zoho_column": "gov_id_aadhaar",
          "db_column": "gov_id_aadhaar",
          "is_jsonb_array": True
        },
        {
          "label": "2.4 Government ID Verified — Ration Card",
          "type": "checkbox",
          "page": 2,
          "section": 2,
          "parent_label": "2.4 Government ID Verified",
          "zoho_column": "gov_id_ration",
          "db_column": "gov_id_ration",
          "is_jsonb_array": True
        },
        {
          "label": "2.4 Government ID Verified — Driving Licence",
          "type": "checkbox",
          "page": 2,
          "section": 2,
          "parent_label": "2.4 Government ID Verified",
          "zoho_column": "gov_id_driving",
          "db_column": "gov_id_driving",
          "is_jsonb_array": True
        },
        {
          "label": "2.4 Government ID Verified — Voter ID",
          "type": "checkbox",
          "page": 2,
          "section": 2,
          "parent_label": "2.4 Government ID Verified",
          "zoho_column": "gov_id_voter",
          "db_column": "gov_id_voter",
          "is_jsonb_array": True
        },
        {
          "label": "2.4 Government ID Verified — Other",
          "type": "checkbox",
          "page": 2,
          "section": 2,
          "parent_label": "2.4 Government ID Verified",
          "zoho_column": "gov_id_other",
          "db_column": "gov_id_other",
          "is_jsonb_array": True
        },
        {
          "label": "2.4 Government ID Verified — Other (specify)",
          "type": "specify",
          "page": 2,
          "section": 2,
          "parent_option_label": "Other",
          "parent_label": "2.4 Government ID Verified",
          "zoho_column": "gov_id_other_specify",
          "db_column": "gov_id_other_specify"
        },
        {
          "label": "2.5 Family Members",
          "type": "table_header",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members"
        },
        {
          "label": "2.5 Family Members — Row 1 — Name",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 1,
          "column_name": "Name"
        },
        {
          "label": "2.5 Family Members — Row 1 — Age",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 1,
          "column_name": "Age"
        },
        {
          "label": "2.5 Family Members — Row 1 — Education",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 1,
          "column_name": "Education"
        },
        {
          "label": "2.5 Family Members — Row 1 — Occupation",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 1,
          "column_name": "Occupation"
        },
        {
          "label": "2.5 Family Members — Row 1 — Annual Income",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 1,
          "column_name": "Annual Income"
        },
        {
          "label": "2.5 Family Members — Row 2 — Name",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 2,
          "column_name": "Name"
        },
        {
          "label": "2.5 Family Members — Row 2 — Age",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 2,
          "column_name": "Age"
        },
        {
          "label": "2.5 Family Members — Row 2 — Education",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 2,
          "column_name": "Education"
        },
        {
          "label": "2.5 Family Members — Row 2 — Occupation",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 2,
          "column_name": "Occupation"
        },
        {
          "label": "2.5 Family Members — Row 2 — Annual Income",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 2,
          "column_name": "Annual Income"
        },
        {
          "label": "2.5 Family Members — Row 3 — Name",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 3,
          "column_name": "Name"
        },
        {
          "label": "2.5 Family Members — Row 3 — Age",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 3,
          "column_name": "Age"
        },
        {
          "label": "2.5 Family Members — Row 3 — Education",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 3,
          "column_name": "Education"
        },
        {
          "label": "2.5 Family Members — Row 3 — Occupation",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 3,
          "column_name": "Occupation"
        },
        {
          "label": "2.5 Family Members — Row 3 — Annual Income",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 3,
          "column_name": "Annual Income"
        },
        {
          "label": "2.5 Family Members — Row 4 — Name",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 4,
          "column_name": "Name"
        },
        {
          "label": "2.5 Family Members — Row 4 — Age",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 4,
          "column_name": "Age"
        },
        {
          "label": "2.5 Family Members — Row 4 — Education",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 4,
          "column_name": "Education"
        },
        {
          "label": "2.5 Family Members — Row 4 — Occupation",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 4,
          "column_name": "Occupation"
        },
        {
          "label": "2.5 Family Members — Row 4 — Annual Income",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 4,
          "column_name": "Annual Income"
        },
        {
          "label": "2.5 Family Members — Row 5 — Name",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 5,
          "column_name": "Name"
        },
        {
          "label": "2.5 Family Members — Row 5 — Age",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 5,
          "column_name": "Age"
        },
        {
          "label": "2.5 Family Members — Row 5 — Education",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 5,
          "column_name": "Education"
        },
        {
          "label": "2.5 Family Members — Row 5 — Occupation",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 5,
          "column_name": "Occupation"
        },
        {
          "label": "2.5 Family Members — Row 5 — Annual Income",
          "type": "table_row",
          "page": 2,
          "section": 2,
          "table_header_label": "2.5 Family Members",
          "row_index": 5,
          "column_name": "Annual Income"
        }
      ],
      "tables": [
        {
          "header_label": "2.5 Family Members",
          "columns": [
            {
              "name": "Name",
              "type": "text"
            },
            {
              "name": "Age",
              "type": "numeric"
            },
            {
              "name": "Education",
              "type": "text"
            },
            {
              "name": "Occupation",
              "type": "text"
            },
            {
              "name": "Annual Income",
              "type": "numeric"
            }
          ],
          "row_count": 5,
          "blank_area_pages": [
            2
          ]
        }
      ]
    },
    {
      "number": 3,
      "name": "Housing Condition",
      "pages": [
        2,
        3
      ],
      "fields": [
        {
          "label": "3.1 House Ownership — Own",
          "type": "radio",
          "page": 2,
          "section": 3,
          "mutually_exclusive_with": [
            "3.1 House Ownership — Rented"
          ],
          "zoho_column": "house_ownership",
          "db_column": "house_ownership",
          "is_yes_no_pair": True
        },
        {
          "label": "3.1 House Ownership — Rented",
          "type": "radio",
          "page": 2,
          "section": 3,
          "mutually_exclusive_with": [
            "3.1 House Ownership — Own"
          ],
          "is_yes_no_pair": True
        },
        {
          "label": "3.1.1 If rented, what is the rent amount?",
          "type": "text",
          "page": 2,
          "section": 3,
          "conditional_parent": "3.1 House Ownership — Rented",
          "conditional_value": "Yes",
          "zoho_column": "rent_amount",
          "db_column": "rent_amount"
        },
        {
          "label": "3.2 Type of Home",
          "type": "checkbox",
          "page": 2,
          "section": 3,
          "options": []
        },
        {
          "label": "3.2 Type of Home — Individual",
          "type": "checkbox",
          "page": 2,
          "section": 3,
          "parent_label": "3.2 Type of Home",
          "zoho_column": "home_type_individual",
          "db_column": "home_type_individual",
          "is_jsonb_array": True
        },
        {
          "label": "3.2 Type of Home — Private Apartment",
          "type": "checkbox",
          "page": 2,
          "section": 3,
          "parent_label": "3.2 Type of Home",
          "zoho_column": "home_type_apartment",
          "db_column": "home_type_apartment",
          "is_jsonb_array": True
        },
        {
          "label": "3.2 Type of Home — Housing Board",
          "type": "checkbox",
          "page": 2,
          "section": 3,
          "parent_label": "3.2 Type of Home",
          "zoho_column": "home_type_housing_board",
          "db_column": "home_type_housing_board",
          "is_jsonb_array": True
        },
        {
          "label": "3.2 Type of Home — Line House",
          "type": "checkbox",
          "page": 2,
          "section": 3,
          "parent_label": "3.2 Type of Home",
          "zoho_column": "home_type_line_house",
          "db_column": "home_type_line_house",
          "is_jsonb_array": True
        },
        {
          "label": "3.2 Type of Home — Others",
          "type": "checkbox",
          "page": 2,
          "section": 3,
          "parent_label": "3.2 Type of Home",
          "zoho_column": "home_type_others",
          "db_column": "home_type_others",
          "is_jsonb_array": True
        },
        {
          "label": "3.2 Type of Home — Others (specify)",
          "type": "specify",
          "page": 2,
          "section": 3,
          "parent_option_label": "Others",
          "parent_label": "3.2 Type of Home",
          "zoho_column": "home_type_others_specify",
          "db_column": "home_type_others_specify"
        },
        {
          "label": "3.3 Type of Ceiling",
          "type": "checkbox",
          "page": 3,
          "section": 3,
          "options": []
        },
        {
          "label": "3.3 Type of Ceiling — Roof (Kurai)",
          "type": "checkbox",
          "page": 3,
          "section": 3,
          "parent_label": "3.3 Type of Ceiling",
          "zoho_column": "ceiling_roof",
          "db_column": "ceiling_roof",
          "is_jsonb_array": True
        },
        {
          "label": "3.3 Type of Ceiling — Tiled",
          "type": "checkbox",
          "page": 3,
          "section": 3,
          "parent_label": "3.3 Type of Ceiling",
          "zoho_column": "ceiling_tiled",
          "db_column": "ceiling_tiled",
          "is_jsonb_array": True
        },
        {
          "label": "3.3 Type of Ceiling — Asbestos / Sheet",
          "type": "checkbox",
          "page": 3,
          "section": 3,
          "parent_label": "3.3 Type of Ceiling",
          "zoho_column": "ceiling_asbestos",
          "db_column": "ceiling_asbestos",
          "is_jsonb_array": True
        },
        {
          "label": "3.3 Type of Ceiling — Concrete",
          "type": "checkbox",
          "page": 3,
          "section": 3,
          "parent_label": "3.3 Type of Ceiling",
          "zoho_column": "ceiling_concrete",
          "db_column": "ceiling_concrete",
          "is_jsonb_array": True
        },
        {
          "label": "3.4 Number of Bedrooms",
          "type": "text",
          "page": 3,
          "section": 3,
          "numeric_only": True,
          "zoho_column": "number_of_bedrooms",
          "db_column": "number_of_bedrooms"
        },
        {
          "label": "3.4.1 Type of Bedroom — Separate Bedroom",
          "type": "radio",
          "page": 3,
          "section": 3,
          "mutually_exclusive_with": [
            "3.4.1 Type of Bedroom — No Separate Bedroom"
          ],
          "zoho_column": "type_of_bedroom",
          "db_column": "type_of_bedroom",
          "is_yes_no_pair": True
        },
        {
          "label": "3.4.1 Type of Bedroom — No Separate Bedroom",
          "type": "radio",
          "page": 3,
          "section": 3,
          "mutually_exclusive_with": [
            "3.4.1 Type of Bedroom — Separate Bedroom"
          ]
        },
        {
          "label": "3.5 Bathroom - Separate",
          "type": "radio",
          "page": 3,
          "section": 3,
          "mutually_exclusive_with": [
            "3.5 Bathroom - Common for Apartment"
          ],
          "zoho_column": "bathroom",
          "db_column": "bathroom",
          "is_yes_no_pair": True
        },
        {
          "label": "3.5 Bathroom - Common for Apartment",
          "type": "radio",
          "page": 3,
          "section": 3,
          "mutually_exclusive_with": [
            "3.5 Bathroom - Separate"
          ]
        },
        {
          "label": "3.6 Kitchen Type — Separate Kitchen",
          "type": "radio",
          "page": 3,
          "section": 3,
          "mutually_exclusive_with": [
            "3.6 Kitchen Type — Hall with Kitchen"
          ],
          "zoho_column": "kitchen_type",
          "db_column": "kitchen_type"
        },
        {
          "label": "3.6 Kitchen Type — Hall with Kitchen",
          "type": "radio",
          "page": 3,
          "section": 3,
          "mutually_exclusive_with": [
            "3.6 Kitchen Type — Separate Kitchen"
          ]
        }
      ],
      "tables": []
    },
    {
      "number": 4,
      "name": "Financial Background",
      "pages": [
        3,
        4,
        5
      ],
      "fields": [
        {
          "label": "4.1 Assets at Home",
          "type": "checkbox",
          "page": 3,
          "section": 4,
          "options": []
        },
        {
          "label": "4.1 Assets at Home(tick all that apply) - Washing Machine",
          "type": "checkbox",
          "page": 3,
          "section": 4,
          "parent_label": "4.1 Assets at Home",
          "zoho_column": "assets_washing_machine",
          "db_column": "assets_washing_machine",
          "is_jsonb_array": True
        },
        {
          "label": "4.1 Assets at Home(tick all that apply) - Fridge",
          "type": "checkbox",
          "page": 3,
          "section": 4,
          "parent_label": "4.1 Assets at Home",
          "zoho_column": "assets_fridge",
          "db_column": "assets_fridge",
          "is_jsonb_array": True
        },
        {
          "label": "4.1 Assets at Home(tick all that apply) - AC",
          "type": "checkbox",
          "page": 3,
          "section": 4,
          "parent_label": "4.1 Assets at Home",
          "zoho_column": "assets_ac",
          "db_column": "assets_ac",
          "is_jsonb_array": True
        },
        {
          "label": "4.1 Assets at Home(tick all that apply) - LED TV",
          "type": "checkbox",
          "page": 3,
          "section": 4,
          "parent_label": "4.1 Assets at Home",
          "zoho_column": "assets_led_tv",
          "db_column": "assets_led_tv",
          "is_jsonb_array": True
        },
        {
          "label": "4.1 Assets at Home(tick all that apply) - Two-Wheeler",
          "type": "checkbox",
          "page": 3,
          "section": 4,
          "parent_label": "4.1 Assets at Home",
          "zoho_column": "assets_two_wheeler",
          "db_column": "assets_two_wheeler",
          "is_jsonb_array": True
        },
        {
          "label": "4.1 Assets at Home(tick all that apply) - Car",
          "type": "checkbox",
          "page": 3,
          "section": 4,
          "parent_label": "4.1 Assets at Home",
          "zoho_column": "assets_car",
          "db_column": "assets_car",
          "is_jsonb_array": True
        },
        {
          "label": "4.1 Assets at Home(tick all that apply) - Smartphone",
          "type": "checkbox",
          "page": 3,
          "section": 4,
          "parent_label": "4.1 Assets at Home",
          "zoho_column": "assets_smartphone",
          "db_column": "assets_smartphone",
          "is_jsonb_array": True
        },
        {
          "label": "4.1 Assets at Home(tick all that apply) - Separate Wi-Fi",
          "type": "checkbox",
          "page": 3,
          "section": 4,
          "parent_label": "4.1 Assets at Home",
          "zoho_column": "assets_wifi",
          "db_column": "assets_wifi",
          "is_jsonb_array": True
        },
        {
          "label": "4.1 Assets at Home(tick all that apply) - Others:",
          "type": "checkbox",
          "page": 3,
          "section": 4,
          "parent_label": "4.1 Assets at Home",
          "zoho_column": "assets_others",
          "db_column": "assets_others",
          "is_jsonb_array": True
        },
        {
          "label": "4.1 Assets at Home(tick all that apply) - Others (specify):",
          "type": "specify",
          "page": 3,
          "section": 4,
          "parent_option_label": "Others:",
          "parent_label": "4.1 Assets at Home",
          "zoho_column": "assets_others_specify",
          "db_column": "assets_others_specify"
        },
        {
          "label": "4.2 Amount of Last Electricity Bill",
          "type": "text",
          "page": 3,
          "section": 4,
          "zoho_column": "electricity_bill_amount",
          "db_column": "electricity_bill_amount"
        },
        {
          "label": "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes",
          "type": "radio",
          "page": 3,
          "section": 4,
          "mutually_exclusive_with": [
            "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — No"
          ],
          "is_yes_no_pair": True,
          "zoho_column": "owns_other_assets",
          "db_column": "owns_other_assets"
        },
        {
          "label": "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — No",
          "type": "radio",
          "page": 3,
          "section": 4,
          "mutually_exclusive_with": [
            "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes"
          ]
        },
        {
          "label": "4.3.1 If Yes, list their properties:",
          "type": "table_header",
          "page": 3,
          "section": 4,
          "table_header_label": "4.3.1 If Yes, list their properties:",
          "conditional_parent": "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes",
          "conditional_value": "Yes"
        },
        {
          "label": "4.4 Apart from your job, is there any other source of income? — Yes",
          "type": "radio",
          "page": 4,
          "section": 4,
          "mutually_exclusive_with": [
            "4.4 Apart from your job, is there any other source of income? — No"
          ],
          "is_yes_no_pair": True,
          "zoho_column": "has_other_income",
          "db_column": "has_other_income"
        },
        {
          "label": "4.4 Apart from your job, is there any other source of income? — No",
          "type": "radio",
          "page": 4,
          "section": 4,
          "mutually_exclusive_with": [
            "4.4 Apart from your job, is there any other source of income? — Yes"
          ]
        },
        {
          "label": "4.4.1 If Yes, list other sources of income:",
          "type": "table_header",
          "page": 4,
          "section": 4,
          "table_header_label": "4.4.1 If Yes, list other sources of income:",
          "conditional_parent": "4.4 Apart from your job, is there any other source of income? — Yes",
          "conditional_value": "Yes"
        },
        {
          "label": "4.5 Income Type",
          "type": "checkbox",
          "page": 4,
          "section": 4,
          "options": []
        },
        {
          "label": "4.5 Income Type — Monthly",
          "type": "checkbox",
          "page": 4,
          "section": 4,
          "parent_label": "4.5 Income Type",
          "zoho_column": "income_type_monthly",
          "db_column": "income_type_monthly",
          "is_jsonb_array": True
        },
        {
          "label": "4.5 Income Type — Monthly (specify)",
          "type": "specify",
          "page": 4,
          "section": 4,
          "parent_option_label": "Monthly",
          "parent_label": "4.5 Income Type",
          "zoho_column": "income_type_monthly_specify",
          "db_column": "income_type_monthly_specify"
        },
        {
          "label": "4.5 Income Type — Daily",
          "type": "checkbox",
          "page": 4,
          "section": 4,
          "parent_label": "4.5 Income Type",
          "zoho_column": "income_type_daily",
          "db_column": "income_type_daily",
          "is_jsonb_array": True
        },
        {
          "label": "4.5 Income Type — Daily (specify)",
          "type": "specify",
          "page": 4,
          "section": 4,
          "parent_option_label": "Daily",
          "parent_label": "4.5 Income Type",
          "zoho_column": "income_type_daily_specify",
          "db_column": "income_type_daily_specify"
        },
        {
          "label": "4.5 Income Type — Weekly",
          "type": "checkbox",
          "page": 4,
          "section": 4,
          "parent_label": "4.5 Income Type",
          "zoho_column": "income_type_weekly",
          "db_column": "income_type_weekly",
          "is_jsonb_array": True
        },
        {
          "label": "4.5 Income Type — Weekly (specify)",
          "type": "specify",
          "page": 4,
          "section": 4,
          "parent_option_label": "Weekly",
          "parent_label": "4.5 Income Type",
          "zoho_column": "income_type_weekly_specify",
          "db_column": "income_type_weekly_specify"
        },
        {
          "label": "4.5 Income Type — Ad-Hoc",
          "type": "checkbox",
          "page": 4,
          "section": 4,
          "parent_label": "4.5 Income Type",
          "zoho_column": "income_type_adhoc",
          "db_column": "income_type_adhoc",
          "is_jsonb_array": True
        },
        {
          "label": "4.5 Income Type — Ad-Hoc (specify)",
          "type": "specify",
          "page": 4,
          "section": 4,
          "parent_option_label": "Ad-Hoc",
          "parent_label": "4.5 Income Type",
          "zoho_column": "income_type_adhoc_specify",
          "db_column": "income_type_adhoc_specify"
        },
        {
          "label": "4.6 Do you have any loans? — Yes",
          "type": "radio",
          "page": 4,
          "section": 4,
          "mutually_exclusive_with": [
            "4.6 Do you have any loans? — No"
          ],
          "is_yes_no_pair": True,
          "zoho_column": "has_loans",
          "db_column": "has_loans"
        },
        {
          "label": "4.6 Do you have any loans? — No",
          "type": "radio",
          "page": 4,
          "section": 4,
          "mutually_exclusive_with": [
            "4.6 Do you have any loans? — Yes"
          ]
        },
        {
          "label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
          "type": "table_header",
          "page": 4,
          "section": 4,
          "table_header_label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
          "conditional_parent": "4.6 Do you have any loans? — Yes",
          "conditional_value": "Yes"
        },
        {
          "label": "4.7 If you choose any college, how much is the college fee?",
          "type": "text",
          "page": 5,
          "section": 4,
          "zoho_column": "college_fee",
          "db_column": "college_fee"
        },
        {
          "label": "4.8 If the college fee is higher, how will you manage it?",
          "type": "text",
          "page": 5,
          "section": 4,
          "zoho_column": "manage_higher_fee",
          "db_column": "manage_higher_fee"
        },
        {
          "label": "4.9 If you do not receive this scholarship, how will you pay the fees?",
          "type": "text",
          "page": 5,
          "section": 4,
          "zoho_column": "manage_without_scholarship",
          "db_column": "manage_without_scholarship"
        },
        {
          "label": "4.3.1 If Yes, list their properties: — Row 1 — Property Description",
          "type": "table_row",
          "page": 3,
          "section": 4,
          "table_header_label": "4.3.1 If Yes, list their properties:",
          "row_index": 1,
          "column_name": "Property Description"
        },
        {
          "label": "4.3.1 If Yes, list their properties: — Row 1 — Owner Name",
          "type": "table_row",
          "page": 3,
          "section": 4,
          "table_header_label": "4.3.1 If Yes, list their properties:",
          "row_index": 1,
          "column_name": "Owner Name"
        },
        {
          "label": "4.3.1 If Yes, list their properties: — Row 1 — Approximate Value",
          "type": "table_row",
          "page": 3,
          "section": 4,
          "table_header_label": "4.3.1 If Yes, list their properties:",
          "row_index": 1,
          "column_name": "Approximate Value"
        },
        {
          "label": "4.3.1 If Yes, list their properties: — Row 2 — Property Description",
          "type": "table_row",
          "page": 3,
          "section": 4,
          "table_header_label": "4.3.1 If Yes, list their properties:",
          "row_index": 2,
          "column_name": "Property Description"
        },
        {
          "label": "4.3.1 If Yes, list their properties: — Row 2 — Owner Name",
          "type": "table_row",
          "page": 3,
          "section": 4,
          "table_header_label": "4.3.1 If Yes, list their properties:",
          "row_index": 2,
          "column_name": "Owner Name"
        },
        {
          "label": "4.3.1 If Yes, list their properties: — Row 2 — Approximate Value",
          "type": "table_row",
          "page": 3,
          "section": 4,
          "table_header_label": "4.3.1 If Yes, list their properties:",
          "row_index": 2,
          "column_name": "Approximate Value"
        },
        {
          "label": "4.3.1 If Yes, list their properties: — Row 3 — Property Description",
          "type": "table_row",
          "page": 3,
          "section": 4,
          "table_header_label": "4.3.1 If Yes, list their properties:",
          "row_index": 3,
          "column_name": "Property Description"
        },
        {
          "label": "4.3.1 If Yes, list their properties: — Row 3 — Owner Name",
          "type": "table_row",
          "page": 3,
          "section": 4,
          "table_header_label": "4.3.1 If Yes, list their properties:",
          "row_index": 3,
          "column_name": "Owner Name"
        },
        {
          "label": "4.3.1 If Yes, list their properties: — Row 3 — Approximate Value",
          "type": "table_row",
          "page": 3,
          "section": 4,
          "table_header_label": "4.3.1 If Yes, list their properties:",
          "row_index": 3,
          "column_name": "Approximate Value"
        },
        {
          "label": "4.3.1 If Yes, list their properties: — Row 4 — Property Description",
          "type": "table_row",
          "page": 3,
          "section": 4,
          "table_header_label": "4.3.1 If Yes, list their properties:",
          "row_index": 4,
          "column_name": "Property Description"
        },
        {
          "label": "4.3.1 If Yes, list their properties: — Row 4 — Owner Name",
          "type": "table_row",
          "page": 3,
          "section": 4,
          "table_header_label": "4.3.1 If Yes, list their properties:",
          "row_index": 4,
          "column_name": "Owner Name"
        },
        {
          "label": "4.3.1 If Yes, list their properties: — Row 4 — Approximate Value",
          "type": "table_row",
          "page": 3,
          "section": 4,
          "table_header_label": "4.3.1 If Yes, list their properties:",
          "row_index": 4,
          "column_name": "Approximate Value"
        },
        {
          "label": "4.4.1 If Yes, list other sources of income: — Row 1 — Source of Income",
          "type": "table_row",
          "page": 4,
          "section": 4,
          "table_header_label": "4.4.1 If Yes, list other sources of income:",
          "row_index": 1,
          "column_name": "Source of Income"
        },
        {
          "label": "4.4.1 If Yes, list other sources of income: — Row 1 — Amount",
          "type": "table_row",
          "page": 4,
          "section": 4,
          "table_header_label": "4.4.1 If Yes, list other sources of income:",
          "row_index": 1,
          "column_name": "Amount"
        },
        {
          "label": "4.4.1 If Yes, list other sources of income: — Row 2 — Source of Income",
          "type": "table_row",
          "page": 4,
          "section": 4,
          "table_header_label": "4.4.1 If Yes, list other sources of income:",
          "row_index": 2,
          "column_name": "Source of Income"
        },
        {
          "label": "4.4.1 If Yes, list other sources of income: — Row 2 — Amount",
          "type": "table_row",
          "page": 4,
          "section": 4,
          "table_header_label": "4.4.1 If Yes, list other sources of income:",
          "row_index": 2,
          "column_name": "Amount"
        },
        {
          "label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount: — Row 1 — Sr.No.",
          "type": "table_row",
          "page": 4,
          "section": 4,
          "table_header_label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
          "row_index": 1,
          "column_name": "Sr.No."
        },
        {
          "label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount: — Row 1 — Loan Purpose",
          "type": "table_row",
          "page": 4,
          "section": 4,
          "table_header_label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
          "row_index": 1,
          "column_name": "Loan Purpose"
        },
        {
          "label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount: — Row 1 — Loan Amount Taken",
          "type": "table_row",
          "page": 4,
          "section": 4,
          "table_header_label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
          "row_index": 1,
          "column_name": "Loan Amount Taken"
        },
        {
          "label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount: — Row 1 — Pending Loan Amount",
          "type": "table_row",
          "page": 4,
          "section": 4,
          "table_header_label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
          "row_index": 1,
          "column_name": "Pending Loan Amount"
        },
        {
          "label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount: — Row 2 — Sr.No.",
          "type": "table_row",
          "page": 4,
          "section": 4,
          "table_header_label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
          "row_index": 2,
          "column_name": "Sr.No."
        },
        {
          "label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount: — Row 2 — Loan Purpose",
          "type": "table_row",
          "page": 4,
          "section": 4,
          "table_header_label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
          "row_index": 2,
          "column_name": "Loan Purpose"
        },
        {
          "label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount: — Row 2 — Loan Amount Taken",
          "type": "table_row",
          "page": 4,
          "section": 4,
          "table_header_label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
          "row_index": 2,
          "column_name": "Loan Amount Taken"
        },
        {
          "label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount: — Row 2 — Pending Loan Amount",
          "type": "table_row",
          "page": 4,
          "section": 4,
          "table_header_label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
          "row_index": 2,
          "column_name": "Pending Loan Amount"
        },
        {
          "label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount: — Row 3 — Sr.No.",
          "type": "table_row",
          "page": 4,
          "section": 4,
          "table_header_label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
          "row_index": 3,
          "column_name": "Sr.No."
        },
        {
          "label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount: — Row 3 — Loan Purpose",
          "type": "table_row",
          "page": 4,
          "section": 4,
          "table_header_label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
          "row_index": 3,
          "column_name": "Loan Purpose"
        },
        {
          "label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount: — Row 3 — Loan Amount Taken",
          "type": "table_row",
          "page": 4,
          "section": 4,
          "table_header_label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
          "row_index": 3,
          "column_name": "Loan Amount Taken"
        },
        {
          "label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount: — Row 3 — Pending Loan Amount",
          "type": "table_row",
          "page": 4,
          "section": 4,
          "table_header_label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
          "row_index": 3,
          "column_name": "Pending Loan Amount"
        }
      ],
      "tables": [
        {
          "header_label": "4.3.1 If Yes, list their properties:",
          "columns": [
            {
              "name": "Property Description",
              "type": "text"
            },
            {
              "name": "Owner Name",
              "type": "text"
            },
            {
              "name": "Approximate Value",
              "type": "numeric"
            }
          ],
          "row_count": 4,
          "blank_area_pages": [
            3,
            4
          ]
        },
        {
          "header_label": "4.4.1 If Yes, list other sources of income:",
          "columns": [
            {
              "name": "Source of Income",
              "type": "text"
            },
            {
              "name": "Amount",
              "type": "numeric"
            }
          ],
          "row_count": 2
        },
        {
          "header_label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:",
          "columns": [
            {
              "name": "Sr.No.",
              "type": "numeric"
            },
            {
              "name": "Loan Purpose",
              "type": "text"
            },
            {
              "name": "Loan Amount Taken",
              "type": "numeric"
            },
            {
              "name": "Pending Loan Amount",
              "type": "numeric"
            }
          ],
          "row_count": 3
        }
      ]
    },
    {
      "number": 5,
      "name": "Health Information",
      "pages": [
        5
      ],
      "fields": [
        {
          "label": "5.1 Does the student have any health issues? — Yes",
          "type": "radio",
          "page": 5,
          "section": 5,
          "mutually_exclusive_with": [
            "5.1 Does the student have any health issues? — No"
          ],
          "is_yes_no_pair": True,
          "zoho_column": "has_health_issues",
          "db_column": "has_health_issues"
        },
        {
          "label": "5.1 Does the student have any health issues? — No",
          "type": "radio",
          "page": 5,
          "section": 5,
          "mutually_exclusive_with": [
            "5.1 Does the student have any health issues? — Yes"
          ]
        },
        {
          "label": "5.2 If yes, list the health issues",
          "type": "text",
          "page": 5,
          "section": 5,
          "conditional_parent": "5.1 Does the student have any health issues? — Yes",
          "conditional_value": "Yes",
          "zoho_column": "health_issues_description",
          "db_column": "health_issues_description"
        }
      ],
      "tables": []
    },
    {
      "number": 6,
      "name": "Student Commitment",
      "pages": [
        5,
        6
      ],
      "fields": [
        {
          "label": "6.1 Will you study college for three years without any obstacle?",
          "type": "text",
          "page": 5,
          "section": 6,
          "zoho_column": "study_commitment",
          "db_column": "study_commitment"
        },
        {
          "label": "6.2 If we have a training program within 15 km from your home, can you come?",
          "type": "radio",
          "page": 5,
          "section": 6,
          "options": [
            {
              "label": "Yes",
              "value": "Yes"
            },
            {
              "label": "No",
              "value": "No"
            },
            {
              "label": "Maybe",
              "value": "Maybe"
            }
          ],
          "zoho_column": "training_program_availability",
          "db_column": "training_program_availability"
        },
        {
          "label": "6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)?",
          "type": "radio",
          "page": 6,
          "section": 6,
          "options": [
            {
              "label": "Yes",
              "value": "Yes"
            },
            {
              "label": "No",
              "value": "No"
            }
          ],
          "zoho_column": "ready_for_skill_classes",
          "db_column": "ready_for_skill_classes"
        }
      ],
      "tables": []
    },
    {
      "number": 7,
      "name": "Scholarship Information",
      "pages": [
        6
      ],
      "fields": [
        {
          "label": "7.1 Has the student received or applied for any other scholarships for their UG degree?",
          "type": "text",
          "page": 6,
          "section": 7,
          "zoho_column": "other_scholarships",
          "db_column": "other_scholarships"
        }
      ],
      "tables": []
    },
    {
      "number": 8,
      "name": "Volunteer Observation",
      "pages": [
        6
      ],
      "fields": [
        {
          "label": "8.1 What is your opinion about the student, their family members, and their living condition?",
          "type": "text",
          "page": 6,
          "section": 8,
          "zoho_column": "volunteer_opinion",
          "db_column": "volunteer_opinion"
        },
        {
          "label": "8.2 Will you recommend this student for this scholarship?",
          "type": "radio",
          "page": 6,
          "section": 8,
          "options": [
            {
              "label": "Yes",
              "value": "Yes"
            },
            {
              "label": "No",
              "value": "No"
            },
            {
              "label": "Not Sure",
              "value": "Not Sure"
            }
          ],
          "zoho_column": "recommend_student",
          "db_column": "recommend_student"
        },
        {
          "label": "8.3 Any other comments you want to share?",
          "type": "text",
          "page": 6,
          "section": 8,
          "zoho_column": "volunteer_comments",
          "db_column": "volunteer_comments"
        }
      ],
      "tables": []
    }
  ]
}

def radio_opts(*values: str) -> List[Dict[str, str]]:
    return [{"label": v, "value": v} for v in values]

def checkbox_opt(label: str, value: str) -> Dict[str, str]:
    return {"label": label, "value": value}

def getAllFields(schema: Dict[str, Any]) -> List[Dict]:
    return [f for s in schema["sections"] for f in s["fields"]]

def getTableHeaders(schema: Dict) -> List[Dict]:
    return [f for s in schema["sections"] for f in s["fields"] if f["type"] == "table_header"]

def getTableDefinitions(schema: Dict) -> List[Dict]:
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
            table = next((t for s in FORM_SCHEMA["sections"] for t in s["tables"] if t["header_label"] == field.get("table_header_label")), None)
            if not table:
                errors.append(f"Table header references non-existent table: {field.get('table_header_label')}")
    return len(errors) == 0, errors
