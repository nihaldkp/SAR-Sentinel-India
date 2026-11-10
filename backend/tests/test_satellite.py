from datetime import datetime
from typing import Any

from fastapi.testclient import TestClient

from app.main import app
from app.services import satellite

client = TestClient(app)


class MockASFResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
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
                        "fileID": "NISAR_TEST_SCENE",
                        "platform": "NISAR",
                        "sensor": "L-SAR",
                        "processingLevel": "GCOV",
                        "startTime": "2026-10-01T00:00:00Z",
                        "stopTime": "2026-10-01T00:01:00Z",
                        "mainBandPolarization": "HH+HV",
                        "url": "https://example.test/real-product-link",
                        "bytes": 1234,
                    },
                }
            ],
        }


class MockASFClient:
    def __init__(self, **_: Any) -> None:
        self.request_params: dict[str, Any] | None = None

    async def __aenter__(self) -> "MockASFClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def get(self, url: str, *, params: dict[str, Any], headers: dict[str, str]) -> MockASFResponse:
        assert url == satellite.ASF_SEARCH_URL
        assert headers["User-Agent"].startswith("SAR-Sentinel-India")
        self.request_params = params
        return MockASFResponse()


def test_satellite_search_returns_real_catalog_metadata_contract(monkeypatch: Any) -> None:
    monkeypatch.setattr(satellite.httpx, "AsyncClient", MockASFClient)

    response = client.get(
        "/api/satellite/search",
        params={
            "river_id": "kaveri",
            "mission": "NISAR",
            "start_date": "2026-10-01",
            "end_date": "2026-10-31",
            "product_type": "GCOV",
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["source"] == "ASF DAAC"
    assert result["mission"] == "NISAR"
    assert result["product_type"] == "GCOV"
    assert result["observations"][0]["id"] == "NISAR_TEST_SCENE"
    assert result["observations"][0]["platform"] == "NISAR"
    assert result["observations"][0]["sensor"] == "L-SAR"
    assert result["observations"][0]["polarization"] == "HH+HV"
    assert result["observations"][0]["footprint"]["type"] == "Polygon"
    assert result["observations"][0]["download_url"] == "https://example.test/real-product-link"
    assert "requires product-specific" in result["observations"][0]["analysis_readiness"]
    assert "download links may require earthdata authentication" in result["note"].lower()


def test_satellite_search_rejects_reversed_dates_without_catalog_request() -> None:
    response = client.get(
        "/api/satellite/search",
        params={
            "river_id": "kaveri",
            "mission": "SENTINEL-1",
            "start_date": "2026-10-31",
            "end_date": "2026-10-01",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "start_date must be on or before end_date."


def test_satellite_search_rejects_unsupported_product_level() -> None:
    response = client.get(
        "/api/satellite/search",
        params={
            "river_id": "kaveri",
            "mission": "NISAR",
            "start_date": "2026-10-01",
            "end_date": "2026-10-31",
            "product_type": "MADE_UP",
        },
    )

    assert response.status_code == 422


def test_satellite_search_rejects_unknown_river() -> None:
    response = client.get(
        "/api/satellite/search",
        params={
            "river_id": "not-a-river",
            "mission": "NISAR",
            "start_date": "2026-10-01",
            "end_date": "2026-10-31",
        },
    )

    assert response.status_code == 404


def test_iso_datetime_parser_handles_utc_and_invalid_values() -> None:
    assert satellite._to_datetime("2026-10-01T00:00:00Z") == datetime.fromisoformat("2026-10-01T00:00:00+00:00")
    assert satellite._to_datetime("not a datetime") is None


def test_footprint_filter_requires_intersection_with_projected_river_corridor(
    monkeypatch: Any,
) -> None:
    from rasterio.warp import transform_geom
    from shapely.geometry import LineString, box, mapping

    projected_crs = (
        "+proj=aeqd +lat_0=15.50000000 +lon_0=77.00000000 "
        "+datum=WGS84 +units=m +no_defs +type=crs"
    )
    river = type(
        "RiverFixture",
        (),
        {
            "id": "test-river",
            "centerline": type(
                "CenterlineFixture",
                (),
                {
                    "model_dump": lambda self: mapping(
                        LineString([(77.0, 15.0), (77.0, 16.0)])
                    )
                },
            )(),
        },
    )()
    monkeypatch.setattr(satellite, "RIVER_CATALOG", [river])

    near_footprint = transform_geom(
        projected_crs,
        "EPSG:4326",
        mapping(box(-500, -500, 500, 500)),
    )
    far_footprint = transform_geom(
        projected_crs,
        "EPSG:4326",
        mapping(box(8_000, -500, 9_000, 500)),
    )
    features = [
        {"type": "Feature", "id": "overlap", "geometry": near_footprint},
        {"type": "Feature", "id": "outside", "geometry": far_footprint},
    ]

    matches = satellite._filter_features_by_river_corridor(features, "test-river")

    assert [feature["id"] for feature in matches] == ["overlap"]
