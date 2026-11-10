import { useEffect, useMemo, useRef, useState } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js/lib/core";
import scatter from "plotly.js/lib/scatter";
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
  Compass,
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
  Circle,
  GeoJSON,
  ImageOverlay,
  MapContainer,
  Polygon,
  Polyline,
  Popup,
  TileLayer,
  Tooltip,
  useMap,
} from "react-leaflet";
import { API_BASE_URL, fetchCatalog, fetchObservations, fetchRivers } from "./services/api.js";
import SatelliteSearchPanel from "./components/SatelliteSearchPanel.jsx";
import AnalysisWorkspace from "./components/AnalysisWorkspace.jsx";
import AutomaticAcquisitionPanel from "./components/AutomaticAcquisitionPanel.jsx";
import AIAnalysisPanel from "./components/AIAnalysisPanel.jsx";
import ValidationWorkspace from "./components/ValidationWorkspace.jsx";
import RiverNetworkExplorer from "./components/RiverNetworkExplorer.jsx";

Plotly.register([scatter]);
const Plot = createPlotlyComponent(Plotly);

const regions = {
  "Krishna basin · Karnataka": {
    center: [15.72, 75.72],
    zoom: 7,
    extent: "North Karnataka, India",
    analyzed: "2,480 km²",
    changed: "126 km²",
    changePercent: 5.1,
    sites: 18,
    outline: [
      [16.55, 74.72],
      [16.68, 76.22],
      [15.98, 77.34],
      [14.96, 77.13],
      [14.82, 75.74],
      [15.35, 74.78],
    ],
    changes: [
      { center: [16.12, 75.74], radius: 8500, area: "34 km²", confidence: "Illustrative" },
      { center: [15.66, 76.2], radius: 11000, area: "51 km²", confidence: "Illustrative" },
      { center: [15.18, 75.76], radius: 7000, area: "22 km²", confidence: "Illustrative" },
      { center: [16.24, 76.68], radius: 5900, area: "19 km²", confidence: "Illustrative" },
    ],
  },
  "Godavari basin · Telangana": {
    center: [18.02, 80.2],
    zoom: 7,
    extent: "Northern Telangana, India",
    analyzed: "1,960 km²",
    changed: "94 km²",
    changePercent: 4.8,
    sites: 13,
    outline: [
      [18.84, 79.18],
      [18.9, 80.74],
      [18.18, 81.37],
      [17.32, 80.82],
      [17.34, 79.57],
      [18.02, 79.12],
    ],
    changes: [
      { center: [18.42, 79.96], radius: 9000, area: "36 km²", confidence: "Illustrative" },
      { center: [17.92, 80.48], radius: 10000, area: "41 km²", confidence: "Illustrative" },
      { center: [17.62, 79.87], radius: 6200, area: "17 km²", confidence: "Illustrative" },
    ],
  },
  "Mahanadi basin · Odisha": {
    center: [20.48, 84.12],
    zoom: 7,
    extent: "Western Odisha, India",
    analyzed: "2,130 km²",
    changed: "108 km²",
    changePercent: 5.1,
    sites: 16,
    outline: [
      [21.23, 83.19],
      [21.3, 84.63],
      [20.76, 85.34],
      [19.88, 84.89],
      [19.78, 83.87],
      [20.31, 83.22],
    ],
    changes: [
      { center: [20.94, 84.08], radius: 9000, area: "39 km²", confidence: "Illustrative" },
      { center: [20.38, 84.67], radius: 10500, area: "48 km²", confidence: "Illustrative" },
      { center: [20.04, 83.91], radius: 6800, area: "21 km²", confidence: "Illustrative" },
    ],
  },
};

const DEFAULT_REGION_ID = "krishna-karnataka";
const DEFAULT_REGION_NAME = "Krishna basin · Karnataka";
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

const navigation = [
  { label: "Overview", icon: BarChart3 },
  { label: "Map explorer", icon: Map },
  { label: "Change analysis", icon: Activity },
  { label: "Impact explorer", icon: Sprout },
  { label: "AI analysis", icon: Radio },
];

const secondaryNavigation = [
  { label: "Data & methodology", icon: BookOpen },
  { label: "About the project", icon: CircleHelp },
];

function MapViewport({ region, rivers, riverSelection, selectedFootprint, selectedAnalysisLayer, selectedOpticalLayer, selectedNetworkFeature }) {
  const map = useMap();
  const [regionLatitude, regionLongitude] = region.center;
  const regionZoom = region.zoom;

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

        <div className="sidebar-label">WORKSPACE</div>
        <nav aria-label="Main navigation" className="nav-stack">{navigation.map(renderLink)}</nav>

        <div className="sidebar-label secondary-label">PROJECT</div>
        <nav aria-label="Project navigation" className="nav-stack">{secondaryNavigation.map(renderLink)}</nav>

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

function ChangeMap({ region, layer, onSelectChange, rivers, riverSelection, riverLayers, selectedObservation, selectedFootprint, selectedAnalysisLayer, selectedOpticalLayer, selectedNetworkFeature }) {
  const showChanges = layer === "Candidate change";
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
      <Polygon
        positions={region.outline}
        pathOptions={{ color: "#328f87", weight: 1.5, fillColor: "#6abbb0", fillOpacity: 0.11, dashArray: "6 5" }}
      >
        <Tooltip sticky>Illustrative area of interest · {region.extent}</Tooltip>
      </Polygon>
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
      {showChanges && region.changes.map((change, index) => (
        <Circle
          center={change.center}
          eventHandlers={{ click: () => onSelectChange(index) }}
          key={`${region.extent}-${index}`}
          pathOptions={{ color: "#ba6731", weight: 2, fillColor: "#edaa63", fillOpacity: 0.58 }}
          radius={change.radius}
        >
          <Popup>
            <strong>Illustrative candidate {String(index + 1).padStart(2, "0")}</strong><br />
            Area estimate: {change.area}<br />
            Status: synthetic demo only<br />
            Evidence confidence: not validated
          </Popup>
        </Circle>
      ))}
      {!showChanges && region.changes.map((change, index) => (
        <Circle
          center={change.center}
          key={`${region.extent}-${index}`}
          pathOptions={{ color: "#5483a4", weight: 1, fillColor: "#80aecd", fillOpacity: 0.36 }}
          radius={change.radius * 1.23}
        >
          <Tooltip sticky>Simulated radar footprint · not satellite data</Tooltip>
        </Circle>
      ))}
    </MapContainer>
  );
}

function TrendChart({ region }) {
  const values = useMemo(() => {
    const seed = region.extent.length;
    return [31, 35, 32, 42, 39, 48, 44, 54, 51, 63, 58, 68].map((value, index) => value + ((seed * (index + 2)) % 7) - 3);
  }, [region]);

  return (
    <Plot
      config={{ displayModeBar: false, responsive: true }}
      data={[
        {
          x: ["Jun 02", "Jun 05", "Jun 08", "Jun 11", "Jun 14", "Jun 17", "Jun 20", "Jun 23", "Jun 26", "Jun 29", "Jul 02", "Jul 05"],
          y: values,
          type: "scatter",
          mode: "lines",
          line: { color: "#378f86", width: 2.5, shape: "spline" },
          fill: "tozeroy",
          fillcolor: "rgba(55,143,134,0.09)",
          hovertemplate: "%{x}<br>Relative index: %{y}<extra>Simulated</extra>",
        },
      ]}
      layout={{
        autosize: true,
        height: 205,
        margin: { l: 36, r: 10, t: 8, b: 30 },
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        font: { family: "Inter, sans-serif", size: 10, color: "#86949b" },
        xaxis: { fixedrange: true, showgrid: false, zeroline: false, linecolor: "#e9eeec", tickfont: { size: 9 } },
        yaxis: { fixedrange: true, showgrid: true, gridcolor: "#edf1ef", zeroline: false, tickfont: { size: 9 }, title: { text: "Relative signal", font: { size: 9 } } },
        showlegend: false,
        hoverlabel: { bgcolor: "#173b43", font: { color: "#fff" } },
      }}
      useResizeHandler
      style={{ width: "100%" }}
    />
  );
}

function App() {
  const [activePage, setActivePage] = useState("Overview");
  const [selectedRegionId, setSelectedRegionId] = useState(DEFAULT_REGION_ID);
  const [catalog, setCatalog] = useState([]);
  const [catalogStatus, setCatalogStatus] = useState("loading");
  const [catalogError, setCatalogError] = useState("");
  const [catalogRetry, setCatalogRetry] = useState(0);
  const [observations, setObservations] = useState([]);
  const [observationStatus, setObservationStatus] = useState("loading");
  const [observationError, setObservationError] = useState("");
  const [rivers, setRivers] = useState([]);
  const [riverStatus, setRiverStatus] = useState("loading");
  const [riverError, setRiverError] = useState("");
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
  const catalogRegion = catalog.find((item) => item.id === selectedRegionId);
  const regionName = catalogRegion?.name ?? DEFAULT_REGION_NAME;
  const region = regions[regionName];
  const mapRegion = catalogRegion
    ? { ...region, center: [catalogRegion.center_latitude, catalogRegion.center_longitude] }
    : region;
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

  useEffect(() => {
    const controller = new AbortController();
    fetchCatalog(controller.signal)
      .then(({ regions: apiRegions }) => {
        if (!apiRegions.length) {
          throw new Error("The API region catalog is empty; no dashboard region is available.");
        }
        const unsupportedRegion = apiRegions.find((item) => !regions[item.name]);
        if (unsupportedRegion) {
          throw new Error(`The API region "${unsupportedRegion.name}" has no configured demonstration map.`);
        }
        setCatalog(apiRegions);
        setSelectedRegionId((current) => (
          apiRegions.find((item) => item.id === current)?.id ?? apiRegions[0].id
        ));
        setCatalogError("");
        setCatalogStatus("connected");
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          setCatalogError(error.message);
          setCatalogStatus("error");
        }
      });
    return () => controller.abort();
  }, [catalogRetry]);

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
    if (catalogStatus !== "connected" || !selectedRegionId) {
      return undefined;
    }
    const controller = new AbortController();
    setObservationStatus("loading");
    setObservationError("");
    setObservations([]);
    fetchObservations(selectedRegionId, controller.signal)
      .then((items) => {
        setObservations(items);
        setObservationStatus("loaded");
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          setObservations([]);
          setObservationError(error.message);
          setObservationStatus("error");
        }
      });
    return () => controller.abort();
  }, [catalogStatus, selectedRegionId]);

  const selectPage = (page) => {
    setActivePage(page);
    if (page === "AI analysis") {
      setNotice("");
      document.getElementById("ai-analysis")?.scrollIntoView({ behavior: "smooth", block: "start" });
    } else if (page !== "Overview" && page !== "Map explorer") {
      setNotice(`${page} is a preview section. Live analysis will be added in a later milestone.`);
    } else {
      setNotice("");
    }
  };

  const selectRegion = (event) => {
    setSelectedRegionId(event.target.value);
    setSelectedChange(null);
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
    setRiverLayers((current) => ({
      ...current,
      [layerName]: !current[layerName],
    }));
  };

  const scenarioWindow = observations.length
    ? (() => {
      const dates = observations.map((item) => item.scenario_date).sort();
      return `${new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", timeZone: "UTC" }).format(new Date(dates[0]))} — ${new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }).format(new Date(dates[dates.length - 1]))}`;
    })()
    : observationStatus === "loading" && catalogStatus === "connected"
      ? "Loading scenario dates…"
      : catalogStatus === "error" || observationStatus === "error"
        ? "API catalog unavailable"
        : "No scenario dates available";

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
            <div className={`status-pill ${catalogStatus === "connected" ? "status-pill-connected" : catalogStatus === "error" ? "status-pill-error" : ""}`}><span className="status-dot" /> API {catalogStatus === "connected" ? "CONNECTED · DEMO" : catalogStatus === "error" ? "UNAVAILABLE" : "CONNECTING"}</div>
            <button className="profile-button" title="Project workspace" type="button">SI</button>
          </div>
        </header>

        <div className="page-content">
          <div className="demo-banner" role="status">
            <div className="demo-banner-icon"><Radio size={16} /></div>
            <div><strong>{catalogStatus === "connected" ? "API catalog connected · overview metrics are demonstrations" : "Demonstration mode"}</strong><span>Overview metrics, charts, and scenarios are illustrative; real satellite acquisitions and processing results are shown separately below when available.</span></div>
            <span className="demo-banner-tag">SIMULATED</span>
          </div>

          {(catalogStatus === "error" || observationStatus === "error") && (
            <div className="api-error-banner" role="alert">
              <CircleHelp size={16} />
            <div><strong>{catalogStatus === "error" ? "Backend catalog unavailable" : "Observation catalog unavailable"}</strong><span>{catalogStatus === "error" ? catalogError : observationError} The map remains a frontend-only synthetic preview; its scenarios are not loaded from the API.</span></div>
            {catalogStatus === "error" && <button onClick={() => { setCatalogStatus("loading"); setCatalogError(""); setCatalogRetry((retry) => retry + 1); }} type="button">Retry connection</button>}
            </div>
          )}

          {notice && <div className="preview-notice"><CircleHelp size={16} />{notice}<button aria-label="Dismiss notice" onClick={() => setNotice("")} type="button"><X size={15} /></button></div>}

          <section className="page-heading">
            <div>
              <div className="eyebrow"><span className="eyebrow-line" /> EARTH OBSERVATION · INDIA</div>
              <h1>{activePage === "Overview" || activePage === "Map explorer" ? "Surface change overview" : activePage}</h1>
              <p className="heading-subtitle">A simulated preview of how SAR observations could help surface changes for review.</p>
            </div>
            <div className="heading-actions">
              <label className="region-select-wrap">
                <Compass size={15} />
                <select aria-label="Select demonstration region" disabled={catalogStatus !== "connected"} onChange={selectRegion} value={selectedRegionId}>
                  {catalogStatus === "loading" && <option value={DEFAULT_REGION_ID}>Loading regions…</option>}
                  {catalogStatus === "error" && <option value={DEFAULT_REGION_ID}>API catalog unavailable</option>}
                  {catalog.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
                <ChevronDown size={14} />
              </label>
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
              <button className="export-button" onClick={() => setNotice("Create a candidate analysis below to access its mask, GeoJSON, and PDF report downloads.")} type="button">
                <Download size={15} /> Export
              </button>
            </div>
          </section>

          <section aria-label="Demonstration summary metrics" className="metrics-grid">
            <MetricCard icon={Crosshair} label="Area in view" value={region.analyzed} note="illustrative coverage" tone="blue" />
            <MetricCard icon={Droplets} label="Candidate change" value={region.changed} note="not a damage estimate" trend="+2.4%" tone="amber" />
            <MetricCard icon={Layers3} label="Candidate regions" value={String(region.sites).padStart(2, "0")} note="simulated clusters" tone="teal" />
            <MetricCard icon={ShieldAlert} label="Evidence status" value="Unvalidated" note="demo values only" tone="slate" />
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
                    <button aria-pressed={riverLayers.leftBank} className={riverLayers.leftBank ? "river-layer-button active" : "river-layer-button"} disabled onClick={() => toggleRiverLayer("leftBank")} title="Left-bank boundary data is not available yet" type="button">Left bank</button>
                    <button aria-pressed={riverLayers.rightBank} className={riverLayers.rightBank ? "river-layer-button active" : "river-layer-button"} disabled onClick={() => toggleRiverLayer("rightBank")} title="Right-bank boundary data is not available yet" type="button">Right bank</button>
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
                  {riverLayers.rightBank && visibleRivers.some((river) => river.right_bank_boundary) && (
                    <div className="legend-item"><span className="legend-swatch outline-swatch" />Right bank</div>
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

          <RiverNetworkExplorer selected={selectedNetworkFeature} cancelSelectionRef={cancelNetworkSelection} onSelect={(feature) => {
            setSelectedNetworkFeature(feature);
            if (feature) {
              setSelectedObservation(null);
              setSelectedAnalysisLayer(null);
              setSelectedOpticalLayer(null);
            }
          }} />

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

          <footer className="page-footer">
            <span><span className="footer-status-dot" /> DEMO OVERLAYS · LIVE ACQUISITIONS SHOWN SEPARATELY</span>
            <span>Designed for NASA Space Apps Challenge 2026 <span className="footer-separator">·</span> “Dancing with the SARs”</span>
          </footer>
        </div>
      </main>
    </div>
  );
}

export default App;
