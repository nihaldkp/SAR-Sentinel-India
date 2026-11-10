import json
import multiprocessing
from datetime import datetime
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.validation import WindowedValidationMetadata
from app.services import validation


def _transition_worker(directory, validation_id, action, barrier, queue):
    validation.VALIDATION_DIR = Path(directory)
    barrier.wait(timeout=20)
    try:
        if action == "evaluate":
            result = validation.evaluate_windowed_assessment(validation_id)
        else:
            result = validation.reject_windowed_assessment(validation_id, "Test rejection")
        queue.put(("success", result.status))
    except (ValueError, validation.ComparisonBusy) as error:
        queue.put(("rejected", str(error)))


def raster_bytes(values: np.ndarray, west: int = 500_000) -> bytes:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    buffer = BytesIO()
    with rasterio.open(
        buffer, "w", driver="GTiff", width=values.shape[1], height=values.shape[0],
        count=1, dtype="uint8", crs="EPSG:32643", transform=from_origin(west, 1_600_000, 10, 10),
        nodata=255, tiled=True, blockxsize=256, blockysize=256, compress="deflate",
    ) as dataset:
        dataset.write(values, 1)
    return buffer.getvalue()


def metadata() -> WindowedValidationMetadata:
    return WindowedValidationMetadata.model_validate({
        "river_id": "tungabhadra", "candidate_product_id": "fixture",
        "candidate_sensor": "fixture", "candidate_processing_version": "v1",
        "candidate_acquisition_datetime": "2026-11-06T00:25:20Z",
        "reference_dataset_id": "reference", "reference_provider": "fixture",
        "reference_acquisition_datetime": "2026-11-06T03:00:00Z",
        "reference_resolution_m": 10, "reviewer": "fixture",
        "review_date": "2026-11-09", "independent_review_completed": True,
        "reference_methodology": "fixture", "limitations": ["test only"],
        "minimum_common_pixels": 2, "minimum_coverage_fraction": 0.1,
        "minimum_pixels_per_class": 1, "spatial_block_size_pixels": 2,
        "minimum_blocks_per_class": 1,
    })


def test_windowed_assessment_and_evaluation_match_numpy(monkeypatch, tmp_path):
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path)
    monkeypatch.setattr(validation, "COMPARISON_WINDOW_SIZE", 3)
    rng = np.random.default_rng(42)
    candidate = rng.choice([0, 1, 255], size=(9, 11), p=[0.4, 0.4, 0.2]).astype("uint8")
    reference = rng.choice([0, 1, 255], size=(9, 11), p=[0.4, 0.4, 0.2]).astype("uint8")
    response = TestClient(app).post(
        "/api/analysis/validation/windowed-assessments",
        data={"metadata_json": json.dumps(metadata().model_dump(mode="json"))},
        files={"candidate_file": ("c.tif", raster_bytes(candidate), "image/tiff"),
               "reference_file": ("r.tif", raster_bytes(reference), "image/tiff")},
    )
    assert response.status_code == 201, response.text
    result = response.json()
    shared = (candidate != 255) & (reference != 255)
    tp = int(np.count_nonzero(shared & (candidate == 1) & (reference == 1)))
    tn = int(np.count_nonzero(shared & (candidate == 0) & (reference == 0)))
    fp = int(np.count_nonzero(shared & (candidate == 1) & (reference == 0)))
    fn = int(np.count_nonzero(shared & (candidate == 0) & (reference == 1)))
    assert result["status"] == "thresholds_met_awaiting_evaluation"
    assert result["acquisition_time_difference_seconds"] == 9280
    assert result["precision"] is None
    assert result["confusion_matrix"] == {"true_positive": tp, "true_negative": tn, "false_positive": fp, "false_negative": fn}
    assert result["processing"]["windows_processed"] == 12
    assert len(result["processing"]["candidate_sha256"]) == 64
    evaluated = TestClient(app).post(f"/api/analysis/validation/windowed-assessments/{result['validation_id']}/evaluate")
    assert evaluated.status_code == 200, evaluated.text
    value = evaluated.json()
    assert value["precision"] == pytest.approx(tp / (tp + fp))
    assert value["recall"] == pytest.approx(tp / (tp + fn))
    assert value["f1_score"] == pytest.approx(2 * tp / (2 * tp + fp + fn))
    assert value["intersection_over_union"] == pytest.approx(tp / (tp + fp + fn))
    assert value["overall_agreement"] == pytest.approx((tp + tn) / int(shared.sum()))
    assert value["evaluation_completed_at"] is not None
    assert value["acquisition_time_difference_seconds"] == 9280
    assert validation.get_validation_report(result["validation_id"]).status == "validation_completed"
    assert TestClient(app).post(f"/api/analysis/validation/windowed-assessments/{result['validation_id']}/evaluate").status_code == 422


def test_windowed_rejects_misalignment_without_creating_report(monkeypatch, tmp_path):
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path)
    a = np.asarray([[0, 1], [1, 0]], dtype="uint8")
    with pytest.raises(ValueError, match="no resampling"):
        validation.assess_windowed_masks(raster_bytes(a), raster_bytes(a, west=500_010), metadata())
    assert list(tmp_path.iterdir()) == []


def test_acquisition_separation_handles_timezones_and_legacy_naive_dates(monkeypatch, tmp_path):
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path)
    data = raster_bytes(np.asarray([[0, 1], [1, 0]], dtype="uint8"))
    result = validation.assess_windowed_masks(data, data, metadata())
    later_with_offset = datetime.fromisoformat("2026-11-06T09:30:00+05:30")
    assert result.model_copy(update={"reference_acquisition_datetime": later_with_offset}).acquisition_time_difference_seconds == 12880
    before = datetime.fromisoformat("2026-11-05T23:25:20+00:00")
    assert result.model_copy(update={"reference_acquisition_datetime": before}).acquisition_time_difference_seconds == 3600
    naive = datetime.fromisoformat("2026-11-06T03:00:00")
    assert result.model_copy(update={"reference_acquisition_datetime": naive}).acquisition_time_difference_seconds is None


def test_windowed_large_raster_and_insufficient_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path)
    labels = np.zeros((2100, 2100), dtype="uint8")
    labels[100:200, 300:400] = 1
    labels[:10] = 255
    raster = raster_bytes(labels)
    result = validation.assess_windowed_masks(raster, raster, metadata())
    assert result.common_valid_pixel_count == 2100 * 2090
    assert result.reference_class_counts == {"0": 2100 * 2090 - 10000, "1": 10000}
    assert result.processing["windows_processed"] == 25
    insufficient = metadata().model_copy(update={"minimum_pixels_per_class": 10001})
    result = validation.assess_windowed_masks(raster, raster, insufficient)
    assert result.status == "insufficient_evidence"
    with pytest.raises(ValueError, match="awaiting evaluation"):
        validation.evaluate_windowed_assessment(result.validation_id)


def test_windowed_empty_and_zero_precision(monkeypatch, tmp_path):
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path)
    candidate = np.zeros((2, 2), dtype="uint8")
    reference = np.asarray([[0, 1], [1, 0]], dtype="uint8")
    result = validation.assess_windowed_masks(raster_bytes(candidate), raster_bytes(reference), metadata())
    evaluated = validation.evaluate_windowed_assessment(result.validation_id)
    assert evaluated.precision is None
    assert evaluated.recall == 0
    assert evaluated.f1_score == 0
    assert evaluated.intersection_over_union == 0
    assert evaluated.overall_agreement == 0.5
    missing = raster_bytes(np.full((2, 2), 255, dtype="uint8"))
    result = validation.assess_windowed_masks(missing, raster_bytes(reference), metadata())
    assert result.status == "insufficient_spatial_overlap"
    assert result.precision is None


def test_windowed_work_and_block_limits_do_not_persist(monkeypatch, tmp_path):
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path)
    raster = raster_bytes(np.asarray([[0, 1], [1, 0]], dtype="uint8"))
    monkeypatch.setattr(validation, "MAX_COMPARISON_PIXEL_READS", 7)
    with pytest.raises(ValueError, match="pixel-read limit"):
        validation.assess_windowed_masks(raster, raster, metadata())
    assert list(tmp_path.iterdir()) == []


def test_rejection_is_persisted_and_cannot_be_evaluated(monkeypatch, tmp_path):
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path)
    raster = raster_bytes(np.asarray([[0, 1], [1, 0]], dtype="uint8"))
    result = validation.assess_windowed_masks(raster, raster, metadata())
    client = TestClient(app)
    endpoint = f"/api/analysis/validation/windowed-assessments/{result.validation_id}"
    assert client.post(f"{endpoint}/reject", json={"reason": "  "}).status_code == 422
    response = client.post(f"{endpoint}/reject", json={"reason": "Labels are unsuitable"})
    assert response.status_code == 200
    assert response.json()["status"] == "evaluation_rejected"
    saved = validation.get_validation_report(result.validation_id)
    assert saved.evaluation_outcome_detail == "Labels are unsuitable"
    assert saved.evaluation_completed_at is not None
    assert saved.precision is None
    assert client.post(f"{endpoint}/evaluate").status_code == 422
    assert client.post(f"{endpoint}/reject", json={"reason": "again"}).status_code == 422


def test_invalid_stored_counts_persist_failed_outcome(monkeypatch, tmp_path):
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path)
    raster = raster_bytes(np.asarray([[0, 1], [1, 0]], dtype="uint8"))
    result = validation.assess_windowed_masks(raster, raster, metadata())
    path = tmp_path / result.validation_id / "result.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["confusion_matrix"]["true_positive"] += 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    response = TestClient(app).post(f"/api/analysis/validation/windowed-assessments/{result.validation_id}/evaluate")
    assert response.status_code == 422
    saved = validation.get_validation_report(result.validation_id)
    assert saved.status == "evaluation_failed"
    assert saved.evaluation_outcome_detail == "Assessment confusion counts are inconsistent."
    assert saved.evaluation_completed_at is not None
    assert saved.precision is None
    assert validation.validation_status().status == "validation_pending"


@pytest.mark.parametrize("actions", [("evaluate", "evaluate"), ("evaluate", "reject")])
def test_transition_is_serialized_across_processes(monkeypatch, tmp_path, actions):
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path)
    raster = raster_bytes(np.asarray([[0, 1], [1, 0]], dtype="uint8"))
    result = validation.assess_windowed_masks(raster, raster, metadata())
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    processes = [
        context.Process(target=_transition_worker, args=(str(tmp_path), result.validation_id, action, barrier, queue))
        for action in actions
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0
    outcomes = [queue.get(timeout=5) for _ in processes]
    assert sorted(outcome[0] for outcome in outcomes) == ["rejected", "success"]
    saved = validation.get_validation_report(result.validation_id)
    assert saved.status in {"validation_completed", "evaluation_rejected"}
    assert len(saved.evaluation_transitions) == 1
    assert saved.evaluation_transitions[0].previous_status == "thresholds_met_awaiting_evaluation"
    assert saved.evaluation_transitions[0].new_status == saved.status
