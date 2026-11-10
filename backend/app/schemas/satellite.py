from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic import field_validator

from app.redaction import redact_sensitive_text, redact_url


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

    @field_validator("metadata_url", "download_url", mode="before")
    @classmethod
    def redact_external_urls(cls, value: str | None) -> str | None:
        return redact_url(value)


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

    @field_validator("source_url", mode="before")
    @classmethod
    def redact_source_url(cls, value: str) -> str:
        return redact_url(value) or ""

    @field_validator("note", mode="before")
    @classmethod
    def redact_note(cls, value: str) -> str:
        return redact_sensitive_text(value)
