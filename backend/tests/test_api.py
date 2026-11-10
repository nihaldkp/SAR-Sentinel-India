import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_identifies_demonstration_mode() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "data_mode": "demonstration"}


def test_regions_are_marked_as_simulated() -> None:
    response = client.get("/api/regions")

    assert response.status_code == 200
    regions = response.json()
    assert [region["id"] for region in regions] == [
        "krishna-karnataka",
        "godavari-telangana",
        "mahanadi-odisha",
    ]
    assert all(region["is_simulated"] for region in regions)


def test_observations_can_be_filtered_to_a_region() -> None:
    response = client.get("/api/observations", params={"region_id": "krishna-karnataka"})

    assert response.status_code == 200
    observations = response.json()
    assert len(observations) == 2
    assert {item["region_id"] for item in observations} == {"krishna-karnataka"}
    assert all(item["is_simulated"] for item in observations)
    assert all(item["source"] == "synthetic_demo" for item in observations)


def test_unknown_region_filter_returns_helpful_not_found() -> None:
    response = client.get("/api/observations", params={"region_id": "not-a-region"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown region_id: not-a-region"


def test_local_frontend_origin_is_allowed_by_cors() -> None:
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_local_frontend_origin_with_vite_fallback_port_is_allowed_by_cors() -> None:
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://127.0.0.1:5175",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5175"


def test_rivers_are_exposed_with_real_centerline_geometry() -> None:
    response = client.get("/api/rivers")

    assert response.status_code == 200
    rivers = response.json()
    assert [river["id"] for river in rivers] == ["kaveri", "tungabhadra"]
    assert all(river["boundary_data_status"] == "unavailable" for river in rivers)
    assert all(river["centerline"]["type"] == "MultiLineString" for river in rivers)
    assert all(len(river["centerline"]["coordinates"]) >= 1 for river in rivers)
    assert all(river["left_bank_boundary"] is None for river in rivers)
    assert all(river["right_bank_boundary"] is None for river in rivers)
    assert all(river["license"].endswith("ODbL) 1.0") for river in rivers)
    assert all(river["retrieval_date"] == "2026-11-09" for river in rivers)
    assert [river["osm_element_id"] for river in rivers] == [2704746, 2742213]


def test_river_geojson_has_valid_wgs84_coordinates_and_provenance() -> None:
    data_path = Path(__file__).resolve().parents[1] / "app" / "data" / "rivers.geojson"
    payload = json.loads(data_path.read_text(encoding="utf-8"))

    assert payload["type"] == "FeatureCollection"
    assert payload["attribution"] == "© OpenStreetMap contributors"
    assert "ODbL" in payload["license"]
    assert payload["license_url"] == "https://www.openstreetmap.org/copyright"
    assert payload["retrieval_date"] == "2026-11-09"
    assert len(payload["features"]) == 2

    expected_bounds = {
        "kaveri": (75.5, 80.0, 10.8, 12.7),
        "tungabhadra": (75.5, 78.3, 14.0, 16.0),
    }
    for feature in payload["features"]:
        river_id = feature["id"]
        properties = feature["properties"]
        geometry = feature["geometry"]
        assert geometry["type"] == "MultiLineString"
        assert properties["osm_element_type"] == "relation"
        assert properties["source_url"].endswith(f"/relation/{properties['osm_element_id']}")
        assert properties["retrieval_url"].startswith("https://nominatim.openstreetmap.org/search?")

        coordinates = [
            point
            for segment in geometry["coordinates"]
            for point in segment
        ]
        assert coordinates
        assert all(
            len(point) == 2
            and -180 <= point[0] <= 180
            and -90 <= point[1] <= 90
            for point in coordinates
        )
        west, east, south, north = expected_bounds[river_id]
        longitudes = [point[0] for point in coordinates]
        latitudes = [point[1] for point in coordinates]
        assert min(longitudes) >= west
        assert max(longitudes) <= east
        assert min(latitudes) >= south
        assert max(latitudes) <= north
        assert all(len(segment) >= 2 for segment in geometry["coordinates"])


def test_specific_river_detail_endpoint_returns_geographical_metadata() -> None:
    response = client.get("/api/rivers/kaveri")

    assert response.status_code == 200
    river = response.json()
    assert river["name"] == "Kaveri River"
    assert river["states"] == "Karnataka, Tamil Nadu"
    assert river["available_geographical_data"] == ["centerline"]
    assert river["source_url"] == "https://www.openstreetmap.org/relation/2704746"
    assert river["retrieval_url"].startswith("https://nominatim.openstreetmap.org/search?")
    assert river["license_url"] == "https://www.openstreetmap.org/copyright"
    assert river["future_nisar_integration"]["supported"] is True


def test_unknown_river_returns_helpful_not_found() -> None:
    response = client.get("/api/rivers/not-a-river")

    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown river_id: not-a-river"


def test_sentinel2_candidate_metadata_and_mask_endpoints(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import acquisitions

    product_id = "NISAR_TEST_PRODUCT"
    metadata = {
        "status": "unvalidated_candidate",
        "counts": {
            "common_valid_pixels": 12,
            "ndwi_candidate_pixels": 4,
            "candidate_area_m2": 400,
        },
        "limitations": ["Not ground truth."],
    }
    mask_path = tmp_path / "ndwi-candidate-mask.tif"
    mask_path.write_bytes(b"fixture-geotiff")
    monkeypatch.setattr(
        acquisitions,
        "nisar_optical_reference_metadata",
        lambda river_id, requested_product_id: metadata,
    )
    monkeypatch.setattr(
        acquisitions,
        "nisar_optical_reference_path",
        lambda river_id, requested_product_id, output_name: mask_path,
    )

    response = client.get(
        f"/api/acquisitions/nisar/{product_id}/processing/sentinel2-reference",
        params={"river_id": "tungabhadra"},
    )
    assert response.status_code == 200
    assert response.json() == metadata

    download = client.get(
        f"/api/acquisitions/nisar/{product_id}/processing/sentinel2-reference/mask",
        params={"river_id": "tungabhadra"},
    )
    assert download.status_code == 200
    assert download.content == b"fixture-geotiff"
    assert download.headers["content-type"].startswith("image/tiff")


def test_sentinel2_preview_and_geospatial_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import numpy as np
    import pytest

    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import Affine

    from app.services import acquisitions

    product_id = "NISAR_TEST_PRODUCT"
    reference_directory = tmp_path / "sentinel2-reference"
    reference_directory.mkdir()
    mask_path = reference_directory / "ndwi-candidate-mask.tif"
    with rasterio.open(
        mask_path,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="uint8",
        crs="EPSG:32643",
        transform=Affine(10, 0, 500_000, 0, -10, 1_600_020),
        nodata=255,
    ) as output:
        output.write(np.asarray([[0, 1], [255, 1]], dtype=np.uint8), 1)
    metadata_path = reference_directory / "processing-metadata.json"
    metadata_path.write_text(
        json.dumps({
            "status": "unvalidated_candidate",
            "classification": "exploratory Sentinel-2 NDWI water candidate",
            "ndwi_threshold": 0,
            "grid": {"pixel_area_m2": 100},
            "counts": {
                "common_valid_pixels": 3,
                "ndwi_candidate_pixels": 2,
                "candidate_area_m2": 200,
            },
            "source": {
                "item_id": "S2C_MSIL2A_20261106T052011_R062_T43PGT_20261106T101206",
                "acquisition_datetime": "2026-11-06T05:20:11.025000Z",
                "catalog_cloud_cover_percent": 38.783842,
            },
            "limitations": ["Not ground truth."],
        }),
        encoding="utf-8",
    )
    observation_id = "S2C_MSIL2A_20261106T052011_R062_T43PES_20261106T101206"
    observation_directory = (
        tmp_path
        / "nisar-processing"
        / "sentinel2-observations"
        / observation_id
    )
    observation_directory.mkdir(parents=True)
    observation_mask_path = observation_directory / "ndwi-candidate-mask.tif"
    with rasterio.open(
        observation_mask_path,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="uint8",
        crs="EPSG:32643",
        transform=Affine(10, 0, 500_000, 0, -10, 1_600_020),
        nodata=255,
    ) as output:
        output.write(np.asarray([[0, 1], [255, 1]], dtype=np.uint8), 1)
    (observation_directory / "processing-metadata.json").write_text(
        json.dumps({
            "status": "unvalidated_candidate",
            "classification": "exploratory Sentinel-2 NDWI water candidate",
            "ndwi_threshold": 0,
            "grid": {"pixel_area_m2": 100},
            "counts": {
                "common_valid_pixels": 3,
                "ndwi_candidate_pixels": 2,
                "candidate_area_m2": 200,
            },
            "source": {
                "item_id": observation_id,
                "acquisition_datetime": "2026-11-06T05:20:11.025000Z",
                "mgrs_tile": "43PES",
                "catalog_cloud_cover_percent": 41.829962,
            },
            "limitations": ["Not ground truth."],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        acquisitions,
        "_nisar_product_record",
        lambda river_id, requested_product_id: (
            {
                "acquisition_start": "2026-11-06T00:25:20Z",
                "processing_result": {},
            },
            tmp_path / "product.h5",
        ),
    )
    monkeypatch.setattr(
        acquisitions,
        "nisar_optical_reference_path",
        lambda river_id, requested_product_id, output_name: (
            mask_path if output_name == "mask" else metadata_path
        ),
    )

    metadata_response = client.get(
        f"/api/acquisitions/nisar/{product_id}/processing/sentinel2-reference",
        params={"river_id": "tungabhadra"},
    )
    assert metadata_response.status_code == 200
    metadata = metadata_response.json()
    assert metadata["crs"] == "EPSG:32643"
    assert metadata["bounds_wgs84"]["west"] < metadata["bounds_wgs84"]["east"]
    assert metadata["bounds_wgs84"]["south"] < metadata["bounds_wgs84"]["north"]
    assert metadata["dimensions"] == {"width": 2, "height": 2}
    assert metadata["nodata_value"] == 255
    assert metadata["nisar_acquisition_datetime"] == "2026-11-06T00:25:20Z"
    assert metadata["acquisition_time_difference_seconds"] == 17_691.025
    assert metadata["mapped_centerline_coverage_percent"] == 21.7962
    assert metadata["preview_url"].endswith("/preview?river_id=tungabhadra")
    assert len(metadata["additional_observations"]) == 1
    observation = metadata["additional_observations"][0]
    assert observation["source"]["item_id"] == observation_id
    assert observation["source"]["mgrs_tile"] == "43PES"
    assert observation["counts"]["common_valid_pixels"] == 3
    assert observation["crs"] == "EPSG:32643"
    assert observation["nodata_value"] == 255
    assert observation["acquisition_time_difference_seconds"] == 17_691.025

    preview_response = client.get(metadata["preview_url"])
    assert preview_response.status_code == 200
    assert preview_response.headers["content-type"].startswith("image/png")
    assert preview_response.content.startswith(b"\x89PNG\r\n\x1a\n")

    observation_preview = client.get(observation["preview_url"])
    assert observation_preview.status_code == 200
    assert observation_preview.headers["content-type"].startswith("image/png")
    observation_mask = client.get(observation["mask_url"])
    assert observation_mask.status_code == 200
    assert observation_mask.headers["content-type"].startswith("image/tiff")
