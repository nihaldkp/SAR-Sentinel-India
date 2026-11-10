# SAR Sentinel India — Architecture and Implementation Audit

**Audit date:** 2026-11-10

**Workspace:** `D:\SAR-Sentinel-India`

**Status:** Snapshot of the implemented application and verified data, not a claim of scientific validation or project completion.

## National platform checkpoint

The existing map now filters its already loaded pilot river choices; it still
loads complete GeoJSON geometries and is not suitable for national-scale
pagination. River processing and discovery remain constrained by static
`RIVER_CATALOG`. HydroRIVERS resolution and inclusion thresholds exclude
smaller features; NWIC source terms and schema need verification. No national
source or additional satellite imagery was acquired. The requested monitoring
modules and cross-module integrations remain incomplete.

## NISAR connection audit continuation

The existing A_009 candidate was corroborated against a bounded HDF5 sample
and displayed in the live dashboard. Public ASF metadata matched local IDs
and sizes. Authenticated retrieval and checksums were not tested. Recovery
infers statuses from local files, and structural HDF5 checks do not reject all
spoofed products. The new catalog-based status summary cannot establish current
connectivity or authentication; it does not persist per-attempt history.
See [NISAR audit](./data/NISAR-CONNECTION-AUDIT.md).

## Latest continuation — national coverage and calculation limits

The local river API returned two OSM records, not a national network; selector options are now catalog-driven but processing and schemas still have geographic restrictions. CWC source terms/coverage require verification, and HydroRIVERS thresholds exclude smaller features. No source was imported. SQLite-bound common-support calculation holds a local write transaction across processing, which can block other writers; it is not an evaluation or crash-safe report publication. Authentication, comprehensive security and scientific validation remain open. Backend 156 passed/1 skipped, mocked browser 17 passed. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — transactional reservation only

SQLite `BEGIN IMMEDIATE` serializes bounded reservation and withdrawal against each other; immutable input snapshots and events are preserved using database triggers. Separate-process reservation races and transactional event-write rollback were tested. This is local cooperating-process safety only: database/schema access bypasses application protections, no authentication exists, and path/symlink/junction and TOCTOU review remains incomplete. SQLite and legacy JSON reports are not atomic together. Windowed computation was separated from its legacy JSON write, but no bound evaluation, report-integrity recovery or supersession is implemented, so the requested stopping gate remains open. Focused 71 passed/1 skipped, backend 151 passed/1 skipped; no current live browser audit. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — identity check is not authorization

A bound-reference snapshot verifies declared selection fields, candidate/reference fingerprints, exact grid and recorded review state, and persists the result under the same local SQLite write lock as review transitions. Independent-process check/withdraw races are covered. This is not authenticated identity or independence, does not assess thresholds, and is not enforced by evaluation. A snapshot can become stale; the different report JSON store prevents claiming a single atomic end-to-end transaction. No authorization or complete file-security audit was added. Inputs remain limited to 2 million pixels; historical outputs are not superseded. No new real-data browser audit or scientific accuracy result occurred. Focused 34 passed, backend 145 passed/1 skipped, mocked browser 16 passed, build and dependency check passed; see [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — partial reference lifecycle

New API-only SQLite records preserve declared product/acquisition/version and input hashes with reference bytes and unauthenticated review history. They are not consumed by validation, AI or the UI, and there is no automatic stale/superseded policy. Review transitions use SQLite transactions; report evaluation/rejection uses a separate SQLite mutex and atomic JSON, tested across spawned processes. These are local cooperating-worker protections, not distributed locks or authorization. The broader file-serving/TOCTOU audit remains incomplete; the actual Windows symlink regression was skipped.

Actual local A_009 browser and acquisition-disabled API smoke succeeded; reference review tests used temporary databases and controlled rasters, not genuine labels. Focused 31 passed, backend 142 passed/1 skipped, mocked Playwright 16 passed, build and dependency check passed. Details: [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — security and live verification remain partial

Reference metadata and report listings previously read some files without verifying their final resolved target; those paths now reuse containment- and identifier-checked readers. Simulated external resolution was rejected; real symlink test skipped because this Windows account lacks symlink privilege. TOCTOU remains, and there is no authentication or per-user authorization: UUIDs are not access control. Cross-process transitions are not serialized. Do not treat this as a comprehensive file-security audit.

Real local browser checks verified A_009 candidate, A_010 NoData, Kaveri observations and pending validation; live API and a mask range request succeeded. Other requested live surfaces remain unverified. Evaluation failure/rejection is now persisted for supported paths, but full evidence lifecycle and attestation authentication remain incomplete. Tests: backend 133 passed/1 skipped, focused 53 passed/1 skipped, mocked browser 16 passed, build and dependency check passed; see [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — partial reviewed assessment and security audit

The new persisted no-resampling assessment supports identical grids in bounded windows and gates scores behind a separate evaluation. Input identities are fingerprinted; AI links NISAR reports only after matching the selected candidate hash and declared product/date/version. Attestations are not authenticated, and the complete nine-state evidence lifecycle is absent. Reference footprint beyond the recorded grid/support, partial overlap, cross-worker limits and Sentinel-1 version linkage remain incomplete.

Selected serving paths use resolved containment checks; file opens following checks leave TOCTOU considerations, and multiuser authorization/ownership and all consumers have not been comprehensively reviewed. No security-audit completion is claimed. In-process local API checks confirm 10/4 Sentinel-1 observations and A_009/A_010 candidate/no-data status; the current Playwright tests use mocks. Focused/backend/browser tests passed 48/128/16, targeted safety 3, build and dependency check passed. Details: [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## 2026-11-10 continuation — bounded comparison and data audit

- Full-size A_009 versus minimum-10-pixel mask was compared over 2,193 windows and 12,910,080 shared valid pixels; candidate-mask IoU 0.927026 is exploratory overlap, not accuracy. Pixel-aligned partial overlap with the actual Sentinel-2 43PFS mask was also exercised. Limits, shared-support and no-resampling details are in [README.md](./README.md); reviewed-reference comparisons remain subject to the two-million-pixel cap.
- A_010 has zero valid paired pixels across 5,213,075 corridor cells and no water area/mask, despite 33.26% geometric grid-centerline overlap. SQLite `quick_check` passed; 14 processed Sentinel-1 source rasters were inspected, and Sentinel-2 tile candidate areas are not additive because footprints overlap.
- Evidence status uses product/date-matched reports and reference attestations without authenticating them. No persisted workflow can establish a separate thresholds-met/awaiting-validation state or independently certified validation. Fixed WGS84 coordinate checks and selected resolved-file containment, but direct raster consumers, remaining paths and symlink/TOCTOU behavior still need review.
- Live local dashboard checks covered A_009, A_010 and deterministic AI status; browser regression responses remain fixtures. Verification: 29 focused validation, 11 AI, 60 combined focused, 120 backend and 16 Playwright tests passed; build and `pip check` passed. Five scientific checklist items and broader audit work remain open; see [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## In progress — real-data audit checkpoint

- Reviewed scores additionally require operator-declared minimum pixels and occupied square blocks for each class. Blocks are anchored at the candidate grid's top-left; occupancy does not demonstrate independence or representativeness. Older reports without these criteria have scores withheld without rewriting stored files.
- Both comparison modes now expose all pairwise candidate-area differences, disagreement and candidate-mask IoU on shared support. Undefined zero-denominator and zero-union cases are unavailable. These are exploratory overlap, not accuracy.
- A bounded in-memory A_009 crop was verified against its minimum-10-pixel sensitivity mask. The full A_009 mask was rejected at the two-million-pixel upload limit; a full-scene endpoint comparison remains unsupported.
- Saved changes passed 25 focused validation tests, 103 backend tests, 16 Playwright tests and the production build; `pip check` was clean. The Starlette/httpx warning and Vite chunk advisory remain. Audit work and scientific evidence gaps remain open; see [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest update — evidence gates and exploratory method comparison

- Reviewed scores require independent-review attestation, common support containing both reference classes, and operator-declared minimum shared pixels and coverage. Validation coverage uses candidate-valid pixels as denominator; reviewed method coverage uses reference-valid pixels on the candidate grid. Thresholds do not establish representativeness.
- Insufficient reports no longer imply overall completion. Historical reports lacking qualifying thresholds are served without accuracy metrics; their persisted files are not changed. Reviewed method reports retain submitted reference metadata, and the reference must declare 255 NoData.
- Candidate-only exploratory method comparison reports shared-grid coverage, per-method candidate area and differing area relative to the first method, without reference scores or winner; reviewed comparisons provide the same area diagnostics on reference-common support. The Analysis workspace links to the existing form.
- Focused validation 18 passed; full backend 96 passed with one Starlette/httpx warning; Playwright 16 passed; build passed with a 1,596.74 kB chunk advisory. No independent labels, scientific scores or verified width outputs were produced. The five evidence-dependent checklist items remain open.

## Latest update — Reference-data, evaluation, and river-axis audit

- Checklist remains **64/69 (92.8%)**; the five unchecked criteria remain evidence-dependent. The reference catalog/import UI and shared-support method-evaluation endpoint are preparation workflows, not evidence that labels or a superior classifier exist.
- The river-axis sampling workflow is integrated in the Analysis dashboard. A public-source check found the CWC/NWIC national river-line GeoJSON advertises a 356,234,820-byte download; it was not fetched. Its target feature/CRS and active-channel fit remain unverified; generalized HydroRIVERS, historical GRWL widths, and the Bhuvan WBIS technical document are not substitutes for event-date labels or channel-bank evidence.
- Reference rasters are limited to 100 MB and two million pixels, must be one-band 0/1/255 GeoTIFFs with 255 declared NoData, projected metre CRS matching declared provenance, and a resolution matching the metadata within 5%. Reference IDs are UUID-normalized and resolved within the configured directory. Operator review/source identity is not authenticated.
- Method comparisons accept two through eight masks, enforce exact candidate grid identity and 255 NoData, and use the same common-valid pixels for all candidates. Both reference classes must exist in the shared support before metrics are produced. Warnings prohibit automatic winner selection or generalization claims.
- Axis sampling is bounded to 250 stations and 2,000 sample positions per transect. It requires a supplied LineString fully contained by a supplied Polygon/MultiPolygon, transforms from WGS84 to the candidate raster CRS, limits measurements to the supplied corridor, preserves corridor gaps when evaluating candidate segments, and reports valid/raster coverage and quality flags. Axis provenance remains unauthenticated, OSM is not used as a trusted channel axis, and uncertainty is explicitly not quantified.
- Regression suite: **88 backend passed** (one existing Starlette/httpx deprecation warning); **15 Playwright passed**; production build passed with a 1,593.08 kB main-JavaScript chunk advisory; project-venv `pip check` clean. Fifteen acquisition-disabled smoke requests returned HTTP 200 for core APIs, reference data, both deterministic AI summaries and both temporal-pair endpoints.
- No independent labels, validation metrics, alternative-method results, or verified width outputs were produced. Automatic acquisition remained disabled; no source satellite assets changed. Git reports project contents as untracked, so tracked diff checks do not cover the full workspace.

## Previous update — Compatible Sentinel-1 candidate comparisons and final verification

- Implemented exact-grid temporal candidate-pair discovery and comparison, a dashboard selection/result view, provenance-bearing comparison outputs, and a narrow recovery for persisted S1 results marked failed by a known legacy response-schema error. Recovery verifies result/mask identity and metadata before changing catalog status.
- Live catalog checks found five Kaveri and one Tungabhadra compatible pairs. Both rivers' actual comparison mask and PDF download endpoints returned HTTP 200. Results report 436,083 common-valid pixels for the exercised Kaveri pair and 418,128 for Tungabhadra, while keeping gain/loss explicitly unvalidated.
- Full local verification passed: 77 backend tests (one existing Starlette/httpx deprecation warning), 11 Playwright tests, production build, and `pip check`. The build retains the Vite advisory for the 1,569.99 kB main JavaScript chunk.
- Smoke checks returned HTTP 200 for acquisition status, temporal-pair listing and deterministic AI Analysis against the local catalog; AI summary reported five Kaveri and one Tungabhadra compatible pairs. Automatic acquisition was explicitly disabled; no job was submitted.
- The workspace contains real satellite candidate products, but no independent reference labels or validation metrics. Compatible raster candidates permit exploratory comparisons only; their grid identity does not prove accurate co-registration or scientific change. The OSM centerline and absent bank geometry do not support verified automated width.
- `FINAL_PROJECT_COMPLETION_REPORT.md` documents implementation, real data status, outcomes, setup, and remaining scientific dependencies. Checklist count is 61/69 (88.4%); this is not a scientific completion percentage.
- Git status reports the workspace content as untracked, so no complete tracked diff is available. No files were staged or committed.

## Latest update — Component-size candidate sensitivity

- Added an opt-in NISAR component-size sensitivity workflow with bounded request schemas, tiled component labeling, separate output masks, fixed allowlisted downloads, metadata/provenance, and explicit quality flags. Existing product/catalog and source-mask paths are resolved before processing; outputs refuse overwrite.
- The dashboard exposes 2/5/10-pixel scenarios and their separately stored GeoTIFFs. The default candidate classification remains unfiltered. No component is asserted to be speckle, and no scientific cleanup threshold is selected.
- Real Tungabhadra A_009 outputs match their metadata: all are 25,660 × 21,962, EPSG:32643, 10 m, NoData 255, and each retains 550,634,840 NoData cells. Candidate pixels reclassified by the size rule are 89,437 / 202,003 / 283,567. The original mask was read-only.
- Validation: 79 backend tests passed (one existing Starlette/httpx deprecation warning), 12 Playwright tests passed, production build passed with the Vite 1,572.54 kB chunk advisory, and `pip check` passed. Core API and all sensitivity metadata/GeoTIFF routes returned HTTP 200 with automatic scheduling disabled.
- Checklist count is **64/69 (92.8%)**. The three Phase 5 workflow/evaluation items are complete as exploratory software deliverables. Independent validation/labels, an independently justified alternate classifier, and axis/width measurement remain blocked by missing evidence and geometry.
- Workspace remains untracked in Git; `git diff --check` alone does not cover untracked files. No files were staged or committed.

## 2026-11-09 update — AI provenance and selection audit

- The AI summary API is an explicitly deterministic function of the selected river's persisted acquisition catalog. No environment setting, dependency, API client, or configured LLM provider is present; therefore there is no provider fallback path to test.
- Product options now include available acquisition bounds, source/provider, product type, polarization, processing CRS and pixel size. Sentinel-1 provenance uses the STAC item URL and license; signed asset URLs and local paths are not included.
- The UI displays selected product provenance, hides stale metrics when selection changes until rerun, synchronizes a selected ASF discovery observation with the dashboard river, and only analyzes that observation if it exists in the persisted product catalog. Search-only metadata is clearly shown as unprocessed and does not generate metrics.
- The selected satellite footprint and candidate polygon overlay now have dynamic legend caveats. Browser regression verifies discovery-only behavior and map river synchronization.
- The new comparison workflow reports only exact-grid compatible candidate pairs and creates explicitly unvalidated outputs; scientific interpretation remains blocked by missing reference labels, seasonal analysis and co-registration-error evidence.
- A read-only connected-component review of the real A_009 candidate mask (25,660 × 21,962; EPSG:32643; 10 m; NoData 255) found 160,502 eight-connected candidate components. A 2-pixel minimum would remove 89,437 candidate pixels; a 100-pixel minimum would remove 634,217. These are parameter sensitivity diagnostics only. No filtered raster was written because there are no independent labels to justify classifying small components as noise.

## 2026-11-09 update — Independent-validation workflow

- Added `backend/app/schemas/validation.py`, `backend/app/services/validation.py`, and status, upload, and report routes in `backend/app/api/routes.py`.
- The service validates single-band 0/1/255 rasters, requires declared 255 NoData and a projected metre candidate grid, bounds uploads/pixel counts, resamples reference labels to candidate support with nearest-neighbour, and computes metrics only on common valid pixels when both reference classes exist. Insufficient overlap or class diversity is explicit.
- Provenance-bearing JSON reports are written atomically under `outputs/validation/`; uploaded raster bytes are not retained. The API does not authenticate reviewer claims or verify source independence, label quality, or sampling design.
- `frontend/src/components/ValidationWorkspace.jsx` adds an explicit no-labels-pending state, provenance/file form, loading/error handling, metrics and saved-report links, and warnings that NDWI is not independent reference data. `App.jsx`, `services/api.js`, `styles.css`, and the Playwright suite integrate and verify it.
- The browser's completed-result scenario uses a test-only API fixture; no real reviewed reference labels or project validation scores exist. Scientific validation remains blocked pending suitable independent labels.
- Latest verification for this update: 75 backend tests passed (one existing Starlette/httpx deprecation warning); 9 Playwright browser tests passed; production build passed with a 1,562.53 kB main-JS chunk advisory. No satellite product was downloaded and no acquisition job was submitted.
- Bounded file-serving review found fixed NISAR/analysis output names, catalog-based product resolution, resolved containment checks for optical per-tile outputs, UUID validation for validation report IDs, and missing-output 404 behavior. Existing UI tests exercise optional bank-layer availability, optical preview errors/removal and validation pending/error/report states. No additional path or map-layer defect was found in this bounded pass.
- Automated river-axis sampling remains deferred: the OSM centerline is a mapped reference line rather than an independently verified active-channel axis, and no left/right bank datasets are available. Generating normal transects from it would create geometry-based assumptions and cannot produce verified bank-to-bank widths. The existing manual transect service is explicitly an unvalidated candidate-water segment estimate.

## Executive summary

SAR Sentinel India is an existing React/Vite dashboard backed by a FastAPI service. It combines illustrative overview content, OSM-sourced Kaveri and Tungabhadra centerlines, ASF catalog discovery, automatic Sentinel-1 RTC acquisition, a product-specific NISAR GCOV processor, and an operator-uploaded GeoTIFF analysis workflow.

The project has successfully processed one genuine Tungabhadra NISAR L2 UR GCOV product into a **candidate** water classification. It has not independently validated that classification or implemented verified riverbank extraction, flood detection, erosion/deposition assessment, or riverbank-change measurement. The demonstrated map circles, overview metrics, and date scenarios remain explicitly labeled as simulated.

## 2026-11-09 update — Deterministic AI Analysis

- `backend/app/api/routes.py` now exposes `POST /api/analysis/ai-summary`, with typed contracts in `backend/app/schemas/ai_analysis.py` and catalog-based calculations in `backend/app/services/ai_analysis.py`.
- The endpoint reads existing persisted NISAR and Sentinel-1 catalog results and linked Sentinel-2 NDWI metadata. It reports centerline/valid support, candidate pixels and area, NISAR polarization and threshold diagnostics, optical time/support context, and temporal-comparison eligibility.
- This is deterministic local rule-based output, not an external LLM. No accuracy metric or scientific change product is generated. The API explicitly preserves no-data versus failed states and labels available classifications as unvalidated candidates.
- `frontend/src/components/AIAnalysisPanel.jsx` adds river/product selection, status and error handling, candidate metrics, limitations and safe next steps. `App.jsx`, `api.js`, `styles.css`, and the Playwright suite integrate and verify it.
- Current verification for this update: 68 backend tests passed; production build passed with a 1,552.51 kB JavaScript chunk advisory; 7 Microsoft Edge browser tests passed. An acquisition-disabled API smoke test returned HTTP 200 against the real local catalog and selected NISAR A_009. Existing Starlette/httpx deprecation warning remains.

## 2026-11-09 update — Additional Sentinel-2 tile candidates

- `backend/scripts/inspect_sentinel2_coverage.py` screens STAC items without signing assets and measures item-footprint centerline overlap plus existing NISAR-valid pixels below each footprint. It does not claim optical clear-pixel support.
- Four same-overpass 2026-11-06 tiles (43PER, 43PES, 43PFS, 43PFT) now have separate exploratory candidate masks under `nisar-processing/sentinel2-observations/`. The script only allows the baseline item and these screened adjacent tiles, spaces signing requests, avoids retrying 429 responses, and does not persist signed URLs.
- Processing metadata reports 788,166 common-valid pixels for 43PER, 1,630,335 for 43PES, 1,972,759 for 43PFS, and 1,266,000 for 43PFT. Per-tile support overlaps; do not sum it as unique coverage. Candidate masks use NDWI > 0 and are explicitly unvalidated.
- The existing metadata endpoint now includes available additional observations. New per-tile preview and mask routes are consumed by `AutomaticAcquisitionPanel.jsx`, where each tile has independent map visibility and download controls. Existing NISAR layers and the 43PGT output remain separate.
- Automatic acquisition is explicitly opt-in: unset `SAR_AUTO_ACQUISITION_ENABLED` means no scheduler.
- Final verification for this continuation: 71 backend tests passed (one existing Starlette/httpx deprecation warning); all 7 Microsoft Edge tests passed; production build passed with a 1,554.55 kB main-JS advisory; `pip check` and `git diff --check` passed. Live metadata, PNG preview and GeoTIFF routes returned HTTP 200 for all four saved tiles. Windowed raster counts matched metadata and preserved 255 NoData. Checklist is 53/67 (79.1%).

## Stored temporal-output compatibility check

- Read-only Rasterio inspection covered three processed Sentinel-1 candidate masks per river via the persisted analysis registry. All are 1,200 × 1,200; all Kaveri masks have distinct EPSG:32643 transforms, while Tungabhadra has distinct transforms across two EPSG:32643 masks and one EPSG:32644 mask. The stored thresholds differ.
- No current same-river pair meets the comparison service's exact CRS, affine transform, and dimension requirement. No change analysis was run, no reprojection/resampling was performed, and no new raster was created. Candidate differences must not be interpreted as physical change.
- Existing download links are conditional on real result URLs; NISAR and Sentinel-2 A_009 outputs are locally present and linked.
- Completion checklist at this inspection: 49/64 (76.6%). Same-grid temporal comparison from compatible actual acquisitions remains pending.

## Repository structure

### Backend

- `backend/app/main.py` creates the FastAPI application, registers CORS for local development origins, includes the `/api` router, and starts/stops the optional automatic acquisition loop through the application lifespan.
- `backend/app/api/routes.py` defines API endpoints and validates request metadata and file uploads.
- `backend/app/schemas/` contains Pydantic response/request contracts for the catalog, rivers, satellite searches, acquisition records, and analysis results.
- `backend/app/services/catalog.py` contains static demonstration regions and observations.
- `backend/app/services/rivers.py` loads and validates the separate GeoJSON river catalog.
- `backend/app/services/satellite.py` searches ASF metadata, then intersects returned product footprints with a projected 1,500 m buffer around a river centerline.
- `backend/app/services/acquisitions.py` manages ASF authentication/search, Sentinel-1 RTC reads, SQLite catalog persistence, NISAR local-product recovery, and acquisition lifecycle.
- `backend/app/services/nisar_gcov.py` is the product-specific, windowed NISAR L2 GCOV processor.
- `backend/app/services/analysis.py` processes operator-supplied GeoTIFFs, produces candidate masks, compares compatible masks, samples user-drawn transects, and writes reports.
- `backend/app/services/validation.py` compares user-submitted independent-reference labels on common valid raster support and persists provenance-bearing JSON reports.
- `backend/tests/` contains backend API, acquisition, satellite-search, analysis, and NISAR fixture tests.

### Frontend

- `frontend/src/App.jsx` owns the dashboard shell, river selection, Leaflet map, demonstration layers, and map-layer state.
- `frontend/src/components/SatelliteSearchPanel.jsx` searches satellite metadata without downloading or processing products.
- `frontend/src/components/AutomaticAcquisitionPanel.jsx` displays automatic acquisition state and separates NISAR results from Sentinel-1 RTC observations.
- `frontend/src/components/AnalysisWorkspace.jsx` accepts operator-prepared GeoTIFFs and presents candidate analysis, comparison, and width workflows.
- `frontend/src/components/ValidationWorkspace.jsx` submits independently reviewed mask labels and displays pending status, errors, provenance, and per-report metrics/caveats.
- `frontend/src/services/api.js` wraps API requests, abort handling, response validation, and error messages.
- `frontend/src/styles.css` provides the dashboard and responsive component styling.
- `frontend/package.json` defines Vite development, production-build, and Playwright end-to-end test scripts.

### Data and generated outputs

- `backend/app/data/rivers.geojson` stores river feature geometry and source/provenance metadata.
- `data/acquisitions/` stores local Sentinel-1 clipped RTC subsets and downloaded NISAR HDF5 products plus processing outputs.
- `data/satellite_catalog.sqlite3` persists acquisition scan/product metadata.
- `outputs/analysis/` stores manual GeoTIFF workflow results and reports.
- Repository-root `.env` is ignored by Git; it must not be committed or printed.

## Geographic river data and map

The river catalog contains OSM/Nominatim relation geometries for Kaveri (relation 2704746) and Tungabhadra (relation 2742213). The data records source URLs, retrieval date, and ODbL attribution. These are community-mapped reference **centerlines**, not independently surveyed channel edges. The Tungabhadra relation carries a source `fixme` note.

The river API returns geography and provenance independently of application logic. Both left- and right-bank geometries are currently unavailable and represented as `null`; the frontend disables those layer controls. No bank lines are inferred from the centerlines.

The existing Leaflet map remains in use. The river selector supports both rivers or either single river, fits the map to visible geometry, and the active legend follows the visible river. Selecting another river clears stale satellite/analysis overlays. In Both Rivers mode the information panel summarizes both rivers. Demonstration area outlines, simulated radar footprints, candidate circles, overview metrics, and scenarios remain illustrative rather than satellite observations.

## Frontend-to-backend data flow

1. `api.js` fetches health/demo catalog data and river features from FastAPI.
2. The dashboard renders the static demonstration overview separately from the actual acquisition panel.
3. Satellite search requests query ASF metadata. Results can be selected on the map, but the search panel itself does not download data.
4. The automatic acquisition panel polls `/api/acquisitions`, can request an explicit catalog refresh when enabled, and can request processing of an already downloaded NISAR product.
5. Uploaded GeoTIFFs are submitted to `/api/analysis/water-mask`; resulting GeoJSON can be overlaid on the map and result files downloaded.
6. API/network errors are surfaced in the relevant component; loading states and cancellation are used for catalog requests.

## API inventory

| Endpoint | Purpose and data mode |
|---|---|
| `GET /api/health` | Health response; deliberately reports demonstration mode. |
| `GET /api/regions` | Static, simulated overview regions. |
| `GET /api/observations` | Static, synthetic demonstration observations, optionally filtered by region. |
| `GET /api/rivers` | OSM river metadata and centerline GeoJSON-derived geometry. |
| `GET /api/rivers/{river_id}` | Single river record; unknown IDs return 404. |
| `GET /api/satellite/search` | ASF metadata search for NISAR or Sentinel-1 product types; no download or processing. |
| `GET /api/acquisitions` | Persisted Sentinel-1/NISAR catalog and processing state, including recovered local NISAR records. |
| `POST /api/acquisitions/refresh` | Manual acquisition/catalog refresh; returns 503 when automatic acquisition is disabled. |
| `GET /api/acquisitions/{river_id}/{product_id}/raster` | Downloads an acquired Sentinel-1 corridor raster. |
| `GET /api/acquisitions/nisar/{product_id}/download` | Downloads a locally verified HDF5 product. |
| `POST /api/acquisitions/nisar/{product_id}/process?river_id=...` | Processes a previously downloaded NISAR product. |
| `GET /api/acquisitions/nisar/{product_id}/processing?river_id=...` | Returns NISAR processing metadata. |
| `GET /api/acquisitions/nisar/{product_id}/processing/{mask,measurements,polygons,comparison,sensitivity}` | Downloads NISAR rasters or display GeoJSON. |
| `GET /api/acquisitions/nisar/{product_id}/processing/sentinel2-reference?river_id=...` | Returns explicitly unvalidated Sentinel-2 NDWI candidate metadata when available. |
| `GET /api/acquisitions/nisar/{product_id}/processing/sentinel2-reference/preview?river_id=...` | Serves a WGS84 PNG map preview with candidate, non-candidate and NoData classes distinguished. |
| `GET /api/acquisitions/nisar/{product_id}/processing/sentinel2-reference/mask?river_id=...` | Downloads the NoData-preserving optical candidate GeoTIFF. |
| `GET /api/acquisitions/nisar/{product_id}/processing/sentinel2-observations/{observation_id}/{preview,mask}?river_id=...` | Serves a per-tile additional exploratory preview or NoData-preserving candidate GeoTIFF. |
| `GET /api/analysis/status` | Reports GeoTIFF processing availability and requirements. |
| `POST /api/analysis/water-mask` | Accepts a calibrated, geocoded single-band GeoTIFF and explicit metadata. |
| `POST /api/analysis/change` | Compares compatible, chronological, same-river analysis masks on identical grids. |
| `POST /api/analysis/width` | Samples candidate-water segments along a user-supplied transect. |
| `GET /api/analysis/{analysis_id}` | Returns a saved analysis result. |
| `GET /api/analysis/{analysis_id}/{mask,polygons,report}` | Downloads analysis output files. |

Analysis uploads are limited to 100 MB and 2,000,000 pixels. Raster inputs must have one band, a projected metre-based CRS, and operator-confirmed calibration and terrain correction. Result access validates UUID analysis IDs and restricts output names to files listed in the stored result.

## Satellite discovery and acquisition

### ASF catalog search

Searches initially use a river-centerline bounding box for catalog retrieval. Returned product geometries are then transformed to a local azimuthal-equidistant metre-based CRS and intersected with a 1,500 m centerline buffer. Matching products are ranked by overlap area. The service requests up to five times the requested count (maximum 100) to reduce the chance that coarse bounding-box matches crowd out true corridor-overlapping scenes. This improves geometric screening; it does not certify product suitability or valid pixel coverage.

The same exact corridor-overlap filter is used by automatic authenticated and unauthenticated NISAR discovery.

### Automatic Sentinel-1 fallback

Automatic acquisition scheduling is now **opt-in**: `SAR_AUTO_ACQUISITION_ENABLED` defaults to false. Only when explicitly set to true does the application perform an initial background catalog refresh at startup and repeat at a configurable polling interval. The service requests the official Microsoft Planetary Computer read-only token, reads a local window from a Sentinel-1 RTC COG, and clips it to a 1,500 m centerline corridor. The provider has already performed radiometric calibration and terrain correction; the app does not process raw Sentinel-1 GRD.

The NISAR search is attempted first. When Earthdata authentication is unavailable, the service reports the condition and retains the Sentinel-1 fallback. A 5×5 Lee-style local-statistic filter and Otsu threshold are used for Sentinel-1 **candidate** open-water masks. Failed/empty-valid-data scenes must remain failures or no-data; validity criteria must not be relaxed to force output.

### NISAR GCOV processing

The separate processor reads actual frequency-A `HHHH`, `HVHV`, `mask`, `xCoordinates`, `yCoordinates`, spacing, and projection datasets from the HDF5 product. It processes windows rather than loading the full product into memory and preserves invalid/out-of-corridor pixels as NoData.

The current classification is:

1. Convert linear power to dB using `10 * log10(max(power, 1e-6))`.
2. Estimate independent HH and HV Otsu thresholds using 900 histogram bins from −60 to +30 dB.
3. Label a pixel as a combined candidate only where `HH_dB <= HH_threshold` **and** `HV_dB <= HV_threshold`, among valid paired pixels in the rasterized corridor.
4. Compare HH-only, HV-only and combined candidates on the same valid pixels. Recompute candidates with both thresholds shifted together by −2, −1, 0, +1 and +2 dB. These are sensitivity scenarios, not confidence intervals.
5. Report 8-connected component diagnostics without despeckling or removing components.

The complete mask is a GeoTIFF. Display GeoJSON is simplified, omits components smaller than three pixels, and is capped at 5,000 features; that cap does not truncate the raster.

## Actual products and measured results

### Tungabhadra NISAR

- A real A_009 NISAR L2 UR GCOV product (6,811,549,696 bytes) was downloaded, opened as HDF5, processed, and registered locally.
- Its frequency-A grid is EPSG:32643 at 10 m. The existing processing metadata reports 15,356,387 corridor pixels, 12,910,080 valid paired HH/HV pixels (84.0698%), and 3,885,882 combined candidate pixels, or 388.5882 km².
- The stored exploratory thresholds are HH −11.75 dB and HV −19.05 dB. The ±1 dB area sensitivity range is approximately 327.5272–459.9289 km².
- The result is a single-date **unvalidated candidate classification**. No reference labels, confusion matrix, accuracy score, statistical confidence, or independently validated bank/water geometry are available.
- A second real A_010 product (6,618,611,712 bytes) has no valid paired pixels in the mapped river corridor. It correctly has no candidate mask or candidate water area.

### Kaveri Sentinel-1 failure diagnosis

The latest failed item is `S1D_IW_GRDH_1SDV_20261107T004804_20261107T004835_005354_00A33B_rtc`. The ASF/STAC footprint bounds intersect the mapped river and catalog coverage is 22.0352% of the full centerline. The 1,200×1,200, 10 m EPSG:32643 crop contains 22,758.1 m of reference centerline and 459,523 rasterized corridor cells. However, the saved crop has 1,440,000 NoData cells, zero valid mask pixels, and zero finite-positive backscatter values. The code correctly refuses to classify it. The original COG mask was not separately re-read, so the precise upstream source of the missing observations is unresolved.

### Independent optical reference

Sentinel-2 L2A metadata and bounded real pixels have been inspected for Tungabhadra. Tile 43PGT (2026-11-06 05:20:11 UTC; catalog cloud cover 38.78%) intersects 124.15 km (21.80%) of the mapped centerline. B03/B08 reflectance and the 20 m SCL layer were read from remote COG windows; SCL was nearest-neighbor resampled to the existing 10 m NISAR grid. On the tile/corridor intersection, 1,011,220 pixels (101.122 km²) were common-valid after NISAR validity, SCL classes 4/5/6, and reflectance NoData screening. A separate 10 m EPSG:32643 NDWI > 0 optical candidate raster contains 69,498 candidates (6.9498 km²) on that support. Four additional same-overpass tiles now have separate candidate outputs and independent UI controls: 43PER (788,166 common-valid; 28,194 candidate pixels), 43PES (1,630,335; 122,670), 43PFS (1,972,759; 931,867), and 43PFT (1,266,000; 32,019). These per-tile supports overlap and must not be added as unique coverage. The dashboard uses distinct candidate/non-candidate/NoData colors, cloud and acquisition metadata, per-tile map controls, and a visible not-ground-truth warning. The existing descriptive agreement (74.51% simple agreement and 20.19% IoU) compares two unvalidated candidate methods only; it is not accuracy or independent validation. The optical threshold is unvalidated, SCL is not ground truth, the observations are 4 h 54 min apart, and coverage remains partial. Full counts and caveats are in `data/SENTINEL2-NISAR-COMPARISON-DIAGNOSTIC.md`.

An independent-reference investigation screened Landsat Collection 2, JRC Global Surface Water through 2024, ESA WorldCover 2021, GRWL, CWC/NWIC discharge, and NRSC/Bhuvan WBIS. The closest Landsat 9 scene to Tungabhadra A_009 is 67 h 15 min earlier and reports 86.63% scene cloud cover. A bounded 40×40 window centered at EPSG:32643 (718740 E, 1753830 N; grid-snapped bounds 718125–719325 E, 1753245–1754445 N) contained 955 common-support cells, of which 465 passed QA_PIXEL bits 0–5, relevant QA_RADSAT bits, valid band masks, and nonzero reflectance checks. These cells were clustered in 8/16 sub-blocks; the false-color view showed no unambiguous channel/bank boundary at 30 m. No labels/template were created. Clearer scenes are about 10–12 days earlier. Eight Landsat scene footprints intersect the Kaveri centerline, but no Kaveri product-support overlap was computed. These results identify a possible source for future limited manual labels, not ground truth or validation. Details and limitations are in `data/INDEPENDENT-VALIDATION-INVESTIGATION.md`.

## Security, reliability, and performance notes

- Earthdata credentials are loaded from the process environment or ignored root `.env`; credentials are not included in the documented API responses or project source.
- The UI polls acquisition status; job lifecycle state is persisted in SQLite and worker execution is managed by the backend process. Interrupted jobs are marked failed for safe retry at restart.
- The local NISAR recovery path reads existing HDF5/processing metadata so empty catalog refreshes do not erase downloaded products. The API explicitly labels locally recovered records when a remote scan reports no new data.
- CORS allows local development origins only. Upload size and raster pixel limits are enforced server-side.
- A backend test warning remains: Starlette's `TestClient` integration reports an `httpx` deprecation warning.
- The frontend production build passes but emits Vite's advisory that the main JavaScript chunk is approximately 1.53 MB (above the 500 kB threshold).
- Playwright browser regressions cover river selection/legend alignment, centerline visibility, unavailable bank controls, persistent-job retry UI, AI Analysis states, and Sentinel-2 tile selection/removal. Microsoft Edge is used because bundled Chromium failed to launch on this Windows host (`spawn UNKNOWN`).
- `npm audit` reports one moderate advisory for the existing Vite 6.4.4 dependency, with a fix available. No high or critical advisory was reported; this unrelated dependency update was not included in the test implementation.
- The root Git worktree currently reports project content as untracked. No files have been staged or committed as part of this audit.

## Historical verification snapshot — before validation and temporal-pair milestones

- Backend: `python -m pytest` — **71 passed**, one Starlette/httpx deprecation warning.
- Frontend: `npm run build` — **passed**, main-JavaScript chunk is 1,554.55 kB (Vite advisory above 500 kB).
- Dependencies: `python -m pip check` — no broken requirements.
- Live API, with automatic acquisition disabled: A_009 Sentinel-2 metadata and the four additional tile previews/masks returned HTTP 200. The additional tile GeoTIFFs were streamed locally to verify EPSG:32643, 255 NoData and class counts against metadata. No complete source scene was downloaded and no acquisition job was submitted.
- Whitespace: `git diff --check` — passed.
- Browser regression suite: `PLAYWRIGHT_CHANNEL=msedge npm run test:e2e` — **7 passed**.
- Checklist: **53/67 (79.1%)**. Automatic acquisition is disabled unless explicitly enabled; its default is covered by a regression test.

## Remaining work and limits

1. The bounded file-serving, error-state, optional-layer and map-legend audits are complete for the reviewed surfaces; continue regression checks if those surfaces change.
2. Obtain independent, date-compatible, human-reviewed water labels before computing confusion matrices or accuracy metrics; the available Landsat patch is too ambiguous and no other reviewed labels are available.
3. Implement candidate cleanup only as a separate, reproducible output with retained original mask, NoData and quality flags, and only when independent evidence justifies parameters.
4. Add river-axis sampling and quality/coverage reporting only with trustworthy channel-axis/bank inputs; do not call candidate-water segments verified bank width.
5. Candidate temporal comparisons are available for six exact-grid Sentinel-1 pairs, but independent validation, co-registration-error assessment, seasonal normalization and interpretation as hydrological change remain unavailable. The available NISAR candidate is still single-date.
6. Preserve explicit limits on floods, erosion/deposition, verified banks and scientific change until suitable methods and independent evidence exist.
7. `FINAL_PROJECT_COMPLETION_REPORT.md` is current as of the latest verified continuation and should be updated if implementation or test results change.
