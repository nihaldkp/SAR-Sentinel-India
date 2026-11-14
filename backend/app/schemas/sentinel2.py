from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Sentinel2Observation(BaseModel):
    model_config = ConfigDict(extra="allow")

    river_id: str
    item_id: str
    acquisition_datetime: str | None = None
    cloud_cover_percent: float | None = None
    status: str
    source: str
    collection: str
    valid_pixel_count: int | None = None
    valid_pixel_percent: float | None = None
    corridor_pixel_count: int | None = None
    raster_pixel_percent: float | None = None
    crs: str | None = None
    resolution_m: float | None = None
    index_statistics: dict[str, dict[str, float]] = Field(default_factory=dict)
    output_paths: dict[str, str] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    bounds_wgs84: dict[str, float] | None = None
    preview_color_scale: dict[str, Any] = Field(default_factory=dict)
    vegetation_validation: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class Sentinel2ObservationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    river_id: str
    source: str
    collection: str
    observations: list[Sentinel2Observation]
    historical_comparisons: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class Sentinel2ComparisonRequest(BaseModel):
    river_id: str
    earlier_item_id: str
    later_item_id: str


class Sentinel2ComparisonResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    river_id: str
    earlier_item_id: str
    later_item_id: str
    status: str
    indices: dict[str, dict[str, float | int]]
    limitations: list[str] = Field(default_factory=list)
