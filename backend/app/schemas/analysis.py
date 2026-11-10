from datetime import datetime
import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from app.schemas.satellite import Mission

Longitude = Annotated[float, Field(ge=-180, le=180)]
Latitude = Annotated[float, Field(ge=-90, le=90)]


class AnalysisMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    river_id: str = Field(min_length=1, max_length=80)
    mission: Mission
    product_type: str = Field(min_length=1, max_length=40)
    source_product_id: str = Field(min_length=1, max_length=200)
    acquisition_start: datetime
    polarization: str = Field(min_length=1, max_length=40)
    band_description: str = Field(min_length=1, max_length=120)
    signal_scale: Literal["linear_power", "decibels"]
    radiometric_calibration_confirmed: bool
    terrain_correction_confirmed: bool

    @field_validator("acquisition_start")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("acquisition_start must include a timezone.")
        return value


class WaterMaskRequest(AnalysisMetadata):
    threshold_method: Literal["otsu", "fixed_db"] = "otsu"
    threshold_db: float | None = Field(default=None, ge=-50, le=5)

    @model_validator(mode="after")
    def validate_threshold(self) -> "WaterMaskRequest":
        if self.threshold_method == "fixed_db" and self.threshold_db is None:
            raise ValueError("threshold_db is required when threshold_method is fixed_db.")
        if self.threshold_method == "otsu" and self.threshold_db is not None:
            raise ValueError("threshold_db must be omitted when threshold_method is otsu.")
        return self


class ChangeDetectionRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    earlier_analysis_id: str = Field(min_length=1, max_length=36)
    later_analysis_id: str = Field(min_length=1, max_length=36)


class WidthMeasurementRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str = Field(min_length=1, max_length=36)
    start: tuple[Longitude, Latitude]
    end: tuple[Longitude, Latitude]


class AnalysisResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str
    analysis_type: Literal["water_mask"]
    status: Literal["unvalidated_candidate"]
    source_product_id: str
    mission: Mission
    river_id: str
    acquisition_start: datetime
    polarization: str
    band_description: str
    signal_scale: Literal["linear_power", "decibels"]
    threshold_method: Literal["otsu", "fixed_db"]
    threshold_db: float
    threshold_sensitivity_range_db: float
    filter_method: str
    valid_pixel_count: int
    water_pixel_count: int
    valid_data_fraction: float
    pixel_area_m2: float
    candidate_water_area_m2: float
    candidate_water_area_lower_m2: float
    candidate_water_area_upper_m2: float
    input_crs: str
    mask_url: str
    polygons_url: str
    report_url: str
    caveats: list[str]


class ChangeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    change_id: str
    analysis_type: Literal["two_date_water_extent_comparison"]
    status: Literal["unvalidated_candidate"]
    earlier_analysis_id: str
    later_analysis_id: str
    earlier_source_product_id: str
    later_source_product_id: str
    earlier_acquisition_start: datetime
    later_acquisition_start: datetime
    mission: Mission
    product_type: str
    polarization: str
    threshold_method: Literal["otsu", "fixed_db"]
    earlier_threshold_db: float
    later_threshold_db: float
    threshold_delta_db: float
    filter_method: str
    crs: str
    pixel_size_m: float
    common_valid_pixel_count: int
    common_valid_area_m2: float
    common_valid_fraction: float = Field(ge=0, le=1)
    water_gain_pixel_count: int
    water_loss_pixel_count: int
    pixel_area_m2: float
    candidate_water_gain_area_m2: float
    candidate_water_loss_area_m2: float
    change_mask_url: str
    report_url: str
    caveats: list[str]


class TemporalCandidatePair(BaseModel):
    model_config = ConfigDict(frozen=True)

    river_id: str
    earlier_analysis_id: str
    later_analysis_id: str
    earlier_source_product_id: str
    later_source_product_id: str
    earlier_acquisition_start: datetime
    later_acquisition_start: datetime
    elapsed_days: float
    mission: Mission
    product_type: str
    polarization: str
    threshold_method: Literal["otsu", "fixed_db"]
    earlier_threshold_db: float
    later_threshold_db: float
    threshold_delta_db: float
    filter_method: str
    crs: str
    pixel_size_m: float
    width: int
    height: int
    common_valid_pixel_count: int
    common_valid_area_m2: float
    common_valid_fraction: float = Field(ge=0, le=1)
    earlier_source_record_url: str
    later_source_record_url: str
    seasonal_context: str
    parameter_compatibility: str
    caveats: list[str]


class WidthMeasurementResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str
    transect_length_m: float
    sampled_water_segments_m: list[float]
    longest_contiguous_water_width_m: float
    status: Literal["unvalidated_candidate"]
    caveats: list[str]


class RiverAxisSamplingRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str = Field(min_length=1, max_length=36)
    axis_dataset_id: str = Field(min_length=1, max_length=256)
    axis_source_name: str = Field(min_length=1, max_length=256)
    axis_source_url: HttpUrl
    axis_geojson: dict[str, Any]
    corridor_geojson: dict[str, Any]
    station_spacing_m: float = Field(ge=20, le=5_000)
    transect_half_length_m: float = Field(ge=20, le=5_000)
    minimum_valid_fraction: float = Field(default=0.8, ge=0.5, le=1)

    @field_validator("axis_geojson", "corridor_geojson")
    @classmethod
    def limit_geometry_coordinates(cls, value: dict[str, Any]) -> dict[str, Any]:
        geometry = value.get("geometry") if value.get("type") == "Feature" else value
        if not isinstance(geometry, dict):
            raise ValueError("Provide a GeoJSON geometry or Feature.")
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list):
            raise ValueError("GeoJSON coordinates must be an array.")

        def count_positions(node: Any) -> int:
            if (
                isinstance(node, (list, tuple))
                and len(node) >= 2
                and isinstance(node[0], (int, float)) and not isinstance(node[0], bool)
                and isinstance(node[1], (int, float)) and not isinstance(node[1], bool)
            ):
                if (
                    len(node) not in (2, 3)
                    or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in node)
                    or not -180 <= node[0] <= 180
                    or not -90 <= node[1] <= 90
                ):
                    raise ValueError("GeoJSON positions must contain finite WGS84 longitude and latitude.")
                return 1
            if isinstance(node, (list, tuple)) and node:
                return sum(count_positions(item) for item in node)
            raise ValueError("GeoJSON coordinates must contain valid positions.")

        if count_positions(coordinates) < 2 or count_positions(coordinates) > 20_000:
            raise ValueError("Each GeoJSON geometry must contain between 2 and 20,000 positions.")
        return value

    @model_validator(mode="after")
    def validate_axis_and_corridor_types(self) -> "RiverAxisSamplingRequest":
        axis = self.axis_geojson.get("geometry", self.axis_geojson)
        corridor = self.corridor_geojson.get("geometry", self.corridor_geojson)
        if axis.get("type") != "LineString":
            raise ValueError("axis_geojson must be a GeoJSON LineString or LineString Feature.")
        if corridor.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError("corridor_geojson must be a GeoJSON Polygon or MultiPolygon.")
        return self


class RiverAxisWidthSample(BaseModel):
    chainage_m: float
    candidate_width_m: float | None = None
    valid_fraction: float = Field(ge=0, le=1)
    raster_coverage_fraction: float = Field(ge=0, le=1)
    sampled_pixel_count: int
    valid_pixel_count: int
    quality_status: Literal["usable_candidate", "low_valid_coverage", "no_candidate", "outside_raster"]
    quality_flags: list[str]


class RiverAxisSamplingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    analysis_id: str
    source_product_id: str
    acquisition_start: datetime
    axis_dataset_id: str
    axis_source_name: str
    axis_source_url: HttpUrl
    axis_geometry_status: Literal["user_supplied_not_independently_verified"]
    axis_length_m: float
    station_spacing_m: float
    transect_half_length_m: float
    raster_resolution_m: float
    requested_station_count: int
    accepted_station_count: int
    coverage_fraction: float = Field(ge=0, le=1)
    uncertainty_m: float | None = None
    uncertainty_status: Literal["not_quantified"]
    samples: list[RiverAxisWidthSample]
    quality_flags: list[str]
    caveats: list[str]


class AnalysisCapabilities(BaseModel):
    geotiff_processing_available: bool
    rasterio_available: bool
    input_requirement: str
    raw_product_preprocessing_available: bool = False
    real_satellite_product_downloaded: bool = False
    unavailable_reason: str | None = None
