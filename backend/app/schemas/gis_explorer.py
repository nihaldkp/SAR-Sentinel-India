from typing import Any, Literal

from pydantic import BaseModel, Field


class GISLayer(BaseModel):
    layer_id: str
    name: str
    category: str
    layer_type: Literal["vector", "raster", "unavailable"]
    status: Literal["available", "unavailable", "error"]
    evidence_status: str | None = None
    source: str
    date: str | None = None
    crs: str | None = None
    resolution_m: float | None = None
    river_id: str | None = None
    geometry_type: str | None = None
    feature_count: int | None = None
    bounds_wgs84: dict[str, float] | None = None
    preview_bounds_wgs84: dict[str, float] | None = None
    width: int | None = None
    height: int | None = None
    data_type: str | None = None
    nodata: int | float | None = None
    valid_pixel_count: int | None = None
    provenance: str
    message: str | None = None
    temporary: bool = False


class GISLayerCatalog(BaseModel):
    layers: list[GISLayer]
    limitations: list[str]


class GISInspectRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    river_id: Literal["both", "kaveri", "tungabhadra"] = "both"
    layer_ids: list[str] = Field(default_factory=list, max_length=20)


class GISMeasurementRequest(BaseModel):
    geometry: dict[str, Any]


class GISImportResponse(BaseModel):
    layer: GISLayer
