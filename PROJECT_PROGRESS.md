# SAR Sentinel India — Project Progress

**Last updated:** 2026-11-10

**Current stage:** Reference-source discovery/import, common-support method evaluation, and guarded candidate-axis sampling are integrated in the dashboard. Independent labels, an empirically justified alternate method, verified channel-axis/bank geometry, and quantified width uncertainty remain unavailable.

**Verified checklist completion:** 64 of 69 items (92.8%). This counts checked deliverables only and does not indicate scientific validation or overall product readiness.

## Source verification and snapshot review — partial

CWC metadata and the general NWIC copyright policy were checked; release
version, identifier stability, exact coverage, dataset-specific conditions
and full-source CRS/schema remain unresolved. Snapshot staging now preserves
history, supports restart and paginated provisional comparisons, and does not
alter the active catalogue. A cross-process interruption test and an isolated
genuine Balijan sample passed; there is no second real source version.
National dataset acquisition, import and acceptance remain incomplete.
Reviewed identity decisions and atomic catalogue publication/rollback are not
implemented. Focused backend: 20 passed; mocked river Playwright: 21 passed;
build passed with a chunk-size warning. See [handoff](./PROJECT_HANDOFF.md).

## NWIC explorer continuation — incomplete national phase

The SQLite-backed NWIC feature explorer supports paginated filters and
on-demand map geometry, separate from pilot monitoring controls. A genuine
bounded Balijan extract was imported only into an isolated session database
and verified through the real API and browser; no national project dataset
was imported. The importer refuses different input fingerprints pending safe
version reconciliation. Focused backend tests: 17 passed; mocked river
Playwright: 21 passed; production build passed with a chunk-size warning.
Dataset-specific rights, national import, scalable updates, aliases, topology
and generalized monitoring remain open. See [handoff](./PROJECT_HANDOFF.md).
The older prototype section below describes its earlier state.

## NWIC importer prototype

Bounded NWIC metadata/KML inspection identified real source attributes and a
projected-coordinate hazard in its GeoJSON. A resumable local KML importer
prototype was tested with fixtures and one genuine extracted source feature in
an isolated session database. No national dataset was imported into the
project, and the API/map remain pilot-only. Source terms, version updates,
concurrency, scalable search and real-data integration remain incomplete.
Focused importer/pilot API tests: 15 passed. See [handoff](./PROJECT_HANDOFF.md).

## National platform checkpoint

The existing map selector can now search the two pilot records, preserving the
selected map when filtered. This is client-side, not national, paginated or
database-backed. Real local API/browser smoke passed; 19 mocked Playwright
tests, 12 backend API tests and the build passed. No source was imported.
Agriculture, forest, earthquake, InSAR and combined monitoring remain
incomplete; see [handoff](./PROJECT_HANDOFF.md) for phase 1 continuation.

## Latest continuation — NISAR connection audit

Existing A_009 NISAR GCOV candidate is visible on the real dashboard; provider
search and a bounded HDF5-to-output comparison corroborate provenance. File
checksum, fresh authenticated retrieval and independent accuracy remain
unverified. A catalog-derived diagnostic explicitly reports unknown live
connectivity/authentication rather than inferring success from cached files.
See [audit](./data/NISAR-CONNECTION-AUDIT.md). Backend 159 passed/1 skipped;
focused validation 41 passed/1 skipped; mocked Playwright 18 passed; build
passed. The prior temporal-separation display adds provenance, not validation.

## Latest continuation — national coverage not yet available

The map selector now reflects the API catalog, but the catalog still contains only two OSM study rivers; searchable national data, general processing and coverage counts are not implemented. A separate bound common-support calculation now persists in SQLite without publishing accuracy metrics or reports; full bound evaluation and recovery remain incomplete. Backend 156 passed/1 skipped, mocked Playwright 17 passed, build passed. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — transactional reservation foundation

Added SQLite-backed exact-identity, attestation and raster-snapshot reservations, append-only transition history and atomic withdrawal rejection, with cross-process race and rollback tests. Extracted windowed computation from legacy report persistence. This is **not bound evaluation**: execution, report publication/recovery, supersession, AI and UI remain unimplemented. Focused 71 passed/1 skipped; backend 151 passed/1 skipped; no new live browser or scientific validation. Checklist unchanged. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — recorded identity/review snapshots

The bound-reference API can now persist and list point-in-time declared identity, grid, fingerprint and review checks, serialized with local review transitions. These checks do not authorize evaluation, verify independence, or connect references to evaluation, AI or UI. The 2-million-pixel candidate limit remains. Focused 34 passed; backend 145 passed/1 skipped; mocked Playwright 16 passed; build and `pip check` passed. No current-turn real browser test or real accuracy result. Checklist unchanged. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — API-only bound reference preparation

Added a separate SQLite-backed unreviewed reference record with declared product binding, raster fingerprints, review history and transaction-protected pending/attestation/rejection/withdrawal actions. Windowed report transitions now serialize cooperating local workers through SQLite and persist history in atomic JSON. This API is not connected to evaluation, AI or UI; identity authentication, supersession, security and full live audit remain open. Focused 31 passed, backend 142 passed/1 skipped, mocked Playwright 16 passed; build and `pip check` passed. Actual local API and A_009 browser smoke succeeded. Checklist unchanged. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — outcomes and live checks

Added persisted rejection, known consistency-check failure and successful evaluation timestamps; terminal transitions are guarded within one process. Tightened reference/report listing containment; actual symlink testing was skipped due to Windows privilege restrictions while simulated resolved-target coverage passed. Fresh local-data browser/API checks verified A_009, A_010, Kaveri observations and pending validation, but not every requested surface. Full lifecycle, authorization, TOCTOU, multiworker control and scientific validation remain open. Focused 53 passed/1 skipped, backend 133 passed/1 skipped, mocked Playwright 16 passed; build and `pip check` passed. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — reviewed assessment (partial)

- Added persistent exact-grid windowed assessments with a separate explicit evaluation action, unauthenticated reviewer declarations, input hashes, class/block evidence and bounded processing. The existing small-raster resampling route remains available. AI links submitted NISAR reports only when product/date/version and local candidate hash match; this is not authenticated validation.
- The nine-state evidence lifecycle, unreviewed-reference import, failed/rejected assessments, Sentinel-1 hash/version linkage, comprehensive security and new live-browser audit remain incomplete. A controlled 2,100 × 2,100 raster was tested; no real reviewed reference or real accuracy result exists.
- Focused backend 48, targeted safety 3, full backend 128 and mocked Playwright 16 passed; build and `pip check` passed. Six local API GETs and both river summaries returned 200 with acquisition disabled. Full caveats and next action: [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md). Five scientific checklist items remain open.

## 2026-11-10 — Windowed real-data and evidence-status continuation

- Full-size A_009 exploratory candidate comparison now succeeds using bounded windows, without resampling or accuracy claims. Reviewed comparison remains limited to two million pixels. Processing limits and remaining memory caveats are in [README.md](./README.md).
- AI evidence status now uses matching submitted reports and recorded reference attestations without treating those attestations as authenticated. A separate thresholds-met/awaiting-validation state and independently authenticated scientific-validation state are not available in the existing data model.
- Live local dashboard verification showed A_009 candidate values and A_010 no-data correctly. Fixed invalid WGS84 axis coordinates and tightened several output-path containment checks. Further file-serving review remains.
- Verification: focused validation 29 passed, AI 11 passed, combined focused 60 passed, full backend 120 passed, Playwright 16 passed, production build passed, `pip check` clean. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md) for exact caveats, data counts and next action.

## In-progress real-data audit — class distribution and pairwise overlap

- Reviewed metrics now also require operator-declared minimum pixels and occupied grid blocks per reference class. These gates do not establish representativeness; older reports lacking them have metrics withheld without rewriting stored files.
- Candidate comparisons now expose every pair's absolute and relative area differences, disagreement, and candidate-mask IoU. Zero denominators or unions are unavailable, not accuracy or evidence of a best method.
- An in-memory A_009 512 × 512 crop comparison was exercised against the minimum-10-pixel sensitivity mask. Full-size A_009 was rejected by the two-million-pixel endpoint limit; no full-scene method comparison or scientific validation was established.
- Verification: 25 focused validation tests, 103 backend tests, 16 Playwright tests and production build passed; `pip check` was clean. Seven safe API GETs returned 200; full-size comparison returned the expected 422. Existing Starlette/httpx and Vite chunk warnings remain.
- The broader audit is incomplete; see [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md) for precise outstanding work. The five evidence-dependent checklist items remain open.

## Latest verification — validation evidence and exploratory comparison

- Reviewed the existing reference import, AI Analysis, method comparison and supplied-axis sampling workflows; retained their existing dashboard integration and scientific caveats.
- Added operator-declared minimum shared-pixel and coverage gates to reviewed metrics, corrected overall status for insufficient reports, enforced reference NoData in method evaluation, and withheld metrics from legacy reports lacking thresholds without rewriting them. Thresholds do not establish representativeness.
- Added a candidate-only exploratory comparison with shared support, per-method areas and disagreement area; reviewed comparisons now include these quantities and preserve submitted reference provenance. Analysis links to the existing comparison form. No winner or unreferenced accuracy is reported.
- Tests: focused validation **18 passed**, full backend **96 passed** (one Starlette/httpx deprecation warning), Playwright **16 passed**, production build passed (1,596.74 kB main-JS advisory). Tests used fixtures; no scientific labels, validation scores, or verified widths were created. Automatic acquisition was not enabled.
- The five evidence-dependent checklist items remain open. No files were staged or committed.

## Latest verified milestone — reference ingestion, method evaluation, and axis-sampling safeguards

- Recalculated the actual checklist: **64/69 (92.8%)**, with the original five evidence-dependent items still unchecked. No item was marked complete merely because software scaffolding now exists.
- Added a metadata-only catalog of JRC Global Surface Water, Landsat Collection 2 Level-2, CWC/NWIC river lines, HydroRIVERS, and GRWL, with intended-use and temporal/spatial/license caveats. The dashboard can import and list user-reviewed 0/1/255 reference GeoTIFFs with provenance; the service bounds file size/pixels, checks CRS/resolution/NoData/classes, stores separately, and does not authenticate the reviewer or source.
- Added a method-comparison API/client for two to eight supplied candidate rasters on identical grids and one shared common-valid reference support. It records parameters, does not select a winner, and requires operator attestation; no alternate method was run against real labels or justified scientifically.
- Added a bounded, user-supplied GeoJSON axis/corridor sampling API with per-station candidate-segment lengths, valid/raster coverage, quality states, and flags. It does not derive geometry from OSM; it labels axis/corridor provenance unverified and uncertainty unquantified. A focused regression found and fixed potential joining of candidate segments across gaps outside a disconnected corridor.
- Checked the official CWC/NWIC direct river-network endpoint: it serves GeoJSON and advertised 356,234,820 bytes. The national file was not downloaded; actual target features/CRS and suitability as an active-channel axis remain unverified. HydroRIVERS' approximately 500 m source grid and static Landsat-derived GRWL widths do not provide event-date labels or defensible 10 m bank geometry. The official Bhuvan source surfaced in this review is a 2016 WBIS technical document, not a verified target-reach event-date label download.
- Documented that actual independent labels, scientifically justified alternative methods, trusted active-channel geometry, and quantified width uncertainty remain unavailable. No real reference labels, scores, or width results were generated.
- Final verification: backend suite **88 passed** with one existing Starlette/httpx deprecation warning; Playwright **15 passed**; frontend production build passed with a **1,593.08 kB** main-JS chunk advisory; project-venv `pip check` found no broken requirements. Acquisition-disabled API smoke returned HTTP 200 for 15 core/catalog/analysis/AI endpoints, including both rivers' deterministic summaries and temporal-pair listings.
- The first full browser run exposed two ambiguous labels after adding the method form; the validation tests now scope inputs to the validation form, and the complete 15-test suite passes. A first smoke script also used a nonexistent app-state property after all endpoints returned 200; it was corrected to check the actual acquisition service setting and then passed.
- Automatic acquisition stayed disabled; no satellite data were downloaded and no jobs started. No files were staged or committed. Git still reports the workspace content as untracked, so `git diff --check` alone cannot inspect untracked-file whitespace.
- Direct whitespace scan passed for files changed in this continuation. A broader scan found pre-existing trailing spaces in `data/NISAR-GCOV-SPATIAL-DIAGNOSTIC.md` and `data/SENTINEL2-NISAR-COMPARISON-DIAGNOSTIC.md`; those unrelated files were not edited.

## Latest verified milestone — NISAR component-size sensitivity

- Added a bounded, opt-in API and dashboard action that generates separate 8-connected component-size candidate scenarios from an already processed mask. Each scenario is provenance-bearing, preserves CRS/transform/10 m resolution and 255 NoData, and is written beside (not over) the source.
- Generated real A_009 scenarios for minimum component sizes 2, 5, and 10. From 3,885,882 source candidate pixels, the scenarios reclassify 89,437 / 202,003 / 283,567 pixels; remaining candidate counts are 3,796,445 / 3,683,879 / 3,602,315. All 550,634,840 NoData pixels were preserved. Outputs are explicitly exploratory and no threshold is endorsed.
- The source candidate mask remains unchanged. The UI displays all parameters, separate-mask downloads and quality flags; it does not call removed pixels speckle or validated non-water. No acquisition/download job was started and automatic acquisition remained disabled.
- Checklist is recalculated from actual boxes: **64/69 (92.8%)**. Three Phase 5 software/evaluation items are checked. Independent validation, alternate classifier, reviewed labels, river-axis sampling and automated width-quality work remain unchecked pending evidence.
- Verification: full backend suite **79 passed** (one existing Starlette/httpx deprecation warning); full Playwright suite **12 passed**; frontend production build passed with a 1,572.54 kB Vite chunk advisory; `pip check` found no broken requirements. Health, regions, observations, rivers, acquisitions, analysis status, validation status, AI summary, sensitivity metadata and all three mask download endpoints returned HTTP 200 with acquisition scheduling disabled.
- The first focused browser assertion used a heading role for a bold label and failed; the selector was corrected and the focused test and full suite passed. An exploratory `npm test` command was blocked by PowerShell's `npm.ps1` execution policy; verification used `npm.cmd`.
- No files were staged or committed. Existing satellite products and the source candidate mask were not modified.

## Latest verified milestone — Compatible Sentinel-1 temporal candidate comparisons

- Implemented strict pair eligibility, a pair-discovery API, common-valid support/provenance results, and a user-triggered comparison workflow for persisted Sentinel-1 candidates. Pairing requires chronological same-river observations, identical CRS/transform/dimensions, projected metre grids, valid 0/1/255 masks, matching mission/product/polarization/filter/threshold method, and compatible fixed-threshold settings.
- The legacy acquisition registry contained Sentinel-1 results marked failed after a historical response-schema error even though their persisted result and mask existed. A narrow, idempotent recovery path now restores only rows with that exact legacy error signature and verifies product identity, candidate status, mask classes/NoData, grid, pixel size, counts, area and threshold before changing registry status.
- Live catalog/API verification with automatic acquisition explicitly disabled found **5 Kaveri** and **1 Tungabhadra** compatible pairs. Kaveri pair `S1D_IW_GRDH_1SDV_20261021T003932_20261021T003957_005106_009AB6_rtc` → `S1D_IW_GRDH_1SDV_20261102T003932_20261102T003957_005281_00A0BC_rtc` has 436,083 common-valid pixels; its candidate comparison reports 56,238 gain and 71,969 loss pixels. Tungabhadra's available pair has 418,128 common-valid pixels and reports 47,214 gain and 54,174 loss pixels. These remain unvalidated candidate differences, not verified water change.
- Both actual comparison mask and PDF download routes returned HTTP 200. AI summary POSTs returned HTTP 200 and reported `compatible_pair_available` with per-river pair counts; automatic acquisition remained disabled and no new acquisition job or satellite download was started.
- Focused backend tests: **52 passed**. Full backend suite: **77 passed**, one existing Starlette/httpx deprecation warning. Full Playwright suite: **11 passed**. Frontend build passed with a 1,569.99 kB main-JS chunk advisory. `pip check` found no broken requirements.
- A first focused test run exposed an indentation error in the new recovery fixture; after correction, the suite exposed an undefined `earlier` reference in comparison-result persistence. Both were fixed and the focused/full suites passed.
- No source satellite products or candidate masks were modified. Comparison masks/PDFs are separate outputs. No files were staged or committed; Git reports project files as untracked.

## Final verification and project closeout

- Backend suite: **77 passed**, one existing Starlette/httpx deprecation warning.
- Playwright browser suite: **11 passed**.
- Frontend production build: passed; main JavaScript chunk is 1,569.99 kB and triggers Vite's existing >500 kB advisory.
- `pip check`: no broken requirements. `git diff --check`: no output/errors.
- Acquisition-disabled API smoke checks returned HTTP 200 for health, regions, rivers, acquisitions, analysis status, validation status, and the deterministic AI summary. The selected record was the locally persisted Tungabhadra NISAR A_009 product, acquired at `2026-11-06T00:25:20Z`; the response included candidate metrics and ASF DAAC provenance.
- Automatic acquisition was explicitly disabled for the smoke check; no acquisition or processing job was submitted, and no background Node/Python process remained.
- Final report created at `FINAL_PROJECT_COMPLETION_REPORT.md`. It distinguishes verified software delivery from unvalidated candidate outputs and outstanding reference, temporal-pair, and bank-geometry evidence.
- The actual checklist count is **61/69 (88.4%)**. Unchecked work is retained where evidence-dependent: independent validation, empirically justified cleanup/alternate classification, and trusted axis/bank inputs.
- Git reports workspace files as untracked, so it cannot produce a complete tracked baseline diff. No files were staged or committed.

## Previous verified milestone — AI Analysis provenance and selection integration

- Extended each persisted product option in `POST /api/analysis/ai-summary` with acquisition end time, provider, product type, polarization, CRS, pixel size, and source-license/catalog-record fields where present. Sentinel-1 reports its STAC item URL, never its signed asset URL; NISAR reports ASF DAAC and processing provenance without exposing local paths.
- The dashboard now displays provenance for the product whose measurements are currently shown. Changing the product selector marks existing metrics stale until Run Analysis is clicked, avoiding the appearance that values belong to the newly selected product.
- Selecting an ASF discovery result now synchronizes the dashboard river and map footprint. The AI panel uses it only if the product exists in that river's persisted catalog; otherwise it explicitly labels the result as discovery metadata only and does not infer measurements.
- The only analysis implementation is deterministic/rule-based. No LLM provider configuration, integration or fallback path exists; no model-specific behavior was executed or claimed.
- Added backend and browser regression coverage for product provenance, no leakage of Sentinel-1 asset URLs, selected discovery behavior, global river synchronization, catalog-only warnings, and map-footprint legend.
- Verification so far: focused AI backend tests **4 passed**; focused AI/map browser tests **3 passed**; frontend production build passed (1,565.26 kB main-JS chunk advisory). Full suites are pending after remaining work.
- Temporal comparison remains unavailable: latest stored-grid inspection recorded no same-river Sentinel-1 pair with identical CRS, affine transform and dimensions, and candidate thresholds differ. A single processed NISAR candidate date and same-overpass Sentinel-2 tiles do not provide a compatible same-sensor temporal pair. No comparison was fabricated.
- Read-only cleanup feasibility check on the actual A_009 mask (`25660 × 21962`, EPSG:32643, 10 m pixels, NoData 255) found 160,502 eight-connected candidate components. Arbitrary minimum sizes of 2/5/10/25/50/100 pixels would remove respectively 89,437/202,003/283,567/397,838/504,298/634,217 candidate pixels. Because no independent labels establish which are noise versus narrow real channels, no filter parameter was selected and no output was generated.

## Previous verified milestone — Map legend and error/file-serving audit

- Reviewed file response routes, path resolvers, output allowlists, UUID validation, containment checks, missing-file responses, optical preview error/removal handling and disabled unavailable-bank controls. No unhandled arbitrary output path was identified in the inspected surfaces.
- Added selected satellite catalog footprint provenance to the dynamic map legend and clarified that polygon overlays are candidate geometry only; unshown surroundings are not evidence of non-water.
- Checklist now counts **57/69 (82.6%)**, based on actual checked boxes. Remaining unchecked items include independent reviewed labels, scientifically justified candidate cleanup/method comparison, trusted river-axis/bank inputs and compatible temporal products.

## Latest verified milestone — Independent-validation workflow integration

- Added `GET /api/analysis/validation/status`, `POST /api/analysis/validation`, and `GET /api/analysis/validation/{validation_id}` with typed provenance and result contracts.
- The service accepts only bounded, single-band GeoTIFF masks with classes 0/1/255 and declared 255 NoData; it aligns the reference labels to the candidate grid with nearest-neighbour resampling and calculates confusion metrics only on common valid support when both reference classes exist. Inadequate overlap or single-class references return explicit statuses and no metric score.
- Reports persist atomically as JSON with source, acquisition time, reviewer, methodology, limitations, CRS, common-support counts and caveats. Submitted raster bytes are not retained. The service cannot independently verify reviewer identity, source independence, label quality or sampling design.
- Added a responsive dashboard workspace with a truthful pending state, provenance/file inputs, loading/error handling, report metrics, saved-report links, and explicit warnings against treating Sentinel-2 NDWI as ground truth. No reference labels or validation scores currently exist.
- Updated README, checklist, audit and handoff. Checklist recalculated from checked boxes: **55/69 (79.7%)**. Scientific validation remains blocked until suitable independent labels are obtained and reviewed.
- Verification: focused backend tests 4 passed; full backend suite **75 passed** with one existing Starlette/httpx deprecation warning; frontend production build passed with a 1,562.53 kB main-JS chunk advisory; Playwright browser tests **9 passed** including pending and completed report states. No product was downloaded, no acquisition job was submitted, and no scientific result was created.
- The UI completion test uses an explicit test-only API fixture; it is not evidence that project reference labels or scores exist.
- Bounded file-serving and map-layer review found fixed output-name allowlists, product/catalog lookups, resolved directory containment checks for Sentinel-2 outputs, UUID validation for report paths, and no user-supplied arbitrary output filename. Existing regressions cover invalid observation traversal, real/missing output handling, preview errors, and unavailable bank-layer controls/legends. No code change was indicated by this review.
- Reviewed the pending river-axis measurement task: automated cross-sections from the currently available OSM centerline would make the results depend on an unverified axis, while no independent bank geometry exists. The existing user-drawn transect remains a candidate-mask segment measurement and is not a verified bank-to-bank width. Defer automated river-axis sampling until a suitable channel-axis reference and valid support are available; do not manufacture bank geometry.
- Next: continue the remaining engineering audit for independent tasks that do not require unavailable scientific references; retain compatible temporal comparisons, validated bank/width claims and validation scores as blocked. Candidate independent-validation results must not be interpreted beyond submitted labels; keep reference acquisition/quality and scientific eligibility as explicit limitations.

## Latest verified milestone — Additional Sentinel-2 tile coverage

- Added `backend/scripts/inspect_sentinel2_coverage.py`, which reproducibly queries Planetary Computer STAC metadata for 2026-11-05 through 2026-11-09 and reports item footprints, acquisition/cloud metadata, centerline overlap, and existing NISAR-valid pixels beneath each footprint. It does not sign or download imagery.
- The screen returned 11 items. Same-day tiles 43PER, 43PES, 43PFS, and 43PFT add centerline segments beyond the existing 43PGT footprint. Footprint lengths and NISAR-mask counts are geometric/support screening only, not clear optical pixels.
- Extended `backend/scripts/create_sentinel2_candidate.py` for those screened same-overpass IDs only. It signs required COG assets sequentially with 2.5 seconds between requests, does not retry HTTP 429 responses, persists no signed URLs, and writes distinct per-item outputs under `nisar-processing/sentinel2-observations/`. The existing 43PGT output is untouched. Processing skips COG reads in blocks outside valid NISAR corridor support.
- Generated real bounded-COG exploratory NDWI outputs for 43PER, 43PES, 43PFS, and 43PFT. On their respective NISAR grids, common-valid counts are 788,166; 1,630,335; 1,972,759; and 1,266,000. Candidate counts are 28,194; 122,670; 931,867; and 32,019. Supports overlap and must not be added together. None is ground truth or an independent validation reference.
- Added API discovery through the existing `sentinel2-reference` metadata route, plus per-observation preview and mask routes. The acquisition dashboard lists the additional tile/date/cloud/support information and lets each tile be independently shown/removed and downloaded without replacing or disabling NISAR layers.
- Changed scheduled acquisition to opt-in by default and added a regression test; no scheduled/manual acquisition was started during this work.
- Verification: full backend suite 71 passed (one existing Starlette/httpx deprecation warning); production frontend build passed (1,554.55 kB main JS chunk advisory); all 7 Edge browser tests passed; live API returned HTTP 200 for metadata, preview PNG and GeoTIFF of each of the four additional tiles; `pip check` found no broken requirements; `git diff --check` passed. Streamed raster checks confirmed candidate/non-candidate counts match metadata and all other cells remain 255 NoData. This phase added a test that scheduling defaults off. No scheduler/job was started.
- No complete Sentinel-2 scene was downloaded. B03/B08/SCL were read via bounded COG access; only derived 10 m candidate GeoTIFFs and metadata were saved. No independent labels, validation scores, temporal-change outputs or scientific bank measurements were created.
- Next: assess remaining unchecked engineering items (including output/file-serving audit, optional-layer legends, candidate cleanup, and river-axis sampling) and complete those that can be justified without independent labels. Keep temporal comparison and scientific validation blocked where data are insufficient; do not create the final report while feasible tasks remain.

## Latest verified milestone — Deterministic AI Analysis

- Added `POST /api/analysis/ai-summary`, typed request/response models, and a local rule-based service that reads the persisted acquisition catalog. No external LLM is used.
- The summary reports selectable real NISAR/Sentinel-1 products, centerline and valid-support coverage, NoData, candidate pixels/area, NISAR HH/HV thresholds, polarization and threshold-sensitivity diagnostics, linked Sentinel-2 NDWI context, and whether a temporal comparison needs further review.
- The default prefers the newest usable processed NISAR product where one exists; the dashboard allows selecting another product or river. No-data and failed products are counted separately.
- The dashboard explicitly labels the analysis deterministic/rule-based and states that candidates are not ground truth, independent validation is unavailable, and no accuracy/flood/erosion/deposition/verified-bank result is produced.
- Live TestClient smoke test against the persisted local catalog returned HTTP 200 and selected Tungabhadra NISAR A_009. It reported 12,910,080 valid of 15,356,387 corridor pixels (84.07%), 3,885,882 candidate pixels (388.5882 km²), 93.748% mapped-centerline coverage, and candidate-area sensitivity from 271.5856 to 545.3585 km² (70.45% range across recorded perturbations). Its linked Sentinel-2 candidate reports 1,011,220 common-valid pixels (101.122 km²), 69,498 candidate pixels (6.9498 km²), threshold 0, and a 17,691.025-second offset. These are stored processing facts, not validation results.
- The temporal status is `not_evaluated` because products exist but compatibility and scientific context still require explicit review. No temporal change result or accuracy score was computed.
- Verification: full backend suite 68 passed; frontend build passed (existing large-chunk advisory: 1,552.51 kB JS); Edge Playwright suite 7 passed, including navigation, empty-catalog, and API-error behavior; live API smoke test passed with automatic acquisition disabled. One existing Starlette/httpx deprecation warning remains.
- No satellite products were downloaded or processed in this milestone; no acquisition job was submitted. No server or background process was left running.

## Latest verified investigation — Stored multi-date outputs

- Read the persisted Sentinel-1 `water-mask.tif` outputs and their result metadata for all three processed acquisitions per river. This was read-only; the mask rasters and catalog were not modified.
- All Kaveri candidate masks are 1,200 × 1,200 in EPSG:32643 but have different affine transforms. Tungabhadra has three masks, with one in EPSG:32644 and the other two in EPSG:32643; all have different transforms. The available pair thresholds also differ.
- Therefore, there is no currently stored same-river pair meeting the existing exact CRS/transform/dimensions requirement. No change mask was produced. The existing comparison endpoint must retain its same-river, chronological, exact-grid checks; any future regridding requires an explicit, documented method and uncertainty handling.
- Verified the acquisition dashboard's downloads are shown only when the corresponding persisted result URL exists; real NISAR A_009 processing outputs and optical candidate output are linked. The checklist item for real-output-only controls is now checked.
- No satellite products were downloaded or processed; no comparison job or output was created.
- Checklist is 49/64 (76.6%). The final report remains pending.

## Completed and verified

- Existing React, Leaflet, FastAPI, Rasterio, SQLite and satellite-service architecture inspected and retained.
- Real Tungabhadra NISAR L2 UR GCOV A_009 was previously downloaded, opened as HDF5, processed and registered; its processing status remains unvalidated candidate.
- NISAR HH/HV comparisons, five threshold offsets and connected-component diagnostics exist; previous actual output counts are documented in `data/NISAR-GCOV-SPATIAL-DIAGNOSTIC.md`.
- Sentinel-1 RTC processing and fallback are present; backend tests cover acquisition and analysis paths.
- Health, regions, observations, river, analysis-capability and acquisition APIs returned HTTP 200 in the current local smoke test.
- `.env` is ignored by Git; Python dependency check reported no broken requirements.
- The map displayed both centerlines and each individual selection in browser checks. The legend now reflects the selected river, and changing river selection clears a stale satellite overlay.
- Backend acquisition/NISAR focused tests passed after adding local NISAR catalog recovery (23 passed).
- ASF Sentinel-1 and NISAR search results are now filtered against a projected 1,500 m centerline corridor after broad catalog retrieval; retrieval asks for up to five times the requested count (maximum 100) to prevent unrelated bounding-box matches from crowding out corridor matches.
- Local NISAR products and processing metadata recover into the API catalog after empty catalog scans. A recovered local product now reports `metadata_found` with an explicit recovery message rather than the contradictory “no data” status.
- Live, acquisition-disabled API verification recovered both Tungabhadra NISAR products and served the A_009 processing result: 12,910,080 valid paired pixels and 3,885,882 unvalidated candidate pixels.
- Diagnosed the latest Kaveri Sentinel-1 failure. The scene footprint intersects the river, and the 12 km crop contains 22.758 km of the mapped centerline and 459,523 corridor cells, but all 1,440,000 output cells are NoData and zero valid positive VV pixels remain. This is a genuine no-observation result for that crop, not a basis to relax classification validity rules.
- Created `PROJECT-AUDIT.md` documenting the current architecture, API inventory, data flows, actual products/results, tested behavior, known limitations, and remaining work.
- Added Playwright end-to-end tests for both/single-river legend selection, centerline layer visibility, and disabled unavailable bank layers. Both tests pass using installed Microsoft Edge.
- Added a typed `InsufficientValidDataError` for the established minimum-valid-pixel gate. Acquisition refreshes record this outcome as `no_data`, while unrelated exceptions remain `failed`; when all discovered scenes have no usable valid pixels, the river scan reports a no-data explanation instead of implying a processing failure.
- Updated the acquisition panel's no-data label and added backend, API, and browser regression coverage for the distinction. No validity masks, pixel thresholds, or classification rules were relaxed.
- Added SQLite-backed persistent job records for NISAR downloads, NISAR GCOV processing, and Sentinel-1 RTC acquisition/processing, including identifiers, timestamps, stage, nullable progress percentage, safe error text, output references, and retry lineage.
- Added job submission, listing/filtering, detail, retry, and queued-only cancellation APIs. A partial unique SQLite index prevents concurrent jobs for the same river/product/operation; retries create linked records and completed products are reused.
- Added startup recovery: queued jobs resume; interrupted running/downloading/processing jobs are marked failed with an explicit safe-retry message. Job records survive process restarts in the existing SQLite catalog.
- Made NISAR downloads stage to unique temporary directories, verify catalog size and required GCOV HDF5 grid/polarization structure before atomic promotion, and refuse to overwrite existing files. Invalid/incomplete staged downloads are discarded.
- Added dashboard job stage/status/timestamps/error/output display and retry controls, plus queue controls for NISAR download/processing and failed Sentinel-1 candidates. Percentages are omitted while progress cannot be measured.
- Added job API/persistence/recovery/retry/no-data/redaction tests, HDF5 atomic-download regression coverage, and a Playwright job status/retry regression.
- Queried Planetary Computer Sentinel-2 L2A for Tungabhadra (2026-11-05 through 2026-11-08): 11 STAC items intersected the centerline. Five same-day 2026-11-06 tiles report 38.78%–50.29% tile cloud cover. The lowest-cloud tile, `S2C_MSIL2A_20261106T052011_R062_T43PGT_20261106T101206`, intersects 124.15 km (21.80%) of the mapped centerline by STAC footprint.
- Used Planetary Computer's read-only Sentinel-2 SAS endpoint without printing or persisting its token. For tile 43PGT, bounded B04 (10 m uint16) and SCL (20 m uint8) COG windows returned actual pixels. For adjacent same-acquisition tile 43PES, bounded B03/B04/B08 (10 m uint16) and SCL windows were also read. Both tile grids use EPSG:32643; reflectance dimensions are 10,980² and SCL dimensions 5,490². No imagery was saved locally.
- Scanned 12 small SCL windows along the overlapping section of 43PGT. The sample at 51.5 km contained 14,400 valid SCL pixels, 0.9% cloud/shadow/snow classes, and 1,205 class-6 water pixels. Other sampled locations were much cloudier (up to 95%). This verifies access, not an optical mask or validation.
- Inspected a representative T43PES window: B03/B04/B08 each returned 90,000 valid pixels; its 150×150 SCL window returned 22,500 pixels and was dominated by cloud/shadow classes. Scene-level cloud cover cannot replace pixel-level masking.
- Compared tile 43PGT with the existing A_009 mask on its 10 m EPSG:32643 grid, using SCL classes 4/5/6 as clear and excluding NoData, clouds, shadows, and unclassified pixels. The tile corridor intersection contains 3,592,602 cells; 1,011,220 cells (101.122 km²) have common NISAR-valid, clear-SCL, valid B03/B08 support.
- Within that common support, 318,650 NISAR candidate pixels (31.865 km²) and 69,498 NDWI>0 optical candidate pixels (6.9498 km²) overlap in 65,194 cells (6.5194 km²). Simple agreement is 74.51%, IoU 20.19%; both are descriptive only, not accuracy scores. NDWI is uncalibrated, SCL is not ground truth, SCL is resampled from 20 m to 10 m, acquisitions are 4 h 54 min 51 sec apart, and the tile covers only 21.80% of the centerline.
- Persisted the measured methods, counts, temporal offset, resampling, and limitations in `data/SENTINEL2-NISAR-COMPARISON-DIAGNOSTIC.md`. At that diagnostic checkpoint no optical candidate raster or validation result had yet been created.
- Created `backend/app/services/optical_reference.py` and a scoped catalog/signing CLI. Bounded B03/B08/SCL COG reads generated a separate 10,302 × 7,746, 10 m EPSG:32643 raster; 0/1 encode non-candidate/candidate and 255 is NoData. It has 1,011,220 common-valid pixels and 69,498 NDWI candidates (6.9498 km²). The common-valid count reproduces the diagnostic; no full Sentinel-2 tile or signed URL was saved.
- Added API endpoints for the optical metadata and GeoTIFF, linked their URLs from the local A_009 processing result, and added a dashboard panel for candidate counts, acquisition time, limitations, and raster download. It is explicitly labeled exploratory and not ground truth; no accuracy score is displayed.
- At the candidate-generation checkpoint, fixture coverage verified nearest-neighbor SCL resampling, NDWI thresholding, NoData preservation, existing-output protection, API download/metadata, catalog-link merging, and browser display.
- Added a browser-renderable PNG preview of the existing candidate raster. The backend reprojects the raster to WGS84 for the map image, keeps class 0, class 1 and NoData 255 visually distinct, provides the exact preview bounds/CRS in metadata, and does not alter the source GeoTIFF.
- Added an independently toggleable Leaflet image layer that coexists with the existing NISAR GeoJSON and river-centerline layers. The legend distinguishes candidate, non-candidate and NoData/invalid/unavailable pixels and displays the warning “EXPLORATORY SENTINEL-2 NDWI OUTPUT — NOT GROUND TRUTH.” A fetch-based loading/error state is shown for preview failures.
- Displayed Sentinel-2 and NISAR acquisition times, their 4 h 54 min 51.025 sec offset, 101.122 km² common-valid area, approximately 21.8% mapped-centerline coverage, catalog cloud cover, NDWI threshold, and the Sentinel-2 source product identifier when present. Coverage is exposed only for the exact tile whose footprint intersection was measured in the existing diagnostic.
- Verified the actual A_009 metadata and preview endpoints with acquisition automation disabled. Metadata returned EPSG:32643, WGS84 bounds west 76.862031/south 15.269866/east 77.830303/north 15.979812, 1,011,220 common-valid pixels, 21.7962% coverage, and 17,691.025 seconds between acquisition start times. Preview returned `image/png` (31,975 bytes); health, regions, and observations also returned HTTP 200.
- Latest verification: all 64 backend tests passed (one existing Starlette/httpx deprecation warning); frontend production build passed (existing ~1.54 MB Vite chunk advisory); all 4 Microsoft Edge browser tests passed, including map layer coexistence, removal, class legend, metadata and preview error state.
- Investigated public Landsat, JRC Global Surface Water, ESA WorldCover, GRWL, CWC/NWIC, and NRSC/Bhuvan datasets for independent validation. No ready-made event-date reference labels are available for the current 2026 candidates; exact sources, terms, time fit, measured overlap, and a reproducible future protocol are documented in `data/INDEPENDENT-VALIDATION-INVESTIGATION.md`.
- The nearest Tungabhadra Landsat scene (`LC09_L2SP_144049_20261103_02_T1`) is 2 d 19 h 15 min before NISAR A_009, has 86.63% scene cloud cover, and only 6,570/112,430 common-support 30 m cells passed the QA_PIXEL bits 0–5 screen (5.844%). This is a coverage diagnostic, not validation.
- Inspected a 40×40 Landsat 9 COG window (1.2 km square, EPSG:32643) centered at 718740 E / 1753830 N. 955 of 1,600 30 m cells overlapped the actual NISAR/Sentinel-2 common-valid support; 465 cells (48.69%, about 0.4185 km²) also passed QA_PIXEL bits 0–5, relevant QA_RADSAT saturation bits 2–5, all four COG masks, and nonzero reflectance checks.
- Those 465 clear cells occur in 8 of 16 equal spatial sub-blocks, concentrated in the southern half of this patch. The SWIR1/NIR/red false-color preview did not reveal an unambiguous channel/bank boundary; the 30 m pixels and 67 h 15 min 08.940 s acquisition offset do not support defensible labels from this sample. No manual-label template or reference raster was created.
- Clearer Tungabhadra Landsat scenes on 2026-10-26 and 2026-10-25 passed the QA screen over 67.271% and 70.031% of sampled common support, respectively, but their ~10–12 day temporal offsets make them unsuitable as event-date labels without independent evidence of stable hydrologic conditions.
- Eight Landsat scene footprints intersect the Kaveri mapped centerline in the searched date range. No Kaveri common-valid raster overlap or reference labels were evaluated.
- No full scene or global dataset was downloaded, no validation labels or accuracy metrics were generated, and no existing satellite product or candidate mask was changed.
- A fresh STAC lookup and six individually paced asset-signing requests later succeeded (HTTP 200); the earlier 429 was not retried repeatedly. Signed URLs were kept in memory only. Acquisition scheduling was disabled in the command environment.

## Current implementation changes

- `frontend/src/App.jsx`: dynamic visible-river legend and subtitle; selecting a river clears the previously selected satellite footprint/candidate overlay; overview banner distinguishes demonstration metrics from real acquisitions.
- `backend/app/services/acquisitions.py`: recover previously downloaded GCOV HDF5 products and processing metadata into SQLite-backed catalog status; retain them across empty discovery; report local recovery instead of contradictory no-data status; filter authenticated NISAR search results to the river corridor.
- `backend/app/services/satellite.py`: use ASF bounding boxes for candidate retrieval, then exact projected-corridor footprint intersection and overlap ranking.
- `backend/app/services/analysis.py`: expose a specific insufficient-valid-pixel exception without changing the existing 32-pixel minimum.
- `backend/app/services/acquisition_jobs.py`: persistent job lifecycle, queue worker, restart recovery, deduplication, retry and output references.
- `backend/app/main.py`, `backend/app/api/routes.py`, `backend/app/schemas/acquisitions.py`: startup recovery, job endpoints and typed request/response models.
- `backend/tests/test_analysis.py`, `backend/tests/test_acquisitions.py`, `backend/tests/test_acquisition_jobs.py`, `backend/tests/test_satellite.py`: regression tests for no-data behavior, recovery, job lifecycle, safe downloads and corridor filtering.
- `backend/requirements.txt`, `README.md`: declare Shapely and document footprint filtering and cache recovery.
- `PROJECT-AUDIT.md`: architecture, endpoint, data, science, UI, and verification audit.
- `frontend/playwright.config.js`, `frontend/tests/e2e/rivers.spec.js`, `frontend/package.json`, `frontend/package-lock.json`: repeatable browser regression tests and runner configuration.
- `frontend/src/components/AutomaticAcquisitionPanel.jsx`: explicitly describe no-data as an absence of usable observations in the mapped corridor.
- `frontend/src/services/api.js`, `frontend/src/components/AutomaticAcquisitionPanel.jsx`, `frontend/src/styles.css`, and `frontend/tests/e2e/rivers.spec.js`: job API client, live job status/retry controls and browser regression.
- `backend/app/services/optical_reference.py`, `backend/scripts/create_sentinel2_candidate.py`, `backend/tests/test_optical_reference.py`: reproducible COG-based optical candidate generation and fixture tests.
- `backend/app/api/routes.py`, `backend/app/services/acquisitions.py`, `backend/app/schemas/acquisitions.py`, `backend/tests/test_api.py`, `backend/tests/test_acquisitions.py`: safe Sentinel-2 metadata/mask endpoints and catalog link recovery.
- `frontend/src/services/api.js`, `frontend/src/components/AutomaticAcquisitionPanel.jsx`, `frontend/tests/e2e/rivers.spec.js`: optical candidate metadata and download controls with explicit caveats.
- `data/SENTINEL2-NISAR-COMPARISON-DIAGNOSTIC.md`, `data/README.md`, `PROJECT-AUDIT.md`, `PROJECT_PROGRESS.md`, `PROJECT_TASK_CHECKLIST.md`, `PROJECT_CHANGELOG.md`, `PROJECT_HANDOFF.md`: scientific measurements, limitations, and progress/handoff records.
- `.gitignore`, `README.md`: ignore Playwright outputs and document how to run browser tests.

## Known issues and limitations

- The local catalog currently has 16 Sentinel-1 acquisition records: 6 processed, 10 failed. The latest Kaveri candidate (`S1D_IW_GRDH_1SDV_20261107T004804_20261107T004835_005354_00A33B_rtc`) has 22.0352% full-centerline coverage, but its corridor crop has zero valid VV pixels and was correctly not classified. The output raster is all NoData; provider-side source validity was not separately re-read, so the precise cause of the source missing data within that swath remains unknown.
- New refreshes now store the established low-valid-pixel outcome as `no_data`; historical catalog rows are not rewritten until they are retried.
- Job recovery marks interrupted active work failed and permits an explicit retry; it does not pretend to resume in-memory processing. Downloads restart into a fresh staging directory and only verified files are promoted. Orphaned temp directories from process termination are not currently garbage-collected; available disk space is checked before a new download.
- Previous empty NISAR catalog scans are now reconciled with locally stored products on API reads. The latest A_009/A_010 local recovery and processing API behavior is verified; do not start another catalog refresh or download just to repeat this check.
- Sentinel-2 reflectance and SCL pixels were read, one-tile common-support diagnostics were calculated, and an exploratory optical candidate raster was persisted. No independent validation metric exists; comparison remains descriptive and covers only part of the centerline with spatially variable cloud/shadow.
- No despeckling/cleanup result has been produced; the current NISAR mask is unchanged and unvalidated.
- No validated NISAR multi-date comparison, erosion/deposition, flooding, verified banks or scientifically validated width has been produced.
- Overview metrics/charts and demonstration polygons remain illustrative; the UI labels them.
- Frontend production build succeeds but Vite warns that the main JavaScript chunk is about 1.53 MB. `npm audit` reports one moderate advisory on the existing Vite 6.4.4 dependency; it has a fix available but was not changed as part of this test-focused task.
- The repository currently reports the whole project as untracked in Git (`??` at top-level); do not stage or alter user Git history without instruction.

## Verification snapshot

- Latest complete backend suite: 64 passed, with one Starlette/httpx deprecation warning.
- Latest frontend production build: passed; Vite reports a 1.54 MB JavaScript chunk above its 500 kB advisory threshold.
- Frontend browser regressions: 4 passed using installed Microsoft Edge, including optical candidate map visibility/removal, class legend, existing NISAR layer coexistence and preview failure messaging. Bundled Playwright Chromium could not launch in this environment (`spawn UNKNOWN`); the test config supports `PLAYWRIGHT_CHANNEL=msedge`.
- `npm audit`: one moderate advisory for existing Vite 6.4.4; no high or critical findings.
- `pip check`: no broken requirements.
- Live TestClient API smoke test with automatic acquisition disabled: A_009 optical metadata and preview returned HTTP 200; preview was 31,975 bytes (`image/png`) with WGS84 bounds and EPSG:32643 source metadata. `/api/health`, `/api/regions`, and `/api/observations` returned HTTP 200. No acquisition job was submitted and no satellite product was downloaded.
- `git diff --check` passed. Git still reports the project files as untracked at the top level; nothing was staged.
- Browser smoke test: both rivers selected -> both lines and legend entries visible; Kaveri selected -> only its line and legend entry visible. Tungabhadra-only selection was separately verified.
- API smoke test: `/api/health`, `/api/regions`, `/api/observations`, `/api/rivers`, `/api/rivers/tungabhadra`, `/api/analysis/status`, `/api/acquisitions` all returned HTTP 200 before the final catalog-recovery code was loaded by the already-running process.

## Next actions

1. Investigate whether a different near-date Landsat scene or additional same-day Sentinel-2 tile offers clear, spatially distributed water-boundary pixels; Sentinel-2 remains optical-modality evidence and cannot validate its own NDWI classification.
2. Obtain contemporaneous field, aerial/drone, or independently reviewed high-resolution water-boundary evidence. Do not label the current Landsat patch or calculate confusion matrices, precision, recall, F1, IoU, or accuracy without independent review.
3. For Kaveri, identify a target classification/acquisition and compute overlap against actual valid pixels before selecting any reference.
4. Keep candidate cleanup, bank, width, flood and change-detection claims blocked until their methods and independent evidence are available.
5. Keep `FINAL_PROJECT_COMPLETION_REPORT.md` pending while feasible development and validation tasks remain.
