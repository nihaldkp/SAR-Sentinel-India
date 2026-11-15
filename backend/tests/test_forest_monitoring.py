import csv
import json
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin
from rasterio.warp import transform, transform_bounds
from shapely.geometry import shape

from app.main import app
from app.services import acquisition_jobs, acquisitions, forest_monitoring, sentinel2


def _write_source(path: Path, values: np.ndarray, *, resolution: int, crs: str, origin: tuple[float, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype=values.dtype,
        crs=crs,
        transform=from_origin(origin[0], origin[1], resolution, resolution),
        nodata=0,
    ) as dataset:
        dataset.write(values, 1)


def test_windowed_validity_respects_source_mask(tmp_path):
    source_path = tmp_path / "masked-source.tif"
    values = np.ones((100, 100), dtype=np.uint8)
    with rasterio.open(
        source_path,
        "w",
        driver="GTiff",
        width=100,
        height=100,
        count=1,
        dtype="uint8",
        crs="EPSG:32643",
        transform=from_origin(0, 2000, 10, 10),
    ) as dataset:
        dataset.write(values, 1)
        mask = np.full(values.shape, 255, dtype=np.uint8)
        mask[:20, :20] = 0
        dataset.write_mask(mask)

    with rasterio.open(source_path) as dataset:
        validity = forest_monitoring._windowed_validity(
            dataset,
            from_origin(0, 2000, 20, 20),
            rasterio.crs.CRS.from_epsg(32643),
            (50, 50),
        )

    assert not validity[0, 0]
    assert validity[10, 10]
    assert validity[-1, -1]


def _fixture_assets(tmp_path: Path, monkeypatch, *, all_cloud: bool = False):
    crs = "EPSG:32643"
    width = height = 512
    center_x, center_y = 500000, 1250000
    origin = (center_x - 5120, center_y + 5120)
    scl = np.full((height, width), 4, dtype=np.uint8)
    scl[170:190, 170:190] = 8
    scl[200:220, 200:220] = 3
    scl[230:250, 230:250] = 6
    scl[260:280, 260:280] = 7
    scl[165:285, 165:285] = 8
    if all_cloud:
        scl[:] = 9

    bands = {
        "B02": np.full((height * 2, width * 2), 500, dtype=np.uint16),
        "B04": np.full((height * 2, width * 2), 1000, dtype=np.uint16),
        "B08": np.full((height * 2, width * 2), 5000, dtype=np.uint16),
        "B11": np.full((height, width), 2000, dtype=np.uint16),
        "SCL": scl,
    }
    for name in ("B02", "B04", "B08"):
        bands[name][330:560, 330:560] = 4000
    bands["B11"][330:340, 330:340] = 0
    assets = {}
    for name, values in bands.items():
        resolution = 10 if name in {"B02", "B04", "B08"} else 20
        path = tmp_path / "source" / f"{name}.tif"
        _write_source(path, values, resolution=resolution, crs=crs, origin=origin)
        assets[name] = str(path)

    west, south, east, north = transform_bounds(
        crs, "EPSG:4326", origin[0], origin[1] - height * 20,
        origin[0] + width * 20, origin[1], densify_pts=21,
    )
    line_x, line_y = transform(
        crs,
        "EPSG:4326",
        [center_x - 1000, center_x + 1000],
        [center_y, center_y],
    )
    record = {
        "river_id": "kaveri",
        "item_id": "synthetic-s2-item",
        "status": "processed",
        "acquisition_datetime": "2026-11-13T05:10:41Z",
        "source": "Microsoft Planetary Computer",
        "collection": "sentinel-2-l2a",
        "stac_item_url": "https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-2-l2a/items/synthetic-s2-item",
        "footprint": {
            "type": "Polygon",
            "coordinates": [[
                [west, south], [east, south], [east, north], [west, north], [west, south],
            ]],
        },
        "assets": {
            name: f"https://sentinel2l2a01.blob.core.windows.net/sentinel2/{name}.tif"
            for name in bands
        },
    }
    monkeypatch.setattr(sentinel2, "_load_catalog", lambda: [record])
    monkeypatch.setattr(forest_monitoring, "_river_geometry", lambda _: {
        "type": "LineString",
        "coordinates": [[line_x[0], line_y[0]], [line_x[1], line_y[1]]],
    })
    monkeypatch.setattr(
        forest_monitoring,
        "_signed_assets",
        lambda _: assets,
    )
    monkeypatch.setattr(
        acquisitions,
        "CATALOG_PATH",
        tmp_path / "catalog.sqlite3",
    )
    monkeypatch.setattr(
        forest_monitoring,
        "DATA_ROOT",
        tmp_path / "forest-output",
    )
    return record


def test_forest_analysis_builds_projected_zones_masks_clouds_and_writes_real_outputs(tmp_path, monkeypatch) -> None:
    _fixture_assets(tmp_path, monkeypatch)

    result = forest_monitoring.process_item("kaveri", "synthetic-s2-item", [100, 500])

    assert result["status"] == "completed"
    assert result["processing_parameters"]["target_crs"] == "EPSG:32643"
    assert result["processing_parameters"]["included_scl_classes"] == [4, 5]
    assert result["processing_parameters"]["excluded_scl_classes"] == [0, 1, 2, 3, 6, 7, 8, 9, 10, 11]
    assert result["processing_parameters"]["output_nodata"] == -9999.0
    assert result["grid"]["transform"] == [20.0, 0.0, 498500.0, 0.0, -20.0, 1250500.0, 0.0, 0.0, 1.0]
    assert result["source_footprint_wgs84"]["type"] == "Polygon"
    assert [zone["zone_id"] for zone in result["zones"]] == ["0-100m", "100-500m"]
    for zone in result["zones"]:
        assert zone["zone_area_km2"] > 0
        assert 0 < zone["valid_data_coverage_percent"] < 100
        assert zone["scl_masked_pixel_count"] > 0
        assert zone["ndvi"]["mean"] == pytest.approx((0.5 - 0.1) / (0.5 + 0.1), abs=0.01)
        assert zone["evi"]["mean"] is not None
        assert zone["ndmi"]["mean"] == pytest.approx((0.5 - 0.2) / (0.5 + 0.2), abs=0.01)
    assert result["tree_cover"]["status"] == "not_available"
    assert result["temporal_change"]["status"] == "insufficient_observations"
    assert result["river_vegetation_relationship"]["status"] == "insufficient_temporal_overlap"
    assert set(result["output_sha256"]) == {
        "zones.geojson", "stats.csv", "ndvi.tif", "evi.tif", "ndmi.tif",
    }

    analysis_id = result["analysis_id"]
    summary = forest_monitoring.get_analysis(analysis_id)
    assert summary["analysis_id"] == analysis_id
    zones = json.loads(forest_monitoring.get_output_path(analysis_id, "zones.geojson").read_text())
    assert all(shape(feature["geometry"]).is_valid for feature in zones["features"])
    with rasterio.open(forest_monitoring.get_output_path(analysis_id, "ndvi.tif")) as raster:
        assert raster.nodata == -9999.0
        assert raster.crs.to_string() == "EPSG:32643"
        assert tuple(raster.transform) == tuple(result["grid"]["transform"])
    with forest_monitoring.get_output_path(analysis_id, "stats.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert float(rows[0]["ndvi_mean"]) == pytest.approx(result["zones"][0]["ndvi"]["mean"])


def test_forest_analysis_is_idempotent_and_preserves_no_data(tmp_path, monkeypatch) -> None:
    _fixture_assets(tmp_path, monkeypatch, all_cloud=True)

    first = forest_monitoring.process_item("kaveri", "synthetic-s2-item", [500])
    monkeypatch.setattr(
        forest_monitoring,
        "_signed_assets",
        lambda _: pytest.fail("A completed analysis should be reused."),
    )
    repeated = forest_monitoring.process_item("kaveri", "synthetic-s2-item", [500])

    assert repeated == first
    assert first["status"] == "no_data"
    assert first["zones"][0]["valid_pixel_count"] == 0
    assert first["zones"][0]["ndvi"]["mean"] is None
    with pytest.raises(FileNotFoundError, match="output is not available"):
        forest_monitoring.get_output_path(first["analysis_id"], "ndvi.tif")


def test_forest_api_observations_references_and_downloads(tmp_path, monkeypatch) -> None:
    record = _fixture_assets(tmp_path, monkeypatch)
    observation = forest_monitoring.list_observations("kaveri")
    assert observation["temporal_change_status"] == "insufficient_observations"
    assert observation["observations"][0]["has_source_assets"] is True
    assert forest_monitoring.list_references()["tree_cover_statistics_status"] == "not_available"

    result = forest_monitoring.process_item("kaveri", record["item_id"], [500])
    client = TestClient(app)
    summary_response = client.get(f"/api/forest/analyses/{result['analysis_id']}")
    assert summary_response.status_code == 200
    assert summary_response.json()["status"] == "completed"
    zones_response = client.get(f"/api/forest/analyses/{result['analysis_id']}/zones.geojson")
    assert zones_response.status_code == 200
    assert zones_response.headers["content-type"].startswith("application/geo+json")
    stats_response = client.get(f"/api/forest/analyses/{result['analysis_id']}/stats.csv")
    assert stats_response.status_code == 200
    raster_response = client.get(f"/api/forest/analyses/{result['analysis_id']}/indices/ndvi.tif")
    assert raster_response.status_code == 200
    preview_response = client.get(f"/api/forest/analyses/{result['analysis_id']}/preview/ndvi.png")
    assert preview_response.status_code == 200
    assert preview_response.headers["content-type"] == "image/png"
    evidence_response = client.get(
        f"/api/forest/analyses/{result['analysis_id']}/evidence-summary"
    )
    assert evidence_response.status_code == 200
    assert evidence_response.json()["analysis_mode"] == "deterministic_evidence_summary"
    assert "do not establish tree cover" in evidence_response.json()["conclusion"]
    assert client.get("/api/forest/references").json()["tree_cover_statistics_status"] == "not_available"


def test_worldcover_import_tree_cover_job_and_downloads(tmp_path, monkeypatch) -> None:
    record = _fixture_assets(tmp_path, monkeypatch)
    analysis = forest_monitoring.process_item("kaveri", record["item_id"], [500])
    source_path = tmp_path / "worldcover.tif"
    values = np.full((2000, 2000), 20, dtype=np.uint8)
    values[800:1200, 800:1200] = 10
    with rasterio.open(
        source_path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="uint8",
        crs="EPSG:32643",
        transform=from_origin(490000, 1260000, 10, 10),
        nodata=0,
    ) as dataset:
        dataset.write(values, 1)

    client = TestClient(app)
    payload = source_path.read_bytes()
    invalid_upload = client.post(
        "/api/forest/references/import",
        data={"dataset_id": "esa-worldcover-2021-v200"},
        files={"reference_file": ("invalid.tif", b"not a GeoTIFF", "image/tiff")},
    )
    assert invalid_upload.status_code == 422
    import_response = client.post(
        "/api/forest/references/import",
        data={"dataset_id": "esa-worldcover-2021-v200"},
        files={"reference_file": ("worldcover.tif", payload, "image/tiff")},
    )
    assert import_response.status_code == 201
    reference = import_response.json()
    repeated = forest_monitoring.import_worldcover_reference(
        "esa-worldcover-2021-v200", payload
    )
    assert repeated["reference_id"] == reference["reference_id"]
    assert client.get("/api/forest/references").json()["tree_cover_statistics_status"] == "available_after_import"

    monkeypatch.setattr(acquisition_jobs, "_schedule", lambda _: None)
    job_response = client.post(
        f"/api/forest/analyses/{analysis['analysis_id']}/tree-cover-jobs",
        json={"reference_id": reference["reference_id"]},
    )
    assert job_response.status_code == 202
    job_id = job_response.json()["job_id"]
    acquisition_jobs._execute(job_id)
    job = acquisition_jobs.get_job(job_id)
    assert job.status == "completed"
    statistics_response = client.get(job.output_references["tree_cover_statistics"])
    assert statistics_response.status_code == 200
    statistics = statistics_response.json()
    assert statistics["status"] == "completed"
    assert statistics["source_crs"] == "EPSG:32643"
    assert any(zone["tree_cover_pixel_count"] > 0 for zone in statistics["zones"])
    assert any(zone["valid_data_coverage_percent"] > 0 for zone in statistics["zones"])

    raster_response = client.get(job.output_references["tree_cover_raster"])
    assert raster_response.status_code == 200
    assert raster_response.headers["content-type"].startswith("image/tiff")
    with rasterio.open(BytesIO(raster_response.content)) as downloaded:
        values = downloaded.read(1, masked=True)
        assert downloaded.crs.to_string() == "EPSG:6933"
        assert downloaded.nodata == 255
        assert np.count_nonzero(~np.ma.getmaskarray(values)) > 0
        assert np.any(values.compressed() == 1)
    preview_response = client.get(
        f"/api/forest/analyses/{analysis['analysis_id']}/tree-cover/"
        f"{reference['reference_id']}/preview.png"
    )
    assert preview_response.status_code == 200
    assert preview_response.headers["content-type"] == "image/png"
    with rasterio.open(BytesIO(preview_response.content)) as preview:
        assert preview.count == 4
        assert preview.width <= 512
        assert preview.height <= 512
    csv_response = client.get(
        f"/api/forest/analyses/{analysis['analysis_id']}/tree-cover/"
        f"{reference['reference_id']}/stats.csv"
    )
    assert csv_response.status_code == 200
    assert len(list(csv.DictReader(csv_response.text.splitlines()))) == 1
    evidence_response = client.get(
        f"/api/forest/analyses/{analysis['analysis_id']}/evidence-summary",
        params={"reference_id": reference["reference_id"]},
    )
    assert evidence_response.status_code == 200
    tree_cover_percent = statistics["zones"][0]["tree_cover_percent_of_valid_area"]
    assert any(
        f"{tree_cover_percent:.1f}%" in finding
        for finding in evidence_response.json()["observed_zone_summaries"]
    )
    assert "cannot establish later loss" in evidence_response.json()["conclusion"]

    unknown_path = tmp_path / "unknown-classes.tif"
    with rasterio.open(
        unknown_path,
        "w",
        driver="GTiff",
        width=2000,
        height=2000,
        count=1,
        dtype="uint8",
        crs="EPSG:32643",
        transform=from_origin(490000, 1260000, 10, 10),
        nodata=0,
    ) as dataset:
        dataset.write(np.full((2000, 2000), 11, dtype=np.uint8), 1)
    unknown_reference = forest_monitoring.import_worldcover_reference(
        "esa-worldcover-2021-v200", unknown_path.read_bytes()
    )
    insufficient = forest_monitoring.calculate_tree_cover_statistics(
        analysis["analysis_id"], unknown_reference["reference_id"]
    )
    assert insufficient["status"] == "no_data"
    assert all(zone["valid_pixel_count"] == 0 for zone in insufficient["zones"])
    with pytest.raises(FileNotFoundError, match="Tree-cover output"):
        forest_monitoring.get_tree_cover_output_path(
            analysis["analysis_id"], unknown_reference["reference_id"], "tree-cover.tif"
        )
    no_data_job_response = client.post(
        f"/api/forest/analyses/{analysis['analysis_id']}/tree-cover-jobs",
        json={"reference_id": unknown_reference["reference_id"]},
    )
    assert no_data_job_response.status_code == 202
    no_data_job_id = no_data_job_response.json()["job_id"]
    acquisition_jobs._execute(no_data_job_id)
    no_data_job = acquisition_jobs.get_job(no_data_job_id)
    assert no_data_job.status == "no_data"
    assert no_data_job.current_stage == (
        "No recognized reference classes; coverage report generated and raster withheld"
    )
    assert "tree_cover_raster" not in no_data_job.output_references


def test_forest_analysis_job_preserves_parameters_and_publishes_outputs(tmp_path, monkeypatch) -> None:
    record = _fixture_assets(tmp_path, monkeypatch)
    captured = {}
    monkeypatch.setattr(acquisition_jobs, "_schedule", lambda _: None)

    def fake_process(river_id, item_id, distances):
        captured.update({"river_id": river_id, "item_id": item_id, "distances": distances})
        return {
            "analysis_id": "a" * 64,
            "status": "completed",
        }

    monkeypatch.setattr(forest_monitoring, "process_item", fake_process)
    request = {
        "river_id": "kaveri",
        "item_id": record["item_id"],
        "zone_distances_m": [250, 750, 1500],
    }
    response = TestClient(app).post("/api/forest/analyses", json=request)

    assert response.status_code == 202
    job = response.json()
    acquisition_jobs._execute(job["job_id"])
    finished = acquisition_jobs.get_job(job["job_id"])
    assert finished.status == "completed"
    assert captured == {
        "river_id": "kaveri",
        "item_id": record["item_id"],
        "distances": [250, 750, 1500],
    }
    assert finished.output_references["analysis"] == f"/api/forest/analyses/{'a' * 64}"


def test_forest_analysis_api_rejects_non_increasing_zone_distances() -> None:
    response = TestClient(app).post("/api/forest/analyses", json={
        "river_id": "kaveri",
        "item_id": "missing",
        "zone_distances_m": [500, 300],
    })
    assert response.status_code == 422


@pytest.mark.parametrize(
    "distances",
    ([0, 100], [100, 100], [500, 300], [6000], [1, 2, 3, 4, 5, 6, 7]),
)
def test_forest_zone_distance_validation_rejects_invalid_values(distances) -> None:
    with pytest.raises(ValueError):
        forest_monitoring.validate_zone_distances(list(distances))
