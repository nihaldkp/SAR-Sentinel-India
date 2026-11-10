from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin

from app.main import app
from app.schemas.integration import OutputRegistrationRequest
from app.services import acquisitions, integration

client = TestClient(app)
PRODUCT_ID = (
    "NISAR_L2_UR_GCOV_035_012_A_009_4005_DHDH_A_20261106T002520_"
    "20261106T002555_P05036_F_F_J_001"
)


@pytest.fixture
def configured_catalog(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "satellite_catalog.sqlite3")
    monkeypatch.setattr(acquisitions, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(
        acquisitions,
        "ACQUISITION_ROOT",
        tmp_path / "data" / "acquisitions",
    )
    monkeypatch.setattr(integration, "OUTPUT_ROOT", tmp_path / "outputs" / "integration")
    monkeypatch.setattr(integration, "_schedule", lambda _job_id: None)
    integration.configure_processing_adapters(sar=None, gis=None)

    product_path = acquisitions.ACQUISITION_ROOT / "tungabhadra" / PRODUCT_ID / f"{PRODUCT_ID}.h5"
    product_path.parent.mkdir(parents=True)
    product_path.write_bytes(b"fixture NISAR bytes")
    checksum = hashlib.sha256(product_path.read_bytes()).hexdigest()
    record = {
        "product_id": PRODUCT_ID,
        "acquisition_identifier": PRODUCT_ID,
        "acquisition_start": "2026-11-06T00:25:20+00:00",
        "acquisition_end": "2026-11-06T00:25:55+00:00",
        "product_level": "GCOV",
        "product_type": "GCOV",
        "download_status": "downloaded",
        "size_bytes": product_path.stat().st_size,
        "local_path": str(product_path.relative_to(tmp_path)),
        "sha256": checksum,
        "integrity_status": "sha256_fingerprint_only",
        "structure_verification_status": "verified",
        "provider_authenticity_status": "not_verified",
        "scientific_validation_status": "not_performed",
        "source_url_reference": "https://nisar.asf.earthdatacloud.nasa.gov/test.h5",
        "download_timestamp": "2026-11-06T01:00:00+00:00",
        "provider_checksum_algorithm": None,
        "provider_checksum": None,
    }
    monkeypatch.setattr(
        integration,
        "_product_records",
        lambda river_id=None: (
            [("tungabhadra", record, product_path)]
            if river_id in (None, "tungabhadra")
            else []
        ),
    )
    monkeypatch.setattr(
        acquisitions,
        "_nisar_product_record",
        lambda river_id, product_id: (
            record,
            product_path,
        )
        if river_id == "tungabhadra" and product_id == PRODUCT_ID
        else (_ for _ in ()).throw(FileNotFoundError("Fixture product not found.")),
    )
    return {"record": record, "product_path": product_path, "tmp_path": tmp_path}


def _processing_request() -> dict[str, Any]:
    return {
        "river_id": "tungabhadra",
        "product_id": PRODUCT_ID,
        "processing_config": {"frequency": "A", "polarizations": ["HH", "HV"]},
        "processing_version": "teammate-sar-0.1",
    }


def _gis_request(output_id: str) -> dict[str, Any]:
    return {
        "input_output_ids": [output_id],
        "analysis_type": "river_change_candidate",
        "river_id": "tungabhadra",
        "spatial_extent": {
            "type": "Polygon",
            "coordinates": [[[75.5, 14.0], [76.0, 14.0], [76.0, 14.5], [75.5, 14.5], [75.5, 14.0]]],
        },
        "acquisition_start": "2026-11-06T00:25:20+00:00",
        "acquisition_end": "2026-11-06T00:25:55+00:00",
        "analysis_config": {"minimum_area_m2": 25},
        "processing_version": "teammate-gis-0.1",
    }


def _make_sar_output(request: Any) -> OutputRegistrationRequest:
    output_directory = Path(request.output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        output_directory / "candidate-mask.tif",
        "w",
        driver="GTiff",
        width=1,
        height=1,
        count=1,
        dtype="uint8",
        crs="EPSG:32643",
        transform=from_origin(0, 0, 10, 10),
        nodata=255,
    ) as dataset:
        dataset.write(np.array([[1]], dtype="uint8"), 1)
    return OutputRegistrationRequest(
        outputs=[
            {
                "role": "candidate_mask",
                "storage_key": f"{request.job_id}/candidate-mask.tif",
                "output_type": "raster",
                "media_type": "image/tiff",
                "metadata": {
                    "crs": "EPSG:32643",
                    "width": 1,
                    "height": 1,
                    "transform": [10, 0, 0, 0, -10, 0],
                    "nodata": 255,
                    "units": "class_code",
                },
            }
        ],
        result_metadata={
            "classification_status": "unvalidated_candidate",
            "scientific_validation_status": "validated",
        },
    )


class MockSARAdapter:
    def process(self, request: Any) -> OutputRegistrationRequest:
        assert Path(request.local_file_path).is_file()
        assert request.acquisition.product_id == PRODUCT_ID
        return _make_sar_output(request)


class MockGISAdapter:
    def analyze(self, request: Any) -> OutputRegistrationRequest:
        assert len(request.input_outputs) == 1
        output_directory = Path(request.output_directory)
        output_directory.mkdir(parents=True, exist_ok=True)
        (output_directory / "candidate-result.geojson").write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [],
                    "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
                }
            ),
            encoding="utf-8",
        )
        return OutputRegistrationRequest(
            outputs=[
                {
                    "role": "candidate_result",
                    "storage_key": f"{request.job_id}/candidate-result.geojson",
                    "output_type": "vector",
                    "media_type": "application/geo+json",
                    "metadata": {"crs": "EPSG:4326", "geometry_type": "MultiPolygon"},
                }
            ],
            result_metadata={"status": "unvalidated_candidate"},
            spatial_results={"type": "FeatureCollection", "features": []},
            metrics={"candidate_feature_count": 0},
        )


def _completed_sar_job() -> tuple[str, str]:
    integration.configure_processing_adapters(sar=MockSARAdapter(), gis=None)
    response = client.post("/api/processing/jobs", json=_processing_request())
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    integration._execute(job_id)
    result = client.get(f"/api/processing/jobs/{job_id}")
    assert result.status_code == 200
    assert result.json()["status"] == "completed"
    output_id = result.json()["outputs"][0]["output_id"]
    return job_id, output_id


def test_verified_acquisitions_and_verification_api(
    configured_catalog: dict[str, Any],
) -> None:
    page = client.get("/api/integration/acquisitions")
    assert page.status_code == 200
    assert page.json()["total"] == 1
    acquisition = page.json()["items"][0]
    assert acquisition["product_id"] == PRODUCT_ID
    assert acquisition["structure_verification_status"] == "verified"
    assert acquisition["provider_authenticity_status"] == "not_verified"
    assert acquisition["scientific_validation_status"] == "not_performed"
    assert not Path(acquisition["file_reference"]).is_absolute()

    detail = client.get(f"/api/integration/acquisitions/tungabhadra/{PRODUCT_ID}")
    verification = client.get(
        f"/api/integration/acquisitions/tungabhadra/{PRODUCT_ID}/verification"
    )
    assert detail.status_code == verification.status_code == 200
    assert verification.json()["verification_scope"] == "recorded_download_verification"
    assert verification.json()["sha256"] == configured_catalog["record"]["sha256"]


def test_missing_acquisition_and_product_identity_mismatch_are_rejected(
    configured_catalog: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = client.get("/api/integration/acquisitions/tungabhadra/NISAR_NOT_CACHED")
    assert missing.status_code == 404

    mismatched_record = dict(configured_catalog["record"], product_id="NISAR_DIFFERENT_PRODUCT")
    monkeypatch.setattr(
        integration,
        "_product_records",
        lambda _river_id=None: [("tungabhadra", dict(configured_catalog["record"]), configured_catalog["product_path"])],
    )
    monkeypatch.setattr(
        acquisitions,
        "_nisar_product_record",
        lambda _river_id, _product_id: (mismatched_record, configured_catalog["product_path"]),
    )
    mismatch = client.get(f"/api/integration/acquisitions/tungabhadra/{PRODUCT_ID}")
    assert mismatch.status_code == 422
    assert "identity" in mismatch.json()["detail"].casefold()


def test_processing_submission_is_persistent_and_idempotent(
    configured_catalog: dict[str, Any],
) -> None:
    first = client.post("/api/processing/jobs", json=_processing_request())
    second = client.post("/api/processing/jobs", json=_processing_request())
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert first.json()["status"] == "blocked"
    assert first.json()["error_code"] == "adapter_unavailable"
    assert "registered" in first.json()["error_message"]
    listed = client.get("/api/processing/jobs?limit=1&offset=0")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert len(listed.json()["items"]) == 1


def test_processing_adapter_completes_job_and_registers_hashed_output(
    configured_catalog: dict[str, Any],
) -> None:
    integration.configure_processing_adapters(sar=MockSARAdapter(), gis=None)
    submitted = client.post("/api/processing/jobs", json=_processing_request())
    job_id = submitted.json()["job_id"]
    integration._execute(job_id)

    response = client.get(f"/api/processing/jobs/{job_id}")
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "completed"
    assert result["result_metadata"]["classification_status"] == "unvalidated_candidate"
    assert result["result_metadata"]["scientific_validation_status"] == "not_performed"
    provenance = result["result_metadata"]["provenance"]
    assert provenance["source_acquisition"]["product_id"] == PRODUCT_ID
    assert provenance["source_acquisition"]["sha256"] == configured_catalog["record"]["sha256"]
    assert provenance["source_acquisition"]["provider_authenticity_status"] == "not_verified"
    output = result["outputs"][0]
    assert (
        output["metadata"]["provenance"]["source_acquisition"]["sha256"]
        == configured_catalog["record"]["sha256"]
    )
    file_path = configured_catalog["tmp_path"] / "outputs" / "integration" / output["storage_key"]
    assert output["sha256"] == hashlib.sha256(file_path.read_bytes()).hexdigest()
    assert output["metadata"]["crs"] == "EPSG:32643"


def test_processing_registration_rejects_missing_file_and_path_traversal(
    configured_catalog: dict[str, Any],
) -> None:
    submitted = client.post("/api/processing/jobs", json=_processing_request())
    job_id = submitted.json()["job_id"]
    missing = client.post(
        f"/api/processing/jobs/{job_id}/outputs",
        json={
            "outputs": [
                {
                    "role": "raster",
                    "storage_key": f"{job_id}/missing.tif",
                    "output_type": "raster",
                    "media_type": "image/tiff",
                    "metadata": {
                        "crs": "EPSG:32643",
                        "width": 1,
                        "height": 1,
                        "transform": [10, 0, 0, 0, -10, 0],
                        "nodata": None,
                        "units": "not_applicable",
                    },
                }
            ]
        },
    )
    traversal = client.post(
        f"/api/processing/jobs/{job_id}/outputs",
        json={
            "outputs": [
                {
                    "role": "raster",
                    "storage_key": f"{job_id}/../outside.tif",
                    "output_type": "raster",
                    "media_type": "image/tiff",
                    "metadata": {
                        "crs": "EPSG:32643",
                        "width": 1,
                        "height": 1,
                        "transform": [10, 0, 0, 0, -10, 0],
                        "nodata": None,
                        "units": "not_applicable",
                    },
                }
            ]
        },
    )
    assert missing.status_code == 404
    assert traversal.status_code == 422


@pytest.mark.parametrize("invalid", ["malformed", "metadata_mismatch"])
def test_processing_registration_rejects_invalid_raster_contents(
    configured_catalog: dict[str, Any],
    invalid: str,
) -> None:
    submitted = client.post("/api/processing/jobs", json=_processing_request())
    job_id = submitted.json()["job_id"]
    output_directory = configured_catalog["tmp_path"] / "outputs" / "integration" / job_id
    output_directory.mkdir(parents=True)
    output_path = output_directory / "invalid.tif"
    metadata = {
        "crs": "EPSG:32643",
        "width": 1,
        "height": 1,
        "transform": [10, 0, 0, 0, -10, 0],
        "nodata": 255,
        "units": "class_code",
    }
    if invalid == "malformed":
        output_path.write_bytes(b"not a GeoTIFF")
    else:
        with rasterio.open(
            output_path,
            "w",
            driver="GTiff",
            width=1,
            height=1,
            count=1,
            dtype="uint8",
            crs="EPSG:32643",
            transform=from_origin(0, 0, 10, 10),
            nodata=255,
        ) as dataset:
            dataset.write(np.array([[1]], dtype="uint8"), 1)
        metadata["width"] = 2
    response = client.post(
        f"/api/processing/jobs/{job_id}/outputs",
        json={
            "outputs": [
                {
                    "role": "invalid_raster",
                    "storage_key": f"{job_id}/invalid.tif",
                    "output_type": "raster",
                    "media_type": "image/tiff",
                    "metadata": metadata,
                }
            ]
        },
    )
    assert response.status_code == 422
    assert "raster" in response.json()["detail"].casefold()


def test_gis_job_requires_registered_completed_inputs_and_valid_extent(
    configured_catalog: dict[str, Any],
) -> None:
    bad_river = client.post(
        "/api/gis/jobs",
        json={**_gis_request("missing-output"), "river_id": "not-a-river"},
    )
    invalid_extent = client.post(
        "/api/gis/jobs",
        json={
            **_gis_request("missing-output"),
            "spatial_extent": {"type": "Polygon", "coordinates": [[[181, 0], [0, 0], [0, 1], [181, 0]]]},
        },
    )
    demo_region = client.post(
        "/api/gis/jobs",
        json={
            **_gis_request("missing-output"),
            "river_id": None,
            "region_id": "krishna-karnataka",
        },
    )
    missing_output = client.post("/api/gis/jobs", json=_gis_request("missing-output"))
    assert bad_river.status_code == 422
    assert invalid_extent.status_code == 422
    assert demo_region.status_code == 422
    assert missing_output.status_code == 404


def test_gis_adapter_results_and_river_association_are_persisted(
    configured_catalog: dict[str, Any],
) -> None:
    _, output_id = _completed_sar_job()
    integration.configure_processing_adapters(sar=MockSARAdapter(), gis=MockGISAdapter())
    submitted = client.post("/api/gis/jobs", json=_gis_request(output_id))
    assert submitted.status_code == 202
    job_id = submitted.json()["job_id"]
    integration._execute(job_id)

    status = client.get(f"/api/gis/jobs/{job_id}")
    result = client.get(f"/api/gis/jobs/{job_id}/results")
    assert status.status_code == result.status_code == 200
    assert result.json()["status"] == "completed"
    assert result.json()["spatial_results"]["type"] == "FeatureCollection"
    assert result.json()["metrics"]["candidate_feature_count"] == 0
    assert result.json()["outputs"][0]["output_type"] == "vector"
    gis_provenance = result.json()["result_metadata"]["provenance"]
    assert gis_provenance["input_sources"][0]["source_acquisition"]["product_id"] == PRODUCT_ID
    assert result.json()["result_metadata"]["scientific_validation_status"] == "not_performed"
    association = client.post(
        f"/api/gis/jobs/{job_id}/association",
        json={"target_type": "river", "target_id": "tungabhadra"},
    )
    assert association.status_code == 200
    assert association.json()["target_id"] == "tungabhadra"
    assert len(client.get(f"/api/gis/jobs/{job_id}").json()["associations"]) == 1


def test_duplicate_gis_submission_is_idempotent_and_changed_inputs_conflict(
    configured_catalog: dict[str, Any],
) -> None:
    _, output_id = _completed_sar_job()
    request = _gis_request(output_id)
    first = client.post("/api/gis/jobs", json=request)
    duplicate = client.post("/api/gis/jobs", json=request)
    changed = client.post(
        "/api/gis/jobs",
        json={**request, "analysis_config": {"different": True}},
    )
    assert first.status_code == duplicate.status_code == changed.status_code == 202
    assert first.json()["job_id"] == duplicate.json()["job_id"]
    assert changed.json()["job_id"] != first.json()["job_id"]


def test_gis_rejects_registered_output_changed_after_registration(
    configured_catalog: dict[str, Any],
) -> None:
    _, output_id = _completed_sar_job()
    output = integration.get_output(output_id)
    assert output is not None
    path = integration._storage_path(output.job_id, output.storage_key)
    path.write_bytes(b"changed after registration")
    response = client.post("/api/gis/jobs", json=_gis_request(output_id))
    assert response.status_code == 409
    assert "changed after registration" in response.json()["detail"]


def test_failed_job_redacts_secrets_and_can_be_retried(
    configured_catalog: dict[str, Any],
) -> None:
    class FailingAdapter:
        def process(self, _request: Any) -> OutputRegistrationRequest:
            raise RuntimeError(
                "Authorization: Bearer never-return-this-secret; "
                "download https://provider.example/file.h5?X-Amz-Credential=hidden"
                "&X-Amz-Signature=signed-secret&X-Amz-Expires=300"
            )

    integration.configure_processing_adapters(sar=FailingAdapter(), gis=None)
    submitted = client.post("/api/processing/jobs", json=_processing_request())
    job_id = submitted.json()["job_id"]
    integration._execute(job_id)
    failed = client.get(f"/api/processing/jobs/{job_id}").json()
    assert failed["status"] == "failed"
    assert "never-return-this-secret" not in json.dumps(failed)
    assert "signed-secret" not in json.dumps(failed)
    assert "X-Amz-Signature" not in json.dumps(failed)
    assert "[REDACTED]" in failed["error_message"]

    integration.configure_processing_adapters(sar=MockSARAdapter(), gis=None)
    retry = client.post(f"/api/integration/jobs/{job_id}/retry")
    assert retry.status_code == 202
    assert retry.json()["retry_of_job_id"] == job_id
    integration._execute(retry.json()["job_id"])
    assert client.get(f"/api/processing/jobs/{retry.json()['job_id']}").json()["status"] == "completed"


def test_sensitive_job_configuration_is_rejected_without_echoing_secret(
    configured_catalog: dict[str, Any],
) -> None:
    response = client.post(
        "/api/processing/jobs",
        json={
            **_processing_request(),
            "processing_config": {"earthdata_token": "do-not-echo-this"},
        },
    )
    assert response.status_code == 422
    assert "do-not-echo-this" not in response.text
    signed_url = client.post(
        "/api/processing/jobs",
        json={
            **_processing_request(),
            "processing_config": {
                "source": "https://provider.example/file.h5?X-Amz-Signature=private"
            },
        },
    )
    assert signed_url.status_code == 422
    assert "X-Amz-Signature" not in signed_url.text
    assert "private" not in signed_url.text


def test_interrupted_integration_jobs_are_recovered_as_failed(
    configured_catalog: dict[str, Any],
) -> None:
    submitted = client.post("/api/processing/jobs", json=_processing_request())
    job_id = submitted.json()["job_id"]
    integration._mark_job(job_id, status="running")
    integration.recover_interrupted_jobs()
    recovered = client.get(f"/api/processing/jobs/{job_id}")
    assert recovered.json()["status"] == "failed"
    assert recovered.json()["error_code"] == "process_interrupted"
    assert "Backend stopped" in recovered.json()["error_message"]


def test_output_directory_must_be_scoped_to_its_job(
    configured_catalog: dict[str, Any],
) -> None:
    submitted = client.post("/api/processing/jobs", json=_processing_request())
    job_id = submitted.json()["job_id"]
    other_directory = integration.OUTPUT_ROOT / "another-job"
    other_directory.mkdir(parents=True)
    (other_directory / "output.tif").write_bytes(b"data")
    response = client.post(
        f"/api/processing/jobs/{job_id}/outputs",
        json={
            "outputs": [
                {
                    "role": "mask",
                    "storage_key": "another-job/output.tif",
                    "output_type": "raster",
                    "media_type": "image/tiff",
                    "metadata": {
                        "crs": "EPSG:32643",
                        "width": 1,
                        "height": 1,
                        "transform": [10, 0, 0, 0, -10, 0],
                        "nodata": None,
                        "units": "not_applicable",
                    },
                }
            ]
        },
    )
    assert response.status_code == 422
