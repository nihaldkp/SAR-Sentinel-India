import { useEffect, useMemo, useRef, useState } from "react";
import { GeoJSON, ImageOverlay, MapContainer, TileLayer, useMap } from "react-leaflet";
import { Activity, AlertTriangle, Download, FileSearch, RefreshCw, ShieldCheck } from "lucide-react";
import {
  fetchAcquisitionJob,
  fetchForestAnalysis,
  fetchForestEvidenceSummary,
  fetchForestObservations,
  fetchForestReferences,
  fetchForestTreeCoverStatistics,
  fetchForestZones,
  fetchRivers,
  forestAnalysisOutputUrl,
  forestIndexPreviewUrl,
  forestTreeCoverPreviewUrl,
  importForestReference,
  submitForestAnalysis,
  submitForestTreeCoverJob,
} from "../services/api.js";

const INDEXES = ["ndvi", "evi", "ndmi"];
const DEFAULT_ZONE_DISTANCES = "500,1000,3000,5000";

function formatDate(value) {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date unavailable"
    : new Intl.DateTimeFormat("en-GB", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: "UTC",
    }).format(date) + " UTC";
}

function formatMetric(value, digits = 3) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "Unavailable";
}

function parseZoneDistances(value) {
  const distances = value.split(",").map((part) => Number(part.trim()));
  if (
    distances.length < 1 ||
    distances.length > 6 ||
    distances.some((distance) => !Number.isInteger(distance) || distance < 1 || distance > 5000) ||
    distances.some((distance, index) => index > 0 && distance <= distances[index - 1])
  ) {
    throw new Error("Enter 1–6 unique, increasing whole-number distances from 1 to 5,000 metres.");
  }
  return distances;
}

function geometryBounds(geometry) {
  const coordinates = [];
  const collect = (value) => {
    if (!Array.isArray(value)) return;
    if (value.length >= 2 && value.every((coordinate) => typeof coordinate === "number")) {
      coordinates.push(value);
      return;
    }
    value.forEach(collect);
  };
  collect(geometry?.coordinates);
  if (!coordinates.length) return null;
  const longitudes = coordinates.map(([longitude]) => longitude);
  const latitudes = coordinates.map(([, latitude]) => latitude);
  return {
    west: Math.min(...longitudes),
    south: Math.min(...latitudes),
    east: Math.max(...longitudes),
    north: Math.max(...latitudes),
  };
}

function MapBounds({ bounds }) {
  const map = useMap();
  useEffect(() => {
    if (bounds) {
      map.fitBounds(
        [[bounds.south, bounds.west], [bounds.north, bounds.east]],
        { padding: [18, 18], maxZoom: 12 },
      );
    }
  }, [bounds, map]);
  return null;
}

function IndexOverlay({ analysis, indexName }) {
  const [previewUrl, setPreviewUrl] = useState(null);
  const [previewError, setPreviewError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl;
    setPreviewUrl(null);
    setPreviewError("");
    fetch(forestIndexPreviewUrl(analysis.analysis_id, indexName), { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Preview request failed (${response.status}).`);
        if (!response.headers.get("content-type")?.startsWith("image/png")) {
          throw new Error("The forest preview endpoint returned an unexpected file type.");
        }
        return response.blob();
      })
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setPreviewUrl(objectUrl);
      })
      .catch((error) => {
        if (error.name !== "AbortError") setPreviewError(error.message);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [analysis.analysis_id, indexName]);

  if (previewError) return <div className="forest-map-state" role="alert">{previewError}</div>;
  if (!previewUrl) return <div className="forest-map-state" role="status">Loading {indexName.toUpperCase()} preview…</div>;
  const bounds = analysis.grid.bounds_wgs84;
  return (
    <ImageOverlay
      alt={`Observed Sentinel-2 ${indexName.toUpperCase()} in the river-side analysis zones`}
      bounds={[[bounds.south, bounds.west], [bounds.north, bounds.east]]}
      opacity={0.78}
      url={previewUrl}
    />
  );
}

function TreeCoverOverlay({ analysis, referenceId, statistics }) {
  const [previewUrl, setPreviewUrl] = useState(null);
  const [previewError, setPreviewError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl;
    setPreviewUrl(null);
    setPreviewError("");
    fetch(forestTreeCoverPreviewUrl(analysis.analysis_id, referenceId), { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`Tree-cover preview request failed (${response.status}).`);
        if (!response.headers.get("content-type")?.startsWith("image/png")) {
          throw new Error("The tree-cover preview endpoint returned an unexpected file type.");
        }
        return response.blob();
      })
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setPreviewUrl(objectUrl);
      })
      .catch((error) => {
        if (error.name !== "AbortError") setPreviewError(error.message);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [analysis.analysis_id, referenceId]);

  if (previewError) return <div className="forest-map-state" role="alert">{previewError}</div>;
  if (!previewUrl) return <div className="forest-map-state" role="status">Loading tree-cover reference preview…</div>;
  const bounds = statistics.output.bounds_wgs84;
  return (
    <ImageOverlay
      alt="Imported ESA WorldCover tree-cover class and other valid classes"
      bounds={[[bounds.south, bounds.west], [bounds.north, bounds.east]]}
      opacity={0.9}
      url={previewUrl}
    />
  );
}

function ForestMap({ river, analysis, zones, selectedIndex, treeCover, showTreeCover }) {
  const bounds = analysis?.grid?.bounds_wgs84 ?? geometryBounds(river?.centerline);
  const center = bounds
    ? [(bounds.south + bounds.north) / 2, (bounds.west + bounds.east) / 2]
    : [15.72, 75.72];
  return (
    <div className="forest-map-wrap">
      <MapContainer key={analysis?.analysis_id ?? river?.id ?? "forest-map"} center={center} zoom={analysis ? 9 : 6} scrollWheelZoom className="forest-map">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapBounds bounds={bounds} />
        {analysis?.status === "completed" && <IndexOverlay analysis={analysis} indexName={selectedIndex} />}
        {showTreeCover && treeCover && (
          <TreeCoverOverlay
            analysis={analysis}
            referenceId={treeCover.reference_id}
            statistics={treeCover}
          />
        )}
        {zones && <GeoJSON data={zones} style={{
          color: "#b55f2d",
          weight: 1.5,
          fillColor: "#e5a152",
          fillOpacity: 0.12,
        }} />}
        {river?.centerline && <GeoJSON data={river.centerline} style={{
          color: "#174f8b",
          weight: 3,
          opacity: 0.95,
        }} />}
      </MapContainer>
    </div>
  );
}

function IndexChart({ zones, indexName }) {
  const values = zones
    .map((zone) => zone[indexName]?.mean)
    .filter((value) => typeof value === "number" && Number.isFinite(value));
  const minimum = values.length ? Math.min(...values) : 0;
  const maximum = values.length ? Math.max(...values) : 0;
  const spread = maximum - minimum;

  return (
    <section className="forest-index-chart" aria-label={`${indexName.toUpperCase()} by distance zone`}>
      <h4>{indexName.toUpperCase()} mean by distance zone</h4>
      <p>Bars compare observed zones relative to this scene; values are unitless spectral indices.</p>
      {zones.map((zone) => {
        const value = zone[indexName]?.mean;
        const width = typeof value === "number"
          ? (spread === 0 ? 100 : 12 + ((value - minimum) / spread) * 88)
          : 0;
        return (
          <div className="forest-chart-row" key={zone.zone_id}>
            <span>{zone.zone_id}</span>
            <div className="forest-chart-track">
              <span style={{ width: `${width}%` }} />
            </div>
            <strong>{formatMetric(value)}</strong>
          </div>
        );
      })}
    </section>
  );
}

export default function ForestMonitoringPanel({
  riverSelection,
  onSelectRiver,
  onReportContext,
}) {
  const [riverId, setRiverId] = useState(riverSelection === "both" ? "kaveri" : riverSelection);
  const [catalog, setCatalog] = useState(null);
  const [references, setReferences] = useState(null);
  const [river, setRiver] = useState(null);
  const [catalogStatus, setCatalogStatus] = useState("loading");
  const [catalogError, setCatalogError] = useState("");
  const [itemId, setItemId] = useState("");
  const [zoneDistancesText, setZoneDistancesText] = useState(DEFAULT_ZONE_DISTANCES);
  const [selectedIndex, setSelectedIndex] = useState("ndvi");
  const [job, setJob] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [zones, setZones] = useState(null);
  const [evidenceSummary, setEvidenceSummary] = useState(null);
  const [referenceFile, setReferenceFile] = useState(null);
  const [selectedReferenceId, setSelectedReferenceId] = useState("");
  const [treeCoverStatistics, setTreeCoverStatistics] = useState(null);
  const [referenceBusy, setReferenceBusy] = useState(false);
  const [treeCoverBusy, setTreeCoverBusy] = useState(false);
  const [treeCoverStage, setTreeCoverStage] = useState("");
  const [showTreeCover, setShowTreeCover] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const requestSequence = useRef(0);
  const activeController = useRef(null);
  const treeCoverController = useRef(null);
  const referenceInput = useRef(null);

  useEffect(() => {
    if (riverSelection !== "both") setRiverId(riverSelection);
  }, [riverSelection]);

  useEffect(() => () => {
    requestSequence.current += 1;
    activeController.current?.abort();
    treeCoverController.current?.abort();
  }, []);

  useEffect(() => {
    if (!riverId) return undefined;
    requestSequence.current += 1;
    activeController.current?.abort();
    treeCoverController.current?.abort();
    treeCoverController.current = null;
    activeController.current = null;
    setLoading(false);
    setJob(null);
    const controller = new AbortController();
    setCatalogStatus("loading");
    setCatalogError("");
    setCatalog(null);
    setRiver(null);
    setAnalysis(null);
    setZones(null);
    setEvidenceSummary(null);
    setTreeCoverStatistics(null);
    setShowTreeCover(false);
    Promise.all([
      fetchForestObservations(riverId, controller.signal),
      fetchForestReferences(controller.signal),
      fetchRivers(controller.signal),
    ])
      .then(([observationCatalog, referenceCatalog, rivers]) => {
        if (controller.signal.aborted) return;
        setCatalog(observationCatalog);
        setReferences(referenceCatalog);
        const importedReferences = referenceCatalog.references.filter(
          (reference) => reference.status === "pixels_imported",
        );
        setSelectedReferenceId((current) => (
          importedReferences.some((reference) => reference.reference_id === current)
            ? current
            : importedReferences[0]?.reference_id ?? ""
        ));
        setRiver(rivers.find((item) => item.id === riverId) ?? null);
        setItemId((current) => (
          observationCatalog.observations.some((item) => item.item_id === current && item.has_source_assets)
            ? current
            : observationCatalog.observations.find((item) => item.has_source_assets)?.item_id ?? ""
        ));
        setCatalogStatus("loaded");
      })
      .catch((requestError) => {
        if (requestError.name !== "AbortError") {
          setCatalogError(requestError.message);
          setCatalogStatus("error");
        }
      });
    return () => controller.abort();
  }, [riverId, refresh]);

  const availableObservations = useMemo(
    () => (catalog?.observations ?? []).filter((observation) => observation.has_source_assets),
    [catalog],
  );
  const selectedObservation = availableObservations.find((observation) => observation.item_id === itemId) ?? null;

  useEffect(() => {
    onReportContext({
      domain: "forest",
      riverSelection,
      status: catalogStatus,
      riverId,
      itemId: selectedObservation?.item_id ?? null,
      indexName: selectedIndex,
    });
  }, [catalogStatus, itemId, onReportContext, riverId, riverSelection, selectedIndex, selectedObservation?.item_id]);

  const runAnalysis = async () => {
    if (!riverId || !itemId) return;
    let distances;
    try {
      distances = parseZoneDistances(zoneDistancesText);
    } catch (parseError) {
      setError(parseError.message);
      return;
    }
    const requestId = ++requestSequence.current;
    activeController.current?.abort();
    treeCoverController.current?.abort();
    treeCoverController.current = null;
    const controller = new AbortController();
    activeController.current = controller;
    setLoading(true);
    setError("");
    setJob(null);
    setAnalysis(null);
    setZones(null);
    setEvidenceSummary(null);
    setTreeCoverStatistics(null);
    setShowTreeCover(false);
    try {
      const submitted = await submitForestAnalysis({
        riverId,
        itemId,
        zoneDistancesM: distances,
      }, controller.signal);
      if (requestId !== requestSequence.current) return;
      setJob(submitted);
      let currentJob = submitted;
      while (["queued", "running", "downloading", "processing"].includes(currentJob.status)) {
        await new Promise((resolve) => window.setTimeout(resolve, 900));
        currentJob = await fetchAcquisitionJob(submitted.job_id, controller.signal);
        if (requestId !== requestSequence.current) return;
        setJob(currentJob);
      }
      if (currentJob.status === "failed" || currentJob.status === "cancelled") {
        throw new Error(currentJob.error_message || "Forest analysis did not complete.");
      }
      const analysisUrl = currentJob.output_references?.analysis;
      const analysisId = analysisUrl?.split("/").filter(Boolean).at(-1);
      if (!analysisId) throw new Error("The completed forest job did not include an analysis output.");
      const [result, zoneFeatures] = await Promise.all([
        fetchForestAnalysis(analysisId, controller.signal),
        fetchForestZones(analysisId, controller.signal),
      ]);
      if (requestId === requestSequence.current) {
        setAnalysis(result);
        setZones(zoneFeatures);
      }
    } catch (requestError) {
      if (requestError.name !== "AbortError" && requestId === requestSequence.current) {
        setError(requestError.message);
      }
    } finally {
      if (requestId === requestSequence.current) {
        setLoading(false);
        activeController.current = null;
      }
    }
  };

  const generateEvidenceSummary = async () => {
    if (!analysis) return;
    const controller = new AbortController();
    setError("");
    try {
      setEvidenceSummary(await fetchForestEvidenceSummary(
        analysis.analysis_id,
        controller.signal,
        treeCoverStatistics ? selectedReferenceId : undefined,
      ));
    } catch (requestError) {
      setError(requestError.message);
    }
  };

  const importReference = async () => {
    if (!referenceFile) return;
    setReferenceBusy(true);
    setError("");
    try {
      const imported = await importForestReference(referenceFile);
      const refreshed = await fetchForestReferences();
      treeCoverController.current?.abort();
      treeCoverController.current = null;
      setReferences(refreshed);
      setSelectedReferenceId(imported.reference_id);
      setReferenceFile(null);
      if (referenceInput.current) referenceInput.current.value = "";
      setTreeCoverStatistics(null);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setReferenceBusy(false);
    }
  };

  const calculateTreeCover = async () => {
    if (!analysis || !selectedReferenceId) return;
    setTreeCoverBusy(true);
    setTreeCoverStage("Queueing tree-cover statistics");
    setError("");
    setTreeCoverStatistics(null);
    const controller = new AbortController();
    treeCoverController.current?.abort();
    treeCoverController.current = controller;
    try {
      const submitted = await submitForestTreeCoverJob(
        analysis.analysis_id,
        selectedReferenceId,
        controller.signal,
      );
      let currentJob = submitted;
      while (["queued", "running", "downloading", "processing"].includes(currentJob.status)) {
        setTreeCoverStage(currentJob.current_stage || "Processing tree-cover reference");
        await new Promise((resolve) => window.setTimeout(resolve, 900));
        currentJob = await fetchAcquisitionJob(submitted.job_id, controller.signal);
      }
      if (currentJob.status === "failed" || currentJob.status === "cancelled") {
        throw new Error(currentJob.error_message || "Tree-cover statistics did not complete.");
      }
      const statistics = await fetchForestTreeCoverStatistics(
        analysis.analysis_id,
        selectedReferenceId,
        controller.signal,
      );
      setTreeCoverStatistics(statistics);
      setShowTreeCover(statistics.status === "completed");
      setTreeCoverStage("");
    } catch (requestError) {
      if (requestError.name !== "AbortError") setError(requestError.message);
    } finally {
      setTreeCoverBusy(false);
      if (treeCoverController.current === controller) treeCoverController.current = null;
    }
  };

  const availableDates = catalog?.distinct_processed_acquisition_times?.length ?? 0;
  const importedReferences = (references?.references ?? []).filter(
    (reference) => reference.status === "pixels_imported",
  );
  return (
    <section className="workspace-section forest-monitoring-workspace" aria-label="Forest monitoring">
      <div className="workspace-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow-line" /> FORESTS · SATELLITE EVIDENCE</div>
          <h2>Forest monitoring</h2>
          <p>Measure Sentinel-2 vegetation signals in configurable land-area zones around the registered river centerline.</p>
        </div>
        <span className="evidence-disclosure">
          {catalogStatus === "loading" ? "Loading observations" : catalogStatus === "error" ? "Unavailable" : `${availableObservations.length} source tile${availableObservations.length === 1 ? "" : "s"}`}
        </span>
      </div>

      <div className="panel forest-controls">
        <label>
          River
          <select aria-label="Forest river" value={riverId} onChange={(event) => {
            setRiverId(event.target.value);
            onSelectRiver(event.target.value);
          }}>
            <option value="kaveri">Kaveri River</option>
            <option value="tungabhadra">Tungabhadra River</option>
          </select>
        </label>
        <label className="forest-date-control">
          Sentinel-2 observation date / tile
          <select aria-label="Forest observation date" value={itemId} onChange={(event) => {
            activeController.current?.abort();
            activeController.current = null;
            treeCoverController.current?.abort();
            treeCoverController.current = null;
            requestSequence.current += 1;
            setLoading(false);
            setJob(null);
            setAnalysis(null);
            setZones(null);
            setEvidenceSummary(null);
            setTreeCoverStatistics(null);
            setShowTreeCover(false);
            setItemId(event.target.value);
          }}>
            {availableObservations.length === 0 && <option value="">No source scenes available</option>}
            {availableObservations.map((observation) => (
              <option key={observation.item_id} value={observation.item_id}>
                {formatDate(observation.acquisition_datetime)} · {observation.item_id}
              </option>
            ))}
          </select>
        </label>
        <label>
          Zone outer distances (m)
          <input
            aria-label="Zone outer distances in metres"
            value={zoneDistancesText}
            onChange={(event) => setZoneDistancesText(event.target.value)}
          />
        </label>
        <button className="button-primary" type="button" onClick={runAnalysis} disabled={loading || !itemId}>
          <RefreshCw size={14} className={loading ? "spin-icon" : ""} />
          {loading ? "Processing…" : "Run zone analysis"}
        </button>
      </div>

      {catalogStatus === "loading" && <p className="forest-state" role="status"><Activity size={14} /> Loading locally catalogued Sentinel-2 observations…</p>}
      {catalogError && <p className="forest-error" role="alert"><AlertTriangle size={14} /> {catalogError}</p>}
      {error && <p className="forest-error" role="alert"><AlertTriangle size={14} /> {error}</p>}
      {!loading && !error && catalogStatus === "loaded" && !availableObservations.length && (
        <p className="forest-state" role="status">No Sentinel-2 L2A source assets are available for this river in the local catalog.</p>
      )}
      {loading && job && (
        <p className="forest-state" role="status">
          <Activity size={14} /> {job.current_stage || "Queued"}{typeof job.progress_percent === "number" ? ` · ${job.progress_percent}%` : ""}
        </p>
      )}

      <section className="panel forest-map-panel" aria-label="Forest zone map">
        <div className="panel-header">
          <div>
            <h3>River-side analysis map</h3>
            <p className="panel-subtitle">Blue: registered OSM centerline · orange outlines: generated distance zones · raster: observed {selectedIndex.toUpperCase()}; optional green overlay: imported WorldCover tree-cover class.</p>
          </div>
          <div className="forest-map-layers">
            <label className="forest-index-select">
              Index layer
              <select aria-label="Forest index layer" value={selectedIndex} onChange={(event) => setSelectedIndex(event.target.value)}>
                {INDEXES.map((index) => <option value={index} key={index}>{index.toUpperCase()}</option>)}
              </select>
            </label>
            <label>
              <input
                type="checkbox"
                aria-label="Show imported tree-cover reference layer"
                checked={showTreeCover}
                disabled={!treeCoverStatistics}
                onChange={(event) => setShowTreeCover(event.target.checked)}
              />
              WorldCover tree cover
            </label>
          </div>
        </div>
        <ForestMap
          river={river}
          analysis={analysis}
          zones={zones}
          selectedIndex={selectedIndex}
          treeCover={treeCoverStatistics}
          showTreeCover={showTreeCover}
        />
      </section>

      {analysis && (
        <>
          <section className="panel forest-results" aria-label="Forest vegetation statistics">
            <div className="panel-header">
              <div>
                <h3>Observed vegetation-index statistics</h3>
                <p className="panel-subtitle">
                  {analysis.item_id} · {formatDate(analysis.acquisition_datetime)} · {analysis.grid.crs} · {analysis.grid.resolution_m} m
                </p>
              </div>
              <div className="forest-downloads" aria-label="Generated forest analysis downloads">
                <a href={forestAnalysisOutputUrl(analysis.analysis_id, "zones.geojson")}><Download size={13} /> Zones GeoJSON</a>
                <a href={forestAnalysisOutputUrl(analysis.analysis_id, "stats.csv")}><Download size={13} /> Statistics CSV</a>
                {analysis.status === "completed" && INDEXES.map((index) => (
                  <a href={forestAnalysisOutputUrl(analysis.analysis_id, `indices/${index}.tif`)} key={index}>
                    <Download size={13} /> {index.toUpperCase()} GeoTIFF
                  </a>
                ))}
              </div>
            </div>
            <p className="forest-method-note">
              Statistics use pixels in the requested land-area zones, not centerline-clipped index rasters. SCL classes 4 and 5 are retained; clouds, shadows, water, snow and unclassified pixels are excluded.
            </p>
            <div className="forest-chart-grid">
              {INDEXES.map((index) => <IndexChart key={index} zones={analysis.zones} indexName={index} />)}
            </div>
            <div className="forest-table-wrap">
              <table>
                <caption>Per-zone valid support and observed index summaries</caption>
                <thead>
                  <tr><th>Zone</th><th>Zone area km²</th><th>Raster coverage</th><th>Valid data</th><th>NDVI mean</th><th>EVI mean</th><th>NDMI mean</th></tr>
                </thead>
                <tbody>
                  {analysis.zones.map((zone) => (
                    <tr key={zone.zone_id}>
                      <th scope="row">{zone.zone_id}</th>
                      <td>{formatMetric(zone.zone_area_km2, 2)}</td>
                      <td>{formatMetric(zone.raster_coverage_percent, 1)}%</td>
                      <td>{formatMetric(zone.valid_data_coverage_percent, 1)}%</td>
                      <td>{formatMetric(zone.ndvi.mean)}</td>
                      <td>{formatMetric(zone.evi.mean)}</td>
                      <td>{formatMetric(zone.ndmi.mean)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel forest-evidence" aria-label="Forest evidence and limitations">
            <div className="panel-header">
              <div>
                <h3>Evidence, reference data and limitations</h3>
                <p className="panel-subtitle">Processing provenance and limits are returned with each reproducible analysis.</p>
              </div>
              <button type="button" className="button-secondary" onClick={generateEvidenceSummary}>
                <FileSearch size={14} /> Generate evidence summary
              </button>
            </div>
            <div className="forest-reference-import">
              <label>
                ESA WorldCover 2021 v200 GeoTIFF
                <input
                  ref={referenceInput}
                  aria-label="ESA WorldCover GeoTIFF"
                  type="file"
                  accept=".tif,.tiff,image/tiff"
                  onChange={(event) => setReferenceFile(event.target.files?.[0] ?? null)}
                />
              </label>
              <button
                type="button"
                className="button-secondary"
                onClick={importReference}
                disabled={!referenceFile || referenceBusy}
              >
                {referenceBusy ? "Importing…" : "Import reference pixels"}
              </button>
              <label>
                Imported reference
                <select
                  aria-label="Imported forest reference"
                  value={selectedReferenceId}
                  disabled={!importedReferences.length}
                  onChange={(event) => {
                    treeCoverController.current?.abort();
                    setSelectedReferenceId(event.target.value);
                    setTreeCoverStatistics(null);
                    setEvidenceSummary(null);
                  }}
                >
                  {importedReferences.length === 0 && <option value="">No reference pixels imported</option>}
                  {importedReferences.map((reference) => (
                    <option key={reference.reference_id} value={reference.reference_id}>
                      {reference.name} · {reference.source_sha256.slice(0, 12)}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="button-primary"
                onClick={calculateTreeCover}
                disabled={!selectedReferenceId || treeCoverBusy}
              >
                {treeCoverBusy ? "Calculating…" : "Calculate tree-cover statistics"}
              </button>
              {treeCoverBusy && <span role="status">{treeCoverStage}</span>}
              <small>
                Upload a locally obtained single-band WorldCover GeoTIFF. Uploads are size-limited; dataset identity is user-supplied and is not independently authenticated.
              </small>
            </div>
            <div className="forest-evidence-grid">
              <div>
                <strong>Tree cover reference</strong>
                <span>
                  {treeCoverStatistics?.status === "completed"
                    ? "Observed class statistics"
                    : treeCoverStatistics?.status === "no_data"
                      ? "Insufficient valid coverage"
                      : "Not measured"}
                </span>
                <small>
                  {treeCoverStatistics
                    ? `${treeCoverStatistics.dataset_name} class 10; plantations are included and the uploaded source is not independently authenticated.`
                    : `${references?.references?.[0]?.name ?? "Reference metadata unavailable"} is metadata only until reference pixels are imported.`}
                </small>
              </div>
              <div><strong>Temporal change</strong><span>{availableDates < 2 ? "Insufficient dates" : "Compatibility not assessed"}</span><small>{availableDates} distinct processed acquisition time(s); a single date cannot distinguish seasonality from persistent change.</small></div>
              <div><strong>River relationship</strong><span>Not assessed</span><small>No temporally matched, spatially compatible vegetation and river-water observations are available.</small></div>
            </div>
            {treeCoverStatistics && (
              <section className="forest-tree-cover-results" aria-label="Tree-cover reference statistics">
                <p>
                  {treeCoverStatistics.status === "completed"
                    ? `ESA WorldCover ${treeCoverStatistics.reference_year}, class 10 only. Values describe the imported reference and are not independently validated forest area or change.`
                    : "No recognized WorldCover class pixels overlap the valid zone support; the raster is withheld and only coverage statistics are available."}
                </p>
                <div className="forest-downloads">
                  {treeCoverStatistics.status === "completed" && (
                    <a href={forestAnalysisOutputUrl(analysis.analysis_id, `tree-cover/${selectedReferenceId}/tree-cover.tif`)}>
                      <Download size={13} /> Tree-cover class GeoTIFF
                    </a>
                  )}
                  <a href={forestAnalysisOutputUrl(analysis.analysis_id, `tree-cover/${selectedReferenceId}/stats.csv`)}>
                    <Download size={13} /> Tree-cover statistics CSV
                  </a>
                </div>
                <div className="forest-table-wrap">
                  <table>
                    <caption>WorldCover tree-cover class by river-side zone</caption>
                    <thead><tr><th>Zone</th><th>Tree-cover area km²</th><th>Of valid area</th><th>Valid coverage</th></tr></thead>
                    <tbody>{treeCoverStatistics.zones.map((zone) => (
                      <tr key={zone.zone_id}>
                        <th scope="row">{zone.zone_id}</th>
                        <td>{formatMetric(zone.tree_cover_area_km2, 3)}</td>
                        <td>{formatMetric(zone.tree_cover_percent_of_valid_area, 1)}%</td>
                        <td>{formatMetric(zone.valid_data_coverage_percent, 1)}%</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              </section>
            )}
            <div className="forest-caveats">
              <ShieldCheck size={15} />
              <span>{analysis.uncertainty_and_limitations.join(" ")}</span>
            </div>
            {evidenceSummary && (
              <div className="forest-ai-summary" role="status">
                <strong>Deterministic, evidence-grounded summary</strong>
                <p>{evidenceSummary.conclusion}</p>
                <ul>{evidenceSummary.observed_zone_summaries.map((finding) => <li key={finding}>{finding}</li>)}</ul>
              </div>
            )}
          </section>
        </>
      )}
      {catalogStatus === "loaded" && !analysis && (
        <section className="panel forest-temporal-note" aria-label="Temporal comparison availability">
          <strong>Date selection and comparison</strong>
          <span>
            {availableDates < 2
              ? `Only ${availableDates} distinct processed Sentinel-2 acquisition time(s) are available; vegetation change and seasonal trends cannot be estimated.`
              : "Multiple dates exist, but no multi-date comparison is reported until common support, masks and processing compatibility have been checked."}
          </span>
        </section>
      )}
      <span className="sr-only" aria-live="polite">{catalogStatus === "loaded" ? `${availableDates} distinct Sentinel-2 dates available` : ""}</span>
    </section>
  );
}
