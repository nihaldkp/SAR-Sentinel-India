from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.schemas.acquisitions import NisarProduct

PRODUCTION_DATA_ROOT = Path(__file__).resolve().parents[1] / "data" / "production"
PRODUCTION_CATALOGUE_PATH = PRODUCTION_DATA_ROOT / "catalogue.json"
MAX_CATALOGUE_BYTES = 256 * 1024
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024


class ProductionCatalogueError(RuntimeError):
    pass


class PackagedGeoJSON(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    relative_path: str
    size_bytes: int = Field(gt=0, le=MAX_ARTIFACT_BYTES)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    crs: Literal["EPSG:4326"]
    feature_count: int = Field(gt=0)
    vectorization_truncated: bool

    @field_validator("relative_path")
    @classmethod
    def require_safe_relative_path(cls, value: str) -> str:
        if "\\" in value or ":" in value or value.startswith("/"):
            raise ValueError("Packaged artifact paths must be relative POSIX paths.")
        path = PurePosixPath(value)
        if not path.parts or path.is_absolute() or any(
            part in {"", ".", ".."} for part in path.parts
        ):
            raise ValueError("Packaged artifact paths must not contain traversal components.")
        return path.as_posix()


class ProductionRiverStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    river_id: str
    nisar_status: Literal["metadata_found", "no_data"]
    last_checked_at: datetime
    nisar_product_id: str | None = None
    nisar_acquisition_start: datetime | None = None
    message: str

    @field_validator("last_checked_at", "nisar_acquisition_start")
    @classmethod
    def require_aware_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Production catalogue timestamps must include a timezone.")
        return value


class ProductionNisarRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    river_id: str
    processing_status: Literal["unvalidated_candidate", "no_data"]
    source_availability: str
    product: NisarProduct
    candidate_geojson: PackagedGeoJSON | None = None

    @model_validator(mode="after")
    def validate_record(self) -> "ProductionNisarRecord":
        result = self.product.processing_result
        acquisition_start = self.product.acquisition_start
        if (
            self.product.artifact_availability != "metadata_only"
            or self.product.local_path is not None
            or self.product.source_url is not None
            or self.product.source_url_reference is not None
            or self.product.size_bytes is None
            or self.product.size_bytes <= 0
            or self.product.sha256 is None
            or not re.fullmatch(r"[a-f0-9]{64}", self.product.sha256)
            or acquisition_start is None
            or acquisition_start.tzinfo is None
            or acquisition_start.utcoffset() is None
            or self.product.acquisition_identifier != self.product.product_id
            or self.product.structure_verification_status != "verified"
            or self.product.scientific_validation_status != "not_performed"
            or result is None
            or result.river_id != self.river_id
            or result.product_id != self.product.product_id
        ):
            raise ValueError("Packaged NISAR records must be metadata-only and internally consistent.")
        expected_result_status = (
            "unvalidated_candidate"
            if self.processing_status == "unvalidated_candidate"
            else "no_valid_corridor_data"
        )
        if result.status != expected_result_status:
            raise ValueError("Packaged processing status does not match the recorded result.")
        expected_product_status = (
            "processed" if self.processing_status == "unvalidated_candidate" else "no_data"
        )
        if self.product.processing_status != expected_product_status:
            raise ValueError("Packaged acquisition status does not match its processing result.")
        if self.processing_status == "unvalidated_candidate" and self.candidate_geojson is None:
            raise ValueError("A candidate record must declare its display GeoJSON artifact.")
        if self.processing_status == "no_data" and self.candidate_geojson is not None:
            raise ValueError("A no-data record must not declare a candidate GeoJSON artifact.")
        return self


class ProductionCatalogue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    rivers: list[ProductionRiverStatus] = Field(min_length=1)
    records: list[ProductionNisarRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_records(self) -> "ProductionCatalogue":
        river_ids = [river.river_id for river in self.rivers]
        product_ids = [(record.river_id, record.product.product_id) for record in self.records]
        if len(river_ids) != len(set(river_ids)):
            raise ValueError("Packaged river statuses must be unique.")
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("Packaged NISAR records must be unique.")
        if any(record.river_id not in river_ids for record in self.records):
            raise ValueError("Every packaged product must have a matching river status.")
        return self


def _resolve_asset_path(relative_path: str, artifact_root: Path) -> Path:
    root = artifact_root.resolve()
    path = (root / Path(*PurePosixPath(relative_path).parts)).resolve()
    if not path.is_relative_to(root):
        raise ProductionCatalogueError("A packaged artifact path is outside the production data directory.")
    return path


def _validate_artifacts(catalogue: ProductionCatalogue, artifact_root: Path) -> None:
    for record in catalogue.records:
        artifact = record.candidate_geojson
        if artifact is None:
            continue
        path = _resolve_asset_path(artifact.relative_path, artifact_root)
        try:
            data = path.read_bytes()
        except OSError as error:
            raise ProductionCatalogueError("A declared production GeoJSON artifact is missing.") from error
        if (
            len(data) != artifact.size_bytes
            or hashlib.sha256(data).hexdigest() != artifact.sha256
        ):
            raise ProductionCatalogueError("A production GeoJSON artifact failed its SHA-256 check.")
        try:
            geojson = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProductionCatalogueError("A production GeoJSON artifact is invalid JSON.") from error
        if not isinstance(geojson, dict):
            raise ProductionCatalogueError(
                "A production GeoJSON artifact must be a FeatureCollection object."
            )
        crs_metadata = geojson.get("crs")
        crs_properties = (
            crs_metadata.get("properties") if isinstance(crs_metadata, dict) else None
        )
        features = geojson.get("features")
        crs = crs_properties.get("name") if isinstance(crs_properties, dict) else None
        if (
            geojson.get("type") != "FeatureCollection"
            or crs != artifact.crs
            or not isinstance(features, list)
            or len(features) != artifact.feature_count
        ):
            raise ProductionCatalogueError("A production GeoJSON artifact does not match its catalogue metadata.")


def _load_catalogue(path: Path, artifact_root: Path) -> ProductionCatalogue:
    try:
        data = path.read_bytes()
        if len(data) > MAX_CATALOGUE_BYTES:
            raise ProductionCatalogueError("The packaged production catalogue exceeds its size limit.")
        catalogue = ProductionCatalogue.model_validate(json.loads(data))
    except ProductionCatalogueError:
        raise
    except FileNotFoundError as error:
        raise ProductionCatalogueError("The packaged production catalogue is missing.") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        raise ProductionCatalogueError("The packaged production catalogue is invalid.") from error
    _validate_artifacts(catalogue, artifact_root)
    return catalogue


@lru_cache(maxsize=1)
def _load_default_catalogue() -> ProductionCatalogue:
    return _load_catalogue(PRODUCTION_CATALOGUE_PATH, PRODUCTION_DATA_ROOT)


def load_production_catalogue(
    path: Path | None = None,
    artifact_root: Path | None = None,
) -> ProductionCatalogue:
    if path is None and artifact_root is None:
        return _load_default_catalogue()
    return _load_catalogue(
        path or PRODUCTION_CATALOGUE_PATH,
        artifact_root or PRODUCTION_DATA_ROOT,
    )


def get_record(river_id: str, product_id: str) -> ProductionNisarRecord | None:
    catalogue = load_production_catalogue()
    return next(
        (
            record
            for record in catalogue.records
            if record.river_id == river_id and record.product.product_id == product_id
        ),
        None,
    )


def get_candidate_geojson_path(river_id: str, product_id: str) -> Path:
    record = get_record(river_id, product_id)
    if record is None or record.candidate_geojson is None:
        raise FileNotFoundError(f"No packaged candidate GeoJSON is available for {river_id}/{product_id}.")
    return _resolve_asset_path(record.candidate_geojson.relative_path, PRODUCTION_DATA_ROOT)
