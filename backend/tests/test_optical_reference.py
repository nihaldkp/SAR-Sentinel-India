import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.services.optical_reference import (
    _color_candidate_classes,
    _encode_rgba_png,
    create_candidate_preview,
    create_ndwi_candidate,
)


def _write_raster(
    path: Path,
    values: np.ndarray,
    *,
    transform: Any,
    dtype: str,
    nodata: int,
) -> None:
    rasterio = pytest.importorskip("rasterio")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype=dtype,
        crs="EPSG:32643",
        transform=transform,
        nodata=nodata,
    ) as output:
        output.write(values, 1)


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path, dict[str, Any]]:
    from rasterio.transform import Affine
    from shapely.geometry import mapping, box
    from rasterio.warp import transform_geom

    nisar_mask = tmp_path / "nisar-mask.tif"
    band03 = tmp_path / "B03.tif"
    band08 = tmp_path / "B08.tif"
    scl = tmp_path / "SCL.tif"
    transform = Affine(10, 0, 500_000, 0, -10, 4_500_040)
    mask_values = np.zeros((4, 4), dtype=np.uint8)
    mask_values[0, 0] = 255
    _write_raster(nisar_mask, mask_values, transform=transform, dtype="uint8", nodata=255)

    b03_values = np.full((4, 4), 1_000, dtype=np.uint16)
    b08_values = np.full((4, 4), 1_000, dtype=np.uint16)
    b03_values[1:3, 1:3] = 2_000
    _write_raster(band03, b03_values, transform=transform, dtype="uint16", nodata=0)
    _write_raster(band08, b08_values, transform=transform, dtype="uint16", nodata=0)

    scl_transform = Affine(20, 0, 500_000, 0, -20, 4_500_040)
    scl_values = np.asarray([[4, 3], [6, 5]], dtype=np.uint8)
    _write_raster(scl, scl_values, transform=scl_transform, dtype="uint8", nodata=0)
    footprint = transform_geom(
        "EPSG:32643",
        "EPSG:4326",
        mapping(box(500_000, 4_500_000, 500_040, 4_500_040)),
        precision=8,
    )
    return nisar_mask, band03, band08, scl, footprint


def test_ndwi_candidate_resamples_masks_and_preserves_nodata(tmp_path: Path) -> None:
    rasterio = pytest.importorskip("rasterio")
    nisar_mask, band03, band08, scl, footprint = _write_inputs(tmp_path)
    output_directory = tmp_path / "result"
    result = create_ndwi_candidate(
        band03_path=band03,
        band08_path=band08,
        scl_path=scl,
        nisar_mask_path=nisar_mask,
        footprint=footprint,
        output_directory=output_directory,
        source_metadata={"item_id": "fixture-item"},
    )

    assert result["status"] == "unvalidated_candidate"
    assert result["counts"]["corridor_pixels_in_footprint"] == 15
    assert result["counts"]["clear_scl_pixels_in_corridor"] == 11
    assert result["counts"]["common_valid_pixels"] == 11
    assert result["counts"]["ndwi_candidate_pixels"] == 3
    assert result["counts"]["candidate_area_m2"] == 300
    with rasterio.open(result["mask_path"]) as mask:
        values = mask.read(1)
        assert mask.crs.to_string() == "EPSG:32643"
        assert mask.res == (10, 10)
        assert mask.nodata == 255
        assert values[0, 0] == 255
        assert set(np.unique(values)).issubset({0, 1, 255})
        assert np.count_nonzero(values == 1) == 3
        assert np.count_nonzero(values == 0) == 8
    metadata = json.loads(Path(result["metadata_path"]).read_text(encoding="utf-8"))
    assert metadata["source"] == {"item_id": "fixture-item"}
    assert metadata["resampling"]["SCL"] == "nearest"
    assert any("not ground truth" in item for item in metadata["limitations"])
    assert "href" not in json.dumps(metadata).lower()


def test_ndwi_candidate_refuses_existing_output_and_invalid_threshold(tmp_path: Path) -> None:
    nisar_mask, band03, band08, scl, footprint = _write_inputs(tmp_path)
    output_directory = tmp_path / "result"
    output_directory.mkdir()
    with pytest.raises(FileExistsError):
        create_ndwi_candidate(
            band03_path=band03,
            band08_path=band08,
            scl_path=scl,
            nisar_mask_path=nisar_mask,
            footprint=footprint,
            output_directory=output_directory,
            source_metadata={},
        )
    with pytest.raises(ValueError, match="finite"):
        create_ndwi_candidate(
            band03_path=band03,
            band08_path=band08,
            scl_path=scl,
            nisar_mask_path=nisar_mask,
            footprint=footprint,
            output_directory=tmp_path / "other",
            source_metadata={},
            ndwi_threshold=float("nan"),
        )


def test_candidate_preview_distinguishes_candidate_non_candidate_and_nodata() -> None:
    values = np.asarray([[0, 1, 255]], dtype=np.uint8)
    rgba = _color_candidate_classes(values)

    assert tuple(rgba[0, 0]) == (242, 190, 86, 150)
    assert tuple(rgba[0, 1]) == (0, 130, 140, 225)
    assert tuple(rgba[0, 2]) == (180, 190, 190, 125)
    assert _encode_rgba_png(rgba).startswith(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(ValueError, match="only 0, 1, and 255"):
        _color_candidate_classes(np.asarray([[2]], dtype=np.uint8))


def test_candidate_preview_is_georeferenced_in_wgs84_and_keeps_partial_nodata(
    tmp_path: Path,
) -> None:
    import struct
    import zlib

    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import Affine

    mask = tmp_path / "candidate-mask.tif"
    values = np.asarray([[0, 1], [255, 1]], dtype=np.uint8)
    _write_raster(
        mask,
        values,
        transform=Affine(10, 0, 500_000, 0, -10, 1_600_020),
        dtype="uint8",
        nodata=255,
    )
    preview = create_candidate_preview(mask, max_dimension=64)

    assert preview.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", preview[16:24])
    assert width > 0 and height > 0
    assert max(width, height) <= 64
    with rasterio.open(mask) as source:
        assert source.crs.to_string() == "EPSG:32643"
        assert source.nodata == 255

    idat_offset = preview.index(b"IDAT") + 4
    compressed_size = struct.unpack(">I", preview[idat_offset - 8:idat_offset - 4])[0]
    decoded = zlib.decompress(preview[idat_offset:idat_offset + compressed_size])
    assert decoded and len(decoded) == height * (1 + width * 4)
