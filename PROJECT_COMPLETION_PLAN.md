# SAR Sentinel India — Completion Plan

This plan tracks feasible engineering and scientific work separately from evidence
that is blocked by unavailable independent reference data. Completion is based on
verified acceptance criteria, not estimated effort.

## Current execution order — national platform

The latest request prioritizes national river work. Current pilot-only
client-side selector search is an incremental UX improvement, not the
requested spatial database or paginated explorer. Next inspect licensed
national source metadata and schema; build a resumable source-provenanced
spatial catalog and wire paginated selection to the existing map and processing
gates. Preserve the existing two pilot workflows and report unmonitored
features honestly. Then address agriculture, forest, earthquake events,
complex-data InSAR, combined analysis and AI in the requested order.
The previously requested bound-reference evaluation remains incomplete.
Detailed checkpoint and required tests: [handoff](./PROJECT_HANDOFF.md).

## Latest continuation — national coverage scope

Only two OSM study rivers are registered. The selector consumes the existing catalog but national dataset import, source-specific identity/topology, paginated search, monitoring coverage and generalized processing are open. Verify licensing and source schemas before import. Bound count calculation now persists transactionally without metrics; complete bound evaluation and recoverable reports first. Backend 156 passed/1 skipped, mocked browser 17 passed. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — reservation precedes evaluation

SQLite reservations now snapshot candidate bytes, exact identity and attested reference metadata and are atomically rejected upon withdrawal. Separate-process races and injected rollback are covered. Windowed calculation is separated from legacy persistence. The stopping gate is not met: implement guarded conditional evaluation state, revalidation, DB-authoritative result, crash-safe derived report generation and recovery before integration. Supersession, full security and live UI audits also remain. Focused 71 passed/1 skipped, backend 151 passed/1 skipped; checklist 64/69. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — transactional integration still required

Point-in-time identity/review checks and audit history are implemented for small candidates; they do not enable evaluation or verify evidence adequacy. Next design a crash-safe transaction coordinating current review state and both raster identities with persisted assessment/evaluation, including withdrawal races, invalidation and historical supersession. Only then integrate both reviewed paths, deterministic AI and UI, and complete security and real-browser audit. Focused 34 passed, backend 145 passed/1 skipped, mocked browser 16 passed; build passed. Checklist remains 64/69. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — remaining integration

API-only product-bound reference preparation and transactional review history now exist, plus local cross-process serialization of report transitions. Existing evaluation, AI and dashboard do not consume the new records; identity verification, supersession, complete file/security and live dashboard audits remain open. Preserve separate legacy workflows and do not infer scientific validation. Focused 31 passed, backend 142 passed/1 skipped, mocked Playwright 16 passed and build passed; checklist 64/69. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — next steps

Evaluation rejection and known consistency-check failures now persist terminal outcomes with timestamps; same-process transition checks do not protect multiple workers. Reference/report list containment was tightened, but a real symlink test was skipped and TOCTOU and authorization remain open. Live local browser checks covered A_009/A_010, Kaveri and validation pending; other surfaces remain unverified. Implement the product-bound import/review/attestation lifecycle and safe cross-process transitions, then complete file and live UI audits. Backend 133 passed/1 skipped, focused 53 passed/1 skipped, mocked Playwright 16 passed; build passed. Checklist unchanged. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## Latest continuation — remaining work

The same-grid windowed assessment and explicit evaluation are implemented with limits and unauthenticated provenance; the complete nine-state reference/evaluation lifecycle, failed/rejected persistence, Sentinel-1 identity linkage, comprehensive file-security review and fresh live-browser verification remain open. Preserve the existing legacy workflow. Focused/backend/Playwright tests passed 48/128/16; build and dependency check passed. Scientific checklist remains 64/69. Next implement product-bound lifecycle states and attestation provenance, then complete file-serving and live dashboard review; see [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## 2026-11-10 continuation — remaining engineering and evidence

The exploratory endpoint can now process full A_009 candidate masks in bounded windows; reviewed comparison still cannot. Evidence status reflects matching submitted reports and attestations, not authenticated validation. The record model still lacks a separate pre-validation thresholds-met assessment. Selected path containment and WGS84 axis input checks were strengthened, but further file-serving and live-dashboard audit remains. Verification passed 29 focused validation tests, 11 AI tests, 120 backend tests, 16 Playwright tests and the frontend build. See [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md); all five scientific criteria remain incomplete.

## In-progress real-data audit checkpoint

Per-class pixel and occupied-block gates and pairwise candidate overlap are implemented, but block occupancy is not proof of representative sampling. Full-size A_009 comparison remains blocked by the two-million-pixel upload limit. Verification passed 25 focused validation tests, 103 backend tests, 16 Playwright tests and the frontend build. The broader audit and all five evidence-dependent checklist items remain open; see [PROJECT_HANDOFF.md](./PROJECT_HANDOFF.md).

## 2026-11-10 continuation — evidence gates

Reviewed scores now require operator-declared minimum shared-pixel and coverage thresholds as well as both reference classes; missing or unmet thresholds withhold metrics. Legacy reports without qualifying thresholds are served without scores, without altering saved files. These gates do not establish representativeness. A candidate-only exploratory comparison now reports shared support, per-method areas and disagreement without accuracy or a winner; the Analysis workspace links to the existing comparison form. Independent labels, method justification, trusted geometry and quantified uncertainty remain required.

Verification: 18 focused validation tests, 96 full backend tests, and 16 Playwright tests passed; the frontend build passed with a 1,596.74 kB chunk advisory. The backend emitted one existing Starlette/httpx warning. No acquisition was enabled and no real validation or width output was generated.

## Phase F — Remaining evidence-dependent checklist items

**Status:** Preparation workflows implemented; all five original acceptance criteria remain incomplete because their required evidence or trusted inputs are unavailable.

- Reference-source catalog lists public datasets with specific temporal/spatial and license limitations. It does not acquire data. Dashboard/API import is ready for independently reviewed 0/1/255 GeoTIFFs, but no suitable labels have been obtained.
- A method-evaluation API compares two to eight candidate rasters over identical grids and common-valid support. It does not nominate a winner. No independent labels exist to establish that another classification method is scientifically or empirically justified.
- A bounded river-axis sampling API accepts explicit caller-supplied axis and corridor geometry and reports candidate segments/coverage/quality flags. It does not use OSM as a verified active-channel axis, and no trustworthy axis/bank geometry is available.
- The CWC/NWIC national river-line endpoint advertises a 356,234,820-byte GeoJSON; it was not downloaded. Feature identity, CRS and active-channel fit remain unverified. HydroRIVERS is generalized at ~500 m; GRWL is a static Landsat-derived product; the available Bhuvan WBIS source is a 2016 technical document, not verified event-date target labels.
- Uncertainty is explicitly returned as `null` / `not_quantified`; the width quality/coverage acceptance criterion therefore remains incomplete.
- Checklist remains **64/69 (92.8%)**. Do not mark the five criteria complete until independent labels, method evidence, trusted geometry and defensible uncertainty analysis meet the original acceptance criteria.

**Verification evidence:** backend 88 passed (one existing Starlette/httpx deprecation warning), Playwright 15 passed, frontend build passed (1,593.08 kB main-JS advisory), project-venv `pip check` clean, and 15 acquisition-disabled API smoke requests returned HTTP 200. No satellite acquisition or data download occurred.

## Phase E — Candidate component-size sensitivity

**Status:** Software workflow implemented and evaluated on the actual NISAR A_009 candidate raster; scientific cleanup remains unsupported.

- [x] Create separately stored component-size scenario masks without modifying the canonical candidate or its NoData.
- [x] Evaluate tested 8-connected 2/5/10-pixel scenarios on the real A_009 candidate.
- [x] Expose parameters, comparison counts, quality caveats and scenario downloads.
- [ ] Select or recommend a scientifically justified cleanup threshold; this remains blocked without independent labels.

**Acceptance evidence:** The real source has 3,885,882 candidate pixels and 550,634,840 NoData cells. The 2/5/10 scenarios reclassify 89,437 / 202,003 / 283,567 candidate pixels, respectively; every generated mask retains the complete NoData count and source grid. All results are explicitly sensitivity scenarios, not validated cleanup or noise removal. Full tests: 79 backend and 12 browser tests passed.

## Phase A — Deterministic AI Analysis

**Status:** Complete and verified

- [x] Add a typed API for deterministic, rule-based river analysis.
- [x] Base every reported value on the selected river's persisted acquisition catalog.
- [x] Report coverage, valid/no-data support, candidate outputs, NISAR polarization and threshold diagnostics, optical comparison context, and temporal-comparison eligibility.
- [x] Explicitly distinguish unavailable validation from candidate observations and avoid unsupported change claims.
- [x] Integrate a responsive dashboard panel with river/product selection, loading, error, and empty-data states.
- [x] Add backend and browser regression tests for populated and empty catalogs.
- [x] Document the endpoint and interpretation limits.

**Acceptance evidence:** 68 backend tests, production build, 7 Edge browser tests,
and an automatic-acquisition-disabled smoke test against the persisted catalog passed.

## Phase B — Remaining Feasible Data and Workflow Investigation

**Status:** Feasible software work complete; temporal comparisons are exploratory, while independent interpretation remains evidence-blocked

- [x] Review prior Sentinel-2 catalog/pixel inspections for additional independent
  reference evidence; the available NDWI product remains exploratory and is not
  independent ground truth.
- [x] Inspect the existing output controls and persisted products; download links
  are conditional on actual result URLs and available output records.
- [x] Inspect actual same-river Sentinel-1 mask grids, chronology, and thresholds
  for compatible temporal pairs.
- [x] Determine whether additional Sentinel-2 acquisitions provide genuinely new,
  spatially distributed optical evidence; do not treat NDWI as independent labels.
- [x] Process separate, NoData-preserving candidates for the 2026-11-06 43PER,
  43PES, 43PFS, and 43PFT tiles; expose per-tile metadata, map previews and
  downloads without changing the existing 43PGT output.
- [x] Discover compatible same-river Sentinel-1 candidate pairs and produce
  provenance-bearing comparisons only for chronological, exact-grid pairs with
  matching product, polarization, filter, and threshold method.
- [ ] Keep classification validation, bank extraction, width, flood, erosion and
  deposition claims blocked absent appropriate methods and independent evidence.

**Acceptance evidence:** The live catalog exposes five compatible Kaveri and one
compatible Tungabhadra Sentinel-1 candidate pair. Exact-grid comparisons report
common-valid pixels/area, source products and dates, thresholds, filtering,
seasonal context, and caveats. Real comparison masks and PDF reports returned
HTTP 200 from the download APIs. Outputs remain explicitly unvalidated candidate
differences; no independent labels or hydrological claims were created.

The STAC screen returned 11 items from 2026-11-05 through 2026-11-09. Four
additional 2026-11-06 tiles were processed from bounded COG reads. They contain
788,166 (43PER), 1,630,335 (43PES), 1,972,759 (43PFS), and 1,266,000 (43PFT)
common-valid NISAR-grid pixels. These are exploratory optical supports, not
ground-truth labels; per-item support overlaps and must not be summed.

## Phase C — Final Verification and Handoff

**Status:** Feasible software verification and final report complete; evidence-dependent scientific tasks remain blocked

- [x] Run backend tests, frontend build, browser regressions, API checks, dependency
  checks, and Git whitespace checks.
- [x] Update progress, checklist, changelog, audit, and handoff from verified results.
- [x] Create `FINAL_PROJECT_COMPLETION_REPORT.md` after feasible tasks were done
  and every remaining blocker is accurately stated.

**Acceptance evidence:** Latest verification: 79 backend tests passed (one existing
Starlette/httpx deprecation warning), 12 Playwright browser tests passed, and the
production build passed with a 1,572.54 kB main-JS advisory. `pip check` found no
broken requirements; catalog, deterministic AI, temporal-pair, comparison, and
download API smoke checks passed with automatic acquisition disabled. No
independent reference labels were available and no validation scores were
created. See `FINAL_PROJECT_COMPLETION_REPORT.md`.

## Phase D — Independent-validation workflow

**Status:** Software workflow implemented and tested; scientific validation remains blocked by unavailable independent labels.

- [x] Add provenance-bearing validation status, upload, and report API endpoints.
- [x] Compare bounded 0/1/255 GeoTIFF masks on common valid support with categorical nearest-neighbour alignment.
- [x] Gate metric output on overlap and representation of both reference classes.
- [x] Integrate pending, loading, error, report and caveat states in the dashboard.
- [ ] Obtain and review suitable independent labels before claiming scientific validation or interpreting any scores.

## Known scientific blockers

- No independently reviewed, event-date water reference labels currently exist.
- The inspected near-date Landsat patch is too ambiguous at 30 m for defensible
  manual water-boundary labeling.
- Many same-river Sentinel-1 candidate rasters have incompatible transforms
  (and one Tungabhadra raster uses a different UTM zone) and are rejected. Six
  exact-grid pairs pass declared compatibility checks, but comparison results
  remain unvalidated and do not establish accurate co-registration or change.
- Existing NISAR and Sentinel-2 classifications remain unvalidated candidates.
- Automated centerline-normal width sampling is deferred because the available OSM line is not a verified active-channel axis and no independent bank geometries are available.
- Real satellite candidate products do not establish erosion, deposition, flood
  detection, or validated riverbank change.
