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
    file_hash = Column(Text, unique=True)
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
    photograph_notes = Column(Text)  # 2.3 follow-up notes field
    gov_id_other_specify = Column(Text)  # 2.4 Other (specify)
    gov_id_aadhaar = Column(Text)
    gov_id_ration = Column(Text)
    gov_id_voter = Column(Text)
    gov_id_driving = Column(Text)
    gov_id_other = Column(Text)
    government_id_verified = Column(JSONB)
    family_members = Column(JSONB)

    # Section 3: Housing Condition
    house_ownership = Column(Text)
    rent_amount = Column(Text)
    type_of_home = Column(Text)  # Was JSONB, now TEXT per migration v2
    home_type_individual = Column(Text)
    home_type_apartment = Column(Text)
    home_type_housing_board = Column(Text)
    home_type_line_house = Column(Text)
    home_type_others = Column(Text)
    home_type_others_specify = Column(Text)
    type_of_ceiling = Column(Text)  # Was JSONB, now TEXT per migration v6
    ceiling_roof = Column(Text)
    ceiling_tiled = Column(Text)
    ceiling_asbestos = Column(Text)
    ceiling_concrete = Column(Text)
    number_of_bedrooms = Column(Text)
    type_of_bedroom = Column(Text)
    bathroom = Column(Text)
    kitchen_type = Column(Text)  # Was JSONB, now TEXT per migration v2

    # Section 4: Financial Background
    assets_at_home = Column(JSONB)
    assets_ac = Column(Text)
    assets_smartphone = Column(Text)
    assets_washing_machine = Column(Text)
    assets_car = Column(Text)
    assets_led_tv = Column(Text)
    assets_fridge = Column(Text)
    assets_wifi = Column(Text)
    assets_two_wheeler = Column(Text)
    assets_others = Column(Text)
    assets_others_specify = Column(Text)
    electricity_bill_amount = Column(Text)
    owns_other_assets = Column(Text)  # Was BOOLEAN, now TEXT per migration v2
    other_assets_details = Column(JSONB)
    has_other_income = Column(Text)  # Was BOOLEAN, now TEXT per migration v2
    other_income_sources = Column(JSONB)
    income_type = Column(Text)
    income_type_monthly = Column(Text)
    income_type_weekly = Column(Text)
    income_type_daily = Column(Text)
    income_type_adhoc = Column(Text)
    income_type_monthly_specify = Column(Text)
    income_type_weekly_specify = Column(Text)
    income_type_daily_specify = Column(Text)
    income_type_adhoc_specify = Column(Text)
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