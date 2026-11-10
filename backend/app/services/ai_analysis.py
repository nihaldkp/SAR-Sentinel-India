import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from app.schemas.acquisitions import AcquisitionStatus, NisarProduct
from app.schemas.ai_analysis import (
    AnalysisCoverage,
    AnalysisProductOption,
    CandidateMetrics,
    EvidenceStatus,
    OpticalComparison,
    RiverAnalysisResponse,
    TemporalComparison,
    ThresholdSensitivity,
)
from app.services import acquisitions
from app.services import analysis as analysis_service
from app.services import validation


_BASE_LIMITATIONS = [
    "Candidate classifications are exploratory; submitted review attestations and source independence are not authenticated.",
    "This summary does not calculate or display confusion matrices or accuracy scores.",
    "Water-candidate area is not a verified river boundary or river width measurement.",
    "Water-extent differences do not establish floods, erosion, deposition, or riverbank change.",
]


def _evidence_status(river_id: str, product: AnalysisProductOption | None) -> tuple[EvidenceStatus, str]:
    reports = validation.list_validation_reports()
    matching = [
        report for report in reports
        if product is not None
        and report.river_id == river_id
        and report.candidate_product_id == product.product_id
        and product.acquisition_start is not None
        and report.candidate_acquisition_datetime == product.acquisition_start
        and product.processing_version is not None
        and report.candidate_processing_version == product.processing_version
    ]
    if matching:
        if product.satellite != "NISAR":
            return "candidate_identity_unverified", "Submitted assessments match declared metadata, but the selected candidate raster identity cannot be verified."
        try:
            path = acquisitions.nisar_processing_output_path(river_id, product.product_id, "mask")
            if path.stat().st_size > validation.MAX_UPLOAD_BYTES:
                return "candidate_identity_unverified", "The selected candidate raster exceeds the identity-check size limit; submitted assessments are not linked."
            digest = hashlib.sha256()
            bytes_read = 0
            with path.open("rb") as candidate:
                for chunk in iter(lambda: candidate.read(1024 * 1024), b""):
                    bytes_read += len(chunk)
                    if bytes_read > validation.MAX_UPLOAD_BYTES:
                        return "candidate_identity_unverified", "The selected candidate raster exceeds the identity-check size limit; submitted assessments are not linked."
                    digest.update(chunk)
            candidate_digest = digest.hexdigest()
            matching = [
                report for report in matching
                if report.processing and report.processing.get("candidate_sha256") == candidate_digest
            ]
        except (FileNotFoundError, OSError, ValueError):
            return "candidate_identity_unverified", "The selected candidate raster could not be checked; submitted assessments are not linked."
        if not matching:
            return "candidate_identity_unverified", "Submitted assessment raster fingerprints do not match the selected candidate; assessments are not linked."
    if any(report.status == "validation_completed" and report.independent_review_completed for report in matching):
        return (
            "sample_validation_completed",
            "A submitted review-attested sample met the recorded thresholds for this product and date. "
            "The application cannot authenticate independence, review or representativeness; this is not scientific certification.",
        )
    if any(report.status == "thresholds_met_awaiting_evaluation" for report in matching):
        return "thresholds_met_awaiting_evaluation", "A matching submitted assessment meets its declared thresholds and awaits evaluation; source identity and attestations are not authenticated."
    if any(report.status == "insufficient_evidence" for report in matching):
        return "evidence_thresholds_unmet", "A matching submitted report lacks or does not meet the recorded evidence thresholds; scores are withheld."
    if any(report.status in {"evaluation_failed", "evaluation_rejected"} for report in matching):
        return "evaluation_rejected_or_failed", "A matching submitted assessment was rejected or failed evaluation; scores were not produced. Attestations are not authenticated."
    if matching:
        return "insufficient_valid_labels", "A matching submitted report lacks sufficient valid reference labels or spatial overlap."
    references = validation.list_reference_data()
    if any(record.metadata.independent_review_completed for record in references):
        return (
            "reviewed_reference_available",
            "A reference with a submitted review attestation is available, but its applicability to this river and product is not established; review is not authenticated.",
        )
    if references:
        return "reference_imported_unreviewed", "An imported reference exists without a recorded review attestation; its suitability is unknown."
    return "independent_reference_unavailable", "No imported reference or matching validation report is available."


def _fraction(value: float | None) -> float | None:
    return value


def _option_is_usable(product: NisarProduct) -> bool:
    result = product.processing_result
    return bool(
        result
        and result.status == "unvalidated_candidate"
        and result.valid_pixel_count > 0
        and result.candidate_water_area_m2 is not None
    )


def _options_for_river(river_status) -> list[AnalysisProductOption]:
    options = [
        AnalysisProductOption(
            product_id=product.product_id,
            satellite="NISAR",
            acquisition_start=product.acquisition_start,
            acquisition_end=product.acquisition_end,
            processing_status=product.processing_status,
            processing_version=product.processing_result.processor_version if product.processing_result else None,
            is_usable_candidate=_option_is_usable(product),
            valid_data_fraction=(
                _fraction(product.processing_result.valid_data_fraction)
                if product.processing_result
                else None
            ),
            source_name="ASF DAAC",
            product_type=product.product_level,
            polarization=(
                product.processing_result.polarization
                if product.processing_result
                else product.polarization or []
            ),
            input_crs=(
                product.processing_result.input_crs
                if product.processing_result
                else None
            ),
            pixel_size_m=(
                product.processing_result.pixel_size_m
                if product.processing_result
                else None
            ),
        )
        for product in river_status.nisar_products
    ]
    options.extend(
        AnalysisProductOption(
            product_id=observation.product_id,
            satellite="SENTINEL-1",
            acquisition_start=observation.acquisition_start,
            acquisition_end=observation.acquisition_end,
            processing_status=observation.processing_status,
            is_usable_candidate=(
                observation.valid_pixel_count > 0
                and observation.candidate_water_area_m2 >= 0
            ),
            valid_data_fraction=_fraction(observation.valid_data_fraction),
            source_name=observation.source,
            source_record_url=observation.stac_item_url,
            source_license=observation.source_license,
            product_type=observation.product_type,
            polarization=[observation.polarization],
            input_crs=observation.input_crs,
            pixel_size_m=observation.pixel_size_m,
        )
        for observation in river_status.observations
    )
    options.extend(
        AnalysisProductOption(
            product_id=issue.product_id,
            satellite="SENTINEL-1",
            acquisition_start=None,
            processing_status=issue.status,
            is_usable_candidate=False,
            source_name="Microsoft Planetary Computer Sentinel-1 RTC",
        )
        for issue in river_status.issues
    )
    return sorted(
        options,
        key=lambda item: item.acquisition_start or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )


def _selected_nisar_product(river_status, product_id: str | None) -> NisarProduct | None:
    products = river_status.nisar_products
    if product_id is not None:
        return next((product for product in products if product.product_id == product_id), None)
    usable = [product for product in products if _option_is_usable(product)]
    if usable:
        return max(usable, key=lambda product: product.acquisition_start or datetime.min.replace(tzinfo=timezone.utc))
    return max(
        products,
        key=lambda product: product.acquisition_start or datetime.min.replace(tzinfo=timezone.utc),
        default=None,
    )


def _selected_observation(river_status, product_id: str | None):
    observations = river_status.observations
    if product_id is not None:
        return next((item for item in observations if item.product_id == product_id), None)
    return max(observations, key=lambda item: item.acquisition_start, default=None)


def _sensitivity(result) -> ThresholdSensitivity:
    samples = result.threshold_sensitivity
    areas = [
        float(sample.get("candidate_area_m2", sample.get("candidate_water_area_m2"))) / 1_000_000
        for sample in samples
        if "candidate_area_m2" in sample or "candidate_water_area_m2" in sample
    ]
    area_range_percent = (
        (max(areas) - min(areas)) / (result.candidate_water_area_m2 / 1_000_000) * 100
        if areas and result.candidate_water_area_m2
        else None
    )
    return ThresholdSensitivity(
        samples=samples,
        candidate_area_min_km2=min(areas) if areas else None,
        candidate_area_max_km2=max(areas) if areas else None,
        candidate_area_range_percent=area_range_percent,
        interpretation=(
            "Exploratory candidate-area sensitivity to the recorded threshold perturbations; "
            "it is not classification confidence or validation."
        ),
    )


def _nisar_metrics(product: NisarProduct | None) -> tuple[CandidateMetrics | None, ThresholdSensitivity | None, list[dict]]:
    result = product.processing_result if product else None
    if result is None:
        return None, None, []
    valid_fraction = _fraction(result.valid_data_fraction)
    return (
        CandidateMetrics(
            classification_status=result.status,
            candidate_water_pixel_count=result.water_pixel_count,
            candidate_water_area_km2=(
                result.candidate_water_area_m2 / 1_000_000
                if result.candidate_water_area_m2 is not None
                else None
            ),
            valid_pixel_count=result.valid_pixel_count,
            corridor_pixel_count=result.corridor_pixel_count,
            valid_data_fraction=valid_fraction,
            no_data_fraction=1.0 - valid_fraction if valid_fraction is not None else None,
            hh_threshold_db=result.hh_threshold_db,
            hv_threshold_db=result.hv_threshold_db,
        ),
        _sensitivity(result),
        result.polarization_comparison,
    )


def _sentinel1_metrics(observation) -> CandidateMetrics:
    valid_fraction = _fraction(observation.valid_data_fraction)
    return CandidateMetrics(
        classification_status=observation.processing_status,
        candidate_water_pixel_count=observation.water_pixel_count,
        candidate_water_area_km2=observation.candidate_water_area_m2 / 1_000_000,
        valid_pixel_count=observation.valid_pixel_count,
        valid_data_fraction=valid_fraction,
        no_data_fraction=1.0 - valid_fraction if valid_fraction is not None else None,
        threshold_db=observation.threshold_db,
    )


def _optical_comparison(river_id: str, product: NisarProduct | None) -> OpticalComparison:
    result = product.processing_result if product else None
    if not result or not result.optical_reference_url or not result.optical_candidate_mask_url:
        return OpticalComparison(
            available=False,
            status="not_available",
            warning="No persisted Sentinel-2 candidate raster is linked to this NISAR product.",
        )
    metadata = acquisitions.nisar_optical_reference_metadata(river_id, product.product_id)
    source = metadata.get("source", {})
    counts = metadata.get("counts", {})
    acquisition_start = source.get("acquisition_datetime")
    optical_time = (
        datetime.fromisoformat(acquisition_start.replace("Z", "+00:00"))
        if isinstance(acquisition_start, str)
        else None
    )
    time_difference_seconds = (
        abs((optical_time - result.acquisition_start).total_seconds())
        if optical_time is not None and result.acquisition_start is not None
        else None
    )
    grid = metadata.get("grid", {})
    pixel_area_m2 = grid.get("pixel_area_m2")
    common_area_km2 = (
        counts["common_valid_pixels"] * pixel_area_m2 / 1_000_000
        if isinstance(pixel_area_m2, (int, float))
        and isinstance(counts.get("common_valid_pixels"), int)
        else None
    )
    candidate_area_km2 = (
        counts["candidate_area_m2"] / 1_000_000
        if isinstance(counts.get("candidate_area_m2"), (int, float))
        else None
    )
    return OpticalComparison(
        available=True,
        status="exploratory_candidate_only",
        source_product_id=source.get("item_id"),
        acquisition_start=optical_time,
        time_difference_seconds=time_difference_seconds,
        common_valid_pixel_count=counts.get("common_valid_pixels"),
        common_valid_area_km2=common_area_km2,
        candidate_water_pixel_count=counts.get("ndwi_candidate_pixels"),
        candidate_water_area_km2=candidate_area_km2,
        ndwi_threshold=metadata.get("ndwi_threshold"),
        warning=(
            "Sentinel-2 NDWI is an exploratory candidate classification, not ground truth; "
            "area agreement must not be interpreted as accuracy."
        ),
    )


def build_river_analysis(
    catalog: AcquisitionStatus,
    river_id: str,
    product_id: str | None = None,
) -> RiverAnalysisResponse:
    river_status = next((item for item in catalog.rivers if item.river_id == river_id), None)
    if river_status is None:
        raise LookupError(f"Unknown river_id: {river_id}")

    products = _options_for_river(river_status)
    selected_option = (
        next((item for item in products if item.product_id == product_id), None)
        if product_id is not None
        else next(
            (
                item for item in products
                if item.satellite == "NISAR" and item.is_usable_candidate
            ),
            next((item for item in products if item.is_usable_candidate), products[0] if products else None),
        )
    )
    if product_id is not None and selected_option is None:
        raise LookupError(f"Unknown product_id for {river_id}: {product_id}")

    selected_nisar = None
    selected_observation = None
    if selected_option:
        if selected_option.satellite == "NISAR":
            selected_nisar = _selected_nisar_product(river_status, selected_option.product_id)
        else:
            selected_observation = _selected_observation(river_status, selected_option.product_id)

    candidate_metrics = None
    sensitivity = None
    polarization_comparison: list[dict] = []
    centerline_coverage = None
    corridor_half_width = None
    if selected_nisar:
        candidate_metrics, sensitivity, polarization_comparison = _nisar_metrics(selected_nisar)
        if selected_nisar.processing_result:
            centerline_coverage = selected_nisar.processing_result.reference_centerline_coverage_percent
            corridor_half_width = selected_nisar.processing_result.corridor_half_width_m
    elif selected_observation:
        candidate_metrics = _sentinel1_metrics(selected_observation)
        centerline_coverage = selected_observation.centerline_coverage_percent
        corridor_half_width = selected_observation.corridor_half_width_m

    usable_count = sum(item.is_usable_candidate for item in products)
    no_data_count = sum(
        item.processing_status == "no_data"
        for item in products
    )
    failed_count = sum(item.processing_status == "failed" for item in products)
    temporal_pairs = analysis_service.list_compatible_candidate_pairs(river_status.observations)
    usable_observation_count = sum(
        item.is_usable_candidate
        for item in products
        if item.satellite == "SENTINEL-1"
    )
    temporal_comparison = TemporalComparison(
        status=(
            "compatible_pair_available"
            if temporal_pairs
            else "no_compatible_pair"
            if usable_observation_count >= 2
            else "insufficient_observations"
        ),
        available_pair_count=len(temporal_pairs),
        explanation=(
            (
                f"{len(temporal_pairs)} same-sensor Sentinel-1 candidate pair(s) passed the exact-grid, "
                "polarization, product-type, filter, and threshold-method checks. Use Change analysis "
                "to generate an exploratory comparison; no seasonal adjustment or independent validation is applied."
            )
            if temporal_pairs
            else (
                "Multiple Sentinel-1 candidate observations exist, but none passed the persisted grid and "
                "processing-compatibility checks required for comparison."
                if usable_observation_count >= 2
                else "Fewer than two usable Sentinel-1 candidate observations are available for this river."
            )
        ),
    )

    optical = _optical_comparison(river_id, selected_nisar)
    findings = []
    if candidate_metrics and selected_option and selected_option.is_usable_candidate:
        findings.append(
            f"{selected_option.satellite} product {selected_option.product_id} contains "
            f"{candidate_metrics.candidate_water_pixel_count or 0:,} candidate-water pixels; "
            "this is an unvalidated candidate result."
        )
        if candidate_metrics.valid_data_fraction is not None:
            findings.append(
                f"Valid support is {candidate_metrics.valid_data_fraction * 100:.2f}% "
                "of the reported processing support; remaining pixels are not classified."
            )
    elif candidate_metrics:
        findings.append(
            f"Product {selected_option.product_id if selected_option else ''} has status "
            f"{candidate_metrics.classification_status}; no candidate-water result is available."
        )
    else:
        findings.append("No usable processed candidate output is available for this river.")

    evidence_status, evidence_explanation = _evidence_status(river_id, selected_option)
    warnings = [
        "This is deterministic local rule-based analysis of persisted catalog records; it is not an LLM-generated scientific conclusion.",
        "Candidate classifications are not ground truth; this summary does not report accuracy scores.",
    ]
    if no_data_count:
        warnings.append(
            f"{no_data_count} catalog product(s) have no-data processing status; "
            "they are not treated as candidate classifications."
        )
    if failed_count:
        warnings.append(
            f"{failed_count} catalog product(s) have failed processing status; "
            "they are distinct from no-data results and are not treated as candidates."
        )
    if optical.available:
        warnings.append(optical.warning)

    return RiverAnalysisResponse(
        analysis_id=str(uuid4()),
        generated_at=datetime.now(timezone.utc),
        analysis_mode="deterministic_rule_based",
        data_mode="persisted_satellite_acquisition_catalog",
        river_id=river_id,
        selected_product_id=selected_option.product_id if selected_option else None,
        products=products,
        coverage=AnalysisCoverage(
            catalog_product_count=len(products),
            usable_candidate_count=usable_count,
            no_data_product_count=no_data_count,
            failed_product_count=failed_count,
            mapped_centerline_coverage_percent=centerline_coverage,
            corridor_half_width_m=corridor_half_width,
        ),
        candidate_metrics=candidate_metrics,
        threshold_sensitivity=sensitivity,
        polarization_comparison=polarization_comparison,
        optical_comparison=optical,
        temporal_comparison=temporal_comparison,
        validation_status=evidence_status,
        validation_explanation=evidence_explanation,
        findings=findings,
        warnings=warnings,
        limitations=_BASE_LIMITATIONS,
        recommended_next_steps=[
            "Review acquisition quality, valid-pixel support, and candidate-map NoData before interpretation.",
            "Obtain independently reviewed, temporally compatible water-reference labels before computing validation metrics.",
            "Use change analysis only after compatible grids, acquisition dates, seasons, and processing parameters are verified.",
        ],
    )


def analyze_river(river_id: str, product_id: str | None = None) -> RiverAnalysisResponse:
    return build_river_analysis(acquisitions.get_catalog_status(), river_id, product_id)
