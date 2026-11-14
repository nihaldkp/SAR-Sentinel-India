import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

from app.main import app
from app.services import sentinel2, vegetation_validation


def _write_index(path: Path, values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:32644",
        transform=from_origin(500000, 1500000, 20, 20),
        nodata=-9999,
    ) as dataset:
        dataset.write(values.astype("float32"), 1)


def test_historical_comparison_uses_common_georeferenced_support(tmp_path, monkeypatch) -> None:
    data_root = tmp_path / "data" / "acquisitions" / "sentinel2"
    monkeypatch.setattr(sentinel2, "DATA_ROOT", data_root)
    monkeypatch.setattr(sentinel2, "CATALOG_PATH", data_root / "catalog.json")
    values = np.ones((4, 4), dtype="float32")
    later_values = values + 0.1
    for item_id, item_values in (("earlier", values), ("later", later_values)):
        for index_name in ("ndvi", "evi", "ndmi"):
            _write_index(
                data_root / "kaveri" / item_id / f"{index_name}.tif",
                item_values,
            )

    records = []
    for item_id, date in (("earlier", "2026-11-01T05:00:00Z"), ("later", "2026-11-13T05:00:00Z")):
        records.append({
            "river_id": "kaveri",
            "item_id": item_id,
            "status": "processed",
            "acquisition_datetime": date,
            "processor_version": sentinel2.PROCESSOR_VERSION,
            "crs": "EPSG:32644",
            "resolution_m": 20,
            "valid_pixel_count": 16,
            "output_paths": {
                name: f"acquisitions/sentinel2/kaveri/{item_id}/{name}.tif"
                for name in ("ndvi", "evi", "ndmi")
            },
        })
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / "catalog.json").write_text(json.dumps(records), encoding="utf-8")

    result = sentinel2.compare_observations("kaveri", "earlier", "later")

    assert result["status"] == "unvalidated_difference"
    assert result["common_valid_pixel_count"] == 16
    assert result["indices"]["ndvi"]["mean_difference"] == pytest.approx(0.1)
    assert result["interval_days"] == 12


def test_rendered_preview_is_rgba_with_transparent_nodata(tmp_path) -> None:
    path = tmp_path / "ndvi.tif"
    values = np.array([[0.5, -9999]], dtype="float32")
    _write_index(path, values)

    rendered = sentinel2.render_index_png(path)

    with rasterio.MemoryFile(rendered) as memory_file:
        with memory_file.open() as dataset:
            assert dataset.count == 4
            assert dataset.read(4).tolist() == [[255, 0]]


def test_preview_endpoint_uses_each_geotiff_not_cached_png(tmp_path, monkeypatch) -> None:
    root = tmp_path / "sentinel2"
    monkeypatch.setattr(sentinel2, "DATA_ROOT", root)
    folder = root / "kaveri" / "observation"
    values = np.array([[-1, 0, 1], [0.25, -9999, np.nan]], dtype="float32")
    for index, offset in (("ndvi", 0), ("evi", 0.1), ("ndmi", 0.2)):
        _write_index(folder / f"{index}.tif", np.where(np.isfinite(values) & (values != -9999), values + offset, values))
    # A stale cache must neither be required nor treated as source data.
    (folder / "ndvi.png").write_bytes(b"stale")

    client = TestClient(app)
    previews = []
    for index in ("ndvi", "evi", "ndmi"):
        response = client.get(f"/api/sentinel2/kaveri/observation/{index}/png")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "no-store"
        with rasterio.MemoryFile(response.content) as memory_file:
            with memory_file.open() as dataset:
                assert dataset.count == 4
                image = dataset.read()
                assert image[3].tolist() == [[255, 255, 255], [255, 0, 0]]
                assert len(np.unique(image[:3, 0, :], axis=1)) == 3
                previews.append(image)
    assert not np.array_equal(previews[0], previews[1])
    assert not np.array_equal(previews[1], previews[2])


def test_preview_respects_internal_mask_and_north_up_orientation(tmp_path) -> None:
    path = tmp_path / "ndvi.tif"
    _write_index(path, np.array([[-1, 0], [1, 0.5]], dtype="float32"))
    with rasterio.open(path, "r+") as dataset:
        dataset.write_mask(np.array([[255, 0], [255, 255]], dtype="uint8"))

    with rasterio.MemoryFile(sentinel2.render_index_png(path)) as memory_file:
        with memory_file.open() as dataset:
            image = dataset.read()
    assert image[:, 0, 0].tolist() == [49, 54, 149, 255]
    assert image[3, 0, 1] == 0
    assert image[:, 1, 0].tolist() == [0, 104, 55, 255]


def test_overview_retains_sparse_valid_samples_and_averages_them(tmp_path) -> None:
    path = tmp_path / "ndvi.tif"
    values = np.full((512, 512), -9999, dtype="float32")
    values[100, 100] = -1
    values[100, 101] = 1
    values[300, 300] = 1
    with rasterio.open(
        path, "w", driver="GTiff", height=512, width=512, count=1,
        dtype="float32", crs="EPSG:3857", transform=from_origin(0, 10240, 20, 20),
        nodata=-9999,
    ) as dataset:
        dataset.write(values, 1)

    with rasterio.MemoryFile(sentinel2.render_index_png(path, overview=True)) as memory_file:
        with memory_file.open() as dataset:
            image = dataset.read()

    assert image.shape == (4, 256, 256)
    assert np.count_nonzero(image[3]) >= 2
    assert np.count_nonzero(image[3] == 0) > 65000
    colors = image[:3, image[3] > 0].T
    assert any(np.all(color == [255, 255, 191]) for color in colors)
    assert any(np.all(color == [0, 104, 55]) for color in colors)


def test_cached_observation_bounds_match_preview_projection(tmp_path, monkeypatch) -> None:
    root = tmp_path / "sentinel2"
    monkeypatch.setattr(sentinel2, "DATA_ROOT", root)
    path = root / "kaveri" / "observation" / "ndvi.tif"
    _write_index(path, np.ones((3, 4), dtype="float32"))
    monkeypatch.setattr(sentinel2, "_load_catalog", lambda: [{
        "river_id": "kaveri", "item_id": "observation", "status": "processed",
        "bounds_wgs84": {"west": 0, "south": 0, "east": 0, "north": 0},
    }])

    record = sentinel2.get_observations("kaveri")["observations"][0]
    with rasterio.open(path) as dataset:
        projected = transform_bounds(dataset.crs, "EPSG:3857", *dataset.bounds)
    expected = transform_bounds("EPSG:3857", "EPSG:4326", *projected)
    assert list(record["bounds_wgs84"].values()) == pytest.approx(expected)


def test_grid_mismatch_reports_raster_statistics_without_changing_catalog(tmp_path, monkeypatch) -> None:
    root = tmp_path / "data" / "acquisitions" / "sentinel2"
    monkeypatch.setattr(sentinel2, "DATA_ROOT", root)
    monkeypatch.setattr(sentinel2, "CATALOG_PATH", root / "catalog.json")
    for name, value in (("ndvi", 0.1), ("evi", 0.2), ("ndmi", 0.3)):
        _write_index(root / "kaveri" / "item" / f"{name}.tif",
                     np.array([[value, -9999, value], [value, -9999, value]], dtype="float32"))
    stored = {
        "river_id": "kaveri", "item_id": "item", "status": "processed",
        "width": 1, "height": 1, "valid_pixel_count": 8, "valid_pixel_percent": 80,
        "corridor_pixel_count": 10, "processor_version": "old", "processed_at": "old",
        "output_paths": {name: f"acquisitions/sentinel2/kaveri/item/{name}.tif"
                         for name in ("ndvi", "evi", "ndmi")},
    }
    sentinel2.CATALOG_PATH.write_text(json.dumps([stored]), encoding="utf-8")
    result = sentinel2.get_observations("kaveri")["observations"][0]
    assert (result["width"], result["height"], result["valid_pixel_count"]) == (3, 2, 4)
    assert result["index_statistics"]["evi"]["mean"] == pytest.approx(0.2)
    assert result["valid_pixel_percent"] is None and result["corridor_pixel_count"] is None
    assert result["processor_version"] is None and result["processed_at"] is None
    assert result["raster_reconciliation"]["catalog_metadata"]["valid_pixel_count"] == 8
    assert json.loads(sentinel2.CATALOG_PATH.read_text(encoding="utf-8")) == [stored]
    with pytest.raises(ValueError, match="processing provenance is unresolved"):
        vegetation_validation._candidate(SimpleNamespace(river_id="kaveri", item_id="item", index_name="ndvi"))
    with pytest.raises(ValueError, match="catalog record describes a different raster grid"):
        sentinel2.compare_observations("kaveri", "item", "item")
