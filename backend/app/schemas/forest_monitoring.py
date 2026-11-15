from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ForestAnalysisRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    river_id: Literal["kaveri", "tungabhadra"]
    item_id: str = Field(min_length=1, max_length=512)
    zone_distances_m: list[Annotated[int, Field(strict=True, ge=1, le=5000)]] = Field(
        default_factory=lambda: [500, 1000, 3000, 5000],
        min_length=1,
        max_length=6,
    )

    @field_validator("zone_distances_m")
    @classmethod
    def validate_zone_distances(cls, value: list[int]) -> list[int]:
        if value != sorted(set(value)):
            raise ValueError("Zone distances must be unique and strictly increasing.")
        return value


class ForestIndexStatistics(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid_pixel_count: int
    mean: float | None = None
    standard_deviation: float | None = None
    minimum: float | None = None
    maximum: float | None = None


class ForestZoneStatistics(BaseModel):
    model_config = ConfigDict(frozen=True)

    zone_id: str
    inner_distance_m: int
    outer_distance_m: int
    zone_area_km2: float
    raster_covered_area_km2: float
    valid_area_km2: float
    raster_coverage_percent: float
    valid_data_coverage_percent: float | None = None
    clear_scl_pixel_count: int
    valid_pixel_count: int
    scl_masked_pixel_count: int
    ndvi: ForestIndexStatistics
    evi: ForestIndexStatistics
    ndmi: ForestIndexStatistics


class ForestAnalysisSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int
    analysis_id: str
    status: Literal["completed", "no_data"]
    river_id: str
    item_id: str
    acquisition_datetime: datetime | None = None
    source: str
    collection: str
    stac_item_url: str | None = None
    source_footprint_wgs84: dict[str, Any] | None = None
    cloud_cover_percent: float | None = None
    asset_sources: dict[str, str]
    generated_at: datetime
    processor_version: str
    processing_parameters: dict[str, Any]
    grid: dict[str, Any]
    zones: list[ForestZoneStatistics]
    tree_cover: dict[str, Any]
    temporal_change: dict[str, Any]
    river_vegetation_relationship: dict[str, Any]
    uncertainty_and_limitations: list[str]
    output_sha256: dict[str, str]


class ForestObservationCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    river_id: str
    source: str
    collection: str
    observations: list[dict[str, Any]]
    distinct_processed_acquisition_times: list[str]
    temporal_change_status: Literal[
        "available_for_compatibility_check",
        "insufficient_observations",
    ]
    limitations: list[str]


class ForestReferenceCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    references: list[dict[str, Any]]
    tree_cover_statistics_status: Literal["not_available", "available_after_import"]


class ForestReferenceImportResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    dataset_id: Literal["esa-worldcover-2021-v200"]
    name: str
    year: int
    resolution_m: int
    source_url: str
    license: str
    tree_cover_class: int
    status: Literal["pixels_imported"]
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provenance_verification: Literal["user_supplied_not_independently_authenticated"]
    imported_at: datetime
    source_raster: dict[str, Any]
    limitations: list[str]


class ForestTreeCoverRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class ForestTreeCoverZoneStatistics(BaseModel):
    model_config = ConfigDict(frozen=True)

    zone_id: str
    zone_area_km2: float
    raster_coverage_percent: float | None = None
    valid_data_coverage_percent: float | None = None
    valid_pixel_count: int
    tree_cover_pixel_count: int
    tree_cover_area_km2: float
    tree_cover_percent_of_valid_area: float | None = None


class ForestTreeCoverStatistics(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    river_id: Literal["kaveri", "tungabhadra"]
    reference_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    dataset_id: Literal["esa-worldcover-2021-v200"]
    dataset_name: str
    reference_year: int
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_crs: str
    analysis_crs: Literal["EPSG:6933"]
    resolution_m: int
    tree_cover_class: int
    tree_cover_label: str
    status: Literal["completed", "no_data"]
    zones: list[ForestTreeCoverZoneStatistics]
    output: dict[str, Any]
    limitations: list[str]
    generated_at: datetime
    output_sha256: dict[str, str]


class ForestEvidenceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str
    generated_at: datetime
    analysis_mode: Literal["deterministic_evidence_summary"]
    river_id: str
    item_id: str
    acquisition_datetime: datetime | None = None
    observed_zone_summaries: list[str]
    limitations: list[str]
    conclusion: str
