import json
import uuid
from typing import Any
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import acquisitions
from app.services.nisar_gcov import NisarGcovProcessingUnavailable

client = TestClient(app)
TEST_NISAR_PRODUCT_ID = "NISAR_L2_UR_GCOV_TEST_001"


def _write_minimal_nisar_product(path: Path, product_id: str) -> None:
    h5py = pytest.importorskip("h5py")
    with h5py.File(path, "w") as dataset:
        dataset.attrs["mission_name"] = "NISAR"
        dataset.attrs["title"] = "NISAR L2 GCOV Product"
        identification = dataset.create_group("science/LSAR/identification")
        for field, value in {
            "missionId": "NISAR",
            "platformName": "NISAR",
            "instrumentName": "LSAR",
            "productLevel": "L2",
            "productType": "GCOV",
            "granuleId": product_id,
        }.items():
            identification.create_dataset(field, data=np.bytes_(value))
        identification.create_dataset("listOfFrequencies", data=np.asarray([b"A"], dtype="S1"))
        grid = dataset.create_group("science/LSAR/GCOV/grids/frequencyA")
        grid.create_dataset("HHHH", data=np.ones((2, 2), dtype=np.float32)).attrs.update(
            {"units": "1", "grid_mapping": "projection"}
        )
        grid.create_dataset("HVHV", data=np.ones((2, 2), dtype=np.float32)).attrs.update(
            {"units": "1", "grid_mapping": "projection"}
        )
        grid.create_dataset("mask", data=np.ones((2, 2), dtype=np.uint8))
        grid.create_dataset("xCoordinates", data=np.asarray([1.0, 2.0]))
        grid.create_dataset("yCoordinates", data=np.asarray([2.0, 1.0]))
        grid.create_dataset("xCoordinateSpacing", data=np.float64(1.0))
        grid.create_dataset("yCoordinateSpacing", data=np.float64(-1.0))
        grid.create_dataset("listOfPolarizations", data=np.asarray([b"HH", b"HV"], dtype="S2"))
        grid.create_dataset("projection", data=np.uint32(32643)).attrs["epsg_code"] = 32643


def test_automatic_acquisition_is_opt_in(monkeypatch: Any) -> None:
    monkeypatch.delenv("SAR_AUTO_ACQUISITION_ENABLED", raising=False)
    assert acquisitions.automatic_acquisition_enabled() is False
    for enabled in ("1", "true", "YES", "on"):
        monkeypatch.setenv("SAR_AUTO_ACQUISITION_ENABLED", enabled)
        assert acquisitions.automatic_acquisition_enabled() is True
    for disabled in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("SAR_AUTO_ACQUISITION_ENABLED", disabled)
        assert acquisitions.automatic_acquisition_enabled() is False


def test_catalog_recovers_a_completed_result_after_legacy_response_schema_failure(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.transform import from_origin

    product_id = "S1_RECOVERABLE_TEST_PRODUCT"
    analysis_id = str(uuid.uuid4())
    output_dir = tmp_path / "outputs" / "analysis"
    analysis_dir = output_dir / analysis_id
    analysis_dir.mkdir(parents=True)
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "catalog.sqlite3")
    monkeypatch.setattr(acquisitions, "ACQUISITION_ROOT", tmp_path / "acquisitions")
    monkeypatch.setattr(acquisitions, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(acquisitions.analysis, "OUTPUT_DIR", output_dir)

    mask = np.zeros((20, 20), dtype=np.uint8)
    mask[:5, :] = 1
    with rasterio.open(
        analysis_dir / "water-mask.tif",
        "w",
        driver="GTiff",
        height=20,
        width=20,
        count=1,
        dtype="uint8",
        crs="EPSG:32643",
        transform=from_origin(500_000, 1_350_000, 10, 10),
        nodata=255,
    ) as dataset:
        dataset.write(mask, 1)

    metadata = {
        "river_id": "kaveri",
        "mission": "SENTINEL-1",
        "product_type": "GRD-RTC",
        "source_product_id": product_id,
        "acquisition_start": "2026-10-01T00:00:00Z",
        "polarization": "VV",
        "signal_scale": "linear_power",
        "radiometric_calibration_confirmed": True,
        "terrain_correction_confirmed": True,
    }
    (analysis_dir / "result.json").write_text(
        json.dumps(
            {
                "analysis_id": analysis_id,
                "analysis_type": "water_mask",
                "status": "unvalidated_candidate",
                "river_id": "kaveri",
                "source_product_id": product_id,
                "mission": "SENTINEL-1",
                "acquisition_start": metadata["acquisition_start"],
                "polarization": "VV",
                "threshold_method": "otsu",
                "threshold_db": -10,
                "filter_method": "Lee 5x5",
                "valid_pixel_count": 400,
                "water_pixel_count": 100,
                "valid_data_fraction": 1,
                "candidate_water_area_m2": 10_000,
                "operator_supplied_metadata": metadata,
                "output_files": {"mask": "water-mask.tif"},
                "mask_url": f"/api/analysis/{analysis_id}/mask",
                "polygons_url": f"/api/analysis/{analysis_id}/polygons",
                "report_url": f"/api/analysis/{analysis_id}/report",
                "caveats": [],
            }
        ),
        encoding="utf-8",
    )
    item = {
        "id": product_id,
        "properties": {
            "datetime": metadata["acquisition_start"],
            "end_datetime": "2026-10-01T00:00:30Z",
            "platform": "sentinel-1d",
        },
        "geometry": {"type": "Polygon", "coordinates": []},
        "assets": {"vv": {"href": "https://example.test/asset"}},
    }
    result = SimpleNamespace(
        analysis_id=analysis_id,
        candidate_water_area_m2=10_000,
        candidate_water_area_lower_m2=9_000,
        candidate_water_area_upper_m2=11_000,
        threshold_db=-10,
        input_crs="EPSG:32643",
        pixel_area_m2=100,
    )
    with acquisitions._catalog_connection() as connection:
        acquisitions._insert_or_update_product(
            connection,
            "kaveri",
            item,
            25,
            status="failed",
            error="4 validation errors for AcquiredObservation\nvalid_pixel_count missing",
            analysis_result=result,
        )

    catalog = acquisitions.get_catalog_status()
    river = next(river for river in catalog.rivers if river.river_id == "kaveri")
    assert any(item.product_id == product_id for item in river.observations)
    with acquisitions._catalog_connection() as connection:
        row = connection.execute(
            "SELECT status, error FROM acquired_products WHERE river_id=? AND product_id=?",
            ("kaveri", product_id),
        ).fetchone()
    assert row["status"] == "processed"
    assert row["error"] is None


def test_sentinel2_observation_path_rejects_invalid_identifier() -> None:
    with pytest.raises(ValueError, match="Invalid Sentinel-2 observation identifier"):
        acquisitions.nisar_optical_observation_path(
            "tungabhadra",
            "NISAR_TEST_PRODUCT",
            "../outside",
            "mask",
        )


def test_cached_nisar_processing_result_keeps_available_optical_links() -> None:
    product_id = "NISAR_TEST_PRODUCT"
    local = {
        "product_id": product_id,
        "download_status": "downloaded",
        "processing_result": {
            "status": "unvalidated_candidate",
            "optical_reference_url": "/api/optical-reference",
            "optical_candidate_mask_url": "/api/optical-reference/mask",
        },
    }
    cached = {
        "product_id": product_id,
        "download_status": "downloaded",
        "processing_result": {"status": "unvalidated_candidate"},
    }

    merged = acquisitions._merge_nisar_product_records([local], [cached])

    assert merged[0]["processing_result"]["optical_reference_url"] == "/api/optical-reference"
    assert merged[0]["processing_result"]["optical_candidate_mask_url"] == "/api/optical-reference/mask"


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (acquisitions.NisarProcessingBusy("processing busy"), 409),
        (NisarGcovProcessingUnavailable("processor dependencies unavailable"), 503),
    ],
)
def test_nisar_processing_errors_have_explicit_http_status(
    monkeypatch: Any,
    error: Exception,
    expected_status: int,
) -> None:
    def fail_processing(*_: Any) -> None:
        raise error

    monkeypatch.setattr(acquisitions, "process_nisar_product", fail_processing)

    response = client.post(
        "/api/acquisitions/nisar/test-product/process",
        params={"river_id": "tungabhadra"},
    )

    assert response.status_code == expected_status
    assert response.json()["detail"] == str(error)


def test_nisar_component_sensitivity_endpoint_validates_and_returns_provenance(
    monkeypatch: Any,
) -> None:
    def create_sensitivity(river_id: str, product_id: str, sizes: list[int]) -> list[dict[str, Any]]:
        return [
            {
                "status": "exploratory_candidate_sensitivity",
                "river_id": river_id,
                "product_id": product_id,
                "source_product_id": product_id,
                "acquisition_start": "2026-11-06T00:25:20Z",
                "minimum_component_pixels": size,
                "connectivity": 8,
                "component_count": 20,
                "component_count_reclassified_nonwater": 3,
                "candidate_pixel_count_before": 100,
                "candidate_pixel_count_after": 97,
                "candidate_pixels_reclassified_nonwater": 3,
                "candidate_pixels_removed_fraction": 0.03,
                "valid_pixel_count": 200,
                "nodata_pixel_count_preserved": 50,
                "candidate_area_before_m2": 10_000,
                "candidate_area_after_m2": 9_700,
                "crs": "EPSG:32643",
                "pixel_size_m": 10,
                "processing_completed_at": "2026-11-09T00:00:00Z",
                "quality_flags": ["Exploratory sensitivity only."],
                "mask_url": f"/api/acquisitions/nisar/{product_id}/processing/component-sensitivity/{size}/mask?river_id={river_id}",
            }
            for size in sizes
        ]

    monkeypatch.setattr(acquisitions, "create_nisar_component_sensitivity", create_sensitivity)
    endpoint = "/api/acquisitions/nisar/NISAR_TEST/processing/component-sensitivity"
    response = client.post(
        endpoint,
        params={"river_id": "tungabhadra"},
        json={"minimum_component_sizes": [2, 5]},
    )

    assert response.status_code == 200
    assert [item["minimum_component_pixels"] for item in response.json()] == [2, 5]
    assert response.json()[0]["source_product_id"] == "NISAR_TEST"
    assert response.json()[0]["nodata_pixel_count_preserved"] == 50

    duplicate = client.post(
        endpoint,
        params={"river_id": "tungabhadra"},
        json={"minimum_component_sizes": [2, 2]},
    )
    assert duplicate.status_code == 422


def test_segment_clip_reports_intersection_and_outside_cases() -> None:
    clipped = acquisitions._clip_segment((-5, 5), (15, 5), (0, 0, 10, 10))

    assert clipped == ((0.0, 5.0), (10.0, 5.0))
    assert acquisitions._clip_segment((-5, -5), (-1, -1), (0, 0, 10, 10)) is None


def test_coverage_returns_centerline_percentage_and_projected_lines() -> None:
    geometry = {
        "type": "LineString",
        "coordinates": [[-5, 5], [5, 5], [15, 5]],
    }

    percent, lines, points = acquisitions._coverage(
        geometry,
        "EPSG:4326",
        (0, 0, 10, 10),
    )

    assert percent == 50
    assert len(lines) == 1
    assert points[0] == (0.0, 5.0)
    assert points[-1] == (10.0, 5.0)


def test_catalog_status_is_explicitly_empty_before_first_scan(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "catalog.sqlite3")

    response = client.get("/api/acquisitions")

    assert response.status_code == 200
    status = response.json()
    assert status["enabled"] is False
    assert status["source"] == "Microsoft Planetary Computer Sentinel-1 RTC"
    assert [river["river_id"] for river in status["rivers"]] == ["kaveri", "tungabhadra"]
    assert all(river["status"] == "idle" for river in status["rivers"])
    assert all(not river["observations"] for river in status["rivers"])


def test_automatic_catalog_search_uses_exact_centerline_and_recent_window(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"features": []}

    def fake_post(url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: int) -> Response:
        captured.update(json)
        assert url == f"{acquisitions.STAC_URL}/search"
        assert "User-Agent" in headers
        assert timeout == 60
        return Response()

    monkeypatch.setattr(acquisitions.httpx, "post", fake_post)
    river = next(river for river in acquisitions.RIVER_CATALOG if river.id == "kaveri")

    assert acquisitions._item_features(river.id, river.centerline.model_dump()) == []
    assert captured["collections"] == ["sentinel-1-rtc"]
    assert captured["intersects"] == river.centerline.model_dump()
    assert captured["limit"] == acquisitions.SEARCH_LIMIT
    assert captured["sortby"][0]["direction"] == "desc"


def test_nisar_product_access_reports_earthdata_authentication_without_bypass(monkeypatch: Any) -> None:
    class Response:
        status_code = 401
        url = httpx.URL("https://urs.earthdata.nasa.gov/oauth/authorize")

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_: Any) -> None:
            return None

    def fake_stream(method: str, url: str, **kwargs: Any) -> Response:
        assert method == "GET"
        assert url.startswith("https://nisar.asf.earthdatacloud.nasa.gov/")
        assert kwargs["headers"]["Range"] == "bytes=0-0"
        assert kwargs["follow_redirects"] is True
        return Response()

    monkeypatch.setattr(acquisitions.httpx, "stream", fake_stream)

    state, message = acquisitions._check_nisar_download(
        "https://nisar.asf.earthdatacloud.nasa.gov/example.h5"
    )

    assert state == "authentication_required"
    assert "Earthdata Login" in message
    assert "Configure EARTHDATA_TOKEN" in message
    assert "no product bytes were downloaded" in message


def test_missing_earthdata_token_is_reported_without_creating_a_session(
    monkeypatch: Any,
) -> None:
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    monkeypatch.setattr(
        acquisitions,
        "import_module",
        lambda _name: pytest.fail("ASF client should not be imported without a token."),
    )

    session, error = acquisitions._earthdata_session()

    assert session is None
    assert error == "not_configured"
    assert "EARTHDATA_TOKEN is not configured" in acquisitions._earthdata_authentication_message(error)


def test_invalid_earthdata_token_is_reported_without_logging_the_token(
    monkeypatch: Any,
    caplog: Any,
) -> None:
    token = "unit-test-earthdata-secret"

    class ASFAuthenticationError(Exception):
        pass

    class Session:
        def auth_with_token(self, value: str) -> "Session":
            raise ASFAuthenticationError(f"Invalid token: {value}")

    monkeypatch.setenv("EARTHDATA_TOKEN", token)
    monkeypatch.setattr(
        acquisitions,
        "import_module",
        lambda _name: SimpleNamespace(ASFSession=Session),
    )

    session, error = acquisitions._earthdata_session()

    assert session is None
    assert error == "rejected"
    assert "invalid or expired" in acquisitions._earthdata_authentication_message(error)
    assert token not in caplog.text


def test_earthdata_authentication_service_failure_is_not_reported_as_success(
    monkeypatch: Any,
    caplog: Any,
) -> None:
    token = "unit-test-earthdata-secret"

    class Session:
        def auth_with_token(self, value: str) -> "Session":
            raise ConnectionError(f"failed while using {value}")

    monkeypatch.setenv("EARTHDATA_TOKEN", token)
    monkeypatch.setattr(
        acquisitions,
        "import_module",
        lambda _name: SimpleNamespace(ASFSession=Session),
    )

    session, error = acquisitions._earthdata_session()

    assert session is None
    assert error == "error"
    assert "network request failed" in acquisitions._earthdata_authentication_message(error)
    assert token not in caplog.text


def test_authenticated_nisar_range_probe_verifies_access_without_reading_product(
    monkeypatch: Any,
) -> None:
    class Response:
        status_code = 206
        url = "https://nisar.asf.earthdatacloud.nasa.gov/example.h5"

        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    response = Response()

    class Session:
        def get(self, url: str, **kwargs: Any) -> Response:
            assert url == response.url
            assert kwargs["headers"]["Range"] == "bytes=0-0"
            assert kwargs["stream"] is True
            assert kwargs["allow_redirects"] is True
            assert kwargs["timeout"] == 30
            assert "Authorization" not in kwargs["headers"]
            return response

    status, message = acquisitions._check_nisar_download(response.url, session=Session())

    assert status == "authenticated_access_verified"
    assert "one-byte range request" in message
    assert "no full product was downloaded" in message
    assert response.closed is True


def test_authenticated_nisar_range_probe_rejects_denied_access() -> None:
    class Response:
        status_code = 403
        url = "https://nisar.asf.earthdatacloud.nasa.gov/example.h5"

        def close(self) -> None:
            return None

    class Session:
        def get(self, _url: str, **_kwargs: Any) -> Response:
            return Response()

    status, message = acquisitions._check_nisar_download(
        "https://nisar.asf.earthdatacloud.nasa.gov/example.h5",
        session=Session(),
    )

    assert status == "authentication_failed"
    assert "account authorization" in message


def test_nisar_metadata_only_reports_authenticated_access_after_range_probe(
    monkeypatch: Any,
) -> None:
    feature = {
        "type": "Feature",
        "id": "NISAR_TEST_PRODUCT",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [75.93, 12.43],
                [75.95, 12.43],
                [75.95, 12.45],
                [75.93, 12.45],
                [75.93, 12.43],
            ]],
        },
        "properties": {
            "fileID": "NISAR_TEST_PRODUCT",
            "url": "https://nisar.asf.earthdatacloud.nasa.gov/test.h5",
            "processingLevel": "GCOV",
        },
    }
    session = object()
    monkeypatch.setattr(acquisitions, "_search_nisar", lambda _river_id, session=None: [feature])
    monkeypatch.setattr(
        acquisitions,
        "_check_nisar_download",
        lambda _url, session=None: ("authenticated_access_verified", "range verified")
        if session is not None
        else pytest.fail("Authenticated access requires the authenticated session."),
    )

    result = acquisitions._nisar_metadata("kaveri", session=session)

    assert result["status"] == "metadata_found"
    assert result["authentication_status"] == "data_access_verified"
    assert result["last_successful_search"] is not None
    assert result["products"][0]["availability"] == "authenticated_access_verified"


def test_catalog_persists_authenticated_search_evidence(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "catalog.sqlite3")
    monkeypatch.setattr(acquisitions, "ACQUISITION_ROOT", tmp_path / "acquisitions")
    checked_at = "2026-11-10T12:00:00Z"
    searched_at = "2026-11-10T11:59:59Z"
    nisar = {
        "status": "metadata_found",
        "product_id": "NISAR_TEST_PRODUCT",
        "acquisition_start": None,
        "products": [],
        "message": "Authenticated access verified.",
        "authentication_status": "data_access_verified",
        "authentication_checked_at": checked_at,
        "last_successful_search": searched_at,
    }

    with acquisitions._catalog_connection() as connection:
        acquisitions._write_scan(
            connection,
            "tungabhadra",
            "processed",
            nisar,
            0,
            None,
        )

    status = acquisitions.get_catalog_status().model_dump(mode="json")
    river = next(item for item in status["rivers"] if item["river_id"] == "tungabhadra")
    connection_status = status["nisar_connection_status"]

    assert river["earthdata_authentication_status"] == "data_access_verified"
    assert river["earthdata_authentication_checked_at"] == checked_at
    assert river["last_successful_nisar_search"] == searched_at
    assert connection_status["authentication_status"] == "data_access_verified"
    assert connection_status["last_successful_search"] == searched_at


def test_authenticated_nisar_search_uses_asf_search_session(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    product = {
        "type": "Feature",
        "id": "NISAR_TEST",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [75.93, 12.43],
                [75.95, 12.43],
                [75.95, 12.45],
                [75.93, 12.45],
                [75.93, 12.43],
            ]],
        },
        "properties": {"fileID": "NISAR_TEST"},
    }

    class Options:
        def __init__(self, *, session: object) -> None:
            captured["session"] = session

    class Results(list):
        def raise_if_incomplete(self) -> None:
            captured["complete"] = True

    def geo_search(**kwargs: Any) -> Results:
        captured.update(kwargs)
        return Results([SimpleNamespace(geojson=lambda: product)])

    fake_asf = SimpleNamespace(ASFSearchOptions=Options, geo_search=geo_search)
    monkeypatch.setattr(acquisitions, "import_module", lambda name: fake_asf)
    session = object()

    results = acquisitions._search_nisar("kaveri", session=session)

    assert results == [product]
    assert captured["session"] is session
    assert captured["dataset"] == "NISAR"
    assert captured["processingLevel"] == "GCOV"
    assert captured["maxResults"] == acquisitions.NISAR_SEARCH_LIMIT * 5
    assert captured["complete"] is True


def test_earthdata_token_is_passed_only_to_asf_authentication(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    token = "unit-test-token-never-logged"

    class Session:
        def auth_with_token(self, value: str) -> "Session":
            captured["token"] = value
            return self

    fake_asf = SimpleNamespace(ASFSession=Session)
    monkeypatch.setenv("EARTHDATA_TOKEN", token)
    monkeypatch.setattr(acquisitions, "import_module", lambda name: fake_asf)

    session, error = acquisitions._earthdata_session()

    assert isinstance(session, Session)
    assert error is None
    assert captured["token"] == token


def test_nisar_metadata_preserves_product_details_without_authentication(
    monkeypatch: Any,
) -> None:
    feature = {
        "type": "Feature",
        "id": "NISAR_TEST_PRODUCT",
        "properties": {
            "fileID": "NISAR_TEST_PRODUCT",
            "url": "https://nisar.asf.earthdatacloud.nasa.gov/test.h5",
            "startTime": "2026-11-06T00:24:47Z",
            "stopTime": "2026-11-06T00:25:21Z",
            "processingLevel": "GCOV",
            "bytes": {"test.h5": {"bytes": 1024, "format": "HDF5"}},
        },
    }

    monkeypatch.setattr(acquisitions, "_search_nisar", lambda river_id, session=None: [feature])
    monkeypatch.setattr(
        acquisitions,
        "_check_nisar_download",
        lambda url: ("authentication_required", "Earthdata Login required."),
    )

    metadata = acquisitions._nisar_metadata("kaveri")

    assert metadata["status"] == "authentication_required"
    assert metadata["products"][0]["product_id"] == "NISAR_TEST_PRODUCT"
    assert metadata["products"][0]["product_level"] == "GCOV"
    assert metadata["products"][0]["size_bytes"] == 1024
    assert metadata["products"][0]["polarization"] is None


def test_authenticated_product_lookup_keeps_signed_url_transient(
    monkeypatch: Any,
) -> None:
    product_id = TEST_NISAR_PRODUCT_ID
    raw_url = "https://nisar.asf.earthdatacloud.nasa.gov/test.h5?X-Amz-Signature=private"
    feature = {
        "type": "Feature",
        "id": product_id,
        "properties": {
            "fileID": product_id,
            "url": raw_url,
            "processingLevel": "GCOV",
            "bytes": {"test.h5": {"bytes": 1024}},
            "sha256sum": "a" * 64,
        },
    }

    class Result:
        def geojson(self) -> dict[str, Any]:
            return feature

    class ASF:
        @staticmethod
        def ASFSearchOptions(*, session: object) -> object:
            assert session is marker
            return object()

        @staticmethod
        def granule_search(ids: list[str], *, opts: object) -> list[Result]:
            assert ids == [product_id]
            assert opts is not None
            return [Result()]

    marker = object()
    monkeypatch.setattr(acquisitions, "import_module", lambda _name: ASF)

    product = acquisitions._search_nisar_product_by_id(product_id, marker)

    assert product["_download_url"] == raw_url
    assert product["source_url"] == "https://nisar.asf.earthdatacloud.nasa.gov/test.h5"
    assert product["provider_checksum_algorithm"] == "sha256"
    assert product["provider_checksum"] == "a" * 64


def test_catalog_serializes_nisar_products_with_download_state(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "catalog.sqlite3")
    product = {
        "product_id": "NISAR_TEST_PRODUCT",
        "acquisition_start": "2026-11-06T00:24:47+00:00",
        "acquisition_end": "2026-11-06T00:25:21+00:00",
        "product_level": "GCOV",
        "polarization": ["HH", "HV"],
        "size_bytes": 1024,
        "availability": "authenticated_catalog",
        "download_status": "not_attempted",
        "source_url": "https://nisar.asf.earthdatacloud.nasa.gov/test.h5?sig=private",
        "_download_url": "https://nisar.asf.earthdatacloud.nasa.gov/test.h5?sig=private",
        "local_path": None,
        "hdf5_groups": [],
        "message": None,
    }

    with acquisitions._catalog_connection() as connection:
        acquisitions._write_scan(
            connection,
            "kaveri",
            "searching",
            {
                "status": "metadata_found",
                "product_id": product["product_id"],
                "acquisition_start": product["acquisition_start"],
                "message": "Authenticated catalog search succeeded.",
            },
            0,
            None,
            [product],
        )
    river = next(
        river for river in acquisitions.get_catalog_status().rivers if river.river_id == "kaveri"
    )

    assert river.nisar_products[0].product_id == "NISAR_TEST_PRODUCT"
    assert river.nisar_products[0].polarization == ["HH", "HV"]
    assert river.nisar_products[0].download_status == "not_attempted"
    assert river.nisar_products[0].source_url == "https://nisar.asf.earthdatacloud.nasa.gov/test.h5"


class _DownloadResponse:
    def __init__(
        self,
        status_code: int,
        headers: dict[str, str],
        chunks: list[bytes],
        fail_after_first: bool = False,
        url: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers
        self.chunks = chunks
        self.fail_after_first = fail_after_first
        self.url = url
        self.closed = False

    def iter_content(self, chunk_size: int):
        del chunk_size
        for index, chunk in enumerate(self.chunks):
            yield chunk
            if self.fail_after_first and index == 0:
                raise TimeoutError("simulated interrupted transfer")

    def close(self) -> None:
        self.closed = True


def _download_product(product_id: str = TEST_NISAR_PRODUCT_ID) -> dict[str, Any]:
    return {
        "product_id": product_id,
        "product_level": "GCOV",
        "source_url": "https://nisar.asf.earthdatacloud.nasa.gov/product.h5",
        "_download_url": "https://nisar.asf.earthdatacloud.nasa.gov/product.h5?X-Amz-Signature=private",
        "source_url_reference": "https://nisar.asf.earthdatacloud.nasa.gov/product.h5",
        "size_bytes": None,
        "download_status": "not_attempted",
        "availability": "authenticated_catalog",
        "hdf5_groups": [],
    }


def test_nisar_download_verifies_full_file_checksum_and_metadata(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    pytest.importorskip("h5py")
    monkeypatch.setattr(acquisitions, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(acquisitions, "ACQUISITION_ROOT", tmp_path / "data" / "acquisitions")
    monkeypatch.setattr(acquisitions, "NISAR_DOWNLOAD_RESERVE_BYTES", 0)
    source = tmp_path / f"{TEST_NISAR_PRODUCT_ID}.h5"
    _write_minimal_nisar_product(source, TEST_NISAR_PRODUCT_ID)
    payload = source.read_bytes()
    digest = acquisitions.calculate_checksums(source)["sha256"]
    response = _DownloadResponse(
        200,
        {"Content-Length": str(len(payload))},
        [payload],
    )

    class Session:
        def get(self, url: str, **kwargs: Any) -> _DownloadResponse:
            assert "X-Amz-Signature=private" in url
            assert kwargs["stream"] is True
            return response

    product = _download_product()
    product["size_bytes"] = len(payload)
    product["provider_checksum_algorithm"] = "sha256"
    product["provider_checksum"] = digest

    result = acquisitions._download_nisar_product("kaveri", product, Session())

    final_path = tmp_path / result["local_path"]
    manifest_path = final_path.parent / "download-verification.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert response.closed
    assert final_path.read_bytes() == payload
    assert result["download_status"] == "downloaded"
    assert result["sha256"] == digest
    assert result["integrity_status"] == "provider_checksum_verified"
    assert result["structure_verification_status"] == "verified"
    assert result["provider_authenticity_status"] == "provider_checksum_verified"
    assert result["scientific_validation_status"] == "not_performed"
    assert result["download_timestamp"]
    assert result["acquisition_identifier"] == TEST_NISAR_PRODUCT_ID
    assert result["size_bytes"] == len(payload)
    assert result["source_url_reference"] == "https://nisar.asf.earthdatacloud.nasa.gov/product.h5"
    assert manifest["acquisition_identifier"] == TEST_NISAR_PRODUCT_ID
    assert manifest["product_type"] == "GCOV"
    assert manifest["file_size_bytes"] == len(payload)
    assert "X-Amz-Signature" not in manifest["source_url_reference"]
    assert "private" not in manifest["source_url_reference"]

    class NoNetwork:
        def get(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("A verified product must be reused without another request.")

    reused = _download_product()
    reused.update(
        {
            "size_bytes": len(payload),
            "provider_checksum_algorithm": "sha256",
            "provider_checksum": digest,
        }
    )
    assert acquisitions._download_nisar_product("kaveri", reused, NoNetwork())["sha256"] == digest


def test_catalog_product_record_drops_signed_url_and_query_parameters() -> None:
    record = acquisitions._catalog_product_records(
        [
            {
                "product_id": TEST_NISAR_PRODUCT_ID,
                "source_url": "https://nisar.asf.earthdatacloud.nasa.gov/file.h5?sig=private",
                "_download_url": "https://nisar.asf.earthdatacloud.nasa.gov/file.h5?sig=private",
            }
        ]
    )[0]

    assert "_download_url" not in record
    assert record["source_url"] == "https://nisar.asf.earthdatacloud.nasa.gov/file.h5"
    assert "private" not in json.dumps(record)


def test_nisar_download_recovers_verified_staging_directory_after_finalize_interruption(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    pytest.importorskip("h5py")
    monkeypatch.setattr(acquisitions, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(acquisitions, "ACQUISITION_ROOT", tmp_path / "data" / "acquisitions")
    monkeypatch.setattr(acquisitions, "NISAR_DOWNLOAD_RESERVE_BYTES", 0)
    source = tmp_path / f"{TEST_NISAR_PRODUCT_ID}.h5"
    _write_minimal_nisar_product(source, TEST_NISAR_PRODUCT_ID)
    payload = source.read_bytes()
    product = _download_product()
    product["size_bytes"] = len(payload)
    response = _DownloadResponse(
        200,
        {"Content-Length": str(len(payload))},
        [payload],
    )
    river_directory = tmp_path / "data" / "acquisitions" / "kaveri"
    staging_directory = river_directory / f".nisar-download-{TEST_NISAR_PRODUCT_ID}"
    product_directory = river_directory / TEST_NISAR_PRODUCT_ID
    real_replace = acquisitions.os.replace

    def interrupt_final_directory_rename(source_path: Any, destination_path: Any) -> None:
        if Path(source_path) == staging_directory and Path(destination_path) == product_directory:
            raise PermissionError("simulated process interruption before atomic finalization")
        real_replace(source_path, destination_path)

    with monkeypatch.context() as patch:
        patch.setattr(acquisitions.os, "replace", interrupt_final_directory_rename)
        with pytest.raises(PermissionError, match="simulated process interruption"):
            acquisitions._download_nisar_product(
                "kaveri",
                product,
                SimpleNamespace(get=lambda *_args, **_kwargs: response),
            )

    class NoNetwork:
        def get(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("A complete staged product should be finalized without redownloading.")

    recovered = acquisitions._download_nisar_product("kaveri", product, NoNetwork())
    assert recovered["download_status"] == "downloaded"
    assert (tmp_path / recovered["local_path"]).read_bytes() == payload


def test_provider_checksum_metadata_is_normalized_and_rejects_malformed_values() -> None:
    assert acquisitions._provider_checksum({"md5sum": "A" * 32}) == (
        "md5",
        "a" * 32,
    )
    with pytest.raises(ValueError, match="malformed"):
        acquisitions._provider_checksum({"sha256sum": "not-a-checksum"})


def test_nisar_download_resumes_interruption_and_records_fingerprint_without_provider_checksum(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    pytest.importorskip("h5py")
    monkeypatch.setattr(acquisitions, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(acquisitions, "ACQUISITION_ROOT", tmp_path / "data" / "acquisitions")
    monkeypatch.setattr(acquisitions, "NISAR_DOWNLOAD_RESERVE_BYTES", 0)
    source = tmp_path / f"{TEST_NISAR_PRODUCT_ID}.h5"
    _write_minimal_nisar_product(source, TEST_NISAR_PRODUCT_ID)
    payload = source.read_bytes()
    split = len(payload) // 2
    first = _DownloadResponse(
        200,
        {"Content-Length": str(len(payload))},
        [payload[:split]],
        fail_after_first=True,
    )
    second = _DownloadResponse(
        206,
        {"Content-Range": f"bytes {split}-{len(payload) - 1}/{len(payload)}"},
        [payload[split:]],
    )

    class Session:
        def __init__(self) -> None:
            self.responses = [first, second]
            self.headers: list[dict[str, str]] = []

        def get(self, _url: str, **kwargs: Any) -> _DownloadResponse:
            self.headers.append(kwargs["headers"])
            return self.responses.pop(0)

    session = Session()
    product = _download_product()
    product["size_bytes"] = len(payload)

    with pytest.raises(RuntimeError, match="interrupted"):
        acquisitions._download_nisar_product("kaveri", product, session)
    pending = (
        tmp_path / "data" / "acquisitions" / "kaveri"
        / f".nisar-download-{TEST_NISAR_PRODUCT_ID}"
        / "product.h5.part"
    )
    assert pending.stat().st_size == split

    result = acquisitions._download_nisar_product("kaveri", product, session)
    final_path = tmp_path / result["local_path"]
    assert session.headers[1]["Range"] == f"bytes={split}-"
    assert final_path.read_bytes() == payload
    assert result["integrity_status"] == "sha256_fingerprint_only"
    assert result["provider_authenticity_status"] == "not_verified"


@pytest.mark.parametrize(
    ("payload", "provider_checksum", "message"),
    [
        (b"not an HDF5 product", None, "HDF5"),
        (None, "0" * 64, "provider checksum"),
    ],
)
def test_invalid_or_corrupted_nisar_download_is_not_finalized(
    monkeypatch: Any,
    tmp_path: Path,
    payload: bytes | None,
    provider_checksum: str | None,
    message: str,
) -> None:
    pytest.importorskip("h5py")
    monkeypatch.setattr(acquisitions, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(acquisitions, "ACQUISITION_ROOT", tmp_path / "data" / "acquisitions")
    monkeypatch.setattr(acquisitions, "NISAR_DOWNLOAD_RESERVE_BYTES", 0)
    if payload is None:
        source = tmp_path / f"{TEST_NISAR_PRODUCT_ID}.h5"
        _write_minimal_nisar_product(source, TEST_NISAR_PRODUCT_ID)
        payload = source.read_bytes()
    response = _DownloadResponse(200, {"Content-Length": str(len(payload))}, [payload])
    product = _download_product()
    product["size_bytes"] = len(payload)
    if provider_checksum is not None:
        product["provider_checksum_algorithm"] = "sha256"
        product["provider_checksum"] = provider_checksum

    with pytest.raises(RuntimeError, match=message):
        acquisitions._download_nisar_product(
            "kaveri",
            product,
            SimpleNamespace(get=lambda *_args, **_kwargs: response),
        )

    product_directory = (
        tmp_path / "data" / "acquisitions" / "kaveri" / TEST_NISAR_PRODUCT_ID
    )
    assert not product_directory.exists()
    assert not list(product_directory.parent.glob(".nisar-download-*/" + "*.h5.part"))


def test_nisar_download_rejects_invalid_hdf5_product_identity(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    pytest.importorskip("h5py")
    monkeypatch.setattr(acquisitions, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(acquisitions, "ACQUISITION_ROOT", tmp_path / "data" / "acquisitions")
    monkeypatch.setattr(acquisitions, "NISAR_DOWNLOAD_RESERVE_BYTES", 0)
    source = tmp_path / "invalid.h5"
    _write_minimal_nisar_product(source, "NISAR_L2_UR_GCOV_DIFFERENT_001")
    payload = source.read_bytes()
    response = _DownloadResponse(200, {"Content-Length": str(len(payload))}, [payload])

    with pytest.raises(RuntimeError, match="granuleId"):
        acquisitions._download_nisar_product(
            "kaveri",
            _download_product(),
            SimpleNamespace(get=lambda *_args, **_kwargs: response),
        )

    assert not (
        tmp_path / "data" / "acquisitions" / "kaveri" / TEST_NISAR_PRODUCT_ID
    ).exists()


def test_nisar_download_credential_failure_does_not_expose_signed_url(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(acquisitions, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(acquisitions, "ACQUISITION_ROOT", tmp_path / "data" / "acquisitions")
    monkeypatch.setattr(acquisitions, "NISAR_DOWNLOAD_RESERVE_BYTES", 0)
    response = _DownloadResponse(401, {}, [])

    with pytest.raises(PermissionError) as error:
        acquisitions._download_nisar_product(
            "kaveri",
            _download_product(),
            SimpleNamespace(get=lambda *_args, **_kwargs: response),
        )
    assert "private" not in str(error.value)
    assert "X-Amz-Signature" not in str(error.value)


@pytest.mark.parametrize(
    ("status_code", "headers", "response_url", "expected_error"),
    [
        (200, {"Content-Type": "text/html"}, None, "login page"),
        (200, {}, "https://urs.earthdata.nasa.gov/login", "login page"),
        (500, {}, None, "HTTP 500"),
    ],
)
def test_nisar_download_handles_expired_auth_and_http_errors_safely(
    monkeypatch: Any,
    tmp_path: Path,
    status_code: int,
    headers: dict[str, str],
    response_url: str | None,
    expected_error: str,
) -> None:
    monkeypatch.setattr(acquisitions, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(acquisitions, "ACQUISITION_ROOT", tmp_path / "data" / "acquisitions")
    monkeypatch.setattr(acquisitions, "NISAR_DOWNLOAD_RESERVE_BYTES", 0)
    response = _DownloadResponse(status_code, headers, [], url=response_url)

    with pytest.raises((PermissionError, RuntimeError), match=expected_error) as error:
        acquisitions._download_nisar_product(
            "kaveri",
            _download_product(),
            SimpleNamespace(get=lambda *_args, **_kwargs: response),
        )
    assert "private" not in str(error.value)
    assert "X-Amz-Signature" not in str(error.value)


def test_nisar_size_bytes_uses_hdf5_asset_size() -> None:
    properties = {
        "bytes": {
            "product.h5": {"bytes": 100},
            "product.png": {"bytes": 25},
        }
    }

    assert acquisitions._nisar_size_bytes(
        properties,
        "https://nisar.asf.earthdatacloud.nasa.gov/product.h5",
    ) == 100


def test_refresh_preserves_and_recovers_local_nisar_products(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    h5py = pytest.importorskip("h5py")
    monkeypatch.setattr(acquisitions, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(acquisitions, "ACQUISITION_ROOT", tmp_path / "data" / "acquisitions")
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "catalog.sqlite3")

    product_id = (
        "NISAR_L2_UR_GCOV_035_012_A_009_4005_DHDH_A_"
        "20261106T002520_20261106T002555_P05036_F_F_J_001"
    )
    product_directory = acquisitions.ACQUISITION_ROOT / "tungabhadra" / product_id
    product_directory.mkdir(parents=True)
    product_path = product_directory / f"{product_id}.h5"
    _write_minimal_nisar_product(product_path, product_id)
    processing_directory = product_directory / "nisar-processing"
    processing_directory.mkdir()
    (processing_directory / "processing-metadata.json").write_text(
        json.dumps(
            {
                "status": "unvalidated_candidate",
                "product_id": product_id,
                "acquisition_start": "2026-11-06T00:25:20+00:00",
                "acquisition_end": "2026-11-06T00:25:55+00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        acquisitions,
        "_nisar_metadata",
        lambda *_args, **_kwargs: {
            "status": "no_data",
            "product_id": None,
            "products": [],
            "message": "No newly discovered NISAR products.",
        },
    )
    monkeypatch.setattr(acquisitions, "_item_features", lambda *_args: [])
    river = SimpleNamespace(
        id="tungabhadra",
        centerline=SimpleNamespace(model_dump=lambda: {"type": "LineString", "coordinates": []}),
    )

    with acquisitions._catalog_connection() as connection:
        acquisitions._refresh_river(
            connection,
            river,
            "test-sas-token",
            None,
            None,
            download_nisar=False,
        )
        row = connection.execute(
            "SELECT nisar_products_json FROM river_scans WHERE river_id='tungabhadra'"
        ).fetchone()

    products = json.loads(row["nisar_products_json"])
    assert len(products) == 1
    assert products[0]["product_id"] == product_id
    assert products[0]["download_status"] == "downloaded"
    assert products[0]["availability"] == "downloaded_verified"
    assert products[0]["polarization"] == ["HH", "HV"]
    assert products[0]["processing_status"] == "processed"
    assert products[0]["processing_result"]["status"] == "unvalidated_candidate"
    assert (tmp_path / products[0]["local_path"]).is_file()


def test_catalog_status_recovers_hdf5_product_missing_from_sqlite(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    h5py = pytest.importorskip("h5py")
    monkeypatch.setattr(acquisitions, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(acquisitions, "ACQUISITION_ROOT", tmp_path / "data" / "acquisitions")
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "catalog.sqlite3")

    product_id = (
        "NISAR_L2_UR_GCOV_035_012_A_009_4005_DHDH_A_"
        "20261106T002520_20261106T002555_P05036_F_F_J_001"
    )
    product_directory = acquisitions.ACQUISITION_ROOT / "tungabhadra" / product_id
    product_directory.mkdir(parents=True)
    _write_minimal_nisar_product(product_directory / f"{product_id}.h5", product_id)
    with acquisitions._catalog_connection() as connection:
        acquisitions._write_scan(
            connection,
            "tungabhadra",
            "no_data",
            {"status": "no_data", "products": []},
            0,
            "No new products found.",
            [],
        )

    status = acquisitions.get_catalog_status()
    tungabhadra = next(item for item in status.rivers if item.river_id == "tungabhadra")

    assert tungabhadra.nisar_status == "metadata_found"
    assert tungabhadra.nisar_product_id == product_id
    assert "Recovered 1 locally stored NISAR GCOV product(s)" in tungabhadra.nisar_message
    assert len(tungabhadra.nisar_products) == 1
    assert tungabhadra.nisar_products[0].product_id == product_id
    assert tungabhadra.nisar_products[0].download_status == "downloaded"
    assert tungabhadra.nisar_products[0].polarization == ["HH", "HV"]
    assert tungabhadra.nisar_products[0].processing_status == "not_attempted"


def test_refresh_reports_corridor_without_valid_pixels_as_no_data(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "catalog.sqlite3")
    monkeypatch.setattr(acquisitions, "ACQUISITION_ROOT", tmp_path / "data" / "acquisitions")
    item = {
        "id": "SENTINEL_NO_VALID_PIXELS",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [75.9, 12.4],
                [76.0, 12.4],
                [76.0, 12.5],
                [75.9, 12.5],
                [75.9, 12.4],
            ]],
        },
        "properties": {
            "datetime": "2026-11-07T00:48:19Z",
            "end_datetime": "2026-11-07T00:48:35Z",
            "platform": "sentinel-1d",
            "sat:orbit_state": "ascending",
            "sat:relative_orbit": 12,
            "proj:epsg": 32643,
            "proj:bbox": [500000, 1350000, 510000, 1360000],
        },
        "assets": {"vv": {"href": "https://example.invalid/vv.tif"}},
    }
    monkeypatch.setattr(
        acquisitions,
        "_nisar_metadata",
        lambda *_args, **_kwargs: {
            "status": "no_data",
            "product_id": None,
            "products": [],
            "message": "No new NISAR products.",
        },
    )
    monkeypatch.setattr(acquisitions, "_item_features", lambda *_args: [item])
    monkeypatch.setattr(acquisitions, "_coverage", lambda *_args: (22.0, [], []))

    def no_valid_data(*_args: Any, **_kwargs: Any) -> None:
        raise acquisitions.analysis.InsufficientValidDataError(
            "The raster has fewer than 32 valid positive backscatter pixels."
        )

    monkeypatch.setattr(acquisitions, "_process_candidate", no_valid_data)
    river = SimpleNamespace(
        id="kaveri",
        centerline=SimpleNamespace(
            model_dump=lambda: {"type": "LineString", "coordinates": [[75.9, 12.4], [76.0, 12.5]]}
        ),
    )

    with acquisitions._catalog_connection() as connection:
        acquisitions._refresh_river(
            connection,
            river,
            "unused-token",
            None,
            None,
            download_nisar=False,
        )
        scan = connection.execute(
            "SELECT status, message FROM river_scans WHERE river_id='kaveri'"
        ).fetchone()
        product = connection.execute(
            """
            SELECT status, error, analysis_id, candidate_water_area_m2
            FROM acquired_products
            WHERE river_id='kaveri' AND product_id=?
            """,
            (item["id"],),
        ).fetchone()

    assert scan["status"] == "no_data"
    assert "no valid positive backscatter pixels" in scan["message"]
    assert product["status"] == "no_data"
    assert "fewer than 32" in product["error"]
    assert product["analysis_id"] is None
    assert product["candidate_water_area_m2"] is None

    response = client.get("/api/acquisitions")
    assert response.status_code == 200
    river_status = next(
        river for river in response.json()["rivers"] if river["river_id"] == "kaveri"
    )
    assert river_status["status"] == "no_data"
    assert "no valid positive backscatter pixels" in river_status["message"]
    assert river_status["issues"] == []


def test_nisar_processing_api_persists_result_and_serves_outputs(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    from app.services import nisar_gcov

    product_id = "NISAR_TEST_PRODUCT"
    monkeypatch.setattr(acquisitions, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(acquisitions, "ACQUISITION_ROOT", tmp_path / "data" / "acquisitions")
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "catalog.sqlite3")
    product_directory = acquisitions.ACQUISITION_ROOT / "tungabhadra" / product_id
    product_directory.mkdir(parents=True)
    source_path = product_directory / "test.h5"
    source_path.write_bytes(b"test product")
    product = {
        "product_id": product_id,
        "product_level": "GCOV",
        "acquisition_start": "2026-11-06T00:25:54+00:00",
        "acquisition_end": "2026-11-06T00:26:28+00:00",
        "polarization": ["HH", "HV"],
        "size_bytes": 12,
        "availability": "downloaded_verified",
        "download_status": "downloaded",
        "local_path": str(source_path.relative_to(tmp_path)),
        "hdf5_groups": ["science"],
    }
    with acquisitions._catalog_connection() as connection:
        acquisitions._write_scan(
            connection,
            "tungabhadra",
            "idle",
            {"status": "metadata_found", "products": [product]},
            0,
            None,
            [product],
        )

    processing_calls = []

    def fake_process(path: Path, passed_product_id: str, river_id: str, output_dir: Path) -> dict[str, Any]:
        assert path == source_path
        assert passed_product_id == product_id
        assert river_id == "tungabhadra"
        output_dir.mkdir(parents=True)
        (output_dir / "candidate-water-mask.tif").write_bytes(b"mask")
        (output_dir / "gcov-measurements.tif").write_bytes(b"measurements")
        (output_dir / "candidate-water.geojson").write_text(
            '{"type":"FeatureCollection","features":[]}',
            encoding="utf-8",
        )
        processing_calls.append(product_id)
        return {
            "river_id": river_id,
            "product_id": product_id,
            "status": "unvalidated_candidate",
            "processor_version": "test",
            "algorithm": "fixture",
            "frequency": "frequencyA",
            "dataset_paths": {"hh": "HHHH", "hv": "HVHV"},
            "polarization": ["HH", "HV"],
            "input_crs": "EPSG:32643",
            "pixel_size_m": 10,
            "reference_centerline_coverage_percent": 30,
            "reference_centerline_length_km": 10,
            "covered_centerline_length_km": 3,
            "corridor_half_width_m": 1500,
            "corridor_pixel_count": 100,
            "valid_pixel_count": 90,
            "valid_data_fraction": 0.9,
            "water_pixel_count": 20,
            "candidate_water_area_m2": 2000,
            "candidate_water_area_lower_m2": 1500,
            "candidate_water_area_upper_m2": 2500,
            "hh_threshold_db": -15,
            "hv_threshold_db": -20,
            "threshold_sensitivity_db": 1,
            "mask_width": 10,
            "mask_height": 10,
            "mask_url": "",
            "polygons_url": "",
            "metadata_url": "",
            "polygon_feature_count": 1,
            "vectorization_truncated": False,
            "processing_completed_at": "2026-11-09T00:00:00+00:00",
            "caveats": ["Unvalidated fixture."],
        }

    def fake_quality_diagnostics(
        result: dict[str, Any],
        product_path: Path,
        river_id: str,
        passed_product_id: str,
    ) -> dict[str, Any]:
        output_dir = product_path.parent / "nisar-processing"
        (output_dir / "polarization-comparison.tif").write_bytes(b"comparison")
        (output_dir / "threshold-sensitivity.tif").write_bytes(b"sensitivity")
        result["comparison_url"] = (
            f"/api/acquisitions/nisar/{passed_product_id}/processing/comparison?river_id={river_id}"
        )
        result["sensitivity_url"] = (
            f"/api/acquisitions/nisar/{passed_product_id}/processing/sensitivity?river_id={river_id}"
        )
        result["connected_component_summary"] = {"component_count": 1}
        return result

    monkeypatch.setattr(nisar_gcov, "process_gcov_product", fake_process)
    monkeypatch.setattr(acquisitions, "_attach_nisar_quality_diagnostics", fake_quality_diagnostics)
    endpoint = f"/api/acquisitions/nisar/{product_id}"
    response = client.post(f"{endpoint}/process", params={"river_id": "tungabhadra"})

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "unvalidated_candidate"
    assert result["acquisition_start"] == "2026-11-06T00:25:54Z"
    assert result["mask_url"].endswith("?river_id=tungabhadra")
    cached_result = acquisitions.process_nisar_product("tungabhadra", product_id)
    assert cached_result["candidate_water_area_m2"] == result["candidate_water_area_m2"]
    assert cached_result["processing_completed_at"] == "2026-11-09T00:00:00+00:00"
    assert processing_calls == [product_id]

    catalog = client.get("/api/acquisitions")
    assert catalog.status_code == 200
    registered = catalog.json()["rivers"][1]["nisar_products"][0]
    assert registered["processing_status"] == "processed"
    assert registered["processing_result"]["candidate_water_area_m2"] == 2000

    metadata = client.get(f"{endpoint}/processing", params={"river_id": "tungabhadra"})
    assert metadata.status_code == 200
    mask = client.get(f"{endpoint}/processing/mask", params={"river_id": "tungabhadra"})
    assert mask.status_code == 200
    assert mask.content == b"mask"
    measurements = client.get(
        f"{endpoint}/processing/measurements",
        params={"river_id": "tungabhadra"},
    )
    assert measurements.status_code == 200
    assert measurements.content == b"measurements"
    polygons = client.get(f"{endpoint}/processing/polygons", params={"river_id": "tungabhadra"})
    assert polygons.status_code == 200
    assert polygons.json()["type"] == "FeatureCollection"
    comparison = client.get(
        f"{endpoint}/processing/comparison",
        params={"river_id": "tungabhadra"},
    )
    assert comparison.status_code == 200
    assert comparison.content == b"comparison"
    sensitivity = client.get(
        f"{endpoint}/processing/sensitivity",
        params={"river_id": "tungabhadra"},
    )
    assert sensitivity.status_code == 200
    assert sensitivity.content == b"sensitivity"


def test_sentinel_processing_response_includes_quality_metrics(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    rasterio = pytest.importorskip("rasterio")
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin

    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "catalog.sqlite3")
    monkeypatch.setattr(acquisitions.analysis, "OUTPUT_DIR", tmp_path / "analysis")
    values = np.ones((20, 20), dtype=np.float32)
    values[8:12, :] = 0.01
    with MemoryFile() as memory_file:
        with memory_file.open(
            driver="GTiff",
            width=20,
            height=20,
            count=1,
            dtype="float32",
            crs="EPSG:32643",
            transform=from_origin(500000, 1350000, 10, 10),
        ) as dataset:
            dataset.write(values, 1)
        raster_bytes = memory_file.read()
    monkeypatch.setattr(acquisitions, "_coverage", lambda *args: (50.0, [], []))

    def write_fixture(
        item: dict[str, Any],
        river_id: str,
        geometry: dict[str, Any],
        output_path: Path,
        token: str,
    ) -> tuple[float, float, str]:
        output_path.write_bytes(raster_bytes)
        return 50.0, 10.0, "EPSG:32643"

    monkeypatch.setattr(acquisitions, "_read_clipped_raster", write_fixture)
    item = {
        "id": "SENTINEL_TEST_PRODUCT",
        "geometry": {"type": "Polygon", "coordinates": []},
        "properties": {
            "datetime": "2026-11-07T00:00:00Z",
            "end_datetime": "2026-11-07T00:00:30Z",
            "platform": "sentinel-1d",
            "proj:epsg": 32643,
            "proj:bbox": [500000, 1349800, 500200, 1350000],
        },
        "assets": {"vv": {"href": "https://example.test/rtc.tif"}},
    }

    with acquisitions._catalog_connection() as connection:
        observation = acquisitions._process_candidate(
            connection,
            "kaveri",
            {"type": "LineString", "coordinates": [[76.0, 12.0], [76.1, 12.1]]},
            item,
            "test-token",
        )

    assert observation.valid_pixel_count == 400
    assert 0 < observation.valid_data_fraction <= 1
    assert observation.water_pixel_count > 0
    assert observation.filter_method


def test_acquisition_refresh_endpoint_does_not_run_when_disabled() -> None:
    response = client.post("/api/acquisitions/refresh")

    assert response.status_code == 503
    assert response.json()["detail"] == "Automatic satellite acquisition is disabled."


def test_catalog_persists_unsigned_stac_asset_url_only(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "catalog.sqlite3")
    item = {
        "id": "TEST_FIXTURE_ITEM",
        "geometry": {"type": "Polygon", "coordinates": []},
        "properties": {
            "datetime": "2026-11-07T00:00:00Z",
            "platform": "sentinel-1d",
            "sat:orbit_state": "descending",
            "sat:relative_orbit": 63,
        },
        "assets": {
            "vv": {
                "href": "https://example.test/unsigned.tiff",
            }
        },
    }
    with acquisitions._catalog_connection() as connection:
        acquisitions._insert_or_update_product(
            connection,
            "kaveri",
            item,
            3.2,
            status="acquiring",
        )
        asset_url = connection.execute(
            "SELECT asset_source_url FROM acquired_products WHERE product_id=?",
            ("TEST_FIXTURE_ITEM",),
        ).fetchone()[0]
        assert connection.execute("SELECT COUNT(*) FROM acquired_products").fetchone()[0] == 1
        assert asset_url == "https://example.test/unsigned.tiff"
