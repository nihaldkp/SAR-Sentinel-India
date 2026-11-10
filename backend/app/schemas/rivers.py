from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class NisarPreparedEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    supported: Literal[True] = True
    acquisition_datetime: str | None = None
    polarizations: list[str] = Field(default_factory=list)
    geographic_footprint: dict[str, Any] | None = None
    processed_water_masks: list[dict[str, Any]] = Field(default_factory=list)
    extracted_riverbank_boundaries: list[dict[str, Any]] = Field(default_factory=list)
    multi_date_change_detection_results: list[dict[str, Any]] = Field(default_factory=list)


class RiverGeometry(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: Literal["LineString", "MultiLineString"]
    coordinates: list[list[list[float]]] | list[list[float]]


class River(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    states: str = Field(min_length=1)
    geographical_location: str = Field(min_length=1)
    data_source: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    retrieval_url: str = Field(min_length=1)
    osm_element_type: Literal["way", "relation"]
    osm_element_id: int = Field(gt=0)
    retrieval_date: str = Field(min_length=1)
    license: str = Field(min_length=1)
    license_url: str = Field(min_length=1)
    upstream_quality_note: str | None = None
    available_geographical_data: list[str] = Field(default_factory=list)
    boundary_data_status: Literal["available", "unavailable"]
    left_bank_boundary: RiverGeometry | None = None
    right_bank_boundary: RiverGeometry | None = None
    centerline: RiverGeometry
    future_nisar_integration: NisarPreparedEnvelope = Field(default_factory=NisarPreparedEnvelope)
