import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Download, FileUp, LoaderCircle, Waves } from "lucide-react";
import {
  API_BASE_URL,
  compareWaterMasks,
  fetchAnalysisCapabilities,
  fetchAnalysisPolygons,
  fetchTemporalCandidatePairs,
  measureWaterWidth,
  processWaterMask,
  sampleCandidateWidthsAlongAxis,
} from "../services/api.js";

const PRODUCT_TYPES = {
  NISAR: ["GCOV"],
  "SENTINEL-1": ["GRD_HD", "GRD_MD", "GRD_MS"],
};

function localDateTime(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function formatArea(value) {
  return new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(value);
}

export default function AnalysisWorkspace({ riverSelection, selectedObservation, onSelectAnalysisGeometry }) {
  const [riverId, setRiverId] = useState(riverSelection === "tungabhadra" ? "tungabhadra" : "kaveri");
  const [mission, setMission] = useState("NISAR");
  const [productType, setProductType] = useState("GCOV");
  const [productId, setProductId] = useState("");
  const [acquisitionStart, setAcquisitionStart] = useState("");
  const [polarization, setPolarization] = useState("");
  const [bandDescription, setBandDescription] = useState("");
  const [signalScale, setSignalScale] = useState("decibels");
  const [thresholdMethod, setThresholdMethod] = useState("otsu");
  const [thresholdDb, setThresholdDb] = useState("-17");
  const [calibrationConfirmed, setCalibrationConfirmed] = useState(false);
  const [terrainConfirmed, setTerrainConfirmed] = useState(false);
  const [file, setFile] = useState(null);
  const [analyses, setAnalyses] = useState([]);
  const [earlierId, setEarlierId] = useState("");
  const [laterId, setLaterId] = useState("");
  const [transectAnalysisId, setTransectAnalysisId] = useState("");
  const [startLon, setStartLon] = useState("");
  const [startLat, setStartLat] = useState("");
  const [endLon, setEndLon] = useState("");
  const [endLat, setEndLat] = useState("");
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const [capabilities, setCapabilities] = useState(null);
  const [capabilityError, setCapabilityError] = useState("");
  const [comparison, setComparison] = useState(null);
  const [temporalPairs, setTemporalPairs] = useState([]);
  const [temporalPairsLoading, setTemporalPairsLoading] = useState(false);
  const [temporalPairsError, setTemporalPairsError] = useState("");
  const [widthResult, setWidthResult] = useState(null);
  const [axisDatasetId, setAxisDatasetId] = useState("");
  const [axisSourceName, setAxisSourceName] = useState("");
  const [axisSourceUrl, setAxisSourceUrl] = useState("");
  const [axisGeojson, setAxisGeojson] = useState("");
  const [corridorGeojson, setCorridorGeojson] = useState("");
  const [axisStationSpacing, setAxisStationSpacing] = useState("200");
  const [axisTransectHalfLength, setAxisTransectHalfLength] = useState("500");
  const [axisMinimumCoverage, setAxisMinimumCoverage] = useState("0.8");
  const [axisSamplingStatus, setAxisSamplingStatus] = useState("idle");
  const [axisSamplingError, setAxisSamplingError] = useState("");
  const [axisSamplingResult, setAxisSamplingResult] = useState(null);

  useEffect(() => {
    if (riverSelection === "kaveri" || riverSelection === "tungabhadra") {
      setRiverId(riverSelection);
    }
  }, [riverSelection]);

  useEffect(() => {
    const controller = new AbortController();
    setTemporalPairs([]);
    setTemporalPairsError("");
    setTemporalPairsLoading(true);
    fetchTemporalCandidatePairs(riverId, controller.signal)
      .then(setTemporalPairs)
      .catch((requestError) => {
        if (requestError.name !== "AbortError") {
          setTemporalPairsError(requestError.message);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setTemporalPairsLoading(false);
        }
      });
    return () => controller.abort();
  }, [riverId]);

  useEffect(() => {
    const controller = new AbortController();
    fetchAnalysisCapabilities(controller.signal)
      .then(setCapabilities)
      .catch((requestError) => {
        if (requestError.name !== "AbortError") {
          setCapabilityError(requestError.message);
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!selectedObservation) {
      return;
    }
    setRiverId(selectedObservation.river_id);
    setMission(selectedObservation.mission);
    setProductType(PRODUCT_TYPES[selectedObservation.mission]?.includes(selectedObservation.product_type)
      ? selectedObservation.product_type
      : PRODUCT_TYPES[selectedObservation.mission]?.[0] ?? "");
    setProductId(selectedObservation.id ?? "");
    setAcquisitionStart(localDateTime(selectedObservation.acquisition_start));
    setPolarization(selectedObservation.polarization ?? "");
  }, [selectedObservation]);

  const analysisOptions = useMemo(
    () => analyses.map(({ result }) => ({
      id: result.analysis_id,
      label: `${result.source_product_id} · ${new Date(result.acquisition_start).toLocaleDateString()}`,
    })),
    [analyses],
  );

  const setMissionSelection = (value) => {
    setMission(value);
    setProductType(PRODUCT_TYPES[value][0]);
  };

  const submitWaterMask = async (event) => {
    event.preventDefault();
    setStatus("loading");
    setError("");
    try {
      const metadata = {
        river_id: riverId,
        mission,
        product_type: productType,
        source_product_id: productId.trim(),
        acquisition_start: new Date(acquisitionStart).toISOString(),
        polarization: polarization.trim(),
        band_description: bandDescription.trim(),
        signal_scale: signalScale,
        radiometric_calibration_confirmed: calibrationConfirmed,
        terrain_correction_confirmed: terrainConfirmed,
        threshold_method: thresholdMethod,
        ...(thresholdMethod === "fixed_db" ? { threshold_db: Number(thresholdDb) } : {}),
      };
      const result = await processWaterMask(file, metadata);
      setAnalyses((current) => [...current, { result }]);
      setTransectAnalysisId(result.analysis_id);
      setStatus("loaded");
    } catch (requestError) {
      setError(requestError.message);
      setStatus("error");
    }
  };

  const runComparison = async () => {
    setStatus("loading");
    setError("");
    try {
      setComparison(await compareWaterMasks(earlierId, laterId));
      setStatus("loaded");
    } catch (requestError) {
      setError(requestError.message);
      setStatus("error");
    }
  };

  const runPersistedComparison = async (pair) => {
    setStatus("loading");
    setError("");
    try {
      setComparison(await compareWaterMasks(pair.earlier_analysis_id, pair.later_analysis_id));
      setStatus("loaded");
    } catch (requestError) {
      setError(requestError.message);
      setStatus("error");
    }
  };

  const runWidthMeasurement = async () => {
    setStatus("loading");
    setError("");
    try {
      setWidthResult(await measureWaterWidth({
        analysisId: transectAnalysisId,
        start: [Number(startLon), Number(startLat)],
        end: [Number(endLon), Number(endLat)],
      }));
      setStatus("loaded");
    } catch (requestError) {
      setError(requestError.message);
      setStatus("error");
    }
  };

  const runAxisSampling = async (event) => {
    event.preventDefault();
    setAxisSamplingStatus("loading");
    setAxisSamplingError("");
    setAxisSamplingResult(null);
    try {
      const axisGeometry = JSON.parse(axisGeojson);
      const corridorGeometry = JSON.parse(corridorGeojson);
      const result = await sampleCandidateWidthsAlongAxis({
        analysis_id: transectAnalysisId,
        axis_dataset_id: axisDatasetId.trim(),
        axis_source_name: axisSourceName.trim(),
        axis_source_url: axisSourceUrl.trim(),
        axis_geojson: axisGeometry,
        corridor_geojson: corridorGeometry,
        station_spacing_m: Number(axisStationSpacing),
        transect_half_length_m: Number(axisTransectHalfLength),
        minimum_valid_fraction: Number(axisMinimumCoverage),
      });
      setAxisSamplingResult(result);
      setAxisSamplingStatus("loaded");
    } catch (requestError) {
      setAxisSamplingError(
        requestError instanceof SyntaxError
          ? "Axis and corridor must each be valid GeoJSON objects."
          : requestError.message,
      );
      setAxisSamplingStatus("error");
    }
  };

  const showOnMap = async (result) => {
    setStatus("loading");
    setError("");
    try {
      const geojson = await fetchAnalysisPolygons(result.polygons_url);
      onSelectAnalysisGeometry({
        analysisId: result.analysis_id,
        geojson,
        river_id: result.river_id,
        source_type: "user-provided raster",
      });
      setStatus("loaded");
    } catch (requestError) {
      setError(requestError.message);
      setStatus("error");
    }
  };

  return (
    <article className="panel analysis-workspace">
      <div className="panel-header">
        <div>
          <div className="panel-title-row"><h2>Local SAR analysis</h2><span className="analysis-candidate-tag">UNVALIDATED WORKFLOW</span></div>
          <p className="panel-subtitle">Upload a calibrated, geocoded, single-band GeoTIFF. ASF search does not download the data.</p>
        </div>
      </div>

      <div className="analysis-caveat" role="note">
        This accepts operator-prepared raster exports only. The workflow does not calibrate raw SAR products, independently verify metadata, or produce verified riverbanks, erosion, deposition, flood extent, or accuracy scores.
      </div>
      <p><a href="#method-comparison">Compare candidate classification methods in the validation workspace</a></p>
      {capabilityError && <div className="satellite-error" role="alert"><AlertCircle size={15} />Analysis capability check failed: {capabilityError}</div>}
      {capabilities && !capabilities.geotiff_processing_available && (
        <div className="analysis-unavailable" role="status">
          <strong>Processing unavailable in this environment.</strong>
          <span>{capabilities.unavailable_reason}</span>
          <small>Raw NISAR/Sentinel-1 preprocessing is not implemented. No synthetic fallback is used.</small>
        </div>
      )}

      <section className="analysis-tools temporal-pair-workspace" aria-labelledby="temporal-pairs-title">
        <h3 id="temporal-pairs-title">Persisted satellite candidate comparisons</h3>
        <p className="analysis-caveat">
          Only same-river, chronological candidates with matching mission, product type, polarization, filter, threshold method, and exact raster grid are offered. Comparisons are exploratory, retain common-valid support, and are not validated river change.
        </p>
        {temporalPairsLoading && <p className="analysis-result-line">Checking persisted candidate grids and processing provenance…</p>}
        {temporalPairsError && <p className="satellite-error" role="alert">{temporalPairsError}</p>}
        {!temporalPairsLoading && !temporalPairsError && temporalPairs.length === 0 && (
          <p className="analysis-result-line">No compatible persisted candidate pair is currently available for {riverId}.</p>
        )}
        {temporalPairs.length > 0 && (
          <ul className="analysis-result-list">
            {temporalPairs.map((pair) => (
              <li key={`${pair.earlier_analysis_id}-${pair.later_analysis_id}`}>
                <span>
                  <strong>{pair.earlier_source_product_id} → {pair.later_source_product_id}</strong>
                  <small>
                    {new Date(pair.earlier_acquisition_start).toLocaleString()} → {new Date(pair.later_acquisition_start).toLocaleString()} ·
                    {" "}{pair.mission} {pair.product_type} {pair.polarization} · {pair.crs} · {pair.pixel_size_m} m
                  </small>
                  <small>
                    Common valid support: {pair.common_valid_pixel_count.toLocaleString()} pixels ·
                    {" "}{formatArea(pair.common_valid_area_m2)} m² · {(pair.common_valid_fraction * 100).toFixed(2)}% of grid
                  </small>
                  <small>
                    Threshold: {pair.earlier_threshold_db.toFixed(3)} → {pair.later_threshold_db.toFixed(3)} dB ({pair.threshold_method}) · {pair.seasonal_context}
                  </small>
                  <small>{pair.parameter_compatibility}</small>
                </span>
                <button
                  className="analysis-secondary-button"
                  disabled={status === "loading"}
                  onClick={() => runPersistedComparison(pair)}
                  type="button"
                >
                  {status === "loading" ? "Comparing…" : "Compare candidates"}
                </button>
              </li>
            ))}
          </ul>
        )}
        {comparison && (
          <div className="temporal-comparison-result" role="status">
            <strong>Unvalidated candidate extent comparison</strong>
            <span>{comparison.earlier_source_product_id} → {comparison.later_source_product_id}</span>
            <span>
              Common support {comparison.common_valid_pixel_count.toLocaleString()} pixels ·
              {" "}{formatArea(comparison.common_valid_area_m2)} m² ·
              {" "}{(comparison.common_valid_fraction * 100).toFixed(2)}% of grid
            </span>
            <span>
              Candidate-water gain {formatArea(comparison.candidate_water_gain_area_m2)} m² ·
              {" "}loss {formatArea(comparison.candidate_water_loss_area_m2)} m²
            </span>
            <span>
              {comparison.threshold_method} threshold {comparison.earlier_threshold_db.toFixed(3)} →{" "}
              {comparison.later_threshold_db.toFixed(3)} dB · no seasonal adjustment or independent validation
            </span>
            <span className="analysis-output-links">
              <a href={`${API_BASE_URL}${comparison.change_mask_url}`}>Candidate comparison mask</a>
              <a href={`${API_BASE_URL}${comparison.report_url}`}><Download size={12} /> Report</a>
            </span>
          </div>
        )}
      </section>

      <form className="analysis-form" onSubmit={submitWaterMask}>
        <label>River
          <select onChange={(event) => setRiverId(event.target.value)} value={riverId}>
            <option value="kaveri">Kaveri</option>
            <option value="tungabhadra">Tungabhadra</option>
          </select>
        </label>
        <label>Mission
          <select onChange={(event) => setMissionSelection(event.target.value)} value={mission}>
            <option value="NISAR">NISAR</option>
            <option value="SENTINEL-1">Sentinel-1</option>
          </select>
        </label>
        <label>Product
          <select onChange={(event) => setProductType(event.target.value)} value={productType}>
            {PRODUCT_TYPES[mission].map((type) => <option key={type}>{type}</option>)}
          </select>
        </label>
        <label>Source product ID
          <input onChange={(event) => setProductId(event.target.value)} required value={productId} />
        </label>
        <label>Acquisition time (local)
          <input onChange={(event) => setAcquisitionStart(event.target.value)} required type="datetime-local" value={acquisitionStart} />
        </label>
        <label>Polarization
          <input onChange={(event) => setPolarization(event.target.value)} placeholder="e.g. VV" required value={polarization} />
        </label>
        <label>Exported band description
          <input onChange={(event) => setBandDescription(event.target.value)} placeholder="Describe the selected scalar band" required value={bandDescription} />
        </label>
        <label>Raster scale
          <select onChange={(event) => setSignalScale(event.target.value)} value={signalScale}>
            <option value="decibels">Decibels (dB)</option>
            <option value="linear_power">Linear power</option>
          </select>
        </label>
        <label>Threshold
          <select onChange={(event) => setThresholdMethod(event.target.value)} value={thresholdMethod}>
            <option value="otsu">Otsu (automatic)</option>
            <option value="fixed_db">Fixed dB</option>
          </select>
        </label>
        {thresholdMethod === "fixed_db" && (
          <label>Threshold value (dB)
            <input max="5" min="-50" onChange={(event) => setThresholdDb(event.target.value)} required step="0.1" type="number" value={thresholdDb} />
          </label>
        )}
        <label className="analysis-file-input"><FileUp size={15} /> Calibrated GeoTIFF
          <input
            accept=".tif,.tiff,image/tiff"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            required
            type="file"
          />
          <small>{file ? `${file.name} · ${(file.size / (1024 * 1024)).toFixed(1)} MB` : "Maximum 100 MB · one band · projected metres"}</small>
        </label>
        <label className="analysis-confirmation">
          <input checked={calibrationConfirmed} onChange={(event) => setCalibrationConfirmed(event.target.checked)} required type="checkbox" />
          I confirm radiometric calibration is complete.
        </label>
        <label className="analysis-confirmation">
          <input checked={terrainConfirmed} onChange={(event) => setTerrainConfirmed(event.target.checked)} required type="checkbox" />
          I confirm terrain correction/geocoding is complete.
        </label>
        <button className="satellite-search-button analysis-submit" disabled={status === "loading" || !file || capabilities?.geotiff_processing_available !== true} type="submit">
          {status === "loading" ? <LoaderCircle className="analysis-spinner" size={14} /> : <Waves size={14} />}
          {status === "loading" ? "Processing…" : "Create candidate water mask"}
        </button>
      </form>

      {status === "error" && <div className="satellite-error" role="alert"><AlertCircle size={15} />{error}</div>}

      {analyses.length > 0 && (
        <div className="analysis-tools">
          <section>
            <h3>Two-date extent comparison</h3>
            <div className="analysis-tool-row">
              <label>Earlier acquisition<select onChange={(event) => setEarlierId(event.target.value)} value={earlierId}>
                <option value="">Select analysis</option>
                {analysisOptions.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
              </select></label>
              <label>Later acquisition<select onChange={(event) => setLaterId(event.target.value)} value={laterId}>
                <option value="">Select analysis</option>
                {analysisOptions.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
              </select></label>
              <button className="analysis-secondary-button" disabled={!earlierId || !laterId || status === "loading"} onClick={runComparison} type="button">Compare masks</button>
            </div>
          </section>

          <section>
            <h3>Transect-based width estimate</h3>
            <div className="analysis-tool-row analysis-transect-row">
              <label>Water mask<select onChange={(event) => setTransectAnalysisId(event.target.value)} value={transectAnalysisId}>
                <option value="">Select analysis</option>
                {analysisOptions.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
              </select></label>
              <label>Start lon<input onChange={(event) => setStartLon(event.target.value)} required step="any" type="number" value={startLon} /></label>
              <label>Start lat<input onChange={(event) => setStartLat(event.target.value)} required step="any" type="number" value={startLat} /></label>
              <label>End lon<input onChange={(event) => setEndLon(event.target.value)} required step="any" type="number" value={endLon} /></label>
              <label>End lat<input onChange={(event) => setEndLat(event.target.value)} required step="any" type="number" value={endLat} /></label>
              <button className="analysis-secondary-button" disabled={!transectAnalysisId || !startLon || !startLat || !endLon || !endLat || status === "loading"} onClick={runWidthMeasurement} type="button">Measure</button>
            </div>
            {widthResult && <p className="analysis-result-line">
              Longest candidate-water segment: {formatArea(widthResult.longest_contiguous_water_width_m)} m · not a verified bank-to-bank width.
            </p>}
          </section>

          <section className="river-axis-workspace">
            <h3>Candidate sampling along a supplied river axis</h3>
            <p className="analysis-caveat">
              Geometry is supplied by the operator and is not authenticated. Do not use the dashboard OSM centerline as a surveyed active-channel axis. Output measures candidate-mask segments only; uncertainty is not quantified and no verified bank-to-bank width is produced.
            </p>
            <form className="analysis-form river-axis-form" onSubmit={runAxisSampling}>
              <label>Candidate mask
                <select onChange={(event) => setTransectAnalysisId(event.target.value)} required value={transectAnalysisId}>
                  <option value="">Select analysis</option>
                  {analysisOptions.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                </select>
              </label>
              <label>Axis dataset ID<input maxLength={256} onChange={(event) => setAxisDatasetId(event.target.value)} required value={axisDatasetId} /></label>
              <label>Geometry source name<input maxLength={256} onChange={(event) => setAxisSourceName(event.target.value)} required value={axisSourceName} /></label>
              <label>Source URL<input onChange={(event) => setAxisSourceUrl(event.target.value)} required type="url" value={axisSourceUrl} /></label>
              <label>Station spacing (m)<input min="1" onChange={(event) => setAxisStationSpacing(event.target.value)} required step="any" type="number" value={axisStationSpacing} /></label>
              <label>Transect half-length (m)<input min="1" onChange={(event) => setAxisTransectHalfLength(event.target.value)} required step="any" type="number" value={axisTransectHalfLength} /></label>
              <label>Minimum valid coverage<input max="1" min="0.5" onChange={(event) => setAxisMinimumCoverage(event.target.value)} required step="0.05" type="number" value={axisMinimumCoverage} /></label>
              <label className="validation-wide-field">Axis GeoJSON (WGS84 LineString)<textarea onChange={(event) => setAxisGeojson(event.target.value)} required rows={3} value={axisGeojson} /></label>
              <label className="validation-wide-field">Corridor GeoJSON (WGS84 Polygon or MultiPolygon)<textarea onChange={(event) => setCorridorGeojson(event.target.value)} required rows={3} value={corridorGeojson} /></label>
              <button className="analysis-secondary-button validation-wide-field" disabled={axisSamplingStatus === "loading" || !transectAnalysisId} type="submit">
                {axisSamplingStatus === "loading" ? "Sampling…" : "Sample candidate segments"}
              </button>
            </form>
            {axisSamplingError && <p className="analysis-unavailable" role="alert">{axisSamplingError}</p>}
            {axisSamplingResult && (
              <div className="axis-sampling-result" role="region" aria-label="Candidate axis sampling results">
                <strong>Candidate-mask sampling · geometry unverified</strong>
                <span>{axisSamplingResult.axis_dataset_id} · {axisSamplingResult.axis_source_name} · {axisSamplingResult.axis_geometry_status.replaceAll("_", " ")}</span>
                <span>
                  Accepted {axisSamplingResult.accepted_station_count}/{axisSamplingResult.requested_station_count} stations ·
                  {" "}{(axisSamplingResult.coverage_fraction * 100).toFixed(1)}% accepted coverage ·
                  {" "}{axisSamplingResult.raster_resolution_m} m raster resolution
                </span>
                <span>Measurement uncertainty: not quantified. Segment length is not surveyed bank-to-bank width.</span>
                <ul className="axis-sample-list">
                  {axisSamplingResult.samples.map((sample, index) => (
                    <li key={`${sample.chainage_m}-${index}`}>
                      <span>
                        <strong>Chainage {sample.chainage_m.toFixed(1)} m · {sample.quality_status.replaceAll("_", " ")}</strong>
                        <small>
                          Candidate segment: {sample.candidate_width_m === null ? "unavailable" : `${sample.candidate_width_m.toFixed(1)} m`} ·
                          {" "}valid {(sample.valid_fraction * 100).toFixed(1)}% · raster {(sample.raster_coverage_fraction * 100).toFixed(1)}%
                        </small>
                        <small>{sample.quality_flags.join(" ")}</small>
                      </span>
                    </li>
                  ))}
                </ul>
                {[...axisSamplingResult.quality_flags, ...axisSamplingResult.caveats].map((flag) => (
                  <small key={flag}>{flag}</small>
                ))}
              </div>
            )}
          </section>

          <section>
            <h3>Candidate outputs</h3>
            <ul className="analysis-result-list">
              {analyses.map(({ result }) => (
                <li key={result.analysis_id}>
                  <span><strong>{result.source_product_id}</strong><small>
                    {new Date(result.acquisition_start).toLocaleString()} · {formatArea(result.candidate_water_area_m2)} m² candidate water
                    {" "}({formatArea(result.candidate_water_area_lower_m2)}–{formatArea(result.candidate_water_area_upper_m2)} m² at ±1 dB; not a confidence interval)
                  </small></span>
                  <span className="analysis-output-links">
                    <button disabled={status === "loading"} onClick={() => showOnMap(result)} type="button">Map</button>
                    <a href={`${API_BASE_URL}${result.mask_url}`}>Mask</a>
                    <a href={`${API_BASE_URL}${result.polygons_url}`}>GeoJSON</a>
                    <a href={`${API_BASE_URL}${result.report_url}`}><Download size={12} /> PDF</a>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </article>
  );
}
