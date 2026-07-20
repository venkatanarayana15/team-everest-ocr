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
  // Mutually-exclusive radio groups (e.g. 3.1, 4.3) collapsed into one Field:
  // the original member child fields, used to fan a single selection out to siblings.
  mutexMembers?: Field[];
  // For "specify" follow-up fields: the option label this text input belongs to
  // (e.g. "Others" for "3.2 Type of Home — Others (specify)").
  parent_option_label?: string | null;
  // For radio/checkbox groups: nested "specify" follow-up fields, shown inline
  // only when their associated option is selected.
  specifyChildren?: Field[];
}

export interface Section {
  number: number;
  name: string;
  page: number;
}

export interface StatusResponse {
  status: string;
  message?: string;
  log?: Array<{ t: string; msg: string }>;
  pages?: number;
}

export interface JobStatus {
  status: string;
  message?: string;
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
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
    primary: TokenUsage;
    secondary: TokenUsage;
    total: TokenUsage;
  };
  pdf_times?: Record<string, number>;
  batch?: boolean;
  num_pdfs?: number;
  pdf_names?: string[];
}

export interface JobInfo {
  job_id: string;
  status: string;
  fields: number | null;
}

export interface TesseractWord {
  text: string;
  page: number;
  bbox: [number, number, number, number];
  confidence: number;
}

export interface TesseractData {
  pages: Record<string, TesseractWord[]>;
}
