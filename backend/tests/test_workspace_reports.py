import base64
import re
import zlib
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from app.main import app
from app.services import acquisitions, sentinel2, vegetation_validation

client = TestClient(app)


def page_text(pdf: bytes) -> bytes:
    pages = []
    for stream in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.DOTALL):
        try:
            pages.append(zlib.decompress(base64.a85decode(stream.strip().removesuffix(b"~>"))))
        except (ValueError, zlib.error):
            continue
    return b"\n".join(pages)


@pytest.fixture
def report_data(monkeypatch, tmp_path):
    rivers = [
        {"river_id": river, "nisar_products": [], "observations": []}
        for river in ("kaveri", "tungabhadra")
    ]
    monkeypatch.setattr(acquisitions, "get_catalog_status", lambda: SimpleNamespace(
        model_dump=lambda **kwargs: {"rivers": rivers}
    ))
    record = {
        "river_id": "kaveri", "item_id": "TEST-OBSERVATION",
        "status": "processed", "valid_pixel_count": 4,
        "acquisition_datetime": "2026-01-02T00:00:00Z",
        "resolution_m": 20,
    }
    monkeypatch.setattr(sentinel2, "_load_catalog", lambda: [record])
    monkeypatch.setattr(vegetation_validation, "list_assessments", lambda river: [])
    paths = {}
    for index, value in (("ndvi", 0.1), ("evi", 0.4), ("ndmi", -0.5)):
        path = tmp_path / f"{index}.tif"
        with rasterio.open(
            path, "w", driver="GTiff", width=3, height=2, count=1, dtype="float32",
            crs="EPSG:4326", transform=from_origin(76, 15, 0.001, 0.001), nodata=-9999,
        ) as dataset:
            dataset.write(np.array([[value, value, -9999], [value, -9999, -9999]], dtype="float32"), 1)
        paths[index] = path
    monkeypatch.setattr(sentinel2, "_cached_raster_path", lambda record, index: paths[index])
    return record


@pytest.mark.parametrize("workspace", [
    "Overview", "Map explorer", "Change analysis", "Impact explorer",
    "Agriculture", "Forest monitoring",
])
def test_workspace_report_without_candidate(report_data, workspace):
    response = client.post("/api/reports/workspace", json={
        "workspace": workspace, "river_id": "kaveri",
    })
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "Kaveri" in response.headers["content-disposition"]
    assert workspace.replace(" ", "-") in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF-")
    text = page_text(response.content)
    assert workspace.encode() in text
    assert b"No AI model or external AI service was used" in text
    assert b"Unavailable" in text


@pytest.mark.parametrize(("index", "mean"), [
    ("ndvi", b"0.1000"), ("evi", b"0.4000"), ("ndmi", b"-0.5000"),
])
def test_selected_raster_and_catalog_mismatch(report_data, index, mean):
    response = client.post("/api/reports/workspace", json={
        "workspace": "Agriculture", "river_id": "kaveri",
        "vegetation_river_id": "kaveri", "vegetation_item_id": "TEST-OBSERVATION",
        "index_name": index,
    })
    assert response.status_code == 200
    text = page_text(response.content)
    assert index.upper().encode() in text
    assert b"TEST-OBSERVATION" in text
    assert mean in text
    assert b"NOT_VALIDATED" in text
    if index == "ndvi":
        assert b"discrepancy has not been resolved" in text
    else:
        assert b"refer to NDVI" in text


def test_report_rejects_incompatible_or_unknown_observation(report_data):
    selection = {
        "workspace": "Agriculture", "river_id": "tungabhadra",
        "vegetation_river_id": "kaveri", "vegetation_item_id": "TEST-OBSERVATION",
        "index_name": "ndvi",
    }
    assert client.post("/api/reports/workspace", json=selection).status_code == 422
    selection["river_id"] = "kaveri"
    selection["vegetation_item_id"] = "missing"
    assert client.post("/api/reports/workspace", json=selection).status_code == 422


def test_report_includes_assessment_provenance(report_data, monkeypatch):
    monkeypatch.setattr(vegetation_validation, "list_assessments", lambda river: [{
        "status": "VALIDATION_FAILED", "reason": "Criteria not met",
        "protocol": {
            "item_id": "TEST-OBSERVATION", "domain": "forest", "index_name": "ndmi",
            "reference_dataset": "Independent fixture", "landcover_dataset": "Cover fixture",
            "methodology": "Sample comparison",
        },
        "metrics": {"rmse": 0.2, "mae": 0.1, "bias": 0.05, "common_target_pixels": 20},
        "limitations": ["Fixture limitation"],
    }])
    response = client.post("/api/reports/workspace", json={
        "workspace": "Forest monitoring", "river_id": "kaveri",
        "vegetation_river_id": "kaveri", "vegetation_item_id": "TEST-OBSERVATION",
        "index_name": "ndmi",
    })
    assert response.status_code == 200
    text = page_text(response.content)
    for expected in (b"VALIDATION_FAILED", b"Independent fixture", b"Cover fixture",
                     b"RMSE 0.2000", b"Fixture limitation"):
        assert expected in text
