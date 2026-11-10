import asyncio
import json
import logging
import math
import os
import re
import shutil
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import quote, urlparse

import httpx
import numpy as np
from dotenv import load_dotenv

from app.schemas.acquisitions import (
    AcquisitionIssue,
    AcquiredObservation,
    AcquisitionStatus,
    NisarProduct,
    RiverAcquisitionStatus,
)
from app.schemas.analysis import WaterMaskRequest
from app.services import analysis
from app.services.optical_reference import create_candidate_preview
from app.services.rivers import RIVER_CATALOG

LOGGER = logging.getLogger(__name__)
STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
SAS_TOKEN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token/sentinel-1-rtc"
ASF_SEARCH_URL = "https://api.daac.asf.alaska.edu/services/search/param"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPOSITORY_ROOT / ".env", override=False)
POLL_INTERVAL_SECONDS = max(300, int(os.getenv("SAR_ACQUISITION_POLL_SECONDS", "21600")))
SEARCH_LOOKBACK_DAYS = 45
SEARCH_LIMIT = 12
NISAR_SEARCH_LIMIT = 3
CORRIDOR_HALF_WIDTH_M = 1_500
ANALYSIS_WINDOW_SIZE_M = 12_000
MAX_ANALYSIS_PIXELS = 2_000_000
NISAR_DOWNLOAD_RESERVE_BYTES = 1_000_000_000
ACQUISITION_ROOT = REPOSITORY_ROOT / "data" / "acquisitions"
CATALOG_PATH = REPOSITORY_ROOT / "data" / "satellite_catalog.sqlite3"

_REFRESH_LOCK = threading.Lock()
_NISAR_PROCESS_LOCK = threading.Lock()
_NISAR_COMPONENT_SENSITIVITY_LOCK = threading.Lock()
_NISAR_DOWNLOAD_LOCK = threading.Lock()


class NisarProcessingBusy(RuntimeError):
    pass


def automatic_acquisition_enabled() -> bool:
    return os.getenv("SAR_AUTO_ACQUISITION_ENABLED", "false").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def polling_interval_seconds() -> int:
    return POLL_INTERVAL_SECONDS


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _database() -> sqlite3.Connection:
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(CATALOG_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS river_scans (
            river_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            last_checked_at TEXT,
            nisar_status TEXT NOT NULL,
            nisar_product_id TEXT,
            nisar_acquisition_start TEXT,
            nisar_message TEXT,
            nisar_products_json TEXT NOT NULL DEFAULT '[]',
            candidate_count INTEGER NOT NULL DEFAULT 0,
            message TEXT
        )
        """
    )
    scan_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(river_scans)")
    }
    if "nisar_products_json" not in scan_columns:
        connection.execute(
            "ALTER TABLE river_scans ADD COLUMN nisar_products_json TEXT NOT NULL DEFAULT '[]'"
        )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS acquired_products (
            river_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            mission TEXT NOT NULL,
            product_type TEXT NOT NULL,
            platform TEXT,
            acquisition_start TEXT NOT NULL,
            acquisition_end TEXT,
            polarization TEXT NOT NULL,
            orbit_state TEXT,
            relative_orbit INTEGER,
            footprint_json TEXT NOT NULL,
            centerline_coverage_percent REAL NOT NULL,
            source TEXT NOT NULL,
            stac_item_url TEXT NOT NULL,
            asset_source_url TEXT NOT NULL,
            source_license TEXT NOT NULL,
            provider_processing TEXT NOT NULL,
            processing_status TEXT NOT NULL,
            analysis_id TEXT,
            candidate_water_area_m2 REAL,
            candidate_water_area_lower_m2 REAL,
            candidate_water_area_upper_m2 REAL,
            threshold_db REAL,
            input_crs TEXT,
            pixel_size_m REAL,
            corridor_half_width_m REAL NOT NULL,
            downloaded_at TEXT,
            status TEXT NOT NULL,
            error TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (river_id, product_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS acquisition_jobs (
            job_id TEXT PRIMARY KEY,
            river_id TEXT NOT NULL,
            satellite TEXT NOT NULL,
            product_id TEXT NOT NULL,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            progress_percent INTEGER,
            current_stage TEXT NOT NULL,
            error_message TEXT,
            output_references_json TEXT NOT NULL DEFAULT '{}',
            retry_of_job_id TEXT,
            CHECK (status IN (
                'queued', 'running', 'downloading', 'processing',
                'completed', 'no_data', 'failed', 'cancelled'
            ))
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_acquisition_jobs_active_product
        ON acquisition_jobs(river_id, satellite, product_id, job_type)
        WHERE status IN ('queued', 'running', 'downloading', 'processing')
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_acquisition_jobs_created ON acquisition_jobs(created_at DESC)"
    )
    connection.commit()
    return connection


@contextmanager
def _catalog_connection() -> Iterator[sqlite3.Connection]:
    connection = _database()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _lines(geometry: dict[str, Any]) -> list[list[list[float]]]:
    if geometry.get("type") == "LineString":
        return [geometry.get("coordinates", [])]
    if geometry.get("type") == "MultiLineString":
        return geometry.get("coordinates", [])
    raise ValueError(f"Unsupported river centerline geometry type: {geometry.get('type')}")


def _clip_segment(
    start: tuple[float, float],
    end: tuple[float, float],
    bounds: tuple[float, float, float, float],
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    left, bottom, right, top = bounds
    dx, dy = end[0] - start[0], end[1] - start[1]
    lower, upper = 0.0, 1.0
    for direction, distance in (
        (-dx, start[0] - left),
        (dx, right - start[0]),
        (-dy, start[1] - bottom),
        (dy, top - start[1]),
    ):
        if direction == 0:
            if distance < 0:
                return None
            continue
        ratio = distance / direction
        if direction < 0:
            if ratio > upper:
                return None
            lower = max(lower, ratio)
        else:
            if ratio < lower:
                return None
            upper = min(upper, ratio)
    return (
        (start[0] + lower * dx, start[1] + lower * dy),
        (start[0] + upper * dx, start[1] + upper * dy),
    )


def _projected_centerline(
    geometry: dict[str, Any],
    target_crs: Any,
) -> tuple[list[list[tuple[float, float]]], float]:
    rasterio = analysis._require_rasterio()
    from rasterio.warp import transform

    projected_lines: list[list[tuple[float, float]]] = []
    total_length = 0.0
    for line in _lines(geometry):
        if len(line) < 2:
            continue
        longitudes = [point[0] for point in line]
        latitudes = [point[1] for point in line]
        xs, ys = transform("EPSG:4326", target_crs, longitudes, latitudes)
        points = list(zip(xs, ys))
        projected_lines.append(points)
        total_length += sum(
            math.hypot(end[0] - start[0], end[1] - start[1])
            for start, end in zip(points, points[1:])
        )
    if not projected_lines or total_length <= 0:
        raise ValueError("The river catalog contains no usable centerline segments.")
    return projected_lines, total_length


def _clipped_segments(
    lines: list[list[tuple[float, float]]],
    bounds: tuple[float, float, float, float],
) -> tuple[list[dict[str, Any]], float, list[tuple[float, float]]]:
    features: list[dict[str, Any]] = []
    total_length = 0.0
    reference_points: list[tuple[float, float]] = []
    for line in lines:
        for start, end in zip(line, line[1:]):
            clipped = _clip_segment(start, end, bounds)
            if clipped is None:
                continue
            clipped_start, clipped_end = clipped
            length = math.hypot(
                clipped_end[0] - clipped_start[0],
                clipped_end[1] - clipped_start[1],
            )
            if length <= 0:
                continue
            total_length += length
            reference_points.extend(clipped)
            features.append(
                {
                    "type": "LineString",
                    "coordinates": [list(clipped_start), list(clipped_end)],
                }
            )
    return features, total_length, reference_points


def _coverage(
    geometry: dict[str, Any],
    crs: Any,
    bounds: tuple[float, float, float, float],
) -> tuple[float, list[list[tuple[float, float]]], list[tuple[float, float]]]:
    lines, total_length = _projected_centerline(geometry, crs)
    _, inside_length, points = _clipped_segments(lines, bounds)
    return min(100.0, inside_length / total_length * 100), lines, points


def _item_features(river_id: str, geometry: dict[str, Any]) -> list[dict[str, Any]]:
    start = (_now() - timedelta(days=SEARCH_LOOKBACK_DAYS)).isoformat().replace("+00:00", "Z")
    end = _now().isoformat().replace("+00:00", "Z")
    response = httpx.post(
        f"{STAC_URL}/search",
        json={
            "collections": ["sentinel-1-rtc"],
            "intersects": geometry,
            "datetime": f"{start}/{end}",
            "limit": SEARCH_LIMIT,
            "sortby": [{"field": "properties.datetime", "direction": "desc"}],
        },
        headers={"User-Agent": "SAR-Sentinel-India/0.1"},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise ValueError("Planetary Computer returned an invalid STAC ItemCollection.")
    return [
        feature
        for feature in features
        if isinstance(feature, dict)
        and isinstance(feature.get("id"), str)
        and isinstance(feature.get("geometry"), dict)
        and isinstance((feature.get("assets") or {}).get("vv"), dict)
        and isinstance((feature.get("assets") or {})["vv"].get("href"), str)
    ]


def _search_nisar(river_id: str, session: Any | None = None) -> list[dict[str, Any]]:
    from app.services.satellite import (
        _filter_features_by_river_corridor,
        _river_search_wkt,
    )

    end_date = _now()
    start_date = end_date - timedelta(days=SEARCH_LOOKBACK_DAYS)
    geometry = _river_search_wkt(river_id)
    if session is not None:
        asf = import_module("asf_search")
        options = asf.ASFSearchOptions(session=session)
        results = asf.geo_search(
            dataset="NISAR",
            processingLevel="GCOV",
            intersectsWith=geometry,
            start=start_date.isoformat().replace("+00:00", "Z"),
            end=end_date.isoformat().replace("+00:00", "Z"),
            maxResults=NISAR_SEARCH_LIMIT * 5,
            opts=options,
        )
        if hasattr(results, "raise_if_incomplete"):
            results.raise_if_incomplete()
        features = []
        for product in results:
            feature = product.geojson()
            if isinstance(feature, dict):
                features.append(feature)
        return _filter_features_by_river_corridor(features, river_id, NISAR_SEARCH_LIMIT)
    response = httpx.get(
        ASF_SEARCH_URL,
        params={
            "dataset": "NISAR",
            "processingLevel": "GCOV",
            "intersectsWith": geometry,
            "start": start_date.isoformat().replace("+00:00", "Z"),
            "end": end_date.isoformat().replace("+00:00", "Z"),
            "output": "geojson",
            "maxResults": str(NISAR_SEARCH_LIMIT * 5),
        },
        headers={"User-Agent": "SAR-Sentinel-India/0.1"},
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise ValueError("ASF DAAC returned invalid NISAR search results.")
    return _filter_features_by_river_corridor(
        [feature for feature in features if isinstance(feature, dict)],
        river_id,
        NISAR_SEARCH_LIMIT,
    )


def _earthdata_session() -> tuple[Any | None, str | None]:
    token = os.getenv("EARTHDATA_TOKEN", "").strip()
    if not token:
        return None, None
    try:
        asf = import_module("asf_search")
        return asf.ASFSession().auth_with_token(token), None
    except Exception as error:
        LOGGER.warning(
            "Earthdata token authentication failed (%s); continuing with unauthenticated NISAR metadata and Sentinel-1 fallback.",
            type(error).__name__,
        )
        return None, type(error).__name__


def _nisar_size_bytes(
    properties: dict[str, Any],
    product_url: str | None = None,
) -> int | None:
    sizes = properties.get("bytes")
    if isinstance(sizes, int) and sizes >= 0:
        return sizes
    if isinstance(sizes, dict):
        if product_url:
            product_name = Path(urlparse(product_url).path).name
            product_asset = sizes.get(product_name)
            if isinstance(product_asset, dict):
                product_size = product_asset.get("bytes")
                if isinstance(product_size, int) and product_size >= 0:
                    return product_size
        byte_values = [
            item.get("bytes")
            for item in sizes.values()
            if isinstance(item, dict) and isinstance(item.get("bytes"), int)
        ]
        if byte_values:
            return sum(value for value in byte_values if value >= 0)
    return None


def _nisar_product_metadata(feature: dict[str, Any], authenticated: bool) -> dict[str, Any] | None:
    properties = feature.get("properties") or {}
    product_id = properties.get("fileID") or feature.get("id")
    product_url = properties.get("url")
    if not isinstance(product_id, str) or not isinstance(product_url, str):
        return None
    start = _timestamp(properties.get("startTime"))
    end = _timestamp(properties.get("stopTime"))
    product_level = properties.get("processingLevel") or "GCOV"
    polarization = properties.get("polarization") or properties.get("mainBandPolarization") or properties.get(
        "sideBandPolarization"
    )
    if isinstance(polarization, str):
        polarization = [polarization]
    elif isinstance(polarization, list):
        polarization = [value for value in polarization if isinstance(value, str)]
    else:
        polarization = None
    return {
        "product_id": product_id,
        "acquisition_start": start.isoformat() if start else None,
        "acquisition_end": end.isoformat() if end else None,
        "product_level": str(product_level),
        "polarization": polarization,
        "size_bytes": _nisar_size_bytes(properties, product_url),
        "availability": "authenticated_catalog" if authenticated else "authentication_required",
        "download_status": "not_attempted",
        "source_url": product_url,
        "local_path": None,
        "hdf5_groups": [],
        "message": None,
    }


def _download_nisar_product(
    river_id: str,
    product: dict[str, Any],
    session: Any,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    product_url = product["source_url"]
    parsed_url = urlparse(product_url)
    if parsed_url.scheme != "https" or not (
        parsed_url.hostname == "asf.earthdatacloud.nasa.gov"
        or (parsed_url.hostname or "").endswith(".asf.earthdatacloud.nasa.gov")
    ):
        raise ValueError("ASF returned a NISAR URL outside the approved ASF Earthdata Cloud host.")
    product_name = Path(parsed_url.path).name
    if not product_name or product_name in {".", ".."}:
        raise ValueError("ASF returned a NISAR product URL without a valid file name.")
    product_directory = ACQUISITION_ROOT / river_id / _safe_product_id(product["product_id"])
    product_directory.mkdir(parents=True, exist_ok=True)
    final_path = product_directory / product_name
    expected_size = product.get("size_bytes")
    with _NISAR_DOWNLOAD_LOCK:
        if final_path.is_file():
            if progress_callback is not None:
                progress_callback("Validating existing NISAR HDF5 product")
            groups, polarizations = _inspect_nisar_hdf5(final_path, expected_size)
        else:
            required_bytes = (expected_size or 0) + NISAR_DOWNLOAD_RESERVE_BYTES
            if shutil.disk_usage(product_directory).free < required_bytes:
                product["download_status"] = "insufficient_disk_space"
                product["message"] = (
                    "Download not attempted: the product requires approximately "
                    f"{expected_size or 'unknown'} bytes plus a 1 GB safety reserve."
                )
                return product
            staging_directory = Path(
                tempfile.mkdtemp(prefix=".nisar-download-", dir=product_directory)
            )
            try:
                asf = import_module("asf_search")
                asf.download_urls(urls=[product_url], path=str(staging_directory), session=session)
                expected_size = product.get("size_bytes")
                staged_path = staging_directory / product_name
                if not staged_path.is_file() or staged_path.stat().st_size == 0:
                    raise ValueError("ASF download completed without a non-empty NISAR product file.")
                if progress_callback is not None:
                    progress_callback("Verifying downloaded file size and HDF5 structure")
                groups, polarizations = _inspect_nisar_hdf5(staged_path, expected_size)
                if final_path.exists():
                    raise FileExistsError(
                        "A product file appeared during download; refusing to overwrite it."
                    )
                os.replace(staged_path, final_path)
            finally:
                shutil.rmtree(staging_directory, ignore_errors=True)
        product["download_status"] = "downloaded"

    product["availability"] = "downloaded_verified"
    product["local_path"] = str(final_path.relative_to(REPOSITORY_ROOT))
    product["hdf5_groups"] = groups
    if polarizations:
        product["polarization"] = polarizations
    product["message"] = (
        "Downloaded through ASF's authenticated client and opened successfully with h5py. "
        "Processing is available separately for supported frequency-A HH/HV GCOV inputs."
    )
    return product


def _inspect_nisar_hdf5(
    path: Path,
    expected_size: Any,
) -> tuple[list[str], list[str]]:
    import h5py

    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("The NISAR product is missing or empty.")
    if isinstance(expected_size, int) and path.stat().st_size != expected_size:
        raise ValueError("The NISAR file size does not match ASF catalog metadata.")
    with h5py.File(path, "r") as dataset:
        groups = sorted(name for name, value in dataset.items() if isinstance(value, h5py.Group))
        if not groups:
            raise ValueError("The NISAR HDF5 product has no readable top-level groups.")
        if "science/LSAR/GCOV/grids" not in dataset:
            raise ValueError("The HDF5 file does not contain the expected NISAR GCOV grids.")
        polarizations: list[str] = []
        for frequency in ("frequencyA", "frequencyB"):
            polarization_path = f"science/LSAR/GCOV/grids/{frequency}/listOfPolarizations"
            if polarization_path not in dataset:
                continue
            values = np.asarray(dataset[polarization_path][()]).reshape(-1).tolist()
            for value in values:
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="replace")
                if isinstance(value, str) and value and value not in polarizations:
                    polarizations.append(value)
        if not polarizations:
            raise ValueError("The NISAR GCOV product does not report any grid polarizations.")
    return groups, polarizations


def _check_nisar_download(product_url: str) -> tuple[str, str]:
    try:
        with httpx.stream(
            "GET",
            product_url,
            headers={"Range": "bytes=0-0", "User-Agent": "SAR-Sentinel-India/0.1"},
            follow_redirects=True,
            timeout=30,
        ) as response:
            final_host = response.url.host or ""
            if response.status_code in {401, 403} or final_host.endswith("urs.earthdata.nasa.gov"):
                return (
                    "authentication_required",
                    "NISAR GCOV metadata is available, but ASF redirects product access to NASA Earthdata Login. "
                    "No credentials were available; no download or authentication bypass was attempted.",
                )
            if response.status_code in {200, 206}:
                return (
                    "publicly_accessible_unprocessed",
                    "The NISAR product responds without Earthdata authentication, but an NISAR GCOV HDF5 "
                    "reader is not implemented; this product was not downloaded or treated as processed.",
                )
            return (
                "error",
                f"The NISAR product access check returned HTTP {response.status_code}.",
            )
    except httpx.HTTPError as error:
        return "error", f"NISAR product access check failed: {error}"


def _nisar_metadata(
    river_id: str,
    session: Any | None = None,
    authentication_error: str | None = None,
) -> dict[str, Any]:
    try:
        features = _search_nisar(river_id, session=session)
        products = [
            product
            for feature in features
            if (product := _nisar_product_metadata(feature, authenticated=session is not None))
        ]
        if not products:
            return {
                "status": "no_data",
                "product_id": None,
                "acquisition_start": None,
                "products": [],
                "message": f"No NISAR GCOV product was found for this river in the last {SEARCH_LOOKBACK_DAYS} days.",
            }
        if session is None:
            access_status, message = _check_nisar_download(products[0]["source_url"])
            products[0]["availability"] = access_status
            products[0]["message"] = message
            if authentication_error:
                status = "error"
                message = (
                    f"Earthdata token authentication could not be completed ({authentication_error}); "
                    "ASF metadata was checked without credentials and Sentinel-1 fallback will continue."
                )
                products[0]["message"] = message
            else:
                status = access_status if access_status in {"authentication_required", "error"} else "metadata_found"
        else:
            status = "metadata_found"
            message = (
                f"Authenticated ASF search found {len(products)} NISAR GCOV product(s). "
                "NISAR GCOV HDF5 products are cataloged separately from the Sentinel-1 RTC processing pipeline."
            )
        first = products[0]
        return {
            "status": status,
            "product_id": first["product_id"],
            "acquisition_start": first["acquisition_start"],
            "products": products,
            "message": message,
        }
    except (httpx.HTTPError, ValueError, KeyError) as error:
        LOGGER.warning("NISAR metadata search failed for %s (%s).", river_id, type(error).__name__)
        return {
            "status": "error",
            "product_id": None,
            "acquisition_start": None,
            "products": [],
            "message": f"NISAR discovery failed ({type(error).__name__}); Sentinel-1 fallback will continue.",
        }
    except Exception as error:
        LOGGER.warning("NISAR metadata search failed for %s (%s).", river_id, type(error).__name__)
        return {
            "status": "error",
            "product_id": None,
            "acquisition_start": None,
            "products": [],
            "message": f"NISAR discovery failed ({type(error).__name__}); Sentinel-1 fallback will continue.",
        }


def _safe_product_id(product_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", product_id)[:180]


def _local_nisar_product_records(river_id: str) -> list[dict[str, Any]]:
    import h5py

    river_directory = (ACQUISITION_ROOT / river_id).resolve()
    if not river_directory.is_relative_to(ACQUISITION_ROOT.resolve()) or not river_directory.is_dir():
        return []

    recovered: list[dict[str, Any]] = []
    for product_directory in river_directory.iterdir():
        if not product_directory.is_dir() or "_GCOV_" not in product_directory.name:
            continue
        product_id = product_directory.name
        product_path_candidates = list(product_directory.glob("*.h5"))
        if len(product_path_candidates) != 1:
            if product_path_candidates:
                LOGGER.warning(
                    "Skipping cached NISAR product %s: expected one HDF5 file, found %s.",
                    product_id,
                    len(product_path_candidates),
                )
            continue

        product_path = product_path_candidates[0].resolve()
        if (
            not product_path.is_relative_to(ACQUISITION_ROOT.resolve())
            or not product_path.is_file()
        ):
            continue

        metadata_path = product_directory / "nisar-processing" / "processing-metadata.json"
        metadata: dict[str, Any] = {}
        if metadata_path.is_file():
            try:
                decoded_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if isinstance(decoded_metadata, dict):
                    metadata = decoded_metadata
            except (OSError, json.JSONDecodeError) as error:
                LOGGER.warning(
                    "Could not read cached NISAR processing metadata for %s (%s).",
                    product_id,
                    type(error).__name__,
                )

        try:
            with h5py.File(product_path, "r") as dataset:
                if "science/LSAR/GCOV" not in dataset:
                    LOGGER.warning("Skipping cached NISAR product %s: GCOV group is absent.", product_id)
                    continue
                groups = sorted(
                    name for name, value in dataset.items() if isinstance(value, h5py.Group)
                )
                polarizations: list[str] = []
                for frequency in ("frequencyA", "frequencyB"):
                    polarization_path = (
                        f"science/LSAR/GCOV/grids/{frequency}/listOfPolarizations"
                    )
                    if polarization_path not in dataset:
                        continue
                    for value in np.asarray(dataset[polarization_path][()]).reshape(-1):
                        if isinstance(value, bytes):
                            value = value.decode("utf-8", errors="replace")
                        if isinstance(value, str) and value and value not in polarizations:
                            polarizations.append(value)
        except (OSError, ValueError) as error:
            LOGGER.warning(
                "Skipping cached NISAR product %s: HDF5 validation failed (%s).",
                product_id,
                type(error).__name__,
            )
            continue

        date_match = re.search(r"_(\d{8}T\d{6})_(\d{8}T\d{6})_", product_id)
        acquisition_start = metadata.get("acquisition_start")
        acquisition_end = metadata.get("acquisition_end")
        if date_match:
            for index, key in enumerate(("acquisition_start", "acquisition_end"), start=1):
                if not metadata.get(key):
                    acquisition = datetime.strptime(date_match.group(index), "%Y%m%dT%H%M%S")
                    metadata[key] = acquisition.replace(tzinfo=timezone.utc).isoformat()
            acquisition_start = metadata.get("acquisition_start")
            acquisition_end = metadata.get("acquisition_end")

        processing_result = (
            metadata
            if metadata.get("status") in {"unvalidated_candidate", "no_valid_corridor_data"}
            else None
        )
        if processing_result and processing_result["status"] == "unvalidated_candidate":
            processing_result = _attach_optical_candidate_urls(
                processing_result,
                river_id,
                product_id,
                product_path,
            )
        processing_status = (
            "processed"
            if processing_result and processing_result["status"] == "unvalidated_candidate"
            else "no_data"
            if processing_result
            else "not_attempted"
        )
        recovered.append(
            {
                "product_id": product_id,
                "acquisition_start": acquisition_start,
                "acquisition_end": acquisition_end,
                "product_level": "GCOV",
                "polarization": polarizations or None,
                "size_bytes": product_path.stat().st_size,
                "availability": "downloaded_verified",
                "download_status": "downloaded",
                "source_url": None,
                "local_path": str(product_path.relative_to(REPOSITORY_ROOT)),
                "hdf5_groups": groups,
                "message": "Recovered from the verified local HDF5 product and processing metadata.",
                "processing_status": processing_status,
                "processing_message": None,
                "processing_result": processing_result,
            }
        )
    return recovered


def _merge_nisar_product_records(
    discovered: list[dict[str, Any]],
    cached: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cached_by_id = {
        product["product_id"]: product
        for product in cached
        if isinstance(product.get("product_id"), str)
    }
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for product in discovered:
        product_id = product["product_id"]
        previous = cached_by_id.get(product_id, {})
        current = dict(product)
        if previous.get("download_status") == "downloaded":
            for field in (
                "availability",
                "download_status",
                "local_path",
                "hdf5_groups",
                "processing_status",
                "processing_message",
                "processing_result",
                "message",
            ):
                if field in previous:
                    current[field] = previous[field]
            local_processing_result = product.get("processing_result") or {}
            cached_processing_result = dict(current.get("processing_result") or {})
            for field in ("optical_reference_url", "optical_candidate_mask_url"):
                if field in local_processing_result:
                    cached_processing_result[field] = local_processing_result[field]
            if cached_processing_result:
                current["processing_result"] = cached_processing_result
        merged.append(current)
        seen.add(product_id)
    merged.extend(
        product
        for product in cached
        if product.get("product_id") not in seen
    )
    return merged


def _cached_nisar_product_records(
    connection: sqlite3.Connection,
    river_id: str,
) -> list[dict[str, Any]]:
    row = connection.execute(
        "SELECT nisar_products_json FROM river_scans WHERE river_id=?",
        (river_id,),
    ).fetchone()
    previous = json.loads(row["nisar_products_json"] or "[]") if row else []
    return _merge_nisar_product_records(
        _local_nisar_product_records(river_id),
        previous,
    )


def _read_clipped_raster(
    item: dict[str, Any],
    river_id: str,
    river_geometry: dict[str, Any],
    output_path: Path,
    sas_token: str,
) -> tuple[float, float, str]:
    rasterio = analysis._require_rasterio()
    from rasterio.features import rasterize
    from rasterio.windows import Window, from_bounds
    from scipy.ndimage import distance_transform_edt

    asset = item["assets"]["vv"]
    href = str(asset["href"])
    signed_href = f"{href}{'&' if '?' in href else '?'}{sas_token.lstrip('?')}"
    properties = item.get("properties") or {}
    with rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        GDAL_HTTP_MAX_RETRY="3",
        GDAL_HTTP_RETRY_DELAY="1",
    ):
        with rasterio.open(signed_href) as source:
            if source.crs is None or not source.crs.is_projected:
                raise ValueError("Sentinel-1 RTC asset has no projected CRS.")
            if source.count != 1:
                raise ValueError("Sentinel-1 RTC VV asset is not a single-band raster.")
            if not math.isclose(abs(source.transform.a), abs(source.transform.e), rel_tol=0.1):
                raise ValueError("Sentinel-1 RTC asset has non-square or unsupported pixels.")

            source_bounds = (
                source.bounds.left,
                source.bounds.bottom,
                source.bounds.right,
                source.bounds.top,
            )
            coverage_percent, centerline_lines, points = _coverage(
                river_geometry,
                source.crs,
                source_bounds,
            )
            if not points or coverage_percent <= 0:
                raise ValueError("The RTC raster bounds do not contain the river centerline returned by STAC.")
            scene_center_x = (source.bounds.left + source.bounds.right) / 2
            scene_center_y = (source.bounds.bottom + source.bounds.top) / 2
            center_x, center_y = min(
                points,
                key=lambda point: math.hypot(point[0] - scene_center_x, point[1] - scene_center_y),
            )

            pixel_size = max(abs(source.transform.a), abs(source.transform.e))
            half_size = min(ANALYSIS_WINDOW_SIZE_M / 2, math.sqrt(MAX_ANALYSIS_PIXELS) * pixel_size / 2)
            crop_bounds = (
                center_x - half_size,
                center_y - half_size,
                center_x + half_size,
                center_y + half_size,
            )
            window = from_bounds(*crop_bounds, transform=source.transform)
            window = window.round_offsets().round_lengths()
            window = window.intersection(Window(0, 0, source.width, source.height))
            if window.width < 3 or window.height < 3:
                raise ValueError("The river intersects the product edge but leaves no usable raster window.")
            if window.width * window.height > MAX_ANALYSIS_PIXELS:
                raise ValueError("The clipped river window exceeds the configured pixel limit.")

            transform = source.window_transform(window)
            window_bounds = rasterio.windows.bounds(window, source.transform)
            corridor_segments, _, _ = _clipped_segments(centerline_lines, window_bounds)
            if not corridor_segments:
                raise ValueError("No river centerline segment falls inside the selected raster window.")
            centerline_mask = rasterize(
                ((feature, 1) for feature in corridor_segments),
                out_shape=(int(window.height), int(window.width)),
                transform=transform,
                fill=0,
                all_touched=True,
                dtype="uint8",
            ).astype(bool)
            if not centerline_mask.any():
                raise ValueError("The river centerline could not be rasterized into the RTC crop.")

            pixel_y = math.hypot(transform.b, transform.e)
            pixel_x = math.hypot(transform.a, transform.d)
            distance = distance_transform_edt(~centerline_mask, sampling=(pixel_y, pixel_x))
            corridor_mask = distance <= CORRIDOR_HALF_WIDTH_M
            data = source.read(1, window=window, masked=True)
            nodata = source.nodata if source.nodata is not None else -32768.0
            values = np.asarray(data.filled(nodata), dtype=np.float32)
            valid = ~np.ma.getmaskarray(data) & np.isfinite(values)
            corridor_mask &= valid
            values[~corridor_mask] = nodata

            output_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = output_path.with_suffix(".tmp.tif")
            profile = source.profile.copy()
            profile.update(
                driver="GTiff",
                width=int(window.width),
                height=int(window.height),
                count=1,
                dtype="float32",
                nodata=nodata,
                transform=transform,
                compress="deflate",
                predictor=3,
                tiled=True,
                blockxsize=256,
                blockysize=256,
            )
            with rasterio.open(temporary_path, "w", **profile) as output:
                output.write(values, 1)
                output.update_tags(
                    source="Microsoft Planetary Computer sentinel-1-rtc",
                    river_id=river_id,
                    source_product_id=item["id"],
                    acquisition_start=str(properties.get("datetime", "")),
                    polarization="VV",
                    corridor_centerline_source="OpenStreetMap; see project river geometry provenance",
                    corridor_half_width_m=str(CORRIDOR_HALF_WIDTH_M),
                    provider_processing="radiometric calibration and terrain correction performed upstream",
                    original_asset_href=href,
                )
            os.replace(temporary_path, output_path)
            return coverage_percent, pixel_size, source.crs.to_string()


def _insert_or_update_product(
    connection: sqlite3.Connection,
    river_id: str,
    item: dict[str, Any],
    coverage_percent: float,
    status: str,
    error: str | None = None,
    analysis_result: Any | None = None,
    local_path: Path | None = None,
) -> None:
    properties = item.get("properties") or {}
    product_id = item["id"]
    assets = item.get("assets") or {}
    asset_href = (assets.get("vv") or {}).get("href", "")
    acquisition_start = _timestamp(properties.get("datetime"))
    if acquisition_start is None:
        raise ValueError(f"STAC item {product_id} has no valid acquisition time.")
    acquired_at = _now().isoformat() if analysis_result is not None else None
    connection.execute(
        """
        INSERT INTO acquired_products (
            river_id, product_id, mission, product_type, platform,
            acquisition_start, acquisition_end, polarization, orbit_state,
            relative_orbit, footprint_json, centerline_coverage_percent,
            source, stac_item_url, asset_source_url, source_license,
            provider_processing, processing_status, analysis_id,
            candidate_water_area_m2, candidate_water_area_lower_m2,
            candidate_water_area_upper_m2, threshold_db, input_crs,
            pixel_size_m, corridor_half_width_m, downloaded_at, status, error, updated_at
        ) VALUES (
            ?, ?, 'SENTINEL-1', 'GRD-RTC', ?, ?, ?, 'VV',
            ?, ?, ?, ?, 'Microsoft Planetary Computer', ?, ?, 'CC-BY-4.0',
            ?, 'unvalidated_candidate', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT(river_id, product_id) DO UPDATE SET
            platform=excluded.platform,
            acquisition_start=excluded.acquisition_start,
            acquisition_end=excluded.acquisition_end,
            orbit_state=excluded.orbit_state,
            relative_orbit=excluded.relative_orbit,
            footprint_json=excluded.footprint_json,
            centerline_coverage_percent=excluded.centerline_coverage_percent,
            stac_item_url=excluded.stac_item_url,
            asset_source_url=excluded.asset_source_url,
            provider_processing=excluded.provider_processing,
            processing_status=excluded.processing_status,
            analysis_id=COALESCE(excluded.analysis_id, acquired_products.analysis_id),
            candidate_water_area_m2=COALESCE(excluded.candidate_water_area_m2, acquired_products.candidate_water_area_m2),
            candidate_water_area_lower_m2=COALESCE(excluded.candidate_water_area_lower_m2, acquired_products.candidate_water_area_lower_m2),
            candidate_water_area_upper_m2=COALESCE(excluded.candidate_water_area_upper_m2, acquired_products.candidate_water_area_upper_m2),
            threshold_db=COALESCE(excluded.threshold_db, acquired_products.threshold_db),
            input_crs=COALESCE(excluded.input_crs, acquired_products.input_crs),
            pixel_size_m=COALESCE(excluded.pixel_size_m, acquired_products.pixel_size_m),
            corridor_half_width_m=excluded.corridor_half_width_m,
            downloaded_at=COALESCE(excluded.downloaded_at, acquired_products.downloaded_at),
            status=excluded.status,
            error=excluded.error,
            updated_at=excluded.updated_at
        """,
        (
            river_id,
            product_id,
            properties.get("platform"),
            acquisition_start.isoformat(),
            _timestamp(properties.get("end_datetime")).isoformat()
            if _timestamp(properties.get("end_datetime"))
            else None,
            properties.get("sat:orbit_state"),
            properties.get("sat:relative_orbit"),
            json.dumps(item.get("geometry")),
            coverage_percent,
            f"{STAC_URL}/collections/sentinel-1-rtc/items/{product_id}",
            asset_href,
            "Catalyst radiometrically terrain-corrected RTC, derived from ESA Sentinel-1 GRD; linear calibrated intensity.",
            analysis_result.analysis_id if analysis_result is not None else None,
            analysis_result.candidate_water_area_m2 if analysis_result is not None else None,
            analysis_result.candidate_water_area_lower_m2 if analysis_result is not None else None,
            analysis_result.candidate_water_area_upper_m2 if analysis_result is not None else None,
            analysis_result.threshold_db if analysis_result is not None else None,
            analysis_result.input_crs if analysis_result is not None else None,
            pixel_size_from_result(analysis_result) if analysis_result is not None else None,
            CORRIDOR_HALF_WIDTH_M,
            acquired_at,
            status,
            error,
            _now().isoformat(),
        ),
    )


def pixel_size_from_result(result: Any) -> float | None:
    return math.sqrt(result.pixel_area_m2) if result is not None else None


def _record_failure(
    connection: sqlite3.Connection,
    river_id: str,
    item: dict[str, Any],
    geometry: dict[str, Any],
    message: str,
    status: str = "failed",
) -> None:
    try:
        properties = item.get("properties") or {}
        epsg = properties.get("proj:epsg")
        bbox = properties.get("proj:bbox")
        coverage = 0.0
        if isinstance(epsg, int) and isinstance(bbox, list) and len(bbox) == 4:
            coverage, _, _ = _coverage(geometry, f"EPSG:{epsg}", tuple(map(float, bbox)))
        _insert_or_update_product(
            connection,
            river_id,
            item,
            coverage,
            status=status,
            error=message,
        )
        connection.commit()
    except (ValueError, KeyError, TypeError):
        LOGGER.exception("Unable to record failed product %s for %s", item.get("id"), river_id)


def _process_candidate(
    connection: sqlite3.Connection,
    river_id: str,
    river_geometry: dict[str, Any],
    item: dict[str, Any],
    token: str,
    stage_callback: Callable[[str, str], None] | None = None,
) -> AcquiredObservation:
    product_id = item["id"]
    properties = item.get("properties") or {}
    epsg = properties.get("proj:epsg")
    bbox = properties.get("proj:bbox")
    if not isinstance(epsg, int) or not isinstance(bbox, list) or len(bbox) != 4:
        raise ValueError("STAC item has no projected raster bounds or EPSG code.")
    coverage, projected_lines, _ = _coverage(
        river_geometry,
        f"EPSG:{epsg}",
        tuple(map(float, bbox)),
    )
    if coverage <= 0:
        raise ValueError("The STAC footprint intersects the river, but projected RTC bounds do not.")

    product_directory = ACQUISITION_ROOT / river_id / _safe_product_id(product_id)
    product_directory.mkdir(parents=True, exist_ok=True)
    stac_path = product_directory / "stac-item.json"
    stac_path.write_text(json.dumps(item, indent=2), encoding="utf-8")
    raster_path = product_directory / "vv-river-corridor.tif"
    connection.execute(
        "UPDATE acquired_products SET status='acquiring', error=NULL, updated_at=? WHERE river_id=? AND product_id=?",
        (_now().isoformat(), river_id, product_id),
    )
    connection.commit()
    coverage, pixel_size, crs = _read_clipped_raster(
        item,
        river_id,
        river_geometry,
        raster_path,
        token,
    )
    connection.execute(
        "UPDATE acquired_products SET status='processing', updated_at=? WHERE river_id=? AND product_id=?",
        (_now().isoformat(), river_id, product_id),
    )
    connection.commit()
    if stage_callback is not None:
        stage_callback("processing", "Classifying valid Sentinel-1 RTC corridor pixels")

    acquisition_start = _timestamp(properties.get("datetime"))
    if acquisition_start is None:
        raise ValueError(f"STAC item {product_id} has no valid acquisition timestamp.")
    request = WaterMaskRequest(
        river_id=river_id,
        mission="SENTINEL-1",
        product_type="GRD-RTC",
        source_product_id=product_id,
        acquisition_start=acquisition_start,
        polarization="VV",
        band_description="Planetary Computer Sentinel-1 RTC VV calibrated linear intensity",
        signal_scale="linear_power",
        radiometric_calibration_confirmed=True,
        terrain_correction_confirmed=True,
        threshold_method="otsu",
    )
    acquisition_caveats = (
        "Real Sentinel-1 RTC VV pixels were read from the Microsoft Planetary Computer COG; ESA/Catalyst radiometric calibration and terrain correction are upstream processing, not performed by this application.",
        f"The analyzed subset is a {2 * CORRIDOR_HALF_WIDTH_M:,} m-wide corridor buffer around an OSM reference centerline, not a verified river channel boundary.",
        f"The raster scene covers approximately {coverage:.2f}% of the mapped river centerline; the result is a local subset and not whole-river coverage.",
        "The selected orbit is not a matched multi-date time series; no change, flood, erosion, or deposition conclusion is derived from this single acquisition.",
    )
    result = analysis.process_water_mask(
        raster_path.read_bytes(),
        request,
        additional_caveats=acquisition_caveats,
    )
    _insert_or_update_product(
        connection,
        river_id,
        item,
        coverage,
        status="processed",
        analysis_result=result,
    )
    connection.commit()
    source_url = (item.get("assets", {}).get("vv") or {}).get("href", "")
    return AcquiredObservation(
        river_id=river_id,
        product_id=product_id,
        mission="SENTINEL-1",
        product_type="GRD-RTC",
        platform=properties.get("platform"),
        acquisition_start=acquisition_start,
        acquisition_end=_timestamp(properties.get("end_datetime")),
        polarization="VV",
        orbit_state=properties.get("sat:orbit_state"),
        relative_orbit=properties.get("sat:relative_orbit"),
        footprint=item["geometry"],
        centerline_coverage_percent=coverage,
        source="Microsoft Planetary Computer",
        stac_item_url=f"{STAC_URL}/collections/sentinel-1-rtc/items/{product_id}",
        asset_source_url=source_url,
        source_license="CC-BY-4.0",
        provider_processing="Catalyst RTC; upstream radiometric calibration and terrain correction; source asset is linear intensity.",
        processing_status="unvalidated_candidate",
        analysis_id=result.analysis_id,
        candidate_water_area_m2=result.candidate_water_area_m2,
        candidate_water_area_lower_m2=result.candidate_water_area_lower_m2,
        candidate_water_area_upper_m2=result.candidate_water_area_upper_m2,
        threshold_db=result.threshold_db,
        valid_pixel_count=result.valid_pixel_count,
        valid_data_fraction=result.valid_data_fraction,
        water_pixel_count=result.water_pixel_count,
        filter_method=result.filter_method,
        input_crs=crs,
        pixel_size_m=pixel_size,
        corridor_half_width_m=CORRIDOR_HALF_WIDTH_M,
        analysis_url=f"/api/analysis/{result.analysis_id}",
        mask_url=result.mask_url,
        polygons_url=result.polygons_url,
        report_url=result.report_url,
        caveats=result.caveats,
        downloaded_at=_now(),
    )


def _write_scan(
    connection: sqlite3.Connection,
    river_id: str,
    status: str,
    nisar: dict[str, Any],
    candidate_count: int,
    message: str | None,
    nisar_products: list[dict[str, Any]] | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO river_scans (
            river_id, status, last_checked_at, nisar_status, nisar_product_id,
            nisar_acquisition_start, nisar_message, nisar_products_json, candidate_count, message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(river_id) DO UPDATE SET
            status=excluded.status,
            last_checked_at=excluded.last_checked_at,
            nisar_status=excluded.nisar_status,
            nisar_product_id=excluded.nisar_product_id,
            nisar_acquisition_start=excluded.nisar_acquisition_start,
            nisar_message=excluded.nisar_message,
            nisar_products_json=excluded.nisar_products_json,
            candidate_count=excluded.candidate_count,
            message=excluded.message
        """,
        (
            river_id,
            status,
            _now().isoformat(),
            nisar.get("status", "not_checked"),
            nisar.get("product_id"),
            nisar.get("acquisition_start"),
            nisar.get("message"),
            json.dumps(nisar_products if nisar_products is not None else nisar.get("products", [])),
            candidate_count,
            message,
        ),
    )
    connection.commit()


def _refresh_river(
    connection: sqlite3.Connection,
    river: Any,
    token: str,
    nisar_session: Any | None,
    authentication_error: str | None,
    download_nisar: bool,
) -> bool:
    river_id = river.id
    river_geometry = river.centerline.model_dump()
    nisar = _nisar_metadata(river_id, nisar_session, authentication_error)
    discovered_products = nisar.get("products", [])
    cached_products = _cached_nisar_product_records(connection, river_id)
    download_attempted = False
    if download_nisar and nisar_session is not None and discovered_products:
        download_attempted = True
        product = discovered_products[0]
        prior = next(
            (item for item in cached_products if item.get("product_id") == product["product_id"]),
            None,
        )
        if prior and prior.get("download_status") == "downloaded":
            product = _merge_nisar_product_records([product], [prior])[0]
        else:
            try:
                product = _download_nisar_product(river_id, product, nisar_session)
            except Exception as error:
                LOGGER.warning(
                    "Authenticated NISAR download or HDF5 verification failed for %s (%s).",
                    product["product_id"],
                    type(error).__name__,
                )
                product["download_status"] = "failed"
                product["availability"] = "download_failed"
                product["message"] = (
                    f"Authenticated ASF download or HDF5 verification failed ({type(error).__name__}); "
                    "Sentinel-1 fallback will continue."
                )
        discovered_products[0] = product
        nisar["message"] = product.get("message") or nisar["message"]
    nisar_products = _merge_nisar_product_records(discovered_products, cached_products)
    nisar["products"] = nisar_products
    no_valid_data_count = 0
    try:
        _write_scan(connection, river_id, "searching", nisar, 0, None, nisar_products)
        candidates = _item_features(river_id, river_geometry)
        _write_scan(connection, river_id, "searching", nisar, len(candidates), None, nisar_products)
        for item in candidates:
            product_id = item["id"]
            previous = connection.execute(
                "SELECT status, analysis_id FROM acquired_products WHERE river_id=? AND product_id=?",
                (river_id, product_id),
            ).fetchone()
            if previous and previous["status"] == "processed" and previous["analysis_id"]:
                continue
            if previous and previous["status"] in {"acquiring", "processing"}:
                recent_update = connection.execute(
                    "SELECT updated_at FROM acquired_products WHERE river_id=? AND product_id=?",
                    (river_id, product_id),
                ).fetchone()
                updated_at = _timestamp(recent_update["updated_at"] if recent_update else None)
                if updated_at and _now() - updated_at < timedelta(hours=1):
                    continue
            try:
                result = _process_candidate(connection, river_id, river_geometry, item, token)
                _write_scan(
                    connection,
                    river_id,
                    "processed",
                    nisar,
                    len(candidates),
                    f"Automatically acquired and processed {product_id}; output is an unvalidated candidate water mask.",
                    nisar_products,
                )
                LOGGER.info("Processed real Sentinel-1 RTC item %s for %s", product_id, river_id)
                return download_attempted
            except analysis.InsufficientValidDataError as error:
                LOGGER.info(
                    "No valid Sentinel-1 RTC pixels were available for %s / %s.",
                    river_id,
                    product_id,
                )
                _record_failure(
                    connection,
                    river_id,
                    item,
                    river_geometry,
                    str(error),
                    status="no_data",
                )
                no_valid_data_count += 1
                continue
            except Exception as error:
                LOGGER.exception("Satellite acquisition/processing failed for %s (%s)", river_id, product_id)
                _record_failure(connection, river_id, item, river_geometry, str(error))
                continue
        existing = connection.execute(
            "SELECT COUNT(*) FROM acquired_products WHERE river_id=? AND status='processed'",
            (river_id,),
        ).fetchone()[0]
        if candidates and existing:
            _write_scan(
                connection,
                river_id,
                "processed",
                nisar,
                len(candidates),
                f"No new Sentinel-1 RTC item was available; {existing} previously processed item(s) are cached.",
                nisar_products,
            )
        elif candidates and no_valid_data_count == len(candidates):
            _write_scan(
                connection,
                river_id,
                "no_data",
                nisar,
                len(candidates),
                (
                    "Sentinel-1 RTC scenes intersected the mapped river, but no valid positive "
                    "backscatter pixels were available in the analyzed corridor; no water "
                    "classification was generated."
                ),
                nisar_products,
            )
        elif candidates:
            _write_scan(
                connection,
                river_id,
                "failed",
                nisar,
                len(candidates),
                "Catalog products were found, but every unprocessed product failed acquisition or processing. See product errors.",
                nisar_products,
            )
        elif nisar.get("status") == "authentication_required":
            _write_scan(
                connection,
                river_id,
                "blocked",
                nisar,
                0,
                "No public Sentinel-1 RTC scenes were found in the search window; NISAR access status is shown separately.",
                nisar_products,
            )
        else:
            _write_scan(
                connection,
                river_id,
                "no_data",
                nisar,
                0,
                f"No Sentinel-1 RTC scenes intersecting this river were found in the last {SEARCH_LOOKBACK_DAYS} days.",
                nisar_products,
            )
        return download_attempted
    except Exception as error:
        LOGGER.exception("Automatic catalog refresh failed for %s", river_id)
        _write_scan(
            connection,
            river_id,
            "failed",
            nisar,
            0,
            f"Sentinel-1 RTC discovery failed: {error}",
            nisar_products,
        )
        return download_attempted


def refresh_catalog() -> AcquisitionStatus:
    if not automatic_acquisition_enabled():
        return get_catalog_status()
    if not _REFRESH_LOCK.acquire(blocking=False):
        return get_catalog_status()
    try:
        with _catalog_connection() as connection:
            nisar_session, authentication_error = _earthdata_session()
            nisar_download_attempted = False
            try:
                token_response = httpx.get(SAS_TOKEN_URL, timeout=30)
                token_response.raise_for_status()
                token_payload = token_response.json()
                sas_token = token_payload.get("token")
                if not isinstance(sas_token, str) or not sas_token:
                    raise ValueError("Planetary Computer did not return a read-only SAS token.")
            except (httpx.HTTPError, ValueError) as error:
                LOGGER.exception("Unable to obtain Planetary Computer Sentinel-1 RTC read token")
                for river in RIVER_CATALOG:
                    nisar = _nisar_metadata(river.id, nisar_session, authentication_error)
                    nisar_products = _merge_nisar_product_records(
                        nisar.get("products", []),
                        _cached_nisar_product_records(connection, river.id),
                    )
                    nisar["products"] = nisar_products
                    _write_scan(
                        connection,
                        river.id,
                        "failed",
                        nisar,
                        0,
                        f"Sentinel-1 RTC data signing failed: {error}",
                        nisar_products,
                    )
                return _status_from_connection(connection)

            for river in RIVER_CATALOG:
                nisar_download_attempted = _refresh_river(
                    connection,
                    river,
                    sas_token,
                    nisar_session,
                    authentication_error,
                    not nisar_download_attempted,
                )
            return _status_from_connection(connection)
    finally:
        _REFRESH_LOCK.release()


def _observation_from_row(row: sqlite3.Row) -> AcquiredObservation:
    result = analysis._load_result(row["analysis_id"])
    return AcquiredObservation(
        river_id=row["river_id"],
        product_id=row["product_id"],
        mission="SENTINEL-1",
        product_type="GRD-RTC",
        platform=row["platform"],
        acquisition_start=_timestamp(row["acquisition_start"]),
        acquisition_end=_timestamp(row["acquisition_end"]),
        polarization=row["polarization"],
        orbit_state=row["orbit_state"],
        relative_orbit=row["relative_orbit"],
        footprint=json.loads(row["footprint_json"]),
        centerline_coverage_percent=row["centerline_coverage_percent"],
        source="Microsoft Planetary Computer",
        stac_item_url=row["stac_item_url"],
        asset_source_url=row["asset_source_url"],
        source_license=row["source_license"],
        provider_processing=row["provider_processing"],
        processing_status="unvalidated_candidate",
        analysis_id=row["analysis_id"],
        candidate_water_area_m2=row["candidate_water_area_m2"],
        candidate_water_area_lower_m2=row["candidate_water_area_lower_m2"],
        candidate_water_area_upper_m2=row["candidate_water_area_upper_m2"],
        threshold_db=row["threshold_db"],
        valid_pixel_count=result["valid_pixel_count"],
        valid_data_fraction=result["valid_data_fraction"],
        water_pixel_count=result["water_pixel_count"],
        filter_method=result["filter_method"],
        input_crs=row["input_crs"],
        pixel_size_m=row["pixel_size_m"],
        corridor_half_width_m=row["corridor_half_width_m"],
        analysis_url=f"/api/analysis/{row['analysis_id']}",
        mask_url=result["mask_url"],
        polygons_url=result["polygons_url"],
        report_url=result["report_url"],
        caveats=result["caveats"],
        downloaded_at=_timestamp(row["downloaded_at"]),
    )


def _recover_completed_candidate_rows(connection: sqlite3.Connection, river_id: str) -> None:
    try:
        rasterio = analysis._require_rasterio()
    except analysis.ProcessingUnavailable:
        return
    rows = connection.execute(
        """
        SELECT product_id, analysis_id, error, input_crs, pixel_size_m,
               candidate_water_area_m2, threshold_db, processing_status
        FROM acquired_products
        WHERE river_id=? AND status='failed' AND analysis_id IS NOT NULL
          AND error LIKE '4 validation errors for AcquiredObservation%'
        """,
        (river_id,),
    ).fetchall()
    for row in rows:
        if any(
            row[field] is None
            for field in ("input_crs", "pixel_size_m", "candidate_water_area_m2", "threshold_db")
        ):
            continue
        try:
            result = analysis._load_result(row["analysis_id"])
            if not isinstance(result, dict):
                continue
            result_path, _ = analysis.read_output(row["analysis_id"], "water-mask.tif")
            with rasterio.open(result_path) as dataset:
                if (
                    dataset.count != 1
                    or dataset.nodata != 255
                    or dataset.crs is None
                    or dataset.crs.to_string() != row["input_crs"]
                    or dataset.width * dataset.height > analysis.MAX_RASTER_PIXELS
                ):
                    continue
                mask = dataset.read(1)
                valid = (dataset.read_masks(1) > 0) & (mask != dataset.nodata)
                if np.any(valid & ~np.isin(mask, (0, 1))):
                    continue
                valid_count = int(valid.sum())
                candidate_count = int((valid & (mask == 1)).sum())
                pixel_area = abs(
                    dataset.transform.a * dataset.transform.e
                    - dataset.transform.b * dataset.transform.d
                )
                pixel_size_x = math.hypot(dataset.transform.a, dataset.transform.d)
                pixel_size_y = math.hypot(dataset.transform.b, dataset.transform.e)
            metadata = result.get("operator_supplied_metadata")
            if (
                result.get("analysis_type") != "water_mask"
                or result.get("status") != "unvalidated_candidate"
                or result.get("river_id") != river_id
                or result.get("source_product_id") != row["product_id"]
                or row["processing_status"] != "unvalidated_candidate"
                or result.get("mission") != "SENTINEL-1"
                or result.get("polarization") != "VV"
                or not isinstance(metadata, dict)
                or metadata.get("source_product_id") != row["product_id"]
                or metadata.get("mission") != "SENTINEL-1"
                or metadata.get("product_type") != "GRD-RTC"
                or metadata.get("polarization") != "VV"
                or metadata.get("radiometric_calibration_confirmed") is not True
                or metadata.get("terrain_correction_confirmed") is not True
                or valid_count != result.get("valid_pixel_count")
                or candidate_count != result.get("water_pixel_count")
                or not math.isclose(
                    candidate_count * pixel_area,
                    float(row["candidate_water_area_m2"]),
                    rel_tol=0,
                    abs_tol=1e-6,
                )
                or not math.isclose(
                    float(result.get("threshold_db")),
                    float(row["threshold_db"]),
                    rel_tol=0,
                    abs_tol=1e-9,
                )
                or not math.isclose(pixel_size_x, float(row["pixel_size_m"]), rel_tol=0, abs_tol=1e-6)
                or not math.isclose(pixel_size_y, float(row["pixel_size_m"]), rel_tol=0, abs_tol=1e-6)
            ):
                continue
        except (FileNotFoundError, ValueError, rasterio.errors.RasterioError):
            continue

        connection.execute(
            """
            UPDATE acquired_products
            SET status='processed', error=NULL, updated_at=?
            WHERE river_id=? AND product_id=? AND status='failed'
            """,
            (_now().isoformat(), river_id, row["product_id"]),
        )
        LOGGER.info(
            "Recovered completed Sentinel-1 candidate catalog record for %s/%s after verifying its persisted result.",
            river_id,
            row["product_id"],
        )


def _status_from_connection(connection: sqlite3.Connection) -> AcquisitionStatus:
    for river in RIVER_CATALOG:
        local_products = _local_nisar_product_records(river.id)
        if not local_products:
            continue
        row = connection.execute(
            """
            SELECT nisar_status, nisar_product_id, nisar_acquisition_start,
                   nisar_message, nisar_products_json
            FROM river_scans WHERE river_id=?
            """,
            (river.id,),
        ).fetchone()
        if not row:
            continue
        previous_products = json.loads(row["nisar_products_json"] or "[]")
        merged_products = _merge_nisar_product_records(local_products, previous_products)
        recovered_status = row["nisar_status"] in {"no_data", "not_checked"}
        if merged_products != previous_products or recovered_status:
            latest_product = max(
                local_products,
                key=lambda product: product.get("acquisition_start") or "",
            )
            nisar_status = "metadata_found" if recovered_status else row["nisar_status"]
            nisar_product_id = (
                latest_product["product_id"]
                if recovered_status
                else row["nisar_product_id"]
            )
            acquisition_start = (
                latest_product.get("acquisition_start")
                if recovered_status
                else row["nisar_acquisition_start"]
            )
            nisar_message = (
                (
                    f"Recovered {len(local_products)} locally stored NISAR GCOV product(s); "
                    "the latest remote search reported no new products."
                )
                if recovered_status
                else row["nisar_message"]
            )
            connection.execute(
                """
                UPDATE river_scans
                SET nisar_products_json=?, nisar_status=?, nisar_product_id=?,
                    nisar_acquisition_start=?, nisar_message=?
                WHERE river_id=?
                """,
                (
                    json.dumps(merged_products),
                    nisar_status,
                    nisar_product_id,
                    acquisition_start,
                    nisar_message,
                    river.id,
                ),
            )
    connection.commit()
    scans = {
        row["river_id"]: row
        for row in connection.execute("SELECT * FROM river_scans").fetchall()
    }
    river_statuses: list[RiverAcquisitionStatus] = []
    for river in RIVER_CATALOG:
        _recover_completed_candidate_rows(connection, river.id)
        scan = scans.get(river.id)
        rows = connection.execute(
            """
            SELECT * FROM acquired_products
            WHERE river_id=? AND status='processed' AND analysis_id IS NOT NULL
            ORDER BY acquisition_start DESC
            LIMIT 10
            """,
            (river.id,),
        ).fetchall()
        observations = [_observation_from_row(row) for row in rows]
        issue_rows = connection.execute(
            """
            SELECT product_id, status, error, updated_at
            FROM acquired_products
            WHERE river_id=? AND status IN ('failed', 'acquiring', 'processing')
            ORDER BY updated_at DESC
            LIMIT 10
            """,
            (river.id,),
        ).fetchall()
        river_statuses.append(
            RiverAcquisitionStatus(
                river_id=river.id,
                status=scan["status"] if scan else "idle",
                last_checked_at=_timestamp(scan["last_checked_at"]) if scan else None,
                nisar_status=scan["nisar_status"] if scan else "not_checked",
                nisar_product_id=scan["nisar_product_id"] if scan else None,
                nisar_acquisition_start=_timestamp(scan["nisar_acquisition_start"]) if scan else None,
                nisar_message=scan["nisar_message"] if scan else None,
                nisar_products=[
                    NisarProduct.model_validate(product)
                    for product in json.loads(scan["nisar_products_json"] or "[]")
                ]
                if scan
                else [],
                candidate_count=scan["candidate_count"] if scan else 0,
                latest_observation=observations[0] if observations else None,
                observations=observations,
                issues=[
                    AcquisitionIssue(
                        product_id=row["product_id"],
                        status=row["status"],
                        error=row["error"],
                        updated_at=_timestamp(row["updated_at"]),
                    )
                    for row in issue_rows
                ],
                message=scan["message"] if scan else None,
            )
        )
    checked_times = [
        row["last_checked_at"]
        for row in scans.values()
        if row["last_checked_at"]
    ]
    latest_check = max(checked_times) if checked_times else None
    return AcquisitionStatus(
        enabled=automatic_acquisition_enabled(),
        polling_interval_seconds=POLL_INTERVAL_SECONDS,
        last_checked_at=_timestamp(latest_check),
        source="Microsoft Planetary Computer Sentinel-1 RTC",
        source_url=f"{STAC_URL}/collections/sentinel-1-rtc",
        license="CC-BY-4.0",
        rivers=river_statuses,
    )


def get_catalog_status() -> AcquisitionStatus:
    with _catalog_connection() as connection:
        return _status_from_connection(connection)


def acquired_raster_path(river_id: str, product_id: str) -> Path:
    with _catalog_connection() as connection:
        row = connection.execute(
            "SELECT status FROM acquired_products WHERE river_id=? AND product_id=?",
            (river_id, product_id),
        ).fetchone()
    if not row or row["status"] != "processed":
        raise FileNotFoundError(f"No processed acquisition found for {river_id}/{product_id}.")
    path = (ACQUISITION_ROOT / river_id / _safe_product_id(product_id) / "vv-river-corridor.tif").resolve()
    if not path.is_relative_to(ACQUISITION_ROOT.resolve()) or not path.is_file():
        raise FileNotFoundError(f"The acquired Sentinel-1 raster for {product_id} is missing.")
    return path


def nisar_product_path(product_id: str) -> Path:
    with _catalog_connection() as connection:
        scans = connection.execute(
            "SELECT nisar_products_json FROM river_scans"
        ).fetchall()
    for scan in scans:
        for product in json.loads(scan["nisar_products_json"] or "[]"):
            if product.get("product_id") != product_id or not product.get("local_path"):
                continue
            path = (REPOSITORY_ROOT / product["local_path"]).resolve()
            if not path.is_relative_to(ACQUISITION_ROOT.resolve()) or not path.is_file():
                break
            return path
    raise FileNotFoundError(f"No verified local NISAR product found for {product_id}.")


def _nisar_product_record(
    river_id: str,
    product_id: str,
) -> tuple[dict[str, Any], Path]:
    if river_id not in {river.id for river in RIVER_CATALOG}:
        raise ValueError(f"Unsupported river_id: {river_id}")
    with _catalog_connection() as connection:
        row = connection.execute(
            "SELECT nisar_products_json FROM river_scans WHERE river_id=?",
            (river_id,),
        ).fetchone()
    if not row:
        raise FileNotFoundError(f"No NISAR catalog entry found for {river_id}/{product_id}.")
    products = json.loads(row["nisar_products_json"] or "[]")
    product = next((item for item in products if item.get("product_id") == product_id), None)
    if not product or not product.get("local_path"):
        raise FileNotFoundError(f"No downloaded NISAR product found for {river_id}/{product_id}.")
    product_path = (REPOSITORY_ROOT / product["local_path"]).resolve()
    if not product_path.is_relative_to(ACQUISITION_ROOT.resolve()) or not product_path.is_file():
        raise FileNotFoundError(f"The downloaded NISAR product for {product_id} is missing.")
    if product.get("product_level") != "GCOV":
        raise ValueError(f"NISAR {product.get('product_level')} processing is not supported.")
    return product, product_path


def _save_nisar_product_record(
    river_id: str,
    product_id: str,
    updated_product: dict[str, Any],
) -> None:
    with _catalog_connection() as connection:
        row = connection.execute(
            "SELECT nisar_products_json FROM river_scans WHERE river_id=?",
            (river_id,),
        ).fetchone()
        if not row:
            raise FileNotFoundError(f"No NISAR catalog entry found for {river_id}/{product_id}.")
        products = json.loads(row["nisar_products_json"] or "[]")
        product_index = next(
            (index for index, item in enumerate(products) if item.get("product_id") == product_id),
            None,
        )
        if product_index is None:
            raise FileNotFoundError(f"No NISAR catalog entry found for {river_id}/{product_id}.")
        products[product_index] = updated_product
        connection.execute(
            "UPDATE river_scans SET nisar_products_json=? WHERE river_id=?",
            (json.dumps(products), river_id),
        )
        connection.commit()


def nisar_processing_result(river_id: str, product_id: str) -> dict[str, Any]:
    product, product_path = _nisar_product_record(river_id, product_id)
    result = product.get("processing_result")
    if not result:
        raise FileNotFoundError(f"No NISAR processing result found for {river_id}/{product_id}.")
    if result.get("status") == "no_valid_corridor_data":
        result["mask_url"] = None
        result["measurements_url"] = None
        result["polygons_url"] = None
        product["processing_result"] = result
        product["processing_status"] = "no_data"
        _save_nisar_product_record(river_id, product_id, product)
        metadata_path = product_path.parent / "nisar-processing" / "processing-metadata.json"
        if metadata_path.is_file():
            metadata_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if result.get("status") == "unvalidated_candidate":
        result = _attach_optical_candidate_urls(
            result,
            river_id,
            product_id,
            product_path,
        )
    return result


def _attach_optical_candidate_urls(
    result: dict[str, Any],
    river_id: str,
    product_id: str,
    product_path: Path,
) -> dict[str, Any]:
    reference_directory = product_path.parent / "nisar-processing" / "sentinel2-reference"
    if not (
        (reference_directory / "processing-metadata.json").is_file()
        and (reference_directory / "ndwi-candidate-mask.tif").is_file()
    ):
        return result
    encoded_product_id = quote(product_id, safe="")
    encoded_river_id = quote(river_id, safe="")
    endpoint = (
        f"/api/acquisitions/nisar/{encoded_product_id}/processing/"
        "sentinel2-reference"
    )
    return {
        **result,
        "optical_reference_url": f"{endpoint}?river_id={encoded_river_id}",
        "optical_candidate_mask_url": f"{endpoint}/mask?river_id={encoded_river_id}",
    }


def nisar_optical_reference_path(
    river_id: str,
    product_id: str,
    output_name: str,
) -> Path:
    allowed_outputs = {
        "mask": "ndwi-candidate-mask.tif",
        "metadata": "processing-metadata.json",
    }
    if output_name not in allowed_outputs:
        raise ValueError("Unsupported Sentinel-2 candidate output.")
    _, product_path = _nisar_product_record(river_id, product_id)
    reference_directory = (
        product_path.parent / "nisar-processing" / "sentinel2-reference"
    ).resolve()
    if not reference_directory.is_relative_to(product_path.parent.resolve()):
        raise ValueError("Sentinel-2 candidate output path is outside the product directory.")
    result_path = (reference_directory / allowed_outputs[output_name]).resolve()
    if not result_path.is_relative_to(reference_directory) or not result_path.is_file():
        raise FileNotFoundError(
            f"Sentinel-2 candidate output {output_name} is not available."
        )
    return result_path


def nisar_optical_observation_path(
    river_id: str,
    product_id: str,
    observation_id: str,
    output_name: str,
) -> Path:
    allowed_outputs = {
        "mask": "ndwi-candidate-mask.tif",
        "metadata": "processing-metadata.json",
    }
    if output_name not in allowed_outputs:
        raise ValueError("Unsupported Sentinel-2 observation output.")
    if not re.fullmatch(r"S2[A-Z]_MSIL2A_[A-Za-z0-9_]{1,140}", observation_id):
        raise ValueError("Invalid Sentinel-2 observation identifier.")
    _, product_path = _nisar_product_record(river_id, product_id)
    processing_directory = (product_path.parent / "nisar-processing").resolve()
    observation_directory = (
        processing_directory / "sentinel2-observations" / observation_id
    ).resolve()
    if (
        not observation_directory.is_relative_to(processing_directory)
        or not observation_directory.is_relative_to(product_path.parent.resolve())
    ):
        raise ValueError("Sentinel-2 observation output is outside the product directory.")
    metadata_path = (observation_directory / allowed_outputs["metadata"]).resolve()
    if not metadata_path.is_relative_to(observation_directory) or not metadata_path.is_file():
        raise FileNotFoundError("Sentinel-2 observation metadata is not available.")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Sentinel-2 observation metadata is unreadable.") from error
    if not isinstance(metadata, dict) or (metadata.get("source") or {}).get("item_id") != observation_id:
        raise ValueError("Sentinel-2 observation identifier does not match its metadata.")
    output_path = (observation_directory / allowed_outputs[output_name]).resolve()
    if not output_path.is_relative_to(observation_directory) or not output_path.is_file():
        raise FileNotFoundError(f"Sentinel-2 observation output {output_name} is not available.")
    return output_path


def nisar_optical_observations(
    river_id: str,
    product_id: str,
) -> list[dict[str, Any]]:
    product, product_path = _nisar_product_record(river_id, product_id)
    observation_root = (
        product_path.parent / "nisar-processing" / "sentinel2-observations"
    )
    if not observation_root.exists():
        return []
    observations: list[dict[str, Any]] = []
    for directory in sorted(observation_root.iterdir()):
        if not directory.is_dir():
            continue
        metadata_path = nisar_optical_observation_path(
            river_id, product_id, directory.name, "metadata"
        )
        mask_path = nisar_optical_observation_path(
            river_id, product_id, directory.name, "mask"
        )
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("Sentinel-2 observation metadata is unreadable.") from error
        if not isinstance(metadata, dict) or not isinstance(metadata.get("counts"), dict):
            raise ValueError("Sentinel-2 observation metadata has an invalid structure.")
        try:
            import rasterio
            from rasterio.warp import transform_bounds

            with rasterio.open(mask_path) as raster:
                if raster.crs is None or raster.nodata != 255:
                    raise ValueError("Sentinel-2 observation raster has invalid CRS or NoData metadata.")
                metadata["crs"] = raster.crs.to_string()
                metadata["bounds_wgs84"] = dict(
                    zip(
                        ("west", "south", "east", "north"),
                        transform_bounds(
                            raster.crs, "EPSG:4326", *raster.bounds, densify_pts=21
                        ),
                        strict=True,
                    )
                )
                metadata["dimensions"] = {"width": raster.width, "height": raster.height}
                metadata["nodata_value"] = raster.nodata
        except ImportError as error:
            raise RuntimeError("Sentinel-2 raster metadata requires Rasterio.") from error

        encoded_product = quote(product_id, safe="")
        encoded_river = quote(river_id, safe="")
        encoded_observation = quote(directory.name, safe="")
        endpoint = (
            f"/api/acquisitions/nisar/{encoded_product}/processing/"
            f"sentinel2-observations/{encoded_observation}"
        )
        metadata["preview_url"] = f"{endpoint}/preview?river_id={encoded_river}"
        metadata["mask_url"] = f"{endpoint}/mask?river_id={encoded_river}"
        nisar_acquisition = product.get("acquisition_start") or (
            product.get("processing_result") or {}
        ).get("acquisition_start")
        if isinstance(nisar_acquisition, str):
            metadata["nisar_acquisition_datetime"] = nisar_acquisition
            nisar_time = _timestamp(nisar_acquisition)
            sentinel2_time = _timestamp(
                (metadata.get("source") or {}).get("acquisition_datetime")
            )
            if nisar_time and sentinel2_time:
                metadata["acquisition_time_difference_seconds"] = abs(
                    (sentinel2_time - nisar_time).total_seconds()
                )
        observations.append(metadata)
    return observations


def create_nisar_optical_reference_preview(mask_path: str | Path) -> bytes:
    return create_candidate_preview(mask_path)


def nisar_optical_reference_metadata(
    river_id: str,
    product_id: str,
) -> dict[str, Any]:
    product, _ = _nisar_product_record(river_id, product_id)
    metadata_path = nisar_optical_reference_path(river_id, product_id, "metadata")
    mask_path = nisar_optical_reference_path(river_id, product_id, "mask")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Sentinel-2 candidate metadata is unreadable.") from error
    if not isinstance(metadata, dict) or not isinstance(metadata.get("counts"), dict):
        raise ValueError("Sentinel-2 candidate metadata has an invalid structure.")
    try:
        import rasterio
        from rasterio.warp import transform_bounds

        with rasterio.open(mask_path) as raster:
            if raster.crs is None or raster.nodata != 255:
                raise ValueError("Sentinel-2 candidate raster has invalid CRS or NoData metadata.")
            metadata["crs"] = raster.crs.to_string()
            metadata["bounds_wgs84"] = dict(
                zip(
                    ("west", "south", "east", "north"),
                    transform_bounds(raster.crs, "EPSG:4326", *raster.bounds, densify_pts=21),
                    strict=True,
                )
            )
            metadata["dimensions"] = {"width": raster.width, "height": raster.height}
            metadata["nodata_value"] = raster.nodata
            metadata["preview_url"] = (
                f"/api/acquisitions/nisar/{quote(product_id, safe='')}/processing/"
                f"sentinel2-reference/preview?river_id={quote(river_id, safe='')}"
            )
    except ImportError as error:
        raise RuntimeError("Sentinel-2 raster metadata requires Rasterio.") from error

    nisar_acquisition = product.get("acquisition_start")
    if not nisar_acquisition:
        nisar_acquisition = (product.get("processing_result") or {}).get("acquisition_start")
    if isinstance(nisar_acquisition, str):
        metadata["nisar_acquisition_datetime"] = nisar_acquisition
        sentinel2_acquisition = (metadata.get("source") or {}).get("acquisition_datetime")
        nisar_time = _timestamp(nisar_acquisition)
        sentinel2_time = _timestamp(sentinel2_acquisition)
        if nisar_time and sentinel2_time:
            metadata["acquisition_time_difference_seconds"] = abs(
                (sentinel2_time - nisar_time).total_seconds()
            )

    source_item_id = (metadata.get("source") or {}).get("item_id")
    if river_id == "tungabhadra" and source_item_id == (
        "S2C_MSIL2A_20261106T052011_R062_T43PGT_20261106T101206"
    ):
        metadata["mapped_centerline_coverage_percent"] = 21.7962
        metadata["mapped_centerline_coverage_source"] = (
            "Measured STAC-footprint intersection with the mapped centerline; "
            "see SENTINEL2-NISAR-COMPARISON-DIAGNOSTIC.md."
        )
    metadata["additional_observations"] = nisar_optical_observations(
        river_id, product_id
    )
    return metadata


def _attach_nisar_quality_diagnostics(
    result: dict[str, Any],
    product_path: Path,
    river_id: str,
    product_id: str,
) -> dict[str, Any]:
    if result.get("status") != "unvalidated_candidate":
        return result
    from app.services.nisar_gcov import CLASSIFICATION_ALGORITHM, build_classification_diagnostics

    output_directory = product_path.parent / "nisar-processing"
    diagnostics = build_classification_diagnostics(
        output_directory / "gcov-measurements.tif",
        output_directory / "candidate-water-mask.tif",
        output_directory,
        float(result["hh_threshold_db"]),
        float(result["hv_threshold_db"]),
        float(result["pixel_size_m"]) ** 2,
    )
    result.update(diagnostics)
    result["algorithm"] = CLASSIFICATION_ALGORITHM
    encoded_product = quote(product_id, safe="")
    encoded_river = quote(river_id, safe="")
    result["comparison_url"] = (
        f"/api/acquisitions/nisar/{encoded_product}/processing/comparison"
        f"?river_id={encoded_river}"
    )
    result["sensitivity_url"] = (
        f"/api/acquisitions/nisar/{encoded_product}/processing/sensitivity"
        f"?river_id={encoded_river}"
    )
    return result


def process_nisar_product(river_id: str, product_id: str) -> dict[str, Any]:
    if not _NISAR_PROCESS_LOCK.acquire(blocking=False):
        raise NisarProcessingBusy("Another NISAR GCOV processing job is already running.")
    try:
        product, product_path = _nisar_product_record(river_id, product_id)
        if product.get("processing_status") in {"processed", "no_data"} and product.get("processing_result"):
            result = product["processing_result"]
            if result.get("status") == "no_valid_corridor_data":
                result["mask_url"] = None
                result["measurements_url"] = None
                result["polygons_url"] = None
                product["processing_result"] = result
                _save_nisar_product_record(river_id, product_id, product)
            elif result.get("status") == "unvalidated_candidate":
                from app.services.nisar_gcov import CLASSIFICATION_ALGORITHM

                if (
                    not result.get("connected_component_summary")
                    or result.get("algorithm") != CLASSIFICATION_ALGORITHM
                ):
                    result = _attach_nisar_quality_diagnostics(
                        result,
                        product_path,
                        river_id,
                        product_id,
                    )
                    product["processing_result"] = result
                    _save_nisar_product_record(river_id, product_id, product)
                    (product_path.parent / "nisar-processing" / "processing-metadata.json").write_text(
                        json.dumps(result, indent=2),
                        encoding="utf-8",
                    )
            return product["processing_result"]
        if product.get("download_status") != "downloaded":
            raise ValueError("Only a downloaded and HDF5-verified NISAR product can be processed.")

        product["processing_status"] = "processing"
        product["processing_message"] = None
        _save_nisar_product_record(river_id, product_id, product)
        try:
            from app.services.nisar_gcov import process_gcov_product

            output_directory = product_path.parent / "nisar-processing"
            result = process_gcov_product(
                product_path,
                product_id,
                river_id,
                output_directory,
            )
            result = _attach_nisar_quality_diagnostics(
                result,
                product_path,
                river_id,
                product_id,
            )
            result["acquisition_start"] = product.get("acquisition_start")
            result["acquisition_end"] = product.get("acquisition_end")
            has_candidate = result["status"] == "unvalidated_candidate"
            if has_candidate:
                result["mask_url"] = (
                    f"/api/acquisitions/nisar/{quote(product_id, safe='')}/processing/mask"
                    f"?river_id={quote(river_id, safe='')}"
                )
                result["measurements_url"] = (
                    f"/api/acquisitions/nisar/{quote(product_id, safe='')}/processing/measurements"
                    f"?river_id={quote(river_id, safe='')}"
                )
                result["polygons_url"] = (
                    f"/api/acquisitions/nisar/{quote(product_id, safe='')}/processing/polygons"
                    f"?river_id={quote(river_id, safe='')}"
                )
            else:
                result["mask_url"] = None
                result["measurements_url"] = None
                result["polygons_url"] = None
            result["metadata_url"] = (
                f"/api/acquisitions/nisar/{quote(product_id, safe='')}/processing"
                f"?river_id={quote(river_id, safe='')}"
            )
            metadata_path = output_directory / "processing-metadata.json"
            metadata_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            product["processing_status"] = "processed" if has_candidate else "no_data"
            product["processing_message"] = (
                "Unvalidated, single-date candidate water classification; no riverbank or change analysis."
                if has_candidate
                else (
                    "No candidate mask generated: no valid paired, fully focused HH/HV samples "
                    "were available inside this product's mapped river corridor."
                )
            )
            product["processing_result"] = result
            _save_nisar_product_record(river_id, product_id, product)
            return result
        except Exception as error:
            product["processing_status"] = "failed"
            product["processing_message"] = f"{type(error).__name__}: {error}"
            _save_nisar_product_record(river_id, product_id, product)
            LOGGER.exception(
                "NISAR GCOV processing failed for %s / %s.",
                river_id,
                product_id,
            )
            raise
    finally:
        _NISAR_PROCESS_LOCK.release()


def create_nisar_component_sensitivity(
    river_id: str,
    product_id: str,
    minimum_component_sizes: list[int],
) -> list[dict[str, Any]]:
    if not _NISAR_COMPONENT_SENSITIVITY_LOCK.acquire(blocking=False):
        raise NisarProcessingBusy("Another NISAR component-sensitivity operation is already running.")
    try:
        product, product_path = _nisar_product_record(river_id, product_id)
        processing_result = product.get("processing_result")
        if (
            product.get("processing_status") != "processed"
            or not processing_result
            or processing_result.get("status") != "unvalidated_candidate"
        ):
            raise FileNotFoundError(
                f"No processed candidate mask is available for {river_id}/{product_id}."
            )
        processing_directory = product_path.parent / "nisar-processing"
        mask_path = processing_directory / "candidate-water-mask.tif"
        if not mask_path.is_file():
            raise FileNotFoundError(f"No candidate mask is available for {river_id}/{product_id}.")
        from app.services.nisar_gcov import build_component_sensitivity_outputs

        results = build_component_sensitivity_outputs(
            mask_path,
            processing_directory / "component-sensitivity",
            minimum_component_sizes,
        )
        for result in results:
            minimum_size = result["minimum_component_pixels"]
            result.update(
                {
                    "river_id": river_id,
                    "product_id": product_id,
                    "source_product_id": product_id,
                    "acquisition_start": product.get("acquisition_start"),
                    "mask_url": (
                        f"/api/acquisitions/nisar/{quote(product_id, safe='')}/processing/"
                        f"component-sensitivity/{minimum_size}/mask?river_id={quote(river_id, safe='')}"
                    ),
                }
            )
            result_path = (
                processing_directory
                / "component-sensitivity"
                / f"minimum-{minimum_size}-pixels-8-connectivity"
                / "metadata.json"
            )
            result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return results
    finally:
        _NISAR_COMPONENT_SENSITIVITY_LOCK.release()


def nisar_component_sensitivity_output_path(
    river_id: str,
    product_id: str,
    minimum_component_pixels: int,
    output_name: str,
) -> Path:
    if not 2 <= minimum_component_pixels <= 100_000:
        raise ValueError("Minimum component size must be between 2 and 100,000 pixels.")
    allowed_outputs = {
        "mask": "candidate-water-mask.tif",
        "metadata": "metadata.json",
    }
    if output_name not in allowed_outputs:
        raise ValueError("Unsupported component-sensitivity output.")
    product, product_path = _nisar_product_record(river_id, product_id)
    if (
        product.get("processing_status") != "processed"
        or not product.get("processing_result")
        or product["processing_result"].get("status") != "unvalidated_candidate"
    ):
        raise FileNotFoundError(f"No processed candidate mask is available for {river_id}/{product_id}.")
    processing_directory = (product_path.parent / "nisar-processing").resolve()
    if not processing_directory.is_relative_to(product_path.parent.resolve()):
        raise ValueError("NISAR processing output path is outside the product directory.")
    sensitivity_directory = (
        processing_directory
        / "component-sensitivity"
        / f"minimum-{minimum_component_pixels}-pixels-8-connectivity"
    ).resolve()
    if not sensitivity_directory.is_relative_to(processing_directory):
        raise ValueError("Component-sensitivity output path is outside the processing directory.")
    output_path = (sensitivity_directory / allowed_outputs[output_name]).resolve()
    if not output_path.is_relative_to(sensitivity_directory) or not output_path.is_file():
        raise FileNotFoundError(
            f"Component-sensitivity output for minimum size {minimum_component_pixels} is not available."
        )
    return output_path


def nisar_processing_output_path(
    river_id: str,
    product_id: str,
    output_name: str,
) -> Path:
    allowed_outputs = {
        "mask": "candidate-water-mask.tif",
        "measurements": "gcov-measurements.tif",
        "polygons": "candidate-water.geojson",
        "metadata": "processing-metadata.json",
        "comparison": "polarization-comparison.tif",
        "sensitivity": "threshold-sensitivity.tif",
    }
    if output_name not in allowed_outputs:
        raise ValueError("Unsupported NISAR processing output.")
    _, product_path = _nisar_product_record(river_id, product_id)
    processing_directory = (product_path.parent / "nisar-processing").resolve()
    if not processing_directory.is_relative_to(product_path.parent.resolve()):
        raise ValueError("NISAR processing output path is outside the product directory.")
    result_path = (processing_directory / allowed_outputs[output_name]).resolve()
    if not result_path.is_relative_to(processing_directory) or not result_path.is_file():
        raise FileNotFoundError(f"NISAR processing output {output_name} is not available.")
    return result_path


async def refresh_catalog_async() -> AcquisitionStatus:
    return await asyncio.to_thread(refresh_catalog)


async def automatic_refresh_loop() -> None:
    while automatic_acquisition_enabled():
        try:
            await refresh_catalog_async()
        except Exception:
            LOGGER.exception("Unexpected error in scheduled satellite acquisition")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
