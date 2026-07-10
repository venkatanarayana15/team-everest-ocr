-- OCR Questionnaire Extraction — PostgreSQL/Supabase Schema
-- Run this in Supabase SQL Editor to create the production table.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS ocr_documents (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- File metadata
    file_name       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',

    -- Processing metadata
    job_id          TEXT,
    file_hash       TEXT,
    processing_time DOUBLE PRECISION,
    confidence_score DOUBLE PRECISION,
    num_pdfs        INTEGER,
    result_json     JSONB,

    -- ── Header fields (section = null) ──
    volunteer_name              TEXT,
    co_volunteer_name           TEXT,
    date_of_visit               TEXT,

    -- ── Section 1: Student Profile ──
    application_id              TEXT,
    student_full_name           TEXT,
    gender                      TEXT,

    -- ── Section 2: Family Background ──
    family_status               TEXT,
    relationship_death_year     TEXT,
    relationship_death_reason   TEXT,
    photograph_kept_at_home     BOOLEAN,
    government_id_verified      JSONB,
    family_members              JSONB,

    -- ── Section 3: Housing Condition ──
    house_ownership             TEXT,
    rent_amount                 TEXT,
    type_of_home                JSONB,
    type_of_ceiling             JSONB,
    number_of_bedrooms          TEXT,
    type_of_bedroom             TEXT,
    bathroom                    TEXT,
    kitchen_type                JSONB,

    -- ── Section 4: Financial Background ──
    assets_at_home              JSONB,
    last_electricity_bill_amount TEXT,
    owns_other_assets           BOOLEAN,
    other_assets_details        JSONB,
    has_other_income            BOOLEAN,
    other_income_sources        JSONB,
    income_type                 TEXT,
    has_loans                   TEXT,
    loan_details                JSONB,
    college_fee                 TEXT,
    manage_higher_fee           TEXT,
    manage_without_scholarship  TEXT,

    -- ── Section 5: Health Information ──
    has_health_issues           BOOLEAN,
    health_issues_description   TEXT,

    -- ── Section 6: Student Commitment ──
    study_commitment            TEXT,
    training_program_availability TEXT,
    ready_for_skill_classes     TEXT,

    -- ── Section 7: Scholarship Information ──
    other_scholarships          TEXT,

    -- ── Section 8: Volunteer Observation ──
    volunteer_opinion           TEXT,
    recommend_student           TEXT,
    volunteer_comments          TEXT,

    -- Timestamps
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

-- Backfill job_id for rows created before the column was populated
UPDATE ocr_documents SET job_id = result_json->>'job_id'
    WHERE job_id IS NULL AND result_json IS NOT NULL;

-- Unique constraint for idempotent upsert
-- NOTE: Must be a real UNIQUE constraint (not a partial index) so that
-- ON CONFLICT (job_id) works in asyncpg/PostgreSQL.
ALTER TABLE ocr_documents
    ADD CONSTRAINT uq_ocr_documents_job_id UNIQUE (job_id);

ALTER TABLE ocr_documents
    ADD CONSTRAINT uq_ocr_documents_file_hash UNIQUE (file_hash);

-- Trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ocr_documents_updated_at ON ocr_documents;
CREATE TRIGGER trg_ocr_documents_updated_at
    BEFORE UPDATE ON ocr_documents
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
