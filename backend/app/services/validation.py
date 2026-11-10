import json
import hashlib
import math
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from contextlib import ExitStack, closing, contextmanager
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Iterator, Literal

import numpy as np

from app.schemas.validation import (
    ExploratoryMethodMetadata,
    ExploratoryMethodResult,
    EvaluationTransition,
    MethodCandidate,
    MethodEvaluationMetadata,
    MethodEvaluationResult,
    PairwiseComparison,
    ReferenceDataImportMetadata,
    ReferenceDataRecord,
    ReferenceDataSource,
    ValidationMetadata,
    ValidationResult,
    ValidationStatus,
    WindowedValidationMetadata,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
VALIDATION_DIR = REPOSITORY_ROOT / "outputs" / "validation"
REFERENCE_DATA_DIR = REPOSITORY_ROOT / "outputs" / "reference-data"
METHOD_EVALUATION_DIR = REPOSITORY_ROOT / "outputs" / "validation" / "method-comparisons"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_RASTER_PIXELS = 2_000_000
COMPARISON_WINDOW_SIZE = 512
MAX_COMPARISON_PIXEL_READS = 5_000_000_000
MAX_COMPARISON_SECONDS = 180
MAX_COMPARISON_BLOCK_PIXELS = 1_048_576
_EXPLORATORY_COMPARISON_LOCK = threading.Lock()
_REVIEWED_WINDOW_LOCK = threading.Lock()
LABEL_VALUES = (0, 1, 255)
_VALIDATION_CAVEATS = [
    "Metrics describe only the submitted labels and common valid raster support.",
    "The application does not independently verify reference provenance, reviewer decisions, sampling design, or label quality.",
    "The result is not a claim of operational or scientific validation outside the submitted reference sample.",
    "Categorical reference labels were resampled to the candidate grid using nearest-neighbour.",
]
REFERENCE_DATA_SOURCES = [
    ReferenceDataSource(
        source_id="jrc-global-surface-water-v1-5",
        name="JRC Global Surface Water 1984–2024",
        provider="European Commission Joint Research Centre",
        source_url="https://global-surface-water.appspot.com/download",
        access_url="https://global-surface-water.appspot.com/download",
        temporal_coverage="1984–2024; monthly history for 2022–2024 in v1.5",
        nominal_resolution_m=30,
        geographic_coverage="Global terrestrial surface-water observation coverage; valid observations vary by location and period.",
        spatial_reference="Inspect the downloaded tile's CRS and geotransform; do not assume one CRS for every delivery.",
        data_format="Raster water occurrence, seasonality, recurrence, and monthly-history layers.",
        access_notes="The official portal provides map/tile downloads and Google Earth Engine access; this application does not fetch tiles.",
        license_status="Copernicus data; free use with required attribution",
        intended_use="Historical or seasonal context; not event-date labels for the 2026 NISAR acquisition.",
        limitation=(
            "Landsat-derived monthly/summary product; v1.5 transitions between Landsat collections. "
            "The provider documents a sparse-observation recurrence issue."
        ),
    ),
    ReferenceDataSource(
        source_id="usgs-landsat-collection-2-level-2",
        name="Landsat Collection 2 Level-2 Surface Reflectance",
        provider="USGS EROS",
        source_url="https://www.usgs.gov/landsat-missions/landsat-collection-2-surface-reflectance",
        access_url="https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2",
        temporal_coverage="Per-scene acquisitions; scene-specific dates and QA required",
        nominal_resolution_m=30,
        geographic_coverage="Global land scene archive; individual scene footprints and clear-pixel coverage vary.",
        spatial_reference="Scene-specific CRS/UTM zone in product metadata; inspect each asset before reprojection.",
        data_format="Level-2 surface-reflectance and QA rasters, commonly distributed as GeoTIFF/COG assets.",
        access_notes="USGS describes the product; the linked STAC collection exposes scene metadata and cloud-optimized assets.",
        license_status="USGS Landsat products have no use restrictions; cite the product",
        intended_use="Potential basis for independently reviewed manual labels when clear, aligned, and temporally suitable.",
        limitation=(
            "Optical labels require per-pixel cloud/cirrus/shadow/snow/saturation screening and human review; "
            "the previously inspected sample was unsuitable."
        ),
    ),
    ReferenceDataSource(
        source_id="nwic-cwc-river-network",
        name="CWC River Network",
        provider="Central Water Commission / National Water Informatics Centre, Government of India",
        source_url="https://nwdp.nwic.gov.in/dataset/river-line/resource/6e552705-842d-40a4-92b2-8506bb66df2a",
        access_url="https://nwdp.nwic.gov.in/dataset/3209962f-d0ff-45b8-910a-209bf69a0ccf/resource/6e552705-842d-40a4-92b2-8506bb66df2a/download/river_network.geojson",
        temporal_coverage="Dataset resource updated 2025-11-17; no event-date label period",
        nominal_resolution_m=None,
        geographic_coverage="India river-network coverage; target-river feature identity and local fit require inspection.",
        spatial_reference="Not verified from the resource landing page; inspect the downloaded vector metadata.",
        data_format="GeoJSON river-line vector; feature identity, CRS and geometry completeness require inspection.",
        access_notes=(
            "The direct resource returned application/geo+json and advertised 356,234,820 bytes by HTTP HEAD "
            "on 2026-11-09; this application does not download it. Confirm redistribution terms."
        ),
        license_status="Portal lists 'Other (Open)'; verify applicable terms before redistribution",
        intended_use="Candidate river-network/axis reference for manual reach-level review, not bank labels.",
        limitation=(
            "Portal describes a linear representation of river paths; it does not certify active channel axes, "
            "wetted banks, or event-date location accuracy."
        ),
    ),
    ReferenceDataSource(
        source_id="hydrorivers-v1",
        name="HydroRIVERS v1.0",
        provider="HydroSHEDS / WWF / McGill University",
        source_url="https://www.hydrosheds.org/products/hydrorivers",
        access_url="https://www.hydrosheds.org/products/hydrorivers",
        temporal_coverage="Static network delineation from HydroSHEDS elevation-derived data",
        nominal_resolution_m=500,
        geographic_coverage="Global river network; documented regional exclusions and minimum drainage-area thresholds apply.",
        spatial_reference="HydroRIVERS vectors use geographic coordinates in the published product; verify the downloaded file metadata.",
        data_format="Vector river network derived from HydroSHEDS flow direction and accumulation grids.",
        access_notes="The product page links regional downloads and technical documentation.",
        license_status="Check current HydroSHEDS terms and attribution before use",
        intended_use="Regional hydrographic topology and broad network context.",
        limitation=(
            "Derived from a 15 arc-second (~500 m at equator) grid; too coarse to serve as a 10 m channel axis "
            "or bank reference."
        ),
    ),
    ReferenceDataSource(
        source_id="grwl-v1-01",
        name="Global River Widths from Landsat (GRWL) v1.01",
        provider="Allen and Pavelsky",
        source_url="https://zenodo.org/records/1269595",
        access_url="https://zenodo.org/records/1269595",
        temporal_coverage="Static product; source acquisitions span multiple Landsat missions and dates",
        nominal_resolution_m=30,
        geographic_coverage="Global river reaches meeting the product's Landsat mapping criteria; reach availability is not universal.",
        spatial_reference="Inspect the specific raster/vector asset metadata; do not infer the NISAR grid CRS.",
        data_format="Landsat-derived river mask and width products distributed as raster/vector data.",
        access_notes="The Zenodo record provides versioned files and documentation; inspect license and metadata per asset.",
        license_status="See the Zenodo record and cited product terms",
        intended_use="Potential broad-scale historical width context after local reach and acquisition provenance review.",
        limitation=(
            "Landsat-derived fixed-discharge widths are not event-date labels or current NISAR bank geometry; "
            "regional availability and local fit must be verified before interpretation."
        ),
    ),
]


class ValidationUnavailable(RuntimeError):
    pass


class ComparisonBusy(RuntimeError):
    pass


def _rasterio() -> Any:
    try:
        import rasterio
    except ImportError as error:
        raise ValidationUnavailable("Raster validation requires Rasterio.") from error
    return rasterio


def _read_mask(raster_bytes: bytes, label: str):
    rasterio = _rasterio()
    try:
        with rasterio.io.MemoryFile(raster_bytes) as memory_file:
            with memory_file.open() as dataset:
                if dataset.count != 1:
                    raise ValueError(f"{label} GeoTIFF must contain exactly one band.")
                if dataset.width * dataset.height > MAX_RASTER_PIXELS:
                    raise ValueError(
                        f"{label} raster exceeds the {MAX_RASTER_PIXELS:,}-pixel limit."
                    )
                if dataset.crs is None or dataset.transform is None:
                    raise ValueError(f"{label} GeoTIFF must include a CRS and geotransform.")
                if (
                    not np.isfinite(dataset.transform[:6]).all()
                    or dataset.transform.a * dataset.transform.e
                    - dataset.transform.b * dataset.transform.d == 0
                ):
                    raise ValueError(f"{label} GeoTIFF has an invalid geotransform.")
                values = dataset.read(1)
                valid_mask = dataset.read_masks(1) != 0
                if not np.isin(values[valid_mask], LABEL_VALUES).all():
                    raise ValueError(f"{label} raster labels must be 0, 1, or 255.")
                if np.issubdtype(values.dtype, np.floating) and not np.isfinite(values[valid_mask]).all():
                    raise ValueError(f"{label} raster contains non-finite labels.")
                values = np.where(valid_mask, values, 255)
                return values.astype(np.uint8, copy=False), dataset.profile.copy(), dataset.crs
    except rasterio.errors.RasterioError as error:
        raise ValueError(f"Unable to read the {label} GeoTIFF: {error}") from error


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".validation-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, indent=2)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def _meets_evidence_thresholds(
    count: int, coverage: float, minimum_pixels: int | None, minimum_coverage: float | None,
    minimum_per_class: int | None, block_size: int | None, minimum_blocks: int | None,
    class_counts: dict[str, int] | None, block_counts: dict[str, int] | None,
) -> bool:
    return (
        minimum_pixels is not None
        and minimum_pixels >= 2
        and minimum_coverage is not None
        and 0 < minimum_coverage <= 1
        and count >= minimum_pixels
        and coverage >= minimum_coverage
        and minimum_per_class is not None
        and minimum_per_class >= 1
        and block_size is not None
        and block_size >= 1
        and minimum_blocks is not None
        and minimum_blocks >= 1
        and class_counts is not None
        and block_counts is not None
        and all(class_counts.get(label, 0) >= minimum_per_class for label in ("0", "1"))
        and all(block_counts.get(label, 0) >= minimum_blocks for label in ("0", "1"))
    )


def _read_validation_report(path: Path) -> ValidationResult:
    result = ValidationResult.model_validate_json(path.read_text(encoding="utf-8"))
    if result.status == "validation_completed" and not _meets_evidence_thresholds(
        result.common_valid_pixel_count, result.valid_reference_coverage_fraction,
        result.minimum_common_pixels, result.minimum_coverage_fraction,
        result.minimum_pixels_per_class, result.spatial_block_size_pixels,
        result.minimum_blocks_per_class, result.reference_class_counts,
        result.reference_class_block_counts,
    ):
        return result.model_copy(update={
            "status": "insufficient_evidence",
            "precision": None,
            "recall": None,
            "f1_score": None,
            "intersection_over_union": None,
            "overall_agreement": None,
            "warnings": [*result.warnings, "Stored report lacks qualifying evidence thresholds; accuracy metrics are withheld."],
        })
    return result


def list_validation_reports() -> list[ValidationResult]:
    if not VALIDATION_DIR.exists():
        return []
    return [get_validation_report(path.parent.name) for path in sorted(VALIDATION_DIR.glob("*/result.json"), reverse=True)]


def validation_status() -> ValidationStatus:
    reports = list_validation_reports()
    if any(report.status == "validation_completed" for report in reports):
        return ValidationStatus(
            status="validation_completed",
            message="Validation reports exist for submitted reference datasets.",
            reports=reports[:25],
        )
    if list_reference_data():
        return ValidationStatus(
            status="reference_dataset_available",
            message=(
                "User-imported reviewed reference rasters are available. Their suitability, "
                "independence, and review quality are not authenticated; no completed validation "
                "report currently meets the evidence requirements."
            ),
            reports=reports[:25],
        )
    if any(report.status == "thresholds_met_awaiting_evaluation" for report in reports):
        return ValidationStatus(
            status="reference_dataset_available",
            message="A submitted assessment meets its declared thresholds and awaits evaluation; review and provenance are not authenticated.",
            reports=reports[:25],
        )
    return ValidationStatus(
        status="validation_pending",
        message=(
            "Independent scientific validation pending. Submitted reports did not meet the "
            "evidence requirements."
            if reports
            else "Independent scientific validation pending. No suitable reviewed reference labels "
            "are currently available."
        ),
        reports=reports[:25],
    )


def reference_data_sources() -> list[ReferenceDataSource]:
    return list(REFERENCE_DATA_SOURCES)


def _reference_record(reference_id: str) -> ReferenceDataRecord:
    try:
        normalized_id = str(uuid.UUID(reference_id))
    except ValueError as error:
        raise ValueError("Invalid reference-data identifier.") from error
    directory = (REFERENCE_DATA_DIR / normalized_id).resolve()
    if not directory.is_relative_to(REFERENCE_DATA_DIR.resolve()):
        raise ValueError("Reference-data path is outside the configured directory.")
    metadata_path = (directory / "metadata.json").resolve()
    if not metadata_path.is_relative_to(directory) or not metadata_path.is_file():
        raise FileNotFoundError(f"Reference dataset {normalized_id} was not found.")
    record = ReferenceDataRecord.model_validate_json(metadata_path.read_text(encoding="utf-8"))
    if record.reference_id != normalized_id:
        raise ValueError("Reference-data record identifier does not match its directory.")
    return record


def import_reviewed_reference_data(
    raster_bytes: bytes,
    metadata: ReferenceDataImportMetadata,
) -> ReferenceDataRecord:
    if not metadata.independent_review_completed:
        raise ValueError("Reference data must be independently reviewed before import.")
    if not raster_bytes or len(raster_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError("Reference GeoTIFF must be nonempty and no larger than 100 MB.")
    labels, profile, crs = _read_mask(raster_bytes, "Reference")
    if profile.get("nodata") != 255:
        raise ValueError("Reference GeoTIFF must declare 255 as uncertain/NoData.")
    if not crs.is_projected or crs.linear_units.casefold() not in {"metre", "meter"}:
        raise ValueError("Reference-data CRS must be projected in metres.")
    if crs.to_string() != metadata.crs:
        raise ValueError("Declared reference CRS does not match the GeoTIFF CRS.")
    actual_resolution = min(
        math.hypot(profile["transform"].a, profile["transform"].d),
        math.hypot(profile["transform"].b, profile["transform"].e),
    )
    if not math.isclose(actual_resolution, metadata.resolution_m, rel_tol=0.05):
        raise ValueError("Declared resolution differs from the GeoTIFF resolution by more than 5%.")
    label_counts = {
        str(value): int(count)
        for value, count in zip(*np.unique(labels, return_counts=True))
    }
    if not label_counts.get("0") or not label_counts.get("1"):
        raise ValueError("Reviewed reference raster must contain both water (1) and non-water (0) labels.")
    reference_id = str(uuid.uuid4())
    output_directory = REFERENCE_DATA_DIR / reference_id
    output_directory.mkdir(parents=True, exist_ok=False)
    labels_path = output_directory / "reference-labels.tif"
    record = ReferenceDataRecord(
        reference_id=reference_id,
        metadata=metadata,
        width=profile["width"],
        height=profile["height"],
        label_counts=label_counts,
        nodata_value=255,
        review_attestation=(
            "Reviewer attestation recorded; source independence and label quality are not "
            "independently authenticated by this application."
        ),
        labels_url=f"/api/analysis/reference-data/{reference_id}/labels",
    )
    try:
        labels_path.write_bytes(raster_bytes)
        _atomic_json(output_directory / "metadata.json", record.model_dump(mode="json"))
    except Exception:
        for path in output_directory.iterdir():
            path.unlink()
        output_directory.rmdir()
        raise
    return record


def list_reference_data() -> list[ReferenceDataRecord]:
    if not REFERENCE_DATA_DIR.exists():
        return []
    records: list[ReferenceDataRecord] = []
    for metadata_path in sorted(REFERENCE_DATA_DIR.glob("*/metadata.json"), reverse=True):
        records.append(_reference_record(metadata_path.parent.name))
    return records[:100]


def reference_data_labels_path(reference_id: str) -> tuple[Path, ReferenceDataRecord]:
    record = _reference_record(reference_id)
    path = (REFERENCE_DATA_DIR / record.reference_id / "reference-labels.tif").resolve()
    if not path.is_relative_to(REFERENCE_DATA_DIR.resolve()) or not path.is_file():
        raise FileNotFoundError(f"Reference labels for {record.reference_id} were not found.")
    return path, record


def _reference_distribution(
    reference: np.ndarray, shared: np.ndarray, block_size: int | None,
) -> tuple[dict[str, int], dict[str, int] | None]:
    counts = {str(label): int(np.count_nonzero(shared & (reference == label))) for label in (0, 1)}
    if block_size is None:
        return counts, None
    blocks = {}
    for label in (0, 1):
        rows, columns = np.nonzero(shared & (reference == label))
        block_columns = (reference.shape[1] + block_size - 1) // block_size
        blocks[str(label)] = int(np.unique((rows // block_size) * block_columns + columns // block_size).size)
    return counts, blocks


def _evidence_sufficient(
    metadata: ValidationMetadata, count: int, coverage: float,
    class_counts: dict[str, int], block_counts: dict[str, int] | None,
) -> bool:
    return _meets_evidence_thresholds(
        count, coverage, metadata.minimum_common_pixels, metadata.minimum_coverage_fraction,
        metadata.minimum_pixels_per_class, metadata.spatial_block_size_pixels,
        metadata.minimum_blocks_per_class, class_counts, block_counts,
    )


def _read_candidate_grids(
    candidate_rasters: list[bytes],
) -> tuple[list[tuple[np.ndarray, dict[str, Any], Any]], float]:
    if any(not raster or len(raster) > MAX_UPLOAD_BYTES for raster in candidate_rasters):
        raise ValueError("Each method GeoTIFF must be nonempty and no larger than 100 MB.")
    candidates = [_read_mask(raster, "Candidate method") for raster in candidate_rasters]
    base_values, base_profile, base_crs = candidates[0]
    if not base_crs.is_projected or base_crs.linear_units.casefold() not in {"metre", "meter"}:
        raise ValueError("Candidate method CRS must be projected in metres.")
    grid_key = (base_values.shape, base_profile["transform"], base_crs)
    for values, profile, crs in candidates:
        if profile.get("nodata") != 255:
            raise ValueError("Every candidate method GeoTIFF must declare 255 as NoData.")
        if (values.shape, profile["transform"], crs) != grid_key:
            raise ValueError(
                "Candidate method rasters must share exactly the same dimensions, transform, and CRS."
            )
    pixel_area = abs(
        base_profile["transform"].a * base_profile["transform"].e
        - base_profile["transform"].b * base_profile["transform"].d
    )
    if not math.isfinite(pixel_area) or pixel_area <= 0:
        raise ValueError("Candidate method rasters have invalid pixel area.")
    return candidates, pixel_area


def _candidate_summaries(
    candidates: list[tuple[np.ndarray, dict[str, Any], Any]],
    shared: np.ndarray,
    pixel_area: float,
) -> list[dict[str, Any]]:
    count = int(np.count_nonzero(shared))
    baseline = candidates[0][0]
    summaries = []
    for values, _, _ in candidates:
        candidate_pixels = int(np.count_nonzero(shared & (values == 1)))
        different_pixels = int(np.count_nonzero(shared & (values != baseline)))
        summaries.append({
            "candidate_pixel_count": candidate_pixels if count else None,
            "candidate_area_m2": candidate_pixels * pixel_area if count else None,
            "difference_from_first_pixel_count": different_pixels if count else None,
            "difference_from_first_area_m2": different_pixels * pixel_area if count else None,
        })
    return summaries


def _pairwise_comparisons(
    candidates: list[tuple[np.ndarray, dict[str, Any], Any]],
    methods: list[MethodCandidate],
    shared: np.ndarray,
    pixel_area: float,
) -> list[PairwiseComparison]:
    count = int(np.count_nonzero(shared))
    pairs = []
    for first in range(len(candidates)):
        for second in range(first + 1, len(candidates)):
            a = shared & (candidates[first][0] == 1)
            b = shared & (candidates[second][0] == 1)
            a_count = int(np.count_nonzero(a))
            b_count = int(np.count_nonzero(b))
            intersection = int(np.count_nonzero(a & b))
            union = int(np.count_nonzero(a | b))
            disagreement = int(np.count_nonzero(a ^ b))
            pairs.append(PairwiseComparison(
                first_method_id=methods[first].method_id,
                second_method_id=methods[second].method_id,
                absolute_area_difference_m2=abs(a_count - b_count) * pixel_area if count else None,
                area_difference_fraction_of_first=abs(a_count - b_count) / a_count if count and a_count else None,
                disagreement_pixel_count=disagreement if count else None,
                disagreement_fraction=disagreement / count if count else None,
                intersection_over_union=intersection / union if count and union else None,
            ))
    return pairs


def compare_exploratory_methods(
    candidate_rasters: list[bytes],
    metadata: ExploratoryMethodMetadata,
) -> ExploratoryMethodResult:
    if not _EXPLORATORY_COMPARISON_LOCK.acquire(blocking=False):
        raise ComparisonBusy("An exploratory comparison is already running in this server process.")
    try:
        return _compare_exploratory_methods_windowed(candidate_rasters, metadata)
    finally:
        _EXPLORATORY_COMPARISON_LOCK.release()


def _compare_exploratory_methods_windowed(
    candidate_rasters: list[bytes],
    metadata: ExploratoryMethodMetadata,
) -> ExploratoryMethodResult:
    if len(candidate_rasters) != len(metadata.methods):
        raise ValueError("Provide exactly one candidate GeoTIFF for each declared method.")
    if any(not raster or len(raster) > MAX_UPLOAD_BYTES for raster in candidate_rasters):
        raise ValueError("Each method GeoTIFF must be nonempty and no larger than 100 MB.")
    rasterio = _rasterio()
    from rasterio.windows import Window

    start = time.monotonic()
    with ExitStack() as stack:
        stack.enter_context(rasterio.Env(GDAL_CACHEMAX=64_000_000))
        try:
            datasets = []
            for content in candidate_rasters:
                memory = stack.enter_context(rasterio.io.MemoryFile(content))
                datasets.append(stack.enter_context(memory.open()))
            base = datasets[0]
            base_crs = base.crs
            affine = base.transform
            if base_crs is None or not base_crs.is_projected or base_crs.linear_units.casefold() not in {"metre", "meter"}:
                raise ValueError("Candidate method CRS must be projected in metres.")
            if not np.isfinite(affine[:6]).all() or not math.isfinite(affine.a * affine.e - affine.b * affine.d) or abs(affine.a * affine.e - affine.b * affine.d) <= 0:
                raise ValueError("Candidate method rasters have invalid pixel area or transform.")
            pixel_area = abs(affine.a * affine.e - affine.b * affine.d)
            offsets = []
            for dataset in datasets:
                if dataset.count != 1 or dataset.nodata != 255:
                    raise ValueError("Every candidate method GeoTIFF must contain one band and declare 255 as NoData.")
                if dataset.dtypes[0] != "uint8":
                    raise ValueError("Windowed candidate masks must use uint8 labels.")
                if dataset.block_shapes[0][0] * dataset.block_shapes[0][1] > MAX_COMPARISON_BLOCK_PIXELS:
                    raise ValueError("Candidate raster storage blocks exceed the safe windowed comparison limit.")
                transform = dataset.transform
                if not np.isfinite(transform[:6]).all() or not math.isfinite(transform.a * transform.e - transform.b * transform.d) or abs(transform.a * transform.e - transform.b * transform.d) <= 0:
                    raise ValueError("Candidate method rasters have invalid pixel area or transform.")
                if dataset.crs != base_crs or (transform.a, transform.b, transform.d, transform.e) != (affine.a, affine.b, affine.d, affine.e):
                    raise ValueError("Candidate method rasters must share exactly the same CRS and pixel basis; resampling is not supported.")
                col, row = (~affine) @ (transform.c, transform.f)
                if not math.isfinite(col) or not math.isfinite(row):
                    raise ValueError("Candidate method rasters have invalid grid offsets.")
                if not math.isclose(col, round(col), rel_tol=0, abs_tol=1e-7) or not math.isclose(row, round(row), rel_tol=0, abs_tol=1e-7):
                    raise ValueError("Candidate method rasters must share exactly the same pixel alignment.")
                offsets.append((round(col), round(row)))

            left = max(offset[0] for offset in offsets)
            top = max(offset[1] for offset in offsets)
            right = min(offset[0] + ds.width for offset, ds in zip(offsets, datasets))
            bottom = min(offset[1] + ds.height for offset, ds in zip(offsets, datasets))
            width, height = max(0, right - left), max(0, bottom - top)
            if width * height * len(datasets) > MAX_COMPARISON_PIXEL_READS:
                raise ValueError("Comparison exceeds the safe pixel-read limit.")
            candidate_counts = [0] * len(datasets)
            different_counts = [0] * len(datasets)
            intersections = {(i, j): 0 for i in range(len(datasets)) for j in range(i + 1, len(datasets))}
            disagreements = dict.fromkeys(intersections, 0)
            count = 0
            windows = 0
            rows = range(top, bottom, COMPARISON_WINDOW_SIZE) if width and height else ()
            for row in rows:
                for col in range(left, right, COMPARISON_WINDOW_SIZE):
                    if time.monotonic() - start > MAX_COMPARISON_SECONDS:
                        raise ValueError("Comparison exceeded the processing time limit; no result was produced.")
                    window_width = min(COMPARISON_WINDOW_SIZE, right - col)
                    window_height = min(COMPARISON_WINDOW_SIZE, bottom - row)
                    arrays = []
                    shared = np.ones((window_height, window_width), dtype=bool)
                    for dataset, (offset_col, offset_row) in zip(datasets, offsets):
                        window = Window(col - offset_col, row - offset_row, window_width, window_height)
                        values = dataset.read(1, window=window)
                        valid_mask = dataset.read_masks(1, window=window) != 0
                        if not np.isin(values[valid_mask], LABEL_VALUES).all():
                            raise ValueError("Candidate method raster labels must be 0, 1, or 255.")
                        shared &= valid_mask & (values != 255)
                        arrays.append(values)
                    count += int(np.count_nonzero(shared))
                    masks = [shared & (values == 1) for values in arrays]
                    for index, mask in enumerate(masks):
                        candidate_counts[index] += int(np.count_nonzero(mask))
                        different_counts[index] += int(np.count_nonzero(shared & (arrays[index] != arrays[0])))
                    for i, j in intersections:
                        intersections[i, j] += int(np.count_nonzero(masks[i] & masks[j]))
                        disagreements[i, j] += int(np.count_nonzero(masks[i] ^ masks[j]))
                    windows += 1
            base_pixels = base.width * base.height
            source_grids = [
                {"method_id": method.method_id, "width": dataset.width, "height": dataset.height,
                 "transform": list(dataset.transform[:6]), "column_offset_from_first": offset[0],
                 "row_offset_from_first": offset[1], "nodata": dataset.nodata}
                for method, dataset, offset in zip(metadata.methods, datasets, offsets)
            ]
            if time.monotonic() - start > MAX_COMPARISON_SECONDS:
                raise ValueError("Comparison exceeded the processing time limit; no result was produced.")
        except rasterio.errors.RasterioError as error:
            raise ValueError(f"Unable to read candidate GeoTIFF: {error}") from error

    summaries = [{
        "candidate_pixel_count": n if count else None,
        "candidate_area_m2": n * pixel_area if count else None,
        "difference_from_first_pixel_count": d if count else None,
        "difference_from_first_area_m2": d * pixel_area if count else None,
    } for n, d in zip(candidate_counts, different_counts)]
    pairs = []
    for (i, j), intersection in intersections.items():
        union = candidate_counts[i] + candidate_counts[j] - intersection
        pairs.append(PairwiseComparison(
            first_method_id=metadata.methods[i].method_id,
            second_method_id=metadata.methods[j].method_id,
            absolute_area_difference_m2=abs(candidate_counts[i] - candidate_counts[j]) * pixel_area if count else None,
            area_difference_fraction_of_first=abs(candidate_counts[i] - candidate_counts[j]) / candidate_counts[i] if count and candidate_counts[i] else None,
            disagreement_pixel_count=disagreements[i, j] if count else None,
            disagreement_fraction=disagreements[i, j] / count if count else None,
            intersection_over_union=intersection / union if count and union else None,
        ))
    return ExploratoryMethodResult(
        status="exploratory_comparison" if count else "insufficient_spatial_overlap",
        river_id=metadata.river_id,
        candidate_product_id=metadata.candidate_product_id,
        candidate_acquisition_datetime=metadata.candidate_acquisition_datetime,
        shared_common_valid_pixel_count=count,
        shared_grid_coverage_fraction=count / base_pixels,
        candidate_crs=base_crs.to_string(),
        pixel_area_m2=pixel_area,
        methods=[
            {"method_id": method.method_id, "method_name": method.method_name,
             "parameters": method.parameters, **summary}
            for method, summary in zip(metadata.methods, summaries)
        ],
        pairwise_comparisons=pairs,
        processing={
            "mode": "windowed", "window_width_pixels": COMPARISON_WINDOW_SIZE,
            "window_height_pixels": COMPARISON_WINDOW_SIZE, "windows_processed": windows,
            "overlap_width_pixels": width, "overlap_height_pixels": height,
            "coverage_denominator": "first candidate grid pixels",
            "resampling": "none", "max_pixel_reads": MAX_COMPARISON_PIXEL_READS,
            "time_limit_seconds": MAX_COMPARISON_SECONDS, "source_grids": source_grids,
        },
        warnings=[
            "Exploratory candidate differences on shared valid pixels are not accuracy or validation.",
            "No reference labels were supplied; no method is selected as best.",
            "Pixel alignment does not establish co-registration, source identity, or scientific suitability.",
            "Pairwise IoU and disagreement compare candidates only; they are not accuracy. Percentage area difference uses the first method as denominator.",
        ],
    )


def assess_windowed_masks(
    candidate_bytes: bytes,
    reference_bytes: bytes,
    metadata: WindowedValidationMetadata,
) -> ValidationResult:
    if not metadata.independent_review_completed:
        raise ValueError("A review and independence attestation is required for this assessment.")
    if not candidate_bytes or not reference_bytes or len(candidate_bytes) + len(reference_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError("Combined candidate and reference GeoTIFFs must be nonempty and no larger than 100 MB.")
    if not _REVIEWED_WINDOW_LOCK.acquire(blocking=False):
        raise ComparisonBusy("A reviewed windowed comparison is already running in this server process.")
    try:
        return _assess_windowed_masks(candidate_bytes, reference_bytes, metadata)
    finally:
        _REVIEWED_WINDOW_LOCK.release()


def _assess_windowed_masks(
    candidate_bytes: bytes,
    reference_bytes: bytes,
    metadata: WindowedValidationMetadata,
) -> ValidationResult:
    result = _calculate_windowed_masks(candidate_bytes, reference_bytes, metadata)
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    output_directory = VALIDATION_DIR / result.validation_id
    output_directory.mkdir(parents=True, exist_ok=False)
    _atomic_json(output_directory / "result.json", result.model_dump(mode="json"))
    return result


def _calculate_windowed_masks(
    candidate_bytes: bytes,
    reference_bytes: bytes,
    metadata: WindowedValidationMetadata,
) -> ValidationResult:
    rasterio = _rasterio()
    from rasterio.windows import Window

    start = time.monotonic()
    with ExitStack() as stack:
        stack.enter_context(rasterio.Env(GDAL_CACHEMAX=64_000_000))
        try:
            datasets = []
            for content in (candidate_bytes, reference_bytes):
                memory = stack.enter_context(rasterio.io.MemoryFile(content))
                datasets.append(stack.enter_context(memory.open()))
            candidate, reference = datasets
            crs, transform = candidate.crs, candidate.transform
            determinant = transform.a * transform.e - transform.b * transform.d
            if crs is None or not crs.is_projected or crs.linear_units.casefold() not in {"metre", "meter"}:
                raise ValueError("Candidate raster CRS must be projected in metres.")
            if not np.isfinite(transform[:6]).all() or not math.isfinite(determinant) or determinant == 0:
                raise ValueError("Candidate raster has an invalid transform.")
            for raster in datasets:
                if raster.count != 1 or raster.nodata != 255 or raster.dtypes[0] != "uint8":
                    raise ValueError("Both GeoTIFFs must have one uint8 band and declare 255 as NoData.")
                if raster.block_shapes[0][0] * raster.block_shapes[0][1] > MAX_COMPARISON_BLOCK_PIXELS:
                    raise ValueError("Raster storage blocks exceed the safe windowed comparison limit.")
                if (raster.width, raster.height, raster.crs, raster.transform) != (
                    candidate.width, candidate.height, crs, transform
                ):
                    raise ValueError("Windowed reviewed rasters must share exactly the same dimensions, CRS, and transform; no resampling is performed.")
            resolution = min(math.hypot(transform.a, transform.d), math.hypot(transform.b, transform.e))
            if not math.isclose(resolution, metadata.reference_resolution_m, rel_tol=0.05):
                raise ValueError("Declared reference resolution differs from the raster grid by more than 5%.")
            if candidate.width * candidate.height * 2 > MAX_COMPARISON_PIXEL_READS:
                raise ValueError("Comparison exceeds the safe pixel-read limit.")
            block_size = metadata.spatial_block_size_pixels
            block_cols = (candidate.width + block_size - 1) // block_size if block_size else 0
            block_rows = (candidate.height + block_size - 1) // block_size if block_size else 0
            if block_rows * block_cols > MAX_RASTER_PIXELS:
                raise ValueError("Spatial distribution exceeds the two-million-block safety limit; choose a larger declared block size.")
            occupied = [np.zeros(block_rows * block_cols, dtype=bool) for _ in range(2)] if block_size else None
            candidate_count = reference_count = common_count = 0
            tp = tn = fp = fn = windows = 0
            for row in range(0, candidate.height, COMPARISON_WINDOW_SIZE):
                for col in range(0, candidate.width, COMPARISON_WINDOW_SIZE):
                    if time.monotonic() - start > MAX_COMPARISON_SECONDS:
                        raise ValueError("Comparison exceeded the processing time limit; no assessment was produced.")
                    window = Window(col, row, min(COMPARISON_WINDOW_SIZE, candidate.width-col), min(COMPARISON_WINDOW_SIZE, candidate.height-row))
                    values = [r.read(1, window=window) for r in datasets]
                    masks = [r.read_masks(1, window=window) != 0 for r in datasets]
                    for array, mask in zip(values, masks):
                        if not np.isin(array[mask], LABEL_VALUES).all():
                            raise ValueError("Raster labels must be 0, 1, or 255.")
                    c, r = values
                    cv = masks[0] & (c != 255)
                    rv = masks[1] & (r != 255)
                    shared = cv & rv
                    candidate_count += int(np.count_nonzero(cv))
                    reference_count += int(np.count_nonzero(rv))
                    common_count += int(np.count_nonzero(shared))
                    tp += int(np.count_nonzero(shared & (c == 1) & (r == 1)))
                    tn += int(np.count_nonzero(shared & (c == 0) & (r == 0)))
                    fp += int(np.count_nonzero(shared & (c == 1) & (r == 0)))
                    fn += int(np.count_nonzero(shared & (c == 0) & (r == 1)))
                    if occupied is not None and block_size is not None:
                        for label in (0, 1):
                            rr, cc = np.nonzero(shared & (r == label))
                            ids = ((rr + row) // block_size) * block_cols + (cc + col) // block_size
                            occupied[label][ids] = True
                    windows += 1
            if time.monotonic() - start > MAX_COMPARISON_SECONDS:
                raise ValueError("Comparison exceeded the processing time limit; no assessment was produced.")
            width, height = candidate.width, candidate.height
            crs_string = crs.to_string()
            grid_transform = list(transform[:6])
        except rasterio.errors.RasterioError as error:
            raise ValueError(f"Unable to read submitted GeoTIFF: {error}") from error

    class_counts = {"0": tn + fp, "1": tp + fn}
    block_counts = {str(label): int(np.count_nonzero(occupied[label])) for label in (0, 1)} if occupied is not None else None
    coverage = common_count / candidate_count if candidate_count else 0.0
    if not common_count:
        status = "insufficient_spatial_overlap"
    elif not all(class_counts.values()):
        status = "insufficient_valid_labels"
    elif not _evidence_sufficient(metadata, common_count, coverage, class_counts, block_counts):
        status = "insufficient_evidence"
    else:
        status = "thresholds_met_awaiting_evaluation"
    result_id = str(uuid.uuid4())
    result = ValidationResult(
        validation_id=result_id, status=status, river_id=metadata.river_id,
        candidate_product_id=metadata.candidate_product_id, candidate_sensor=metadata.candidate_sensor,
        candidate_acquisition_datetime=metadata.candidate_acquisition_datetime,
        reference_dataset_id=metadata.reference_dataset_id, reference_provider=metadata.reference_provider,
        reference_acquisition_datetime=metadata.reference_acquisition_datetime,
        reference_resolution_m=metadata.reference_resolution_m, reference_crs=crs_string, candidate_crs=crs_string,
        reviewer=metadata.reviewer, review_date=metadata.review_date,
        independent_review_completed=metadata.independent_review_completed,
        reference_methodology=metadata.reference_methodology, limitations=metadata.limitations,
        confusion_matrix={"true_positive": tp, "true_negative": tn, "false_positive": fp, "false_negative": fn} if common_count else None,
        candidate_valid_pixel_count=candidate_count, reference_valid_pixel_count_on_candidate_grid=reference_count,
        common_valid_pixel_count=common_count, valid_reference_coverage_fraction=coverage,
        minimum_common_pixels=metadata.minimum_common_pixels, minimum_coverage_fraction=metadata.minimum_coverage_fraction,
        minimum_pixels_per_class=metadata.minimum_pixels_per_class, spatial_block_size_pixels=block_size,
        minimum_blocks_per_class=metadata.minimum_blocks_per_class, reference_class_counts=class_counts,
        reference_class_block_counts=block_counts, pixel_area_m2=abs(determinant), resampling="none",
        candidate_processing_version=metadata.candidate_processing_version,
        processing={"mode": "windowed", "window_pixels": COMPARISON_WINDOW_SIZE, "windows_processed": windows,
                    "width": width, "height": height, "transform": grid_transform,
                    "candidate_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
                    "reference_sha256": hashlib.sha256(reference_bytes).hexdigest()},
        report_url=f"/api/analysis/validation/{result_id}",
        warnings=["Review and independence are operator attestations, not authenticated facts.",
                  "Candidate identity and processing version are operator-declared; applicability is not authenticated.",
                  "Occupied blocks and thresholds do not establish representativeness or scientific validity."],
    )
    return result


def compare_independent_masks(
    candidate_bytes: bytes,
    reference_bytes: bytes,
    metadata: ValidationMetadata,
) -> ValidationResult:
    if not metadata.independent_review_completed:
        raise ValueError("Independent reviewer attestation is required before calculating metrics.")
    if not candidate_bytes or len(candidate_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError("Candidate GeoTIFF must be nonempty and no larger than 100 MB.")
    if not reference_bytes or len(reference_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError("Reference GeoTIFF must be nonempty and no larger than 100 MB.")

    rasterio = _rasterio()
    candidate, candidate_profile, candidate_crs = _read_mask(candidate_bytes, "Candidate")
    reference, reference_profile, reference_crs = _read_mask(reference_bytes, "Reference")
    if candidate_profile.get("nodata") != 255:
        raise ValueError("Candidate GeoTIFF must declare 255 as NoData.")
    if reference_profile.get("nodata") != 255:
        raise ValueError("Reference GeoTIFF must declare 255 as uncertain/NoData.")
    if not candidate_crs.is_projected or candidate_crs.linear_units.casefold() not in {
        "metre",
        "meter",
    }:
        raise ValueError("Candidate raster CRS must be projected in metres.")
    pixel_area = abs(
        candidate_profile["transform"].a * candidate_profile["transform"].e
        - candidate_profile["transform"].b * candidate_profile["transform"].d
    )
    if not math.isfinite(pixel_area) or pixel_area <= 0:
        raise ValueError("Candidate raster has invalid pixel area.")

    aligned_reference = np.full(candidate.shape, 255, dtype=np.uint8)
    from rasterio.warp import reproject

    reproject(
        source=reference,
        destination=aligned_reference,
        src_transform=reference_profile["transform"],
        src_crs=reference_crs,
        src_nodata=255,
        dst_transform=candidate_profile["transform"],
        dst_crs=candidate_crs,
        dst_nodata=255,
        resampling=rasterio.enums.Resampling.nearest,
        init_dest_nodata=True,
    )

    candidate_valid = np.isin(candidate, (0, 1))
    reference_valid = np.isin(aligned_reference, (0, 1))
    common = candidate_valid & reference_valid
    candidate_count = int(np.count_nonzero(candidate_valid))
    reference_count = int(np.count_nonzero(reference_valid))
    common_count = int(np.count_nonzero(common))
    coverage = common_count / candidate_count if candidate_count else 0.0
    class_counts, block_counts = _reference_distribution(aligned_reference, common, metadata.spatial_block_size_pixels)
    tp = int(np.count_nonzero(common & (candidate == 1) & (aligned_reference == 1)))
    tn = int(np.count_nonzero(common & (candidate == 0) & (aligned_reference == 0)))
    fp = int(np.count_nonzero(common & (candidate == 1) & (aligned_reference == 0)))
    fn = int(np.count_nonzero(common & (candidate == 0) & (aligned_reference == 1)))

    if common_count == 0:
        status = "insufficient_spatial_overlap"
    elif not np.any(aligned_reference[common] == 0) or not np.any(
        aligned_reference[common] == 1
    ):
        status = "insufficient_valid_labels"
    elif not _evidence_sufficient(metadata, common_count, coverage, class_counts, block_counts):
        status = "insufficient_evidence"
    else:
        status = "validation_completed"

    precision_denominator = tp + fp
    recall_denominator = tp + fn
    union = tp + fp + fn
    precision = tp / precision_denominator if precision_denominator else None
    recall = tp / recall_denominator if recall_denominator else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    iou = tp / union if union else None
    result_id = str(uuid.uuid4())
    report_url = f"/api/analysis/validation/{result_id}"
    result = ValidationResult(
        validation_id=result_id,
        status=status,
        river_id=metadata.river_id,
        candidate_product_id=metadata.candidate_product_id,
        candidate_sensor=metadata.candidate_sensor,
        candidate_acquisition_datetime=metadata.candidate_acquisition_datetime,
        reference_dataset_id=metadata.reference_dataset_id,
        reference_provider=metadata.reference_provider,
        reference_acquisition_datetime=metadata.reference_acquisition_datetime,
        reference_resolution_m=metadata.reference_resolution_m,
        reference_crs=reference_crs.to_string(),
        candidate_crs=candidate_crs.to_string(),
        reviewer=metadata.reviewer,
        review_date=metadata.review_date,
        independent_review_completed=metadata.independent_review_completed,
        reference_methodology=metadata.reference_methodology,
        limitations=metadata.limitations,
        confusion_matrix=(
            {"true_positive": tp, "true_negative": tn, "false_positive": fp, "false_negative": fn}
            if common_count
            else None
        ),
        precision=precision if status == "validation_completed" else None,
        recall=recall if status == "validation_completed" else None,
        f1_score=f1 if status == "validation_completed" else None,
        intersection_over_union=iou if status == "validation_completed" else None,
        candidate_valid_pixel_count=candidate_count,
        reference_valid_pixel_count_on_candidate_grid=reference_count,
        common_valid_pixel_count=common_count,
        valid_reference_coverage_fraction=coverage,
        minimum_common_pixels=metadata.minimum_common_pixels,
        minimum_coverage_fraction=metadata.minimum_coverage_fraction,
        minimum_pixels_per_class=metadata.minimum_pixels_per_class,
        spatial_block_size_pixels=metadata.spatial_block_size_pixels,
        minimum_blocks_per_class=metadata.minimum_blocks_per_class,
        reference_class_counts=class_counts,
        reference_class_block_counts=block_counts,
        pixel_area_m2=pixel_area,
        resampling="nearest",
        report_url=report_url,
        warnings=[*_VALIDATION_CAVEATS, "Operator-declared thresholds do not establish sample representativeness or scientific validity."],
    )
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    output_directory = VALIDATION_DIR / result_id
    output_directory.mkdir(parents=True, exist_ok=False)
    try:
        _atomic_json(output_directory / "result.json", result.model_dump(mode="json"))
    except Exception:
        output_directory.rmdir()
        raise
    return result


def get_validation_report(validation_id: str) -> ValidationResult:
    try:
        normalized_id = str(uuid.UUID(validation_id))
    except ValueError as error:
        raise ValueError("Invalid validation identifier.") from error
    path = (VALIDATION_DIR / normalized_id / "result.json").resolve()
    if not path.is_relative_to(VALIDATION_DIR.resolve()) or not path.is_file():
        raise FileNotFoundError(f"Validation report {normalized_id} was not found.")
    result = _read_validation_report(path)
    if result.validation_id != normalized_id:
        raise ValueError("Validation report identifier does not match its directory.")
    return result


@contextmanager
def _assessment_transition_lock() -> Iterator[None]:
    if not _REVIEWED_WINDOW_LOCK.acquire(blocking=False):
        raise ComparisonBusy("A reviewed windowed comparison is already running in this server process.")
    try:
        VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(VALIDATION_DIR / ".assessment-transitions.sqlite3", timeout=5)) as connection, connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as error:
                if getattr(error, "sqlite_errorcode", None) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                    raise ComparisonBusy("Another assessment transition is running.") from error
                raise
            yield
    finally:
        _REVIEWED_WINDOW_LOCK.release()


def _transition(result: ValidationResult, status: str, detail: str, recorded_at: datetime) -> list[EvaluationTransition]:
    return [*result.evaluation_transitions, EvaluationTransition(
        previous_status=result.status, new_status=status, recorded_at=recorded_at, detail=detail,
    )]


def _save_assessment_outcome(
    result: ValidationResult, status: Literal["evaluation_failed", "evaluation_rejected"], detail: str,
) -> ValidationResult:
    recorded_at = datetime.now(timezone.utc)
    updated = result.model_copy(update={
        "status": status,
        "evaluation_completed_at": recorded_at,
        "evaluation_outcome_detail": detail,
        "evaluation_transitions": _transition(result, status, detail, recorded_at),
        "precision": None,
        "recall": None,
        "f1_score": None,
        "intersection_over_union": None,
        "overall_agreement": None,
    })
    path = (VALIDATION_DIR / result.validation_id / "result.json").resolve()
    if not path.is_relative_to(VALIDATION_DIR.resolve()) or not path.is_file():
        raise FileNotFoundError("Assessment was not found.")
    _atomic_json(path, updated.model_dump(mode="json"))
    return updated


def reject_windowed_assessment(validation_id: str, reason: str) -> ValidationResult:
    if not reason.strip() or len(reason) > 1000:
        raise ValueError("A rejection reason of at most 1000 characters is required.")
    with _assessment_transition_lock():
        result = get_validation_report(validation_id)
        if result.status != "thresholds_met_awaiting_evaluation" or result.resampling != "none":
            raise ValueError("Only a qualifying windowed assessment awaiting evaluation can be rejected.")
        return _save_assessment_outcome(result, "evaluation_rejected", reason.strip())
def evaluate_windowed_assessment(validation_id: str) -> ValidationResult:
    with _assessment_transition_lock():
        result = get_validation_report(validation_id)
        if result.status != "thresholds_met_awaiting_evaluation" or result.resampling != "none":
            raise ValueError("Only a qualifying windowed assessment awaiting evaluation can be evaluated.")
        if not result.independent_review_completed or result.confusion_matrix is None or not _meets_evidence_thresholds(
            result.common_valid_pixel_count, result.valid_reference_coverage_fraction,
            result.minimum_common_pixels, result.minimum_coverage_fraction, result.minimum_pixels_per_class,
            result.spatial_block_size_pixels, result.minimum_blocks_per_class,
            result.reference_class_counts, result.reference_class_block_counts,
        ):
            message = "Assessment does not satisfy the evidence requirements."
            _save_assessment_outcome(result, "evaluation_failed", message)
            raise ValueError(message)
        matrix = result.confusion_matrix
        if set(matrix) != {"true_positive", "true_negative", "false_positive", "false_negative"} or any(
            count < 0 for count in matrix.values()
        ) or sum(matrix.values()) != result.common_valid_pixel_count:
            message = "Assessment confusion counts are inconsistent."
            _save_assessment_outcome(result, "evaluation_failed", message)
            raise ValueError(message)
        tp, tn, fp, fn = (matrix[key] for key in ("true_positive", "true_negative", "false_positive", "false_negative"))
        if result.reference_class_counts != {"0": tn + fp, "1": tp + fn} or not (tn + fp and tp + fn):
            message = "Assessment reference counts are inconsistent."
            _save_assessment_outcome(result, "evaluation_failed", message)
            raise ValueError(message)
        recorded_at = datetime.now(timezone.utc)
        detail = "Evaluation completed on submitted common-valid counts."
        result = result.model_copy(update={
            "status": "validation_completed",
            "evaluation_completed_at": recorded_at,
            "evaluation_outcome_detail": detail,
            "evaluation_transitions": _transition(result, "validation_completed", detail, recorded_at),
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1_score": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            "intersection_over_union": tp / (tp + fp + fn) if tp + fp + fn else None,
            "overall_agreement": (tp + tn) / result.common_valid_pixel_count,
        })
        path = (VALIDATION_DIR / result.validation_id / "result.json").resolve()
        if not path.is_relative_to(VALIDATION_DIR.resolve()) or not path.is_file():
            raise FileNotFoundError("Assessment was not found.")
        _atomic_json(path, result.model_dump(mode="json"))
        return result
def compare_classification_methods(
    candidate_rasters: list[bytes],
    reference_bytes: bytes,
    metadata: MethodEvaluationMetadata,
) -> MethodEvaluationResult:
    if not metadata.reference_metadata.independent_review_completed:
        raise ValueError("Independent reviewer attestation is required before comparing methods.")
    if len(candidate_rasters) != len(metadata.methods):
        raise ValueError("Provide exactly one candidate GeoTIFF for each declared method.")
    if not reference_bytes or len(reference_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError("Reference GeoTIFF must be nonempty and no larger than 100 MB.")

    rasterio = _rasterio()
    candidates, pixel_area = _read_candidate_grids(candidate_rasters)
    reference, reference_profile, reference_crs = _read_mask(reference_bytes, "Reference")
    base_values, base_profile, base_crs = candidates[0]
    if reference_profile.get("nodata") != 255:
        raise ValueError("Reference GeoTIFF must declare 255 as uncertain/NoData.")

    aligned_reference = np.full(base_values.shape, 255, dtype=np.uint8)
    from rasterio.warp import reproject

    reproject(
        source=reference,
        destination=aligned_reference,
        src_transform=reference_profile["transform"],
        src_crs=reference_crs,
        src_nodata=255,
        dst_transform=base_profile["transform"],
        dst_crs=base_crs,
        dst_nodata=255,
        resampling=rasterio.enums.Resampling.nearest,
        init_dest_nodata=True,
    )
    reference_valid = np.isin(aligned_reference, (0, 1))
    shared = reference_valid.copy()
    for values, _, _ in candidates:
        shared &= np.isin(values, (0, 1))
    shared_count = int(np.count_nonzero(shared))
    reference_count = int(np.count_nonzero(reference_valid))
    coverage = shared_count / reference_count if reference_count else 0.0
    class_counts, block_counts = _reference_distribution(
        aligned_reference, shared, metadata.reference_metadata.spatial_block_size_pixels,
    )
    both_reference_classes = (
        shared_count > 0
        and np.any(aligned_reference[shared] == 0)
        and np.any(aligned_reference[shared] == 1)
    )
    if shared_count == 0:
        status = "insufficient_spatial_overlap"
    elif not both_reference_classes:
        status = "insufficient_valid_labels"
    elif not _evidence_sufficient(metadata.reference_metadata, shared_count, coverage, class_counts, block_counts):
        status = "insufficient_evidence"
    else:
        status = "evaluation_completed"

    method_results: list[dict[str, Any]] = []
    summaries = _candidate_summaries(candidates, shared, pixel_area)
    for method, (values, _, _), summary in zip(metadata.methods, candidates, summaries):
        if status == "evaluation_completed":
            tp = int(np.count_nonzero(shared & (values == 1) & (aligned_reference == 1)))
            tn = int(np.count_nonzero(shared & (values == 0) & (aligned_reference == 0)))
            fp = int(np.count_nonzero(shared & (values == 1) & (aligned_reference == 0)))
            fn = int(np.count_nonzero(shared & (values == 0) & (aligned_reference == 1)))
            precision = tp / (tp + fp) if tp + fp else None
            recall = tp / (tp + fn) if tp + fn else None
            f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
            union = tp + fp + fn
            iou = tp / union if union else None
            confusion_matrix = {
                "true_positive": tp,
                "true_negative": tn,
                "false_positive": fp,
                "false_negative": fn,
            }
        else:
            precision = recall = f1 = iou = None
            confusion_matrix = None
        method_results.append(
            {
                "method_id": method.method_id,
                "method_name": method.method_name,
                "parameters": method.parameters,
                **summary,
                "confusion_matrix": confusion_matrix,
                "precision": precision,
                "recall": recall,
                "f1_score": f1,
                "intersection_over_union": iou,
            }
        )

    evaluation_id = str(uuid.uuid4())
    report = MethodEvaluationResult(
        evaluation_id=evaluation_id,
        status=status,
        river_id=metadata.reference_metadata.river_id,
        candidate_product_id=metadata.reference_metadata.candidate_product_id,
        candidate_acquisition_datetime=metadata.reference_metadata.candidate_acquisition_datetime,
        reference_dataset_id=metadata.reference_metadata.reference_dataset_id,
        reference_acquisition_datetime=metadata.reference_metadata.reference_acquisition_datetime,
        reference_metadata=metadata.reference_metadata,
        temporal_offset_seconds=abs(
            (
                metadata.reference_metadata.candidate_acquisition_datetime
                - metadata.reference_metadata.reference_acquisition_datetime
            ).total_seconds()
        ),
        shared_common_valid_pixel_count=shared_count,
        shared_reference_coverage_fraction=coverage,
        minimum_common_pixels=metadata.reference_metadata.minimum_common_pixels,
        minimum_coverage_fraction=metadata.reference_metadata.minimum_coverage_fraction,
        minimum_pixels_per_class=metadata.reference_metadata.minimum_pixels_per_class,
        spatial_block_size_pixels=metadata.reference_metadata.spatial_block_size_pixels,
        minimum_blocks_per_class=metadata.reference_metadata.minimum_blocks_per_class,
        reference_class_counts=class_counts,
        reference_class_block_counts=block_counts,
        candidate_crs=base_crs.to_string(),
        pixel_area_m2=pixel_area,
        methods=method_results,
        pairwise_comparisons=_pairwise_comparisons(candidates, metadata.methods, shared, pixel_area),
        warnings=[
            "All methods are evaluated on the same common-valid pixels for a fair spatial-support comparison.",
            "Metrics are descriptive of this submitted reviewed sample and do not establish generalization or scientific validity.",
            "The application records but cannot authenticate reviewer identity, source independence, or label quality.",
            "No best method is selected automatically; use a predeclared, spatially appropriate evaluation design.",
            "Temporal offset and source-grid resampling must be considered when interpreting reference comparisons.",
            "Operator-declared thresholds do not establish sample representativeness or scientific validity.",
            "Pairwise IoU and disagreement compare candidates only; they are not accuracy. Percentage area difference uses the first method as denominator.",
        ],
        report_url=f"/api/analysis/validation/method-comparisons/{evaluation_id}",
    )
    output_directory = METHOD_EVALUATION_DIR / evaluation_id
    output_directory.mkdir(parents=True, exist_ok=False)
    try:
        _atomic_json(output_directory / "result.json", report.model_dump(mode="json"))
    except Exception:
        output_directory.rmdir()
        raise
    return report


def get_method_evaluation_report(evaluation_id: str) -> MethodEvaluationResult:
    try:
        normalized_id = str(uuid.UUID(evaluation_id))
    except ValueError as error:
        raise ValueError("Invalid method-evaluation identifier.") from error
    path = (METHOD_EVALUATION_DIR / normalized_id / "result.json").resolve()
    if not path.is_relative_to(METHOD_EVALUATION_DIR.resolve()) or not path.is_file():
        raise FileNotFoundError(f"Method-evaluation report {normalized_id} was not found.")
    result = MethodEvaluationResult.model_validate_json(path.read_text(encoding="utf-8"))
    if result.status == "evaluation_completed" and not _meets_evidence_thresholds(
        result.shared_common_valid_pixel_count, result.shared_reference_coverage_fraction,
        result.minimum_common_pixels, result.minimum_coverage_fraction,
        result.minimum_pixels_per_class, result.spatial_block_size_pixels,
        result.minimum_blocks_per_class, result.reference_class_counts,
        result.reference_class_block_counts,
    ):
        return result.model_copy(update={
            "status": "insufficient_evidence",
            "methods": [
                {**method, "confusion_matrix": None, "precision": None, "recall": None,
                 "f1_score": None, "intersection_over_union": None}
                for method in result.methods
            ],
            "warnings": [*result.warnings, "Stored report lacks qualifying evidence thresholds; accuracy metrics are withheld."],
        })
    return result
