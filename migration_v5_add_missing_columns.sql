-- Migration v5: add all missing scalar columns to ocr_documents
--
-- The form_schema.ts single source of truth declares db_columns that the
-- _extract_structured_fields() code writes as standalone columns, but the
-- ocr_documents table never received these columns. This migration adds them.
--
-- All columns are TEXT to match what the Python code generates (JSON-encoded
-- arrays for checkbox groups, free-text for specify fields).
--
-- Idempotent — safe to re-run. Run in Supabase SQL Editor.

-- Section 2: Family Background — Government ID child columns
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS gov_id_aadhaar TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS gov_id_ration TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS gov_id_voter TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS gov_id_driving TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS gov_id_other TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS gov_id_other_specify TEXT;

-- Section 3: Housing Condition — Type of Home child columns
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS home_type_individual TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS home_type_apartment TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS home_type_housing_board TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS home_type_line_house TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS home_type_others TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS home_type_others_specify TEXT;

-- Section 3: Housing Condition — Type of Ceiling child columns
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS ceiling_roof TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS ceiling_tiled TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS ceiling_asbestos TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS ceiling_concrete TEXT;

-- Section 4: Financial Background — Assets at Home child columns
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS assets_ac TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS assets_smartphone TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS assets_washing_machine TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS assets_car TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS assets_led_tv TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS assets_fridge TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS assets_wifi TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS assets_two_wheeler TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS assets_others TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS assets_others_specify TEXT;

-- Section 4: Financial Background — Income Type child columns
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS income_type_monthly TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS income_type_weekly TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS income_type_daily TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS income_type_adhoc TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS income_type_monthly_specify TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS income_type_weekly_specify TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS income_type_daily_specify TEXT;
ALTER TABLE ocr_documents ADD COLUMN IF NOT EXISTS income_type_adhoc_specify TEXT;
