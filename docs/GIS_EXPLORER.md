# GIS Explorer

The GIS Explorer is a local-data viewer and basic inspection workspace for the
Kaveri and Tungabhadra project. It reuses existing river, Sentinel-2, Forest,
water-analysis, NISAR and SQLite-catalog outputs. It does not acquire remote
datasets or generate new scientific classifications.

## Local layer availability

The current local catalog contains 69 available layers and four explicit
unavailable entries:

- Available: registered OSM river centerlines; Sentinel-2 NDVI/EVI/NDMI
  GeoTIFFs; Forest zone geometries, indices and previews; Sentinel-1 candidate
  water masks and display polygons; NISAR candidate mask and display polygon;
  and any locally registered Forest reference outputs.
- Unavailable: river-bank boundaries, flood/inundation, administrative
  boundaries, and a tree-cover reference raster.

Availability is discovered from the local files and existing SQLite records.
The inventory can change as new local processing outputs are registered. No
unavailable item is rendered as observed data. Sentinel-1 and NISAR water
products are candidates, not validated water boundaries. Sentinel-2 vegetation
indices are centerline-clipped; Forest outputs cover only their actual source
tile and analysis zones. The catalog does not assert continuous corridor
coverage.

Current local source records include Sentinel-2 observations from 2026-11-13,
Sentinel-1 candidate water observations from 2026-10-09 through 2026-11-07,
and a Tungabhadra NISAR candidate from 2026-11-06. Each layer's metadata is
the authority for its own date, CRS, resolution, source and processing status.
Those dates are not necessarily comparable across products.

## Map and inspection behavior

- The page uses Leaflet with OpenStreetMap tiles, pan/zoom, scale, fullscreen,
  reset view, layer visibility, opacity, ordering, zoom-to-layer, filtering and
  a legend for visible layers.
- Vector features are delivered as GeoJSON. Raster preview requests read the
  source GeoTIFF and use a `WarpedVRT` in EPSG:3857, nearest-neighbour
  resampling and a 512-pixel maximum longest side. NoData stays transparent;
  the preview is for display, not analysis.
- Raster metadata retains the source CRS, dimensions, data type, NoData,
  resolution, valid-pixel count, date and provenance. Original GeoTIFF downloads
  are not reprojected or resampled.
- Map clicks report WGS84 latitude/longitude, sample only selected visible
  raster layers, and report intersecting vector attributes where available.
  Out-of-bounds, unavailable, and NoData samples are not replaced with values.
- Length measurements transform WGS84 geometries into the UTM zone selected
  from the geometry centroid. Area calculations transform to EPSG:6933.
  These are basic geometry measurements, not calibrated river or ecological
  measurements.
- Drawings are held in browser memory until cleared/exported. GeoJSON export
  downloads a FeatureCollection. Vector CSV download exports source properties.

## Import safety and storage

Only GeoJSON (`.geojson`/`.json`) is accepted for import. The backend enforces
a 10 MiB upload cap and a 50,000-feature cap, requires a FeatureCollection,
checks finite WGS84 coordinates and supported geometries, and rejects invalid
features. Input CRS must be EPSG:4326 or CRS84; no arbitrary server path is
accepted. Temporary source files are stored under
`backend/app/data/gis_explorer/uploads/`, separately from project source
datasets, with layer metadata in the existing SQLite catalog. Users can
remove imported temporary layers from the UI.

The project has no general-purpose raster upload API in GIS Explorer. Raster
outputs are discovered from supported local project catalogs and served by
layer ID after server-side resolution. A failed layer load is surfaced in the
layer panel; missing layer IDs return an error rather than serving an arbitrary
file.

## API

All endpoints are under `/api/gis`:

| Method and route | Purpose |
| --- | --- |
| `GET /layers?river_id=both\|kaveri\|tungabhadra` | Dynamic local layer catalog and limitations |
| `GET /layers/{layer_id}/metadata` | Metadata for one catalogued layer |
| `GET /layers/{layer_id}/features` | Vector features as GeoJSON |
| `GET /layers/{layer_id}/preview.png` | Bounded display preview for a raster |
| `GET /layers/{layer_id}/download?format=native\|csv` | Native GeoTIFF/GeoJSON or vector-attribute CSV |
| `POST /inspect` | Sample visible raster layers and query intersecting vector features |
| `POST /measure` | Validate a GeoJSON geometry and calculate length/area |
| `POST /layers/import` | Validate and store a temporary GeoJSON upload |
| `DELETE /layers/{layer_id}` | Remove a temporary imported layer |

River selection is restricted to the registered pilot IDs. The catalog is
marked `no-cache` so newly registered outputs or temporary imports can appear
immediately. Requests reject invalid coordinates, geometry, unsupported
formats and unavailable data with explicit HTTP errors.

## Verification and limitations

Backend tests cover catalog status, missing layers, raster metadata/download,
valid and NoData sampling, raster previews, water-mask vector/CSV downloads,
GeoJSON validation, and geometry measurements. The browser test exercises real
local layer UI behavior, pixel inspection, raster and CSV downloads, measuring
a line, and a visible preview-load error.

Final project checks: backend **272 passed, 3 skipped**; full Playwright
**37 passed**; Python compilation, `pip check`, frontend production build,
`npm ls --depth=0`, and `git diff --check` passed. The earlier
Agriculture detached-scroll failure was fixed and the responsive all-pages
test now verifies no browser errors or horizontal overflow. The frontend
build retains a 528.30 kB chunk-size advisory; see the
[completion report](../FINAL_PROJECT_COMPLETION_REPORT.md) for test warnings
and limitations.

The module does not provide authoritative bank lines, flood extents,
administrative boundaries, broad-area Sentinel-2 rasters, raster editing,
remote data discovery, topology repair, or a geodatabase editor. Uploaded
GeoJSON is not independently verified. OSM river centerlines are references,
not surveyed channel axes. Candidate SAR classifications are not validation.
Layer availability and basic geometry checks do not imply scientific
validation.
