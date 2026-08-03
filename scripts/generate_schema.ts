#!/usr/bin/env node
/**
 * Code Generation Script for Form Schema
 * Generates all derived artifacts from form_schema.ts
 * Run with: npx ts-node scripts/generate_schema.ts
 */

import * as fs from 'fs';
import * as path from 'path';

import { FORM_SCHEMA } from '../form_schema';

const SCHEMA_VERSION = FORM_SCHEMA.version;
const FORM_NAME = FORM_SCHEMA.formName;
const TOTAL_PAGES = FORM_SCHEMA.totalPages;

// ============================================================================
// SCHEMA DEFINITION (single source of truth: form_schema.ts)
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