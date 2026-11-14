from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorkspaceReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: Literal[
        "Overview", "Map explorer", "Change analysis", "Impact explorer",
        "Agriculture", "Forest monitoring", "AI analysis", "Data & methodology",
        "About the project",
    ]
    river_id: Literal["both", "kaveri", "tungabhadra"]
    selected_product_id: str | None = Field(default=None, max_length=250)
    selected_analysis_id: str | None = Field(default=None, max_length=250)
    selected_optical_item_id: str | None = Field(default=None, max_length=250)
    selected_network_id: str | None = Field(default=None, max_length=200)
    map_layer: Literal["centerline", "satellite footprint", "candidate mask", "Sentinel-2 NDWI candidate"] = "centerline"
    vegetation_river_id: Literal["kaveri", "tungabhadra"] | None = None
    vegetation_item_id: str | None = Field(default=None, max_length=250)
    index_name: Literal["ndvi", "evi", "ndmi"] | None = None

    @model_validator(mode="after")
    def check_vegetation_context(self):
        if (self.vegetation_river_id is None) != (self.vegetation_item_id is None):
            raise ValueError("Vegetation river and item must be provided together.")
        if self.vegetation_river_id and self.river_id not in ("both", self.vegetation_river_id):
            raise ValueError("The selected vegetation observation is outside the selected river.")
        if self.vegetation_item_id and not self.index_name:
            raise ValueError("The selected vegetation observation requires an index.")
        if self.workspace not in ("Agriculture", "Forest monitoring") and (
            self.vegetation_item_id or self.index_name
        ):
            raise ValueError("Vegetation context is only supported on land-monitoring workspaces.")
        return self
