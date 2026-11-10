from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Mission = Literal["NISAR", "SENTINEL-1"]


class SatelliteObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    mission: Mission
    platform: str | None = None
    sensor: str | None = None
    acquisition_start: datetime | None = None
    acquisition_end: datetime | None = None
    polarization: str | None = None
    product_type: str | None = None
    footprint: dict[str, Any] | None = None
    metadata_url: str | None = None
    download_url: str | None = None
    file_size_bytes: int | None = Field(default=None, ge=0)
    source: Literal["ASF DAAC"]
    analysis_readiness: str


class SatelliteSearchResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    river_id: str
    mission: Mission
    product_type: str
    query_start: datetime
    query_end: datetime
    source: Literal["ASF DAAC"]
    source_url: str
    observations: list[SatelliteObservation]
    note: str
