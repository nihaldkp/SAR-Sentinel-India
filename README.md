<<<<<<< HEAD
# SAR Sentinel India

**See the Change. Understand the Risk. Act Sooner.**

SAR Sentinel India is an Earth-observation project for exploring river-region SAR data. Existing dashboard metrics and preview layers remain explicitly demonstration data. Its automatic service discovers NISAR and Sentinel-1 RTC products; the separate NISAR GCOV workflow has processed an authenticated Tungabhadra scene into an unvalidated, single-date candidate open-water classification.

The dashboard's **NISAR Data Connection Status** summarizes catalog-reported
product stages. Live provider connectivity, authentication and the last
successful search are unknown unless independently tested; counts do not
establish file integrity or scientific validation. See the
[NISAR connection audit](./data/NISAR-CONNECTION-AUDIT.md) for verified evidence
and remaining gaps. Automatic acquisition remains opt-in.

The map's river search filters names and IDs already returned by `/api/rivers`.
The current catalog has only Kaveri and Tungabhadra; search is client-side and
does not provide national coverage, pagination or proof of monitoring.

## Requirements

- Node.js and npm
- Python 3.12 is recommended for the planned geospatial backend; the existing `backend/.venv` uses Python 3.12.10.
- Git
- A Python 3.12 environment with Rasterio able to load its native libraries
- Internet access to ASF DAAC, Microsoft Planetary Computer STAC, its SAS token endpoint, and Sentinel-1 RTC COG storage

## Run the frontend

In PowerShell:

```powershell
Set-Location 'D:\SAR-Sentinel-India\frontend'
npm.cmd install
npm.cmd run dev
```

Open the local URL printed by Vite, usually `http://localhost:5173`.
The frontend reads regions and demonstration scenario dates from the backend API. To use a different local API URL, copy `frontend\.env.example` to `frontend\.env.local`, update `VITE_API_BASE_URL`, and restart Vite. If Vite selects another local port because the default is occupied, the backend allows localhost development origins.

To create a production build:

```powershell
npm.cmd run build
```

The river map has Playwright browser regression tests. Install the bundled browser once, then run them:

```powershell
npx.cmd playwright install chromium
npm.cmd run test:e2e
```

On Windows, if Playwright's bundled Chromium cannot launch in the current environment but Microsoft Edge is installed, set `PLAYWRIGHT_CHANNEL=msedge` for the test command.

## Run the backend API

In a second PowerShell terminal:

```powershell
Set-Location 'D:\SAR-Sentinel-India'
& '.\backend\.venv\Scripts\python.exe' -m pip install -r .\backend\requirements.txt
Set-Location '.\backend'
& '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`. Interactive API documentation is at `http://127.0.0.1:8000/docs`.

Initial endpoints:

- `GET /api/health`
- `GET /api/regions`
- `GET /api/observations`
- `GET /api/observations?region_id=krishna-karnataka`
- `GET /api/rivers`
- `GET /api/rivers/{river_id}`
- `GET /api/satellite/search?river_id=kaveri&mission=NISAR&start_date=2026-10-01&end_date=2026-10-31&product_type=GCOV`
- `GET /api/acquisitions`
- `POST /api/acquisitions/refresh`
- `POST /api/acquisitions/nisar/{product_id}/process?river_id=tungabhadra`
- `GET /api/acquisitions/nisar/{product_id}/processing?river_id=tungabhadra`
- `POST /api/acquisitions/nisar/{product_id}/processing/component-sensitivity?river_id=tungabhadra` — creates separately stored 8-connected component-size scenarios from an existing candidate mask; request body: `{"minimum_component_sizes":[2,5,10]}`.
- `GET /api/acquisitions/nisar/{product_id}/processing/component-sensitivity/{minimum_component_pixels}?river_id=tungabhadra` — reads scenario metadata.
- `GET /api/acquisitions/nisar/{product_id}/processing/component-sensitivity/{minimum_component_pixels}/mask?river_id=tungabhadra` — downloads a NoData-preserving scenario GeoTIFF.
- `GET /api/acquisitions/nisar/{product_id}/processing/sentinel2-reference?river_id=tungabhadra`
- `GET /api/acquisitions/nisar/{product_id}/processing/sentinel2-reference/preview?river_id=tungabhadra`
- `GET /api/acquisitions/nisar/{product_id}/processing/sentinel2-reference/mask?river_id=tungabhadra`
- `GET /api/acquisitions/nisar/{product_id}/processing/sentinel2-observations/{observation_id}/preview?river_id=tungabhadra`
- `GET /api/acquisitions/nisar/{product_id}/processing/sentinel2-observations/{observation_id}/mask?river_id=tungabhadra`
- NISAR HH/HV, mask, and GeoJSON downloads: `/api/acquisitions/nisar/{product_id}/processing/{measurements|mask|polygons}?river_id=tungabhadra`
- `GET /api/analysis/status`
- `GET /api/analysis/validation/status`
- `GET /api/analysis/reference-sources` — metadata-only catalog of public context sources and their scientific/license limitations; it does not download any datasets.
- `GET /api/analysis/reference-data` and `POST /api/analysis/reference-data` — list or import an independently reviewed, single-band GeoTIFF with 0/1/255 labels and source/reviewer provenance.
- `GET /api/analysis/reference-data/{reference_id}/labels` — download an imported label raster.
- `POST /api/analysis/bound-references` — upload a candidate mask and reference raster with `metadata_json` to record an **unreviewed**, operator-declared product association and input fingerprints.
- `GET /api/analysis/bound-references` / `GET /api/analysis/bound-references/{reference_id}` — list or inspect these records.
- `POST /api/analysis/bound-references/{reference_id}/review` — request review, record an attestation, reject, or withdraw an attestation through explicit transitions.
- `POST /api/analysis/bound-references/{reference_id}/eligibility` — submit `candidate_file` and `identity_json` (river, product ID, sensor, timezone-aware acquisition timestamp, processing version) for a persisted point-in-time identity, review and exact-grid check. Candidate uploads remain subject to the 2-million-pixel and 100 MB limits.
- `GET /api/analysis/bound-references/{reference_id}/eligibility` — return the latest 100 recorded checks for that reference. Audit storage is limited to 10,000 checks; exhaustion returns an error.
- A passing identity/review check is **not** evaluation permission: declarations are unauthenticated, evidence thresholds and independence are not established, and review or files may change. The existing evaluation, AI and dashboard workflows do not consume these records or recheck them at evaluation time.
- `POST /api/analysis/bound-assessment-reservations/{assessment_id}` — reserve a caller-generated UUID using `reference_id`, `metadata_json` (the windowed validation metadata) and `candidate_file`. It stores an immutable candidate snapshot and the reference/review snapshot with exact fingerprints after checking the current attestation and identical grid. This **does not execute an assessment or generate a report**.
- `GET /api/analysis/bound-assessment-reservations/{assessment_id}` and `/events` — read a reservation and its transition history. Reusing the same UUID with identical inputs returns its current historical state; different inputs are rejected. Withdrawal atomically rejects outstanding reservations. A reservation is not scientific validation or evidence that the submitted review is authentic.
- `POST /api/analysis/bound-assessment-reservations/{assessment_id}/calculate` — transactionally records a bounded, common-support calculation from reserved input bytes, after checking the current attestation and fingerprints. It returns counts, not accuracy metrics or a published report. The SQLite write lock is held during computation, so competing writers can time out; the API does not provide report publication or recovery.
- Reservation inputs retain the existing two-million-pixel-per-raster and 100 MB combined limit. Candidate snapshots have a separate 1,000-record / 1 GiB quota. This API has no authentication; restrict access to trusted local users. Evaluation, report recovery, supersession and integration with existing workflows remain unimplemented.
- `GET /api/analysis/bound-references/{reference_id}/labels` — download a stored reference after its SHA-256 is checked.
- `POST /api/analysis/validation` — compare submitted candidate and independently reviewed reference GeoTIFFs using classes 0, 1, and 255; metadata is required in the `metadata_json` form field.
- `POST /api/analysis/validation/windowed-assessments` — assess matching-grid candidate and review-attested reference uploads without resampling; supply `candidate_processing_version` in `metadata_json`.
- `POST /api/analysis/validation/windowed-assessments/{validation_id}/evaluate` — evaluate a previously persisted, threshold-qualified assessment.
- `POST /api/analysis/validation/windowed-assessments/{validation_id}/reject` — record an operator-supplied rejection reason for an assessment awaiting evaluation.
- `GET /api/analysis/validation/{validation_id}` — retrieve a persisted provenance-bearing report.
- `POST /api/analysis/validation/methods` — compare two to eight supplied candidate masks over identical grids and the same common-valid pixels; requires independent-review metadata and does not choose a winning method.
- `POST /api/analysis/validation/methods/exploratory` — compare two to eight same-grid candidate masks without reference labels; reports shared support, candidate areas and pairwise overlap, not accuracy. This response is not persisted.
- `GET /api/analysis/validation/method-comparisons/{evaluation_id}` — retrieve a persisted method-comparison report.
- `POST /api/analysis/water-mask`
- `POST /api/analysis/ai-summary` — deterministic, rule-based summary of persisted river acquisition and processing records; accepts `{"river_id":"tungabhadra","product_id":"..."}` with optional `product_id`.
- `GET /api/analysis/temporal-pairs?river_id=kaveri` — lists persisted same-river Sentinel-1 candidate pairs that pass exact-grid, product, polarization, filter, and threshold-method checks, including common-valid support and provenance.
- `POST /api/analysis/change`
- `POST /api/analysis/width`
- `POST /api/analysis/width/river-axis` — sample candidate-mask segments along a caller-supplied GeoJSON axis and corridor. The service reports quality/coverage flags but does not authenticate geometry provenance or quantify measurement uncertainty.
- `GET /api/analysis/{analysis_id}` and result download routes (`/mask`, `/polygons`, `/report`)

The CWC/NWIC river-network catalog entry links to its direct GeoJSON resource. The portal advertised a 356 MB national file during the 2026-11-09 source check; the application does not fetch it. Its generalized river lines are not event-date water labels, bank geometries, or verified active-channel axes.

## River reference geometry

The application currently registers only the two OSM study-area centerlines below. The map selector derives its options from that catalog, but it is not a national searchable database; satellite processing, AI and validation remain limited to the supported study areas. A listed centerline does not establish monitoring coverage.

The [CWC river-network listing](https://nwdp.nwic.gov.in/dataset/river-line) describes a linear network, with its [GeoJSON resource](https://nwdp.nwic.gov.in/dataset/river-line/resource/6e552705-842d-40a4-92b2-8506bb66df2a) last updated 2025-11-17 and labeled “Other (Open)”; detailed coverage, classification and redistribution terms still require verification. [HydroRIVERS v1](https://www.hydrosheds.org/products/hydrorivers) uses a 15-arc-second source grid and includes rivers meeting a catchment area of at least 10 km² or mean flow of at least 0.1 m³/s, so it omits smaller features. Neither source has been imported here and neither establishes complete coverage of every Indian watercourse.

The map includes OpenStreetMap/Nominatim relation centerlines for the Kaveri (relation 2704746) and Tungabhadra (relation 2742213) rivers, stored in `backend/app/data/rivers.geojson`. The dataset records the source relation URLs, Nominatim retrieval URLs, retrieval date, and ODbL attribution. These are community-mapped reference geometries, not independently surveyed scientific products; the Tungabhadra source relation is tagged `fixme`. Only centerlines are available; left and right riverbank geometries are unavailable. A NISAR-derived candidate layer is exploratory and is not a verified boundary or change result.

## Automatic real satellite acquisition

Automatic acquisition scheduling is **disabled by default**. To opt in, set `SAR_AUTO_ACQUISITION_ENABLED=true`; only then does FastAPI start the background task, check both river centerlines, and repeat at the configured interval (six hours by default; configurable with `SAR_ACQUISITION_POLL_SECONDS`). It first searches the ASF DAAC NISAR GCOV catalog. When `EARTHDATA_TOKEN` is configured, it authenticates with ASF's supported `asf_search.ASFSession.auth_with_token()` client and attempts one product download per catalog refresh. Downloaded NISAR HDF5 files are validated for readable top-level groups and registered in the SQLite river catalog. Without a usable token, NISAR access is reported and the service continues with Sentinel-1. Set the token in the process environment or in the ignored repository-root `.env`; never commit that file.

### Exploratory Sentinel-2 tile candidates

The existing NISAR A_009 processing result links to the original 43PGT Sentinel-2 candidate and to any additional same-overpass tiles saved under `nisar-processing/sentinel2-observations/<STAC-item-id>/`. The dashboard exposes each available tile independently, including its acquisition time, catalog cloud percentage, common-valid pixels, NDWI candidate count, preview, and GeoTIFF download. Every output uses NDWI > 0 on the NISAR grid, SCL classes 4/5/6, and NoData outside common valid support. These are exploratory classifications, not ground truth or validation results.

Use `backend/scripts/inspect_sentinel2_coverage.py` for metadata-only STAC footprint screening. Use `backend/scripts/create_sentinel2_candidate.py --item-id <screened-item-id>` only for the explicitly allowlisted 2026-11-06 A_009 overpass tiles. The processing command reads B03/B08/SCL COG windows only where the existing NISAR candidate mask is valid under the tile footprint; it does not download complete scenes, overwrite outputs, retry a rate-limit response, or save signed asset URLs.

Catalog retrieval uses the mapped centerline's bounding box, then filters product footprints against a 1,500 m projected buffer around the actual centerline and ranks matches by overlap. It requests up to five times the requested result count (capped at 100) before applying that exact corridor test, so loose bounding-box matches do not consume the full result limit. The NISAR automatic search uses the same corridor test. If a later scan finds no new NISAR metadata, locally stored HDF5 products and processing metadata remain in the catalog and the API reports that they were recovered locally.

The Sentinel-1 fallback queries the Microsoft Planetary Computer STAC `sentinel-1-rtc` collection, requests the official read-only SAS token, and reads only a local 12 km COG window around an intersecting centerline segment. It clips processing to a 1.5 km half-width centerline corridor. The source RTC collection has already undergone radiometric calibration and terrain correction upstream; this app does not reprocess raw GRD. It stores the clipped VV GeoTIFF and unsigned STAC item metadata under `data/acquisitions/`, with a SQLite catalog at `data/satellite_catalog.sqlite3`. Duplicate river/product pairs are not downloaded and processed again.

The downloaded linear-power VV data are processed with a 5×5 Lee-style filter and Otsu threshold into **unvalidated candidate open-water masks**, EPSG:4326 GeoJSON, and PDF reports. The NISAR workflow reads the actual L2 GCOV frequency-A `HHHH` and `HVHV` covariance rasters plus the product's fully-focused-sample validity mask, uses projected coordinate axes and projection metadata, and writes georeferenced measurements and candidate-mask rasters only when valid paired pixels exist in the 1.5 km OSM-centerline corridor. Separate Otsu thresholds in dB are estimated from paired valid corridor pixels; the candidate class requires both HH and HV values to be below their thresholds. If the corridor contains no valid samples, the API records a no-data result and does not create water-area values or mask files. The acquisition panel presents NISAR results separately.

Sources and access APIs:

- ASF DAAC search: `https://api.daac.asf.alaska.edu/services/search/param`
- Microsoft Planetary Computer Sentinel-1 RTC STAC: `https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-1-rtc`
- Microsoft Planetary Computer read-only token API: `https://planetarycomputer.microsoft.com/api/sas/v1/openapi.json`
- Sentinel-1 RTC terms: CC BY 4.0, as declared by its STAC collection.
- OSM centerline attribution/licence is recorded with the existing river dataset.

### Configure an Earthdata token on Windows

The root `.env` file is ignored by Git. If `EARTHDATA_TOKEN` is already set in the PowerShell terminal that starts the backend, copy it into that local file without putting its value in shell history or source code:

```powershell
Set-Location D:\SAR-Sentinel-India
if ([string]::IsNullOrWhiteSpace($env:EARTHDATA_TOKEN)) { throw "EARTHDATA_TOKEN is not set in this PowerShell process." }
Set-Content -Path .env -Value "EARTHDATA_TOKEN=$env:EARTHDATA_TOKEN" -NoNewline
```

Alternatively, export `$env:EARTHDATA_TOKEN` in the same PowerShell process before starting Uvicorn. Do not paste the token into chat or commit `.env`. `.env.example` contains only an empty placeholder.

## Scientific limitations

The initial NISAR processor is product-specific to the downloaded L2 GCOV HDF5 structure. It verifies dataset names, dimensions, declared linear-power units, the fully-focused validity mask, coordinate-axis spacing, and EPSG projection before reading data in windows. Frequency A is 10 m; the product's frequency B is 80 m and is not used. NISAR's geocoded grid is written without an extra reprojection. The processing endpoint requires a previously downloaded, HDF5-verified product and does not trigger any additional downloads.

The NISAR mask is an **unvalidated candidate classification**, not a verified river boundary. Low HH/HV backscatter can also occur over non-water surfaces and shadow; the processor has no ground-truth labels, accuracy score, statistical confidence, or independent screening for terrain, vegetation, and incidence-angle effects. Candidate-classified area counts only valid paired pixels in the rasterized corridor. The ±1 dB range is threshold sensitivity, not a statistical confidence interval. The first Tungabhadra scene (`...A_010...`) has an ASF footprint that does not intersect the river corridor; all 5,213,075 rasterized corridor cells were marked outside acquisition, so that product correctly yielded no mask or area. A second authenticated scene (`...A_009...`) has valid paired HH/HV samples in the corridor and produced an unvalidated candidate classification: 12,910,080 valid of 15,356,387 corridor pixels (84.07%) and 3,885,882 candidate pixels (388.5882 km²). This is a single-date thresholded candidate result, not a verified water extent or riverbank measurement. Its GeoJSON display is capped at 5,000 features and marked truncated; the GeoTIFF retains the complete candidate raster and NoData. Kaveri has no downloaded product in this workflow. No river width, erosion, deposition, flood, or riverbank movement is claimed.

The A_010 metadata also reports 33.26% centerline overlap with the rectangular raster grid; this is geometric grid coverage, not valid acquisition support. Its persisted processing result has zero valid paired corridor pixels and no candidate area or mask.

The optional component-size sensitivity control creates separate 8-connected threshold scenarios from an existing NISAR candidate mask; it does not change the source mask or the default classification. The real A_009 scenarios for minimum sizes 2, 5, and 10 pixels reclassified 89,437 (2.30%), 202,003 (5.20%), and 283,567 (7.30%) of candidate pixels as non-water, respectively. All 550,634,840 NoData pixels were preserved in each full-resolution GeoTIFF. These parameter-driven differences are exploratory sensitivity only: no removed pixel is established as noise, and no threshold is recommended without independent reviewed labels.

The Sentinel-1 result likewise covers only the acquired local subset, not the entire river. Its corridor is based on community-mapped OSM centerlines, not verified channel banks. Persisted observations can be compared only when they pass the exact-grid and processing-compatibility checks; the resulting comparison remains an unvalidated candidate-water difference. It does not prove erosion, deposition, flooding, or true hydrological change. The API reports common valid support, thresholds, acquisition dates, and processing provenance, but does not assess co-registration error or perform seasonal normalization.

The manual GeoTIFF analysis workspace remains for local research, but automatic observation discovery, acquisition, and candidate processing do not require it. If live services are unavailable, the UI shows explicit no-data/error status and never substitutes the demonstration layer.

The dashboard's **AI-Powered River Analysis** panel is a local deterministic summary, not an external LLM. It uses persisted catalog and processing metadata to report candidate-pixel/area values, valid and NoData support, NISAR threshold and polarization diagnostics, linked exploratory Sentinel-2 context, and whether compatible temporal candidate pairs are available. It also checks persisted validation reports against the selected river, product ID and acquisition time, and reports reference attestations separately; importing a reference does not establish its applicability or authenticate its review. A completed submitted-sample evaluation is not scientific certification. The current workflow has no separately persisted “thresholds met, awaiting validation” state, and cannot authenticate independence. Temporal comparisons are a separate, user-triggered workflow and remain explicitly unvalidated. The summary does not calculate accuracy metrics or claim flood, erosion, deposition, or verified-bank detection.

The panel shows the selected product's provider, product ID, acquisition time, product type, polarization and available CRS/resolution provenance. Selecting a product from the live ASF search synchronizes the river and map footprint; search metadata alone is not treated as a processed observation. A matching persisted product must exist before its measurements can be shown. Changing the selected product marks prior metrics stale until analysis is rerun. The implementation is deterministic; no external LLM provider is configured or called.

The **Independent reference validation** workspace accepts single-band candidate and reviewed-reference GeoTIFFs, records acquisition and review provenance, aligns reference labels to the candidate grid with nearest-neighbour resampling, and computes metrics only on common valid pixels when both reference classes are represented. Both inputs must declare 255 as NoData/uncertain; uploads are bounded to 100 MB and two million pixels. Reports contain caveats and persist as JSON under `outputs/validation/`; rasters submitted directly for a one-off validation are not retained. The separate reviewed-reference import workflow described below intentionally stores imported reference rasters under `outputs/reference-data/`. The API distinguishes no-data/pending status from the presence of imported reference data, but imported data does not itself produce validation metrics. The service cannot authenticate the named provider/reviewer or establish the independence, quality, or sampling design of user-supplied labels. No independent reference labels or scientific validation scores are currently available; do not use Sentinel-2 NDWI as an independent reference for another candidate classification.

The same form also offers a **windowed same-grid assessment** for larger rasters. It requires identical dimensions, CRS and affine transform, one uint8 band, 255 NoData and no resampling; even aligned partial overlap is not currently supported. It honors internal validity masks, uses common-valid pixels for class and confusion counts, and persists the input SHA-256 fingerprints, submitted product/version, grid, windows and declared thresholds. Scores are withheld until a threshold-qualified assessment is explicitly evaluated. Review, independence, product and version are operator declarations, not authenticated facts; for NISAR the AI summary additionally compares the candidate fingerprint with the locally selected raster before associating a report. A hash match is not proof of reference quality or certification. Legacy reports and products without a verifiable version cannot be linked this way.

An awaiting assessment can be rejected with a recorded reason, or evaluated once. An inconsistent stored assessment produces an explicit evaluation error and a persisted failed outcome when the report remains writable; completed, failed and rejected outcomes include timestamps and cannot be evaluated again. Storage failures cannot be guaranteed to record an outcome. These are sample-workflow outcomes, not authentication or scientific certification.

Product-bound reference import is a separate, API-only preparation workflow. It stores a reference raster and immutable operator-declared candidate identity, SHA-256 fingerprints, grid and review history in a local SQLite database. The submitted candidate raster is fingerprinted but not retained. The API does not authenticate the association, reviewer or reference source; a null candidate processing version means unknown. Imports begin unreviewed; an explicit pending transition precedes an attestation or rejection, and an attestation can be withdrawn. This workflow is **not yet linked to the existing evaluation, AI summary or dashboard**, and it does not automatically supersede earlier references.

Both uploaded GeoTIFFs in this preparation workflow are currently limited to two million pixels each and 100 MB combined; stored references are limited to 1,000 records and 1 GiB of raster bytes. Raster bytes, SQLite overhead, concurrent uploads and processing buffers mean these limits are not a hard memory or total-disk bound. Reference transitions use a SQLite write transaction; existing windowed evaluation/rejection uses a SQLite local-process mutex around atomic report replacement and records terminal transitions in the report. These mechanisms cover cooperating workers using the same local database and do not provide distributed locking or protection from direct file modification.

The application has no user authentication or per-user authorization. Local report and file identifiers are not access controls; deploy only in a trusted, access-restricted environment. Resolved path checks reduce traversal but do not eliminate symlink changes between checking and opening files. A comprehensive file-security audit and cross-process concurrency controls remain outstanding.

Windowed uploads are buffered in memory (100 MB combined limit), then processed in 512 × 512 windows with a 64 MB GDAL cache target. Storage blocks, total pixel reads, distribution blocks, and cooperative 180-second execution are capped; one assessment or evaluation runs per server process. These are not hard process-memory or wall-clock guarantees: concurrent uploads can buffer before the lock, independent workers have independent locks, and a stalled GDAL read cannot be preempted. The UI shows a processing state rather than incremental progress. The original small-raster nearest-neighbour workflow remains available with its two-million-pixel-per-input limit.

The workspace also lists public reference-source metadata and accepts locally reviewed 0/1/255 GeoTIFF labels with their source, acquisition time, CRS, resolution, license, reviewer, review method, and limitations. The catalog is for discovery only: JRC Global Surface Water is historical context (1984–2024), Landsat Collection 2 requires scene-specific QA and human review, CWC/NWIC river lines are not active-channel/bank surveys, HydroRIVERS is too coarse for 10 m channel work, and GRWL is a static Landsat-derived width product rather than event-date truth. Importing a raster records a human attestation but does not authenticate its source, reviewer, independence, or quality. No automatic download is performed. Imported label files can be downloaded for use with the validation endpoint.

Reviewed validation and method evaluation additionally require operator-declared `minimum_common_pixels` (at least 2), `minimum_coverage_fraction` (greater than 0 and at most 1), `minimum_pixels_per_class`, `spatial_block_size_pixels`, and `minimum_blocks_per_class` (each at least 1). The coverage denominator is candidate-valid pixels for single-mask validation, or reference-valid pixels on the candidate grid for method evaluation. For each reference class, count common-support pixels and occupied square blocks of the declared pixel size, anchored at the candidate grid's top-left. Missing or unmet thresholds yield `insufficient_evidence` and no accuracy metrics. Choose thresholds before analysis for the intended sampling design; occupied blocks do not establish spatial independence, representativeness, or scientific validity. Historical reports lacking qualifying thresholds and distribution counts are served with metrics withheld without changing their stored files.

`POST /api/analysis/validation/methods` provides a research framework for alternative-method comparison, not a recommendation to deploy another classifier. Reviewed evaluation requires two to eight candidate masks on exactly the same dimensions, transform, CRS and NoData convention, and remains limited to two million pixels per input. It scores all masks on one shared intersection of valid pixels with a reviewed reference when the evidence gates pass and stores submitted provenance.

Exploratory comparison accepts aligned, partially overlapping uint8 GeoTIFFs in the same projected metre CRS and pixel basis, without resampling. It computes the intersection of valid data for all methods using 512 × 512 windows, reports coverage relative to the first grid, and records grid transforms, offsets and window parameters. Only overlapping pixels are inspected. Uploads are limited to 100 MB combined; storage blocks are limited to 1,048,576 pixels, work to 5 billion pixel reads and processing to 180 seconds checked between windows. One comparison executes at a time per server process; concurrent attempts return 409 after their uploads have been read, so simultaneous uploads can still consume memory. This is not a hard deadline on an individual GDAL read, and multiple server processes have separate limits. Compressed uploads are buffered in memory, Rasterio/GDAL uses a 64 MB cache, and window arrays scale with method count; no complete decompressed scene is allocated. Larger or unusually tiled files may be rejected.

Both comparison modes report candidate areas, disagreement with the first method, and all pairwise absolute area differences, differences relative to the first method in each pair, disagreement fractions, and candidate-mask IoU on shared support. A zero first-method area makes the relative difference unavailable; a zero union makes IoU unavailable; empty shared support makes pairwise quantities unavailable. Candidate overlap is not accuracy. The Analysis workspace links to this form in the validation workspace. The application does not select a winner. Method choice and evaluation design remain unsupported until appropriate independent labels and predeclared, spatially suitable evaluation evidence are available.

`POST /api/analysis/width/river-axis` accepts a caller-supplied WGS84 GeoJSON LineString and Polygon/MultiPolygon corridor, transforms them to the analysis raster CRS, requires the corridor to contain the axis, and applies bounded station/transect sampling to an existing candidate mask. It reports per-station candidate segment length, valid/raster coverage, quality status, and flags. Geometry source details are operator-supplied and unauthenticated; OSM centerlines are not automatically used. The result explicitly identifies the axis as unverified, the segment as candidate-mask width rather than surveyed bank-to-bank width, and uncertainty as not quantified. No trusted active-channel axis or bank geometry is currently available, so this endpoint is preparatory and no verified river-width result is claimed.

`GET /api/acquisitions` reports catalog state; `POST /api/acquisitions/refresh` requests an immediate scan only when scheduling is enabled. Keep the default off by leaving `SAR_AUTO_ACQUISITION_ENABLED` unset; set it to `true` only to opt in. Manual product/job actions remain explicit user operations.

Generated acquisition files and NISAR processing outputs are stored under `data/acquisitions/`; Sentinel-1 analyses remain under `outputs/analysis/`. These runtime data directories are excluded from Git. Two Tungabhadra NISAR GCOV products from 6 November 2026 UTC are registered: the `A_010` scene has no valid corridor samples, while the `A_009` scene was processed into an unvalidated candidate classification. Processing is an explicit user action through the dashboard or API. Automated tests use small clearly identified synthetic HDF5 fixtures and do not process the multi-gigabyte products.

Run backend tests from the repository root:

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest .\backend\tests
```

## Demonstration data notice

Dashboard demonstration observations, charts, demo polygons, and metrics remain synthetic and illustrative. Automatic acquisition records come from real satellite product assets and are labeled separately. Their thresholded water masks are unvalidated candidates, not verified riverbanks, flood/damage findings, erosion/deposition, or scientifically validated measurements.

## Current milestone

- **Milestone 2:** Initial interactive frontend with a simulated-data badge, selectable demonstration regions, map layers, and dashboard navigation.
- **Milestone 3:** Frontend production build and interactive dashboard verified in a browser.
- **Milestone 4:** FastAPI health, region catalog, and explicitly simulated observation catalog endpoints.
- **Milestone 5:** Frontend health, region, and observation catalog calls connected to the backend, with visible connection errors and retry.
- **Milestone 6:** Kaveri and Tungabhadra OpenStreetMap reference centerlines exposed through the river API and visualized on the existing map; no verified banks or satellite analysis.
- **Milestone 7:** Live ASF metadata discovery and local candidate raster-analysis, comparison, width, and PDF workflows are implemented.
- **Milestone 8:** Automatic NISAR metadata checks, authenticated GCOV acquisition, a separate windowed HH/HV processor with explicit no-valid-corridor-data handling, processing metadata/API, downloadable outputs, and NISAR-specific dashboard display are implemented. The Tungabhadra `A_009` scene produced an unvalidated candidate classification from valid corridor data; the `A_010` scene correctly returned no data. Sentinel-1 RTC acquisition and fallback remain intact.
- **Milestone 9:** The A_009 candidate has HH-only/HV-only/combined comparisons, five equal-threshold-offset sensitivity cases, and 8-connected fragmentation diagnostics. Bounded Sentinel-2 pixels were inspected and used to create a NoData-preserving exploratory NDWI candidate raster. The dashboard can display that raster as an independent map layer with acquisition/coverage metadata and a candidate/non-candidate/NoData legend. It remains unvalidated and is not ground truth.
- Existing demonstration overlays, charts, and metrics remain synthetic. Neither NISAR nor Sentinel-1 candidate masks have ground-truth validation. No verified riverbank boundaries, erosion/deposition, flood detection, or scientifically validated change detection is available.
=======
# SAR-Sentinel-India
>>>>>>> origin/main
