from __future__ import annotations

import math
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

IntegrationJobType = Literal["sar_processing", "gis_analysis"]
IntegrationJobStatus = Literal["queued", "running", "blocked", "completed", "failed"]
IntegrationOutputType = Literal["raster", "vector", "metadata"]
AssociationType = Literal["river", "region"]


class VerifiedAcquisition(BaseModel):
    model_config = ConfigDict(frozen=True)

    river_id: str
    product_id: str
    mission: Literal["NISAR"] = "NISAR"
    product_type: Literal["GCOV"]
    acquisition_start: datetime
    acquisition_end: datetime | None = None
    spatial_coverage: dict[str, Any] | None = None
    file_reference: str
    file_size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    integrity_status: Literal[
        "provider_checksum_verified",
        "sha256_fingerprint_only",
    ]
    structure_verification_status: Literal["verified"]
    provider_authenticity_status: Literal[
        "not_verified",
        "provider_checksum_verified",
    ]
    scientific_validation_status: Literal["not_performed"]
    source_url_reference: str | None = None
    download_timestamp: datetime | None = None
    provider_checksum_algorithm: Literal["sha256", "md5"] | None = None
    provider_checksum: str | None = None

    @field_validator("acquisition_start", "acquisition_end", "download_timestamp")
    @classmethod
    def require_aware_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Acquisition timestamps must include a timezone.")
        return value


class VerifiedAcquisitionPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    limit: int
    offset: int
    items: list[VerifiedAcquisition]


class AcquisitionVerification(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: str
    acquisition_identifier: str
    file_size_bytes: int
    sha256: str
    integrity_status: Literal[
        "provider_checksum_verified",
        "sha256_fingerprint_only",
    ]
    structure_verification_status: Literal["verified"]
    provider_authenticity_status: Literal[
        "not_verified",
        "provider_checksum_verified",
    ]
    provider_checksum_algorithm: Literal["sha256", "md5"] | None = None
    provider_checksum: str | None = None
    scientific_validation_status: Literal["not_performed"]
    verified_at: datetime | None = None
    verification_scope: Literal["recorded_download_verification"]


class ProcessingJobCreate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    river_id: str = Field(min_length=1, max_length=80)
    product_id: str = Field(min_length=1, max_length=200)
    processing_config: dict[str, Any] = Field(default_factory=dict)
    processing_version: str = Field(min_length=1, max_length=128)

    @field_validator("processing_config")
    @classmethod
    def bound_processing_config(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(str(value).encode("utf-8")) > 64 * 1024:
            raise ValueError("Processing configuration must not exceed 64 KiB.")
        return value


class GISJobCreate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    input_output_ids: list[str] = Field(min_length=1, max_length=32)
    analysis_type: str = Field(min_length=1, max_length=100)
    river_id: str | None = Field(default=None, min_length=1, max_length=80)
    region_id: str | None = Field(default=None, min_length=1, max_length=120)
    spatial_extent: dict[str, Any] | None = None
    acquisition_start: datetime | None = None
    acquisition_end: datetime | None = None
    analysis_config: dict[str, Any] = Field(default_factory=dict)
    processing_version: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_request(self) -> "GISJobCreate":
        if bool(self.river_id) == bool(self.region_id):
            raise ValueError("Provide exactly one of river_id or region_id.")
        if len(set(self.input_output_ids)) != len(self.input_output_ids):
            raise ValueError("input_output_ids must be unique.")
        if (
            self.acquisition_start is not None
            and self.acquisition_end is not None
            and self.acquisition_end < self.acquisition_start
        ):
            raise ValueError("acquisition_end must not precede acquisition_start.")
        if len(str(self.analysis_config).encode("utf-8")) > 64 * 1024:
            raise ValueError("Analysis configuration must not exceed 64 KiB.")
        if self.spatial_extent is not None:
            _validate_geojson_extent(self.spatial_extent)
        return self

    @field_validator("acquisition_start", "acquisition_end")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Acquisition timestamps must include a timezone.")
        return value


def _validate_geojson_extent(extent: dict[str, Any]) -> None:
    if extent.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("spatial_extent must be a GeoJSON Polygon or MultiPolygon.")
    if extent.get("crs") not in (None, "EPSG:4326"):
        raise ValueError("GeoJSON spatial_extent coordinates must use EPSG:4326.")

    coordinates = extent.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        raise ValueError("spatial_extent must contain coordinates.")

    def validate_ring(ring: Any) -> None:
        if not isinstance(ring, list) or len(ring) < 4:
            raise ValueError("GeoJSON polygon rings must contain at least four positions.")
        positions: list[tuple[float, float]] = []
        for position in ring:
            if (
                not isinstance(position, (list, tuple))
                or len(position) < 2
                or not isinstance(position[0], (int, float))
                or not isinstance(position[1], (int, float))
            ):
                raise ValueError("GeoJSON positions must contain longitude and latitude.")
            longitude, latitude = float(position[0]), float(position[1])
            if (
                not math.isfinite(longitude)
                or not math.isfinite(latitude)
                or not -180 <= longitude <= 180
                or not -90 <= latitude <= 90
            ):
                raise ValueError("GeoJSON spatial_extent coordinates are outside WGS84 bounds.")
            positions.append((longitude, latitude))
        if positions[0] != positions[-1]:
            raise ValueError("GeoJSON polygon rings must be closed.")

    polygons = [coordinates] if extent["type"] == "Polygon" else coordinates
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise ValueError("Each GeoJSON polygon must contain at least one ring.")
        for ring in polygon:
            validate_ring(ring)


class OutputAssetRegistration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str = Field(min_length=1, max_length=100)
    storage_key: str = Field(min_length=1, max_length=512)
    output_type: IntegrationOutputType
    media_type: str = Field(min_length=1, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("storage_key")
    @classmethod
    def require_safe_relative_key(cls, value: str) -> str:
        if "\\" in value or ":" in value or value.startswith("/"):
            raise ValueError("storage_key must be a relative forward-slash path.")
        if any(part in {"", ".", ".."} for part in value.split("/")):
            raise ValueError("storage_key must not contain traversal or empty path components.")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("storage_key must not contain traversal or absolute path components.")
        return path.as_posix()

    @model_validator(mode="after")
    def validate_asset_metadata(self) -> "OutputAssetRegistration":
        if len(str(self.metadata).encode("utf-8")) > 32 * 1024:
            raise ValueError("Output metadata must not exceed 32 KiB.")
        if self.output_type in {"raster", "vector"} and not self.metadata.get("crs"):
            raise ValueError("Raster and vector outputs must declare their CRS.")
        if self.output_type == "raster":
            width = self.metadata.get("width")
            height = self.metadata.get("height")
            transform = self.metadata.get("transform")
            if (
                not isinstance(width, int)
                or isinstance(width, bool)
                or width <= 0
                or not isinstance(height, int)
                or isinstance(height, bool)
                or height <= 0
            ):
                raise ValueError("Raster outputs must declare positive width and height.")
            if (
                not isinstance(transform, list)
                or len(transform) != 6
                or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in transform)
            ):
                raise ValueError("Raster outputs must declare a finite six-value affine transform.")
            if not isinstance(self.metadata.get("units"), str) or not self.metadata["units"].strip():
                raise ValueError("Raster outputs must declare measurement units or 'not_applicable'.")
            if "nodata" not in self.metadata:
                raise ValueError("Raster outputs must declare nodata, using null when absent.")
        if self.output_type == "vector" and not isinstance(self.metadata.get("geometry_type"), str):
            raise ValueError("Vector outputs must declare their geometry_type.")
        return self


class OutputRegistrationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outputs: list[OutputAssetRegistration] = Field(min_length=1, max_length=32)
    result_metadata: dict[str, Any] = Field(default_factory=dict)
    spatial_results: dict[str, Any] | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_unique_output_roles(self) -> "OutputRegistrationRequest":
        roles = [output.role for output in self.outputs]
        if len(roles) != len(set(roles)):
            raise ValueError("Output roles must be unique within a job.")
        if len(str(self.result_metadata).encode("utf-8")) > 64 * 1024:
            raise ValueError("Result metadata must not exceed 64 KiB.")
        if len(str(self.spatial_results).encode("utf-8")) > 256 * 1024:
            raise ValueError("Spatial results must not exceed 256 KiB.")
        if len(str(self.metrics).encode("utf-8")) > 64 * 1024:
            raise ValueError("Metrics must not exceed 64 KiB.")
        return self


class IntegrationOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    output_id: str
    job_id: str
    role: str
    storage_key: str
    output_type: IntegrationOutputType
    media_type: str
    size_bytes: int
    sha256: str
    registered_at: datetime
    metadata: dict[str, Any]


class IntegrationAssociationCreate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    target_type: AssociationType
    target_id: str = Field(min_length=1, max_length=200)


class IntegrationAssociation(BaseModel):
    model_config = ConfigDict(frozen=True)

    association_id: str
    job_id: str
    target_type: AssociationType
    target_id: str
    associated_at: datetime


class IntegrationJob(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: str
    job_type: IntegrationJobType
    status: IntegrationJobStatus
    created_at: datetime
    updated_at: datetime
    retry_of_job_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    request: dict[str, Any]
    result_metadata: dict[str, Any] = Field(default_factory=dict)
    spatial_results: dict[str, Any] | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    outputs: list[IntegrationOutput] = Field(default_factory=list)
    associations: list[IntegrationAssociation] = Field(default_factory=list)


class ProcessingAdapterInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: str
    acquisition: VerifiedAcquisition
    local_file_path: str
    output_directory: str
    processing_config: dict[str, Any]
    processing_version: str


class GISAdapterInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: str
    input_outputs: list[IntegrationOutput]
    input_file_paths: list[str]
    output_directory: str
    analysis_type: str
    river_id: str | None = None
    region_id: str | None = None
    spatial_extent: dict[str, Any] | None = None
    acquisition_start: datetime | None = None
    acquisition_end: datetime | None = None
    analysis_config: dict[str, Any]
    processing_version: str
