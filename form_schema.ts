/**
 * Single Source of Truth: Form Schema Definition
 * 
 * This file defines the complete form hierarchy for the 6-page Home Visit Questionnaire.
 * All downstream artifacts (prompt templates, template fields, Zoho mappings, DB columns,
 * frontend types, validation schemas) are generated from this definition.
 * 
 * Run `npm run generate:schema` (or `python scripts/generate_schema.py`) to regenerate
 * all derived artifacts after making changes here.
 */

// ============================================================================
// TYPE DEFINITIONS
// ============================================================================

export type FieldType = 
  | 'text' 
  | 'radio' 
  | 'checkbox' 
  | 'table_row' 
  | 'table_header' 
  | 'specify';

export interface FieldOption {
  label: string;           // Display label (e.g., "Aadhaar Card")
  value: string;           // Value when selected (e.g., "Aadhaar Card")
}

export interface TableColumn {
  name: string;            // Column name (e.g., "Property Description")
  type: 'text' | 'numeric' | 'enum';
  enumValues?: string[];   // For enum columns
}

export interface TableDefinition {
  headerLabel: string;     // e.g., "4.3.1 If Yes, list their properties:"
  columns: TableColumn[];
  rowCount: number;        // Pre-printed rows in form
  blankAreaPages?: number[]; // Pages with extra handwriting areas for this table
}

export interface FieldDefinition {
  label: string;           // Full label as it appears on form
  shortLabel?: string;     // Short version for UI (optional)
  type: FieldType;
  page: number;
  section: number | null;
  
  // For radio/checkbox fields
  options?: FieldOption[];
  mutuallyExclusiveWith?: string[]; // Labels of mutually exclusive options
  
  // For table rows
  tableHeaderLabel?: string; // Parent table header label
  rowIndex?: number;         // 1-based row number
  columnName?: string;       // Column name for table cells
  
  // For specify fields
  isSpecify?: boolean;
  parentOptionLabel?: string;
  
  // Conditional logic
  conditionalParent?: string; // Parent field label that controls visibility
  conditionalValue?: string;  // Value that makes this field required ("Yes")
  
  // Validation
  required?: boolean;
  numericOnly?: boolean;
  allowedValues?: string[];
  
  // Zoho/DB mapping
  zohoColumn?: string;
  dbColumn?: string;
  isJsonbArray?: boolean;
  isSingleSelect?: boolean;
  isYesNoPair?: boolean;
  skipIfEmpty?: boolean;

  // For checkbox/radio group membership
  parent_label?: string;   // Parent question label this option belongs to
}

export interface SectionDefinition {
  number: number | null;
  name: string;
  pages: number[];
  fields: FieldDefinition[];
  tables: TableDefinition[];
}

export interface FormSchema {
  version: string;
  formName: string;
  totalPages: number;
  sections: SectionDefinition[];
}

// ============================================================================
// FORM SCHEMA DEFINITION
// ============================================================================

export const FORM_SCHEMA: FormSchema = {
  version: '1.0.0',
  formName: 'I Am The Change — Home Visit Questionnaire',
  totalPages: 6,
  sections: [
    // ========================================================================
    // SECTION 1: Student Profile (Page 1)
    // ========================================================================
    {
      number: 1,
      name: 'Student Profile',
      pages: [1],
      fields: [
        {
          label: '1.1 Application ID',
          type: 'text',
          page: 1,
          section: 1,
          required: true,
          zohoColumn: 'application_id',
          dbColumn: 'application_id',
        },
        {
          label: '1.2 Student Full Name',
          type: 'text',
          page: 1,
          section: 1,
          required: true,
          zohoColumn: 'student_full_name',
          dbColumn: 'student_full_name',
        },
        {
          label: '1.3 Gender',
          type: 'radio',
          page: 1,
          section: 1,
          required: true,
          options: [
            { label: 'Male', value: 'Male' },
            { label: 'Female', value: 'Female' },
            { label: 'Others', value: 'Others' },
          ],
          zohoColumn: 'gender',
          dbColumn: 'gender',
        },
      ],
      tables: [],
    },

    // ========================================================================
    // SECTION 2: Family Background (Pages 1-2)
    // ========================================================================
    {
      number: 2,
      name: 'Family Background',
      pages: [1, 2],
      fields: [
        {
          label: '2.1 Family Status',
          type: 'radio',
          page: 1,
          section: 2,
          required: true,
          options: [
            { label: 'Having both parents', value: 'Having both parents' },
            { label: 'Single Parent', value: 'Single Parent' },
            { label: 'Parentless', value: 'Parentless' },
          ],
          zohoColumn: 'family_status',
          dbColumn: 'family_status',
        },
        // blank_text_below_2_1 is internal, not in schema
        {
          label: '2.2 Relationship Details — Year of Death / Separation',
          type: 'text',
          page: 1,
          section: 2,
          numericOnly: true,
          zohoColumn: 'relationship_death_year',
          dbColumn: 'relationship_death_year',
        },
        {
          label: '2.2 Relationship Details — Reason for Death / Separation',
          type: 'text',
          page: 1,
          section: 2,
          zohoColumn: 'relationship_death_reason',
          dbColumn: 'relationship_death_reason',
        },
        {
          label: '2.3 Is Father/Mother photograph kept at home?',
          type: 'radio',
          page: 2,
          section: 2,
          required: true,
          options: [
            { label: 'Yes', value: 'Yes' },
            { label: 'No', value: 'No' },
          ],
          zohoColumn: 'photograph_kept_at_home',
          dbColumn: 'photograph_kept_at_home',
        },
        {
          label: '2.3 Is Father/Mother photograph kept at home? — Notes',
          type: 'text',
          page: 2,
          section: 2,
        },
        // Government ID Verified - parent
        {
          label: '2.4 Government ID Verified',
          type: 'checkbox',
          page: 2,
          section: 2,
          options: [], // Options defined below
        },
        {
          label: '2.4 Government ID Verified — Aadhaar Card',
          type: 'checkbox',
          page: 2,
          section: 2,
          parent_label: '2.4 Government ID Verified',
        },
        {
          label: '2.4 Government ID Verified — Ration Card',
          type: 'checkbox',
          page: 2,
          section: 2,
          parent_label: '2.4 Government ID Verified',
        },
        {
          label: '2.4 Government ID Verified — Driving Licence',
          type: 'checkbox',
          page: 2,
          section: 2,
          parent_label: '2.4 Government ID Verified',
        },
        {
          label: '2.4 Government ID Verified — Voter ID',
          type: 'checkbox',
          page: 2,
          section: 2,
          parent_label: '2.4 Government ID Verified',
        },
        {
          label: '2.4 Government ID Verified — Other',
          type: 'checkbox',
          page: 2,
          section: 2,
          parent_label: '2.4 Government ID Verified',
        },
        {
          label: '2.4 Government ID Verified — Other (specify)',
          type: 'specify',
          page: 2,
          section: 2,
          parentOptionLabel: 'Other',
          parent_label: '2.4 Government ID Verified',
        },
        // Family Members Table
        {
          label: '2.5 Family Members',
          type: 'table_header',
          page: 2,
          section: 2,
          tableHeaderLabel: '2.5 Family Members',
        },
      ],
      tables: [
        {
          headerLabel: '2.5 Family Members',
          columns: [
            { name: 'Name', type: 'text' },
            { name: 'Age', type: 'numeric' },
            { name: 'Education', type: 'text' },
            { name: 'Occupation', type: 'text' },
            { name: 'Annual Income', type: 'numeric' },
          ],
          rowCount: 5, // 4 pre-printed + 1 extra for handwritten
          blankAreaPages: [2],
        },
      ],
    },

    // ========================================================================
    // SECTION 3: Housing Condition (Pages 2-3)
    // ========================================================================
    {
      number: 3,
      name: 'Housing Condition',
      pages: [2, 3],
      fields: [
        // House Ownership (mutually exclusive pair)
        {
          label: '3.1 House Ownership — Own',
          type: 'radio',
          page: 2,
          section: 3,
          mutuallyExclusiveWith: ['3.1 House Ownership — Rented'],
          zohoColumn: 'house_ownership',
          dbColumn: 'house_ownership',
          isYesNoPair: true,
        },
        {
          label: '3.1 House Ownership — Rented',
          type: 'radio',
          page: 2,
          section: 3,
          mutuallyExclusiveWith: ['3.1 House Ownership — Own'],
          isYesNoPair: true,
        },
        {
          label: '3.1.1 If rented, what is the rent amount?',
          type: 'text',
          page: 2,
          section: 3,
          conditionalParent: '3.1 House Ownership — Rented',
          conditionalValue: 'Yes',
          zohoColumn: 'rent_amount',
          dbColumn: 'rent_amount',
        },
        // Type of Home (single-select)
        {
          label: '3.2 Type of Home',
          type: 'radio',
          page: 2,
          section: 3,
          options: [], // options below
        },
        {
          label: '3.2 Type of Home — Individual',
          type: 'radio',
          page: 2,
          section: 3,
          parent_label: '3.2 Type of Home',
        },
        {
          label: '3.2 Type of Home — Private Apartment',
          type: 'radio',
          page: 2,
          section: 3,
          parent_label: '3.2 Type of Home',
        },
        {
          label: '3.2 Type of Home — Housing Board',
          type: 'radio',
          page: 2,
          section: 3,
          parent_label: '3.2 Type of Home',
        },
        {
          label: '3.2 Type of Home — Line House',
          type: 'radio',
          page: 2,
          section: 3,
          parent_label: '3.2 Type of Home',
        },
        {
          label: '3.2 Type of Home — Others',
          type: 'radio',
          page: 2,
          section: 3,
          parent_label: '3.2 Type of Home',
        },
        {
          label: '3.2 Type of Home — Others (specify)',
          type: 'specify',
          page: 2,
          section: 3,
          parentOptionLabel: 'Others',
          parent_label: '3.2 Type of Home',
        },
        // Type of Ceiling (single-select)
        {
          label: '3.3 Type of Ceiling',
          type: 'radio',
          page: 3,
          section: 3,
          options: [],
        },
        {
          label: '3.3 Type of Ceiling — Roof (Kurai)',
          type: 'radio',
          page: 3,
          section: 3,
          parent_label: '3.3 Type of Ceiling',
        },
        {
          label: '3.3 Type of Ceiling — Tiled',
          type: 'radio',
          page: 3,
          section: 3,
          parent_label: '3.3 Type of Ceiling',
        },
        {
          label: '3.3 Type of Ceiling — Asbestos / Sheet',
          type: 'radio',
          page: 3,
          section: 3,
          parent_label: '3.3 Type of Ceiling',
        },
        {
          label: '3.3 Type of Ceiling — Concrete',
          type: 'radio',
          page: 3,
          section: 3,
          parent_label: '3.3 Type of Ceiling',
        },
        // Number of Bedrooms
        {
          label: '3.4 Number of Bedrooms',
          type: 'text',
          page: 3,
          section: 3,
          numericOnly: true,
          zohoColumn: 'number_of_bedrooms',
          dbColumn: 'number_of_bedrooms',
        },
        // Type of Bedroom (mutually exclusive)
        {
          label: '3.4.1 Type of Bedroom — Separate Bedroom',
          type: 'radio',
          page: 3,
          section: 3,
          mutuallyExclusiveWith: ['3.4.1 Type of Bedroom — No Separate Bedroom'],
          zohoColumn: 'type_of_bedroom',
          dbColumn: 'type_of_bedroom',
          isYesNoPair: true,
        },
        {
          label: '3.4.1 Type of Bedroom — No Separate Bedroom',
          type: 'radio',
          page: 3,
          section: 3,
          mutuallyExclusiveWith: ['3.4.1 Type of Bedroom — Separate Bedroom'],
        },
        // Bathroom (mutually exclusive)
        {
          label: '3.5 Bathroom - Separate',
          type: 'radio',
          page: 3,
          section: 3,
          mutuallyExclusiveWith: ['3.5 Bathroom - Common for Apartment'],
          zohoColumn: 'bathroom',
          dbColumn: 'bathroom',
          isYesNoPair: true,
        },
        {
          label: '3.5 Bathroom - Common for Apartment',
          type: 'radio',
          page: 3,
          section: 3,
          mutuallyExclusiveWith: ['3.5 Bathroom - Separate'],
        },
        // Kitchen Type
        {
          label: '3.6 Kitchen Type — Separate Kitchen',
          type: 'radio',
          page: 3,
          section: 3,
          mutuallyExclusiveWith: ['3.6 Kitchen Type — Hall with Kitchen'],
          zohoColumn: 'kitchen_type',
          dbColumn: 'kitchen_type',
        },
        {
          label: '3.6 Kitchen Type — Hall with Kitchen',
          type: 'radio',
          page: 3,
          section: 3,
          mutuallyExclusiveWith: ['3.6 Kitchen Type — Separate Kitchen'],
        },
      ],
      tables: [],
    },

    // ========================================================================
    // SECTION 4: Financial Background (Pages 3-5)
    // ========================================================================
    {
      number: 4,
      name: 'Financial Background',
      pages: [3, 4, 5],
      fields: [
        // Assets at Home (multi-select with specify)
        {
          label: '4.1 Assets at Home',
          type: 'checkbox',
          page: 3,
          section: 4,
          options: [],
        },
        {
          label: '4.1 Assets at Home(tick all that apply) - Washing Machine',
          type: 'checkbox',
          page: 3,
          section: 4,
          parent_label: '4.1 Assets at Home',
        },
        {
          label: '4.1 Assets at Home(tick all that apply) - Fridge',
          type: 'checkbox',
          page: 3,
          section: 4,
          parent_label: '4.1 Assets at Home',
        },
        {
          label: '4.1 Assets at Home(tick all that apply) - AC',
          type: 'checkbox',
          page: 3,
          section: 4,
          parent_label: '4.1 Assets at Home',
        },
        {
          label: '4.1 Assets at Home(tick all that apply) - LED TV',
          type: 'checkbox',
          page: 3,
          section: 4,
          parent_label: '4.1 Assets at Home',
        },
        {
          label: '4.1 Assets at Home(tick all that apply) - Two-Wheeler',
          type: 'checkbox',
          page: 3,
          section: 4,
          parent_label: '4.1 Assets at Home',
        },
        {
          label: '4.1 Assets at Home(tick all that apply) - Car',
          type: 'checkbox',
          page: 3,
          section: 4,
          parent_label: '4.1 Assets at Home',
        },
        {
          label: '4.1 Assets at Home(tick all that apply) - Smartphone',
          type: 'checkbox',
          page: 3,
          section: 4,
          parent_label: '4.1 Assets at Home',
        },
        {
          label: '4.1 Assets at Home(tick all that apply) - Separate Wi-Fi',
          type: 'checkbox',
          page: 3,
          section: 4,
          parent_label: '4.1 Assets at Home',
        },
        {
          label: '4.1 Assets at Home(tick all that apply) - Others:',
          type: 'checkbox',
          page: 3,
          section: 4,
          parent_label: '4.1 Assets at Home',
        },
        {
          label: '4.1 Assets at Home(tick all that apply) - Others (specify):',
          type: 'specify',
          page: 3,
          section: 4,
          parentOptionLabel: 'Others:',
          parent_label: '4.1 Assets at Home',
        },
        // Electricity Bill
        {
          label: '4.2 Amount of Last Electricity Bill',
          type: 'text',
          page: 3,
          section: 4,
          zohoColumn: 'electricity_bill_amount',
          dbColumn: 'electricity_bill_amount',
        },
        // Own Other Assets (mutually exclusive)
        {
          label: '4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes',
          type: 'radio',
          page: 3,
          section: 4,
          mutuallyExclusiveWith: ['4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — No'],
          isYesNoPair: true,
          zohoColumn: 'owns_other_assets',
          dbColumn: 'owns_other_assets',
        },
        {
          label: '4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — No',
          type: 'radio',
          page: 3,
          section: 4,
          mutuallyExclusiveWith: ['4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes'],
          conditionalValue: 'No',
        },
        // 4.3.1 Table (conditional)
        {
          label: '4.3.1 If Yes, list their properties:',
          type: 'table_header',
          page: 3,
          section: 4,
          tableHeaderLabel: '4.3.1 If Yes, list their properties:',
          conditionalParent: '4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes',
          conditionalValue: 'Yes',
        },
        // 4.4 Other Income Source (single radio, rendered like 8.2)
        {
          label: '4.4 Apart from your job, is there any other source of income?',
          type: 'radio',
          page: 4,
          section: 4,
          options: [
            { label: 'Yes', value: 'Yes' },
            { label: 'No', value: 'No' },
          ],
          zohoColumn: 'has_other_income',
          dbColumn: 'has_other_income',
        },
        // 4.4.1 Table (conditional)
        {
          label: '4.4.1 If Yes, list other sources of income:',
          type: 'table_header',
          page: 4,
          section: 4,
          tableHeaderLabel: '4.4.1 If Yes, list other sources of income:',
          conditionalParent: '4.4 Apart from your job, is there any other source of income?',
          conditionalValue: 'Yes',
        },
        // Income Type (multi-select with specify)
        {
          label: '4.5 Income Type',
          type: 'checkbox',
          page: 4,
          section: 4,
          options: [],
        },
        {
          label: '4.5 Income Type — Monthly',
          type: 'checkbox',
          page: 4,
          section: 4,
          parent_label: '4.5 Income Type',
        },
        {
          label: '4.5 Income Type — Monthly (specify)',
          type: 'specify',
          page: 4,
          section: 4,
          parentOptionLabel: 'Monthly',
          parent_label: '4.5 Income Type',
        },
        {
          label: '4.5 Income Type — Daily',
          type: 'checkbox',
          page: 4,
          section: 4,
          parent_label: '4.5 Income Type',
        },
        {
          label: '4.5 Income Type — Daily (specify)',
          type: 'specify',
          page: 4,
          section: 4,
          parentOptionLabel: 'Daily',
          parent_label: '4.5 Income Type',
        },
        {
          label: '4.5 Income Type — Weekly',
          type: 'checkbox',
          page: 4,
          section: 4,
          parent_label: '4.5 Income Type',
        },
        {
          label: '4.5 Income Type — Weekly (specify)',
          type: 'specify',
          page: 4,
          section: 4,
          parentOptionLabel: 'Weekly',
          parent_label: '4.5 Income Type',
        },
        {
          label: '4.5 Income Type — Ad-Hoc',
          type: 'checkbox',
          page: 4,
          section: 4,
          parent_label: '4.5 Income Type',
        },
        {
          label: '4.5 Income Type — Ad-Hoc (specify)',
          type: 'specify',
          page: 4,
          section: 4,
          parentOptionLabel: 'Ad-Hoc',
          parent_label: '4.5 Income Type',
        },
        // Loans (single radio, like 2.3)
        {
          label: '4.6 Do you have any loans?',
          type: 'radio',
          page: 4,
          section: 4,
          required: true,
          options: [
            { label: 'Yes', value: 'Yes' },
            { label: 'No', value: 'No' },
          ],
          zohoColumn: 'has_loans',
          dbColumn: 'has_loans',
        },
        // 4.6.1 Table (conditional)
        {
          label: '4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:',
          type: 'table_header',
          page: 4,
          section: 4,
          tableHeaderLabel: '4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:',
          conditionalParent: '4.6 Do you have any loans?',
          conditionalValue: 'Yes',
        },
        // College Fee
        {
          label: '4.7 If you choose any college, how much is the college fee?',
          type: 'text',
          page: 5,
          section: 4,
          zohoColumn: 'college_fee',
          dbColumn: 'college_fee',
        },
        {
          label: '4.8 If the college fee is higher, how will you manage it?',
          type: 'text',
          page: 5,
          section: 4,
          zohoColumn: 'manage_higher_fee',
          dbColumn: 'manage_higher_fee',
        },
        {
          label: '4.9 If you do not receive this scholarship, how will you pay the fees?',
          type: 'text',
          page: 5,
          section: 4,
          zohoColumn: 'manage_without_scholarship',
          dbColumn: 'manage_without_scholarship',
        },
      ],
      tables: [
        {
          headerLabel: '4.3.1 If Yes, list their properties:',
          columns: [
            { name: 'Property Description', type: 'text' },
            { name: 'Owner Name', type: 'text' },
            { name: 'Approximate Value', type: 'numeric' },
          ],
          rowCount: 4,
          blankAreaPages: [3, 4],
        },
        {
          headerLabel: '4.4.1 If Yes, list other sources of income:',
          columns: [
            { name: 'Source of Income', type: 'text' },
            { name: 'Amount', type: 'numeric' },
          ],
          rowCount: 2,
        },
        {
          headerLabel: '4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount:',
          columns: [
            { name: 'Sr.No.', type: 'numeric' },
            { name: 'Loan Purpose', type: 'text' },
            { name: 'Loan Amount Taken', type: 'numeric' },
            { name: 'Pending Loan Amount', type: 'numeric' },
          ],
          rowCount: 3,
        },
      ],
    },

    // ========================================================================
    // SECTION 5: Health Information (Page 5)
    // ========================================================================
    {
      number: 5,
      name: 'Health Information',
      pages: [5],
      fields: [
        {
          label: '5.1 Does the student have any health issues?',
          type: 'radio',
          page: 5,
          section: 5,
          required: true,
          options: [
            { label: 'Yes', value: 'Yes' },
            { label: 'No', value: 'No' },
          ],
          zohoColumn: 'has_health_issues',
          dbColumn: 'has_health_issues',
        },
        {
          label: '5.2 If yes, list the health issues',
          type: 'text',
          page: 5,
          section: 5,
          conditionalParent: '5.1 Does the student have any health issues?',
          conditionalValue: 'Yes',
          zohoColumn: 'health_issues_description',
          dbColumn: 'health_issues_description',
        },
      ],
      tables: [],
    },

    // ========================================================================
    // SECTION 6: Student Commitment (Pages 5-6)
    // ========================================================================
    {
      number: 6,
      name: 'Student Commitment',
      pages: [5, 6],
      fields: [
        {
          label: '6.1 Will you study college for three years without any obstacle?',
          type: 'text',
          page: 5,
          section: 6,
          zohoColumn: 'study_commitment',
          dbColumn: 'study_commitment',
        },
        {
          label: '6.2 If we have a training program within 15 km from your home, can you come?',
          type: 'radio',
          page: 5,
          section: 6,
          options: [
            { label: 'Yes', value: 'Yes' },
            { label: 'No', value: 'No' },
            { label: 'Maybe', value: 'Maybe' },
          ],
          zohoColumn: 'training_program_availability',
          dbColumn: 'training_program_availability',
        },
        {
          label: '6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)?',
          type: 'radio',
          page: 6,
          section: 6,
          options: [
            { label: 'Yes', value: 'Yes' },
            { label: 'No', value: 'No' },
          ],
          zohoColumn: 'ready_for_skill_classes',
          dbColumn: 'ready_for_skill_classes',
        },
      ],
      tables: [],
    },

    // ========================================================================
    // SECTION 7: Scholarship Information (Page 6)
    // ========================================================================
    {
      number: 7,
      name: 'Scholarship Information',
      pages: [6],
      fields: [
        {
          label: '7.1 Has the student received or applied for any other scholarships for their UG degree?',
          type: 'text',
          page: 6,
          section: 7,
          zohoColumn: 'other_scholarships',
          dbColumn: 'other_scholarships',
        },
      ],
      tables: [],
    },

    // ========================================================================
    // SECTION 8: Volunteer Observation (Page 6)
    // ========================================================================
    {
      number: 8,
      name: 'Volunteer Observation',
      pages: [6],
      fields: [
        {
          label: '8.1 What is your opinion about the student, their family members, and their living condition?',
          type: 'text',
          page: 6,
          section: 8,
          zohoColumn: 'volunteer_opinion',
          dbColumn: 'volunteer_opinion',
        },
        {
          label: '8.2 Will you recommend this student for this scholarship?',
          type: 'radio',
          page: 6,
          section: 8,
          options: [
            { label: 'Yes', value: 'Yes' },
            { label: 'No', value: 'No' },
            { label: 'Not Sure', value: 'Not Sure' },
          ],
          zohoColumn: 'recommend_student',
          dbColumn: 'recommend_student',
        },
        {
          label: '8.3 Any other comments you want to share?',
          type: 'text',
          page: 6,
          section: 8,
          zohoColumn: 'volunteer_comments',
          dbColumn: 'volunteer_comments',
        },
      ],
      tables: [],
    },

    // ========================================================================
    // HEADER FIELDS (Page 1, section = null)
    // ========================================================================
    {
      number: null,
      name: 'Header',
      pages: [1],
      fields: [
        {
          label: 'Volunteer Name',
          type: 'text',
          page: 1,
          section: null,
          zohoColumn: 'volunteer_name',
          dbColumn: 'volunteer_name',
        },
        {
          label: 'Co-Volunteer Name',
          type: 'text',
          page: 1,
          section: null,
          zohoColumn: 'co_volunteer_name',
          dbColumn: 'co_volunteer_name',
        },
        {
          label: 'Date of Visit',
          type: 'text',
          page: 1,
          section: null,
          zohoColumn: 'date_of_visit',
          dbColumn: 'date_of_visit',
        },
      ],
      tables: [],
    },
  ],
};

// ============================================================================
// DERIVED DATA GENERATION FUNCTIONS
// ============================================================================

export function getAllFields(schema: FormSchema): FieldDefinition[] {
  return schema.sections.flatMap(s => s.fields);
}

export function getTableHeaders(schema: FormSchema): FieldDefinition[] {
  return schema.sections.flatMap(s => s.fields.filter(f => f.type === 'table_header'));
}

export function getTableDefinitions(schema: FormSchema): TableDefinition[] {
  return schema.sections.flatMap(s => s.tables);
}

export function getAllFieldLabels(schema: FormSchema): string[] {
  return getAllFields(schema).map(f => f.label);
}

export function getRadioPairs(schema: FormSchema): { yes: string; no: string }[] {
  const pairs: { yes: string; no: string }[] = [];
  const fields = getAllFields(schema);
  
  for (const field of fields) {
    if (field.isYesNoPair) {
      // Find the matching No option
      const noOption = fields.find(f => 
        f.label.includes(field.label.replace(' — Yes', ' — No')) ||
        f.label.includes(field.label.replace(' — Yes', ' — No'))
      );
      if (noOption) {
        pairs.push({ yes: field.label, no: noOption.label });
      }
    }
  }
  return pairs;
}

export function getMutuallyExclusiveGroups(schema: FormSchema): string[][] {
  const groups: Map<string, Set<string>> = new Map();
  
  for (const field of getAllFields(schema)) {
    if (field.mutuallyExclusiveWith) {
      for (const other of field.mutuallyExclusiveWith) {
        const key = [field.label, other].sort().join('|');
        if (!groups.has(key)) groups.set(key, new Set());
        groups.get(key)!.add(field.label);
        groups.get(key)!.add(other);
      }
    }
  }
  
  return Array.from(groups.values()).map(s => Array.from(s));
}

export function getCheckboxGroups(schema: FormSchema): { parent: string; options: string[] }[] {
  const groups: Map<string, Set<string>> = new Map();
  
  for (const field of getAllFields(schema)) {
    if (field.parent_label && field.type === 'checkbox') {
      if (!groups.has(field.parent_label)) {
        groups.set(field.parent_label, new Set());
      }
      groups.get(field.parent_label)!.add(field.label);
    }
  }
  
  return Array.from(groups.entries()).map(([parent, options]) => ({
    parent,
    options: Array.from(options),
  }));
}

// ============================================================================
// VALIDATION
// ============================================================================

export function validateSchema(schema: FormSchema): { valid: boolean; errors: string[] } {
  const errors: string[] = [];
  const labels = new Set<string>();
  
  for (const field of getAllFields(schema)) {
    // Check for duplicate labels
    if (labels.has(field.label)) {
      errors.push(`Duplicate field label: ${field.label}`);
    }
    labels.add(field.label);
    
    // Validate mutually exclusive pairs
    if (field.mutuallyExclusiveWith) {
      for (const other of field.mutuallyExclusiveWith) {
        if (!getAllFields(schema).some(f => f.label === other)) {
          errors.push(`Mutually exclusive reference not found: ${field.label} -> ${other}`);
        }
      }
    }
    
    // Validate conditional parents
    if (field.conditionalParent) {
      if (!getAllFields(schema).some(f => f.label === field.conditionalParent)) {
        errors.push(`Conditional parent not found: ${field.conditionalParent} for ${field.label}`);
      }
    }
    
    // Validate table headers
    if (field.type === 'table_header') {
      const table = schema.sections.flatMap(s => s.tables).find(t => t.headerLabel === field.tableHeaderLabel);
      if (!table) {
        errors.push(`Table header references non-existent table: ${field.tableHeaderLabel}`);
      }
    }
  }
  
  return { valid: errors.length === 0, errors };
}

// ============================================================================
// EXPORT FOR CODEGEN
// ============================================================================

export default FORM_SCHEMA;