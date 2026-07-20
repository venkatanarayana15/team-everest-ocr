from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal, Any, Dict


class StructuredField(BaseModel):
    """Structured field extracted from form with hierarchy metadata."""
    label: str = ""
    value: str = ""
    confidence: int = Field(default=0, ge=0, le=100)
    page: int = 1
    section_number: Optional[int] = None
    bbox: Optional[List[int]] = None
    value_bbox: Optional[List[int]] = None
    needs_clarification: bool = False
    reason: Optional[str] = None
    is_verified: bool = False
    verifier_confidence: Optional[int] = None
    verification_note: Optional[str] = None
    extracted_by: Optional[str] = None
    verified_by: Optional[str] = None
    original_value: Optional[str] = None
    is_edited: bool = False
    position_hint: Optional[str] = None
    
    # Hierarchy fields (populated by backend enrichment)
    parent_label: Optional[str] = None
    field_type: Optional[Literal["text", "radio", "checkbox", "table_row", "table_header", "specify"]] = None
    group_id: Optional[str] = None
    row_index: Optional[int] = None
    column_name: Optional[str] = None

    @field_validator("confidence")
    @classmethod
    def confidence_must_be_valid(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("confidence must be between 0 and 100")
        return v


class ExtractionResponse(BaseModel):
    """Response from primary LLM extraction."""
    fields: List[StructuredField] = []
    sections: List[Dict[str, Any]] = []
    overall_confidence: int = 0
    coverage: Optional[int] = None
    confidence: Optional[int] = None
    num_pages: int = 0
    processing_time: Optional[float] = None
    primary_model: str = ""
    secondary_model: str = ""
    token_usage: Optional[Dict[str, Any]] = None
    pdf_times: Optional[Dict[str, float]] = None
    batch: bool = False
    num_pdfs: Optional[int] = None
    pdf_names: Optional[List[str]] = None
    raw_text: str = ""
    overall_confidence: Optional[int] = None
    coverage: Optional[int] = None
    confidence: Optional[int] = None
    clarification_needed: List[str] = []
    raw_text: str = ""
    markdown_output: str = ""

    model_config = {
        "extra": "allow"
    }


class VerificationResult(BaseModel):
    """Result from secondary verification."""
    verifications: List[Dict[str, Any]] = []
    new_fields: List[StructuredField] = []

    model_config = {
        "extra": "allow"
    }


class JobResult(BaseModel):
    """Complete job result for API response."""
    overall_confidence: int
    coverage: Optional[int] = None
    confidence: Optional[int] = None
    num_pages: int
    processing_time: Optional[float] = None
    fields: List[StructuredField] = []
    sections: List[Dict[str, Any]] = []
    raw_text: str = ""
    primary_model: str = ""
    secondary_model: str = ""
    token_usage: Optional[Dict[str, Any]] = None
    pdf_times: Optional[Dict[str, float]] = None
    batch: bool = False
    num_pdfs: Optional[int] = None
    pdf_names: Optional[List[str]] = None


# Type alias for backwards compatibility
FieldDict = Dict[str, Any]


def validate_field_dict(data: dict) -> StructuredField:
    """Validate a raw field dict and return StructuredField or raise."""
    return StructuredField.model_validate(data)


def validate_fields_list(data: list[dict]) -> list[StructuredField]:
    """Validate a list of raw field dicts."""
    return [validate_field_dict(d) for d in data]


def to_dict(field: StructuredField) -> dict:
    """Convert StructuredField to dict for JSON serialization."""
    return field.model_dump(exclude_none=False)