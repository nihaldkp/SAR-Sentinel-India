from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.acquisitions import AcquisitionJobCreate
from app.services import acquisition_jobs, acquisitions

client = TestClient(app)


def _catalog_product() -> dict[str, Any]:
    return {
        "product_id": "NISAR_TEST_JOB_PRODUCT",
        "acquisition_start": "2026-11-06T00:25:20+00:00",
        "acquisition_end": "2026-11-06T00:25:55+00:00",
        "product_level": "GCOV",
        "polarization": ["HH", "HV"],
        "size_bytes": 100,
        "availability": "authenticated_catalog",
        "download_status": "not_attempted",
        "source_url": "https://nisar.asf.earthdatacloud.nasa.gov/test.h5",
        "local_path": None,
        "hdf5_groups": [],
        "message": None,
        "processing_status": "not_attempted",
        "processing_message": None,
        "processing_result": None,
    }


def _prepare_catalog(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(acquisition_jobs, "_schedule", lambda _job_id: None)
    nisar = {
        "status": "metadata_found",
        "product_id": "NISAR_TEST_JOB_PRODUCT",
        "acquisition_start": "2026-11-06T00:25:20+00:00",
        "message": "Test catalog fixture.",
        "products": [_catalog_product()],
    }
    with acquisitions._catalog_connection() as connection:
        acquisitions._write_scan(
            connection,
            "tungabhadra",
            "idle",
            nisar,
            0,
            None,
            nisar["products"],
        )


def _create_nisar_download() -> str:
    job = acquisition_jobs.create_job(
        AcquisitionJobCreate(
            river_id="tungabhadra",
            satellite="NISAR",
            product_id="NISAR_TEST_JOB_PRODUCT",
            job_type="nisar_download",
        )
    )
    return job.job_id


def test_job_records_are_persistent_and_duplicate_active_work_is_rejected(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    _prepare_catalog(monkeypatch, tmp_path)
    job_id = _create_nisar_download()

    persisted = acquisition_jobs.get_job(job_id)
    assert persisted is not None
    assert persisted.status == "queued"
    assert persisted.progress_percent == 0
    assert persisted.current_stage == "Queued"
    assert persisted.created_at is not None

    with pytest.raises(acquisition_jobs.ActiveJobConflict):
        _create_nisar_download()

    assert [job.job_id for job in acquisition_jobs.list_jobs(river_id="tungabhadra")] == [job_id]


def test_restart_marks_interrupted_jobs_failed_and_retry_creates_linked_job(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    _prepare_catalog(monkeypatch, tmp_path)
    job_id = _create_nisar_download()
    acquisition_jobs._update_job(
        job_id,
        status="processing",
        stage="Verifying product",
        started=True,
    )

    acquisition_jobs.recover_interrupted_jobs()

    interrupted = acquisition_jobs.get_job(job_id)
    assert interrupted is not None
    assert interrupted.status == "failed"
    assert interrupted.completed_at is not None
    assert interrupted.progress_percent is None
    assert "backend stopped" in interrupted.error_message

    retried = acquisition_jobs.retry_job(job_id)
    assert retried.status == "queued"
    assert retried.retry_of_job_id == job_id
    assert retried.job_id != job_id


def test_job_no_data_status_is_distinct_and_has_truthful_completion_fields(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(acquisition_jobs, "_schedule", lambda _job_id: None)
    request = AcquisitionJobCreate(
        river_id="kaveri",
        satellite="SENTINEL-1",
        product_id="SENTINEL_NO_DATA_PRODUCT",
        job_type="sentinel1_acquisition",
    )
    job = acquisition_jobs.create_job(request)
    monkeypatch.setattr(
        acquisition_jobs,
        "_run_sentinel1_acquisition",
        lambda _job: ("no_data", {}),
    )

    acquisition_jobs._execute(job.job_id)

    completed = acquisition_jobs.get_job(job.job_id)
    assert completed is not None
    assert completed.status == "no_data"
    assert completed.current_stage == "No valid corridor data; no classification output generated"
    assert completed.progress_percent == 100
    assert completed.started_at is not None
    assert completed.completed_at is not None
    assert completed.output_references == {}


def test_job_failure_redacts_credentials_and_exposes_api_retry(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    _prepare_catalog(monkeypatch, tmp_path)
    job_id = _create_nisar_download()
    monkeypatch.setattr(
        acquisition_jobs,
        "_run_nisar_download",
        lambda _job: (_ for _ in ()).throw(RuntimeError("request failed token=secret-value")),
    )

    acquisition_jobs._execute(job_id)
    response = client.get(f"/api/acquisition-jobs/{job_id}")

    assert response.status_code == 200
    failed = response.json()
    assert failed["status"] == "failed"
    assert "token=[REDACTED]" in failed["error_message"]
    assert "secret-value" not in failed["error_message"]
    assert response.json()["completed_at"] is not None

    retry = client.post(f"/api/acquisition-jobs/{job_id}/retry")
    assert retry.status_code == 202
    assert retry.json()["status"] == "queued"
    assert retry.json()["retry_of_job_id"] == job_id
    assert client.get("/api/acquisition-jobs?river_id=tungabhadra").status_code == 200


def test_job_submission_detail_list_and_queued_cancellation_apis(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "jobs.sqlite3")
    monkeypatch.setattr(acquisition_jobs, "_schedule", lambda _job_id: None)
    payload = {
        "river_id": "kaveri",
        "satellite": "SENTINEL-1",
        "product_id": "SENTINEL_API_TEST_PRODUCT",
        "job_type": "sentinel1_acquisition",
    }

    submitted = client.post("/api/acquisition-jobs", json=payload)

    assert submitted.status_code == 202
    job_id = submitted.json()["job_id"]
    assert client.get(f"/api/acquisition-jobs/{job_id}").json()["status"] == "queued"
    assert len(client.get("/api/acquisition-jobs?river_id=kaveri").json()) == 1

    cancelled = client.post(f"/api/acquisition-jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["completed_at"] is not None
