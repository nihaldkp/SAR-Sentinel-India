import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  BookOpen,
  ChevronDown,
  CircleHelp,
  Clock3,
  CloudRain,
  Crosshair,
  Download,
  Droplets,
  FileSearch,
  Layers3,
  Map,
  Menu,
  Radio,
  Satellite,
  ShieldAlert,
  Sprout,
  Waves,
  X,
} from "lucide-react";
import {
  GeoJSON,
  ImageOverlay,
  MapContainer,
  Polyline,
  TileLayer,
  useMap,
} from "react-leaflet";
import {
  API_BASE_URL,
  compareSentinel2Observations,
  downloadWorkspaceReport,
  fetchAutomaticAcquisitions,
  fetchSentinel2Observations,
  fetchRivers,
  sentinel2PreviewUrl,
} from "./services/api.js";
import SatelliteSearchPanel from "./components/SatelliteSearchPanel.jsx";
import AnalysisWorkspace from "./components/AnalysisWorkspace.jsx";
import AutomaticAcquisitionPanel from "./components/AutomaticAcquisitionPanel.jsx";
import AIAnalysisPanel from "./components/AIAnalysisPanel.jsx";
import ValidationWorkspace from "./components/ValidationWorkspace.jsx";
import RiverNetworkExplorer from "./components/RiverNetworkExplorer.jsx";

function toLeafletPolyline(geojsonCoordinates) {
  if (!Array.isArray(geojsonCoordinates)) {
    return [];
  }
  return geojsonCoordinates.map(([longitude, latitude]) => [latitude, longitude]);
}

function flattenRiverSegments(geometry) {
  if (!geometry || !Array.isArray(geometry.coordinates)) {
    return [];
  }
  return geometry.coordinates.flatMap((segment) => (
    Array.isArray(segment[0]) ? segment.map(([longitude, latitude]) => [latitude, longitude]) : []
  ));
}

function renderRiverSegments(river, geometryKey, color, active, weight = 4) {
  if (!active || !river?.[geometryKey]?.coordinates) {
    return null;
  }

  return river[geometryKey].coordinates.map((segment, index) => (
    <Polyline
      key={`${river.id}-${geometryKey}-${index}`}
      pathOptions={{ color, weight, opacity: 0.9, fill: false }}
      positions={toLeafletPolyline(segment)}
    />
  ));
}

function buildRealMapRegion(rivers, riverSelection) {
  const activeRivers = riverSelection === "both"
    ? rivers
    : rivers.filter((river) => river.id === riverSelection);
  const points = activeRivers.flatMap((river) => flattenRiverSegments(river.centerline));
  if (!points.length) {
    return { center: [15.72, 75.72], zoom: 6, extent: "Registered river geometry unavailable" };
  }
  const latitudes = points.map(([latitude]) => latitude);
  const longitudes = points.map(([, longitude]) => longitude);
  return {
    center: [
      (Math.min(...latitudes) + Math.max(...latitudes)) / 2,
      (Math.min(...longitudes) + Math.max(...longitudes)) / 2,
    ],
    zoom: activeRivers.length > 1 ? 6 : 8,
    extent: activeRivers.map((river) => river.display_name).join(" · "),
  };
}

const navigation = [
  { label: "Overview", icon: BarChart3 },
  { label: "Map explorer", icon: Map },
  { label: "Change analysis", icon: Activity },
  { label: "Impact explorer", icon: Sprout },
  { label: "Agriculture", icon: Sprout },
  { label: "Forest monitoring", icon: Layers3 },
  { label: "AI analysis", icon: Radio },
];

const secondaryNavigation = [
  { label: "Data & methodology", icon: BookOpen },
  { label: "About the project", icon: CircleHelp },
];
const NO_REAL_MEASUREMENT = "Real observation unavailable — no validated measurement available.";
const LEGACY_DEMONSTRATION_MODE = false;

function MapViewport({ region, rivers, riverSelection, selectedFootprint, selectedAnalysisLayer, selectedOpticalLayer, selectedNetworkFeature }) {
  const map = useMap();
  const [regionLatitude, regionLongitude] = region.center;
  const regionZoom = region.zoom;

  useEffect(() => {
    const observer = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map]);

  useEffect(() => {
    if (selectedNetworkFeature?.geometry?.coordinates) {
      const points = collectGeoJSONPoints(selectedNetworkFeature.geometry.coordinates);
      if (points.length) {
        map.fitBounds(points, { padding: [28, 28] });
        return;
      }
    }
    if (selectedAnalysisLayer?.geojson?.features?.length) {
      const analysisPoints = selectedAnalysisLayer.geojson.features.flatMap((feature) => (
        feature.geometry?.coordinates ? collectGeoJSONPoints(feature.geometry.coordinates) : []
      ));
      if (analysisPoints.length) {
        map.fitBounds(analysisPoints, { padding: [24, 24] });
        return;
      }
    }

    if (selectedOpticalLayer?.boundsWgs84) {
      const { west, south, east, north } = selectedOpticalLayer.boundsWgs84;
      map.fitBounds([[south, west], [north, east]], { padding: [24, 24] });
      return;
    }

    if (selectedFootprint) {
      const footprintPoints = collectGeoJSONPoints(selectedFootprint.coordinates);
      if (footprintPoints.length) {
        map.fitBounds(footprintPoints, { padding: [24, 24] });
        return;
      }
    }

    const activeRivers = riverSelection === "both"
      ? rivers
      : rivers.filter((river) => river.id === riverSelection);

    const riverPoints = activeRivers.flatMap((river) => flattenRiverSegments(river.centerline));
    if (riverPoints.length) {
      const latitudes = riverPoints.map(([latitude]) => latitude);
      const longitudes = riverPoints.map(([, longitude]) => longitude);
      const sw = [Math.min(...latitudes), Math.min(...longitudes)];
      const ne = [Math.max(...latitudes), Math.max(...longitudes)];
      map.fitBounds([sw, ne], { padding: [28, 28] });
      return;
    }

    map.flyTo([regionLatitude, regionLongitude], regionZoom, { duration: 0.65 });
  }, [map, regionLatitude, regionLongitude, regionZoom, rivers, riverSelection, selectedFootprint, selectedAnalysisLayer, selectedOpticalLayer, selectedNetworkFeature]);

  return null;
}

function collectGeoJSONPoints(coordinates) {
  if (!Array.isArray(coordinates)) {
    return [];
  }
  if (coordinates.length >= 2 && coordinates.every((coordinate) => typeof coordinate === "number")) {
    return [[coordinates[1], coordinates[0]]];
  }
  return coordinates.flatMap(collectGeoJSONPoints);
}

function OpticalRasterOverlay({ layer }) {
  const [preview, setPreview] = useState({ status: "loading", url: null });
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl;
    setPreview({ status: "loading", url: null });
    fetch(`${API_BASE_URL}${layer.previewUrl}`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Preview request failed (${response.status}).`);
        }
        if (!response.headers.get("content-type")?.startsWith("image/png")) {
          throw new Error("Preview endpoint did not return a PNG image.");
        }
        return response.blob();
      })
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setPreview({ status: "loaded", url: objectUrl });
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          setPreview({ status: "error", url: null });
        }
      });
    return () => {
      controller.abort();
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [layer.previewUrl]);

  return (
    <>
      {preview.status === "loaded" && (
        <ImageOverlay
          alt="Exploratory Sentinel-2 NDWI candidate raster"
          bounds={[
            [layer.boundsWgs84.south, layer.boundsWgs84.west],
            [layer.boundsWgs84.north, layer.boundsWgs84.east],
          ]}
          opacity={0.9}
          url={preview.url}
        />
      )}
      {preview.status === "loading" && <div className="map-optical-status" role="status">Loading Sentinel-2 preview…</div>}
      {preview.status === "error" && (
        <div className="map-optical-error" role="alert">
          Sentinel-2 preview could not be loaded. The original raster remains available from its product panel.
        </div>
      )}
    </>
  );
}

function Sidebar({ activePage, onNavigate, open, onClose }) {
  const renderLink = ({ label, icon: Icon }) => (
    <button
      aria-current={activePage === label ? "page" : undefined}
      className={`nav-link ${activePage === label ? "nav-link-active" : ""}`}
      key={label}
      onClick={() => {
        onNavigate(label);
        onClose();
      }}
      type="button"
    >
      <Icon size={17} strokeWidth={1.8} />
      <span>{label}</span>
      {label === "Map explorer" && <span className="nav-live-dot" />}
    </button>
  );

  return (
    <>
      {open && <button aria-label="Close navigation overlay" className="sidebar-scrim" onClick={onClose} type="button" />}
      <aside className={`sidebar ${open ? "sidebar-open" : ""}`}>
        <div className="brand-lockup">
          <div className="brand-mark"><Satellite size={20} /></div>
          <div>
            <div className="brand-name">SAR Sentinel</div>
            <div className="brand-region">INDIA · EARTH OBSERVATION</div>
          </div>
          <button aria-label="Close menu" className="icon-button sidebar-close" onClick={onClose} type="button"><X size={18} /></button>
        </div>

        <div className="sidebar-nav-scroll">
          <div className="sidebar-label">WORKSPACE</div>
          <nav aria-label="Main navigation" className="nav-stack">{navigation.map(renderLink)}</nav>

          <div className="sidebar-label secondary-label">PROJECT</div>
          <nav aria-label="Project navigation" className="nav-stack">{secondaryNavigation.map(renderLink)}</nav>
        </div>

        <div className="sidebar-bottom">
          <div className="mission-mini">
            <div className="mission-mini-icon"><Waves size={17} /></div>
            <p>See the change.<br /><strong>Understand the risk.</strong></p>
          </div>
          <div className="sidebar-footnote">NASA SPACE APPS CHALLENGE · 2026</div>
        </div>
      </aside>
    </>
  );
}

function MetricCard({ icon: Icon, label, value, note, trend, tone }) {
  return (
    <article className="metric-card">
      <div className={`metric-icon metric-icon-${tone}`}><Icon size={17} strokeWidth={1.8} /></div>
      <div className="metric-copy">
        <div className="metric-label">{label}</div>
        <div className="metric-value">{value}</div>
        <div className="metric-note">{trend && <span className={`metric-trend ${trend.startsWith("+") ? "trend-up" : ""}`}>{trend.startsWith("+") ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}{trend}</span>}{note}</div>
      </div>
    </article>
  );
}

function formatEvidenceDate(value) {
  if (!value) {
    return "Date not available";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date not available"
    : new Intl.DateTimeFormat("en-GB", {
      dateStyle: "medium",
      timeZone: "UTC",
    }).format(date);
}

function formatEvidenceNumber(value, maximumFractionDigits = 1) {
  return Number.isFinite(value)
    ? new Intl.NumberFormat("en-IN", { maximumFractionDigits }).format(value)
    : "Not available";
}

function evidenceProducts(catalog, riverSelection) {
  const rivers = catalog?.rivers ?? [];
  return rivers
    .filter((river) => riverSelection === "both" || river.river_id === riverSelection)
    .flatMap((river) => (river.nisar_products ?? []).map((product) => ({
      ...product,
      river_id: river.river_id,
    })))
    .sort((left, right) => (
      new Date(right.acquisition_start ?? 0).getTime()
      - new Date(left.acquisition_start ?? 0).getTime()
    ));
}

function evidenceSources(catalog, riverSelection) {
    const rivers = (catalog?.rivers ?? []).filter((river) => (
      riverSelection === "both" || river.river_id === riverSelection
    ));
    return {
      nisarProducts: rivers.flatMap((river) => river.nisar_products ?? []),
      sentinelObservations: rivers.flatMap((river) => river.observations ?? []),
    };
}

function EvidenceProductRow({ product }) {
  const result = product.processing_result;
  const status = result?.status ?? product.processing_status ?? product.download_status;
  const isCandidate = status === "unvalidated_candidate";
  const isNoData = status === "no_valid_corridor_data" || product.processing_status === "no_data";
  const isFailure = status === "failed" || status === "processing_failed" || status === "error";
  return (
    <article className="evidence-product">
      <div className="evidence-product-heading">
        <div>
          <strong className="evidence-product-id">{product.product_id}</strong>
          <span>{product.river_id} · {formatEvidenceDate(product.acquisition_start)}</span>
          <span className="evidence-product-source">
            {product.local_path ? "Recovered locally · NISAR L2 UR GCOV acquisition" : "NISAR L2 UR GCOV catalog acquisition"}
          </span>
        </div>
        <span className={`evidence-status ${isCandidate ? "evidence-status-candidate" : isNoData ? "evidence-status-empty" : ""}`}>
          {isCandidate ? "Processed — unvalidated candidate" : isNoData ? "Processed — no usable corridor data" : isFailure ? "Processing failed" : String(status ?? "Not processed").replaceAll("_", " ")}
        </span>
      </div>
      {isCandidate && result ? (
        <div className="evidence-facts">
          <span>CRS <strong>{result.input_crs}</strong></span>
          <span>Resolution <strong>{formatEvidenceNumber(result.pixel_size_m, 1)} m</strong></span>
          <span>Valid pixels <strong>{formatEvidenceNumber(result.valid_pixel_count, 0)}</strong> ({formatEvidenceNumber((result.valid_data_fraction ?? 0) * 100, 1)}%)</span>
          <span>Corridor coverage <strong>{formatEvidenceNumber(result.reference_centerline_coverage_percent, 1)}%</strong></span>
          <span>Candidate area <strong>{formatEvidenceNumber(result.candidate_water_area_m2, 1)} m²</strong></span>
        </div>
      ) : isNoData && result ? (
        <p className="evidence-note">
          No candidate mask was generated because {formatEvidenceNumber(result.valid_pixel_count, 0)} valid paired HH/HV pixels were available in {formatEvidenceNumber(result.corridor_pixel_count, 0)} corridor pixels. This is a processing outcome, not a failed satellite acquisition.
        </p>
      ) : isFailure ? (
        <p className="evidence-note">Processing failed; no candidate measurement is available for this acquisition.</p>
      ) : (
        <p className="evidence-note">The product is recorded locally but processing has not produced a usable result.</p>
      )}
    </article>
  );
}

function AcquisitionEvidence({ catalog, status, error, riverSelection }) {
  const products = evidenceProducts(catalog, riverSelection);
  if (status === "loading") {
    return <div className="workspace-empty" role="status">Loading locally recovered NISAR acquisitions…</div>;
  }
  if (status === "error") {
    return <div className="workspace-empty workspace-empty-error" role="alert">{error}</div>;
  }
  if (!products.length) {
    return <div className="workspace-empty">No locally recovered NISAR products are available for the selected river.</div>;
  }
  return (
    <div className="evidence-list">
      {products.map((product) => <EvidenceProductRow key={product.product_id} product={product} />)}
    </div>
  );
}

function SentinelObservationEvidence({ catalog, status, error, riverSelection }) {
  const { sentinelObservations } = evidenceSources(catalog, riverSelection);
  if (status === "loading") {
    return <div className="workspace-empty" role="status">Loading Sentinel-1 observations…</div>;
  }
  if (status === "error") {
    return <div className="workspace-empty workspace-empty-error" role="alert">{error}</div>;
  }
  if (!sentinelObservations.length) {
    return <div className="workspace-empty">No Sentinel-1 observation is available for the selected river.</div>;
  }
  return (
    <div className="evidence-list">
      {sentinelObservations.map((observation) => {
        const isCandidate = observation.processing_status === "unvalidated_candidate";
        const isNoData = observation.processing_status === "no_data";
        return (
          <article className="evidence-product" key={observation.product_id}>
            <div className="evidence-product-heading">
              <div>
                <strong className="evidence-product-id">{observation.product_id}</strong>
                <span>{formatEvidenceDate(observation.acquisition_start)} · {observation.polarization ?? "Polarization unavailable"}</span>
                <span className="evidence-product-source">{observation.source ?? "Sentinel-1 source unavailable"} · {observation.product_type ?? "Product type unavailable"}</span>
              </div>
              <span className={`evidence-status ${isCandidate ? "evidence-status-candidate" : isNoData ? "evidence-status-empty" : ""}`}>
                {isCandidate ? "Processed — scientifically unvalidated candidate" : isNoData ? "No valid data" : String(observation.processing_status ?? "Unavailable").replaceAll("_", " ")}
              </span>
            </div>
            {isCandidate ? (
              <div className="evidence-facts">
                <span>Valid pixels <strong>{formatEvidenceNumber(observation.valid_pixel_count, 0)}</strong> ({formatEvidenceNumber((observation.valid_data_fraction ?? 0) * 100, 1)}%)</span>
                <span>Candidate pixels <strong>{formatEvidenceNumber(observation.water_pixel_count, 0)}</strong></span>
                <span>Candidate area <strong>{formatEvidenceNumber(observation.candidate_water_area_m2 / 1_000_000, 4)} km²</strong></span>
                <span>Coverage <strong>{formatEvidenceNumber(observation.centerline_coverage_percent, 2)}%</strong></span>
              </div>
            ) : (
              <p className="evidence-note">No candidate measurement is available for this observation.</p>
            )}
          </article>
        );
      })}
    </div>
  );
}

function ImpactExplorer({ catalog, status, error, riverSelection }) {
  const products = evidenceProducts(catalog, riverSelection);
  const candidates = products
    .filter((product) => (
      product.processing_result?.status === "unvalidated_candidate" &&
      Number.isFinite(product.processing_result.valid_pixel_count) &&
      Number.isFinite(product.processing_result.candidate_water_area_m2)
    ))
    .sort((left, right) => (
      new Date(right.acquisition_start ?? 0).getTime() - new Date(left.acquisition_start ?? 0).getTime()
    ));
  const selectedCandidate = candidates[0];
  const selectedResult = selectedCandidate?.processing_result;
  const metricsReady = status === "loaded";
  return (
    <section className="workspace-section" aria-label="Impact explorer">
      <div className="workspace-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow-line" /> REAL ACQUISITION EVIDENCE</div>
          <h2>Impact explorer</h2>
          <p>Locally recovered NISAR GCOV observations and their exploratory corridor-level processing outputs.</p>
        </div>
        <span className="evidence-disclosure">Candidate classifications · not validated impact</span>
      </div>
      <div className="workspace-metrics">
        <MetricCard icon={Satellite} label="Recovered products" value={metricsReady ? String(products.length) : "Not available"} note="NISAR GCOV records" tone="blue" />
        <MetricCard icon={Crosshair} label="Valid pixels" value={metricsReady && selectedResult ? formatEvidenceNumber(selectedResult.valid_pixel_count, 0) : "Unavailable"} note="selected candidate only" tone="teal" />
        <MetricCard icon={Droplets} label="Candidate area" value={metricsReady && selectedResult ? `${formatEvidenceNumber(selectedResult.candidate_water_area_m2, 1)} m²` : "Unavailable"} note="not flood extent" tone="amber" />
      </div>
      {metricsReady && selectedCandidate ? (
        <div className="comparison-callout" aria-label="Selected impact candidate">
          <strong>Selected acquisition:</strong>{" "}
          {selectedCandidate.product_id} · {formatEvidenceDate(selectedCandidate.acquisition_start)} ·{" "}
          {selectedCandidate.local_path ? "Recovered locally · NISAR L2 UR GCOV" : "NISAR L2 UR GCOV catalog record"} ·{" "}
          Processed — scientifically unvalidated candidate. Historical acquisitions and Sentinel-1 records are not included in these metrics.
        </div>
      ) : metricsReady ? (
        <div className="workspace-empty" role="status">No eligible NISAR candidate is available for the selected river. Candidate metrics are unavailable.</div>
      ) : null}
      <div className="panel workspace-panel">
        <div className="panel-header">
          <div><h2>Acquisition evidence</h2><p className="panel-subtitle">A_009 and A_010 remain separate observations with separate processing outcomes.</p></div>
        </div>
        <AcquisitionEvidence catalog={catalog} status={status} error={error} riverSelection={riverSelection} />
      </div>
    </section>
  );
}

function ChangeAnalysis({ catalog, status, error, riverSelection }) {
  const products = evidenceProducts(catalog, riverSelection);
  const candidates = products.filter((product) => product.processing_result?.status === "unvalidated_candidate");
  const matchingGridMetadata = candidates.length > 1 && new Set(
    candidates.map((product) => `${product.processing_result.input_crs}:${product.processing_result.pixel_size_m}`),
  ).size === 1;
  return (
    <section className="workspace-section" aria-label="Change analysis">
      <div className="workspace-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow-line" /> TEMPORAL EVIDENCE</div>
          <h2>Change analysis</h2>
          <p>Available acquisition dates and processing states are shown without inventing a change percentage.</p>
        </div>
        <span className="evidence-disclosure">No unvalidated change claim</span>
      </div>
      <div className="panel workspace-panel">
        <div className="panel-header">
          <div><h2>Observation timeline</h2><p className="panel-subtitle">Comparisons require compatible candidate masks and a documented comparison operation.</p></div>
        </div>
        <AcquisitionEvidence catalog={catalog} status={status} error={error} riverSelection={riverSelection} />
        {status === "loaded" && (
          <div className="comparison-callout">
            {matchingGridMetadata
              ? "Some candidates share declared CRS and resolution, but spatial overlap and comparison compatibility have not been established here. No change percentage is calculated."
              : "Change detection is unavailable because two compatible candidate masks are required; no change percentage is calculated."}
          </div>
        )}
      </div>
    </section>
  );
}

function RealOverview({
  catalog,
  status,
  error,
  riverSelection,
  rivers,
  riverLayers,
  riverStatus,
  riverError,
  selectedObservation,
  selectedFootprint,
  selectedAnalysisLayer,
  selectedOpticalLayer,
  selectedNetworkFeature,
  onToggleRiverLayer,
  onSelectAnalysisGeometry,
  onToggleOpticalLayer,
  onSelectNetworkFeature,
  cancelNetworkSelection,
  mapFocused,
}) {
  const { nisarProducts, sentinelObservations } = evidenceSources(catalog, riverSelection);
  const candidateNisarProducts = nisarProducts.filter((product) => product.processing_result?.status === "unvalidated_candidate");
  const candidateSentinelObservations = sentinelObservations.filter((observation) => observation.processing_status === "unvalidated_candidate");
  const processedCandidates = candidateNisarProducts.length + candidateSentinelObservations.length;
  const candidateRecords = [
    ...candidateNisarProducts.map((product) => ({
      acquisition_start: product.acquisition_start,
      candidatePixels: product.processing_result?.water_pixel_count,
      candidateAreaM2: product.processing_result?.candidate_water_area_m2,
    })),
    ...candidateSentinelObservations.map((observation) => ({
      acquisition_start: observation.acquisition_start,
      candidatePixels: observation.water_pixel_count,
      candidateAreaM2: observation.candidate_water_area_m2,
    })),
  ].sort((left, right) => (
    new Date(right.acquisition_start ?? 0).getTime() - new Date(left.acquisition_start ?? 0).getTime()
  ));
  const latestCandidate = candidateRecords[0];
  const candidatePixels = latestCandidate?.candidatePixels;
  const candidateAreaM2 = latestCandidate?.candidateAreaM2;
  const catalogObservationCount = nisarProducts.length + sentinelObservations.length;
  const candidateArea = processedCandidates > 0 && Number.isFinite(candidateAreaM2) && candidateAreaM2 > 0
    ? `${formatEvidenceNumber(candidateAreaM2 / 1_000_000, 4)} km²`
    : "Unavailable";
  const region = buildRealMapRegion(rivers, riverSelection);
  const visibleRivers = riverSelection === "both"
    ? rivers
    : rivers.filter((river) => river.id === riverSelection);

  return (
    <>
      <section aria-label="Real satellite overview" className="metrics-grid">
        <MetricCard icon={Satellite} label="Catalog observations" value={status === "loaded" ? String(catalogObservationCount) : NO_REAL_MEASUREMENT} note="NISAR + Sentinel-1 records" tone="blue" />
        <MetricCard icon={Activity} label="Processed candidates" value={status === "loaded" ? String(processedCandidates) : NO_REAL_MEASUREMENT} note="unvalidated candidate results" tone="amber" />
        <MetricCard icon={Crosshair} label="Latest candidate pixels" value={status === "loaded" && Number.isFinite(candidatePixels) ? formatEvidenceNumber(candidatePixels, 0) : "Unavailable"} note="unvalidated water classification" tone="teal" />
        <MetricCard icon={Droplets} label="Latest candidate area" value={status === "loaded" ? candidateArea : NO_REAL_MEASUREMENT} note="not validated inundation" tone="slate" />
      </section>

      <section className={`analysis-grid ${mapFocused ? "map-focused" : ""}`}>
        <article className="panel map-panel">
          <div className="panel-header map-panel-header">
            <div>
              <div className="panel-title-row"><h2>Satellite evidence map</h2><span className="panel-live-tag"><span /> REAL DATA ONLY</span></div>
              <p className="panel-subtitle">{region.extent}</p>
              <p className="panel-subtitle">Registered river geometry and selected georeferenced evidence layers are shown when available.</p>
              <p className="panel-subtitle">A registered centerline does not establish monitoring coverage.</p>
            </div>
            <div className="river-layer-controls">
              <button aria-pressed={riverLayers.centerline} className={riverLayers.centerline ? "river-layer-button active" : "river-layer-button"} onClick={() => onToggleRiverLayer("centerline")} type="button">Centerline</button>
              <button aria-pressed={riverLayers.leftBank} className={riverLayers.leftBank ? "river-layer-button active" : "river-layer-button"} disabled={riverStatus !== "loaded"} onClick={() => onToggleRiverLayer("leftBank")} type="button">Left bank</button>
              <button aria-pressed={riverLayers.rightBank} className={riverLayers.rightBank ? "river-layer-button active" : "river-layer-button"} disabled={riverStatus !== "loaded"} onClick={() => onToggleRiverLayer("rightBank")} type="button">Right bank</button>
            </div>
          </div>
          {riverStatus === "loading" && <div className="river-data-status" role="status">Loading registered river geometry…</div>}
          {riverStatus === "error" && <div className="river-data-error" role="alert">River geometry could not be loaded: {riverError}</div>}
          <div className="map-frame">
            <ChangeMap
              region={region}
              layer="real-observations"
              onSelectChange={() => {}}
              rivers={rivers}
              riverSelection={riverSelection}
              riverLayers={riverLayers}
              selectedObservation={selectedObservation}
              selectedFootprint={selectedFootprint}
              selectedAnalysisLayer={selectedAnalysisLayer}
              selectedOpticalLayer={selectedOpticalLayer}
              selectedNetworkFeature={selectedNetworkFeature}
            />
            <div className="map-legend">
              <div className="legend-title">MAP KEY · REAL SOURCES</div>
              {riverLayers.centerline && visibleRivers.map((river) => (
                <div className="legend-item" key={`real-river-legend-${river.id}`}>
                  <span className={`legend-swatch ${river.id === "kaveri" ? "kaveri-swatch" : "tungabhadra-swatch"}`} />
                  {river.name} · OSM
                </div>
              ))}
              {riverLayers.leftBank && <div className="legend-item legend-item-muted">{visibleRivers.some((river) => river.left_bank_boundary) ? "Left bank boundary" : "Left bank boundary data unavailable"}</div>}
              {riverLayers.rightBank && <div className="legend-item legend-item-muted">{visibleRivers.some((river) => river.right_bank_boundary) ? "Right bank boundary" : "Right bank boundary data unavailable"}</div>}
              {selectedFootprint && <div className="legend-item"><span className="legend-swatch footprint-swatch" />{selectedObservation?.mission ?? "Satellite"} footprint · metadata only</div>}
              {selectedNetworkFeature && <div className="legend-item">NWIC: {selectedNetworkFeature.name || "Unnamed feature"} · registered, monitoring unknown</div>}
              {selectedAnalysisLayer && (
                <>
                  <div className="legend-item"><span className="legend-swatch analysis-water-swatch" />Candidate water · unvalidated</div>
                  <div className="legend-item"><span className="legend-swatch analysis-coverage-swatch" />Candidate polygons only · outside not shown</div>
                </>
              )}
              {selectedOpticalLayer && (
                <>
                  <div className="legend-item"><span className="legend-swatch optical-candidate-swatch" />Candidate water · exploratory</div>
                  <div className="legend-item"><span className="legend-swatch optical-noncandidate-swatch" />Not classified as candidate</div>
                  <div className="legend-item"><span className="legend-swatch optical-nodata-swatch" />NoData / invalid / unavailable</div>
                  <div className="optical-map-warning">EXPLORATORY SENTINEL-2 NDWI OUTPUT — NOT GROUND TRUTH.</div>
                </>
              )}
              {!selectedFootprint && !selectedAnalysisLayer && !selectedOpticalLayer && (
                <div className="legend-item legend-item-muted">Select a persisted acquisition or processed output to display its georeferenced layer.</div>
              )}
            </div>
            <div className="map-attribution-note">River geometry: OpenStreetMap contributors · satellite layers: persisted product outputs when selected</div>
          </div>
        </article>

        <article className="panel workspace-panel">
          <div className="panel-header">
            <div><h2>Observation evidence</h2><p className="panel-subtitle">Actual acquisition metadata and processing outcomes from the backend catalog.</p></div>
          </div>
          <AcquisitionEvidence catalog={catalog} status={status} error={error} riverSelection={riverSelection} />
        </article>
      </section>

      <RiverNetworkExplorer selected={selectedNetworkFeature} cancelSelectionRef={cancelNetworkSelection} onSelect={onSelectNetworkFeature} />
    </>
  );
}

function MethodologySection() {
  const steps = [
    ["Discovery and recovery", "NISAR L2 GCOV products are discovered through ASF metadata and locally recovered products are structurally checked as NISAR GCOV HDF5 files."],
    ["HH/HV processing", "Frequency-A HHHH and HVHV gamma0 linear-power datasets are read with the product validity mask and mapped river corridor."],
    ["Candidate thresholding", "Power is converted with 10*log10(max(power, 1e-6)); independent 900-bin Otsu thresholds classify pixels where both HH and HV are below threshold."],
    ["Outputs and metadata", "The pipeline writes a NoData-preserving candidate mask GeoTIFF, two-band measurement GeoTIFF, display-only GeoJSON, and processing metadata."],
    ["Sentinel-1 RTC workflow", "The application reads real Sentinel-1 RTC VV calibrated linear-intensity COG pixels from Microsoft Planetary Computer inside a 3,000 m OSM centerline corridor. Upstream Catalyst RTC radiometric calibration and terrain correction are recorded as provenance; this application does not repeat those upstream steps."],
    ["Sentinel-1 classification limits", "The shared processing converts positive linear power to dB, applies the implemented 5x5 Lee local-statistic filter, estimates an independent Otsu threshold, and writes NoData-preserving candidate outputs. Valid-pixel support and centerline coverage are persisted; the result is an unvalidated candidate, not a validated water or flood measurement."],
  ];
  return (
    <section className="workspace-section" aria-label="Data and methodology">
      <div className="workspace-heading">
        <div><div className="eyebrow"><span className="eyebrow-line" /> REPRODUCIBLE PIPELINE</div><h2>Data & methodology</h2><p>Implemented processing steps and the boundaries of what the outputs mean.</p></div>
      </div>
      <div className="methodology-grid">
        {steps.map(([title, description], index) => (
          <article className="panel methodology-card" key={title}><span className="methodology-index">0{index + 1}</span><h2>{title}</h2><p>{description}</p></article>
        ))}
      </div>
      <div className="panel limitations-panel">
        <h2>Interpretation limits</h2>
        <p>Candidate pixels can also represent radar-dark surfaces, shadow, or other non-water targets. The corridor buffer and threshold sensitivity are exploratory diagnostics; no ground-truth accuracy assessment, flood validation, riverbank measurement, or scientific validation is performed.</p>
      </div>
    </section>
  );
}

function AboutSection() {
  return (
    <section className="workspace-section" aria-label="About the project">
      <div className="workspace-heading">
        <div><div className="eyebrow"><span className="eyebrow-line" /> NASA SPACE APPS CHALLENGE 2026</div><h2>About the project</h2><p>Understanding Indian rivers through openly documented satellite observation workflows.</p></div>
      </div>
      <div className="about-grid">
        <article className="panel about-card"><h2>Purpose</h2><p>SAR Sentinel India helps teams inspect river and water-body observations, connect them to mapped river corridors, and hand reproducible candidate outputs to GIS analysts.</p></article>
        <article className="panel about-card"><h2>Supported observations</h2><p>The application supports NISAR GCOV acquisition and candidate processing, Sentinel-1 RTC acquisition and candidate analysis, and OpenStreetMap river centerline context where records are available.</p></article>
        <article className="panel about-card"><h2>Current capability</h2><p>Real product records, processing metadata, masks, measurements, and display polygons can be inspected. Overview metrics are derived from the selected river's persisted acquisition records; unavailable measurements are not replaced with illustrative values.</p></article>
        <article className="panel about-card"><h2>Responsible interpretation</h2><p>Outputs labeled candidate or unvalidated are not verified inundation, damage, river boundaries, erosion, deposition, or environmental measurements. Independent GIS and scientific review remains necessary.</p></article>
      </div>
    </section>
  );
}

function Sentinel2MapViewport({ bounds }) {
  const map = useMap();
  useEffect(() => {
    if (bounds) {
      map.fitBounds([[bounds.south, bounds.west], [bounds.north, bounds.east]], { padding: [18, 18] });
    }
  }, [bounds, map]);
  return null;
}

function Sentinel2Preview({ record, indexName, refreshVersion }) {
  const [failed, setFailed] = useState(false);
  return (
    <figure>
      {failed ? (
        <div className="sentinel2-preview-error" role="status">Preview unavailable. Check the API and try refreshing the records.</div>
      ) : (
        <img
          src={`${sentinel2PreviewUrl(record.river_id, record.item_id, indexName, { overview: true })}${refreshVersion ? `&refresh=${refreshVersion}` : ""}`}
          alt={`${indexName.toUpperCase()} spatial index preview for ${record.item_id}`}
          loading="lazy"
          onError={() => setFailed(true)}
        />
      )}
      <figcaption>
        {indexName.toUpperCase()} · valid-pixel mean overview ·{" "}
        <a href={sentinel2PreviewUrl(record.river_id, record.item_id, indexName)} target="_blank" rel="noreferrer">Full-resolution PNG</a>
      </figcaption>
    </figure>
  );
}

function Sentinel2IndexMap({ record, indexName, onIndexChange, opacity, onOpacityChange }) {
  const bounds = record?.bounds_wgs84;
  const colorScale = record?.preview_color_scale;
  if (!record || record.status !== "processed" || !bounds) {
    return (
      <div className="sentinel2-map-unavailable" role="status">
        Real raster map unavailable — this observation has no georeferenced processed output.
      </div>
    );
  }
  return (
    <div className="sentinel2-map-panel">
      <div className="sentinel2-map-controls">
        <label>
          Index
          <select value={indexName} onChange={(event) => onIndexChange(event.target.value)}>
            <option value="ndvi">NDVI</option>
            <option value="evi">EVI</option>
            <option value="ndmi">NDMI</option>
          </select>
        </label>
        <label>
          Opacity
          <input
            type="range"
            min="0.1"
            max="1"
            step="0.05"
            value={opacity}
            onChange={(event) => onOpacityChange(Number(event.target.value))}
          />
          <span>{Math.round(opacity * 100)}%</span>
        </label>
      </div>
      <MapContainer
        center={[(bounds.south + bounds.north) / 2, (bounds.west + bounds.east) / 2]}
        zoom={10}
        scrollWheelZoom
        className="sentinel2-leaflet-map"
      >
        <Sentinel2MapViewport bounds={bounds} />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <ImageOverlay
          alt={`${indexName.toUpperCase()} raster for ${record.item_id}`}
          bounds={[[bounds.south, bounds.west], [bounds.north, bounds.east]]}
          opacity={opacity}
          url={sentinel2PreviewUrl(record.river_id, record.item_id, indexName)}
        />
      </MapContainer>
      <div className="sentinel2-map-footer">
        <span>{indexName.toUpperCase()} · -1</span>
        <span
          className="sentinel2-color-scale"
          style={{ background: `linear-gradient(90deg, ${colorScale?.low || "#313695"}, ${colorScale?.middle || "#ffffbf"}, ${colorScale?.high || "#006837"})` }}
        />
        <span>+1 · transparent NoData</span>
      </div>
      <p className="panel-subtitle">Real {indexName.toUpperCase()} GeoTIFF rendered within its WGS84 bounds. The fixed scale clips values outside -1 to +1; the middle colour represents 0. Date: {new Date(record.acquisition_datetime).toLocaleString()} · Product: {record.item_id}</p>
    </div>
  );
}

function LandMonitoringSection({ title, eyebrow, description, catalog, status, error, riverSelection, domain, onReportContext }) {
  const [sentinel2ByRiver, setSentinel2ByRiver] = useState({});
  const [sentinel2Status, setSentinel2Status] = useState("loading");
  const [sentinel2Error, setSentinel2Error] = useState("");
  const [sentinel2Refresh, setSentinel2Refresh] = useState(0);
  const [selectedIndex, setSelectedIndex] = useState("ndvi");
  const [mapOpacity, setMapOpacity] = useState(0.85);
  const [selectedRecordKey, setSelectedRecordKey] = useState("");
  const { nisarProducts, sentinelObservations } = evidenceSources(catalog, riverSelection);
  useEffect(() => {
    const controller = new AbortController();
    const riverIds = riverSelection === "both" ? ["kaveri", "tungabhadra"] : [riverSelection];
    setSentinel2Status("loading");
    setSentinel2Error("");
    Promise.all(riverIds.map((riverId) => fetchSentinel2Observations(riverId, { signal: controller.signal })))
      .then((responses) => {
        setSentinel2ByRiver(Object.fromEntries(responses.map((response) => [response.river_id, response])));
        setSentinel2Status("loaded");
      })
      .catch((fetchError) => {
        if (fetchError.name !== "AbortError") {
          setSentinel2Error(fetchError.message);
          setSentinel2Status("error");
        }
      });
    return () => controller.abort();
  }, [riverSelection, sentinel2Refresh]);
  const sentinel2Records = sentinel2Status === "loaded"
    ? Object.values(sentinel2ByRiver).flatMap((response) => response.observations)
    : [];
  const processedRecords = sentinel2Records.filter((record) => record.status === "processed");
  const selectedRecord = processedRecords.find((record) => `${record.river_id}-${record.item_id}` === selectedRecordKey)
    || processedRecords[0]
    || null;
  useEffect(() => {
    onReportContext({
      domain, riverSelection, status: sentinel2Status,
      riverId: selectedRecord?.river_id ?? null,
      itemId: selectedRecord?.item_id ?? null,
      indexName: selectedIndex,
    });
  }, [domain, riverSelection, sentinel2Status, selectedRecord, selectedIndex, onReportContext]);
  const historicalComparisons = sentinel2Status === "loaded"
    ? Object.values(sentinel2ByRiver).flatMap((response) => response.historical_comparisons || [])
    : [];
  const sourceSummary = sentinel2Status === "loading"
    ? "Loading Sentinel-2 observations."
    : sentinel2Status === "error"
      ? "Sentinel-2 observations could not be loaded."
      : processedRecords.length
        ? "Processed Sentinel-2 observations are available for the selected river."
        : status === "loading"
          ? "Loading the other satellite acquisition catalog."
          : status === "error"
            ? "The other satellite acquisition catalog is unavailable."
            : nisarProducts.length || sentinelObservations.length
              ? "Satellite records are available for inspection, but no processed Sentinel-2 vegetation index is cached."
              : "No compatible satellite observation is currently available for the selected river.";
  return (
    <section className="workspace-section" aria-label={title}>
      <div className="workspace-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow-line" /> {eyebrow}</div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        <span className="evidence-disclosure">{sentinel2Status === "loading" ? "Loading Sentinel-2" : sentinel2Status === "error" ? "Sentinel-2 unavailable" : processedRecords.length ? "Processed Sentinel-2 indices" : `No ${domain} index available`}</span>
      </div>
      <div className="panel monitoring-status-panel">
        <div className="monitoring-status-icon"><Satellite size={18} /></div>
        <div>
          <h2>{sentinel2Status === "loading" ? "Loading Sentinel-2 observations" : sentinel2Status === "error" ? "Sentinel-2 observations unavailable" : processedRecords.length ? "Sentinel-2 vegetation indices are available" : "Vegetation indicators are not available"}</h2>
          <p>{sourceSummary} {sentinel2Status === "loaded" && (processedRecords.length ? "NDVI, EVI and NDMI remain unvalidated except for the sample-scoped index assessments shown below; crop classes, forest-loss measurements, health scores, and yield estimates are not generated by the current application." : "NDVI, EVI, crop classes, forest-loss measurements, health scores, and yield estimates are not generated by the current application.")}</p>
        </div>
        {domain === "forest" && (
          <div className="monitoring-limitations">
            <strong>Forest-specific evidence is not yet available</strong>
            <span>These indices describe spectral vegetation and moisture signals, not forest cover or forest loss. Distinguishing natural forest from plantations and agricultural vegetation requires suitable independent land-cover references; forest classification and change validation are not implemented.</span>
            <span>River-distance zones (0–100 m, 100–500 m and 500–1,000 m) and near-versus-outer comparisons are unavailable: the saved index rasters sample only the mapped centerline, and no suitable local tree-cover reference is integrated.</span>
          </div>
        )}
      </div>
      <div className="panel workspace-panel sentinel2-monitoring-panel">
        <div className="panel-header">
          <div>
            <h2>Sentinel-2 Level-2A vegetation indices</h2>
            <p className="panel-subtitle">Microsoft Planetary Computer surface-reflectance observations, independently masked and processed at the recorded output resolution. Only valid pixels on the mapped centerline are shown; the surrounding rectangle is transparent. Zoom in on the map to inspect the narrow valid areas.</p>
            <p className="panel-subtitle">Thumbnail cells show the mean of valid source pixels in each cell; their visible footprint is not the measured area. The map uses the full-resolution raster.</p>
          </div>
          <div className="sentinel2-panel-actions">
            <span className="evidence-disclosure">{sentinel2Status === "loaded" ? `${sentinel2Records.length} record${sentinel2Records.length === 1 ? "" : "s"}` : sentinel2Status === "error" ? "Unavailable" : "Loading"}</span>
            <button type="button" onClick={() => setSentinel2Refresh((value) => value + 1)}>Refresh saved records</button>
          </div>
        </div>
        {sentinel2Error && <p className="inline-error">{sentinel2Error}</p>}
        {!sentinel2Error && sentinel2Status === "loading" && <p role="status">Loading genuine Sentinel-2 observations…</p>}
        {sentinel2Status === "loaded" && !sentinel2Records.length && (
          <p>Real observation unavailable — no Sentinel-2 product with the required B02, B04, B08, B11 and SCL assets is cached for this river.</p>
        )}
        {processedRecords.length > 0 && (
          <>
            <label className="sentinel2-record-selector">
              Map observation
              <select
                value={selectedRecord ? `${selectedRecord.river_id}-${selectedRecord.item_id}` : ""}
                onChange={(event) => setSelectedRecordKey(event.target.value)}
              >
                {processedRecords.map((record) => (
                  <option key={`${record.river_id}-${record.item_id}`} value={`${record.river_id}-${record.item_id}`}>
                    {record.river_id} · {record.item_id} · {new Date(record.acquisition_datetime).toLocaleDateString()}
                  </option>
                ))}
              </select>
            </label>
            <Sentinel2IndexMap
              record={selectedRecord}
              indexName={selectedIndex}
              onIndexChange={setSelectedIndex}
              opacity={mapOpacity}
              onOpacityChange={setMapOpacity}
            />
          </>
        )}
        {historicalComparisons.length > 0 && (
          <div className="sentinel2-history">
            <h3>Compatible historical comparison</h3>
            {historicalComparisons.map((comparison) => (
              <div key={`${comparison.earlier_item_id}-${comparison.later_item_id}`} className="sentinel2-history-card">
                <strong>{new Date(comparison.earlier_acquisition_datetime).toLocaleDateString()} → {new Date(comparison.later_acquisition_datetime).toLocaleDateString()}</strong>
                <span>{comparison.interval_days.toFixed(1)} days · {comparison.common_valid_pixel_count} common valid pixels · {comparison.common_support_percent_of_earlier.toFixed(2)}% common support</span>
                <div className="sentinel2-history-indices">
                  {["ndvi", "evi", "ndmi"].map((indexName) => (
                    <span key={indexName}>{indexName.toUpperCase()} Δ {comparison.indices[indexName].mean_difference.toFixed(4)}</span>
                  ))}
                </div>
                <small>Unvalidated index difference only; not evidence of crop failure, deforestation, degradation, or confirmed environmental change.</small>
              </div>
            ))}
          </div>
        )}
        {sentinel2Records.map((record) => (
          <article className="sentinel2-observation" key={`${record.river_id}-${record.item_id}`}>
            <div className="sentinel2-observation-header">
              <div>
                <h3>{record.river_id} · {record.item_id}</h3>
                <p>{record.acquisition_datetime ? new Date(record.acquisition_datetime).toLocaleString() : "Acquisition date unavailable"} · {record.status}</p>
              </div>
              <span className="evidence-disclosure">Land-cover and change unvalidated</span>
            </div>
            {record.raster_reconciliation && (
              <p className="monitoring-limitations" role="status">{record.raster_reconciliation.reason} Stored catalog: {record.raster_reconciliation.catalog_metadata.width} × {record.raster_reconciliation.catalog_metadata.height}, {record.raster_reconciliation.catalog_metadata.valid_pixel_count} NDVI valid pixels; current raster: {record.width} × {record.height}, {record.valid_pixel_count} NDVI valid pixels.</p>
            )}
            {record.status === "processed" ? (
              <>
                <div className="sentinel2-metric-grid">
                  {["ndvi", "evi", "ndmi"].map((indexName) => {
                    const stats = record.index_statistics?.[indexName];
                    const assessment = record.vegetation_validation?.[`${domain}:${indexName}`];
                    const protocol = assessment?.protocol;
                    const metrics = assessment?.recorded_status ? null : assessment?.metrics;
                    return (
                      <div className="sentinel2-index-card" key={indexName}>
                        <strong>{indexName.toUpperCase()}</strong>
                        <span>{stats ? `mean ${stats.mean.toFixed(3)}` : "Unavailable"}</span>
                        <small>{stats ? `${stats.minimum.toFixed(3)} to ${stats.maximum.toFixed(3)}` : "No valid pixels"}</small>
                        <small>Index validation: {assessment?.status || "NOT_VALIDATED"}</small>
                        <small>{assessment?.reason || "No independent reference assessment has been recorded."}</small>
                        {protocol && (
                          <>
                            <small>Index reference: {protocol.reference_dataset} · {protocol.reference_provider} · {protocol.reference_acquisition_datetime} · native {protocol.reference_resolution_m} m</small>
                            <small>Land-cover reference: {protocol.landcover_dataset} · {protocol.landcover_provider} · {protocol.landcover_acquisition_datetime} · native {protocol.landcover_resolution_m} m</small>
                            <small>Sources: {protocol.reference_source} ({protocol.reference_license}) · {protocol.landcover_source} ({protocol.landcover_license})</small>
                            <small>Declared review: {protocol.reviewer} · {protocol.review_date}</small>
                            <small>Method: {protocol.methodology}</small>
                            <small>Reference time offsets: index {(Math.abs(Date.parse(protocol.reference_acquisition_datetime) - Date.parse(record.acquisition_datetime)) / 86400000).toFixed(2)} days · land cover {(Math.abs(Date.parse(protocol.landcover_acquisition_datetime) - Date.parse(record.acquisition_datetime)) / 86400000).toFixed(2)} days</small>
                          </>
                        )}
                        {metrics && (
                          <>
                            <small>Target common pixels: {metrics.common_target_pixels} · coverage of candidate valid pixels: {(metrics.target_coverage_fraction * 100).toFixed(2)}% · spatial blocks: {metrics.target_spatial_blocks}</small>
                            <small>CRS: {metrics.crs} · bounds: {metrics.bounds.join(", ")}</small>
                            {metrics.rmse != null && <small>RMSE {metrics.rmse.toFixed(4)} · MAE {metrics.mae.toFixed(4)} · bias {metrics.bias.toFixed(4)}</small>}
                            <small>Reference class counts and index means: {Object.entries(metrics.classes).map(([name, value]) => `${name}: ${value.count}${value.candidate_mean == null ? "" : ` (mean ${value.candidate_mean.toFixed(3)})`}`).join(" · ")}</small>
                          </>
                        )}
                        {assessment?.limitations?.map((limitation) => <small key={limitation}>{limitation}</small>)}
                      </div>
                    );
                  })}
                </div>
                <div className="sentinel2-preview-grid">
                  {["ndvi", "evi", "ndmi"].map((indexName) => (
                    <Sentinel2Preview key={`${indexName}-${sentinel2Refresh}`} record={record} indexName={indexName} refreshVersion={sentinel2Refresh} />
                  ))}
                </div>
                <p className="panel-subtitle">
                  {record.cloud_cover_percent == null ? "Cloud cover unavailable" : `${record.cloud_cover_percent.toFixed(1)}% cloud cover`} ·
                  {" "}{record.valid_pixel_percent == null ? "Centerline coverage unavailable" : `${record.valid_pixel_percent.toFixed(2)}% valid centerline pixels`} ·
                  {" "}{record.raster_pixel_percent == null ? "Raster coverage unavailable" : `${record.raster_pixel_percent.toFixed(3)}% of raster pixels valid`} · {record.crs || "CRS unavailable"} · {record.resolution_m == null ? "Resolution unavailable" : `${record.resolution_m} m`}
                </p>
              </>
            ) : (
              <p>Real observation unavailable — {record.error || "processing did not produce usable pixels"}.</p>
            )}
            <p className="monitoring-limitations">Indices are not crop-yield, crop-health, forest-loss, or deforestation measurements. Independent validation and compatible historical observations are required for interpretation.</p>
          </article>
        ))}
      </div>
      <div className="panel workspace-panel">
        <div className="panel-header">
          <div>
            <h2>Available satellite observations</h2>
            <p className="panel-subtitle">These records can support future domain-specific analysis after suitable optical data and validated methods are added.</p>
          </div>
        </div>
        <h3 className="monitoring-source-heading">NISAR L2 UR GCOV</h3>
        <AcquisitionEvidence catalog={catalog} status={status} error={error} riverSelection={riverSelection} />
        <h3 className="monitoring-source-heading">Sentinel-1 RTC</h3>
        <SentinelObservationEvidence catalog={catalog} status={status} error={error} riverSelection={riverSelection} />
      </div>
      <div className="monitoring-limitations">
        <strong>Current limitation</strong>
        <span>Available NISAR GCOV and Sentinel-1 records are SAR observations for exploratory water and surface-change workflows. They do not establish crop type, crop condition, forest cover, deforestation, or agricultural statistics. Acquisition dates, source metadata, and coverage must be reviewed before any future vegetation comparison.</span>
      </div>
    </section>
  );
}

function ChangeMap({ region, layer, onSelectChange, rivers, riverSelection, riverLayers, selectedObservation, selectedFootprint, selectedAnalysisLayer, selectedOpticalLayer, selectedNetworkFeature }) {
  const activeRivers = riverSelection === "both"
    ? rivers
    : rivers.filter((river) => river.id === riverSelection);

  return (
    <MapContainer center={region.center} zoom={region.zoom} scrollWheelZoom className="leaflet-map">
      <MapViewport
        region={region}
        rivers={rivers}
        riverSelection={riverSelection}
        selectedFootprint={selectedFootprint}
        selectedAnalysisLayer={selectedAnalysisLayer}
        selectedOpticalLayer={selectedOpticalLayer}
        selectedNetworkFeature={selectedNetworkFeature}
      />
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {selectedOpticalLayer && <OpticalRasterOverlay layer={selectedOpticalLayer} />}
      {selectedNetworkFeature && riverLayers.centerline && (
        <GeoJSON key={`nwic-${selectedNetworkFeature.source_object_id}`} data={selectedNetworkFeature.geometry} style={{ color: "#7043a3", weight: 4 }} />
      )}
      {selectedFootprint && (
        <GeoJSON
          data={{ type: "Feature", properties: {}, geometry: selectedFootprint }}
          key={`satellite-footprint-${JSON.stringify(selectedFootprint).slice(0, 100)}`}
          style={{ color: "#7b4da1", weight: 2, fillColor: "#b491ca", fillOpacity: 0.12, dashArray: "5 4" }}
        />
      )}
      {selectedAnalysisLayer?.geojson && (
        <GeoJSON
          data={selectedAnalysisLayer.geojson}
          key={`analysis-water-mask-${selectedAnalysisLayer.analysisId}`}
          style={{
            color: selectedAnalysisLayer.source_type === "NISAR GCOV" ? "#7043a3" : "#0c7180",
            weight: 1.5,
            fillColor: selectedAnalysisLayer.source_type === "NISAR GCOV" ? "#a783c8" : "#36b5b4",
            fillOpacity: 0.42,
          }}
        />
      )}
      {activeRivers.flatMap((river) => [
        riverLayers.centerline && renderRiverSegments(river, "centerline", river.id === "kaveri" ? "#1f7fc2" : "#eb8a2f", true, 4),
        riverLayers.leftBank && renderRiverSegments(river, "left_bank_boundary", "#7b91a6", Boolean(river.left_bank_boundary), 2),
        riverLayers.rightBank && renderRiverSegments(river, "right_bank_boundary", "#9d7a58", Boolean(river.right_bank_boundary), 2),
      ])}
    </MapContainer>
  );
}

function App() {
  const [activePage, setActivePage] = useState("Overview");
  const [rivers, setRivers] = useState([]);
  const [riverStatus, setRiverStatus] = useState("loading");
  const [riverError, setRiverError] = useState("");
  const [nisarCatalog, setNisarCatalog] = useState(null);
  const [nisarStatus, setNisarStatus] = useState("loading");
  const [nisarError, setNisarError] = useState("");
  const [nisarRetry, setNisarRetry] = useState(0);
  const [riverSearch, setRiverSearch] = useState("");
  const [selectedNetworkFeature, setSelectedNetworkFeature] = useState(null);
  const cancelNetworkSelection = useRef(null);
  const [selectedObservation, setSelectedObservation] = useState(null);
  const [selectedAnalysisLayer, setSelectedAnalysisLayer] = useState(null);
  const [selectedOpticalLayer, setSelectedOpticalLayer] = useState(null);
  const [layer, setLayer] = useState("Candidate change");
  const [riverSelection, setRiverSelection] = useState("both");
  const [riverLayers, setRiverLayers] = useState({ centerline: true, leftBank: false, rightBank: false });
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [selectedChange, setSelectedChange] = useState(null);
  const [notice, setNotice] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  const exportLock = useRef(false);
  const [landReportContext, setLandReportContext] = useState(null);
  const catalogRegion = null;
  const region = buildRealMapRegion(rivers, riverSelection);
  const mapRegion = region;
  const selectedRiver = riverSelection === "both" ? null : rivers.find((item) => item.id === riverSelection) ?? null;
  const normalizedRiverSearch = riverSearch.trim().normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const matchingRivers = rivers.filter((river) => (
    [river.name, river.display_name, river.id].some((value) => (
      value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().includes(normalizedRiverSearch)
    ))
  ));
  const selectableRivers = rivers.filter((river) => (
    matchingRivers.includes(river) || river.id === riverSelection
  ));
  const riverInfo = selectedRiver ?? (rivers.length ? rivers[0] : null);
  const riverInfoItems = selectedRiver ? [selectedRiver] : rivers;
  const visibleRivers = riverSelection === "both"
    ? rivers
    : rivers.filter((river) => river.id === riverSelection);
  const riverInfoStates = [...new Set(riverInfoItems.flatMap((river) => river.states.split(", ")))].join(", ");
  const riverInfoLocations = riverInfoItems.map((river) => river.geographical_location).join("; ");
  const selectedFootprint = selectedObservation?.footprint?.coordinates
    ? selectedObservation.footprint
    : null;
  const isEvidencePage = ["Overview", "Map explorer", "Change analysis", "Impact explorer", "Data & methodology", "About the project", "Agriculture", "Forest monitoring", "AI analysis"].includes(activePage);
  const isChangeAnalysisPage = activePage === "Change analysis";
  const isFunctionalPage = isEvidencePage || isChangeAnalysisPage;

  useEffect(() => {
    const controller = new AbortController();
    setRiverStatus("loading");
    setRiverError("");
    fetchRivers(controller.signal)
      .then((items) => {
        setRivers(items);
        setRiverStatus("loaded");
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          setRiverError(error.message);
          setRiverStatus("error");
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setNisarStatus("loading");
    fetchAutomaticAcquisitions(controller.signal)
      .then((response) => {
        setNisarCatalog(response);
        setNisarError("");
        setNisarStatus("loaded");
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          setNisarError(error.message);
          setNisarStatus("error");
        }
      });
    return () => controller.abort();
  }, [nisarRetry]);

  const selectPage = (page) => {
    setActivePage(page);
    setExportError("");
    if (page === "AI analysis") {
      setNotice("");
      document.getElementById("ai-analysis")?.scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      setNotice("");
    }
  };

  const selectRiverId = (nextRiverSelection) => {
    cancelNetworkSelection.current?.();
    setSelectedNetworkFeature(null);
    setRiverSelection(nextRiverSelection);
    setSelectedObservation(null);
    setSelectedAnalysisLayer(null);
    setSelectedOpticalLayer((current) => (
      current && nextRiverSelection !== "both" && current.riverId !== nextRiverSelection
        ? null
        : current
    ));
  };

  const selectRiver = (event) => selectRiverId(event.target.value);

  const selectNetworkFeature = (feature) => {
    setSelectedNetworkFeature(feature);
    if (feature) {
      setSelectedObservation(null);
      setSelectedAnalysisLayer(null);
      setSelectedOpticalLayer(null);
      if (feature.geometry.pilot_match) {
        setRiverSearch("");
        setRiverSelection(feature.geometry.pilot_match.river_id);
      }
    }
  };

  const exportReport = async () => {
    if (exportLock.current) return;
    exportLock.current = true;
    setExporting(true);
    setExportError("");
    setNotice("");
    const isLand = activePage === "Agriculture" || activePage === "Forest monitoring";
    const selectedNisar = selectedAnalysisLayer?.analysisId?.startsWith("nisar-")
      ? selectedAnalysisLayer.analysisId.slice(6) : null;
    const context = {
      workspace: activePage,
      river_id: riverSelection,
      selected_product_id: isLand ? null : selectedOpticalLayer?.productId ?? selectedNisar ?? selectedObservation?.id ?? null,
      selected_analysis_id: isLand ? null : selectedAnalysisLayer?.analysisId ?? null,
      selected_optical_item_id: isLand ? null : selectedOpticalLayer?.itemId ?? null,
      selected_network_id: isLand ? null : selectedNetworkFeature?.source_object_id ?? null,
      map_layer: isLand ? "centerline" : selectedOpticalLayer ? "Sentinel-2 NDWI candidate"
        : selectedAnalysisLayer ? "candidate mask"
          : selectedFootprint ? "satellite footprint" : "centerline",
      vegetation_river_id: isLand ? landReportContext?.riverId ?? null : null,
      vegetation_item_id: isLand ? landReportContext?.itemId ?? null : null,
      index_name: isLand ? landReportContext?.indexName ?? null : null,
    };
    try {
      const filename = await downloadWorkspaceReport(context);
      setNotice(`Report downloaded: ${filename}. Interpretation uses deterministic rules, not an AI model.`);
    } catch (error) {
      setExportError(error.message);
    } finally {
      exportLock.current = false;
      setExporting(false);
    }
  };

  const selectSatelliteObservation = (observation) => {
    if (observation) {
      cancelNetworkSelection.current?.();
      setSelectedNetworkFeature(null);
    }
    setSelectedObservation(observation);
    if (observation) {
      setSelectedAnalysisLayer(null);
      if (rivers.some((river) => river.id === observation.river_id)) {
        setRiverSelection(observation.river_id);
        setSelectedOpticalLayer((current) => (
          current && current.riverId !== observation.river_id ? null : current
        ));
      }
    }
  };

  const selectAnalysisGeometry = (analysisLayer) => {
    cancelNetworkSelection.current?.();
    setSelectedNetworkFeature(null);
    setSelectedObservation(null);
    setSelectedAnalysisLayer(analysisLayer);
    if (rivers.some((river) => river.id === analysisLayer.river_id)) {
      setRiverSelection(analysisLayer.river_id);
      setSelectedOpticalLayer((current) => (
        current && current.riverId !== analysisLayer.river_id ? null : current
      ));
    }
  };

  const toggleOpticalLayer = (opticalLayer) => {
    if (opticalLayer) {
      cancelNetworkSelection.current?.();
      setSelectedNetworkFeature(null);
    }
    setSelectedOpticalLayer((current) => (
      opticalLayer &&
      current?.productId === opticalLayer.productId &&
      current?.itemId === opticalLayer.itemId
        ? null
        : opticalLayer
    ));
  };

  const toggleRiverLayer = (layerName) => {
    setRiverLayers((current) => {
      const next = {
        ...current,
        [layerName]: !current[layerName],
      };
      if (layerName === "leftBank" && next.leftBank) {
        next.rightBank = false;
      }
      if (layerName === "rightBank" && next.rightBank) {
        next.leftBank = false;
      }
      return next;
    });
  };

  return (
    <div className="app-shell">
      <Sidebar activePage={activePage} onNavigate={selectPage} open={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />

      <main className="main-area">
        <header className="topbar">
          <div className="topbar-left">
            <button aria-label="Open navigation" className="icon-button mobile-menu" onClick={() => setMobileNavOpen(true)} type="button"><Menu size={20} /></button>
            <div className="breadcrumb">Workspace <span>/</span> <strong>{activePage}</strong></div>
          </div>
          <div className="topbar-right">
            <div className={`status-pill ${nisarStatus === "loaded" ? "status-pill-connected" : nisarStatus === "error" ? "status-pill-error" : ""}`}><span className="status-dot" /> Satellite API {nisarStatus === "loaded" ? "CONNECTED · REAL DATA" : nisarStatus === "error" ? "UNAVAILABLE" : "CONNECTING"}</div>
            <button className="profile-button" title="Project workspace" type="button">SI</button>
          </div>
        </header>

        <div className="page-content">
          <div className="demo-banner" role="status">
            <div className="demo-banner-icon"><Radio size={16} /></div>
            <div><strong>Real data only</strong><span>Overview values come from persisted satellite acquisition records, processing outputs, and registered river geometry. When a real observation is unavailable, no substitute measurement is shown.</span></div>
            <span className="demo-banner-tag">REAL DATA</span>
          </div>

          {nisarStatus === "error" && (
            <div className="api-error-banner" role="alert">
              <CircleHelp size={16} />
            <div><strong>Satellite acquisition catalog unavailable</strong><span>{nisarError} {NO_REAL_MEASUREMENT}</span></div>
            <button onClick={() => { setNisarStatus("loading"); setNisarError(""); setNisarCatalog(null); setNisarRetry((retry) => retry + 1); }} type="button">Retry connection</button>
            </div>
          )}

          {notice && <div className="preview-notice"><CircleHelp size={16} />{notice}<button aria-label="Dismiss notice" onClick={() => setNotice("")} type="button"><X size={15} /></button></div>}
          {exportError && <div className="api-error-banner" role="alert">Report export failed: {exportError}</div>}

          <section className="page-heading">
            <div>
              <div className="eyebrow"><span className="eyebrow-line" /> EARTH OBSERVATION · INDIA</div>
              <h1>{activePage === "Overview" ? "Surface change overview" : activePage}</h1>
              <p className="heading-subtitle">Real acquisition records and implemented processing information, with scientific limitations shown explicitly.</p>
            </div>
            <div className="heading-actions">
              <label className="river-select-wrap">
                <FileSearch size={15} />
                <input
                  aria-label="Search registered rivers"
                  disabled={riverStatus !== "loaded"}
                  onChange={(event) => setRiverSearch(event.target.value)}
                  placeholder="Search registered rivers"
                  type="search"
                  value={riverSearch}
                />
              </label>
              <label className="river-select-wrap">
                <Waves size={15} />
                <select aria-label="Select river" disabled={riverStatus !== "loaded"} onChange={selectRiver} value={riverSelection}>
                  <option value="both">{rivers.length === 2 ? "Both Rivers" : "All registered rivers"}</option>
                  {selectableRivers.map((river) => <option key={river.id} value={river.id}>{river.display_name}</option>)}
                </select>
                <ChevronDown size={14} />
              </label>
              {riverStatus === "loaded" && riverSearch.trim() && matchingRivers.length === 0 && (
                <span role="status">No registered rivers match this search.</span>
              )}
              <button className="export-button" onClick={exportReport} disabled={exporting || (["Agriculture", "Forest monitoring"].includes(activePage) && (landReportContext?.domain !== (activePage === "Agriculture" ? "agriculture" : "forest") || landReportContext?.riverSelection !== riverSelection || landReportContext?.status === "loading"))} type="button">
                <Download size={15} /> {exporting ? "Generating report..." : "Export"}
              </button>
            </div>
          </section>

          {isChangeAnalysisPage && <ChangeAnalysis catalog={nisarCatalog} status={nisarStatus} error={nisarError} riverSelection={riverSelection} />}
          {isEvidencePage ? (
            <>
              {(activePage === "Overview" || activePage === "Map explorer") && (
                <RealOverview
                  catalog={nisarCatalog}
                  status={nisarStatus}
                  error={nisarError}
                  riverSelection={riverSelection}
                  rivers={rivers}
                  riverLayers={riverLayers}
                  riverStatus={riverStatus}
                  riverError={riverError}
                  selectedObservation={selectedObservation}
                  selectedFootprint={selectedFootprint}
                  selectedAnalysisLayer={selectedAnalysisLayer}
                  selectedOpticalLayer={selectedOpticalLayer}
                  selectedNetworkFeature={selectedNetworkFeature}
                  onToggleRiverLayer={toggleRiverLayer}
                  onSelectAnalysisGeometry={selectAnalysisGeometry}
                  onToggleOpticalLayer={toggleOpticalLayer}
                  onSelectNetworkFeature={selectNetworkFeature}
                  cancelNetworkSelection={cancelNetworkSelection}
                  mapFocused={activePage === "Map explorer"}
                />
              )}
              {activePage === "Impact explorer" && <ImpactExplorer catalog={nisarCatalog} status={nisarStatus} error={nisarError} riverSelection={riverSelection} />}
              {activePage === "Agriculture" && <LandMonitoringSection title="Agriculture monitoring" eyebrow="AGRICULTURE · SATELLITE EVIDENCE" description="Review available satellite observations around registered river corridors without inventing crop or vegetation measurements." catalog={nisarCatalog} status={nisarStatus} error={nisarError} riverSelection={riverSelection} domain="agriculture" onReportContext={setLandReportContext} />}
              {activePage === "Forest monitoring" && <LandMonitoringSection title="Forest monitoring" eyebrow="FORESTS · SATELLITE EVIDENCE" description="Review available satellite observations and understand which forest and vegetation analyses are not yet supported." catalog={nisarCatalog} status={nisarStatus} error={nisarError} riverSelection={riverSelection} domain="forest" onReportContext={setLandReportContext} />}
              {activePage === "Data & methodology" && <MethodologySection />}
              {activePage === "About the project" && <AboutSection />}
              {activePage === "Change analysis" && (
                <section className="satellite-section" aria-label="Local satellite analysis">
                  <AnalysisWorkspace onSelectAnalysisGeometry={selectAnalysisGeometry} riverSelection={riverSelection} selectedObservation={selectedObservation} />
                </section>
              )}
              {activePage === "AI analysis" && (
                <section className="satellite-section" aria-label="Data-grounded river analysis">
                  <div className="ai-analysis-anchor" id="ai-analysis">
                    <AIAnalysisPanel onSelectRiver={selectRiverId} riverSelection={riverSelection} selectedObservation={selectedObservation} />
                  </div>
                </section>
              )}
              {(activePage === "Overview" || activePage === "Map explorer") && (
                <>
                  <section className="satellite-section" aria-label="Data-grounded river analysis">
                    <div className="ai-analysis-anchor" id="ai-analysis">
                      <AIAnalysisPanel onSelectRiver={selectRiverId} riverSelection={riverSelection} selectedObservation={selectedObservation} />
                    </div>
                  </section>
                  <section className="satellite-section" aria-label="Automatic satellite data acquisition">
                    <AutomaticAcquisitionPanel onSelectAnalysisGeometry={selectAnalysisGeometry} onToggleOpticalLayer={toggleOpticalLayer} selectedOpticalLayer={selectedOpticalLayer} />
                  </section>
                  <section className="satellite-section" aria-label="Satellite observation discovery">
                    <SatelliteSearchPanel riverSelection={riverSelection} onSelectObservation={selectSatelliteObservation} />
                  </section>
                  <section className="satellite-section" aria-label="Local satellite analysis">
                    <AnalysisWorkspace onSelectAnalysisGeometry={selectAnalysisGeometry} riverSelection={riverSelection} selectedObservation={selectedObservation} />
                  </section>
                  <section className="satellite-section" aria-label="Independent reference validation">
                    <ValidationWorkspace riverSelection={riverSelection} />
                  </section>
                </>
              )}
            </>
          ) : (LEGACY_DEMONSTRATION_MODE && (
            <>
          <section aria-label="Demonstration summary metrics" className="metrics-grid">
            <MetricCard icon={Crosshair} label="Area in view" value={region.analyzed} note="illustrative coverage" tone="blue" />
            <MetricCard icon={Droplets} label="Candidate change" value={region.changed} note="not a damage estimate" trend="+2.4%" tone="amber" />
            <MetricCard icon={Layers3} label="Candidate regions" value={String(region.sites).padStart(2, "0")} note="simulated clusters" tone="teal" />
            <MetricCard icon={ShieldAlert} label="Evidence status" value="Illustrative" note="not satellite-derived" tone="slate" />
          </section>

          <section className="analysis-grid">
            <article className="panel map-panel">
              <div className="panel-header map-panel-header">
                <div>
                  <div className="panel-title-row"><h2>River map</h2><span className="panel-live-tag"><span /> GEOGRAPHY LAYER</span></div>
                  <p className="panel-subtitle">
                    {catalogRegion ? `${catalogRegion.basin} basin · ${catalogRegion.state}` : region.extent}
                    <span> · </span>
                    {riverSelection === "both" ? "Registered river" : selectedRiver?.name ?? "Selected river"} centerline{riverSelection === "both" ? "s" : ""}
                  </p>
                  <p className="panel-subtitle">A registered centerline does not establish monitoring coverage.</p>
                </div>
                <div className="river-toolbar">
                  <label className="layer-select">
                    <Layers3 size={14} />
                    <select aria-label="Select map layer" onChange={(event) => setLayer(event.target.value)} value={layer}>
                      <option>Candidate change</option>
                      <option>Simulated radar</option>
                    </select>
                    <ChevronDown size={13} />
                  </label>
                  <div className="river-layer-controls">
                    <button aria-pressed={riverLayers.centerline} className={riverLayers.centerline ? "river-layer-button active" : "river-layer-button"} onClick={() => toggleRiverLayer("centerline")} type="button">Centerline</button>
                    <button aria-pressed={riverLayers.leftBank} className={riverLayers.leftBank ? "river-layer-button active" : "river-layer-button"} disabled={riverStatus !== "loaded"} onClick={() => toggleRiverLayer("leftBank")} title="Show the available left-bank boundary, or its explicit unavailable state" type="button">Left bank</button>
                    <button aria-pressed={riverLayers.rightBank} className={riverLayers.rightBank ? "river-layer-button active" : "river-layer-button"} disabled={riverStatus !== "loaded"} onClick={() => toggleRiverLayer("rightBank")} title="Show the available right-bank boundary, or its explicit unavailable state" type="button">Right bank</button>
                  </div>
                </div>
              </div>
              {riverStatus === "loading" && <div className="river-data-status" role="status">Loading river centerlines…</div>}
              {riverStatus === "error" && <div className="river-data-error" role="alert">River geometry could not be loaded: {riverError}</div>}
              <div className="map-frame">
                <ChangeMap region={mapRegion} layer={layer} onSelectChange={setSelectedChange} rivers={rivers} riverSelection={riverSelection} riverLayers={riverLayers} selectedObservation={selectedObservation} selectedFootprint={selectedFootprint} selectedAnalysisLayer={selectedAnalysisLayer} selectedOpticalLayer={selectedOpticalLayer} selectedNetworkFeature={selectedNetworkFeature} />
                <div className="map-sim-label"><span /> {selectedNetworkFeature ? "OSM + CWC/NWIC GEOGRAPHY" : "OSM GEOGRAPHY"} · DEMO OVERLAY</div>
                <div className="map-legend">
                  <div className="legend-title">MAP KEY</div>
                  {selectedNetworkFeature && riverLayers.centerline && <div>NWIC: {selectedNetworkFeature.name || "Unnamed feature"} · registered, monitoring unknown</div>}
                  {riverLayers.centerline && visibleRivers.map((river) => (
                    <div className="legend-item" key={`river-legend-${river.id}`}>
                      <span className={`legend-swatch ${river.id === "kaveri" ? "kaveri-swatch" : "tungabhadra-swatch"}`} />
                      {river.name} · OSM
                    </div>
                  ))}
                  {riverLayers.leftBank && visibleRivers.some((river) => river.left_bank_boundary) && (
                    <div className="legend-item"><span className="legend-swatch outline-swatch" />Left bank</div>
                  )}
                  {riverLayers.leftBank && !visibleRivers.some((river) => river.left_bank_boundary) && (
                    <div className="legend-item legend-item-muted">Left bank boundary data unavailable</div>
                  )}
                  {riverLayers.rightBank && visibleRivers.some((river) => river.right_bank_boundary) && (
                    <div className="legend-item"><span className="legend-swatch outline-swatch" />Right bank</div>
                  )}
                  {riverLayers.rightBank && !visibleRivers.some((river) => river.right_bank_boundary) && (
                    <div className="legend-item legend-item-muted">Right bank boundary data unavailable</div>
                  )}
                  {selectedFootprint && selectedObservation && (
                    <>
                      <div className="legend-separator">LIVE CATALOG FOOTPRINT</div>
                      <div className="legend-item"><span className="legend-swatch footprint-swatch" />{selectedObservation.mission} footprint · metadata only</div>
                    </>
                  )}
                  <div className="legend-separator">SYNTHETIC PREVIEW</div>
                  {layer === "Candidate change"
                    ? <div className="legend-item"><span className="legend-swatch candidate-swatch" />Candidate area (demo)</div>
                    : <div className="legend-item"><span className="legend-swatch radar-swatch" />Radar footprint (demo)</div>}
                  {selectedAnalysisLayer && <>
                    <div className="legend-separator analysis-legend-separator">
                      {selectedAnalysisLayer.source_type === "automatically acquired Sentinel-1 RTC"
                        ? "REAL SENTINEL-1 RTC"
                        : selectedAnalysisLayer.source_type === "NISAR GCOV"
                          ? "REAL NISAR GCOV · L2"
                          : "UPLOADED RASTER"}
                    </div>
                    <div className={`legend-item ${selectedAnalysisLayer.source_type === "NISAR GCOV" ? "nisar-analysis-legend" : ""}`}>
                      <span className="legend-swatch analysis-water-swatch" />Candidate water · unvalidated
                    </div>
                    <div className="legend-item"><span className="legend-swatch analysis-coverage-swatch" />Candidate polygons only · outside not shown</div>
                  </>}
                  {selectedOpticalLayer && <>
                    <div className="legend-separator optical-legend-separator">EXPLORATORY SENTINEL-2 NDWI</div>
                    <div className="legend-item"><span className="legend-swatch optical-candidate-swatch" />Candidate water · exploratory</div>
                    <div className="legend-item"><span className="legend-swatch optical-noncandidate-swatch" />Not classified as candidate</div>
                    <div className="legend-item"><span className="legend-swatch optical-nodata-swatch" />NoData / invalid / unavailable</div>
                    <div className="optical-map-warning">EXPLORATORY SENTINEL-2 NDWI OUTPUT — NOT GROUND TRUTH.</div>
                  </>}
                  <div className="legend-item"><span className="legend-swatch outline-swatch" />Study area (illustrative)</div>
                </div>
                <div className="map-attribution-note">River data: © OpenStreetMap contributors · ODbL 1.0{selectedNetworkFeature ? " · CWC / National Water Data Portal" : ""}</div>
              </div>
              <div className="map-footer">
                <div><span className="footer-label">RIVER DISPLAY</span><strong>{riverSelection === "both" ? "All registered rivers" : riverInfo?.name ?? "No river selected"}</strong></div>
                <div><span className="footer-label">BOUNDARY STATUS</span><strong>{riverInfo ? riverInfo.boundary_data_status.toUpperCase() : "UNAVAILABLE"}</strong></div>
                <button className="text-link" onClick={() => selectPage("Map explorer")} type="button">Open map explorer <ArrowUpRight size={14} /></button>
              </div>
            </article>

            <article className="panel trend-panel">
              <div className="panel-header">
                <div>
                  <div className="panel-title-row"><h2>Signal trend</h2><span className="synthetic-chip">SYNTHETIC</span></div>
                  <p className="panel-subtitle">Illustrative relative signal · not measured</p>
                </div>
                <button aria-label="About this chart" className="icon-button subtle-icon" onClick={() => setNotice("This synthetic line is included only to preview the chart layout; it is not a radar time series.")} type="button"><CircleHelp size={16} /></button>
              </div>
              <div className="chart-wrap"><TrendChart region={region} /></div>
              <div className="trend-summary">
                <div className="trend-summary-mark"><Activity size={15} /></div>
                <div><strong>Illustrative pattern only</strong><span>Real change metrics require compatible, processed observations.</span></div>
              </div>
            </article>
          </section>

          <RiverNetworkExplorer selected={selectedNetworkFeature} cancelSelectionRef={cancelNetworkSelection} onSelect={selectNetworkFeature} />

          <section className="satellite-section" aria-label="Data-grounded river analysis">
            <div className="ai-analysis-anchor" id="ai-analysis">
              <AIAnalysisPanel
                onSelectRiver={selectRiverId}
                riverSelection={riverSelection}
                selectedObservation={selectedObservation}
              />
            </div>
          </section>

          <section className="satellite-section" aria-label="Automatic satellite data acquisition">
            <AutomaticAcquisitionPanel
              onSelectAnalysisGeometry={selectAnalysisGeometry}
              onToggleOpticalLayer={toggleOpticalLayer}
              selectedOpticalLayer={selectedOpticalLayer}
            />
          </section>

          <section className="satellite-section" aria-label="Satellite observation discovery">
            <SatelliteSearchPanel riverSelection={riverSelection} onSelectObservation={selectSatelliteObservation} />
          </section>

          <section className="satellite-section" aria-label="Local satellite analysis">
            <AnalysisWorkspace onSelectAnalysisGeometry={selectAnalysisGeometry} riverSelection={riverSelection} selectedObservation={selectedObservation} />
          </section>

          <section className="satellite-section" aria-label="Independent reference validation">
            <ValidationWorkspace riverSelection={riverSelection} />
          </section>

          <section className="lower-grid">
            <article className="panel candidates-panel">
              <div className="panel-header lower-panel-header">
                <div><h2>Candidate regions</h2><p className="panel-subtitle">Synthetic examples for interaction preview</p></div>
                <button className="text-link" onClick={() => selectPage("Change analysis")} type="button">View analysis <ArrowUpRight size={14} /></button>
              </div>
              <div className="candidate-list">
                {region.changes.slice(0, 3).map((change, index) => (
                  <button
                    aria-pressed={selectedChange === index}
                    className={`candidate-row ${selectedChange === index ? "candidate-row-selected" : ""}`}
                    key={`${region.extent}-${index}`}
                    onClick={() => setSelectedChange(index)}
                    type="button"
                  >
                    <span className={`candidate-index candidate-index-${index + 1}`}>{String(index + 1).padStart(2, "0")}</span>
                    <span className="candidate-main"><strong>Illustrative cluster {String(index + 1).padStart(2, "0")}</strong><small>Demo candidate · not a verified event</small></span>
                    <span className="candidate-area">{change.area}<small>simulated</small></span>
                    <ChevronDown className="candidate-chevron" size={15} />
                  </button>
                ))}
              </div>
            </article>

            <article className="panel source-panel">
              <div className="panel-header lower-panel-header">
                <div><h2>River information</h2><p className="panel-subtitle">Geographical context and data availability</p></div>
                <FileSearch size={17} className="source-header-icon" />
              </div>
              <div className="source-content">
                <div className="source-row">
                  <span className="source-icon source-icon-sim"><Waves size={15} /></span>
                  <div><strong>River name</strong><span>{riverSelection === "both" ? riverInfoItems.map((river) => river.name).join(" + ") : riverInfo?.name ?? "Unavailable"}</span></div>
                  <span className="source-state"><span /> {riverInfoItems.map((river) => river.id).join(" · ") || "N/A"}</span>
                </div>
                <div className="source-row">
                  <span className="source-icon source-icon-method"><Map size={15} /></span>
                  <div><strong>Geographical location</strong><span>{riverInfoLocations || "Information pending"}</span></div>
                  <span className="source-state source-state-muted"><span /> {riverInfoStates || "State data"}</span>
                </div>
                <div className="source-row">
                  <span className="source-icon source-icon-sim"><Satellite size={15} /></span>
                  <div><strong>Available data</strong><span>{riverInfoItems.length ? "Centerline geometry only" : "No river data"}</span></div>
                  <span className="source-state"><span /> {riverInfoItems.some((river) => river.boundary_data_status === "available") ? "BANK DATA" : "BANKS UNAVAILABLE"}</span>
                </div>
                <div className="source-row">
                  <span className="source-icon source-icon-method"><BookOpen size={15} /></span>
                  <div>
                    <strong>Data source · ODbL 1.0</strong>
                    <span className="river-source-links">
                      {riverInfoItems.map((river) => (
                        <a className="river-source-link" href={river.source_url} key={river.id} rel="noreferrer" target="_blank">
                          {river.name} OSM {river.osm_element_type} {river.osm_element_id}
                        </a>
                      ))}
                    </span>
                  </div>
                  <span className="source-state source-state-muted"><span /> {riverInfo?.retrieval_date ?? "OSM"}</span>
                </div>
              </div>
              <div className="source-caveat"><CloudRain size={14} /><span>
                OpenStreetMap centerlines are community-mapped references, not independently surveyed. {riverInfoItems.some((river) => river.upstream_quality_note) ? "The Tungabhadra source relation is tagged fixme. " : ""}
                Left and right riverbank geometries are unavailable.
              </span></div>
            </article>
          </section>
            </>
          ))}

          <footer className="page-footer">
            <span><span className="footer-status-dot" /> REAL SATELLITE EVIDENCE · CANDIDATE OUTPUTS REMAIN UNVALIDATED</span>
            <span>Designed for NASA Space Apps Challenge 2026 <span className="footer-separator">·</span> “Dancing with the SARs”</span>
          </footer>
        </div>
      </main>
    </div>
  );
}

export default App;
