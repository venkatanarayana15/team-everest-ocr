-- Migration v7: Drop unused child-label columns from ocr_documents
--
-- These 36 columns were defined in the schema but are never populated by
-- _extract_structured_fields() because parent-level routing dicts
-- (_JSONB_GROUP_PARENTS, _SINGLE_SELECT_PARENT, _YESNO_PARENT) consume the
-- child labels first, setting the parent JSONB / TEXT column. The child
-- columns therefore remain NULL in every row.
--
-- The data for these fields is still preserved in result_json → fields[].
--
-- For each group below, the parent column (e.g. assets_at_home, type_of_home,
-- government_id_verified, income_type) retains the aggregated value.
--
-- file_hash was also removed since it was only used for deduplication and is
-- no longer needed.

-- 1. Drop the unique constraint on file_hash first
ALTER TABLE ocr_documents DROP CONSTRAINT IF EXISTS uq_ocr_documents_file_hash;

-- 2. Section 2: Family Background
ALTER TABLE ocr_documents
    DROP COLUMN IF EXISTS photograph_notes,
    DROP COLUMN IF EXISTS gov_id_other_specify,
    DROP COLUMN IF EXISTS gov_id_aadhaar,
    DROP COLUMN IF EXISTS gov_id_ration,
    DROP COLUMN IF EXISTS gov_id_voter,
    DROP COLUMN IF EXISTS gov_id_driving,
    DROP COLUMN IF EXISTS gov_id_other;

-- 3. Section 3: Housing Condition
ALTER TABLE ocr_documents
    DROP COLUMN IF EXISTS home_type_individual,
    DROP COLUMN IF EXISTS home_type_apartment,
    DROP COLUMN IF EXISTS home_type_housing_board,
    DROP COLUMN IF EXISTS home_type_line_house,
    DROP COLUMN IF EXISTS home_type_others,
    DROP COLUMN IF EXISTS home_type_others_specify,
    DROP COLUMN IF EXISTS ceiling_roof,
    DROP COLUMN IF EXISTS ceiling_tiled,
    DROP COLUMN IF EXISTS ceiling_asbestos,
    DROP COLUMN IF EXISTS ceiling_concrete;

-- 4. Section 4: Financial Background — Assets children
ALTER TABLE ocr_documents
    DROP COLUMN IF EXISTS assets_ac,
    DROP COLUMN IF EXISTS assets_smartphone,
    DROP COLUMN IF EXISTS assets_washing_machine,
    DROP COLUMN IF EXISTS assets_car,
    DROP COLUMN IF EXISTS assets_led_tv,
    DROP COLUMN IF EXISTS assets_fridge,
    DROP COLUMN IF EXISTS assets_wifi,
    DROP COLUMN IF EXISTS assets_two_wheeler,
    DROP COLUMN IF EXISTS assets_others,
    DROP COLUMN IF EXISTS assets_others_specify;

-- 5. Section 4: Financial Background — Income Type children
ALTER TABLE ocr_documents
    DROP COLUMN IF EXISTS income_type_monthly,
    DROP COLUMN IF EXISTS income_type_weekly,
    DROP COLUMN IF EXISTS income_type_daily,
    DROP COLUMN IF EXISTS income_type_adhoc,
    DROP COLUMN IF EXISTS income_type_monthly_specify,
    DROP COLUMN IF EXISTS income_type_weekly_specify,
    DROP COLUMN IF EXISTS income_type_daily_specify,
    DROP COLUMN IF EXISTS income_type_adhoc_specify;

-- 6. Processing metadata
ALTER TABLE ocr_documents DROP COLUMN IF EXISTS file_hash;
