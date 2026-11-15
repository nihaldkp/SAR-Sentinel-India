"""Windowed, reproducible Sentinel-2 vegetation summaries for river-side zones."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import math
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask, geometry_window
from rasterio.io import MemoryFile
from rasterio.transform import Affine
from rasterio.warp import reproject, transform_bounds, transform_geom
from rasterio.windows import Window
from rasterio.vrt import WarpedVRT
from shapely.geometry import shape

from app.redaction import redact_sensitive_text
from app.services import acquisitions, sentinel2
from app.services.rivers import RIVER_CATALOG

LOGGER = logging.getLogger(__name__)
DATA_ROOT = Path(__file__).resolve().parents[1] / "data" / "forest_monitoring"
PROCESSOR_VERSION = "forest-s2-zones-1.3"
DEFAULT_ZONE_DISTANCES_M = [500, 1000, 3000, 5000]
ALLOWED_SCL_CLASSES = {4, 5}
WORLD_COVER_DATASETS = {
    "esa-worldcover-2021-v200": {
        "name": "ESA WorldCover 2021 v200",
        "year": 2021,
        "resolution_m": 10,
        "source_url": "https://esa-worldcover.org/en/data-access",
        "license": "CC BY 4.0",
        "tree_cover_class": 10,
    }
}
WORLD_COVER_CLASSES = {10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100}
MAX_REFERENCE_BYTES = 100 * 1024 * 1024
MAX_REFERENCE_PIXELS = 80_000_000
BLOCK_SIZE = 512
MAX_ANALYSIS_PIXELS = 12_000_000
MIN_FREE_BYTES = 256 * 1024 * 1024
_PROCESS_LOCK = threading.Lock()


def validate_zone_distances(distances: list[int] | None) -> list[int]:
    result = list(DEFAULT_ZONE_DISTANCES_M if distances is None else distances)
    if not 1 <= len(result) <= 6:
        raise ValueError("Provide between one and six increasing zone distances.")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in result):
        raise ValueError("Zone distances must be whole numbers of metres.")
    if any(value <= 0 or value > 5000 for value in result):
        raise ValueError("Zone distances must be between 1 and 5,000 metres.")
    if result != sorted(set(result)):
        raise ValueError("Zone distances must be unique and strictly increasing.")
    return result


def _river_geometry(river_id: str) -> dict[str, Any]:
    river = next((item for item in RIVER_CATALOG if item.id == river_id), None)
    if river is None:
        raise ValueError(f"Unsupported river_id: {river_id}")
    return river.centerline.model_dump()


def _catalog_record(river_id: str, item_id: str) -> dict[str, Any]:
    record = next(
        (
            item for item in sentinel2._load_catalog()
            if item.get("river_id") == river_id and item.get("item_id") == item_id
        ),
        None,
    )
    if record is None:
        raise FileNotFoundError(f"Sentinel-2 item {item_id} is not in the local optical catalog.")
    if not isinstance(record.get("assets"), dict) or not all(
        record["assets"].get(name) for name in ("B02", "B04", "B08", "B11", "SCL")
    ):
        raise ValueError("The Sentinel-2 item does not have all required L2A assets.")
    return record


def _asset_identity(href: str) -> str:
    parts = urlsplit(href)
    if parts.scheme != "https" or parts.hostname != "sentinel2l2a01.blob.core.windows.net":
        raise ValueError("The optical asset host is not an approved Sentinel-2 source.")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _public_url(href: str | None) -> str | None:
    if not href:
        return None
    parts = urlsplit(href)
    if parts.scheme != "https" or not parts.hostname:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _signed_assets(record: dict[str, Any]) -> dict[str, str]:
    with httpx.Client() as client:
        token = sentinel2._planetary_computer_token(client)
    return {
        name: sentinel2._sign_href(_asset_identity(href), token)
        for name, href in record["assets"].items()
        if name in {"B02", "B04", "B08", "B11", "SCL"}
    }


def _hash_json(value: Any) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _analysis_id(record: dict[str, Any], distances: list[int]) -> str:
    identity = {
        "river_id": record["river_id"],
        "item_id": record["item_id"],
        "acquisition_datetime": record.get("acquisition_datetime"),
        "assets": {
            name: _asset_identity(href)
            for name, href in sorted(record["assets"].items())
            if name in {"B02", "B04", "B08", "B11", "SCL"}
        },
        "river_geometry": _river_geometry(record["river_id"]),
        "zone_distances_m": distances,
        "processor_version": PROCESSOR_VERSION,
    }
    return _hash_json(identity)


def _analysis_row(analysis_id: str) -> dict[str, Any] | None:
    with acquisitions._catalog_connection() as connection:
        row = connection.execute(
            "SELECT * FROM forest_analyses WHERE analysis_id=?",
            (analysis_id,),
        ).fetchone()
    return dict(row) if row else None


def _start_analysis(analysis_id: str, river_id: str, item_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with acquisitions._catalog_connection() as connection:
        connection.execute(
            """
            INSERT INTO forest_analyses (
                analysis_id, river_id, item_id, status, created_at, updated_at
            ) VALUES (?, ?, ?, 'running', ?, ?)
            ON CONFLICT(analysis_id) DO UPDATE SET
                status='running', output_directory=NULL, error_message=NULL, updated_at=excluded.updated_at
            """,
            (analysis_id, river_id, item_id, now, now),
        )
        connection.commit()


def _finish_analysis(
    analysis_id: str,
    *,
    status: str,
    output_directory: str | None = None,
    error_message: str | None = None,
) -> None:
    with acquisitions._catalog_connection() as connection:
        connection.execute(
            """
            UPDATE forest_analyses
            SET status=?, output_directory=?, error_message=?, updated_at=?
            WHERE analysis_id=?
            """,
            (
                status,
                output_directory,
                redact_sensitive_text(error_message)[:2000] if error_message else None,
                datetime.now(timezone.utc).isoformat(),
                analysis_id,
            ),
        )
        connection.commit()


def _output_directory(analysis_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{64}", analysis_id):
        raise FileNotFoundError("Forest analysis was not found.")
    row = _analysis_row(analysis_id)
    if row is None or row["status"] not in {"completed", "no_data"} or not row["output_directory"]:
        raise FileNotFoundError("Forest analysis output is not available.")
    directory = (DATA_ROOT / row["output_directory"]).resolve()
    if DATA_ROOT.resolve() not in directory.parents:
        raise ValueError("Forest analysis output path is invalid.")
    return directory


def get_analysis(analysis_id: str) -> dict[str, Any]:
    path = _output_directory(analysis_id) / "summary.json"
    if not path.is_file():
        raise FileNotFoundError("Forest analysis summary is unavailable.")
    return json.loads(path.read_text(encoding="utf-8"))


def get_output_path(analysis_id: str, filename: str) -> Path:
    if filename not in {"zones.geojson", "stats.csv", "ndvi.tif", "evi.tif", "ndmi.tif"}:
        raise FileNotFoundError("Forest analysis output is not available.")
    path = _output_directory(analysis_id) / filename
    if not path.is_file():
        raise FileNotFoundError("Forest analysis output is not available.")
    return path


def _validate_grid(dataset: rasterio.DatasetReader) -> tuple[float, float]:
    if dataset.crs is None or not dataset.crs.is_projected:
        raise ValueError("Sentinel-2 analysis requires a projected source CRS.")
    if dataset.crs.linear_units.casefold() not in {"metre", "meter", "meters", "metres"}:
        raise ValueError("Sentinel-2 analysis requires a projected CRS measured in metres.")
    transform = dataset.transform
    if not math.isclose(transform.b, 0, abs_tol=1e-9) or not math.isclose(transform.d, 0, abs_tol=1e-9):
        raise ValueError("Rotated Sentinel-2 source grids are not supported.")
    x_resolution, y_resolution = abs(transform.a), abs(transform.e)
    if x_resolution <= 0 or y_resolution <= 0 or not math.isclose(x_resolution, y_resolution, rel_tol=1e-6):
        raise ValueError("Sentinel-2 analysis requires square source pixels.")
    return x_resolution, y_resolution


def _windowed_values(
    dataset: rasterio.DatasetReader,
    window: Window,
    target_transform: Affine,
    target_crs,
    shape_2d: tuple[int, int],
) -> np.ndarray:
    output = np.zeros(shape_2d, dtype=np.float32)
    reproject(
        source=rasterio.band(dataset, 1),
        destination=output,
        src_transform=dataset.transform,
        src_crs=dataset.crs,
        src_nodata=dataset.nodata if dataset.nodata is not None else 0,
        dst_transform=target_transform,
        dst_crs=target_crs,
        dst_nodata=0,
        resampling=Resampling.bilinear,
    )
    return output


def _windowed_scl(
    dataset: rasterio.DatasetReader,
    window: Window,
    target_transform: Affine,
    target_crs,
    shape_2d: tuple[int, int],
) -> np.ndarray:
    output = np.zeros(shape_2d, dtype=np.uint8)
    reproject(
        source=rasterio.band(dataset, 1),
        destination=output,
        src_transform=dataset.transform,
        src_crs=dataset.crs,
        src_nodata=dataset.nodata if dataset.nodata is not None else 0,
        dst_transform=target_transform,
        dst_crs=target_crs,
        dst_nodata=0,
        resampling=Resampling.nearest,
    )
    return output


def _windowed_validity(
    dataset: rasterio.DatasetReader,
    target_transform: Affine,
    target_crs,
    shape_2d: tuple[int, int],
) -> np.ndarray:
    if dataset.crs != target_crs:
        raise ValueError("Sentinel-2 source bands do not share the B11 CRS.")
    west, south, east, north = rasterio.transform.array_bounds(
        shape_2d[0], shape_2d[1], target_transform,
    )
    source_window = rasterio.windows.from_bounds(
        west, south, east, north, transform=dataset.transform,
    ).round_offsets().round_lengths()
    try:
        source_window = source_window.intersection(
            Window(0, 0, dataset.width, dataset.height)
        )
    except rasterio.errors.WindowError:
        return np.zeros(shape_2d, dtype=bool)
    if source_window.width <= 0 or source_window.height <= 0:
        return np.zeros(shape_2d, dtype=bool)
    source_mask = dataset.read_masks(1, window=source_window)
    output = np.zeros(shape_2d, dtype=np.uint8)
    reproject(
        source=source_mask,
        destination=output,
        src_transform=dataset.window_transform(source_window),
        src_crs=dataset.crs,
        dst_transform=target_transform,
        dst_crs=target_crs,
        src_nodata=0,
        dst_nodata=0,
        resampling=Resampling.nearest,
    )
    return output > 0


def _new_accumulator() -> dict[str, float | int]:
    return {"count": 0, "sum": 0.0, "sum_squares": 0.0, "minimum": math.inf, "maximum": -math.inf}


def _accumulate(accumulator: dict[str, float | int], values: np.ndarray) -> None:
    if values.size == 0:
        return
    selected = values.astype(np.float64, copy=False)
    accumulator["count"] += int(selected.size)
    accumulator["sum"] += float(selected.sum(dtype=np.float64))
    accumulator["sum_squares"] += float(np.square(selected).sum(dtype=np.float64))
    accumulator["minimum"] = min(float(accumulator["minimum"]), float(selected.min()))
    accumulator["maximum"] = max(float(accumulator["maximum"]), float(selected.max()))


def _finalize_stats(accumulator: dict[str, float | int]) -> dict[str, float | int | None]:
    count = int(accumulator["count"])
    if not count:
        return {"valid_pixel_count": 0, "mean": None, "standard_deviation": None, "minimum": None, "maximum": None}
    mean = float(accumulator["sum"]) / count
    variance = max(0.0, float(accumulator["sum_squares"]) / count - mean * mean)
    return {
        "valid_pixel_count": count,
        "mean": mean,
        "standard_deviation": math.sqrt(variance),
        "minimum": float(accumulator["minimum"]),
        "maximum": float(accumulator["maximum"]),
    }


def _write_geojson(path: Path, features: list[dict[str, Any]]) -> None:
    payload = {
        "type": "FeatureCollection",
        "name": "Sentinel-2 river-side analysis zones",
        "source": "OpenStreetMap river centerline",
        "features": features,
    }
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def _write_csv(path: Path, zones: list[dict[str, Any]]) -> None:
    fields = [
        "zone_id", "inner_distance_m", "outer_distance_m", "zone_area_km2",
        "raster_covered_area_km2", "valid_area_km2", "raster_coverage_percent",
        "valid_data_coverage_percent", "clear_scl_pixel_count", "valid_pixel_count",
    ]
    for index in ("ndvi", "evi", "ndmi"):
        fields.extend(f"{index}_{field}" for field in (
            "valid_pixel_count", "mean", "standard_deviation", "minimum", "maximum"
        ))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for zone in zones:
            row = {key: zone.get(key) for key in fields if not key.startswith(("ndvi_", "evi_", "ndmi_"))}
            for index in ("ndvi", "evi", "ndmi"):
                row.update({
                    f"{index}_{key}": zone[index].get(key)
                    for key in ("valid_pixel_count", "mean", "standard_deviation", "minimum", "maximum")
                })
            writer.writerow(row)


def _observations_for_river(river_id: str) -> list[dict[str, Any]]:
    return [
        item for item in sentinel2._load_catalog()
        if item.get("river_id") == river_id
        and item.get("status") == "processed"
        and item.get("acquisition_datetime")
    ]


def _process(
    record: dict[str, Any],
    distances: list[int],
    analysis_id: str,
    output_directory: Path,
) -> dict[str, Any]:
    line = shape(_river_geometry(record["river_id"]))
    footprint = shape(record["footprint"]) if record.get("footprint") else None
    clipped_line = line.intersection(footprint) if footprint is not None else line
    if clipped_line.is_empty:
        raise ValueError("The selected Sentinel-2 footprint does not overlap the river centerline.")

    assets = _signed_assets(record)
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MULTIRANGE="YES"):
        with rasterio.open(assets["B11"]) as swir_dataset:
            x_resolution, y_resolution = _validate_grid(swir_dataset)
            target_crs = swir_dataset.crs
            projected_line = shape(transform_geom(
                "EPSG:4326", target_crs, clipped_line.__geo_interface__
            ))
            projected_footprint = (
                shape(transform_geom("EPSG:4326", target_crs, footprint.__geo_interface__))
                if footprint is not None else None
            )
            zones: list[dict[str, Any]] = []
            zone_geometries = []
            inner = 0
            for outer in distances:
                outer_geometry = projected_line.buffer(outer)
                inner_geometry = projected_line.buffer(inner) if inner else None
                ring = outer_geometry.difference(inner_geometry) if inner_geometry is not None else outer_geometry
                if ring.is_empty or not ring.is_valid or ring.area <= 0:
                    raise ValueError(f"River-side zone {inner}-{outer} m is empty or invalid.")
                zone_geometries.append(ring)
                zones.append({
                    "zone_id": f"{inner}-{outer}m",
                    "inner_distance_m": inner,
                    "outer_distance_m": outer,
                    "zone_area_m2": float(ring.area),
                    "total_pixel_count": 0,
                    "clear_scl_pixel_count": 0,
                    "valid_pixel_count": 0,
                    "index_accumulators": {
                        index: _new_accumulator() for index in ("ndvi", "evi", "ndmi")
                    },
                })
                inner = outer

            outer_geometry = zone_geometries[-1]
            try:
                source_window = geometry_window(
                    swir_dataset,
                    [outer_geometry.__geo_interface__],
                    boundless=False,
                ).round_offsets().round_lengths()
            except rasterio.errors.WindowError as error:
                raise ValueError("The outer river-side zone does not intersect the Sentinel-2 raster.") from error
            source_window = source_window.intersection(
                Window(0, 0, swir_dataset.width, swir_dataset.height)
            )
            width, height = int(source_window.width), int(source_window.height)
            if width <= 0 or height <= 0:
                raise ValueError("The outer river-side zone has no raster support.")
            if width * height > MAX_ANALYSIS_PIXELS:
                raise ValueError(
                    f"The requested raster window exceeds the {MAX_ANALYSIS_PIXELS:,}-pixel processing limit."
                )
            raster_transform = swir_dataset.window_transform(source_window)
            pixel_area_m2 = x_resolution * y_resolution
            profiles = {
                "driver": "GTiff",
                "width": width,
                "height": height,
                "count": 1,
                "dtype": "float32",
                "crs": target_crs,
                "transform": raster_transform,
                "nodata": -9999.0,
                "compress": "deflate",
                "predictor": 3,
                "tiled": True,
                "blockxsize": 256,
                "blockysize": 256,
            }
            raster_paths = {
                name: output_directory / f"{name}.tif"
                for name in ("ndvi", "evi", "ndmi")
            }
            total_blocks = math.ceil(width / BLOCK_SIZE) * math.ceil(height / BLOCK_SIZE)
            completed_blocks = 0
            with rasterio.open(assets["SCL"]) as scl_dataset, \
                    rasterio.open(assets["B02"]) as blue_dataset, \
                    rasterio.open(assets["B04"]) as red_dataset, \
                    rasterio.open(assets["B08"]) as nir_dataset, \
                    rasterio.open(raster_paths["ndvi"], "w", **profiles) as ndvi_output, \
                    rasterio.open(raster_paths["evi"], "w", **profiles) as evi_output, \
                    rasterio.open(raster_paths["ndmi"], "w", **profiles) as ndmi_output:
                index_outputs = {
                    "ndvi": ndvi_output,
                    "evi": evi_output,
                    "ndmi": ndmi_output,
                }
                for row_offset in range(0, height, BLOCK_SIZE):
                    block_height = min(BLOCK_SIZE, height - row_offset)
                    for column_offset in range(0, width, BLOCK_SIZE):
                        block_width = min(BLOCK_SIZE, width - column_offset)
                        output_window = Window(column_offset, row_offset, block_width, block_height)
                        source_block = Window(
                            source_window.col_off + column_offset,
                            source_window.row_off + row_offset,
                            block_width,
                            block_height,
                        )
                        target_transform = swir_dataset.window_transform(source_block)
                        shape_2d = (block_height, block_width)
                        swir = swir_dataset.read(1, window=source_block, masked=True)
                        scl = _windowed_scl(
                            scl_dataset, source_block, target_transform, target_crs, shape_2d
                        )
                        clear = (
                            np.isin(scl, list(ALLOWED_SCL_CLASSES))
                            & _windowed_validity(
                                scl_dataset, target_transform, target_crs, shape_2d
                            )
                        )
                        blue = _windowed_values(
                            blue_dataset, source_block, target_transform, target_crs, shape_2d
                        )
                        red = _windowed_values(
                            red_dataset, source_block, target_transform, target_crs, shape_2d
                        )
                        nir = _windowed_values(
                            nir_dataset, source_block, target_transform, target_crs, shape_2d
                        )
                        swir_values = swir.filled(0).astype(np.float32, copy=False)
                        reflectance_valid = (
                            ~np.ma.getmaskarray(swir)
                            & clear
                            & np.isfinite(blue)
                            & np.isfinite(red)
                            & np.isfinite(nir)
                            & np.isfinite(swir_values)
                            & _windowed_validity(
                                blue_dataset, target_transform, target_crs, shape_2d
                            )
                            & _windowed_validity(
                                red_dataset, target_transform, target_crs, shape_2d
                            )
                            & _windowed_validity(
                                nir_dataset, target_transform, target_crs, shape_2d
                            )
                            & (blue > 0)
                            & (red > 0)
                            & (nir > 0)
                            & (swir_values > 0)
                        )
                        indices = sentinel2.calculate_indices(
                            blue, red, nir, swir_values, reflectance_valid
                        )
                        union_zone_mask = np.zeros(shape_2d, dtype=bool)
                        for zone_geometry, zone in zip(zone_geometries, zones):
                            zone_mask = geometry_mask(
                                [zone_geometry.__geo_interface__],
                                out_shape=shape_2d,
                                transform=target_transform,
                                invert=True,
                            )
                            if projected_footprint is not None:
                                zone_mask &= geometry_mask(
                                    [projected_footprint.__geo_interface__],
                                    out_shape=shape_2d,
                                    transform=target_transform,
                                    invert=True,
                                )
                            union_zone_mask |= zone_mask
                            zone["total_pixel_count"] += int(zone_mask.sum())
                            zone["clear_scl_pixel_count"] += int((zone_mask & clear).sum())
                            zone_valid = zone_mask & reflectance_valid
                            zone["valid_pixel_count"] += int(zone_valid.sum())
                            for name, array in indices.items():
                                _accumulate(zone["index_accumulators"][name], array[zone_valid])

                        for name, output in index_outputs.items():
                            raster_values = np.where(
                                union_zone_mask & np.isfinite(indices[name]),
                                indices[name],
                                -9999.0,
                            ).astype(np.float32)
                            output.write(raster_values, 1, window=output_window)
                        completed_blocks += 1
                        if completed_blocks == 1 or completed_blocks == total_blocks or completed_blocks % 16 == 0:
                            LOGGER.info(
                                "Forest analysis %s processed block %d of %d",
                                analysis_id[:12],
                                completed_blocks,
                                total_blocks,
                            )

    features: list[dict[str, Any]] = []
    zone_results: list[dict[str, Any]] = []
    for zone_geometry, zone in zip(zone_geometries, zones):
        metrics = {}
        for index in ("ndvi", "evi", "ndmi"):
            metrics[index] = _finalize_stats(zone["index_accumulators"][index])
        total_pixels = int(zone["total_pixel_count"])
        valid_pixels = int(zone["valid_pixel_count"])
        covered_area_m2 = total_pixels * pixel_area_m2
        valid_area_m2 = valid_pixels * pixel_area_m2
        result = {
            "zone_id": zone["zone_id"],
            "inner_distance_m": zone["inner_distance_m"],
            "outer_distance_m": zone["outer_distance_m"],
            "zone_area_km2": zone["zone_area_m2"] / 1_000_000,
            "raster_covered_area_km2": covered_area_m2 / 1_000_000,
            "valid_area_km2": valid_area_m2 / 1_000_000,
            "raster_coverage_percent": min(100.0, covered_area_m2 / zone["zone_area_m2"] * 100),
            "valid_data_coverage_percent": (
                valid_pixels / total_pixels * 100 if total_pixels else None
            ),
            "clear_scl_pixel_count": int(zone["clear_scl_pixel_count"]),
            "valid_pixel_count": valid_pixels,
            "scl_masked_pixel_count": max(0, total_pixels - int(zone["clear_scl_pixel_count"])),
            **metrics,
        }
        zone_results.append(result)
        features.append({
            "type": "Feature",
            "properties": {
                "zone_id": zone["zone_id"],
                "inner_distance_m": zone["inner_distance_m"],
                "outer_distance_m": zone["outer_distance_m"],
                "zone_area_km2": result["zone_area_km2"],
            },
            "geometry": transform_geom(
                target_crs, "EPSG:4326", zone_geometry.__geo_interface__
            ),
        })

    acquisition_times = {
        item.get("acquisition_datetime")
        for item in _observations_for_river(record["river_id"])
    }
    temporal_status = "available_for_compatible_comparison" if len(acquisition_times) >= 2 else "insufficient_observations"
    relationship_status = "insufficient_temporal_overlap"
    index_stats = {
        name: any(zone[name]["valid_pixel_count"] > 0 for zone in zone_results)
        for name in ("ndvi", "evi", "ndmi")
    }
    status = "completed" if any(index_stats.values()) else "no_data"
    if status == "no_data":
        for path in raster_paths.values():
            path.unlink(missing_ok=True)

    zone_path = output_directory / "zones.geojson"
    csv_path = output_directory / "stats.csv"
    _write_geojson(zone_path, features)
    _write_csv(csv_path, zone_results)
    crs_wgs84_bounds = transform_bounds(
        target_crs,
        "EPSG:4326",
        *rasterio.transform.array_bounds(height, width, raster_transform),
        densify_pts=21,
    )
    output_hashes = {
        path.name: _file_sha256(path)
        for path in [zone_path, csv_path, *raster_paths.values()]
        if path.is_file()
    }
    summary = {
        "schema_version": 1,
        "analysis_id": analysis_id,
        "status": status,
        "river_id": record["river_id"],
        "item_id": record["item_id"],
        "acquisition_datetime": record.get("acquisition_datetime"),
        "source": record.get("source", "Microsoft Planetary Computer"),
        "collection": record.get("collection", "sentinel-2-l2a"),
        "stac_item_url": _public_url(record.get("stac_item_url")),
        "source_footprint_wgs84": record.get("footprint"),
        "cloud_cover_percent": record.get("cloud_cover_percent"),
        "asset_sources": {
            name: _asset_identity(href)
            for name, href in sorted(record["assets"].items())
            if name in {"B02", "B04", "B08", "B11", "SCL"}
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "processor_version": PROCESSOR_VERSION,
        "processing_parameters": {
            "zone_distances_m": distances,
            "target_resolution_m": x_resolution,
            "target_crs": str(target_crs),
            "reflectance_scale_factor": 0.0001,
            "reflectance_resampling": "bilinear to the native 20 m B11 grid",
            "scene_classification_resampling": "nearest",
            "included_scl_classes": sorted(ALLOWED_SCL_CLASSES),
            "excluded_scl_classes": sorted(set(range(12)) - ALLOWED_SCL_CLASSES),
            "valid_mask": "SCL class 4 or 5; finite positive B02/B04/B08/B11 reflectance; valid source-data masks",
            "pixel_inclusion": "pixel center inside projected vector zone",
            "area_method": "pixel count multiplied by projected pixel area",
            "block_size_pixels": BLOCK_SIZE,
            "output_nodata": -9999.0,
        },
        "grid": {
            "crs": str(target_crs),
            "resolution_m": x_resolution,
            "width": width,
            "height": height,
            "transform": list(raster_transform),
            "bounds_wgs84": {
                "west": crs_wgs84_bounds[0],
                "south": crs_wgs84_bounds[1],
                "east": crs_wgs84_bounds[2],
                "north": crs_wgs84_bounds[3],
            },
        },
        "zones": zone_results,
        "tree_cover": {
            "status": "not_available",
            "reason": "No tree-cover reference raster is integrated locally; vegetation indices are not tree-cover measurements.",
        },
        "temporal_change": {
            "status": temporal_status,
            "distinct_processed_acquisition_times": len(acquisition_times),
            "reason": "Compatible multi-date forest-zone rasters are not available." if len(acquisition_times) < 2 else "A compatible, common-support forest-zone comparison has not yet been run.",
        },
        "river_vegetation_relationship": {
            "status": relationship_status,
            "reason": "No temporally matched, spatially compatible forest-zone and river-water observations are available.",
        },
        "uncertainty_and_limitations": [
            "These are spectral vegetation-index summaries, not tree-cover, forest-condition, forest-loss, or deforestation measurements.",
            "The OSM river centerline is a reference geometry, not a verified bank or active channel.",
            "SCL classes 4 and 5 are retained; all other SCL classes are excluded, including water, clouds and cloud shadows.",
            "Valid-data coverage is reported per zone; index values are not independently validated.",
            "A single acquisition cannot separate seasonal variation from persistent change.",
        ],
        "output_sha256": output_hashes,
    }
    (output_directory / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary


def process_item(
    river_id: str,
    item_id: str,
    zone_distances_m: list[int] | None = None,
) -> dict[str, Any]:
    distances = validate_zone_distances(zone_distances_m)
    record = _catalog_record(river_id, item_id)
    analysis_id = _analysis_id(record, distances)
    with _PROCESS_LOCK:
        row = _analysis_row(analysis_id)
        if row and row["status"] in {"completed", "no_data"} and row["output_directory"]:
            try:
                return get_analysis(analysis_id)
            except (FileNotFoundError, ValueError, json.JSONDecodeError):
                pass
        DATA_ROOT.parent.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(DATA_ROOT.parent).free < MIN_FREE_BYTES:
            raise OSError(
                f"Forest output requires at least {MIN_FREE_BYTES // (1024 * 1024)} MB of free space."
            )
        _start_analysis(analysis_id, river_id, item_id)
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        temporary_parent = DATA_ROOT
        try:
            with tempfile.TemporaryDirectory(prefix=f".{analysis_id[:12]}-", dir=temporary_parent) as temp_name:
                temporary_directory = Path(temp_name)
                result = _process(record, distances, analysis_id, temporary_directory)
                output_directory = DATA_ROOT / f"{analysis_id}-{uuid4().hex[:8]}"
                os.replace(temporary_directory, output_directory)
            _finish_analysis(
                analysis_id,
                status=result["status"],
                output_directory=output_directory.name,
            )
            return result
        except Exception as error:
            _finish_analysis(analysis_id, status="failed", error_message=str(error))
            raise


def list_observations(river_id: str) -> dict[str, Any]:
    if river_id not in {river.id for river in RIVER_CATALOG}:
        raise ValueError(f"Unsupported river_id: {river_id}")
    records = [
        {
            "item_id": record.get("item_id"),
            "acquisition_datetime": record.get("acquisition_datetime"),
            "status": record.get("status"),
            "source": record.get("source"),
            "collection": record.get("collection"),
            "crs": record.get("crs"),
            "resolution_m": record.get("resolution_m"),
            "valid_pixel_count": record.get("valid_pixel_count"),
            "bounds_wgs84": record.get("bounds_wgs84"),
            "has_source_assets": bool(
                isinstance(record.get("assets"), dict)
                and all(record["assets"].get(name) for name in ("B02", "B04", "B08", "B11", "SCL"))
            ),
        }
        for record in sentinel2._load_catalog()
        if record.get("river_id") == river_id
    ]
    dates = sorted({
        record["acquisition_datetime"]
        for record in records
        if record["status"] == "processed" and record.get("acquisition_datetime")
    })
    return {
        "river_id": river_id,
        "source": "Microsoft Planetary Computer",
        "collection": "sentinel-2-l2a",
        "observations": sorted(
            records,
            key=lambda item: item.get("acquisition_datetime") or "",
            reverse=True,
        ),
        "distinct_processed_acquisition_times": dates,
        "temporal_change_status": "available_for_compatibility_check" if len(dates) >= 2 else "insufficient_observations",
        "limitations": [
            "The local Sentinel-2 index rasters are centerline-clipped; forest analyses read the original L2A COG assets instead.",
            "Tile counts are not unique landscape coverage; do not sum overlapping tile records as area.",
            "No tree-cover reference raster is integrated.",
        ],
    }


def _reference_directory(reference_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{64}", reference_id):
        raise FileNotFoundError("Forest reference was not found.")
    directory = (DATA_ROOT / "references" / reference_id).resolve()
    if DATA_ROOT.resolve() not in directory.parents:
        raise ValueError("Forest reference path is invalid.")
    return directory


def _register_reference(metadata: dict[str, Any]) -> None:
    reference_id = metadata["reference_id"]
    relative_path = (Path("references") / reference_id / "worldcover.tif").as_posix()
    with acquisitions._catalog_connection() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO forest_reference_imports (
                reference_id, dataset_id, source_sha256, relative_path,
                metadata_json, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                reference_id,
                metadata["dataset_id"],
                metadata["source_sha256"],
                relative_path,
                json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                metadata["imported_at"],
            ),
        )


def _reference_record(reference_id: str) -> dict[str, Any]:
    directory = _reference_directory(reference_id)
    raster_path = directory / "worldcover.tif"
    if not raster_path.is_file():
        raise FileNotFoundError("Forest reference pixels have not been imported.")
    with acquisitions._catalog_connection() as connection:
        row = connection.execute(
            "SELECT relative_path, metadata_json FROM forest_reference_imports WHERE reference_id=?",
            (reference_id,),
        ).fetchone()
    metadata_path = directory / "metadata.json"
    if row is None:
        if not metadata_path.is_file():
            raise FileNotFoundError("Forest reference metadata is unavailable.")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        _register_reference(metadata)
        return metadata
    expected_path = (Path("references") / reference_id / "worldcover.tif").as_posix()
    if row["relative_path"] != expected_path:
        raise ValueError("Forest reference catalog path is invalid.")
    return json.loads(row["metadata_json"])


def get_imported_reference(reference_id: str) -> dict[str, Any]:
    return _reference_record(reference_id)


def import_worldcover_reference(dataset_id: str, content: bytes) -> dict[str, Any]:
    dataset_metadata = WORLD_COVER_DATASETS.get(dataset_id)
    if dataset_metadata is None:
        raise ValueError("The requested forest reference dataset is not supported.")
    if not content or len(content) > MAX_REFERENCE_BYTES:
        raise ValueError(f"Upload a non-empty GeoTIFF no larger than {MAX_REFERENCE_BYTES // (1024 * 1024)} MiB.")
    content_sha256 = hashlib.sha256(content).hexdigest()
    reference_id = hashlib.sha256(
        f"{dataset_id}:{content_sha256}".encode("ascii")
    ).hexdigest()
    directory = _reference_directory(reference_id)
    raster_path = directory / "worldcover.tif"
    metadata_path = directory / "metadata.json"
    if metadata_path.is_file():
        if not raster_path.is_file():
            raise OSError("Imported forest reference metadata exists without its raster.")
        return _reference_record(reference_id)

    with MemoryFile(content) as memory_file:
        with memory_file.open() as dataset:
            if dataset.driver != "GTiff" or dataset.count != 1 or dataset.dtypes != ("uint8",):
                raise ValueError("The reference must be a single-band uint8 GeoTIFF.")
            if dataset.crs is None or dataset.nodata not in {0, 255}:
                raise ValueError("The reference GeoTIFF must have a CRS and NoData value 0 or 255.")
            if dataset.width <= 0 or dataset.height <= 0 or dataset.width * dataset.height > MAX_REFERENCE_PIXELS:
                raise ValueError("The reference raster exceeds the supported pixel limit.")
            source_metadata = {
                "crs": dataset.crs.to_string(),
                "width": dataset.width,
                "height": dataset.height,
                "transform": list(dataset.transform),
                "bounds": list(dataset.bounds),
                "nodata": int(dataset.nodata),
            }

    directory.mkdir(parents=True, exist_ok=True)
    temporary_raster = directory / f".worldcover-{uuid4().hex}.tmp"
    temporary_metadata = directory / f".metadata-{uuid4().hex}.tmp"
    metadata = {
        "reference_id": reference_id,
        "dataset_id": dataset_id,
        **dataset_metadata,
        "status": "pixels_imported",
        "source_sha256": content_sha256,
        "provenance_verification": "user_supplied_not_independently_authenticated",
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "source_raster": source_metadata,
        "raster_filename": "worldcover.tif",
        "limitations": [
            "WorldCover class 10 is tree cover and includes plantations; natural forest and plantations are not distinguished.",
            "WorldCover is partly Sentinel-2-derived and is not independent validation of Sentinel-2 vegetation indices.",
            "The 2021 reference predates the 2026 observation and cannot establish 2026 tree-cover loss or gain.",
        ],
    }
    try:
        temporary_raster.write_bytes(content)
        temporary_metadata.write_text(
            json.dumps(metadata, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary_raster, raster_path)
        os.replace(temporary_metadata, metadata_path)
    finally:
        temporary_raster.unlink(missing_ok=True)
        temporary_metadata.unlink(missing_ok=True)
    _register_reference(metadata)
    return metadata


def list_references() -> dict[str, Any]:
    metadata_only = {
        "id": "esa-worldcover-2021-v200",
        **WORLD_COVER_DATASETS["esa-worldcover-2021-v200"],
        "status": "metadata_only_not_integrated",
        "limitations": [
            "Tree cover includes plantations; natural forest and plantation cannot be distinguished by this class.",
            "WorldCover is partly Sentinel-2-derived and is not independent validation of Sentinel-2 indices.",
            "The 2021 reference predates the 2026 observations and is not evidence of 2026 tree-cover change.",
            "No local WorldCover pixels are currently imported.",
        ],
    }
    imported = []
    with acquisitions._catalog_connection() as connection:
        rows = connection.execute(
            "SELECT reference_id FROM forest_reference_imports ORDER BY imported_at, reference_id"
        ).fetchall()
    for row in rows:
        metadata = _reference_record(row["reference_id"])
        imported.append({
            key: value for key, value in metadata.items()
            if key != "raster_filename"
        })
    return {
        "references": [metadata_only, *imported],
        "tree_cover_statistics_status": (
            "available_after_import" if imported else "not_available"
        ),
    }


def calculate_tree_cover_statistics(
    analysis_id: str,
    reference_id: str,
) -> dict[str, Any]:
    analysis = get_analysis(analysis_id)
    reference = _reference_record(reference_id)
    analysis_directory = _output_directory(analysis_id)
    output_directory = analysis_directory / "tree-cover" / reference_id
    summary_path = output_directory / "summary.json"
    raster_path = output_directory / "tree-cover.tif"
    if summary_path.is_file():
        cached = json.loads(summary_path.read_text(encoding="utf-8"))
        if (
            cached.get("source_sha256") == reference["source_sha256"]
            and (cached.get("status") == "no_data" or raster_path.is_file())
        ):
            return cached

    zones_geojson = json.loads(
        (analysis_directory / "zones.geojson").read_text(encoding="utf-8")
    )
    zones = []
    for feature in zones_geojson.get("features", []):
        properties = feature.get("properties", {})
        geometry = shape(transform_geom("EPSG:4326", "EPSG:6933", feature["geometry"]))
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError("The forest analysis contains an invalid distance-zone geometry.")
        zones.append({
            "zone_id": properties["zone_id"],
            "geometry": geometry,
            "area_m2": geometry.area,
            "covered_pixel_count": 0,
            "valid_pixel_count": 0,
            "tree_pixel_count": 0,
        })
    if not zones:
        raise ValueError("The forest analysis has no distance zones.")

    source_path = _reference_directory(reference_id) / "worldcover.tif"
    with rasterio.open(source_path) as source:
        west, south, east, north = transform_bounds(
            source.crs, "EPSG:6933", *source.bounds, densify_pts=21,
        )
        left = math.floor(west / 10) * 10
        bottom = math.floor(south / 10) * 10
        right = math.ceil(east / 10) * 10
        top = math.ceil(north / 10) * 10
        target_width = max(1, math.ceil((right - left) / 10))
        target_height = max(1, math.ceil((top - bottom) / 10))
        with WarpedVRT(
            source,
            crs="EPSG:6933",
            transform=rasterio.transform.from_origin(left, top, 10, 10),
            width=target_width,
            height=target_height,
            src_nodata=source.nodata,
            nodata=255,
            dtype="uint8",
            resampling=Resampling.nearest,
        ) as reference_grid:
            try:
                window = geometry_window(
                    reference_grid,
                    [zones[-1]["geometry"].__geo_interface__],
                    boundless=False,
                ).round_offsets().round_lengths()
            except rasterio.errors.WindowError as error:
                raise ValueError("The imported reference does not overlap the analysis zones.") from error
            window = window.intersection(
                Window(0, 0, reference_grid.width, reference_grid.height)
            )
            width, height = int(window.width), int(window.height)
            if width <= 0 or height <= 0:
                raise ValueError("The imported reference does not overlap the analysis zones.")
            if width * height > MAX_ANALYSIS_PIXELS:
                raise ValueError(
                    f"The reference-zone window exceeds the {MAX_ANALYSIS_PIXELS:,}-pixel processing limit."
                )
            output_directory.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=f".{reference_id[:12]}-", dir=output_directory.parent
            ) as temporary_directory:
                temporary_root = Path(temporary_directory)
                temporary_raster = temporary_root / "tree-cover.tif"
                transform = reference_grid.window_transform(window)
                profile = {
                    "driver": "GTiff",
                    "width": width,
                    "height": height,
                    "count": 1,
                    "dtype": "uint8",
                    "crs": "EPSG:6933",
                    "transform": transform,
                    "nodata": 255,
                    "compress": "deflate",
                }
                with rasterio.open(temporary_raster, "w", **profile) as output:
                    for row_offset in range(0, height, BLOCK_SIZE):
                        block_height = min(BLOCK_SIZE, height - row_offset)
                        for column_offset in range(0, width, BLOCK_SIZE):
                            block_width = min(BLOCK_SIZE, width - column_offset)
                            block_window = Window(
                                window.col_off + column_offset,
                                window.row_off + row_offset,
                                block_width,
                                block_height,
                            )
                            block_transform = reference_grid.window_transform(block_window)
                            values = reference_grid.read(1, window=block_window, masked=True)
                            classes = values.filled(255).astype(np.uint8, copy=False)
                            valid_classes = (
                                ~np.ma.getmaskarray(values)
                                & np.isin(classes, list(WORLD_COVER_CLASSES))
                            )
                            result = np.full(classes.shape, 255, dtype=np.uint8)
                            for zone in zones:
                                inside = geometry_mask(
                                    [zone["geometry"].__geo_interface__],
                                    out_shape=classes.shape,
                                    transform=block_transform,
                                    invert=True,
                                )
                                selected = inside & valid_classes
                                zone["covered_pixel_count"] += int(np.count_nonzero(inside))
                                zone["valid_pixel_count"] += int(np.count_nonzero(selected))
                                zone["tree_pixel_count"] += int(
                                    np.count_nonzero(selected & (classes == 10))
                                )
                                result[selected] = 0
                                result[selected & (classes == 10)] = 1
                            output.write(
                                result,
                                1,
                                window=Window(
                                    column_offset,
                                    row_offset,
                                    block_width,
                                    block_height,
                                ),
                            )

                zone_statistics = []
                pixel_area_m2 = abs(transform.a * transform.e)
                for zone in zones:
                    covered = zone["covered_pixel_count"]
                    valid = zone["valid_pixel_count"]
                    tree = zone["tree_pixel_count"]
                    zone_statistics.append({
                        "zone_id": zone["zone_id"],
                        "zone_area_km2": zone["area_m2"] / 1_000_000,
                        "raster_coverage_percent": min(
                            100.0,
                            covered * pixel_area_m2 / zone["area_m2"] * 100,
                        ) if zone["area_m2"] else None,
                        "valid_data_coverage_percent": (
                            valid / covered * 100 if covered else None
                        ),
                        "valid_pixel_count": valid,
                        "tree_cover_pixel_count": tree,
                        "tree_cover_area_km2": tree * pixel_area_m2 / 1_000_000,
                        "tree_cover_percent_of_valid_area": (
                            tree / valid * 100 if valid else None
                        ),
                    })
                summary = {
                    "analysis_id": analysis_id,
                    "river_id": analysis["river_id"],
                    "reference_id": reference_id,
                    "dataset_id": reference["dataset_id"],
                    "dataset_name": reference["name"],
                    "reference_year": reference["year"],
                    "source_sha256": reference["source_sha256"],
                    "source_crs": reference["source_raster"]["crs"],
                    "analysis_crs": "EPSG:6933",
                    "resolution_m": 10,
                    "tree_cover_class": 10,
                    "tree_cover_label": "WorldCover tree cover; plantations not separable",
                    "status": (
                        "completed"
                        if any(zone["valid_pixel_count"] for zone in zones)
                        else "no_data"
                    ),
                    "zones": zone_statistics,
                    "output": {
                        "filename": "tree-cover.tif" if any(zone["valid_pixel_count"] for zone in zones) else None,
                        "width": width,
                        "height": height,
                        "transform": list(transform),
                        "crs": "EPSG:6933",
                        "bounds_wgs84": dict(zip(
                            ("west", "south", "east", "north"),
                            transform_bounds(
                                "EPSG:6933",
                                "EPSG:4326",
                                *rasterio.transform.array_bounds(height, width, transform),
                                densify_pts=21,
                            ),
                        )),
                        "nodata": 255,
                        "class_values": {"other_valid_worldcover_class": 0, "tree_cover": 1, "nodata": 255},
                    },
                    "limitations": reference["limitations"] + [
                        "Area statistics represent imported raster pixels inside the raster footprint; uncovered zone area is reported separately.",
                        "This classification is not independently validated and does not establish tree-cover loss or gain.",
                    ],
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
                temporary_csv = temporary_root / "stats.csv"
                with temporary_csv.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=list(zone_statistics[0]),
                    )
                    writer.writeheader()
                    writer.writerows(zone_statistics)
                summary["output_sha256"] = {
                    "stats.csv": _file_sha256(temporary_csv),
                }
                if summary["status"] == "completed":
                    summary["output_sha256"]["tree-cover.tif"] = _file_sha256(temporary_raster)
                (temporary_root / "summary.json").write_text(
                    json.dumps(summary, sort_keys=True, separators=(",", ":")),
                    encoding="utf-8",
                )
                final_directory = output_directory
                final_directory.mkdir(parents=True, exist_ok=True)
                if summary["status"] == "completed":
                    os.replace(temporary_raster, final_directory / "tree-cover.tif")
                os.replace(temporary_csv, final_directory / "stats.csv")
                os.replace(temporary_root / "summary.json", final_directory / "summary.json")
    return summary


def get_tree_cover_summary(analysis_id: str, reference_id: str) -> dict[str, Any]:
    path = _output_directory(analysis_id) / "tree-cover" / reference_id / "summary.json"
    if not re.fullmatch(r"[a-f0-9]{64}", reference_id) or not path.is_file():
        raise FileNotFoundError("Tree-cover statistics are not available.")
    return json.loads(path.read_text(encoding="utf-8"))


def get_tree_cover_output_path(
    analysis_id: str,
    reference_id: str,
    filename: str,
) -> Path:
    if filename not in {"tree-cover.tif", "stats.csv"} or not re.fullmatch(r"[a-f0-9]{64}", reference_id):
        raise FileNotFoundError("Tree-cover output is not available.")
    path = _output_directory(analysis_id) / "tree-cover" / reference_id / filename
    if not path.is_file():
        raise FileNotFoundError("Tree-cover output is not available.")
    return path


def render_tree_cover_preview(
    analysis_id: str,
    reference_id: str,
) -> tuple[bytes, dict[str, float]]:
    path = get_tree_cover_output_path(analysis_id, reference_id, "tree-cover.tif")
    with rasterio.open(path) as dataset:
        scale = min(1.0, 512 / max(dataset.width, dataset.height))
        width = max(1, round(dataset.width * scale))
        height = max(1, round(dataset.height * scale))
        source = dataset.read(1, masked=True).filled(255).astype(np.uint8, copy=False)
        preview = np.full((height, width), 255, dtype=np.uint8)
        reproject(
            source=source,
            destination=preview,
            src_transform=dataset.transform,
            src_crs=dataset.crs,
            src_nodata=255,
            dst_transform=rasterio.transform.from_bounds(
                *dataset.bounds, width, height,
            ),
            dst_crs=dataset.crs,
            dst_nodata=255,
            resampling=Resampling.nearest,
        )
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        valid = preview != 255
        tree_cover = preview == 1
        rgba[valid] = (220, 173, 79, 100)
        rgba[tree_cover] = (38, 135, 89, 205)
        bounds = transform_bounds(dataset.crs, "EPSG:4326", *dataset.bounds)
    with MemoryFile() as memory_file:
        with memory_file.open(
            driver="PNG",
            height=height,
            width=width,
            count=4,
            dtype="uint8",
        ) as image:
            image.write(np.moveaxis(rgba, 2, 0))
        return memory_file.read(), {
            "west": bounds[0],
            "south": bounds[1],
            "east": bounds[2],
            "north": bounds[3],
        }


def render_preview(analysis_id: str, index_name: str) -> tuple[bytes, tuple[float, float, float, float]]:
    if index_name not in {"ndvi", "evi", "ndmi"}:
        raise FileNotFoundError("The requested vegetation index is unavailable.")
    path = get_output_path(analysis_id, f"{index_name}.tif")
    with rasterio.open(path) as dataset:
        bounds = transform_bounds(dataset.crs, "EPSG:3857", *dataset.bounds)
    return sentinel2.render_index_png(path, overview=True), bounds
