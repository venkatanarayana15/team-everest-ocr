export interface Field {
  label: string;
  value: string;
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
  num_pages: number;
  processing_time: number;
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
