import json
import sqlite3
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

import numpy as np
import rasterio
from fastapi.testclient import TestClient
from PIL import Image
from rasterio.transform import from_origin, xy
from rasterio.warp import transform

from app.main import app
from app.services import acquisitions, analysis, forest_monitoring, gis_explorer, sentinel2


def _configure_gis_fixture(tmp_path: Path, monkeypatch):
    path = tmp_path / "ndvi.tif"
    values = np.array(
        [[0.25, 0.6, -9999], [0.1, -9999, 0.4]],
        dtype=np.float32,
    )
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=3,
        height=2,
        count=1,
        dtype="float32",
        crs="EPSG:32643",
        transform=from_origin(500000, 1700000, 10, 10),
        nodata=-9999,
    ) as dataset:
        dataset.write(values, 1)

    record = {
        "river_id": "kaveri",
        "item_id": "S2_TEST_PRODUCT",
        "status": "processed",
        "source": "Sentinel-2 L2A",
        "acquisition_datetime": "2026-11-13T05:10:41Z",
        "output_paths": {"ndvi": str(path), "evi": str(path), "ndmi": str(path)},
        "valid_pixel_counts_by_index": {"ndvi": 4, "evi": 4, "ndmi": 4},
    }
    monkeypatch.setattr(sentinel2, "_load_catalog", lambda: [record])
    monkeypatch.setattr(sentinel2, "_cached_raster_path", lambda _record, _index: path)
    monkeypatch.setattr(forest_monitoring, "_analysis_row", lambda _analysis_id: None)
    monkeypatch.setattr(forest_monitoring, "list_references", lambda: {"references": []})
    monkeypatch.setattr(gis_explorer, "_forest_rows", lambda: [])
    monkeypatch.setattr(gis_explorer, "_analysis_records", lambda _river_id: [])
    monkeypatch.setattr(gis_explorer, "_nisar_products", lambda: [])
    monkeypatch.setattr(gis_explorer, "UPLOAD_ROOT", tmp_path / "uploads")

    database = sqlite3.connect(":memory:", check_same_thread=False)
    database.row_factory = sqlite3.Row

    @contextmanager
    def catalog_connection():
        yield database

    monkeypatch.setattr(acquisitions, "_catalog_connection", catalog_connection)
    return path, values


def _layer_id(client: TestClient) -> str:
    response = client.get("/api/gis/layers?river_id=kaveri")
    assert response.status_code == 200
    return next(
        layer["layer_id"]
        for layer in response.json()["layers"]
        if layer["category"] == "Sentinel-2 vegetation indices"
        and "NDVI" in layer["name"]
    )


def _lat_lon_for_pixel(path: Path, row: int, column: int) -> tuple[float, float]:
    with rasterio.open(path) as dataset:
        x, y = xy(dataset.transform, row, column, offset="center")
        longitude, latitude = transform(dataset.crs, "EPSG:4326", [x], [y])
    return latitude[0], longitude[0]


def test_gis_catalog_lists_local_data_and_explicit_unavailable_layers(tmp_path, monkeypatch):
    _configure_gis_fixture(tmp_path, monkeypatch)
    client = TestClient(app)

    response = client.get("/api/gis/layers?river_id=kaveri")
    assert response.status_code == 200
    catalog = response.json()
    river = next(layer for layer in catalog["layers"] if layer["layer_id"] == "river-centerlines")
    ndvi = next(layer for layer in catalog["layers"] if layer["category"] == "Sentinel-2 vegetation indices")
    nisar = next(layer for layer in catalog["layers"] if layer["layer_id"] == "nisar-candidate-water")
    assert river["status"] == "available"
    assert river["geometry_type"] == "MultiLineString"
    assert ndvi["status"] == "available"
    assert ndvi["crs"] == "EPSG:32643"
    assert ndvi["width"] == 3 and ndvi["height"] == 2
    assert ndvi["nodata"] == -9999
    assert ndvi["valid_pixel_count"] == 4
    assert ndvi["preview_bounds_wgs84"]
    assert nisar["status"] == "unavailable"
    assert nisar["message"]
    missing = client.get("/api/gis/layers/not-a-real-layer/metadata")
    assert missing.status_code == 404


def test_gis_raster_download_is_original_and_inspection_preserves_nodata(tmp_path, monkeypatch):
    path, values = _configure_gis_fixture(tmp_path, monkeypatch)
    client = TestClient(app)
    layer_id = _layer_id(client)

    download = client.get(
        f"/api/gis/layers/{layer_id}/download?river_id=kaveri"
    )
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("image/tiff")
    assert f'filename="{layer_id}.tif"' in download.headers["content-disposition"]
    with rasterio.MemoryFile(download.content) as memory_file:
        with memory_file.open() as dataset:
            assert dataset.crs.to_string() == "EPSG:32643"
            assert dataset.nodata == -9999
            np.testing.assert_array_equal(dataset.read(1), values)

    latitude, longitude = _lat_lon_for_pixel(path, 0, 0)
    inspected = client.post(
        "/api/gis/inspect",
        json={
            "latitude": latitude,
            "longitude": longitude,
            "river_id": "kaveri",
            "layer_ids": [layer_id],
        },
    )
    assert inspected.status_code == 200
    assert inspected.json()["layers"][0]["value"] == 0.25
    assert inspected.json()["layers"][0]["valid"] is True

    latitude, longitude = _lat_lon_for_pixel(path, 1, 1)
    nodata = client.post(
        "/api/gis/inspect",
        json={
            "latitude": latitude,
            "longitude": longitude,
            "river_id": "kaveri",
            "layer_ids": [layer_id],
        },
    )
    assert nodata.status_code == 200
    assert nodata.json()["layers"][0]["value"] is None
    assert nodata.json()["layers"][0]["valid"] is False
    assert "NoData" in nodata.json()["layers"][0]["reason"]

    preview = client.get(f"/api/gis/layers/{layer_id}/preview.png?river_id=kaveri")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert preview.content.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(BytesIO(preview.content)) as image:
        alpha = np.asarray(image.convert("RGBA"))[..., 3]
        assert np.any(alpha == 0)
        assert np.any(alpha > 0)


def test_gis_catalog_exposes_persisted_water_mask_and_polygons(tmp_path, monkeypatch):
    _configure_gis_fixture(tmp_path, monkeypatch)
    analysis_id = "11111111-2222-4333-8444-555555555555"
    output_directory = tmp_path / "water-output"
    output_directory.mkdir()
    mask_path = output_directory / "water-mask.tif"
    with rasterio.open(
        mask_path,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="uint8",
        crs="EPSG:32643",
        transform=from_origin(500000, 1700000, 10, 10),
        nodata=255,
    ) as dataset:
        dataset.write(np.array([[0, 1], [255, 1]], dtype=np.uint8), 1)
    (output_directory / "water-polygons.geojson").write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "id": "candidate-1",
                "properties": {"status": "unvalidated_candidate"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[75.0, 15.0], [75.001, 15.0], [75.001, 15.001], [75.0, 15.001], [75.0, 15.0]]],
                },
            }],
        }),
        encoding="utf-8",
    )
    result = {
        "analysis_id": analysis_id,
        "analysis_type": "water_mask",
        "status": "unvalidated_candidate",
        "river_id": "kaveri",
        "source_product_id": "S1_TEST",
        "acquisition_start": "2026-11-07T00:47:52Z",
        "mission": "Sentinel-1",
        "valid_pixel_count": 3,
    }
    monkeypatch.setattr(gis_explorer, "_analysis_records", lambda _river_id: [result])
    monkeypatch.setattr(analysis, "_analysis_directory", lambda _analysis_id: output_directory)
    client = TestClient(app)

    catalog = client.get("/api/gis/layers?river_id=kaveri").json()["layers"]
    mask = next(layer for layer in catalog if layer["layer_id"] == f"water-mask-{analysis_id}")
    polygons = next(layer for layer in catalog if layer["layer_id"] == f"water-polygons-{analysis_id}")
    assert mask["status"] == "available"
    assert mask["valid_pixel_count"] == 3
    assert mask["evidence_status"] == "unvalidated_candidate"
    assert "not a verified" in mask["provenance"]
    assert polygons["status"] == "available"
    assert client.get(f"/api/gis/layers/{polygons['layer_id']}/features?river_id=kaveri").json()["features"][0]["id"] == "candidate-1"
    download = client.get(f"/api/gis/layers/{mask['layer_id']}/download?river_id=kaveri")
    assert download.status_code == 200
    with rasterio.MemoryFile(download.content) as memory_file:
        with memory_file.open() as dataset:
            assert dataset.nodata == 255
            assert dataset.read(1)[0, 1] == 1


def test_geojson_import_export_and_removal_are_scoped_to_temporary_uploads(tmp_path, monkeypatch):
    _configure_gis_fixture(tmp_path, monkeypatch)
    client = TestClient(app)
    collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "test-point",
                "properties": {"name": "sample", "value": 2},
                "geometry": {"type": "Point", "coordinates": [75.0, 15.0]},
            }
        ],
    }
    imported = client.post(
        "/api/gis/layers/import",
        files={"file": ("sample.geojson", json.dumps(collection).encode(), "application/geo+json")},
    )
    assert imported.status_code == 201
    layer = imported.json()["layer"]
    assert layer["temporary"] is True
    assert layer["feature_count"] == 1

    features = client.get(f"/api/gis/layers/{layer['layer_id']}/features")
    assert features.status_code == 200
    assert features.json()["features"][0]["properties"]["name"] == "sample"
    csv_download = client.get(
        f"/api/gis/layers/{layer['layer_id']}/download?format=csv"
    )
    assert csv_download.status_code == 200
    assert "name,value" in csv_download.text
    assert "sample,2" in csv_download.text

    removed = client.delete(f"/api/gis/layers/{layer['layer_id']}")
    assert removed.status_code == 200
    assert client.get(f"/api/gis/layers/{layer['layer_id']}/metadata").status_code == 404


def test_geojson_crs_and_geometry_validation_and_measurements(tmp_path, monkeypatch):
    _configure_gis_fixture(tmp_path, monkeypatch)
    client = TestClient(app)
    invalid = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:32643"}},
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "Point", "coordinates": [75.0, 15.0]},
        }],
    }
    rejected = client.post(
        "/api/gis/layers/import",
        files={"file": ("projected.geojson", json.dumps(invalid).encode(), "application/geo+json")},
    )
    assert rejected.status_code == 422
    assert "EPSG:4326" in rejected.json()["detail"]

    measured = client.post(
        "/api/gis/measure",
        json={
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[75.0, 15.0], [75.001, 15.0], [75.001, 15.001], [75.0, 15.001], [75.0, 15.0]]],
            }
        },
    )
    assert measured.status_code == 200
    assert measured.json()["length_m"] > 0
    assert measured.json()["area_m2"] > 0
    assert "32643" in measured.json()["measurement_crs"]

    invalid_geometry = client.post(
        "/api/gis/measure",
        json={"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}},
    )
    assert invalid_geometry.status_code == 422
