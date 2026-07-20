#!/usr/bin/env node
/**
 * Code Generation Script for Form Schema
 * Generates all derived artifacts from form_schema.ts
 * Run with: npx ts-node scripts/generate_schema.ts
 */

import * as fs from 'fs';
import * as path from 'path';

// Import the schema - we'll need to compile TypeScript first or use a JSON representation
// For now, let's create a JSON version of the schema that both Python and Node can use

const SCHEMA_VERSION = '1.0.0';
const FORM_NAME = 'I Am The Change — Home Visit Questionnaire';
const TOTAL_PAGES = 6;

// ============================================================================
// SCHEMA DEFINITION (mirrors form_schema.ts)
// ============================================================================

interface FieldOption {
  label: string;
  value: string;
}

interface TableColumn {
  name: string;
  type: 'text' | 'numeric' | 'enum';
  enumValues?: string[];
}

interface TableDefinition {
  headerLabel: string;
  columns: { name: string; type: 'text' | 'numeric' | 'enum'; enumValues?: string[] }[];
  rowCount: number;
  blankAreaPages?: number[];
}

interface FieldDefinition {
  label: string;
  type: 'text' | 'radio' | 'checkbox' | 'table_row' | 'table_header' | 'specify';
  page: number;
  section: number | null;
  options?: { label: string; value: string }[];
  mutuallyExclusiveWith?: string[];
  tableHeaderLabel?: string;
  rowIndex?: number;
  columnName?: string;
  isSpecify?: boolean;
  parentOptionLabel?: string;
  parentLabel?: string;
  conditionalParent?: string;
  conditionalValue?: string;
  required?: boolean;
  numericOnly?: boolean;
  allowedValues?: string[];
  zohoColumn?: string;
  dbColumn?: string;
  isJsonbArray?: boolean;
  isSingleSelect?: boolean;
  isYesNoPair?: boolean;
  skipIfEmpty?: boolean;
}

interface TableDefinitionFull {
  headerLabel: string;
  columns: { name: string; type: 'text' | 'numeric' | 'enum'; enumValues?: string[] }[];
  rowCount: number;
  blankAreaPages?: number[];
}

interface SectionDefinition {
  number: number | null;
  name: string;
  pages: number[];
  fields: FieldDefinition[];
  tables: TableDefinitionFull[];
}

interface FormSchema {
  version: string;
  formName: string;
  totalPages: number;
  sections: SectionDefinition[];
}

// Include the full schema definition here
// (In production, you'd import from a shared JSON file)

const FORM_SCHEMA = {
  version: '1.0.0',
  formName: 'I Am The Change — Home Visit Questionnaire',
  totalPages: 6,
  sections: [
    {
      number: 1,
      name: 'Student Profile',
      pages: [1],
      fields: [
        { label: '1.1 Application ID', type: 'text', page: 1, section: 1, required: true, zohoColumn: 'application_id', dbColumn: 'application_id' },
        { label: '1.2 Student Full Name', type: 'text', page: 1, section: 1, required: true, zohoColumn: 'student_full_name', dbColumn: 'student_full_name' },
        { label: '1.3 Gender', type: 'radio', page: 1, section: 1, required: true, options: [{label:'Male',value:'Male'},{label:'Female',value:'Female'},{label:'Others',value:'Others'}], zohoColumn: 'gender', dbColumn: 'gender' },
      ],
      tables: [],
    },
    {
      number: 2,
      name: 'Family Background',
      pages: [1, 2],
      fields: [
        { label: '2.1 Family Status', type: 'radio', page: 1, section: 2, required: true, options: [{label:'Having both parents',value:'Having both parents'},{label:'Single Parent',value:'Single Parent'},{label:'Parentless',value:'Parentless'}], zohoColumn: 'family_status', dbColumn: 'family_status' },
        { label: '2.2 Relationship Details — Year of Death / Separation', type: 'text', page: 1, section: 2, numericOnly: true, zohoColumn: 'relationship_death_year', dbColumn: 'relationship_death_year' },
        { label: '2.2 Relationship Details — Reason for Death / Separation', type: 'text', page: 1, section: 2, zohoColumn: 'relationship_death_reason', dbColumn: 'relationship_death_reason' },
        { label: '2.3 Is Father/Mother photograph kept at home?', type: 'radio', page: 2, section: 2, required: true, options: [{label:'Yes',value:'Yes'},{label:'No',value:'No'}], zohoColumn: 'photograph_kept_at_home', dbColumn: 'photograph_kept_at_home' },
        { label: '2.3 Is Father/Mother photograph kept at home? — Notes', type: 'text', page: 2, section: 2, zohoColumn: 'photograph_notes', dbColumn: 'photograph_notes' },
        { label: '2.4 Government ID Verified', type: 'checkbox', page: 2, section: 2, options: [] },
        { label: '2.4 Government ID Verified — Aadhaar Card', type: 'checkbox', page: 2, section: 2, parentLabel: '2.4 Government ID Verified', zohoColumn: 'gov_id_aadhaar', dbColumn: 'gov_id_aadhaar', isJsonbArray: true },
        { label: '2.4 Government ID Verified — Ration Card', type: 'checkbox', page: 2, section: 2, parentLabel: '2.4 Government ID Verified', zohoColumn: 'gov_id_ration', dbColumn: 'gov_id_ration', isJsonbArray: true },
        { label: '2.4 Government ID Verified — Driving Licence', type: 'checkbox', page: 2, section: 2, parentLabel: '2.4 Government ID Verified', zohoColumn: 'gov_id_driving', dbColumn: 'gov_id_driving', isJsonbArray: true },
        { label: '2.4 Government ID Verified — Voter ID', type: 'checkbox', page: 2, section: 2, parentLabel: '2.4 Government ID Verified', zohoColumn: 'gov_id_voter', dbColumn: 'gov_id_voter', isJsonbArray: true },
        { label: '2.4 Government ID Verified — Other', type: 'checkbox', page: 2, section: 2, parentLabel: '2.4 Government ID Verified', zohoColumn: 'gov_id_other', dbColumn: 'gov_id_other', isJsonbArray: true },
        { label: '2.4 Government ID Verified — Other (specify)', type: 'specify', page: 2, section: 2, parentOptionLabel: 'Other', parentLabel: '2.4 Government ID Verified', zohoColumn: 'gov_id_other_specify', dbColumn: 'gov_id_other_specify' },
        { label: '2.5 Family Members', type: 'table_header', page: 2, section: 2, tableHeaderLabel: '2.5 Family Members' },
      ],
      tables: [{
        headerLabel: '2.5 Family Members',
        columns: [
          { name: 'Name', type: 'text' },
          { name: 'Age', type: 'numeric' },
          { name: 'Education', type: 'text' },
          { name: 'Occupation', type: 'text' },
          { name: 'Annual Income', type: 'numeric' },
        ],
        rowCount: 5,
        blankAreaPages: [2],
      }],
    },
    // ... (abbreviated for brevity - full schema would be here)
  ],
};

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

function getAllFields(schema: any) {
  return schema.sections.flatMap(s => s.fields);
}

function getTableHeaders(schema: any) {
  return schema.sections.flatMap(s => s.fields.filter(f => f.type === 'table_header'));
}

function getAllFieldsRecursive(schema: any) {
  return schema.sections.flatMap(s => s.fields);
}

function validateSchema(schema: any) {
  const errors: string[] = [];
  const labels = new Set<string>();
  
  for (const field of getAllFieldsRecursive(schema)) {
    if (labels.has(field.label)) {
      throw new Error(`Duplicate field label: ${field.label}`);
    }
    labels.add(field.label);
  }
  return true;
}

// ============================================================================
// GENERATORS
// ============================================================================

function generatePromptFieldList(schema: any): { [page: number]: string } {
  const mappings: { [page: number]: string } = {};
  
  for (let pageNum = 1; pageNum <= 6; pageNum++) {
    const pageFields = getAllFieldsRecursive(schema).filter(f => f.page === pageNum);
    if (!pageFields.length) continue;
    
    const sections: { [key: number]: any[] } = {};
    for (const f of pageFields) {
      const sec = f.section;
      if (!sections[sec]) sections[sec] = [];
      sections[sec].push(f);
    }
    
    const lines: string[] = [];
    const sectionNames: { [key: number]: string } = {
      1: 'Student Profile', 2: 'Family Background', 3: 'Housing Condition',
      4: 'Financial Background', 5: 'Health Information', 6: 'Student Commitment',
      7: 'Scholarship Information', 8: 'Volunteer Observation',
    };
    
    // Header fields first
    const headerFields = pageFields.filter(f => f.section === null);
    if (headerFields.length) {
      lines.push(`--- Header (Page 1, section=null) — ${headerFields.length} fields ---`);
      for (const f of headerFields) {
        lines.push(`  ${f.label}  [text]`);
      }
    }
    
    for (const secNum of Object.keys(sections).map(Number).sort((a,b)=>a-b)) {
      const secFields = sections[secNum];
      const secName = sectionNames[secNum] || `Section ${secNum}`;
      lines.push(`--- Section ${secNum} — ${secName} (Page ${pageNum}) — ${secFields.length} fields ---`);
      
      for (const f of secFields) {
        if (f.type === 'table_header') continue;
        let fieldType = '';
        if (f.type === 'radio') {
          const opts = (f.options || []).map(o => o.value).join(' | ');
          fieldType = `[radio → ${opts}]`;
        } else if (f.type === 'checkbox') {
          fieldType = '[checkbox — ✓ if checked, ✗ if empty]';
        } else if (f.type === 'specify') {
          fieldType = '[text — free-text next to parent checkbox]';
        } else {
          fieldType = '[text]';
        }
        const cond = f.conditionalParent ? `  // CONDITIONAL: only if '${f.conditionalParent}' = '${f.conditionalValue}'` : '';
        lines.push(`  ${f.label}  ${fieldType}${cond}`);
      }
    }
    
    return lines.join('\n');
  }
}

function generateKnownTemplateFields(schema: any) {
  const fields = [];
  for (const f of getAllFieldsRecursive(schema)) {
    if (f.type === 'specify') continue;
    fields.push({
      label: f.label,
      section_number: f.section,
      page: f.page,
      field_type: f.type,
      zoho_column: f.zohoColumn,
      db_column: f.dbColumn,
    });
  }
  return fields;
}

function generateZohoMappings(schema: any) {
  const mapping: { [key: string]: string } = {};
  for (const f of getAllFieldsRecursive(schema)) {
    if (f.zohoColumn) {
      mapping[f.label] = f.zohoColumn;
    }
  }
  return mapping;
}

function generateKnownTemplateFieldsTS(schema: any): string {
  const lines: string[] = [];
  for (const f of getAllFieldsRecursive(schema)) {
    if (f.type === 'specify') continue;
    lines.push(`  {"label": "${f.label}", "section_number": ${f.section === null ? 'null' : f.section}, "page": ${f.page}},`);
  }
  return lines.join('\n');
}

function generateTypesTS(): string {
  return `// Generated from form_schema.ts - DO NOT EDIT MANUALLY
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
`;
}

// ============================================================================
// MAIN
// ============================================================================

function main() {
  console.log('Validating schema...');
  validateSchema(FORM_SCHEMA);
  console.log('Schema validation passed!');
  
  console.log('\nGenerating artifacts...');
  
  // Generate PAGE_FIELD_MAPPINGS
  const pageMappings: { [page: number]: string } = {};
  for (let pageNum = 1; pageNum <= 6; pageNum++) {
    const pageFields = getAllFieldsRecursive(FORM_SCHEMA).filter(f => f.page === pageNum);
    if (!pageFields.length) continue;
    
    const sections: { [key: number]: any[] } = {};
    for (const f of pageFields) {
      const sec = f.section;
      if (!sections[sec]) sections[sec] = [];
      sections[sec].push(f);
    }
    
    const lines: string[] = [];
    const sectionNames: { [key: number]: string } = {
      1: 'Student Profile', 2: 'Family Background', 3: 'Housing Condition',
      4: 'Financial Background', 5: 'Health Information', 6: 'Student Commitment',
      7: 'Scholarship Information', 8: 'Volunteer Observation',
    };
    
    const headerFields = pageFields.filter(f => f.section === null);
    if (headerFields.length) {
      lines.push(`--- Header (Page 1, section=null) — ${headerFields.length} fields ---`);
      for (const f of headerFields) {
        lines.push(`  ${f.label}  [text]`);
      }
    }
    
    for (const secNum of Object.keys(sections).map(Number).sort((a,b)=>a-b)) {
      const secFields = sections[secNum];
      const secName = sectionNames[secNum] || `Section ${secNum}`;
      lines.push(`--- Section ${secNum} — ${secName} (Page ${pageNum}) — ${secFields.length} fields ---`);
      
      for (const f of secFields) {
        if (f.type === 'table_header') continue;
        let fieldType = '';
        if (f.type === 'radio') {
          const opts = (f.options || []).map(o => o.value).join(' | ');
          fieldType = `[radio → ${opts}]`;
        } else if (f.type === 'checkbox') {
          fieldType = '[checkbox — ✓ if checked, ✗ if empty]';
        } else if (f.type === 'specify') {
          fieldType = '[text — free-text next to parent checkbox]';
        } else {
          fieldType = '[text]';
        }
        const cond = f.conditionalParent ? `  // CONDITIONAL: only if '${f.conditionalParent}' = '${f.conditionalValue}'` : '';
        lines.push(`  ${f.label}  ${fieldType}${cond}`);
      }
    }
    
    // TODO: Complete the script
    console.log('Script needs completion - run "npx ts-node scripts/generate_schema.ts" after fixing');
    process.exit(1);
}

main();