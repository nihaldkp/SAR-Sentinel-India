from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VegetationAssessmentProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    river_id: Literal["kaveri", "tungabhadra"]
    item_id: str = Field(min_length=1, max_length=512)
    index_name: Literal["ndvi", "evi", "ndmi"]
    domain: Literal["agriculture", "forest"]
    reference_dataset: str = Field(min_length=1, max_length=256)
    reference_provider: str = Field(min_length=1, max_length=256)
    reference_source: str = Field(min_length=1, max_length=2000)
    reference_license: str = Field(min_length=1, max_length=256)
    reference_acquisition_datetime: datetime
    reference_resolution_m: float = Field(gt=0, le=100000)
    landcover_dataset: str = Field(min_length=1, max_length=256)
    landcover_provider: str = Field(min_length=1, max_length=256)
    landcover_source: str = Field(min_length=1, max_length=2000)
    landcover_license: str = Field(min_length=1, max_length=256)
    landcover_acquisition_datetime: datetime
    landcover_resolution_m: float = Field(gt=0, le=100000)
    reviewer: str = Field(min_length=1, max_length=256)
    review_date: date
    methodology: str = Field(min_length=1, max_length=4000)
    limitations: list[str] = Field(min_length=1, max_length=50)
    independence_attested: Literal[True] = Field(description="The numerical reference and reviewed labels are independent of the candidate Sentinel-2 imagery and its derivatives.")
    review_completed: Literal[True] = Field(description="The operator attests that the reference and class labels were independently reviewed.")
    no_pseudoreplication_attested: Literal[True] = Field(description="Each paired numeric measurement represents a distinct reference sample; resampling has not replicated measurements into multiple evaluation pixels.")
    maximum_time_difference_days: float = Field(ge=0, le=3650)
    minimum_common_pixels: int = Field(ge=2, le=2_000_000)
    minimum_coverage_fraction: float = Field(gt=0, le=1)
    minimum_pixels_per_class: int = Field(ge=1, le=2_000_000)
    spatial_block_size_pixels: int = Field(ge=1, le=2_000_000)
    minimum_target_blocks: int = Field(ge=1, le=2_000_000)
    maximum_rmse: float = Field(ge=0, le=1000)

    @field_validator("item_id")
    @classmethod
    def safe_item(cls, value: str) -> str:
        if "/" in value or "\\" in value or ".." in value or not value.strip():
            raise ValueError("Invalid item identifier.")
        return value

    @field_validator("reference_acquisition_datetime", "landcover_acquisition_datetime")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("Reference timestamps must include a timezone.")
        return value

    @field_validator("reference_source", "landcover_source")
    @classmethod
    def no_secret_urls(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme and (parsed.query or parsed.fragment or parsed.username or parsed.password):
            raise ValueError("Source URLs must not contain credentials, query strings, or fragments.")
        return value

    @model_validator(mode="after")
    def nonblank(self):
        for field in ("reference_dataset", "reference_provider", "reference_source", "reference_license",
                      "landcover_dataset", "landcover_provider", "landcover_source", "landcover_license",
                      "reviewer", "methodology"):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} must not be blank.")
        if any(not item.strip() for item in self.limitations):
            raise ValueError("Limitations must not be blank.")
        return self
