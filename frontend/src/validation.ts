import { z } from 'zod';
import type { Field, Section } from './types';

// Field hierarchy field types
export const FieldTypeSchema = z.enum([
  'text',
  'radio',
  'checkbox',
  'table_row',
  'table_header',
  'specify'
]);

export const BBoxSchema = z
  .tuple([z.number(), z.number(), z.number(), z.number()])
  .nullable();

export const FieldSchema = z.object({
  label: z.string(),
  value: z.string().nullable(),
  confidence: z.number().int().min(0).max(100),
  page: z.number().int().positive(),
  section_number: z.number().int().nullable(),
  bbox: BBoxSchema,
  value_bbox: BBoxSchema,
  needs_clarification: z.boolean(),
  reason: z.string().nullable(),
  is_verified: z.boolean(),
  verifier_confidence: z.number().int().min(0).max(100).nullable(),
  verification_note: z.string().nullable(),
  extracted_by: z.string().nullable(),
  verified_by: z.string().nullable(),
  original_value: z.string().nullable(),
  is_edited: z.boolean().optional(),
  position_hint: z.string().optional(),
  
  // Hierarchy fields
  parent_label: z.string().nullable().optional(),
  field_type: FieldTypeSchema.nullable().optional(),
  group_id: z.string().nullable().optional(),
  row_index: z.number().int().positive().nullable().optional(),
column_name: z.string().nullable().optional(),
}).passthrough(); // Allow extra fields for future extensibility

export const SectionSchema = z.object({
  number: z.number().int().nullable(),
  name: z.string(),
  page: z.number().int().positive(),
});

export const JobResultSchema = z.object({
  overall_confidence: z.number().int().min(0).max(100),
  coverage: z.number().int().min(0).max(100).optional(),
  confidence: z.number().int().min(0).max(100).optional(),
  num_pages: z.number().int().positive(),
  processing_time: z.number().optional(),
  fields: z.array(FieldSchema),
  sections: z.array(SectionSchema),
  raw_text: z.string(),
  primary_model: z.string(),
  secondary_model: z.string(),
  token_usage: z.object({
    primary: z.object({
      prompt_tokens: z.number(),
      completion_tokens: z.number(),
      total_tokens: z.number(),
    }),
    secondary: z.object({
      prompt_tokens: z.number(),
      completion_tokens: z.number(),
      total_tokens: z.number(),
    }),
    total: z.object({
      prompt_tokens: z.number(),
      completion_tokens: z.number(),
      total_tokens: z.number(),
    }),
  }).optional(),
  pdf_times: z.record(z.string(), z.number()).optional(),
  batch: z.boolean().optional(),
  num_pdfs: z.number().int().optional(),
  pdf_names: z.array(z.string()).optional(),
  input_type: z.string().optional(),
}).passthrough();

export type ValidatedField = z.infer<typeof FieldSchema>;
export type ValidatedJobResult = z.infer<typeof JobResultSchema>;

export function validateField(data: unknown): ValidatedField {
  return FieldSchema.parse(data);
}

export function validateFields(data: unknown): ValidatedField[] {
  return z.array(FieldSchema).parse(data);
}

export function validateJobResult(data: unknown): ValidatedJobResult {
  return JobResultSchema.parse(data);
}