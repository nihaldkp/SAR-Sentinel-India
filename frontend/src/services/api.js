const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

async function request(path, { signal, method = "GET", body, headers } = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { signal, method, body, headers });
  } catch (error) {
    if (error.name === "AbortError") {
      throw error;
    }
    throw new Error(`Cannot reach the SAR Sentinel API at ${API_BASE_URL}. Start the backend and try again.`);
  }

  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`The SAR Sentinel API returned an invalid response for ${path}.`);
  }

  if (!response.ok) {
    const detail = typeof payload.detail === "string" ? payload.detail : response.statusText;
    throw new Error(`API request failed (${response.status}): ${detail}`);
  }
  return payload;
}

function isRegion(value) {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    typeof value.center_latitude === "number" &&
    typeof value.center_longitude === "number" &&
    value.data_mode === "demonstration" &&
    value.is_simulated === true
  );
}

function isObservation(value) {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof value.id === "string" &&
    typeof value.region_id === "string" &&
    typeof value.scenario_date === "string" &&
    !Number.isNaN(Date.parse(value.scenario_date)) &&
    typeof value.label === "string" &&
    value.source === "synthetic_demo" &&
    value.is_simulated === true &&
    value.status === "demonstration_only"
  );
}

function isRiver(value) {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    typeof value.display_name === "string" &&
    typeof value.states === "string" &&
    typeof value.geographical_location === "string" &&
    typeof value.data_source === "string" &&
    typeof value.source_url === "string" &&
    typeof value.retrieval_url === "string" &&
    (value.osm_element_type === "way" || value.osm_element_type === "relation") &&
    typeof value.osm_element_id === "number" &&
    typeof value.retrieval_date === "string" &&
    typeof value.license === "string" &&
    typeof value.license_url === "string" &&
    Array.isArray(value.available_geographical_data) &&
    typeof value.boundary_data_status === "string" &&
    (value.boundary_data_status === "available" || value.boundary_data_status === "unavailable") &&
    value.centerline !== null &&
    typeof value.centerline === "object" &&
    Array.isArray(value.centerline.coordinates)
  );
}

function isSatelliteObservation(value) {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof value.id === "string" &&
    (value.mission === "NISAR" || value.mission === "SENTINEL-1") &&
    typeof value.source === "string" &&
    typeof value.analysis_readiness === "string"
  );
}

export async function fetchCatalog(signal) {
  const [health, regions] = await Promise.all([
    request("/api/health", { signal }),
    request("/api/regions", { signal }),
  ]);

  if (health.status !== "ok" || health.data_mode !== "demonstration") {
    throw new Error("The SAR Sentinel API returned an unexpected health status or data mode.");
  }
  if (!Array.isArray(regions) || !regions.every(isRegion)) {
    throw new Error("The SAR Sentinel API returned an invalid region catalog.");
  }
  return { health, regions };
}

export async function fetchObservations(regionId, signal) {
  const observations = await request(`/api/observations?region_id=${encodeURIComponent(regionId)}`, { signal });
  if (!Array.isArray(observations) || !observations.every(isObservation)) {
    throw new Error("The SAR Sentinel API returned an invalid observation catalog.");
  }
  return observations;
}

export async function fetchRivers(signal) {
  const rivers = await request("/api/rivers", { signal });
  if (!Array.isArray(rivers) || !rivers.every(isRiver)) {
    throw new Error("The SAR Sentinel API returned an invalid river catalog.");
  }
  return rivers;
}

export async function searchRiverNetwork(filters, signal) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== "" && value !== null && value !== undefined) params.set(key, String(value));
  }
  const result = await request(`/api/river-network/features?${params}`, { signal });
  if (!result || !Array.isArray(result.features) || !Number.isInteger(result.total) ||
      !result.features.every((feature) => typeof feature.source_object_id === "string")) {
    throw new Error("The river network API returned an invalid result.");
  }
  return result;
}

export async function fetchRiverNetworkGeometry(id, signal) {
  const geometry = await request(`/api/river-network/features/${encodeURIComponent(id)}/geometry`, { signal });
  if (!geometry || !["LineString", "MultiLineString"].includes(geometry.type) ||
      !Array.isArray(geometry.coordinates)) {
    throw new Error("The river network API returned invalid geometry.");
  }
  return geometry;
}

export async function searchSatelliteObservations({ riverId, mission, startDate, endDate, productType }, signal) {
  const params = new URLSearchParams({
    river_id: riverId,
    mission,
    start_date: startDate,
    end_date: endDate,
  });
  if (productType) {
    params.set("product_type", productType);
  }
  const result = await request(`/api/satellite/search?${params.toString()}`, { signal });
  if (
    result === null ||
    typeof result !== "object" ||
    result.source !== "ASF DAAC" ||
    !Array.isArray(result.observations) ||
    !result.observations.every(isSatelliteObservation)
  ) {
    throw new Error("The satellite catalog returned an invalid response.");
  }
  return result;
}

export async function processWaterMask(file, metadata, signal) {
  const body = new FormData();
  body.append("file", file);
  body.append("metadata_json", JSON.stringify(metadata));
  return request("/api/analysis/water-mask", { signal, method: "POST", body });
}

export async function compareWaterMasks(earlierAnalysisId, laterAnalysisId, signal) {
  return request("/api/analysis/change", {
    signal,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ earlier_analysis_id: earlierAnalysisId, later_analysis_id: laterAnalysisId }),
  });
}

export async function fetchTemporalCandidatePairs(riverId, signal) {
  const params = new URLSearchParams({ river_id: riverId });
  const pairs = await request(`/api/analysis/temporal-pairs?${params.toString()}`, { signal });
  if (
    !Array.isArray(pairs) ||
    !pairs.every((pair) =>
      pair !== null &&
      typeof pair === "object" &&
      pair.river_id === riverId &&
      typeof pair.earlier_analysis_id === "string" &&
      typeof pair.later_analysis_id === "string" &&
      typeof pair.earlier_source_product_id === "string" &&
      typeof pair.later_source_product_id === "string" &&
      typeof pair.common_valid_pixel_count === "number" &&
      typeof pair.common_valid_area_m2 === "number" &&
      typeof pair.common_valid_fraction === "number" &&
      typeof pair.parameter_compatibility === "string" &&
      typeof pair.seasonal_context === "string"
    )
  ) {
    throw new Error("The temporal candidate-pair endpoint returned an invalid response.");
  }
  return pairs;
}

export async function measureWaterWidth({ analysisId, start, end }, signal) {
  return request("/api/analysis/width", {
    signal,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ analysis_id: analysisId, start, end }),
  });
}

export async function sampleCandidateWidthsAlongAxis(requestBody, signal) {
  const result = await request("/api/analysis/width/river-axis", {
    signal,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(requestBody),
  });
  if (
    result === null ||
    typeof result !== "object" ||
    typeof result.analysis_id !== "string" ||
    typeof result.source_product_id !== "string" ||
    typeof result.axis_geometry_status !== "string" ||
    typeof result.requested_station_count !== "number" ||
    typeof result.accepted_station_count !== "number" ||
    typeof result.coverage_fraction !== "number" ||
    typeof result.raster_resolution_m !== "number" ||
    result.uncertainty_status !== "not_quantified" ||
    !Array.isArray(result.samples) ||
    !Array.isArray(result.quality_flags) ||
    !Array.isArray(result.caveats)
  ) {
    throw new Error("The river-axis sampling endpoint returned an invalid response.");
  }
  return result;
}

export async function fetchAnalysisCapabilities(signal) {
  const result = await request("/api/analysis/status", { signal });
  if (
    result === null ||
    typeof result !== "object" ||
    typeof result.geotiff_processing_available !== "boolean" ||
    typeof result.raw_product_preprocessing_available !== "boolean" ||
    typeof result.real_satellite_product_downloaded !== "boolean"
  ) {
    throw new Error("The analysis capability endpoint returned an invalid response.");
  }
  return result;
}

export async function runRiverAnalysis(riverId, productId, signal) {
  const result = await request("/api/analysis/ai-summary", {
    signal,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      river_id: riverId,
      ...(productId ? { product_id: productId } : {}),
    }),
  });
  if (
    result === null ||
    typeof result !== "object" ||
    result.analysis_mode !== "deterministic_rule_based" ||
    result.data_mode !== "persisted_satellite_acquisition_catalog" ||
    result.river_id !== riverId ||
    !Array.isArray(result.products) ||
    !result.products.every((product) =>
      product !== null &&
      typeof product === "object" &&
      typeof product.product_id === "string" &&
      (product.satellite === "NISAR" || product.satellite === "SENTINEL-1") &&
      typeof product.processing_status === "string" &&
      typeof product.is_usable_candidate === "boolean" &&
      Array.isArray(product.polarization)
    ) ||
    (result.selected_product_id !== null &&
      !result.products.some((product) => product.product_id === result.selected_product_id)) ||
    !Array.isArray(result.findings) ||
    !Array.isArray(result.warnings) ||
    !Array.isArray(result.limitations) ||
    !Array.isArray(result.recommended_next_steps) ||
    result.coverage === null ||
    typeof result.coverage !== "object" ||
    result.optical_comparison === null ||
    typeof result.optical_comparison !== "object" ||
    result.temporal_comparison === null ||
    typeof result.temporal_comparison !== "object"
  ) {
    throw new Error("The river-analysis endpoint returned an invalid response.");
  }
  return result;
}

export async function fetchValidationStatus(signal) {
  const result = await request("/api/analysis/validation/status", { signal });
  if (
    result === null ||
    typeof result !== "object" ||
    !["validation_pending", "reference_dataset_available", "validation_completed"].includes(result.status) ||
    typeof result.message !== "string" ||
    !Array.isArray(result.reports)
  ) {
    throw new Error("The validation status endpoint returned an invalid response.");
  }
  return result;
}

export async function fetchReferenceSources(signal) {
  const result = await request("/api/analysis/reference-sources", { signal });
  if (
    !Array.isArray(result) ||
    !result.every((source) => (
      source !== null &&
      typeof source === "object" &&
      typeof source.source_id === "string" &&
      typeof source.name === "string" &&
      typeof source.provider === "string" &&
      typeof source.source_url === "string" &&
      typeof source.access_url === "string" &&
      typeof source.temporal_coverage === "string" &&
      typeof source.license_status === "string" &&
      typeof source.geographic_coverage === "string" &&
      typeof source.spatial_reference === "string" &&
      typeof source.data_format === "string" &&
      typeof source.access_notes === "string" &&
      typeof source.intended_use === "string" &&
      typeof source.limitation === "string"
    ))
  ) {
    throw new Error("The reference-source endpoint returned an invalid response.");
  }
  return result;
}

export async function fetchImportedReferenceData(signal) {
  const result = await request("/api/analysis/reference-data", { signal });
  if (
    !Array.isArray(result) ||
    !result.every((reference) => (
      reference !== null &&
      typeof reference === "object" &&
      typeof reference.reference_id === "string" &&
      typeof reference.labels_url === "string" &&
      typeof reference.metadata?.dataset_id === "string"
    ))
  ) {
    throw new Error("The imported reference-data endpoint returned an invalid response.");
  }
  return result;
}

export async function importReviewedReferenceData(file, metadata, signal) {
  const form = new FormData();
  form.append("reference_file", file);
  form.append("metadata_json", JSON.stringify(metadata));
  const result = await request("/api/analysis/reference-data", {
    signal,
    method: "POST",
    body: form,
  });
  if (
    result === null ||
    typeof result !== "object" ||
    typeof result.reference_id !== "string" ||
    typeof result.labels_url !== "string" ||
    typeof result.metadata?.dataset_id !== "string"
  ) {
    throw new Error("The reference-data import endpoint returned an invalid response.");
  }
  return result;
}

export async function evaluateClassificationMethods(referenceFile, candidateFiles, metadata, signal) {
  const form = new FormData();
  form.append("reference_file", referenceFile);
  candidateFiles.forEach((file) => form.append("candidate_files", file));
  form.append("metadata_json", JSON.stringify(metadata));
  const result = await request("/api/analysis/validation/methods", {
    signal,
    method: "POST",
    body: form,
  });
  if (
    result === null ||
    typeof result !== "object" ||
    typeof result.evaluation_id !== "string" ||
    !Array.isArray(result.methods) ||
    typeof result.shared_common_valid_pixel_count !== "number" ||
    typeof result.report_url !== "string"
  ) {
    throw new Error("The classification-method evaluation endpoint returned an invalid response.");
  }
  return result;
}

export async function compareExploratoryMethods(candidateFiles, metadata, signal) {
  const form = new FormData();
  candidateFiles.forEach((file) => form.append("candidate_files", file));
  form.append("metadata_json", JSON.stringify(metadata));
  const result = await request("/api/analysis/validation/methods/exploratory", {
    signal,
    method: "POST",
    body: form,
  });
  if (
    result === null ||
    typeof result !== "object" ||
    !["exploratory_comparison", "insufficient_spatial_overlap"].includes(result.status) ||
    !Array.isArray(result.methods) ||
    typeof result.shared_common_valid_pixel_count !== "number" ||
    typeof result.shared_grid_coverage_fraction !== "number" ||
    !Array.isArray(result.warnings)
  ) {
    throw new Error("The exploratory method comparison endpoint returned an invalid response.");
  }
  return result;
}

function validateRasterReport(result) {
  if (
    result === null || typeof result !== "object" || typeof result.validation_id !== "string" ||
    !["reference_dataset_available", "insufficient_spatial_overlap", "insufficient_valid_labels",
      "insufficient_evidence", "thresholds_met_awaiting_evaluation", "validation_completed",
      "evaluation_failed", "evaluation_rejected"].includes(result.status) ||
    typeof result.candidate_product_id !== "string" || typeof result.reference_dataset_id !== "string" ||
    typeof result.common_valid_pixel_count !== "number" || typeof result.report_url !== "string"
  ) {
    throw new Error("The raster validation endpoint returned an invalid response.");
  }
  return result;
}

export async function submitRasterValidation(candidateFile, referenceFile, metadata, signal, windowed = false) {
  const form = new FormData();
  form.append("candidate_file", candidateFile);
  form.append("reference_file", referenceFile);
  form.append("metadata_json", JSON.stringify(metadata));
  const result = await request(windowed ? "/api/analysis/validation/windowed-assessments" : "/api/analysis/validation", {
    signal,
    method: "POST",
    body: form,
  });
  return validateRasterReport(result);
}

export async function evaluateWindowedAssessment(validationId, signal) {
  const result = await request(`/api/analysis/validation/windowed-assessments/${encodeURIComponent(validationId)}/evaluate`, {
    signal, method: "POST",
  });
  return validateRasterReport(result);
}

export async function rejectWindowedAssessment(validationId, reason, signal) {
  const result = await request(`/api/analysis/validation/windowed-assessments/${encodeURIComponent(validationId)}/reject`, {
    signal, method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }),
  });
  return validateRasterReport(result);
}

export async function fetchAnalysisPolygons(path, signal) {
  const result = await request(path, { signal });
  if (
    result?.type !== "FeatureCollection" ||
    !Array.isArray(result.features) ||
    !result.features.every((feature) => feature?.type === "Feature" && feature.geometry?.type)
  ) {
    throw new Error("The analysis polygon endpoint returned invalid GeoJSON.");
  }
  return result;
}

export async function fetchAutomaticAcquisitions(signal) {
  const result = await request("/api/acquisitions", { signal });
  if (
    result === null ||
    typeof result !== "object" ||
    typeof result.enabled !== "boolean" ||
    !Array.isArray(result.rivers) ||
    !result.rivers.every((river) => (
      river !== null &&
      typeof river === "object" &&
      typeof river.river_id === "string" &&
      typeof river.status === "string" &&
      Array.isArray(river.observations) &&
      Array.isArray(river.issues)
    ))
  ) {
    throw new Error("The automatic satellite catalog returned an invalid response.");
  }
  return result;
}

export async function refreshAutomaticAcquisitions(signal) {
  return request("/api/acquisitions/refresh", { signal, method: "POST" });
}

export async function processNisarProduct(riverId, productId, signal) {
  const result = await request(
    `/api/acquisitions/nisar/${encodeURIComponent(productId)}/process?river_id=${encodeURIComponent(riverId)}`,
    { signal, method: "POST" },
  );
  if (
    result === null ||
    typeof result !== "object" ||
    !["unvalidated_candidate", "no_valid_corridor_data"].includes(result.status) ||
    (result.status === "unvalidated_candidate" &&
      (typeof result.mask_url !== "string" || typeof result.polygons_url !== "string")) ||
    (result.status === "unvalidated_candidate" &&
      (!Array.isArray(result.polarization_comparison) ||
        !Array.isArray(result.threshold_sensitivity) ||
        !result.connected_component_summary ||
        typeof result.comparison_url !== "string" ||
        typeof result.sensitivity_url !== "string")) ||
    (result.status === "no_valid_corridor_data" && result.valid_pixel_count !== 0)
  ) {
    throw new Error("The NISAR processing endpoint returned an invalid result.");
  }
  return result;
}

export async function runNisarComponentSensitivity(riverId, productId, minimumComponentSizes, signal) {
  const result = await request(
    `/api/acquisitions/nisar/${encodeURIComponent(productId)}/processing/component-sensitivity?river_id=${encodeURIComponent(riverId)}`,
    {
      signal,
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ minimum_component_sizes: minimumComponentSizes }),
    },
  );
  if (
    !Array.isArray(result) ||
    !result.every((item) => (
      item !== null &&
      typeof item === "object" &&
      item.status === "exploratory_candidate_sensitivity" &&
      item.river_id === riverId &&
      item.product_id === productId &&
      item.source_product_id === productId &&
      typeof item.minimum_component_pixels === "number" &&
      item.connectivity === 8 &&
      typeof item.component_count === "number" &&
      typeof item.candidate_pixel_count_before === "number" &&
      typeof item.candidate_pixel_count_after === "number" &&
      typeof item.candidate_pixels_reclassified_nonwater === "number" &&
      typeof item.candidate_pixels_removed_fraction === "number" &&
      typeof item.candidate_area_before_m2 === "number" &&
      typeof item.candidate_area_after_m2 === "number" &&
      typeof item.valid_pixel_count === "number" &&
      typeof item.nodata_pixel_count_preserved === "number" &&
      typeof item.crs === "string" &&
      typeof item.pixel_size_m === "number" &&
      typeof item.processing_completed_at === "string" &&
      Array.isArray(item.quality_flags) &&
      item.quality_flags.every((flag) => typeof flag === "string") &&
      typeof item.mask_url === "string"
    ))
  ) {
    throw new Error("The NISAR component-sensitivity endpoint returned an invalid response.");
  }
  return result;
}

const acquisitionJobStatuses = new Set([
  "queued",
  "running",
  "downloading",
  "processing",
  "completed",
  "no_data",
  "failed",
  "cancelled",
]);

function isAcquisitionJob(value) {
  return (
    value !== null &&
    typeof value === "object" &&
    typeof value.job_id === "string" &&
    typeof value.river_id === "string" &&
    typeof value.satellite === "string" &&
    typeof value.product_id === "string" &&
    typeof value.job_type === "string" &&
    acquisitionJobStatuses.has(value.status) &&
    typeof value.created_at === "string" &&
    typeof value.current_stage === "string" &&
    value.output_references !== null &&
    typeof value.output_references === "object"
  );
}

export async function fetchNisarOpticalReference(path, signal) {
  const result = await request(path, { signal });
  if (
    result === null ||
    typeof result !== "object" ||
    result.status !== "unvalidated_candidate" ||
    typeof result.classification !== "string" ||
    typeof result.ndwi_threshold !== "number" ||
    result.counts === null ||
    typeof result.counts !== "object" ||
    typeof result.counts.common_valid_pixels !== "number" ||
    typeof result.counts.ndwi_candidate_pixels !== "number" ||
    typeof result.counts.candidate_area_m2 !== "number" ||
    result.source === null ||
    typeof result.source !== "object" ||
    typeof result.source.acquisition_datetime !== "string" ||
    typeof result.preview_url !== "string" ||
    result.bounds_wgs84 === null ||
    typeof result.bounds_wgs84 !== "object" ||
    !["west", "south", "east", "north"].every((key) => Number.isFinite(result.bounds_wgs84[key])) ||
    typeof result.crs !== "string" ||
    typeof result.nodata_value !== "number" ||
    !Array.isArray(result.limitations) ||
    !result.limitations.every((item) => typeof item === "string") ||
    (result.additional_observations !== undefined &&
      (!Array.isArray(result.additional_observations) ||
        !result.additional_observations.every((item) => (
          item !== null &&
          typeof item === "object" &&
          item.status === "unvalidated_candidate" &&
          item.source !== null &&
          typeof item.source === "object" &&
          typeof item.source.item_id === "string" &&
          typeof item.preview_url === "string" &&
          typeof item.mask_url === "string" &&
          item.bounds_wgs84 !== null &&
          typeof item.bounds_wgs84 === "object" &&
          ["west", "south", "east", "north"].every((key) => Number.isFinite(item.bounds_wgs84[key])) &&
          item.counts !== null &&
          typeof item.counts === "object" &&
          typeof item.counts.common_valid_pixels === "number"
        ))))
  ) {
    throw new Error("The Sentinel-2 candidate metadata endpoint returned an invalid response.");
  }
  return result;
}

export async function fetchAcquisitionJobs(signal) {
  const result = await request("/api/acquisition-jobs?limit=50", { signal });
  if (!Array.isArray(result) || !result.every(isAcquisitionJob)) {
    throw new Error("The acquisition jobs endpoint returned an invalid response.");
  }
  return result;
}

export async function submitAcquisitionJob(job, signal) {
  const result = await request("/api/acquisition-jobs", {
    signal,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(job),
  });
  if (!isAcquisitionJob(result)) {
    throw new Error("The acquisition jobs endpoint returned an invalid response.");
  }
  return result;
}

export async function retryAcquisitionJob(jobId, signal) {
  const result = await request(
    `/api/acquisition-jobs/${encodeURIComponent(jobId)}/retry`,
    { signal, method: "POST" },
  );
  if (!isAcquisitionJob(result)) {
    throw new Error("The acquisition jobs endpoint returned an invalid response.");
  }
  return result;
}

export { API_BASE_URL };
