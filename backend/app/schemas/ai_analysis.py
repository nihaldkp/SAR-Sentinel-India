from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RiverAnalysisRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    river_id: Literal["kaveri", "tungabhadra"]
    product_id: str | None = Field(default=None, min_length=1, max_length=512)


class AnalysisProductOption(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: str
    satellite: Literal["NISAR", "SENTINEL-1"]
    acquisition_start: datetime | None
    acquisition_end: datetime | None = None
    processing_status: str
    processing_version: str | None = None
    is_usable_candidate: bool
    valid_data_fraction: float | None = Field(default=None, ge=0, le=1)
    source_name: str | None = None
    source_record_url: str | None = None
    source_license: str | None = None
    product_type: str | None = None
    polarization: list[str] = Field(default_factory=list)
    input_crs: str | None = None
    pixel_size_m: float | None = Field(default=None, gt=0)


class AnalysisCoverage(BaseModel):
    model_config = ConfigDict(frozen=True)

    catalog_product_count: int
    usable_candidate_count: int
    no_data_product_count: int
    failed_product_count: int
    mapped_centerline_coverage_percent: float | None = None
    corridor_half_width_m: float | None = None


class CandidateMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    classification_status: str
    candidate_water_pixel_count: int | None = None
    candidate_water_area_km2: float | None = None
    valid_pixel_count: int | None = None
    corridor_pixel_count: int | None = None
    valid_data_fraction: float | None = Field(default=None, ge=0, le=1)
    no_data_fraction: float | None = Field(default=None, ge=0, le=1)
    threshold_db: float | None = None
    hh_threshold_db: float | None = None
    hv_threshold_db: float | None = None


class ThresholdSensitivity(BaseModel):
    model_config = ConfigDict(frozen=True)

    samples: list[dict[str, int | float]]
    candidate_area_min_km2: float | None = None
    candidate_area_max_km2: float | None = None
    candidate_area_range_percent: float | None = None
    interpretation: str


class OpticalComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool
    status: str
    source_product_id: str | None = None
    acquisition_start: datetime | None = None
    time_difference_seconds: float | None = None
    common_valid_pixel_count: int | None = None
    common_valid_area_km2: float | None = None
    candidate_water_pixel_count: int | None = None
    candidate_water_area_km2: float | None = None
    ndwi_threshold: float | None = None
    warning: str


class TemporalComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal[
        "insufficient_observations",
        "no_compatible_pair",
        "compatible_pair_available",
    ]
    available_pair_count: int
    explanation: str


EvidenceStatus = Literal[
    "independent_reference_unavailable",
    "candidate_identity_unverified",
    "reference_imported_unreviewed",
    "reviewed_reference_available",
    "insufficient_valid_labels",
    "evidence_thresholds_unmet",
    "thresholds_met_awaiting_evaluation",
    "evaluation_rejected_or_failed",
    "sample_validation_completed",
]


class RiverAnalysisResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str
    generated_at: datetime
    analysis_mode: Literal["deterministic_rule_based"]
    data_mode: Literal["persisted_satellite_acquisition_catalog"]
    river_id: str
    selected_product_id: str | None = None
    products: list[AnalysisProductOption]
    coverage: AnalysisCoverage
    candidate_metrics: CandidateMetrics | None = None
    threshold_sensitivity: ThresholdSensitivity | None = None
    polarization_comparison: list[dict[str, str | int | float]]
    optical_comparison: OpticalComparison
    temporal_comparison: TemporalComparison
    validation_status: EvidenceStatus
    validation_explanation: str
    findings: list[str]
    warnings: list[str]
    limitations: list[str]
    recommended_next_steps: list[str]
