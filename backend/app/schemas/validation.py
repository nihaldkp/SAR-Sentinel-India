from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, computed_field, field_validator


class ValidationMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    river_id: Literal["kaveri", "tungabhadra"]
    candidate_product_id: str = Field(min_length=1, max_length=512)
    candidate_sensor: str = Field(min_length=1, max_length=80)
    candidate_acquisition_datetime: datetime
    reference_dataset_id: str = Field(min_length=1, max_length=256)
    reference_provider: str = Field(min_length=1, max_length=256)
    reference_acquisition_datetime: datetime
    reference_resolution_m: float = Field(gt=0, le=100_000)
    reviewer: str = Field(min_length=1, max_length=256)
    review_date: date
    independent_review_completed: bool = False
    reference_methodology: str = Field(min_length=1, max_length=4_000)
    limitations: list[str] = Field(min_length=1, max_length=50)
    minimum_common_pixels: int | None = Field(default=None, ge=2, le=2_000_000)
    minimum_coverage_fraction: float | None = Field(default=None, gt=0, le=1)
    minimum_pixels_per_class: int | None = Field(default=None, ge=1, le=2_000_000)
    spatial_block_size_pixels: int | None = Field(default=None, ge=1, le=2_000_000)
    minimum_blocks_per_class: int | None = Field(default=None, ge=1, le=2_000_000)

    @field_validator("reference_acquisition_datetime")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reference_acquisition_datetime must include a timezone.")
        return value

    @field_validator("candidate_acquisition_datetime")
    @classmethod
    def require_candidate_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("candidate_acquisition_datetime must include a timezone.")
        return value

    @field_validator("limitations")
    @classmethod
    def require_nonempty_limitations(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("Each limitation must contain text.")
        return value


class WindowedValidationMetadata(ValidationMetadata):
    candidate_processing_version: str = Field(min_length=1, max_length=256)


class EvaluationTransition(BaseModel):
    previous_status: str
    new_status: str
    recorded_at: datetime
    detail: str


class ValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    validation_id: str
    status: Literal[
        "reference_dataset_available",
        "insufficient_spatial_overlap",
        "insufficient_valid_labels",
        "insufficient_evidence",
        "thresholds_met_awaiting_evaluation",
        "validation_completed",
        "evaluation_failed",
        "evaluation_rejected",
    ]
    river_id: str
    candidate_product_id: str
    candidate_sensor: str
    candidate_acquisition_datetime: datetime
    reference_dataset_id: str
    reference_provider: str
    reference_acquisition_datetime: datetime
    reference_resolution_m: float
    reference_crs: str
    candidate_crs: str
    reviewer: str
    review_date: date
    independent_review_completed: bool
    reference_methodology: str
    limitations: list[str]
    confusion_matrix: dict[str, int] | None = None
    precision: float | None = Field(default=None, ge=0, le=1)
    recall: float | None = Field(default=None, ge=0, le=1)
    f1_score: float | None = Field(default=None, ge=0, le=1)
    intersection_over_union: float | None = Field(default=None, ge=0, le=1)
    overall_agreement: float | None = Field(default=None, ge=0, le=1)
    candidate_valid_pixel_count: int
    reference_valid_pixel_count_on_candidate_grid: int
    common_valid_pixel_count: int
    valid_reference_coverage_fraction: float = Field(ge=0, le=1)
    minimum_common_pixels: int | None = None
    minimum_coverage_fraction: float | None = None
    minimum_pixels_per_class: int | None = None
    spatial_block_size_pixels: int | None = None
    minimum_blocks_per_class: int | None = None
    reference_class_counts: dict[str, int] | None = None
    reference_class_block_counts: dict[str, int] | None = None
    pixel_area_m2: float
    resampling: Literal["nearest", "none"]
    candidate_processing_version: str | None = None
    processing: dict[str, Any] | None = None
    evaluation_completed_at: datetime | None = None
    evaluation_outcome_detail: str | None = None
    evaluation_transitions: list[EvaluationTransition] = Field(default_factory=list)
    report_url: str
    warnings: list[str]

    @computed_field
    @property
    def acquisition_time_difference_seconds(self) -> float | None:
        candidate = self.candidate_acquisition_datetime
        reference = self.reference_acquisition_datetime
        if candidate.utcoffset() is None or reference.utcoffset() is None:
            return None
        return abs((candidate - reference).total_seconds())


class EvaluationRejection(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A rejection reason is required.")
        return value.strip()


class ValidationStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["validation_pending", "reference_dataset_available", "validation_completed"]
    message: str
    reports: list[ValidationResult]


class ReferenceDataSource(BaseModel):
    source_id: str
    name: str
    provider: str
    source_url: HttpUrl
    access_url: HttpUrl
    temporal_coverage: str
    nominal_resolution_m: float | None = None
    geographic_coverage: str
    spatial_reference: str
    data_format: str
    access_notes: str
    license_status: str
    intended_use: str
    limitation: str


class ReferenceDataImportMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_id: str = Field(min_length=1, max_length=256)
    provider: str = Field(min_length=1, max_length=256)
    source_url: HttpUrl
    acquisition_datetime: datetime
    resolution_m: float = Field(gt=0, le=100_000)
    crs: str = Field(min_length=1, max_length=80)
    license: str = Field(min_length=1, max_length=256)
    reviewer: str = Field(min_length=1, max_length=256)
    review_date: date
    review_method: str = Field(min_length=1, max_length=4_000)
    independent_review_completed: bool
    limitations: list[str] = Field(min_length=1, max_length=50)

    @field_validator("acquisition_datetime")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("acquisition_datetime must include a timezone.")
        return value

    @field_validator("limitations")
    @classmethod
    def require_nonempty_limitations(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("Each limitation must contain text.")
        return value


class ReferenceDataRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_id: str
    metadata: ReferenceDataImportMetadata
    width: int
    height: int
    label_counts: dict[str, int]
    nodata_value: int
    review_attestation: str
    labels_url: str


class MethodCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    method_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    method_name: str = Field(min_length=1, max_length=256)
    parameters: dict[str, str | int | float | bool] = Field(max_length=50)


class MethodEvaluationMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_metadata: ValidationMetadata
    methods: list[MethodCandidate] = Field(min_length=2, max_length=8)

    @field_validator("methods")
    @classmethod
    def require_unique_methods(cls, value: list[MethodCandidate]) -> list[MethodCandidate]:
        if len({method.method_id for method in value}) != len(value):
            raise ValueError("Method IDs must be unique.")
        return value


class ExploratoryMethodMetadata(BaseModel):
    river_id: Literal["kaveri", "tungabhadra"]
    candidate_product_id: str = Field(min_length=1, max_length=512)
    candidate_acquisition_datetime: datetime | None = None
    methods: list[MethodCandidate] = Field(min_length=2, max_length=8)

    @field_validator("candidate_acquisition_datetime")
    @classmethod
    def require_candidate_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("candidate_acquisition_datetime must include a timezone.")
        return value

    @field_validator("methods")
    @classmethod
    def require_unique_methods(cls, value: list[MethodCandidate]) -> list[MethodCandidate]:
        return MethodEvaluationMetadata.require_unique_methods(value)


class PairwiseComparison(BaseModel):
    first_method_id: str
    second_method_id: str
    absolute_area_difference_m2: float | None
    area_difference_fraction_of_first: float | None
    disagreement_pixel_count: int | None
    disagreement_fraction: float | None
    intersection_over_union: float | None


class ExploratoryMethodResult(BaseModel):
    status: Literal["exploratory_comparison", "insufficient_spatial_overlap"]
    river_id: str
    candidate_product_id: str
    candidate_acquisition_datetime: datetime | None = None
    shared_common_valid_pixel_count: int
    shared_grid_coverage_fraction: float = Field(ge=0, le=1)
    candidate_crs: str
    pixel_area_m2: float
    methods: list[dict[str, Any]]
    pairwise_comparisons: list[PairwiseComparison]
    processing: dict[str, Any]
    warnings: list[str]


class MethodEvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    evaluation_id: str
    status: Literal[
        "evaluation_completed",
        "insufficient_spatial_overlap",
        "insufficient_valid_labels",
        "insufficient_evidence",
    ]
    river_id: str
    candidate_product_id: str
    candidate_acquisition_datetime: datetime
    reference_dataset_id: str
    reference_acquisition_datetime: datetime
    reference_metadata: ValidationMetadata | None = None
    temporal_offset_seconds: float
    shared_common_valid_pixel_count: int
    shared_reference_coverage_fraction: float = Field(ge=0, le=1)
    minimum_common_pixels: int | None = None
    minimum_coverage_fraction: float | None = None
    minimum_pixels_per_class: int | None = None
    spatial_block_size_pixels: int | None = None
    minimum_blocks_per_class: int | None = None
    reference_class_counts: dict[str, int] | None = None
    reference_class_block_counts: dict[str, int] | None = None
    candidate_crs: str
    pixel_area_m2: float
    methods: list[dict[str, Any]]
    pairwise_comparisons: list[PairwiseComparison] = Field(default_factory=list)
    warnings: list[str]
    report_url: str
