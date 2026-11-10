import { useEffect, useState } from "react";
import { AlertCircle, ExternalLink, Search, Satellite } from "lucide-react";
import { searchSatelliteObservations } from "../services/api.js";

const PRODUCT_TYPES = {
  NISAR: ["GCOV", "GSLC", "RSLC", "RIFG", "RUNW", "ROFF", "GUNW", "GOFF", "SME2", "L0B"],
  "SENTINEL-1": ["GRD_HD", "GRD_MD", "GRD_MS", "SLC", "RAW"],
};

function initialStartDate() {
  const date = new Date();
  date.setDate(date.getDate() - 30);
  return date.toISOString().slice(0, 10);
}

function formatDate(value) {
  if (!value) {
    return "Not provided by catalog";
  }
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" })
    .format(new Date(value));
}

export default function SatelliteSearchPanel({ riverSelection, onSelectObservation }) {
  const [riverId, setRiverId] = useState(riverSelection === "tungabhadra" ? "tungabhadra" : "kaveri");
  const [mission, setMission] = useState("NISAR");
  const [productType, setProductType] = useState("GCOV");
  const [startDate, setStartDate] = useState(initialStartDate);
  const [endDate, setEndDate] = useState(new Date().toISOString().slice(0, 10));
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [selectedId, setSelectedId] = useState("");

  useEffect(() => {
    if (riverSelection === "kaveri" || riverSelection === "tungabhadra") {
      setRiverId(riverSelection);
    }
  }, [riverSelection]);

  const selectMission = (event) => {
    const nextMission = event.target.value;
    setMission(nextMission);
    setProductType(PRODUCT_TYPES[nextMission][0]);
  };

  const search = async (event) => {
    event.preventDefault();
    setStatus("loading");
    setError("");
    setResult(null);
    setSelectedId("");
    onSelectObservation(null);
    try {
      const response = await searchSatelliteObservations({
        riverId,
        mission,
        startDate,
        endDate,
        productType,
      });
      setResult(response);
      setStatus("loaded");
    } catch (requestError) {
      setError(requestError.message);
      setStatus("error");
    }
  };

  const selectObservation = (observation) => {
    setSelectedId(observation.id);
    onSelectObservation({ ...observation, river_id: riverId });
  };

  return (
    <article className="panel satellite-search-panel">
      <div className="panel-header">
        <div>
          <div className="panel-title-row"><h2>Satellite catalog discovery</h2><span className="satellite-source-tag"><Satellite size={11} /> LIVE ASF METADATA</span></div>
          <p className="panel-subtitle">Search actual NISAR and Sentinel-1 catalog records. This does not download or process products.</p>
        </div>
      </div>

      <form className="satellite-search-form" onSubmit={search}>
        <label>River
          <select onChange={(event) => setRiverId(event.target.value)} value={riverId}>
            <option value="kaveri">Kaveri</option>
            <option value="tungabhadra">Tungabhadra</option>
          </select>
        </label>
        <label>Mission
          <select onChange={selectMission} value={mission}>
            <option value="NISAR">NISAR</option>
            <option value="SENTINEL-1">Sentinel-1</option>
          </select>
        </label>
        <label>Product
          <select onChange={(event) => setProductType(event.target.value)} value={productType}>
            {PRODUCT_TYPES[mission].map((type) => <option key={type}>{type}</option>)}
          </select>
        </label>
        <label>From
          <input onChange={(event) => setStartDate(event.target.value)} required type="date" value={startDate} />
        </label>
        <label>To
          <input onChange={(event) => setEndDate(event.target.value)} required type="date" value={endDate} />
        </label>
        <button className="satellite-search-button" disabled={status === "loading"} type="submit">
          <Search size={14} /> {status === "loading" ? "Searching…" : "Search ASF"}
        </button>
      </form>

      {status === "error" && <div className="satellite-error" role="alert"><AlertCircle size={15} />{error}</div>}
      {status === "loaded" && (
        <div className="satellite-results">
          <div className="satellite-results-heading">
            <strong>{result.observations.length} catalog result{result.observations.length === 1 ? "" : "s"}</strong>
            <a href={result.source_url} rel="noreferrer" target="_blank">Open ASF query <ExternalLink size={12} /></a>
          </div>
          {result.observations.length === 0
            ? <p className="satellite-empty">No matching products were returned for this river, date range and product type.</p>
            : result.observations.map((observation) => (
              <div
                className={`satellite-observation ${selectedId === observation.id ? "satellite-observation-selected" : ""}`}
                key={observation.id}
              >
                <button
                  aria-pressed={selectedId === observation.id}
                  className="satellite-observation-select"
                  onClick={() => selectObservation(observation)}
                  type="button"
                >
                  <span className="satellite-observation-main">
                    <strong>{observation.id}</strong>
                    <small>{observation.mission} · {observation.sensor ?? "sensor metadata unavailable"} · {observation.product_type ?? productType}</small>
                    <small>{formatDate(observation.acquisition_start)} · Polarization: {observation.polarization ?? "not specified"}</small>
                    <small>{observation.analysis_readiness}</small>
                  </span>
                </button>
                {observation.download_url && (
                  <a
                    className="satellite-product-link"
                    href={observation.download_url}
                    rel="noreferrer"
                    target="_blank"
                  >
                    Product link <ExternalLink size={11} />
                  </a>
                )}
              </div>
            ))}
          <p className="satellite-catalog-note">{result.note}</p>
        </div>
      )}
    </article>
  );
}
