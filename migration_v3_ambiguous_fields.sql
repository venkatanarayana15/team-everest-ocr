-- Migration v3: Add ambiguous_fields column for human review flagging
-- Stores mark resolution ambiguity details as JSONB when checkbox marks
-- could not be confidently resolved.

ALTER TABLE ocr_documents
    ADD COLUMN IF NOT EXISTS ambiguous_fields JSONB DEFAULT '{}';

COMMENT ON COLUMN ocr_documents.ambiguous_fields IS
    'Stores checkbox mark resolution ambiguity details. '
    'Keys are field names, values describe the ambiguity reason. '
    'Non-empty means the field value may be incorrect and needs human review.';
