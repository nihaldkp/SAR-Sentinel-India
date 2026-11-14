import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from app.services import nisar_gcov
from app.schemas.acquisitions import NisarProcessingResult

TEST_PRODUCT_ID = "NISAR_L2_UR_GCOV_TEST_001"


def _write_gcov_fixture(
    path: Path,
    *,
    include_hv: bool = True,
    valid_data: bool = True,
    product_id: str = TEST_PRODUCT_ID,
    normalization_convention: str = "gamma0",
    expression_convention: str = "Linear power",
) -> None:
    h5py = pytest.importorskip("h5py")
    height = width = 32
    x_coordinates = 500_005 + np.arange(width, dtype=np.float64) * 10
    y_coordinates = 4_500_155 - np.arange(height, dtype=np.float64) * 10
    with h5py.File(path, "w") as dataset:
        dataset.attrs["mission_name"] = "NISAR"
        dataset.attrs["title"] = "NISAR L2 GCOV Product"
        identification = dataset.create_group("science/LSAR/identification")
        for field, value in {
            "missionId": "NISAR",
            "platformName": "NISAR",
            "instrumentName": "LSAR",
            "productLevel": "L2",
            "productType": "GCOV",
            "granuleId": product_id,
        }.items():
            identification.create_dataset(field, data=np.bytes_(value))
        identification.create_dataset("listOfFrequencies", data=np.asarray([b"A"], dtype="S1"))
        rtc_parameters = dataset.create_group(
            "science/LSAR/GCOV/metadata/processingInformation/parameters/rtc"
        )
        rtc_parameters.create_dataset(
            "outputBackscatterNormalizationConvention",
            data=np.bytes_(normalization_convention),
        )
        rtc_parameters.create_dataset(
            "outputBackscatterExpressionConvention",
            data=np.bytes_(expression_convention),
        )
        grid = dataset.create_group("science/LSAR/GCOV/grids/frequencyA")
        projection = grid.create_dataset("projection", data=np.uint32(32643))
        projection.attrs["epsg_code"] = np.uint32(32643)
        grid.create_dataset("xCoordinates", data=x_coordinates)
        grid.create_dataset("yCoordinates", data=y_coordinates)
        grid.create_dataset("xCoordinateSpacing", data=np.float64(10))
        grid.create_dataset("yCoordinateSpacing", data=np.float64(-10))
        grid.create_dataset("listOfPolarizations", data=np.asarray([b"HH", b"HV"], dtype="S2"))
        validity_mask = np.ones((height, width), dtype=np.uint8) if valid_data else np.full(
            (height, width),
            255,
            dtype=np.uint8,
        )
        hh = np.full((height, width), 0.1, dtype=np.float32)
        hv = np.full((height, width), 0.03, dtype=np.float32)
        hh[14:18, :] = 0.001
        hv[14:18, :] = 0.0001
        hh[1, 1] = 0
        hv[1, 1] = 0
        hh[0, 0] = np.nan
        hv[0, 0] = np.nan
        validity_mask[0, 0] = 255

        grid.create_dataset("mask", data=validity_mask, chunks=(16, 16))
        hh_dataset = grid.create_dataset("HHHH", data=hh, chunks=(16, 16))
        hh_dataset.attrs["units"] = b"1"
        hh_dataset.attrs["grid_mapping"] = b"projection"
        hh_dataset.attrs["_FillValue"] = np.float32(np.nan)
        if include_hv:
            hv_dataset = grid.create_dataset("HVHV", data=hv, chunks=(16, 16))
            hv_dataset.attrs["units"] = b"1"
            hv_dataset.attrs["grid_mapping"] = b"projection"
            hv_dataset.attrs["_FillValue"] = np.float32(np.nan)


def _fixture_river() -> Any:
    from rasterio.warp import transform_geom
    from shapely.geometry import LineString, mapping

    projected_line = LineString([(500_015, 4_500_000), (500_285, 4_500_000)])
    geographic_line = transform_geom(
        "EPSG:32643",
        "EPSG:4326",
        mapping(projected_line),
        precision=8,
    )
    return SimpleNamespace(
        id="test-river",
        centerline=SimpleNamespace(model_dump=lambda: geographic_line),
    )


def test_process_small_gcov_fixture_preserves_georeferencing_and_nodata(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    rasterio = pytest.importorskip("rasterio")
    source_path = tmp_path / "small-gcov.h5"
    _write_gcov_fixture(source_path)
    monkeypatch.setattr(nisar_gcov, "RIVER_CATALOG", [_fixture_river()])

    result = nisar_gcov.process_gcov_product(
        source_path,
        TEST_PRODUCT_ID,
        "test-river",
        tmp_path / "processing",
    )

    assert result["status"] == "unvalidated_candidate"
    metadata = json.loads(
        (tmp_path / "processing" / "processing-metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert metadata["scientific_validation_status"] == "not_performed"
    assert result["dataset_paths"]["hh"].endswith("/HHHH")
    assert result["dataset_paths"]["hv"].endswith("/HVHV")
    assert result["input_crs"] == "EPSG:32643"
    assert result["pixel_size_m"] == 10
    assert result["polarization"] == ["HH", "HV"]
    assert result["input_measurement_convention"] == "gamma0 linear power"
    assert result["input_backscatter_normalization_convention"] == "gamma0"
    assert result["input_backscatter_expression_convention"] == "Linear power"
    assert result["power_to_db_conversion"] == "10*log10(max(power, 1e-6))"
    assert result["power_to_db_floor_linear"] == pytest.approx(1e-6)
    assert result["power_to_db_floor_db"] == pytest.approx(-60)
    assert result["valid_pixel_count"] == 1023
    assert result["corridor_pixel_count"] == 1024
    assert result["valid_data_fraction"] == pytest.approx(1023 / 1024)
    assert result["water_pixel_count"] > 0
    assert result["candidate_water_area_m2"] == result["water_pixel_count"] * 100
    assert result["reference_centerline_coverage_percent"] == pytest.approx(100)

    diagnostics = nisar_gcov.build_classification_diagnostics(
        tmp_path / "processing" / "gcov-measurements.tif",
        tmp_path / "processing" / "candidate-water-mask.tif",
        tmp_path / "processing",
        result["hh_threshold_db"],
        result["hv_threshold_db"],
        100,
    )
    comparison = {
        item["classification"]: item["candidate_pixel_count"]
        for item in diagnostics["polarization_comparison"]
    }
    assert comparison["HH-only"] >= comparison["HH+HV"]
    assert comparison["HV-only"] >= comparison["HH+HV"]
    assert all(
        item["candidate_area_m2"] == item["candidate_pixel_count"] * 100
        for item in diagnostics["polarization_comparison"]
    )
    sensitivity_counts = [
        item["candidate_pixel_count"] for item in diagnostics["threshold_sensitivity"]
    ]
    assert sensitivity_counts == sorted(sensitivity_counts)
    assert sensitivity_counts[2] == result["water_pixel_count"]
    assert [item["offset_db"] for item in diagnostics["threshold_sensitivity"]] == [
        -2,
        -1,
        0,
        1,
        2,
    ]
    assert diagnostics["connected_component_summary"]["connectivity"] == 8
    assert diagnostics["connected_component_summary"]["component_count"] > 0

    with rasterio.open(tmp_path / "processing" / "candidate-water-mask.tif") as mask:
        assert mask.crs.to_string() == "EPSG:32643"
        assert mask.res == (10, 10)
        assert mask.transform.e == -10
        assert mask.nodata == 255
        values = mask.read(1)
        assert values[0, 0] == 255
        assert set(np.unique(values)).issubset({0, 1, 255})
    with rasterio.open(tmp_path / "processing" / "gcov-measurements.tif") as measurements:
        assert measurements.count == 2
        assert measurements.crs.to_string() == "EPSG:32643"
        assert measurements.nodata is not None and np.isnan(measurements.nodata)
        assert measurements.descriptions == (
            "HHHH linear covariance power",
            "HVHV linear covariance power",
        )
        values = measurements.read(1)
        assert np.isnan(values[0, 0])
        assert values[1, 1] == 0
        assert values[15, 0] == pytest.approx(0.001)
        assert values[4, 4] == pytest.approx(0.1)
    with rasterio.open(tmp_path / "processing" / "polarization-comparison.tif") as comparison:
        assert comparison.count == 3
        assert comparison.crs.to_string() == "EPSG:32643"
        assert comparison.nodata == 255
        assert comparison.descriptions == ("HH-only", "HV-only", "HH+HV combined")
        values = comparison.read()
        assert np.all(values[:, 0, 0] == 255)
        assert set(np.unique(values)).issubset({0, 1, 255})
    with rasterio.open(tmp_path / "processing" / "threshold-sensitivity.tif") as sensitivity:
        assert sensitivity.count == 5
        assert sensitivity.crs.to_string() == "EPSG:32643"
        assert sensitivity.nodata == 255
        assert np.all(sensitivity.read()[:, 0, 0] == 255)
        assert set(np.unique(sensitivity.read())).issubset({0, 1, 255})
    polygons = json.loads((tmp_path / "processing" / "candidate-water.geojson").read_text())
    assert polygons["type"] == "FeatureCollection"
    assert all(feature["properties"]["class"] == "unvalidated_candidate_open_water" for feature in polygons["features"])


def test_connected_components_merge_across_tile_and_diagonal_boundaries(tmp_path: Path) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import Affine

    path = tmp_path / "component-mask.tif"
    values = np.full((520, 520), 255, dtype=np.uint8)
    values[10, 255:257] = 1
    values[255, 255] = 1
    values[256, 256] = 1
    values[510, 510] = 1
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=520,
        height=520,
        count=1,
        dtype="uint8",
        crs="EPSG:32643",
        transform=Affine(10, 0, 0, 0, -10, 5200),
        nodata=255,
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as output:
        output.write(values, 1)

    with rasterio.open(path) as source:
        summary = nisar_gcov._connected_component_summary(source)

    assert summary == {
        "connectivity": 8,
        "component_count": 3,
        "isolated_pixel_component_count": 1,
        "components_up_to_four_pixels": 3,
        "pixels_in_components_up_to_four": 5,
        "largest_component_pixels": 2,
    }


def test_component_sensitivity_outputs_are_separate_and_preserve_nodata(
    tmp_path: Path,
) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import Affine

    source_path = tmp_path / "candidate-mask.tif"
    original = np.zeros((32, 32), dtype=np.uint8)
    original[0, 0] = 255
    original[2, 2] = 1
    original[8, 8:10] = 1
    original[15, 15:18] = 1
    with rasterio.open(
        source_path,
        "w",
        driver="GTiff",
        width=32,
        height=32,
        count=1,
        dtype="uint8",
        crs="EPSG:32643",
        transform=Affine(10, 0, 500_000, 0, -10, 1_350_000),
        nodata=255,
        tiled=True,
        blockxsize=16,
        blockysize=16,
    ) as output:
        output.write(original, 1)

    output_directory = tmp_path / "component-sensitivity"
    results = nisar_gcov.build_component_sensitivity_outputs(
        source_path,
        output_directory,
        [2, 3],
    )

    assert [item["minimum_component_pixels"] for item in results] == [2, 3]
    assert results[0]["candidate_pixel_count_before"] == 6
    assert results[0]["candidate_pixel_count_after"] == 5
    assert results[0]["candidate_pixels_reclassified_nonwater"] == 1
    assert results[1]["candidate_pixel_count_after"] == 3
    assert results[1]["candidate_pixels_reclassified_nonwater"] == 3
    assert results[0]["nodata_pixel_count_preserved"] == 1
    assert "not a validated cleanup" in results[0]["quality_flags"][0]

    first_path = (
        output_directory / "minimum-2-pixels-8-connectivity" / "candidate-water-mask.tif"
    )
    second_path = (
        output_directory / "minimum-3-pixels-8-connectivity" / "candidate-water-mask.tif"
    )
    with rasterio.open(source_path) as source, rasterio.open(first_path) as first, rasterio.open(
        second_path
    ) as second:
        assert np.array_equal(source.read(1), original)
        assert first.crs.to_string() == "EPSG:32643"
        assert first.transform == source.transform
        assert first.nodata == 255
        assert first.read(1)[0, 0] == 255
        assert first.read(1)[2, 2] == 0
        assert first.read(1)[8, 8] == 1
        assert second.read(1)[8, 8] == 0
        assert second.read(1)[15, 15] == 1

    cached = nisar_gcov.build_component_sensitivity_outputs(
        source_path,
        output_directory,
        [3, 2],
    )
    assert [item["minimum_component_pixels"] for item in cached] == [2, 3]


def test_gcov_processor_rejects_missing_hv_dataset(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "missing-hv.h5"
    _write_gcov_fixture(source_path, include_hv=False)
    monkeypatch.setattr(nisar_gcov, "RIVER_CATALOG", [_fixture_river()])

    with pytest.raises(ValueError, match="missing required frequency-A datasets"):
        nisar_gcov.process_gcov_product(
            source_path,
            TEST_PRODUCT_ID,
            "test-river",
            tmp_path / "processing",
        )


def test_gcov_processor_rejects_river_outside_product_extent(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "small-gcov.h5"
    _write_gcov_fixture(source_path)
    monkeypatch.setattr(nisar_gcov, "RIVER_CATALOG", [])

    with pytest.raises(ValueError, match="Unsupported river_id"):
        nisar_gcov.process_gcov_product(
            source_path,
            TEST_PRODUCT_ID,
            "missing-river",
            tmp_path / "processing",
        )


def test_gcov_processor_reports_no_data_without_fabricating_a_mask(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "no-valid-pixels.h5"
    _write_gcov_fixture(source_path, valid_data=False)
    monkeypatch.setattr(nisar_gcov, "RIVER_CATALOG", [_fixture_river()])
    output_directory = tmp_path / "processing"

    result = nisar_gcov.process_gcov_product(
        source_path,
        TEST_PRODUCT_ID,
        "test-river",
        output_directory,
    )

    assert result["status"] == "no_valid_corridor_data"
    assert NisarProcessingResult.model_validate(result).status == "no_valid_corridor_data"
    assert result["input_measurement_convention"] == "gamma0 linear power"
    assert result["power_to_db_conversion"] == "10*log10(max(power, 1e-6))"
    assert result["corridor_pixel_count"] > 0
    assert result["valid_pixel_count"] == 0
    assert result["candidate_water_area_m2"] is None
    assert result["hh_threshold_db"] is None
    assert result["mask_url"] is None
    assert not (output_directory / "candidate-water-mask.tif").exists()
    assert not (output_directory / "gcov-measurements.tif").exists()
    assert (output_directory / "processing-metadata.json").is_file()


@pytest.mark.parametrize(
    ("normalization_convention", "expression_convention"),
    [("sigma0", "Linear power"), ("gamma0", "Decibels")],
)
def test_gcov_processor_rejects_unsupported_measurement_conventions(
    tmp_path: Path,
    monkeypatch: Any,
    normalization_convention: str,
    expression_convention: str,
) -> None:
    source_path = tmp_path / "unsupported-convention.h5"
    _write_gcov_fixture(
        source_path,
        normalization_convention=normalization_convention,
        expression_convention=expression_convention,
    )
    monkeypatch.setattr(nisar_gcov, "RIVER_CATALOG", [_fixture_river()])

    with pytest.raises(ValueError, match="requires gamma0 measurements expressed as linear power"):
        nisar_gcov.process_gcov_product(
            source_path,
            TEST_PRODUCT_ID,
            "test-river",
            tmp_path / "processing",
        )
