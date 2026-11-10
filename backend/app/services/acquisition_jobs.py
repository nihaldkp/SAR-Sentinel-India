import json
import logging
import re
import sqlite3
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from app.redaction import redact_sensitive_text
from app.schemas.acquisitions import AcquisitionJob, AcquisitionJobCreate
from app.services import acquisitions
from app.services.rivers import RIVER_CATALOG

LOGGER = logging.getLogger(__name__)
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="satellite-job")
_SCHEDULE_LOCK = threading.Lock()
_SCHEDULED: set[str] = set()


class ActiveJobConflict(RuntimeError):
    pass


class JobNotRetryable(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job_from_row(row: sqlite3.Row) -> AcquisitionJob:
    return AcquisitionJob(
        job_id=row["job_id"],
        river_id=row["river_id"],
        satellite=row["satellite"],
        product_id=row["product_id"],
        job_type=row["job_type"],
        status=row["status"],
        created_at=acquisitions._timestamp(row["created_at"]),
        started_at=acquisitions._timestamp(row["started_at"]),
        completed_at=acquisitions._timestamp(row["completed_at"]),
        progress_percent=row["progress_percent"],
        current_stage=row["current_stage"],
        error_message=row["error_message"],
        output_references=json.loads(row["output_references_json"] or "{}"),
        retry_of_job_id=row["retry_of_job_id"],
    )


def _read_job(job_id: str) -> AcquisitionJob | None:
    with acquisitions._catalog_connection() as connection:
        row = connection.execute(
            "SELECT * FROM acquisition_jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
    return _job_from_row(row) if row else None


def list_jobs(
    river_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[AcquisitionJob]:
    clauses: list[str] = []
    values: list[Any] = []
    if river_id is not None:
        clauses.append("river_id=?")
        values.append(river_id)
    if status is not None:
        clauses.append("status=?")
        values.append(status)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with acquisitions._catalog_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM acquisition_jobs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (*values, limit),
        ).fetchall()
    return [_job_from_row(row) for row in rows]


def get_job(job_id: str) -> AcquisitionJob | None:
    return _read_job(job_id)


def _validate_job_request(request: AcquisitionJobCreate) -> None:
    if request.river_id not in {river.id for river in RIVER_CATALOG}:
        raise ValueError(f"Unknown river identifier: {request.river_id}")
    expected_satellite = (
        "NISAR" if request.job_type.startswith("nisar_") else "SENTINEL-1"
    )
    if request.satellite != expected_satellite:
        raise ValueError("The satellite does not match the requested job type.")
    if request.job_type == "nisar_download":
        with acquisitions._catalog_connection() as connection:
            products = acquisitions._cached_nisar_product_records(connection, request.river_id)
        if not any(product.get("product_id") == request.product_id for product in products):
            raise FileNotFoundError(
                f"NISAR product {request.product_id} is not present in the river's catalog."
            )
    elif request.job_type == "nisar_processing":
        product, _ = acquisitions._nisar_product_record(request.river_id, request.product_id)
        if product.get("download_status") != "downloaded":
            raise ValueError("NISAR processing requires a downloaded and HDF5-verified product.")


def create_job(
    request: AcquisitionJobCreate,
    retry_of_job_id: str | None = None,
) -> AcquisitionJob:
    _validate_job_request(request)
    now = _now().isoformat()
    job_id = str(uuid.uuid4())
    with acquisitions._catalog_connection() as connection:
        try:
            connection.execute(
                """
                INSERT INTO acquisition_jobs (
                    job_id, river_id, satellite, product_id, job_type, status,
                    created_at, progress_percent, current_stage, retry_of_job_id
                ) VALUES (?, ?, ?, ?, ?, 'queued', ?, 0, 'Queued', ?)
                """,
                (
                    job_id,
                    request.river_id,
                    request.satellite,
                    request.product_id,
                    request.job_type,
                    now,
                    retry_of_job_id,
                ),
            )
            connection.commit()
        except sqlite3.IntegrityError as error:
            if "idx_acquisition_jobs_active_product" in str(error) or "UNIQUE constraint failed" in str(error):
                raise ActiveJobConflict(
                    "An active job already exists for this river, product, satellite, and operation."
                ) from error
            raise
    _schedule(job_id)
    job = get_job(job_id)
    if job is None:
        raise RuntimeError("The queued acquisition job could not be read back from SQLite.")
    return job


def retry_job(job_id: str) -> AcquisitionJob:
    previous = get_job(job_id)
    if previous is None:
        raise FileNotFoundError(f"Acquisition job {job_id} was not found.")
    if previous.status != "failed":
        raise JobNotRetryable("Only failed acquisition jobs can be retried.")
    request = AcquisitionJobCreate(
        river_id=previous.river_id,
        satellite=previous.satellite,
        product_id=previous.product_id,
        job_type=previous.job_type,
    )
    return create_job(request, retry_of_job_id=previous.job_id)


def cancel_job(job_id: str) -> AcquisitionJob:
    with acquisitions._catalog_connection() as connection:
        row = connection.execute(
            "SELECT status FROM acquisition_jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"Acquisition job {job_id} was not found.")
        if row["status"] != "queued":
            raise JobNotRetryable("Only queued jobs can be cancelled safely.")
        updated = connection.execute(
            """
            UPDATE acquisition_jobs
            SET status='cancelled', completed_at=?, progress_percent=NULL,
                current_stage='Cancelled before execution'
            WHERE job_id=? AND status='queued'
            """,
            (_now().isoformat(), job_id),
        )
        if updated.rowcount != 1:
            raise JobNotRetryable("The queued job started before it could be cancelled.")
        connection.commit()
    job = get_job(job_id)
    if job is None:
        raise RuntimeError("The cancelled acquisition job could not be read from SQLite.")
    return job


def _update_job(
    job_id: str,
    *,
    status: str,
    stage: str,
    progress_percent: int | None = None,
    error_message: str | None = None,
    output_references: dict[str, str] | None = None,
    started: bool = False,
    completed: bool = False,
) -> None:
    now = _now().isoformat()
    fields = [
        "status=?",
        "current_stage=?",
        "progress_percent=?",
        "error_message=?",
    ]
    values: list[Any] = [status, stage, progress_percent, error_message]
    if output_references is not None:
        fields.append("output_references_json=?")
        values.append(json.dumps(output_references))
    if started:
        fields.append("started_at=COALESCE(started_at, ?)")
        values.append(now)
    if completed:
        fields.append("completed_at=?")
        values.append(now)
    values.append(job_id)
    with acquisitions._catalog_connection() as connection:
        connection.execute(
            f"UPDATE acquisition_jobs SET {', '.join(fields)} WHERE job_id=?",
            values,
        )
        connection.commit()


def _safe_error(error: Exception) -> str:
    message = re.sub(
        r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*",
        "Bearer [REDACTED]",
        str(error),
    )
    message = re.sub(
        r"(?i)(access_token|authorization|token|signature|sig)=([^&\s]+)",
        r"\1=[REDACTED]",
        message,
    )
    return redact_sensitive_text(message)[:2000]


def _run_nisar_download(job: AcquisitionJob) -> dict[str, str]:
    with acquisitions._catalog_connection() as connection:
        products = acquisitions._cached_nisar_product_records(connection, job.river_id)
    product = next(
        (item for item in products if item.get("product_id") == job.product_id),
        None,
    )
    if product is None:
        raise FileNotFoundError("The NISAR product is no longer present in the catalog.")
    session, authentication_error = acquisitions._earthdata_session()
    if session is None:
        raise PermissionError(
            acquisitions._earthdata_authentication_message(authentication_error)
        )
    product.update(
        acquisitions._search_nisar_product_by_id(job.product_id, session)
    )
    access_status, access_message = acquisitions._check_nisar_download(
        product["_download_url"],
        session=session,
    )
    if access_status != "authenticated_access_verified":
        raise PermissionError(access_message)
    _update_job(
        job.job_id,
        status="downloading",
        stage="Downloading NISAR product from ASF to a temporary file",
        started=True,
    )
    product = acquisitions._download_nisar_product(
        job.river_id,
        product,
        session,
        progress_callback=lambda stage: _update_job(
            job.job_id,
            status="processing",
            stage=stage,
            started=True,
        ),
    )
    if product.get("download_status") != "downloaded":
        raise RuntimeError(product.get("message") or "NISAR download did not complete.")
    _update_job(job.job_id, status="processing", stage="Recording verified product metadata")
    acquisitions._save_nisar_product_record(job.river_id, job.product_id, product)
    return {
        "download": f"/api/acquisitions/nisar/{quote(job.product_id, safe='')}/download",
    }


def _run_nisar_processing(job: AcquisitionJob) -> tuple[str, dict[str, str]]:
    _update_job(
        job.job_id,
        status="processing",
        stage="Processing verified NISAR GCOV measurements",
        started=True,
    )
    result = acquisitions.process_nisar_product(job.river_id, job.product_id)
    if result.get("status") == "no_valid_corridor_data":
        return "no_data", {"metadata": result["metadata_url"]}
    return "completed", {
        key: value
        for key, value in {
            "metadata": result.get("metadata_url"),
            "mask": result.get("mask_url"),
            "measurements": result.get("measurements_url"),
            "polygons": result.get("polygons_url"),
            "comparison": result.get("comparison_url"),
            "sensitivity": result.get("sensitivity_url"),
        }.items()
        if isinstance(value, str)
    }


def _run_sentinel1_acquisition(job: AcquisitionJob) -> tuple[str, dict[str, str]]:
    river = next(river for river in RIVER_CATALOG if river.id == job.river_id)
    _update_job(
        job.job_id,
        status="downloading",
        stage="Finding the requested Sentinel-1 RTC scene in the catalog",
        started=True,
    )
    features = acquisitions._item_features(job.river_id, river.centerline.model_dump())
    item = next((feature for feature in features if feature.get("id") == job.product_id), None)
    if item is None:
        raise FileNotFoundError(
            "The requested Sentinel-1 RTC product was not found in the current catalog search window."
        )
    with acquisitions._catalog_connection() as connection:
        previous = connection.execute(
            """
            SELECT analysis_id FROM acquired_products
            WHERE river_id=? AND product_id=? AND status='processed' AND analysis_id IS NOT NULL
            """,
            (job.river_id, job.product_id),
        ).fetchone()
    if previous:
        analysis_id = previous["analysis_id"]
        return "completed", {"analysis": f"/api/analysis/{analysis_id}"}
    with acquisitions._catalog_connection() as connection:
        try:
            result = acquisitions._process_candidate(
                connection,
                job.river_id,
                river.centerline.model_dump(),
                item,
                "",
                stage_callback=lambda status, stage: _update_job(
                    job.job_id,
                    status=status,
                    stage=stage,
                    started=True,
                ),
            )
        except acquisitions.analysis.InsufficientValidDataError as error:
            acquisitions._record_failure(
                connection,
                job.river_id,
                item,
                river.centerline.model_dump(),
                str(error),
                status="no_data",
            )
            return "no_data", {}
        except Exception as error:
            acquisitions._record_failure(
                connection,
                job.river_id,
                item,
                river.centerline.model_dump(),
                _safe_error(error),
            )
            raise
    return "completed", {
        "analysis": result.analysis_url,
        "mask": result.mask_url,
        "polygons": result.polygons_url,
        "report": result.report_url,
    }


def _execute(job_id: str) -> None:
    with acquisitions._catalog_connection() as connection:
        row = connection.execute(
            "SELECT * FROM acquisition_jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
        if row is None:
            return
        claimed = connection.execute(
            """
            UPDATE acquisition_jobs
            SET status='running', started_at=COALESCE(started_at, ?),
                current_stage='Preparing requested satellite operation',
                progress_percent=NULL, error_message=NULL
            WHERE job_id=? AND status='queued'
            """,
            (_now().isoformat(), job_id),
        )
        connection.commit()
        if claimed.rowcount != 1:
            return
    job = _job_from_row(row)
    if job.status != "queued":
        return
    try:
        if job.job_type == "nisar_download":
            references = _run_nisar_download(job)
            final_status = "completed"
        elif job.job_type == "nisar_processing":
            final_status, references = _run_nisar_processing(job)
        else:
            final_status, references = _run_sentinel1_acquisition(job)
        stage = "No valid corridor data; no classification output generated" if final_status == "no_data" else "Completed"
        _update_job(
            job_id,
            status=final_status,
            stage=stage,
            progress_percent=100,
            output_references=references,
            completed=True,
        )
    except Exception as error:
        safe_message = _safe_error(error)
        LOGGER.error("Satellite job %s failed (%s)", job_id, type(error).__name__)
        _update_job(
            job_id,
            status="failed",
            stage="Failed",
            error_message=safe_message,
            completed=True,
        )


def _schedule(job_id: str) -> None:
    with _SCHEDULE_LOCK:
        if job_id in _SCHEDULED:
            return
        _SCHEDULED.add(job_id)
        future = _EXECUTOR.submit(_execute, job_id)

    def clear_scheduled(_: Future[Any]) -> None:
        with _SCHEDULE_LOCK:
            _SCHEDULED.discard(job_id)

    future.add_done_callback(clear_scheduled)


def recover_interrupted_jobs() -> None:
    now = _now().isoformat()
    with acquisitions._catalog_connection() as connection:
        connection.execute(
            """
            UPDATE acquisition_jobs
            SET status='failed', completed_at=?, progress_percent=NULL,
                current_stage='Interrupted by backend restart; safe retry available',
                error_message='The backend stopped before this job completed. Retry to safely restart the operation.'
            WHERE status IN ('running', 'downloading', 'processing')
            """,
            (now,),
        )
        queued = [
            row["job_id"]
            for row in connection.execute(
                "SELECT job_id FROM acquisition_jobs WHERE status='queued'"
            ).fetchall()
        ]
        connection.commit()
    for job_id in queued:
        _schedule(job_id)
