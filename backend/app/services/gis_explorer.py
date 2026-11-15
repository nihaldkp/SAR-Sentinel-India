from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds, transform_geom
from shapely.geometry import Point, mapping, shape

from app.services import acquisitions, analysis, forest_monitoring, sentinel2
from app.services.rivers import RIVER_CATALOG

UPLOAD_ROOT = Path(__file__).resolve().parents[1] / "data" / "gis_explorer" / "uploads"
MAX_GEOJSON_BYTES = 10 * 1024 * 1024
MAX_GEOJSON_FEATURES = 50_000
MAX_PREVIEW_SIDE = 512
ALLOWED_RIVERS = {"both", *(river.id for river in RIVER_CATALOG)}
UNAVAILABLE_LAYERS = (
    {
        "layer_id": "river-bank-boundaries",
        "name": "River bank boundaries",
        "category": "Rivers",
        "source": "Local project datasets",
        "message": "Only registered river centerlines are available; bank boundaries are not present.",
    },
    {
        "layer_id": "flood-inundation",
        "name": "Flood / inundation",
        "category": "Hydrology",
        "source": "Local project datasets",
        "message": "No flood or inundation layer is present in the local project catalog.",
    },
    {
        "layer_id": "administrative-boundaries",
        "name": "Administrative boundaries",
        "category": "Reference",
        "source": "Local project datasets",
        "message": "No administrative-boundary dataset is present in the local project catalog.",
    },
)


def _stable_id(identity: str) -> str:
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _reject_json_constant(value: str):
    raise ValueError(f"GeoJSON contains a non-finite numeric constant: {value}.")


def _ensure_upload_table() -> None:
    with acquisitions._catalog_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS gis_user_layers (
                layer_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                file_name TEXT NOT NULL UNIQUE,
                feature_count INTEGER NOT NULL,
                uploaded_at TEXT NOT NULL
            )
            """
        )


def _bounds_wgs84(dataset: rasterio.DatasetReader) -> dict[str, float]:
    west, south, east, north = transform_bounds(
        dataset.crs, "EPSG:4326", *dataset.bounds, densify_pts=21
    )
    return {
        "west": float(west),
        "south": float(south),
        "east": float(east),
        "north": float(north),
    }


def _raster_layer(
    *,
    layer_id: str,
    name: str,
    category: str,
    source: str,
    path: Path,
    provenance: str,
    evidence_status: str = "observed_index",
    river_id: str | None = None,
    date: str | None = None,
    valid_pixel_count: int | None = None,
) -> dict[str, Any]:
    layer: dict[str, Any] = {
        "layer_id": layer_id,
        "name": name,
        "category": category,
        "layer_type": "raster",
        "status": "available",
        "evidence_status": evidence_status,
        "source": source,
        "date": date,
        "river_id": river_id,
        "provenance": provenance,
        "_path": path,
    }
    try:
        with rasterio.open(path) as dataset:
            if dataset.count < 1 or dataset.crs is None:
                raise ValueError("Raster has no band or CRS metadata.")
            crs = dataset.crs
            resolution_m = None
            if crs.is_projected and crs.linear_units.casefold() in {"metre", "meter", "meters", "metres"}:
                resolution_m = float(max(abs(dataset.res[0]), abs(dataset.res[1])))
            layer.update(
                crs=dataset.crs.to_string(),
                resolution_m=resolution_m,
                bounds_wgs84=_bounds_wgs84(dataset),
                width=dataset.width,
                height=dataset.height,
                data_type=dataset.dtypes[0],
                nodata=dataset.nodata,
            )
            preview_bounds_mercator = transform_bounds(
                dataset.crs, "EPSG:3857", *dataset.bounds, densify_pts=21
            )
            if not all(math.isfinite(value) for value in preview_bounds_mercator):
                raise ValueError("Raster bounds cannot be transformed to the web map CRS.")
            preview_bounds = transform_bounds(
                "EPSG:3857", "EPSG:4326", *preview_bounds_mercator, densify_pts=21
            )
            layer["preview_bounds_wgs84"] = {
                "west": float(preview_bounds[0]),
                "south": float(preview_bounds[1]),
                "east": float(preview_bounds[2]),
                "north": float(preview_bounds[3]),
            }
            if valid_pixel_count is not None:
                layer["valid_pixel_count"] = valid_pixel_count
    except (OSError, rasterio.errors.RasterioError, ValueError) as error:
        layer.update(status="error", message=f"Raster metadata could not be read: {error}")
    return layer


def _vector_layer(
    *,
    layer_id: str,
    name: str,
    category: str,
    source: str,
    provenance: str,
    evidence_status: str = "reference_geometry",
    features: dict[str, Any] | None = None,
    path: Path | None = None,
    river_id: str | None = None,
    date: str | None = None,
    temporary: bool = False,
    metadata_only: bool = False,
    geometry_type: str | None = None,
    feature_count: int | None = None,
    bounds_wgs84: dict[str, float] | None = None,
) -> dict[str, Any]:
    collection = features
    if collection is None and path is not None and not metadata_only:
        collection = json.loads(path.read_text(encoding="utf-8"))
    collection = collection or {"type": "FeatureCollection", "features": []}
    geometries = [
        item.get("geometry", {}).get("type")
        for item in collection.get("features", [])
        if item.get("geometry")
    ]
    layer: dict[str, Any] = {
        "layer_id": layer_id,
        "name": name,
        "category": category,
        "layer_type": "vector",
        "status": "available",
        "evidence_status": evidence_status,
        "source": source,
        "date": date,
        "crs": "EPSG:4326",
        "geometry_type": geometry_type or ", ".join(sorted(set(geometries))) or None,
        "feature_count": feature_count if feature_count is not None else (
            None if metadata_only else len(collection.get("features", []))
        ),
        "river_id": river_id,
        "provenance": provenance,
        "temporary": temporary,
        "_path": path,
        "_features": collection if path is None else None,
    }
    if bounds_wgs84:
        layer["bounds_wgs84"] = bounds_wgs84
    if not bounds_wgs84 and collection.get("features"):
        points = [
            (float(x), float(y))
            for feature in collection["features"]
            for x, y in _coordinate_pairs(feature.get("geometry"))
        ]
        if points:
            layer["bounds_wgs84"] = {
                "west": min(point[0] for point in points),
                "south": min(point[1] for point in points),
                "east": max(point[0] for point in points),
                "north": max(point[1] for point in points),
            }
    return layer


def _coordinate_pairs(geometry: dict[str, Any] | None):
    if not isinstance(geometry, dict):
        return
    coordinates = geometry.get("coordinates")
    if geometry.get("type") == "GeometryCollection":
        for child in geometry.get("geometries", []):
            yield from _coordinate_pairs(child)
        return

    def walk(value: Any):
        if (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and all(isinstance(item, (int, float)) for item in value[:2])
        ):
            yield float(value[0]), float(value[1])
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from walk(child)

    yield from walk(coordinates)


def _registered_rivers(river_id: str) -> dict[str, Any]:
    features = []
    for river in RIVER_CATALOG:
        if river_id != "both" and river.id != river_id:
            continue
        features.append(
            {
                "type": "Feature",
                "id": river.id,
                "properties": {
                    "river_id": river.id,
                    "name": river.display_name,
                    "source": river.data_source,
                    "retrieval_date": river.retrieval_date,
                    "license": river.license,
                    "boundary_data_status": river.boundary_data_status,
                },
                "geometry": river.centerline.model_dump(),
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _forest_rows() -> list[dict[str, Any]]:
    with acquisitions._catalog_connection() as connection:
        rows = connection.execute(
            """
            SELECT analysis_id, river_id, item_id, status
            FROM forest_analyses
            WHERE status IN ('completed', 'no_data')
            ORDER BY updated_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _nisar_products() -> list[dict[str, Any]]:
    with acquisitions._catalog_connection() as connection:
        rows = connection.execute(
            "SELECT river_id, nisar_products_json FROM river_scans"
        ).fetchall()
    products = []
    for row in rows:
        for product in json.loads(row["nisar_products_json"] or "[]"):
            result = product.get("processing_result") or {}
            if (
                product.get("processing_status") == "processed"
                and result.get("status") == "unvalidated_candidate"
            ):
                products.append({"river_id": row["river_id"], **product})
    return products


def _analysis_records(river_id: str) -> list[dict[str, Any]]:
    if not analysis.OUTPUT_DIR.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for directory in analysis.OUTPUT_DIR.iterdir():
        if not directory.is_dir():
            continue
        try:
            result = analysis._load_result(directory.name)
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            continue
        if (
            result.get("analysis_type") != "water_mask"
            or result.get("status") != "unvalidated_candidate"
            or (river_id != "both" and result.get("river_id") != river_id)
        ):
            continue
        records.append(result)
    return sorted(records, key=lambda item: item.get("acquisition_start") or "", reverse=True)


def _catalog_records(river_id: str) -> list[dict[str, Any]]:
    if river_id not in ALLOWED_RIVERS:
        raise ValueError("Unsupported river selection.")
    records: list[dict[str, Any]] = [
        _vector_layer(
            layer_id="river-centerlines",
            name="Registered river centerlines",
            category="Rivers",
            source="OpenStreetMap river geometry",
            provenance="Registered Kaveri and Tungabhadra centerlines; no bank boundaries are implied.",
            features=_registered_rivers(river_id),
            river_id=None if river_id == "both" else river_id,
        )
    ]
    for observation in sentinel2._load_catalog():
        if observation.get("status") != "processed":
            continue
        item_river = observation.get("river_id")
        if river_id != "both" and item_river != river_id:
            continue
        item_id = observation.get("item_id")
        if not isinstance(item_id, str):
            continue
        date = observation.get("acquisition_datetime")
        for index_name in ("ndvi", "evi", "ndmi"):
            try:
                path = sentinel2._cached_raster_path(observation, index_name)
            except (ValueError, FileNotFoundError):
                continue
            records.append(
                _raster_layer(
                    layer_id=f"s2-{_stable_id(f'{item_river}:{item_id}:{index_name}')}",
                    name=f"Sentinel-2 {index_name.upper()} · {item_river.title()} · {date or 'date unknown'}",
                    category="Sentinel-2 vegetation indices",
                    source=observation.get("source") or "Sentinel-2 L2A",
                    path=path,
                    provenance=(
                        f"Product {item_id}; locally processed Sentinel-2 L2A index. "
                        "Existing rasters are centerline-clipped and do not represent full surrounding forest coverage."
                    ),
                    river_id=item_river,
                    date=date,
                    valid_pixel_count=observation.get("valid_pixel_counts_by_index", {}).get(index_name),
                )
            )
    water_mask_count = 0
    tree_cover_count = 0
    for result in _analysis_records(river_id):
        analysis_id = result["analysis_id"]
        try:
            analysis_directory = analysis._analysis_directory(analysis_id)
        except (FileNotFoundError, ValueError):
            continue
        mask_path = analysis_directory / "water-mask.tif"
        if not mask_path.is_file():
            continue
        date = result.get("acquisition_start")
        river_name = result.get("river_id", "unknown").title()
        product_id = result.get("source_product_id", "unknown product")
        mask_layer = _raster_layer(
            layer_id=f"water-mask-{analysis_id}",
            name=f"Sentinel-1 water candidate · {river_name} · {date or product_id}",
            category="Water masks",
            source=result.get("mission") or "Sentinel-1 SAR",
            path=mask_path,
            provenance=(
                f"Unvalidated candidate generated from {product_id}; acquisition {date or 'not recorded'}. "
                "This is not a verified river boundary or flood extent."
            ),
            evidence_status="unvalidated_candidate",
            river_id=result.get("river_id"),
            date=date,
            valid_pixel_count=result.get("valid_pixel_count"),
        )
        records.append(mask_layer)
        if mask_layer["status"] == "available":
            water_mask_count += 1
        polygon_path = analysis_directory / "water-polygons.geojson"
        if polygon_path.is_file():
            records.append(
                _vector_layer(
                    layer_id=f"water-polygons-{analysis_id}",
                    name=f"Water extent polygons · {river_name} · {date or product_id}",
                    category="Water masks",
                    source=result.get("mission") or "Sentinel-1 SAR",
                    provenance=f"Display polygons from unvalidated candidate analysis {analysis_id}; not a verified boundary.",
                    evidence_status="unvalidated_candidate",
                    path=polygon_path,
                    river_id=result.get("river_id"),
                    date=date,
                    metadata_only=True,
                    geometry_type="Polygon",
                    bounds_wgs84=mask_layer.get("bounds_wgs84"),
                )
            )
    nisar_count = 0
    for product in _nisar_products():
        product_river = product["river_id"]
        if river_id != "both" and river_id != product_river:
            continue
        product_id = product.get("product_id")
        if not isinstance(product_id, str):
            continue
        try:
            mask_path = acquisitions.nisar_processing_output_path(
                product_river, product_id, "mask"
            )
        except (FileNotFoundError, ValueError):
            continue
        result = product.get("processing_result") or {}
        date = product.get("acquisition_start")
        mask_layer = _raster_layer(
            layer_id="nisar-" + _stable_id(f"{product_river}:{product_id}"),
            name=f"NISAR GCOV candidate water · {product_river.title()} · {date or product_id}",
            category="NISAR",
            source="NISAR L2 GCOV frequency A",
            path=mask_path,
            provenance=(
                f"Unvalidated candidate from {product_id}; acquisition {date or 'not recorded'}. "
                "Candidate open-water classification; not a verified river boundary."
            ),
            evidence_status="unvalidated_candidate",
            river_id=product_river,
            date=date,
            valid_pixel_count=result.get("valid_pixel_count"),
        )
        records.append(mask_layer)
        if mask_layer["status"] == "available":
            nisar_count += 1
        try:
            polygons_path = acquisitions.nisar_processing_output_path(
                product_river, product_id, "polygons"
            )
        except FileNotFoundError:
            polygons_path = None
        if polygons_path:
            records.append(
                _vector_layer(
                    layer_id="nisar-polygons-" + _stable_id(f"{product_river}:{product_id}"),
                    name=f"NISAR candidate polygons · {product_river.title()} · {date or product_id}",
                    category="NISAR",
                    source="NISAR L2 GCOV frequency A",
                    provenance=f"Display polygons from candidate {product_id}; simplified and potentially truncated.",
                    evidence_status="unvalidated_candidate",
                    path=polygons_path,
                    river_id=product_river,
                    date=date,
                    metadata_only=True,
                    geometry_type="Polygon",
                    bounds_wgs84=mask_layer.get("bounds_wgs84"),
                )
            )
    for reference in forest_monitoring.list_references()["references"]:
        if reference.get("status") != "pixels_imported":
            continue
        reference_id = reference.get("reference_id")
        if not isinstance(reference_id, str):
            continue
        try:
            path = forest_monitoring._reference_directory(reference_id) / "worldcover.tif"
        except (FileNotFoundError, ValueError):
            continue
        if not path.is_file():
            continue
        reference_layer = _raster_layer(
            layer_id=f"forest-reference-{reference_id[:20]}",
            name=f"Tree-cover reference · {reference.get('name', 'imported dataset')} · {reference.get('year', 'year unknown')}",
            category="Forest reference / candidate",
            source=reference.get("name") or "User-imported forest reference",
            path=path,
            provenance=(
                f"User-imported reference {reference_id}; provenance is not independently authenticated. "
                "WorldCover class 10 includes plantations and is not independent Sentinel-2 validation."
            ),
            evidence_status="reference_dataset",
            date=str(reference.get("year")) if reference.get("year") else None,
        )
        records.append(reference_layer)
        if reference_layer["status"] == "available":
            tree_cover_count += 1
    for row in _forest_rows():
        if river_id != "both" and row["river_id"] != river_id:
            continue
        summary = {}
        try:
            summary = forest_monitoring.get_analysis(row["analysis_id"])
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            pass
        date = summary.get("acquisition_datetime")
        for index_name in ("ndvi", "evi", "ndmi"):
            try:
                path = forest_monitoring.get_output_path(row["analysis_id"], f"{index_name}.tif")
            except FileNotFoundError:
                continue
            records.append(
                _raster_layer(
                    layer_id="forest-" + _stable_id(f"{row['analysis_id']}:{index_name}"),
                    name=f"Forest corridor {index_name.upper()} · {row['river_id'].title()} · {date or 'date unknown'}",
                    category="Forest monitoring",
                    source="Sentinel-2 L2A",
                    path=path,
                    provenance=(
                        f"Forest zone analysis {row['analysis_id']}; original raster source was processed "
                        "for the zone workflow. This index layer is not a tree-cover classification."
                    ),
                    river_id=row["river_id"],
                    date=date,
                )
            )
        try:
            zones_path = forest_monitoring.get_output_path(row["analysis_id"], "zones.geojson")
        except FileNotFoundError:
            zones_path = None
        if zones_path:
            records.append(
                _vector_layer(
                    layer_id=f"forest-zones-{row['analysis_id'][:20]}",
                    name=f"Forest analysis distance zones · {row['river_id'].title()}",
                    category="Forest monitoring",
                    source="Generated from registered river centerline",
                    provenance=f"Analysis {row['analysis_id']}; distance zones are analysis areas, not forest boundaries.",
                    evidence_status="generated_analysis_zone",
                    path=zones_path,
                    river_id=row["river_id"],
                    date=date,
                )
            )
        try:
            tree_cover_root = forest_monitoring._output_directory(row["analysis_id"]) / "tree-cover"
        except (FileNotFoundError, ValueError):
            tree_cover_root = None
        if tree_cover_root is not None and tree_cover_root.is_dir():
            for summary_path in tree_cover_root.glob("*/summary.json"):
                reference_id = summary_path.parent.name
                if not re.fullmatch(r"[a-f0-9]{64}", reference_id):
                    continue
                try:
                    summary = forest_monitoring.get_tree_cover_summary(row["analysis_id"], reference_id)
                    path = forest_monitoring.get_tree_cover_output_path(
                        row["analysis_id"], reference_id, "tree-cover.tif"
                    )
                except FileNotFoundError:
                    continue
                tree_layer = _raster_layer(
                    layer_id="forest-tree-" + _stable_id(f"{row['analysis_id']}:{reference_id}"),
                    name=f"Tree-cover candidate · {row['river_id'].title()} · {summary.get('dataset_id', reference_id[:10])}",
                    category="Forest reference / candidate",
                    source=summary.get("dataset_name") or "Imported reference dataset",
                    path=path,
                    provenance=(
                        "Candidate tree-cover classification; not independently validated. "
                        f"Reference {reference_id}."
                    ),
                    evidence_status="unvalidated_candidate",
                    river_id=row["river_id"],
                    date=str(summary.get("reference_year")) if summary.get("reference_year") else None,
                )
                records.append(tree_layer)
                if tree_layer["status"] == "available":
                    tree_cover_count += 1
    _ensure_upload_table()
    with acquisitions._catalog_connection() as connection:
        uploads = connection.execute(
            "SELECT layer_id, display_name, file_name, feature_count, uploaded_at FROM gis_user_layers ORDER BY uploaded_at DESC"
        ).fetchall()
    for upload in uploads:
        path = (UPLOAD_ROOT / upload["file_name"]).resolve()
        if UPLOAD_ROOT.resolve() not in path.parents or not path.is_file():
            continue
        records.append(
            _vector_layer(
                layer_id=upload["layer_id"],
                name=upload["display_name"],
                category="Imported GeoJSON",
                source="User-imported GeoJSON",
                provenance=f"Temporary local import uploaded at {upload['uploaded_at']}; source CRS accepted as EPSG:4326.",
                evidence_status="user_imported",
                path=path,
                temporary=True,
            )
        )
    unavailable_layers = list(UNAVAILABLE_LAYERS)
    if nisar_count == 0:
        unavailable_layers.append(
            {
                "layer_id": "nisar-candidate-water",
                "name": "NISAR GCOV candidate water",
                "category": "NISAR",
                "source": "Local processed NISAR outputs",
                "message": "No local NISAR candidate-water raster is available to display.",
            }
        )
    if water_mask_count == 0:
        unavailable_layers.append(
            {
                "layer_id": "water-mask-unavailable",
                "name": "Water masks / water extent",
                "category": "Water masks",
                "source": "Local project analysis outputs",
                "message": "No local water-mask analysis output is available for this river selection.",
            }
        )
    if tree_cover_count == 0:
        unavailable_layers.append(
            {
                "layer_id": "independent-tree-cover-reference",
                "name": "Tree-cover reference raster",
                "category": "Forest reference / candidate",
                "source": "ESA WorldCover 2021 v200 or another imported reference",
                "message": "No local tree-cover reference raster has been imported.",
            }
        )
    for unavailable in unavailable_layers:
        records.append(
            {
                **unavailable,
                "layer_type": "unavailable",
                "status": "unavailable",
                "evidence_status": "unavailable",
                "provenance": unavailable["message"],
                "temporary": False,
            }
        )
    return records


def _public_layer(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not key.startswith("_")}


def list_layers(river_id: str = "both") -> dict[str, Any]:
    return {
        "layers": [_public_layer(record) for record in _catalog_records(river_id)],
        "limitations": [
            "The existing Sentinel-2 index rasters are centerline-clipped; they are not full-area river-side observations.",
            "A layer marked candidate or unvalidated is not an independently validated result.",
            "Unavailable layers are listed for transparency and contain no map data.",
        ],
    }


def _resolve_layer(layer_id: str, river_id: str = "both") -> dict[str, Any]:
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,100}", layer_id):
        raise FileNotFoundError("GIS layer was not found.")
    for record in _catalog_records(river_id):
        if record["layer_id"] == layer_id:
            if record["status"] != "available":
                raise FileNotFoundError(record.get("message") or "GIS layer is not available.")
            return record
    raise FileNotFoundError("GIS layer was not found.")


def get_layer_metadata(layer_id: str, river_id: str = "both") -> dict[str, Any]:
    return _public_layer(_resolve_layer(layer_id, river_id))


def get_layer_features(layer_id: str, river_id: str = "both") -> dict[str, Any]:
    record = _resolve_layer(layer_id, river_id)
    if record["layer_type"] != "vector":
        raise ValueError("This GIS layer is not a vector layer.")
    if record.get("_features") is not None:
        return record["_features"]
    path = record.get("_path")
    if not isinstance(path, Path) or not path.is_file():
        raise FileNotFoundError("Vector data file is unavailable.")
    collection = json.loads(path.read_text(encoding="utf-8"))
    if collection.get("type") != "FeatureCollection" or not isinstance(collection.get("features"), list):
        raise ValueError("Stored vector data is not a valid GeoJSON FeatureCollection.")
    return collection


def get_download(layer_id: str, river_id: str = "both", output_format: str = "native"):
    record = _resolve_layer(layer_id, river_id)
    if record["layer_type"] == "raster":
        if output_format != "native":
            raise ValueError("Raster layers can only be downloaded in their native GeoTIFF format.")
        path = record["_path"]
        if not isinstance(path, Path) or not path.is_file():
            raise FileNotFoundError("Raster data file is unavailable.")
        return path, f"{layer_id}.tif", "image/tiff"
    if record["layer_type"] != "vector":
        raise ValueError("This layer has no downloadable data.")
    collection = get_layer_features(layer_id, river_id)
    if output_format == "csv":
        rows = [feature.get("properties") or {} for feature in collection["features"]]
        fields = sorted({key for row in rows for key in row})
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=["feature_id", *fields], extrasaction="ignore")
        writer.writeheader()
        for feature, properties in zip(collection["features"], rows):
            row = {
                key: value if isinstance(value, (str, int, float, bool)) or value is None
                else json.dumps(value, ensure_ascii=False, sort_keys=True)
                for key, value in properties.items()
            }
            writer.writerow({"feature_id": feature.get("id"), **row})
        return output.getvalue().encode("utf-8"), f"{layer_id}.csv", "text/csv; charset=utf-8"
    if output_format != "native":
        raise ValueError("Unsupported GIS download format.")
    path = record.get("_path")
    if isinstance(path, Path) and path.is_file():
        return path, f"{layer_id}.geojson", "application/geo+json"
    return json.dumps(collection, ensure_ascii=False).encode("utf-8"), f"{layer_id}.geojson", "application/geo+json"


def render_raster_preview(layer_id: str, river_id: str = "both") -> tuple[bytes, dict[str, float]]:
    record = _resolve_layer(layer_id, river_id)
    if record["layer_type"] != "raster":
        raise ValueError("This GIS layer is not a raster layer.")
    path = record["_path"]
    with rasterio.open(path) as source:
        bounds_mercator = transform_bounds(
            source.crs, "EPSG:3857", *source.bounds, densify_pts=21
        )
        if not all(math.isfinite(value) for value in bounds_mercator):
            raise ValueError("Raster bounds cannot be transformed to the web map CRS.")
        scale = min(1.0, MAX_PREVIEW_SIDE / max(source.width, source.height))
        width = max(1, round(source.width * scale))
        height = max(1, round(source.height * scale))
        dst_transform = from_bounds(*bounds_mercator, width, height)
        with WarpedVRT(
            source,
            crs="EPSG:3857",
            transform=dst_transform,
            width=width,
            height=height,
            resampling=Resampling.nearest,
        ) as preview:
            values = preview.read(1, masked=True)
            valid = ~np.ma.getmaskarray(values) & np.isfinite(values.data)
            data = values.data
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        if record.get("evidence_status") == "reference_dataset":
            rgba[valid] = (54, 91, 83, 55)
            rgba[valid & (data == 10)] = (37, 132, 89, 205)
        elif np.issubdtype(data.dtype, np.integer):
            rgba[valid & (data == 1)] = (37, 132, 89, 205)
            rgba[valid & (data == 0)] = (40, 82, 91, 45)
            other = valid & (data != 0) & (data != 1)
            rgba[other] = (205, 168, 71, 190)
        else:
            normalized = np.clip((data + 1.0) / 2.0, 0.0, 1.0)
            rgba[..., 0] = (178 * (1.0 - normalized) + 35 * normalized).astype(np.uint8)
            rgba[..., 1] = (112 * (1.0 - normalized) + 145 * normalized).astype(np.uint8)
            rgba[..., 2] = (65 * (1.0 - normalized) + 75 * normalized).astype(np.uint8)
            rgba[..., 3] = np.where(valid, 185, 0).astype(np.uint8)
        from PIL import Image

        output = io.BytesIO()
        Image.fromarray(rgba, mode="RGBA").save(output, format="PNG")
        west, south, east, north = transform_bounds(
            "EPSG:3857", "EPSG:4326", *bounds_mercator, densify_pts=21
        )
        return output.getvalue(), {
            "west": float(west),
            "south": float(south),
            "east": float(east),
            "north": float(north),
        }


def _raster_sample(record: dict[str, Any], longitude: float, latitude: float) -> dict[str, Any]:
    path = record["_path"]
    with rasterio.open(path) as dataset:
        from rasterio.warp import transform

        x, y = transform("EPSG:4326", dataset.crs, [longitude], [latitude])
        row, column = dataset.index(x[0], y[0])
        if not (0 <= row < dataset.height and 0 <= column < dataset.width):
            return {"value": None, "valid": False, "reason": "Outside raster coverage."}
        sample = dataset.read(1, window=((row, row + 1), (column, column + 1)), masked=True)[0, 0]
        if np.ma.is_masked(sample) or not np.isfinite(sample):
            return {"value": None, "valid": False, "reason": "NoData or invalid raster pixel."}
        return {"value": float(sample), "valid": True, "reason": None}


def inspect_location(request: dict[str, Any]) -> dict[str, Any]:
    latitude = float(request["latitude"])
    longitude = float(request["longitude"])
    river_id = request.get("river_id", "both")
    result: list[dict[str, Any]] = []
    records = {record["layer_id"]: record for record in _catalog_records(river_id)}
    for layer_id in request.get("layer_ids", []):
        record = records.get(layer_id)
        if record is None or record["status"] != "available":
            result.append({"layer_id": layer_id, "status": "unavailable", "value": None})
            continue
        if record["layer_type"] == "raster":
            result.append(
                {
                    "layer_id": layer_id,
                    "name": record["name"],
                    "status": "available",
                    **_raster_sample(record, longitude, latitude),
                }
            )
            continue
        point = Point(longitude, latitude)
        matches = []
        for feature in get_layer_features(layer_id, river_id).get("features", []):
            geometry = feature.get("geometry")
            if geometry and shape(geometry).intersects(point):
                matches.append(
                    {
                        "id": feature.get("id"),
                        "properties": feature.get("properties") or {},
                    }
                )
        result.append(
            {
                "layer_id": layer_id,
                "name": record["name"],
                "status": "available",
                "features": matches[:20],
                "feature_count": len(matches),
            }
        )
    return {"latitude": latitude, "longitude": longitude, "layers": result}


def measure_geometry(geometry_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(geometry_payload, dict):
        raise ValueError("Geometry must be a GeoJSON geometry object.")
    try:
        geometry = shape(geometry_payload)
    except (TypeError, ValueError) as error:
        raise ValueError("Geometry is not valid GeoJSON.") from error
    if geometry.is_empty or not geometry.is_valid:
        raise ValueError("Geometry must be nonempty and valid.")
    if geometry.geom_type not in {
        "Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"
    }:
        raise ValueError("Geometry must be a point, line, or polygon.")
    points = list(_coordinate_pairs(geometry_payload))
    if not points or any(
        not math.isfinite(x) or not math.isfinite(y) or x < -180 or x > 180 or y < -90 or y > 90
        for x, y in points
    ):
        raise ValueError("Geometry coordinates must be finite longitude/latitude values in EPSG:4326.")
    centroid = geometry.centroid
    if not -80 <= centroid.y <= 84:
        raise ValueError("Geometry measurements require a centroid between 80°S and 84°N for UTM.")
    utm_zone = min(60, max(1, int((centroid.x + 180) // 6) + 1))
    utm_epsg = (32600 if centroid.y >= 0 else 32700) + utm_zone
    projected = shape(
        transform_geom("EPSG:4326", f"EPSG:{utm_epsg}", mapping(geometry))
    )
    length_m = float(projected.length)
    area_m2 = 0.0
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        equal_area = shape(transform_geom("EPSG:4326", "EPSG:6933", mapping(geometry)))
        area_m2 = float(equal_area.area)
    if not math.isfinite(length_m) or not math.isfinite(area_m2):
        raise ValueError("Geometry measurement produced a non-finite result.")
    return {
        "geometry_type": geometry.geom_type,
        "length_m": length_m,
        "area_m2": area_m2,
        "measurement_crs": f"UTM zone EPSG:{utm_epsg} length; EPSG:6933 equal-area surface area.",
    }


def import_geojson(content: bytes, filename: str | None) -> dict[str, Any]:
    if len(content) > MAX_GEOJSON_BYTES:
        raise ValueError("GeoJSON upload exceeds the 10 MB size limit.")
    if filename and Path(filename.replace("\\", "/")).suffix.lower() not in {".json", ".geojson"}:
        raise ValueError("Upload a .geojson or .json file.")
    try:
        collection = json.loads(content, parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Uploaded file is not valid UTF-8 GeoJSON.") from error
    if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
        raise ValueError("GeoJSON must be a FeatureCollection.")
    if collection.get("crs"):
        crs_info = collection["crs"]
        if not isinstance(crs_info, dict) or not isinstance(crs_info.get("properties"), dict):
            raise ValueError("GeoJSON CRS metadata must identify EPSG:4326 / CRS84.")
        crs_name = str(crs_info.get("properties", {}).get("name", "")).upper()
        if "4326" not in crs_name and "CRS84" not in crs_name:
            raise ValueError("Imported GeoJSON must use EPSG:4326 / CRS84 coordinates.")
    features = collection.get("features")
    if not isinstance(features, list) or not features or len(features) > MAX_GEOJSON_FEATURES:
        raise ValueError(f"GeoJSON must contain between 1 and {MAX_GEOJSON_FEATURES} features.")
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError(f"Feature {index + 1} is not a GeoJSON Feature.")
        geometry_payload = feature.get("geometry")
        if not isinstance(geometry_payload, dict):
            raise ValueError(f"Feature {index + 1} has no supported geometry.")
        try:
            geometry = shape(geometry_payload)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Feature {index + 1} has invalid geometry.") from error
        if geometry.is_empty or not geometry.is_valid:
            raise ValueError(f"Feature {index + 1} geometry must be nonempty and valid.")
        if geometry.geom_type not in {
            "Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"
        }:
            raise ValueError(f"Feature {index + 1} geometry type is unsupported.")
        points = list(_coordinate_pairs(geometry_payload))
        if not points or any(
            not math.isfinite(x) or not math.isfinite(y) or x < -180 or x > 180 or y < -90 or y > 90
            for x, y in points
        ):
            raise ValueError(f"Feature {index + 1} coordinates are not valid EPSG:4326 values.")
        if feature.get("properties") is not None and not isinstance(feature.get("properties"), dict):
            raise ValueError(f"Feature {index + 1} properties must be an object.")
    normalized_name = Path((filename or "imported.geojson").replace("\\", "/")).name
    display_name = Path(normalized_name).stem[:100] or "Imported GeoJSON"
    layer_id = f"upload-{uuid4().hex}"
    file_name = f"{layer_id}.geojson"
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    path = (UPLOAD_ROOT / file_name).resolve()
    if UPLOAD_ROOT.resolve() not in path.parents:
        raise ValueError("Upload destination is invalid.")
    path.write_text(
        json.dumps(collection, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    try:
        _ensure_upload_table()
        with acquisitions._catalog_connection() as connection:
            connection.execute(
                "INSERT INTO gis_user_layers(layer_id, display_name, file_name, feature_count, uploaded_at) VALUES (?, ?, ?, ?, ?)",
                (
                    layer_id,
                    display_name,
                    file_name,
                    len(features),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return get_layer_metadata(layer_id)


def remove_imported_layer(layer_id: str) -> None:
    _ensure_upload_table()
    with acquisitions._catalog_connection() as connection:
        row = connection.execute(
            "SELECT file_name FROM gis_user_layers WHERE layer_id=?",
            (layer_id,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError("Temporary imported layer was not found.")
        path = (UPLOAD_ROOT / row["file_name"]).resolve()
        if UPLOAD_ROOT.resolve() not in path.parents:
            raise ValueError("Temporary upload path is invalid.")
        connection.execute("DELETE FROM gis_user_layers WHERE layer_id=?", (layer_id,))
    if path.exists():
        path.unlink()
