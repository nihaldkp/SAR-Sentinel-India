import io
from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from app.main import app
from app.services import sentinel2, vegetation_validation


@pytest.fixture
def assessment_setup(tmp_path, monkeypatch):
    root = tmp_path / "data" / "acquisitions" / "sentinel2"
    monkeypatch.setattr(sentinel2, "DATA_ROOT", root)
    monkeypatch.setattr(vegetation_validation, "STORE", tmp_path / "assessments.sqlite3")
    path = root / "kaveri" / "item" / "ndvi.tif"
    path.parent.mkdir(parents=True)
    values = np.arange(25, dtype="float32").reshape(5, 5) / 30
    with rasterio.open(path, "w", driver="GTiff", width=5, height=5, count=1,
                       dtype="float32", crs="EPSG:32643",
                       transform=from_origin(500000, 1500000, 20, 20), nodata=-9999) as dataset:
        dataset.write(values, 1)
    record = {
        "river_id": "kaveri", "item_id": "item", "status": "processed",
        "source": "Microsoft Planetary Computer", "collection": "sentinel-2-l2a",
        "acquisition_datetime": "2026-11-13T05:00:00Z", "processor_version": "test",
        "output_paths": {"ndvi": "acquisitions/sentinel2/kaveri/item/ndvi.tif"},
    }
    monkeypatch.setattr(sentinel2, "_load_catalog", lambda: [record.copy()])
    protocol = {
        "river_id": "kaveri", "item_id": "item", "index_name": "ndvi", "domain": "agriculture",
        "reference_dataset": "Reviewed measurements", "reference_provider": "Provider",
        "reference_source": "Field instrument", "reference_license": "Fixture", "reference_acquisition_datetime": "2026-11-13T05:00:00Z",
        "reference_resolution_m": 20, "landcover_dataset": "Reviewed labels", "landcover_provider": "Provider",
        "landcover_source": "Field survey", "landcover_license": "Fixture", "landcover_acquisition_datetime": "2026-11-13T05:00:00Z",
        "landcover_resolution_m": 20, "reviewer": "Reviewer", "review_date": "2026-11-14", "methodology": "Independent survey",
        "limitations": ["Fixture"], "independence_attested": True, "review_completed": True,
        "no_pseudoreplication_attested": True,
        "maximum_time_difference_days": 1, "minimum_common_pixels": 3,
        "minimum_coverage_fraction": 0.1, "minimum_pixels_per_class": 2,
        "spatial_block_size_pixels": 2, "minimum_target_blocks": 1, "maximum_rmse": 0.2,
    }
    return TestClient(app), path, values, protocol


def reference_bytes(values, offset=0.1, transform=None, labels=None):
    classes = np.repeat(np.arange(5, dtype="float32"), 5).reshape(5, 5) if labels is None else labels
    with MemoryFile() as memory:
        with memory.open(driver="GTiff", width=5, height=5, count=2, dtype="float32",
                         crs="EPSG:32643", transform=transform or from_origin(500000, 1500000, 20, 20),
                         nodata=-9999) as dataset:
            dataset.write(values + offset, 1)
            dataset.write(classes, 2)
        return memory.read()


@pytest.mark.parametrize(("offset", "minimum_pixels", "expected"), [
    (0.1, 3, "VALIDATED"),
    (0.3, 3, "VALIDATION_FAILED"),
    (0.1, 6, "INSUFFICIENT_REFERENCE_DATA"),
])
def test_predeclared_assessment_persists_results(assessment_setup, offset, minimum_pixels, expected):
    client, _, values, protocol = assessment_setup
    protocol["minimum_common_pixels"] = minimum_pixels
    created = client.post("/api/sentinel2/index-assessments", json=protocol)
    assert created.status_code == 201
    assert created.json()["status"] == "NOT_VALIDATED"
    assessment_id = created.json()["assessment_id"]
    reference = reference_bytes(values, offset)
    response = client.post(f"/api/sentinel2/index-assessments/{assessment_id}/evaluate",
                           files={"reference_file": ("reference.tif", io.BytesIO(reference), "image/tiff")})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == expected
    assert result["metrics"]["common_target_pixels"] == 5
    if expected == "INSUFFICIENT_REFERENCE_DATA":
        assert result["metrics"]["rmse"] is None
    else:
        assert result["metrics"]["rmse"] == pytest.approx(offset)
    assert [entry["count"] for entry in result["metrics"]["classes"].values()] == [5, 5, 5, 5, 5]
    assert client.get(f"/api/sentinel2/index-assessments/{assessment_id}").json() == result
    assert client.get(f"/api/sentinel2/index-assessments/{assessment_id}/reference").content == reference
    assert client.post(f"/api/sentinel2/index-assessments/{assessment_id}/evaluate",
                       files={"reference_file": ("reference.tif", reference_bytes(values), "image/tiff")}).status_code == 422
    observation = client.get("/api/sentinel2/observations", params={"river_id": "kaveri"}).json()["observations"][0]
    assert observation["vegetation_validation"]["agriculture:ndvi"]["status"] == expected
    assert observation["vegetation_validation"]["forest:ndvi"]["status"] == "NOT_VALIDATED"
    assert "unavailable" in observation["vegetation_validation"]["forest:evi"]["reason"]


def test_requires_independence_time_compatibility_and_same_grid(assessment_setup):
    client, _, values, protocol = assessment_setup
    assert client.post("/api/sentinel2/index-assessments", json={**protocol, "independence_attested": False}).status_code == 422
    assert client.post("/api/sentinel2/index-assessments", json={**protocol, "no_pseudoreplication_attested": False}).status_code == 422
    assert client.post("/api/sentinel2/index-assessments", json={**protocol, "reference_acquisition_datetime": "2020-01-01T00:00:00Z"}).status_code == 422
    assessment_id = client.post("/api/sentinel2/index-assessments", json=protocol).json()["assessment_id"]
    shifted = reference_bytes(values, transform=from_origin(500020, 1500000, 20, 20))
    result = client.post(f"/api/sentinel2/index-assessments/{assessment_id}/evaluate",
                         files={"reference_file": ("reference.tif", shifted, "image/tiff")})
    assert result.status_code == 422
    assert "identical" in result.json()["detail"]
    assert client.get(f"/api/sentinel2/index-assessments/{assessment_id}").json()["status"] == "NOT_VALIDATED"


def test_changed_candidate_invalidates_recorded_result(assessment_setup):
    client, path, values, protocol = assessment_setup
    assessment_id = client.post("/api/sentinel2/index-assessments", json=protocol).json()["assessment_id"]
    client.post(f"/api/sentinel2/index-assessments/{assessment_id}/evaluate",
                files={"reference_file": ("reference.tif", reference_bytes(values), "image/tiff")})
    with rasterio.open(path, "r+") as dataset:
        dataset.write(values + 0.5, 1)
    result = client.get(f"/api/sentinel2/index-assessments/{assessment_id}").json()
    assert result["status"] == "NOT_VALIDATED"
    assert result["recorded_status"] == "VALIDATED"


def test_forest_assessment_uses_natural_forest_and_distinguishes_plantations(assessment_setup):
    client, _, values, protocol = assessment_setup
    protocol["domain"] = "forest"
    assessment_id = client.post("/api/sentinel2/index-assessments", json=protocol).json()["assessment_id"]
    result = client.post(f"/api/sentinel2/index-assessments/{assessment_id}/evaluate",
                         files={"reference_file": ("reference.tif", reference_bytes(values), "image/tiff")}).json()
    assert result["status"] == "VALIDATED"
    assert result["target_class"] == "natural_forest"
    assert result["metrics"]["classes"]["natural_forest"]["candidate_mean"] == pytest.approx(values[2].mean())
    assert result["metrics"]["classes"]["plantation"]["candidate_mean"] == pytest.approx(values[3].mean())


def test_unknown_reference_class_is_rejected(assessment_setup):
    client, _, values, protocol = assessment_setup
    assessment_id = client.post("/api/sentinel2/index-assessments", json=protocol).json()["assessment_id"]
    labels = np.full((5, 5), 5, dtype="float32")
    response = client.post(f"/api/sentinel2/index-assessments/{assessment_id}/evaluate",
                           files={"reference_file": ("reference.tif", reference_bytes(values, labels=labels), "image/tiff")})
    assert response.status_code == 422
    assert "labels must be" in response.json()["detail"]


def test_reference_nodata_is_not_used_in_agreement(assessment_setup):
    client, _, values, protocol = assessment_setup
    assessment_id = client.post("/api/sentinel2/index-assessments", json=protocol).json()["assessment_id"]
    reference = values.copy()
    reference[1, 0] = -9999
    response = client.post(f"/api/sentinel2/index-assessments/{assessment_id}/evaluate",
                           files={"reference_file": ("reference.tif", reference_bytes(reference, offset=0), "image/tiff")})
    result = response.json()
    assert result["status"] == "VALIDATED"
    assert result["metrics"]["common_target_pixels"] == 4
    assert result["metrics"]["rmse"] == 0


def test_in_progress_status_is_persisted_during_evaluation(assessment_setup, monkeypatch):
    client, _, values, protocol = assessment_setup
    assessment_id = client.post("/api/sentinel2/index-assessments", json=protocol).json()["assessment_id"]
    calculate = vegetation_validation._calculate

    def check_in_progress(path, content, settings):
        stored = vegetation_validation.get_assessment(assessment_id)
        assert stored["status"] == "VALIDATION_IN_PROGRESS"
        assert stored["reference_sha256"]
        return calculate(path, content, settings)

    monkeypatch.setattr(vegetation_validation, "_calculate", check_in_progress)
    response = client.post(f"/api/sentinel2/index-assessments/{assessment_id}/evaluate",
                           files={"reference_file": ("reference.tif", reference_bytes(values), "image/tiff")})
    assert response.json()["status"] == "VALIDATED"
