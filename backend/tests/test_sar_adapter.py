
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import rasterio
from rasterio.transform import from_origin

from app.services import sar_adapter
from app.services.sar_adapter import NisarGcovAdapter


def fake_processor(
    *,
    hdf5_path,
    product_id,
    river_id,
    output_directory,
):
    output_directory.mkdir(parents=True)

    transform = from_origin(500000, 1000, 10, 10)

    for filename, count in [
        ("candidate-water-mask.tif", 1),
        ("gcov-measurements.tif", 2),
    ]:
        with rasterio.open(
            output_directory / filename,
            "w",
            driver="GTiff",
            height=10,
            width=10,
            count=count,
            dtype="float32",
            crs="EPSG:32643",
            transform=transform,
            nodata=-9999.0,
        ) as dataset:
            for band in range(1, count + 1):
                dataset.write(
                    np.ones((10, 10), dtype=np.float32),
                    band,
                )

    (output_directory / "candidate-water.geojson").write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [],
                },
            }],
        }),
        encoding="utf-8",
    )

    (output_directory / "processing-metadata.json").write_text(
        json.dumps({
            "status": "unvalidated_candidate",
            "scientific_validation_status": "not_performed",
        }),
        encoding="utf-8",
    )

    return {
        "status": "unvalidated_candidate",
        "pixel_count": 100,
    }


def test_nisar_gcov_adapter_generates_correct_storage_keys(
    tmp_path, monkeypatch
):
    source_file = tmp_path / "source.h5"
    source_file.write_bytes(b"test")

    job_id = "adapter-test-job"
    job_directory = tmp_path / job_id
    job_directory.mkdir()

    monkeypatch.setattr(
        sar_adapter,
        "process_gcov_product",
        fake_processor,
    )

    request = SimpleNamespace(
        job_id=job_id,
        output_directory=job_directory,
        local_file_path=source_file,
        acquisition=SimpleNamespace(
            product_id="test-product",
            river_id="test-river",
        ),
        processing_version="test-version",
    )

    result = NisarGcovAdapter().process(request)

    expected_keys = {
        f"{job_id}/nisar-gcov/candidate-water-mask.tif",
        f"{job_id}/nisar-gcov/gcov-measurements.tif",
        f"{job_id}/nisar-gcov/candidate-water.geojson",
        f"{job_id}/nisar-gcov/processing-metadata.json",
    }

    actual_keys = {output.storage_key for output in result.outputs}

    assert actual_keys == expected_keys
    assert result.result_metadata["scientific_validation_status"] == (
        "not_performed"
    )
    assert result.result_metadata["status"] == "unvalidated_candidate"


def test_nisar_gcov_adapter_rejects_missing_source(tmp_path):
    job_directory = tmp_path / "job"
    job_directory.mkdir()

    request = SimpleNamespace(
        job_id="missing-source-job",
        output_directory=job_directory,
        local_file_path=tmp_path / "missing.h5",
        acquisition=SimpleNamespace(
            product_id="test-product",
            river_id="test-river",
        ),
        processing_version="test-version",
    )

    import pytest

    with pytest.raises(FileNotFoundError):
        NisarGcovAdapter().process(request)
