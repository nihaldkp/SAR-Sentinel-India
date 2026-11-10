import { expect, test } from "@playwright/test";

const regions = [{
  id: "krishna-karnataka",
  name: "Krishna basin · Karnataka",
  basin: "Krishna",
  state: "Karnataka",
  center_latitude: 15.72,
  center_longitude: 75.72,
  data_mode: "demonstration",
  is_simulated: true,
}];

const observations = [{
  id: "krishna-demo",
  region_id: "krishna-karnataka",
  scenario_date: "2026-06-12",
  label: "Illustrative scenario",
  source: "synthetic_demo",
  product_type: "illustrative_backscatter_scenario",
  is_simulated: true,
  status: "demonstration_only",
}];

const rivers = [
  river("kaveri", "Kaveri River", 75.94, 12.44, 2704746),
  river("tungabhadra", "Tungabhadra River", 76.45, 15.34, 2742213),
];

const referenceSources = [{
  source_id: "landsat-c2-fixture",
  name: "Landsat Collection 2 Level-2 Surface Reflectance",
  provider: "USGS EROS",
  source_url: "https://www.usgs.gov/landsat-missions/landsat-collection-2-surface-reflectance",
  access_url: "https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2",
  temporal_coverage: "Per-scene acquisitions; scene-specific dates and QA required",
  nominal_resolution_m: 30,
  geographic_coverage: "Global land scenes; clear support varies.",
  spatial_reference: "Scene-specific CRS; inspect metadata.",
  data_format: "Level-2 GeoTIFF/COG assets.",
  access_notes: "STAC metadata and assets are available from the linked catalog.",
  license_status: "USGS Landsat products have no use restrictions; cite the product",
  intended_use: "Potential basis for independently reviewed manual labels.",
  limitation: "A human must review each scene.",
}];

function river(id, name, longitude, latitude, osmElementId) {
  const geometry = {
    type: "MultiLineString",
    coordinates: [[
      [longitude, latitude],
      [longitude + 0.02, latitude + 0.02],
    ]],
  };
  return {
    id,
    name,
    display_name: name,
    states: "Karnataka, Tamil Nadu",
    geographical_location: "Southern India",
    data_source: "OpenStreetMap",
    source_url: "https://www.openstreetmap.org/",
    retrieval_url: "https://nominatim.openstreetmap.org/",
    osm_element_type: "relation",
    osm_element_id: osmElementId,
    retrieval_date: "2026-11-09",
    license: "ODbL-1.0",
    license_url: "https://opendatacommons.org/licenses/odbl/",
    available_geographical_data: ["centerline"],
    boundary_data_status: "unavailable",
    left_bank_boundary: null,
    right_bank_boundary: null,
    centerline: geometry,
    future_nisar_integration: {
      supported: true,
      polarizations: [],
      processed_water_masks: [],
      extracted_riverbank_boundaries: [],
      multi_date_change_detection_results: [],
    },
  };
}

const acquisitionRiver = (riverId) => ({
  river_id: riverId,
  status: "no_data",
  nisar_status: "no_data",
  nisar_products: [],
  candidate_count: 0,
  observations: [],
  issues: [],
});

test.beforeEach(async ({ page }) => {
  page.on("pageerror", (error) => console.error("Browser page error:", error));
  await page.route("**/api/**", async (route) => {
    const { pathname } = new URL(route.request().url());
    const payload = {
      "/api/health": { status: "ok", data_mode: "demonstration" },
      "/api/regions": regions,
      "/api/rivers": rivers,
      "/api/river-network/features": { total: 0, limit: 20, offset: 0, features: [] },
      "/api/analysis/status": {
        geotiff_processing_available: true,
        rasterio_available: true,
        raw_product_preprocessing_available: false,
        real_satellite_product_downloaded: false,
        input_requirement: "Single-band GeoTIFF",
      },
      "/api/analysis/temporal-pairs": [],
      "/api/analysis/validation/status": {
        status: "validation_pending",
        message: "Independent scientific validation pending. No suitable reviewed reference labels are currently available.",
        reports: [],
      },
      "/api/analysis/reference-sources": referenceSources,
      "/api/analysis/reference-data": [],
      "/api/acquisitions": {
        enabled: false,
        polling_interval_seconds: 21600,
        source: "Microsoft Planetary Computer Sentinel-1 RTC",
        source_url: "https://planetarycomputer.microsoft.com/",
        license: "CC-BY-4.0",
        rivers: [acquisitionRiver("kaveri"), acquisitionRiver("tungabhadra")],
      },
      "/api/acquisition-jobs": [],
      "/api/analysis/ai-summary": {
        analysis_id: "fixture-analysis-run",
        generated_at: "2026-11-09T12:00:00Z",
        analysis_mode: "deterministic_rule_based",
        data_mode: "persisted_satellite_acquisition_catalog",
        river_id: "tungabhadra",
        selected_product_id: "NISAR_A009_FIXTURE",
        products: [{
          product_id: "NISAR_A009_FIXTURE",
          satellite: "NISAR",
          acquisition_start: "2026-11-06T00:25:20Z",
          processing_status: "processed",
          is_usable_candidate: true,
          valid_data_fraction: 0.8,
          source_name: "ASF DAAC",
          product_type: "L2_GCOV",
          polarization: ["HH", "HV"],
          input_crs: "EPSG:32643",
          pixel_size_m: 10,
        }, {
          product_id: "S1_FIXTURE",
          satellite: "SENTINEL-1",
          acquisition_start: "2026-11-05T00:25:20Z",
          processing_status: "unvalidated_candidate",
          is_usable_candidate: true,
          valid_data_fraction: 0.7,
          source_name: "Microsoft Planetary Computer",
          source_record_url: "https://example.test/stac/item",
          source_license: "CC-BY-4.0",
          product_type: "GRD-RTC",
          polarization: ["VV"],
          input_crs: "EPSG:32643",
          pixel_size_m: 10,
        }],
        coverage: {
          catalog_product_count: 2,
          usable_candidate_count: 1,
          no_data_product_count: 1,
          failed_product_count: 0,
          mapped_centerline_coverage_percent: 21.8,
          corridor_half_width_m: 1500,
        },
        candidate_metrics: {
          classification_status: "unvalidated_candidate",
          candidate_water_pixel_count: 250,
          candidate_water_area_km2: 0.025,
          valid_pixel_count: 800,
          corridor_pixel_count: 1000,
          valid_data_fraction: 0.8,
          no_data_fraction: 0.2,
          hh_threshold_db: -12,
          hv_threshold_db: -18,
        },
        threshold_sensitivity: {
          samples: [],
          candidate_area_min_km2: 0.02,
          candidate_area_max_km2: 0.03,
          candidate_area_range_percent: 40,
          interpretation: "Recorded threshold perturbations only.",
        },
        polarization_comparison: [{ classification: "HH+HV", candidate_area_m2: 30000 }],
        optical_comparison: {
          available: false,
          status: "not_available",
          warning: "No linked Sentinel-2 candidate.",
        },
        temporal_comparison: {
          status: "insufficient_observations",
          available_pair_count: 0,
          explanation: "Fewer than two usable candidate observations are available.",
        },
        validation_status: "independent_reference_unavailable",
        validation_explanation: "No imported reference or matching validation report is available.",
        findings: ["NISAR candidate result is unvalidated."],
        warnings: ["No independent reference."],
        limitations: ["No accuracy metrics are available."],
        recommended_next_steps: ["Obtain independently reviewed reference labels."],
      },
    };
    const response = pathname === "/api/observations"
      ? observations
      : payload[pathname];
    if (response === undefined) {
      await route.fulfill({ status: 404, json: { detail: "Not found" } });
      return;
    }
    await route.fulfill({ json: response });
  });
  await page.route("https://*.tile.openstreetmap.org/**", (route) => route.abort());
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: "Select river" })).toBeEnabled();
});

test("river selection keeps the map legend aligned with visible centerlines", async ({ page }) => {
  const riverSelect = page.getByRole("combobox", { name: "Select river" });
  const legend = page.locator(".map-legend");

  await expect(page.getByText("No usable satellite observations in the mapped river corridor").first()).toBeVisible();
  await expect(legend.getByText("Kaveri River · OSM")).toBeVisible();
  await expect(legend.getByText("Tungabhadra River · OSM")).toBeVisible();

  await riverSelect.selectOption("kaveri");
  await expect(legend.getByText("Kaveri River · OSM")).toBeVisible();
  await expect(legend.getByText("Tungabhadra River · OSM")).toHaveCount(0);

  await riverSelect.selectOption("tungabhadra");
  await expect(legend.getByText("Tungabhadra River · OSM")).toBeVisible();
  await expect(legend.getByText("Kaveri River · OSM")).toHaveCount(0);
});

test("river selector reflects additional catalog entries without implying monitoring coverage", async ({ page }) => {
  const extra = river("fixture-river", "Fixture River", 77, 14, 12345);
  await page.route("**/api/rivers", (route) => route.fulfill({ json: [...rivers, extra] }));
  await page.reload();
  const select = page.getByRole("combobox", { name: "Select river" });
  await expect(select).toBeEnabled();
  await expect(select.locator("option[value='both']")).toHaveText("All registered rivers");
  await expect(select.locator("option[value='fixture-river']")).toHaveText("Fixture River");
  await select.selectOption("fixture-river");
  await expect(page.locator(".map-legend").getByText("Fixture River · OSM")).toBeVisible();
  await expect(page.locator(".map-legend").getByText("Kaveri River · OSM")).toHaveCount(0);
  await expect(page.getByText("A registered centerline does not establish monitoring coverage.")).toBeVisible();
});

test("registered river search filters choices without changing the map selection", async ({ page }) => {
  const search = page.getByRole("searchbox", { name: "Search registered rivers" });
  const select = page.getByRole("combobox", { name: "Select river" });
  await search.fill("KAVERI");
  await expect(select.locator("option[value='kaveri']")).toHaveCount(1);
  await expect(select.locator("option[value='tungabhadra']")).toHaveCount(0);
  await select.selectOption("kaveri");
  await search.fill("tungabhadra");
  await expect(select).toHaveValue("kaveri");
  await expect(select.locator("option[value='kaveri']")).toHaveCount(1);
  await expect(select.locator("option[value='tungabhadra']")).toHaveCount(1);
  await search.fill("not-a-registered-river");
  await expect(page.getByText("No registered rivers match this search.")).toBeVisible();
  await expect(select).toHaveValue("kaveri");
  await expect(page.locator(".map-legend").getByText("Kaveri River · OSM")).toBeVisible();
  await search.clear();
  await expect(select.locator("option[value='tungabhadra']")).toHaveCount(1);
});

test("NWIC explorer pages search results and retains selected geometry", async ({ page }) => {
  await page.route("**/api/river-network/features?**", async (route) => {
    const url = new URL(route.request().url());
    const offset = Number(url.searchParams.get("offset"));
    const query = url.searchParams.get("q");
    const feature = { source_object_id: offset ? "2" : "1", name: offset ? "Second fixture" : "First fixture" };
    await route.fulfill({ json: { total: query === "missing" ? 0 : 21, limit: 20, offset, features: query === "missing" ? [] : [feature] } });
  });
  await page.route("**/api/river-network/features/1/geometry", (route) => route.fulfill({
    json: { type: "LineString", coordinates: [[76, 15], [76.1, 15.1]] },
  }));
  await page.reload();
  const explorer = page.getByRole("region", { name: "NWIC river network explorer" });
  await explorer.getByRole("button", { name: "First fixture · source ID 1" }).click();
  await expect(explorer.getByText(/satellite status unknown/)).toBeVisible();
  await expect(page.locator(".map-legend").getByText(/NWIC: First fixture/)).toBeVisible();
  await explorer.getByRole("button", { name: "Next rivers" }).click();
  await expect(explorer.getByRole("button", { name: "Second fixture · source ID 2" })).toBeVisible();
  await expect(explorer.getByText(/Selected: First fixture/)).toBeVisible();
  await explorer.getByLabel("River name or source ID").fill("missing");
  await expect(explorer.getByText(/0 matching source features/)).toBeVisible();
  await expect(explorer.getByText(/Selected: First fixture/)).toBeVisible();
});

test("pilot selection cancels a pending NWIC geometry selection", async ({ page }) => {
  await page.route("**/api/river-network/features?**", (route) => route.fulfill({
    json: { total: 1, limit: 20, offset: 0, features: [{ source_object_id: "1", name: "Fixture" }] },
  }));
  let releaseGeometry;
  const geometryReady = new Promise((resolve) => { releaseGeometry = resolve; });
  let geometryRequested;
  const requestStarted = new Promise((resolve) => { geometryRequested = resolve; });
  await page.route("**/api/river-network/features/1/geometry", async (route) => {
    geometryRequested();
    await geometryReady;
    await route.fulfill({ json: { type: "LineString", coordinates: [[76, 15], [77, 16]] } }).catch(() => {});
  });
  await page.reload();
  const explorer = page.getByRole("region", { name: "NWIC river network explorer" });
  await explorer.getByRole("button", { name: "Fixture · source ID 1" }).click();
  await requestStarted;
  await page.getByRole("combobox", { name: "Select river" }).selectOption("kaveri");
  releaseGeometry();
  await expect(explorer.getByRole("button", { name: "Fixture · source ID 1" })).toBeEnabled();
  await expect(explorer.getByText(/Selected: Fixture/)).toHaveCount(0);
  await expect(page.locator(".map-legend").getByText("Kaveri River · OSM")).toBeVisible();
});

test("centerline visibility toggles while unavailable bank layers stay disabled", async ({ page }) => {
  const legend = page.locator(".map-legend");
  const centerline = page.getByRole("button", { name: "Centerline" });

  await expect(page.getByRole("button", { name: "Left bank" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Right bank" })).toBeDisabled();
  await expect(legend.getByText("Kaveri River · OSM")).toBeVisible();

  await centerline.click();
  await expect(centerline).toHaveAttribute("aria-pressed", "false");
  await expect(legend.getByText("Kaveri River · OSM")).toHaveCount(0);

  await centerline.click();
  await expect(centerline).toHaveAttribute("aria-pressed", "true");
  await expect(legend.getByText("Kaveri River · OSM")).toBeVisible();
});

test("compatible persisted Sentinel-1 candidates can be compared with provenance and common support", async ({ page }) => {
  const pair = {
    river_id: "kaveri",
    earlier_analysis_id: "analysis-early",
    later_analysis_id: "analysis-late",
    earlier_source_product_id: "S1_EARLY",
    later_source_product_id: "S1_LATE",
    earlier_acquisition_start: "2026-10-21T00:39:45Z",
    later_acquisition_start: "2026-11-02T00:39:45Z",
    elapsed_days: 12,
    mission: "SENTINEL-1",
    product_type: "GRD-RTC",
    polarization: "VV",
    threshold_method: "otsu",
    earlier_threshold_db: -8.42,
    later_threshold_db: -8.51,
    threshold_delta_db: -0.09,
    filter_method: "Lee 5x5",
    crs: "EPSG:32643",
    pixel_size_m: 10,
    width: 1200,
    height: 1200,
    common_valid_pixel_count: 436083,
    common_valid_area_m2: 43608300,
    common_valid_fraction: 0.302835,
    earlier_source_record_url: "https://example.test/earlier",
    later_source_record_url: "https://example.test/later",
    seasonal_context: "Acquisitions are 12 days apart; no seasonal adjustment was applied.",
    parameter_compatibility: "The same Otsu method and filter were used, but the threshold was estimated separately for each date.",
    caveats: ["Unvalidated candidates."],
  };
  await page.route("**/api/analysis/temporal-pairs**", async (route) => {
    await route.fulfill({ json: [pair] });
  });
  await page.route("**/api/analysis/change", async (route) => {
    await route.fulfill({
      json: {
        change_id: "change-fixture",
        analysis_type: "two_date_water_extent_comparison",
        status: "unvalidated_candidate",
        earlier_analysis_id: pair.earlier_analysis_id,
        later_analysis_id: pair.later_analysis_id,
        earlier_source_product_id: pair.earlier_source_product_id,
        later_source_product_id: pair.later_source_product_id,
        earlier_acquisition_start: pair.earlier_acquisition_start,
        later_acquisition_start: pair.later_acquisition_start,
        mission: pair.mission,
        product_type: pair.product_type,
        polarization: pair.polarization,
        threshold_method: pair.threshold_method,
        earlier_threshold_db: pair.earlier_threshold_db,
        later_threshold_db: pair.later_threshold_db,
        threshold_delta_db: pair.threshold_delta_db,
        filter_method: pair.filter_method,
        crs: pair.crs,
        pixel_size_m: pair.pixel_size_m,
        common_valid_pixel_count: pair.common_valid_pixel_count,
        common_valid_area_m2: pair.common_valid_area_m2,
        common_valid_fraction: pair.common_valid_fraction,
        water_gain_pixel_count: 100,
        water_loss_pixel_count: 80,
        pixel_area_m2: 100,
        candidate_water_gain_area_m2: 10000,
        candidate_water_loss_area_m2: 8000,
        change_mask_url: "/api/analysis/change-fixture/mask",
        report_url: "/api/analysis/change-fixture/report",
        caveats: pair.caveats,
      },
    });
  });
  await page.reload();
  await page.getByRole("button", { name: "Change analysis" }).click();

  await expect(page.getByRole("heading", { name: "Persisted satellite candidate comparisons" })).toBeVisible();
  await expect(page.getByText("Common valid support: 436,083 pixels")).toBeVisible();
  await page.getByRole("button", { name: "Compare candidates" }).click();
  await expect(page.getByText("Unvalidated candidate extent comparison")).toBeVisible();
  await expect(page.getByText(/Candidate-water gain 10,000 m²/)).toBeVisible();
});

test("acquisition jobs show stage, errors, and a retry action", async ({ page }) => {
  const failedJob = {
    job_id: "job-failed-1",
    river_id: "tungabhadra",
    satellite: "NISAR",
    product_id: "NISAR_TEST_PRODUCT",
    job_type: "nisar_processing",
    status: "failed",
    created_at: "2026-11-09T08:00:00Z",
    started_at: "2026-11-09T08:01:00Z",
    completed_at: "2026-11-09T08:02:00Z",
    progress_percent: null,
    current_stage: "Failed",
    error_message: "Fixture processing error",
    output_references: {},
    retry_of_job_id: null,
  };
  await page.route("**/api/acquisition-jobs**", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 202,
        json: { ...failedJob, job_id: "job-retry-1", status: "queued", error_message: null, retry_of_job_id: failedJob.job_id },
      });
      return;
    }
    await route.fulfill({ json: [failedJob] });
  });
  await page.reload();

  await expect(page.getByRole("heading", { name: "Acquisition and processing jobs" })).toBeVisible();
  await expect(page.getByText("Fixture processing error")).toBeVisible();
  await expect(page.getByText("Stage-based progress; percentage not reported")).toBeVisible();
  await page.getByRole("button", { name: "Retry failed job" }).click();
  await expect(page.getByText("Retry of job job-failed-1")).toBeVisible();
});

test("Sentinel-2 candidate details remain explicitly exploratory", async ({ page }) => {
  const productId = "NISAR_OPTICAL_FIXTURE";
  let failPreview = false;
  const processingResult = {
    status: "unvalidated_candidate",
    input_crs: "EPSG:32643",
    pixel_size_m: 10,
    valid_pixel_count: 100,
    valid_data_fraction: 1,
    candidate_water_area_m2: 1000,
    candidate_water_area_lower_m2: 800,
    candidate_water_area_upper_m2: 1200,
    covered_centerline_length_km: 1,
    reference_centerline_length_km: 2,
    reference_centerline_coverage_percent: 50,
    polarization_comparison: [],
    threshold_sensitivity: [],
    connected_component_summary: null,
    geojson_display_note: null,
    mask_url: null,
    measurements_url: null,
    comparison_url: null,
    sensitivity_url: null,
    polygons_url: `/api/analysis/${productId}/polygons`,
    metadata_url: null,
    optical_reference_url: `/api/acquisitions/nisar/${productId}/processing/sentinel2-reference?river_id=tungabhadra`,
    optical_candidate_mask_url: `/api/acquisitions/nisar/${productId}/processing/sentinel2-reference/mask?river_id=tungabhadra`,
  };
  await page.route("**/api/acquisitions", async (route) => {
    await route.fulfill({
      json: {
        enabled: false,
        polling_interval_seconds: 21600,
        source: "Microsoft Planetary Computer Sentinel-1 RTC",
        source_url: "https://planetarycomputer.microsoft.com/",
        license: "CC-BY-4.0",
        rivers: [{
          ...acquisitionRiver("tungabhadra"),
          nisar_status: "metadata_found",
          nisar_products: [{
            product_id: productId,
            product_level: "GCOV",
            polarization: ["HH", "HV"],
            size_bytes: 10,
            availability: "downloaded_verified",
            download_status: "downloaded",
            hdf5_groups: [],
            processing_status: "processed",
            processing_result: processingResult,
          }],
          observations: [],
          issues: [],
        }],
      },
    });

  });
  await page.route("**/sentinel2-reference?*", async (route) => {
    await route.fulfill({
      json: {
        status: "unvalidated_candidate",
        classification: "exploratory Sentinel-2 NDWI water candidate",
        ndwi_threshold: 0,
        grid: { pixel_area_m2: 100 },
        counts: {
          common_valid_pixels: 1011220,
          ndwi_candidate_pixels: 69498,
          candidate_area_m2: 6949800,
        },
        source: {
          item_id: "S2C_MSIL2A_20261106T052011_R062_T43PGT_20261106T101206",
          acquisition_datetime: "2026-11-06T05:20:11.025000Z",
          catalog_cloud_cover_percent: 38.783842,
        },
        nisar_acquisition_datetime: "2026-11-06T00:25:20Z",
        acquisition_time_difference_seconds: 17691.025,
        mapped_centerline_coverage_percent: 21.7962,
        preview_url: `/api/acquisitions/nisar/${productId}/processing/sentinel2-reference/preview?river_id=tungabhadra`,
        bounds_wgs84: { west: 75.5, south: 14, east: 78.3, north: 16 },
        crs: "EPSG:32643",
        dimensions: { width: 10302, height: 7746 },
        nodata_value: 255,
        additional_observations: [{
          status: "unvalidated_candidate",
          classification: "exploratory Sentinel-2 NDWI water candidate",
          ndwi_threshold: 0,
          grid: { pixel_area_m2: 100 },
          counts: {
            common_valid_pixels: 1630335,
            ndwi_candidate_pixels: 122670,
            candidate_area_m2: 12267000,
          },
          source: {
            item_id: "S2C_MSIL2A_20261106T052011_R062_T43PES_20261106T101206",
            mgrs_tile: "43PES",
            acquisition_datetime: "2026-11-06T05:20:11.025000Z",
            catalog_cloud_cover_percent: 41.829962,
          },
          acquisition_time_difference_seconds: 17691.025,
          preview_url: `/api/acquisitions/nisar/${productId}/processing/sentinel2-observations/S2C_MSIL2A_20261106T052011_R062_T43PES_20261106T101206/preview?river_id=tungabhadra`,
          mask_url: `/api/acquisitions/nisar/${productId}/processing/sentinel2-observations/S2C_MSIL2A_20261106T052011_R062_T43PES_20261106T101206/mask?river_id=tungabhadra`,
          bounds_wgs84: { west: 75.5, south: 14, east: 78.3, north: 16 },
          crs: "EPSG:32643",
          nodata_value: 255,
        }],
        limitations: ["This is an unvalidated optical candidate classification, not ground truth."],
      },
    });
  });
  await page.route(/\/preview\?/, async (route) => {
    if (failPreview && route.request().url().includes("sentinel2-reference")) {
      await route.fulfill({ status: 503, body: "Preview unavailable" });
    } else {
      await route.fulfill({
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/r9sAAAAASUVORK5CYII=",
          "base64",
        ),
      });
    }
  });
  await page.route(`**/analysis/${productId}/polygons`, async (route) => {
    await route.fulfill({
      json: {
        type: "FeatureCollection",
        features: [{
          type: "Feature",
          properties: {},
          geometry: {
            type: "Polygon",
            coordinates: [[[76, 15], [76.01, 15], [76.01, 15.01], [76, 15.01], [76, 15]]],
          },
        }],
      },
    });
  });
  await page.reload();

  await page.getByRole("button", { name: "Show exploratory comparison details" }).click();
  await expect(page.getByText(/Common valid pixels: 1,011,220/)).toBeVisible();
  await expect(page.getByText("Catalog tile cloud cover: 38.78%")).toBeVisible();
  await expect(page.getByText(/optical candidates: 69,498/)).toBeVisible();
  await expect(page.getByText(/Common valid area: 101\.122 km²/)).toBeVisible();
  await expect(page.getByText(/mapped centerline coverage: ~21.8%/)).toBeVisible();
  await expect(page.getByText(/offset: 4 h 54 min 51\.025 sec/)).toBeVisible();
  await expect(page.getByText(/not ground truth/i).last()).toBeVisible();
  await expect(page.getByText(/Common valid pixels: 1,630,335/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Show Sentinel-2 43PES candidate on map" })).toBeVisible();
  await page.getByRole("button", { name: "Show Sentinel-2 43PES candidate on map" }).click();
  await expect(page.locator("img.leaflet-image-layer")).toBeVisible();
  await page.getByRole("button", { name: "Remove Sentinel-2 43PES layer from map" }).click();
  await page.getByRole("button", { name: "Show Sentinel-2 candidate on map" }).click();
  const opticalImage = page.locator("img.leaflet-image-layer");
  await expect(opticalImage).toBeVisible();
  await expect(page.getByText("EXPLORATORY SENTINEL-2 NDWI OUTPUT — NOT GROUND TRUTH.")).toBeVisible();
  await expect(page.getByText("Not classified as candidate")).toBeVisible();
  await expect(page.getByText("NoData / invalid / unavailable")).toBeVisible();
  await page.getByRole("button", { name: "Show NISAR candidate on map" }).click();
  await expect(page.getByText("Candidate water · unvalidated")).toBeVisible();
  await expect(opticalImage).toBeVisible();
  await page.getByRole("button", { name: "Remove Sentinel-2 layer from map" }).click();
  await expect(opticalImage).toHaveCount(0);
  await expect(page.getByText("Candidate water · unvalidated")).toBeVisible();
  failPreview = true;
  await page.getByRole("button", { name: "Show Sentinel-2 candidate on map" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Sentinel-2 preview could not be loaded" })).toBeVisible();
  await page.getByRole("button", { name: "Remove Sentinel-2 layer from map" }).click();
  await expect(page.getByText("Candidate water · unvalidated")).toBeVisible();
  await expect(page.getByRole("link", { name: "Sentinel-2 NDWI candidate GeoTIFF" })).toHaveAttribute(
    "href",
    new RegExp("sentinel2-reference/mask"),
  );
});

test("rule-based river analysis reports real-catalog candidate context without accuracy claims", async ({ page }) => {
  await page.getByRole("button", { name: "AI analysis" }).click();
  await expect(page.getByRole("heading", { name: "AI-Powered River Analysis" })).toBeVisible();
  await page.getByRole("combobox", { name: "Analysis river" }).selectOption("tungabhadra");

  await expect(page.getByText("NISAR candidate result is unvalidated.")).toBeVisible();
  await expect(page.getByText("0.0250 km²").first()).toBeVisible();
  await expect(page.getByText("Selected observation provenance")).toBeVisible();
  await expect(page.getByText("ASF DAAC", { exact: false }).first()).toBeVisible();
  await expect(page.getByText(/EPSG:32643/)).toBeVisible();
  await expect(page.getByRole("region", { name: "Data-grounded river analysis" }).getByText("Evidence status", { exact: true })).toBeVisible();
  await expect(page.getByText("HH+HV: 0.0300 km²")).toBeVisible();
  await expect(page.getByText("RULE-BASED", { exact: true })).toBeVisible();
  await expect(page.getByText(/no external AI service/i)).toBeVisible();
  await expect(page.getByText("No imported reference or matching validation report is available.")).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Select river" })).toHaveValue("tungabhadra");
  await page.getByRole("combobox", { name: "Analysis satellite product" }).selectOption("S1_FIXTURE");
  await expect(page.getByText(/Product selection changed to S1_FIXTURE/)).toBeVisible();
  await expect(page.getByText("Selected observation provenance")).toHaveCount(0);
  await page.getByRole("combobox", { name: "Analysis satellite product" }).selectOption("NISAR_A009_FIXTURE");
  await page.getByRole("button", { name: "Run analysis" }).click();
  await expect(page.getByText("NISAR candidate result is unvalidated.")).toBeVisible();
});

test("selected ASF discovery observation updates the river and is not mistaken for processed analysis", async ({ page }) => {
  await page.route("**/api/analysis/ai-summary", async (route) => {
    const body = JSON.parse(route.request().postData() ?? "{}");
    await route.fulfill({
      json: {
        analysis_id: "empty-kaveri-analysis",
        generated_at: "2026-11-09T12:00:00Z",
        analysis_mode: "deterministic_rule_based",
        data_mode: "persisted_satellite_acquisition_catalog",
        river_id: body.river_id,
        selected_product_id: null,
        products: [],
        coverage: {
          catalog_product_count: 0,
          usable_candidate_count: 0,
          no_data_product_count: 0,
          failed_product_count: 0,
          mapped_centerline_coverage_percent: null,
          corridor_half_width_m: null,
        },
        candidate_metrics: null,
        threshold_sensitivity: null,
        polarization_comparison: [],
        optical_comparison: {
          available: false,
          status: "not_available",
          warning: "No linked optical candidate.",
        },
        temporal_comparison: {
          status: "insufficient_observations",
          available_pair_count: 0,
          explanation: "Fewer than two usable candidate observations are available for this river.",
        },
        validation_status: "independent_reference_unavailable",
        findings: ["No usable processed candidate output is available for this river."],
        warnings: ["No independent reference."],
        limitations: ["No accuracy metrics are available."],
        recommended_next_steps: ["Obtain independently reviewed labels."],
      },
    });
  });
  await page.route("**/api/satellite/search?**", async (route) => {
    await route.fulfill({
      json: {
        river_id: "kaveri",
        mission: "NISAR",
        product_type: "GCOV",
        query_start: "2026-10-01T00:00:00Z",
        query_end: "2026-11-09T23:59:59Z",
        source: "ASF DAAC",
        source_url: "https://search.asf.alaska.edu/",
        observations: [{
          id: "NISAR_DISCOVERY_ONLY",
          mission: "NISAR",
          source: "ASF DAAC",
          analysis_readiness: "Catalog metadata only; not downloaded.",
          acquisition_start: "2026-11-08T00:25:20Z",
          product_type: "L2_GCOV",
          footprint: {
            type: "Polygon",
            coordinates: [[[75.8, 12.3], [76.0, 12.3], [76.0, 12.5], [75.8, 12.5], [75.8, 12.3]]],
          },
        }],
        note: "Test-only metadata fixture.",
      },
    });
  });
  const searchPanel = page.locator(".satellite-search-panel");
  await searchPanel.scrollIntoViewIfNeeded();
  await searchPanel.getByRole("button", { name: /Search ASF/ }).click();
  await searchPanel.getByRole("button", { name: /NISAR_DISCOVERY_ONLY/ }).click();

  await expect(page.getByRole("combobox", { name: "Select river" })).toHaveValue("kaveri");
  await expect(page.locator(".map-legend").getByText("NISAR footprint · metadata only")).toBeVisible();
  await page.getByRole("button", { name: "AI analysis" }).click();
  const analysisPanel = page.getByRole("article", { name: "AI-Powered River Analysis" });
  await expect(analysisPanel.getByText(/is discovery metadata only and is not in the persisted processed-product catalog/i)).toBeVisible();
  await expect(analysisPanel.getByText("NISAR_DISCOVERY_ONLY · NISAR · L2_GCOV")).toBeVisible();
  await expect(analysisPanel.getByText("No usable processed candidate output is available for this river.")).toBeVisible();
});

test("AI analysis renders an explicit empty-catalog state", async ({ page }) => {
  await page.route("**/api/analysis/ai-summary", async (route) => {
    await route.fulfill({
      json: {
        analysis_id: "empty-analysis",
        generated_at: "2026-11-09T12:00:00Z",
        analysis_mode: "deterministic_rule_based",
        data_mode: "persisted_satellite_acquisition_catalog",
        river_id: "kaveri",
        selected_product_id: null,
        products: [],
        coverage: {
          catalog_product_count: 0,
          usable_candidate_count: 0,
          no_data_product_count: 0,
          failed_product_count: 0,
          mapped_centerline_coverage_percent: null,
          corridor_half_width_m: null,
        },
        candidate_metrics: null,
        threshold_sensitivity: null,
        polarization_comparison: [],
        optical_comparison: { available: false, status: "not_available", warning: "No linked optical candidate." },
        temporal_comparison: {
          status: "insufficient_observations",
          available_pair_count: 0,
          explanation: "Fewer than two usable candidate observations are available for this river.",
        },
        validation_status: "independent_reference_unavailable",
        findings: ["No usable processed candidate output is available for this river."],
        warnings: ["No independent reference."],
        limitations: ["No accuracy metrics are available."],
        recommended_next_steps: ["Obtain independent labels."],
      },
    });
  });
  await page.getByRole("combobox", { name: "Analysis river" }).selectOption("kaveri");

  await expect(page.getByText("No usable processed candidate output is available for this river.")).toBeVisible();
  await expect(page.getByText("0 catalog product(s)")).toBeVisible();
  await expect(page.getByText("Unavailable").first()).toBeVisible();
});

test("AI analysis displays API errors instead of a success-shaped fallback", async ({ page }) => {
  await page.route("**/api/analysis/ai-summary", async (route) => {
    await route.fulfill({ status: 503, json: { detail: "Analysis service unavailable." } });
  });
  await page.getByRole("combobox", { name: "Analysis river" }).selectOption("kaveri");

  await expect(page.getByRole("alert").filter({ hasText: "Analysis service unavailable." })).toBeVisible();
});

test("independent validation explains the pending state and requires reviewed input files", async ({ page }) => {
  const workspace = page.getByRole("article", { name: "Independent reference validation" });
  await workspace.scrollIntoViewIfNeeded();

  await expect(workspace.getByRole("heading", { name: "Independent reference validation" })).toBeVisible();
  await expect(workspace.getByRole("status")).toContainText("No suitable reviewed reference labels are currently available.");
  await expect(workspace.getByText(/cannot independently verify a provider, reviewer/i)).toBeVisible();
  await expect(workspace.getByText(/Do not use Sentinel-2 NDWI as an independent reference/i)).toBeVisible();
  const validationForm = workspace.locator("form").last();
  await expect(validationForm.getByLabel("Candidate mask GeoTIFF (0/1/255)")).toBeVisible();
  await expect(validationForm.getByLabel("Reviewed reference GeoTIFF (1 water, 0 non-water, 255 uncertain/NoData)")).toBeVisible();
  await expect(workspace.getByRole("button", { name: "Validate against reviewed labels" })).toBeDisabled();
});

test("reference catalog explains source limitations and reviewed labels can be imported", async ({ page }) => {
  const workspace = page.getByRole("article", { name: "Independent reference validation" });
  let importedRecord = null;
  await page.route("**/api/analysis/reference-data", async (route) => {
    if (route.request().method() === "POST") {
      importedRecord = {
        reference_id: "reviewed-fixture",
        metadata: { dataset_id: "landsat-scene-fixture", provider: "USGS EROS" },
        width: 20,
        height: 20,
        label_counts: { "0": 200, "1": 100, "255": 100 },
        nodata_value: 255,
        review_attestation: "Test-only reviewer attestation.",
        labels_url: "/api/analysis/reference-data/reviewed-fixture/labels",
      };
      await route.fulfill({ status: 201, json: importedRecord });
      return;
    }
    await route.fulfill({ json: importedRecord ? [importedRecord] : [] });
  });
  await page.route("**/api/analysis/validation/status", async (route) => {
    await route.fulfill({
      json: importedRecord
        ? {
          status: "reference_dataset_available",
          message: "User-imported reviewed reference rasters are available. Their suitability, independence, and review quality are not authenticated; no completed validation report currently meets the evidence requirements.",
          reports: [],
        }
        : {
          status: "validation_pending",
          message: "Independent scientific validation pending. No suitable reviewed reference labels are currently available.",
          reports: [],
        },
    });
  });
  await page.reload();
  await workspace.scrollIntoViewIfNeeded();
  await expect(workspace.getByRole("link", { name: referenceSources[0].name })).toBeVisible();
  await expect(workspace.getByRole("link", { name: "Official source" })).toBeVisible();
  await expect(workspace.getByRole("link", { name: "Access / download" })).toBeVisible();
  await expect(workspace.getByText(/Spatial reference: Scene-specific CRS/)).toBeVisible();
  await expect(workspace.getByText(/does not download data or convert contextual products into ground truth/i)).toBeVisible();

  await workspace.getByText("Import an independently reviewed reference GeoTIFF").click();
  await workspace.getByLabel("Dataset ID", { exact: true }).fill("landsat-scene-fixture");
  await workspace.getByLabel("Provider", { exact: true }).fill("USGS EROS");
  await workspace.getByLabel("Source URL", { exact: true }).fill(referenceSources[0].source_url);
  await workspace.getByLabel("Acquisition time (local)", { exact: true }).fill("2026-11-06T03:00");
  await workspace.getByLabel("Resolution (metres)", { exact: true }).fill("30");
  await workspace.getByLabel("Raster CRS", { exact: true }).fill("EPSG:32643");
  await workspace.getByLabel("License", { exact: true }).fill("USGS Landsat terms");
  const importForm = workspace.locator("details.validation-reference-import form");
  await importForm.getByLabel("Reviewer", { exact: true }).fill("fixture reviewer");
  await importForm.getByLabel("Review date", { exact: true }).fill("2026-11-09");
  await importForm.getByLabel("Reviewed 0/1/255 GeoTIFF").setInputFiles({
    name: "reviewed-labels.tif",
    mimeType: "image/tiff",
    buffer: Buffer.from("test fixture only"),
  });
  await importForm.getByLabel("Review method").fill("Human review of a test fixture.");
  await importForm.getByLabel("Limitations, one per line").fill("No real reference labels are included.");
  await importForm.getByLabel(/I confirm these labels were independently reviewed/).check();
  await workspace.getByRole("button", { name: "Import reviewed labels" }).click();

  await expect(workspace.getByText("Stored reviewed label raster reviewed-fixture.", { exact: true })).toBeVisible();
  await expect(workspace.getByRole("status").filter({ hasText: "User-imported reviewed reference rasters are available." })).toBeVisible();
  await expect(workspace.getByRole("link", { name: "landsat-scene-fixture · USGS EROS · 20 × 20" })).toBeVisible();
});

test("method comparison reports common support and limitations without selecting a winner", async ({ page }) => {
  const result = {
    evaluation_id: "fixture-method-evaluation",
    status: "evaluation_completed",
    river_id: "tungabhadra",
    candidate_product_id: "NISAR_A009_FIXTURE",
    candidate_acquisition_datetime: "2026-11-06T00:25:20Z",
    reference_dataset_id: "REVIEWED_FIXTURE",
    reference_acquisition_datetime: "2026-11-06T03:00:00Z",
    temporal_offset_seconds: 9260,
    shared_common_valid_pixel_count: 500,
    shared_reference_coverage_fraction: 0.8,
    candidate_crs: "EPSG:32643",
    pixel_area_m2: 100,
    methods: [{
      method_id: "threshold-a",
      method_name: "HH threshold",
      parameters: { threshold_db: -12 },
      candidate_area_m2: 15000,
      difference_from_first_area_m2: 0,
      confusion_matrix: { true_positive: 100, true_negative: 300, false_positive: 50, false_negative: 50 },
      precision: 2 / 3,
      recall: 2 / 3,
      f1_score: 2 / 3,
      intersection_over_union: 0.5,
    }, {
      method_id: "threshold-b",
      method_name: "HH+HV threshold",
      parameters: { hh_db: -12, hv_db: -18 },
      candidate_area_m2: 17000,
      difference_from_first_area_m2: 4000,
      confusion_matrix: { true_positive: 110, true_negative: 290, false_positive: 60, false_negative: 40 },
      precision: 110 / 170,
      recall: 110 / 150,
      f1_score: 0.6875,
      intersection_over_union: 0.5238,
    }],
    warnings: ["Test-only fixture; no method winner is selected."],
    report_url: "/api/analysis/validation/method-comparisons/fixture-method-evaluation",
  };
  await page.route("**/api/analysis/validation/methods", async (route) => {
    await route.fulfill({ status: 201, json: result });
  });
  const workspace = page.getByRole("article", { name: "Independent reference validation" });
  const methodDetails = workspace.locator("details.validation-method-evaluation");
  await workspace.scrollIntoViewIfNeeded();
  await methodDetails.locator("summary").click();
  await methodDetails.getByLabel("Candidate product ID").fill("NISAR_A009_FIXTURE");
  await methodDetails.getByLabel("Candidate sensor").fill("NISAR L-band GCOV");
  await methodDetails.getByLabel("Candidate acquisition (local)").fill("2026-11-06T00:25");
  await methodDetails.getByLabel("Reference dataset ID").fill("REVIEWED_FIXTURE");
  await methodDetails.getByLabel("Reference provider").fill("Independently reviewed fixture");
  await methodDetails.getByLabel("Reference acquisition (local)").fill("2026-11-06T03:00");
  await methodDetails.getByLabel("Reference resolution (m)").fill("10");
  await methodDetails.getByLabel("Minimum common pixels").fill("100");
  await methodDetails.getByLabel("Minimum reference coverage fraction").fill("0.5");
  await methodDetails.getByLabel("Minimum pixels per reference class").fill("10");
  await methodDetails.getByLabel("Spatial block size (pixels)").fill("4");
  await methodDetails.getByLabel("Minimum occupied blocks per reference class").fill("2");
  await methodDetails.getByLabel("Reviewer").fill("fixture reviewer");
  await methodDetails.getByLabel("Review date").fill("2026-11-09");
  await methodDetails.getByLabel("Reviewed reference GeoTIFF (0/1/255)").setInputFiles({
    name: "reviewed-reference-fixture.tif",
    mimeType: "image/tiff",
    buffer: Buffer.from("test fixture only"),
  });
  for (const [index, title] of ["Candidate method 1", "Candidate method 2"].entries()) {
    const candidate = methodDetails.locator(".method-candidate-input").nth(index);
    await candidate.getByLabel("Method name").fill(title);
    await candidate.getByLabel("Parameters (JSON scalar values)").fill(JSON.stringify({ threshold_db: -12 - index }));
    await candidate.getByLabel("Candidate mask GeoTIFF (0/1/255)").setInputFiles({
      name: `method-${index + 1}.tif`,
      mimeType: "image/tiff",
      buffer: Buffer.from("test fixture only"),
    });
  }
  await methodDetails.getByLabel("Reference methodology").fill("Test fixture only.");
  await methodDetails.getByLabel("Limitations, one per line").fill("Mocked response, not scientific evidence.");
  await methodDetails.getByLabel(/I confirm these reference labels were independently reviewed/).check();
  await methodDetails.getByRole("button", { name: "Evaluate both methods" }).click();

  const report = methodDetails.getByRole("region", { name: "Method comparison result" });
  await expect(report).toContainText("evaluation completed · no method selected");
  await expect(report).toContainText("500 shared valid pixels");
  await expect(report).toContainText("Candidate/reference time offset: 2.57 hours");
  await expect(report).toContainText("HH threshold");
  await expect(report).toContainText("HH+HV threshold");
  await expect(report).toContainText("Candidate area: 17,000 m²");
  await expect(report).toContainText("differing area from first method: 4,000 m²");
});

test("exploratory method comparison works without reference labels and surfaces API errors", async ({ page }) => {
  let fail = false;
  await page.route("**/api/analysis/validation/methods/exploratory", async (route) => {
    expect(route.request().postData()).not.toContain('name="reference_file"');
    await route.fulfill(fail ? { status: 422, json: { detail: "Candidate grids differ." } } : {
      json: {
        status: "exploratory_comparison",
        shared_common_valid_pixel_count: 3,
        shared_grid_coverage_fraction: 0.75,
        methods: [
          { method_id: "method-a", method_name: "Method A", parameters: {}, candidate_area_m2: 200, difference_from_first_area_m2: 0 },
          { method_id: "method-b", method_name: "Method B", parameters: {}, candidate_area_m2: 100, difference_from_first_area_m2: 100 },
        ],
        pairwise_comparisons: [{
          first_method_id: "method-a", second_method_id: "method-b",
          absolute_area_difference_m2: 100, area_difference_fraction_of_first: 0.5,
          disagreement_fraction: 1 / 3, intersection_over_union: 0.5,
        }],
        warnings: ["No reference labels were supplied; no method is selected as best."],
      },
    });
  });
  const analysis = page.locator("article.analysis-workspace");
  await expect(analysis.getByRole("link", { name: /Compare candidate classification methods/ })).toHaveAttribute("href", "#method-comparison");
  const details = page.locator("details.validation-method-evaluation");
  await details.locator("summary").click();
  await details.getByLabel("Comparison mode").selectOption("exploratory");
  await details.getByLabel("Candidate product ID").fill("fixture");
  for (const candidate of await details.locator(".method-candidate-input").all()) {
    await candidate.getByLabel("Candidate mask GeoTIFF (0/1/255)").setInputFiles({
      name: "candidate.tif", mimeType: "image/tiff", buffer: Buffer.from("fixture"),
    });
  }
  await details.getByRole("button", { name: "Evaluate both methods" }).click();
  const report = details.getByRole("region", { name: "Method comparison result" });
  await expect(report).toContainText("exploratory comparison · no method selected");
  await expect(report).toContainText("75.00% grid coverage");
  await expect(report).toContainText("Candidate area: 100 m²");
  await expect(report).toContainText("differing area from first method: 100 m²");
  await expect(report).toContainText("candidate-mask IoU 50.00% (not accuracy)");
  await expect(report).toContainText("difference relative to first 50.00%");
  await expect(report).not.toContainText("Precision");
  fail = true;
  await details.getByRole("button", { name: "Evaluate both methods" }).click();
  await expect(details.getByRole("alert")).toContainText("Candidate grids differ.");
  await expect(report).toHaveCount(0);
});

test("axis sampling displays per-station candidate quality and unquantified uncertainty", async ({ page }) => {
  await page.route("**/api/analysis/water-mask", async (route) => {
    await route.fulfill({
      status: 201,
      json: {
        analysis_id: "fixture-axis-analysis",
        river_id: "tungabhadra",
        source_product_id: "NISAR_A009_AXIS_FIXTURE",
        acquisition_start: "2026-11-06T00:25:20Z",
        candidate_water_area_m2: 10000,
        candidate_water_area_lower_m2: 8000,
        candidate_water_area_upper_m2: 12000,
        mask_url: "/api/analysis/fixture-axis-analysis/mask",
        polygons_url: "/api/analysis/fixture-axis-analysis/polygons",
        report_url: "/api/analysis/fixture-axis-analysis/report",
      },
    });
  });
  await page.route("**/api/analysis/width/river-axis", async (route) => {
    await route.fulfill({
      json: {
        analysis_id: "fixture-axis-analysis",
        source_product_id: "NISAR_A009_AXIS_FIXTURE",
        acquisition_start: "2026-11-06T00:25:20Z",
        axis_dataset_id: "USER_AXIS_FIXTURE",
        axis_source_name: "Test-only user geometry",
        axis_source_url: "https://example.test/axis",
        axis_geometry_status: "user_supplied_not_independently_verified",
        axis_length_m: 400,
        station_spacing_m: 200,
        transect_half_length_m: 100,
        raster_resolution_m: 10,
        requested_station_count: 3,
        accepted_station_count: 1,
        coverage_fraction: 1 / 3,
        uncertainty_m: null,
        uncertainty_status: "not_quantified",
        samples: [{
          chainage_m: 0,
          candidate_width_m: 30,
          valid_fraction: 1,
          raster_coverage_fraction: 1,
          sampled_pixel_count: 21,
          valid_pixel_count: 21,
          quality_status: "usable_candidate",
          quality_flags: ["Test-only candidate segment."],
        }, {
          chainage_m: 200,
          candidate_width_m: null,
          valid_fraction: 0.4,
          raster_coverage_fraction: 1,
          sampled_pixel_count: 21,
          valid_pixel_count: 8,
          quality_status: "low_valid_coverage",
          quality_flags: ["Insufficient valid support."],
        }, {
          chainage_m: 400,
          candidate_width_m: null,
          valid_fraction: 1,
          raster_coverage_fraction: 1,
          sampled_pixel_count: 21,
          valid_pixel_count: 21,
          quality_status: "no_candidate",
          quality_flags: ["No candidate pixels at this station."],
        }],
        quality_flags: ["Fixture geometry is not independently verified."],
        caveats: ["Candidate segment is not surveyed bank width."],
      },
    });
  });
  const workspace = page.locator("article.analysis-workspace");
  await workspace.getByLabel("Source product ID").fill("NISAR_A009_AXIS_FIXTURE");
  await workspace.getByLabel("Acquisition time (local)").fill("2026-11-06T00:25");
  await workspace.getByLabel("Polarization").fill("HH+HV");
  await workspace.getByLabel("Exported band description").fill("fixture power-derived input");
  await workspace.getByLabel("Calibrated GeoTIFF").setInputFiles({
    name: "candidate-mask-input.tif",
    mimeType: "image/tiff",
    buffer: Buffer.from("test fixture only"),
  });
  await workspace.getByLabel("I confirm radiometric calibration is complete.").check();
  await workspace.getByLabel("I confirm terrain correction/geocoding is complete.").check();
  await workspace.getByRole("button", { name: "Create candidate water mask" }).click();

  await workspace.getByLabel("Axis dataset ID").fill("USER_AXIS_FIXTURE");
  await workspace.getByLabel("Geometry source name").fill("Test-only user geometry");
  await workspace.getByLabel("Source URL").fill("https://example.test/axis");
  await workspace.getByLabel("Axis GeoJSON (WGS84 LineString)").fill(JSON.stringify({
    type: "LineString",
    coordinates: [[76, 15], [76.01, 15]],
  }));
  await workspace.getByLabel("Corridor GeoJSON (WGS84 Polygon or MultiPolygon)").fill(JSON.stringify({
    type: "Polygon",
    coordinates: [[[75.99, 14.99], [76.02, 14.99], [76.02, 15.01], [75.99, 15.01], [75.99, 14.99]]],
  }));
  await workspace.getByRole("button", { name: "Sample candidate segments" }).click();

  const result = workspace.getByRole("region", { name: "Candidate axis sampling results" });
  await expect(result).toContainText("Accepted 1/3 stations");
  await expect(result).toContainText("Measurement uncertainty: not quantified");
  await expect(result).toContainText("Candidate segment: 30.0 m");
  await expect(result).toContainText("low valid coverage");
  await expect(result).toContainText("no candidate");
});

test("independent validation displays completed report metrics from the API", async ({ page }) => {
  await page.route("**/api/analysis/validation", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        json: {
          status: "validation_pending",
          message: "Independent scientific validation pending.",
          reports: [],
        },
      });
      return;
    }
    await route.fulfill({
      status: 201,
      json: {
        validation_id: "fixture-validation",
        status: "validation_completed",
        river_id: "tungabhadra",
        candidate_product_id: "NISAR_A009_FIXTURE",
        candidate_sensor: "NISAR L-band GCOV",
        candidate_acquisition_datetime: "2026-11-06T00:25:20Z",
        reference_dataset_id: "REVIEWED_FIXTURE",
        reference_provider: "Test-only fixture",
        reference_acquisition_datetime: "2026-11-06T03:00:00Z",
        acquisition_time_difference_seconds: 9280,
        reference_resolution_m: 10,
        reference_crs: "EPSG:32643",
        candidate_crs: "EPSG:32643",
        reviewer: "test reviewer",
        review_date: "2026-11-09",
        reference_methodology: "Test-only fixture response; no real reference labels.",
        limitations: ["Browser test fixture only."],
        confusion_matrix: {
          true_positive: 9,
          true_negative: 8,
          false_positive: 1,
          false_negative: 2,
        },
        precision: 0.9,
        recall: 0.8181818182,
        f1_score: 0.8571428571,
        intersection_over_union: 0.75,
        candidate_valid_pixel_count: 20,
        reference_valid_pixel_count_on_candidate_grid: 20,
        common_valid_pixel_count: 20,
        valid_reference_coverage_fraction: 1,
        pixel_area_m2: 100,
        resampling: "nearest",
        report_url: "/api/analysis/validation/fixture-validation",
        warnings: ["Browser test fixture only; not a scientific result."],
      },
    });
  });
  const workspace = page.getByRole("article", { name: "Independent reference validation" });
  const validationForm = workspace.locator("form").last();
  await workspace.scrollIntoViewIfNeeded();
  await validationForm.getByLabel("Candidate product ID").fill("NISAR_A009_FIXTURE");
  await validationForm.getByLabel("Candidate sensor").fill("NISAR L-band GCOV");
  await validationForm.getByLabel("Candidate acquisition (local time)").fill("2026-11-06T00:25");
  await validationForm.getByLabel("Candidate mask GeoTIFF (0/1/255)").setInputFiles({
    name: "candidate.tif",
    mimeType: "image/tiff",
    buffer: Buffer.from("fixture"),
  });
  await validationForm.getByLabel("Reference dataset ID").fill("REVIEWED_FIXTURE");
  await validationForm.getByLabel("Reference provider").fill("Test-only fixture");
  await validationForm.getByLabel("Reference acquisition (local time)").fill("2026-11-06T03:00");
  await validationForm.getByLabel("Reference resolution (metres)").fill("10");
  await validationForm.getByLabel("Minimum common pixels").fill("10");
  await validationForm.getByLabel("Minimum candidate coverage fraction").fill("0.5");
  await validationForm.getByLabel("Minimum pixels per reference class").fill("2");
  await validationForm.getByLabel("Spatial block size (pixels)").fill("2");
  await validationForm.getByLabel("Minimum occupied blocks per reference class").fill("1");
  await validationForm.getByLabel("Reviewed reference GeoTIFF (1 water, 0 non-water, 255 uncertain/NoData)").setInputFiles({
    name: "reference.tif",
    mimeType: "image/tiff",
    buffer: Buffer.from("fixture"),
  });
  await validationForm.getByLabel("Reviewer", { exact: true }).fill("test reviewer");
  await validationForm.getByLabel("Review date", { exact: true }).fill("2026-11-09");
  await validationForm.getByLabel("I confirm the reference labels were independently reviewed").check();
  await validationForm.getByLabel("Reference methodology").fill("Test-only fixture response.");
  await validationForm.getByLabel("Known limitations (one per line)").fill("Browser test fixture only.");
  await workspace.getByRole("button", { name: "Validate against reviewed labels" }).click();

  await expect(workspace.getByRole("region", { name: "Validation report" })).toContainText("validation completed");
  await expect(workspace.getByRole("region", { name: "Validation report" })).toContainText("TP 9 · TN 8 · FP 1 · FN 2");
  await expect(workspace.getByRole("region", { name: "Validation report" })).toContainText("Precision 90.00%");
  await expect(workspace.getByRole("region", { name: "Validation report" })).toContainText("Acquisition separation: 2.58 hours · temporal suitability requires independent review");
  await expect(workspace.getByRole("region", { name: "Validation report" })).toContainText("Browser test fixture only; not a scientific result.");

  const assessment = {
    validation_id: "fixture-windowed",
    status: "thresholds_met_awaiting_evaluation",
    candidate_product_id: "NISAR_A009_FIXTURE",
    reference_dataset_id: "REVIEWED_FIXTURE",
    common_valid_pixel_count: 20,
    report_url: "/api/analysis/validation/fixture-windowed",
    warnings: ["Test fixture only."],
  };
  await page.route("**/api/analysis/validation/windowed-assessments", async (route) => {
    expect(route.request().postData()).toContain('"candidate_processing_version":"fixture-v1"');
    await route.fulfill({ status: 201, json: assessment });
  });
  await page.route("**/api/analysis/validation/windowed-assessments/fixture-windowed/evaluate", async (route) => {
    await route.fulfill({
      json: { ...assessment, status: "validation_completed", precision: 0.9, recall: 0.8, f1_score: 0.85, intersection_over_union: 0.75, overall_agreement: 0.85 },
    });
  });
  await validationForm.getByLabel("Validation mode").selectOption("windowed");
  await validationForm.getByLabel("Candidate processing version").fill("fixture-v1");
  await workspace.getByRole("button", { name: "Assess reviewed labels" }).click();
  await expect(workspace.getByRole("region", { name: "Validation report" })).toContainText("thresholds met awaiting evaluation");
  await workspace.getByRole("button", { name: "Evaluate submitted assessment" }).click();
  await expect(workspace.getByRole("region", { name: "Validation report" })).toContainText("Agreement 85.00%");
  await page.route("**/api/analysis/validation/windowed-assessments/fixture-windowed/reject", async (route) => {
    expect(route.request().postDataJSON()).toEqual({ reason: "Fixture labels unsuitable" });
    await route.fulfill({ json: { ...assessment, status: "evaluation_rejected", evaluation_outcome_detail: "Fixture labels unsuitable" } });
  });
  await workspace.getByRole("button", { name: "Assess reviewed labels" }).click();
  await workspace.getByLabel("Rejection reason").fill("Fixture labels unsuitable");
  await workspace.getByRole("button", { name: "Reject submitted assessment" }).click();
  await expect(workspace.getByRole("region", { name: "Validation report" })).toContainText("evaluation rejected");
  await expect(workspace.getByRole("region", { name: "Validation report" })).toContainText("Fixture labels unsuitable");
});

test("NISAR component sensitivity shows separate candidate scenarios and scientific cautions", async ({ page }) => {
  const productId = "NISAR_COMPONENT_FIXTURE";
  const processingResult = {
    status: "unvalidated_candidate",
    input_crs: "EPSG:32643",
    pixel_size_m: 10,
    valid_pixel_count: 100,
    valid_data_fraction: 1,
    candidate_water_area_m2: 10_000,
    candidate_water_area_lower_m2: 8_000,
    candidate_water_area_upper_m2: 12_000,
    covered_centerline_length_km: 1,
    reference_centerline_length_km: 2,
    reference_centerline_coverage_percent: 50,
    polarization_comparison: [],
    threshold_sensitivity: [],
    connected_component_summary: {
      component_count: 10,
      isolated_pixel_component_count: 3,
      components_up_to_four_pixels: 5,
      pixels_in_components_up_to_four: 8,
      largest_component_pixels: 50,
    },
    mask_url: `/api/analysis/${productId}/mask`,
    measurements_url: null,
    comparison_url: null,
    sensitivity_url: null,
    polygons_url: `/api/analysis/${productId}/polygons`,
    metadata_url: null,
  };
  await page.route("**/api/acquisitions", async (route) => {
    await route.fulfill({
      json: {
        enabled: false,
        polling_interval_seconds: 21600,
        source: "Microsoft Planetary Computer Sentinel-1 RTC",
        source_url: "https://planetarycomputer.microsoft.com/",
        license: "CC-BY-4.0",
        rivers: [{
          ...acquisitionRiver("tungabhadra"),
          nisar_status: "metadata_found",
          nisar_products: [{
            product_id: productId,
            product_level: "GCOV",
            polarization: ["HH", "HV"],
            size_bytes: 10,
            availability: "downloaded_verified",
            download_status: "downloaded",
            hdf5_groups: [],
            processing_status: "processed",
            processing_result: processingResult,
          }],
        }],
      },
    });
  });
  await page.route("**/component-sensitivity?*", async (route) => {
    expect(route.request().method()).toBe("POST");
    expect(route.request().postDataJSON()).toEqual({ minimum_component_sizes: [2, 5, 10] });
    await route.fulfill({
      json: [2, 5, 10].map((minimum, index) => {
        const removed = [89_437, 202_003, 283_567][index];
        const remaining = [3_796_445, 3_683_879, 3_602_315][index];
        return {
          status: "exploratory_candidate_sensitivity",
          river_id: "tungabhadra",
          product_id: productId,
          source_product_id: productId,
          acquisition_start: "2026-11-06T00:25:20Z",
          minimum_component_pixels: minimum,
          connectivity: 8,
          component_count: 160_502,
          component_count_reclassified_nonwater: removed,
          candidate_pixel_count_before: 3_885_882,
          candidate_pixel_count_after: remaining,
          candidate_pixels_reclassified_nonwater: removed,
          candidate_pixels_removed_fraction: removed / 3_885_882,
          valid_pixel_count: 12_910_080,
          nodata_pixel_count_preserved: 550_634_840,
          candidate_area_before_m2: 388_588_200,
          candidate_area_after_m2: remaining * 100,
          crs: "EPSG:32643",
          pixel_size_m: 10,
          processing_completed_at: "2026-11-09T19:04:22Z",
          quality_flags: [
            "This is a user-selected component-size sensitivity scenario, not a validated cleanup.",
            "Removed candidate pixels are not established as noise.",
          ],
          mask_url: `/api/acquisitions/nisar/${productId}/processing/component-sensitivity/${minimum}/mask?river_id=tungabhadra`,
        };
      }),
    });
  });
  await page.reload();

  await expect(page.getByText("Component-size sensitivity scenarios", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Compare 2, 5 and 10 pixel minimums" }).click();
  await expect(page.getByText(/≥2 pixels: 89,437 candidate pixels reclassified/)).toBeVisible();
  await expect(page.getByText(/≥5 pixels: 202,003 candidate pixels reclassified/)).toBeVisible();
  await expect(page.getByText(/≥10 pixels: 283,567 candidate pixels reclassified/)).toBeVisible();
  await expect(page.getByText("Removed candidate pixels are not established as noise.")).toBeVisible();
  await expect(page.getByRole("link", { name: "separate scenario mask" })).toHaveCount(3);
});

test("NISAR connection summary distinguishes cached records from live verification", async ({ page }) => {
  await page.route("**/api/acquisitions", async (route) => {
    await route.fulfill({ json: {
      enabled: false,
      rivers: [acquisitionRiver("kaveri")],
      nisar_connection_status: {
        provider_connectivity: "unknown",
        authentication_status: "unknown",
        authentication_checked_at: null,
        last_successful_search: null,
        cached_product_count: 2,
        recorded_download_count: 1,
        recorded_inspection_count: 1,
        recorded_processing_count: 0,
        latest_recorded_inspection_product_id: "example-gcov",
        latest_recorded_inspection_acquisition: "2026-11-06T00:25:20Z",
        latest_recorded_processing: null,
        recorded_error: true,
      },
    } });
  });
  await page.reload();
  const summary = page.getByRole("region", { name: "NISAR Data Connection Status" });
  await expect(summary.getByText(/Current connectivity: unknown/)).toBeVisible();
  await expect(summary.getByText(/Authentication: unknown/)).toBeVisible();
  await expect(summary.getByText(/Catalog-reported unique products: 2/)).toBeVisible();
  await expect(summary.getByText(/example-gcov/)).toBeVisible();
  await expect(summary.getByText(/A catalog or processing error is recorded/)).toBeVisible();
  await expect(summary.getByText(/cached product counts do not verify checksums/)).toBeVisible();
});

test("NISAR connection summary displays recorded authenticated product access", async ({ page }) => {
  await page.route("**/api/acquisitions", async (route) => {
    await route.fulfill({ json: {
      enabled: false,
      rivers: [acquisitionRiver("tungabhadra")],
      nisar_connection_status: {
        provider_connectivity: "available",
        authentication_status: "data_access_verified",
        authentication_checked_at: "2026-11-10T12:00:00Z",
        last_successful_search: "2026-11-10T11:59:59Z",
        cached_product_count: 1,
        recorded_download_count: 0,
        recorded_inspection_count: 0,
        recorded_processing_count: 0,
        latest_recorded_inspection_product_id: null,
        latest_recorded_inspection_acquisition: null,
        latest_recorded_processing: null,
        recorded_error: false,
      },
    } });
  });
  await page.reload();
  const summary = page.getByRole("region", { name: "NISAR Data Connection Status" });
  await expect(summary.getByText(/available at last successful search/)).toBeVisible();
  await expect(summary.getByText(/product access verified by one-byte request/)).toBeVisible();
  await expect(summary.getByText(/10 Nov 2026/).first()).toBeVisible();
});
