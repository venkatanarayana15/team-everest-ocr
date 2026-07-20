"""SQLAlchemy models for the OCR documents table."""

from sqlalchemy import Column, String, Text, Boolean, Numeric, DateTime, UUID, JSON, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class OCRDocument(Base):
    """OCR Document model matching the ocr_documents table."""

    __tablename__ = "ocr_documents"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    file_name = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="pending")
    job_id = Column(Text, unique=True)
    processing_time = Column(Numeric)
    confidence_score = Column(Numeric)
    num_pdfs = Column(Numeric)
    result_json = Column(JSON, nullable=True)
    num_pdfs = Column("num_pdfs", Numeric)

    # Header fields
    volunteer_name = Column(Text)
    co_volunteer_name = Column(Text)
    date_of_visit = Column(Text)

    # Section 1: Student Profile
    application_id = Column(Text)
    student_full_name = Column(Text)
    gender = Column(Text)

    # Section 2: Family Background
    family_status = Column(Text)
    relationship_death_year = Column(Text)
    relationship_death_reason = Column(Text)
    photograph_kept_at_home = Column(Text)  # Was BOOLEAN, now TEXT per migration v2
    government_id_verified = Column(JSONB)
    family_members = Column(JSONB)

    # Section 3: Housing Condition
    house_ownership = Column(Text)
    rent_amount = Column(Text)
    type_of_home = Column(Text)  # Was JSONB, now TEXT per migration v2
    type_of_ceiling = Column(Text)  # Was JSONB, now TEXT per migration v6
    number_of_bedrooms = Column(Text)
    type_of_bedroom = Column(Text)
    bathroom = Column(Text)
    kitchen_type = Column(Text)  # Was JSONB, now TEXT per migration v2

    # Section 4: Financial Background
    assets_at_home = Column(JSONB)
    electricity_bill_amount = Column(Text)
    owns_other_assets = Column(Text)  # Was BOOLEAN, now TEXT per migration v2
    other_assets_details = Column(JSONB)
    has_other_income = Column(Text)  # Was BOOLEAN, now TEXT per migration v2
    other_income_sources = Column(JSONB)
    income_type = Column(Text)
    has_loans = Column(Text)  # Was BOOLEAN, now TEXT per migration v2
    loan_details = Column(JSONB)
    college_fee = Column(Text)
    manage_higher_fee = Column(Text)
    manage_without_scholarship = Column(Text)

    # Section 5: Health Information
    has_health_issues = Column(Text)  # Was BOOLEAN, now TEXT per migration v2
    health_issues_description = Column(Text)

    # Section 6: Student Commitment
    study_commitment = Column(Text)
    training_program_availability = Column(Text)
    ready_for_skill_classes = Column(Text)  # Was BOOLEAN, now TEXT per migration v2

    # Section 7: Scholarship Information
    other_scholarships = Column(Text)

    # Section 8: Volunteer Observation
    volunteer_opinion = Column(Text)
    recommend_student = Column(Text)
    volunteer_comments = Column(Text)

    # Ambiguity tracking
    ambiguous_fields = Column(JSONB, default={})

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    processed_at = Column(DateTime(timezone=True))

    # Relationship for relationship_details
    relationship_details = Column(JSONB, default=[])

    def __repr__(self):
        return f"<OCRDocument(id={self.id}, file_name={self.file_name}, status={self.status})>"