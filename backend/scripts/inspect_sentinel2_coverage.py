import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import rasterio
from rasterio.features import geometry_mask, geometry_window
from rasterio.warp import transform_geom
from rasterio.windows import Window
from shapely.geometry import box, shape
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-2-l2a"
DEFAULT_START = "2026-11-05T00:00:00Z"
DEFAULT_END = "2026-11-09T23:59:59Z"
BASELINE_ITEM_ID = "S2C_MSIL2A_20261106T052011_R062_T43PGT_20261106T101206"
NISAR_PRODUCT_PREFIX = "NISAR_L2_UR_GCOV_035_012_A_009_4005_DHDH_A_20261106T002520"


def _intersecting_centerline_km(
    line_projected,
    nisar_bounds,
    item_footprint,
    baseline_footprint,
) -> tuple[float, float]:
    nisar_footprint = box(
        nisar_bounds.left,
        nisar_bounds.bottom,
        nisar_bounds.right,
        nisar_bounds.top,
    )
    supported_line = line_projected.intersection(nisar_footprint)
    item_line = supported_line.intersection(item_footprint)
    incremental_line = item_line.difference(baseline_footprint)
    return item_line.length / 1000, incremental_line.length / 1000


def _valid_pixels_under_footprint(dataset, footprint_wgs84: dict[str, Any]) -> int:
    projected = transform_geom(
        "EPSG:4326",
        dataset.crs,
        footprint_wgs84,
        precision=-1,
    )
    try:
        window = geometry_window(dataset, [projected]).round_offsets().round_lengths()
        window = window.intersection(Window(0, 0, dataset.width, dataset.height))
    except rasterio.errors.WindowError:
        return 0
    if window.width <= 0 or window.height <= 0:
        return 0
    values = dataset.read(1, window=window)
    inside = geometry_mask(
        [projected],
        out_shape=values.shape,
        transform=dataset.window_transform(window),
        invert=True,
    )
    return int(((values != dataset.nodata) & inside).sum())


def _search_items(
    client: httpx.Client,
    geometry: dict[str, Any],
    start: str,
    end: str,
) -> list[dict[str, Any]]:
    response = client.post(
        f"{STAC_URL}/search",
        json={
            "collections": [COLLECTION],
            "datetime": f"{start}/{end}",
            "intersects": geometry,
            "limit": 100,
        },
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("features")
    if not isinstance(items, list):
        raise RuntimeError("Sentinel-2 STAC response has no feature list.")
    if len(items) >= 100:
        raise RuntimeError(
            "STAC returned the full page limit; narrow the time range before screening."
        )
    return items


def inspect_coverage(start: str = DEFAULT_START, end: str = DEFAULT_END) -> dict[str, Any]:
    repository_root = Path(__file__).resolve().parents[2]
    river_catalog = json.loads(
        (repository_root / "backend" / "app" / "data" / "rivers.geojson").read_text(
            encoding="utf-8"
        )
    )
    river = next(
        (feature for feature in river_catalog["features"] if feature["id"] == "tungabhadra"),
        None,
    )
    if river is None:
        raise RuntimeError("The Tungabhadra reference centerline is unavailable.")

    nisar_directories = list(
        (repository_root / "data" / "acquisitions" / "tungabhadra").glob(
            f"{NISAR_PRODUCT_PREFIX}*"
        )
    )
    if len(nisar_directories) != 1:
        raise RuntimeError("Expected the existing A_009 NISAR product directory.")
    nisar_directory = nisar_directories[0] / "nisar-processing"
    nisar_mask_path = nisar_directory / "candidate-water-mask.tif"
    optical_metadata_path = (
        nisar_directory / "sentinel2-reference" / "processing-metadata.json"
    )
    if not nisar_mask_path.is_file() or not optical_metadata_path.is_file():
        raise RuntimeError("The existing A_009 raster or baseline optical metadata is missing.")
    baseline_metadata = json.loads(optical_metadata_path.read_text(encoding="utf-8"))
    baseline_item_id = baseline_metadata["source"]["item_id"]

    with httpx.Client(
        timeout=45,
        headers={"User-Agent": "SAR-Sentinel-India/metadata-screening"},
    ) as client:
        items = _search_items(client, river["geometry"], start, end)

    baseline = next((item for item in items if item.get("id") == baseline_item_id), None)
    if baseline is None:
        with httpx.Client(
            timeout=30,
            headers={"User-Agent": "SAR-Sentinel-India/metadata-screening"},
        ) as client:
            response = client.get(
                f"{STAC_URL}/collections/{COLLECTION}/items/{baseline_item_id}"
            )
            response.raise_for_status()
            baseline = response.json()
    baseline_footprint_wgs84 = baseline.get("geometry")
    if not isinstance(baseline_footprint_wgs84, dict):
        raise RuntimeError("The baseline Sentinel-2 item has no valid geometry.")

    results: list[dict[str, Any]] = []
    with rasterio.open(nisar_mask_path) as nisar:
        if nisar.crs is None or nisar.nodata is None:
            raise RuntimeError("The A_009 candidate mask lacks CRS or NoData metadata.")
        nisar_crs = nisar.crs.to_string()
        line_projected = shape(
            transform_geom(
                "EPSG:4326",
                nisar.crs,
                river["geometry"],
                precision=-1,
            )
        )
        baseline_projected = shape(
            transform_geom(
                "EPSG:4326",
                nisar.crs,
                baseline_footprint_wgs84,
                precision=-1,
            )
        )
        projected_footprints = [baseline_projected]
        for item in items:
            properties = item.get("properties") or {}
            geometry = item.get("geometry")
            item_id = item.get("id")
            if not isinstance(item_id, str) or not isinstance(geometry, dict):
                continue
            footprint_projected = shape(
                transform_geom("EPSG:4326", nisar.crs, geometry, precision=-1)
            )
            projected_footprints.append(footprint_projected)
            centerline_km, incremental_centerline_km = _intersecting_centerline_km(
                line_projected,
                nisar.bounds,
                footprint_projected,
                baseline_projected,
            )
            results.append(
                {
                    "item_id": item_id,
                    "acquisition_datetime": properties.get("datetime")
                    or properties.get("start_datetime"),
                    "tile": properties.get("s2:mgrs_tile"),
                    "cloud_cover_percent": properties.get("eo:cloud_cover"),
                    "centerline_coverage_within_nisar_bounds_km": round(
                        centerline_km, 3
                    ),
                    "incremental_centerline_coverage_beyond_baseline_km": round(
                        incremental_centerline_km, 3
                    ),
                    "nisar_valid_pixels_under_item_footprint": _valid_pixels_under_footprint(
                        nisar, geometry
                    ),
                    "has_B03_B08_SCL": all(
                        key in (item.get("assets") or {}) for key in ("B03", "B08", "SCL")
                    ),
                    "baseline_item": item_id == baseline_item_id,
                }
            )

    results.sort(
        key=lambda item: (
            item["acquisition_datetime"] or "",
            item["tile"] or "",
        )
    )
    return {
        "status": "metadata_and_existing_nisar_support_only",
        "river_id": "tungabhadra",
        "nisar_product_id": nisar_directories[0].name,
        "nisar_crs": nisar_crs,
        "collection": COLLECTION,
        "search_interval": {"start": start, "end": end},
        "baseline_item_id": baseline_item_id,
        "candidate_items": len(results),
        "centerline_coverage_union_within_nisar_bounds_km": round(
            line_projected.intersection(
                box(nisar.bounds.left, nisar.bounds.bottom, nisar.bounds.right, nisar.bounds.top)
            ).intersection(unary_union(projected_footprints)).length
            / 1000,
            3,
        ),
        "note": (
            "Footprint metrics are geometric screening, not clear optical support. "
            "NISAR valid-pixel counts indicate where the A_009 corridor mask is valid "
            "beneath each footprint; Sentinel-2 SCL/reflectance must be inspected separately."
        ),
        "items": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Screen Sentinel-2 STAC metadata against Tungabhadra NISAR A_009 "
            "without signing or downloading imagery."
        )
    )
    parser.add_argument("--start", default=DEFAULT_START, help="STAC start timestamp (UTC).")
    parser.add_argument("--end", default=DEFAULT_END, help="STAC end timestamp (UTC).")
    args = parser.parse_args()
    print(json.dumps(inspect_coverage(args.start, args.end), indent=2))


if __name__ == "__main__":
    main()
