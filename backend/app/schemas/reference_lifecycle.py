from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.validation import ValidationResult, WindowedValidationMetadata


class BoundReferenceMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    river_id: Literal["kaveri", "tungabhadra"]
    candidate_product_id: str = Field(min_length=1, max_length=512)
    candidate_sensor: Literal["NISAR", "SENTINEL-1"]
    candidate_acquisition_datetime: datetime
    candidate_processing_version: str | None = Field(default=None, min_length=1, max_length=256)
    reference_dataset_id: str = Field(min_length=1, max_length=256)
    reference_source: str = Field(min_length=1, max_length=2000)
    reference_acquisition_datetime: datetime | None = None
    provenance: str = Field(min_length=1, max_length=4000)

    @field_validator(
        "candidate_product_id", "reference_dataset_id",
        "reference_source", "provenance",
    )
    @classmethod
    def require_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Text must not be blank.")
        return value.strip()

    @field_validator("candidate_processing_version")
    @classmethod
    def require_version_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Processing version must not be blank; use null if unknown.")
        return value.strip() if value is not None else None

    @field_validator("candidate_acquisition_datetime", "reference_acquisition_datetime")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Acquisition timestamps must include a timezone.")
        return value

    @field_validator("reference_source")
    @classmethod
    def reject_secret_bearing_urls(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme and (parsed.query or parsed.fragment or parsed.username or parsed.password):
            raise ValueError("Reference source URLs must not contain credentials, query strings or fragments.")
        return value


class ReviewAction(BaseModel):
    action: Literal["request_review", "attest", "reject", "withdraw"]
    declared_reviewer: str | None = Field(default=None, max_length=256)
    declaration: str | None = Field(default=None, max_length=4000)
    scope: str | None = Field(default=None, max_length=4000)
    evidence: str | None = Field(default=None, max_length=4000)
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def check_action_details(self):
        if self.action == "attest" and any(
            not value or not value.strip()
            for value in (self.declared_reviewer, self.declaration, self.scope)
        ):
            raise ValueError("Attestation requires a declared reviewer, declaration and review scope.")
        if self.action in {"reject", "withdraw"} and (not self.reason or not self.reason.strip()):
            raise ValueError("A reason is required for rejection or withdrawal.")
        return self


class ReferenceReviewEvent(BaseModel):
    previous_status: str | None
    new_status: str
    recorded_at: datetime
    action: str
    details: dict[str, str | None]


class BoundReferenceRecord(BaseModel):
    reference_id: str
    metadata: BoundReferenceMetadata
    candidate_sha256: str
    reference_sha256: str
    reference_crs: str
    reference_width: int
    reference_height: int
    reference_transform: list[float]
    reference_resolution_m: list[float]
    label_counts: dict[str, int]
    nodata_value: int
    imported_at: datetime
    review_status: Literal["imported", "review_pending", "attestation_recorded", "rejected", "withdrawn"]
    review_history: list[ReferenceReviewEvent]
    identity_verification: Literal["operator_declared_not_authenticated"] = "operator_declared_not_authenticated"
    limitations: list[str]


class CandidateIdentity(BaseModel):
    river_id: Literal["kaveri", "tungabhadra"]
    candidate_product_id: str = Field(min_length=1, max_length=512)
    candidate_sensor: Literal["NISAR", "SENTINEL-1"]
    candidate_acquisition_datetime: datetime
    candidate_processing_version: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("candidate_product_id", "candidate_processing_version")
    @classmethod
    def require_nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Text must not be blank.")
        return value.strip() if value is not None else None

    @field_validator("candidate_acquisition_datetime")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Acquisition timestamp must include a timezone.")
        return value


class ReferenceEligibility(BaseModel):
    reference_id: str
    checked_at: datetime
    candidate_identity: CandidateIdentity
    review_status: str
    identity_review_checks_passed: bool
    reasons: list[str]
    candidate_sha256: str
    reference_sha256: str
    limitations: list[str]


class BoundAssessmentReservation(BaseModel):
    assessment_id: str
    reference_id: str
    state: Literal["assessment_reserved", "evaluation_rejected"]
    created_at: datetime
    updated_at: datetime
    candidate_sha256: str
    reference_sha256: str
    metadata: WindowedValidationMetadata
    reference_at_reservation: BoundReferenceRecord
    reason: str | None = None
    limitations: list[str] = Field(default_factory=lambda: [
        "Reservation only: evaluation, report generation and recovery are not implemented.",
        "Reference review, independence and candidate identity are operator-declared and unauthenticated.",
    ])


class BoundAssessmentEvent(BaseModel):
    previous_state: str | None
    new_state: str
    recorded_at: datetime
    reason: str


class BoundAssessmentCalculation(BaseModel):
    reservation: BoundAssessmentReservation
    calculated_at: datetime
    result: ValidationResult
    limitations: list[str] = Field(default_factory=lambda: [
        "Calculation only; no evaluation or report has been published.",
        "Reference review, independence and candidate identity are operator-declared and unauthenticated.",
    ])
