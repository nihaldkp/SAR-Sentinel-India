# SAR Sentinel India — Session Handoff

**Updated:** 2026-11-10

**Workspace:** `D:\SAR-Sentinel-India`

## Source verification and snapshot review — current checkpoint

The official [CWC CKAN record](https://nwdp.nwic.gov.in/api/3/action/package_show?id=river-line)
currently identifies this [KML download](https://nwdp.nwic.gov.in/dataset/3209962f-d0ff-45b8-910a-209bf69a0ccf/resource/e73dec66-cb5b-45e7-9a18-0c1b2199a9c2/download/river_network.kml)
(261,635,405 bytes; resource last modified 2025-11-17 06:29:59.448604;
metadata modified 2025-11-17 06:37:34.622058). The version and checksum fields
are empty; those timestamps are not a verified dataset release version. The
general [copyright policy](https://nwdp.nwic.gov.in/footer/copyrightPolicy)
permits accurate, non-misleading reproduction with prominent attribution,
except identified third-party material. Dataset-specific third-party status,
redistribution conditions, stable ID guarantees, feature resolution and
coverage exclusions are not documented by that record and remain unresolved.

The KML standard specifies geographic longitude/latitude coordinates; one
actual Balijan sample contains a LineString and source attributes OBJECTID,
UID_River, basin, sub-basin, states and start/end districts. The importer
preserves these and stores a MultiLineString with longitude/latitude ordering;
no projected-to-geographic transformation was performed or verified. The
metadata also says WGS84 datum and LCC without projection parameters; the
GeoJSON CRS and all-source geometry types remain unverified. A single feature
cannot establish ID stability, national coverage, district coverage, or the
accuracy of the dataset's CRS. Start/end district is not traversed-district
coverage. Do not equate catalogue entries with monitored rivers.

`backend/app/services/nwic_snapshot_review.py` stages snapshots separately
from the live explorer and retains source/version/fingerprint, progress,
timestamps, errors, prior completed review snapshot and review status.
Per-feature SQLite transactions support resumption; completed snapshots
can be compared in pages for ID presence, changed attributes/geometry and
changed UID_River. Matching OBJECTIDs are provisional, not verified identities.
No automatic promotion, removal, identity approval, active catalogue rollback
or full reconciliation is implemented. Legacy active imports remain separate;
their old history is not migrated into review snapshots. Staging an existing
source again is needed to compare it. A sidecar SQLite lock serializes
cooperating stage and legacy import processes; contention fails immediately
with a retry message, and OS process exit releases the lock. Preserve the
sidecar and do not assume network-filesystem locking semantics.

CLI from backend: `python -m app.import_nwic_rivers PATH --source-version LABEL
--stage-review [--max-features N]`; use `--history`, `--compare OLD_SHA NEW_SHA
[--offset N --limit N]`, and `--abandon SHA` to preserve an unusable incomplete
snapshot while allowing a different one. Abandonment is irreversible; reports
need review and do not constitute permission to publish. A failed/incomplete
snapshot blocks other staged inputs until resumed or abandoned. Metadata
timestamps and fingerprints identify input bytes, not provider authenticity.
Input change detection uses file metadata and cannot detect adversarial
same-size/timestamp mutation. Per-feature transactions, hashing and replay
from the beginning need national-scale benchmarks.

The genuine bounded Balijan extract was staged in the existing isolated
session database; one feature, unchanged self-comparison, and existing API
visibility were verified. This is not a second release or evidence of ID
stability. A cross-process test interrupted a staging worker after a committed
feature, verified same/different imports were rejected during its lock, and
resumed after process termination. Fixture comparisons cover add/remove,
attribute, geometry and UID conflicts; these are not real-version evidence.
Focused backend tests: 20 passed with one Starlette warning. River Playwright:
21 passed; production build passed with a chunk-size warning; Python
compilation and `pip check` passed.

**Status:** source partially verified; review staging tested; one sample
imported in isolation; national dataset not acquired, imported or accepted.
Phase 1 remains unchecked. **Next:** obtain authoritative dataset-specific
rights, full CRS/schema/coverage and identifier/version guarantees, and a
second genuine version where available. Implement reviewed identity decisions,
atomic live snapshot promotion and rollback preserving all prior versions,
migrate/associate legacy imports, test concurrent/interrupted publication and
measure national-scale performance before importing a full source. Current
legacy importer can expose incomplete first imports and is not publication-safe.

## NWIC explorer continuation — partial, current resume point

This checkpoint supersedes the older statements below that there is no NWIC
API or map integration. The [NWIC copyright policy](https://nwdp.nwic.gov.in/footer/copyrightPolicy)
permits accurate reproduction free of charge with prominent acknowledgement,
excluding identified third-party copyright and misleading use. Dataset-specific
third-party status, resolution, completeness and ID stability remain unverified.

The existing SQLite catalog now has paginated `/api/river-network/features`
search by name or source ID, basin, sub-basin, state and endpoint district, and
bounding-box overlap filtering; `/api/river-network/features/{id}/geometry`
retrieves one geometry. The dashboard NWIC explorer uses these endpoints,
shows source attribution and unknown monitoring status, preserves selection
across filtering/pagination, and cancels pending geometry requests on pilot
selection. Monitoring controls remain attached to the separate pilot selector;
NWIC selection does not enable processing. Alias/type filtering, verified
topology, complete district coverage and exact spatial intersection are absent.

The importer now atomically refuses a second input fingerprint in a catalog,
preventing mixed snapshots and destructive provenance replacement; this is a
safety restriction, not an update/reconciliation mechanism or a full worker
lock. Same-fingerprint concurrent workers may fail on checkpoint contention.
There is no dry-run or national-scale performance/concurrency validation.

The previously acquired bounded Balijan Placemark extract was imported into
`C:\Users\nihal\.copilot\session-state\3af747e8-a07c-48f9-a0c6-8633f6ee57da\files\nwic-explorer-real-sample.sqlite3`
only: one feature, OBJECTID 1. Its SHA-256 identifies the wrapper extract, not
the national KML. Real API search/geometry and a local browser selection
displayed Balijan with unknown monitoring; no national project data was
imported. Temporary servers were stopped and acquisition scheduling disabled.
Focused importer/explorer/pilot backend tests: 17 passed, one deprecation
warning; mocked river Playwright: 21 passed; production build passed with a
chunk-size warning. `pip check` and Python syntax compilation passed before
the final importer guard; targeted backend tests passed afterward.

**Exact resume:** implement and test source-version history and explicit
reconciliation, robust cross-process import behavior, input mutation and
interruption cases, dry-run and performance with a safely acquired source.
Verify dataset-specific rights, schema, aliases, identifiers and resolution;
only then consider full-source import. Integrate the paginated explorer with
pilot selection and general processing rather than treating map display as
monitoring. Test real imported records at scale, selection and pilot
compatibility. Phase 1 remains unchecked; full data is not present.

## 2026-11-10 — NWIC source and import prototype checkpoint

The [NWIC CKAN metadata](https://nwdp.nwic.gov.in/api/3/action/package_show?id=river-line)
identifies CWC's River Network, modified 2025-11-17, with KML (261,635,405
bytes), GeoJSON (356,234,820 bytes), and zipped shapefile (74,588,261 bytes).
The stated geographic bounding box is 6–37°08′N, 68–98°E, not proof of
complete coverage. The metadata says WGS84 datum and LCC, without complete LCC
projection parameters or resolution. A bounded GeoJSON range showed projected
coordinates (millions), so do not treat that GeoJSON as longitude/latitude.
Its exact CRS remains unverified. A bounded KML range exposed a complete first
Placemark, Balijan, OBJECTID 1, UID_River 28, Brahmaputra / Brahmaputra Upper,
and KML longitude/latitude geometry; `Confluence` was a name, not a verified
topological ID. Do not infer district-wide coverage from start/end districts.
Aliases, full schema/coverage and identifier stability remain unverified.

The portal labels the dataset `Other (Open)` but no specific use or
redistribution license terms were identified. Do not claim permission to
redistribute. HydroRIVERS' official page permits scientific, educational and
commercial use subject to its license; its Asia download is 103 MB GDB or
91 MB shapefile and its 15 arc-second / 10 km² or 0.1 m³/s thresholds exclude
smaller features. Source license terms and data suitability must be checked
before distribution; no full dataset was downloaded.

Implemented `backend/app/services/nwic_river_import.py` and CLI
`python -m app.import_nwic_rivers PATH --source-version VERSION [--max-features N]`
from the backend environment. It streams local NWIC KML after a SHA-256 pass,
checkpoints each validated Placemark in the existing satellite SQLite database,
stores source metadata and serialized source Placemark, indexes bounds in an
R-tree, resumes by fingerprint and ordinal, rejects duplicate IDs and refuses
changed cross-version identity conflicts. It does not modify pilot records.
On resume it hashes and scans from the beginning; per-feature transactions and
the entire feature geometry can be expensive. It does not provide verified
aliases, topology, full update reconciliation, national-performance testing or
a database-backed API. Import input/version authenticity is operator-declared;
file-stat checks are not a security guarantee. Concurrent different-version
imports are not validated; run one importer at a time. Avoid importing the full
source until data terms, exact schema, version identity and operating behavior
have been reviewed.

An actual first KML feature was copied from a bounded HTTPS range into a KML
wrapper and imported only into an isolated session test database, not the
project catalog; it is not a national dataset import. Focused importer and
existing API tests: 15 passed, one Starlette warning. Existing API/UI still
show only the two pilots; no database explorer, national map selection or
production build was tested this turn. No Phase 1 box changed.

**Exact resume:** continue Task 2 in `backend/app/services/nwic_river_import.py`:
validate full source schema and ID stability, harden concurrent imports and
update/conflict handling, add interrupt/malformed/input-change tests and
measure bounded import on authorized source data. Then implement paginated
backend search/filter/bbox endpoints and connect the existing frontend search,
selection and on-demand geometry; test genuine records and pilot compatibility.
Clarify dataset terms before storing/distributing full national data. Run
focused importer/API/Playwright tests and the production build after UI changes.

## 2026-11-10 — National platform phase 1 checkpoint

The map's existing `/api/rivers` selector now has case- and accent-insensitive
name/display-name/ID search. It preserves the current map selection when a
filter excludes it and explicitly reports no matches. This is client-side
search of the existing two pilot records, not a paginated, database-backed
national explorer. No river data was imported and no monitoring was added.
Real local API/browser smoke confirmed two pilot rivers and search filtering,
with automatic acquisition disabled. Mocked rivers Playwright suite: 19 passed;
backend `test_api.py`: 12 passed; full backend: 159 passed, 1 skipped (Windows
symlink privilege); production build passed with a chunk advisory. Temporary
local API and frontend servers used for the smoke were stopped.

HydroRIVERS official product page states 15 arc-second source resolution,
10 km² catchment or 0.1 m³/s flow thresholds, and links a license governing
redistribution; it excludes smaller streams and is not complete national
coverage. NWIC's river-line portal is a lead, but feature schema, coverage and
specific license terms remain unverified. No bulk source was downloaded.

**Resume phase 1:** inspect the CWC/NWIC source's actual metadata/schema and
licensing via bounded requests; design and implement a resumable spatially
indexed catalog import with source IDs, names, topology and conflict provenance.
Integrate paginated selection and geometry fetch into the existing map without
claiming unprocessed rivers are monitored. Existing analysis and acquisition
services use `RIVER_CATALOG` and remain pilot-limited. Test import idempotence,
pagination, geometry, aliases, topology, failure/recovery, API and live map
before moving to agriculture. No satellite product was downloaded or reprocessed.

Phases 2–9 (agriculture, forest, earthquakes, InSAR, combined analysis, AI,
integrated dashboard, architecture and full acceptance) remain incomplete;
do not treat existing preview pages as implemented monitoring modules.
Scientific checklist remains 64/69; independent validation is still unavailable.

## 2026-11-10 — NISAR connection audit

Live ASF search, local HDF5 metadata, a bounded source-to-output pixel check,
real API and browser display corroborate an existing NISAR GCOV candidate.
See [NISAR connection audit](./data/NISAR-CONNECTION-AUDIT.md) for product IDs,
sizes, caveats, exact scope and outstanding evidence. No satellite product was
downloaded or reprocessed. Authenticated access and checksums remain unverified.
Catalog recovery can overwrite search status and the HDF5 checker can accept
spoofed structures; do not treat it as authenticated provenance.

The API now includes a conservative catalog-derived NISAR connection summary,
also shown in the dashboard. It does not record live connectivity, authentication,
successful search timestamps, full match totals or precise last errors; those
remain unknown or unavailable. Counts are catalog claims, including no-data
processing results. Next: persist sanitized per-attempt evidence, verify
authenticity and checksum, and test genuine retrieval and synthetic rejection.

Prior interrupted work added time-separation provenance to validation results
and dashboard without changing scientific eligibility. Checklist remains 64/69
with all five scientific items open. Latest tests: focused validation 41 passed,
1 skipped; backend 159 passed, 1 skipped; Playwright 18 passed with mocked APIs;
production build passed with a chunk-size advisory. Skip: Windows symlink
privilege. Live API and browser confirmed the summary; acquisition stayed disabled.

## 2026-11-10 — National river request and bound calculation checkpoint

- **National coverage is not implemented.** The current `/api/rivers` reads two OSM records from the static GeoJSON, not a paginated database. In-process acquisition-disabled API smoke returned HTTP 200 for health, rivers and acquisitions; rivers reported **2 features, 2 unique IDs, 2 nonempty line geometries**: Kaveri and Tungabhadra. Basin/sub-basin, tributary relationships and national coverage counts were not measured and must not be invented.
- The frontend selector now derives options from the API catalog instead of a fixed two-item list; observation/analysis selection uses catalog membership. It explicitly states that a registered centerline does not establish monitoring coverage. This is not a searchable/paginated national explorer or general monitoring: schemas, services, UI workflows, acquisition and AI still contain two-river restrictions. Mocked third-river test exercises map selection only, not processing.
- Source investigation: [CWC river network](https://nwdp.nwic.gov.in/dataset/river-line) / [GeoJSON listing](https://nwdp.nwic.gov.in/dataset/river-line/resource/6e552705-842d-40a4-92b2-8506bb66df2a) describes river lines, last updated 2025-11-17, license “Other (Open)”; detailed classification, completeness, update/version and redistribution terms need verification. [HydroRIVERS v1](https://www.hydrosheds.org/products/hydrorivers) is 15 arc-seconds and selects at least 10 km² catchment or 0.1 m³/s mean flow, so excludes smaller mapped streams. No national dataset was downloaded or imported. Survey of India, India-WRIS, state sources, conflict resolution and licensing remain unreviewed.
- The interrupted prior continuation added `POST /api/analysis/bound-assessment-reservations/{id}/calculate`, backed by `bound_assessment_calculations` and immutable-result triggers in the existing reference SQLite DB. It checks reserved identity, current attestation and raster hashes, then computes and commits common-support counts under `BEGIN IMMEDIATE`, using the existing process-local reviewed-comparison lock. Repeat calls return the stored result while the reservation remains eligible. Withdrawal blocks or follows the transaction and rejects the reservation; after withdrawal, calls do not return the calculation as current. It produces no metrics or report. A worker crash during calculation rolls the transaction back; retry succeeds. It holds a write lock through computation, potentially blocking other writers for the 5-second timeout; not suitable as a scalable general job architecture.
- **Bound evaluation and crash-safe report publication are still incomplete**: no evaluation-running lifecycle, result publication, report checksums/recovery, supersession, AI or UI linkage. No generic river processing or independent scientific validation was established. Existing legacy validation remains unbound. The new calculation is not an accuracy report.
- Validation with acquisition disabled: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_bound_reservations.py backend\tests\test_reference_lifecycle.py backend\tests\test_windowed_validation.py -q`: **30 passed**. Full `backend\.venv\Scripts\python.exe -m pytest backend\tests -q -rs`: **156 passed, 1 skipped**, missing Windows symlink privilege; Starlette/httpx warning. From `frontend`, `PLAYWRIGHT_CHANNEL=msedge` and `npm.cmd run test:e2e`: **17 passed**, mocked responses; `npm.cmd run build` passed with chunk-size advisory. `pip check`, `compileall` and direct changed-file trailing-whitespace scan passed. A shared browser tab had stale connection-refused events; no fresh live browser verification was claimed.
- Changed in these continuations: `backend/app/schemas/reference_lifecycle.py`, `backend/app/services/reference_lifecycle.py`, `backend/app/api/routes.py`, `backend/tests/test_bound_reservations.py`, `frontend/src/App.jsx`, `frontend/tests/e2e/rivers.spec.js`, README and project trackers. Git shows project files untracked; `git diff --check` alone does not inspect them.
- **Next:** finish and test transactional bound evaluation and recoverable report publication before AI/validation integration, as requested by the prior ordered milestone. In parallel planning for the newly requested national catalog, verify source access/license and inspect authorized local source schemas; design bounded, resumable import, source-specific stable identity and topology, geometry/index storage and paginated search without changing existing real catalog or implying monitored coverage. Do not fetch satellite data or bulk river data without assessing licensing, size and operational impact. Checklist remains 64/69; it does not represent national completion.

## 2026-11-10 — Expanded platform continuation in progress

- The new request prioritizes bound evaluation and recoverable publication before any new monitoring module. Current disk inspection confirms reservation-only SQLite state and a separate, side-effect-free windowed calculation; existing JSON evaluations remain unbound.
- Baseline with acquisition disabled: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_bound_reservations.py backend\tests\test_reference_lifecycle.py backend\tests\test_windowed_validation.py -q` returned **25 passed**, one Starlette warning. Git reports project files untracked.
- Next implement and verify an intermediate, SQLite-authoritative bound calculation without publishing scores or reports; do not imply this satisfies bound evaluation or the crash-safe publication gate.

## 2026-11-10 — Transactional reservation foundation (milestone incomplete)

- Implemented reservation-only `POST /api/analysis/bound-assessment-reservations/{assessment_id}` and GET for the reservation and `/events`. Inputs: caller-generated UUID, `reference_id`, candidate GeoTIFF and `WindowedValidationMetadata` as `metadata_json`. No endpoint executes this reservation or writes/serves a report. Existing legacy validation remains separate and unchanged.
- The reference SQLite database lazily gains `bound_assessments` and append-only `bound_assessment_events` plus triggers protecting input columns and historical deletion. Under `BEGIN IMMEDIATE`, reservation checks the current attestation, candidate selection/version and reference dataset/acquisition, reviewer declaration, hashes, exact grids, uint8/NoData 255, masks/labels and resolution; it saves metadata, attested reference record, hashes and candidate raster BLOB in one commit. Candidate and reference are limited to 2 million pixels each and 100 MB combined; reservations have a separate 1,000-record / 1 GiB BLOB quota. Existing reference bytes are not duplicated for each reservation.
- A retry with the same UUID and identical metadata, candidate hash and reference ID returns the existing state, including a rejected state; incompatible retries fail. On withdrawal, pending reservations and their events are rejected in the same SQLite transaction as the reference transition; no new UUID can reserve the withdrawn record. Imported/review-pending/rejected references also cannot be newly reserved. Stored snapshots are not authentication, independent evidence or a score.
- `sqlite3` uses its existing 5-second busy timeout and default configured journal mode; this change does not enable WAL. Reservation and withdrawal use only the shared reference database write lock, not the legacy report lock. The transaction holds the lock while it reads/validates the bounded reference; busy requests can fail explicitly. Local cooperating processes are covered, not distributed hosts or adversaries able to alter the DB/schema. Existing path, symlink/junction and TOCTOU issues and lack of authentication remain; do not expose to untrusted users.
- New fixture-based tests verify API retry/withdrawal, mismatch/NoData/grid/reference tampering, persisted events, DB immutable-input triggers, rollback of withdrawal if event insertion fails, integrity check, and spawned-process withdrawal/reservation, same-ID duplicate reservation and conflicting-input reservation races. No real reference labels were imported; no new live API server or browser check was performed.
- Extracted the windowed computation from the legacy JSON write and verified its calculated counts match the persisted path without creating a report. This private calculation helper is not a bound evaluator; callers must enforce input size, review and concurrency safeguards and must not expose its legacy report URL as an existing report.
- Latest focused test: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_bound_reservations.py backend\tests\test_reference_lifecycle.py backend\tests\test_windowed_validation.py backend\tests\test_validation.py backend\tests\test_ai_analysis.py -q -rs` **71 passed, 1 skipped**. Full `backend\.venv\Scripts\python.exe -m pytest backend\tests -q -rs` **151 passed, 1 skipped**. Both used `SAR_AUTO_ACQUISITION_ENABLED=false`; skip is Windows symlink privilege; Starlette/httpx warning persists. `pip check` and `compileall` passed.
- **Stopping gate NOT met:** no bound evaluation, running/failure/recovery/report states, report checksum/atomic publication, crash-point recovery, process-race evaluation tests, during-evaluation revalidation, automatic supersession, small/windowed integration, AI or UI. Legacy reports cannot be considered protected by these reservations. No scientific validation or new evidence. Checklist stays 64/69.
- **Exact next step:** implement a DB-authoritative conditional running/result state using the extracted calculation with explicit size, review and concurrency guards, input rechecks and withdrawal policy, followed by derived-report write/checksum/recovery protocol and fault-injection tests. Preserve JSON history and never serve a report until DB state and checksum authorize it. Re-run the entire backend suite after each stage; do not wire AI/UI until the stopping gate is demonstrated.

## 2026-11-10 — Transactional integration milestone started

- Baseline with acquisition disabled: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_reference_lifecycle.py backend\tests\test_windowed_validation.py backend\tests\test_validation.py backend\tests\test_ai_analysis.py -q` returned **65 passed, 1 skipped**, Starlette warning. The skip is the known missing Windows symlink privilege.
- All repository files remain untracked. Current storage: bound references/review/eligibility snapshots use one SQLite database; windowed assessments calculate and immediately write an independently authoritative JSON report, and evaluation updates JSON behind a different SQLite mutex. The small path also writes JSON and resamples. Neither path resolves a bound reference, so neither is safe to call inside a reference transaction as though SQLite and JSON commit atomically.
- Implementing a separate transactional reservation foundation first. It must not be presented as evaluation: execution, immutable publication/recovery, supersession, and integration still require implementation and tests.

## 2026-11-10 — Identity-check continuation (partial)

- Added `POST /api/analysis/bound-references/{id}/eligibility` for a reuploaded small candidate and caller-selected identity. It checks all declared identity fields, an available processing version, candidate SHA-256, stored-reference SHA-256, exact CRS/grid, and attestation state. It records both passing and well-formed mismatch outcomes in SQLite; GET returns the latest 100. Total audit quota: 10,000 checks. Invalid requests are rejected and are not audit events.
- The snapshot and reference transitions acquire the same local SQLite `BEGIN IMMEDIATE` lock; a spawned-process check/withdrawal race passed. A check may validly pass before a withdrawal and becomes stale immediately afterward. `identity_review_checks_passed` is deliberately not an evaluation authorization: no thresholds, sample adequacy, independence or catalog-authenticated identity are checked. Inputs remain subject to the 2-million-pixel and 100 MB limits.
- No evaluation, supersession, AI or UI integration was implemented. The legacy small and windowed evaluation paths still accept separate operator declarations and do not enforce bound-reference checks. Reference SQLite and report JSON use different coordination; do not wire them with a check-then-evaluate race or claim an atomic cross-store transaction. There is no authentication or ownership; do not expose this API to untrusted users.
- Final validation with `SAR_AUTO_ACQUISITION_ENABLED=false`: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_reference_lifecycle.py backend\tests\test_windowed_validation.py backend\tests\test_ai_analysis.py -q`: **34 passed**; `backend\.venv\Scripts\python.exe -m pytest backend\tests -q`: **145 passed, 1 skipped**, Starlette/httpx warning. From `frontend`, `PLAYWRIGHT_CHANNEL=msedge` and `npm.cmd run test:e2e`: **16 passed** (fixture/mocked responses); `npm.cmd run build`: passed with 1,603.18 kB chunk advisory. `backend\.venv\Scripts\python.exe -m pip check`: clean; `compileall` succeeded; editor problems: no errors on changed Python files.
- In-process TestClient with acquisition disabled returned 200 for `/api/health`, `/api/rivers`, `/api/acquisitions`, and `/api/analysis/bound-references`. The actual lifecycle database was absent, so its integrity was not checked. No current-turn real browser test, genuine reference import, real accuracy result or new real-scene comparison was performed. Historical real-data observations below were not reverified here.
- The skipped backend test requires symlink-creation privilege unavailable on this Windows account. Git reports all project files untracked; `git diff --check` passes but cannot check them. A direct trailing-whitespace scan of all 12 changed files found none. Checklist remains 64/69; scientific evidence is still missing.
- **Next exact step:** design one transactional persistence and locking protocol binding reference ID, full selected identity and current candidate/reference hashes to assessment creation and evaluation, including withdrawal/invalidation and crash recovery; require reupload or verified catalog access at evaluation. Add process-race, rollback and old-report tests before wiring both reviewed routes, AI and UI. Then complete supersession, remaining security and real-browser audit.

## 2026-11-10 — Integration continuation started

- Read the full handoff, current lifecycle, evaluation, AI and route implementations, scientific investigation and project trackers. Git reports project files untracked; preserve everything. Acquisition is disabled for tests.
- Baseline `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_reference_lifecycle.py backend\tests\test_windowed_validation.py backend\tests\test_ai_analysis.py -q`: **31 passed**, one Starlette warning. Existing controlled tests are fixtures; prior live A_009 observations are recorded below.
- Current risk: reference review uses one SQLite database while assessment outcomes use separate JSON files and a different SQLite mutex. A check at submission alone cannot protect evaluation against concurrent withdrawal or altered reference bytes. Existing legacy validation accepts separately submitted reviewer declarations and is not linked to bound references. Do not treat either workflow as authenticated or silently claim end-to-end integration.
- Next: implement independently testable, fail-closed eligibility and identity checks, then wire only where review and input revalidation can be protected against concurrent transitions. Preserve legacy behavior explicitly and document any remaining gap.

## Latest continuation — cross-process transitions and reference lifecycle (partial)

- Current continuation preserves all data and uses `SAR_AUTO_ACQUISITION_ENABLED=false`. Windowed assessment evaluation/rejection now acquires a SQLite `BEGIN IMMEDIATE` lock around read/atomic JSON replacement, with the transition history stored in the same JSON report. Separate spawned-process evaluate/evaluate and evaluate/reject tests passed; the lock serializes cooperating workers on the same local SQLite file only, not distributed hosts or direct file writers. SQLite and the JSON are not a single database transaction; a saved JSON outcome remains authoritative if releasing the lock fails. Existing reports load with an empty transition list. `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_windowed_validation.py -q`: **9 passed**, one Starlette warning.
- Added API-only bound-reference records: submit candidate/reference GeoTIFFs, declared river/product/sensor/acquisition/version and reference source/provenance; candidate and reference SHA-256, reference CRS/grid/counts and import time persist with the reference bytes in a separate SQLite database. Version may be null for unknown. Import is unreviewed; pending, attestation, rejection and withdrawal are explicit transaction-protected transitions with history, and reviewer identity/source independence remain unauthenticated. Inputs are currently limited to 2 million pixels each and 100 MB combined; SQLite reference payload quota is 1 GiB and 1,000 records. URL sources with query/credentials are rejected and errors omit submitted inputs. A separate-process attest/reject race test passed.
- Crucial limitations: this new API-only record is **not wired to existing validation, AI or frontend**, so evaluations do not yet bind to these reference IDs or verify reference fingerprints, and existing AI reference status does not include them. No automatic stale/superseded links or reference/candidate change invalidation exists. Product/acquisition/version association is operator-declared, not catalog-authenticated. Legacy report and reference workflows remain available and separate. Reference storage does not authenticate users; no user authorization exists. The comprehensive file security audit remains open.
- Sentinel-1 `AcquiredObservation.provider_processing` describes upstream RTC, while the actual `AnalysisResult` contains algorithm parameters and analysis ID but no immutable processor version; do not invent one. Method reports remain unlinked. Actual live UI recheck using local catalog showed A_009 candidate 388.5882 km², deterministic summary, unavailable reference and Sentinel-2 comparison; new lifecycle cannot be live-tested through the dashboard because no controls exist. Controlled lifecycle tests use temporary SQLite and synthetic test rasters only.
- Final commands with acquisition disabled: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_reference_lifecycle.py backend\tests\test_windowed_validation.py backend\tests\test_ai_analysis.py -q`: **31 passed**; `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_validation.py -k 'reference_and_report_listings' -q -rs`: **1 passed, 1 skipped, 30 deselected** (symlink privilege unavailable); `backend\.venv\Scripts\python.exe -m pytest backend\tests -q`: **142 passed, 1 skipped** (Starlette/httpx warning). `frontend` `npm.cmd run test:e2e`: **16 passed** with mocks; `npm.cmd run build`: passed (1,603.18 kB advisory). `backend\.venv\Scripts\python.exe -m pip check`: clean.
- Live local acquisition-disabled API: seven GET endpoints including `/api/analysis/bound-references` and both AI POSTs returned 200; Kaveri 10 and Tungabhadra 4 Sentinel-1 observations; A_009 12,910,080 valid pixels and 388,588,200 m² candidate area; A_010 zero valid pixels and no area. Real browser AI check showed A_009, 388.5882 km², deterministic summary, missing independent reference and Sentinel-2 comparison. Actual import/review/evaluation via browser, full tile overlap, comparison submission, reports, stale/error/loading states were not checked. Controlled API tests use temporary databases and fixtures; no real reference was imported. SQLite consistency-change failure test confirms no review transition is committed on a failed write.
- Next: safely integrate bound references with exact-identity validation and AI/UI; define historical supersession and invalidation under transactional control; complete live checks and comprehensive file/security audit. Do not claim scientific completion.

## Latest continuation — evaluation outcomes and fresh live checks (partial)

- Added operator rejection of a qualifying windowed assessment via `POST /api/analysis/validation/windowed-assessments/{id}/reject` and the existing validation form. A nonempty reason, outcome timestamp and `evaluation_rejected` status persist; terminal assessments cannot be reevaluated or rejected again. Evaluation now timestamps successful outcomes and persists `evaluation_failed` when stored evidence/count consistency checks fail, returning HTTP 422 rather than success. Storage errors cannot reliably record a failure. The locks remain process-local, so simultaneous transitions in different workers can race; there is no authenticated operator identity, initiation record, repeat policy or full nine-state lifecycle.
- AI shows a matching rejected/failed outcome without claiming certification. NISAR linkage still requires matching river/product/date/declared processor version and candidate hash; Sentinel-1 lacks a verified version and method reports remain unlinked. Imported-unreviewed references, review-pending and separate attestation transitions, authenticated identities, fingerprint-change supersession, reference provenance and product-bound lifecycle remain open.
- Confirmed reference metadata reads and reference/validation listing paths previously bypassed checks on their final resolved metadata/report targets. They now reuse containment-checked, identifier-checked reads; a simulated external resolved-target regression passed. The real symlink regression was **skipped** on Windows because `WinError 1314` denies symlink creation. This fix does not close TOCTOU races between checking and opening, does not establish authorization, and is not a comprehensive file-security audit. The application has no user authentication or per-user authorization; UUIDs are not access control. Trust-restrict deployment.
- Fresh live checks used a local Vite server and API with `SAR_AUTO_ACQUISITION_ENABLED=false` and uvicorn `--lifespan off` (no scheduler or startup recovery); no mocked browser responses. Tungabhadra AI selected actual A_009: candidate 388.5882 km², valid support 84.07%, independent reference unavailable, deterministic/no external AI; A_010: zero valid support, 100% NoData, unavailable area. Kaveri AI showed 10 usable Sentinel-1 observations and 2 failed records. Validation workspace displayed pending evidence and its existing mode control. Six GET endpoints and both AI POSTs returned 200; acquisition status disabled; A_009 mask range returned 206 and processing/optical metadata returned 200; invalid report ID returned 422. Sentinel-2 tile overlap, comparison submission, report download, loading and error states were not freshly verified in this live run.
- Tests, acquisition disabled: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_windowed_validation.py backend\tests\test_validation.py backend\tests\test_ai_analysis.py -q`: **53 passed, 1 skipped**; `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_validation.py -k 'reference_and_report_listings' -q -rs`: **1 passed, 1 skipped, 30 deselected**; `backend\.venv\Scripts\python.exe -m pytest backend\tests -q`: **133 passed, 1 skipped** (Starlette/httpx warning). `frontend`: `npm.cmd run test:e2e` **16 passed** with mocked fixtures including rejection; `npm.cmd run build` passed with 1,603.18 kB chunk advisory; `backend\.venv\Scripts\python.exe -m pip check` clean; `git diff --check` passes but excludes untracked files.
- No data downloads or real reference/accuracy results. Checklist remains **64/69**; five scientific criteria remain open. Next exact action: implement a product-bound persisted reference-import/review/attestation lifecycle with explicit authentication limitations, safe transitions and cross-process concurrency; then extend identity linkage and finish the file-serving and live dashboard audits.

## Latest continuation — reviewed assessment, partial audit

- Status: **partial implementation, not a completed engineering/security audit or scientific validation**. Preserve all data and untracked work; no acquisition, download, staging, reset or commit. Automatic acquisition was disabled for tests and API smoke checks.
- Added persisted windowed reviewed assessments and a separate evaluation endpoint/UI step. Inputs must be identical-grid uint8 0/1/255 rasters with validity masks, projected metre CRS and no resampling; even aligned partial overlap is not supported. Counts, class and occupied-block distribution, grid/window provenance, thresholds, reviewer declarations, product/version and SHA-256 fingerprints persist. Qualified scores are calculated only on explicit evaluation; thresholds and attestations do not authenticate review or establish representativeness.
- Limits: uploads buffered before a process-local lock, 100 MB combined input, 512 × 512 windows, 64 MB GDAL cache target, 1,048,576-pixel storage block, 5 billion pixel reads, 2 million distribution blocks, and 180-second cooperative time limit. There is no cross-worker lock, hard memory/deadline guarantee or incremental progress. The previous nearest-neighbour workflow remains and retains its two-million-pixel limit. Real full-scene reviewed validation was not run; a controlled 2,100 × 2,100 test was.
- AI report linking requires matching river, product, acquisition and processing-version declarations and a SHA-256 match to the selected local NISAR candidate mask. Missing, mismatched or over-limit raster identity is reported as unverified. This does not authenticate metadata, reviewer or reference; Sentinel-1 records lack a processor version and legacy reports lack fingerprints. Method-evaluation reports are still not product-bound. Imported unreviewed references, authenticated attestations and persisted failed/rejected evaluations remain unimplemented; there is no nine-state evidence lifecycle.
- Legacy validation now respects internal GDAL validity masks. Read-only inspection found resolved-path containment in several analysis, reference and acquisition routes. This is not a comprehensive file-security audit: symlink/TOCTOU races between resolution and `FileResponse` open, cross-process access, ownership/authentication and all file consumers need review. No new security fix is claimed.
- Latest commands with `SAR_AUTO_ACQUISITION_ENABLED=false`: `backend\.venv\Scripts\python.exe -m pytest backend\tests\test_windowed_validation.py backend\tests\test_validation.py backend\tests\test_ai_analysis.py -q` **48 passed**; three targeted file-safety tests **3 passed**; `backend\.venv\Scripts\python.exe -m pytest backend\tests -q` **128 passed** (one Starlette/httpx warning). `npm.cmd run test:e2e` **16 passed** (mocked API fixtures, including both assessment and evaluation); `npm.cmd run build` passed with a 1,602.18 kB chunk advisory. `pip check` found no broken requirements. `git diff --check` passes but excludes untracked files; a direct touched-file trailing-whitespace scan found none.
- In-process local API smoke: six GET endpoints and AI summaries for both rivers returned 200; acquisition disabled. Catalog: 10 Kaveri and 4 Tungabhadra Sentinel-1 observations, 2 Tungabhadra NISAR products. A_009 has 12,910,080 valid pixels and 388,588,200 m² candidate area; A_010 has zero valid pixels and no area. Both AI summaries report no independent reference. This was not a new live-browser integration run; earlier dashboard and Sentinel-2 checks are historical below.
- Checklist remains **64/69**; all five scientific evidence items remain open. No real reference labels or accuracy scores were generated.
- Next exact action: implement a product-specific persisted reference/review/evaluation lifecycle, including imported-unreviewed and failed/rejected states and documented attestation provenance, without trusting declarations; then complete the path/TOCTOU/ownership review and live browser/API verification. Expand large-grid tests, limits, reference coverage and partial-overlap support only when safely designed.

## 2026-11-10 — Windowed comparison and evidence-status continuation

- Status: engineering improvements verified; **the overall scientific and end-to-end audit is not complete**. Preserve all data and untracked changes, keep acquisition disabled, and do not stage, commit, reset, delete or download.
- Exploratory comparison uses aligned common-grid intersection windows, no resampling, 512 × 512 pixels, uint8 0/1/255 and raster validity masks. The 100 MB combined compressed upload limit remains; GDAL cache is set to 64 MB; storage blocks are capped at 1,048,576 pixels, work at 5 billion pixel reads, time at 180 seconds between windows, and concurrency at one comparison per server process. Compressed bytes are buffered, native overhead is not a hard memory cap, GDAL reads cannot be preempted by the cooperative timer, and multiple server processes have independent locks. Only overlap pixels are checked; a result is returned after completion rather than with incremental progress. Reviewed comparison remains limited to two million pixels per input.
- Actual A_009 versus minimum-10-pixel mask returned HTTP 200: 2,193 windows, 12,910,080 shared valid pixels, areas 388,588,200 and 360,231,500 m², 283,567 disagreements and candidate IoU 0.927026. An A_009/Sentinel-2 43PFS partial overlap produced 1,972,759 shared pixels. These are exploratory overlap, not accuracy or evidence of change.
- Final saved-code full-size API repeat returned the same counts and IoU in 4.00 s. Per-process computation is serialized only after uploads are read, so concurrent requests can still buffer uploads before rejection; the cooperative timer cannot preempt a stalled GDAL read.
- AI summary now matches validation reports by river, product ID and acquisition time; exposes absent reference, unreviewed imported reference, attested reference, insufficient labels/overlap, unmet thresholds and completed submitted-sample evaluation states. Reference and report claims are operator-supplied and not authenticated. The current import rejects unreviewed uploads, so that state can only reflect an existing unattested record; there is no separately recorded thresholds-met-but-awaiting-validation state and no basis for an independently authenticated scientific-validation claim. Method-evaluation reports are not linked to the selected candidate, and this remains an engineering limitation.
- A_010 persisted metadata reports zero valid paired pixels in 5,213,075 corridor cells, no mask/area, and 33.26% geometric grid-centerline overlap; grid overlap is not usable acquisition support. SQLite `quick_check` passed; catalog has 10 Kaveri and 4 Tungabhadra processed Sentinel-1 records and 2 Kaveri failures. The 14 local source VV rasters inspected were 1200 × 1200 in EPSG:32643 or 32644 with -32768 NoData. Sentinel-2 masks overlap spatially; do not sum their candidate areas as unique coverage.
- Live local dashboard with acquisition disabled showed A_009's 388.5882 km² candidate and 84.07% valid support, and A_010's unavailable candidate area with 100% NoData; it labels overview metrics demonstration and AI deterministic. Servers used only for this check were stopped. Browser suite uses mocked responses, while this dashboard check used the local API.
- Fixed acceptance of invalid WGS84 axis coordinates and tightened resolved output-file containment in several acquisition and analysis paths. This was not a comprehensive security review; direct raster consumers and other file paths still warrant review, including symlink/TOCTOU behavior.
- Verification: focused validation **29 passed**; focused AI **11 passed**; combined validation/AI/analysis **60 passed**; full backend **120 passed**; Playwright **16 passed** after fixing an initially ambiguous selector; frontend build passed (1,600.56 kB chunk advisory); `pip check` clean. Eight read-only API GETs and both AI summaries returned 200, invalid IDs returned 422/404, and A_009 mask returned 200. One Starlette/httpx warning remains. Git diff check excludes untracked files.
- Checklist remains **64/69**; all five scientific criteria remain open. No reviewed real labels, scientific accuracy, verified widths, new satellite downloads or acquisition jobs were created.
- Next exact step: define and implement a persisted, product-linked pre-validation evidence assessment and authenticated provenance policy before offering the requested “thresholds met, awaiting validation” or independently validated states; then extend reviewed comparison to bounded large-raster processing and finish the remaining file-serving and live-dashboard audit.

## In progress — real-data end-to-end audit (2026-11-10)

- New continuation: exploratory comparison now processes uint8 candidate GeoTIFFs in 512 × 512 windows, allows pixel-aligned partial overlap without resampling, and bounds compressed uploads, source block size, pixel reads and elapsed processing time. Reviewed comparison remains on its original two-million-pixel path. Focused validation suite: 27 passed before final cleanup. Full-size A_009 versus minimum-10-pixel mask returned HTTP 200 in 3.92 s, 2,193 windows and 12,910,080 shared valid pixels; areas 388,588,200 and 360,231,500 m², disagreement 283,567 pixels, candidate IoU 0.927026. This is exploratory overlap, not accuracy. UI/provenance documentation, evidence-state work, boundedness tests and complete regression remain pending; do not treat this stage as finished.
- Current checkpoint: audit remains **in progress**, not a completed end-to-end scientific audit. Workspace content is untracked; preserve it. Automatic acquisition was disabled for backend commands; no source products were altered, jobs started, files staged, or commits made.
- Added operator-declared minimum reference pixels per class, pixel-sized square blocks anchored at the candidate grid's top-left, and minimum occupied blocks per class on common support. Missing or unmet gates withhold reviewed metrics, including on legacy reports without rewriting their files. Occupied blocks do not prove representativeness or independence.
- Added all-pairs candidate area differences, first-method-relative fractions, disagreement and candidate-mask IoU, with unavailable values for zero denominator/union or empty support. Optional exploratory acquisition time and dashboard fields/results were added. Candidate overlap is not accuracy.
- Read-only local inventory found nine named candidate mask TIFFs: A_009 and its three sensitivity masks are 25,660 × 21,962; five Sentinel-2 masks are also larger than two million pixels. All nine declare EPSG:32643, 10 m pixels and NoData 255. SQLite read-only counts: two river scans, 16 acquired products, zero jobs. Persisted validation status is pending with zero reports and zero imported references.
- A bounded in-memory 512 × 512 A_009 crop at row 0, column 15360 compared the original and minimum-10-pixel masks: 14,606 common valid pixels, areas 166,600 and 135,500 m², 311 disagreements, IoU 0.813325. This is exploratory crop overlap, not full-scene or accuracy. A real full-size A_009 API submission returned 422 at the two-million-pixel limit; full-scene method comparison remains unsupported.
- Verification on saved changes: **25 focused validation tests**, **103 backend tests**, **16 Playwright tests**, and frontend production build passed. Python `pip check` passed. Seven acquisition-disabled read-only API smoke requests returned 200; full-size rejection returned 422. Warnings: Starlette/httpx deprecation and Vite 1,599.99 kB main-chunk advisory. Direct whitespace scan passed for changed code and README; `git diff --check` excludes untracked files.
- The initial focused-test attempt with system Python 3.15 failed because pytest was not installed there; the successful runs used the existing project virtual environment, without installing packages.
- Unresolved audit work: trace A_010 and Sentinel-1 provenance and processing, axis/file-serving paths and live dashboard end to end; assess the deterministic AI service's hardcoded `independent_reference_unavailable` status if references or reports later exist; design a safely bounded full-scene comparison if required. Five scientific/evidence-dependent checklist items remain open; no real reviewed labels, scientific accuracy, or verified widths were created.
- Next exact action: reproduce the AI status discrepancy using isolated reference/report fixtures and decide product-specific status semantics; continue the acquisition-disabled, read-only audit of A_010/Sentinel-1 and axis/API paths before marking this audit complete.

## Latest handoff — evidence thresholds and candidate-only comparison

- Reviewed current disk contents rather than retrying the earlier failed edits. Reviewed metrics now require operator-declared minimum common pixels and coverage; insufficient or legacy reports without qualifying thresholds have accuracy metrics withheld by the API without altering stored files. Overall status does not treat an insufficient report as completed.
- The existing validation form supports both reviewed evaluation and a candidate-only exploratory comparison; the Analysis workspace links to it. Both show same-support candidate areas and disagreement from the first method. Candidate-only responses have no accuracy scores or winner and are not persisted.
- Reviewed method reports now retain submitted reference metadata, and the reference must declare 255 NoData. Operator declarations and reviewer/source claims are not independently authenticated. Neither thresholds nor exact-grid matching establish scientific validity.
- Verification with automatic acquisition disabled for backend commands: focused validation **18 passed**, full backend **96 passed** (one Starlette/httpx warning), full Playwright **16 passed**, production build passed (1,596.74 kB main-JS advisory). Browser responses for the new UI are fixtures.
- Checklist remains **64/69**; independent labels, empirical method justification, trusted channel geometry and quantified uncertainty remain missing. No scientific results, downloads or acquisition jobs were created; nothing was staged or committed.

## Latest verified handoff — reference workflows and candidate axis sampling

- Checklist: **64/69 (92.8%)**, recalculated from [PROJECT_TASK_CHECKLIST.md](./PROJECT_TASK_CHECKLIST.md). All five remaining boxes remain unchecked: independent validation; empirically justified alternate classification; suitable independent labels; sampling on a trusted channel axis/corridor; and quality/coverage/quantified uncertainty for automated width. Software scaffolding does not fulfill these evidence-dependent acceptance criteria.
- Implemented source-catalog and reviewed-reference GeoTIFF import/list/download APIs and dashboard UI. Import metadata includes source URL, date, CRS/resolution, license, reviewer, review method and limitations. The import validates the 0/1/255 raster conventions and records (but cannot authenticate) review attestation. No real labels are present or claimed.
- Implemented `POST /api/analysis/validation/methods` and a frontend API client. It requires two to eight candidate masks on identical grids and evaluates every method over the same common-valid pixels; it does not select a winner. No alternative classifier has been run or scientifically justified.
- Implemented bounded `POST /api/analysis/width/river-axis` using caller-supplied WGS84 GeoJSON LineString/corridor geometry and integrated its form/results in the Analysis dashboard. It reports candidate segments and coverage/quality flags, requires the corridor to contain the axis, does not infer axis/banks from OSM, and explicitly reports unverified geometry and `uncertainty_status=not_quantified`. It is not a verified width product.
- Checked public geometry leads. CWC/NWIC's direct national river-network endpoint advertises a 356,234,820-byte GeoJSON, so it was not downloaded; feature coverage, CRS and active-channel suitability remain unverified. HydroRIVERS' generalized ~500 m network, static GRWL products, and the 2016 Bhuvan WBIS technical document do not provide verified event-date labels or channel-bank geometry for this task.
- A regression now verifies corridor gaps do not join separate candidate-mask segments. Focused API tests cover source catalog/import, shared-support method comparison, axis coverage and rejection cases.
- Full verification after the latest changes: backend **88 passed**, one Starlette/httpx deprecation warning; Playwright **15 passed**; production build passed with the Vite **1,593.08 kB** chunk-size advisory; project-venv `pip check` found no broken requirements. Acquisition-disabled smoke checks returned HTTP 200 for 15 API requests spanning health, regions, observations, both rivers, acquisitions, analysis/validation/reference data, both river AI summaries and temporal-pair endpoints.
- The first browser run found two strict-mode ambiguities caused by shared labels across the new method-comparison form and existing validation form. The tests now scope selectors to the intended validation form; focused and complete browser reruns passed. A first smoke assertion referenced nonexistent app state after successful responses; the repeat checks the service's actual acquisition flag and passed.
- Files changed in this continuation: `README.md`; `backend/app/api/routes.py`; `backend/app/schemas/analysis.py`; `backend/app/schemas/validation.py`; `backend/app/services/analysis.py`; `backend/app/services/validation.py`; `backend/tests/test_analysis.py`; `backend/tests/test_validation.py`; `frontend/src/components/ValidationWorkspace.jsx`; `frontend/src/services/api.js`; `frontend/src/styles.css`; `frontend/tests/e2e/rivers.spec.js`; `data/INDEPENDENT-VALIDATION-INVESTIGATION.md`; `PROJECT_PROGRESS.md`; `PROJECT_TASK_CHECKLIST.md`; `PROJECT_CHANGELOG.md`; `PROJECT-AUDIT.md`; `PROJECT_COMPLETION_PLAN.md`; `PROJECT_HANDOFF.md`; `FINAL_PROJECT_COMPLETION_REPORT.md`.
- No source satellite products were changed, no labels/metrics were fabricated, no acquisition job/download was started, and nothing was staged or committed. Worktree files remain untracked in Git; direct whitespace scan passed for the changed files. A broad scan found unrelated pre-existing trailing spaces in two diagnostic reports; they were left untouched.
- Next steps require external evidence: obtain event-date independently reviewed labels; use a predeclared design to assess methods; obtain trusted channel-axis/corridor and bank evidence; quantify width uncertainty before presenting automated widths. Until then, keep all five checklist items open.

## Latest verified handoff — NISAR component-size sensitivity

- Checklist recalculated from boxes: **64/69 (92.8%)**. Only the three Phase 5 sensitivity workflow/evaluation items were marked complete; the remaining five items are blocked by missing independent labels or trusted channel geometry.
- Added a POST sensitivity endpoint and matching metadata/download endpoints. Frontend offers 2/5/10-pixel minimum component scenarios; separate outputs preserve the original source, 255 NoData, CRS, transform, and 10 m resolution. API uses bounded sizes, catalog-verified product resolution and fixed output-name allowlists.
- Generated outputs for the existing Tungabhadra A_009 product under `data\acquisitions\tungabhadra\<product-id>\nisar-processing\component-sensitivity\`. Source mask was not modified. At thresholds 2/5/10, candidate pixels reclassified are 89,437 / 202,003 / 283,567; remaining candidate counts are 3,796,445 / 3,683,879 / 3,602,315. Each raster preserves 550,634,840 NoData pixels. These are exploratory parameter sensitivities; no removed pixel is demonstrated to be noise and no cleanup threshold is recommended.
- Full verification: backend **79 passed**, one existing Starlette/httpx deprecation warning; Playwright **12 passed**; production build passed with 1,572.54 kB main-JS Vite advisory; `pip check` passed. API smoke endpoints and all three sensitivity metadata/download routes returned HTTP 200 with `SAR_AUTO_ACQUISITION_ENABLED=0`.
- Initial browser test locator expected a heading while the dashboard uses bold text; corrected locator and reran successfully. An exploratory `npm test -- --list` invocation was blocked by PowerShell policy; final runs used `npm.cmd run test:e2e`.
- Files changed in this milestone: `README.md`, `data/README.md`, `backend/app/services/nisar_gcov.py`, `frontend/src/components/AutomaticAcquisitionPanel.jsx`, `frontend/src/services/api.js`, `frontend/tests/e2e/rivers.spec.js`, `PROJECT_PROGRESS.md`, `PROJECT_TASK_CHECKLIST.md`, `PROJECT_CHANGELOG.md`, `PROJECT-AUDIT.md`, `PROJECT_COMPLETION_PLAN.md`, `PROJECT_HANDOFF.md`, `FINAL_PROJECT_COMPLETION_REPORT.md`.
- No satellite source products or canonical candidate masks were modified. Automatic acquisition remained disabled; no downloads or acquisition jobs were started. Nothing was staged or committed; project files are untracked in Git.
- Remaining tasks in order: independent validation; empirically justified alternative classifier (only if evidence supports one); obtain independent reviewed labels; axis sampling with a trusted axis/corridor; quality/coverage/uncertainty for any future candidate-width samples. Do not use the OSM centerline as verified channel axis and do not claim scientifically validated cleanup or widths.

## Latest verified handoff — compatible Sentinel-1 candidate comparisons

- Checklist recalculated from the actual checked boxes: **61 / 69 (88.4%)**. This is a software/data task count, not scientific validation.
- The persisted catalog currently exposes **five Kaveri and one Tungabhadra** exact-grid Sentinel-1 candidate pairs. Pair discovery and comparison enforce source/product/polarization/filter/threshold-method compatibility, chronology, projected metre grid identity, valid masks and common support.
- Actual Kaveri comparison: 436,083 common-valid pixels; 56,238 candidate gain and 71,969 candidate loss pixels. Actual Tungabhadra comparison: 418,128 common-valid pixels; 47,214 candidate gain and 54,174 candidate loss pixels. These are exploratory unvalidated mask differences only.
- Actual comparison mask and PDF download routes both returned HTTP 200 for each river. AI summary POSTs returned HTTP 200 and reported compatible pair counts 5 and 1, respectively. Automatic acquisition was explicitly disabled; no download or acquisition job was started.
- Full backend suite: **77 passed**, one existing Starlette/httpx deprecation warning. Full Playwright suite: **11 passed**. Frontend production build passed with a 1,569.99 kB main-JS advisory. `pip check` found no broken requirements.
- New functionality includes `GET /api/analysis/temporal-pairs`, strict two-date compatibility checks and provenance-bearing PDF/GeoTIFF outputs, a dashboard pair selector/result panel, and carefully gated recovery of legacy failed rows whose verified persisted outputs predate an `AcquiredObservation` response-schema fix.
- Files changed in this continuation: `README.md`; `backend/app/api/routes.py`; `backend/app/schemas/analysis.py`; `backend/app/schemas/ai_analysis.py`; `backend/app/services/acquisitions.py`; `backend/app/services/ai_analysis.py`; `backend/app/services/analysis.py`; `backend/tests/test_acquisitions.py`; `backend/tests/test_analysis.py`; `frontend/src/components/AnalysisWorkspace.jsx`; `frontend/src/services/api.js`; `frontend/src/styles.css`; `frontend/tests/e2e/rivers.spec.js`; and the progress, checklist, changelog, audit, completion-plan, handoff and final-report documents.
- No source satellite products or candidate masks were modified. Comparison outputs are stored separately. Git reports project files as untracked; nothing was staged or committed.
- Remaining external/scientific blockers: independent reviewed water labels; evidence for cleanup/alternate classification; accurate co-registration and seasonal-normalization evidence for interpreting temporal differences; trusted active-channel axis and bank geometries. Do not claim validation, verified river change, flood, erosion, deposition or bank-to-bank width.
- Exact final commands: from repository root run `& '.\backend\.venv\Scripts\python.exe' -m pytest backend\tests`, `& '.\backend\.venv\Scripts\python.exe' -m pip check`, then in `frontend` run `npx.cmd playwright test` and `npm.cmd run build`. The API smoke used `TestClient` from `backend` with `SAR_AUTO_ACQUISITION_ENABLED=0`.

## Previous continuation — AI provenance and map integration

- Checklist recalculated from actual checked boxes: **57 / 69 (82.6%)**.
- AI Analysis API now returns available product provenance (provider, ID, acquisition range, type, polarization, CRS/resolution, and license/catalog link where available). Signed asset URLs and local paths are excluded.
- The AI dashboard displays selected-product provenance and hides stale measurements until a changed product selection is rerun. Selecting a live ASF discovery result synchronizes the map/dashboard river; if it is not in the persisted processed catalog, the AI panel explicitly treats it as discovery metadata only.
- No LLM provider is configured or integrated; the only supported behavior is the deterministic rule-based summary. There is no separate model fallback to test.
- Dynamic map legends now distinguish selected live catalog footprints and candidate polygons, clarifying that off-polygon areas are not classified.
- Verification so far: backend AI tests **4 passed**; focused Playwright tests **3 passed**; frontend build passed with a 1,565.26 kB bundle advisory. Run full suites after continuing remaining work.
- Temporal investigation remains blocked: existing actual Sentinel-1 candidate rasters have incompatible same-river grids/thresholds, and only one processed NISAR candidate date is available. Same-overpass Sentinel-2 tiles are not a temporal pair. No temporal comparison was produced.
- Remaining feasible work: investigate whether a separate candidate-mask cleanup diagnostic is justified and safely implementable; finish final API/data-integrity audit. Keep independent validation, channel-width claims and temporal results blocked until evidence exists.
- Read-only cleanup analysis of actual NISAR A_009 `candidate-water-mask.tif`: 25,660 × 21,962, uint8, NoData 255, EPSG:32643, 100 m² pixels; counts 9,024,198 non-candidate, 3,885,882 candidate, and 550,634,840 NoData; 160,502 8-connected candidate components. A 2-pixel minimum removes 89,437 pixels; 5 removes 202,003; 10 removes 283,567; 25 removes 397,838; 50 removes 504,298; 100 removes 634,217. No cutoff or output was created because there is no evidence to label the removed parts as noise.

## Latest continuation — Independent-validation workflow integration

- Checklist recalculated from actual checked boxes: **55 / 69 (79.7%)**. This measures checked software/data tasks only, not scientific completion.
- Added `GET /api/analysis/validation/status`, `POST /api/analysis/validation`, and `GET /api/analysis/validation/{validation_id}` with provenance-bearing Pydantic contracts.
- Candidate and reference inputs are bounded single-band GeoTIFF masks (0 non-water, 1 water, 255 uncertain/NoData; both declare 255). The candidate CRS must be projected metres. Reference labels are aligned to the candidate grid with nearest-neighbour. Metrics use only common valid pixels and are returned only if both reference classes occur; insufficient overlap/classes are explicit.
- JSON reports are persisted atomically under `outputs/validation/`; uploaded raster bytes are not retained. Provenance fields do not independently authenticate providers/reviewers, label quality, independence, or sampling design.
- Added the dashboard validation workspace: pending/loading/error states, provenance/file inputs, report metrics and history links, and caveats warning that Sentinel-2 NDWI must not be used as independent evidence. The warning is not an automated provenance check.
- Verification: focused validation tests **4 passed**; full backend suite **75 passed** (one existing Starlette/httpx deprecation warning); Playwright browser suite **9 passed**; frontend build passed (1,562.53 kB main-JS chunk warning); `pip check` found no broken requirements; changed-code whitespace scan passed and `git diff --check` emitted no output. Git lists repository content as untracked, so it does not provide a complete tracked diff.
- No independent labels, validation metrics, satellite downloads, processing jobs, or scientific outputs were created in this phase.
- Files changed in the validation/UI/audit continuation: `backend/app/schemas/validation.py`, `backend/app/services/validation.py`, `backend/app/api/routes.py`, `backend/tests/test_validation.py`, `frontend/src/components/ValidationWorkspace.jsx`, `frontend/src/services/api.js`, `frontend/src/App.jsx`, `frontend/src/styles.css`, `frontend/tests/e2e/rivers.spec.js`, `README.md`, `PROJECT_PROGRESS.md`, `PROJECT_TASK_CHECKLIST.md`, `PROJECT_CHANGELOG.md`, `PROJECT_HANDOFF.md`, `PROJECT-AUDIT.md`, and `PROJECT_COMPLETION_PLAN.md`.
- Reproduction commands from the repository root:
  - `& '.\backend\.venv\Scripts\python.exe' -m pytest`
  - `Set-Location .\frontend; npm.cmd run build`
  - `Set-Location .\frontend; npx.cmd playwright test tests/e2e/rivers.spec.js`
  - `& '.\backend\.venv\Scripts\python.exe' -m pip check`
- Bounded file-serving/map-layer audit found fixed output names and catalog/path constraints, UUID validation for report paths, and existing error/empty-state coverage for downloads, optical previews and unavailable bank layers. No code change was indicated.
- Automated river-axis sampling was assessed and deferred: the available OSM centerline is not a surveyed/verified active-channel axis and there are no bank geometries. Generating width transects from it would introduce unsupported positional assumptions. Existing manual transects remain candidate-water segment estimates, not channel widths.
- **Next exact task:** continue independent remaining engineering tasks without relying on fabricated labels/banks or incompatible temporal inputs. Keep the final completion report pending while feasible tasks remain.
- No long-running backend, development server, download, or acquisition job was intentionally left running.

## Latest continuation — Additional Sentinel-2 tile candidates

- Checklist recalculated from actual checked boxes: **53 / 67 (79.1%)**. Do not describe this as scientific completion.
- The metadata-first screen returned 11 Sentinel-2 L2A items for 2026-11-05 through 2026-11-09. Four same-overpass tiles beyond 43PGT (43PER, 43PES, 43PFS, 43PFT) were processed into distinct exploratory candidate masks under the existing A_009 product's `nisar-processing/sentinel2-observations/<item-id>/` folder. The 43PGT product was not overwritten.
- Common-valid / NDWI-candidate pixels: 43PER 788,166 / 28,194; 43PES 1,630,335 / 122,670; 43PFS 1,972,759 / 931,867; 43PFT 1,266,000 / 32,019. Supports overlap. These are exploratory NDWI candidates, not ground truth or independent validation.
- The existing A_009 metadata API lists these observations. Per-item preview and TIFF routes are integrated in the dashboard with independent visibility/removal and download controls; NISAR layers remain separate.
- `SAR_AUTO_ACQUISITION_ENABLED` is now opt-in; unset means automatic scheduling remains disabled. No acquisition job was submitted.
- Latest verification: full backend suite 71 passed (one existing Starlette/httpx deprecation warning); Edge browser suite 7 passed; frontend build passed (main JS chunk 1,554.55 kB advisory); live metadata/preview/mask requests for each new tile returned HTTP 200; streamed output checks confirmed candidate/non-candidate counts and 255 NoData; `pip check` found no broken requirements; `git diff --check` passed.
- Changed source files include `backend/app/services/optical_reference.py`, `backend/app/services/acquisitions.py`, `backend/app/api/routes.py`, `backend/scripts/create_sentinel2_candidate.py`, and `backend/scripts/inspect_sentinel2_coverage.py`; test files `backend/tests/test_acquisitions.py`, `backend/tests/test_api.py`, `backend/tests/test_sentinel2_coverage.py`, and `frontend/tests/e2e/rivers.spec.js`; UI `frontend/src/App.jsx`, `frontend/src/components/AutomaticAcquisitionPanel.jsx`, `frontend/src/services/api.js`; documentation/data: README, audit, completion plan, progress, checklist, changelog, this handoff, data README and Sentinel-2 diagnostic. All project files are untracked at Git root; do not stage.
- No full optical scene was downloaded. Signed URLs remain memory-only. No process or background job is running.
- **Historical next-step note (superseded by the latest handoff above):** inspect remaining unchecked work and implement only changes justified without independent labels or compatible temporal data.

## Resume here

1. Read `PROJECT_COMPLETION_PLAN.md`, `PROJECT_HANDOFF.md`, `PROJECT_PROGRESS.md`, `PROJECT_TASK_CHECKLIST.md`, `PROJECT_CHANGELOG.md`, and `PROJECT-AUDIT.md`.
2. Inspect Git/worktree state; project files are reported as untracked. Do not stage or discard them.
3. AI Analysis remains deterministic and catalog-driven, not an external LLM. The current live smoke selected the latest Kaveri Sentinel-1 candidate and Tungabhadra NISAR A_009, both with explicit candidate status and provenance.
4. The catalog exposes five Kaveri and one Tungabhadra exact-grid Sentinel-1 pair. Separate persisted comparisons were created for one pair per river and their mask/PDF routes returned HTTP 200. Kaveri comparison has 436,083 common-valid pixels (56,238 candidate gain, 71,969 loss); Tungabhadra has 418,128 (47,214 gain, 54,174 loss). These differences are unvalidated, not hydrological change.
5. Latest verification: backend 77 passed (one existing Starlette/httpx deprecation warning); Playwright 11 passed; production build passed (1,569.99 kB JavaScript chunk advisory); `pip check` found no broken requirements. Acquisition scheduling was explicitly disabled for API checks.
6. Checklist is **61/69 (88.4%)**. Remaining tasks are independent reference labels, empirically supported cleanup/alternate classification, and trustworthy channel-axis/bank inputs. Exact-grid equality does not prove co-registration; don't infer flood, erosion, deposition, or verified river change.
7. `FINAL_PROJECT_COMPLETION_REPORT.md` has been updated. If continuing, investigate only remaining software work that can be justified without independent labels or bank geometry, then update all tracking docs and rerun affected tests. Do not stage, commit, or download large products.
8. No development server, acquisition job, or background download is running. Set `SAR_AUTO_ACQUISITION_ENABLED=0` for future API smoke tests.
9. Persistent acquisition jobs and the separately labeled Sentinel-2 NDWI candidate workflow are implemented and verified. The existing optical candidate raster now has an independent Leaflet preview layer with class/NoData legend, map bounds, acquisition metadata, and a visible not-ground-truth warning.
10. The independent-reference investigation and bounded Landsat inspection are documented in `data/INDEPENDENT-VALIDATION-INVESTIGATION.md`. The nearest-date scene was inspected at 718740 E / 1753830 N in EPSG:32643; 465 of 955 common-support cells passed QA and band checks, but the quicklook showed no defensible 30 m water boundary. No label template or labels were created. Do not calculate accuracy metrics until independent reference labels exist.
11. The architecture audit is available in `PROJECT-AUDIT.md`. River-map Playwright tests, corridor filtering, local NISAR recovery and the Kaveri low-valid-pixel diagnosis are complete. Existing real files are under `data/acquisitions/tungabhadra/`:
   - A_009: 6,811,549,696 bytes; processed status is `unvalidated_candidate`.
   - A_010: 6,618,611,712 bytes; processing correctly reports `no_valid_corridor_data`.
   Do not re-download either product.

The latest Kaveri item is `S1D_IW_GRDH_1SDV_20261107T004804_20261107T004835_005354_00A33B_rtc`. Its scene footprint overlaps the river; the rasterized corridor contains 459,523 cells and 22.758 km of reference centerline, but the saved 1,200×1,200 crop is entirely NoData (-32768), with zero valid positive VV pixels. No algorithm or validity criteria were relaxed. The precise upstream reason for the source no-data pixels remains unverified because the original COG window/mask was not re-read.

## Current local processes

- No development server or download was left running by the latest phase. A temporary API server on port 8001 was stopped after smoke tests; check ports before starting anything.
- Never print or inspect the Earthdata token. Set `SAR_AUTO_ACQUISITION_ENABLED=false` for future API smoke tests.

## Latest verified commands/results

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest
```

Result at the latest phase: 64 passed, one Starlette/httpx deprecation warning.

```powershell
Push-Location '.\frontend'; npm.cmd run build; $result=$LASTEXITCODE; Pop-Location; exit $result
```

Result at the latest phase: build passed; Vite reports a 1.54 MB JavaScript chunk above its 500 kB advisory threshold.

Latest live TestClient smoke test used automatic acquisition disabled: A_009 optical metadata and preview both returned HTTP 200; preview was 31,975 bytes (`image/png`) and metadata reported EPSG:32643, WGS84 bounds, 1,011,220 common-valid pixels, 21.7962% mapped-centerline coverage, and 17,691.025 seconds between acquisition start times. `/api/health`, `/api/regions`, and `/api/observations` also returned HTTP 200. No job was submitted and no product was downloaded.

`pip check` reported no broken requirements; `git diff --check` passed.

Frontend Playwright: 4 tests passed with `PLAYWRIGHT_CHANNEL=msedge`, including optical layer display/removal, class/NoData legend, NISAR layer coexistence, and preview error state. Bundled Chromium launch previously failed on this host with `spawn UNKNOWN`; Microsoft Edge is installed.

## Do not repeat or do

- Do not re-download A_009/A_010 or any other multi-gigabyte product during catalog recovery.
- Do not treat OSM geometry as ground truth.
- Do not claim Sentinel-2 validation: the persisted optical NDWI raster is an unvalidated candidate, and reported agreement numbers are descriptive, not accuracy metrics.
- Do not claim verified riverbanks, floods, erosion/deposition or multi-date scientific change.
- Never display/log the Earthdata token.
- Preserve the Sentinel-1 fallback and clearly labeled demonstration overlays.

## Latest phase changes

- `backend/app/services/analysis.py`: added `InsufficientValidDataError` at the existing minimum-valid-pixel check.
- `backend/app/services/acquisitions.py`: record that typed condition as `no_data`; keep unrelated exceptions as `failed`; clarify scan messaging when all candidates lack usable pixels.
- `frontend/src/components/AutomaticAcquisitionPanel.jsx`: clarified corridor-specific no-data label.
- `backend/app/services/acquisition_jobs.py`: SQLite job lifecycle, async workers, restart recovery, duplicate prevention, retry and output references.
- `backend/app/schemas/acquisitions.py`, `backend/app/api/routes.py`, `backend/app/main.py`: typed models, job API, and startup recovery.
- `backend/tests/test_acquisition_jobs.py`, `backend/tests/test_acquisitions.py`: API/lifecycle/recovery/retry/redaction and atomic HDF5 staging regression coverage.
- `frontend/src/services/api.js`, `frontend/src/components/AutomaticAcquisitionPanel.jsx`, `frontend/src/styles.css`, `frontend/tests/e2e/rivers.spec.js`: job operations and dashboard status/retry UI.
- Historical job-phase checklist: 38/60 items (63.3%). The final completion report remains pending.
- Sentinel-2: 11 Planetary Computer L2A items intersected Tungabhadra for 2026-11-05..08. Same-day tile 43PGT has 38.783842% item cloud cover and 124.15 km / 21.80% STAC-footprint centerline overlap. Bounded actual B04 10 m uint16 and SCL 20 m uint8 windows were read from 43PGT; B03/B04/B08 reflectance and SCL windows were read from adjacent same-acquisition tile 43PES. Both use EPSG:32643 and the provider's read-only SAS token (not displayed); no image was saved. At one 43PGT window along 51.5 km, 14,400 SCL pixels were non-NoData, 0.9% were cloud/shadow/snow classes, and class 6 contained 1,205 water pixels. Other samples were much cloudier.
- Historical pre-comparison checklist: 39/60 items (65.0%). See the current phase below for authoritative status.
- Exact next task at that phase was the SCL-valid Sentinel-2/A_009 common-grid coverage calculation; that diagnostic is now complete and documented. The diagnostic phase did not create an optical mask or validation score; the later phase below created the exploratory mask.
- Unfinished: optical candidate map visualization, independent scientific validation, candidate filtering evaluation, width/change validation, final full audit/report.

## Files changed in the latest job phase

- `backend/app/services/acquisition_jobs.py` — persistent job lifecycle, worker dispatch, recovery, retry and deduplication.
- `backend/app/services/acquisitions.py` — SQLite job table/index, job stage callback and atomic HDF5 download validation.
- `backend/app/schemas/acquisitions.py`, `backend/app/api/routes.py`, `backend/app/main.py` — job schemas, endpoints and startup recovery.
- `backend/tests/test_acquisition_jobs.py`, `backend/tests/test_acquisitions.py` — API, persistence, lifecycle, retry, redaction and safe-download tests.
- `frontend/src/services/api.js`, `frontend/src/components/AutomaticAcquisitionPanel.jsx`, `frontend/src/styles.css`, `frontend/tests/e2e/rivers.spec.js` — job API client, dashboard job list/actions and browser coverage.
- `PROJECT_PROGRESS.md`, `PROJECT_TASK_CHECKLIST.md`, `PROJECT_CHANGELOG.md`, `PROJECT_HANDOFF.md` — progress and resume records.
- Previously existing project files remain untracked at the top level; nothing was staged or committed.

## Historical phase — Sentinel-2/NISAR common-support diagnostic

- **Checklist at that phase:** 40/60 (66.7%).
- **Coverage:** 43PGT footprint intersects 124.153 km / 21.796% of the mapped Tungabhadra centerline and about 359.27 km² of the 1,500 m corridor. Common valid 10 m pixels: 1,011,220 (101.122 km²).
- **Comparison:** NISAR candidate 318,650 pixels; NDWI > 0 candidate 69,498; both 65,194. Descriptive agreement 74.51%, IoU 20.19%. These are not validation or accuracy metrics.
- **Method caveats:** SCL classes 4/5/6 counted as clear; 20 m SCL nearest-neighbor resampled to 10 m; acquisition offset 4 h 54 min 51.025 sec. No ground truth was established.
- **Files added/updated this phase:** `data/SENTINEL2-NISAR-COMPARISON-DIAGNOSTIC.md`, `data/README.md`, `PROJECT-AUDIT.md`, `PROJECT_PROGRESS.md`, `PROJECT_TASK_CHECKLIST.md`, `PROJECT_CHANGELOG.md`, `PROJECT_HANDOFF.md`.
- **Verification:** documentation consistency and working-tree state only. Backend/frontend tests were not rerun; latest prior results remain 57 backend tests passed, 3 Edge tests passed, frontend build passed with a large-chunk advisory, `pip check` clean. No process or download was started.
- This diagnostic informed the next phase; see the current handoff below.

## Previous phase — Sentinel-2 candidate raster map preview

- **Current verified checklist:** 43/60 (71.7%); final completion report remains pending.
- **Existing source output:** A_009 `nisar-processing/sentinel2-reference/ndwi-candidate-mask.tif`; 10,302 × 7,746 pixels, 10 m EPSG:32643, labels 0/1/255 for non-candidate/candidate/NoData. It was not regenerated or modified.
- **Preview API:** `GET /api/acquisitions/nisar/{product_id}/processing/sentinel2-reference/preview?river_id=tungabhadra` serves a bounded PNG reprojected to WGS84. Metadata includes exact WGS84 bounds, source CRS, image dimensions, NoData value, preview URL and acquisition timing.
- **Map behavior:** The optical overlay is separately selectable/removable, can coexist with the existing NISAR GeoJSON and river layers, and fits the map to its raster bounds. Its legend distinguishes candidate, non-candidate and NoData/invalid/unavailable pixels. Loading/error messages and the exact warning “EXPLORATORY SENTINEL-2 NDWI OUTPUT — NOT GROUND TRUTH.” are present.
- **Available metadata:** Sentinel-2 tile `S2C_MSIL2A_20261106T052011_R062_T43PGT_20261106T101206`; catalog tile cloud cover 38.783842%; source EPSG:32643; WGS84 bounds 76.862031–77.830303°E / 15.269866–15.979812°N; 1,011,220 common-valid pixels = 101.122 km²; NDWI threshold 0; NISAR start 00:25:20 UTC; Sentinel-2 acquisition 05:20:11.025 UTC; offset 17,691.025 seconds; mapped-centerline coverage approximately 21.8%.
- **Verification:** 64 backend tests passed (one Starlette/httpx deprecation warning); production frontend build passed with the existing ~1.54 MB Vite chunk advisory; 4 Edge tests passed. Actual local A_009 metadata and preview endpoints returned HTTP 200; PNG size 31,975 bytes. Health, regions and observations API checks returned HTTP 200.
- **Files changed in this phase:** `backend/app/services/optical_reference.py`, `backend/app/services/acquisitions.py`, `backend/app/api/routes.py`, `backend/tests/test_optical_reference.py`, `backend/tests/test_api.py`, `frontend/src/App.jsx`, `frontend/src/components/AutomaticAcquisitionPanel.jsx`, `frontend/src/services/api.js`, `frontend/src/styles.css`, `frontend/tests/e2e/rivers.spec.js`, and the four project tracking files.
- **Running processes/downloads:** none. No product was downloaded and no satellite raster output was recalculated or overwritten.
- **Next task:** evaluate whether an independently suitable reference can validate candidate classes; keep OSM and this exploratory NDWI classification out of the role of ground truth. Follow the pending checklist for cleanup, independent validation, and measurement/change work; do not generate the final report while feasible assignments remain.
- **Resume commands (PowerShell):**
  - `Push-Location 'D:\SAR-Sentinel-India\backend'; & '.\.venv\Scripts\python.exe' -m pytest; $result=$LASTEXITCODE; Pop-Location; exit $result`
  - `Push-Location 'D:\SAR-Sentinel-India\frontend'; npm.cmd run build; $result=$LASTEXITCODE; Pop-Location; exit $result`
  - `$env:PLAYWRIGHT_CHANNEL='msedge'; Push-Location 'D:\SAR-Sentinel-India\frontend'; npm.cmd run test:e2e; $result=$LASTEXITCODE; Pop-Location; exit $result`
- The candidate-generation CLI intentionally refuses to overwrite its existing output directory. Do not rerun it with the default output path.

## Latest phase — independent-reference investigation

- **Current verified checklist:** 46/62 (74.2%). The displayed comparison area/cloud/NoData/time context, dataset investigation, and bounded Landsat pixel/manual-label-feasibility inspection are checked; actual independent classification validation remains unchecked.
- **Investigation report:** `data/INDEPENDENT-VALIDATION-INVESTIGATION.md`. It records the STAC searches, dataset license/access assessment, exact support bounds, temporal offsets, QA-clear counts, Kaveri centerline-footprint intersections, and proposed manual-label validation protocol.
- **Key measured result:** Tungabhadra Landsat 9 scene `LC09_L2SP_144049_20261103_02_T1` is 67 h 15 min before NISAR A_009. QA_PIXEL bits 0–5 passed for 6,570/112,430 common-support 30 m cells (5.844%; ~5.913 km²); scene cloud cover is 86.63%. The clearer 2026-10-26 Landsat 8 scene passed 75,633/112,430 cells (67.271%) but is 10 d 19 h before NISAR. These are QA/coverage diagnostics, not validation.
- **Bounded pixel inspection:** 40×40 Landsat pixels (1.2 km square, EPSG:32643; requested center 718740 E / 1753830 N, grid-snapped bounds 718125–719325 E, 1753245–1754445 N) were read for green/red/NIR/SWIR1/QA_PIXEL/QA_RADSAT. Of 1,600 cells, 955 were on the actual common-valid support and 465 passed QA_PIXEL, band-specific saturation, COG-mask, and nonzero-DN checks (48.69% of local support; ~0.4185 km²). They occupy only 8 of 16 sub-blocks in the southern half. A false-color quicklook did not show an unambiguous channel/bank boundary at 30 m. No sample template, labels, or metrics were created.
- Landsat reflectance used `DN × 0.0000275 − 0.2`. The Landsat time offset from NISAR is 67 h 15 min 08.940 s. Six current asset-signing calls returned HTTP 200 with 2.5 seconds between requests; URLs remained in memory. The earlier HTTP 429 was not retried repeatedly.
- Eight Landsat item footprints intersect the Kaveri centerline in the searched dates; no Kaveri product mask/common-valid support was evaluated.
- JRC GSW 2022–2024 monthly history, WorldCover 2021, static GRWL, gauge discharge, and WBIS were assessed. No ready-made, temporally compatible spatial labels were identified.
- **No labels or accuracy metrics were created.** No full Landsat scene or global archive was downloaded, no local satellite outputs were modified, and no application code changed.
- **Verification:** documentation consistency and `git diff --check` only. Backend/frontend tests were not rerun because this phase changed documentation only; latest code results remain 64 backend tests, 4 Edge tests, and a successful production build.
- **Running jobs/processes:** none left running; no download or satellite processing is active.
- **Next exact action:** investigate whether a different near-date Landsat acquisition or another same-day Sentinel-2 tile offers spatially distributed, visibly interpretable water-boundary pixels; do not use the existing NDWI candidate mask to guide reference labels.
- Seek contemporaneous field survey, georeferenced aerial/drone imagery, or independently reviewed high-resolution labels. No validation labels or accuracy metrics are available.
- After that, obtain independently reviewed water/non-water/uncertain labels and date-matched hydrologic context if available. Only then implement metric calculations. For Kaveri, first identify a target classification and calculate actual common-valid overlap.
- Do not create `FINAL_PROJECT_COMPLETION_REPORT.md` while feasible work remains.
- Verification this phase: documentation formatting, checklist arithmetic (46/62), and `git diff --check` passed. No backend tests/build/browser tests rerun (documentation-only updates); the latest code-test results remain 64 backend tests, 4 Edge tests, successful production build.
- Exact remote inspection: Planetary Computer STAC `POST /api/stac/v1/search` for collection `landsat-c2-l2`, ID `LC09_L2SP_144049_20261103_02_T1`; signed assets `green`, `red`, `nir08`, `swir16`, `qa_pixel`, `qa_radsat`; Rasterio bounded reads at EPSG:32643 bounds `(718125, 1753245, 719325, 1754445)`. This was an inline Python diagnostic piped to `backend\.venv\Scripts\python.exe`; no reusable script was added.
- Acquisition scheduling was disabled in the inspection command environment. No process/download remains running, no full scene was downloaded, no raster was modified, and no signed URL was retained.
