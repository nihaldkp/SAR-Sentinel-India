import asyncio
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import ValidationError

from app.schemas.acquisitions import (
    AcquisitionJob,
    AcquisitionJobCreate,
    AcquisitionJobState,
    AcquisitionStatus,
    NisarComponentSensitivityRequest,
    NisarComponentSensitivityResult,
    NisarProcessingResult,
)
from app.schemas.ai_analysis import RiverAnalysisRequest, RiverAnalysisResponse
from app.schemas.analysis import (
    AnalysisCapabilities,
    AnalysisResult,
    ChangeDetectionRequest,
    ChangeResult,
    RiverAxisSamplingRequest,
    RiverAxisSamplingResult,
    TemporalCandidatePair,
    WaterMaskRequest,
    WidthMeasurementRequest,
    WidthMeasurementResult,
)
from app.schemas.catalog import HealthResponse, Observation, Region
from app.schemas.reference_lifecycle import BoundAssessmentCalculation, BoundAssessmentEvent, BoundAssessmentReservation, BoundReferenceMetadata, BoundReferenceRecord, CandidateIdentity, ReferenceEligibility, ReviewAction
from app.schemas.rivers import River
from app.schemas.satellite import SatelliteSearchResponse
from app.schemas.validation import (
    EvaluationRejection,
    ExploratoryMethodMetadata,
    ExploratoryMethodResult,
    MethodEvaluationMetadata,
    MethodEvaluationResult,
    ReferenceDataImportMetadata,
    ReferenceDataRecord,
    ReferenceDataSource,
    ValidationMetadata,
    ValidationResult,
    ValidationStatus,
    WindowedValidationMetadata,
)
from app.services import analysis
from app.services import acquisitions
from app.services import acquisition_jobs
from app.services import reference_lifecycle
from app.services import ai_analysis
from app.services import nwic_river_explorer
from app.services.analysis import ProcessingUnavailable
from app.services.nisar_gcov import NisarGcovProcessingUnavailable
from app.services.catalog import DEMO_OBSERVATIONS, DEMO_REGIONS
from app.services.rivers import RIVER_CATALOG
from app.services.satellite import search_satellite_catalog
from app.services import validation

router = APIRouter(prefix="/api")
MAX_ANALYSIS_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_METHOD_EVALUATION_UPLOAD_BYTES = 100 * 1024 * 1024


def _validate_analysis_metadata(request: WaterMaskRequest) -> None:
    if request.river_id not in {river.id for river in RIVER_CATALOG}:
        raise HTTPException(status_code=422, detail=f"Unsupported river_id: {request.river_id}")
    supported_products = (
        {"GCOV"}
        if request.mission == "NISAR"
        else {"GRD_HD", "GRD_MD", "GRD_MS", "GRD-RTC"}
    )
    if request.product_type not in supported_products:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{request.mission} {request.product_type} is not accepted by the current "
                "analysis-ready raster workflow. Provide a calibrated, geocoded single-band export."
            ),
        )


@router.get("/health", response_model=HealthResponse, tags=["status"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", data_mode="demonstration")


@router.get("/regions", response_model=list[Region], tags=["catalog"])
def list_regions() -> list[Region]:
    return DEMO_REGIONS


@router.get("/observations", response_model=list[Observation], tags=["catalog"])
def list_observations(
    region_id: str | None = Query(default=None, description="Filter by a supported demo region ID.")
) -> list[Observation]:
    if region_id is not None and not any(region.id == region_id for region in DEMO_REGIONS):
        raise HTTPException(status_code=404, detail=f"Unknown region_id: {region_id}")

    observations = DEMO_OBSERVATIONS
    if region_id is not None:
        observations = [item for item in observations if item.region_id == region_id]
    return observations


@router.get("/rivers", response_model=list[River], tags=["geography"])
def list_rivers() -> list[River]:
    return RIVER_CATALOG


@router.get("/river-network/features", tags=["geography"])
def search_river_network(
    q: str | None = Query(default=None, max_length=200),
    basin: str | None = Query(default=None, max_length=200),
    sub_basin: str | None = Query(default=None, max_length=200),
    state: str | None = Query(default=None, max_length=200),
    district: str | None = Query(default=None, max_length=200),
    west: float | None = Query(default=None, ge=-180, le=180),
    south: float | None = Query(default=None, ge=-90, le=90),
    east: float | None = Query(default=None, ge=-180, le=180),
    north: float | None = Query(default=None, ge=-90, le=90),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> dict[str, Any]:
    bounds = (west, south, east, north)
    if any(value is not None for value in bounds):
        if west is None or south is None or east is None or north is None:
            raise HTTPException(status_code=422, detail="Provide valid west, south, east and north bounds.")
        if west >= east or south >= north:
            raise HTTPException(status_code=422, detail="Provide valid west, south, east and north bounds.")
        bbox = (west, south, east, north)
    else:
        bbox = None
    return nwic_river_explorer.search_features(
        query=q, basin=basin, sub_basin=sub_basin, state=state,
        district=district, bbox=bbox, limit=limit, offset=offset,
    )


@router.get("/river-network/features/{source_object_id}/geometry", tags=["geography"])
def get_river_network_geometry(source_object_id: str) -> dict[str, Any]:
    geometry = nwic_river_explorer.feature_geometry(source_object_id)
    if geometry is None:
        raise HTTPException(status_code=404, detail="NWIC feature not found.")
    return geometry


@router.get("/rivers/{river_id}", response_model=River, tags=["geography"])
def get_river(river_id: str) -> River:
    river = next((item for item in RIVER_CATALOG if item.id == river_id), None)
    if river is None:
        raise HTTPException(status_code=404, detail=f"Unknown river_id: {river_id}")
    return river


@router.get("/satellite/search", response_model=SatelliteSearchResponse, tags=["satellite"])
async def search_satellite(
    river_id: str = Query(description="River used to define the search extent."),
    mission: Literal["NISAR", "SENTINEL-1"] = Query(),
    start_date: date = Query(),
    end_date: date = Query(),
    product_type: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
) -> SatelliteSearchResponse:
    return await search_satellite_catalog(
        river_id=river_id,
        mission=mission,
        start_date=start_date,
        end_date=end_date,
        product_type=product_type,
        limit=limit,
    )


@router.get("/acquisitions", response_model=AcquisitionStatus, tags=["satellite"])
def get_acquisitions() -> AcquisitionStatus:
    return acquisitions.get_catalog_status()


@router.post(
    "/analysis/ai-summary",
    response_model=RiverAnalysisResponse,
    tags=["analysis"],
)
def create_ai_analysis_summary(request: RiverAnalysisRequest) -> RiverAnalysisResponse:
    try:
        return ai_analysis.analyze_river(request.river_id, request.product_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/acquisitions/refresh", response_model=AcquisitionStatus, tags=["satellite"])
async def refresh_acquisitions() -> AcquisitionStatus:
    if not acquisitions.automatic_acquisition_enabled():
        raise HTTPException(status_code=503, detail="Automatic satellite acquisition is disabled.")
    return await acquisitions.refresh_catalog_async()


@router.post(
    "/acquisition-jobs",
    response_model=AcquisitionJob,
    status_code=202,
    tags=["satellite"],
)
def submit_acquisition_job(request: AcquisitionJobCreate) -> AcquisitionJob:
    try:
        return acquisition_jobs.create_job(request)
    except acquisition_jobs.ActiveJobConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get(
    "/acquisition-jobs",
    response_model=list[AcquisitionJob],
    tags=["satellite"],
)
def list_acquisition_jobs(
    river_id: str | None = None,
    status: AcquisitionJobState | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AcquisitionJob]:
    return acquisition_jobs.list_jobs(river_id=river_id, status=status, limit=limit)


@router.get(
    "/acquisition-jobs/{job_id}",
    response_model=AcquisitionJob,
    tags=["satellite"],
)
def get_acquisition_job(job_id: str) -> AcquisitionJob:
    job = acquisition_jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Acquisition job {job_id} was not found.")
    return job


@router.post(
    "/acquisition-jobs/{job_id}/retry",
    response_model=AcquisitionJob,
    status_code=202,
    tags=["satellite"],
)
def retry_acquisition_job(job_id: str) -> AcquisitionJob:
    try:
        return acquisition_jobs.retry_job(job_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except acquisition_jobs.ActiveJobConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except acquisition_jobs.JobNotRetryable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/acquisition-jobs/{job_id}/cancel",
    response_model=AcquisitionJob,
    tags=["satellite"],
)
def cancel_acquisition_job(job_id: str) -> AcquisitionJob:
    try:
        return acquisition_jobs.cancel_job(job_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except acquisition_jobs.JobNotRetryable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/acquisitions/{river_id}/{product_id}/raster", tags=["satellite"])
def download_acquired_raster(river_id: str, product_id: str) -> FileResponse:
    try:
        path = acquisitions.acquired_raster_path(river_id, product_id)
        return FileResponse(path, media_type="image/tiff", filename=f"{product_id}-VV-corridor.tif")
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/acquisitions/nisar/{product_id}/download", tags=["satellite"])
def download_acquired_nisar_product(product_id: str) -> FileResponse:
    try:
        path = acquisitions.nisar_product_path(product_id)
        return FileResponse(path, media_type="application/x-hdf5", filename=path.name)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/acquisitions/nisar/{product_id}/process",
    response_model=NisarProcessingResult,
    tags=["satellite"],
)
def process_acquired_nisar_product(
    product_id: str,
    river_id: str = Query(description="River reference used to define the analysis corridor."),
) -> NisarProcessingResult:
    try:
        return NisarProcessingResult.model_validate(
            acquisitions.process_nisar_product(river_id, product_id)
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except acquisitions.NisarProcessingBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except NisarGcovProcessingUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get(
    "/acquisitions/nisar/{product_id}/processing",
    response_model=NisarProcessingResult,
    tags=["satellite"],
)
def get_nisar_processing_result(
    product_id: str,
    river_id: str = Query(description="River associated with the NISAR product."),
) -> NisarProcessingResult:
    try:
        return NisarProcessingResult.model_validate(
            acquisitions.nisar_processing_result(river_id, product_id)
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/acquisitions/nisar/{product_id}/processing/component-sensitivity",
    response_model=list[NisarComponentSensitivityResult],
    tags=["satellite"],
)
async def create_nisar_component_sensitivity(
    product_id: str,
    request: NisarComponentSensitivityRequest,
    river_id: str = Query(description="River associated with the NISAR candidate mask."),
) -> list[NisarComponentSensitivityResult]:
    try:
        results = await asyncio.to_thread(
            acquisitions.create_nisar_component_sensitivity,
            river_id,
            product_id,
            request.minimum_component_sizes,
        )
        return [
            NisarComponentSensitivityResult.model_validate(result)
            for result in results
        ]
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except acquisitions.NisarProcessingBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except NisarGcovProcessingUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get(
    "/acquisitions/nisar/{product_id}/processing/component-sensitivity/{minimum_component_pixels}",
    response_model=NisarComponentSensitivityResult,
    tags=["satellite"],
)
def get_nisar_component_sensitivity(
    product_id: str,
    minimum_component_pixels: int,
    river_id: str = Query(description="River associated with the NISAR candidate mask."),
) -> NisarComponentSensitivityResult:
    try:
        metadata_path = acquisitions.nisar_component_sensitivity_output_path(
            river_id,
            product_id,
            minimum_component_pixels,
            "metadata",
        )
        return NisarComponentSensitivityResult.model_validate_json(
            metadata_path.read_text(encoding="utf-8")
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get(
    "/acquisitions/nisar/{product_id}/processing/component-sensitivity/{minimum_component_pixels}/mask",
    tags=["satellite"],
)
def download_nisar_component_sensitivity_mask(
    product_id: str,
    minimum_component_pixels: int,
    river_id: str = Query(description="River associated with the NISAR candidate mask."),
) -> FileResponse:
    try:
        path = acquisitions.nisar_component_sensitivity_output_path(
            river_id,
            product_id,
            minimum_component_pixels,
            "mask",
        )
        return FileResponse(
            path,
            media_type="image/tiff",
            filename=f"candidate-sensitivity-min-{minimum_component_pixels}-pixels.tif",
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get(
    "/acquisitions/nisar/{product_id}/processing/sentinel2-reference",
    tags=["satellite"],
)
def get_nisar_sentinel2_reference(
    product_id: str,
    river_id: str = Query(description="River associated with the NISAR product."),
) -> dict[str, Any]:
    try:
        return acquisitions.nisar_optical_reference_metadata(river_id, product_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get(
    "/acquisitions/nisar/{product_id}/processing/sentinel2-reference/preview",
    tags=["satellite"],
)
async def preview_nisar_sentinel2_candidate(
    product_id: str,
    river_id: str = Query(description="River associated with the NISAR product."),
) -> Response:
    try:
        path = acquisitions.nisar_optical_reference_path(river_id, product_id, "mask")
        image = await asyncio.to_thread(
            acquisitions.create_nisar_optical_reference_preview,
            path,
        )
        return Response(content=image, media_type="image/png", headers={"Cache-Control": "no-store"})
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get(
    "/acquisitions/nisar/{product_id}/processing/sentinel2-reference/mask",
    tags=["satellite"],
)
def download_nisar_sentinel2_candidate_mask(
    product_id: str,
    river_id: str = Query(description="River associated with the NISAR product."),
) -> FileResponse:
    try:
        path = acquisitions.nisar_optical_reference_path(river_id, product_id, "mask")
        return FileResponse(
            path,
            media_type="image/tiff",
            filename="sentinel2-ndwi-candidate-mask.tif",
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get(
    "/acquisitions/nisar/{product_id}/processing/sentinel2-observations/"
    "{observation_id}/preview",
    tags=["satellite"],
)
async def preview_nisar_sentinel2_observation(
    product_id: str,
    observation_id: str,
    river_id: str = Query(description="River associated with the NISAR product."),
) -> Response:
    try:
        path = acquisitions.nisar_optical_observation_path(
            river_id, product_id, observation_id, "mask"
        )
        image = await asyncio.to_thread(
            acquisitions.create_nisar_optical_reference_preview,
            path,
        )
        return Response(content=image, media_type="image/png", headers={"Cache-Control": "no-store"})
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get(
    "/acquisitions/nisar/{product_id}/processing/sentinel2-observations/"
    "{observation_id}/mask",
    tags=["satellite"],
)
def download_nisar_sentinel2_observation_mask(
    product_id: str,
    observation_id: str,
    river_id: str = Query(description="River associated with the NISAR product."),
) -> FileResponse:
    try:
        path = acquisitions.nisar_optical_observation_path(
            river_id, product_id, observation_id, "mask"
        )
        return FileResponse(
            path,
            media_type="image/tiff",
            filename=f"{observation_id}-ndwi-candidate-mask.tif",
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/acquisitions/nisar/{product_id}/processing/mask", tags=["satellite"])
def download_nisar_candidate_mask(
    product_id: str,
    river_id: str = Query(description="River associated with the NISAR product."),
) -> FileResponse:
    try:
        path = acquisitions.nisar_processing_output_path(river_id, product_id, "mask")
        return FileResponse(path, media_type="image/tiff", filename="candidate-water-mask.tif")
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/acquisitions/nisar/{product_id}/processing/measurements", tags=["satellite"])
def download_nisar_gcov_measurements(
    product_id: str,
    river_id: str = Query(description="River associated with the NISAR product."),
) -> FileResponse:
    try:
        path = acquisitions.nisar_processing_output_path(river_id, product_id, "measurements")
        return FileResponse(path, media_type="image/tiff", filename="gcov-measurements.tif")
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/acquisitions/nisar/{product_id}/processing/polygons", tags=["satellite"])
def download_nisar_candidate_polygons(
    product_id: str,
    river_id: str = Query(description="River associated with the NISAR product."),
) -> FileResponse:
    try:
        path = acquisitions.nisar_processing_output_path(river_id, product_id, "polygons")
        return FileResponse(path, media_type="application/geo+json", filename="candidate-water.geojson")
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/acquisitions/nisar/{product_id}/processing/comparison", tags=["satellite"])
def download_nisar_polarization_comparison(
    product_id: str,
    river_id: str = Query(description="River associated with the NISAR product."),
) -> FileResponse:
    try:
        path = acquisitions.nisar_processing_output_path(river_id, product_id, "comparison")
        return FileResponse(path, media_type="image/tiff", filename="polarization-comparison.tif")
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/acquisitions/nisar/{product_id}/processing/sensitivity", tags=["satellite"])
def download_nisar_threshold_sensitivity(
    product_id: str,
    river_id: str = Query(description="River associated with the NISAR product."),
) -> FileResponse:
    try:
        path = acquisitions.nisar_processing_output_path(river_id, product_id, "sensitivity")
        return FileResponse(path, media_type="image/tiff", filename="threshold-sensitivity.tif")
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/analysis/status", response_model=AnalysisCapabilities, tags=["analysis"])
def get_analysis_capabilities() -> AnalysisCapabilities:
    try:
        analysis._require_rasterio()
    except ProcessingUnavailable as error:
        return AnalysisCapabilities(
            geotiff_processing_available=False,
            rasterio_available=False,
            input_requirement="Single-band calibrated GeoTIFF in a projected metre-based CRS.",
            unavailable_reason=str(error),
        )
    return AnalysisCapabilities(
        geotiff_processing_available=True,
        rasterio_available=True,
        input_requirement="Single-band calibrated GeoTIFF in a projected metre-based CRS.",
    )


@router.get(
    "/analysis/validation/status",
    response_model=ValidationStatus,
    tags=["analysis"],
)
def get_validation_status() -> ValidationStatus:
    try:
        return validation.validation_status()
    except validation.ValidationUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get(
    "/analysis/reference-sources",
    response_model=list[ReferenceDataSource],
    tags=["analysis"],
)
def get_reference_data_sources() -> list[ReferenceDataSource]:
    return validation.reference_data_sources()


@router.post("/analysis/bound-references", response_model=BoundReferenceRecord, status_code=201, tags=["analysis"])
async def import_bound_reference(
    candidate_file: UploadFile = File(),
    reference_file: UploadFile = File(),
    metadata_json: str = Form(),
) -> BoundReferenceRecord:
    uploads = (candidate_file, reference_file)
    try:
        if any(not upload.filename or Path(upload.filename).suffix.casefold() not in {".tif", ".tiff"} for upload in uploads):
            raise HTTPException(status_code=422, detail="Upload candidate and reference GeoTIFF files.")
        try:
            metadata = BoundReferenceMetadata.model_validate_json(metadata_json)
        except ValidationError as error:
            raise HTTPException(
                status_code=422,
                detail=error.errors(include_input=False, include_context=False, include_url=False),
            ) from error
        candidate = await candidate_file.read(validation.MAX_UPLOAD_BYTES + 1)
        reference = await reference_file.read(max(0, validation.MAX_UPLOAD_BYTES - len(candidate)) + 1)
        if len(candidate) + len(reference) > validation.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Combined GeoTIFF uploads are limited to 100 MB.")
        try:
            return await asyncio.to_thread(reference_lifecycle.import_bound_reference, candidate, reference, metadata)
        except validation.ComparisonBusy as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except validation.ValidationUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        for upload in uploads:
            await upload.close()


@router.get("/analysis/bound-references", response_model=list[BoundReferenceRecord], tags=["analysis"])
def list_bound_references() -> list[BoundReferenceRecord]:
    try:
        return reference_lifecycle.list_bound_references()
    except validation.ComparisonBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/analysis/bound-references/{reference_id}", response_model=BoundReferenceRecord, tags=["analysis"])
def get_bound_reference(reference_id: str) -> BoundReferenceRecord:
    try:
        return reference_lifecycle.get_bound_reference(reference_id)
    except validation.ComparisonBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/analysis/bound-references/{reference_id}/review", response_model=BoundReferenceRecord, tags=["analysis"])
async def transition_bound_reference(reference_id: str, action: ReviewAction) -> BoundReferenceRecord:
    try:
        return await asyncio.to_thread(reference_lifecycle.transition_review, reference_id, action)
    except validation.ComparisonBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/analysis/bound-references/{reference_id}/eligibility", response_model=ReferenceEligibility, tags=["analysis"])
async def check_bound_reference_eligibility(
    reference_id: str, candidate_file: UploadFile = File(), identity_json: str = Form(),
) -> ReferenceEligibility:
    try:
        if not candidate_file.filename or Path(candidate_file.filename).suffix.casefold() not in {".tif", ".tiff"}:
            raise HTTPException(status_code=422, detail="Upload a candidate GeoTIFF.")
        try:
            identity = CandidateIdentity.model_validate_json(identity_json)
        except ValidationError as error:
            raise HTTPException(
                status_code=422,
                detail=error.errors(include_input=False, include_context=False, include_url=False),
            ) from error
        candidate = await candidate_file.read(validation.MAX_UPLOAD_BYTES + 1)
        if len(candidate) > validation.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Candidate GeoTIFF is limited to 100 MB.")
        try:
            return await asyncio.to_thread(reference_lifecycle.check_eligibility, reference_id, candidate, identity)
        except validation.ComparisonBusy as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except validation.ValidationUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        await candidate_file.close()


@router.get("/analysis/bound-references/{reference_id}/eligibility", response_model=list[ReferenceEligibility], tags=["analysis"])
def list_bound_reference_eligibility_checks(reference_id: str) -> list[ReferenceEligibility]:
    try:
        return reference_lifecycle.list_eligibility_checks(reference_id)
    except validation.ComparisonBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/analysis/bound-references/{reference_id}/labels", tags=["analysis"])
def download_bound_reference(reference_id: str) -> Response:
    try:
        raster = reference_lifecycle.reference_raster(reference_id)
        return Response(content=raster, media_type="image/tiff")
    except validation.ComparisonBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/analysis/bound-assessment-reservations/{assessment_id}", response_model=BoundAssessmentReservation, tags=["analysis"])
async def reserve_bound_assessment(
    assessment_id: str, reference_id: str = Form(), metadata_json: str = Form(), candidate_file: UploadFile = File(),
) -> BoundAssessmentReservation:
    try:
        if not candidate_file.filename or Path(candidate_file.filename).suffix.casefold() not in {".tif", ".tiff"}:
            raise HTTPException(status_code=422, detail="Upload a candidate GeoTIFF.")
        try:
            metadata = WindowedValidationMetadata.model_validate_json(metadata_json)
        except ValidationError as error:
            raise HTTPException(
                status_code=422, detail=error.errors(include_input=False, include_context=False, include_url=False),
            ) from error
        candidate = await candidate_file.read(validation.MAX_UPLOAD_BYTES + 1)
        if len(candidate) > validation.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Candidate GeoTIFF is limited to 100 MB.")
        try:
            return await asyncio.to_thread(reference_lifecycle.reserve_assessment, assessment_id, reference_id, candidate, metadata)
        except validation.ComparisonBusy as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except validation.ValidationUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        await candidate_file.close()


@router.get("/analysis/bound-assessment-reservations/{assessment_id}", response_model=BoundAssessmentReservation, tags=["analysis"])
def get_bound_assessment_reservation(assessment_id: str) -> BoundAssessmentReservation:
    try:
        return reference_lifecycle.get_assessment_reservation(assessment_id)
    except validation.ComparisonBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/analysis/bound-assessment-reservations/{assessment_id}/events", response_model=list[BoundAssessmentEvent], tags=["analysis"])
def list_bound_assessment_events(assessment_id: str) -> list[BoundAssessmentEvent]:
    try:
        return reference_lifecycle.list_assessment_events(assessment_id)
    except validation.ComparisonBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/analysis/bound-assessment-reservations/{assessment_id}/calculate", response_model=BoundAssessmentCalculation, tags=["analysis"])
async def calculate_bound_assessment(assessment_id: str) -> BoundAssessmentCalculation:
    try:
        return await asyncio.to_thread(reference_lifecycle.calculate_reserved_assessment, assessment_id)
    except validation.ComparisonBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except validation.ValidationUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get(
    "/analysis/reference-data",
    response_model=list[ReferenceDataRecord],
    tags=["analysis"],
)
def list_imported_reference_data() -> list[ReferenceDataRecord]:
    return validation.list_reference_data()


@router.post(
    "/analysis/reference-data",
    response_model=ReferenceDataRecord,
    status_code=201,
    tags=["analysis"],
)
async def import_reviewed_reference_data(
    reference_file: UploadFile = File(description="Reviewed GeoTIFF labels (0 non-water, 1 water, 255 uncertain)."),
    metadata_json: str = Form(description="Source, acquisition, reviewer, and license provenance."),
) -> ReferenceDataRecord:
    if not reference_file.filename or Path(reference_file.filename).suffix.casefold() not in {".tif", ".tiff"}:
        raise HTTPException(status_code=422, detail="Upload a reviewed reference GeoTIFF.")
    try:
        metadata = ReferenceDataImportMetadata.model_validate_json(metadata_json)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        raster_bytes = await reference_file.read(validation.MAX_UPLOAD_BYTES + 1)
    finally:
        await reference_file.close()
    if len(raster_bytes) > validation.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Reference GeoTIFF uploads are limited to 100 MB.")
    try:
        return await asyncio.to_thread(validation.import_reviewed_reference_data, raster_bytes, metadata)
    except validation.ValidationUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get(
    "/analysis/reference-data/{reference_id}/labels",
    tags=["analysis"],
)
def download_reference_data_labels(reference_id: str) -> FileResponse:
    try:
        path, record = validation.reference_data_labels_path(reference_id)
        return FileResponse(
            path,
            media_type="image/tiff",
            filename=f"{record.reference_id}-reviewed-reference-labels.tif",
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/analysis/validation/methods",
    response_model=MethodEvaluationResult,
    status_code=201,
    tags=["analysis"],
)
async def evaluate_classification_methods(
    reference_file: UploadFile = File(description="Independently reviewed reference labels (0/1/255)."),
    candidate_files: list[UploadFile] = File(description="One candidate mask GeoTIFF for each declared method."),
    metadata_json: str = Form(description="Reference metadata and ordered method descriptors."),
) -> MethodEvaluationResult:
    uploads = [reference_file, *candidate_files]
    try:
        if len(candidate_files) < 2 or len(candidate_files) > 8:
            raise HTTPException(status_code=422, detail="Submit between two and eight candidate method rasters.")
        if any(not upload.filename or Path(upload.filename).suffix.casefold() not in {".tif", ".tiff"} for upload in uploads):
            raise HTTPException(status_code=422, detail="All method and reference files must be GeoTIFFs.")
        try:
            metadata = MethodEvaluationMetadata.model_validate_json(metadata_json)
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if len(metadata.methods) != len(candidate_files):
            raise HTTPException(status_code=422, detail="Provide exactly one GeoTIFF for each method descriptor.")
        total_bytes = 0
        raster_contents: list[bytes] = []
        for upload in uploads:
            remaining_limit = MAX_METHOD_EVALUATION_UPLOAD_BYTES - total_bytes
            contents = await upload.read(remaining_limit + 1)
            total_bytes += len(contents)
            if total_bytes > MAX_METHOD_EVALUATION_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Combined reference and method GeoTIFF uploads are limited to 100 MB.",
                )
            raster_contents.append(contents)
        reference_bytes, *candidate_bytes = raster_contents
        try:
            return await asyncio.to_thread(
                validation.compare_classification_methods,
                candidate_bytes,
                reference_bytes,
                metadata,
            )
        except validation.ValidationUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        for upload in uploads:
            await upload.close()


@router.post(
    "/analysis/validation/methods/exploratory",
    response_model=ExploratoryMethodResult,
    tags=["analysis"],
)
async def compare_exploratory_classification_methods(
    candidate_files: list[UploadFile] = File(description="Candidate mask GeoTIFFs."),
    metadata_json: str = Form(description="Candidate provenance and ordered method descriptors."),
) -> ExploratoryMethodResult:
    try:
        if not 2 <= len(candidate_files) <= 8:
            raise HTTPException(status_code=422, detail="Submit between two and eight candidate method rasters.")
        if any(not upload.filename or Path(upload.filename).suffix.casefold() not in {".tif", ".tiff"} for upload in candidate_files):
            raise HTTPException(status_code=422, detail="All method files must be GeoTIFFs.")
        try:
            metadata = ExploratoryMethodMetadata.model_validate_json(metadata_json)
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if len(metadata.methods) != len(candidate_files):
            raise HTTPException(status_code=422, detail="Provide exactly one GeoTIFF for each method descriptor.")
        total_bytes = 0
        contents = []
        for upload in candidate_files:
            raster = await upload.read(MAX_METHOD_EVALUATION_UPLOAD_BYTES - total_bytes + 1)
            total_bytes += len(raster)
            if total_bytes > MAX_METHOD_EVALUATION_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Combined method GeoTIFF uploads are limited to 100 MB.")
            contents.append(raster)
        try:
            return await asyncio.to_thread(validation.compare_exploratory_methods, contents, metadata)
        except validation.ComparisonBusy as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except validation.ValidationUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        for upload in candidate_files:
            await upload.close()


@router.get(
    "/analysis/validation/method-comparisons/{evaluation_id}",
    response_model=MethodEvaluationResult,
    tags=["analysis"],
)
def get_method_comparison_report(evaluation_id: str) -> MethodEvaluationResult:
    try:
        return validation.get_method_evaluation_report(evaluation_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/analysis/validation",
    response_model=ValidationResult,
    status_code=201,
    tags=["analysis"],
)
async def validate_candidate_mask(
    candidate_file: UploadFile = File(description="Candidate mask GeoTIFF with 0/1/255 classes."),
    reference_file: UploadFile = File(description="Independently reviewed label GeoTIFF with 0/1/255 classes."),
    metadata_json: str = Form(description="Reference provenance and candidate product metadata."),
) -> ValidationResult:
    for uploaded_file in (candidate_file, reference_file):
        if not uploaded_file.filename or Path(uploaded_file.filename).suffix.casefold() not in {
            ".tif",
            ".tiff",
        }:
            raise HTTPException(status_code=422, detail="Upload candidate and reference GeoTIFF files.")
    try:
        metadata = ValidationMetadata.model_validate_json(metadata_json)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        candidate_bytes = await candidate_file.read(validation.MAX_UPLOAD_BYTES + 1)
        reference_bytes = await reference_file.read(validation.MAX_UPLOAD_BYTES + 1)
    finally:
        await candidate_file.close()
        await reference_file.close()
    if len(candidate_bytes) > validation.MAX_UPLOAD_BYTES or len(reference_bytes) > validation.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Each validation GeoTIFF is limited to 100 MB.")
    try:
        return await asyncio.to_thread(
            validation.compare_independent_masks,
            candidate_bytes,
            reference_bytes,
            metadata,
        )
    except validation.ValidationUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/analysis/validation/windowed-assessments",
    response_model=ValidationResult,
    status_code=201,
    tags=["analysis"],
)
async def assess_windowed_validation(
    candidate_file: UploadFile = File(),
    reference_file: UploadFile = File(),
    metadata_json: str = Form(),
) -> ValidationResult:
    uploads = (candidate_file, reference_file)
    try:
        if any(not upload.filename or Path(upload.filename).suffix.casefold() not in {".tif", ".tiff"} for upload in uploads):
            raise HTTPException(status_code=422, detail="Upload candidate and reference GeoTIFF files.")
        try:
            metadata = WindowedValidationMetadata.model_validate_json(metadata_json)
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        candidate_bytes = await candidate_file.read(validation.MAX_UPLOAD_BYTES + 1)
        remaining = max(0, validation.MAX_UPLOAD_BYTES - len(candidate_bytes))
        reference_bytes = await reference_file.read(remaining + 1)
        if len(candidate_bytes) + len(reference_bytes) > validation.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Combined GeoTIFF uploads are limited to 100 MB.")
        try:
            return await asyncio.to_thread(validation.assess_windowed_masks, candidate_bytes, reference_bytes, metadata)
        except validation.ComparisonBusy as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except validation.ValidationUnavailable as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        for upload in uploads:
            await upload.close()


@router.post(
    "/analysis/validation/windowed-assessments/{validation_id}/evaluate",
    response_model=ValidationResult,
    tags=["analysis"],
)
async def evaluate_windowed_assessment(validation_id: str) -> ValidationResult:
    try:
        return await asyncio.to_thread(validation.evaluate_windowed_assessment, validation_id)
    except validation.ComparisonBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/analysis/validation/windowed-assessments/{validation_id}/reject",
    response_model=ValidationResult,
    tags=["analysis"],
)
async def reject_windowed_assessment(validation_id: str, request: EvaluationRejection) -> ValidationResult:
    try:
        return await asyncio.to_thread(validation.reject_windowed_assessment, validation_id, request.reason)
    except validation.ComparisonBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get(
    "/analysis/validation/{validation_id}",
    response_model=ValidationResult,
    tags=["analysis"],
)
def get_validation_report(validation_id: str) -> ValidationResult:
    try:
        return validation.get_validation_report(validation_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/analysis/water-mask", response_model=AnalysisResult, tags=["analysis"])
async def create_water_mask(
    file: UploadFile = File(description="Single-band, calibrated GeoTIFF in a projected metre-based CRS."),
    metadata_json: str = Form(description="JSON fields described by the WaterMaskRequest schema."),
) -> AnalysisResult:
    if not file.filename or Path(file.filename).suffix.casefold() not in {".tif", ".tiff"}:
        raise HTTPException(status_code=422, detail="Upload a GeoTIFF file with a .tif or .tiff extension.")
    try:
        request = WaterMaskRequest.model_validate_json(metadata_json)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    _validate_analysis_metadata(request)
    try:
        raster_bytes = await file.read(MAX_ANALYSIS_UPLOAD_BYTES + 1)
    finally:
        await file.close()
    if len(raster_bytes) > MAX_ANALYSIS_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="GeoTIFF uploads are limited to 100 MB.")
    try:
        return await asyncio.to_thread(analysis.process_water_mask, raster_bytes, request)
    except ProcessingUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/analysis/change", response_model=ChangeResult, tags=["analysis"])
def create_water_change_comparison(request: ChangeDetectionRequest) -> ChangeResult:
    try:
        return analysis.compare_water_masks(request)
    except ProcessingUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get(
    "/analysis/temporal-pairs",
    response_model=list[TemporalCandidatePair],
    tags=["analysis"],
)
def list_temporal_candidate_pairs(
    river_id: Literal["kaveri", "tungabhadra"] = Query(),
) -> list[TemporalCandidatePair]:
    catalog = acquisitions.get_catalog_status()
    river_status = next((river for river in catalog.rivers if river.river_id == river_id), None)
    if river_status is None:
        raise HTTPException(status_code=404, detail=f"Unknown river_id: {river_id}")
    try:
        return analysis.list_compatible_candidate_pairs(river_status.observations)
    except FileNotFoundError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ProcessingUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/analysis/width", response_model=WidthMeasurementResult, tags=["analysis"])
def create_width_measurement(request: WidthMeasurementRequest) -> WidthMeasurementResult:
    try:
        return analysis.measure_water_width(request)
    except ProcessingUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/analysis/width/river-axis",
    response_model=RiverAxisSamplingResult,
    tags=["analysis"],
)
def sample_widths_along_river_axis(request: RiverAxisSamplingRequest) -> RiverAxisSamplingResult:
    try:
        return analysis.sample_candidate_widths_along_axis(request)
    except ProcessingUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/analysis/{analysis_id}", tags=["analysis"])
def get_analysis(analysis_id: str) -> dict:
    try:
        return analysis._load_result(analysis_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/analysis/{analysis_id}/mask", tags=["analysis"])
def download_analysis_mask(analysis_id: str) -> FileResponse:
    try:
        result = analysis._load_result(analysis_id)
        filename = "water-mask.tif" if result["analysis_type"] == "water_mask" else "change-mask.tif"
        path, _ = analysis.read_output(analysis_id, filename)
        return FileResponse(path, media_type="image/tiff", filename=filename)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/analysis/{analysis_id}/polygons", tags=["analysis"])
def download_analysis_polygons(analysis_id: str) -> FileResponse:
    try:
        path, _ = analysis.read_output(analysis_id, "water-polygons.geojson")
        return FileResponse(path, media_type="application/geo+json", filename="water-polygons.geojson")
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/analysis/{analysis_id}/report", tags=["analysis"])
def download_analysis_report(analysis_id: str) -> StreamingResponse:
    try:
        report: BytesIO = analysis.build_pdf_report(analysis_id)
        return StreamingResponse(
            report,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="sar-sentinel-{analysis_id}.pdf"'},
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
