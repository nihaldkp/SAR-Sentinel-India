import hashlib
import math
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import numpy as np

from app.schemas.reference_lifecycle import (
    BoundAssessmentCalculation,
    BoundAssessmentEvent,
    BoundAssessmentReservation,
    BoundReferenceMetadata,
    BoundReferenceRecord,
    CandidateIdentity,
    ReferenceEligibility,
    ReferenceReviewEvent,
    ReviewAction,
)
from app.schemas.validation import ValidationResult, WindowedValidationMetadata
from app.services import validation

DATABASE_PATH = validation.REPOSITORY_ROOT / "outputs" / "reference-lifecycle.sqlite3"
MAX_REFERENCE_RECORDS = 1000
MAX_REFERENCE_STORAGE_BYTES = 1024 * 1024 * 1024
MAX_RESERVED_ASSESSMENTS = 1000
MAX_RESERVED_CANDIDATE_BYTES = 1024 * 1024 * 1024


@contextmanager
def _database() -> Iterator[sqlite3.Connection]:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(DATABASE_PATH, timeout=5)) as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS bound_references (
                    reference_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    reference_raster BLOB NOT NULL
                )"""
            )
            yield connection
    except sqlite3.OperationalError as error:
        if getattr(error, "sqlite_errorcode", None) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise validation.ComparisonBusy("Reference storage is busy; retry the request.") from error
        raise


def _id(reference_id: str) -> str:
    try:
        return str(uuid.UUID(reference_id))
    except ValueError as error:
        raise ValueError("Invalid reference identifier.") from error


def _reservation_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS bound_assessments (
            assessment_id TEXT PRIMARY KEY,
            reference_id TEXT NOT NULL REFERENCES bound_references(reference_id),
            state TEXT NOT NULL CHECK(state IN ('assessment_reserved', 'evaluation_rejected')),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            candidate_sha256 TEXT NOT NULL, reference_sha256 TEXT NOT NULL,
            metadata_json TEXT NOT NULL, reference_json TEXT NOT NULL,
            candidate_raster BLOB NOT NULL, reason TEXT
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS bound_assessment_events (
            event_id INTEGER PRIMARY KEY, assessment_id TEXT NOT NULL REFERENCES bound_assessments(assessment_id),
            previous_state TEXT, new_state TEXT NOT NULL, recorded_at TEXT NOT NULL, reason TEXT NOT NULL
        )"""
    )
    connection.execute(
        """CREATE TRIGGER IF NOT EXISTS bound_assessment_immutable_inputs
           BEFORE UPDATE OF assessment_id,reference_id,created_at,candidate_sha256,reference_sha256,
                            metadata_json,reference_json,candidate_raster ON bound_assessments
           BEGIN SELECT RAISE(ABORT, 'assessment input identity is immutable'); END"""
    )
    connection.execute(
        """CREATE TRIGGER IF NOT EXISTS bound_assessment_no_delete
           BEFORE DELETE ON bound_assessments
           BEGIN SELECT RAISE(ABORT, 'assessment history cannot be deleted'); END"""
    )
    connection.execute(
        """CREATE TRIGGER IF NOT EXISTS bound_assessment_event_no_update
           BEFORE UPDATE ON bound_assessment_events
           BEGIN SELECT RAISE(ABORT, 'assessment events are immutable'); END"""
    )
    connection.execute(
        """CREATE TRIGGER IF NOT EXISTS bound_assessment_event_no_delete
           BEFORE DELETE ON bound_assessment_events
           BEGIN SELECT RAISE(ABORT, 'assessment events cannot be deleted'); END"""
    )


def _reservation_from_row(row: tuple) -> BoundAssessmentReservation:
    return BoundAssessmentReservation(
        assessment_id=row[0], reference_id=row[1], state=row[2], created_at=row[3],
        updated_at=row[4], candidate_sha256=row[5], reference_sha256=row[6],
        metadata=WindowedValidationMetadata.model_validate_json(row[7]),
        reference_at_reservation=BoundReferenceRecord.model_validate_json(row[8]), reason=row[9],
    )


_RESERVATION_COLUMNS = (
    "assessment_id,reference_id,state,created_at,updated_at,candidate_sha256,"
    "reference_sha256,metadata_json,reference_json,reason"
)


def import_bound_reference(
    candidate_bytes: bytes, reference_bytes: bytes, metadata: BoundReferenceMetadata,
) -> BoundReferenceRecord:
    if not candidate_bytes or not reference_bytes or len(candidate_bytes) + len(reference_bytes) > validation.MAX_UPLOAD_BYTES:
        raise ValueError("Combined candidate and reference GeoTIFFs must be nonempty and no larger than 100 MB.")
    _, candidate_profile, _ = validation._read_mask(candidate_bytes, "Candidate")
    labels, profile, crs = validation._read_mask(reference_bytes, "Reference")
    if any(item.get("driver") != "GTiff" or item.get("dtype") != "uint8" for item in (candidate_profile, profile)):
        raise ValueError("Both inputs must be uint8 GeoTIFFs.")
    if candidate_profile.get("nodata") != 255 or profile.get("nodata") != 255:
        raise ValueError("Both GeoTIFFs must declare 255 as NoData.")
    if not crs.is_projected or crs.linear_units.casefold() not in {"metre", "meter"}:
        raise ValueError("Reference CRS must be projected in metres.")
    transform = profile["transform"]
    imported_at = datetime.now(timezone.utc)
    record = BoundReferenceRecord(
        reference_id=str(uuid.uuid4()),
        metadata=metadata,
        candidate_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
        reference_sha256=hashlib.sha256(reference_bytes).hexdigest(),
        reference_crs=crs.to_string(),
        reference_width=profile["width"],
        reference_height=profile["height"],
        reference_transform=list(transform[:6]),
        reference_resolution_m=[math.hypot(transform.a, transform.d), math.hypot(transform.b, transform.e)],
        label_counts={str(value): int(count) for value, count in zip(*np.unique(labels, return_counts=True))},
        nodata_value=255,
        imported_at=imported_at,
        review_status="imported",
        review_history=[ReferenceReviewEvent(
            previous_status=None, new_status="imported", recorded_at=imported_at,
            action="import", details={},
        )],
        limitations=[
            "The supplied candidate product, acquisition and processing version are operator declarations, not authenticated.",
            "Reviewers and reference independence are not authenticated; import does not establish label quality.",
            "This record is not yet linked to the evaluation workflow and does not establish scientific validation.",
        ],
    )
    with _database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        count, stored_bytes = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(length(reference_raster)), 0) FROM bound_references"
        ).fetchone()
        if count >= MAX_REFERENCE_RECORDS or stored_bytes + len(reference_bytes) > MAX_REFERENCE_STORAGE_BYTES:
            raise ValueError("Reference storage quota is exhausted.")
        connection.execute(
            "INSERT INTO bound_references(reference_id,status,record_json,reference_raster) VALUES(?,?,?,?)",
            (record.reference_id, record.review_status, record.model_dump_json(), reference_bytes),
        )
    return record


def get_bound_reference(reference_id: str) -> BoundReferenceRecord:
    reference_id = _id(reference_id)
    if not DATABASE_PATH.is_file():
        raise FileNotFoundError("Reference record was not found.")
    with _database() as connection:
        row = connection.execute(
            "SELECT status,record_json FROM bound_references WHERE reference_id=?", (reference_id,),
        ).fetchone()
    if row is None:
        raise FileNotFoundError("Reference record was not found.")
    record = BoundReferenceRecord.model_validate_json(row[1])
    if record.reference_id != reference_id or record.review_status != row[0]:
        raise ValueError("Reference record is inconsistent.")
    return record


def list_bound_references() -> list[BoundReferenceRecord]:
    if not DATABASE_PATH.is_file():
        return []
    with _database() as connection:
        rows = connection.execute(
            "SELECT reference_id,status,record_json FROM bound_references ORDER BY rowid DESC LIMIT 100",
        ).fetchall()
    records = []
    for reference_id, status, record_json in rows:
        record = BoundReferenceRecord.model_validate_json(record_json)
        if record.reference_id != reference_id or record.review_status != status:
            raise ValueError("Reference record is inconsistent.")
        records.append(record)
    return records


def transition_review(reference_id: str, action: ReviewAction) -> BoundReferenceRecord:
    reference_id = _id(reference_id)
    if not DATABASE_PATH.is_file():
        raise FileNotFoundError("Reference record was not found.")
    transitions = {
        ("imported", "request_review"): "review_pending",
        ("review_pending", "attest"): "attestation_recorded",
        ("review_pending", "reject"): "rejected",
        ("attestation_recorded", "withdraw"): "withdrawn",
    }
    with _database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT status,record_json FROM bound_references WHERE reference_id=?", (reference_id,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError("Reference record was not found.")
        record = BoundReferenceRecord.model_validate_json(row[1])
        if record.reference_id != reference_id or record.review_status != row[0]:
            raise ValueError("Reference record is inconsistent.")
        next_status = transitions.get((record.review_status, action.action))
        if next_status is None:
            raise ValueError("The requested reference review transition is not permitted.")
        event = ReferenceReviewEvent(
            previous_status=record.review_status, new_status=next_status,
            recorded_at=datetime.now(timezone.utc), action=action.action,
            details=action.model_dump(exclude={"action"}),
        )
        updated = record.model_copy(update={
            "review_status": next_status, "review_history": [*record.review_history, event],
        })
        connection.execute(
            "UPDATE bound_references SET status=?,record_json=? WHERE reference_id=?",
            (next_status, updated.model_dump_json(), reference_id),
        )
        if next_status == "withdrawn":
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bound_assessments'"
            ).fetchone()
            if exists:
                reason = "Reference attestation withdrawn before evaluation."
                timestamp = event.recorded_at.isoformat()
                ids = connection.execute(
                    "SELECT assessment_id FROM bound_assessments WHERE reference_id=? AND state='assessment_reserved'",
                    (reference_id,),
                ).fetchall()
                connection.execute(
                    "UPDATE bound_assessments SET state='evaluation_rejected',updated_at=?,reason=? "
                    "WHERE reference_id=? AND state='assessment_reserved'",
                    (timestamp, reason, reference_id),
                )
                connection.executemany(
                    "INSERT INTO bound_assessment_events(assessment_id,previous_state,new_state,recorded_at,reason) VALUES(?,?,?,?,?)",
                    [(item[0], "assessment_reserved", "evaluation_rejected", timestamp, reason) for item in ids],
                )
    return updated


def reference_raster(reference_id: str) -> bytes:
    record = get_bound_reference(reference_id)
    with _database() as connection:
        row = connection.execute(
            "SELECT reference_raster FROM bound_references WHERE reference_id=?", (record.reference_id,),
        ).fetchone()
    if row is None:
        raise FileNotFoundError("Reference raster was not found.")
    raster = bytes(row[0])
    if hashlib.sha256(raster).hexdigest() != record.reference_sha256:
        raise ValueError("Stored reference raster fingerprint does not match its record.")
    return raster


def check_eligibility(reference_id: str, candidate_bytes: bytes, identity: CandidateIdentity) -> ReferenceEligibility:
    reference_id = _id(reference_id)
    if not DATABASE_PATH.is_file():
        raise FileNotFoundError("Reference record was not found.")
    if not candidate_bytes or len(candidate_bytes) > validation.MAX_UPLOAD_BYTES:
        raise ValueError("Candidate GeoTIFF must be nonempty and no larger than 100 MB.")
    candidate_hash = hashlib.sha256(candidate_bytes).hexdigest()
    _, profile, crs = validation._read_mask(candidate_bytes, "Candidate")
    if profile.get("driver") != "GTiff" or profile.get("dtype") != "uint8" or profile.get("nodata") != 255:
        raise ValueError("Candidate must be a uint8 GeoTIFF declaring 255 as NoData.")
    with _database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS reference_eligibility_checks (
                check_id TEXT PRIMARY KEY, reference_id TEXT NOT NULL,
                checked_at TEXT NOT NULL, result_json TEXT NOT NULL,
                FOREIGN KEY(reference_id) REFERENCES bound_references(reference_id)
            )"""
        )
        row = connection.execute(
            "SELECT status,record_json,reference_raster FROM bound_references WHERE reference_id=?",
            (reference_id,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError("Reference record was not found.")
        record = BoundReferenceRecord.model_validate_json(row[1])
        if record.reference_id != reference_id or record.review_status != row[0]:
            raise ValueError("Reference record is inconsistent.")
        reference_hash = hashlib.sha256(row[2]).hexdigest()
        reasons = []
        if record.review_status != "attestation_recorded":
            reasons.append(f"Reference review status is {record.review_status}; an attestation is required.")
        if record.metadata.candidate_processing_version is None:
            reasons.append("Candidate processing version is unavailable.")
        for field in CandidateIdentity.model_fields:
            if getattr(identity, field) != getattr(record.metadata, field):
                reasons.append(f"Candidate identity field {field} does not match the bound record.")
        if candidate_hash != record.candidate_sha256:
            reasons.append("Candidate raster fingerprint does not match the imported candidate.")
        if reference_hash != record.reference_sha256:
            reasons.append("Stored reference raster fingerprint does not match its record.")
        if (
            profile["width"] != record.reference_width or profile["height"] != record.reference_height
            or crs.to_string() != record.reference_crs
            or list(profile["transform"][:6]) != record.reference_transform
        ):
            reasons.append("Candidate and reference grids do not match exactly; no resampling is supported.")
        result = ReferenceEligibility(
            reference_id=reference_id, checked_at=datetime.now(timezone.utc), candidate_identity=identity,
            review_status=record.review_status, identity_review_checks_passed=not reasons, reasons=reasons,
            candidate_sha256=candidate_hash, reference_sha256=reference_hash,
            limitations=[
                "This check is a snapshot, not permission to evaluate; review status and fingerprints must be rechecked during evaluation.",
                "Candidate product identity and processing version remain operator declarations, not catalog-authenticated facts.",
                "Evidence thresholds and independence are not assessed; reviewer identity is not authenticated.",
            ],
        )
        if connection.execute("SELECT COUNT(*) FROM reference_eligibility_checks").fetchone()[0] >= 10000:
            raise ValueError("Reference eligibility audit storage limit is exhausted.")
        connection.execute(
            "INSERT INTO reference_eligibility_checks(check_id,reference_id,checked_at,result_json) VALUES(?,?,?,?)",
            (str(uuid.uuid4()), reference_id, result.checked_at.isoformat(), result.model_dump_json()),
        )
    return result


def list_eligibility_checks(reference_id: str) -> list[ReferenceEligibility]:
    reference_id = _id(reference_id)
    if not DATABASE_PATH.is_file():
        raise FileNotFoundError("Reference record was not found.")
    with _database() as connection:
        if connection.execute(
            "SELECT 1 FROM bound_references WHERE reference_id=?", (reference_id,),
        ).fetchone() is None:
            raise FileNotFoundError("Reference record was not found.")
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='reference_eligibility_checks'",
        ).fetchone()
        if not exists:
            return []
        rows = connection.execute(
            "SELECT result_json FROM reference_eligibility_checks WHERE reference_id=? ORDER BY rowid DESC LIMIT 100",
            (reference_id,),
        ).fetchall()
    return [ReferenceEligibility.model_validate_json(row[0]) for row in rows]


def reserve_assessment(
    assessment_id: str, reference_id: str, candidate_bytes: bytes, metadata: WindowedValidationMetadata,
) -> BoundAssessmentReservation:
    assessment_id, reference_id = _id(assessment_id), _id(reference_id)
    if not DATABASE_PATH.is_file():
        raise FileNotFoundError("Reference record was not found.")
    if not candidate_bytes or len(candidate_bytes) > validation.MAX_UPLOAD_BYTES:
        raise ValueError("Candidate GeoTIFF must be nonempty and no larger than 100 MB.")
    candidate_hash = hashlib.sha256(candidate_bytes).hexdigest()
    _, candidate_profile, candidate_crs = validation._read_mask(candidate_bytes, "Candidate")
    if (candidate_profile.get("driver"), candidate_profile.get("dtype"), candidate_profile.get("nodata")) != ("GTiff", "uint8", 255):
        raise ValueError("Candidate must be a uint8 GeoTIFF declaring 255 as NoData.")
    with _database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        _reservation_schema(connection)
        previous = connection.execute(
            f"SELECT {_RESERVATION_COLUMNS},candidate_raster FROM bound_assessments WHERE assessment_id=?",
            (assessment_id,),
        ).fetchone()
        if previous is not None:
            existing = _reservation_from_row(previous[:10])
            if (
                existing.reference_id != reference_id or existing.metadata != metadata
                or existing.candidate_sha256 != candidate_hash
                or hashlib.sha256(previous[10]).hexdigest() != existing.candidate_sha256
            ):
                raise ValueError("Assessment identifier already belongs to different or inconsistent inputs.")
            return existing
        row = connection.execute(
            "SELECT status,record_json,reference_raster FROM bound_references WHERE reference_id=?", (reference_id,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError("Reference record was not found.")
        record = BoundReferenceRecord.model_validate_json(row[1])
        if record.reference_id != reference_id or record.review_status != row[0]:
            raise ValueError("Reference record is inconsistent.")
        if record.review_status != "attestation_recorded":
            raise ValueError("Reference must have a current recorded attestation.")
        if not metadata.independent_review_completed:
            raise ValueError("An independence declaration is required.")
        for field in CandidateIdentity.model_fields:
            if getattr(metadata, field) != getattr(record.metadata, field):
                raise ValueError(f"Candidate identity field {field} does not match the bound record.")
        if record.metadata.candidate_processing_version is None:
            raise ValueError("Candidate processing version is unavailable.")
        if (
            metadata.reference_dataset_id != record.metadata.reference_dataset_id
            or metadata.reference_acquisition_datetime != record.metadata.reference_acquisition_datetime
        ):
            raise ValueError("Reference dataset or acquisition does not match the bound record.")
        attestation = record.review_history[-1]
        if attestation.action != "attest" or metadata.reviewer != attestation.details.get("declared_reviewer"):
            raise ValueError("Assessment reviewer must match the recorded attestation.")
        reference_bytes = bytes(row[2])
        if len(candidate_bytes) + len(reference_bytes) > validation.MAX_UPLOAD_BYTES:
            raise ValueError("Combined candidate and reference GeoTIFFs exceed the 100 MB limit.")
        if candidate_hash != record.candidate_sha256:
            raise ValueError("Candidate fingerprint does not match the bound record.")
        if hashlib.sha256(reference_bytes).hexdigest() != record.reference_sha256:
            raise ValueError("Reference fingerprint does not match the bound record.")
        _, reference_profile, reference_crs = validation._read_mask(reference_bytes, "Reference")
        if (reference_profile.get("driver"), reference_profile.get("dtype"), reference_profile.get("nodata")) != ("GTiff", "uint8", 255):
            raise ValueError("Reference must be a uint8 GeoTIFF declaring 255 as NoData.")
        if (
            candidate_crs != reference_crs
            or candidate_profile["width"] != reference_profile["width"]
            or candidate_profile["height"] != reference_profile["height"]
            or candidate_profile["transform"] != reference_profile["transform"]
            or reference_crs.to_string() != record.reference_crs
            or reference_profile["width"] != record.reference_width
            or reference_profile["height"] != record.reference_height
            or list(reference_profile["transform"][:6]) != record.reference_transform
            or record.nodata_value != 255
            or record.reference_resolution_m != [
                math.hypot(reference_profile["transform"].a, reference_profile["transform"].d),
                math.hypot(reference_profile["transform"].b, reference_profile["transform"].e),
            ]
        ):
            raise ValueError("Candidate and reference grids do not match exactly; no resampling is supported.")
        if not math.isclose(min(record.reference_resolution_m), metadata.reference_resolution_m, rel_tol=0.05):
            raise ValueError("Declared reference resolution differs from the raster grid by more than 5%.")
        count, total = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(length(candidate_raster)),0) FROM bound_assessments"
        ).fetchone()
        if count >= MAX_RESERVED_ASSESSMENTS or total + len(candidate_bytes) > MAX_RESERVED_CANDIDATE_BYTES:
            raise ValueError("Assessment reservation storage quota is exhausted.")
        timestamp = datetime.now(timezone.utc)
        reservation = BoundAssessmentReservation(
            assessment_id=assessment_id, reference_id=reference_id, state="assessment_reserved",
            created_at=timestamp, updated_at=timestamp, candidate_sha256=candidate_hash,
            reference_sha256=record.reference_sha256, metadata=metadata, reference_at_reservation=record,
        )
        connection.execute(
            """INSERT INTO bound_assessments
               (assessment_id,reference_id,state,created_at,updated_at,candidate_sha256,reference_sha256,
                metadata_json,reference_json,candidate_raster,reason) VALUES(?,?,?,?,?,?,?,?,?,?,NULL)""",
            (assessment_id, reference_id, reservation.state, timestamp.isoformat(), timestamp.isoformat(),
             candidate_hash, record.reference_sha256, metadata.model_dump_json(), record.model_dump_json(), candidate_bytes),
        )
        connection.execute(
            "INSERT INTO bound_assessment_events(assessment_id,previous_state,new_state,recorded_at,reason) VALUES(?,NULL,?,?,?)",
            (assessment_id, reservation.state, timestamp.isoformat(), "Reserved with recorded attestation."),
        )
    return reservation


def get_assessment_reservation(assessment_id: str) -> BoundAssessmentReservation:
    assessment_id = _id(assessment_id)
    if not DATABASE_PATH.is_file():
        raise FileNotFoundError("Assessment reservation was not found.")
    with _database() as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bound_assessments'"
        ).fetchone()
        if not exists:
            raise FileNotFoundError("Assessment reservation was not found.")
        row = connection.execute(
            f"SELECT {_RESERVATION_COLUMNS} FROM bound_assessments WHERE assessment_id=?", (assessment_id,),
        ).fetchone()
    if row is None:
        raise FileNotFoundError("Assessment reservation was not found.")
    return _reservation_from_row(row)


def list_assessment_events(assessment_id: str) -> list[BoundAssessmentEvent]:
    assessment_id = _id(assessment_id)
    if not DATABASE_PATH.is_file():
        raise FileNotFoundError("Assessment reservation was not found.")
    with _database() as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bound_assessments'"
        ).fetchone()
        if not exists or connection.execute(
            "SELECT 1 FROM bound_assessments WHERE assessment_id=?", (assessment_id,),
        ).fetchone() is None:
            raise FileNotFoundError("Assessment reservation was not found.")
        rows = connection.execute(
            "SELECT previous_state,new_state,recorded_at,reason FROM bound_assessment_events WHERE assessment_id=? ORDER BY event_id",
            (assessment_id,),
        ).fetchall()
    return [BoundAssessmentEvent(previous_state=row[0], new_state=row[1], recorded_at=row[2], reason=row[3]) for row in rows]


def calculate_reserved_assessment(assessment_id: str) -> BoundAssessmentCalculation:
    assessment_id = _id(assessment_id)
    if not DATABASE_PATH.is_file():
        raise FileNotFoundError("Assessment reservation was not found.")
    if not validation._REVIEWED_WINDOW_LOCK.acquire(blocking=False):
        raise validation.ComparisonBusy("A reviewed windowed comparison is already running in this server process.")
    try:
        with _database() as connection:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='bound_assessments'"
            ).fetchone()
            if not exists:
                raise FileNotFoundError("Assessment reservation was not found.")
            row = connection.execute(
                f"SELECT {_RESERVATION_COLUMNS},candidate_raster FROM bound_assessments WHERE assessment_id=?",
                (assessment_id,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("Assessment reservation was not found.")
            reservation = _reservation_from_row(row[:10])
            if reservation.state != "assessment_reserved":
                raise ValueError("Only a current assessment reservation can be calculated.")
            ref_row = connection.execute(
                "SELECT status,record_json,reference_raster FROM bound_references WHERE reference_id=?",
                (reservation.reference_id,),
            ).fetchone()
            if ref_row is None:
                raise ValueError("Bound reference no longer exists.")
            current = BoundReferenceRecord.model_validate_json(ref_row[1])
            if (
                ref_row[0] != "attestation_recorded"
                or current != reservation.reference_at_reservation
                or current.reference_id != reservation.reference_id
            ):
                raise ValueError("Bound reference or attestation no longer matches the reservation.")
            candidate, reference = bytes(row[10]), bytes(ref_row[2])
            if (
                not candidate or not reference
                or len(candidate) + len(reference) > validation.MAX_UPLOAD_BYTES
                or hashlib.sha256(candidate).hexdigest() != reservation.candidate_sha256
                or hashlib.sha256(reference).hexdigest() != reservation.reference_sha256
                or reservation.candidate_sha256 != current.candidate_sha256
                or reservation.reference_sha256 != current.reference_sha256
            ):
                raise ValueError("Reserved input fingerprint or size is inconsistent.")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS bound_assessment_calculations (
                    assessment_id TEXT PRIMARY KEY REFERENCES bound_assessments(assessment_id),
                    calculated_at TEXT NOT NULL, result_json TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TRIGGER IF NOT EXISTS bound_calculation_no_update
                   BEFORE UPDATE ON bound_assessment_calculations
                   BEGIN SELECT RAISE(ABORT, 'assessment calculation is immutable'); END"""
            )
            connection.execute(
                """CREATE TRIGGER IF NOT EXISTS bound_calculation_no_delete
                   BEFORE DELETE ON bound_assessment_calculations
                   BEGIN SELECT RAISE(ABORT, 'assessment calculation cannot be deleted'); END"""
            )
            previous = connection.execute(
                "SELECT calculated_at,result_json FROM bound_assessment_calculations WHERE assessment_id=?",
                (assessment_id,),
            ).fetchone()
            if previous is not None:
                return BoundAssessmentCalculation(
                    reservation=reservation, calculated_at=previous[0],
                    result=ValidationResult.model_validate_json(previous[1]),
                )
            result = validation._calculate_windowed_masks(candidate, reference, reservation.metadata)
            if (
                hashlib.sha256(candidate).hexdigest() != reservation.candidate_sha256
                or hashlib.sha256(reference).hexdigest() != reservation.reference_sha256
            ):
                raise ValueError("Reserved inputs changed during calculation.")
            result = result.model_copy(update={"validation_id": assessment_id, "report_url": ""})
            timestamp = datetime.now(timezone.utc)
            connection.execute(
                "INSERT INTO bound_assessment_calculations(assessment_id,calculated_at,result_json) VALUES(?,?,?)",
                (assessment_id, timestamp.isoformat(), result.model_dump_json()),
            )
            connection.execute(
                "INSERT INTO bound_assessment_events(assessment_id,previous_state,new_state,recorded_at,reason) VALUES(?,?,?,?,?)",
                (assessment_id, "assessment_reserved", "assessment_reserved", timestamp.isoformat(),
                 "Common-support calculation recorded; evaluation and publication are pending."),
            )
            return BoundAssessmentCalculation(reservation=reservation, calculated_at=timestamp, result=result)
    finally:
        validation._REVIEWED_WINDOW_LOCK.release()
