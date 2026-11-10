import json
import uuid
from types import SimpleNamespace
from typing import Any

import numpy as np
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.services import acquisitions, analysis

client = TestClient(app)


def _unavailable_rasterio() -> Any:
    raise analysis.ProcessingUnavailable("Rasterio is unavailable for this test.")


def _water_mask_metadata(**overrides: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "river_id": "kaveri",
        "mission": "SENTINEL-1",
        "product_type": "GRD_HD",
        "source_product_id": "operator-supplied-product-id",
        "acquisition_start": "2026-10-01T00:00:00Z",
        "polarization": "VV",
        "band_description": "calibrated VV backscatter",
        "signal_scale": "decibels",
        "radiometric_calibration_confirmed": True,
        "terrain_correction_confirmed": True,
        "threshold_method": "otsu",
    }
    metadata.update(overrides)
    return metadata


def test_lee_filter_preserves_invalid_pixels_and_positive_power() -> None:
    power = np.ones((20, 20), dtype=np.float32)
    power[:, 10:] = 10
    valid = np.ones(power.shape, dtype=bool)
    valid[0, 0] = False

    filtered = analysis._lee_filter(power, valid)

    assert np.isnan(filtered[0, 0])
    assert np.isfinite(filtered[valid]).all()
    assert (filtered[valid] > 0).all()


def test_otsu_threshold_separates_two_backscatter_modes() -> None:
    values = np.array([-20.0] * 100 + [-5.0] * 100)

    threshold = analysis._otsu_threshold_db(values)

    assert -20 < threshold < -5


def test_analysis_status_surfaces_geospatial_runtime_availability(monkeypatch: Any) -> None:
    monkeypatch.setattr(analysis, "_require_rasterio", _unavailable_rasterio)

    response = client.get("/api/analysis/status")

    assert response.status_code == 200
    assert response.json()["geotiff_processing_available"] is False
    assert response.json()["raw_product_preprocessing_available"] is False
    assert response.json()["real_satellite_product_downloaded"] is False
    assert "Rasterio is unavailable" in response.json()["unavailable_reason"]


def test_water_mask_upload_reports_dependency_unavailability_without_fallback(monkeypatch: Any) -> None:
    monkeypatch.setattr(analysis, "_require_rasterio", _unavailable_rasterio)

    response = client.post(
        "/api/analysis/water-mask",
        data={"metadata_json": json.dumps(_water_mask_metadata())},
        files={"file": ("input.tif", b"not a real raster", "image/tiff")},
    )

    assert response.status_code == 503
    assert "Rasterio is unavailable for this test." in response.json()["detail"]
    assert "synthetic" not in response.json()["detail"].lower()


def test_water_mask_rejects_products_without_supported_scalar_export() -> None:
    response = client.post(
        "/api/analysis/water-mask",
        data={"metadata_json": json.dumps(_water_mask_metadata(product_type="SLC"))},
        files={"file": ("input.tif", b"not a real raster", "image/tiff")},
    )

    assert response.status_code == 422
    assert "not accepted" in response.json()["detail"]


def test_water_mask_requires_timezone_and_threshold_consistency() -> None:
    missing_timezone = _water_mask_metadata(acquisition_start="2026-10-01T00:00:00")
    response = client.post(
        "/api/analysis/water-mask",
        data={"metadata_json": json.dumps(missing_timezone)},
        files={"file": ("input.tif", b"not a real raster", "image/tiff")},
    )
    assert response.status_code == 422

    invalid_threshold = _water_mask_metadata(threshold_method="fixed_db")
    response = client.post(
        "/api/analysis/water-mask",
        data={"metadata_json": json.dumps(invalid_threshold)},
        files={"file": ("input.tif", b"not a real raster", "image/tiff")},
    )
    assert response.status_code == 422


def test_width_measurement_validates_wgs84_coordinates() -> None:
    response = client.post(
        "/api/analysis/width",
        json={
            "analysis_id": "analysis",
            "start": [200.0, 12.0],
            "end": [76.1, 12.1],
        },
    )

    assert response.status_code == 422


def test_analysis_output_rejects_recorded_paths_outside_analysis_directory(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.setattr(analysis, "OUTPUT_DIR", tmp_path)
    analysis_id = str(uuid.uuid4())
    directory = tmp_path / analysis_id
    directory.mkdir()
    (tmp_path / "outside.tif").write_bytes(b"fixture")
    (directory / "result.json").write_text(json.dumps({"output_files": {"mask": "../outside.tif"}}), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        analysis.read_output(analysis_id, "../outside.tif")


@pytest.mark.parametrize("position", [[999, 0], [0, 91], [True, 1], [1, "bad"], [1, 2, 3, 4]])
def test_axis_sampling_rejects_invalid_wgs84_positions(position: list[Any]) -> None:
    response = client.post("/api/analysis/width/river-axis", json={
        "analysis_id": "analysis",
        "axis_dataset_id": "fixture",
        "axis_source_name": "fixture",
        "axis_source_url": "https://example.test/axis",
        "axis_geojson": {"type": "LineString", "coordinates": [[75, 12], position]},
        "corridor_geojson": {"type": "Polygon", "coordinates": [[[75, 12], [76, 12], [76, 13], [75, 12]]]},
        "station_spacing_m": 20,
        "transect_half_length_m": 20,
    })
    assert response.status_code == 422


def test_river_axis_sampling_reports_candidate_width_and_quality_without_claiming_uncertainty(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin
    from rasterio.warp import transform_geom
    from shapely.geometry import LineString, box, mapping

    analysis_id = "7c0ed299-c1b9-4cc7-a59e-f312d41ae339"
    output_dir = tmp_path / "analysis"
    analysis_dir = output_dir / analysis_id
    analysis_dir.mkdir(parents=True)
    monkeypatch.setattr(analysis, "OUTPUT_DIR", output_dir)
    values = np.zeros((100, 100), dtype=np.uint8)
    values[48:53, :] = 1
    values[:, 10:20] = 255
    with rasterio.open(
        analysis_dir / "water-mask.tif",
        "w",
        driver="GTiff",
        height=100,
        width=100,
        count=1,
        dtype="uint8",
        crs="EPSG:32643",
        transform=from_origin(500_000, 1_600_000, 10, 10),
        nodata=255,
    ) as dataset:
        dataset.write(values, 1)
    (analysis_dir / "result.json").write_text(
        json.dumps(
            {
                "status": "unvalidated_candidate",
                "source_product_id": "NISAR_A009_FIXTURE",
                "acquisition_start": "2026-11-06T00:25:20Z",
            }
        ),
        encoding="utf-8",
    )
    line = LineString([(500_150, 1_599_515), (500_950, 1_599_515)])
    corridor = box(500_000, 1_599_000, 501_000, 1_600_000)
    request = {
        "analysis_id": analysis_id,
        "axis_dataset_id": "CWC-TEST-AXIS",
        "axis_source_name": "Test-only user-supplied axis",
        "axis_source_url": "https://example.test/axis",
        "axis_geojson": transform_geom("EPSG:32643", "EPSG:4326", mapping(line)),
        "corridor_geojson": transform_geom("EPSG:32643", "EPSG:4326", mapping(corridor)),
        "station_spacing_m": 200,
        "transect_half_length_m": 100,
        "minimum_valid_fraction": 0.8,
    }

    response = client.post("/api/analysis/width/river-axis", json=request)

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["source_product_id"] == "NISAR_A009_FIXTURE"
    assert result["axis_geometry_status"] == "user_supplied_not_independently_verified"
    assert result["requested_station_count"] == 5
    assert result["accepted_station_count"] == 4
    assert result["coverage_fraction"] == pytest.approx(0.8)
    assert result["uncertainty_m"] is None
    assert result["uncertainty_status"] == "not_quantified"
    assert all(sample["candidate_width_m"] == pytest.approx(50) for sample in result["samples"][1:])
    assert result["samples"][0]["quality_status"] == "outside_raster"
    assert result["samples"][1]["quality_status"] == "usable_candidate"
    assert any("not independently verified" in item.lower() for item in result["quality_flags"])


def test_river_axis_sampling_does_not_join_candidate_segments_across_corridor_gaps(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin
    from rasterio.warp import transform_geom
    from shapely.geometry import LineString, MultiPolygon, box, mapping

    analysis_id = "0ea2ce38-2382-468f-a3e8-e57270340b4a"
    output_dir = tmp_path / "analysis"
    analysis_dir = output_dir / analysis_id
    analysis_dir.mkdir(parents=True)
    monkeypatch.setattr(analysis, "OUTPUT_DIR", output_dir)
    values = np.zeros((100, 100), dtype=np.uint8)
    values[[40, 48, 56], :] = 1
    with rasterio.open(
        analysis_dir / "water-mask.tif",
        "w",
        driver="GTiff",
        height=100,
        width=100,
        count=1,
        dtype="uint8",
        crs="EPSG:32643",
        transform=from_origin(500_000, 1_600_000, 10, 10),
        nodata=255,
    ) as dataset:
        dataset.write(values, 1)
    (analysis_dir / "result.json").write_text(
        json.dumps(
            {
                "status": "unvalidated_candidate",
                "source_product_id": "NISAR_AXIS_GAP_FIXTURE",
                "acquisition_start": "2026-11-06T00:25:20Z",
            }
        ),
        encoding="utf-8",
    )
    line = LineString([(500_150, 1_599_515), (500_950, 1_599_515)])
    corridor = MultiPolygon(
        [
            box(500_000, 1_599_514, 501_000, 1_599_516),
            box(500_000, 1_599_594, 501_000, 1_599_596),
            box(500_000, 1_599_434, 501_000, 1_599_436),
        ]
    )
    response = client.post(
        "/api/analysis/width/river-axis",
        json={
            "analysis_id": analysis_id,
            "axis_dataset_id": "DISCONNECTED-CORRIDOR-FIXTURE",
            "axis_source_name": "Test-only geometry",
            "axis_source_url": "https://example.test/axis",
            "axis_geojson": transform_geom("EPSG:32643", "EPSG:4326", mapping(line)),
            "corridor_geojson": transform_geom("EPSG:32643", "EPSG:4326", mapping(corridor)),
            "station_spacing_m": 200,
            "transect_half_length_m": 100,
            "minimum_valid_fraction": 0.5,
        },
    )

    assert response.status_code == 200, response.text
    sample = response.json()["samples"][1]
    assert sample["candidate_width_m"] == pytest.approx(10)


def test_river_axis_sampling_rejects_axis_outside_corridor(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin
    from rasterio.warp import transform_geom
    from shapely.geometry import LineString, box, mapping

    analysis_id = "3a58ef10-47a2-42f8-b1e2-274d5bd35c45"
    output_dir = tmp_path / "analysis"
    analysis_dir = output_dir / analysis_id
    analysis_dir.mkdir(parents=True)
    monkeypatch.setattr(analysis, "OUTPUT_DIR", output_dir)
    with rasterio.open(
        analysis_dir / "water-mask.tif",
        "w",
        driver="GTiff",
        height=20,
        width=20,
        count=1,
        dtype="uint8",
        crs="EPSG:32643",
        transform=from_origin(500_000, 1_600_000, 10, 10),
        nodata=255,
    ) as dataset:
        dataset.write(np.zeros((20, 20), dtype=np.uint8), 1)
    (analysis_dir / "result.json").write_text(
        json.dumps(
            {
                "status": "unvalidated_candidate",
                "source_product_id": "NISAR_TEST",
                "acquisition_start": "2026-11-06T00:25:20Z",
            }
        ),
        encoding="utf-8",
    )
    request = {
        "analysis_id": analysis_id,
        "axis_dataset_id": "AXIS-OUTSIDE",
        "axis_source_name": "Test axis",
        "axis_source_url": "https://example.test/axis",
        "axis_geojson": transform_geom(
            "EPSG:32643",
            "EPSG:4326",
            mapping(LineString([(500_100, 1_599_800), (500_300, 1_599_800)])),
        ),
        "corridor_geojson": transform_geom(
            "EPSG:32643",
            "EPSG:4326",
            mapping(box(500_100, 1_599_000, 500_300, 1_599_500)),
        ),
        "station_spacing_m": 100,
        "transect_half_length_m": 100,
    }

    response = client.post("/api/analysis/width/river-axis", json=request)

    assert response.status_code == 422
    assert "fully contain" in response.json()["detail"]


def test_change_and_width_endpoints_surface_processing_unavailability(monkeypatch: Any) -> None:
    monkeypatch.setattr(analysis, "_require_rasterio", _unavailable_rasterio)

    comparison = client.post(
        "/api/analysis/change",
        json={"earlier_analysis_id": "earlier", "later_analysis_id": "later"},
    )
    width = client.post(
        "/api/analysis/width",
        json={
            "analysis_id": "analysis",
            "start": [76.0, 12.0],
            "end": [76.1, 12.1],
        },
    )

    assert comparison.status_code == 503
    assert width.status_code == 503


def test_water_mask_raises_distinct_no_data_error_for_invalid_pixels(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin

    monkeypatch.setattr(analysis, "OUTPUT_DIR", tmp_path)
    profile = {
        "driver": "GTiff",
        "height": 20,
        "width": 20,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:32643",
        "transform": from_origin(500000, 1350000, 10, 10),
        "nodata": -32768,
    }
    with MemoryFile() as memory_file:
        with memory_file.open(**profile) as dataset:
            dataset.write(np.full((20, 20), -32768, dtype=np.float32), 1)
        raster_bytes = memory_file.read()

    from app.schemas.analysis import WaterMaskRequest

    request = WaterMaskRequest.model_validate(_water_mask_metadata())
    with pytest.raises(analysis.InsufficientValidDataError, match="fewer than 32"):
        analysis.process_water_mask(raster_bytes, request)

    assert list(tmp_path.iterdir()) == []


def test_complete_analysis_workflow_with_geotiff_unit_fixtures(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    try:
        from rasterio.io import MemoryFile
        from rasterio.transform import from_origin
        from rasterio.warp import transform
    except ImportError as error:
        pytest.skip(f"Rasterio is not usable in this environment: {error}")

    monkeypatch.setattr(analysis, "OUTPUT_DIR", tmp_path)
    profile = {
        "driver": "GTiff",
        "height": 20,
        "width": 20,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:32643",
        "transform": from_origin(500000, 1350000, 10, 10),
    }

    def raster_fixture(extra_water_rows: int) -> bytes:
        values = np.full((20, 20), -5, dtype=np.float32)
        values[8 : 12 + extra_water_rows, :] = -20
        with MemoryFile() as memory_file:
            with memory_file.open(**profile) as dataset:
                dataset.write(values, 1)
            return memory_file.read()

    def upload(product_id: str, acquisition_start: str, extra_water_rows: int) -> dict[str, Any]:
        metadata = _water_mask_metadata(
            source_product_id=product_id,
            acquisition_start=acquisition_start,
            band_description="synthetic unit-test fixture only",
        )
        response = client.post(
            "/api/analysis/water-mask",
            data={"metadata_json": json.dumps(metadata)},
            files={"file": ("fixture.tif", raster_fixture(extra_water_rows), "image/tiff")},
        )
        assert response.status_code == 200, response.text
        return response.json()

    first = upload("TEST_FIXTURE_1", "2026-10-01T00:00:00Z", 0)
    later = upload("TEST_FIXTURE_2", "2026-10-02T00:00:00Z", 2)

    assert first["status"] == "unvalidated_candidate"
    assert first["candidate_water_area_m2"] == 8_000
    assert first["candidate_water_area_lower_m2"] <= first["candidate_water_area_m2"]
    assert first["candidate_water_area_upper_m2"] >= first["candidate_water_area_m2"]
    assert first["threshold_sensitivity_range_db"] == 1
    assert later["candidate_water_area_m2"] == 12_000
    assert any("do not by themselves isolate a river channel" in caveat for caveat in first["caveats"])
    assert not any("not clipped to a river corridor" in caveat for caveat in first["caveats"])

    contextual_result = analysis.process_water_mask(
        raster_fixture(0),
        analysis.WaterMaskRequest.model_validate(
            _water_mask_metadata(source_product_id="TEST_CORRIDOR_CONTEXT")
        ),
        additional_caveats=("The analyzed raster is limited to the documented river corridor.",),
    )
    persisted_context = analysis._load_result(contextual_result.analysis_id)
    assert "The analyzed raster is limited to the documented river corridor." in persisted_context["caveats"]

    mask_response = client.get(first["mask_url"])
    polygon_response = client.get(first["polygons_url"])
    report_response = client.get(first["report_url"])
    assert mask_response.status_code == 200
    assert polygon_response.status_code == 200
    assert polygon_response.json()["crs"]["properties"]["name"] == "EPSG:4326"
    assert report_response.status_code == 200
    assert report_response.content.startswith(b"%PDF-")
    with MemoryFile(mask_response.content) as memory_file, memory_file.open() as mask:
        assert mask.crs.to_string() == "EPSG:32643"
        assert set(np.unique(mask.read(1))) == {0, 1}

    comparison_response = client.post(
        "/api/analysis/change",
        json={
            "earlier_analysis_id": first["analysis_id"],
            "later_analysis_id": later["analysis_id"],
        },
    )
    assert comparison_response.status_code == 200
    comparison = comparison_response.json()
    assert comparison["candidate_water_gain_area_m2"] == 4_000
    assert comparison["candidate_water_loss_area_m2"] == 0
    assert comparison["earlier_source_product_id"] == "TEST_FIXTURE_1"
    assert comparison["later_source_product_id"] == "TEST_FIXTURE_2"
    assert comparison["common_valid_pixel_count"] == 400
    assert comparison["common_valid_area_m2"] == 40_000
    assert comparison["common_valid_fraction"] == 1
    assert comparison["threshold_method"] == "otsu"

    pairs = analysis.list_compatible_candidate_pairs([
        SimpleNamespace(
            analysis_id=first["analysis_id"],
            acquisition_start=first["acquisition_start"],
            river_id=first["river_id"],
            stac_item_url="https://example.test/first",
        ),
        SimpleNamespace(
            analysis_id=later["analysis_id"],
            acquisition_start=later["acquisition_start"],
            river_id=later["river_id"],
            stac_item_url="https://example.test/later",
        ),
    ])
    assert len(pairs) == 1
    assert pairs[0].common_valid_pixel_count == 400
    assert pairs[0].elapsed_days == pytest.approx(1)
    assert "no seasonal adjustment" in pairs[0].seasonal_context
    monkeypatch.setattr(
        acquisitions,
        "get_catalog_status",
        lambda: SimpleNamespace(
            rivers=[
                SimpleNamespace(
                    river_id="kaveri",
                    observations=[
                        SimpleNamespace(
                            analysis_id=first["analysis_id"],
                            acquisition_start=first["acquisition_start"],
                            river_id="kaveri",
                            stac_item_url="https://example.test/first",
                        ),
                        SimpleNamespace(
                            analysis_id=later["analysis_id"],
                            acquisition_start=later["acquisition_start"],
                            river_id="kaveri",
                            stac_item_url="https://example.test/later",
                        ),
                    ],
                )
            ]
        ),
    )
    pair_response = client.get("/api/analysis/temporal-pairs", params={"river_id": "kaveri"})
    assert pair_response.status_code == 200
    assert pair_response.json()[0]["common_valid_pixel_count"] == 400

    longitudes, latitudes = transform(
        "EPSG:32643",
        "EPSG:4326",
        [500100, 500100],
        [1349960, 1349840],
    )
    width_response = client.post(
        "/api/analysis/width",
        json={
            "analysis_id": first["analysis_id"],
            "start": [longitudes[0], latitudes[0]],
            "end": [longitudes[1], latitudes[1]],
        },
    )
    assert width_response.status_code == 200
    assert width_response.json()["longest_contiguous_water_width_m"] == pytest.approx(40, abs=1)


def test_comparison_rejects_mismatched_processing_provenance() -> None:
    earlier = {
        "analysis_type": "water_mask",
        "status": "unvalidated_candidate",
        "river_id": "kaveri",
        "acquisition_start": "2026-10-01T00:00:00Z",
        "source_product_id": "S1_EARLIER",
        "mission": "SENTINEL-1",
        "polarization": "VV",
        "threshold_method": "otsu",
        "threshold_db": -10,
        "filter_method": "Lee 5x5",
        "operator_supplied_metadata": {
            "mission": "SENTINEL-1",
            "product_type": "GRD-RTC",
            "polarization": "VV",
            "signal_scale": "linear_power",
            "threshold_method": "otsu",
            "source_product_id": "S1_EARLIER",
            "radiometric_calibration_confirmed": True,
            "terrain_correction_confirmed": True,
        },
    }
    later = {
        **earlier,
        "acquisition_start": "2026-10-02T00:00:00Z",
        "source_product_id": "S1_LATER",
        "operator_supplied_metadata": {
            **earlier["operator_supplied_metadata"],
            "source_product_id": "S1_LATER",
            "polarization": "VH",
        },
    }

    with pytest.raises(analysis.IncompatibleCandidatePair, match="polarization"):
        analysis._comparison_metadata(earlier, later)
