import { useEffect, useRef, useState } from "react";
import { Activity, AlertTriangle, BrainCircuit, RefreshCw, ShieldCheck } from "lucide-react";
import { runRiverAnalysis } from "../services/api.js";

function formatPercent(value) {
  return typeof value === "number" ? `${(value * 100).toFixed(2)}%` : "Unavailable";
}

function formatArea(value) {
  return typeof value === "number" ? `${value.toFixed(4)} km²` : "Unavailable";
}

function formatDate(value) {
  if (!value) {
    return "Date unavailable";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date unavailable"
    : new Intl.DateTimeFormat("en-GB", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: "UTC",
    }).format(date) + " UTC";
}

function formatTimeDifference(seconds) {
  if (typeof seconds !== "number") {
    return "Unavailable";
  }
  const hours = seconds / 3600;
  return `${hours.toFixed(2)} hours`;
}

export default function AIAnalysisPanel({ onSelectRiver, riverSelection, selectedObservation }) {
  const [riverId, setRiverId] = useState(riverSelection === "both" ? "" : riverSelection);
  const [productId, setProductId] = useState("");
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const requestSequence = useRef(0);

  useEffect(() => {
    if (riverSelection !== "both") {
      setRiverId(riverSelection);
      setProductId("");
      setAnalysis(null);
    }
  }, [riverSelection]);

  useEffect(() => {
    if (!riverId) {
      return undefined;
    }
    const requestId = ++requestSequence.current;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    runRiverAnalysis(riverId, null, controller.signal)
      .then(async (catalogResult) => {
        const selectedCatalogProduct = (
          selectedObservation?.river_id === riverId &&
          catalogResult.products.some((product) => product.product_id === selectedObservation.id)
        )
          ? selectedObservation.id
          : null;
        const result = selectedCatalogProduct
          ? await runRiverAnalysis(riverId, selectedCatalogProduct, controller.signal)
          : catalogResult;
        if (requestId === requestSequence.current) {
          setAnalysis(result);
          setProductId(result.selected_product_id ?? "");
        }
      })
      .catch((requestError) => {
        if (requestError.name !== "AbortError" && requestId === requestSequence.current) {
          setAnalysis(null);
          setError(requestError.message);
        }
      })
      .finally(() => {
        if (requestId === requestSequence.current) {
          setLoading(false);
        }
      });
    return () => {
      controller.abort();
      if (requestId === requestSequence.current) {
        requestSequence.current += 1;
      }
    };
  }, [riverId, selectedObservation?.id, selectedObservation?.river_id]);

  const analyzeSelected = async () => {
    if (!riverId) {
      return;
    }
    const requestId = ++requestSequence.current;
    setLoading(true);
    setError("");
    try {
      const result = await runRiverAnalysis(riverId, productId || null);
      if (requestId === requestSequence.current) {
        setAnalysis(result);
      }
    } catch (requestError) {
      if (requestId === requestSequence.current) {
        setAnalysis(null);
        setError(requestError.message);
      }
    } finally {
      if (requestId === requestSequence.current) {
        setLoading(false);
      }
    }
  };

  const metrics = analysis?.candidate_metrics;
  const sensitivity = analysis?.threshold_sensitivity;
  const optical = analysis?.optical_comparison;
  const selectedObservationIsInCatalog = Boolean(
    selectedObservation &&
    selectedObservation.river_id === riverId &&
    analysis?.products.some((product) => product.product_id === selectedObservation.id),
  );
  const analysisMatchesSelection = Boolean(
    analysis && (analysis.selected_product_id ?? "") === productId,
  );
  const selectedProduct = analysisMatchesSelection && analysis?.products.find(
    (product) => product.product_id === analysis.selected_product_id,
  );

  return (
    <article className="panel ai-analysis-panel" aria-labelledby="ai-analysis-title">
      <div className="panel-header ai-analysis-header">
        <div>
          <div className="panel-title-row">
            <h2 id="ai-analysis-title">AI-Powered River Analysis</h2>
            <span className="analysis-mode-chip"><BrainCircuit size={11} /> RULE-BASED</span>
          </div>
          <p className="panel-subtitle">Deterministic summary of persisted satellite records · no external AI service</p>
        </div>
        <div className="ai-analysis-controls">
          <label>
            <span>River</span>
            <select aria-label="Analysis river" value={riverId} onChange={(event) => {
              const nextRiverId = event.target.value;
              setRiverId(nextRiverId);
              if (nextRiverId === "kaveri" || nextRiverId === "tungabhadra") {
                onSelectRiver(nextRiverId);
              }
            }}>
              <option value="">Choose a river</option>
              <option value="kaveri">Kaveri River</option>
              <option value="tungabhadra">Tungabhadra River</option>
            </select>
          </label>
          {analysis?.products.length > 0 && (
            <label>
              <span>Satellite product</span>
              <select aria-label="Analysis satellite product" value={productId} onChange={(event) => setProductId(event.target.value)}>
                {analysis.products.map((product) => (
                  <option key={`${product.satellite}-${product.product_id}`} value={product.product_id}>
                    {product.satellite} · {formatDate(product.acquisition_start)} · {product.processing_status}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button className="button-secondary ai-run-button" disabled={!riverId || loading} onClick={analyzeSelected} type="button">
            <RefreshCw size={13} className={loading ? "spin-icon" : ""} />
            {loading ? "Analyzing…" : "Run analysis"}
          </button>
        </div>
      </div>

      <div className="ai-analysis-content">
        <div className="ai-analysis-warning" role="note">
          <ShieldCheck size={15} />
          <span>
            Rule-based analysis only. Candidate water is not ground truth. Review attestations are not authenticated.
            No accuracy, flood, erosion, deposition, or validated-bank result is produced here.
          </span>
        </div>

        {!riverId && <p className="ai-analysis-empty">Choose Kaveri or Tungabhadra to analyze its real catalog records.</p>}
        {loading && <p className="ai-analysis-state"><Activity size={14} /> Loading persisted acquisition records…</p>}
        {error && <p className="ai-analysis-error" role="alert"><AlertTriangle size={14} /> {error}</p>}
        {selectedObservation && selectedObservation.river_id === riverId && !loading && (
          <p className="ai-analysis-state" role="status">
            {selectedObservationIsInCatalog
              ? `Selected catalog observation ${selectedObservation.id} is present in this river's persisted product catalog.`
              : `Selected ASF catalog observation ${selectedObservation.id} is discovery metadata only and is not in the persisted processed-product catalog. No measurements are inferred from it.`}
          </p>
        )}
        {analysis && !loading && !analysisMatchesSelection && (
          <p className="ai-analysis-state" role="status">
            Product selection changed to {productId}; run analysis to load measurements for that product.
          </p>
        )}

        {analysis && !loading && analysisMatchesSelection && (
          <>
            <div className="ai-analysis-meta">
              <span>{riverId === "kaveri" ? "Kaveri River" : "Tungabhadra River"}</span>
              <span>
                {analysis.coverage.catalog_product_count} catalog product(s) ·
                {" "}{analysis.coverage.usable_candidate_count} usable ·
                {" "}{analysis.coverage.no_data_product_count} no-data ·
                {" "}{analysis.coverage.failed_product_count} failed
              </span>
              <span>Generated {formatDate(analysis.generated_at)}</span>
            </div>

            <div className="ai-metric-grid">
              <div><span>Centerline coverage</span><strong>{typeof analysis.coverage.mapped_centerline_coverage_percent === "number" ? `${analysis.coverage.mapped_centerline_coverage_percent.toFixed(2)}%` : "Unavailable"}</strong></div>
              <div><span>Valid data support</span><strong>{formatPercent(metrics?.valid_data_fraction)}</strong></div>
              <div><span>NoData / unclassified</span><strong>{formatPercent(metrics?.no_data_fraction)}</strong></div>
              <div><span>Candidate area</span><strong>{formatArea(metrics?.candidate_water_area_km2)}</strong></div>
              <div><span>Candidate pixels</span><strong>{metrics?.candidate_water_pixel_count?.toLocaleString() ?? "Unavailable"}</strong></div>
              <div><span>Evidence status</span><strong>{analysis.validation_status?.replaceAll("_", " ") ?? "Unavailable"}</strong></div>
            </div>
            {analysis.validation_explanation && <p className="ai-analysis-state">{analysis.validation_explanation}</p>}

            {selectedProduct && (
              <div className="ai-analysis-details ai-provenance-details" aria-label="Selected observation provenance">
                <div>
                  <strong>Selected observation provenance</strong>
                  <span>{selectedProduct.satellite} · {selectedProduct.product_id} · {selectedProduct.product_type ?? "Product type unavailable"}</span>
                  <small>
                    Acquired {formatDate(selectedProduct.acquisition_start)}
                    {selectedProduct.acquisition_end ? ` — ${formatDate(selectedProduct.acquisition_end)}` : ""}
                    {" · "}{selectedProduct.source_name ?? "Source unavailable"}
                  </small>
                  <small>
                    Polarization {selectedProduct.polarization?.length ? selectedProduct.polarization.join(", ") : "unavailable"}
                    {" · "}CRS {selectedProduct.input_crs ?? "unavailable"}
                    {" · "}pixel size {typeof selectedProduct.pixel_size_m === "number" ? `${selectedProduct.pixel_size_m} m` : "unavailable"}
                    {selectedProduct.source_license ? ` · ${selectedProduct.source_license}` : ""}
                  </small>
                  {selectedProduct.source_record_url && (
                    <a href={selectedProduct.source_record_url} target="_blank" rel="noreferrer">Open catalog source record</a>
                  )}
                  <small>Measurements below are read from this selected river’s persisted acquisition record.</small>
                </div>
              </div>
            )}
            {selectedObservation && selectedObservation.river_id === riverId && !selectedObservationIsInCatalog && (
              <div className="ai-analysis-details ai-provenance-details" aria-label="Selected catalog observation">
                <div>
                  <strong>Selected discovery record</strong>
                  <span>{selectedObservation.id} · {selectedObservation.mission} · {selectedObservation.product_type ?? "Product type unavailable"}</span>
                  <small>
                    Acquired {formatDate(selectedObservation.acquisition_start)} ·
                    {" "}{selectedObservation.source} · {selectedObservation.analysis_readiness}
                  </small>
                  <small>Catalog discovery does not mean this product was downloaded or processed.</small>
                </div>
              </div>
            )}

            {metrics && (
              <div className="ai-analysis-details">
                <div>
                  <strong>Selected product</strong>
                  <span>{analysis.selected_product_id} · {metrics.classification_status}</span>
                  <small>
                    {metrics.threshold_db !== null && metrics.threshold_db !== undefined
                      ? `Recorded threshold: ${metrics.threshold_db} dB`
                      : `HH threshold: ${metrics.hh_threshold_db ?? "Unavailable"} dB · HV threshold: ${metrics.hv_threshold_db ?? "Unavailable"} dB`}
                  </small>
                </div>
                <div>
                  <strong>NISAR threshold sensitivity</strong>
                  <span>
                    {sensitivity?.candidate_area_min_km2 !== null && sensitivity?.candidate_area_min_km2 !== undefined
                      ? `${formatArea(sensitivity.candidate_area_min_km2)} — ${formatArea(sensitivity.candidate_area_max_km2)}`
                      : "Unavailable for this product"}
                  </span>
                  {sensitivity?.candidate_area_range_percent !== null && sensitivity?.candidate_area_range_percent !== undefined
                    && <small>{sensitivity.candidate_area_range_percent.toFixed(1)}% recorded area range; not confidence or accuracy</small>}
                </div>
                <div>
                  <strong>Polarization comparison</strong>
                  <span>
                    {analysis.polarization_comparison.length
                      ? analysis.polarization_comparison.map((item) => {
                        const areaM2 = item.candidate_area_m2 ?? item.candidate_water_area_m2;
                        return `${item.classification ?? item.polarization ?? "diagnostic"}: ${formatArea(typeof areaM2 === "number" ? areaM2 / 1_000_000 : null)}`;
                      }).join(" · ")
                      : "Unavailable for this product"}
                  </span>
                  <small>Recorded diagnostics only; not an independent comparison.</small>
                </div>
                <div>
                  <strong>Sentinel-2 comparison</strong>
                  <span>{optical?.available ? `${optical.source_product_id} · ${formatArea(optical.candidate_water_area_km2)} candidate` : "No linked optical candidate"}</span>
                  {optical?.available && (
                    <small>{formatDate(optical.acquisition_start)} · Δ {formatTimeDifference(optical.time_difference_seconds)} · common support {formatArea(optical.common_valid_area_km2)}</small>
                  )}
                  {optical?.available && <small className="ai-inline-warning">{optical.warning}</small>}
                </div>
              </div>
            )}

            <div className="ai-analysis-block">
              <strong>Findings</strong>
              <ul>{analysis.findings.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
            <div className="ai-analysis-block">
              <strong>Temporal comparison</strong>
              <p>{analysis.temporal_comparison.explanation}</p>
            </div>
            <div className="ai-analysis-block">
              <strong>Warnings and limitations</strong>
              <ul>{[...analysis.warnings, ...analysis.limitations].map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
            <div className="ai-analysis-block">
              <strong>Safe next steps</strong>
              <ul>{analysis.recommended_next_steps.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          </>
        )}
      </div>
    </article>
  );
}
