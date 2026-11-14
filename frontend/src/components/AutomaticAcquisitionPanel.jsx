import { useCallback, useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Clock3, Download, ExternalLink, LoaderCircle, Radio, RefreshCw, Satellite } from "lucide-react";
import {
  API_BASE_URL,
  fetchAnalysisPolygons,
  fetchAcquisitionJobs,
  fetchAutomaticAcquisitions,
  fetchNisarOpticalReference,
  runNisarComponentSensitivity,
  retryAcquisitionJob,
  refreshAutomaticAcquisitions,
  submitAcquisitionJob,
} from "../services/api.js";

function formatDate(value) {
  if (!value) {
    return "Not available";
  }
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value)) + " UTC";
}

function formatArea(value) {
  return new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(value);
}

function formatPreciseArea(value) {
  return new Intl.NumberFormat("en", { maximumFractionDigits: 3 }).format(value);
}

function formatTimeDifference(value) {
  if (!Number.isFinite(value)) {
    return "Not available";
  }
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const seconds = Number((value % 60).toFixed(3));
  return `${hours} h ${minutes} min ${seconds} sec`;
}

function formatBytes(value) {
  if (!Number.isFinite(value) || value < 0) {
    return "Size not reported";
  }
  const gibibytes = value / (1024 ** 3);
  return `${gibibytes.toFixed(2)} GB`;
}

function stateLabel(state) {
  return ({
    idle: "Waiting for first automatic catalog scan",
    searching: "Searching official catalogs",
    acquiring: "Reading a clipped RTC window from cloud storage",
    processing: "Processing the real Sentinel-1 RTC subset",
    processed: "Latest available candidate processed or cached",
    no_data: "No usable satellite observations in the mapped river corridor",
    blocked: "NISAR download requires NASA Earthdata authentication",
    failed: "Catalog, acquisition, or processing error",
  })[state] ?? state;
}

function nisarProcessingLabel(product) {
  if (product.processing_result?.status === "unvalidated_candidate") {
    return "Processed — scientifically unvalidated candidate";
  }
  if (product.processing_result?.status === "no_valid_corridor_data" || product.processing_status === "no_data") {
    return "No valid corridor data";
  }
  if (product.processing_status === "processed") {
    return "Processed — result details unavailable";
  }
  return `Processing status: ${String(product.processing_status ?? "unknown").replaceAll("_", " ")}`;
}

function nisarSourceLabel(product) {
  return product.local_path
    ? "Source: locally recovered NISAR L2 UR GCOV product"
    : "Source: NISAR L2 UR GCOV catalog record";
}

function earthdataAuthenticationLabel(status) {
  return ({
    unknown: "unknown",
    not_configured: "not configured",
    token_valid: "token valid; product access unverified",
    data_access_verified: "product access verified by one-byte request",
    rejected: "rejected or expired",
    error: "check the river's Earthdata status message",
  })[status] ?? "unknown";
}

function jobStateLabel(state) {
  return ({
    queued: "Queued",
    running: "Starting",
    downloading: "Downloading",
    processing: "Processing",
    completed: "Completed",
    no_data: "No valid corridor data",
    failed: "Failed",
    cancelled: "Cancelled",
  })[state] ?? state;
}

export default function AutomaticAcquisitionPanel({
  onSelectAnalysisGeometry,
  onToggleOpticalLayer,
  selectedOpticalLayer,
}) {
  const [catalog, setCatalog] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState("");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  const [jobActionId, setJobActionId] = useState("");
  const [opticalMetadataByProduct, setOpticalMetadataByProduct] = useState({});
  const [opticalLoadingId, setOpticalLoadingId] = useState("");
  const [componentSensitivityByProduct, setComponentSensitivityByProduct] = useState({});
  const [componentSensitivityLoadingId, setComponentSensitivityLoadingId] = useState("");

  const loadStatus = useCallback(async (signal) => {
    try {
      const [nextCatalog, nextJobs] = await Promise.all([
        fetchAutomaticAcquisitions(signal),
        fetchAcquisitionJobs(signal),
      ]);
      setCatalog(nextCatalog);
      setJobs(nextJobs);
      setError("");
    } catch (requestError) {
      if (requestError.name !== "AbortError") {
        setError(requestError.message);
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadStatus(controller.signal);
    const timer = window.setInterval(() => loadStatus(controller.signal), 5_000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [loadStatus]);

  const refreshNow = async () => {
    setIsRefreshing(true);
    setError("");
    try {
      setCatalog(await refreshAutomaticAcquisitions());
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsRefreshing(false);
    }
  };

  const showOnMap = async (observation) => {
    setSelectedId(observation.product_id);
    setError("");
    try {
      const geojson = await fetchAnalysisPolygons(observation.polygons_url);
      onSelectAnalysisGeometry({
        analysisId: observation.analysis_id,
        geojson,
        river_id: observation.river_id,
        source_type: "automatically acquired Sentinel-1 RTC",
      });
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  const processNisar = async (riverId, product) => {
    setJobActionId(product.product_id);
    setError("");
    try {
      const job = await submitAcquisitionJob({
        river_id: riverId,
        satellite: "NISAR",
        product_id: product.product_id,
        job_type: "nisar_processing",
      });
      setJobs((current) => [job, ...current.filter((entry) => entry.job_id !== job.job_id)]);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setJobActionId("");
    }
  };

  const runComponentSensitivity = async (riverId, product) => {
    setComponentSensitivityLoadingId(product.product_id);
    setError("");
    try {
      const results = await runNisarComponentSensitivity(
        riverId,
        product.product_id,
        [2, 5, 10],
      );
      setComponentSensitivityByProduct((current) => ({
        ...current,
        [product.product_id]: results,
      }));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setComponentSensitivityLoadingId("");
    }
  };

  const downloadNisar = async (riverId, product) => {
    setJobActionId(product.product_id);
    setError("");
    try {
      const job = await submitAcquisitionJob({
        river_id: riverId,
        satellite: "NISAR",
        product_id: product.product_id,
        job_type: "nisar_download",
      });
      setJobs((current) => [job, ...current.filter((entry) => entry.job_id !== job.job_id)]);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setJobActionId("");
    }
  };

  const retryJob = async (job) => {
    setJobActionId(job.job_id);
    setError("");
    try {
      const retry = await retryAcquisitionJob(job.job_id);
      setJobs((current) => [retry, ...current.filter((entry) => entry.job_id !== retry.job_id)]);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setJobActionId("");
    }
  };

  const queueSentinel1 = async (riverId, issue) => {
    setJobActionId(issue.product_id);
    setError("");
    try {
      const job = await submitAcquisitionJob({
        river_id: riverId,
        satellite: "SENTINEL-1",
        product_id: issue.product_id,
        job_type: "sentinel1_acquisition",
      });
      setJobs((current) => [job, ...current.filter((entry) => entry.job_id !== job.job_id)]);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setJobActionId("");
    }
  };

  const showNisarOnMap = async (riverId, product) => {
    const result = product.processing_result;
    if (!result) {
      return;
    }
    setSelectedId(product.product_id);
    setError("");
    try {
      const geojson = await fetchAnalysisPolygons(result.polygons_url);
      onSelectAnalysisGeometry({
        analysisId: `nisar-${product.product_id}`,
        geojson,
        river_id: riverId,
        source_type: "NISAR GCOV",
      });
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  const loadOpticalReference = async (productId, metadataUrl) => {
    setOpticalLoadingId(productId);
    setError("");
    try {
      const metadata = await fetchNisarOpticalReference(metadataUrl);
      setOpticalMetadataByProduct((current) => ({ ...current, [productId]: metadata }));
      return metadata;
    } catch (requestError) {
      setError(requestError.message);
      return null;
    } finally {
      setOpticalLoadingId("");
    }
  };

  const toggleOpticalMapLayer = async (riverId, product, observationOverride = null) => {
    let metadata = observationOverride;
    if (
      selectedOpticalLayer?.productId === product.product_id &&
      selectedOpticalLayer?.itemId === metadata?.source?.item_id
    ) {
      onToggleOpticalLayer(null);
      return;
    }
    metadata ??= opticalMetadataByProduct[product.product_id];
    if (!metadata) {
      metadata = await loadOpticalReference(
        product.product_id,
        product.processing_result.optical_reference_url,
      );
    }
    if (!metadata) {
      return;
    }
    if (!metadata.preview_url || !metadata.bounds_wgs84) {
      setError("Sentinel-2 preview metadata does not include usable map bounds or an image URL.");
      return;
    }
    onToggleOpticalLayer({
      productId: product.product_id,
      itemId: metadata.source.item_id,
      riverId,
      previewUrl: metadata.preview_url,
      boundsWgs84: metadata.bounds_wgs84,
      metadata,
    });
  };

  return (
    <article className="panel automatic-acquisition-panel" aria-label="Automatic satellite data acquisition">
      <div className="panel-header">
        <div>
          <div className="panel-title-row">
            <h2>Automatic satellite observations</h2>
            <span className="acquisition-live-tag"><span /> {catalog?.enabled ? "AUTO DISCOVERY ON" : "AUTO DISCOVERY OFF"}</span>
          </div>
          <p className="panel-subtitle">Checks NISAR metadata first, then automatically acquires the latest publicly readable Sentinel-1 RTC data.</p>
        </div>
        <button
          className="acquisition-refresh-button"
          disabled={isRefreshing || catalog?.enabled === false}
          onClick={refreshNow}
          type="button"
        >
          {isRefreshing ? <LoaderCircle className="analysis-spinner" size={14} /> : <RefreshCw size={13} />}
          {isRefreshing ? "Checking…" : "Check now"}
        </button>
      </div>

      <div className="acquisition-source-note">
        NISAR GCOV results are separate from Sentinel-1 RTC. Linear HHHH/HVHV power is converted to 10·log10(max(power, 1e-6)) dB; independent Otsu thresholds use 900-bin histograms spanning −60 to +30 dB. HH-only and HV-only are compared on the same valid paired pixels; combined candidates require HH ≤ its threshold AND HV ≤ its threshold. The canonical classification has no spatial filter; optional component-size scenarios create separate copies and are not validated cleanup. These are exploratory candidates, not validated water or riverbank labels; Sentinel-1 RTC remains the fallback.
      </div>

      {error && <div className="satellite-error" role="alert"><AlertCircle size={15} />{error}</div>}
      {!catalog && !error && <div className="acquisition-state" role="status"><LoaderCircle className="analysis-spinner" size={14} />Loading automatic acquisition status…</div>}
      {catalog?.nisar_connection_status && (
        <section className="acquisition-source-note" aria-label="NISAR Data Connection Status">
          <h3>NISAR Data Connection Status</h3>
          <p>
            Provider: ASF DAAC · Current connectivity: {catalog.nisar_connection_status.provider_connectivity === "available"
              ? "available at last successful search"
              : "unknown"} ·
            Authentication: {earthdataAuthenticationLabel(catalog.nisar_connection_status.authentication_status)} ·
            Last successful search: {formatDate(catalog.nisar_connection_status.last_successful_search)}.
          </p>
          <p>
            Earthdata authentication check: {formatDate(catalog.nisar_connection_status.authentication_checked_at)}.
          </p>
          <p>
            Catalog-reported unique products: {catalog.nisar_connection_status.cached_product_count} ·
            Downloads: {catalog.nisar_connection_status.recorded_download_count} ·
            Inspections: {catalog.nisar_connection_status.recorded_inspection_count} ·
            Processing results: {catalog.nisar_connection_status.recorded_processing_count} (including no-data results).
          </p>
          <p>
            Latest acquisition with a catalog-reported inspection: {catalog.nisar_connection_status.latest_recorded_inspection_product_id ?? "none"} ·
            {formatDate(catalog.nisar_connection_status.latest_recorded_inspection_acquisition)}.
          </p>
          <p>
            Latest recorded processing: {catalog.nisar_connection_status.latest_recorded_processing
              ? `${catalog.nisar_connection_status.latest_recorded_processing.product_id} · ${catalog.nisar_connection_status.latest_recorded_processing.status} · ${formatDate(catalog.nisar_connection_status.latest_recorded_processing.completed_at)}`
              : "none"}.
          </p>
          <p>{catalog.nisar_connection_status.recorded_error
            ? "A catalog or processing error is recorded; inspect the affected river or job below."
            : "No error is recorded in the current catalog; past errors may not be retained."}</p>
          <p>Connection and authentication labels reflect the latest recorded checks; cached product counts do not verify checksums or scientific validity.</p>
        </section>
      )}
      {jobs.length > 0 && (
        <section className="acquisition-job-list" aria-label="Satellite jobs">
          <h3>Acquisition and processing jobs</h3>
          {jobs.slice(0, 10).map((job) => (
            <div className="acquisition-job" key={job.job_id} data-testid={`acquisition-job-${job.job_id}`}>
              <div className="acquisition-job-heading">
                <strong>{job.satellite} · {job.job_type.replaceAll("_", " ")} · {jobStateLabel(job.status)}</strong>
                <span>{formatDate(job.created_at)}</span>
              </div>
              <span className="acquisition-job-product">{job.river_id} · {job.product_id}</span>
              <span className="acquisition-job-stage">
                {job.current_stage}
                {job.progress_percent === null
                  ? " · Stage-based progress; percentage not reported"
                  : ` · ${job.progress_percent}%`}
              </span>
              {job.started_at && <span>Started: {formatDate(job.started_at)}</span>}
              {job.completed_at && <span>Finished: {formatDate(job.completed_at)}</span>}
              {job.error_message && <span className="acquisition-job-error" role="alert">{job.error_message}</span>}
              {job.retry_of_job_id && <span>Retry of job {job.retry_of_job_id}</span>}
              {job.status === "failed" && (
                <button
                  disabled={jobActionId === job.job_id}
                  onClick={() => retryJob(job)}
                  type="button"
                >
                  {jobActionId === job.job_id ? "Submitting retry…" : "Retry failed job"}
                </button>
              )}
            </div>
          ))}
        </section>
      )}
      {catalog && (
        <div className="acquisition-rivers">
          {catalog.rivers.map((river) => (
            <section className="acquisition-river" key={river.river_id}>
              <div className="acquisition-river-heading">
                <h3>{river.river_id === "kaveri" ? "Kaveri River" : "Tungabhadra River"}</h3>
                <span className={`acquisition-state-pill acquisition-state-${river.status}`}>
                  {["searching", "acquiring", "processing"].includes(river.status) && <LoaderCircle className="analysis-spinner" size={12} />}
                  {stateLabel(river.status)}
                </span>
              </div>
              <p className="acquisition-last-check"><Clock3 size={12} /> Last catalog check: {formatDate(river.last_checked_at)} · {river.candidate_count} Sentinel-1 scene(s) intersected the mapped centerline</p>

              <div className={`nisar-status nisar-status-${river.nisar_status}`}>
                <Satellite size={14} />
                <div>
                  <strong>NISAR GCOV · {river.nisar_status.replaceAll("_", " ")}</strong>
                  {river.nisar_product_id && <span>{river.nisar_product_id} · {formatDate(river.nisar_acquisition_start)}</span>}
                  <small>{river.nisar_message ?? "NISAR discovery will run automatically with the next catalog scan."}</small>
                </div>
              </div>
              {river.nisar_products?.map((product) => (
                <div className="nisar-product" key={product.product_id}>
                  <strong>{product.product_level} · {product.polarization?.join(", ") ?? "polarization not reported by ASF"}</strong>
                  <span>{product.product_id} · {formatDate(product.acquisition_start)} · {formatBytes(product.size_bytes)}</span>
                  <span>Availability: {product.availability.replaceAll("_", " ")} · download: {product.download_status.replaceAll("_", " ")}</span>
                  {product.hdf5_groups.length > 0 && <span>HDF5 groups: {product.hdf5_groups.join(", ")}</span>}
                  {product.message && <small>{product.message}</small>}
                  {product.local_path && (
                    <a href={`${API_BASE_URL}/api/acquisitions/nisar/${encodeURIComponent(product.product_id)}/download`}>
                      <Download size={12} /> Download verified NISAR HDF5
                    </a>
                  )}
                  {product.download_status !== "downloaded" && product.source_url && (
                    <button
                      disabled={jobActionId === product.product_id}
                      onClick={() => downloadNisar(river.river_id, product)}
                      type="button"
                    >
                      {jobActionId === product.product_id ? "Submitting download…" : "Queue authenticated NISAR download"}
                    </button>
                  )}
                  {product.download_status === "downloaded" && (
                    <div className="nisar-processing">
                      <strong>{nisarProcessingLabel(product)}</strong>
                      <small>{nisarSourceLabel(product)}</small>
                      {product.processing_message && <small>{product.processing_message}</small>}
                      {!product.processing_result && (
                        <button
                          disabled={jobActionId === product.product_id || product.processing_status === "processing"}
                          onClick={() => processNisar(river.river_id, product)}
                          type="button"
                        >
                          {jobActionId === product.product_id
                            ? <><LoaderCircle className="analysis-spinner" size={12} /> Submitting processing job…</>
                            : "Create unvalidated HH/HV water candidate"}
                        </button>
                      )}
                      {product.processing_result && (
                        <>
                          {product.processing_result.status === "no_valid_corridor_data" ? (
                            <>
                              <span>
                                No candidate mask generated: {product.processing_result.valid_pixel_count.toLocaleString()} valid paired HH/HV pixels
                                in {product.processing_result.corridor_pixel_count.toLocaleString()} corridor pixels.
                              </span>
                              <span>
                                Reference-line overlap: {product.processing_result.covered_centerline_length_km.toFixed(1)} km /
                                {product.processing_result.reference_centerline_length_km.toFixed(1)} km
                                ({product.processing_result.reference_centerline_coverage_percent.toFixed(1)}%).
                              </span>
                            </>
                          ) : (
                            <>
                              <span>
                                {product.processing_result.input_crs} · {product.processing_result.pixel_size_m} m ·
                                {product.processing_result.valid_pixel_count.toLocaleString()} valid corridor pixels ·
                                {(product.processing_result.valid_data_fraction * 100).toFixed(1)}% valid coverage
                              </span>
                              <span>
                                Candidate area: {formatArea(product.processing_result.candidate_water_area_m2)} m² ·
                                ±1 dB sensitivity {formatArea(product.processing_result.candidate_water_area_lower_m2)}–
                                {formatArea(product.processing_result.candidate_water_area_upper_m2)} m²
                              </span>
                              {product.processing_result.polarization_comparison?.length > 0 && (
                                <div className="nisar-quality-block">
                                  <strong>Polarization comparison · same valid pixels and independent Otsu thresholds</strong>
                                  {product.processing_result.polarization_comparison.map((item) => (
                                    <span key={item.classification}>
                                      {item.classification}: {item.candidate_pixel_count.toLocaleString()} pixels ·
                                      {formatArea(item.candidate_area_m2 / 1_000_000)} km²
                                    </span>
                                  ))}
                                </div>
                              )}
                              {product.processing_result.threshold_sensitivity?.length > 0 && (
                                <div className="nisar-quality-block">
                                  <strong>Threshold sensitivity · both thresholds shifted equally by −2, −1, 0, +1, +2 dB</strong>
                                  <div className="nisar-sensitivity-bars" role="img" aria-label="Candidate area for each Otsu threshold offset; this is sensitivity, not confidence">
                                    {product.processing_result.threshold_sensitivity.map((item) => {
                                      const maximum = Math.max(
                                        ...product.processing_result.threshold_sensitivity.map((entry) => entry.candidate_area_m2),
                                        1,
                                      );
                                      return (
                                        <div className="nisar-sensitivity-item" key={item.offset_db}>
                                          <span>{item.offset_db > 0 ? "+" : ""}{item.offset_db} dB</span>
                                          <div className="nisar-sensitivity-track">
                                            <span style={{ width: `${(item.candidate_area_m2 / maximum) * 100}%` }} />
                                          </div>
                                          <b>{formatArea(item.candidate_area_m2 / 1_000_000)} km²</b>
                                        </div>
                                      );
                                    })}
                                  </div>
                                  <small>Threshold perturbation only; not a confidence interval or accuracy estimate.</small>
                                </div>
                              )}
                              {product.processing_result.connected_component_summary && (
                                <div className="nisar-quality-block">
                                  <strong>8-connected component diagnostics · no despeckling or component removal</strong>
                                  <span>
                                    {product.processing_result.connected_component_summary.component_count.toLocaleString()} components ·
                                    {product.processing_result.connected_component_summary.isolated_pixel_component_count.toLocaleString()} isolated pixels
                                  </span>
                                  <small>
                                    Up to 4 pixels: {product.processing_result.connected_component_summary.components_up_to_four_pixels.toLocaleString()} components /
                                    {product.processing_result.connected_component_summary.pixels_in_components_up_to_four.toLocaleString()} pixels ·
                                    largest: {product.processing_result.connected_component_summary.largest_component_pixels.toLocaleString()} pixels
                                  </small>
                                </div>
                              )}
                              <div className="nisar-quality-block component-sensitivity">
                                <strong>Component-size sensitivity scenarios</strong>
                                <small>
                                  Optional local analysis of separate candidate-mask copies. A size threshold does not establish that excluded pixels are noise or false water.
                                </small>
                                <button
                                  disabled={componentSensitivityLoadingId === product.product_id}
                                  onClick={() => runComponentSensitivity(river.river_id, product)}
                                  type="button"
                                >
                                  {componentSensitivityLoadingId === product.product_id
                                    ? <><LoaderCircle className="analysis-spinner" size={12} /> Computing sensitivity…</>
                                    : "Compare 2, 5 and 10 pixel minimums"}
                                </button>
                                {(componentSensitivityByProduct[product.product_id] ?? []).map((scenario) => (
                                  <span key={scenario.minimum_component_pixels}>
                                    ≥{scenario.minimum_component_pixels} pixels:{" "}
                                    {scenario.candidate_pixels_reclassified_nonwater.toLocaleString()} candidate pixels reclassified ·
                                    {" "}{formatArea(scenario.candidate_area_after_m2 / 1_000_000)} km² remaining ·
                                    {" "}<a href={`${API_BASE_URL}${scenario.mask_url}`}>separate scenario mask</a>
                                  </span>
                                ))}
                                {componentSensitivityByProduct[product.product_id]?.[0]?.quality_flags?.map((flag) => (
                                  <small key={flag}>{flag}</small>
                                ))}
                              </div>
                            </>
                          )}
                          <span>
                            Reference centerline coverage: {product.processing_result.covered_centerline_length_km.toFixed(1)} km /
                            {product.processing_result.reference_centerline_length_km.toFixed(1)} km
                            ({product.processing_result.reference_centerline_coverage_percent.toFixed(1)}%)
                          </span>
                          {product.processing_result.status === "unvalidated_candidate" ? (
                            <>
                              <small>Candidate classification only; not a verified bank, river width, flood, or change result. A partial Sentinel-2 NDWI candidate mask is available for exploratory comparison; it is not ground truth and no accuracy score has been produced.</small>
                              {product.processing_result.optical_reference_url && product.processing_result.optical_candidate_mask_url && (
                                <div className="nisar-quality-block">
                                  <strong>Sentinel-2 NDWI candidate · exploratory, not ground truth</strong>
                                  {opticalMetadataByProduct[product.product_id] ? (
                                    <>
                                      <span>
                                        Acquired: {formatDate(opticalMetadataByProduct[product.product_id].source.acquisition_datetime)} ·
                                        NDWI &gt; {opticalMetadataByProduct[product.product_id].ndwi_threshold}
                                      </span>
                                      {Number.isFinite(opticalMetadataByProduct[product.product_id].source.catalog_cloud_cover_percent) && (
                                        <span>
                                          Catalog tile cloud cover: {opticalMetadataByProduct[product.product_id].source.catalog_cloud_cover_percent.toFixed(2)}%
                                        </span>
                                      )}
                                      <span>
                                        NISAR acquired: {formatDate(opticalMetadataByProduct[product.product_id].nisar_acquisition_datetime)} ·
                                        offset: {formatTimeDifference(opticalMetadataByProduct[product.product_id].acquisition_time_difference_seconds)}
                                      </span>
                                      <span>
                                        Common valid pixels: {opticalMetadataByProduct[product.product_id].counts.common_valid_pixels.toLocaleString()} ·
                                        optical candidates: {opticalMetadataByProduct[product.product_id].counts.ndwi_candidate_pixels.toLocaleString()} ·
                                        {formatArea(opticalMetadataByProduct[product.product_id].counts.candidate_area_m2)} m²
                                      </span>
                                      <span>
                                        Common valid area: {Number.isFinite(opticalMetadataByProduct[product.product_id].grid?.pixel_area_m2)
                                          ? `${formatPreciseArea(opticalMetadataByProduct[product.product_id].counts.common_valid_pixels * opticalMetadataByProduct[product.product_id].grid.pixel_area_m2 / 1_000_000)} km²`
                                          : "Not available"} ·
                                        mapped centerline coverage: {Number.isFinite(opticalMetadataByProduct[product.product_id].mapped_centerline_coverage_percent)
                                          ? `~${opticalMetadataByProduct[product.product_id].mapped_centerline_coverage_percent.toFixed(1)}%`
                                          : "Not available"}
                                      </span>
                                      <span>Source product: {opticalMetadataByProduct[product.product_id].source.item_id ?? "Not available"}</span>
                                      <div className="optical-map-actions">
                                        <button
                                          aria-pressed={
                                            selectedOpticalLayer?.productId === product.product_id &&
                                            selectedOpticalLayer?.itemId === opticalMetadataByProduct[product.product_id].source.item_id
                                          }
                                          disabled={opticalLoadingId === product.product_id}
                                          onClick={() => toggleOpticalMapLayer(river.river_id, product)}
                                          type="button"
                                        >
                                          {selectedOpticalLayer?.productId === product.product_id &&
                                          selectedOpticalLayer?.itemId === opticalMetadataByProduct[product.product_id].source.item_id
                                            ? "Remove Sentinel-2 layer from map"
                                            : opticalLoadingId === product.product_id
                                              ? "Loading Sentinel-2 map layer…"
                                              : "Show Sentinel-2 candidate on map"}
                                        </button>
                                      </div>
                                      {(opticalMetadataByProduct[product.product_id].additional_observations ?? []).map((observation) => {
                                        const isVisible = selectedOpticalLayer?.productId === product.product_id &&
                                          selectedOpticalLayer?.itemId === observation.source.item_id;
                                        const tile = observation.source.mgrs_tile ?? observation.source.item_id;
                                        return (
                                          <div className="nisar-quality-block" key={observation.source.item_id}>
                                            <strong>Additional Sentinel-2 tile {tile} · exploratory, not ground truth</strong>
                                            <span>
                                              Acquired: {formatDate(observation.source.acquisition_datetime)} ·
                                              catalog cloud: {Number.isFinite(observation.source.catalog_cloud_cover_percent)
                                                ? `${observation.source.catalog_cloud_cover_percent.toFixed(2)}%`
                                                : "not available"}
                                            </span>
                                            <span>
                                              Common valid pixels: {observation.counts.common_valid_pixels.toLocaleString()} ·
                                              candidate pixels: {observation.counts.ndwi_candidate_pixels.toLocaleString()} ·
                                              offset from NISAR: {formatTimeDifference(observation.acquisition_time_difference_seconds)}
                                            </span>
                                            <div className="optical-map-actions">
                                              <button
                                                aria-pressed={isVisible}
                                                onClick={() => toggleOpticalMapLayer(river.river_id, product, observation)}
                                                type="button"
                                              >
                                                {isVisible
                                                  ? `Remove Sentinel-2 ${tile} layer from map`
                                                  : `Show Sentinel-2 ${tile} candidate on map`}
                                              </button>
                                              <a href={`${API_BASE_URL}${observation.mask_url}`}>
                                                <Download size={12} /> Download Sentinel-2 {tile} candidate GeoTIFF
                                              </a>
                                            </div>
                                          </div>
                                        );
                                      })}
                                      {opticalMetadataByProduct[product.product_id].limitations.map((limitation) => (
                                        <small key={limitation}>{limitation}</small>
                                      ))}
                                    </>
                                  ) : (
                                    <button
                                      disabled={opticalLoadingId === product.product_id}
                                      onClick={() => loadOpticalReference(
                                        product.product_id,
                                        product.processing_result.optical_reference_url,
                                      )}
                                      type="button"
                                    >
                                      {opticalLoadingId === product.product_id
                                        ? "Loading Sentinel-2 metadata…"
                                        : "Show exploratory comparison details"}
                                    </button>
                                  )}
                                  <a href={`${API_BASE_URL}${product.processing_result.optical_candidate_mask_url}`}>
                                    <Download size={12} /> Sentinel-2 NDWI candidate GeoTIFF
                                  </a>
                                </div>
                              )}
                              {product.processing_result.geojson_display_note && (
                                <small>{product.processing_result.geojson_display_note}</small>
                              )}
                              <div className="acquisition-actions">
                                <button
                                  aria-pressed={selectedId === product.product_id}
                                  disabled={selectedId === product.product_id}
                                  onClick={() => showNisarOnMap(river.river_id, product)}
                                  type="button"
                                >
                                  <Radio size={12} /> {selectedId === product.product_id ? "Showing on map" : "Show NISAR candidate on map"}
                                </button>
                                {product.processing_result.measurements_url && <a href={`${API_BASE_URL}${product.processing_result.measurements_url}`}><Download size={12} /> HH/HV GeoTIFF</a>}
                                {product.processing_result.mask_url && <a href={`${API_BASE_URL}${product.processing_result.mask_url}`}><Download size={12} /> GeoTIFF mask</a>}
                                {product.processing_result.comparison_url && <a href={`${API_BASE_URL}${product.processing_result.comparison_url}`}><Download size={12} /> HH/HV comparison GeoTIFF</a>}
                                {product.processing_result.sensitivity_url && <a href={`${API_BASE_URL}${product.processing_result.sensitivity_url}`}><Download size={12} /> Threshold sensitivity GeoTIFF</a>}
                                {product.processing_result.polygons_url && <a href={`${API_BASE_URL}${product.processing_result.polygons_url}`}><Download size={12} /> GeoJSON</a>}
                              </div>
                            </>
                          ) : <small>No classified-water area or output raster is reported for this acquisition.</small>}
                          {product.processing_result.metadata_url && (
                            <a href={`${API_BASE_URL}${product.processing_result.metadata_url}`}><Download size={12} /> Processing metadata</a>
                          )}
                        </>
                      )}
                    </div>
                  )}
                  {product.source_url && (
                    <a href={product.source_url} rel="noreferrer" target="_blank">
                      ASF product source <ExternalLink size={10} />
                    </a>
                  )}
                </div>
              ))}

              {river.observations.map((observation) => (
                <div className="acquisition-observation" key={observation.product_id}>
                  <div className="acquisition-observation-heading">
                    <CheckCircle2 size={15} />
                    <strong>{observation.platform ?? "Sentinel-1"} · GRD RTC · {observation.polarization}</strong>
                    <span>Satellite observation · unvalidated analytical candidate</span>
                  </div>
                  <p className="acquisition-product-id">{observation.product_id}</p>
                  <div className="acquisition-metadata-grid">
                    <span><b>Acquired</b>{formatDate(observation.acquisition_start)}</span>
                    <span><b>Orbit</b>{observation.orbit_state ?? "Not reported"} · relative {observation.relative_orbit ?? "N/A"}</span>
                    <span><b>Centerline coverage</b>{observation.centerline_coverage_percent.toFixed(2)}% of mapped river</span>
                    <span><b>Pixel / CRS</b>{observation.pixel_size_m} m · {observation.input_crs}</span>
                    <span><b>Candidate water area</b>{formatArea(observation.candidate_water_area_m2)} m² in the analyzed crop</span>
                    <span><b>Threshold sensitivity</b>{formatArea(observation.candidate_water_area_lower_m2)}–{formatArea(observation.candidate_water_area_upper_m2)} m² (±1 dB; not a confidence interval)</span>
                    <span><b>Raster quality</b>{(observation.valid_data_fraction * 100).toFixed(1)}% valid · {observation.valid_pixel_count.toLocaleString()} pixels</span>
                    <span><b>Filter / threshold</b>{observation.filter_method} · Otsu at {observation.threshold_db.toFixed(2)} dB</span>
                    <span><b>Corridor</b>±{formatArea(observation.corridor_half_width_m)} m around OSM centerline</span>
                    <span><b>Source license</b><a href="https://creativecommons.org/licenses/by/4.0/" rel="noreferrer" target="_blank">{observation.source_license} <ExternalLink size={10} /></a></span>
                  </div>
                  <p className="acquisition-caveat">{observation.caveats.join(" ")}</p>
                  <div className="acquisition-actions">
                    <button
                      aria-pressed={selectedId === observation.product_id}
                      disabled={selectedId === observation.product_id}
                      onClick={() => showOnMap(observation)}
                      type="button"
                    >
                      <Radio size={12} /> {selectedId === observation.product_id ? "Showing on map" : "Show candidate mask on map"}
                    </button>
                    <a href={`${API_BASE_URL}/api/acquisitions/${observation.river_id}/${encodeURIComponent(observation.product_id)}/raster`}>
                      <Download size={12} /> Clipped VV GeoTIFF
                    </a>
                    <a href={observation.stac_item_url} rel="noreferrer" target="_blank">
                      <ExternalLink size={12} /> STAC source item
                    </a>
                    <a href={`${API_BASE_URL}${observation.report_url}`}>
                      <Download size={12} /> Candidate report
                    </a>
                  </div>
                </div>
              ))}

              {!river.observations.length && (
                <div className="acquisition-no-data">
                  {river.message ?? "No automatically acquired and processed Sentinel-1 RTC observation is available yet."}
                </div>
              )}
              {river.issues.map((issue) => (
                <div className="acquisition-issue" key={issue.product_id} role="alert">
                  <AlertCircle size={13} />
                  <span><strong>{issue.product_id}</strong> · {issue.status}: {issue.error ?? "No additional error detail."}</span>
                  {issue.status === "failed" && (
                    <button
                      disabled={jobActionId === issue.product_id}
                      onClick={() => queueSentinel1(river.river_id, issue)}
                      type="button"
                    >
                      {jobActionId === issue.product_id ? "Submitting…" : "Queue Sentinel-1 retry"}
                    </button>
                  )}
                </div>
              ))}
            </section>
          ))}
        </div>
      )}
      {catalog && (
        <p className="acquisition-footer">
          <Satellite size={12} />
          Automatic refresh every {Math.round(catalog.polling_interval_seconds / 3600)} hours · last global check {formatDate(catalog.last_checked_at)} ·
          <a href={catalog.source_url} rel="noreferrer" target="_blank"> {catalog.source} <ExternalLink size={10} /></a>
        </p>
      )}
    </article>
  );
}
