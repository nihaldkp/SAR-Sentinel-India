# SAR Sentinel India — Project Changelog

## Source verification and snapshot review — partial

- Verified CWC portal metadata and general NWIC copyright policy; specific
  rights, stable identifiers and full dataset CRS/schema remain unresolved.
- Added review-only resumable snapshot storage, paginated provisional
  comparison, retained failures and process-shared import serialization.
  Active-catalogue promotion and rollback are not implemented.
- Tested process interruption and the genuine isolated Balijan extract.
  Focused backend: 20 passed; mocked river Playwright: 21 passed; build,
  Python compilation and `pip check` passed. No national dataset was
  acquired or imported. Details and commands: [handoff](./PROJECT_HANDOFF.md).

## NWIC explorer continuation — partial

- Added paginated NWIC feature search and on-demand geometry endpoints, and a
  separate attributed map explorer that explicitly does not select a monitoring
  target. Pilot selection cancels pending NWIC geometry requests.
- Added an atomic guard against importing a different source fingerprint into
  the same catalog until version reconciliation exists.
- Verified the real bounded Balijan extract in an isolated database through
  API and browser. No full national dataset was imported. Focused backend:
  17 passed; mocked river Playwright: 21 passed; production build passed with
  a chunk-size warning. See [handoff](./PROJECT_HANDOFF.md) for limitations.

## 2026-11-10 — NWIC import prototype

- Added streaming local KML import with per-feature SQLite checkpoints,
  source fields and R-tree bounds; conflicting source IDs are rejected.
- Inspected bounded NWIC metadata and one genuine KML feature. The real sample
  was tested in an isolated session database; no national project data import
  or explorer integration occurred. Focused importer/API tests: 15 passed.
- Source terms and CRS, version reconciliation, concurrency, scaling and
  national UI/API integration require further work; see [handoff](./PROJECT_HANDOFF.md).

## 2026-11-10 — Pilot river search

- Added case- and accent-insensitive client-side search of registered river
  names, display names and IDs, retaining the selected map river on filtering.
- Confirmed real local API/browser behavior with two pilot records, 19 mocked
  Playwright tests, 12 backend API tests and a production build. National
  import, paginated database-backed search and monitoring remain incomplete.

## 2026-11-10 — NISAR connection audit and status

- Added catalog-derived NISAR status summary to the acquisition API and
  dashboard, with explicit unknown live connectivity/authentication and
  catalog-only counts. It is not a full persistent attempt-history diagnostic.
- Verified live ASF metadata, two existing HDF5 products, a bounded A_009
  source/output sample and real dashboard display. No download, checksum or
  authenticated access test was performed. See [audit](./data/NISAR-CONNECTION-AUDIT.md).
- Validation results now expose absolute acquisition time separation when
  both times have timezones; the dashboard cautions that suitability requires
  review. Backend 159 passed/1 skipped, focused validation 41 passed/1 skipped,
  mocked Playwright 18 passed and build passed.

## 2026-11-10 — Catalog selector and bound calculation

- Map selector now uses returned catalog entries rather than a fixed list and warns registration does not establish monitoring. Current catalog still contains only Kaveri and Tungabhadra; national search/import and general monitoring remain open.
- Added SQLite-bound, pre-evaluation common-support calculation with input/review rechecks, idempotent retry and process-interruption/withdrawal race tests. No accuracy or report publication was added.
- Backend 156 passed/1 skipped, mocked Playwright 17 passed and frontend build passed. No new national source or satellite data downloaded; no fresh live browser check. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## 2026-11-10 — Bound assessment reservations (partial milestone)

- Added SQLite reservation/event tables, immutable-input/history triggers, bounded candidate snapshots, exact identity/fingerprint/grid checks, idempotent retry, API inspection and atomic rejection of pending reservations on withdrawal.
- Extracted windowed computation from legacy report persistence, preserving the existing API. Fixture tests cover calculation without report creation, cross-process withdrawal, duplicate/conflicting reservations, injected event-write rollback and database integrity. Focused 71 passed/1 skipped, backend 151 passed/1 skipped. No real reference evidence or new live browser audit.
- No evaluation, derived-report recovery, supersession, AI or UI integration was implemented. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## 2026-11-10 — Reference identity-check snapshot

- Added persisted, bounded identity/review/grid/fingerprint checks and retrieval for bound references, with a SQLite lock shared with review transitions and a separate-process withdrawal race test. No evaluation metrics are produced.
- Checks accept small candidate uploads only; passing does not prove authenticated identity, independence or adequate evidence. Evaluation, AI, UI and supersession remain disconnected.
- Focused 34 passed, backend 145 passed/1 skipped, mocked Playwright 16 passed; build and `pip check` passed. No current-turn real browser test or genuine reference import. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — bound-reference preparation and transitions

- Added API-only unreviewed reference records with user-declared product metadata, input hashes, reference raster and explicit unauthenticated review history. SQLite transactions serialize review decisions and enforce storage quotas. This does not bind existing evaluation reports to these records.
- SQLite local locking and atomic JSON history now guard windowed evaluation/rejection across cooperating processes; independent-process races and failed reference-write rollback are covered.
- Focused 31 passed, backend 142 passed/1 skipped, mocked Playwright 16 passed; production build and `pip check` passed. Actual local A_009 browser and API smoke passed. No new real reference or scientific score was produced. Unfinished integration, supersession and security: [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — evaluation outcomes and live checks

- Added persisted terminal rejection and known consistency-failure outcomes, timestamps, AI status, API and form action; no reviewer/operator authentication or cross-worker exclusion.
- Applied resolved containment and identifier checks to reference/validation listings; simulated external resolution passed, actual symlink test skipped for Windows privilege limitations. TOCTOU and comprehensive audit remain open.
- Real local browser/API checks verified selected A_009, A_010, Kaveri and pending validation. Focused 53 passed/1 skipped, backend 133 passed/1 skipped, mocked Playwright 16 passed; build and `pip check` passed. Details and unfinished work: [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — reviewed assessment and candidate identity

- Added persistent bounded exact-grid reviewed assessment, explicit evaluation, form integration, per-class/block support and raster fingerprints; legacy validation now honors internal masks.
- AI requires product/date/version and local NISAR candidate SHA-256 to associate a submitted report. Attestations remain unauthenticated; unmatched or unavailable identity is explicit.
- Focused/backend/Playwright tests passed 48/128/16; three focused safety tests and build passed; `pip check` clean. The full lifecycle, multiworker guarantees, comprehensive security audit and scientific validation remain open. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## 2026-11-10 — Windowed real-data and evidence-status continuation

- Added bounded windowed exploratory comparison for aligned, partially overlapping uint8 candidate rasters, with shared support, pairwise counts and grid/window provenance; full A_009 candidate/sensitivity comparison succeeded. Reviewed comparison remains size-limited.
- Derived AI evidence status from selected-product/date reports and recorded reference attestations without treating them as authenticated; displayed the status and caveats in the existing panel. The workflow does not support a separate thresholds-met/awaiting-validation assessment or independently authenticated validation.
- Rejected invalid WGS84 axis coordinates and tightened several output-file containment checks. Live dashboard and acquisition-disabled API checks used the actual local catalog.
- Tests: focused validation 29, AI 11, combined focused 60, backend 120, Playwright 16 passed; build and `pip check` passed. Existing Starlette/httpx and Vite chunk warnings remain. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md) for limitations and next steps.

## 2026-11-10 — In-progress distribution and pairwise audit

- Added operator-declared per-class pixel and occupied-block gates for reviewed metrics, including legacy-report withholding, plus all-pairs candidate area difference, disagreement and IoU on shared support. No candidate overlap is described as accuracy.
- Exercised an in-memory A_009 crop; the full-size source is rejected by the existing two-million-pixel comparison limit. The broader real-data audit remains incomplete, with five scientific checklist items still open.
- Verification: 25 focused validation tests, 103 backend tests, 16 Playwright tests and frontend build passed; `pip check` clean. Starlette/httpx deprecation and Vite chunk warnings remain. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## 2026-11-10 — Evidence gates and exploratory method comparison

- Required operator-declared minimum shared pixels and coverage for new reviewed scores; withheld legacy scores without recorded qualifying thresholds without modifying stored reports. Corrected overall validation status for insufficient reports, enforced reference NoData for method evaluation, and fixed zero-true-positive F1.
- Added candidate-only common-support comparison without accuracy or a winner; both comparison modes report per-method candidate area and disagreement area. Preserved reviewed reference provenance in method reports and linked the existing form from Analysis.
- Focused validation tests: 18 passed; full backend: 96 passed with one Starlette/httpx warning; Playwright: 16 passed; frontend build passed with a 1,596.74 kB chunk advisory. No real reference labels, scientific metrics, acquisitions or verified width outputs were created.
- The 64/69 checklist count and five evidence-dependent blockers remain unchanged; operator thresholds do not establish representativeness.

## 2026-11-09 — Public geometry-source screening and final regression

- Updated the CWC/NWIC catalog entry to link directly to the national GeoJSON. The official endpoint's HTTP HEAD response advertised a 356,234,820-byte payload; it was not downloaded. Documented that feature/CRS fit and active-channel/bank suitability remain unverified, alongside the limitations of generalized HydroRIVERS, static GRWL, and the Bhuvan WBIS technical document.
- Fixed two Playwright selectors that became ambiguous after the method-comparison form added duplicate labels; selectors now scope to the independent-validation form.
- Final verification: 88 backend tests passed with one existing Starlette/httpx deprecation warning; 15 Playwright tests passed; frontend build passed with the Vite 1,593.08 kB JavaScript chunk advisory; project-venv `pip check` passed; 15 acquisition-disabled API smoke requests returned HTTP 200.
- Checklist remains **64/69 (92.8%)**. No reference labels, comparison scores, width results, or scientific claims were fabricated. No satellite data was downloaded, no acquisition job started, and no files were staged or committed.

## 2026-11-09 — Reference workflows and candidate axis-sampling safeguards

- Added public reference-source discovery and bounded reviewed-label GeoTIFF import/list/download endpoints plus dashboard UI. Source catalog entries state temporal, spatial and license limitations; imported provenance and reviewer attestation are recorded but not authenticated.
- Added common-support comparison for two to eight candidate classification rasters on exactly matching grids, with method parameters and persisted reports; no method winner is selected.
- Added a bounded river-axis/corridor sampling endpoint for caller-supplied GeoJSON. It reports per-station candidate segments, coverage and quality flags, does not infer a trusted axis from OSM, and marks uncertainty as not quantified. A regression test prevents candidate segments from being joined across geometry gaps outside a disconnected corridor.
- The five previously unchecked checklist items remain unchecked: no suitable reviewed labels, empirically justified alternate classifier, trusted channel axis/banks, or quantified width uncertainty are available.
- Verification: 88 backend tests passed (one existing Starlette/httpx deprecation warning); 13 Playwright tests passed; frontend build passed with a 1,579.88 kB main-JS chunk advisory; `pip check` clean. Acquisition-disabled TestClient smoke checks returned HTTP 200 for core/catalog/analysis/reference APIs, both AI summaries, and both temporal-pair listings.
- No satellite data, acquisition jobs, ground-truth labels, or scientific metrics were generated. No files staged or committed.

## 2026-11-09 — NISAR candidate component-size sensitivity

- Added bounded request/result schemas and API routes for separate 8-connected component-size sensitivity masks and metadata. Output names are fixed and scenario paths resolve only under the catalog-verified product processing directory.
- Added tiled/windowed processing that labels connected candidate components, writes separate masks, preserves source NoData, CRS, affine transform and resolution, rejects output overwrite, and marks all results as exploratory. The canonical classification is not changed.
- Added frontend API response validation, an opt-in comparison control, scenario counts/download links and explicit quality caveats; added an end-to-end browser regression.
- Applied the 2/5/10-pixel scenarios to the real Tungabhadra A_009 mask. Removed/reclassified candidate pixels: 89,437 / 202,003 / 283,567; remaining candidate pixels: 3,796,445 / 3,683,879 / 3,602,315; NoData preserved: 550,634,840 per scenario. No parameter is scientifically endorsed and removed pixels are not known to be noise.
- Checklist updated to 64/69 (92.8%): only the three Phase 5 engineering/evaluation deliverables were checked. Independent labels, alternate classification and automated river-axis width remain blocked.
- Verification: 79 backend tests passed (one existing Starlette/httpx deprecation warning); 12 Playwright tests passed; frontend build passed (1,572.54 kB chunk advisory); `pip check` clean; core/API smoke checks and all scenario metadata/download routes returned HTTP 200 with automatic acquisition disabled.
- Only separate scenario masks/metadata were generated; no source satellite products or original candidate masks were altered. No staging or commit performed.

## 2026-11-09 — Compatible Sentinel-1 candidate comparisons

- Added typed compatibility metadata and common-valid support to candidate comparisons, `GET /api/analysis/temporal-pairs`, strict exact-grid/product/polarization/filter/threshold-method checks, and pair discovery in the dashboard.
- Added a narrowly gated legacy catalog recovery path for results marked failed by the known `AcquiredObservation` validation error. It changes status only after verifying persisted result identity, mask values/NoData, CRS/grid, pixel size, counts, candidate area and threshold.
- Live catalog checks found five Kaveri and one Tungabhadra compatible pairs. Generated separate candidate comparison masks and PDF reports for one real pair per river; both download routes returned HTTP 200.
- Example Kaveri pair has 436,083 common-valid pixels, 56,238 candidate gain pixels and 71,969 loss pixels. Tungabhadra pair has 418,128 common-valid pixels, 47,214 gain pixels and 54,174 loss pixels. These remain unvalidated candidate differences and do not establish hydrological change.
- Added backend and browser coverage. Verification: 77 backend tests passed (one existing Starlette/httpx deprecation warning); 11 Playwright tests passed; production build passed (1,569.99 kB main-JS advisory); `pip check` found no broken requirements. Acquisition-disabled API checks passed for pair listing, AI summaries, comparisons and actual mask/PDF downloads.
- No source satellite products or candidate masks were modified, and no new acquisition job or download was started. Updated the checklist to 61/69 (88.4%) and revised project progress, audit, completion plan, handoff and final report. Nothing was staged or committed.

## 2026-11-09 — Previous final verification and completion report

- Completed the AI provenance/selection integration: the deterministic analysis API returns available product provenance without signed asset URLs or local paths; the UI marks stale metrics and distinguishes ASF discovery metadata from persisted processed records.
- Added map legend descriptions for satellite footprints and candidate geometries, including the limitation that areas outside a polygon overlay are not classified.
- Reviewed actual NISAR A_009 connected-component size sensitivity. No cleanup threshold or output was chosen because independent evidence is unavailable to distinguish noise from narrow channel candidates.
- Reconfirmed that no stored Sentinel-1 same-river pair has compatible grids and thresholds; no temporal comparison was generated. No validation labels or metrics were created.
- Final checks: 75 backend tests passed (one existing Starlette/httpx deprecation warning), 10 Playwright tests passed, frontend build passed (1,566.08 kB main-JS chunk advisory), `pip check` found no broken requirements, API smoke checks returned HTTP 200 with automatic acquisition explicitly disabled, and `git diff --check` passed.
- Final checklist is 58/69 (84.1%). Created `FINAL_PROJECT_COMPLETION_REPORT.md`, which records software delivery separately from outstanding scientific and data dependencies. No satellite products were modified in this final continuation.

## 2026-11-09 — AI provenance, dashboard selection and map legend

- Expanded analysis product options with acquisition/provider/product/polarization/CRS/resolution provenance and source licensing/catalog record links when available. Sentinel-1 signed asset URLs and local filesystem paths are not returned.
- Added selected-product provenance and a stale-results guard to the AI Analysis panel. Product metrics are hidden after a selector change until that selected product is explicitly analyzed.
- Synchronized ASF discovery selection with the dashboard river. AI Analysis selects it only when present in that river's persisted catalog; otherwise the UI labels it discovery-only and makes no measurement inference.
- Added dynamic map legend entries for live catalog footprints and candidate polygon coverage limitations.
- Added backend and Playwright regressions for provenance, product selection state, discovery-only handling, and river/map selection.
- AI remains deterministic-only; no LLM provider/configuration is implemented or configured. Latest temporal-grid evidence still shows no comparable stored same-river pair; no temporal product was generated.
- Read-only inspection of the existing A_009 candidate mask found 160,502 eight-connected components; arbitrary size cutoffs remove substantial candidate areas. No cleanup output or parameter was selected because no independent reference distinguishes noise from narrow channel candidates.
- Focused AI backend tests: 4 passed; focused browser tests: 3 passed; frontend build passed (1,565.26 kB JS chunk advisory). Full suite pending.

## 2026-11-09 — Independent-validation workflow integration

- Added typed validation provenance/result/status schemas and endpoints for status, bounded GeoTIFF submission, and persisted report retrieval.
- Added common-valid-pixel confusion matrix and precision/recall/F1/IoU calculations with nearest-neighbour categorical reference alignment, class-presence/overlap gates, upload/pixel bounds, and explicit caveats. Reports are atomic JSON; submitted raster bytes are not persisted.
- Added `ValidationWorkspace.jsx`, API client methods, dashboard placement, responsive styling, pending/loading/error/report history and result UI. It makes no claim that labels exist and warns against using Sentinel-2 NDWI as independent reference.
- Added pending and mocked completed-report browser regressions. The fixture response is test-only, not a scientific result.
- Updated README and project progress, checklist, audit and handoff. Checklist is 55/69 (79.7%); no independent validation labels or metrics exist.
- Verification: 75 backend tests passed (one existing Starlette/httpx deprecation warning); 9 Playwright browser tests passed; frontend build passed with 1,562.53 kB main-JS advisory. No satellite product was downloaded or processed; no acquisition job started.
- Read-only file-serving/map-layer audit confirmed fixed output allowlists, catalog/path constraints and existing negative/error-state coverage; no code change was warranted.
- Reviewed river-axis sampling feasibility and deferred automated cross-sections: OSM centerlines are not independently verified channel axes, and left/right bank geometry is unavailable. The existing hand-drawn transect service remains an unvalidated candidate-mask segment measurement.

## 2026-11-09 — Additional Sentinel-2 same-overpass coverage

- Added metadata-first STAC screening in `backend/scripts/inspect_sentinel2_coverage.py`, including each item’s centerline footprint overlap and valid A_009 mask pixels under the footprint. A bounded COG screening step now skips source reads for processing blocks with no NISAR corridor support.
- Generalized `backend/scripts/create_sentinel2_candidate.py` for the four screened 2026-11-06 adjacent tiles while preserving the original 43PGT output. Signing requests are paced at 2.5 seconds, HTTP 429 responses are not retried, signed URLs are not persisted, and each output is stored separately.
- Generated exploratory candidates for 43PER (788,166 common-valid / 28,194 candidate pixels), 43PES (1,630,335 / 122,670), 43PFS (1,972,759 / 931,867), and 43PFT (1,266,000 / 32,019). These masks overlap and are not validation data; they remain NoData outside per-tile common support.
- Added safe per-observation output path resolution and metadata enrichment in `acquisitions.py`, per-tile preview/download endpoints, and independent map-layer/download controls in the acquisition dashboard. Existing NISAR layers and 43PGT output remain intact.
- Changed automatic acquisition scheduling to default off unless explicitly enabled and added a regression test.
- Added `backend/tests/test_sentinel2_coverage.py`, expanded API and Edge coverage, and updated `README.md`, `data/README.md`, `data/SENTINEL2-NISAR-COMPARISON-DIAGNOSTIC.md`, `PROJECT-AUDIT.md`, progress, checklist, completion plan, and handoff.
- Verification: 71 backend tests passed (one existing Starlette/httpx deprecation warning); all 7 Edge tests passed; frontend build passed (1,554.55 kB main JS advisory); actual metadata/preview/mask API checks succeeded for all four tiles; streamed output checks confirmed class counts, CRS and NoData; `pip check` and `git diff --check` passed. Checklist is 53/67 (79.1%).
- No full satellite scenes were downloaded and no acquisition job was submitted. Only bounded B03/B08/SCL COG reads and derived per-tile candidate outputs were produced. No reference labels, scores, or scientific change outputs were produced.

## 2026-11-09 — Deterministic AI Analysis milestone

- Added `backend/app/schemas/ai_analysis.py`, `backend/app/services/ai_analysis.py`, and `POST /api/analysis/ai-summary` in `backend/app/api/routes.py`. The API reads persisted NISAR/Sentinel-1 records and linked Sentinel-2 metadata, reports coverage/candidate/sensitivity fields, and separates no-data from failed products.
- Default selection prefers the latest usable processed NISAR product when available; the caller can request a river and product explicitly. Temporal pairs are reported as not evaluated pending grid, season, and parameter compatibility checks.
- Added `frontend/src/components/AIAnalysisPanel.jsx`, an API client method, and dashboard integration. The UI shows product/river selectors, real catalog values, findings, warnings, no-data support, loading/errors, and explicit limits. It identifies the implementation as deterministic rule-based analysis, not an external LLM.
- Added backend tests for populated/empty catalogs, NISAR and Sentinel-1 metrics, optional optical context, selection, and no-data/failed distinction; added an Edge browser regression.
- Updated README, project audit, completion plan, progress, checklist, changelog, and handoff. Checklist moved from 46/62 to 47/63 (74.6%).
- Live acquisition-disabled API smoke test selected the persisted Tungabhadra NISAR A_009. Reported facts: 12,910,080/15,356,387 valid/corridor pixels; 3,885,882 unvalidated candidate pixels; 93.748% mapped-centerline coverage; recorded threshold-sensitivity area range 271.5856–545.3585 km² (70.45%); linked S2 common-valid area 101.122 km² and candidate area 6.9498 km². These figures are candidate-processing metadata, not scientific validation.
- Verification: 68 backend tests passed; frontend build passed with existing 1,552.51 kB JS chunk advisory; 7 Edge Playwright tests passed, including navigation/empty/error UI states; live API returned HTTP 200; no new dependencies, product downloads, processing jobs, or satellite processing occurred. One existing Starlette/httpx deprecation warning remains.

## 2026-11-09 — Read-only stored-output temporal compatibility check

- Opened the six persisted Sentinel-1 candidate-water GeoTIFFs using the existing analysis output registry and Rasterio; no inputs or catalog rows were changed.
- All three Kaveri masks are 1,200 × 1,200, EPSG:32643, but have distinct affine transforms. Tungabhadra has three masks with distinct transforms; two use EPSG:32643 and one uses EPSG:32644. The stored pair thresholds differ.
- No same-river pair meets the existing exact CRS/transform/dimension requirement. No change analysis was run and no change raster was created. Reprojection/resampling is not silently performed.
- Confirmed acquisition download actions are conditional on real persisted output URLs; A_009 NISAR and Sentinel-2 output links refer to existing products.
- Recorded this feasibility result in the completion plan, audit, progress, handoff, and checklist. Checklist is now 49/64 (76.6%); temporal change analysis remains pending until compatible inputs and scientific context are available.

## 2026-11-09 — Bounded Landsat pixel inspection and label feasibility

- Re-queried `LC09_L2SP_144049_20261103_02_T1` and read only 40 × 40 pixels per asset (1.2 km square, EPSG:32643) from green, red, NIR, SWIR1, QA_PIXEL, and QA_RADSAT. Planetary Computer signing returned HTTP 200 for six assets with 2.5 seconds between requests; signed URLs were memory-only.
- Compared the Landsat window to the existing common-valid support using nearest-neighbor sampling only for support eligibility; candidate class values were not used to select or interpret pixels.
- In the window, 955/1,600 Landsat cells intersected common support and 465/955 passed QA_PIXEL bits 0–5, QA_RADSAT bits 2–5 for bands B3/B4/B5/B6, per-band COG masks, and nonzero-DN checks. The 465 cells occupied 8/16 equal sub-blocks in the southern half.
- Applied the Landsat Collection 2 scale/offset (`DN × 0.0000275 − 0.2`) and visually reviewed a bounded SWIR1/NIR/red false-color browse. The 30 m patch did not show a defensible, unambiguous water/bank boundary; no reference sample, labels, or metrics were created.
- Recorded the 67 h 15 min 08.940 s NISAR time offset, exact window bounds, QA outcome, reflectance summaries, review decision, and alternative evidence needs in `data/INDEPENDENT-VALIDATION-INVESTIGATION.md`.
- No code, existing raster, or candidate mask changed; no full scene was downloaded. Acquisition scheduling was disabled. The prior 429 was not retried repeatedly; this later bounded request succeeded.
- Updated the checklist to 46/62 (74.2%). Verification was documentation/count/whitespace checks only; backend tests and frontend build were not rerun because no code changed. Latest code verification remains 64 backend tests, 4 Edge tests, and a passing frontend production build.

## 2026-11-09 — Independent water-reference investigation

- Added `data/INDEPENDENT-VALIDATION-INVESTIGATION.md` documenting authoritative dataset candidates, access/license facts, temporal compatibility, measured Landsat footprint/common-support overlap, limitations, and a reproducible future reference-label protocol.
- Screening found 4 Tungabhadra Landsat footprints intersecting the mapped centerline and 8 Kaveri footprints in the 2026-10-25 through 2026-11-18 search. For the existing Tungabhadra common-valid support, the nearest 2026-11-03 scene passed the QA_PIXEL bits 0–5 screen for 6,570/112,430 cells (5.844%); clearer 2026-10-26 and 2026-10-25 scenes were 10–12 days before NISAR.
- Confirmed bounded Landsat reflectance/QA COG access. The first 133 × 133 sample window did not overlap the actual common-valid mask; follow-up signing returned HTTP 429 before a target-supported reflectance window could be read. No full image was fetched, and no label was interpreted.
- Assessed JRC GSW 2022–2024 monthly history, ESA WorldCover 2021, GRWL, CWC/NWIC discharge, and NRSC/Bhuvan WBIS. None provides ready-made, event-date independent water labels for the current candidate rasters.
- No labels, confusion matrix, accuracy metrics, or validation claims were generated. No full scenes or global datasets were downloaded and no satellite product or candidate mask was changed.
- Updated the checklist to 45/61 (73.8%): the map's area/cloud/NoData/time context is complete, and this reference-dataset investigation is complete. Independent classification validation remains unchecked.
- Verification: documentation/source consistency and `git diff --check`; no application code changed, so backend tests and frontend build were not rerun. Latest code verification remains 64 backend tests, 4 Edge tests, and a successful production build.

## 2026-11-09 — Map clarity and NISAR catalog recovery

- Updated `frontend/src/App.jsx` so the river map subtitle and legend reflect visible river selection.
- Changed river selection to clear stale selected observation/analysis overlays, allowing the map to refit to the chosen centerline.
- Clarified that overview metrics and charts are demonstrations while actual acquisition results appear separately.
- Updated `backend/app/services/acquisitions.py` to recover local GCOV records from HDF5-validated files and processing metadata, and to merge old downloaded records with current discovery results.
- Updated `backend/tests/test_acquisitions.py` with fixture coverage for recovery and catalog retention.
- Verification at update: focused backend tests 23 passed; frontend build passed with a large-chunk warning. Full suite after latest changes pending.
- Runtime investigation found an actual Kaveri Sentinel-1 candidate processing failure (<32 valid positive pixels); validity checks were not relaxed.

## 2026-11-09 — Corridor-filtered discovery and recovered catalog status

- Added Shapely to `backend/requirements.txt` for exact product-footprint intersection with a locally projected 1,500 m centerline corridor.
- Updated `backend/app/services/satellite.py` so ASF results are filtered by actual footprint overlap and ranked by overlap area after fetching up to five times the requested limit (maximum 100).
- Updated `backend/app/services/acquisitions.py` to apply the same footprint filter to authenticated and unauthenticated NISAR discovery, and to label locally recovered products consistently when the latest remote scan reports no new data.
- Added regression coverage for overlapping/non-overlapping footprints and NISAR search filtering in `backend/tests/test_satellite.py` and `backend/tests/test_acquisitions.py`.
- Updated `README.md` to document corridor filtering and local catalog recovery.
- Verification: full backend suite 49 passed; frontend build passed (existing 1.53 MB chunk advisory); `pip check` and `git diff --check` passed.
- Live API with automatic acquisitions disabled returned health `ok`, two recovered Tungabhadra NISAR entries, and the A_009 result (12,910,080 valid paired pixels; 3,885,882 unvalidated candidate pixels). No data was downloaded during verification.

## 2026-11-09 — Kaveri Sentinel-1 no-valid-pixel diagnosis

- Examined the latest failed Kaveri item and its existing clipped GeoTIFF without refreshing the catalog or downloading data.
- The STAC footprint overlaps the mapped river; catalog footprint bounds are 73.811879–76.431084°E, 10.430358–12.588491°N. The product reports 22.0352% full-centerline coverage.
- The 1,200 × 1,200, 10 m EPSG:32643 crop bounds transform to 75.559920–75.670538°E, 12.277952–12.386713°N. The reference line intersects the crop for 22,758.1 m and rasterizes to 2,914 cells; the 1.5 km corridor contains 459,523 cells.
- All 1,440,000 output raster cells are NoData (-32768); raster mask valid-pixel count and finite-positive backscatter count are both zero. The failure is genuine absence of usable VV observations in this crop. Provider-side COG masks were not separately re-read, so the source-level cause of the missing observations is undetermined. No classification threshold or validity rule was changed.

## 2026-11-09 — Architecture audit

- Created `PROJECT-AUDIT.md` after reviewing the FastAPI routes/schemas/services, React dashboard and panels, geographic data provenance, satellite catalog/acquisition flow, processing methods, local outputs, tests, and live verification.
- The report distinguishes demonstration-only content, actual downloaded/processed products, unvalidated candidate results, and blocked validation tasks.
- Verification results remain 49 backend tests passed, frontend build passed with a large-chunk advisory, `pip check` clean, and live API recovery verified.

## 2026-11-09 — River-map browser regressions

- Added Playwright as a frontend dev dependency and configured `npm run test:e2e`.
- Added browser tests for Both/Kaveri/Tungabhadra selection and legend alignment, centerline visibility toggling, and disabled unavailable bank controls.
- Added test-result ignore rules and setup instructions in `README.md`.
- Verification: 2 browser tests passed using installed Microsoft Edge. The bundled Playwright Chromium could not launch on this host (`spawn UNKNOWN`), so the documented Windows fallback uses `PLAYWRIGHT_CHANNEL=msedge`.
- Frontend production build passed. `npm audit` reports one moderate advisory for the already-declared Vite 6.4.4 dependency; this unrelated dependency update was left untouched.

## 2026-11-09 — Explicit no-usable-data acquisition state

- Added `analysis.InsufficientValidDataError` for the existing minimum of 32 valid positive backscatter pixels; the valid-data threshold and masking behavior are unchanged.
- Updated `_refresh_river` to persist that specific outcome as `no_data` and keep other acquisition or processing exceptions as `failed`. A scan reports no usable pixels only when every discovered candidate reaches the typed no-data outcome.
- Updated the dashboard's no-data label to say observations are unavailable in the mapped river corridor.
- Added analysis and acquisition regression tests, an API assertion for the returned no-data state/message, and a browser assertion for the no-data label.
- Verification: full backend suite 51 passed (one existing Starlette/httpx deprecation warning); production frontend build passed (existing 1.53 MB chunk advisory); Edge browser suite 2 passed; `pip check` and `git diff --check` passed.

## 2026-11-09 — Persistent acquisition and processing jobs

- Added the SQLite `acquisition_jobs` table and active-job partial unique index, with typed statuses, timestamps, stage, nullable measurable percentage, errors, output references, and retry parent.
- Added asynchronous worker paths for NISAR download, NISAR GCOV processing, and Sentinel-1 RTC acquisition. On startup queued jobs are dispatched and interrupted active jobs are marked failed with a safe-retry message.
- Added job submit/list/detail/retry/cancel API routes. Only queued jobs can be cancelled; only failed jobs can be retried. Active duplicate operations are rejected at the database constraint as well as validated through API errors.
- Hardened NISAR download promotion: isolate work in a temporary directory, check expected catalog size and required GCOV grid/polarization metadata, then atomically move into final storage. Existing files are not overwritten and incomplete staged files are cleaned.
- Added dashboard job stage/state/timestamps/error/output display and retry; exposed queue actions for NISAR download/processing and failed Sentinel-1 products. Progress stays stage-based during work rather than inventing a percent.
- Added persistent job, API, restart-recovery, no-data, retry, credential-redaction and safe-download tests; added a browser test for job failure details and retry.
- Verification: 57 backend tests passed (one existing Starlette/httpx deprecation warning), frontend production build passed (existing 1.53 MB chunk advisory), 3 Edge browser tests passed, `pip check` clean, `git diff --check` passed. Live API smoke check: health `ok`, acquisitions returned two rivers, jobs list returned empty, nonexistent job returned 404. No live job or download was submitted.
- Next: inspect existing/discoverable Sentinel-2 catalog records and verify actual pixel and SCL/cloud-mask access. No optical pixels have been inspected in this phase.

## 2026-11-09 — Sentinel-2 asset and pixel access verification

- Confirmed the local SQLite satellite catalog has no Sentinel-2 table or records, and no Sentinel-2 raster is stored locally.
- Queried Planetary Computer STAC for Tungabhadra (2026-11-05 through 2026-11-08): 11 intersecting L2A items. Five same-day tiles report 38.78%–50.29% tile cloud cover.
- Selected tile 43PGT (38.78% reported cloud cover); its STAC footprint intersects 124.15 km / 21.80% of the mapped centerline.
- Obtained the provider's temporary read-only SAS token without outputting or storing it. For 43PGT, bounded B04 (10 m uint16) and SCL (20 m uint8) COG windows were read; for adjacent same-acquisition tile 43PES, bounded B03/B04/B08 and SCL windows were read. Both tile grids use EPSG:32643. No full tile download or local imagery persistence occurred.
- Along 43PGT, a sampled 120×120 SCL window at 51.5 km had 14,400 valid pixels, 0.9% cloud/shadow/snow classes, and 1,205 class-6 water pixels. Other sampled locations were substantially cloudier, so pixel-level masking remains essential.
- This verifies access to actual optical and SCL pixels only. No optical mask, NISAR comparison, accuracy score, or validation was produced.
- Next: compare actual same-day cloud-screened coverage with the A_009 candidate-mask footprint before deciding whether a limited reference comparison is defensible.

## 2026-11-09 — Sentinel-2/NISAR common-support diagnostic

- Read bounded B03/B08 and SCL COG windows for Sentinel-2 tile 43PGT and compared them with the existing A_009 candidate mask on its 10 m EPSG:32643 grid; no full tile or optical output raster was downloaded or saved.
- The tile covers 124.153 km (21.796% of the mapped centerline) and 359.27 km² of corridor. Common valid support after NISAR validity, valid reflectance, and SCL classes 4/5/6 is 1,011,220 pixels (101.122 km²).
- On that support, NISAR candidates total 318,650 pixels; exploratory NDWI > 0 candidates total 69,498; 65,194 are positive in both. Descriptive simple agreement is 74.51%, IoU 20.19%; these are explicitly not accuracy or validation scores.
- Recorded the 4 h 54 min 51.025 sec acquisition-time offset, SCL 20 m to 10 m nearest-neighbor resampling, pixel counts, coverage and scientific limitations in `data/SENTINEL2-NISAR-COMPARISON-DIAGNOSTIC.md`.
- Updated `data/README.md` and the independent-optical section in `PROJECT-AUDIT.md`. No reference raster, API/UI layer, ground-truth labels, or scientific validation was created.
- Checklist is 40/60 (66.7%); only the reporting of acquisition-time difference, valid coverage and resampling is newly complete. Backend tests and frontend build were not rerun because this phase changed documentation only; previous verification remains 57 backend tests, 3 Edge tests and successful frontend build.
- Next at that checkpoint: decide whether to create a separately labeled, NoData-preserving optical candidate raster. The following phase below completed that work.

## 2026-11-09 — Persisted Sentinel-2 candidate and dashboard access

- Added `backend/app/services/optical_reference.py` for windowed reprojection, nearest-neighbor SCL resampling, clear-class masking, NDWI calculation, common-support handling, NoData preservation, and atomic output-directory creation. Existing output directories are never overwritten.
- Added `backend/scripts/create_sentinel2_candidate.py`, scoped to the already inspected Planetary Computer item and local A_009 NISAR candidate mask. It signs B03/B08/SCL assets in memory, does not print or persist SAS URLs, and reads only needed COG windows; it does not download full Sentinel-2 scenes.
- Created `data/acquisitions/tungabhadra/<A_009-product>/nisar-processing/sentinel2-reference/ndwi-candidate-mask.tif` and `processing-metadata.json`. Raster dimensions are 10,302 × 7,746 at 10 m in EPSG:32643; values 0/1/255 mean non-candidate/candidate/NoData. It has 1,011,220 common-valid pixels and 69,498 NDWI candidates (6,949,800 m²).
- Added safe API access to the metadata and candidate GeoTIFF; local NISAR processing metadata exposes the links only when both outputs exist. Dashboard UI fetches and labels the actual candidate results and displays limitations; the raster is downloadable. No scientific validation or ground truth is implied.
- Added regression tests for mask computation, SCL resampling, validity/NoData, existing-output safety, API access, cached catalog-link retention, and browser rendering.
- Verification: 61 backend tests passed (one existing Starlette/httpx deprecation warning); production frontend build passed (existing large-chunk advisory, ~1.54 MB JS); 4 Edge browser tests passed. Live API smoke check returned HTTP 200 for acquisition status, optical metadata (1,011,220 common-valid pixels), and GeoTIFF download (168,320 bytes).
- Remaining: map rendering/legend for the optical raster, explicit display of cloud/no-data/temporal-offset context, and any defensible independent validation.

## 2026-11-09 — Sentinel-2 candidate raster map preview

- Added a bounded-size PNG renderer for the existing NDWI GeoTIFF. It reprojects to WGS84, uses nearest-neighbor resampling, renders candidate/non-candidate/NoData distinctly, and rejects unexpected classes or invalid raster metadata. The existing GeoTIFF was not modified.
- Added a preview API route and enriched the existing optical metadata response with raster CRS, WGS84 bounds, dimensions, NoData value, preview URL, NISAR acquisition time, and exact acquisition-time offset. The measured 21.7962% centerline coverage is attached only to the matching Sentinel-2 tile.
- Added an independent Leaflet ImageOverlay toggle, map fit to raster bounds, loading/error states, class/NoData legend, and the explicit “EXPLORATORY SENTINEL-2 NDWI OUTPUT — NOT GROUND TRUTH.” warning. The panel displays catalog cloud cover when present. The overlay remains independent of and coexists with NISAR GeoJSON layers.
- Added backend tests for color classes, NoData, PNG output, geospatial metadata and API preview access; extended Edge browser coverage for metadata, preview visibility/removal, preservation of the NISAR layer, and preview failure messaging.
- Live A_009 API verification returned metadata HTTP 200 and PNG preview HTTP 200 (31,975 bytes). Metadata reports EPSG:32643, WGS84 bounds 76.862031–77.830303°E / 15.269866–15.979812°N, 1,011,220 common-valid pixels, 101.122 km² common-valid area, 21.7962% centerline coverage, and a 17,691.025-second acquisition offset.
- Verification: 64 backend tests passed (one existing Starlette/httpx deprecation warning); frontend build passed with the existing ~1.54 MB chunk-size advisory; all 4 Edge browser tests passed. No satellite product was downloaded; no NDWI or NISAR output was recalculated.
- Verified checklist is 43/60 (71.7%). Independent validation, candidate filtering evaluation, scientific width/change claims and the final completion report remain pending.

## Existing verified scientific-processing milestone

- Real Tungabhadra NISAR L2 UR GCOV A_009 (6,811,549,696 bytes) was downloaded and opened as HDF5.
- The windowed frequency-A HH/HV processor created an unvalidated candidate classification, while A_010 was correctly rejected for no valid corridor pixels.
- HH-only/HV-only/combined comparisons, five equal threshold offsets, 8-connected component diagnostics and downloadable GeoTIFFs were added in the preceding milestone.
- Actual results and limitations are documented in `data/NISAR-GCOV-SPATIAL-DIAGNOSTIC.md`.
- Sentinel-2 catalog metadata was discovered; no optical pixels or validation scores were generated.

## Working-tree note

Git reports the existing repository contents as untracked at the top level. Do not assume a clean tracked baseline and do not stage or commit files automatically.
