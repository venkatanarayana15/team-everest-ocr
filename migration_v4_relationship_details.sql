-- Migration v4: Add relationship_details column for 2.2 Relationship Details table
-- Stores structured rows as JSONB array: [{"year": "...", "reason": "..."}, ...]

ALTER TABLE ocr_documents
    ADD COLUMN IF NOT EXISTS relationship_details JSONB DEFAULT '[]';

COMMENT ON COLUMN ocr_documents.relationship_details IS
    'Relationship details section 2.2 — structured rows with '
    '"year" and "reason" columns. Stored as JSONB array of objects.';
