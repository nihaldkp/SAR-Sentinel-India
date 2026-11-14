from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Generator, Protocol
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from pydantic import BaseModel

from app.redaction import redact_sensitive_text, redact_url
from app.schemas.integration import (
    AcquisitionVerification,
    GISAdapterInput,
    GISJobCreate,
    IntegrationAssociation,
    IntegrationAssociationCreate,
    IntegrationJob,
    IntegrationOutput,
    IntegrationJobStatus,
    IntegrationJobType,
    OutputAssetRegistration,
    OutputRegistrationRequest,
    ProcessingAdapterInput,
    ProcessingJobCreate,
    VerifiedAcquisition,
)
from app.services import acquisitions
from app.services.rivers import RIVER_CATALOG

LOGGER = logging.getLogger(__name__)
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
OUTPUT_ROOT = Path(__file__).resolve().parents[3] / "outputs" / "integration"
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="integration-job")
_SCHEDULE_LOCK = threading.Lock()
_SCHEDULED: set[str] = set()
_ADAPTERS_LOCK = threading.Lock()


class ProcessingAdapter(Protocol):
    def process(self, request: ProcessingAdapterInput) -> OutputRegistrationRequest: ...


class GISAdapter(Protocol):
    def analyze(self, request: GISAdapterInput) -> OutputRegistrationRequest: ...


_processing_adapter: ProcessingAdapter | None = None
_gis_adapter: GISAdapter | None = None


class IntegrationJobNotRetryable(RuntimeError):
    pass


class IntegrationOutputUnavailable(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _database_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS integration_jobs (
            job_id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL CHECK(job_type IN ('sar_processing', 'gis_analysis')),
            status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'blocked', 'completed', 'failed')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            request_sha256 TEXT NOT NULL,
            request_json TEXT NOT NULL,
            result_json TEXT NOT NULL DEFAULT '{}',
            error_code TEXT,
            error_message TEXT,
            retry_of_job_id TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS integration_outputs (
            output_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES integration_jobs(job_id),
            role TEXT NOT NULL,
            storage_key TEXT NOT NULL,
            output_type TEXT NOT NULL CHECK(output_type IN ('raster', 'vector', 'metadata')),
            media_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL CHECK(size_bytes > 0),
            sha256 TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            UNIQUE(job_id, role)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS integration_associations (
            association_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES integration_jobs(job_id),
            target_type TEXT NOT NULL CHECK(target_type IN ('river', 'region')),
            target_id TEXT NOT NULL,
            associated_at TEXT NOT NULL,
            UNIQUE(job_id, target_type, target_id)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_integration_jobs_created ON integration_jobs(created_at DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_integration_outputs_job ON integration_outputs(job_id)"
    )


@contextmanager
def _connection_schema() -> Generator[sqlite3.Connection, None, None]:
    connection = acquisitions._database()
    try:
        _database_schema(connection)
        connection.commit()
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()



def _json_text(value: Any) -> str:
    def normalize(item: Any) -> Any:
        if isinstance(item, float):
            if math.isnan(item):
                return "NaN"
            if math.isinf(item):
                return "Infinity" if item > 0 else "-Infinity"
            return item

        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}

        if isinstance(item, (list, tuple)):
            return [normalize(child) for child in item]

        return item

    try:
        return json.dumps(
            normalize(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Integration request and result values must be finite JSON data."
        ) from error



def _reject_secrets(value: Any) -> None:
    sensitive_keys = {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "cookie",
        "credential",
        "earthdata_token",
        "password",
        "refresh_token",
        "sas",
        "secret",
        "sig",
        "signature",
        "token",
        "x_amz_credential",
        "x_amz_security_token",
        "x_amz_signature",
    }

    def inspect(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                normalized_key = str(key).casefold().replace("-", "_")
                if normalized_key in sensitive_keys:
                    raise ValueError(
                        "Integration metadata must not contain credentials or credential-bearing URLs."
                    )
                inspect(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                inspect(child)
        elif isinstance(item, str) and redact_sensitive_text(item) != item:
            raise ValueError(
                "Integration metadata must not contain credentials or credential-bearing URLs."
            )

    inspect(value)
    encoded = _json_text(value)
    if redact_sensitive_text(encoded) != encoded:
        raise ValueError("Integration metadata must not contain credentials or credential-bearing URLs.")
    for token in ("x-amz-signature", "x-amz-credential", "x-amz-security-token"):
        if token in encoded.casefold():
            raise ValueError("Integration metadata must not contain signed URLs.")


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _safe_source_reference(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme.casefold() != "https" or not parts.netloc or "@" in parts.netloc:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _product_records(river_id: str | None = None) -> list[tuple[str, dict[str, Any], Path]]:
    river_ids = [river_id] if river_id is not None else [river.id for river in RIVER_CATALOG]
    verified: list[tuple[str, dict[str, Any], Path]] = []
    for selected_river_id in river_ids:
        local_records = {
            item.get("product_id"): item
            for item in acquisitions._local_nisar_product_records(selected_river_id)
            if item.get("structure_verification_status") == "verified"
            and item.get("download_status") == "downloaded"
            and item.get("sha256")
            and item.get("integrity_status") in {
                "provider_checksum_verified",
                "sha256_fingerprint_only",
            }
        }
        for product_id, local_record in local_records.items():
            try:
                catalog_record, path = acquisitions._nisar_product_record(
                    selected_river_id,
                    product_id,
                )
            except (FileNotFoundError, ValueError):
                continue
            if (
                catalog_record.get("structure_verification_status") != "verified"
                or catalog_record.get("sha256") != local_record.get("sha256")
                or path.stat().st_size != local_record.get("size_bytes")
            ):
                continue
            verified.append((selected_river_id, local_record, path))
    return verified


def _verified_acquisition(
    river_id: str,
    product_id: str,
) -> tuple[VerifiedAcquisition, dict[str, Any], Path]:
    if river_id not in {river.id for river in RIVER_CATALOG}:
        raise ValueError(f"Unknown river_id: {river_id}")
    record = next(
        (
            item
            for selected_river, item, _ in _product_records(river_id)
            if selected_river == river_id and item.get("product_id") == product_id
        ),
        None,
    )
    if record is None:
        raise FileNotFoundError(
            f"No locally present NISAR acquisition with recorded structure verification was found for {river_id}/{product_id}."
        )
    catalog_record, path = acquisitions._nisar_product_record(river_id, product_id)
    acquisition_start = record.get("acquisition_start")
    if not isinstance(acquisition_start, str):
        raise ValueError("The verified NISAR acquisition has no timezone-aware acquisition time.")
    try:
        start = _time(acquisition_start)
        end_value = record.get("acquisition_end")
        end = _time(end_value) if isinstance(end_value, str) else None
        verification = VerifiedAcquisition(
            river_id=river_id,
            product_id=product_id,
            product_type="GCOV",
            acquisition_start=start,
            acquisition_end=end,
            file_reference=path.relative_to(acquisitions.REPOSITORY_ROOT).as_posix(),
            file_size_bytes=path.stat().st_size,
            sha256=record["sha256"],
            integrity_status=record["integrity_status"],
            structure_verification_status="verified",
            provider_authenticity_status=record.get(
                "provider_authenticity_status",
                "not_verified",
            ),
            scientific_validation_status="not_performed",
            source_url_reference=_safe_source_reference(record.get("source_url_reference")),
            download_timestamp=(
                _time(record["download_timestamp"])
                if isinstance(record.get("download_timestamp"), str)
                else None
            ),
            provider_checksum_algorithm=record.get("provider_checksum_algorithm"),
            provider_checksum=record.get("provider_checksum"),
        )
    except (KeyError, TypeError, OSError, ValueError) as error:
        raise ValueError("The recorded NISAR verification metadata is incomplete or inconsistent.") from error
    if catalog_record.get("product_id") != verification.product_id:
        raise ValueError("The NISAR catalog identity does not match the requested product.")
    return verification, record, path


def list_verified_acquisitions(
    *,
    river_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    if river_id is not None and river_id not in {river.id for river in RIVER_CATALOG}:
        raise ValueError(f"Unknown river_id: {river_id}")
    records = _product_records(river_id)
    acquisitions_list = []
    for selected_river_id, record, path in records:
        start = record.get("acquisition_start")
        if not isinstance(start, str):
            continue
        item = VerifiedAcquisition(
            river_id=selected_river_id,
            product_id=record["product_id"],
            product_type="GCOV",
            acquisition_start=_time(start),
            acquisition_end=(
                _time(record["acquisition_end"])
                if isinstance(record.get("acquisition_end"), str)
                else None
            ),
            file_reference=path.relative_to(acquisitions.REPOSITORY_ROOT).as_posix(),
            file_size_bytes=path.stat().st_size,
            sha256=record["sha256"],
            integrity_status=record["integrity_status"],
            structure_verification_status="verified",
            provider_authenticity_status=record.get(
                "provider_authenticity_status",
                "not_verified",
            ),
            scientific_validation_status="not_performed",
            source_url_reference=_safe_source_reference(record.get("source_url_reference")),
            download_timestamp=(
                _time(record["download_timestamp"])
                if isinstance(record.get("download_timestamp"), str)
                else None
            ),
            provider_checksum_algorithm=record.get("provider_checksum_algorithm"),
            provider_checksum=record.get("provider_checksum"),
        )
        acquisitions_list.append(item)
    acquisitions_list.sort(key=lambda item: item.acquisition_start, reverse=True)
    return {
        "total": len(acquisitions_list),
        "limit": limit,
        "offset": offset,
        "items": acquisitions_list[offset : offset + limit],
    }


def get_verified_acquisition(river_id: str, product_id: str) -> VerifiedAcquisition:
    return _verified_acquisition(river_id, product_id)[0]


def get_acquisition_verification(
    river_id: str,
    product_id: str,
) -> AcquisitionVerification:
    acquisition, _, _ = _verified_acquisition(river_id, product_id)
    return AcquisitionVerification(
        product_id=product_id,
        acquisition_identifier=product_id,
        file_size_bytes=acquisition.file_size_bytes,
        sha256=acquisition.sha256,
        integrity_status=acquisition.integrity_status,
        structure_verification_status="verified",
        provider_authenticity_status=acquisition.provider_authenticity_status,
        provider_checksum_algorithm=acquisition.provider_checksum_algorithm,
        provider_checksum=acquisition.provider_checksum,
        scientific_validation_status="not_performed",
        verified_at=acquisition.download_timestamp,
        verification_scope="recorded_download_verification",
    )


def _output_from_row(row: sqlite3.Row) -> IntegrationOutput:
    return IntegrationOutput(
        output_id=row["output_id"],
        job_id=row["job_id"],
        role=row["role"],
        storage_key=row["storage_key"],
        output_type=row["output_type"],
        media_type=row["media_type"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        registered_at=_time(row["registered_at"]),
        metadata=json.loads(row["metadata_json"]),
    )


def _read_job(job_id: str, connection: sqlite3.Connection) -> IntegrationJob | None:
    row = connection.execute(
        "SELECT * FROM integration_jobs WHERE job_id=?",
        (job_id,),
    ).fetchone()
    if row is None:
        return None
    outputs = connection.execute(
        "SELECT * FROM integration_outputs WHERE job_id=? ORDER BY role",
        (job_id,),
    ).fetchall()
    associations = connection.execute(
        "SELECT * FROM integration_associations WHERE job_id=? ORDER BY associated_at, association_id",
        (job_id,),
    ).fetchall()
    result = json.loads(row["result_json"] or "{}")
    return IntegrationJob(
        job_id=row["job_id"],
        job_type=row["job_type"],
        status=row["status"],
        created_at=_time(row["created_at"]),
        updated_at=_time(row["updated_at"]),
        retry_of_job_id=row["retry_of_job_id"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        request=json.loads(row["request_json"]),
        result_metadata=result.get("result_metadata", {}),
        spatial_results=result.get("spatial_results"),
        metrics=result.get("metrics", {}),
        outputs=[_output_from_row(item) for item in outputs],
        associations=[
            IntegrationAssociation(
                association_id=item["association_id"],
                job_id=item["job_id"],
                target_type=item["target_type"],
                target_id=item["target_id"],
                associated_at=_time(item["associated_at"]),
            )
            for item in associations
        ],
    )


def get_job(job_id: str, job_type: IntegrationJobType | None = None) -> IntegrationJob | None:
    with _connection_schema() as connection:
        if job_type is not None:
            row = connection.execute(
                "SELECT 1 FROM integration_jobs WHERE job_id=? AND job_type=?",
                (job_id, job_type),
            ).fetchone()
            if row is None:
                return None
        return _read_job(job_id, connection)


def list_jobs(
    *,
    job_type: IntegrationJobType,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    with _connection_schema() as connection:
        total = connection.execute(
            "SELECT COUNT(*) FROM integration_jobs WHERE job_type=?",
            (job_type,),
        ).fetchone()[0]
        rows = connection.execute(
            """
            SELECT job_id FROM integration_jobs
            WHERE job_type=?
            ORDER BY created_at DESC, job_id
            LIMIT ? OFFSET ?
            """,
            (job_type, limit, offset),
        ).fetchall()
        items = [
            job
            for row in rows
            if (job := _read_job(row["job_id"], connection)) is not None
        ]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


def _adapter_for(job_type: IntegrationJobType) -> ProcessingAdapter | GISAdapter | None:
    with _ADAPTERS_LOCK:
        return _processing_adapter if job_type == "sar_processing" else _gis_adapter


def configure_processing_adapters(
    *,
    sar: ProcessingAdapter | None = None,
    gis: GISAdapter | None = None,
) -> None:
    """Install optional teammate implementations; None leaves jobs explicitly blocked."""
    global _processing_adapter, _gis_adapter
    with _ADAPTERS_LOCK:
        _processing_adapter = sar
        _gis_adapter = gis
    with _connection_schema() as connection:
        rows = connection.execute(
            "SELECT job_id, job_type FROM integration_jobs WHERE status='blocked'"
        ).fetchall()
    for row in rows:
        if _adapter_for(row["job_type"]) is not None:
            _schedule(row["job_id"])


def _request_payload(request: BaseModel) -> dict[str, Any]:
    payload = request.model_dump(mode="json")
    _reject_secrets(payload)
    return payload


def _create_job(
    job_type: IntegrationJobType,
    request: BaseModel,
    *,
    retry_of_job_id: str | None = None,
) -> IntegrationJob:
    payload = _request_payload(request)
    serialized = _json_text(payload)
    request_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    now = _now().isoformat()
    job_id = str(uuid.uuid4())
    adapter_available = _adapter_for(job_type) is not None
    initial_status: IntegrationJobStatus = "queued" if adapter_available else "blocked"
    initial_error = None if adapter_available else "No processing adapter is registered."
    with _connection_schema() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if retry_of_job_id is None:
            existing = connection.execute(
                """
                SELECT job_id FROM integration_jobs
                WHERE job_type=? AND request_sha256=?
                ORDER BY created_at DESC LIMIT 1
                """,
                (job_type, request_hash),
            ).fetchone()
            if existing is not None:
                existing_job = _read_job(existing["job_id"], connection)
                if existing_job is not None:
                    return existing_job
        connection.execute(
            """
            INSERT INTO integration_jobs(
                job_id, job_type, status, created_at, updated_at,
                request_sha256, request_json, error_code, error_message, retry_of_job_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                job_type,
                initial_status,
                now,
                now,
                request_hash,
                serialized,
                None if adapter_available else "adapter_unavailable",
                initial_error,
                retry_of_job_id,
            ),
        )
    if adapter_available:
        _schedule(job_id)
    job = get_job(job_id, job_type)
    if job is None:
        raise RuntimeError("The integration job could not be read back from SQLite.")
    return job


def create_processing_job(request: ProcessingJobCreate) -> IntegrationJob:
    if request.river_id not in {river.id for river in RIVER_CATALOG}:
        raise ValueError(f"Unknown river_id: {request.river_id}")
    _verified_acquisition(request.river_id, request.product_id)
    return _create_job("sar_processing", request)


def create_gis_job(request: GISJobCreate) -> IntegrationJob:
    if request.river_id is not None and request.river_id not in {
        river.id for river in RIVER_CATALOG
    }:
        raise ValueError(f"Unknown river_id: {request.river_id}")
    if request.region_id is not None:
        from app.services.catalog import DEMO_REGIONS

        if any(region.id == request.region_id for region in DEMO_REGIONS):
            raise ValueError("Demonstration-only regions cannot be targets for observation analysis.")
        raise FileNotFoundError(
            "No non-demonstration region catalogue is registered for GIS integration."
        )
    for output_id in request.input_output_ids:
        output = get_output(output_id)
        if output is None:
            raise FileNotFoundError(f"Registered processing output {output_id} was not found.")
        source_job = get_job(output.job_id, "sar_processing")
        if source_job is None or source_job.status != "completed":
            raise ValueError("GIS inputs must reference outputs from completed SAR processing jobs.")
        _verify_output_unchanged(output)
    return _create_job("gis_analysis", request)


def get_output(output_id: str) -> IntegrationOutput | None:
    with _connection_schema() as connection:
        row = connection.execute(
            "SELECT * FROM integration_outputs WHERE output_id=?",
            (output_id,),
        ).fetchone()
    return _output_from_row(row) if row else None


def _storage_path(job_id: str, storage_key: str) -> Path:
    key = PurePosixPath(storage_key)
    if not key.parts or key.parts[0] != job_id:
        raise ValueError("Output files must be stored under their integration job directory.")
    root = OUTPUT_ROOT.resolve()
    unresolved_path = root
    for part in key.parts:
        unresolved_path = unresolved_path / part
        if unresolved_path.is_symlink():
            raise FileNotFoundError("Output files must not use symbolic links.")
    path = unresolved_path.resolve()
    if (
        not path.is_relative_to(root)
        or path.relative_to(root).parts[0] != job_id
        or not path.is_file()
        or path.is_symlink()
    ):
        raise FileNotFoundError("The registered output file is missing or outside its job directory.")
    return path


def _file_sha256(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    if size == 0:
        raise ValueError("Output files must not be empty.")
    return size, digest.hexdigest()


def _validate_output_format(output: OutputAssetRegistration) -> None:
    extension = PurePosixPath(output.storage_key).suffix.casefold()
    expected = {
        "raster": {".tif", ".tiff"},
        "vector": {".geojson", ".gpkg"},
        "metadata": {".json"},
    }[output.output_type]
    if extension not in expected:
        raise ValueError(f"{output.output_type} outputs must use one of: {', '.join(sorted(expected))}.")
    expected_media_types = {
        "raster": {"image/tiff"},
        "vector": {"application/geo+json", "application/geopackage+sqlite3"},
        "metadata": {"application/json"},
    }
    if output.media_type.casefold() not in expected_media_types[output.output_type]:
        raise ValueError(f"Unsupported media_type for {output.output_type} output.")
    _reject_secrets(output.model_dump(mode="json"))
    if output.output_type in {"raster", "vector"}:
        crs = output.metadata.get("crs")
        if not isinstance(crs, str) or not crs.strip():
            raise ValueError("Raster and vector output metadata must declare their CRS.")



def _validate_output_file(
    output: OutputAssetRegistration,
    path: Path,
    size_bytes: int,
) -> None:
    if output.output_type == "raster":
        import rasterio
        from rasterio.crs import CRS

        try:
            with rasterio.open(path) as dataset:
                declared_crs = CRS.from_user_input(output.metadata["crs"])
                declared_transform = tuple(
                    float(value) for value in output.metadata["transform"]
                )
                actual_transform = tuple(
                    float(value) for value in dataset.transform
                )[:6]

                declared_nodata = output.metadata["nodata"]
                actual_nodata = dataset.nodata
                if declared_nodata == "NaN":
                    declared_nodata = float("nan")
                elif declared_nodata == "Infinity":
                    declared_nodata = float("inf")
                elif declared_nodata == "-Infinity":
                    declared_nodata = float("-inf")

                if declared_nodata is None and actual_nodata is None:
                    nodata_matches = True
                elif (
                    isinstance(declared_nodata, (int, float))
                    and not isinstance(declared_nodata, bool)
                    and actual_nodata is not None
                ):
                    declared_value = float(declared_nodata)
                    actual_value = float(actual_nodata)

                    nodata_matches = (
                        math.isnan(declared_value)
                        and math.isnan(actual_value)
                    ) or math.isclose(
                        declared_value,
                        actual_value,
                        rel_tol=0,
                        abs_tol=0,
                    )
                else:
                    nodata_matches = False

                if (
                    dataset.driver != "GTiff"
                    or dataset.count < 1
                    or dataset.width != output.metadata["width"]
                    or dataset.height != output.metadata["height"]
                    or dataset.crs is None
                    or dataset.crs != declared_crs
                    or actual_transform != declared_transform
                    or not nodata_matches
                ):
                    raise ValueError(
                        "Raster file metadata does not match the declared CRS, "
                        "dimensions, transform, or NoData."
                    )

        except (
            rasterio.errors.RasterioError,
            OSError,
            TypeError,
            KeyError,
            ValueError,
        ) as error:
            if isinstance(error, ValueError) and str(error).startswith(
                "Raster file metadata"
            ):
                raise
            raise ValueError(
                "The registered raster is not a readable GeoTIFF "
                "or its metadata is invalid."
            ) from error

    elif output.output_type == "vector" and path.suffix.casefold() == ".geojson":
        if size_bytes > 100 * 1024 * 1024:
            raise ValueError("GeoJSON outputs are limited to 100 MiB.")

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(
                "The registered GeoJSON output is not valid UTF-8 JSON."
            ) from error

        if not isinstance(payload, dict) or payload.get("type") not in {
            "Feature",
            "FeatureCollection",
        }:
            raise ValueError(
                "The GeoJSON output must be a Feature or FeatureCollection."
            )

        if payload["type"] == "FeatureCollection":
            features = payload.get("features")
            if not isinstance(features, list) or any(
                not isinstance(feature, dict)
                or feature.get("type") != "Feature"
                for feature in features
            ):
                raise ValueError(
                    "The GeoJSON FeatureCollection contains invalid features."
                )

        elif not isinstance(payload.get("geometry"), (dict, type(None))):
            raise ValueError("The GeoJSON Feature has an invalid geometry.")

        if output.metadata["crs"].casefold() not in {
            "epsg:4326",
            "ogc:crs84",
        }:
            raise ValueError(
                "GeoJSON output CRS must be EPSG:4326 longitude/latitude."
            )

    elif output.output_type == "vector":
        if size_bytes < 16:
            raise ValueError(
                "The registered GeoPackage output is too small to be valid."
            )

        try:
            with sqlite3.connect(
                f"{path.resolve().as_uri()}?mode=ro",
                uri=True,
            ) as connection:
                application_id = connection.execute(
                    "PRAGMA application_id"
                ).fetchone()[0]

                has_feature_contents = connection.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type='table' AND name='gpkg_contents'"
                ).fetchone()

                if application_id != 0x47504B47 or not has_feature_contents:
                    raise ValueError(
                        "The registered GeoPackage is missing required "
                        "GeoPackage metadata."
                    )

                content_row = connection.execute(
                    "SELECT 1 FROM gpkg_contents "
                    "WHERE data_type='features' LIMIT 1"
                ).fetchone()

                if content_row is None:
                    raise ValueError(
                        "The registered GeoPackage contains no vector feature table."
                    )

        except sqlite3.DatabaseError as error:
            raise ValueError(
                "The registered vector output is not a readable GeoPackage."
            ) from error

    else:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(
                "The registered metadata output is not valid UTF-8 JSON."
            ) from error

        if not isinstance(payload, dict):
            raise ValueError(
                "The registered metadata output must contain a JSON object."
            )



def _verify_output_unchanged(output: IntegrationOutput) -> Path:
    path = _storage_path(output.job_id, output.storage_key)
    size, digest = _file_sha256(path)
    if size != output.size_bytes or digest != output.sha256:
        raise IntegrationOutputUnavailable(
            f"Registered output {output.output_id} changed after registration."
        )
    return path


def _result_provenance(job: IntegrationJob) -> dict[str, Any]:
    provenance: dict[str, Any] = {
        "job_id": job.job_id,
        "job_type": job.job_type,
        "processing_version": job.request["processing_version"],
        "scientific_validation_status": "not_performed",
    }
    if job.job_type == "sar_processing":
        acquisition, record, _ = _verified_acquisition(
            job.request["river_id"],
            job.request["product_id"],
        )
        provenance["source_acquisition"] = {
            "river_id": acquisition.river_id,
            "product_id": acquisition.product_id,
            "product_type": acquisition.product_type,
            "file_size_bytes": acquisition.file_size_bytes,
            "sha256": acquisition.sha256,
            "integrity_status": acquisition.integrity_status,
            "provider_authenticity_status": acquisition.provider_authenticity_status,
            "download_timestamp": record.get("download_timestamp"),
        }
    else:
        input_sources: list[dict[str, Any]] = []
        for output_id in job.request["input_output_ids"]:
            output = get_output(output_id)
            if output is None:
                raise IntegrationOutputUnavailable(
                    f"GIS input output {output_id} is no longer registered."
                )
            source_job = get_job(output.job_id, "sar_processing")
            if source_job is None or source_job.status != "completed":
                raise IntegrationOutputUnavailable(
                    f"GIS input output {output_id} has no completed source job."
                )
            input_sources.append(
                {
                    "output_id": output.output_id,
                    "output_sha256": output.sha256,
                    "source_job_id": source_job.job_id,
                    "source_acquisition": source_job.result_metadata.get(
                        "provenance", {}
                    ).get("source_acquisition"),
                }
            )
        provenance["input_sources"] = input_sources
    return provenance


def _register_outputs(
    job_id: str,
    request: OutputRegistrationRequest,
    *,
    adapter_result: bool,
) -> IntegrationJob:
    _reject_secrets(request.model_dump(mode="json"))
    job = get_job(job_id)
    if job is None:
        raise FileNotFoundError(f"Integration job {job_id} was not found.")
    if job.status not in ({"running"} if adapter_result else {"blocked"}):
        raise IntegrationJobNotRetryable(
            "Outputs can be registered only while an adapter is running or when its job is blocked."
        )
    if job.job_type == "gis_analysis" and request.spatial_results is None:
        raise ValueError("GIS output registration must include spatial_results.")
    prepared: list[tuple[OutputAssetRegistration, Path, int, str]] = []
    for output in request.outputs:
        _validate_output_format(output)
        path = _storage_path(job_id, output.storage_key)
        size, digest = _file_sha256(path)
        _validate_output_file(output, path, size)
        prepared.append((output, path, size, digest))
    provenance = _result_provenance(job)
    now = _now().isoformat()
    result_payload = _json_text(
        {
            "result_metadata": {
                **request.result_metadata,
                "provenance": provenance,
                "scientific_validation_status": "not_performed",
            },
            "spatial_results": request.spatial_results,
            "metrics": request.metrics,
        }
    )
    with _connection_schema() as connection:
        current = connection.execute(
            "SELECT status FROM integration_jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
        allowed = {"running"} if adapter_result else {"blocked"}
        if current is None:
            raise FileNotFoundError(f"Integration job {job_id} was not found.")
        if current["status"] not in allowed:
            raise IntegrationJobNotRetryable("The integration job state changed before output registration.")
        if connection.execute(
            "SELECT 1 FROM integration_outputs WHERE job_id=? LIMIT 1",
            (job_id,),
        ).fetchone():
            raise IntegrationJobNotRetryable("Outputs are already registered for this job.")
        for output, _, size, digest in prepared:
            connection.execute(
                """
                INSERT INTO integration_outputs(
                    output_id, job_id, role, storage_key, output_type, media_type,
                    size_bytes, sha256, registered_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    job_id,
                    output.role,
                    output.storage_key,
                    output.output_type,
                    output.media_type,
                    size,
                    digest,
                    now,
                    _json_text(
                        {
                            **output.metadata,
                            "provenance": provenance,
                        }
                    ),
                ),
            )
        if job.job_type == "gis_analysis":
            stored_request = json.loads(
                connection.execute(
                    "SELECT request_json FROM integration_jobs WHERE job_id=?",
                    (job_id,),
                ).fetchone()["request_json"]
            )
            target_type = "river" if stored_request.get("river_id") is not None else "region"
            target_id = stored_request.get("river_id") or stored_request.get("region_id")
            connection.execute(
                """
                INSERT OR IGNORE INTO integration_associations(
                    association_id, job_id, target_type, target_id, associated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), job_id, target_type, target_id, now),
            )
        connection.execute(
            """
            UPDATE integration_jobs
            SET status='completed', updated_at=?, result_json=?,
                error_code=NULL, error_message=NULL
            WHERE job_id=?
            """,
            (now, result_payload, job_id),
        )
    result = get_job(job_id)
    if result is None:
        raise RuntimeError("The completed integration job could not be read back from SQLite.")
    return result


def register_outputs(
    job_id: str,
    request: OutputRegistrationRequest,
) -> IntegrationJob:
    return _register_outputs(job_id, request, adapter_result=False)


def _mark_job(
    job_id: str,
    *,
    status: IntegrationJobStatus,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    now = _now().isoformat()
    safe_message = (
        _safe_error(error_message)[:2000]
        if error_message is not None
        else None
    )
    with _connection_schema() as connection:
        connection.execute(
            """
            UPDATE integration_jobs
            SET status=?, updated_at=?, error_code=?, error_message=?
            WHERE job_id=?
            """,
            (status, now, error_code, safe_message, job_id),
        )


def _safe_error(message: str) -> str:
    def sanitize_url(match: re.Match[str]) -> str:
        value = match.group(0)
        try:
            parts = urlsplit(value)
            query_keys = {
                key.casefold()
                for key, _ in parse_qsl(parts.query, keep_blank_values=True)
            }
            if any(
                key.startswith("x-amz-")
                for key in query_keys
            ) or query_keys.intersection({"sig", "signature"}):
                return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            return redact_url(value) or "[REDACTED URL]"
        except ValueError:
            return "[REDACTED URL]"

    return redact_sensitive_text(_URL.sub(sanitize_url, message))


def _execute(job_id: str) -> None:
    job = get_job(job_id)
    if job is None:
        return
    adapter = _adapter_for(job.job_type)
    if adapter is None:
        _mark_job(
            job_id,
            status="blocked",
            error_code="adapter_unavailable",
            error_message="No processing adapter is registered.",
        )
        return
    with _connection_schema() as connection:
        claimed = connection.execute(
            """
            UPDATE integration_jobs SET status='running', updated_at=?,
                error_code=NULL, error_message=NULL
            WHERE job_id=? AND status IN ('queued', 'blocked')
            """,
            (_now().isoformat(), job_id),
        )
        if claimed.rowcount != 1:
            return
    try:
        request = job.request
        output_directory = OUTPUT_ROOT / job_id
        output_directory.mkdir(parents=True, exist_ok=True)
        if job.job_type == "sar_processing":
            acquisition, _, path = _verified_acquisition(
                str(request["river_id"]),
                str(request["product_id"]),
            )
            sar_adapter = _adapter_for("sar_processing")
            if sar_adapter is None or not callable(getattr(sar_adapter, "process", None)):
                raise RuntimeError("The registered SAR adapter does not implement process().")
            adapter_result = sar_adapter.process(
                ProcessingAdapterInput(
                    job_id=job_id,
                    acquisition=acquisition,
                    local_file_path=str(path),
                    output_directory=str(output_directory),
                    processing_config=request["processing_config"],
                    processing_version=request["processing_version"],
                )
            )
        else:
            assets = [
                get_output(output_id)
                for output_id in request["input_output_ids"]
            ]
            if any(asset is None for asset in assets):
                raise FileNotFoundError("A registered GIS input output was removed.")
            actual_assets = [asset for asset in assets if asset is not None]
            input_paths = [str(_verify_output_unchanged(asset)) for asset in actual_assets]
            gis_adapter = _adapter_for("gis_analysis")
            if gis_adapter is None or not callable(getattr(gis_adapter, "analyze", None)):
                raise RuntimeError("The registered GIS adapter does not implement analyze().")
            adapter_result = gis_adapter.analyze(
                GISAdapterInput(
                    job_id=job_id,
                    input_outputs=actual_assets,
                    input_file_paths=input_paths,
                    output_directory=str(output_directory),
                    analysis_type=request["analysis_type"],
                    river_id=request.get("river_id"),
                    region_id=request.get("region_id"),
                    spatial_extent=request.get("spatial_extent"),
                    acquisition_start=(
                        _time(request["acquisition_start"])
                        if request.get("acquisition_start")
                        else None
                    ),
                    acquisition_end=(
                        _time(request["acquisition_end"])
                        if request.get("acquisition_end")
                        else None
                    ),
                    analysis_config=request["analysis_config"],
                    processing_version=request["processing_version"],
                )
            )
        if not isinstance(adapter_result, OutputRegistrationRequest):
            adapter_result = OutputRegistrationRequest.model_validate(adapter_result)
        _register_outputs(job_id, adapter_result, adapter_result=True)
    except Exception as error:
        _mark_job(
            job_id,
            status="failed",
            error_code=type(error).__name__,
            error_message=str(error),
        )
        LOGGER.error(
            "Integration job %s failed (%s)",
            job_id,
            type(error).__name__,
        )


def _schedule(job_id: str) -> None:
    with _SCHEDULE_LOCK:
        if job_id in _SCHEDULED:
            return
        _SCHEDULED.add(job_id)
        future = _EXECUTOR.submit(_execute, job_id)

    def clear_scheduled(_: Future[Any]) -> None:
        with _SCHEDULE_LOCK:
            _SCHEDULED.discard(job_id)

    future.add_done_callback(clear_scheduled)


def retry_job(job_id: str) -> IntegrationJob:
    previous = get_job(job_id)
    if previous is None:
        raise FileNotFoundError(f"Integration job {job_id} was not found.")
    if previous.status not in {"failed", "blocked"}:
        raise IntegrationJobNotRetryable("Only failed or adapter-blocked jobs can be retried.")
    request_model: BaseModel
    if previous.job_type == "sar_processing":
        request_model = ProcessingJobCreate.model_validate(previous.request)
        _verified_acquisition(request_model.river_id, request_model.product_id)
    else:
        request_model = GISJobCreate.model_validate(previous.request)
        for output_id in request_model.input_output_ids:
            output = get_output(output_id)
            if output is None:
                raise FileNotFoundError(f"Registered processing output {output_id} was not found.")
            _verify_output_unchanged(output)
    return _create_job(
        previous.job_type,
        request_model,
        retry_of_job_id=previous.job_id,
    )


def associate_job(
    job_id: str,
    request: IntegrationAssociationCreate,
) -> IntegrationAssociation:
    _validate_association_target(request.target_type, request.target_id)
    job = get_job(job_id, "gis_analysis")
    if job is None:
        raise FileNotFoundError(f"GIS job {job_id} was not found.")
    if job.status != "completed":
        raise IntegrationJobNotRetryable("Only completed GIS results can be associated.")
    now = _now().isoformat()
    with _connection_schema() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO integration_associations(
                association_id, job_id, target_type, target_id, associated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), job_id, request.target_type, request.target_id, now),
        )
        row = connection.execute(
            """
            SELECT * FROM integration_associations
            WHERE job_id=? AND target_type=? AND target_id=?
            """,
            (job_id, request.target_type, request.target_id),
        ).fetchone()
    if row is None:
        raise RuntimeError("The GIS result association could not be read back.")
    return IntegrationAssociation(
        association_id=row["association_id"],
        job_id=row["job_id"],
        target_type=row["target_type"],
        target_id=row["target_id"],
        associated_at=_time(row["associated_at"]),
    )


def _validate_association_target(target_type: str, target_id: str) -> None:
    if target_type == "river":
        if target_id not in {river.id for river in RIVER_CATALOG}:
            raise ValueError(f"Unknown river_id: {target_id}")
        return
    from app.services.catalog import DEMO_REGIONS

    if any(region.id == target_id for region in DEMO_REGIONS):
        raise ValueError("Demonstration-only regions cannot be associated with observation analysis.")
    raise FileNotFoundError("No non-demonstration region catalogue is registered.")


def get_gis_result(job_id: str) -> IntegrationJob:
    job = get_job(job_id, "gis_analysis")
    if job is None:
        raise FileNotFoundError(f"GIS job {job_id} was not found.")
    if job.status != "completed":
        raise IntegrationJobNotRetryable("GIS results are available only after the job completes.")
    for output in job.outputs:
        _verify_output_unchanged(output)
    return job


def recover_interrupted_jobs() -> None:
    now = _now().isoformat()
    with _connection_schema() as connection:
        connection.execute(
            """
            UPDATE integration_jobs
            SET status='failed', updated_at=?, error_code='process_interrupted',
                error_message='Backend stopped before the integration job completed.'
            WHERE status='running'
            """,
            (now,),
        )
