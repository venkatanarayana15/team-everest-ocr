-- Migration: add missing columns to ocr_documents
--
-- The form schema (form_schema.ts, the single source of truth) declares db_columns
-- that were never added to the ocr_documents table. This ALTER is idempotent and
-- safe to re-run on Supabase (prod or local).
--
-- Run in the Supabase SQL Editor (or via your migration tool) against production.

-- 2.3 "Is Father/Mother photograph kept at home? — Notes" follow-up text field.
ALTER TABLE ocr_documents
    ADD COLUMN IF NOT EXISTS photograph_notes TEXT;

-- 4.2 "Amount of Last Electricity Bill" — canonical name is electricity_bill_amount
-- (the older DDL used last_electricity_bill_amount, which does not match the code).
ALTER TABLE ocr_documents
    ADD COLUMN IF NOT EXISTS electricity_bill_amount TEXT;

-- Backfill: if a stale last_electricity_bill_amount column exists, copy it over
-- and drop the old column so the schema matches the code exactly.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'ocr_documents' AND column_name = 'last_electricity_bill_amount'
    ) THEN
        UPDATE ocr_documents
           SET electricity_bill_amount = last_electricity_bill_amount
         WHERE electricity_bill_amount IS NULL
           AND last_electricity_bill_amount IS NOT NULL;
        ALTER TABLE ocr_documents DROP COLUMN last_electricity_bill_amount;
    END IF;
END $$;

