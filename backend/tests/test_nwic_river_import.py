import json
import sqlite3
from pathlib import Path

import pytest

from app.services import acquisitions
from app.services.nwic_river_import import import_nwic_kml


def placemark(object_id: str, coordinates: str = "76,15 77,16") -> str:
    return (
        "<Placemark><ExtendedData><SchemaData>"
        f'<SimpleData name="OBJECTID">{object_id}</SimpleData>'
        f'<SimpleData name="UID_River">river-{object_id}</SimpleData>'
        '<SimpleData name="rivname">Fixture</SimpleData>'
        '<SimpleData name="ba_name">Fixture basin</SimpleData>'
        "</SchemaData></ExtendedData>"
        f"<LineString><coordinates>{coordinates}</coordinates></LineString></Placemark>"
    )


def write_kml(path: Path, *features: str) -> None:
    path.write_text(
        '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        + "".join(features) + "</Document></kml>",
        encoding="utf-8",
    )


def test_import_resumes_and_preserves_source_fields(monkeypatch, tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite3"
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", database)
    path = tmp_path / "source.kml"
    write_kml(path, placemark("1"), placemark("2"))
    first = import_nwic_kml(path, "2025-11-17", max_features=1)
    assert first["last_feature"] == 1 and not first["completed"]
    second = import_nwic_kml(path, "2025-11-17")
    assert second["imported"] == 1 and second["completed"]
    assert import_nwic_kml(path, "2025-11-17")["imported"] == 0
    with sqlite3.connect(database) as db:
        rows = db.execute(
            "SELECT source_object_id, source_river_id, source_version, geometry_json, input_sha256, source_feature_kml, source_url FROM nwic_river_features ORDER BY source_object_id"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][:3] == ("1", "river-1", "2025-11-17")
        assert json.loads(rows[0][3])["coordinates"][0][0] == [76, 15]
        assert rows[0][4] == first["sha256"]
        assert "76,15 77,16" in rows[0][5]
        assert rows[0][6] == "https://nwdp.nwic.gov.in/dataset/river-line"
        assert db.execute("SELECT COUNT(*) FROM nwic_river_bounds").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM acquired_products").fetchone()[0] == 0


def test_duplicate_and_invalid_feature_stop_without_advancing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "catalog.sqlite3")
    path = tmp_path / "source.kml"
    write_kml(path, placemark("1"), placemark("1"))
    with pytest.raises(ValueError, match="Duplicate OBJECTID"):
        import_nwic_kml(path, "v1")
    with acquisitions._catalog_connection() as db:
        assert db.execute("SELECT last_feature FROM nwic_imports").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM nwic_river_features").fetchone()[0] == 1
    bad = tmp_path / "bad.kml"
    write_kml(bad, placemark("2", "5000000,4000000 5000001,4000001"))
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "bad-catalog.sqlite3")
    with pytest.raises(ValueError, match="invalid WGS84"):
        import_nwic_kml(bad, "v1")


def test_changed_source_identity_is_not_silently_overwritten(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "catalog.sqlite3")
    path = tmp_path / "source.kml"
    write_kml(path, placemark("1"))
    import_nwic_kml(path, "v1")
    write_kml(path, placemark("1", "76,15 78,16"))
    with pytest.raises(ValueError, match="cross-version identity"):
        import_nwic_kml(path, "v2")
    write_kml(path, placemark("2"))
    with pytest.raises(ValueError, match="different source fingerprint"):
        import_nwic_kml(path, "v2")
    with acquisitions._catalog_connection() as db:
        assert db.execute("SELECT COUNT(*) FROM nwic_river_features").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM nwic_imports").fetchone()[0] == 1
