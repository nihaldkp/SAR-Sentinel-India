from datetime import date, datetime, time, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from app.redaction import redact_sensitive_text, redact_url
from app.schemas.satellite import Mission, SatelliteObservation, SatelliteSearchResponse
from app.services.rivers import RIVER_CATALOG

ASF_SEARCH_URL = "https://api.daac.asf.alaska.edu/services/search/param"
CORRIDOR_HALF_WIDTH_M = 1_500
NISAR_PRODUCTS = {"L0B", "RSLC", "RIFG", "RUNW", "ROFF", "GSLC", "GCOV", "GUNW", "GOFF", "SME2"}
SENTINEL1_PRODUCTS = {"GRD_HD", "GRD_MD", "GRD_MS", "SLC", "RAW"}
DEFAULT_PRODUCT = {"NISAR": "GCOV", "SENTINEL-1": "GRD_HD"}
ANALYSIS_READINESS = {
    ("NISAR", "GCOV"): "geocoded covariance product; requires product-specific band and calibration review",
    ("NISAR", "GSLC"): "geocoded complex product; not directly accepted by scalar water-mask pipeline",
    ("SENTINEL-1", "GRD_HD"): "ground-range detected; radiometric calibration and terrain correction must be verified before analysis",
    ("SENTINEL-1", "GRD_MD"): "ground-range detected; radiometric calibration and terrain correction must be verified before analysis",
    ("SENTINEL-1", "GRD_MS"): "ground-range detected; radiometric calibration and terrain correction must be verified before analysis",
    ("SENTINEL-1", "SLC"): "complex slant-range product; requires a product-specific processing chain",
    ("SENTINEL-1", "RAW"): "raw product; requires sensor-specific focusing and calibration",
}


def _river_search_wkt(river_id: str) -> str:
    river = next((item for item in RIVER_CATALOG if item.id == river_id), None)
    if river is None:
        raise HTTPException(status_code=404, detail=f"Unknown river_id: {river_id}")
    coordinates = river.centerline.coordinates
    segments = coordinates if river.centerline.type == "MultiLineString" else [coordinates]
    points = [point for segment in segments for point in segment]
    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    west, east = min(longitudes), max(longitudes)
    south, north = min(latitudes), max(latitudes)
    return f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"


def _projected_river_corridor(river_id: str) -> tuple[str, Any]:
    from rasterio.warp import transform_geom
    from shapely.geometry import shape

    river = next((item for item in RIVER_CATALOG if item.id == river_id), None)
    if river is None:
        raise HTTPException(status_code=404, detail=f"Unknown river_id: {river_id}")
    geometry = river.centerline.model_dump()
    segments = geometry["coordinates"] if geometry["type"] == "MultiLineString" else [geometry["coordinates"]]
    points = [point for segment in segments for point in segment]
    if not points:
        raise ValueError(f"River {river_id} has no coordinates for corridor construction.")
    longitude = sum(point[0] for point in points) / len(points)
    latitude = sum(point[1] for point in points) / len(points)
    projected_crs = (
        f"+proj=aeqd +lat_0={latitude:.8f} +lon_0={longitude:.8f} "
        "+datum=WGS84 +units=m +no_defs +type=crs"
    )
    projected_centerline = shape(transform_geom("EPSG:4326", projected_crs, geometry))
    return projected_crs, projected_centerline.buffer(CORRIDOR_HALF_WIDTH_M)


def _filter_features_by_river_corridor(
    features: list[dict[str, Any]],
    river_id: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    from rasterio.warp import transform_geom
    from shapely.geometry import shape

    projected_crs, corridor = _projected_river_corridor(river_id)
    overlapping: list[tuple[float, dict[str, Any]]] = []
    for feature in features:
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            continue
        projected_footprint = shape(
            transform_geom("EPSG:4326", projected_crs, geometry)
        )
        if not projected_footprint.is_valid:
            raise ValueError(
                f"ASF returned an invalid footprint for product {feature.get('id', 'unknown')}."
            )
        overlap_area = corridor.intersection(projected_footprint).area
        if overlap_area > 0:
            overlapping.append((overlap_area, feature))
    overlapping.sort(key=lambda result: result[0], reverse=True)
    matches = [feature for _, feature in overlapping]
    return matches[:limit] if limit is not None else matches


def _to_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _observation(feature: dict[str, Any], mission: Mission) -> SatelliteObservation:
    properties = feature.get("properties") or {}
    product_type = properties.get("processingLevel")
    file_size = properties.get("bytes")
    if isinstance(file_size, dict):
        sizes = [item.get("bytes") for item in file_size.values() if isinstance(item, dict)]
        file_size = sum(value for value in sizes if isinstance(value, int))
    if not isinstance(file_size, int) or file_size < 0:
        file_size = None
    product_id = properties.get("fileID") or properties.get("sceneName")
    if not isinstance(product_id, str) or not product_id:
        raise ValueError("ASF response contained a product without a stable identifier.")
    metadata_url = f"{ASF_SEARCH_URL}?{urlencode({'product_list': product_id, 'output': 'geojson'})}"
    product_level = str(product_type) if product_type is not None else "unknown"
    return SatelliteObservation(
        id=product_id,
        mission=mission,
        platform=properties.get("platform"),
        sensor=properties.get("sensor") or properties.get("instrument"),
        acquisition_start=_to_datetime(properties.get("startTime")),
        acquisition_end=_to_datetime(properties.get("stopTime")),
        polarization=properties.get("polarization")
        or properties.get("mainBandPolarization")
        or properties.get("sideBandPolarization"),
        product_type=product_type,
        footprint=feature.get("geometry"),
        metadata_url=metadata_url,
        download_url=redact_url(properties.get("url")),
        file_size_bytes=file_size,
        source="ASF DAAC",
        analysis_readiness=ANALYSIS_READINESS.get(
            (mission, product_level),
            "product-specific processing requirements have not been verified",
        ),
    )


async def search_satellite_catalog(
    river_id: str,
    mission: Mission,
    start_date: date,
    end_date: date,
    product_type: str | None,
    limit: int,
) -> SatelliteSearchResponse:
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date.")

    valid_products = NISAR_PRODUCTS if mission == "NISAR" else SENTINEL1_PRODUCTS
    selected_product = product_type or DEFAULT_PRODUCT[mission]
    if selected_product not in valid_products:
        supported = ", ".join(sorted(valid_products))
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported {mission} product_type. Supported values: {supported}",
        )

    start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end = datetime.combine(end_date, time.max, tzinfo=timezone.utc)
    parameters = {
        "dataset": mission,
        "processingLevel": selected_product,
        "intersectsWith": _river_search_wkt(river_id),
        "start": start.isoformat().replace("+00:00", "Z"),
        "end": end.isoformat().replace("+00:00", "Z"),
        "output": "geojson",
        "maxResults": str(min(100, limit * 5)),
    }

    try:
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
            response = await client.get(
                ASF_SEARCH_URL,
                params=parameters,
                headers={"User-Agent": "SAR-Sentinel-India/0.1"},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(
            status_code=502,
            detail=f"ASF DAAC metadata search failed: {redact_sensitive_text(str(error))}",
        ) from error

    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise HTTPException(status_code=502, detail="ASF DAAC returned an invalid GeoJSON response.")

    try:
        intersecting_features = _filter_features_by_river_corridor(
            [feature for feature in features if isinstance(feature, dict)],
            river_id,
            limit,
        )
        observations = [
            _observation(feature, mission)
            for feature in intersecting_features
        ]
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=502,
            detail=f"ASF DAAC returned invalid product metadata: {redact_sensitive_text(str(error))}",
        ) from error

    return SatelliteSearchResponse(
        river_id=river_id,
        mission=mission,
        product_type=selected_product,
        query_start=start,
        query_end=end,
        source="ASF DAAC",
        source_url=f"{ASF_SEARCH_URL}?{urlencode(parameters)}",
        observations=observations,
        note=(
            "Live ASF DAAC metadata only. Download links may require Earthdata authentication. "
            "The centerline bounding box is used only for catalog retrieval; returned product footprints "
            "are then filtered against a 1,500 m projected river corridor. Product suitability and calibration "
            "must still be reviewed before processing."
        ),
    )
