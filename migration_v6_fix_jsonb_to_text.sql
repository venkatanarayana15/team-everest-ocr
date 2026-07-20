-- Migration v6: Convert remaining JSONB single-select columns to TEXT
--
-- The _extract_structured_fields() code treats type_of_home and type_of_ceiling
-- as single-select radio groups and emits plain strings, but these columns were
-- JSONB in the original schema. Using a JSON string value causes PostgreSQL
-- errors like "invalid input syntax for type json" when the value contains text
-- like "Line house" (token "Line" is not valid JSON).
--
-- Changes:
--   type_of_home      JSONB → TEXT
--   type_of_ceiling   JSONB → TEXT
--
-- Uses #>>'{}' to safely extract the raw text from existing JSONB string values,
-- stripping the enclosing JSON quotes. Idempotent — safe to re-run.
-- NOTE: kitchen_type was already changed to TEXT by migration v2, so it is
-- intentionally excluded.

ALTER TABLE ocr_documents
    ALTER COLUMN type_of_home    TYPE TEXT USING type_of_home#>>'{}',
    ALTER COLUMN type_of_ceiling TYPE TEXT USING type_of_ceiling#>>'{}';
