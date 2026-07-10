-- Migration v2: Unified string fields replacing split boolean checkbox pairs
-- Run this in Supabase SQL Editor after deploying the code changes.
--
-- Changes:
--   photograph_kept_at_home  BOOLEAN → TEXT
--   owns_other_assets        BOOLEAN → TEXT
--   has_other_income         BOOLEAN → TEXT
--   has_health_issues        BOOLEAN → TEXT
--   has_loans                BOOLEAN → TEXT
--   ready_for_skill_classes  BOOLEAN → TEXT
--   kitchen_type             JSONB   → TEXT

ALTER TABLE ocr_documents
    ALTER COLUMN photograph_kept_at_home TYPE TEXT,
    ALTER COLUMN owns_other_assets       TYPE TEXT,
    ALTER COLUMN has_other_income        TYPE TEXT,
    ALTER COLUMN has_health_issues       TYPE TEXT,
    ALTER COLUMN has_loans               TYPE TEXT,
    ALTER COLUMN ready_for_skill_classes TYPE TEXT,
    ALTER COLUMN kitchen_type            TYPE TEXT;
