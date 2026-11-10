import json
import math
import os
import tempfile
from array import array
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from app.services.nisar_product import validate_nisar_gcov_hdf5
from app.services.rivers import RIVER_CATALOG

PROCESSOR_VERSION = "nisar-gcov-candidate-1"
FREQUENCY = "frequencyA"
CORRIDOR_HALF_WIDTH_M = 1_500.0
HISTOGRAM_MIN_DB = -60.0
HISTOGRAM_MAX_DB = 30.0
HISTOGRAM_BINS = 900
THRESHOLD_SENSITIVITY_DB = 1.0
THRESHOLD_OFFSETS_DB = (-2.0, -1.0, 0.0, 1.0, 2.0)
CLASSIFICATION_ALGORITHM = (
    "Convert linear frequency-A HHHH and HVHV power to 10*log10(max(power, 1e-6)) dB; "
    "estimate independent Otsu thresholds from 900-bin histograms spanning -60 to +30 dB; "
    "classify the combined candidate where HH_dB <= HH_threshold AND HV_dB <= HV_threshold."
)
TILE_SIZE = 512
MIN_VECTOR_AREA_PIXELS = 3
MAX_VECTOR_FEATURES = 5_000


class NisarGcovProcessingUnavailable(RuntimeError):
    pass


NISAR_GCOV_CAVEATS = [
    "This is an unvalidated candidate open-water classification, not a verified river boundary.",
    "The dual-polarization Otsu thresholds are data-adaptive exploratory thresholds; no ground-truth labels or accuracy assessment are available.",
    "Low HH and HV backscatter can also occur over non-water surfaces, shadow, and other radar-dark targets; vegetation, incidence-angle, and terrain effects are not independently screened.",
    "The analysis is limited to a 1,500 m corridor around the OpenStreetMap reference centerline and the portion of that corridor inside this product footprint.",
    "Threshold sensitivity shifts both polarization thresholds together by -2, -1, 0, +1, and +2 dB; these deterministic perturbations are not a statistical confidence interval.",
    "Candidate water area is the sum of valid 10 m product-grid pixels classified by the stated rule; it is not river width, channel area, flood extent, erosion, deposition, or riverbank movement.",
    "No spatial speckle filter, majority filter, or minimum-component cleanup is applied; isolated and fragmented candidates are retained and reported as connectivity diagnostics.",
    "The output GeoTIFF preserves invalid and out-of-corridor pixels as NoData. Candidate GeoJSON is simplified, omits components smaller than three pixels, and may be truncated at 5,000 features; it is a display product only, while the mask GeoTIFF contains the complete pixel classification.",
]


def _require_modules() -> tuple[Any, Any, Any, Any, Any]:
    try:
        import h5py
        import rasterio
        from rasterio.features import rasterize, shapes
        from rasterio.transform import Affine
        from rasterio.warp import transform_geom
        from rasterio.windows import Window, from_bounds, transform as window_transform
    except ImportError as error:
        raise NisarGcovProcessingUnavailable(
            "NISAR GCOV processing requires the installed h5py, Rasterio, and Shapely dependencies."
        ) from error
    return h5py, rasterio, rasterize, shapes, (Affine, transform_geom, Window, from_bounds, window_transform)


def _otsu_threshold(histogram: np.ndarray, edges: np.ndarray) -> float:
    counts = histogram.astype(np.float64)
    if counts.sum() < 2:
        raise ValueError("The river corridor has too few valid pixels for an Otsu threshold.")
    centers = (edges[:-1] + edges[1:]) / 2
    probabilities = counts / counts.sum()
    cumulative_weight = np.cumsum(probabilities)
    cumulative_mean = np.cumsum(probabilities * centers)
    denominator = cumulative_weight * (1 - cumulative_weight)
    between_class_variance = np.zeros_like(denominator)
    usable = denominator > 0
    if not np.any(usable):
        raise ValueError("The river-corridor backscatter has insufficient contrast for thresholding.")
    total_mean = cumulative_mean[-1]
    between_class_variance[usable] = (
        (total_mean * cumulative_weight[usable] - cumulative_mean[usable]) ** 2
        / denominator[usable]
    )
    threshold_index = int(np.argmax(between_class_variance))
    if threshold_index <= 0 or threshold_index >= len(centers) - 1:
        raise ValueError("The Otsu threshold fell at the histogram boundary; no mask was generated.")
    return float(centers[threshold_index])


def _db(power: np.ndarray) -> np.ndarray:
    floor = 10.0 ** (HISTOGRAM_MIN_DB / 10.0)
    return (10.0 * np.log10(np.maximum(power, floor))).astype(np.float32, copy=False)


def _tiles(height: int, width: int) -> Iterator[tuple[int, int, int, int]]:
    for row in range(0, height, TILE_SIZE):
        tile_height = min(TILE_SIZE, height - row)
        for column in range(0, width, TILE_SIZE):
            yield row, column, tile_height, min(TILE_SIZE, width - column)


def _write_geojson(
    mask_path: Path,
    output_path: Path,
    source_crs: str,
    pixel_area_m2: float,
    shapes: Any,
    transform_geom: Any,
    Window: Any,
    window_transform: Any,
) -> tuple[int, bool]:
    import rasterio
    from shapely.geometry import shape

    features: list[dict[str, Any]] = []
    truncated = False
    with rasterio.open(mask_path) as source:
        for row, column, height, width in _tiles(source.height, source.width):
            window = Window(column, row, width, height)
            values = source.read(1, window=window)
            candidate = values == 1
            if not np.any(candidate):
                continue
            for geometry, value in shapes(
                values,
                mask=candidate,
                transform=window_transform(window, source.transform),
            ):
                if value != 1:
                    continue
                polygon = shape(geometry)
                if polygon.area < pixel_area_m2 * MIN_VECTOR_AREA_PIXELS:
                    continue
                if len(features) >= MAX_VECTOR_FEATURES:
                    truncated = True
                    break
                simplified = polygon.simplify(math.sqrt(pixel_area_m2), preserve_topology=True)
                features.append(
                    {
                        "type": "Feature",
                        "properties": {"class": "unvalidated_candidate_open_water"},
                        "geometry": transform_geom(
                            source_crs,
                            "EPSG:4326",
                            simplified.__geo_interface__,
                            precision=6,
                        ),
                    }
                )
            if truncated:
                break
    output_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "name": "unvalidated_nisar_gcov_candidate_open_water",
                "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
                "display_only": True,
                "feature_limit": MAX_VECTOR_FEATURES,
                "feature_limit_reached": truncated,
                "complete_classification_in": "candidate-water-mask.tif",
                "note": (
                    "Simplified display polygons; components under three pixels are omitted "
                    "and the feature limit may truncate this collection. The GeoTIFF is the "
                    "complete pixel classification."
                ),
                "features": features,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return len(features), truncated


def _merge_component_labels(
    parent: array,
    component_sizes: array,
    first: np.ndarray,
    second: np.ndarray,
) -> None:
    pairs = np.column_stack((first.ravel(), second.ravel()))
    pairs = pairs[(pairs[:, 0] > 0) & (pairs[:, 1] > 0)]
    if not pairs.size:
        return
    for left, right in np.unique(pairs, axis=0):
        first_id = int(left)
        second_id = int(right)
        while parent[first_id] != first_id:
            parent[first_id] = parent[parent[first_id]]
            first_id = parent[first_id]
        while parent[second_id] != second_id:
            parent[second_id] = parent[parent[second_id]]
            second_id = parent[second_id]
        if first_id == second_id:
            continue
        if component_sizes[first_id] < component_sizes[second_id]:
            first_id, second_id = second_id, first_id
        parent[second_id] = first_id
        component_sizes[first_id] += component_sizes[second_id]


def _connected_component_sizes(
    mask_dataset: Any,
    label_output: Any | None = None,
) -> tuple[list[int], np.ndarray]:
    from scipy.ndimage import label
    from rasterio.windows import Window

    parent = array("I", [0])
    component_sizes = array("Q", [0])
    previous_bottom = np.zeros(mask_dataset.width, dtype=np.uint32)
    structure = np.ones((3, 3), dtype=np.uint8)
    block_height, block_width = mask_dataset.block_shapes[0]
    for row in range(0, mask_dataset.height, block_height):
        height = min(block_height, mask_dataset.height - row)
        current_bottom = np.zeros(mask_dataset.width, dtype=np.uint32)
        previous_right: np.ndarray | None = None
        for column in range(0, mask_dataset.width, block_width):
            width = min(block_width, mask_dataset.width - column)
            window = Window(column, row, width, height)
            candidate = mask_dataset.read(1, window=window) == 1
            labels, count = label(candidate, structure=structure)
            if count:
                counts = np.bincount(labels.ravel(), minlength=count + 1)
                offset = len(parent) - 1
                first_id = offset + 1
                parent.extend(range(first_id, first_id + count))
                component_sizes.extend(int(value) for value in counts[1:])
                labels = np.where(labels > 0, labels + offset, 0).astype(np.uint32)

            if previous_right is not None:
                for shift in (-1, 0, 1):
                    if shift < 0:
                        _merge_component_labels(
                            parent,
                            component_sizes,
                            previous_right[1:],
                            labels[:-1, 0],
                        )
                    elif shift > 0:
                        _merge_component_labels(
                            parent,
                            component_sizes,
                            previous_right[:-1],
                            labels[1:, 0],
                        )
                    else:
                        _merge_component_labels(
                            parent,
                            component_sizes,
                            previous_right,
                            labels[:, 0],
                        )

            above = previous_bottom[max(0, column - 1) : min(mask_dataset.width, column + width + 1)]
            current = labels[0]
            for shift in (-1, 0, 1):
                previous_start = max(0, column - 1)
                current_start = max(0, previous_start - column - shift)
                above_start = column + current_start + shift - previous_start
                length = min(
                    len(above) - above_start,
                    width - current_start,
                )
                if length > 0:
                    _merge_component_labels(
                        parent,
                        component_sizes,
                        above[above_start : above_start + length],
                        current[current_start : current_start + length],
                    )

            current_bottom[column : column + width] = labels[-1]
            previous_right = labels[:, -1]
            if label_output is not None:
                label_output.write(labels, 1, window=window)
        previous_bottom = current_bottom

    root_sizes = [
        component_sizes[index]
        for index in range(1, len(parent))
        if parent[index] == index
    ]
    size_by_label = np.zeros(len(parent), dtype=np.uint64)
    for label_id in range(1, len(parent)):
        root = label_id
        while parent[root] != root:
            parent[root] = parent[parent[root]]
            root = parent[root]
        size_by_label[label_id] = component_sizes[root]
    return root_sizes, size_by_label


def _connected_component_summary(mask_dataset: Any) -> dict[str, int]:
    root_sizes, _ = _connected_component_sizes(mask_dataset)
    return {
        "connectivity": 8,
        "component_count": len(root_sizes),
        "isolated_pixel_component_count": sum(size == 1 for size in root_sizes),
        "components_up_to_four_pixels": sum(size <= 4 for size in root_sizes),
        "pixels_in_components_up_to_four": sum(size for size in root_sizes if size <= 4),
        "largest_component_pixels": max(root_sizes, default=0),
    }


def build_component_sensitivity_outputs(
    mask_path: Path,
    output_directory: Path,
    minimum_component_sizes: list[int],
) -> list[dict[str, Any]]:
    _, rasterio, _, _, _ = _require_modules()

    if not minimum_component_sizes or len(minimum_component_sizes) > 8:
        raise ValueError("Request between one and eight minimum component sizes.")
    if any(size < 2 or size > 100_000 for size in minimum_component_sizes):
        raise ValueError("Minimum component sizes must be between 2 and 100,000 pixels.")
    if len(set(minimum_component_sizes)) != len(minimum_component_sizes):
        raise ValueError("Minimum component sizes must be unique.")
    ordered_sizes = sorted(minimum_component_sizes)
    target_directories = {
        size: output_directory / f"minimum-{size}-pixels-8-connectivity"
        for size in ordered_sizes
    }
    existing = [path for path in target_directories.values() if path.exists()]
    if existing:
        if (
            all(
                (path / "metadata.json").is_file()
                and (path / "candidate-water-mask.tif").is_file()
                for path in existing
            )
            and len(existing) == len(target_directories)
        ):
            return [
                json.loads((target_directories[size] / "metadata.json").read_text(encoding="utf-8"))
                for size in ordered_sizes
            ]
        raise FileExistsError(
            "A component-sensitivity output already exists or is incomplete; refusing to overwrite it."
        )

    output_directory.mkdir(parents=True, exist_ok=True)
    staging_directory = Path(
        tempfile.mkdtemp(prefix=".component-sensitivity-", dir=output_directory)
    )
    try:
        with rasterio.open(mask_path) as source:
            if (
                source.count != 1
                or source.nodata != 255
                or source.crs is None
                or not source.crs.is_projected
                or source.crs.linear_units.casefold() not in {"meter", "metre"}
            ):
                raise ValueError("The source candidate mask must be a georeferenced single-band 0/1/255 raster.")
            label_profile = source.profile.copy()
            label_profile.update(
                driver="GTiff",
                count=1,
                dtype="uint32",
                nodata=0,
                compress="deflate",
                predictor=2,
            )
            labels_path = staging_directory / "component-labels.tif"
            with rasterio.open(labels_path, "w", **label_profile) as labels:
                component_sizes, size_by_label = _connected_component_sizes(source, labels)

            staged_results: dict[int, dict[str, Any]] = {}
            for minimum_size in ordered_sizes:
                variant_directory = staging_directory / f"minimum-{minimum_size}-pixels-8-connectivity"
                variant_directory.mkdir()
                output_path = variant_directory / "candidate-water-mask.tif"
                output_profile = source.profile.copy()
                output_profile.update(
                    driver="GTiff",
                    count=1,
                    dtype="uint8",
                    nodata=255,
                    compress="deflate",
                    predictor=2,
                )
                candidate_before = 0
                candidate_after = 0
                valid_pixel_count = 0
                nodata_pixel_count = 0
                with rasterio.open(labels_path) as labels, rasterio.open(
                    output_path, "w", **output_profile
                ) as output:
                    for _, window in source.block_windows(1):
                        source_values = source.read(1, window=window)
                        label_values = labels.read(1, window=window)
                        source_valid = (source.read_masks(1, window=window) > 0) & (
                            source_values != 255
                        )
                        if np.any(source_valid & ~np.isin(source_values, (0, 1))):
                            raise ValueError("The source candidate mask contains unsupported valid classes.")
                        candidate = source_valid & (source_values == 1)
                        component_sizes_in_window = size_by_label[label_values]
                        keep = candidate & (component_sizes_in_window >= minimum_size)
                        output_values = source_values.astype(np.uint8, copy=True)
                        output_values[~source_valid] = 255
                        output_values[candidate & ~keep] = 0
                        output.write(output_values, 1, window=window)
                        candidate_before += int(candidate.sum())
                        candidate_after += int(keep.sum())
                        valid_pixel_count += int(source_valid.sum())
                        nodata_pixel_count += int((~source_valid).sum())
                pixel_area = abs(
                    source.transform.a * source.transform.e
                    - source.transform.b * source.transform.d
                )
                removed_pixels = candidate_before - candidate_after
                result = {
                    "status": "exploratory_candidate_sensitivity",
                    "source_mask": mask_path.name,
                    "minimum_component_pixels": minimum_size,
                    "connectivity": 8,
                    "component_count": len(component_sizes),
                    "component_count_reclassified_nonwater": sum(
                        size < minimum_size for size in component_sizes
                    ),
                    "candidate_pixel_count_before": candidate_before,
                    "candidate_pixel_count_after": candidate_after,
                    "candidate_pixels_reclassified_nonwater": removed_pixels,
                    "candidate_pixels_removed_fraction": (
                        removed_pixels / candidate_before if candidate_before else 0.0
                    ),
                    "valid_pixel_count": valid_pixel_count,
                    "nodata_pixel_count_preserved": nodata_pixel_count,
                    "candidate_area_before_m2": candidate_before * pixel_area,
                    "candidate_area_after_m2": candidate_after * pixel_area,
                    "processing_completed_at": datetime.now(timezone.utc).isoformat(),
                    "crs": source.crs.to_string(),
                    "pixel_size_m": max(
                        math.hypot(source.transform.a, source.transform.d),
                        math.hypot(source.transform.b, source.transform.e),
                    ),
                    "quality_flags": [
                        "This is a user-selected component-size sensitivity scenario, not a validated cleanup.",
                        "Removed candidate pixels are reclassified as non-water solely by the size rule; they are not established as noise.",
                        "No independent reference labels were used to select or evaluate this parameter.",
                        "The source classification and its NoData pixels are unchanged.",
                    ],
                    "mask_file": "candidate-water-mask.tif",
                }
                (variant_directory / "metadata.json").write_text(
                    json.dumps(result, indent=2),
                    encoding="utf-8",
                )
                staged_results[minimum_size] = result

        committed: list[Path] = []
        try:
            for minimum_size in ordered_sizes:
                target = target_directories[minimum_size]
                os.replace(
                    staging_directory / target.name,
                    target,
                )
                committed.append(target)
        except Exception:
            for target in committed:
                for item in target.iterdir():
                    if item.is_file():
                        item.unlink()
                target.rmdir()
            raise
        return [staged_results[size] for size in ordered_sizes]
    finally:
        if staging_directory.exists():
            for path in sorted(
                staging_directory.rglob("*"),
                key=lambda item: len(item.parts),
                reverse=True,
            ):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            staging_directory.rmdir()


def build_classification_diagnostics(
    measurements_path: Path,
    mask_path: Path,
    output_directory: Path,
    hh_threshold_db: float,
    hv_threshold_db: float,
    pixel_area_m2: float,
) -> dict[str, Any]:
    import rasterio
    from rasterio.windows import Window

    diagnostics_path = output_directory / "classification-diagnostics.json"
    comparison_path = output_directory / "polarization-comparison.tif"
    sensitivity_path = output_directory / "threshold-sensitivity.tif"
    if diagnostics_path.is_file() and comparison_path.is_file() and sensitivity_path.is_file():
        return json.loads(diagnostics_path.read_text(encoding="utf-8"))
    if any(path.exists() for path in (comparison_path, sensitivity_path, diagnostics_path)):
        raise FileExistsError("NISAR classification diagnostics are incomplete; refusing to overwrite them.")

    comparison_descriptor, comparison_name = tempfile.mkstemp(
        prefix=".polarization-comparison-",
        suffix=".tif",
        dir=output_directory,
    )
    sensitivity_descriptor, sensitivity_name = tempfile.mkstemp(
        prefix=".threshold-sensitivity-",
        suffix=".tif",
        dir=output_directory,
    )
    os.close(comparison_descriptor)
    os.close(sensitivity_descriptor)
    comparison_temporary = Path(comparison_name)
    sensitivity_temporary = Path(sensitivity_name)
    count_by_class = {"HH-only": 0, "HV-only": 0, "HH+HV": 0}
    sensitivity_counts = {offset: 0 for offset in THRESHOLD_OFFSETS_DB}
    profile: dict[str, Any]
    try:
        with rasterio.open(measurements_path) as measurements, rasterio.open(mask_path) as source_mask:
            if measurements.count != 2 or (
                measurements.width != source_mask.width or measurements.height != source_mask.height
            ):
                raise ValueError("NISAR comparison inputs have incompatible raster dimensions.")
            profile = {
                "driver": "GTiff",
                "width": measurements.width,
                "height": measurements.height,
                "dtype": "uint8",
                "crs": measurements.crs,
                "transform": measurements.transform,
                "nodata": 255,
                "compress": "deflate",
                "tiled": True,
                "blockxsize": 512,
                "blockysize": 512,
            }
            with (
                rasterio.open(comparison_temporary, "w", count=3, **profile) as comparison,
                rasterio.open(sensitivity_temporary, "w", count=len(THRESHOLD_OFFSETS_DB), **profile) as sensitivity,
            ):
                for band, description in enumerate(("HH-only", "HV-only", "HH+HV combined"), start=1):
                    comparison.set_band_description(band, description)
                for band, offset in enumerate(THRESHOLD_OFFSETS_DB, start=1):
                    sensitivity.set_band_description(band, f"Both thresholds shifted {offset:+g} dB")
                for _, window in measurements.block_windows(1):
                    hh_power, hv_power = measurements.read((1, 2), window=window)
                    valid = np.isfinite(hh_power) & np.isfinite(hv_power)
                    valid &= (hh_power >= 0) & (hv_power >= 0)
                    hh_db = _db(hh_power[valid])
                    hv_db = _db(hv_power[valid])
                    hh_only = hh_db <= hh_threshold_db
                    hv_only = hv_db <= hv_threshold_db
                    combined = hh_only & hv_only
                    count_by_class["HH-only"] += int(hh_only.sum())
                    count_by_class["HV-only"] += int(hv_only.sum())
                    count_by_class["HH+HV"] += int(combined.sum())

                    comparison_values = np.full((3, *valid.shape), 255, dtype=np.uint8)
                    comparison_values[:, valid] = 0
                    valid_positions = np.flatnonzero(valid)
                    comparison_values[0].flat[valid_positions[hh_only]] = 1
                    comparison_values[1].flat[valid_positions[hv_only]] = 1
                    comparison_values[2].flat[valid_positions[combined]] = 1
                    comparison.write(comparison_values, window=window)

                    sensitivity_values = np.full(
                        (len(THRESHOLD_OFFSETS_DB), *valid.shape),
                        255,
                        dtype=np.uint8,
                    )
                    sensitivity_values[:, valid] = 0
                    for band, offset in enumerate(THRESHOLD_OFFSETS_DB):
                        candidate = (
                            (hh_db <= hh_threshold_db + offset)
                            & (hv_db <= hv_threshold_db + offset)
                        )
                        sensitivity_counts[offset] += int(candidate.sum())
                        sensitivity_values[band, valid] = candidate.astype(np.uint8)
                    sensitivity.write(sensitivity_values, window=window)

        with rasterio.open(mask_path) as source_mask:
            component_summary = _connected_component_summary(source_mask)
        diagnostics = {
            "polarization_comparison": [
                {
                    "classification": label,
                    "candidate_pixel_count": count,
                    "candidate_area_m2": count * pixel_area_m2,
                }
                for label, count in count_by_class.items()
            ],
            "threshold_sensitivity": [
                {
                    "offset_db": offset,
                    "candidate_pixel_count": count,
                    "candidate_area_m2": count * pixel_area_m2,
                }
                for offset, count in sensitivity_counts.items()
            ],
            "connected_component_summary": component_summary,
            "comparison_url": "",
            "sensitivity_url": "",
            "geojson_display_note": (
                "Display-only GeoJSON is simplified, omits components smaller than three pixels, "
                "and is capped at 5,000 features. The candidate mask GeoTIFF retains the complete "
                "pixel classification with NoData."
            ),
        }
        os.replace(comparison_temporary, comparison_path)
        os.replace(sensitivity_temporary, sensitivity_path)
        diagnostics_path.write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
        return diagnostics
    except Exception:
        comparison_temporary.unlink(missing_ok=True)
        sensitivity_temporary.unlink(missing_ok=True)
        raise


def process_gcov_product(
    hdf5_path: Path,
    product_id: str,
    river_id: str,
    output_directory: Path,
) -> dict[str, Any]:
    h5py, rasterio, rasterize, raster_shapes, mapping_helpers = _require_modules()
    Affine, transform_geom, Window, from_bounds, window_transform = mapping_helpers

    river = next((item for item in RIVER_CATALOG if item.id == river_id), None)
    if river is None:
        raise ValueError(f"Unsupported river_id: {river_id}")
    if not hdf5_path.is_file():
        raise FileNotFoundError(f"Downloaded NISAR HDF5 product was not found: {hdf5_path.name}")

    from shapely.geometry import box, shape

    with h5py.File(hdf5_path, "r") as source:
        _, polarizations = validate_nisar_gcov_hdf5(source, product_id)
        base = f"science/LSAR/GCOV/grids/{FREQUENCY}/"
        required_paths = {
            "hh": base + "HHHH",
            "hv": base + "HVHV",
            "x": base + "xCoordinates",
            "y": base + "yCoordinates",
            "projection": base + "projection",
            "x_spacing": base + "xCoordinateSpacing",
            "y_spacing": base + "yCoordinateSpacing",
            "polarizations": base + "listOfPolarizations",
            "validity_mask": base + "mask",
        }
        hh_dataset = source[required_paths["hh"]]
        hv_dataset = source[required_paths["hv"]]
        validity_mask_dataset = source[required_paths["validity_mask"]]
        x_coordinates = source[required_paths["x"]][()]
        y_coordinates = source[required_paths["y"]][()]
        projection = source[required_paths["projection"]]
        x_spacing = float(source[required_paths["x_spacing"]][()])
        y_spacing = float(source[required_paths["y_spacing"]][()])
        epsg_code = int(projection.attrs.get("epsg_code", 0))
        pixel_area_m2 = abs(x_spacing * y_spacing)

        source_crs = f"EPSG:{epsg_code}"
        full_transform = Affine(
            x_spacing,
            0,
            float(x_coordinates[0]) - x_spacing / 2,
            0,
            y_spacing,
            float(y_coordinates[0]) - y_spacing / 2,
        )
        grid_bounds = box(
            min(float(x_coordinates[0]), float(x_coordinates[-1])) - abs(x_spacing) / 2,
            min(float(y_coordinates[0]), float(y_coordinates[-1])) - abs(y_spacing) / 2,
            max(float(x_coordinates[0]), float(x_coordinates[-1])) + abs(x_spacing) / 2,
            max(float(y_coordinates[0]), float(y_coordinates[-1])) + abs(y_spacing) / 2,
        )
        projected_reference = shape(
            transform_geom(
                "EPSG:4326",
                source_crs,
                river.centerline.model_dump(),
                precision=-1,
            )
        )
        covered_centerline = projected_reference.intersection(grid_bounds)
        if projected_reference.length <= 0:
            raise ValueError("The river reference centerline has no measurable length.")
        centerline_coverage_percent = 100.0 * covered_centerline.length / projected_reference.length
        corridor = projected_reference.buffer(CORRIDOR_HALF_WIDTH_M).intersection(grid_bounds)
        if corridor.is_empty:
            raise ValueError(
                "The downloaded NISAR product does not overlap the selected river's reference centerline."
            )

        crop = from_bounds(*corridor.bounds, transform=full_transform)
        column_start = max(0, math.floor(crop.col_off))
        row_start = max(0, math.floor(crop.row_off))
        column_stop = min(hh_dataset.shape[1], math.ceil(crop.col_off + crop.width))
        row_stop = min(hh_dataset.shape[0], math.ceil(crop.row_off + crop.height))
        crop_width = column_stop - column_start
        crop_height = row_stop - row_start
        if crop_width <= 0 or crop_height <= 0:
            raise ValueError("The river corridor does not overlap valid NISAR raster pixels.")
        output_transform = window_transform(
            Window(column_start, row_start, crop_width, crop_height),
            full_transform,
        )
        histogram_edges = np.linspace(
            HISTOGRAM_MIN_DB,
            HISTOGRAM_MAX_DB,
            HISTOGRAM_BINS + 1,
            dtype=np.float64,
        )
        hh_histogram = np.zeros(HISTOGRAM_BINS, dtype=np.int64)
        hv_histogram = np.zeros(HISTOGRAM_BINS, dtype=np.int64)
        corridor_pixel_count = 0
        valid_pixel_count = 0
        for row, column, height, width in _tiles(crop_height, crop_width):
            window = Window(column_start + column, row_start + row, width, height)
            local_transform = window_transform(window, full_transform)
            inside_corridor = rasterize(
                [(corridor, 1)],
                out_shape=(height, width),
                transform=local_transform,
                fill=0,
                dtype="uint8",
            ).astype(bool)
            corridor_pixel_count += int(inside_corridor.sum())
            if not np.any(inside_corridor):
                continue
            hh_power = hh_dataset[row_start + row : row_start + row + height,
                                  column_start + column : column_start + column + width]
            hv_power = hv_dataset[row_start + row : row_start + row + height,
                                  column_start + column : column_start + column + width]
            sample_mask = validity_mask_dataset[
                row_start + row : row_start + row + height,
                column_start + column : column_start + column + width,
            ]
            valid = inside_corridor & np.isfinite(hh_power) & np.isfinite(hv_power)
            valid &= (hh_power >= 0) & (hv_power >= 0) & (sample_mask > 0) & (sample_mask != 255)
            count = int(valid.sum())
            valid_pixel_count += count
            if not count:
                continue
            hh_db = np.clip(_db(hh_power[valid]), HISTOGRAM_MIN_DB, HISTOGRAM_MAX_DB)
            hv_db = np.clip(_db(hv_power[valid]), HISTOGRAM_MIN_DB, HISTOGRAM_MAX_DB)
            hh_histogram += np.histogram(hh_db, bins=histogram_edges)[0]
            hv_histogram += np.histogram(hv_db, bins=histogram_edges)[0]

        if corridor_pixel_count == 0:
            raise ValueError(
                "The NISAR product does not contain rasterized pixels in the selected river corridor."
            )
        if valid_pixel_count == 0:
            no_data_result = {
                "river_id": river_id,
                "product_id": product_id,
                "status": "no_valid_corridor_data",
                "processor_version": PROCESSOR_VERSION,
                "algorithm": (
                    "No classification performed: no paired, fully focused frequency-A HH/HV pixels "
                    "were available inside the mapped river corridor."
                ),
                "frequency": FREQUENCY,
                "dataset_paths": {
                    "hh": required_paths["hh"],
                    "hv": required_paths["hv"],
                    "validity_mask": required_paths["validity_mask"],
                    "x_coordinates": required_paths["x"],
                    "y_coordinates": required_paths["y"],
                    "projection": required_paths["projection"],
                },
                "acquisition_start": None,
                "polarization": polarizations,
                "input_crs": source_crs,
                "pixel_size_m": math.sqrt(pixel_area_m2),
                "reference_centerline_coverage_percent": centerline_coverage_percent,
                "reference_centerline_length_km": projected_reference.length / 1000,
                "covered_centerline_length_km": covered_centerline.length / 1000,
                "corridor_half_width_m": CORRIDOR_HALF_WIDTH_M,
                "corridor_pixel_count": corridor_pixel_count,
                "valid_pixel_count": 0,
                "valid_data_fraction": 0.0,
                "water_pixel_count": None,
                "candidate_water_area_m2": None,
                "candidate_water_area_lower_m2": None,
                "candidate_water_area_upper_m2": None,
                "hh_threshold_db": None,
                "hv_threshold_db": None,
                "threshold_sensitivity_db": THRESHOLD_SENSITIVITY_DB,
                "mask_width": 0,
                "mask_height": 0,
                "mask_url": None,
                "measurements_url": None,
                "polygons_url": None,
                "metadata_url": "",
                "polygon_feature_count": 0,
                "vectorization_truncated": False,
                "processing_completed_at": datetime.now(timezone.utc).isoformat(),
                "caveats": NISAR_GCOV_CAVEATS + [
                    "No water mask or area was generated because the product validity mask and HH/HV samples contain no valid paired observations in the reference corridor."
                ],
            }
            if output_directory.exists():
                raise FileExistsError(
                    "A NISAR processing output already exists; use its cached result rather than overwriting it."
                )
            stage_parent = output_directory.parent
            stage_parent.mkdir(parents=True, exist_ok=True)
            stage_directory = Path(
                tempfile.mkdtemp(prefix=".nisar-processing-", dir=stage_parent)
            )
            try:
                (stage_directory / "processing-metadata.json").write_text(
                    json.dumps(no_data_result, indent=2),
                    encoding="utf-8",
                )
                os.replace(stage_directory, output_directory)
            except Exception:
                import shutil

                shutil.rmtree(stage_directory, ignore_errors=True)
                raise
            return no_data_result
        hh_threshold_db = _otsu_threshold(hh_histogram, histogram_edges)
        hv_threshold_db = _otsu_threshold(hv_histogram, histogram_edges)
        stage_parent = output_directory.parent
        stage_parent.mkdir(parents=True, exist_ok=True)
        if output_directory.exists():
            raise FileExistsError(
                "A NISAR processing output already exists; use its cached result rather than overwriting it."
            )
        stage_directory = Path(tempfile.mkdtemp(prefix=".nisar-processing-", dir=stage_parent))
        try:
            mask_path = stage_directory / "candidate-water-mask.tif"
            mask_profile = {
                "driver": "GTiff",
                "width": crop_width,
                "height": crop_height,
                "count": 1,
                "dtype": "uint8",
                "crs": source_crs,
                "transform": output_transform,
                "nodata": 255,
                "compress": "deflate",
                "predictor": 2,
                "tiled": True,
                "blockxsize": TILE_SIZE,
                "blockysize": TILE_SIZE,
            }
            measurements_path = stage_directory / "gcov-measurements.tif"
            measurements_profile = {
                **mask_profile,
                "count": 2,
                "dtype": "float32",
                "nodata": float("nan"),
                "predictor": 3,
            }
            water_pixel_count = 0
            lower_sensitivity_count = 0
            upper_sensitivity_count = 0
            with (
                rasterio.open(mask_path, "w", **mask_profile) as output,
                rasterio.open(measurements_path, "w", **measurements_profile) as measurements,
            ):
                measurements.set_band_description(1, "HHHH linear covariance power")
                measurements.set_band_description(2, "HVHV linear covariance power")
                for row, column, height, width in _tiles(crop_height, crop_width):
                    output_window = Window(column, row, width, height)
                    window = Window(column_start + column, row_start + row, width, height)
                    local_transform = window_transform(window, full_transform)
                    inside_corridor = rasterize(
                        [(corridor, 1)],
                        out_shape=(height, width),
                        transform=local_transform,
                        fill=0,
                        dtype="uint8",
                    ).astype(bool)
                    result = np.full((height, width), 255, dtype=np.uint8)
                    hh_output = np.full((height, width), np.nan, dtype=np.float32)
                    hv_output = np.full((height, width), np.nan, dtype=np.float32)
                    if np.any(inside_corridor):
                        hh_power = hh_dataset[
                            row_start + row : row_start + row + height,
                            column_start + column : column_start + column + width,
                        ]
                        hv_power = hv_dataset[
                            row_start + row : row_start + row + height,
                            column_start + column : column_start + column + width,
                        ]
                        sample_mask = validity_mask_dataset[
                            row_start + row : row_start + row + height,
                            column_start + column : column_start + column + width,
                        ]
                        valid = inside_corridor & np.isfinite(hh_power) & np.isfinite(hv_power)
                        valid &= (hh_power >= 0) & (hv_power >= 0) & (sample_mask > 0) & (sample_mask != 255)
                        result[valid] = 0
                        if np.any(valid):
                            hh_output[valid] = hh_power[valid]
                            hv_output[valid] = hv_power[valid]
                            hh_db = _db(hh_power[valid])
                            hv_db = _db(hv_power[valid])
                            candidate = (hh_db <= hh_threshold_db) & (hv_db <= hv_threshold_db)
                            lower_sensitivity = (
                                (hh_db <= hh_threshold_db - THRESHOLD_SENSITIVITY_DB)
                                & (hv_db <= hv_threshold_db - THRESHOLD_SENSITIVITY_DB)
                            )
                            upper_sensitivity = (
                                (hh_db <= hh_threshold_db + THRESHOLD_SENSITIVITY_DB)
                                & (hv_db <= hv_threshold_db + THRESHOLD_SENSITIVITY_DB)
                            )
                            valid_positions = np.flatnonzero(valid)
                            result.flat[valid_positions[candidate]] = 1
                            water_pixel_count += int(candidate.sum())
                            lower_sensitivity_count += int(lower_sensitivity.sum())
                            upper_sensitivity_count += int(upper_sensitivity.sum())
                    output.write(result, 1, window=output_window)
                    measurements.write(hh_output, 1, window=output_window)
                    measurements.write(hv_output, 2, window=output_window)

            geojson_path = stage_directory / "candidate-water.geojson"
            polygon_count, vectorization_truncated = _write_geojson(
                mask_path,
                geojson_path,
                source_crs,
                pixel_area_m2,
                raster_shapes,
                transform_geom,
                Window,
                window_transform,
            )
            result = {
                "river_id": river_id,
                "product_id": product_id,
                "status": "unvalidated_candidate",
                "processor_version": PROCESSOR_VERSION,
                "algorithm": CLASSIFICATION_ALGORITHM,
                "frequency": FREQUENCY,
                "dataset_paths": {
                    "hh": required_paths["hh"],
                    "hv": required_paths["hv"],
                    "validity_mask": required_paths["validity_mask"],
                    "x_coordinates": required_paths["x"],
                    "y_coordinates": required_paths["y"],
                    "projection": required_paths["projection"],
                },
                "acquisition_start": None,
                "polarization": polarizations,
                "input_crs": source_crs,
                "pixel_size_m": math.sqrt(pixel_area_m2),
                "reference_centerline_coverage_percent": centerline_coverage_percent,
                "reference_centerline_length_km": projected_reference.length / 1000,
                "covered_centerline_length_km": covered_centerline.length / 1000,
                "corridor_half_width_m": CORRIDOR_HALF_WIDTH_M,
                "corridor_pixel_count": corridor_pixel_count,
                "valid_pixel_count": valid_pixel_count,
                "valid_data_fraction": valid_pixel_count / corridor_pixel_count,
                "water_pixel_count": water_pixel_count,
                "candidate_water_area_m2": water_pixel_count * pixel_area_m2,
                "candidate_water_area_lower_m2": lower_sensitivity_count * pixel_area_m2,
                "candidate_water_area_upper_m2": upper_sensitivity_count * pixel_area_m2,
                "hh_threshold_db": hh_threshold_db,
                "hv_threshold_db": hv_threshold_db,
                "threshold_sensitivity_db": THRESHOLD_SENSITIVITY_DB,
                "mask_width": crop_width,
                "mask_height": crop_height,
                "mask_url": "",
                "measurements_url": "",
                "polygons_url": "",
                "metadata_url": "",
                "polygon_feature_count": polygon_count,
                "vectorization_truncated": vectorization_truncated,
                "processing_completed_at": datetime.now(timezone.utc).isoformat(),
                "caveats": NISAR_GCOV_CAVEATS,
            }
            (stage_directory / "processing-metadata.json").write_text(
                json.dumps(result, indent=2),
                encoding="utf-8",
            )
            output_directory.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage_directory, output_directory)
        except Exception:
            import shutil

            shutil.rmtree(stage_directory, ignore_errors=True)
            raise

    return result
