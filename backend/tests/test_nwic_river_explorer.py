from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import acquisitions
from app.services import nwic_river_explorer
from app.services.nwic_river_import import import_nwic_kml
from test_nwic_river_import import placemark, write_kml

client = TestClient(app)


def test_empty_catalog_and_query_validation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "catalog.sqlite3")
    response = client.get("/api/river-network/features")
    assert response.status_code == 200 and response.json()["total"] == 0
    assert response.json()["source_status"] == "not_imported"
    assert client.get("/api/river-network/features", params={"limit": 101}).status_code == 422
    assert client.get("/api/river-network/features", params={"west": 76}).status_code == 422
    assert client.get("/api/river-network/features/missing/geometry").status_code == 404


def test_paginated_search_bbox_and_on_demand_geometry(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "catalog.sqlite3")
    path = tmp_path / "source.kml"
    write_kml(path, placemark("1"), placemark("2", "80,20 81,21"))
    import_nwic_kml(path, "fixture", max_features=1)
    assert client.get("/api/river-network/features").json()["import_complete"] is False
    import_nwic_kml(path, "fixture")
    first = client.get("/api/river-network/features", params={"q": "Fixture", "limit": 1}).json()
    second = client.get("/api/river-network/features", params={"q": "Fixture", "limit": 1, "offset": 1}).json()
    assert first["total"] == 2 and second["total"] == 2
    assert first["source_status"] == "available"
    assert first["import_complete"] is True
    assert client.get("/api/river-network/features", params={"q": "missing"}).json()["source_status"] == "available"
    assert [first["features"][0]["source_object_id"], second["features"][0]["source_object_id"]] == ["1", "2"]
    assert "geometry_json" not in first["features"][0]
    assert first["features"][0]["monitoring_status"] == "unknown"
    assert client.get("/api/river-network/features", params={"q": "river-2"}).json()["total"] == 1
    assert client.get("/api/river-network/features", params={"q": "%"}).json()["total"] == 0
    assert client.get("/api/river-network/features", params={"basin": "Fixture basin"}).json()["total"] == 2
    bounds = {"west": 75, "south": 14, "east": 78, "north": 17}
    filtered = client.get("/api/river-network/features", params=bounds).json()
    assert filtered["total"] == 1 and filtered["features"][0]["source_object_id"] == "1"
    geometry = client.get("/api/river-network/features/1/geometry").json()
    assert geometry["type"] == "MultiLineString" and geometry["coordinates"][0][0] == [76, 15]
    assert client.get("/api/rivers/kaveri").status_code == 200


def test_pilot_link_requires_source_identity_and_mutual_geometry(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "catalog.sqlite3")
    path = tmp_path / "source.kml"
    write_kml(path, placemark("245"))
    import_nwic_kml(path, "2025-11-17")
    geometry = {"type": "MultiLineString", "coordinates": [[[76, 15], [77, 16]]]}
    monkeypatch.setattr(nwic_river_explorer, "RIVER_CATALOG", [
        SimpleNamespace(id="tungabhadra", centerline=SimpleNamespace(model_dump=lambda: geometry))
    ])
    with acquisitions._catalog_connection() as db:
        db.execute(
            "UPDATE nwic_river_features SET source_river_id=?, name=?, basin=?, input_sha256=?",
            ("2912", "Tungabhadra River", "Krishna", nwic_river_explorer.PILOT_SOURCE_SHA256),
        )
    match = client.get("/api/river-network/features/245/geometry").json()["pilot_match"]
    assert match["river_id"] == "tungabhadra"
    assert match["pilot_overlap_fraction"] == pytest.approx(1)
    with acquisitions._catalog_connection() as db:
        db.execute("UPDATE nwic_river_features SET basin='Other'")
    assert "pilot_match" not in client.get("/api/river-network/features/245/geometry").json()
    with acquisitions._catalog_connection() as db:
        db.execute("UPDATE nwic_river_features SET basin='Krishna', geometry_json=?", (
            '{"type":"LineString","coordinates":[[80,20],[81,21]]}',))
    assert "pilot_match" not in client.get("/api/river-network/features/245/geometry").json()
