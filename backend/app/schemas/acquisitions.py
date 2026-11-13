from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.redaction import redact_sensitive_text, redact_url

AcquisitionState = Literal[
    "idle",
    "searching",
    "acquiring",
    "processing",
    "processed",
    "no_data",
    "blocked",
    "failed",
]
AcquisitionJobState = Literal[
    "queued",
    "running",
    "downloading",
    "processing",
    "completed",
    "no_data",
    "failed",
    "cancelled",
]
AcquisitionJobType = Literal[
    "nisar_download",
    "nisar_processing",
    "sentinel1_acquisition",
]


class AcquiredObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    river_id: str
    product_id: str
    mission: Literal["SENTINEL-1"]
    product_type: Literal["GRD-RTC"]
    platform: str | None = None
    acquisition_start: datetime
    acquisition_end: datetime | None = None
    polarization: str
    orbit_state: str | None = None
    relative_orbit: int | None = None
    footprint: dict
    centerline_coverage_percent: float
    source: Literal["Microsoft Planetary Computer"]
    stac_item_url: str
    asset_source_url: str
    source_license: str
    provider_processing: str
    processing_status: Literal["unvalidated_candidate"]
    analysis_id: str
    candidate_water_area_m2: float
    candidate_water_area_lower_m2: float
    candidate_water_area_upper_m2: float
    threshold_db: float
    valid_pixel_count: int
    valid_data_fraction: float
    water_pixel_count: int
    filter_method: str
    input_crs: str
    pixel_size_m: float
    corridor_half_width_m: float
    analysis_url: str
    mask_url: str
    polygons_url: str
    report_url: str
    caveats: list[str]
    downloaded_at: datetime

    @field_validator("stac_item_url", "asset_source_url", mode="before")
    @classmethod
    def redact_external_urls(cls, value: str) -> str:
        return redact_url(value) or ""


class AcquisitionIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: str
    status: Literal["failed", "acquiring", "processing"]
    error: str | None = None
    updated_at: datetime

    @field_validator("error", mode="before")
    @classmethod
    def redact_error(cls, value: str | None) -> str | None:
        return redact_sensitive_text(value) if value is not None else None


class NisarProcessingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    river_id: str
    product_id: str
    status: Literal["unvalidated_candidate", "no_valid_corridor_data"]
    processor_version: str
    algorithm: str
    input_measurement_convention: str | None = None
    input_backscatter_normalization_convention: str | None = None
    input_backscatter_expression_convention: str | None = None
    power_to_db_conversion: str | None = None
    power_to_db_floor_linear: float | None = None
    power_to_db_floor_db: float | None = None
    frequency: str
    dataset_paths: dict[str, str]
    acquisition_start: datetime | None = None
    acquisition_end: datetime | None = None
    polarization: list[str]
    input_crs: str
    pixel_size_m: float
    reference_centerline_coverage_percent: float
    reference_centerline_length_km: float
    covered_centerline_length_km: float
    corridor_half_width_m: float
    corridor_pixel_count: int
    valid_pixel_count: int
    valid_data_fraction: float
    water_pixel_count: int | None
    candidate_water_area_m2: float | None
    candidate_water_area_lower_m2: float | None
    candidate_water_area_upper_m2: float | None
    hh_threshold_db: float | None
    hv_threshold_db: float | None
    threshold_sensitivity_db: float
    mask_width: int
    mask_height: int
    mask_url: str | None
    measurements_url: str | None
    polygons_url: str | None
    comparison_url: str | None = None
    sensitivity_url: str | None = None
    optical_reference_url: str | None = None
    optical_candidate_mask_url: str | None = None
    metadata_url: str
    polygon_feature_count: int
    vectorization_truncated: bool
    geojson_display_note: str | None = None
    polarization_comparison: list[dict[str, str | int | float]] = Field(default_factory=list)
    threshold_sensitivity: list[dict[str, int | float]] = Field(default_factory=list)
    connected_component_summary: dict[str, int] | None = None
    processing_completed_at: datetime
    caveats: list[str]


class NisarComponentSensitivityRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    minimum_component_sizes: list[Annotated[int, Field(ge=2, le=100_000)]] = Field(
        min_length=1,
        max_length=8,
    )

    @field_validator("minimum_component_sizes")
    @classmethod
    def require_unique_sizes(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("Minimum component sizes must be unique.")
        return value


class NisarComponentSensitivityResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["exploratory_candidate_sensitivity"]
    river_id: str
    product_id: str
    source_product_id: str
    acquisition_start: datetime | None = None
    minimum_component_pixels: int
    connectivity: Literal[8]
    component_count: int
    component_count_reclassified_nonwater: int
    candidate_pixel_count_before: int
    candidate_pixel_count_after: int
    candidate_pixels_reclassified_nonwater: int
    candidate_pixels_removed_fraction: float
    valid_pixel_count: int
    nodata_pixel_count_preserved: int
    candidate_area_before_m2: float
    candidate_area_after_m2: float
    crs: str
    pixel_size_m: float
    processing_completed_at: datetime
    quality_flags: list[str]
    mask_url: str


class NisarProduct(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: str
    platform: str | None = None
    acquisition_start: datetime | None = None
    acquisition_end: datetime | None = None
    product_level: str
    processing_type: str | None = None
    product_type: str = "GCOV"
    polarization: list[str] | None = None
    size_bytes: int | None = None
    footprint: dict | None = None
    corridor_coverage_percent: float | None = Field(default=None, ge=0, le=100)
    metadata_source: str | None = None
    availability: str
    download_status: str
    source_url: str | None = None
    source_url_reference: str | None = None
    local_path: str | None = None
    acquisition_identifier: str | None = None
    hdf5_groups: list[str] = Field(default_factory=list)
    sha256: str | None = None
    provider_checksum_algorithm: Literal["sha256", "md5"] | None = None
    provider_checksum: str | None = None
    integrity_status: Literal[
        "not_verified",
        "provider_checksum_verified",
        "sha256_fingerprint_only",
    ] = "not_verified"
    structure_verification_status: Literal["not_verified", "verified", "rejected"] = "not_verified"
    provider_authenticity_status: Literal[
        "not_verified",
        "provider_checksum_verified",
    ] = "not_verified"
    scientific_validation_status: Literal[
        "not_performed",
        "independently_validated",
    ] = "not_performed"
    download_timestamp: datetime | None = None
    message: str | None = None
    authentication_status: Literal[
        "unknown",
        "not_configured",
        "token_valid",
        "data_access_verified",
        "rejected",
        "error",
    ] = "unknown"
    authentication_checked_at: datetime | None = None
    processing_status: Literal["not_attempted", "processing", "processed", "no_data", "failed"] = "not_attempted"
    processing_message: str | None = None
    processing_result: NisarProcessingResult | None = None

    @field_validator("source_url", mode="before")
    @classmethod
    def redact_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if parts.scheme and parts.netloc:
            query = parse_qsl(parts.query, keep_blank_values=True)
            has_signed_parameters = any(
                key.casefold().startswith("x-amz-")
                or key.casefold() in {"sig", "signature"}
                for key, _ in query
            )
            if has_signed_parameters:
                query = [
                    (key, item)
                    for key, item in query
                    if not key.casefold().startswith("x-amz-")
                    and key.casefold() not in {"sig", "signature"}
                ]
            value = urlunsplit(
                (parts.scheme, parts.netloc, parts.path, urlencode(query), "")
            )
        return redact_url(value)

    @field_validator("source_url_reference", mode="before")
    @classmethod
    def remove_source_url_reference_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if parts.scheme and parts.netloc:
            value = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        return redact_url(value)

    @field_validator("message", "processing_message", mode="before")
    @classmethod
    def redact_messages(cls, value: str | None) -> str | None:
        return redact_sensitive_text(value) if value is not None else None


class NisarMetadataRegistrationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    river_id: str = Field(min_length=1, max_length=80)
    product_id: str = Field(min_length=1, max_length=512)


class NisarMetadataRegistrationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    river_id: str
    product: NisarProduct
    registration_status: Literal["registered", "already_registered"]
    corridor_intersects: bool
    corridor_coverage_percent: float = Field(ge=0, le=100)
    coverage_basis: Literal["buffered_centerline_corridor"] = "buffered_centerline_corridor"
    coverage_sufficiency: Literal["not_assessed"] = "not_assessed"


class RiverAcquisitionStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    river_id: str
    status: AcquisitionState
    last_checked_at: datetime | None = None
    nisar_status: Literal["not_checked", "metadata_found", "authentication_required", "no_data", "error"]
    nisar_product_id: str | None = None
    nisar_acquisition_start: datetime | None = None
    nisar_message: str | None = None
    earthdata_authentication_status: Literal[
        "unknown",
        "not_configured",
        "token_valid",
        "data_access_verified",
        "rejected",
        "error",
    ] = "unknown"
    earthdata_authentication_checked_at: datetime | None = None
    last_successful_nisar_search: datetime | None = None
    nisar_products: list[NisarProduct] = Field(default_factory=list)
    candidate_count: int = 0
    latest_observation: AcquiredObservation | None = None
    observations: list[AcquiredObservation]
    issues: list[AcquisitionIssue]
    message: str | None = None

    @field_validator("nisar_message", "message", mode="before")
    @classmethod
    def redact_messages(cls, value: str | None) -> str | None:
        return redact_sensitive_text(value) if value is not None else None


class AcquisitionStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    polling_interval_seconds: int
    last_checked_at: datetime | None = None
    source: Literal["Microsoft Planetary Computer Sentinel-1 RTC"]
    source_url: str
    license: str
    rivers: list[RiverAcquisitionStatus]

    @field_validator("source_url", mode="before")
    @classmethod
    def redact_source_url(cls, value: str) -> str:
        return redact_url(value) or ""

    @computed_field
    @property
    def nisar_connection_status(self) -> dict[str, object]:
        products = [p for river in self.rivers for p in river.nisar_products]
        inspected = [p for p in products if p.download_status == "downloaded" and p.hdf5_groups]
        processed = [p.processing_result for p in products if p.processing_result is not None]
        latest = max(
            (p for p in inspected if p.acquisition_start is not None and p.acquisition_start.utcoffset() is not None),
            key=lambda p: p.acquisition_start.timestamp(),
            default=None,
        )
        latest_processing = max(
            (result for result in processed if result.processing_completed_at.utcoffset() is not None),
            key=lambda result: result.processing_completed_at.timestamp(),
            default=None,
        )
        authentication_checks = [
            river
            for river in self.rivers
            if river.earthdata_authentication_checked_at is not None
        ]
        latest_authentication_check = max(
            authentication_checks,
            key=lambda river: river.earthdata_authentication_checked_at.timestamp(),
            default=None,
        )
        successful_searches = [
            river.last_successful_nisar_search
            for river in self.rivers
            if river.last_successful_nisar_search is not None
        ]
        return {
            "provider": "ASF DAAC",
            "provider_connectivity": "available" if successful_searches else "unknown",
            "authentication_status": (
                latest_authentication_check.earthdata_authentication_status
                if latest_authentication_check
                else "unknown"
            ),
            "authentication_checked_at": (
                latest_authentication_check.earthdata_authentication_checked_at
                if latest_authentication_check
                else None
            ),
            "last_successful_search": max(successful_searches, default=None),
            "cached_product_count": len({p.product_id for p in products}),
            "recorded_download_count": len({p.product_id for p in products if p.download_status == "downloaded"}),
            "recorded_inspection_count": len({p.product_id for p in inspected}),
            "recorded_processing_count": len({result.product_id for result in processed}),
            "latest_recorded_inspection_product_id": latest.product_id if latest else None,
            "latest_recorded_inspection_acquisition": latest.acquisition_start if latest else None,
            "latest_recorded_processing": (
                {"product_id": latest_processing.product_id, "status": latest_processing.status,
                 "completed_at": latest_processing.processing_completed_at}
                if latest_processing else None
            ),
            "recorded_error": any(r.nisar_status == "error" or any(p.processing_status == "failed" for p in r.nisar_products) for r in self.rivers),
        }


class AcquisitionJobCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    river_id: str
    satellite: Literal["NISAR", "SENTINEL-1"]
    product_id: str = Field(min_length=1, max_length=512)
    job_type: AcquisitionJobType


class AcquisitionJob(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: str
    river_id: str
    satellite: Literal["NISAR", "SENTINEL-1"]
    product_id: str
    job_type: AcquisitionJobType
    status: AcquisitionJobState
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    current_stage: str
    error_message: str | None = None
    output_references: dict[str, str] = Field(default_factory=dict)
    retry_of_job_id: str | None = None

    @field_validator("error_message", mode="before")
    @classmethod
    def redact_error(cls, value: str | None) -> str | None:
        return redact_sensitive_text(value) if value is not None else None
