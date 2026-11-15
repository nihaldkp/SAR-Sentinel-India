import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import {
  GeoJSON,
  ImageOverlay,
  MapContainer,
  Polyline,
  ScaleControl,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import {
  ArrowDown,
  ArrowUp,
  Crosshair,
  Download,
  Expand,
  FileUp,
  Layers3,
  MapPin,
  Ruler,
  Trash2,
  X,
} from "lucide-react";
import { API_BASE_URL } from "../services/api.js";

const INITIAL_VIEW = { center: [15.7, 75.7], zoom: 6 };

function apiUrl(path) {
  return `${API_BASE_URL}${path}`;
}

async function responseJson(response) {
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`GIS service returned an invalid response (${response.status}).`);
  }
  if (!response.ok) {
    throw new Error(payload.detail || `GIS request failed (${response.status}).`);
  }
  return payload;
}

function MapBridge({ mapRef, onMapClick }) {
  const map = useMap();
  useEffect(() => {
    mapRef.current = map;
    const observer = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    observer.observe(map.getContainer());
    return () => {
      observer.disconnect();
      mapRef.current = null;
    };
  }, [map, mapRef]);
  useMapEvents({
    click(event) {
      onMapClick(event.latlng);
    },
  });
  return <ScaleControl position="bottomleft" imperial={false} />;
}

function VectorLayer({ layer, riverSelection, opacity, onFeature, onError }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    fetch(apiUrl(`/api/gis/layers/${encodeURIComponent(layer.layer_id)}/features?river_id=${riverSelection}`), {
      signal: controller.signal,
    })
      .then(responseJson)
      .then(setData)
      .catch((error) => {
        if (error.name !== "AbortError") onError(layer.layer_id, error.message);
      });
    return () => controller.abort();
  }, [layer.layer_id, riverSelection, onError]);
  if (!data) return null;
  const color = layer.category === "Rivers" ? "#247f9f" : layer.category === "Forest monitoring" ? "#3d936e" : "#b47f35";
  return (
    <GeoJSON
      data={data}
      eventHandlers={{
        click(event) {
          const feature = event.layer?.feature;
          if (feature) onFeature(layer, feature);
        },
      }}
      key={layer.layer_id}
      pointToLayer={(_feature, latlng) => L.circleMarker(latlng, {
        radius: 5,
        color,
        fillColor: color,
        fillOpacity: opacity,
        opacity,
        weight: 1.5,
      })}
      style={() => ({
        color,
        fillColor: color,
        fillOpacity: layer.category === "Forest monitoring" ? opacity * 0.16 : opacity * 0.06,
        opacity,
        weight: layer.category === "Rivers" ? 3 : 1.5,
      })}
    />
  );
}

function RasterLayer({ layer, riverSelection, opacity, onError }) {
  const [preview, setPreview] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    let objectUrl;
    setPreview(null);
    fetch(apiUrl(`/api/gis/layers/${encodeURIComponent(layer.layer_id)}/preview.png?river_id=${riverSelection}`), {
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error(`Raster preview failed (${response.status}).`);
        if (!response.headers.get("content-type")?.startsWith("image/png")) {
          throw new Error("Raster preview did not return a PNG.");
        }
        return response.blob();
      })
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setPreview(objectUrl);
      })
      .catch((error) => {
        if (error.name !== "AbortError") onError(layer.layer_id, error.message);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [layer.layer_id, riverSelection, onError]);
  if (!preview || !layer.bounds_wgs84) return null;
  return (
    <ImageOverlay
      alt={layer.name}
      bounds={[
        [(layer.preview_bounds_wgs84 || layer.bounds_wgs84).south, (layer.preview_bounds_wgs84 || layer.bounds_wgs84).west],
        [(layer.preview_bounds_wgs84 || layer.bounds_wgs84).north, (layer.preview_bounds_wgs84 || layer.bounds_wgs84).east],
      ]}
      opacity={opacity}
      url={preview}
    />
  );
}

function MapResizer({ resetKey }) {
  const map = useMap();
  useEffect(() => {
    map.invalidateSize({ pan: false });
  }, [map, resetKey]);
  return null;
}

function BoundsFit({ bounds, fitKey }) {
  const map = useMap();
  useEffect(() => {
    if (bounds) {
      map.fitBounds(
        [[bounds.south, bounds.west], [bounds.north, bounds.east]],
        { padding: [32, 32], maxZoom: 13 },
      );
    }
  }, [bounds, fitKey, map]);
  return null;
}

export default function GISExplorer({ riverSelection, onSelectRiver }) {
  const [catalog, setCatalog] = useState(null);
  const [catalogState, setCatalogState] = useState("loading");
  const [catalogError, setCatalogError] = useState("");
  const [layerFilter, setLayerFilter] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [visibleIds, setVisibleIds] = useState(["river-centerlines"]);
  const [layerOrder, setLayerOrder] = useState([]);
  const [opacity, setOpacity] = useState({});
  const [selectedLayerId, setSelectedLayerId] = useState("river-centerlines");
  const [layerErrors, setLayerErrors] = useState({});
  const [mode, setMode] = useState("inspect");
  const [vertices, setVertices] = useState([]);
  const [drawings, setDrawings] = useState([]);
  const [measurement, setMeasurement] = useState(null);
  const [inspection, setInspection] = useState(null);
  const [inspectionState, setInspectionState] = useState("idle");
  const [inspectionError, setInspectionError] = useState("");
  const [featureInfo, setFeatureInfo] = useState(null);
  const [coordinate, setCoordinate] = useState(null);
  const [notice, setNotice] = useState("");
  const [importBusy, setImportBusy] = useState(false);
  const [zoomBounds, setZoomBounds] = useState(null);
  const [zoomKey, setZoomKey] = useState(0);
  const [resetKey, setResetKey] = useState(0);
  const mapRef = useRef(null);
  const importInput = useRef(null);
  const mapPanelRef = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    setCatalogState("loading");
    setCatalogError("");
    fetch(apiUrl(`/api/gis/layers?river_id=${riverSelection}`), { signal: controller.signal })
      .then(responseJson)
      .then((result) => {
        setCatalog(result);
        setVisibleIds((current) => {
          const validIds = new Set(result.layers.filter((layer) => layer.status === "available").map((layer) => layer.layer_id));
          const retained = current.filter((id) => validIds.has(id));
          return retained.length ? retained : ["river-centerlines"];
        });
        setLayerOrder((current) => {
          const ids = result.layers.map((layer) => layer.layer_id);
          return [...current.filter((id) => ids.includes(id)), ...ids.filter((id) => !current.includes(id))];
        });
        setCatalogState("loaded");
      })
      .catch((error) => {
        if (error.name !== "AbortError") {
          setCatalogError(error.message);
          setCatalogState("error");
        }
      });
    return () => controller.abort();
  }, [riverSelection, reloadKey]);

  const orderedLayers = useMemo(() => {
    const layers = catalog?.layers || [];
    return [...layers].sort((a, b) => layerOrder.indexOf(a.layer_id) - layerOrder.indexOf(b.layer_id));
  }, [catalog, layerOrder]);
  const filteredLayers = orderedLayers.filter((layer) => (
    `${layer.name} ${layer.category} ${layer.source} ${layer.date || ""}`
      .toLowerCase()
      .includes(layerFilter.trim().toLowerCase())
  ));
  const visibleLayers = orderedLayers.filter((layer) => visibleIds.includes(layer.layer_id) && layer.status === "available");
  const selectedLayer = catalog?.layers.find((layer) => layer.layer_id === selectedLayerId);
  const handleLayerError = useCallback((layerId, message) => {
    setLayerErrors((current) => ({ ...current, [layerId]: message }));
  }, []);

  const toggleLayer = (layer) => {
    if (layer.status !== "available") {
      setNotice(layer.message || "This layer has no available local data.");
      return;
    }
    setSelectedLayerId(layer.layer_id);
    setLayerErrors((current) => {
      const { [layer.layer_id]: _removed, ...remaining } = current;
      return remaining;
    });
    setVisibleIds((current) => current.includes(layer.layer_id)
      ? current.filter((id) => id !== layer.layer_id)
      : [...current, layer.layer_id]);
  };

  const moveLayer = (layerId, offset) => {
    setLayerOrder((current) => {
      const currentIndex = current.indexOf(layerId);
      const nextIndex = currentIndex + offset;
      if (currentIndex < 0 || nextIndex < 0 || nextIndex >= current.length) return current;
      const next = [...current];
      [next[currentIndex], next[nextIndex]] = [next[nextIndex], next[currentIndex]];
      return next;
    });
  };

  const zoomToLayer = (layer) => {
    if (!layer?.bounds_wgs84) {
      setNotice("This layer has no usable spatial bounds.");
      return;
    }
    setZoomBounds(layer.bounds_wgs84);
    setZoomKey((value) => value + 1);
  };

  const inspectLocation = async (latlng) => {
    const point = {
      latitude: Number(latlng.lat.toFixed(7)),
      longitude: Number(latlng.lng.toFixed(7)),
    };
    setCoordinate(point);
    setFeatureInfo(null);
    setInspectionError("");
    setInspectionState("loading");
    try {
      const response = await fetch(apiUrl("/api/gis/inspect"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...point,
          river_id: riverSelection,
          layer_ids: visibleLayers.map((layer) => layer.layer_id),
        }),
      });
      setInspection(await responseJson(response));
      setInspectionState("loaded");
    } catch (error) {
      setInspectionError(error.message);
      setInspectionState("error");
    }
  };

  const finishDrawing = async () => {
    let geometry;
    if (mode === "draw-point") {
      if (!vertices.length) return;
      geometry = { type: "Point", coordinates: vertices[0] };
    } else if (mode === "measure-area" || mode === "draw-polygon") {
      if (vertices.length < 3) return;
      const ring = [...vertices];
      if (ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) ring.push(ring[0]);
      geometry = { type: "Polygon", coordinates: [ring] };
    } else {
      if (vertices.length < 2) return;
      geometry = { type: "LineString", coordinates: vertices };
    }
    const feature = {
      type: "Feature",
      id: `drawing-${Date.now()}`,
      properties: { name: `Drawing ${drawings.length + 1}` },
      geometry,
    };
    setDrawings((current) => [...current, feature]);
    setVertices([]);
    setMode("inspect");
    try {
      const response = await fetch(apiUrl("/api/gis/measure"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ geometry }),
      });
      setMeasurement(await responseJson(response));
    } catch (error) {
      setMeasurement({ error: error.message });
    }
  };

  const handleMapClick = (latlng) => {
    if (mode === "inspect") {
      void inspectLocation(latlng);
      return;
    }
    const nextPoint = [Number(latlng.lng.toFixed(7)), Number(latlng.lat.toFixed(7))];
    setCoordinate({ latitude: nextPoint[1], longitude: nextPoint[0] });
    if (mode === "draw-point") {
      setVertices([nextPoint]);
      window.setTimeout(() => {
        const feature = {
          type: "Feature",
          id: `drawing-${Date.now()}`,
          properties: { name: `Drawing ${drawings.length + 1}` },
          geometry: { type: "Point", coordinates: nextPoint },
        };
        setDrawings((current) => [...current, feature]);
        setVertices([]);
        setMode("inspect");
        fetch(apiUrl("/api/gis/measure"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ geometry: feature.geometry }),
        }).then(responseJson).then(setMeasurement).catch((error) => setMeasurement({ error: error.message }));
      }, 0);
      return;
    }
    setVertices((current) => [...current, nextPoint]);
  };

  const resetMap = () => {
    setZoomBounds(null);
    mapRef.current?.setView(INITIAL_VIEW.center, INITIAL_VIEW.zoom);
    setResetKey((value) => value + 1);
  };

  const importGeoJSON = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setImportBusy(true);
    setNotice("");
    try {
      const body = new FormData();
      body.append("file", file);
      const response = await fetch(apiUrl("/api/gis/layers/import"), { method: "POST", body });
      const result = await responseJson(response);
      setNotice(`Imported ${result.layer.name} (${result.layer.feature_count} features).`);
      setReloadKey((value) => value + 1);
      setVisibleIds((current) => [...new Set([...current, result.layer.layer_id])]);
      setSelectedLayerId(result.layer.layer_id);
    } catch (error) {
      setNotice(`GeoJSON import failed: ${error.message}`);
    } finally {
      setImportBusy(false);
      event.target.value = "";
    }
  };

  const removeTemporaryLayer = async (layer) => {
    try {
      const response = await fetch(apiUrl(`/api/gis/layers/${encodeURIComponent(layer.layer_id)}`), { method: "DELETE" });
      await responseJson(response);
      setVisibleIds((current) => current.filter((id) => id !== layer.layer_id));
      setSelectedLayerId("river-centerlines");
      setReloadKey((value) => value + 1);
      setNotice(`Removed temporary layer ${layer.name}.`);
    } catch (error) {
      setNotice(`Could not remove temporary layer: ${error.message}`);
    }
  };

  const downloadUrl = (layer, format = "native") => (
    apiUrl(`/api/gis/layers/${encodeURIComponent(layer.layer_id)}/download?river_id=${riverSelection}&format=${format}`)
  );

  const exportDrawings = () => {
    if (!drawings.length) return;
    const blob = new Blob(
      [JSON.stringify({ type: "FeatureCollection", features: drawings }, null, 2)],
      { type: "application/geo+json" },
    );
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "gis-drawings.geojson";
    link.click();
    URL.revokeObjectURL(url);
  };

  const beginMode = (nextMode) => {
    setVertices([]);
    setMode(nextMode);
    setMeasurement(null);
    setNotice(nextMode === "inspect" ? "" : "Click the map to add drawing vertices.");
  };

  const visibleIdsSet = new Set(visibleIds);
  const modeName = {
    inspect: "Inspect",
    "measure-line": "Measure distance",
    "measure-area": "Measure area",
    "draw-point": "Draw point",
    "draw-line": "Draw line",
    "draw-polygon": "Draw polygon",
  }[mode];

  return (
    <section className="gis-explorer" aria-label="GIS Explorer">
      <div className="gis-toolbar">
        <label className="gis-river-select">
          <span>River corridor</span>
          <select aria-label="GIS river selection" onChange={(event) => onSelectRiver(event.target.value)} value={riverSelection}>
            <option value="both">Both registered rivers</option>
            <option value="kaveri">Kaveri</option>
            <option value="tungabhadra">Tungabhadra</option>
          </select>
        </label>
        <div className="gis-tool-group" role="group" aria-label="GIS map tools">
          <button aria-pressed={mode === "inspect"} className={mode === "inspect" ? "active" : ""} onClick={() => beginMode("inspect")} type="button"><Crosshair size={15} /> Inspect</button>
          <button aria-pressed={mode === "measure-line"} className={mode === "measure-line" ? "active" : ""} onClick={() => beginMode("measure-line")} type="button"><Ruler size={15} /> Measure distance</button>
          <button aria-pressed={mode === "measure-area"} className={mode === "measure-area" ? "active" : ""} onClick={() => beginMode("measure-area")} type="button"><MapPin size={15} /> Measure area</button>
          <select aria-label="Drawing tool" onChange={(event) => { if (event.target.value) beginMode(event.target.value); }} value={["draw-point", "draw-line", "draw-polygon"].includes(mode) ? mode : ""}>
            <option value="">Draw feature…</option>
            <option value="draw-point">Point</option>
            <option value="draw-line">Line</option>
            <option value="draw-polygon">Polygon</option>
          </select>
          {mode !== "inspect" && (
            <button disabled={(mode === "draw-point" && vertices.length < 1) || (["measure-area", "draw-polygon"].includes(mode) && vertices.length < 3) || (!["measure-area", "draw-polygon", "draw-point"].includes(mode) && vertices.length < 2)} onClick={() => void finishDrawing()} type="button">Finish</button>
          )}
          {vertices.length > 0 && <button onClick={() => setVertices((current) => current.slice(0, -1))} type="button">Undo point</button>}
          <button onClick={() => { setDrawings([]); setVertices([]); setMeasurement(null); }} type="button"><Trash2 size={14} /> Clear drawings</button>
          {drawings.length > 0 && <button onClick={exportDrawings} type="button"><Download size={14} /> Export drawings</button>}
        </div>
      </div>

      {notice && <div className="gis-notice" role="status">{notice}<button aria-label="Dismiss GIS message" onClick={() => setNotice("")} type="button"><X size={14} /></button></div>}
      {catalogState === "error" && (
        <div className="gis-error" role="alert">
          <strong>GIS layer catalog unavailable.</strong> {catalogError}
          <button onClick={() => setReloadKey((value) => value + 1)} type="button">Retry</button>
        </div>
      )}

      <div className="gis-layout">
        <aside className="gis-layer-panel" aria-label="GIS layer manager">
          <div className="gis-panel-heading">
            <div><Layers3 size={16} /><strong>Layers</strong></div>
            <button aria-label="Add GeoJSON layer" disabled={importBusy} onClick={() => importInput.current?.click()} type="button"><FileUp size={15} /> {importBusy ? "Importing…" : "Import"}</button>
            <input ref={importInput} accept=".geojson,.json,application/geo+json,application/json" aria-label="Import GeoJSON file" className="gis-file-input" onChange={importGeoJSON} type="file" />
          </div>
          {catalogState === "loading" && <div className="gis-empty" role="status">Loading local GIS layers…</div>}
          {catalogState === "loaded" && (
            <>
            <label className="gis-layer-search">
              <span>Filter layers</span>
              <input aria-label="Filter GIS layers" onChange={(event) => setLayerFilter(event.target.value)} placeholder="Name, type, source, or date" value={layerFilter} />
            </label>
            <div className="gis-layer-list">
              {filteredLayers.map((layer) => {
                const active = visibleIdsSet.has(layer.layer_id);
                const layerOpacity = opacity[layer.layer_id] ?? 0.78;
                return (
                  <article className={`gis-layer-item ${selectedLayerId === layer.layer_id ? "selected" : ""} ${layer.status !== "available" ? "unavailable" : ""}`} key={layer.layer_id}>
                    <div className="gis-layer-main">
                      <input
                        aria-label={`Show ${layer.name}`}
                        checked={active}
                        disabled={layer.status !== "available"}
                        onChange={() => toggleLayer(layer)}
                        type="checkbox"
                      />
                      <button className="gis-layer-name" onClick={() => setSelectedLayerId(layer.layer_id)} type="button">
                        <strong>{layer.name}</strong>
                        <span className={`gis-status gis-status-${layer.status}`}>{layer.status}</span>
                      </button>
                    </div>
                    {layer.status !== "available" && <p className="gis-layer-note">{layer.message}</p>}
                    {layer.status === "available" && (
                      <>
                        <div className="gis-layer-meta">{layer.source}{layer.date ? ` · ${layer.date.slice(0, 10)}` : ""}{layer.crs ? ` · ${layer.crs}` : ""}{layer.evidence_status ? ` · ${layer.evidence_status.replaceAll("_", " ")}` : ""}</div>
                        {active && (
                          <div className="gis-layer-actions">
                            <label>Opacity <input aria-label={`Opacity ${layer.name}`} max="1" min="0.1" onChange={(event) => setOpacity((current) => ({ ...current, [layer.layer_id]: Number(event.target.value) }))} step="0.05" type="range" value={layerOpacity} /></label>
                            <button aria-label={`Move ${layer.name} up`} disabled={layerOrder.indexOf(layer.layer_id) <= 0} onClick={() => moveLayer(layer.layer_id, -1)} type="button"><ArrowUp size={13} /></button>
                            <button aria-label={`Move ${layer.name} down`} disabled={layerOrder.indexOf(layer.layer_id) >= layerOrder.length - 1} onClick={() => moveLayer(layer.layer_id, 1)} type="button"><ArrowDown size={13} /></button>
                            <button aria-label={`Zoom to ${layer.name}`} onClick={() => zoomToLayer(layer)} type="button"><Crosshair size={13} /></button>
                          </div>
                        )}
                        {layerErrors[layer.layer_id] && <div className="gis-layer-load-error" role="alert">{layerErrors[layer.layer_id]}</div>}
                      </>
                    )}
                  </article>
                );
              })}
              {filteredLayers.length === 0 && <div className="gis-empty">No layers match this filter.</div>}
            </div>
            </>
          )}
          {catalog?.limitations?.map((item) => <p className="gis-limit-note" key={item}>{item}</p>)}
        </aside>

        <div className="gis-map-column">
          <div className="gis-map-toolbar">
            <span className={`gis-mode-indicator ${mode !== "inspect" ? "drawing" : ""}`}>{modeName}{mode !== "inspect" && " · click map"}</span>
            <button onClick={resetMap} type="button">Reset view</button>
            <button onClick={() => {
              const element = mapPanelRef.current;
              if (element?.requestFullscreen) void element.requestFullscreen();
            }} type="button"><Expand size={14} /> Fullscreen</button>
          </div>
          <div className="gis-map-panel" ref={mapPanelRef}>
            <MapContainer center={INITIAL_VIEW.center} zoom={INITIAL_VIEW.zoom} scrollWheelZoom className="gis-leaflet-map">
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <MapBridge mapRef={mapRef} onMapClick={handleMapClick} />
              <MapResizer resetKey={resetKey} />
              {zoomBounds && <BoundsFit bounds={zoomBounds} fitKey={zoomKey} />}
              {visibleLayers.map((layer) => (
                layer.layer_type === "vector"
                  ? <VectorLayer key={layer.layer_id} layer={layer} onError={handleLayerError} onFeature={(source, feature) => setFeatureInfo({ layer: source, feature })} opacity={opacity[layer.layer_id] ?? 0.78} riverSelection={riverSelection} />
                  : <RasterLayer key={layer.layer_id} layer={layer} onError={handleLayerError} opacity={opacity[layer.layer_id] ?? 0.78} riverSelection={riverSelection} />
              ))}
              {drawings.map((feature) => (
                <GeoJSON
                  data={{ type: "FeatureCollection", features: [feature] }}
                  key={feature.id}
                  pointToLayer={(_item, latlng) => L.circleMarker(latlng, { radius: 5, color: "#b45142", fillOpacity: 0.8 })}
                  style={{ color: "#b45142", weight: 2, fillColor: "#e7a08e", fillOpacity: 0.2 }}
                />
              ))}
              {vertices.length > 1 && (
                <Polyline
                  positions={vertices.map(([longitude, latitude]) => [latitude, longitude])}
                  pathOptions={{ color: "#b45142", dashArray: "5 5", weight: 2 }}
                />
              )}
            </MapContainer>
            {coordinate && <div className="gis-coordinate-display" aria-live="polite">Lat {coordinate.latitude.toFixed(5)} · Lon {coordinate.longitude.toFixed(5)}</div>}
          </div>
          <div className="gis-legend">
            <strong>Visible layer key</strong>
            {visibleLayers.length === 0 && <span>No project layers visible.</span>}
            {visibleLayers.map((layer) => (
              <span key={layer.layer_id}><i className={`gis-legend-swatch gis-legend-${layer.layer_type === "raster" ? "raster" : layer.category === "Rivers" ? "river" : "vector"}`} />{layer.name}</span>
            ))}
            {visibleLayers.some((layer) => layer.layer_type === "raster") && <span className="gis-legend-scale">Vegetation preview: lower index ← → higher index · transparent pixels are NoData</span>}
          </div>
        </div>

        <aside className="gis-info-panel" aria-label="GIS feature information">
          <div className="gis-info-section">
            <div className="gis-info-heading"><Crosshair size={15} /><strong>Inspect location</strong></div>
            <p>Click the map in Inspect mode to read raster pixels and intersecting feature attributes.</p>
            {inspectionState === "loading" && <div role="status">Inspecting visible layers…</div>}
            {inspectionState === "error" && <div className="gis-error-inline" role="alert">{inspectionError}</div>}
            {inspection && (
              <div className="gis-inspection-results">
                {inspection.layers.map((item) => (
                  <div className="gis-inspection-item" key={item.layer_id}>
                    <strong>{item.name || item.layer_id}</strong>
                    {Object.prototype.hasOwnProperty.call(item, "value") ? (
                      <span>{item.valid ? `Pixel value: ${Number(item.value).toPrecision(5)}` : item.reason || "NoData / unavailable"}</span>
                    ) : item.feature_count ? (
                      item.features.map((feature, index) => <pre key={feature.id ?? index}>{JSON.stringify(feature.properties, null, 2)}</pre>)
                    ) : <span>No intersecting feature.</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="gis-info-section">
            <div className="gis-info-heading"><Layers3 size={15} /><strong>Layer details</strong></div>
            {!selectedLayer && <span className="gis-muted">Select a layer to view its metadata.</span>}
            {selectedLayer && (
              <>
                <h3>{selectedLayer.name}</h3>
                <dl className="gis-metadata">
                  <dt>Status</dt><dd>{selectedLayer.status}{selectedLayer.message ? ` · ${selectedLayer.message}` : ""}</dd>
                  <dt>Evidence</dt><dd>{selectedLayer.evidence_status?.replaceAll("_", " ") || "Not classified"}</dd>
                  <dt>Source</dt><dd>{selectedLayer.source}</dd>
                  <dt>Acquisition / date</dt><dd>{selectedLayer.date || "Not recorded"}</dd>
                  <dt>CRS</dt><dd>{selectedLayer.crs || "Not available"}</dd>
                  <dt>Resolution</dt><dd>{selectedLayer.resolution_m ? `${selectedLayer.resolution_m} m` : "Not applicable / not recorded"}</dd>
                  {selectedLayer.width && <><dt>Raster grid</dt><dd>{selectedLayer.width} × {selectedLayer.height} · {selectedLayer.data_type} · NoData {String(selectedLayer.nodata ?? "unset")}</dd></>}
                  {selectedLayer.valid_pixel_count != null && <><dt>Valid pixels</dt><dd>{selectedLayer.valid_pixel_count.toLocaleString()}</dd></>}
                  {selectedLayer.feature_count != null && <><dt>Features</dt><dd>{selectedLayer.feature_count}</dd></>}
                  <dt>Provenance</dt><dd>{selectedLayer.provenance}</dd>
                </dl>
                {selectedLayer.status === "available" && (
                  <div className="gis-download-actions">
                    <a href={downloadUrl(selectedLayer)}><Download size={13} /> {selectedLayer.layer_type === "raster" ? "Download GeoTIFF" : "Download GeoJSON"}</a>
                    {selectedLayer.layer_type === "vector" && <a href={downloadUrl(selectedLayer, "csv")}><Download size={13} /> Export attributes CSV</a>}
                    {selectedLayer.temporary && <button onClick={() => void removeTemporaryLayer(selectedLayer)} type="button"><Trash2 size={13} /> Remove import</button>}
                  </div>
                )}
              </>
            )}
          </div>
          {featureInfo && (
            <div className="gis-info-section">
              <div className="gis-info-heading"><MapPin size={15} /><strong>Selected feature</strong></div>
              <p>{featureInfo.layer.name}</p>
              <pre>{JSON.stringify(featureInfo.feature.properties || {}, null, 2)}</pre>
            </div>
          )}
          {measurement && (
            <div className="gis-info-section">
              <div className="gis-info-heading"><Ruler size={15} /><strong>Measurement</strong></div>
              {measurement.error ? <div className="gis-error-inline" role="alert">{measurement.error}</div> : (
                <dl className="gis-metadata">
                  <dt>Geometry</dt><dd>{measurement.geometry_type}</dd>
                  <dt>Length</dt><dd>{measurement.length_m >= 1000 ? `${(measurement.length_m / 1000).toFixed(3)} km` : `${measurement.length_m.toFixed(2)} m`}</dd>
                  <dt>Area</dt><dd>{measurement.area_m2 >= 1_000_000 ? `${(measurement.area_m2 / 1_000_000).toFixed(4)} km²` : `${measurement.area_m2.toFixed(2)} m²`}</dd>
                  <dt>Method</dt><dd>{measurement.measurement_crs}</dd>
                </dl>
              )}
            </div>
          )}
          {coordinate && <div className="gis-coord-card"><MapPin size={14} />{coordinate.latitude.toFixed(5)}, {coordinate.longitude.toFixed(5)}</div>}
        </aside>
      </div>
    </section>
  );
}
