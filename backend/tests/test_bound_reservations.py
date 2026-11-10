import json
import multiprocessing
import os
import sqlite3
import uuid
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.reference_lifecycle import BoundReferenceMetadata, ReviewAction
from app.schemas.validation import WindowedValidationMetadata
from app.services import reference_lifecycle, validation


def raster(west=500000, nodata=255):
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    buffer = BytesIO()
    with rasterio.open(
        buffer, "w", driver="GTiff", width=2, height=2, count=1, dtype="uint8",
        crs="EPSG:32643", transform=from_origin(west, 1600000, 10, 10), nodata=nodata,
    ) as dataset:
        dataset.write(np.array([[0, 1], [1, 0]], dtype="uint8"), 1)
    return buffer.getvalue()


def reference_metadata():
    return BoundReferenceMetadata.model_validate({
        "river_id": "tungabhadra", "candidate_product_id": "fixture",
        "candidate_sensor": "NISAR", "candidate_acquisition_datetime": "2026-11-06T00:00:00Z",
        "candidate_processing_version": "v1", "reference_dataset_id": "reference",
        "reference_source": "test", "reference_acquisition_datetime": "2026-11-06T03:00:00Z",
        "provenance": "controlled test raster",
    })


def assessment_metadata():
    return WindowedValidationMetadata.model_validate({
        "river_id": "tungabhadra", "candidate_product_id": "fixture", "candidate_sensor": "NISAR",
        "candidate_acquisition_datetime": "2026-11-06T00:00:00Z", "candidate_processing_version": "v1",
        "reference_dataset_id": "reference", "reference_provider": "test",
        "reference_acquisition_datetime": "2026-11-06T03:00:00Z", "reference_resolution_m": 10,
        "reviewer": "test reviewer", "review_date": "2026-11-09", "independent_review_completed": True,
        "reference_methodology": "test", "limitations": ["controlled test only"],
        "minimum_common_pixels": 2, "minimum_coverage_fraction": 0.1, "minimum_pixels_per_class": 1,
        "spatial_block_size_pixels": 2, "minimum_blocks_per_class": 1,
    })


def attest(reference_id):
    reference_lifecycle.transition_review(reference_id, ReviewAction(action="request_review"))
    reference_lifecycle.transition_review(reference_id, ReviewAction(
        action="attest", declared_reviewer="test reviewer", declaration="test", scope="test",
    ))


def worker(db_path, reference_id, assessment_id, data, action, barrier, queue):
    reference_lifecycle.DATABASE_PATH = Path(db_path)
    barrier.wait(timeout=20)
    try:
        if action == "reserve":
            result = reference_lifecycle.reserve_assessment(assessment_id, reference_id, data, assessment_metadata())
            queue.put(("reserved", result.state))
        else:
            reference_lifecycle.transition_review(reference_id, ReviewAction(action="withdraw", reason="test withdrawal"))
            queue.put(("withdrawn",))
    except ValueError as error:
        queue.put(("rejected", str(error)))


def calculation_worker(db_path, assessment_id, barrier, queue, crash=False):
    reference_lifecycle.DATABASE_PATH = Path(db_path)
    if crash:
        def terminate_during_calculation(*args):
            os._exit(23)
        validation._calculate_windowed_masks = terminate_during_calculation
    barrier.wait(timeout=20)
    try:
        result = reference_lifecycle.calculate_reserved_assessment(assessment_id)
        queue.put(("calculated", result.result.common_valid_pixel_count))
    except (ValueError, validation.ComparisonBusy) as error:
        queue.put(("rejected", str(error)))


def test_api_reservation_retry_withdrawal_and_integrity(monkeypatch, tmp_path):
    db = tmp_path / "references.sqlite3"
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", db)
    data = raster()
    reference = reference_lifecycle.import_bound_reference(data, data, reference_metadata())
    assessment_id = str(uuid.uuid4())
    client = TestClient(app)
    endpoint = f"/api/analysis/bound-assessment-reservations/{assessment_id}"

    def post(content=data, metadata=None):
        return client.post(
            endpoint,
            data={"reference_id": reference.reference_id, "metadata_json": json.dumps((metadata or assessment_metadata()).model_dump(mode="json"))},
            files={"candidate_file": ("candidate.tif", content)},
        )

    assert post().status_code == 422
    attest(reference.reference_id)
    created = post()
    assert created.status_code == 200, created.text
    assert created.json()["state"] == "assessment_reserved"
    assert created.json()["reference_at_reservation"]["review_status"] == "attestation_recorded"
    assert created.json()["reference_id"] == reference.reference_id
    assert post().json() == created.json()
    assert post(metadata=assessment_metadata().model_copy(update={"candidate_product_id": "different"})).status_code == 422
    reference_lifecycle.transition_review(reference.reference_id, ReviewAction(action="withdraw", reason="test"))
    assert post().json()["state"] == "evaluation_rejected"
    assert client.get(endpoint).json()["state"] == "evaluation_rejected"
    events = client.get(endpoint + "/events").json()
    assert [event["new_state"] for event in events] == ["assessment_reserved", "evaluation_rejected"]
    assert "withdrawn" in events[-1]["reason"]
    with pytest.raises(ValueError, match="attestation"):
        reference_lifecycle.reserve_assessment(str(uuid.uuid4()), reference.reference_id, data, assessment_metadata())
    with sqlite3.connect(db) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM bound_assessments").fetchone()[0] == 1
        assert connection.execute("SELECT new_state FROM bound_assessment_events ORDER BY event_id").fetchall() == [
            ("assessment_reserved",), ("evaluation_rejected",),
        ]
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE bound_assessments SET reference_id='different'")
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            connection.execute("DELETE FROM bound_assessments")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE bound_assessment_events SET reason='different'")


def test_windowed_calculation_does_not_persist_a_report(monkeypatch, tmp_path):
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path)
    data = raster()
    result = validation._calculate_windowed_masks(data, data, assessment_metadata())
    assert result.status == "thresholds_met_awaiting_evaluation"
    assert result.confusion_matrix == {
        "true_positive": 2, "true_negative": 2, "false_positive": 0, "false_negative": 0,
    }
    assert list(tmp_path.iterdir()) == []
    saved = validation.assess_windowed_masks(data, data, assessment_metadata())
    assert saved.confusion_matrix == result.confusion_matrix
    assert validation.get_validation_report(saved.validation_id) == saved


def test_rejects_mismatches_without_reservation(monkeypatch, tmp_path):
    db = tmp_path / "references.sqlite3"
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", db)
    data = raster()
    reference = reference_lifecycle.import_bound_reference(data, data, reference_metadata())
    attest(reference.reference_id)
    for metadata in (
        assessment_metadata().model_copy(update={"candidate_product_id": "other"}),
        assessment_metadata().model_copy(update={"candidate_processing_version": "other"}),
        assessment_metadata().model_copy(update={"reference_dataset_id": "other"}),
        assessment_metadata().model_copy(update={"reviewer": "other"}),
        assessment_metadata().model_copy(update={"independent_review_completed": False}),
    ):
        with pytest.raises(ValueError):
            reference_lifecycle.reserve_assessment(str(uuid.uuid4()), reference.reference_id, data, metadata)
    with pytest.raises(ValueError, match="fingerprint"):
        reference_lifecycle.reserve_assessment(str(uuid.uuid4()), reference.reference_id, raster(west=500010), assessment_metadata())
    with pytest.raises(ValueError, match="NoData"):
        reference_lifecycle.reserve_assessment(str(uuid.uuid4()), reference.reference_id, raster(nodata=0), assessment_metadata())
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE bound_references SET reference_raster=? WHERE reference_id=?", (b"tampered", reference.reference_id))
    with pytest.raises(ValueError, match="Reference fingerprint"):
        reference_lifecycle.reserve_assessment(str(uuid.uuid4()), reference.reference_id, data, assessment_metadata())
    misaligned = reference_lifecycle.import_bound_reference(data, raster(west=500010), reference_metadata())
    attest(misaligned.reference_id)
    with pytest.raises(ValueError, match="grids"):
        reference_lifecycle.reserve_assessment(str(uuid.uuid4()), misaligned.reference_id, data, assessment_metadata())


def test_withdrawal_races_reservation_across_processes(monkeypatch, tmp_path):
    db = tmp_path / "references.sqlite3"
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", db)
    data = raster()
    reference = reference_lifecycle.import_bound_reference(data, data, reference_metadata())
    attest(reference.reference_id)
    ctx = multiprocessing.get_context("spawn")
    barrier, queue = ctx.Barrier(2), ctx.Queue()
    assessment_id = str(uuid.uuid4())
    processes = [ctx.Process(target=worker, args=(str(db), reference.reference_id, assessment_id, data, action, barrier, queue))
                 for action in ("reserve", "withdraw")]
    for process in processes:
        process.start()
    for process in processes:
        process.join(30)
        assert process.exitcode == 0
    outcomes = [queue.get(timeout=5), queue.get(timeout=5)]
    assert ("withdrawn",) in outcomes
    if any(item[0] == "reserved" for item in outcomes):
        assert reference_lifecycle.get_assessment_reservation(assessment_id).state == "evaluation_rejected"
    else:
        assert any(item[0] == "rejected" and "attestation" in item[1] for item in outcomes)
        with pytest.raises(FileNotFoundError):
            reference_lifecycle.get_assessment_reservation(assessment_id)
    with pytest.raises(ValueError, match="attestation"):
        reference_lifecycle.reserve_assessment(str(uuid.uuid4()), reference.reference_id, data, assessment_metadata())


def test_concurrent_duplicate_reservations_and_withdraw_rollback(monkeypatch, tmp_path):
    db = tmp_path / "references.sqlite3"
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", db)
    data = raster()
    reference = reference_lifecycle.import_bound_reference(data, data, reference_metadata())
    attest(reference.reference_id)
    assessment_id = str(uuid.uuid4())
    ctx = multiprocessing.get_context("spawn")
    barrier, queue = ctx.Barrier(2), ctx.Queue()
    processes = [ctx.Process(target=worker, args=(str(db), reference.reference_id, assessment_id, data, "reserve", barrier, queue))
                 for _ in range(2)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(30)
        assert process.exitcode == 0
    assert [queue.get(timeout=5), queue.get(timeout=5)] == [
        ("reserved", "assessment_reserved"), ("reserved", "assessment_reserved"),
    ]
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM bound_assessments").fetchone()[0] == 1
        connection.execute("""CREATE TRIGGER fail_withdraw BEFORE INSERT ON bound_assessment_events
            WHEN NEW.new_state='evaluation_rejected' BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        reference_lifecycle.transition_review(reference.reference_id, ReviewAction(action="withdraw", reason="test"))
    assert reference_lifecycle.get_bound_reference(reference.reference_id).review_status == "attestation_recorded"
    assert reference_lifecycle.get_assessment_reservation(assessment_id).state == "assessment_reserved"


def test_concurrent_conflicting_reservations_do_not_rebind(monkeypatch, tmp_path):
    db = tmp_path / "references.sqlite3"
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", db)
    candidates = [raster(), raster(west=500010)]
    references = [
        reference_lifecycle.import_bound_reference(data, data, reference_metadata()) for data in candidates
    ]
    for reference in references:
        attest(reference.reference_id)
    ctx = multiprocessing.get_context("spawn")
    barrier, queue = ctx.Barrier(2), ctx.Queue()
    assessment_id = str(uuid.uuid4())
    processes = [
        ctx.Process(target=worker, args=(str(db), reference.reference_id, assessment_id, data, "reserve", barrier, queue))
        for reference, data in zip(references, candidates)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(30)
        assert process.exitcode == 0
    results = [queue.get(timeout=5), queue.get(timeout=5)]
    assert sum(result[0] == "reserved" for result in results) == 1
    assert sum(result[0] == "rejected" and "different or inconsistent" in result[1] for result in results) == 1
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM bound_assessments").fetchone()[0] == 1
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_bound_calculation_is_idempotent_unpublished_and_withdrawal_blocks_retry(monkeypatch, tmp_path):
    db = tmp_path / "references.sqlite3"
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", db)
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path / "legacy-reports")
    data = raster()
    reference = reference_lifecycle.import_bound_reference(data, data, reference_metadata())
    attest(reference.reference_id)
    assessment_id = str(uuid.uuid4())
    reference_lifecycle.reserve_assessment(assessment_id, reference.reference_id, data, assessment_metadata())
    client = TestClient(app)
    endpoint = f"/api/analysis/bound-assessment-reservations/{assessment_id}"
    first = client.post(endpoint + "/calculate")
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["result"]["validation_id"] == assessment_id
    assert result["result"]["status"] == "thresholds_met_awaiting_evaluation"
    assert result["result"]["confusion_matrix"] == {
        "true_positive": 2, "true_negative": 2, "false_positive": 0, "false_negative": 0,
    }
    assert result["result"]["precision"] is None
    assert result["result"]["report_url"] == ""
    assert client.post(endpoint + "/calculate").json() == result
    assert not validation.VALIDATION_DIR.exists()
    assert len(client.get(endpoint + "/events").json()) == 2
    with sqlite3.connect(db) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE bound_assessment_calculations SET result_json='{}'")
    reference_lifecycle.transition_review(reference.reference_id, ReviewAction(action="withdraw", reason="test"))
    assert client.post(endpoint + "/calculate").status_code == 422
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM bound_assessment_calculations").fetchone()[0] == 1


def test_bound_calculation_rejects_reference_mutation_without_result(monkeypatch, tmp_path):
    db = tmp_path / "references.sqlite3"
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", db)
    data = raster()
    reference = reference_lifecycle.import_bound_reference(data, data, reference_metadata())
    attest(reference.reference_id)
    assessment_id = str(uuid.uuid4())
    reference_lifecycle.reserve_assessment(assessment_id, reference.reference_id, data, assessment_metadata())
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE bound_references SET reference_raster=? WHERE reference_id=?", (b"tampered", reference.reference_id))
    with pytest.raises(ValueError, match="fingerprint"):
        reference_lifecycle.calculate_reserved_assessment(assessment_id)
    with sqlite3.connect(db) as connection:
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='bound_assessment_calculations'"
        ).fetchone()[0] == 0


def test_bound_calculation_rolls_back_after_calculation_failure(monkeypatch, tmp_path):
    db = tmp_path / "references.sqlite3"
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", db)
    data = raster()
    reference = reference_lifecycle.import_bound_reference(data, data, reference_metadata())
    attest(reference.reference_id)
    assessment_id = str(uuid.uuid4())
    reference_lifecycle.reserve_assessment(assessment_id, reference.reference_id, data, assessment_metadata())

    def fail(*args):
        raise ValueError("injected calculation failure")

    with monkeypatch.context() as context:
        context.setattr(validation, "_calculate_windowed_masks", fail)
        with pytest.raises(ValueError, match="injected"):
            reference_lifecycle.calculate_reserved_assessment(assessment_id)
    assert len(reference_lifecycle.list_assessment_events(assessment_id)) == 1
    assert reference_lifecycle.calculate_reserved_assessment(assessment_id).result.common_valid_pixel_count == 4


def test_bound_calculation_process_interruption_rolls_back_and_retries(monkeypatch, tmp_path):
    db = tmp_path / "references.sqlite3"
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", db)
    data = raster()
    reference = reference_lifecycle.import_bound_reference(data, data, reference_metadata())
    attest(reference.reference_id)
    assessment_id = str(uuid.uuid4())
    reference_lifecycle.reserve_assessment(assessment_id, reference.reference_id, data, assessment_metadata())
    ctx = multiprocessing.get_context("spawn")
    process = ctx.Process(target=calculation_worker, args=(str(db), assessment_id, ctx.Barrier(1), ctx.Queue(), True))
    process.start()
    process.join(30)
    assert process.exitcode == 23
    with sqlite3.connect(db) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='bound_assessment_calculations'"
        ).fetchone()[0] == 0
    assert reference_lifecycle.calculate_reserved_assessment(assessment_id).result.common_valid_pixel_count == 4
    assert len(reference_lifecycle.list_assessment_events(assessment_id)) == 2


def test_bound_calculation_and_withdrawal_serialize_across_processes(monkeypatch, tmp_path):
    db = tmp_path / "references.sqlite3"
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", db)
    data = raster()
    reference = reference_lifecycle.import_bound_reference(data, data, reference_metadata())
    attest(reference.reference_id)
    assessment_id = str(uuid.uuid4())
    reference_lifecycle.reserve_assessment(assessment_id, reference.reference_id, data, assessment_metadata())
    ctx = multiprocessing.get_context("spawn")
    barrier, queue = ctx.Barrier(2), ctx.Queue()
    processes = [
        ctx.Process(target=calculation_worker, args=(str(db), assessment_id, barrier, queue)),
        ctx.Process(target=worker, args=(str(db), reference.reference_id, assessment_id, data, "withdraw", barrier, queue)),
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(30)
        assert process.exitcode == 0
    outcomes = [queue.get(timeout=5), queue.get(timeout=5)]
    assert ("withdrawn",) in outcomes
    assert any(item == ("calculated", 4) or item[0] == "rejected" for item in outcomes)
    assert reference_lifecycle.get_assessment_reservation(assessment_id).state == "evaluation_rejected"
    with pytest.raises(ValueError, match="current assessment reservation"):
        reference_lifecycle.calculate_reserved_assessment(assessment_id)
