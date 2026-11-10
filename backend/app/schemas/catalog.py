from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: Literal["ok"]
    data_mode: Literal["demonstration"]


class Region(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    basin: str = Field(min_length=1)
    state: str = Field(min_length=1)
    center_latitude: float = Field(ge=-90, le=90)
    center_longitude: float = Field(ge=-180, le=180)
    data_mode: Literal["demonstration"]
    is_simulated: Literal[True]


class Observation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    region_id: str = Field(min_length=1)
    scenario_date: date
    label: str = Field(min_length=1)
    source: Literal["synthetic_demo"]
    product_type: Literal["illustrative_backscatter_scenario"]
    is_simulated: Literal[True]
    status: Literal["demonstration_only"]
