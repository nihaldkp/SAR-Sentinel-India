import { useEffect, useRef, useState } from "react";
import { fetchRiverNetworkGeometry, searchRiverNetwork } from "../services/api.js";

const PAGE_SIZE = 20;

export default function RiverNetworkExplorer({ onSelect, selected, cancelSelectionRef }) {
  const [filters, setFilters] = useState({ q: "", basin: "", sub_basin: "", state: "", district: "" });
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [geometryError, setGeometryError] = useState("");
  const [loadingId, setLoadingId] = useState("");
  const selectionRequest = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const timer = window.setTimeout(() => {
      searchRiverNetwork({ ...filters, limit: PAGE_SIZE, offset }, controller.signal)
        .then(setResult)
        .catch((requestError) => {
          if (requestError.name !== "AbortError") {
            setResult(null);
            setError(requestError.message);
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 300);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [filters, offset]);

  useEffect(() => {
    cancelSelectionRef.current = () => {
      selectionRequest.current?.abort();
      setLoadingId("");
    };
    return () => {
      selectionRequest.current?.abort();
      cancelSelectionRef.current = null;
    };
  }, [cancelSelectionRef]);

  const selectFeature = async (feature) => {
    selectionRequest.current?.abort();
    const controller = new AbortController();
    selectionRequest.current = controller;
    setLoadingId(feature.source_object_id);
    setGeometryError("");
    try {
      const geometry = await fetchRiverNetworkGeometry(feature.source_object_id, controller.signal);
      if (!controller.signal.aborted) onSelect({ ...feature, geometry });
    } catch (requestError) {
      if (requestError.name !== "AbortError") setGeometryError(requestError.message);
    } finally {
      if (!controller.signal.aborted) setLoadingId("");
    }
  };

  return (
    <section className="acquisition-source-note" aria-label="NWIC river network explorer">
      <h3>NWIC river network explorer</h3>
      <p>Source: CWC / <a href="https://nwdp.nwic.gov.in/dataset/river-line" target="_blank" rel="noreferrer">National Water Data Portal River Network</a>. Registration and geometry do not establish satellite monitoring. Endpoint districts are not full district coverage. Monitoring controls remain tied to the pilot river selector, not this selection.</p>
      {Object.entries({ q: "River name or source ID", basin: "Basin", sub_basin: "Sub-basin", state: "State", district: "Start or end district" }).map(([key, label]) => (
        <label key={key} style={{ display: "inline-flex", flexDirection: "column", margin: "4px" }}>
          {label}
          <input value={filters[key]} onChange={(event) => {
            setFilters((current) => ({ ...current, [key]: event.target.value }));
            setOffset(0);
          }} />
        </label>
      ))}
      {loading && <p role="status">Loading river features…</p>}
      {error && <p role="alert">{error}</p>}
      {geometryError && <p role="alert">{geometryError}</p>}
      {!loading && result && (
        <>
          <p>{result.total} matching source features{result.total === 0 ? " · no imported records match" : ""}.</p>
          {result.features.map((feature) => (
            <button key={feature.source_object_id} type="button" disabled={loadingId === feature.source_object_id}
              onClick={() => selectFeature(feature)}>
              {feature.name || "Unnamed feature"} · source ID {feature.source_object_id}
            </button>
          ))}
          <div>
            <button type="button" disabled={offset === 0} onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}>Previous rivers</button>
            <span> Offset {offset} </span>
            <button type="button" disabled={offset + PAGE_SIZE >= result.total} onClick={() => setOffset((value) => value + PAGE_SIZE)}>Next rivers</button>
          </div>
        </>
      )}
      {selected && <p>Selected: {selected.name || "Unnamed feature"} · source ID {selected.source_object_id} · satellite status unknown; no observation linkage verified. <button type="button" onClick={() => { cancelSelectionRef.current?.(); onSelect(null); }}>Clear selected NWIC feature</button></p>}
    </section>
  );
}
