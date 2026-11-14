"""Genuine Sentinel-2 L2A discovery and vegetation-index processing.

This service deliberately keeps optical observations separate from the radar
catalog.  A record is only marked processed after the source assets have been
read and index rasters have been written locally.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.warp import reproject, transform_bounds, transform_geom
from shapely.geometry import shape

from app.redaction import redact_sensitive_text
from app.services.rivers import RIVER_CATALOG

LOGGER = logging.getLogger(__name__)
STAC_SEARCH_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SAS_TOKEN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token/sentinel-2-l2a"
DATA_ROOT = Path(__file__).resolve().parents[1] / "data" / "acquisitions" / "sentinel2"
CATALOG_PATH = DATA_ROOT / "catalog.json"
PROCESSOR_VERSION = "sentinel2-indices-1.4"
VALID_SCL_CLASSES = {4, 5, 6, 7}
PREVIEW_RENDER_LOCK = threading.Lock()


def _river(river_id: str):
    return next((item for item in RIVER_CATALOG if item.id == river_id), None)


def _geometry(river_id: str) -> dict[str, Any]:
    river = _river(river_id)
    if river is None:
        raise ValueError(f"Unsupported river_id: {river_id}")
    return river.centerline.model_dump()


def _load_catalog() -> list[dict[str, Any]]:
    if not CATALOG_PATH.exists():
        return []
    try:
        payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        LOGGER.warning("Unable to read Sentinel-2 cache: %s", error)
        return []
    return payload if isinstance(payload, list) else []


def _save_catalog(records: list[dict[str, Any]]) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=DATA_ROOT, delete=False) as handle:
        json.dump(records, handle, indent=2, sort_keys=True)
        temporary = Path(handle.name)
    os.replace(temporary, CATALOG_PATH)


def _sign_href(href: str, token: str) -> str:
    return f"{href}{'&' if '?' in href else '?'}{token.lstrip('?')}"


def _planetary_computer_token(client: httpx.Client) -> str:
    response = client.get(SAS_TOKEN_URL, timeout=30)
    response.raise_for_status()
    token = response.json().get("token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Microsoft Planetary Computer returned no Sentinel-2 read token.")
    return token


def discover_sentinel2(river_id: str, limit: int = 8) -> list[dict[str, Any]]:
    """Return real STAC items intersecting the selected river."""
    now = datetime.now(timezone.utc)
    payload = {
        "collections": ["sentinel-2-l2a"],
        "intersects": _geometry(river_id),
        "datetime": f"{(now - timedelta(days=730)).isoformat()}/{now.isoformat()}",
        "limit": min(max(limit, 1), 100),
    }
    with httpx.Client() as client:
        response = client.post(STAC_SEARCH_URL, json=payload, timeout=60)
        response.raise_for_status()
    features = response.json().get("features", [])
    records: list[dict[str, Any]] = []
    for item in features:
        if not isinstance(item, dict) or not item.get("id") or not item.get("assets"):
            continue
        assets = item["assets"]
        if not all(name in assets and assets[name].get("href") for name in ("B02", "B04", "B08", "B11", "SCL")):
            continue
        properties = item.get("properties", {})
        acquisition_datetime = (
            item.get("datetime")
            or properties.get("datetime")
            or properties.get("start_datetime")
        )
        records.append({
            "river_id": river_id,
            "item_id": item["id"],
            "acquisition_datetime": acquisition_datetime,
            "cloud_cover_percent": properties.get("eo:cloud_cover"),
            "footprint": item.get("geometry"),
            "bbox": item.get("bbox"),
            "source": "Microsoft Planetary Computer",
            "collection": "sentinel-2-l2a",
            "stac_item_url": next(
                (link.get("href") for link in item.get("links", []) if link.get("rel") == "self"),
                "",
            ),
            "assets": {name: assets[name]["href"] for name in ("B02", "B04", "B08", "B11", "SCL")},
            "status": "discovered",
        })
    return sorted(
        records,
        key=lambda record: record.get("acquisition_datetime") or "",
        reverse=True,
    )


def calculate_indices(
    blue: np.ndarray,
    red: np.ndarray,
    nir: np.ndarray,
    swir: np.ndarray,
    valid: np.ndarray,
) -> dict[str, np.ndarray]:
    """Calculate scaled Sentinel-2 vegetation indices without invalid zeros."""
    blue = blue.astype(np.float32) * 0.0001
    red = red.astype(np.float32) * 0.0001
    nir = nir.astype(np.float32) * 0.0001
    swir = swir.astype(np.float32) * 0.0001
    valid = (
        valid
        & np.isfinite(blue)
        & np.isfinite(red)
        & np.isfinite(nir)
        & np.isfinite(swir)
        & (blue > 0)
        & (red > 0)
        & (nir > 0)
        & (swir > 0)
    )
    ndvi_denominator = nir + red
    evi_denominator = nir + 6 * red - 7.5 * blue + 1
    ndmi_denominator = nir + swir
    result: dict[str, np.ndarray] = {}
    for name, numerator, denominator in (
        ("ndvi", nir - red, ndvi_denominator),
        ("evi", nir - red, evi_denominator),
        ("ndmi", nir - swir, ndmi_denominator),
    ):
        output = np.full(nir.shape, np.nan, dtype=np.float32)
        usable = valid & np.isfinite(denominator) & (denominator != 0)
        if name == "evi":
            output[usable] = 2.5 * numerator[usable] / denominator[usable]
        else:
            output[usable] = numerator[usable] / denominator[usable]
        result[name] = output
    return result


def _read_to_grid(
    dataset: rasterio.DatasetReader,
    target_shape: tuple[int, int],
    target_transform,
    target_crs,
) -> np.ndarray:
    output = np.zeros(target_shape, dtype=np.float32)
    reproject(
        source=rasterio.band(dataset, 1),
        destination=output,
        src_transform=dataset.transform,
        src_crs=dataset.crs,
        dst_transform=target_transform,
        dst_crs=target_crs,
        resampling=Resampling.bilinear,
        src_nodata=0,
        dst_nodata=0,
    )
    return output


def _write_index(path: Path, array: np.ndarray, profile: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **profile) as output:
        output.write(array.astype(np.float32), 1)


def _write_preview(path: Path, array: np.ndarray) -> None:
    rgba = _preview_rgba(array)
    with rasterio.open(
        path,
        "w",
        driver="PNG",
        height=rgba.shape[0],
        width=rgba.shape[1],
        count=4,
        dtype="uint8",
    ) as output:
        output.write(rgba.transpose(2, 0, 1))


def _preview_rgba(array: np.ndarray) -> np.ndarray:
    finite = np.isfinite(array)
    rgba = np.zeros((*array.shape, 4), dtype=np.uint8)
    values = np.clip(array[finite], -1, 1)
    for channel, colors in enumerate(((49, 255, 0), (54, 255, 104), (149, 191, 55))):
        rgba[..., channel][finite] = np.interp(values, (-1, 0, 1), colors).astype(np.uint8)
    rgba[..., 3][finite] = 255
    return rgba


def _web_mercator_bounds(dataset: rasterio.DatasetReader) -> tuple[float, float, float, float]:
    if dataset.crs is None:
        raise ValueError("Sentinel-2 index raster has no CRS.")
    return transform_bounds(dataset.crs, "EPSG:3857", *dataset.bounds)


def _wgs84_bounds(dataset: rasterio.DatasetReader) -> dict[str, float]:
    west, south, east, north = transform_bounds(
        "EPSG:3857", "EPSG:4326", *_web_mercator_bounds(dataset)
    )
    return {"west": west, "south": south, "east": east, "north": north}


def render_index_png(path: Path, *, overview: bool = False) -> bytes:
    # Full-resolution grids can exceed 30 million pixels; avoid concurrent allocation spikes.
    with PREVIEW_RENDER_LOCK:
        return _render_index_png(path, overview=overview)


def _render_index_png(path: Path, *, overview: bool = False) -> bytes:
    with rasterio.open(path) as dataset:
        bounds = _web_mercator_bounds(dataset)
        source = dataset.read(1, masked=True).astype(np.float32).filled(np.nan)
        source[~np.isfinite(source)] = np.nan
        scale = min(1.0, 256 / max(dataset.width, dataset.height)) if overview else 1.0
        width = max(1, round(dataset.width * scale))
        height = max(1, round(dataset.height * scale))
        array = np.full((height, width), np.nan, dtype=np.float32)
        reproject(
            source=source,
            destination=array,
            src_transform=dataset.transform,
            src_crs=dataset.crs,
            src_nodata=np.nan,
            dst_transform=rasterio.transform.from_bounds(
                *bounds, width, height,
            ),
            dst_crs="EPSG:3857",
            dst_nodata=np.nan,
            resampling=Resampling.average if overview and scale < 1 else Resampling.nearest,
        )
    rgba = _preview_rgba(array)
    with MemoryFile() as memory_file:
        with memory_file.open(
            driver="PNG",
            height=rgba.shape[0],
            width=rgba.shape[1],
            count=4,
            dtype="uint8",
        ) as output:
            output.write(rgba.transpose(2, 0, 1))
        return memory_file.read()


def process_sentinel2_item(record: dict[str, Any]) -> dict[str, Any]:
    """Read one real item, calculate indices, and persist the outputs."""
    output_root = DATA_ROOT / record["river_id"] / record["item_id"]
    output_root.mkdir(parents=True, exist_ok=True)
    with httpx.Client() as client:
        token = _planetary_computer_token(client)
    signed = {name: _sign_href(href, token) for name, href in record["assets"].items()}

    with rasterio.open(signed["B11"]) as swir_dataset:
        river_shape = shape(_geometry(record["river_id"]))
        tile_shape = shape(record["footprint"]) if record.get("footprint") else river_shape
        intersected_shape = river_shape.intersection(tile_shape)
        if intersected_shape.is_empty:
            raise ValueError("Sentinel-2 tile does not overlap the selected river geometry.")
        river_geometry = transform_geom(
            "EPSG:4326",
            swir_dataset.crs,
            intersected_shape.__geo_interface__,
        )
        bounds = shape(river_geometry).bounds
        window = rasterio.windows.from_bounds(*bounds, transform=swir_dataset.transform)
        window = window.intersection(rasterio.windows.Window(0, 0, swir_dataset.width, swir_dataset.height))
        height, width = max(1, int(math.ceil(window.height))), max(1, int(math.ceil(window.width)))
        target_transform = swir_dataset.window_transform(
            rasterio.windows.Window(window.col_off, window.row_off, width, height)
        )
        target_crs = swir_dataset.crs
        swir = swir_dataset.read(1, window=window, out_shape=(height, width))
        with rasterio.open(signed["SCL"]) as scl_dataset:
            scl = scl_dataset.read(
                1,
                window=window,
                out_shape=(height, width),
                resampling=Resampling.nearest,
            )
        corridor_mask = geometry_mask(
            [river_geometry],
            out_shape=(height, width),
            transform=target_transform,
            invert=True,
        )
        valid = np.isin(scl, list(VALID_SCL_CLASSES))
        valid &= corridor_mask
        bands: dict[str, np.ndarray] = {}
        for name in ("B02", "B04", "B08"):
            with rasterio.open(signed[name]) as dataset:
                bands[name] = _read_to_grid(dataset, (height, width), target_transform, target_crs)

    indices = calculate_indices(bands["B02"], bands["B04"], bands["B08"], swir, valid)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": target_crs,
        "transform": target_transform,
        "nodata": -9999.0,
        "compress": "deflate",
    }
    output_paths: dict[str, str] = {}
    preview_paths: dict[str, str] = {}
    for name, array in indices.items():
        array = np.where(np.isfinite(array), array, -9999.0)
        path = output_root / f"{name}.tif"
        _write_index(path, array, profile)
        output_paths[name] = str(path.relative_to(DATA_ROOT.parent.parent))
        preview = output_root / f"{name}.png"
        _write_preview(preview, indices[name])
        preview_paths[name] = str(preview.relative_to(DATA_ROOT.parent.parent))

    with rasterio.open(output_root / "ndvi.tif") as dataset:
        bounds_wgs84 = _wgs84_bounds(dataset)

    valid_values = {name: array[np.isfinite(array)] for name, array in indices.items()}
    record.update({
        "status": "processed" if valid_values["ndvi"].size else "no_usable_pixels",
        "processor_version": PROCESSOR_VERSION,
        "crs": str(target_crs),
        "resolution_m": abs(float(target_transform.a)),
        "width": width,
        "height": height,
        "corridor_pixel_count": int(corridor_mask.sum()),
        "valid_pixel_count": int(valid_values["ndvi"].size),
        "valid_pixel_percent": float(valid_values["ndvi"].size / (int(corridor_mask.sum()) or 1) * 100),
        "raster_pixel_percent": float(valid_values["ndvi"].size / (height * width) * 100),
        "index_statistics": {
            name: {
                "mean": float(values.mean()),
                "minimum": float(values.min()),
                "maximum": float(values.max()),
                "p05": float(np.percentile(values, 5)),
                "p95": float(np.percentile(values, 95)),
            }
            for name, values in valid_values.items()
            if values.size
        },
        "processing_parameters": {
            "reflectance_scale_factor": 0.0001,
            "valid_scl_classes": sorted(VALID_SCL_CLASSES),
            "cloud_shadow_scl_classes_excluded": [3, 8, 9, 10, 11],
            "target_resolution_m": 20,
            "formulas": {
                "ndvi": "(B08-B04)/(B08+B04)",
                "evi": "2.5*(B08-B04)/(B08+6*B04-7.5*B02+1)",
                "ndmi": "(B08-B11)/(B08+B11)",
            },
        },
        "output_paths": output_paths,
        "preview_paths": preview_paths,
        "bounds_wgs84": bounds_wgs84,
        "preview_color_scale": {
            "minimum": -1,
            "maximum": 1,
            "low": "#313695",
            "middle": "#ffffbf",
            "high": "#006837",
            "nodata": "transparent",
        },
        "limitations": [
            "Indices are unvalidated observations and do not establish crop yield, crop health, forest loss, or deforestation.",
            "Only pixels passing Sentinel-2 scene-classification masking and corridor geometry masking are included.",
            "Historical comparisons require compatible acquisition conditions and spatial support.",
        ],
        "processed_at": datetime.now(timezone.utc).isoformat(),
    })
    return record


def reconcile_cached_grid(record: dict[str, Any]) -> dict[str, Any]:
    """Expose current raster statistics when a stored catalog describes another grid."""
    if record.get("status") != "processed" or record.get("width") is None or record.get("height") is None:
        return record
    with rasterio.open(_cached_raster_path(record, "ndvi")) as dataset:
        if (record["width"], record["height"]) == (dataset.width, dataset.height):
            return record
        grid = (dataset.width, dataset.height, dataset.crs, dataset.transform)
        bounds = _wgs84_bounds(dataset)
        resolution = abs(float(dataset.transform.a))
    statistics = {}
    ndvi_count = 0
    for name in ("ndvi", "evi", "ndmi"):
        with rasterio.open(_cached_raster_path(record, name)) as dataset:
            if (dataset.width, dataset.height, dataset.crs, dataset.transform) != grid:
                raise ValueError("The cached Sentinel-2 index rasters have incompatible grids.")
            array = dataset.read(1, masked=True).astype(np.float32).filled(np.nan)
            values = array[np.isfinite(array)]
            if name == "ndvi":
                ndvi_count = int(values.size)
            if values.size:
                statistics[name] = {
                    "mean": float(values.mean()),
                    "minimum": float(values.min()),
                    "maximum": float(values.max()),
                    "p05": float(np.percentile(values, 5)),
                    "p95": float(np.percentile(values, 95)),
                }
    original = {key: record.get(key) for key in (
        "width", "height", "crs", "resolution_m", "valid_pixel_count", "valid_pixel_percent",
        "corridor_pixel_count", "raster_pixel_percent", "index_statistics", "processor_version", "processed_at",
    )}
    result = dict(record)
    result.update({
        "width": grid[0], "height": grid[1], "crs": str(grid[2]) if grid[2] else None,
        "resolution_m": resolution, "bounds_wgs84": bounds,
        "valid_pixel_count": ndvi_count,
        "raster_pixel_percent": ndvi_count / (grid[0] * grid[1]) * 100,
        "valid_pixel_percent": None, "corridor_pixel_count": None,
        "index_statistics": statistics, "processor_version": None, "processed_at": None,
        "raster_reconciliation": {
            "status": "catalog_grid_mismatch",
            "reason": "The stored catalog describes a different raster grid. Current statistics were read from the GeoTIFFs; their processing provenance and centerline coverage are unknown.",
            "catalog_metadata": original,
        },
    })
    if not ndvi_count:
        result["status"] = "no_usable_pixels"
    return result


def get_observations(river_id: str, refresh: bool = False, limit: int = 8) -> dict[str, Any]:
    records = [record for record in _load_catalog() if record.get("river_id") == river_id]
    if refresh or not records:
        discovered = discover_sentinel2(river_id, limit=limit)
        existing = {record.get("item_id"): record for record in records}
        for record in discovered:
            cached = existing.get(record["item_id"])
            if cached is not None:
                for field in (
                    "acquisition_datetime",
                    "cloud_cover_percent",
                    "footprint",
                    "bbox",
                    "stac_item_url",
                    "assets",
                ):
                    if cached.get(field) in (None, "", {}):
                        cached[field] = record.get(field)
            if (
                record["item_id"] in existing
                and existing[record["item_id"]].get("status") == "processed"
                and existing[record["item_id"]].get("processor_version") == PROCESSOR_VERSION
            ):
                continue
            try:
                processed = process_sentinel2_item(record)
            except (httpx.HTTPError, OSError, rasterio.errors.RasterioError, ValueError, RuntimeError) as error:
                LOGGER.warning("Sentinel-2 processing failed for %s: %s", record["item_id"], error)
                record.update({
                    "status": "retrieval_failed",
                    "error": redact_sensitive_text(str(error)),
                })
                processed = record
            existing[record["item_id"]] = processed
        all_records = [record for record in _load_catalog() if record.get("river_id") != river_id]
        all_records.extend(existing.values())
        _save_catalog(list(all_records))
        records = list(existing.values())
    records = [reconcile_cached_grid(record) for record in records]
    for record in records:
        if record.get("status") == "processed":
            path = DATA_ROOT / river_id / record["item_id"] / "ndvi.tif"
            if path.is_file():
                with rasterio.open(path) as dataset:
                    record["bounds_wgs84"] = _wgs84_bounds(dataset)
    from app.services import vegetation_validation

    assessments = vegetation_validation.list_assessments(river_id)
    for record in records:
        if record.get("status") != "processed":
            continue
        matching = {}
        for assessment in assessments:
            protocol = assessment["protocol"]
            if protocol["item_id"] != record["item_id"]:
                continue
            key = f'{protocol["domain"]}:{protocol["index_name"]}'
            if key in matching:
                continue
            matching[key] = assessment
        for domain in ("agriculture", "forest"):
            for index_name in ("ndvi", "evi", "ndmi"):
                key = f"{domain}:{index_name}"
                if key not in matching:
                    try:
                        _cached_raster_path(record, index_name)
                        reason = "No independent reference assessment has been recorded."
                    except ValueError:
                        reason = "The index raster is unavailable; no assessment can be performed."
                    matching[key] = {
                        "status": "NOT_VALIDATED",
                        "reason": reason,
                        "candidate_acquisition_datetime": record.get("acquisition_datetime"),
                        "candidate_processing_version": record.get("processor_version"),
                        "candidate_source": record.get("source"),
                    }
        record["vegetation_validation"] = matching
    processed_records = [
        record for record in records
        if record.get("status") == "processed" and record.get("acquisition_datetime")
    ]
    historical_comparisons = []
    unique_dates = {
        record.get("acquisition_datetime") for record in processed_records
    }
    if len(unique_dates) >= 2:
        ordered = sorted(
            processed_records,
            key=lambda item: item.get("acquisition_datetime") or "",
        )
        try:
            historical_comparisons.append(
                compare_observations(
                    river_id,
                    ordered[-2]["item_id"],
                    ordered[-1]["item_id"],
                )
            )
        except (OSError, ValueError, rasterio.errors.RasterioError) as error:
            LOGGER.info("No compatible Sentinel-2 historical comparison for %s: %s", river_id, error)
    return {
        "river_id": river_id,
        "source": "Microsoft Planetary Computer",
        "collection": "sentinel-2-l2a",
        "observations": sorted(records, key=lambda item: item.get("acquisition_datetime") or "", reverse=True),
        "historical_comparisons": historical_comparisons,
        "limitations": [
            "Sentinel-2 index outputs are unvalidated and are not crop, yield, forest-loss, or deforestation measurements.",
            "No-data and retrieval failures are reported explicitly; no synthetic fallback is used.",
        ],
    }


def _cached_record(river_id: str, item_id: str) -> dict[str, Any]:
    record = next(
        (
            item for item in _load_catalog()
            if item.get("river_id") == river_id and item.get("item_id") == item_id
        ),
        None,
    )
    if record is None or record.get("status") != "processed":
        raise ValueError("Both Sentinel-2 observations must be processed.")
    return record


def _cached_raster_path(record: dict[str, Any], index_name: str) -> Path:
    relative_path = record.get("output_paths", {}).get(index_name)
    if not isinstance(relative_path, str):
        raise ValueError(f"{index_name.upper()} output is unavailable.")
    path = (DATA_ROOT.parent.parent / relative_path).resolve()
    if DATA_ROOT.resolve() not in path.parents or not path.is_file():
        raise ValueError(f"{index_name.upper()} output is unavailable.")
    return path


def compare_observations(
    river_id: str,
    earlier_item_id: str,
    later_item_id: str,
) -> dict[str, Any]:
    earlier = _cached_record(river_id, earlier_item_id)
    later = _cached_record(river_id, later_item_id)
    if any(reconcile_cached_grid(record).get("raster_reconciliation") for record in (earlier, later)):
        raise ValueError("Historical comparison is unavailable because a catalog record describes a different raster grid.")
    if earlier_item_id == later_item_id:
        raise ValueError("Historical comparison requires two different acquisition products.")
    if earlier.get("acquisition_datetime") == later.get("acquisition_datetime"):
        raise ValueError("Historical comparison requires different acquisition dates.")
    if earlier.get("crs") != later.get("crs") or earlier.get("resolution_m") != later.get("resolution_m"):
        raise ValueError("Sentinel-2 observations have incompatible CRS or resolution.")

    differences: dict[str, dict[str, float | int]] = {}
    common_support: int | None = None
    for index_name in ("ndvi", "evi", "ndmi"):
        with rasterio.open(_cached_raster_path(earlier, index_name)) as earlier_dataset:
            earlier_array = earlier_dataset.read(1).astype(np.float32)
            earlier_valid = earlier_array != earlier_dataset.nodata
            with rasterio.open(_cached_raster_path(later, index_name)) as later_dataset:
                later_array = np.full(earlier_array.shape, np.nan, dtype=np.float32)
                reproject(
                    source=rasterio.band(later_dataset, 1),
                    destination=later_array,
                    src_transform=later_dataset.transform,
                    src_crs=later_dataset.crs,
                    dst_transform=earlier_dataset.transform,
                    dst_crs=earlier_dataset.crs,
                    resampling=Resampling.bilinear,
                    src_nodata=later_dataset.nodata,
                    dst_nodata=np.nan,
                )
        common = earlier_valid & np.isfinite(later_array)
        if common_support is None:
            common_support = int(common.sum())
        elif common_support != int(common.sum()):
            raise ValueError("Index rasters do not provide identical valid support.")
        if common_support < 10:
            raise ValueError("Historical comparison has insufficient common valid support.")
        difference = later_array[common] - earlier_array[common]
        differences[index_name] = {
            "common_valid_pixel_count": int(common.sum()),
            "mean_difference": float(difference.mean()),
            "minimum_difference": float(difference.min()),
            "maximum_difference": float(difference.max()),
        }

    earlier_count = int(earlier.get("valid_pixel_count") or 0)
    return {
        "river_id": river_id,
        "earlier_item_id": earlier_item_id,
        "later_item_id": later_item_id,
        "earlier_acquisition_datetime": earlier.get("acquisition_datetime"),
        "later_acquisition_datetime": later.get("acquisition_datetime"),
        "interval_days": (
            datetime.fromisoformat(later["acquisition_datetime"].replace("Z", "+00:00"))
            - datetime.fromisoformat(earlier["acquisition_datetime"].replace("Z", "+00:00"))
        ).total_seconds() / 86400,
        "common_valid_pixel_count": common_support,
        "common_support_percent_of_earlier": common_support / earlier_count * 100 if earlier_count else 0,
        "indices": differences,
        "status": "unvalidated_difference",
        "limitations": [
            "Differences are unvalidated index changes, not confirmed crop failure, deforestation, degradation, or environmental change.",
            "Only common valid pixels are compared after reprojection to the earlier observation grid.",
        ],
    }
