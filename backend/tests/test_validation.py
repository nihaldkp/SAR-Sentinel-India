import json
import uuid
from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.validation import (
    MethodEvaluationMetadata,
    ReferenceDataImportMetadata,
    ValidationMetadata,
)
from app.services import validation

client = TestClient(app)


def test_reference_and_report_listings_reject_external_symlinks(monkeypatch: Any, tmp_path: Any) -> None:
    reference_root = tmp_path / "references"
    validation_root = tmp_path / "validation"
    monkeypatch.setattr(validation, "REFERENCE_DATA_DIR", reference_root)
    monkeypatch.setattr(validation, "VALIDATION_DIR", validation_root)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    reference_id = str(uuid.uuid4())
    report_id = str(uuid.uuid4())
    reference_dir = reference_root / reference_id
    report_dir = validation_root / report_id
    reference_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    try:
        (reference_dir / "metadata.json").symlink_to(outside)
        (report_dir / "result.json").symlink_to(outside)
    except OSError as error:
        pytest.skip(f"Symlink creation unavailable: {error}")
    with pytest.raises(FileNotFoundError):
        validation._reference_record(reference_id)
    with pytest.raises(FileNotFoundError):
        validation.list_reference_data()
    with pytest.raises(FileNotFoundError):
        validation.list_validation_reports()


def test_reference_and_report_listings_reject_resolved_paths_outside_root(monkeypatch: Any, tmp_path: Any) -> None:
    reference_root = tmp_path / "references"
    validation_root = tmp_path / "validation"
    monkeypatch.setattr(validation, "REFERENCE_DATA_DIR", reference_root)
    monkeypatch.setattr(validation, "VALIDATION_DIR", validation_root)
    reference_dir = reference_root / str(uuid.uuid4())
    report_dir = validation_root / str(uuid.uuid4())
    reference_dir.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    metadata = reference_dir / "metadata.json"
    report = report_dir / "result.json"
    metadata.write_text("{}", encoding="utf-8")
    report.write_text("{}", encoding="utf-8")
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    original_resolve = Path.resolve

    def resolve_with_external_target(path: Path, *args: Any, **kwargs: Any) -> Path:
        if path in (metadata, report):
            return outside
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve_with_external_target)
    with pytest.raises(FileNotFoundError):
        validation.list_reference_data()
    with pytest.raises(FileNotFoundError):
        validation.list_validation_reports()


def _mask_bytes(
    values: np.ndarray,
    *,
    west: float = 500_000,
    nodata: int | None = 255,
) -> bytes:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    profile = {
        "driver": "GTiff",
        "height": values.shape[0],
        "width": values.shape[1],
        "count": 1,
        "dtype": "uint8",
        "crs": "EPSG:32643",
        "transform": from_origin(west, 1_600_030, 10, 10),
        "nodata": nodata,
    }
    buffer = BytesIO()
    with rasterio.open(buffer, "w", **profile) as raster:
        raster.write(values.astype(np.uint8), 1)
    return buffer.getvalue()


def _metadata(**overrides: Any) -> ValidationMetadata:
    values = {
        "river_id": "tungabhadra",
        "candidate_product_id": "NISAR_A009",
        "candidate_sensor": "NISAR L-band GCOV",
        "candidate_acquisition_datetime": "2026-11-06T00:25:20Z",
        "reference_dataset_id": "INDEPENDENT_REFERENCE_1",
        "reference_provider": "Reviewed field survey",
        "reference_acquisition_datetime": "2026-11-06T03:00:00Z",
        "reference_resolution_m": 10,
        "reviewer": "reviewer-1",
        "review_date": date(2026, 11, 9),
        "independent_review_completed": True,
        "reference_methodology": "Independent review of georeferenced field observations.",
        "limitations": ["Small sample area."],
        "minimum_common_pixels": 2,
        "minimum_coverage_fraction": 0.5,
        "minimum_pixels_per_class": 1,
        "spatial_block_size_pixels": 1,
        "minimum_blocks_per_class": 1,
    }
    values.update(overrides)
    return ValidationMetadata.model_validate(values)


def test_independent_mask_validation_computes_metrics_on_common_valid_support(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path)
    candidate = np.asarray([[1, 1, 0], [1, 0, 255]], dtype=np.uint8)
    reference = np.asarray([[1, 0, 0], [0, 0, 1]], dtype=np.uint8)

    result = validation.compare_independent_masks(
        _mask_bytes(candidate),
        _mask_bytes(reference),
        _metadata(),
    )

    assert result.status == "validation_completed"
    assert result.confusion_matrix == {
        "true_positive": 1,
        "true_negative": 2,
        "false_positive": 2,
        "false_negative": 0,
    }
    assert result.precision == pytest.approx(1 / 3)
    assert result.recall == 1
    assert result.f1_score == 0.5
    assert result.intersection_over_union == pytest.approx(1 / 3)
    assert result.candidate_valid_pixel_count == 5
    assert result.reference_valid_pixel_count_on_candidate_grid == 6
    assert result.common_valid_pixel_count == 5
    assert result.valid_reference_coverage_fraction == 1
    assert result.resampling == "nearest"
    assert result.acquisition_time_difference_seconds == 9280
    assert validation.get_validation_report(result.validation_id).model_dump(mode="json")["acquisition_time_difference_seconds"] == 9280
    assert validation.get_validation_report(result.validation_id) == result


def test_validation_handles_no_overlap_and_single_reference_class(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path)
    candidate = np.zeros((2, 2), dtype=np.uint8)
    reference = np.ones((2, 2), dtype=np.uint8)

    no_overlap = validation.compare_independent_masks(
        _mask_bytes(candidate),
        _mask_bytes(reference, west=600_000),
        _metadata(),
    )
    assert no_overlap.status == "insufficient_spatial_overlap"
    assert no_overlap.common_valid_pixel_count == 0
    assert no_overlap.precision is None

    one_class = validation.compare_independent_masks(
        _mask_bytes(candidate),
        _mask_bytes(np.zeros((2, 2), dtype=np.uint8)),
        _metadata(),
    )
    assert one_class.status == "insufficient_valid_labels"
    assert one_class.confusion_matrix is not None
    assert one_class.precision is None
    assert one_class.intersection_over_union is None


def test_validation_excludes_internal_invalid_mask_pixels(monkeypatch: Any, tmp_path: Any) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin

    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path)
    labels = np.asarray([[0, 1], [1, 0]], dtype=np.uint8)
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff", width=2, height=2, count=1, dtype="uint8",
            crs="EPSG:32643", transform=from_origin(500_000, 1_600_030, 10, 10),
            nodata=255,
        ) as dataset:
            dataset.write(labels, 1)
            dataset.write_mask(np.asarray([[255, 0], [255, 255]], dtype=np.uint8))
        candidate = memory.read()
    result = validation.compare_independent_masks(candidate, _mask_bytes(labels), _metadata())
    assert result.common_valid_pixel_count == 3
    assert result.confusion_matrix == {
        "true_positive": 1, "true_negative": 2, "false_positive": 0, "false_negative": 0,
    }


def test_validation_rejects_bad_classes_and_missing_nodata_declaration() -> None:
    candidate = np.asarray([[0, 1], [1, 0]], dtype=np.uint8)
    invalid_labels = _mask_bytes(np.asarray([[0, 2], [1, 0]], dtype=np.uint8))
    with pytest.raises(ValueError, match="labels must be 0, 1, or 255"):
        validation.compare_independent_masks(
            _mask_bytes(candidate),
            invalid_labels,
            _metadata(),
        )

    with pytest.raises(ValueError, match="255 as uncertain/NoData"):
        validation.compare_independent_masks(
            _mask_bytes(candidate),
            _mask_bytes(candidate, nodata=None),
            _metadata(),
        )


def test_validation_api_exposes_pending_state_and_report(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path)
    status = client.get("/api/analysis/validation/status")
    assert status.status_code == 200
    assert status.json()["status"] == "validation_pending"
    assert status.json()["message"] == (
        "Independent scientific validation pending. No suitable reviewed reference labels "
        "are currently available."
    )

    candidate = np.asarray([[1, 1, 0], [1, 0, 255]], dtype=np.uint8)
    reference = np.asarray([[1, 0, 0], [0, 0, 1]], dtype=np.uint8)
    response = client.post(
        "/api/analysis/validation",
        data={"metadata_json": json.dumps(_metadata().model_dump(mode="json"))},
        files={
            "candidate_file": ("candidate.tif", _mask_bytes(candidate), "image/tiff"),
            "reference_file": ("reference.tif", _mask_bytes(reference), "image/tiff"),
        },
    )
    assert response.status_code == 201, response.text
    report = response.json()
    assert report["status"] == "validation_completed"
    fetched = client.get(report["report_url"])
    assert fetched.status_code == 200
    assert fetched.json() == report


def test_reference_source_catalog_explains_temporal_and_geometric_limits() -> None:
    response = client.get("/api/analysis/reference-sources")

    assert response.status_code == 200
    sources = {item["source_id"]: item for item in response.json()}
    assert sources["jrc-global-surface-water-v1-5"]["nominal_resolution_m"] == 30
    assert "1984–2024" in sources["jrc-global-surface-water-v1-5"]["temporal_coverage"]
    assert "not event-date labels" in sources["jrc-global-surface-water-v1-5"]["intended_use"]
    assert sources["jrc-global-surface-water-v1-5"]["access_url"].startswith("https://")
    assert "Global" in sources["jrc-global-surface-water-v1-5"]["geographic_coverage"]
    assert "CRS" in sources["usgs-landsat-collection-2-level-2"]["spatial_reference"]
    assert "not certify active channel axes" in sources["nwic-cwc-river-network"]["limitation"]
    assert "active channel axes" in sources["nwic-cwc-river-network"]["limitation"]
    assert sources["nwic-cwc-river-network"]["access_url"].endswith("/download/river_network.geojson")
    assert "356,234,820 bytes" in sources["nwic-cwc-river-network"]["access_notes"]
    assert "too coarse" in sources["hydrorivers-v1"]["limitation"]


def test_import_reviewed_reference_raster_persists_provenance_without_claiming_authentication(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    monkeypatch.setattr(validation, "REFERENCE_DATA_DIR", tmp_path / "references")
    labels = _mask_bytes(np.asarray([[1, 0, 255], [0, 1, 0]], dtype=np.uint8))
    metadata = ReferenceDataImportMetadata.model_validate(
        {
            "dataset_id": "REVIEWED_FIELD_SAMPLE",
            "provider": "Test field survey",
            "source_url": "https://example.test/field-survey",
            "acquisition_datetime": "2026-11-06T03:00:00Z",
            "resolution_m": 10,
            "crs": "EPSG:32643",
            "license": "Test license",
            "reviewer": "reviewer-1",
            "review_date": "2026-11-09",
            "review_method": "Independent manual interpretation of field georeferenced observations.",
            "independent_review_completed": True,
            "limitations": ["Small test-only footprint."],
        }
    )

    record = validation.import_reviewed_reference_data(labels, metadata)

    path, fetched_record = validation.reference_data_labels_path(record.reference_id)
    assert path.read_bytes() == labels
    assert fetched_record == record
    assert validation.list_reference_data() == [record]
    assert record.label_counts == {"0": 3, "1": 2, "255": 1}
    assert "not independently authenticated" in record.review_attestation


def test_reference_import_requires_review_attestation_and_consistent_grid(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    monkeypatch.setattr(validation, "REFERENCE_DATA_DIR", tmp_path / "references")
    metadata = {
        "dataset_id": "UNREVIEWED",
        "provider": "Test source",
        "source_url": "https://example.test/source",
        "acquisition_datetime": "2026-11-06T03:00:00Z",
        "resolution_m": 10,
        "crs": "EPSG:32643",
        "license": "Test license",
        "reviewer": "reviewer-1",
        "review_date": "2026-11-09",
        "review_method": "Manual review.",
        "independent_review_completed": False,
        "limitations": ["Test."],
    }
    with pytest.raises(ValueError, match="independently reviewed"):
        validation.import_reviewed_reference_data(
            _mask_bytes(np.asarray([[1, 0], [1, 0]], dtype=np.uint8)),
            ReferenceDataImportMetadata.model_validate(metadata),
        )
    metadata["independent_review_completed"] = True
    metadata["resolution_m"] = 20
    with pytest.raises(ValueError, match="resolution differs"):
        validation.import_reviewed_reference_data(
            _mask_bytes(np.asarray([[1, 0], [1, 0]], dtype=np.uint8)),
            ReferenceDataImportMetadata.model_validate(metadata),
        )
    assert not (tmp_path / "references").exists()


def test_classification_methods_share_support_and_do_not_auto_select_winner(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    monkeypatch.setattr(validation, "METHOD_EVALUATION_DIR", tmp_path / "methods")
    candidate_a = np.asarray([[1, 1, 0], [1, 0, 255]], dtype=np.uint8)
    candidate_b = np.asarray([[1, 0, 0], [0, 0, 0]], dtype=np.uint8)
    reference = np.asarray([[1, 0, 0], [0, 0, 1]], dtype=np.uint8)
    metadata = MethodEvaluationMetadata.model_validate(
        {
            "reference_metadata": _metadata().model_dump(mode="json"),
            "methods": [
                {"method_id": "otsu", "method_name": "Otsu threshold", "parameters": {"window": 0}},
                {"method_id": "fixed", "method_name": "Fixed threshold", "parameters": {"threshold_db": -12}},
            ],
        }
    )

    result = validation.compare_classification_methods(
        [_mask_bytes(candidate_a), _mask_bytes(candidate_b)],
        _mask_bytes(reference),
        metadata,
    )

    assert result.status == "evaluation_completed"
    assert result.shared_common_valid_pixel_count == 5
    assert result.methods[0]["confusion_matrix"] == {
        "true_positive": 1,
        "true_negative": 2,
        "false_positive": 2,
        "false_negative": 0,
    }
    assert result.methods[1]["confusion_matrix"] == {
        "true_positive": 1,
        "true_negative": 4,
        "false_positive": 0,
        "false_negative": 0,
    }
    assert "No best method is selected automatically" in result.warnings[3]
    assert validation.get_method_evaluation_report(result.evaluation_id) == result
    assert result.methods[0]["candidate_area_m2"] == 300
    assert result.methods[1]["candidate_area_m2"] == 100
    assert result.methods[1]["difference_from_first_area_m2"] == 200


@pytest.mark.parametrize(
    "overrides",
    [
        {"minimum_common_pixels": None, "minimum_coverage_fraction": None},
        {"minimum_common_pixels": 5},
        {"minimum_coverage_fraction": 0.76},
        {"minimum_pixels_per_class": None},
        {"minimum_pixels_per_class": 2},
        {"spatial_block_size_pixels": None},
        {"spatial_block_size_pixels": 2, "minimum_blocks_per_class": 2},
        {"minimum_blocks_per_class": None},
    ],
)
def test_evidence_thresholds_withhold_metrics_and_do_not_complete_status(
    monkeypatch: Any, tmp_path: Any, overrides: dict[str, Any],
) -> None:
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path / "validation")
    monkeypatch.setattr(validation, "REFERENCE_DATA_DIR", tmp_path / "references")
    candidate = _mask_bytes(np.asarray([[0, 1], [1, 0]], dtype=np.uint8))
    reference = _mask_bytes(np.asarray([[0, 1], [255, 0]], dtype=np.uint8))
    result = validation.compare_independent_masks(candidate, reference, _metadata(**overrides))
    assert result.status == "insufficient_evidence"
    assert (result.precision, result.recall, result.f1_score, result.intersection_over_union) == (None, None, None, None)
    status = validation.validation_status()
    assert status.status == "validation_pending"
    assert status.reports == [result]
    method_metadata = MethodEvaluationMetadata(
        reference_metadata=_metadata(**overrides),
        methods=[
            {"method_id": "one", "method_name": "One", "parameters": {}},
            {"method_id": "two", "method_name": "Two", "parameters": {}},
        ],
    )
    monkeypatch.setattr(validation, "METHOD_EVALUATION_DIR", tmp_path / "methods")
    comparison = validation.compare_classification_methods([reference, reference], candidate, method_metadata)
    assert comparison.status == "insufficient_evidence"
    assert all(method["f1_score"] is None for method in comparison.methods)


def test_method_comparison_rejects_reference_without_declared_nodata() -> None:
    mask = np.asarray([[0, 1], [1, 0]], dtype=np.uint8)
    metadata = MethodEvaluationMetadata(
        reference_metadata=_metadata(),
        methods=[
            {"method_id": "one", "method_name": "One", "parameters": {}},
            {"method_id": "two", "method_name": "Two", "parameters": {}},
        ],
    )
    with pytest.raises(ValueError, match="255 as uncertain/NoData"):
        validation.compare_classification_methods(
            [_mask_bytes(mask), _mask_bytes(mask)], _mask_bytes(mask, nodata=None), metadata,
        )


def test_exploratory_method_comparison_uses_shared_support_without_accuracy() -> None:
    first = _mask_bytes(np.asarray([[1, 1], [0, 255]], dtype=np.uint8))
    second = _mask_bytes(np.asarray([[0, 1], [0, 1]], dtype=np.uint8))
    metadata = {
        "river_id": "kaveri",
        "candidate_product_id": "fixture",
        "methods": [
            {"method_id": "one", "method_name": "One", "parameters": {}},
            {"method_id": "two", "method_name": "Two", "parameters": {}},
        ],
    }
    response = client.post(
        "/api/analysis/validation/methods/exploratory",
        data={"metadata_json": json.dumps(metadata)},
        files=[
            ("candidate_files", ("one.tif", first, "image/tiff")),
            ("candidate_files", ("two.tif", second, "image/tiff")),
        ],
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "exploratory_comparison"
    assert result["shared_common_valid_pixel_count"] == 3
    assert result["shared_grid_coverage_fraction"] == 0.75
    assert result["methods"][0]["candidate_area_m2"] == 200
    assert result["methods"][1]["candidate_area_m2"] == 100
    assert result["methods"][1]["difference_from_first_area_m2"] == 100
    pair = result["pairwise_comparisons"][0]
    assert pair["absolute_area_difference_m2"] == 100
    assert pair["area_difference_fraction_of_first"] == 0.5
    assert pair["disagreement_fraction"] == pytest.approx(1 / 3)
    assert pair["intersection_over_union"] == 0.5
    assert "precision" not in result["methods"][0]
    assert any("no method is selected" in warning.lower() for warning in result["warnings"])
    mismatched = client.post(
        "/api/analysis/validation/methods/exploratory",
        data={"metadata_json": json.dumps(metadata)},
        files=[
            ("candidate_files", ("one.tif", first, "image/tiff")),
            ("candidate_files", ("two.tif", _mask_bytes(np.zeros((2, 2), dtype=np.uint8), west=500_005), "image/tiff")),
        ],
    )
    assert mismatched.status_code == 422
    assert "exactly the same" in mismatched.json()["detail"]
    empty = client.post(
        "/api/analysis/validation/methods/exploratory",
        data={"metadata_json": json.dumps(metadata)},
        files=[
            ("candidate_files", ("one.tif", _mask_bytes(np.full((2, 2), 255, dtype=np.uint8)), "image/tiff")),
            ("candidate_files", ("two.tif", second, "image/tiff")),
        ],
    )
    assert empty.status_code == 200
    assert empty.json()["status"] == "insufficient_spatial_overlap"
    assert empty.json()["methods"][0]["candidate_area_m2"] is None
    assert empty.json()["pairwise_comparisons"][0]["intersection_over_union"] is None


def test_windowed_comparison_matches_in_memory_reference_across_windows(monkeypatch: Any) -> None:
    from app.schemas.validation import ExploratoryMethodMetadata

    monkeypatch.setattr(validation, "COMPARISON_WINDOW_SIZE", 3)
    rng = np.random.default_rng(42)
    arrays = [rng.choice([0, 1, 255], size=(9, 11), p=[0.45, 0.45, 0.1]).astype(np.uint8) for _ in range(3)]
    metadata = ExploratoryMethodMetadata.model_validate({
        "river_id": "kaveri", "candidate_product_id": "fixture",
        "methods": [{"method_id": str(i), "method_name": str(i), "parameters": {}} for i in range(3)],
    })
    result = validation.compare_exploratory_methods([_mask_bytes(a) for a in arrays], metadata)
    shared = np.logical_and.reduce([a != 255 for a in arrays])
    assert result.shared_common_valid_pixel_count == int(shared.sum())
    assert result.processing["windows_processed"] == 12
    for i, method in enumerate(result.methods):
        assert method["candidate_area_m2"] == int(np.count_nonzero(shared & (arrays[i] == 1))) * 100
    for pair, (i, j) in zip(result.pairwise_comparisons, ((0, 1), (0, 2), (1, 2))):
        a, b = shared & (arrays[i] == 1), shared & (arrays[j] == 1)
        assert pair.disagreement_pixel_count == int(np.count_nonzero(a ^ b))
        assert pair.intersection_over_union == pytest.approx(np.count_nonzero(a & b) / np.count_nonzero(a | b))


def test_windowed_comparison_handles_aligned_partial_and_disjoint_grids() -> None:
    from app.schemas.validation import ExploratoryMethodMetadata

    metadata = ExploratoryMethodMetadata.model_validate({
        "river_id": "kaveri", "candidate_product_id": "fixture",
        "methods": [{"method_id": name, "method_name": name, "parameters": {}} for name in ("a", "b")],
    })
    a = _mask_bytes(np.asarray([[0, 1, 1], [1, 0, 255]], dtype=np.uint8))
    b = _mask_bytes(np.asarray([[1, 0], [1, 1]], dtype=np.uint8), west=500_010)
    result = validation.compare_exploratory_methods([a, b], metadata)
    assert result.shared_common_valid_pixel_count == 3
    assert result.shared_grid_coverage_fraction == 0.5
    assert [item["candidate_pixel_count"] for item in result.methods] == [2, 2]
    assert result.pairwise_comparisons[0].disagreement_pixel_count == 2
    disjoint = validation.compare_exploratory_methods([a, _mask_bytes(np.zeros((2, 2), dtype=np.uint8), west=600_000)], metadata)
    assert disjoint.status == "insufficient_spatial_overlap"
    assert disjoint.pairwise_comparisons[0].intersection_over_union is None


def test_windowed_comparison_accepts_large_controlled_rasters_and_enforces_work_limit(monkeypatch: Any) -> None:
    from app.schemas.validation import ExploratoryMethodMetadata

    labels = np.zeros((2100, 2100), dtype=np.uint8)
    labels[100:200, 300:400] = 1
    labels[0:10] = 255
    raster = _mask_bytes(labels)
    metadata = ExploratoryMethodMetadata.model_validate({
        "river_id": "kaveri", "candidate_product_id": "fixture",
        "methods": [{"method_id": name, "method_name": name, "parameters": {}} for name in ("a", "b")],
    })
    result = validation.compare_exploratory_methods([raster, raster], metadata)
    assert result.shared_common_valid_pixel_count == 2100 * 2090
    assert result.methods[0]["candidate_area_m2"] == 1_000_000
    assert result.pairwise_comparisons[0].intersection_over_union == 1
    assert result.processing["windows_processed"] == 25
    monkeypatch.setattr(validation, "MAX_COMPARISON_PIXEL_READS", 100)
    with pytest.raises(ValueError, match="pixel-read limit"):
        validation.compare_exploratory_methods([raster, raster], metadata)


def test_windowed_comparison_enforces_time_limit_and_busy_status(monkeypatch: Any) -> None:
    from app.schemas.validation import ExploratoryMethodMetadata

    metadata = ExploratoryMethodMetadata.model_validate({
        "river_id": "kaveri", "candidate_product_id": "fixture",
        "methods": [{"method_id": name, "method_name": name, "parameters": {}} for name in ("a", "b")],
    })
    raster = _mask_bytes(np.ones((2, 2), dtype=np.uint8))
    times = iter((0, validation.MAX_COMPARISON_SECONDS + 1))
    monkeypatch.setattr(validation, "time", SimpleNamespace(monotonic=lambda: next(times)))
    with pytest.raises(ValueError, match="processing time limit"):
        validation.compare_exploratory_methods([raster, raster], metadata)
    assert validation._EXPLORATORY_COMPARISON_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(validation.ComparisonBusy):
            validation.compare_exploratory_methods([raster, raster], metadata)
    finally:
        validation._EXPLORATORY_COMPARISON_LOCK.release()


def test_pairwise_comparison_covers_all_pairs_and_zero_union() -> None:
    from app.schemas.validation import ExploratoryMethodMetadata

    empty = _mask_bytes(np.zeros((2, 2), dtype=np.uint8))
    one = _mask_bytes(np.asarray([[1, 0], [0, 0]], dtype=np.uint8))
    metadata = ExploratoryMethodMetadata.model_validate({
        "river_id": "kaveri",
        "candidate_product_id": "fixture",
        "candidate_acquisition_datetime": "2026-11-06T00:25:20Z",
        "methods": [
            {"method_id": name, "method_name": name, "parameters": {}}
            for name in ("a", "b", "c")
        ],
    })
    result = validation.compare_exploratory_methods([empty, empty, one], metadata)
    assert len(result.pairwise_comparisons) == 3
    assert result.pairwise_comparisons[0].intersection_over_union is None
    assert result.pairwise_comparisons[0].absolute_area_difference_m2 == 0
    assert result.pairwise_comparisons[1].area_difference_fraction_of_first is None
    assert result.pairwise_comparisons[1].intersection_over_union == 0
    assert result.candidate_acquisition_datetime == metadata.candidate_acquisition_datetime


def test_spatial_blocks_and_class_counts_are_reported_on_shared_support(
    monkeypatch: Any, tmp_path: Any,
) -> None:
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path)
    labels = _mask_bytes(np.asarray([[0, 0, 1, 1], [0, 0, 1, 1]], dtype=np.uint8))
    result = validation.compare_independent_masks(
        labels, labels, _metadata(minimum_pixels_per_class=4, spatial_block_size_pixels=2),
    )
    assert result.status == "validation_completed"
    assert result.reference_class_counts == {"0": 4, "1": 4}
    assert result.reference_class_block_counts == {"0": 1, "1": 1}
    insufficient = validation.compare_independent_masks(
        labels, labels, _metadata(spatial_block_size_pixels=2, minimum_blocks_per_class=2),
    )
    assert insufficient.status == "insufficient_evidence"
    assert insufficient.precision is None


def test_evidence_thresholds_accept_exact_boundaries(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path / "validation")
    monkeypatch.setattr(validation, "METHOD_EVALUATION_DIR", tmp_path / "methods")
    candidate = _mask_bytes(np.asarray([[0, 1], [1, 0]], dtype=np.uint8))
    partial = _mask_bytes(np.asarray([[0, 1], [255, 0]], dtype=np.uint8))
    metadata = _metadata(minimum_common_pixels=3, minimum_coverage_fraction=0.75)
    result = validation.compare_independent_masks(candidate, partial, metadata)
    assert result.status == "validation_completed"
    assert result.minimum_common_pixels == 3
    assert result.minimum_coverage_fraction == 0.75
    comparison = validation.compare_classification_methods(
        [partial, partial], candidate,
        MethodEvaluationMetadata(
            reference_metadata=metadata,
            methods=[
                {"method_id": "one", "method_name": "One", "parameters": {}},
                {"method_id": "two", "method_name": "Two", "parameters": {}},
            ],
        ),
    )
    assert comparison.status == "evaluation_completed"
    assert comparison.shared_reference_coverage_fraction == 0.75
    assert comparison.minimum_common_pixels == 3
    assert comparison.reference_metadata == metadata


def test_legacy_reports_without_thresholds_are_withheld_without_rewriting(
    monkeypatch: Any, tmp_path: Any,
) -> None:
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path / "validation")
    monkeypatch.setattr(validation, "REFERENCE_DATA_DIR", tmp_path / "references")
    monkeypatch.setattr(validation, "METHOD_EVALUATION_DIR", tmp_path / "methods")
    mask = _mask_bytes(np.asarray([[0, 1], [1, 0]], dtype=np.uint8))
    result = validation.compare_independent_masks(mask, mask, _metadata())
    evaluation = validation.compare_classification_methods(
        [mask, mask], mask,
        MethodEvaluationMetadata(
            reference_metadata=_metadata(),
            methods=[
                {"method_id": "one", "method_name": "One", "parameters": {}},
                {"method_id": "two", "method_name": "Two", "parameters": {}},
            ],
        ),
    )
    paths = [
        validation.VALIDATION_DIR / result.validation_id / "result.json",
        validation.METHOD_EVALUATION_DIR / evaluation.evaluation_id / "result.json",
    ]
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("minimum_pixels_per_class")
        payload.pop("spatial_block_size_pixels")
        payload.pop("minimum_blocks_per_class")
        payload.pop("reference_class_counts")
        payload.pop("reference_class_block_counts")
        path.write_text(json.dumps(payload), encoding="utf-8")
    original = [path.read_bytes() for path in paths]
    fetched = client.get(result.report_url).json()
    assert fetched["status"] == "insufficient_evidence"
    assert fetched["precision"] is None
    assert client.get("/api/analysis/validation/status").json()["status"] == "validation_pending"
    method_report = client.get(evaluation.report_url).json()
    assert method_report["status"] == "insufficient_evidence"
    assert all(item["precision"] is None for item in method_report["methods"])
    assert [path.read_bytes() for path in paths] == original


def test_zero_true_positives_produce_zero_f1_when_defined(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path)
    candidate = _mask_bytes(np.asarray([[1, 0], [1, 0]], dtype=np.uint8))
    reference = _mask_bytes(np.asarray([[0, 1], [0, 1]], dtype=np.uint8))
    result = validation.compare_independent_masks(candidate, reference, _metadata())
    assert result.status == "validation_completed"
    assert result.f1_score == 0


def test_method_evaluation_rejects_mismatched_candidate_grids(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    monkeypatch.setattr(validation, "METHOD_EVALUATION_DIR", tmp_path / "methods")
    metadata = MethodEvaluationMetadata.model_validate(
        {
            "reference_metadata": _metadata().model_dump(mode="json"),
            "methods": [
                {"method_id": "one", "method_name": "Method one", "parameters": {}},
                {"method_id": "two", "method_name": "Method two", "parameters": {}},
            ],
        }
    )
    with pytest.raises(ValueError, match="exactly the same"):
        validation.compare_classification_methods(
            [
                _mask_bytes(np.zeros((2, 2), dtype=np.uint8)),
                _mask_bytes(np.zeros((2, 2), dtype=np.uint8), west=500_010),
            ],
            _mask_bytes(np.asarray([[0, 1], [1, 0]], dtype=np.uint8)),
            metadata,
        )


def test_reference_import_and_method_evaluation_apis(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    monkeypatch.setattr(validation, "VALIDATION_DIR", tmp_path / "validation")
    monkeypatch.setattr(validation, "REFERENCE_DATA_DIR", tmp_path / "references")
    monkeypatch.setattr(validation, "METHOD_EVALUATION_DIR", tmp_path / "methods")
    reference_metadata = {
        "dataset_id": "API_REFERENCE",
        "provider": "Test provider",
        "source_url": "https://example.test/reference",
        "acquisition_datetime": "2026-11-06T03:00:00Z",
        "resolution_m": 10,
        "crs": "EPSG:32643",
        "license": "Test",
        "reviewer": "reviewer",
        "review_date": "2026-11-09",
        "review_method": "Human labels reviewed independently.",
        "independent_review_completed": True,
        "limitations": ["API fixture."],
    }
    imported = client.post(
        "/api/analysis/reference-data",
        data={"metadata_json": json.dumps(reference_metadata)},
        files={
            "reference_file": (
                "reference.tif",
                _mask_bytes(np.asarray([[0, 1], [255, 0]], dtype=np.uint8)),
                "image/tiff",
            )
        },
    )
    assert imported.status_code == 201, imported.text
    reference_record = imported.json()
    assert client.get(reference_record["labels_url"]).content
    assert client.get("/api/analysis/reference-data").json()[0]["reference_id"] == reference_record["reference_id"]
    reference_status = client.get("/api/analysis/validation/status").json()
    assert reference_status["status"] == "reference_dataset_available"
    assert "not authenticated" in reference_status["message"]

    method_metadata = {
        "reference_metadata": _metadata().model_dump(mode="json"),
        "methods": [
            {"method_id": "method-a", "method_name": "Candidate A", "parameters": {"threshold": -10}},
            {"method_id": "method-b", "method_name": "Candidate B", "parameters": {"threshold": -12}},
        ],
    }
    candidate = _mask_bytes(np.asarray([[1, 0], [0, 1]], dtype=np.uint8))
    evaluated = client.post(
        "/api/analysis/validation/methods",
        data={"metadata_json": json.dumps(method_metadata)},
        files=[
            ("reference_file", ("reference.tif", _mask_bytes(np.asarray([[1, 0], [0, 1]], dtype=np.uint8)), "image/tiff")),
            ("candidate_files", ("a.tif", candidate, "image/tiff")),
            ("candidate_files", ("b.tif", candidate, "image/tiff")),
        ],
    )
    assert evaluated.status_code == 201, evaluated.text
    method_result = evaluated.json()
    assert method_result["status"] == "evaluation_completed"
    assert client.get(method_result["report_url"]).json() == method_result
