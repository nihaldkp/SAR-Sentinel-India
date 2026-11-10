import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.acquisitions import AcquisitionStatus, AcquiredObservation
from app.services import acquisitions, ai_analysis, validation
from app.schemas.ai_analysis import AnalysisProductOption

client = TestClient(app)


@pytest.mark.parametrize(
    ("report_status", "reference_attestation", "expected"),
    [
        (None, None, "independent_reference_unavailable"),
        (None, False, "reference_imported_unreviewed"),
        (None, True, "reviewed_reference_available"),
        ("insufficient_valid_labels", None, "insufficient_valid_labels"),
        ("insufficient_spatial_overlap", None, "insufficient_valid_labels"),
        ("insufficient_evidence", None, "evidence_thresholds_unmet"),
        ("thresholds_met_awaiting_evaluation", None, "thresholds_met_awaiting_evaluation"),
        ("evaluation_failed", None, "evaluation_rejected_or_failed"),
        ("evaluation_rejected", None, "evaluation_rejected_or_failed"),
        ("validation_completed", None, "sample_validation_completed"),
    ],
)
def test_ai_evidence_status_uses_matching_reports_and_reference_attestations(
    monkeypatch: pytest.MonkeyPatch, tmp_path, report_status, reference_attestation, expected,
) -> None:
    reports = []
    candidate_path = tmp_path / "candidate.tif"
    candidate_path.write_bytes(b"selected candidate")
    monkeypatch.setattr(acquisitions, "nisar_processing_output_path", lambda *args: candidate_path)
    if report_status:
        report = SimpleNamespace(
            status=report_status, river_id="tungabhadra", candidate_product_id="product",
            candidate_acquisition_datetime=datetime(2026, 11, 6, tzinfo=timezone.utc),
            independent_review_completed=True,
            candidate_processing_version="processor-v1",
            processing={"candidate_sha256": hashlib.sha256(b"selected candidate").hexdigest()},
        )
        reports.append(report)
    monkeypatch.setattr(validation, "list_validation_reports", lambda: reports)
    references = [] if reference_attestation is None else [
        SimpleNamespace(metadata=SimpleNamespace(independent_review_completed=reference_attestation))
    ]
    monkeypatch.setattr(validation, "list_reference_data", lambda: references)
    product = AnalysisProductOption(
        product_id="product", satellite="NISAR", acquisition_start=datetime(2026, 11, 6, tzinfo=timezone.utc),
        processing_status="processed", is_usable_candidate=True,
        processing_version="processor-v1",
    )
    status, explanation = ai_analysis._evidence_status("tungabhadra", product)
    assert status == expected
    assert explanation
    if report_status:
        assert ai_analysis._evidence_status("kaveri", product)[0] == "independent_reference_unavailable"
        shifted = product.model_copy(update={"acquisition_start": datetime(2026, 11, 7, tzinfo=timezone.utc)})
        assert ai_analysis._evidence_status("tungabhadra", shifted)[0] == "independent_reference_unavailable"
        changed_version = product.model_copy(update={"processing_version": "processor-v2"})
        assert ai_analysis._evidence_status("tungabhadra", changed_version)[0] == "independent_reference_unavailable"
        candidate_path.write_bytes(b"different candidate")
        assert ai_analysis._evidence_status("tungabhadra", product)[0] == "candidate_identity_unverified"


def test_ai_prefers_qualifying_assessment_over_insufficient_report(monkeypatch, tmp_path):
    candidate_path = tmp_path / "candidate.tif"
    candidate_path.write_bytes(b"candidate")
    digest = hashlib.sha256(b"candidate").hexdigest()
    common = dict(
        river_id="tungabhadra", candidate_product_id="product",
        candidate_acquisition_datetime=datetime(2026, 11, 6, tzinfo=timezone.utc),
        candidate_processing_version="processor-v1", independent_review_completed=True,
        processing={"candidate_sha256": digest},
    )
    monkeypatch.setattr(acquisitions, "nisar_processing_output_path", lambda *args: candidate_path)
    monkeypatch.setattr(validation, "list_validation_reports", lambda: [
        SimpleNamespace(status="insufficient_evidence", **common),
        SimpleNamespace(status="thresholds_met_awaiting_evaluation", **common),
    ])
    product = AnalysisProductOption(
        product_id="product", satellite="NISAR", acquisition_start=common["candidate_acquisition_datetime"],
        processing_status="processed", is_usable_candidate=True, processing_version="processor-v1",
    )
    assert ai_analysis._evidence_status("tungabhadra", product)[0] == "thresholds_met_awaiting_evaluation"


def _catalog() -> AcquisitionStatus:
    return AcquisitionStatus.model_validate(
        {
            "enabled": False,
            "polling_interval_seconds": 21600,
            "source": "Microsoft Planetary Computer Sentinel-1 RTC",
            "source_url": "https://planetarycomputer.microsoft.com/",
            "license": "CC-BY-4.0",
            "rivers": [
                {
                    "river_id": "kaveri",
                    "status": "no_data",
                    "nisar_status": "no_data",
                    "nisar_products": [],
                    "observations": [],
                    "issues": [],
                },
                {
                    "river_id": "tungabhadra",
                    "status": "processed",
                    "nisar_status": "metadata_found",
                    "nisar_products": [
                        {
                            "product_id": "NISAR_A009_FIXTURE",
                            "acquisition_start": "2026-11-06T00:25:20Z",
                            "product_level": "L2_GCOV",
                            "polarization": ["HH", "HV"],
                            "availability": "downloaded",
                            "download_status": "downloaded",
                            "processing_status": "processed",
                            "processing_result": {
                                "river_id": "tungabhadra",
                                "product_id": "NISAR_A009_FIXTURE",
                                "status": "unvalidated_candidate",
                                "processor_version": "fixture",
                                "algorithm": "fixture candidate",
                                "frequency": "A",
                                "dataset_paths": {},
                                "acquisition_start": "2026-11-06T00:25:20Z",
                                "polarization": ["HH", "HV"],
                                "input_crs": "EPSG:32643",
                                "pixel_size_m": 10,
                                "reference_centerline_coverage_percent": 42.5,
                                "reference_centerline_length_km": 10,
                                "covered_centerline_length_km": 4.25,
                                "corridor_half_width_m": 1500,
                                "corridor_pixel_count": 1000,
                                "valid_pixel_count": 800,
                                "valid_data_fraction": 0.8,
                                "water_pixel_count": 250,
                                "candidate_water_area_m2": 25000,
                                "candidate_water_area_lower_m2": 20000,
                                "candidate_water_area_upper_m2": 30000,
                                "hh_threshold_db": -12,
                                "hv_threshold_db": -18,
                                "threshold_sensitivity_db": 2,
                                "mask_width": 32,
                                "mask_height": 32,
                                "mask_url": "/mask.tif",
                                "measurements_url": None,
                                "polygons_url": "/polygons.geojson",
                                "optical_reference_url": "/optical-metadata",
                                "optical_candidate_mask_url": "/optical-mask",
                                "metadata_url": "/metadata.json",
                                "polygon_feature_count": 0,
                                "vectorization_truncated": False,
                                "polarization_comparison": [
                                    {"classification": "HH-only", "candidate_area_m2": 30000},
                                    {"classification": "HH+HV", "candidate_area_m2": 25000},
                                ],
                                "threshold_sensitivity": [
                                    {"offset_db": -2, "candidate_area_m2": 20000},
                                    {"offset_db": 0, "candidate_area_m2": 25000},
                                    {"offset_db": 2, "candidate_area_m2": 30000},
                                ],
                                "processing_completed_at": "2026-11-06T01:00:00Z",
                                "caveats": ["Exploratory candidate only."],
                            },
                        },
                        {
                            "product_id": "NISAR_A010_FIXTURE",
                            "acquisition_start": "2026-11-07T00:25:20Z",
                            "product_level": "L2_GCOV",
                            "availability": "downloaded",
                            "download_status": "downloaded",
                            "processing_status": "no_data",
                            "processing_result": {
                                "river_id": "tungabhadra",
                                "product_id": "NISAR_A010_FIXTURE",
                                "status": "no_valid_corridor_data",
                                "processor_version": "fixture",
                                "algorithm": "fixture candidate",
                                "frequency": "A",
                                "dataset_paths": {},
                                "polarization": ["HH", "HV"],
                                "input_crs": "EPSG:32643",
                                "pixel_size_m": 10,
                                "reference_centerline_coverage_percent": 0,
                                "reference_centerline_length_km": 10,
                                "covered_centerline_length_km": 0,
                                "corridor_half_width_m": 1500,
                                "corridor_pixel_count": 1000,
                                "valid_pixel_count": 0,
                                "valid_data_fraction": 0,
                                "water_pixel_count": None,
                                "candidate_water_area_m2": None,
                                "candidate_water_area_lower_m2": None,
                                "candidate_water_area_upper_m2": None,
                                "hh_threshold_db": None,
                                "hv_threshold_db": None,
                                "threshold_sensitivity_db": 2,
                                "mask_width": 32,
                                "mask_height": 32,
                                "mask_url": None,
                                "measurements_url": None,
                                "polygons_url": None,
                                "metadata_url": "/metadata.json",
                                "polygon_feature_count": 0,
                                "vectorization_truncated": False,
                                "processing_completed_at": "2026-11-07T01:00:00Z",
                                "caveats": ["No valid corridor data."],
                            },
                        },
                        {
                            "product_id": "NISAR_FAILED_FIXTURE",
                            "acquisition_start": "2026-11-08T00:25:20Z",
                            "product_level": "L2_GCOV",
                            "availability": "downloaded",
                            "download_status": "downloaded",
                            "processing_status": "failed",
                        },
                    ],
                    "observations": [],
                    "issues": [
                        {
                            "product_id": "S1_FAILED_FIXTURE",
                            "status": "failed",
                            "error": "Fixture failure",
                            "updated_at": "2026-11-08T01:00:00Z",
                        }
                    ],
                },
            ],
        }
    )


def test_ai_analysis_uses_real_catalog_metrics_and_preserves_no_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acquisitions, "get_catalog_status", _catalog)
    monkeypatch.setattr(
        acquisitions,
        "nisar_optical_reference_metadata",
        lambda river_id, product_id: {
            "status": "unvalidated_candidate",
            "ndwi_threshold": 0,
            "counts": {
                "common_valid_pixels": 1000,
                "ndwi_candidate_pixels": 100,
                "candidate_area_m2": 10000,
            },
            "grid": {"pixel_area_m2": 100},
            "source": {
                "item_id": "S2_FIXTURE",
                "acquisition_datetime": "2026-11-06T05:20:11Z",
            },
        },
    )

    response = client.post(
        "/api/analysis/ai-summary",
        json={"river_id": "tungabhadra", "product_id": "NISAR_A009_FIXTURE"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["analysis_mode"] == "deterministic_rule_based"
    assert result["selected_product_id"] == "NISAR_A009_FIXTURE"
    selected_provenance = next(
        product for product in result["products"]
        if product["product_id"] == "NISAR_A009_FIXTURE"
    )
    assert selected_provenance["source_name"] == "ASF DAAC"
    assert selected_provenance["product_type"] == "L2_GCOV"
    assert selected_provenance["acquisition_start"] == "2026-11-06T00:25:20Z"
    assert selected_provenance["polarization"] == ["HH", "HV"]
    assert selected_provenance["input_crs"] == "EPSG:32643"
    assert selected_provenance["pixel_size_m"] == 10
    assert result["coverage"]["catalog_product_count"] == 4
    assert result["coverage"]["usable_candidate_count"] == 1
    assert result["coverage"]["no_data_product_count"] == 1
    assert result["coverage"]["failed_product_count"] == 2
    assert result["candidate_metrics"]["candidate_water_pixel_count"] == 250
    assert result["candidate_metrics"]["candidate_water_area_km2"] == 0.025
    assert result["candidate_metrics"]["valid_data_fraction"] == 0.8
    assert result["candidate_metrics"]["no_data_fraction"] == pytest.approx(0.2)
    assert len(result["polarization_comparison"]) == 2
    assert result["threshold_sensitivity"]["candidate_area_range_percent"] == pytest.approx(40)
    assert result["optical_comparison"]["status"] == "exploratory_candidate_only"
    assert result["optical_comparison"]["common_valid_area_km2"] == 0.1
    assert result["validation_status"] == "independent_reference_unavailable"
    assert "accuracy" in " ".join(result["limitations"]).lower()

    default_response = client.post(
        "/api/analysis/ai-summary",
        json={"river_id": "tungabhadra"},
    )
    assert default_response.status_code == 200
    assert default_response.json()["selected_product_id"] == "NISAR_A009_FIXTURE"

    no_data_response = client.post(
        "/api/analysis/ai-summary",
        json={"river_id": "tungabhadra", "product_id": "NISAR_A010_FIXTURE"},
    )
    assert no_data_response.status_code == 200
    no_data_result = no_data_response.json()
    assert no_data_result["candidate_metrics"]["candidate_water_area_km2"] is None
    assert "no candidate-water result" in " ".join(no_data_result["findings"])


def test_ai_analysis_returns_explicit_empty_catalog_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog()
    catalog = catalog.model_copy(
        update={
            "rivers": [
                catalog.rivers[0].model_copy(update={"river_id": "tungabhadra"})
            ]
        }
    )
    monkeypatch.setattr(acquisitions, "get_catalog_status", lambda: catalog)

    response = client.post("/api/analysis/ai-summary", json={"river_id": "tungabhadra"})

    assert response.status_code == 200
    result = response.json()
    assert result["products"] == []
    assert result["selected_product_id"] is None
    assert result["candidate_metrics"] is None
    assert result["coverage"]["usable_candidate_count"] == 0
    assert result["temporal_comparison"]["status"] == "insufficient_observations"
    assert any("No usable processed candidate" in finding for finding in result["findings"])


def test_ai_analysis_rejects_unknown_product_and_river() -> None:
    response = client.post(
        "/api/analysis/ai-summary",
        json={"river_id": "tungabhadra", "product_id": "not-in-catalog"},
    )
    assert response.status_code == 404

    invalid_river = client.post(
        "/api/analysis/ai-summary",
        json={"river_id": "not-a-river"},
    )
    assert invalid_river.status_code == 422


def test_sentinel1_candidate_metrics_are_reported_without_validation_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog()
    river = catalog.rivers[0].model_copy(
        update={
            "river_id": "tungabhadra",
            "observations": [
                AcquiredObservation.model_validate({
                    "river_id": "tungabhadra",
                    "product_id": "S1_FIXTURE",
                    "mission": "SENTINEL-1",
                    "product_type": "GRD-RTC",
                    "acquisition_start": datetime(2026, 11, 6, tzinfo=timezone.utc),
                    "polarization": "VV",
                    "footprint": {},
                    "centerline_coverage_percent": 25,
                    "source": "Microsoft Planetary Computer",
                    "stac_item_url": "https://example.test/item",
                    "asset_source_url": "https://example.test/asset",
                    "source_license": "CC-BY-4.0",
                    "provider_processing": "RTC",
                    "processing_status": "unvalidated_candidate",
                    "analysis_id": "analysis-fixture",
                    "candidate_water_area_m2": 5000,
                    "candidate_water_area_lower_m2": 4000,
                    "candidate_water_area_upper_m2": 6000,
                    "threshold_db": -14,
                    "valid_pixel_count": 50,
                    "valid_data_fraction": 0.5,
                    "water_pixel_count": 5,
                    "filter_method": "fixture",
                    "input_crs": "EPSG:32643",
                    "pixel_size_m": 10,
                    "corridor_half_width_m": 1500,
                    "analysis_url": "/analysis",
                    "mask_url": "/mask",
                    "polygons_url": "/polygons",
                    "report_url": "/report",
                    "caveats": [],
                    "downloaded_at": datetime(2026, 11, 6, 1, tzinfo=timezone.utc),
                })
            ],
        }
    )
    catalog = catalog.model_copy(update={"rivers": [river]})
    monkeypatch.setattr(acquisitions, "get_catalog_status", lambda: catalog)

    response = client.post(
        "/api/analysis/ai-summary",
        json={"river_id": "tungabhadra", "product_id": "S1_FIXTURE"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["candidate_metrics"]["threshold_db"] == -14
    assert result["candidate_metrics"]["candidate_water_area_km2"] == 0.005
    assert result["candidate_metrics"]["valid_data_fraction"] == 0.5
    assert result["optical_comparison"]["available"] is False
    assert result["validation_status"] == "independent_reference_unavailable"
    selected_provenance = next(
        product for product in result["products"]
        if product["product_id"] == "S1_FIXTURE"
    )
    assert selected_provenance["source_name"] == "Microsoft Planetary Computer"
    assert selected_provenance["source_record_url"] == "https://example.test/item"
    assert selected_provenance["source_license"] == "CC-BY-4.0"
    assert selected_provenance["product_type"] == "GRD-RTC"
    assert "asset_source_url" not in selected_provenance
