import json
import math
import uuid
from datetime import datetime
from importlib import import_module
from itertools import combinations
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import numpy as np
from scipy.ndimage import uniform_filter

from app.schemas.analysis import (
    AnalysisResult,
    ChangeDetectionRequest,
    ChangeResult,
    TemporalCandidatePair,
    RiverAxisSamplingRequest,
    RiverAxisSamplingResult,
    RiverAxisWidthSample,
    WaterMaskRequest,
    WidthMeasurementRequest,
    WidthMeasurementResult,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPOSITORY_ROOT / "outputs" / "analysis"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_RASTER_PIXELS = 2_000_000
LEE_WINDOW = 5
THRESHOLD_SENSITIVITY_DB = 1.0
MAX_VECTOR_FEATURES = 5_000

WATER_MASK_CAVEATS = [
    "Candidate open-water extent only; not a verified riverbank or flood/erosion/deposition product.",
    "Candidate pixels may include other low-backscatter surfaces and do not by themselves isolate a river channel.",
    "Input mission, calibration, terrain correction, polarization, and band metadata have not been independently validated by this application.",
    "The input must be a single-band, georeferenced, radiometrically calibrated linear-power or dB raster in a projected metre-based CRS.",
    "Threshold and Lee filtering are generic; no reference labels, accuracy score, or uncertainty calibration are available.",
    "The reported area sensitivity range uses the selected threshold ±1 dB; it is a sensitivity check, not a statistical confidence interval.",
    "Cloud, terrain shadow, vegetation, layover, incidence angle, and seasonal effects are not independently screened.",
]


class ProcessingUnavailable(RuntimeError):
    pass


class InsufficientValidDataError(ValueError):
    pass


class IncompatibleCandidatePair(ValueError):
    pass


def _require_rasterio() -> Any:
    try:
        return import_module("rasterio")
    except ImportError as error:
        raise ProcessingUnavailable(
            "GeoTIFF processing is unavailable because Rasterio could not be loaded in this environment. "
            "No demonstration data or substitute processing was used."
        ) from error


def _new_id() -> str:
    return str(uuid.uuid4())


def _analysis_directory(analysis_id: str) -> Path:
    try:
        normalized_id = str(uuid.UUID(analysis_id))
    except ValueError as error:
        raise ValueError("Invalid analysis identifier.") from error
    directory = (OUTPUT_DIR / normalized_id).resolve()
    if not directory.is_relative_to(OUTPUT_DIR.resolve()) or not directory.is_dir():
        raise FileNotFoundError(f"Analysis {normalized_id} was not found.")
    return directory


def _load_result(analysis_id: str) -> dict[str, Any]:
    directory = _analysis_directory(analysis_id)
    result_path = (directory / "result.json").resolve()
    if not result_path.is_relative_to(directory) or not result_path.is_file():
        raise FileNotFoundError(f"Analysis {analysis_id} was not found.")
    return json.loads(result_path.read_text(encoding="utf-8"))


def _write_geotiff(
    path: Path,
    values: np.ndarray,
    source: Any,
    nodata: int,
) -> None:
    rasterio = _require_rasterio()
    profile = source.profile.copy()
    profile.update(
        driver="GTiff",
        count=1,
        dtype="uint8",
        nodata=nodata,
        compress="deflate",
        predictor=2,
    )
    with rasterio.open(path, "w", **profile) as output:
        output.write(values, 1)


def _lee_filter(power: np.ndarray, valid: np.ndarray) -> np.ndarray:
    weights = uniform_filter(valid.astype(np.float32), size=LEE_WINDOW, mode="reflect")
    safe_power = np.where(valid, power, 0).astype(np.float32)
    local_mean = uniform_filter(safe_power, size=LEE_WINDOW, mode="reflect") / np.maximum(weights, 1e-6)
    local_second_moment = uniform_filter(
        np.where(valid, power * power, 0).astype(np.float32),
        size=LEE_WINDOW,
        mode="reflect",
    ) / np.maximum(weights, 1e-6)
    local_variance = np.maximum(local_second_moment - local_mean * local_mean, 0)
    noise_variance = float(np.percentile(local_variance[valid], 20))
    gain = np.clip(
        (local_variance - noise_variance) / np.maximum(local_variance, 1e-12),
        0,
        1,
    )
    filtered = local_mean + gain * (power - local_mean)
    filtered[~valid] = np.nan
    return filtered


def _otsu_threshold_db(values_db: np.ndarray) -> float:
    finite = values_db[np.isfinite(values_db)]
    if finite.size < 2:
        raise ValueError("The raster does not contain enough valid pixels for thresholding.")
    lower, upper = np.percentile(finite, [1, 99])
    if not math.isfinite(float(lower)) or not math.isfinite(float(upper)) or upper <= lower:
        raise ValueError("The valid raster values have insufficient contrast for thresholding.")
    sample = finite[::max(1, finite.size // 1_000_000)]
    counts, edges = np.histogram(sample, bins=256, range=(lower, upper))
    centers = (edges[:-1] + edges[1:]) / 2
    probabilities = counts.astype(np.float64) / max(int(counts.sum()), 1)
    cumulative_weight = np.cumsum(probabilities)
    cumulative_mean = np.cumsum(probabilities * centers)
    total_mean = cumulative_mean[-1]
    denominator = cumulative_weight * (1 - cumulative_weight)
    between_class_variance = np.zeros_like(denominator)
    usable = denominator > 0
    between_class_variance[usable] = (
        (total_mean * cumulative_weight[usable] - cumulative_mean[usable]) ** 2
        / denominator[usable]
    )
    return float(centers[int(np.argmax(between_class_variance))])


def _write_water_polygons(
    path: Path,
    mask: np.ndarray,
    source: Any,
) -> bool:
    from rasterio.features import shapes
    from rasterio.warp import transform_geom

    features: list[dict[str, Any]] = []
    truncated = False
    for geometry, value in shapes(
        mask.astype(np.uint8),
        mask=mask.astype(bool),
        transform=source.transform,
    ):
        if value != 1:
            continue
        if len(features) >= MAX_VECTOR_FEATURES:
            truncated = True
            break
        features.append(
            {
                "type": "Feature",
                "properties": {"class": "candidate_open_water"},
                "geometry": transform_geom(source.crs, "EPSG:4326", geometry, precision=6),
            }
        )
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "name": "unvalidated_candidate_open_water",
                "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
                "features": features,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return truncated


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def process_water_mask(
    raster_bytes: bytes,
    request: WaterMaskRequest,
    *,
    additional_caveats: tuple[str, ...] = (),
) -> AnalysisResult:
    if not request.radiometric_calibration_confirmed or not request.terrain_correction_confirmed:
        raise ValueError(
            "Processing requires operator confirmation that radiometric calibration and terrain correction are complete."
        )
    if len(raster_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError(f"Raster upload exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")
    rasterio = _require_rasterio()

    analysis_id = _new_id()
    output_dir = OUTPUT_DIR / analysis_id
    output_dir.mkdir(parents=True, exist_ok=False)

    try:
        with rasterio.io.MemoryFile(raster_bytes) as memory_file, memory_file.open() as source:
            if source.count != 1:
                raise ValueError("Upload a single-band GeoTIFF containing calibrated backscatter.")
            if source.crs is None or not source.crs.is_projected:
                raise ValueError("The input raster must use a projected coordinate reference system.")
            if source.crs.linear_units.casefold() not in {"metre", "meter"}:
                raise ValueError("The projected input raster CRS must use metres.")
            if source.width * source.height > MAX_RASTER_PIXELS:
                raise ValueError(f"Raster dimensions exceed the {MAX_RASTER_PIXELS:,}-pixel processing limit.")
            if source.transform.determinant == 0:
                raise ValueError("The input raster has an invalid georeferencing transform.")

            band = source.read(1, masked=True).astype(np.float32)
            raw = np.asarray(band.filled(np.nan), dtype=np.float32)
            valid = np.isfinite(raw)
            if request.signal_scale == "linear_power":
                valid &= raw > 0
                power = raw
            else:
                power = np.power(10.0, raw / 10.0, dtype=np.float32)
                valid &= np.isfinite(power) & (power > 0)
            valid_count = int(valid.sum())
            if valid_count < 32:
                raise InsufficientValidDataError(
                    "The raster has fewer than 32 valid positive backscatter pixels."
                )

            filtered_power = _lee_filter(power, valid)
            filtered_db = 10 * np.log10(np.maximum(filtered_power, 1e-30))
            threshold_db = (
                _otsu_threshold_db(filtered_db[valid])
                if request.threshold_method == "otsu"
                else float(request.threshold_db)
            )
            water = valid & (filtered_db <= threshold_db)
            lower_sensitivity_count = int(
                (valid & (filtered_db <= threshold_db - THRESHOLD_SENSITIVITY_DB)).sum()
            )
            upper_sensitivity_count = int(
                (valid & (filtered_db <= threshold_db + THRESHOLD_SENSITIVITY_DB)).sum()
            )
            water_count = int(water.sum())
            if water_count == 0 or water_count == valid_count:
                raise ValueError(
                    "The selected threshold classified every valid pixel into one class; review the input and threshold."
                )

            mask_values = np.full(raw.shape, 255, dtype=np.uint8)
            mask_values[valid] = 0
            mask_values[water] = 1
            mask_path = output_dir / "water-mask.tif"
            polygons_path = output_dir / "water-polygons.geojson"
            _write_geotiff(mask_path, mask_values, source, nodata=255)
            polygons_truncated = _write_water_polygons(polygons_path, water, source)
            transform_area = abs(
                source.transform.a * source.transform.e
                - source.transform.b * source.transform.d
            )
            valid_fraction = valid_count / raw.size
            caveats = [*WATER_MASK_CAVEATS, *additional_caveats]
            if polygons_truncated:
                caveats.append(f"Polygon output is capped at {MAX_VECTOR_FEATURES:,} features.")
            result = AnalysisResult(
                analysis_id=analysis_id,
                analysis_type="water_mask",
                status="unvalidated_candidate",
                source_product_id=request.source_product_id,
                mission=request.mission,
                river_id=request.river_id,
                acquisition_start=request.acquisition_start,
                polarization=request.polarization,
                band_description=request.band_description,
                signal_scale=request.signal_scale,
                threshold_method=request.threshold_method,
                threshold_db=threshold_db,
                threshold_sensitivity_range_db=THRESHOLD_SENSITIVITY_DB,
                filter_method=(
                    f"Lee local-statistic filter ({LEE_WINDOW}x{LEE_WINDOW}; "
                    "20th-percentile local variance proxy)"
                ),
                valid_pixel_count=valid_count,
                water_pixel_count=water_count,
                valid_data_fraction=valid_fraction,
                pixel_area_m2=transform_area,
                candidate_water_area_m2=water_count * transform_area,
                candidate_water_area_lower_m2=lower_sensitivity_count * transform_area,
                candidate_water_area_upper_m2=upper_sensitivity_count * transform_area,
                input_crs=source.crs.to_string(),
                mask_url=f"/api/analysis/{analysis_id}/mask",
                polygons_url=f"/api/analysis/{analysis_id}/polygons",
                report_url=f"/api/analysis/{analysis_id}/report",
                caveats=caveats,
            )
            result_payload = result.model_dump(mode="json")
            result_payload["operator_supplied_metadata"] = request.model_dump(mode="json")
            result_payload["output_files"] = {
                "mask": "water-mask.tif",
                "polygons": "water-polygons.geojson",
            }
            _save_json(output_dir / "result.json", result_payload)
            return result
    except Exception as error:
        if output_dir.exists():
            for output_file in output_dir.iterdir():
                if output_file.is_file():
                    output_file.unlink()
            output_dir.rmdir()
        if isinstance(error, rasterio.errors.RasterioError):
            raise ValueError(f"Unable to read or write the supplied GeoTIFF: {error}") from error
        raise


def _aware_acquisition_time(result: dict[str, Any]) -> datetime:
    try:
        acquired = datetime.fromisoformat(result["acquisition_start"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as error:
        raise IncompatibleCandidatePair("Both candidate masks must record acquisition timestamps.") from error
    if acquired.tzinfo is None or acquired.utcoffset() is None:
        raise IncompatibleCandidatePair("Candidate acquisition timestamps must include a timezone.")
    return acquired


def _comparison_metadata(
    earlier: dict[str, Any],
    later: dict[str, Any],
) -> dict[str, Any]:
    if earlier.get("analysis_type") != "water_mask" or later.get("analysis_type") != "water_mask":
        raise IncompatibleCandidatePair("Only two single-date candidate water masks can be compared.")
    if earlier.get("status") != "unvalidated_candidate" or later.get("status") != "unvalidated_candidate":
        raise IncompatibleCandidatePair("Both inputs must be explicitly classified as unvalidated candidates.")
    if earlier.get("river_id") != later.get("river_id"):
        raise IncompatibleCandidatePair("Water masks must be from the same river.")

    earlier_time = _aware_acquisition_time(earlier)
    later_time = _aware_acquisition_time(later)
    if earlier_time >= later_time:
        raise IncompatibleCandidatePair("The earlier acquisition must precede the later acquisition.")

    earlier_metadata = earlier.get("operator_supplied_metadata")
    later_metadata = later.get("operator_supplied_metadata")
    if not isinstance(earlier_metadata, dict) or not isinstance(later_metadata, dict):
        raise IncompatibleCandidatePair("Both analyses must retain their processing and product provenance.")

    fields = ("mission", "product_type", "polarization", "signal_scale", "threshold_method")
    for field in fields:
        if not earlier_metadata.get(field) or earlier_metadata.get(field) != later_metadata.get(field):
            raise IncompatibleCandidatePair(f"Candidate masks have incompatible {field.replace('_', ' ')} metadata.")
    for field in ("radiometric_calibration_confirmed", "terrain_correction_confirmed"):
        if earlier_metadata.get(field) is not True or later_metadata.get(field) is not True:
            raise IncompatibleCandidatePair("Both inputs must record calibration and terrain-correction confirmation.")
    if earlier.get("filter_method") != later.get("filter_method"):
        raise IncompatibleCandidatePair("Candidate masks use incompatible spatial filters.")
    if earlier["threshold_method"] != later_metadata["threshold_method"]:
        raise IncompatibleCandidatePair("Candidate result and input threshold-method metadata disagree.")

    earlier_threshold = float(earlier["threshold_db"])
    later_threshold = float(later["threshold_db"])
    if earlier_metadata["threshold_method"] == "fixed_db":
        if not math.isclose(
            earlier_threshold,
            later_threshold,
            rel_tol=0,
            abs_tol=1e-9,
        ):
            raise IncompatibleCandidatePair("Fixed-threshold candidate masks must use the same threshold value.")

    earlier_product_id = earlier.get("source_product_id")
    later_product_id = later.get("source_product_id")
    if not earlier_product_id or not later_product_id or earlier_product_id == later_product_id:
        raise IncompatibleCandidatePair("Candidate masks must identify two distinct source products.")
    if (
        earlier_metadata.get("source_product_id") != earlier_product_id
        or later_metadata.get("source_product_id") != later_product_id
    ):
        raise IncompatibleCandidatePair("Source product identifiers do not match their recorded provenance.")
    for result, metadata, label in (
        (earlier, earlier_metadata, "earlier"),
        (later, later_metadata, "later"),
    ):
        if (
            result.get("mission") != metadata["mission"]
            or result.get("polarization") != metadata["polarization"]
            or result.get("threshold_method") != metadata["threshold_method"]
            or (
                metadata["threshold_method"] == "fixed_db"
                and not math.isclose(
                    float(result.get("threshold_db", math.nan)),
                    float(metadata.get("threshold_db", math.nan)),
                    rel_tol=0,
                    abs_tol=1e-9,
                )
            )
        ):
            raise IncompatibleCandidatePair(
                f"The {label} candidate result disagrees with its recorded input metadata."
            )

    return {
        "earlier_time": earlier_time,
        "later_time": later_time,
        "mission": earlier_metadata["mission"],
        "product_type": earlier_metadata["product_type"],
        "polarization": earlier_metadata["polarization"],
        "threshold_method": earlier_metadata["threshold_method"],
        "earlier_threshold_db": earlier_threshold,
        "later_threshold_db": later_threshold,
        "threshold_delta_db": later_threshold - earlier_threshold,
        "filter_method": earlier["filter_method"],
        "river_id": earlier["river_id"],
        "earlier_product_id": earlier_product_id,
        "later_product_id": later_product_id,
    }


def _prepare_candidate_comparison(
    earlier_analysis_id: str,
    later_analysis_id: str,
) -> dict[str, Any]:
    rasterio = _require_rasterio()
    if earlier_analysis_id == later_analysis_id:
        raise IncompatibleCandidatePair("Choose two different analysis identifiers.")
    earlier = _load_result(earlier_analysis_id)
    later = _load_result(later_analysis_id)
    context = _comparison_metadata(earlier, later)

    earlier_dir = _analysis_directory(earlier_analysis_id)
    later_dir = _analysis_directory(later_analysis_id)
    with rasterio.open(earlier_dir / "water-mask.tif") as first, rasterio.open(
        later_dir / "water-mask.tif"
    ) as second:
        if (
            first.crs != second.crs
            or first.transform != second.transform
            or first.width != second.width
            or first.height != second.height
        ):
            raise IncompatibleCandidatePair(
                "Water masks must have identical CRS, transform, and dimensions; re-align them first."
            )
        if (
            first.crs is None
            or not first.crs.is_projected
            or first.crs.linear_units.casefold() not in {"metre", "meter"}
            or first.nodata != 255
            or second.nodata != 255
        ):
            raise IncompatibleCandidatePair(
                "Candidate masks must use a projected metre CRS and preserve 255 as NoData."
            )
        if first.width * first.height > MAX_RASTER_PIXELS:
            raise IncompatibleCandidatePair("Candidate comparison exceeds the supported raster-pixel limit.")

        first_data = first.read(1)
        second_data = second.read(1)
        first_valid = (first.read_masks(1) > 0) & (first_data != first.nodata)
        second_valid = (second.read_masks(1) > 0) & (second_data != second.nodata)
        if np.any(first_valid & ~np.isin(first_data, (0, 1))) or np.any(
            second_valid & ~np.isin(second_data, (0, 1))
        ):
            raise IncompatibleCandidatePair("Candidate masks contain classes other than 0, 1, and NoData.")
        valid = first_valid & second_valid
        common_valid_count = int(valid.sum())
        if common_valid_count == 0:
            raise IncompatibleCandidatePair("Candidate masks have no common valid pixels.")
        pixel_area = abs(first.transform.a * first.transform.e - first.transform.b * first.transform.d)
        pixel_size_x = math.hypot(first.transform.a, first.transform.d)
        pixel_size_y = math.hypot(first.transform.b, first.transform.e)
        if not math.isclose(pixel_size_x, pixel_size_y, rel_tol=1e-6, abs_tol=1e-6):
            raise IncompatibleCandidatePair("Candidate masks must use square pixels for this comparison.")
        context.update(
            {
                "first_data": first_data,
                "second_data": second_data,
                "valid": valid,
                "common_valid_pixel_count": common_valid_count,
                "total_grid_pixel_count": int(first.width * first.height),
                "common_valid_area_m2": common_valid_count * pixel_area,
                "common_valid_fraction": common_valid_count / (first.width * first.height),
                "pixel_area_m2": pixel_area,
                "pixel_size_m": pixel_size_x,
                "width": first.width,
                "height": first.height,
                "crs": first.crs.to_string(),
            }
        )
    return context


def list_compatible_candidate_pairs(observations: list[Any]) -> list[TemporalCandidatePair]:
    ordered = sorted(observations, key=lambda observation: observation.acquisition_start)
    pairs: list[TemporalCandidatePair] = []
    for earlier_observation, later_observation in combinations(ordered, 2):
        try:
            context = _prepare_candidate_comparison(
                earlier_observation.analysis_id,
                later_observation.analysis_id,
            )
        except IncompatibleCandidatePair:
            continue
        days_apart = (
            context["later_time"] - context["earlier_time"]
        ).total_seconds() / 86_400
        earlier_month = context["earlier_time"].strftime("%B %Y")
        later_month = context["later_time"].strftime("%B %Y")
        threshold_context = (
            "The same Otsu method and filter were used, but the threshold was estimated separately for each date."
            if context["threshold_method"] == "otsu"
            else "The same fixed threshold and filter were used for both dates."
        )
        pairs.append(
            TemporalCandidatePair(
                river_id=earlier_observation.river_id,
                earlier_analysis_id=earlier_observation.analysis_id,
                later_analysis_id=later_observation.analysis_id,
                earlier_source_product_id=context["earlier_product_id"],
                later_source_product_id=context["later_product_id"],
                earlier_acquisition_start=context["earlier_time"],
                later_acquisition_start=context["later_time"],
                elapsed_days=days_apart,
                mission=context["mission"],
                product_type=context["product_type"],
                polarization=context["polarization"],
                threshold_method=context["threshold_method"],
                earlier_threshold_db=context["earlier_threshold_db"],
                later_threshold_db=context["later_threshold_db"],
                threshold_delta_db=context["threshold_delta_db"],
                filter_method=context["filter_method"],
                crs=context["crs"],
                pixel_size_m=context["pixel_size_m"],
                width=context["width"],
                height=context["height"],
                common_valid_pixel_count=context["common_valid_pixel_count"],
                common_valid_area_m2=context["common_valid_area_m2"],
                common_valid_fraction=context["common_valid_fraction"],
                earlier_source_record_url=earlier_observation.stac_item_url,
                later_source_record_url=later_observation.stac_item_url,
                seasonal_context=(
                    f"Acquisitions are {days_apart:.2f} days apart ({earlier_month} to {later_month}); "
                    "no seasonal adjustment was applied."
                ),
                parameter_compatibility=threshold_context,
                caveats=[
                    "A compatible grid and processing configuration do not establish accurate co-registration or scientific validity.",
                    "Common support excludes NoData and invalid pixels from either date.",
                    "Candidate-water gain/loss is exploratory and is not evidence of erosion, deposition, flooding, or verified river change.",
                ],
            )
        )
    return pairs


def compare_water_masks(request: ChangeDetectionRequest) -> ChangeResult:
    context = _prepare_candidate_comparison(
        request.earlier_analysis_id,
        request.later_analysis_id,
    )
    earlier_time = context["earlier_time"]
    later_time = context["later_time"]
    change_id = _new_id()
    output_dir = OUTPUT_DIR / change_id
    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        rasterio = _require_rasterio()
        earlier_dir = _analysis_directory(request.earlier_analysis_id)
        with rasterio.open(earlier_dir / "water-mask.tif") as first:
            first_data = context["first_data"]
            second_data = context["second_data"]
            valid = context["valid"]
            gain = valid & (first_data == 0) & (second_data == 1)
            loss = valid & (first_data == 1) & (second_data == 0)
            gain_count = int(gain.sum())
            loss_count = int(loss.sum())
            change_values = np.full(first_data.shape, 255, dtype=np.uint8)
            change_values[valid] = 0
            change_values[gain] = 1
            change_values[loss] = 2
            mask_path = output_dir / "change-mask.tif"
            _write_geotiff(mask_path, change_values, first, nodata=255)
            pixel_area = context["pixel_area_m2"]
            result = ChangeResult(
                change_id=change_id,
                analysis_type="two_date_water_extent_comparison",
                status="unvalidated_candidate",
                earlier_analysis_id=request.earlier_analysis_id,
                later_analysis_id=request.later_analysis_id,
                earlier_source_product_id=context["earlier_product_id"],
                later_source_product_id=context["later_product_id"],
                earlier_acquisition_start=earlier_time,
                later_acquisition_start=later_time,
                mission=context["mission"],
                product_type=context["product_type"],
                polarization=context["polarization"],
                threshold_method=context["threshold_method"],
                earlier_threshold_db=context["earlier_threshold_db"],
                later_threshold_db=context["later_threshold_db"],
                threshold_delta_db=context["threshold_delta_db"],
                filter_method=context["filter_method"],
                crs=context["crs"],
                pixel_size_m=context["pixel_size_m"],
                common_valid_pixel_count=context["common_valid_pixel_count"],
                common_valid_area_m2=context["common_valid_area_m2"],
                common_valid_fraction=context["common_valid_fraction"],
                water_gain_pixel_count=gain_count,
                water_loss_pixel_count=loss_count,
                pixel_area_m2=pixel_area,
                candidate_water_gain_area_m2=gain_count * pixel_area,
                candidate_water_loss_area_m2=loss_count * pixel_area,
                change_mask_url=f"/api/analysis/{change_id}/mask",
                report_url=f"/api/analysis/{change_id}/report",
                caveats=[
                    "Two-date water-extent differences are candidate changes, not validated hydrological change.",
                    "No seasonal normalization, acquisition-geometry correction, registration-error assessment, or threshold-uncertainty correction was applied.",
                    "Water gain/loss is not evidence of erosion or deposition.",
                    "The service checks equal grids and matching declared processing metadata; it cannot establish accurate co-registration or verify operator-supplied metadata.",
                    (
                        f"Otsu thresholds were independently estimated ({context['earlier_threshold_db']:.3f} dB and "
                        f"{context['later_threshold_db']:.3f} dB); differences may reflect threshold variation."
                        if context["threshold_method"] == "otsu"
                        else "Both dates use the same fixed threshold."
                    ),
                ],
            )
            payload = result.model_dump(mode="json")
            payload["output_files"] = {"mask": "change-mask.tif"}
            payload["river_id"] = context["river_id"]
            _save_json(output_dir / "result.json", payload)
            return result
    except Exception:
        if output_dir.exists():
            for output_file in output_dir.iterdir():
                if output_file.is_file():
                    output_file.unlink()
            output_dir.rmdir()
        raise


def measure_water_width(request: WidthMeasurementRequest) -> WidthMeasurementResult:
    rasterio = _require_rasterio()
    from rasterio.warp import transform

    result = _load_result(request.analysis_id)
    analysis_dir = _analysis_directory(request.analysis_id)
    with rasterio.open(analysis_dir / "water-mask.tif") as mask:
        xs, ys = transform(
            "EPSG:4326",
            mask.crs,
            [request.start[0], request.end[0]],
            [request.start[1], request.end[1]],
        )
        pixel_x = math.hypot(mask.transform.a, mask.transform.d)
        pixel_y = math.hypot(mask.transform.b, mask.transform.e)
        sample_spacing = min(pixel_x, pixel_y)
        if sample_spacing <= 0:
            raise ValueError("The stored raster has an invalid pixel size.")
        line_length = math.hypot(xs[1] - xs[0], ys[1] - ys[0])
        if line_length < sample_spacing or line_length > 50_000:
            raise ValueError("Transect length must be at least one pixel and no more than 50 km.")
        sample_count = min(math.ceil(line_length / sample_spacing) + 1, 100_000)
        columns = np.linspace(xs[0], xs[1], sample_count)
        rows = np.linspace(ys[0], ys[1], sample_count)
        mask_data = mask.read(1)
        positions: list[bool] = []
        for x, y in zip(columns, rows):
            row, column = mask.index(float(x), float(y))
            if 0 <= row < mask.height and 0 <= column < mask.width:
                value = mask_data[row, column]
                positions.append(value == 1)
            else:
                positions.append(False)
        segments: list[float] = []
        spacing_along_line = line_length / max(sample_count - 1, 1)
        current_count = 0
        for is_water in positions:
            if is_water:
                current_count += 1
            elif current_count:
                segments.append(current_count * spacing_along_line)
                current_count = 0
        if current_count:
            segments.append(current_count * spacing_along_line)
        return WidthMeasurementResult(
            analysis_id=request.analysis_id,
            transect_length_m=line_length,
            sampled_water_segments_m=segments,
            longest_contiguous_water_width_m=max(segments, default=0.0),
            status="unvalidated_candidate",
            caveats=[
                "Width is the candidate-water segment sampled along the user-supplied transect, not a verified channel width or bank-to-bank survey.",
                "Accuracy depends on raster pixel size, geolocation, classification threshold, and transect placement.",
                f"Source acquisition: {result['source_product_id']}.",
            ],
        )


def sample_candidate_widths_along_axis(
    request: RiverAxisSamplingRequest,
) -> RiverAxisSamplingResult:
    rasterio = _require_rasterio()
    from rasterio.warp import transform_geom
    from shapely.geometry import Point, mapping, shape

    result = _load_result(request.analysis_id)
    if result.get("status") != "unvalidated_candidate":
        raise ValueError("Axis sampling requires an unvalidated candidate-mask analysis.")
    analysis_dir = _analysis_directory(request.analysis_id)
    with rasterio.open(analysis_dir / "water-mask.tif") as mask:
        if mask.count != 1 or mask.nodata != 255 or mask.crs is None:
            raise ValueError("Candidate mask must be a single-band 0/1/255 raster with CRS metadata.")
        if not mask.crs.is_projected or mask.crs.linear_units.casefold() not in {"metre", "meter"}:
            raise ValueError("Candidate mask CRS must be projected in metres.")
        axis_geojson = request.axis_geojson.get("geometry", request.axis_geojson)
        corridor_geojson = request.corridor_geojson.get("geometry", request.corridor_geojson)
        axis_wgs84 = shape(axis_geojson)
        corridor_wgs84 = shape(corridor_geojson)
        if axis_wgs84.geom_type != "LineString" or axis_wgs84.is_empty or not axis_wgs84.is_valid:
            raise ValueError("Axis geometry must be a valid, nonempty GeoJSON LineString.")
        if (
            corridor_wgs84.geom_type not in {"Polygon", "MultiPolygon"}
            or corridor_wgs84.is_empty
            or not corridor_wgs84.is_valid
        ):
            raise ValueError("Corridor geometry must be a valid, nonempty GeoJSON Polygon or MultiPolygon.")
        axis = shape(transform_geom("EPSG:4326", mask.crs, mapping(axis_wgs84)))
        corridor = shape(transform_geom("EPSG:4326", mask.crs, mapping(corridor_wgs84)))
        if not corridor.covers(axis):
            raise ValueError("The supplied corridor must fully contain the supplied river axis.")
        axis_length = float(axis.length)
        if not math.isfinite(axis_length) or axis_length < request.station_spacing_m:
            raise ValueError("River axis length must be at least one requested station interval.")
        station_count = math.ceil(axis_length / request.station_spacing_m) + 1
        if station_count > 250:
            raise ValueError("Axis sampling is limited to 250 stations; increase station_spacing_m.")
        pixel_x = math.hypot(mask.transform.a, mask.transform.d)
        pixel_y = math.hypot(mask.transform.b, mask.transform.e)
        raster_resolution = min(pixel_x, pixel_y)
        if not math.isfinite(raster_resolution) or raster_resolution <= 0:
            raise ValueError("Candidate raster has an invalid pixel resolution.")
        transect_length = request.transect_half_length_m * 2
        sample_spacing = max(raster_resolution, transect_length / 1_999)
        offsets = np.arange(
            -request.transect_half_length_m,
            request.transect_half_length_m + sample_spacing * 0.5,
            sample_spacing,
        )
        if len(offsets) > 2_000:
            raise ValueError("Transect sampling exceeds the 2,000-sample per station limit.")

        samples: list[RiverAxisWidthSample] = []
        station_distances = [
            min(index * request.station_spacing_m, axis_length)
            for index in range(station_count)
        ]
        for chainage in station_distances:
            point = axis.interpolate(chainage)
            tangent_delta = min(max(request.station_spacing_m * 0.1, 1.0), axis_length / 2)
            before = axis.interpolate(max(0.0, chainage - tangent_delta))
            after = axis.interpolate(min(axis_length, chainage + tangent_delta))
            dx = after.x - before.x
            dy = after.y - before.y
            tangent_length = math.hypot(dx, dy)
            if tangent_length <= 0:
                samples.append(
                    RiverAxisWidthSample(
                        chainage_m=chainage,
                        valid_fraction=0,
                        raster_coverage_fraction=0,
                        sampled_pixel_count=0,
                        valid_pixel_count=0,
                        quality_status="outside_raster",
                        quality_flags=["Local axis direction is undefined at this station."],
                    )
                )
                continue
            normal_x = -dy / tangent_length
            normal_y = dx / tangent_length
            coordinates = [
                (point.x + float(offset) * normal_x, point.y + float(offset) * normal_y)
                for offset in offsets
            ]
            in_corridor = [
                corridor.covers(Point(x, y))
                for x, y in coordinates
            ]
            raster_coordinates: list[tuple[float, float]] = []
            raster_sample_indices: list[int] = []
            for sample_index, ((x, y), is_covered) in enumerate(zip(coordinates, in_corridor)):
                if not is_covered:
                    continue
                row, column = mask.index(x, y)
                inside = 0 <= row < mask.height and 0 <= column < mask.width
                if inside:
                    raster_coordinates.append((x, y))
                    raster_sample_indices.append(sample_index)
            sampled_values = list(mask.sample(raster_coordinates, indexes=1, masked=True))
            valid_values: list[int | None] = [None] * len(coordinates)
            for sample_index, sampled in zip(raster_sample_indices, sampled_values):
                if np.ma.is_masked(sampled[0]):
                    continue
                value = int(sampled[0])
                valid_values[sample_index] = value if value in (0, 1) else None
            denominator = sum(in_corridor)
            raster_count = len(raster_coordinates)
            valid_count = sum(value is not None for value in valid_values)
            raster_coverage = raster_count / denominator if denominator else 0.0
            valid_fraction = valid_count / denominator if denominator else 0.0
            quality_flags: list[str] = []
            candidate_width: float | None = None
            if denominator == 0:
                quality_status = "outside_raster"
                quality_flags.append("No transect sample positions fell inside the supplied corridor.")
            elif valid_count == 0:
                quality_status = "outside_raster"
                quality_flags.append("No valid candidate-mask pixels cover this transect.")
            elif valid_fraction < request.minimum_valid_fraction:
                quality_status = "low_valid_coverage"
                quality_flags.append(
                    f"Valid fraction is below the requested {request.minimum_valid_fraction:.0%} minimum."
                )
            else:
                longest = 0
                current = 0
                for value in valid_values:
                    if value == 1:
                        current += 1
                        longest = max(longest, current)
                    else:
                        current = 0
                candidate_width = longest * sample_spacing
                if longest:
                    quality_status = "usable_candidate"
                    quality_flags.append("Width is the longest contiguous candidate-water segment.")
                else:
                    quality_status = "no_candidate"
                    quality_flags.append("No candidate-water pixels were sampled at this station.")
            if raster_coverage < 1:
                quality_flags.append("Part of the corridor-clipped transect lies outside raster coverage.")
            if sample_spacing > raster_resolution:
                quality_flags.append(
                    "Sampling interval exceeds nominal raster resolution to respect the per-transect sample limit."
                )
            samples.append(
                RiverAxisWidthSample(
                    chainage_m=chainage,
                    candidate_width_m=candidate_width,
                    valid_fraction=valid_fraction,
                    raster_coverage_fraction=raster_coverage,
                    sampled_pixel_count=denominator,
                    valid_pixel_count=valid_count,
                    quality_status=quality_status,
                    quality_flags=quality_flags,
                )
            )

    accepted_count = sum(sample.quality_status == "usable_candidate" for sample in samples)
    return RiverAxisSamplingResult(
        analysis_id=request.analysis_id,
        source_product_id=result["source_product_id"],
        acquisition_start=result["acquisition_start"],
        axis_dataset_id=request.axis_dataset_id,
        axis_source_name=request.axis_source_name,
        axis_source_url=request.axis_source_url,
        axis_geometry_status="user_supplied_not_independently_verified",
        axis_length_m=axis_length,
        station_spacing_m=request.station_spacing_m,
        transect_half_length_m=request.transect_half_length_m,
        raster_resolution_m=raster_resolution,
        requested_station_count=len(samples),
        accepted_station_count=accepted_count,
        coverage_fraction=accepted_count / len(samples) if samples else 0.0,
        uncertainty_m=None,
        uncertainty_status="not_quantified",
        samples=samples,
        quality_flags=[
            "The supplied axis and corridor are not independently verified by this application.",
            "Candidate width is a classified-mask measurement, not a surveyed or validated bank-to-bank width.",
            f"Cross-transect sample spacing is {sample_spacing:.3f} m; nominal raster resolution is {raster_resolution:.3f} m.",
            "Measurement uncertainty has not been quantified; spatial resolution and coverage are reported separately.",
        ],
        caveats=[
            "Axis source identity and URL are operator-supplied provenance and are not authenticated.",
            "The application does not infer axis or bank geometry from the OSM map centerline.",
            "Only valid 0/1 candidate-mask pixels inside the supplied corridor are sampled; 255/invalid pixels reduce coverage.",
            "Candidate-water segments may not correspond to the intended channel or true banks.",
        ],
    )


def read_output(analysis_id: str, filename: str) -> tuple[Path, dict[str, Any]]:
    result = _load_result(analysis_id)
    files = result.get("output_files", {})
    if filename not in files.values():
        raise FileNotFoundError(f"Output {filename} was not found for analysis {analysis_id}.")
    directory = _analysis_directory(analysis_id)
    path = (directory / filename).resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise FileNotFoundError(f"Output {filename} was not found for analysis {analysis_id}.")
    return path, result


def build_pdf_report(analysis_id: str) -> BytesIO:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    result = _load_result(analysis_id)
    stream = BytesIO()
    document = SimpleDocTemplate(stream, pagesize=letter, title="SAR Sentinel India analysis report")
    styles = getSampleStyleSheet()
    content: list[Any] = [
        Paragraph("SAR Sentinel India — Candidate Analysis Report", styles["Title"]),
        Spacer(1, 10),
        Paragraph("Unvalidated research output. Not a scientific finding.", styles["Heading2"]),
        Spacer(1, 10),
    ]
    if result["analysis_type"] == "water_mask":
        rows = [
            ["Field", "Value"],
            ["River", escape(result["river_id"])],
            ["Mission / product", escape(f"{result['mission']} / {result['operator_supplied_metadata']['product_type']}")],
            ["Source product ID", escape(result["source_product_id"])],
            ["Acquisition", escape(result["acquisition_start"])],
            ["Polarization / band", escape(f"{result['polarization']} / {result['band_description']}")],
            ["Input CRS", escape(result["input_crs"])],
            ["Threshold", f"{result['threshold_method']} at {result['threshold_db']:.2f} dB"],
            ["Candidate water area", f"{result['candidate_water_area_m2']:.2f} m²"],
            [
                "±1 dB threshold sensitivity (not a confidence interval)",
                f"{result['candidate_water_area_lower_m2']:.2f}–{result['candidate_water_area_upper_m2']:.2f} m²",
            ],
            ["Valid pixel fraction", f"{result['valid_data_fraction']:.4f}"],
        ]
    else:
        rows = [
            ["Field", "Value"],
            [
                "Source products / acquisition dates",
                escape(
                    f"{result['earlier_source_product_id']} ({result['earlier_acquisition_start']}) to "
                    f"{result['later_source_product_id']} ({result['later_acquisition_start']})"
                ),
            ],
            ["Mission / product / polarization", escape(f"{result['mission']} / {result['product_type']} / {result['polarization']}")],
            ["CRS / pixel size", escape(f"{result['crs']} / {result['pixel_size_m']:.2f} m")],
            [
                "Common valid support",
                f"{result['common_valid_pixel_count']:,} pixels · {result['common_valid_area_m2']:.2f} m² "
                f"({result['common_valid_fraction']:.2%} of the grid)",
            ],
            [
                "Classification parameters",
                escape(
                    f"{result['filter_method']} · {result['threshold_method']} thresholds "
                    f"{result['earlier_threshold_db']:.3f} dB → {result['later_threshold_db']:.3f} dB"
                ),
            ],
            ["Candidate water gain", f"{result['candidate_water_gain_area_m2']:.2f} m²"],
            ["Candidate water loss", f"{result['candidate_water_loss_area_m2']:.2f} m²"],
        ]
    table = Table(rows, colWidths=[150, 360], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#18324b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("WORDWRAP", (0, 0), (-1, -1), "CJK"),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    content.extend([table, Spacer(1, 12), Paragraph("Limitations", styles["Heading2"])])
    content.extend(
        Paragraph(f"- {escape(caveat)}", styles["BodyText"])
        for caveat in result.get("caveats", [])
    )
    content.extend(
        [
            Spacer(1, 12),
            Paragraph(
                "Satellite metadata and processing declarations are not independently verified. "
                "This report does not establish riverbank locations, erosion, deposition, flood extent, "
                "or scientific accuracy.",
                styles["BodyText"],
            ),
        ]
    )
    document.build(content)
    stream.seek(0)
    return stream
