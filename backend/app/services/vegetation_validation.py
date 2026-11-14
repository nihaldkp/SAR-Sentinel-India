"""Operator-declared, sample-scoped vegetation index assessments."""

import hashlib
import json
import math
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.windows import Window

from app.schemas.vegetation_validation import VegetationAssessmentProtocol
from app.services import sentinel2

STORE = Path(__file__).resolve().parents[3] / "outputs" / "vegetation-validation" / "assessments.sqlite3"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_PIXELS = 100_000_000
CLASSES = {0: "other_nonvegetation", 1: "agriculture", 2: "natural_forest",
           3: "plantation", 4: "other_vegetation"}
_EVALUATION_LOCK = threading.Lock()
LIMITATIONS = [
    "This evaluates index agreement only on the submitted, labelled sample; it does not validate land-cover classification, crop health, yield, or deforestation.",
    "Independence, review, sampling design, provenance, and criteria are operator declarations and are not authenticated by the application.",
    "Pixel and block counts do not establish representativeness or scientific certification.",
    "Spectral response, alignment, temporal offsets and reference sampling can affect index agreement.",
]


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate(protocol: VegetationAssessmentProtocol) -> tuple[dict, Path]:
    record = sentinel2.reconcile_cached_grid(sentinel2._cached_record(protocol.river_id, protocol.item_id))
    if record.get("raster_reconciliation"):
        raise ValueError("The candidate raster processing provenance is unresolved because its catalog grid differs.")
    return record, sentinel2._cached_raster_path(record, protocol.index_name)


def _connect() -> sqlite3.Connection:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(STORE, timeout=5)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS assessments (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, "
        "payload TEXT NOT NULL, reference BLOB)"
    )
    return connection


def create_assessment(protocol: VegetationAssessmentProtocol) -> dict:
    record, path = _candidate(protocol)
    if not record.get("acquisition_datetime"):
        raise ValueError("Candidate acquisition timestamp is unavailable.")
    acquired = datetime.fromisoformat(record["acquisition_datetime"].replace("Z", "+00:00"))
    if acquired.utcoffset() is None:
        raise ValueError("Candidate acquisition timestamp has no timezone.")
    for label, date in (("index reference", protocol.reference_acquisition_datetime),
                        ("land-cover reference", protocol.landcover_acquisition_datetime)):
        if abs((acquired - date).total_seconds()) > protocol.maximum_time_difference_days * 86400:
            raise ValueError(f"{label} date exceeds the predeclared temporal tolerance.")
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "assessment_id": str(uuid.uuid4()),
        "status": "NOT_VALIDATED",
        "reason": "Protocol recorded; awaiting independent reference GeoTIFF.",
        "created_at": now,
        "candidate_acquisition_datetime": acquired.isoformat(),
        "candidate_processing_version": record.get("processor_version"),
        "candidate_sha256": _hash_file(path),
        "protocol": protocol.model_dump(mode="json"),
        "metrics": None,
        "limitations": [*LIMITATIONS, *protocol.limitations],
    }
    with closing(_connect()) as connection, connection:
        connection.execute("INSERT INTO assessments (id, created_at, payload) VALUES (?, ?, ?)",
                           (payload["assessment_id"], now, json.dumps(payload)))
    return payload


def get_assessment(assessment_id: str) -> dict:
    try:
        identifier = str(uuid.UUID(assessment_id))
    except ValueError as error:
        raise ValueError("Invalid assessment identifier.") from error
    if not STORE.is_file():
        raise FileNotFoundError("Vegetation assessment not found.")
    with closing(sqlite3.connect(STORE)) as connection:
        row = connection.execute("SELECT payload FROM assessments WHERE id = ?", (identifier,)).fetchone()
    if row is None:
        raise FileNotFoundError("Vegetation assessment not found.")
    return _current_assessment(json.loads(row[0]))


def _current_assessment(assessment: dict) -> dict:
    protocol = VegetationAssessmentProtocol.model_validate(assessment["protocol"])
    try:
        record, path = _candidate(protocol)
        current = (
            _hash_file(path) == assessment["candidate_sha256"]
            and record.get("processor_version") == assessment["candidate_processing_version"]
            and datetime.fromisoformat(record["acquisition_datetime"].replace("Z", "+00:00"))
            == datetime.fromisoformat(assessment["candidate_acquisition_datetime"])
        )
    except (OSError, ValueError, KeyError, AttributeError):
        current = False
    if not current:
        return {
            **assessment,
            "recorded_status": assessment["status"],
            "status": "NOT_VALIDATED",
            "reason": "The assessment is not applicable because the candidate raster or identity is missing or changed.",
        }
    return assessment


def list_assessments(river_id: str) -> list[dict]:
    if not STORE.is_file():
        return []
    with closing(sqlite3.connect(STORE)) as connection:
        rows = connection.execute("SELECT payload FROM assessments ORDER BY created_at DESC, id DESC").fetchall()
    records = [json.loads(row[0]) for row in rows]
    return [_current_assessment(record) for record in records if record["protocol"]["river_id"] == river_id]


def assessment_reference(assessment_id: str) -> bytes:
    assessment = get_assessment(assessment_id)
    with closing(sqlite3.connect(STORE)) as connection:
        row = connection.execute(
            "SELECT reference FROM assessments WHERE id = ?", (assessment["assessment_id"],)
        ).fetchone()
    if row is None or row[0] is None:
        raise FileNotFoundError("No reference GeoTIFF has been recorded for this assessment.")
    content = bytes(row[0])
    if hashlib.sha256(content).hexdigest() != assessment.get("reference_sha256"):
        raise ValueError("Stored reference GeoTIFF does not match the recorded fingerprint.")
    return content


def evaluate_assessment(assessment_id: str, content: bytes) -> dict:
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Reference GeoTIFF must be nonempty and at most 100 MB.")
    with _EVALUATION_LOCK:
        return _evaluate_assessment(assessment_id, content)


def _evaluate_assessment(assessment_id: str, content: bytes) -> dict:
    assessment = get_assessment(assessment_id)
    if assessment["status"] not in {"NOT_VALIDATED", "VALIDATION_IN_PROGRESS"} or assessment.get("recorded_status"):
        raise ValueError("Assessment is not awaiting evaluation.")
    protocol = VegetationAssessmentProtocol.model_validate(assessment["protocol"])
    _, path = _candidate(protocol)
    if _hash_file(path) != assessment["candidate_sha256"]:
        raise ValueError("The candidate GeoTIFF changed after the protocol was recorded.")
    reference_hash = hashlib.sha256(content).hexdigest()
    if reference_hash == assessment["candidate_sha256"]:
        raise ValueError("The candidate cannot be its own reference.")
    assessment.update({
        "status": "VALIDATION_IN_PROGRESS",
        "reason": "The submitted reference is being evaluated.",
        "reference_sha256": reference_hash,
    })
    with closing(_connect()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT payload FROM assessments WHERE id = ?", (assessment["assessment_id"],)).fetchone()
        if row is None or json.loads(row[0])["status"] not in {"NOT_VALIDATED", "VALIDATION_IN_PROGRESS"}:
            raise ValueError("Assessment has already been evaluated.")
        connection.execute("UPDATE assessments SET payload = ?, reference = ? WHERE id = ?",
                           (json.dumps(assessment, allow_nan=False), content, assessment["assessment_id"]))
    try:
        metrics = _calculate(path, content, protocol)
        if _hash_file(path) != assessment["candidate_sha256"]:
            raise ValueError("The candidate GeoTIFF changed during evaluation.")
    except (ValueError, OSError) as error:
        assessment.update({"status": "NOT_VALIDATED", "reason": f"Reference evaluation could not be completed: {error}"})
        _finish_assessment(assessment, reference_hash)
        raise
    target = "agriculture" if protocol.domain == "agriculture" else "natural_forest"
    sufficient = (
        metrics["common_target_pixels"] >= protocol.minimum_common_pixels
        and metrics["target_coverage_fraction"] >= protocol.minimum_coverage_fraction
        and metrics["target_spatial_blocks"] >= protocol.minimum_target_blocks
        and all(item["count"] >= protocol.minimum_pixels_per_class for item in metrics["classes"].values())
    )
    if not sufficient:
        status, reason = "INSUFFICIENT_REFERENCE_DATA", "Submitted common support does not meet the predeclared sample, class, coverage, or spatial-block requirements."
        metrics["rmse"] = metrics["mae"] = metrics["bias"] = None
    elif metrics["rmse"] <= protocol.maximum_rmse:
        status, reason = "VALIDATED", "The predeclared index RMSE criterion was met on the submitted target-class sample."
    else:
        status, reason = "VALIDATION_FAILED", "The predeclared index RMSE criterion was not met on the submitted target-class sample."
    assessment.update({
        "status": status, "reason": reason, "target_class": target,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
    })
    _finish_assessment(assessment, reference_hash)
    return assessment


def _finish_assessment(assessment: dict, reference_hash: str) -> None:
    with closing(_connect()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT payload FROM assessments WHERE id = ?", (assessment["assessment_id"],)).fetchone()
        current = json.loads(row[0]) if row else None
        if current is None or current["status"] != "VALIDATION_IN_PROGRESS" or current["reference_sha256"] != reference_hash:
            raise ValueError("Assessment has changed during evaluation.")
        connection.execute("UPDATE assessments SET payload = ? WHERE id = ?",
                           (json.dumps(assessment, allow_nan=False), assessment["assessment_id"]))


def _calculate(path: Path, content: bytes, protocol: VegetationAssessmentProtocol) -> dict:
    target = 1 if protocol.domain == "agriculture" else 2
    counts = np.zeros(len(CLASSES), dtype=np.int64)
    sums = np.zeros(len(CLASSES), dtype=np.float64)
    candidate_count = common_target = 0
    squared_error = absolute_error = signed_error = 0.0
    occupied: set[tuple[int, int]] = set()
    try:
        with rasterio.open(path) as candidate, MemoryFile(content) as memory, memory.open() as reference:
            if reference.driver != "GTiff" or reference.count != 2 or candidate.count != 1:
                raise ValueError("Reference must be a two-band GeoTIFF; candidate must have one band.")
            if reference.nodata is None or any(dtype not in {"float32", "float64"} for dtype in reference.dtypes):
                raise ValueError("Reference bands must be floating point and declare NoData.")
            if reference.nodata in CLASSES:
                raise ValueError("Reference NoData must not coincide with a land-cover class.")
            if candidate.crs is None or not candidate.crs.is_projected or candidate.crs.linear_units.casefold() not in {"metre", "meter"}:
                raise ValueError("Candidate grid must use a projected metre CRS.")
            if (reference.width, reference.height, reference.crs, reference.transform) != (
                candidate.width, candidate.height, candidate.crs, candidate.transform
            ):
                raise ValueError("Reference and candidate must have identical CRS, dimensions, and transform; no resampling is performed.")
            if candidate.width * candidate.height > MAX_PIXELS:
                raise ValueError("Raster exceeds the 100-million-pixel assessment limit.")
            block = protocol.spatial_block_size_pixels
            if math.ceil(candidate.width / block) * math.ceil(candidate.height / block) > 2_000_000:
                raise ValueError("Spatial blocks exceed the safe limit; choose a larger predeclared block size.")
            if any(h * w > 1_048_576 for h, w in reference.block_shapes):
                raise ValueError("Reference storage blocks exceed the safe window limit.")
            grid_resolution = min(math.hypot(candidate.transform.a, candidate.transform.d),
                                  math.hypot(candidate.transform.b, candidate.transform.e))
            if not math.isfinite(grid_resolution) or grid_resolution <= 0:
                raise ValueError("Candidate grid resolution is invalid.")
            for row in range(0, candidate.height, 512):
                for col in range(0, candidate.width, 512):
                    window = Window(col, row, min(512, candidate.width-col), min(512, candidate.height-row))
                    a = candidate.read(1, window=window, masked=True)
                    r = reference.read(1, window=window, masked=True)
                    c = reference.read(2, window=window, masked=True)
                    valid_a = ~np.ma.getmaskarray(a) & np.isfinite(a.data)
                    valid_c = ~np.ma.getmaskarray(c) & np.isfinite(c.data)
                    if not np.isin(c.data[valid_c], list(CLASSES)).all():
                        raise ValueError("Band 2 labels must be 0 other nonvegetation, 1 agriculture, 2 natural forest, 3 plantation, or 4 other vegetation.")
                    common = valid_a & valid_c
                    candidate_count += int(valid_a.sum())
                    for code in CLASSES:
                        selection = common & (c.data == code)
                        counts[code] += int(selection.sum())
                        sums[code] += float(a.data[selection].astype("float64").sum())
                    selection = common & (c.data == target) & ~np.ma.getmaskarray(r) & np.isfinite(r.data)
                    difference = a.data[selection].astype("float64") - r.data[selection].astype("float64")
                    common_target += int(difference.size)
                    signed_error += float(difference.sum())
                    absolute_error += float(np.abs(difference).sum())
                    squared_error += float(np.square(difference).sum())
                    rr, cc = np.nonzero(selection)
                    block = protocol.spatial_block_size_pixels
                    occupied.update(zip(((rr + row) // block).tolist(), ((cc + col) // block).tolist()))
            bounds = list(candidate.bounds)
            crs = str(candidate.crs)
    except rasterio.errors.RasterioError as error:
        raise ValueError(f"Unable to read assessment GeoTIFF: {error}") from error
    return {
        "candidate_valid_pixels": candidate_count,
        "common_target_pixels": common_target,
        "target_coverage_fraction": common_target / candidate_count if candidate_count else 0,
        "target_spatial_blocks": len(occupied),
        "rmse": math.sqrt(squared_error / common_target) if common_target else None,
        "mae": absolute_error / common_target if common_target else None,
        "bias": signed_error / common_target if common_target else None,
        "classes": {name: {"count": int(counts[code]), "candidate_mean": float(sums[code] / counts[code]) if counts[code] else None}
                    for code, name in CLASSES.items()},
        "crs": crs, "bounds": bounds, "resampling": "none",
    }
