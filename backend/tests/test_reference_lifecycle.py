import hashlib
import json
import multiprocessing
import sqlite3
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.reference_lifecycle import BoundReferenceMetadata, CandidateIdentity, ReviewAction
from app.services import reference_lifecycle


def _raster(west: int = 500000) -> bytes:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    data = BytesIO()
    with rasterio.open(
        data, "w", driver="GTiff", width=2, height=2, count=1, dtype="uint8",
        crs="EPSG:32643", transform=from_origin(west, 1600000, 10, 10), nodata=255,
    ) as raster:
        raster.write(np.asarray([[0, 1], [255, 0]], dtype="uint8"), 1)
    return data.getvalue()


def _metadata() -> BoundReferenceMetadata:
    return BoundReferenceMetadata.model_validate({
        "river_id": "tungabhadra", "candidate_product_id": "test-product",
        "candidate_sensor": "NISAR", "candidate_acquisition_datetime": "2026-11-06T00:25:20Z",
        "candidate_processing_version": "fixture-v1", "reference_dataset_id": "test-reference",
        "reference_source": "test only", "provenance": "controlled test raster",
    })


def _review_worker(db_path, reference_id, action, barrier, queue):
    reference_lifecycle.DATABASE_PATH = Path(db_path)
    barrier.wait(timeout=20)
    try:
        result = reference_lifecycle.transition_review(reference_id, ReviewAction.model_validate(action))
        queue.put(("success", result.review_status))
    except ValueError as error:
        queue.put(("rejected", str(error)))


def _eligibility_worker(db_path, reference_id, candidate, identity, barrier, queue):
    reference_lifecycle.DATABASE_PATH = Path(db_path)
    barrier.wait(timeout=20)
    result = reference_lifecycle.check_eligibility(reference_id, candidate, CandidateIdentity.model_validate(identity))
    queue.put(("checked", result.review_status, result.identity_review_checks_passed))


def test_import_and_review_api_persists_unverified_attestation(monkeypatch, tmp_path):
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", tmp_path / "references.sqlite3")
    raster = _raster()
    client = TestClient(app)
    response = client.post(
        "/api/analysis/bound-references",
        data={"metadata_json": json.dumps(_metadata().model_dump(mode="json"))},
        files={"candidate_file": ("candidate.tif", raster), "reference_file": ("reference.tif", raster)},
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["review_status"] == "imported"
    assert result["identity_verification"] == "operator_declared_not_authenticated"
    assert result["candidate_sha256"] == hashlib.sha256(raster).hexdigest()
    assert result["reference_sha256"] == hashlib.sha256(raster).hexdigest()
    assert result["reference_transform"] == [10, 0, 500000, 0, -10, 1600000]
    assert result["label_counts"] == {"0": 2, "1": 1, "255": 1}
    assert client.get("/api/analysis/bound-references").json()[0]["reference_id"] == result["reference_id"]
    endpoint = f"/api/analysis/bound-references/{result['reference_id']}"
    assert client.get(endpoint + "/labels").content == raster
    assert client.post(endpoint + "/review", json={"action": "attest"}).status_code == 422
    assert client.post(endpoint + "/review", json={"action": "request_review"}).json()["review_status"] == "review_pending"
    response = client.post(endpoint + "/review", json={
        "action": "attest", "declared_reviewer": "test reviewer", "declaration": "Test declaration",
        "scope": "test pixels", "evidence": "test only",
    })
    assert response.status_code == 200
    assert response.json()["review_status"] == "attestation_recorded"
    assert response.json()["review_history"][-1]["details"]["declaration"] == "Test declaration"
    assert client.post(endpoint + "/review", json={"action": "request_review"}).status_code == 422
    assert client.post(endpoint + "/review", json={"action": "withdraw", "reason": "test"}).json()["review_status"] == "withdrawn"
    assert client.get(endpoint).json()["review_status"] == "withdrawn"


def test_import_rejects_secret_bearing_source_url():
    metadata = _metadata().model_dump(mode="json")
    metadata["reference_source"] = "https://example.test/labels?signature=secret"
    with pytest.raises(ValueError, match="query strings"):
        BoundReferenceMetadata.model_validate(metadata)
    raster = _raster()
    response = TestClient(app).post(
        "/api/analysis/bound-references", data={"metadata_json": json.dumps(metadata)},
        files={"candidate_file": ("candidate.tif", raster), "reference_file": ("reference.tif", raster)},
    )
    assert response.status_code == 422
    assert "secret" not in response.text


def test_rejection_and_reference_integrity(monkeypatch, tmp_path):
    db = tmp_path / "references.sqlite3"
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", db)
    raster = _raster()
    record = reference_lifecycle.import_bound_reference(raster, raster, _metadata())
    reference_lifecycle.transition_review(record.reference_id, ReviewAction(action="request_review"))
    rejected = reference_lifecycle.transition_review(record.reference_id, ReviewAction(action="reject", reason="unsuitable"))
    assert rejected.review_status == "rejected"
    assert rejected.review_history[-1].details["reason"] == "unsuitable"
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE bound_references SET reference_raster=? WHERE reference_id=?", (b"tampered", record.reference_id))
    with pytest.raises(ValueError, match="fingerprint"):
        reference_lifecycle.reference_raster(record.reference_id)


def test_eligibility_checks_review_hashes_and_grid_and_persists_audit(monkeypatch, tmp_path):
    db = tmp_path / "references.sqlite3"
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", db)
    candidate = _raster()
    record = reference_lifecycle.import_bound_reference(candidate, candidate, _metadata())
    endpoint = f"/api/analysis/bound-references/{record.reference_id}/eligibility"
    client = TestClient(app)
    identity = _metadata().model_dump(mode="json", include={
        "river_id", "candidate_product_id", "candidate_sensor", "candidate_acquisition_datetime", "candidate_processing_version",
    })

    def check(content, selected_identity=None):
        response = client.post(
            endpoint,
            data={"identity_json": json.dumps(selected_identity if selected_identity is not None else identity)},
            files={"candidate_file": ("candidate.tif", content, "image/tiff")},
        )
        assert response.status_code == 200, response.text
        return response.json()

    pending = check(candidate)
    assert not pending["identity_review_checks_passed"] and "imported" in pending["reasons"][0]
    reference_lifecycle.transition_review(record.reference_id, ReviewAction(action="request_review"))
    assert not check(candidate)["identity_review_checks_passed"]
    reference_lifecycle.transition_review(record.reference_id, ReviewAction(
        action="attest", declared_reviewer="fixture", declaration="test", scope="test",
    ))
    accepted = check(candidate)
    assert accepted["identity_review_checks_passed"]
    assert "not authenticated" in accepted["limitations"][-1]
    changed = check(_raster(west=500010))
    assert not changed["identity_review_checks_passed"]
    assert any("fingerprint" in reason for reason in changed["reasons"])
    assert any("grids" in reason for reason in changed["reasons"])
    for field, value in {
        "river_id": "kaveri", "candidate_product_id": "another-product", "candidate_sensor": "SENTINEL-1",
        "candidate_acquisition_datetime": "2026-11-07T00:25:20Z", "candidate_processing_version": "other",
    }.items():
        mismatched = check(candidate, {**identity, field: value})
        assert not mismatched["identity_review_checks_passed"]
        assert any(field in reason for reason in mismatched["reasons"])
    reference_lifecycle.transition_review(record.reference_id, ReviewAction(action="withdraw", reason="test"))
    assert not check(candidate)["identity_review_checks_passed"]
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM reference_eligibility_checks").fetchone()[0] == 10
        connection.execute("UPDATE bound_references SET reference_raster=? WHERE reference_id=?", (b"tampered", record.reference_id))
    tampered = check(candidate)
    assert not tampered["identity_review_checks_passed"]
    assert any("Stored reference raster fingerprint" in reason for reason in tampered["reasons"])
    history = client.get(endpoint)
    assert history.status_code == 200
    assert len(history.json()) == 11
    assert history.json()[0] == tampered
    assert client.get("/api/analysis/bound-references/00000000-0000-0000-0000-000000000000/eligibility").status_code == 404


def test_eligibility_rejects_unknown_version_and_rejected_reference(monkeypatch, tmp_path):
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", tmp_path / "references.sqlite3")
    raster = _raster()
    metadata = _metadata().model_copy(update={"candidate_processing_version": None})
    record = reference_lifecycle.import_bound_reference(raster, raster, metadata)
    identity = metadata.model_dump(mode="json", include={
        "river_id", "candidate_product_id", "candidate_sensor", "candidate_acquisition_datetime", "candidate_processing_version",
    })
    endpoint = f"/api/analysis/bound-references/{record.reference_id}/eligibility"
    client = TestClient(app)
    assert client.get(endpoint).json() == []
    reference_lifecycle.transition_review(record.reference_id, ReviewAction(action="request_review"))
    reference_lifecycle.transition_review(record.reference_id, ReviewAction(action="reject", reason="unsuitable"))
    result = client.post(endpoint, data={"identity_json": json.dumps(identity)}, files={"candidate_file": ("mask.tif", raster)}).json()
    assert not result["identity_review_checks_passed"]
    assert any("rejected" in reason for reason in result["reasons"])
    assert any("processing version is unavailable" in reason for reason in result["reasons"])


def test_eligibility_and_withdrawal_are_serialized_across_processes(monkeypatch, tmp_path):
    db = tmp_path / "references.sqlite3"
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", db)
    candidate = _raster()
    metadata = _metadata()
    record = reference_lifecycle.import_bound_reference(candidate, candidate, metadata)
    reference_lifecycle.transition_review(record.reference_id, ReviewAction(action="request_review"))
    reference_lifecycle.transition_review(record.reference_id, ReviewAction(
        action="attest", declared_reviewer="fixture", declaration="test", scope="test",
    ))
    ctx = multiprocessing.get_context("spawn")
    barrier, queue = ctx.Barrier(2), ctx.Queue()
    check = ctx.Process(target=_eligibility_worker, args=(
        str(db), record.reference_id, candidate, metadata.model_dump(mode="json"), barrier, queue,
    ))
    withdraw = ctx.Process(target=_review_worker, args=(
        str(db), record.reference_id, {"action": "withdraw", "reason": "test"}, barrier, queue,
    ))
    check.start()
    withdraw.start()
    check.join(30)
    withdraw.join(30)
    assert check.exitcode == 0 and withdraw.exitcode == 0
    results = [queue.get(timeout=5), queue.get(timeout=5)]
    assert ("success", "withdrawn") in results
    snapshot = next(item for item in results if item[0] == "checked")
    assert snapshot in (("checked", "attestation_recorded", True), ("checked", "withdrawn", False))
    assert reference_lifecycle.get_bound_reference(record.reference_id).review_status == "withdrawn"
    assert not reference_lifecycle.check_eligibility(
        record.reference_id, candidate, CandidateIdentity.model_validate(metadata.model_dump()),
    ).identity_review_checks_passed


def test_unknown_version_and_storage_quota(monkeypatch, tmp_path):
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", tmp_path / "references.sqlite3")
    raster = _raster()
    metadata = _metadata().model_copy(update={"candidate_sensor": "SENTINEL-1", "candidate_processing_version": None})
    record = reference_lifecycle.import_bound_reference(raster, raster, metadata)
    assert reference_lifecycle.get_bound_reference(record.reference_id).metadata.candidate_processing_version is None
    monkeypatch.setattr(reference_lifecycle, "MAX_REFERENCE_STORAGE_BYTES", len(raster))
    with pytest.raises(ValueError, match="quota"):
        reference_lifecycle.import_bound_reference(raster, raster, metadata)
    assert len(reference_lifecycle.list_bound_references()) == 1


def test_distinct_inputs_create_distinct_records_without_automatic_supersession(monkeypatch, tmp_path):
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", tmp_path / "references.sqlite3")
    raster = _raster()
    first = reference_lifecycle.import_bound_reference(raster, raster, _metadata())
    changed = _metadata().model_copy(update={
        "candidate_product_id": "other-product", "candidate_processing_version": "fixture-v2",
    })
    second = reference_lifecycle.import_bound_reference(raster, raster, changed)
    assert first.reference_id != second.reference_id
    assert reference_lifecycle.get_bound_reference(first.reference_id).metadata == _metadata()
    assert reference_lifecycle.get_bound_reference(second.reference_id).metadata == changed
    assert reference_lifecycle.get_bound_reference(first.reference_id).review_status == "imported"


def test_storage_failure_does_not_commit_transition(monkeypatch, tmp_path):
    db = tmp_path / "references.sqlite3"
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", db)
    raster = _raster()
    record = reference_lifecycle.import_bound_reference(raster, raster, _metadata())
    with sqlite3.connect(db) as connection:
        connection.execute(
            "CREATE TRIGGER reject_update BEFORE UPDATE ON bound_references "
            "BEGIN SELECT RAISE(ABORT, 'test write failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="test write failure"):
        reference_lifecycle.transition_review(record.reference_id, ReviewAction(action="request_review"))
    stored = reference_lifecycle.get_bound_reference(record.reference_id)
    assert stored.review_status == "imported"
    assert len(stored.review_history) == 1


def test_review_transition_race_uses_separate_processes(monkeypatch, tmp_path):
    db = tmp_path / "references.sqlite3"
    monkeypatch.setattr(reference_lifecycle, "DATABASE_PATH", db)
    raster = _raster()
    record = reference_lifecycle.import_bound_reference(raster, raster, _metadata())
    reference_lifecycle.transition_review(record.reference_id, ReviewAction(action="request_review"))
    context = multiprocessing.get_context("spawn")
    barrier, queue = context.Barrier(2), context.Queue()
    actions = [
        {"action": "attest", "declared_reviewer": "test", "declaration": "test", "scope": "test"},
        {"action": "reject", "reason": "test"},
    ]
    processes = [
        context.Process(target=_review_worker, args=(str(db), record.reference_id, action, barrier, queue))
        for action in actions
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0
    outcomes = [queue.get(timeout=5) for _ in processes]
    assert sorted(result[0] for result in outcomes) == ["rejected", "success"]
    stored = reference_lifecycle.get_bound_reference(record.reference_id)
    assert len(stored.review_history) == 3
    assert stored.review_status in {"attestation_recorded", "rejected"}
