# SAR and GIS Team Integration Contract

This contract is the backend boundary for Apoorva's SAR processing module and
Sushanth's GIS analysis module. It adds no processing algorithm. Until an
adapter is registered, submitted jobs persist as `blocked` with
`adapter_unavailable`; the API does not produce substitute or demonstration
results.

## Status and scope

- **Implemented:** paginated access to locally present NISAR GCOV acquisitions
  whose recorded HDF5 structure and product identity still pass the existing
  acquisition checks; persistent SAR/GIS job records, retry lineage, output
  registration, output fingerprints, failure recovery, and river associations
  use the existing `data/satellite_catalog.sqlite3`.
- **Tested offline:** these endpoints and adapter transitions are tested with
  small fixture files and mock adapters. The mock outputs are test fixtures,
  not satellite observations.
- **Genuine live data:** the previous Earthdata live test verified only an
  authenticated one-byte range request. No complete product download was
  verified. The locally cached GCOV products are each over 6 GiB, so neither
  qualifies for the existing 128 MiB opt-in full-download test. The latest
  authenticated pilot-area and bounded recent-catalog searches identified no
  eligible sized product; this does not prove that none exists outside those
  searches.
- **Awaiting implementation:** Apoorva's SAR processing adapter and
  Sushanth's GIS analysis adapter.
- **Awaiting validation:** independent scientific validation, verified river
  bank/active-channel geometry, and any operational monitoring claim.

An acquisition listed here has a locally present file with recorded
structure/identity verification. The file is not necessarily backed by an
authoritative provider checksum: SHA-256 without that checksum is only an
integrity fingerprint. A listed river centerline does not establish satellite
coverage. Provider authenticity and scientific validation remain separate
statuses.

## API

All routes are under `/api`:

| Purpose | Endpoint |
|---|---|
| Paginated verified NISAR acquisitions | `GET /integration/acquisitions?river_id=tungabhadra&limit=100&offset=0` |
| Acquisition metadata | `GET /integration/acquisitions/{river_id}/{product_id}` |
| Recorded verification status | `GET /integration/acquisitions/{river_id}/{product_id}/verification` |
| Submit SAR processing | `POST /processing/jobs` |
| List/check SAR processing jobs | `GET /processing/jobs`, `GET /processing/jobs/{job_id}` |
| Register SAR outputs | `POST /processing/jobs/{job_id}/outputs` |
| Submit GIS analysis | `POST /gis/jobs` |
| List/check GIS jobs | `GET /gis/jobs`, `GET /gis/jobs/{job_id}` |
| Register GIS outputs and spatial results | `POST /gis/jobs/{job_id}/outputs` |
| Retrieve completed GIS result | `GET /gis/jobs/{job_id}/results` |
| Associate completed GIS result to a river | `POST /gis/jobs/{job_id}/association` |
| Retry failed or blocked job | `POST /integration/jobs/{job_id}/retry` |

SAR submission example:

```json
{
  "river_id": "tungabhadra",
  "product_id": "NISAR_L2_..._GCOV_...",
  "processing_config": {"frequency": "A", "polarizations": ["HH", "HV"]},
  "processing_version": "sar-module-0.1"
}
```

The backend resolves `product_id` against the requested river and rechecks the
local acquisition record before dispatch. The adapter receives the local
verified file path, a relative file reference, product/acquisition metadata,
the configuration and processing version, plus a job-specific output
directory. Spatial coverage is `null` when the catalog does not establish it;
the adapter must derive coverage from the product's validated georeferencing
or leave it unavailable rather than infer it from the river catalogue.

GIS submission example:

```json
{
  "input_output_ids": ["<registered SAR output UUID>"],
  "analysis_type": "change_candidate",
  "river_id": "tungabhadra",
  "spatial_extent": {
    "type": "Polygon",
    "coordinates": [[[75.5, 14.0], [76.0, 14.0], [76.0, 14.5], [75.5, 14.5], [75.5, 14.0]]]
  },
  "acquisition_start": "2026-11-06T00:25:20Z",
  "acquisition_end": "2026-11-06T00:25:55Z",
  "analysis_config": {},
  "processing_version": "gis-module-0.1"
}
```

The extent is optional GeoJSON Polygon/MultiPolygon in WGS84 longitude,
latitude coordinates. Acquisition timestamps, when supplied, must be
timezone-aware. GIS inputs must be registered outputs from a completed SAR
job; registered files are re-fingerprinted before use. `region_id` is present
in the schema for forward compatibility, but current region records are
demonstration-only and are rejected for observation analysis. Current real
associations can target only `RIVER_CATALOG` pilot IDs; this does not assert
coverage or monitoring.

## Adapter interface

Implement the protocol in `backend/app/services/integration.py`. A SAR adapter
implements `process(ProcessingAdapterInput)`, and a GIS adapter implements
`analyze(GISAdapterInput)`. Both return an `OutputRegistrationRequest`; GIS
results must include `spatial_results`.

Minimal shape:

```python
from pathlib import Path

from app.schemas.integration import OutputRegistrationRequest
from app.services.integration import ProcessingAdapterInput


class TeamSarAdapter:
    def process(self, request: ProcessingAdapterInput) -> OutputRegistrationRequest:
        source = Path(request.local_file_path)
        destination = Path(request.output_directory) / "candidate-mask.tif"
        # Run the actual teammate implementation; do not emit placeholder data.
        result = run_team_processor(source, destination, request.processing_config)
        return OutputRegistrationRequest(
            outputs=[
                {
                    "role": "candidate_mask",
                    "storage_key": f"{request.job_id}/candidate-mask.tif",
                    "output_type": "raster",
                    "media_type": "image/tiff",
                    "metadata": {
                        "crs": result.crs,
                        "width": result.width,
                        "height": result.height,
                        "transform": list(result.transform),
                        "nodata": result.nodata,
                        "units": result.units,
                    },
                }
            ],
            result_metadata={
                "source_product_id": request.acquisition.product_id,
                "source_sha256": request.acquisition.sha256,
                "processing_version": request.processing_version,
                "status": "unvalidated_candidate",
            },
        )
```

Register concrete adapters once in backend startup wiring with
`configure_processing_adapters(sar=TeamSarAdapter(), gis=TeamGisAdapter())`.
Do not pass credentials or signed URLs in job configuration or output
metadata. Requests containing credential-like fields or signed URLs are
rejected; error messages are redacted. When an adapter is not installed, a
job remains queryable as `blocked`. The team can then implement/register the
adapter and retry the job, or register externally generated files through the
job's output endpoint.

For external execution, write output files under
`outputs/integration/<job_uuid>/` and register keys relative to that directory
(for example `<job_uuid>/candidate-mask.tif`). The API rejects missing files,
symbolic links, path traversal, cross-job paths, unsupported extensions,
duplicate roles, and geospatial outputs without CRS metadata. Raster metadata
must declare width, height, six affine-transform values, NoData (use JSON
`null` when absent), and units. Vector metadata must declare geometry type and
CRS. The backend parses GeoTIFFs and verifies their CRS, dimensions, affine
transform, and NoData against the declaration. GeoJSON must be UTF-8 JSON with
a Feature or FeatureCollection top-level structure and EPSG:4326 longitude /
latitude CRS; GeoJSON files are limited to 100 MiB. GeoPackages must contain
the GeoPackage application identifier, metadata table, and a vector feature
table. Metadata outputs must be JSON objects. The backend calculates SHA-256
and byte size and checks the file again before a GIS job consumes it. These
format checks do not authenticate the adapter, prove scientific validity, or
verify that the declared algorithm is correct.

On completion, the backend adds provenance that adapters cannot replace:
processing job ID and version, source NISAR product ID/type, source file size
and SHA-256, integrity and provider-authenticity status, or—on GIS jobs—the
input output IDs/hashes and upstream acquisition provenance. Every result is
explicitly marked `scientific_validation_status: not_performed`, regardless
of adapter-supplied result metadata. The same server-derived provenance is
attached to each registered output's metadata. This records lineage; it is
not an independent integrity attestation or scientific endorsement.

## Team handover checklist

- [ ] **Apoorva:** provide the `process(ProcessingAdapterInput)` implementation,
  supported output roles, reproducible processing version, and module tests
  using real, valid raster outputs. Do not claim scientific validation without
  independent evidence.
- [ ] **Sushanth:** provide `analyze(GISAdapterInput)`, required SAR output
  roles, spatial result and metric schemas, CRS/units conventions, provenance
  requirements, and module tests using valid GeoJSON or GeoPackage outputs.
- [ ] Register both adapters through `configure_processing_adapters`; run the
  contract tests with the real adapters and verify job status, retries,
  output hashes, provenance, redacted errors, and river associations.
- [ ] Separately identify an authorized GCOV product no larger than
  134,217,728 bytes and run the opt-in full-download command in the README
  locally. Do not use the cached multi-gigabyte products.
- [ ] Keep provider authenticity and independent scientific validation
  explicitly pending until their separate evidence requirements are met.

## Common conventions

- **Identifiers and provenance:** the NISAR product ID is the stable source
  acquisition identifier. Backend job/output/association IDs are UUIDs.
  Processing requests preserve the source product ID, river ID, configuration
  and module version. Outputs carry the input SHA-256 and source/product
  provenance in their `result_metadata`.
- **CRS and geometry:** every raster/vector output declares its CRS explicitly.
  Do not assume a CRS or spatial accuracy. Submitted GeoJSON extents use WGS84
  longitude/latitude per RFC 7946. GeoJSON result layers should likewise be
  WGS84; projected rasters should retain their source CRS and transform.
- **Raster metadata:** report dimensions, affine transform, NoData and data
  units. Preserve class meanings and distinguish invalid/NoData cells from
  valid non-candidate cells.
- **Times and units:** use timezone-aware UTC timestamps. Report measurement
  units in result metadata and metrics; do not label pixel counts as area or
  distances without a valid CRS and conversion.
- **Data modes:** real provider acquisitions and demonstration data must stay
  separate. Do not associate demo regions or mock results with genuine
  observations. An NWIC feature or river-catalog entry is reference geometry,
  not evidence of acquisition coverage.
- **Failures:** raise an exception with an actionable, non-sensitive message
  when processing fails. The backend persists the job as `failed`, stores a
  redacted error, and records the exception type as `error_code`. Interrupted
  `running` jobs are marked failed on startup; retry creates a new UUID linked
  through `retry_of_job_id`.

## Independent testing and connection

Offline backend regression tests:

```powershell
Set-Location 'D:\SAR-Sentinel-India'
& '.\backend\.venv\Scripts\python.exe' -m pytest .\backend\tests\test_integration_contract.py -q
```

Use temporary files and a mock adapter for module tests. Keep live Earthdata
access out of ordinary tests. Team modules should also test their own
scientific transformations, CRS behavior, NoData handling, units, provenance,
and failure cases independently before registering an adapter. Adapter
registration is integration wiring, not a scientific endorsement.

The existing full-download live test requires an operator-selected GCOV
product with ASF-catalogued size no greater than 128 MiB and a locally
configured token. No product of that size is present in the current local
catalog; do not run it against the cached multi-gigabyte products. Never put
Earthdata tokens or signed URLs in code, request bodies, documentation, or
test fixtures.
