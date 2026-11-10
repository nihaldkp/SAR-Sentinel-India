# SAR Sentinel India — Master Task Checklist

Completion percentage is calculated only from checked items: **64 / 69 = 92.8%**. “Partial” and “blocked” items do not count as complete; this is not a scientific validation score.

National platform phase checkpoint (not included in the historical 69 items):
- [ ] National source import, spatial database, paginated explorer and general river monitoring. NWIC API and map explorer work with an isolated real single-feature extract; review-only snapshot staging and provisional comparison exist. Full national import, dataset-specific rights, stable identities, reviewed reconciliation and atomic publication, unified selection and general monitoring remain incomplete. See [handoff](./PROJECT_HANDOFF.md).
- [ ] Agriculture monitoring with real observations and quality handling.
- [ ] Forest monitoring with real observations and quality handling.
- [ ] Real earthquake-event monitoring.
- [ ] Ground-deformation/InSAR processing from suitable complex inputs.
- [ ] Combined analysis and data-grounded cross-module AI/dashboard integration.
- [ ] National-scale performance, end-to-end real-data verification and scientific evidence.

Latest NISAR audit corroborated existing product processing and live dashboard
display, not scientific validation; no checklist boxes changed. Catalog-based
connection status is partial and cannot verify current authentication or search
history. See [audit](./data/NISAR-CONNECTION-AUDIT.md).

Latest continuation: dynamic existing-catalog map selection and transactional bound count calculation were added; national import/search, generalized monitoring, bound evaluation and publication recovery remain incomplete. Backend 156 passed/1 skipped, mocked browser 17 passed. This historical checklist does not measure new national scope; no boxes changed. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

Latest continuation: bound-reference reservation with immutable input snapshots and atomic withdrawal rejection is tested across processes; windowed computation was separated from report persistence. Evaluation, report recovery, supersession, security and UI remain incomplete; the requested stopping gate is not met. Focused 71 passed/1 skipped, backend 151 passed/1 skipped. No checklist items changed. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

Latest continuation: point-in-time product identity, grid, fingerprints and review checks now have a persistent API audit history; these do not authorize evaluation or establish independent evidence. Evaluation/AI/UI integration, supersession, security and live audit remain open. Focused 34 passed, backend 145 passed/1 skipped, mocked Playwright 16 passed; build passed. No checklist items changed. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

Latest continuation: API-only unreviewed product-bound reference records, review transitions and local SQLite cross-process transition serialization were added, but evaluation/AI/UI integration, supersession and security audit remain open. Focused 31 passed, backend 142 passed/1 skipped, mocked Playwright 16 passed; build passed. No checklist item changed. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

Latest continuation: explicit rejected/failed evaluation outcomes and selected listing containment were added; fresh local-data browser checks covered A_009/A_010 and Kaveri, not the entire requested audit. Backend 133 passed/1 skipped, focused 53 passed/1 skipped, mocked Playwright 16 passed, build passed. No checklist items changed; see [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

Latest continuation: exact-grid windowed reviewed assessment and explicit evaluation are implemented but the requested complete evidence lifecycle and file-security audit are not. Focused/backend/Playwright tests passed 48/128/16; build passed. No evidence-dependent box changed; see [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

2026-11-10 continuation: full-scene exploratory windowing, product-matched evidence status, WGS84 axis input checks and selected path containment were added. Focused validation/AI tests 29/11, backend 120 and Playwright 16 passed; build passed. No evidence-dependent checklist box was changed; the broader audit remains incomplete.

2026-11-10 audit checkpoint: per-class pixel and occupied-block gates and pairwise candidate overlap were added. Focused/backend/Playwright tests passed 25/103/16, respectively, and the frontend build passed. Full-scene comparison remains limited by the two-million-pixel upload cap; the broader audit remains in progress. No checklist items changed.

2026-11-10: Reviewed metrics now require operator-declared minimum shared pixels and coverage, and candidate-only method comparison is available without accuracy claims. These software safeguards do not fulfill the five unchecked evidence-dependent items. Verification: 18 focused validation tests, 96 backend tests, 16 Playwright tests and the frontend build passed.

## Phase 1 — Repository and runtime audit

- [x] Inventory frontend, backend, tests, dependencies and data directories.
- [x] Inspect every API, schema, processing and UI feature and write the requested audit report.
- [x] Verify current health, catalog and river API endpoints.
- [x] Verify Python dependency consistency and `.env` Git-ignore behavior.
- [x] Audit frontend/backend errors and all file-serving paths.

## Phase 2 — River selection and map

- [x] Preserve existing Leaflet map and river geometry API.
- [x] Verify Kaveri-only, Tungabhadra-only and Both Rivers selections in browser.
- [x] Make river legend entries match currently visible centerlines.
- [x] Clear stale satellite footprint/candidate overlay when the river selection changes.
- [x] Add persistent browser-driven regression automation for river selection.
- [x] Add/refine dynamic legends for every optional scientific layer.

## Phase 3 — Satellite discovery and acquisition

- [x] Keep ASF/Earthdata NISAR access and Sentinel-1 RTC fallback architecture.
- [x] Preserve duplicate-avoidance/status tracking behavior already covered by backend tests.
- [x] Distinguish an acquisition with no usable corridor pixels from a genuine processing failure without relaxing validity rules.
- [x] Add recovery and retention of local HDF5-verified NISAR records when catalog scans return no products.
- [x] Verify recovery through the live API after restarting the updated backend.
- [x] Investigate the latest Kaveri Sentinel-1 failure (fewer than 32 valid positive pixels) and confirm whether it is genuinely unusable coverage.
- [x] Improve candidate filtering to use corridor/footprint overlap rather than only broad query extents where needed.
- [x] Add recoverable download/processing-job status beyond request-thread execution.
- [x] Persist job identity, lifecycle timestamps, stage, measurable progress, errors and output references in SQLite.
- [x] Add job submit/list/detail/retry/cancel APIs with active-operation deduplication.
- [x] Keep NISAR download/processing and Sentinel-1 acquisition job paths separate.
- [x] Recover queued and interrupted work after backend restart without corrupting completed products.
- [x] Add dashboard job status, stage, timestamp, error and retry controls.
- [x] Keep automatic acquisition scheduling disabled unless explicitly enabled.

## Phase 4 — NISAR scientific processing

- [x] Read actual frequency-A HHHH/HVHV, geolocation, CRS, spacing and validity information for the downloaded product.
- [x] Keep processing windowed and preserve NoData.
- [x] Preserve exact threshold math, HH/HV comparison, sensitivity and connectivity diagnostics.
- [x] Verify small-fixture tests and the existing actual A_009 outputs.
- [ ] Independently validate the classification. Reference-source discovery and reviewed-label import are now available, but no suitable independent labels have been obtained or scored.
- [ ] Implement and compare another classification method only when scientifically and empirically justified. A common-support comparison API is available for future reviewed comparisons, but no alternative method is currently empirically justified.

## Phase 5 — Filtering and cleanup

- [x] Design a separately stored cleaned candidate mask, preserving invalid pixels.
- [x] Evaluate a tested speckle/connected-component cleanup on real candidate data.
- [x] Expose filter parameters, comparison outputs and quality flags.

The canonical NISAR classification has no spatial filter. An opt-in API/dashboard workflow now creates separately stored 8-connected component-size scenarios without changing the source mask; invalid pixels remain 255 NoData. On the real Tungabhadra A_009 product, the 2-, 5-, and 10-pixel scenarios reclassify 89,437 (2.30%), 202,003 (5.20%), and 283,567 (7.30%) of candidate pixels as non-water. Each output preserves all 550,634,840 NoData pixels. This is a tested sensitivity evaluation, not evidence that removed components are noise and not a recommendation to clean the canonical classification. No cutoff has been selected for scientific use.

## Phase 6 — Sentinel-2 reference preparation

- [x] Discover Sentinel-2 L2A catalog items with overlapping corridor footprints (metadata only, prior work).
- [x] Acquire/read suitable optical pixels and SCL/cloud-shadow masks.
- [x] Generate a documented, NoData-preserving exploratory optical candidate mask on a comparable grid; it is not ground truth.
- [x] Report acquisition-time difference, valid coverage and resampling.
- [x] Screen remaining Sentinel-2 L2A items with reproducible STAC footprint/NISAR-support metrics.
- [x] Generate separate same-overpass tile candidates and expose their metadata, preview, download and map controls without replacing the existing output.

## Phase 7 — Quantitative validation

- [x] Implement confusion-matrix and quality-metric calculations only over mutually valid pixels when both reference classes are present.
- [x] Add provenance-bearing validation API and dashboard submission, pending/error, and report states for reviewed GeoTIFF labels.
- [ ] Obtain independently reviewed, temporally suitable reference labels; no accuracy metrics are reported until such evidence exists. Public-source limitations and a bounded local import workflow are documented; no suitable labels are currently available.
- [x] Show comparison area, clouds, NoData and temporal offset.
- [x] Expose candidate status and scientific limitations in API and UI without presenting them as validation.
- [x] Investigate independent reference datasets, actual target-area scene overlap, temporal fit and access conditions; document a reproducible validation protocol without fabricating labels or scores.
- [x] Inspect bounded near-date Landsat reflectance and QA over actual common-valid support; assess spatial distribution and manual-label feasibility without using candidate classes to guide interpretation.

## Phase 8 — River measurements

- [x] Existing uploaded-mask transect width endpoint reports candidate segments and caveats.
- [ ] Implement river-axis sampling restricted to the intended channel/corridor (deferred: the available OSM centerline is not an independently verified channel axis and riverbank boundaries are unavailable). A bounded API accepts a user-supplied axis and containing corridor, but trusted target geometry is still unavailable and the endpoint does not use OSM. CWC/NWIC's direct national river-line GeoJSON advertised a 356 MB payload; it was not downloaded, and its target features, CRS, active-channel fit, and bank accuracy remain unverified.
- [ ] Add quality flags, coverage and uncertainty for candidate width measurements before presenting automated river-axis samples. Coverage and quality flags are reported by the preparatory API; uncertainty is explicitly unquantified, so the acceptance criterion remains incomplete.

## Phase 9 — Multi-date change detection

- [x] Existing uploaded-mask comparison requires same river, chronological dates and identical grids.
- [x] Inspect actual stored same-river Sentinel-1 candidate-mask grids and identify compatible exact-grid pairs without treating incompatible observations as comparable.
- [x] Build reproducible comparisons from compatible, actual same-sensor acquisitions.
- [x] Report common-valid coverage, acquisition dates, seasonal context, threshold/filter compatibility and provenance.
- [x] Keep comparison outputs explicitly unvalidated; do not label candidate water-extent differences as erosion/deposition or verified hydrological change.

## Phase 10 — Dashboard and API integration

- [x] Keep real NISAR and Sentinel-1 products separately labeled from demo overlays.
- [x] Show real NISAR comparison, threshold sensitivity and component diagnostics.
- [x] Smoke-test health, regions, observations, rivers, analysis status and acquisition APIs.
- [x] Add an independently selectable Sentinel-2 NDWI candidate raster layer with geospatial metadata, class/NoData legend, and explicit exploratory warning.
- [x] Add deterministic local AI Analysis using persisted satellite records, selectable products, diagnostics, loading/error/empty states, and explicit scientific limitations.
- [x] Keep download controls conditional on real output references and persisted files.

## Phase 11 — Performance, QA and documentation

- [x] Run backend tests, frontend build and `pip check`.
- [x] Retain full-resolution NISAR raster outputs and windowed large-product processing.
- [x] Document the existing frontend bundle-size warning.
- [x] Add frontend regression tests with existing or minimal tooling.
- [x] Complete project audit, architecture, setup, API, methods and reproduction documentation.
- [x] Add backend and browser regression tests for acquisition job lifecycle and retry UX.
- [x] Run full backend suite, frontend build, API smoke tests and Git whitespace checks for this phase.

## Final deliverable

- [x] Create `FINAL_PROJECT_COMPLETION_REPORT.md` after feasible work is complete and remaining blockers are stated.
