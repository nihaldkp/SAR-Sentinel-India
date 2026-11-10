import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Database, LoaderCircle, ShieldAlert } from "lucide-react";
import {
  API_BASE_URL,
  compareExploratoryMethods,
  evaluateClassificationMethods,
  evaluateWindowedAssessment,
  fetchImportedReferenceData,
  fetchReferenceSources,
  fetchValidationStatus,
  importReviewedReferenceData,
  rejectWindowedAssessment,
  submitRasterValidation,
} from "../services/api.js";

function percentage(value) {
  return typeof value === "number" ? `${(value * 100).toFixed(2)}%` : "Unavailable";
}

export default function ValidationWorkspace({ riverSelection }) {
  const [status, setStatus] = useState(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [statusError, setStatusError] = useState("");
  const [referenceSources, setReferenceSources] = useState([]);
  const [loadingReferenceCatalog, setLoadingReferenceCatalog] = useState(true);
  const [storedReferences, setStoredReferences] = useState([]);
  const [referenceCatalogError, setReferenceCatalogError] = useState("");
  const [referenceImportFile, setReferenceImportFile] = useState(null);
  const [referenceImporting, setReferenceImporting] = useState(false);
  const [referenceImportError, setReferenceImportError] = useState("");
  const [referenceImportSuccess, setReferenceImportSuccess] = useState("");
  const [methodReferenceFile, setMethodReferenceFile] = useState(null);
  const [methodReviewed, setMethodReviewed] = useState(true);
  const [methodCandidateFiles, setMethodCandidateFiles] = useState([null, null]);
  const [methodNames, setMethodNames] = useState(["Method A", "Method B"]);
  const [methodIds, setMethodIds] = useState(["method-a", "method-b"]);
  const [methodParameters, setMethodParameters] = useState(["{}", "{}"]);
  const [methodEvaluation, setMethodEvaluation] = useState(null);
  const [methodEvaluating, setMethodEvaluating] = useState(false);
  const [methodEvaluationError, setMethodEvaluationError] = useState("");
  const [riverId, setRiverId] = useState(
    riverSelection === "tungabhadra" ? "tungabhadra" : "kaveri",
  );
  const [candidateFile, setCandidateFile] = useState(null);
  const [referenceFile, setReferenceFile] = useState(null);
  const [candidateId, setCandidateId] = useState("");
  const [candidateSensor, setCandidateSensor] = useState("");
  const [candidateDate, setCandidateDate] = useState("");
  const [windowedValidation, setWindowedValidation] = useState(false);
  const [candidateProcessingVersion, setCandidateProcessingVersion] = useState("");
  const [referenceId, setReferenceId] = useState("");
  const [provider, setProvider] = useState("");
  const [referenceDate, setReferenceDate] = useState("");
  const [resolution, setResolution] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [reviewDate, setReviewDate] = useState("");
  const [methodology, setMethodology] = useState("");
  const [limitations, setLimitations] = useState("");
  const [independentReviewCompleted, setIndependentReviewCompleted] = useState(false);
  const [minimumCommonPixels, setMinimumCommonPixels] = useState("");
  const [minimumCoverage, setMinimumCoverage] = useState("");
  const [minimumPerClass, setMinimumPerClass] = useState("");
  const [spatialBlockSize, setSpatialBlockSize] = useState("");
  const [minimumBlocks, setMinimumBlocks] = useState("");
  const [report, setReport] = useState(null);
  const [rejectionReason, setRejectionReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (riverSelection === "kaveri" || riverSelection === "tungabhadra") {
      setRiverId(riverSelection);
    }
  }, [riverSelection]);

  useEffect(() => {
    const controller = new AbortController();
    fetchValidationStatus(controller.signal)
      .then(setStatus)
      .catch((requestError) => {
        if (requestError.name !== "AbortError") {
          setStatusError(requestError.message);
        }
      })
      .finally(() => setLoadingStatus(false));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      fetchReferenceSources(controller.signal),
      fetchImportedReferenceData(controller.signal),
    ])
      .then(([sources, references]) => {
        setReferenceSources(sources);
        setStoredReferences(references);
      })
      .catch((requestError) => {
        if (requestError.name !== "AbortError") {
          setReferenceCatalogError(requestError.message);
        }
      })
      .finally(() => setLoadingReferenceCatalog(false));
    return () => controller.abort();
  }, []);

  const submit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    setReport(null);
    try {
      const result = await submitRasterValidation(candidateFile, referenceFile, {
        river_id: riverId,
        candidate_product_id: candidateId.trim(),
        candidate_sensor: candidateSensor.trim(),
        candidate_acquisition_datetime: new Date(candidateDate).toISOString(),
        reference_dataset_id: referenceId.trim(),
        reference_provider: provider.trim(),
        reference_acquisition_datetime: new Date(referenceDate).toISOString(),
        reference_resolution_m: Number(resolution),
        reviewer: reviewer.trim(),
        review_date: reviewDate,
        independent_review_completed: independentReviewCompleted,
        reference_methodology: methodology.trim(),
        limitations: limitations.split(/\r?\n/).map((value) => value.trim()).filter(Boolean),
        minimum_common_pixels: Number(minimumCommonPixels),
        minimum_coverage_fraction: Number(minimumCoverage),
        minimum_pixels_per_class: Number(minimumPerClass),
        spatial_block_size_pixels: Number(spatialBlockSize),
        minimum_blocks_per_class: Number(minimumBlocks),
        ...(windowedValidation ? { candidate_processing_version: candidateProcessingVersion.trim() } : {}),
      }, undefined, windowedValidation);
      setReport(result);
      try {
        setStatus(await fetchValidationStatus());
        setStatusError("");
      } catch (statusRequestError) {
        setStatusError(statusRequestError.message);
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  };

  const evaluateAssessment = async () => {
    setSubmitting(true);
    setError("");
    try {
      setReport(await evaluateWindowedAssessment(report.validation_id));
      try {
        setStatus(await fetchValidationStatus());
        setStatusError("");
      } catch (statusRequestError) {
        setStatusError(statusRequestError.message);
      }
    } catch (requestError) {
      setError(requestError.message);
      try {
        const latest = await fetchValidationStatus();
        setStatus(latest);
        const saved = latest.reports.find((item) => item.validation_id === report.validation_id);
        if (saved) setReport(saved);
      } catch (statusRequestError) {
        setStatusError(statusRequestError.message);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const rejectAssessment = async () => {
    setSubmitting(true);
    setError("");
    try {
      setReport(await rejectWindowedAssessment(report.validation_id, rejectionReason.trim()));
      try {
        setStatus(await fetchValidationStatus());
        setStatusError("");
      } catch (statusRequestError) {
        setStatusError(statusRequestError.message);
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSubmitting(false);
    }
  };

  const importReference = async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    setReferenceImporting(true);
    setReferenceImportError("");
    setReferenceImportSuccess("");
    try {
      const result = await importReviewedReferenceData(referenceImportFile, {
        dataset_id: formData.get("dataset_id"),
        provider: formData.get("provider"),
        source_url: formData.get("source_url"),
        acquisition_datetime: new Date(formData.get("acquisition_datetime")).toISOString(),
        resolution_m: Number(formData.get("resolution_m")),
        crs: formData.get("crs"),
        license: formData.get("license"),
        reviewer: formData.get("reviewer"),
        review_date: formData.get("review_date"),
        review_method: formData.get("review_method"),
        independent_review_completed: formData.get("independent_review_completed") === "on",
        limitations: String(formData.get("limitations"))
          .split(/\r?\n/)
          .map((value) => value.trim())
          .filter(Boolean),
      });
      setReferenceImportSuccess(`Stored reviewed label raster ${result.reference_id}.`);
      setStoredReferences((references) => [
        result,
        ...references.filter((reference) => reference.reference_id !== result.reference_id),
      ]);
      try {
        setStatus(await fetchValidationStatus());
        setStatusError("");
      } catch (statusRequestError) {
        setStatusError(statusRequestError.message);
      }
      form.reset();
      setReferenceImportFile(null);
    } catch (requestError) {
      setReferenceImportError(requestError.message);
    } finally {
      setReferenceImporting(false);
    }
  };

  const evaluateMethods = async (event) => {
    event.preventDefault();
    setMethodEvaluating(true);
    setMethodEvaluationError("");
    setMethodEvaluation(null);
    try {
      const parameters = methodParameters.map((raw, index) => {
        let value;
        try {
          value = JSON.parse(raw);
        } catch {
          throw new Error(`Parameters for ${methodNames[index] || `method ${index + 1}`} must be valid JSON.`);
        }
        if (
          value === null ||
          Array.isArray(value) ||
          typeof value !== "object" ||
          Object.values(value).some((item) => (
            item === null ||
            !["string", "number", "boolean"].includes(typeof item) ||
            (typeof item === "number" && !Number.isFinite(item))
          ))
        ) {
          throw new Error("Method parameters must be a JSON object with scalar values.");
        }
        return value;
      });
      const methods = methodIds.map((methodId, index) => ({
        method_id: methodId.trim(),
        method_name: methodNames[index].trim(),
        parameters: parameters[index],
      }));
      if (!methodReviewed) {
        setMethodEvaluation(await compareExploratoryMethods(methodCandidateFiles, {
          river_id: riverId,
          candidate_product_id: candidateId.trim(),
          candidate_acquisition_datetime: candidateDate ? new Date(candidateDate).toISOString() : null,
          methods,
        }));
        return;
      }
      const metadata = {
        reference_metadata: {
          river_id: riverId,
          candidate_product_id: candidateId.trim(),
          candidate_sensor: candidateSensor.trim(),
          candidate_acquisition_datetime: new Date(candidateDate).toISOString(),
          reference_dataset_id: referenceId.trim(),
          reference_provider: provider.trim(),
          reference_acquisition_datetime: new Date(referenceDate).toISOString(),
          reference_resolution_m: Number(resolution),
          reviewer: reviewer.trim(),
          review_date: reviewDate,
          independent_review_completed: independentReviewCompleted,
          reference_methodology: methodology.trim(),
          limitations: limitations.split(/\r?\n/).map((value) => value.trim()).filter(Boolean),
          minimum_common_pixels: Number(minimumCommonPixels),
          minimum_coverage_fraction: Number(minimumCoverage),
          minimum_pixels_per_class: Number(minimumPerClass),
          spatial_block_size_pixels: Number(spatialBlockSize),
          minimum_blocks_per_class: Number(minimumBlocks),
        },
        methods,
      };
      setMethodEvaluation(await evaluateClassificationMethods(
        methodReferenceFile,
        methodCandidateFiles,
        metadata,
      ));
    } catch (requestError) {
      setMethodEvaluationError(requestError.message);
    } finally {
      setMethodEvaluating(false);
    }
  };

  return (
    <article className="panel validation-panel" aria-labelledby="validation-title">
      <div className="panel-header">
        <div>
          <div className="panel-title-row"><h2 id="validation-title">Independent reference validation</h2><span className="analysis-mode-chip"><ShieldAlert size={11} /> LABEL-DEPENDENT</span></div>
          <p className="panel-subtitle">Confusion metrics are computed only from supplied independent 0/1/255 GeoTIFF labels.</p>
        </div>
      </div>

      <div className="validation-content">
        {statusError
          ? <p className="analysis-unavailable" role="alert">{statusError}</p>
          : status
            ? <p className={`validation-state validation-state-${status.status}`} role="status">{status.message}</p>
            : loadingStatus && <p className="validation-state" role="status">Loading validation status…</p>}
        <p className="validation-caveat">
          The service records provenance but cannot independently verify a provider, reviewer, label quality, or sampling design.
          Do not use Sentinel-2 NDWI as an independent reference for another candidate classification; this warning is not an automated provenance check.
        </p>
        <section className="validation-report-history" aria-label="Public reference-data sources">
          <strong><Database size={13} /> Public reference-data source guide</strong>
          <p>Source listings are metadata only; the app does not download data or convert contextual products into ground truth.</p>
          {referenceCatalogError
            ? <p role="alert">{referenceCatalogError}</p>
            : loadingReferenceCatalog
              ? <span>Loading reference source catalog…</span>
              : referenceSources.length === 0
                ? <span>No reference sources are currently listed.</span>
                : referenceSources.map((source) => (
              <div className="validation-source-item" key={source.source_id}>
                  <strong><a href={source.source_url} rel="noreferrer" target="_blank">{source.name}</a></strong>
                <span>{source.provider} · {source.temporal_coverage} · {source.nominal_resolution_m ? `${source.nominal_resolution_m} m nominal` : "vector geometry; scale not stated"}</span>
                <small>Coverage: {source.geographic_coverage}</small>
                <small>Spatial reference: {source.spatial_reference}</small>
                <small>Format: {source.data_format} {source.access_notes}</small>
                <small>{source.intended_use} {source.limitation} License: {source.license_status}</small>
                <span className="validation-source-links">
                  <a href={source.source_url} rel="noreferrer" target="_blank">Official source</a>
                  <a href={source.access_url} rel="noreferrer" target="_blank">Access / download</a>
                </span>
              </div>
            ))}
        </section>
        <section className="validation-report-history" aria-label="Imported reviewed reference data">
          <strong>Locally imported reviewed label datasets</strong>
          {storedReferences.length === 0
            ? <span>No reviewed label raster has been imported.</span>
            : storedReferences.map((reference) => (
              <a key={reference.reference_id} href={`${API_BASE_URL}${reference.labels_url}`} target="_blank" rel="noreferrer">
                {reference.metadata.dataset_id} · {reference.metadata.provider} · {reference.width} × {reference.height}
              </a>
            ))}
        </section>
        <details className="validation-reference-import">
          <summary>Import an independently reviewed reference GeoTIFF</summary>
          <p>Only import labels already reviewed by a person. The service stores this file locally; its provenance and reviewer attestation are recorded but not authenticated.</p>
          <form className="validation-form" onSubmit={importReference}>
            <label>Dataset ID<input name="dataset_id" required maxLength={256} /></label>
            <label>Provider<input name="provider" required maxLength={256} /></label>
            <label>Source URL<input name="source_url" required type="url" /></label>
            <label>Acquisition time (local)<input name="acquisition_datetime" required type="datetime-local" /></label>
            <label>Resolution (metres)<input name="resolution_m" required min="0.01" step="any" type="number" /></label>
            <label>Raster CRS<input name="crs" required defaultValue="EPSG:32643" maxLength={80} /></label>
            <label>License<input name="license" required maxLength={256} /></label>
            <label>Reviewer<input name="reviewer" required maxLength={256} /></label>
            <label>Review date<input name="review_date" required type="date" /></label>
            <label className="analysis-file-input">Reviewed 0/1/255 GeoTIFF
              <input required accept=".tif,.tiff,image/tiff" type="file" onChange={(event) => setReferenceImportFile(event.target.files?.[0] ?? null)} />
            </label>
            <label className="validation-wide-field">Review method<textarea name="review_method" required maxLength={4000} rows={2} /></label>
            <label className="validation-wide-field">Limitations, one per line<textarea name="limitations" required rows={2} /></label>
            <label className="validation-wide-field validation-checkbox-field">
              <input name="independent_review_completed" required type="checkbox" />
              I confirm these labels were independently reviewed and are not another candidate classification.
            </label>
            <button className="button-secondary analysis-submit" disabled={referenceImporting || !referenceImportFile} type="submit">
              {referenceImporting ? <LoaderCircle size={13} className="analysis-spinner" /> : <Database size={13} />}
              {referenceImporting ? "Checking and storing reviewed labels…" : "Import reviewed labels"}
            </button>
          </form>
          {referenceImportError && <p className="analysis-unavailable" role="alert">{referenceImportError}</p>}
          {referenceImportSuccess && <p className="validation-state" role="status">{referenceImportSuccess}</p>}
        </details>
        <details className="validation-method-evaluation" id="method-comparison">
          <summary>Compare alternative candidate classifications</summary>
          <p>Supply two masks from the same source observation. Exploratory mode accepts pixel-aligned, partially overlapping grids and processes 512-pixel windows without resampling; reviewed mode requires identical grids and at most two million pixels per input. Uploads are limited to 100 MB combined. Results do not select a winner or establish general accuracy.</p>
          <form className="validation-form" onSubmit={evaluateMethods}>
            <label>Comparison mode
              <select value={methodReviewed ? "reviewed" : "exploratory"} onChange={(event) => { setMethodReviewed(event.target.value === "reviewed"); setMethodEvaluation(null); }}>
                <option value="reviewed">With reviewed reference labels</option>
                <option value="exploratory">Exploratory, without reference labels</option>
              </select>
            </label>
            <label>River
              <select value={riverId} onChange={(event) => setRiverId(event.target.value)}>
                <option value="kaveri">Kaveri River</option>
                <option value="tungabhadra">Tungabhadra River</option>
              </select>
            </label>
            <label>Candidate product ID<input required maxLength={512} value={candidateId} onChange={(event) => setCandidateId(event.target.value)} /></label>
            {!methodReviewed && <label>Candidate acquisition (local, if known)<input type="datetime-local" value={candidateDate} onChange={(event) => setCandidateDate(event.target.value)} /></label>}
            {methodReviewed && <>
            <label>Candidate sensor<input required maxLength={80} value={candidateSensor} onChange={(event) => setCandidateSensor(event.target.value)} /></label>
            <label>Candidate acquisition (local)<input required type="datetime-local" value={candidateDate} onChange={(event) => setCandidateDate(event.target.value)} /></label>
            <label>Reference dataset ID<input required maxLength={256} value={referenceId} onChange={(event) => setReferenceId(event.target.value)} /></label>
            <label>Reference provider<input required maxLength={256} value={provider} onChange={(event) => setProvider(event.target.value)} /></label>
            <label>Reference acquisition (local)<input required type="datetime-local" value={referenceDate} onChange={(event) => setReferenceDate(event.target.value)} /></label>
            <label>Reference resolution (m)<input required min="0.01" step="any" type="number" value={resolution} onChange={(event) => setResolution(event.target.value)} /></label>
            <label>Reviewer<input required maxLength={256} value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label>
            <label>Review date<input required type="date" value={reviewDate} onChange={(event) => setReviewDate(event.target.value)} /></label>
            <label className="analysis-file-input">Reviewed reference GeoTIFF (0/1/255)
              <input required accept=".tif,.tiff,image/tiff" type="file" onChange={(event) => setMethodReferenceFile(event.target.files?.[0] ?? null)} />
            </label>
            <label>Minimum common pixels<input required min="2" max="2000000" step="1" type="number" value={minimumCommonPixels} onChange={(event) => setMinimumCommonPixels(event.target.value)} /></label>
            <label>Minimum reference coverage fraction<input required min="0.000001" max="1" step="any" type="number" value={minimumCoverage} onChange={(event) => setMinimumCoverage(event.target.value)} /></label>
            <label>Minimum pixels per reference class<input required min="1" max="2000000" step="1" type="number" value={minimumPerClass} onChange={(event) => setMinimumPerClass(event.target.value)} /></label>
            <label>Spatial block size (pixels)<input required min="1" max="2000000" step="1" type="number" value={spatialBlockSize} onChange={(event) => setSpatialBlockSize(event.target.value)} /></label>
            <label>Minimum occupied blocks per reference class<input required min="1" max="2000000" step="1" type="number" value={minimumBlocks} onChange={(event) => setMinimumBlocks(event.target.value)} /></label>
            <p className="validation-wide-field">Declare thresholds appropriate to the sampling design before analysis. Reference coverage is shared pixels divided by reference-valid pixels on the candidate grid. Square blocks are anchored at the grid's top-left; each class must occur in the declared number of blocks on shared support. Occupied blocks do not establish representativeness or scientific validity.</p>
            </>}
            {methodIds.map((methodId, index) => (
              <div className="method-candidate-input" key={index}>
                <strong>Candidate method {index + 1}</strong>
                <label>Method ID<input required maxLength={64} pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" value={methodId} onChange={(event) => setMethodIds((current) => current.map((value, itemIndex) => itemIndex === index ? event.target.value : value))} /></label>
                <label>Method name<input required maxLength={256} value={methodNames[index]} onChange={(event) => setMethodNames((current) => current.map((value, itemIndex) => itemIndex === index ? event.target.value : value))} /></label>
                <label>Parameters (JSON scalar values)<textarea required rows={2} value={methodParameters[index]} onChange={(event) => setMethodParameters((current) => current.map((value, itemIndex) => itemIndex === index ? event.target.value : value))} /></label>
                <label className="analysis-file-input">Candidate mask GeoTIFF (0/1/255)
                  <input required accept=".tif,.tiff,image/tiff" type="file" onChange={(event) => setMethodCandidateFiles((current) => current.map((value, itemIndex) => itemIndex === index ? event.target.files?.[0] ?? null : value))} />
                </label>
              </div>
            ))}
            {methodReviewed && <>
            <label className="validation-wide-field">Reference methodology<textarea required maxLength={4000} rows={2} value={methodology} onChange={(event) => setMethodology(event.target.value)} /></label>
            <label className="validation-wide-field">Limitations, one per line<textarea required rows={2} value={limitations} onChange={(event) => setLimitations(event.target.value)} /></label>
            <label className="validation-wide-field validation-checkbox-field">
              <input checked={independentReviewCompleted} onChange={(event) => setIndependentReviewCompleted(event.target.checked)} required type="checkbox" />
              I confirm these reference labels were independently reviewed and are not another candidate classification.
            </label>
            </>}
            <button className="button-secondary analysis-submit validation-wide-field" disabled={methodEvaluating || (methodReviewed && !methodReferenceFile) || methodCandidateFiles.some((file) => !file)} type="submit">
              {methodEvaluating ? <LoaderCircle size={13} className="analysis-spinner" /> : <CheckCircle2 size={13} />}
              {methodEvaluating ? "Comparing on common valid pixels…" : "Evaluate both methods"}
            </button>
          </form>
          {methodEvaluationError && <p className="analysis-unavailable" role="alert">{methodEvaluationError}</p>}
          {methodEvaluation && (
            <section className="method-evaluation-result" aria-label="Method comparison result">
              <strong>{methodEvaluation.status.replaceAll("_", " ")} · no method selected</strong>
              <span>{methodEvaluation.shared_common_valid_pixel_count.toLocaleString()} shared valid pixels · {methodEvaluation.reference_dataset_id ? `${methodEvaluation.reference_dataset_id} · ${percentage(methodEvaluation.shared_reference_coverage_fraction)} reference coverage` : `${percentage(methodEvaluation.shared_grid_coverage_fraction)} grid coverage`}</span>
              {methodEvaluation.processing && <span>Windowed processing: {methodEvaluation.processing.windows_processed.toLocaleString()} windows of up to {methodEvaluation.processing.window_width_pixels} × {methodEvaluation.processing.window_height_pixels} pixels · coverage relative to first grid · no resampling</span>}
              {methodEvaluation.candidate_acquisition_datetime && <span>Candidate acquisition: {new Date(methodEvaluation.candidate_acquisition_datetime).toISOString()}</span>}
              {methodEvaluation.reference_dataset_id && <span>Declared minimum: {methodEvaluation.minimum_common_pixels ?? "Unavailable"} pixels · {percentage(methodEvaluation.minimum_coverage_fraction)} reference coverage</span>}
              {methodEvaluation.reference_class_counts && <span>Reference class pixels (0/1): {methodEvaluation.reference_class_counts["0"]} / {methodEvaluation.reference_class_counts["1"]} · occupied blocks (0/1): {methodEvaluation.reference_class_block_counts?.["0"] ?? "Unavailable"} / {methodEvaluation.reference_class_block_counts?.["1"] ?? "Unavailable"}</span>}
              {typeof methodEvaluation.temporal_offset_seconds === "number" && <span>Candidate/reference time offset: {(methodEvaluation.temporal_offset_seconds / 3600).toFixed(2)} hours · temporal suitability requires human assessment.</span>}
              {methodEvaluation.methods.map((method) => (
                <div className="method-evaluation-item" key={method.method_id}>
                  <strong>{method.method_name}</strong>
                  <small>Parameters: {JSON.stringify(method.parameters)}</small>
                  <small>Candidate area: {method.candidate_area_m2 == null ? "Unavailable" : `${method.candidate_area_m2.toLocaleString()} m² (${(method.candidate_area_m2 / 1_000_000).toFixed(6)} km²)`} · differing area from first method: {method.difference_from_first_area_m2 == null ? "Unavailable" : `${method.difference_from_first_area_m2.toLocaleString()} m²`}</small>
                  <small>{method.confusion_matrix
                    ? `TP ${method.confusion_matrix.true_positive} · TN ${method.confusion_matrix.true_negative} · FP ${method.confusion_matrix.false_positive} · FN ${method.confusion_matrix.false_negative}`
                    : "Confusion metrics unavailable on this support."}</small>
                  {methodEvaluation.status === "evaluation_completed" && <small>Precision {percentage(method.precision)} · Recall {percentage(method.recall)} · F1 {percentage(method.f1_score)} · IoU {percentage(method.intersection_over_union)}</small>}
                </div>
              ))}
              {(methodEvaluation.pairwise_comparisons ?? []).map((pair) => (
                <small key={`${pair.first_method_id}-${pair.second_method_id}`}>
                  {pair.first_method_id} vs {pair.second_method_id}: absolute area difference {pair.absolute_area_difference_m2 == null ? "Unavailable" : `${(pair.absolute_area_difference_m2 / 1_000_000).toFixed(6)} km²`} · difference relative to first {percentage(pair.area_difference_fraction_of_first)} · mask disagreement {percentage(pair.disagreement_fraction)} · candidate-mask IoU {percentage(pair.intersection_over_union)} (not accuracy)
                </small>
              ))}
              {methodEvaluation.warnings.map((warning) => <small key={warning}>{warning}</small>)}
              {methodEvaluation.report_url && <a href={`${API_BASE_URL}${methodEvaluation.report_url}`} rel="noreferrer" target="_blank">Download method comparison report</a>}
            </section>
          )}
        </details>
        {status?.reports?.length > 0 && (
          <section className="validation-report-history" aria-label="Saved validation reports">
            <strong>Saved reports</strong>
            {status.reports.map((savedReport) => (
              <a key={savedReport.validation_id} href={`${API_BASE_URL}${savedReport.report_url}`} target="_blank" rel="noreferrer">
                {savedReport.river_id} · {savedReport.candidate_product_id} vs. {savedReport.reference_dataset_id} · {savedReport.status.replaceAll("_", " ")}
              </a>
            ))}
          </section>
        )}
        <form className="validation-form" onSubmit={submit}>
          <label>Validation mode
            <select value={windowedValidation ? "windowed" : "legacy"} onChange={(event) => { setWindowedValidation(event.target.value === "windowed"); setReport(null); }}>
              <option value="legacy">Small rasters with reference reprojection</option>
              <option value="windowed">Windowed same-grid assessment</option>
            </select>
          </label>
          {windowedValidation && <p className="validation-wide-field">Both rasters must have identical dimensions, CRS and transform; no resampling or partial overlap is supported. Combined uploads are limited to 100 MB. Review, independence, product and version are operator declarations, not authenticated proof.</p>}
          <label>River
            <select value={riverId} onChange={(event) => setRiverId(event.target.value)}>
              <option value="kaveri">Kaveri River</option>
              <option value="tungabhadra">Tungabhadra River</option>
            </select>
          </label>
          <label>Candidate product ID<input required maxLength={512} value={candidateId} onChange={(event) => setCandidateId(event.target.value)} /></label>
          <label>Candidate sensor<input required maxLength={80} value={candidateSensor} onChange={(event) => setCandidateSensor(event.target.value)} /></label>
          {windowedValidation && <label>Candidate processing version<input required maxLength={256} value={candidateProcessingVersion} onChange={(event) => setCandidateProcessingVersion(event.target.value)} /></label>}
          <label>Candidate acquisition (local time)<input required type="datetime-local" value={candidateDate} onChange={(event) => setCandidateDate(event.target.value)} /></label>
          <label className="analysis-file-input">Candidate mask GeoTIFF (0/1/255)
            <input required accept=".tif,.tiff,image/tiff" type="file" onChange={(event) => setCandidateFile(event.target.files?.[0] ?? null)} />
          </label>
          <label>Reference dataset ID<input required maxLength={256} value={referenceId} onChange={(event) => setReferenceId(event.target.value)} /></label>
          <label>Reference provider<input required maxLength={256} value={provider} onChange={(event) => setProvider(event.target.value)} /></label>
          <label>Reference acquisition (local time)<input required type="datetime-local" value={referenceDate} onChange={(event) => setReferenceDate(event.target.value)} /></label>
          <label>Reference resolution (metres)<input required min="0.01" step="any" type="number" value={resolution} onChange={(event) => setResolution(event.target.value)} /></label>
          <label>Minimum common pixels<input required min="2" max="2000000" step="1" type="number" value={minimumCommonPixels} onChange={(event) => setMinimumCommonPixels(event.target.value)} /></label>
          <label>Minimum candidate coverage fraction<input required min="0.000001" max="1" step="any" type="number" value={minimumCoverage} onChange={(event) => setMinimumCoverage(event.target.value)} /></label>
          <label>Minimum pixels per reference class<input required min="1" max="2000000" step="1" type="number" value={minimumPerClass} onChange={(event) => setMinimumPerClass(event.target.value)} /></label>
          <label>Spatial block size (pixels)<input required min="1" max="2000000" step="1" type="number" value={spatialBlockSize} onChange={(event) => setSpatialBlockSize(event.target.value)} /></label>
          <label>Minimum occupied blocks per reference class<input required min="1" max="2000000" step="1" type="number" value={minimumBlocks} onChange={(event) => setMinimumBlocks(event.target.value)} /></label>
          <p className="validation-wide-field">Declare thresholds appropriate to the sampling design before analysis. Candidate coverage is common pixels divided by candidate-valid pixels. Square blocks are anchored at the grid's top-left; each class must occur in the declared number of blocks on common support. Occupied blocks do not establish representativeness or scientific validity.</p>
          <label className="analysis-file-input">Reviewed reference GeoTIFF (1 water, 0 non-water, 255 uncertain/NoData)
            <input required accept=".tif,.tiff,image/tiff" type="file" onChange={(event) => setReferenceFile(event.target.files?.[0] ?? null)} />
          </label>
          <label>Reviewer<input required maxLength={256} value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></label>
          <label>Review date<input required type="date" value={reviewDate} onChange={(event) => setReviewDate(event.target.value)} /></label>
          <label className="validation-wide-field">
            <input
              checked={independentReviewCompleted}
              onChange={(event) => setIndependentReviewCompleted(event.target.checked)}
              type="checkbox"
            />
            I confirm the reference labels were independently reviewed
          </label>
          <label className="validation-wide-field">Reference methodology<textarea required maxLength={4000} rows={2} value={methodology} onChange={(event) => setMethodology(event.target.value)} /></label>
          <label className="validation-wide-field">Known limitations (one per line)<textarea required rows={2} value={limitations} onChange={(event) => setLimitations(event.target.value)} /></label>
          <button className="button-secondary analysis-submit" disabled={submitting || !candidateFile || !referenceFile || !independentReviewCompleted} type="submit">
            {submitting ? <LoaderCircle size={13} className="analysis-spinner" /> : <CheckCircle2 size={13} />}
            {submitting ? "Comparing valid labels…" : windowedValidation ? "Assess reviewed labels" : "Validate against reviewed labels"}
          </button>
        </form>

        {error && <p className="analysis-unavailable" role="alert"><AlertCircle size={13} /> {error}</p>}
        {report && (
          <section className="validation-report" aria-label="Validation report">
            <strong>{report.status.replaceAll("_", " ")}</strong>
            <span>{report.reference_dataset_id} · {report.candidate_product_id} · {report.common_valid_pixel_count.toLocaleString()} common pixels · {percentage(report.valid_reference_coverage_fraction)} candidate support covered</span>
            <span>
              Acquisition separation: {report.acquisition_time_difference_seconds == null
                ? "Unavailable"
                : `${(report.acquisition_time_difference_seconds / 3600).toFixed(2)} hours`}
              {" "}· temporal suitability requires independent review
            </span>
            <span>Declared minimum: {report.minimum_common_pixels ?? "Unavailable"} pixels · {percentage(report.minimum_coverage_fraction)} candidate coverage</span>
            {report.reference_class_counts && <span>Reference class pixels (0/1): {report.reference_class_counts["0"]} / {report.reference_class_counts["1"]} · occupied blocks (0/1): {report.reference_class_block_counts?.["0"] ?? "Unavailable"} / {report.reference_class_block_counts?.["1"] ?? "Unavailable"}</span>}
            {report.confusion_matrix && (
              <span>
                TP {report.confusion_matrix.true_positive.toLocaleString()} · TN {report.confusion_matrix.true_negative.toLocaleString()} ·
                FP {report.confusion_matrix.false_positive.toLocaleString()} · FN {report.confusion_matrix.false_negative.toLocaleString()}
              </span>
            )}
            {report.status === "validation_completed" && (
              <span>
                Precision {percentage(report.precision)} · Recall {percentage(report.recall)} ·
                F1 {percentage(report.f1_score)} · IoU {percentage(report.intersection_over_union)}
                {report.overall_agreement != null && <> · Agreement {percentage(report.overall_agreement)}</>}
              </span>
            )}
            {report.status === "thresholds_met_awaiting_evaluation" && <>
              <button className="button-secondary" type="button" disabled={submitting} onClick={evaluateAssessment}>Evaluate submitted assessment</button>
              <label>Rejection reason<input maxLength={1000} value={rejectionReason} onChange={(event) => setRejectionReason(event.target.value)} /></label>
              <button className="button-secondary" type="button" disabled={submitting || !rejectionReason.trim()} onClick={rejectAssessment}>Reject submitted assessment</button>
            </>}
            {report.evaluation_outcome_detail && <span>Evaluation outcome: {report.evaluation_outcome_detail}</span>}
            {report.warnings.map((warning) => <small key={warning}>{warning}</small>)}
          </section>
        )}
      </div>
    </article>
  );
}
