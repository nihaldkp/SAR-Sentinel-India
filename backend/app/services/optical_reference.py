import json
import os
import struct
import tempfile
import zlib
from pathlib import Path
from typing import Any

import numpy as np

PROCESSOR_VERSION = "sentinel2-ndwi-candidate-1"
CLEAR_SCL_CLASSES = (4, 5, 6)
NDWI_THRESHOLD = 0.0
TILE_SIZE = 512


class OpticalCandidateError(RuntimeError):
    pass


def _encode_rgba_png(rgba: np.ndarray) -> bytes:
    if rgba.ndim != 3 or rgba.shape[2] != 4 or rgba.dtype != np.uint8:
        raise ValueError("PNG preview pixels must be an uint8 RGBA array.")
    height, width, _ = rgba.shape

    def chunk(name: bytes, payload: bytes) -> bytes:
        body = name + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    scanlines = b"".join(b"\0" + rgba[row].tobytes() for row in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )


def _color_candidate_classes(values: np.ndarray) -> np.ndarray:
    if values.ndim != 2 or not np.isin(values, (0, 1, 255)).all():
        raise ValueError("Sentinel-2 candidate raster must contain only 0, 1, and 255.")
    rows, columns = np.indices(values.shape)
    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    rgba[values == 0] = (242, 190, 86, 150)
    rgba[values == 1] = (0, 130, 140, 225)
    nodata = values == 255
    hatch = (rows + columns) % 8 < 2
    rgba[nodata & hatch] = (92, 111, 116, 175)
    rgba[nodata & ~hatch] = (180, 190, 190, 125)
    return rgba


def create_candidate_preview(mask_path: str | Path, max_dimension: int = 1600) -> bytes:
    try:
        import rasterio
        from affine import Affine
        from rasterio.enums import Resampling
        from rasterio.warp import calculate_default_transform, reproject
    except ImportError as error:
        raise OpticalCandidateError("Sentinel-2 map preview requires Rasterio.") from error

    if max_dimension < 1:
        raise ValueError("Preview maximum dimension must be positive.")
    with rasterio.open(mask_path) as source:
        if source.count != 1 or source.nodata != 255 or source.crs is None:
            raise ValueError("Expected a single-band candidate raster with CRS and 255 NoData.")
        if (
            source.transform is None
            or not np.isfinite(source.transform[:6]).all()
            or source.transform.a * source.transform.e
            - source.transform.b * source.transform.d == 0
        ):
            raise ValueError("Sentinel-2 candidate raster has an invalid geotransform.")
        preview_transform, preview_width, preview_height = calculate_default_transform(
            source.crs,
            "EPSG:4326",
            source.width,
            source.height,
            *source.bounds,
        )
        scale = min(1.0, max_dimension / max(preview_width, preview_height))
        width = max(1, round(preview_width * scale))
        height = max(1, round(preview_height * scale))
        preview_transform = preview_transform @ Affine.scale(
            preview_width / width,
            preview_height / height,
        )
        values = np.full((height, width), 255, dtype=np.uint8)
        reproject(
            source=rasterio.band(source, 1),
            destination=values,
            src_transform=source.transform,
            src_crs=source.crs,
            src_nodata=255,
            dst_transform=preview_transform,
            dst_crs="EPSG:4326",
            dst_nodata=255,
            resampling=Resampling.nearest,
            init_dest_nodata=True,
        )
    return _encode_rgba_png(_color_candidate_classes(values))


def create_ndwi_candidate(
    *,
    band03_path: str | Path,
    band08_path: str | Path,
    scl_path: str | Path,
    nisar_mask_path: str | Path,
    footprint: dict[str, Any],
    output_directory: str | Path,
    source_metadata: dict[str, Any],
    ndwi_threshold: float = NDWI_THRESHOLD,
) -> dict[str, Any]:
    """Create an exploratory NDWI mask on the NISAR grid, preserving unsupported pixels."""
    try:
        import rasterio
        from rasterio.features import geometry_mask, geometry_window
        from rasterio.vrt import WarpedVRT
        from rasterio.warp import Resampling, transform_geom
        from rasterio.windows import Window, transform as window_transform
    except ImportError as error:
        raise OpticalCandidateError(
            "Optical candidate generation requires Rasterio."
        ) from error

    if not np.isfinite(ndwi_threshold) or not -1 <= ndwi_threshold <= 1:
        raise ValueError("NDWI threshold must be finite and between -1 and 1.")

    destination = Path(output_directory)
    if destination.exists():
        raise FileExistsError(f"Optical output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    common_valid_count = 0
    candidate_count = 0
    corridor_count = 0
    clear_scl_count = 0
    reflectance_count = 0
    pixel_area_m2 = 0.0

    with rasterio.open(nisar_mask_path) as nisar:
        if nisar.crs is None or nisar.transform is None:
            raise OpticalCandidateError("NISAR candidate mask has no usable CRS/geotransform.")
        if nisar.count != 1 or nisar.nodata != 255:
            raise OpticalCandidateError(
                "Expected a single-band NISAR candidate mask with 255 as NoData."
            )
        projected_footprint = transform_geom(
            "EPSG:4326",
            nisar.crs,
            footprint,
            precision=-1,
        )
        try:
            source_window = geometry_window(nisar, [projected_footprint]).round_offsets().round_lengths()
            source_window = source_window.intersection(
                Window(0, 0, nisar.width, nisar.height)
            )
        except rasterio.errors.WindowError as error:
            raise OpticalCandidateError(
                "Sentinel-2 footprint does not overlap the NISAR candidate-mask grid."
            ) from error

        if source_window.width <= 0 or source_window.height <= 0:
            raise OpticalCandidateError(
                "Sentinel-2 footprint does not overlap the NISAR candidate-mask grid."
            )

        height = int(source_window.height)
        width = int(source_window.width)
        target_transform = window_transform(source_window, nisar.transform)
        pixel_area_m2 = abs(
            target_transform.a * target_transform.e
            - target_transform.b * target_transform.d
        )
        if pixel_area_m2 <= 0:
            raise OpticalCandidateError("NISAR grid has an invalid pixel area.")

        try:
            with (
                rasterio.open(band03_path) as band03,
                rasterio.open(band08_path) as band08,
                rasterio.open(scl_path) as scl,
                WarpedVRT(
                    band03,
                    crs=nisar.crs,
                    transform=target_transform,
                    width=width,
                    height=height,
                    resampling=Resampling.bilinear,
                    nodata=65535,
                ) as band03_vrt,
                WarpedVRT(
                    band08,
                    crs=nisar.crs,
                    transform=target_transform,
                    width=width,
                    height=height,
                    resampling=Resampling.bilinear,
                    nodata=65535,
                ) as band08_vrt,
                WarpedVRT(
                    scl,
                    crs=nisar.crs,
                    transform=target_transform,
                    width=width,
                    height=height,
                    resampling=Resampling.nearest,
                    nodata=0,
                ) as scl_vrt,
            ):
                if band03.count != 1 or band08.count != 1 or scl.count != 1:
                    raise OpticalCandidateError("Each Sentinel-2 source must be single-band.")
                if band03.dtypes[0] != "uint16" or band08.dtypes[0] != "uint16":
                    raise OpticalCandidateError("Sentinel-2 B03 and B08 must be uint16.")
                if scl.dtypes[0] != "uint8":
                    raise OpticalCandidateError("Sentinel-2 SCL must be uint8.")
                if band03.crs is None or band08.crs is None or scl.crs is None:
                    raise OpticalCandidateError("Sentinel-2 source assets must define a CRS.")

                stage_parent = destination.parent
                with tempfile.TemporaryDirectory(
                    prefix=".sentinel2-candidate-",
                    dir=stage_parent,
                ) as temporary_directory:
                    stage = Path(temporary_directory)
                    mask_path = stage / "ndwi-candidate-mask.tif"
                    metadata_path = stage / "processing-metadata.json"
                    profile = nisar.profile.copy()
                    profile.update(
                        driver="GTiff",
                        width=width,
                        height=height,
                        count=1,
                        dtype="uint8",
                        nodata=255,
                        transform=target_transform,
                        compress="deflate",
                        tiled=True,
                        blockxsize=256,
                        blockysize=256,
                        BIGTIFF="IF_SAFER",
                    )

                    with rasterio.open(mask_path, "w", **profile) as output:
                        output.set_band_description(1, "exploratory NDWI water candidate")
                        output.update_tags(
                            classification="unvalidated_optical_candidate",
                            index="NDWI=(B03-B08)/(B03+B08)",
                            threshold=f"NDWI>{ndwi_threshold}",
                            clear_scl_classes=",".join(map(str, CLEAR_SCL_CLASSES)),
                            resampling="B03/B08 bilinear; SCL nearest neighbor",
                            processor_version=PROCESSOR_VERSION,
                        )

                        for row in range(0, height, TILE_SIZE):
                            tile_height = min(TILE_SIZE, height - row)
                            for column in range(0, width, TILE_SIZE):
                                tile_width = min(TILE_SIZE, width - column)
                                tile_window = Window(column, row, tile_width, tile_height)
                                output_transform = window_transform(
                                    tile_window,
                                    target_transform,
                                )
                                inside_footprint = geometry_mask(
                                    [projected_footprint],
                                    out_shape=(tile_height, tile_width),
                                    transform=output_transform,
                                    invert=True,
                                )
                                source_tile_window = Window(
                                    source_window.col_off + column,
                                    source_window.row_off + row,
                                    tile_width,
                                    tile_height,
                                )
                                nisar_values = nisar.read(1, window=source_tile_window)
                                nisar_valid = (nisar_values == 0) | (nisar_values == 1)
                                corridor_support = inside_footprint & nisar_valid
                                classification = np.full(
                                    (tile_height, tile_width),
                                    255,
                                    dtype=np.uint8,
                                )
                                if not np.any(corridor_support):
                                    output.write(classification, 1, window=tile_window)
                                    continue

                                b03 = band03_vrt.read(1, window=tile_window, masked=True)
                                b08 = band08_vrt.read(1, window=tile_window, masked=True)
                                scl_values = scl_vrt.read(1, window=tile_window, masked=True)
                                reflectance_valid = (
                                    ~np.ma.getmaskarray(b03)
                                    & ~np.ma.getmaskarray(b08)
                                    & np.isfinite(b03.data)
                                    & np.isfinite(b08.data)
                                )
                                clear_scl = (
                                    ~np.ma.getmaskarray(scl_values)
                                    & np.isin(scl_values.data, CLEAR_SCL_CLASSES)
                                )
                                corridor_count += int(np.count_nonzero(corridor_support))
                                clear_scl_count += int(
                                    np.count_nonzero(corridor_support & clear_scl)
                                )
                                reflectance_count += int(
                                    np.count_nonzero(corridor_support & reflectance_valid)
                                )

                                denominator = b03.data.astype(np.float32) + b08.data.astype(
                                    np.float32
                                )
                                common = (
                                    corridor_support
                                    & clear_scl
                                    & reflectance_valid
                                    & (denominator != 0)
                                )
                                if np.any(common):
                                    ndwi = np.zeros(
                                        (tile_height, tile_width),
                                        dtype=np.float32,
                                    )
                                    np.divide(
                                        b03.data.astype(np.float32)
                                        - b08.data.astype(np.float32),
                                        denominator,
                                        out=ndwi,
                                        where=common,
                                    )
                                    classification[common] = (
                                        ndwi[common] > ndwi_threshold
                                    ).astype(np.uint8)
                                common_valid_count += int(np.count_nonzero(common))
                                candidate_count += int(
                                    np.count_nonzero(classification == 1)
                                )
                                output.write(classification, 1, window=tile_window)

                    result = {
                        "status": "unvalidated_candidate",
                        "processor_version": PROCESSOR_VERSION,
                        "classification": "exploratory Sentinel-2 NDWI water candidate",
                        "formula": "(B03 - B08) / (B03 + B08)",
                        "ndwi_threshold": ndwi_threshold,
                        "clear_scl_classes": list(CLEAR_SCL_CLASSES),
                        "resampling": {
                            "B03": "bilinear",
                            "B08": "bilinear",
                            "SCL": "nearest",
                        },
                        "grid": {
                            "crs": nisar.crs.to_string(),
                            "transform": list(target_transform),
                            "width": width,
                            "height": height,
                            "pixel_area_m2": pixel_area_m2,
                        },
                        "counts": {
                            "corridor_pixels_in_footprint": corridor_count,
                            "clear_scl_pixels_in_corridor": clear_scl_count,
                            "reflectance_valid_pixels_in_corridor": reflectance_count,
                            "common_valid_pixels": common_valid_count,
                            "ndwi_candidate_pixels": candidate_count,
                            "candidate_area_m2": candidate_count * pixel_area_m2,
                        },
                        "source": source_metadata,
                        "limitations": [
                            "This is an unvalidated optical candidate classification, not ground truth.",
                            "SCL is a classification product; classes 4, 5, and 6 are treated as clear.",
                            "SCL is resampled from 20 m to the 10 m NISAR grid; replicated labels are not independent 10 m observations.",
                            "NDWI > the stated threshold is exploratory and is not calibrated for this river or scene.",
                            "Only pixels inside the Sentinel-2 footprint, mapped NISAR corridor, valid NISAR mask, valid reflectance, and clear SCL support are classified; all other pixels are NoData.",
                            "This tile covers only a partial river segment and was acquired about 4 hours 55 minutes after the NISAR product.",
                            "The output does not establish verified water boundaries, river width, floods, erosion, deposition, or temporal change.",
                        ],
                    }
                    metadata_path.write_text(
                        json.dumps(result, indent=2),
                        encoding="utf-8",
                    )
                    os.rename(stage, destination)
        except rasterio.errors.RasterioIOError:
            raise OpticalCandidateError(
                "Could not read one or more Sentinel-2 raster assets."
            ) from None

    return {
        "output_directory": str(destination),
        "mask_path": str(destination / "ndwi-candidate-mask.tif"),
        "metadata_path": str(destination / "processing-metadata.json"),
        **result,
    }
