"""Incremental import of a locally supplied NWIC River Network KML export."""

import hashlib
import json
import math
import sqlite3
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import MultiLineString

from app.services.acquisitions import _catalog_connection

SOURCE_ID = "cwc-nwic-river-network"
SOURCE_URL = "https://nwdp.nwic.gov.in/dataset/river-line"
KML = "{http://www.opengis.net/kml/2.2}"


@contextmanager
def source_import_lock():
    with _catalog_connection() as connection:
        catalog = connection.execute("PRAGMA database_list").fetchone()[2]
    lock = sqlite3.connect(catalog + ".nwic-import-lock.sqlite3", timeout=0)
    try:
        try:
            lock.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:
            if exc.sqlite_errorcode not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise
            raise RuntimeError("Another NWIC import is running; retry after it finishes") from exc
        yield
    finally:
        lock.close()


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS nwic_imports (
            sha256 TEXT PRIMARY KEY, source_version TEXT NOT NULL,
            last_feature INTEGER NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS nwic_river_features (
            row_id INTEGER PRIMARY KEY, source_object_id TEXT NOT NULL UNIQUE,
            source_river_id TEXT, name TEXT, basin TEXT, sub_basin TEXT,
            states TEXT, start_district TEXT, end_district TEXT,
            confluence_name TEXT, source_version TEXT NOT NULL,
            imported_at TEXT NOT NULL, input_sha256 TEXT NOT NULL,
            properties_json TEXT NOT NULL, geometry_json TEXT NOT NULL,
            source_feature_kml TEXT, source_url TEXT
        )"""
    )
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(nwic_river_features)")}
    if "source_feature_kml" not in columns:
        connection.execute("ALTER TABLE nwic_river_features ADD COLUMN source_feature_kml TEXT")
    if "source_url" not in columns:
        connection.execute("ALTER TABLE nwic_river_features ADD COLUMN source_url TEXT")
    connection.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS nwic_river_bounds USING rtree(row_id, minx, maxx, miny, maxy)"
    )
    connection.execute("CREATE INDEX IF NOT EXISTS nwic_name_idx ON nwic_river_features(name)")
    connection.execute("CREATE INDEX IF NOT EXISTS nwic_basin_idx ON nwic_river_features(basin, sub_basin)")


def _feature(element: ET.Element) -> tuple[dict[str, str], str, tuple[float, float, float, float]]:
    properties = {
        item.attrib["name"]: (item.text or "").strip()
        for item in element.iter(f"{KML}SimpleData")
        if "name" in item.attrib
    }
    if not properties.get("OBJECTID"):
        raise ValueError("NWIC feature is missing OBJECTID")
    lines: list[list[tuple[float, float]]] = []
    for line in element.iter(f"{KML}LineString"):
        text = line.findtext(f"{KML}coordinates")
        if not text:
            raise ValueError(f"NWIC feature {properties['OBJECTID']} has empty coordinates")
        points = []
        for token in text.split():
            parts = token.split(",")
            if len(parts) < 2:
                raise ValueError(f"NWIC feature {properties['OBJECTID']} has invalid coordinates")
            x, y = float(parts[0]), float(parts[1])
            if not math.isfinite(x) or not math.isfinite(y) or not (-180 <= x <= 180 and -90 <= y <= 90):
                raise ValueError(f"NWIC feature {properties['OBJECTID']} has invalid WGS84 coordinates")
            points.append((x, y))
        if len(points) < 2:
            raise ValueError(f"NWIC feature {properties['OBJECTID']} has fewer than two coordinates")
        lines.append(points)
    if not lines:
        raise ValueError(f"NWIC feature {properties['OBJECTID']} has no LineString")
    geometry = MultiLineString(lines)
    if not geometry.is_valid or geometry.is_empty or geometry.length == 0:
        raise ValueError(f"NWIC feature {properties['OBJECTID']} has invalid line geometry")
    geojson = json.dumps({"type": "MultiLineString", "coordinates": lines}, separators=(",", ":"))
    return properties, geojson, geometry.bounds


def import_nwic_kml(path: Path, source_version: str, *, max_features: int | None = None) -> dict[str, object]:
    with source_import_lock():
        return _import_nwic_kml(path, source_version, max_features=max_features)


def _import_nwic_kml(path: Path, source_version: str, *, max_features: int | None = None) -> dict[str, object]:
    """Import a local KML in atomic single-feature checkpoints; never modifies pilot records."""
    if not source_version.strip() or (max_features is not None and max_features < 1):
        raise ValueError("A source version and a positive feature limit are required")
    initial_stat = path.stat()
    identity = (initial_stat.st_size, initial_stat.st_mtime_ns, initial_stat.st_ino)

    def check_input_unchanged() -> None:
        current = path.stat()
        if (current.st_size, current.st_mtime_ns, current.st_ino) != identity:
            raise ValueError("Input KML changed during import; use a stable source file")

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    check_input_unchanged()
    fingerprint = digest.hexdigest()
    with _catalog_connection() as connection:
        _initialize(connection)
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute(
            "SELECT 1 FROM nwic_imports WHERE sha256 != ? LIMIT 1", (fingerprint,)
        ).fetchone():
            raise ValueError(
                "A different source fingerprint is already registered; cross-version identity "
                "and updates require review before importing into this catalog"
            )
        row = connection.execute(
            "SELECT source_version, last_feature, completed FROM nwic_imports WHERE sha256=?",
            (fingerprint,),
        ).fetchone()
        if row and row["source_version"] != source_version:
            raise ValueError("This input fingerprint is already associated with a different source version")
        if row and row["completed"]:
            return {"sha256": fingerprint, "last_feature": row["last_feature"], "completed": True, "imported": 0}
        last_feature = row["last_feature"] if row else 0
        now = datetime.now(timezone.utc).isoformat()
        connection.execute(
            "INSERT OR IGNORE INTO nwic_imports (sha256, source_version, updated_at) VALUES (?, ?, ?)",
            (fingerprint, source_version, now),
        )
        connection.commit()

    count = 0
    index = 0
    stack: list[ET.Element] = []
    with path.open("rb") as source:
        for event, element in ET.iterparse(source, events=("start", "end")):
            if event == "start":
                stack.append(element)
                continue
            if element.tag == f"{KML}Placemark":
                index += 1
                if index > last_feature:
                    check_input_unchanged()
                    props, geometry, bounds = _feature(element)
                    now = datetime.now(timezone.utc).isoformat()
                    with _catalog_connection() as connection:
                        connection.execute("BEGIN IMMEDIATE")
                        progress = connection.execute(
                            "SELECT last_feature, completed FROM nwic_imports WHERE sha256=?", (fingerprint,)
                        ).fetchone()
                        if progress["completed"] or progress["last_feature"] != index - 1:
                            raise ValueError("Import checkpoint changed; retry using the saved checkpoint")
                        existing = connection.execute(
                            "SELECT input_sha256, properties_json, geometry_json FROM nwic_river_features WHERE source_object_id=?",
                            (props["OBJECTID"],),
                        ).fetchone()
                        serialized_properties = json.dumps(props, ensure_ascii=False)
                        if existing and existing["input_sha256"] == fingerprint:
                            raise ValueError(f"Duplicate OBJECTID in input: {props['OBJECTID']}")
                        if existing and (
                            existing["properties_json"] != serialized_properties
                            or existing["geometry_json"] != geometry
                        ):
                            raise ValueError(
                                f"Conflicting source OBJECTID {props['OBJECTID']}; "
                                "cross-version identity and updates require review"
                            )
                        connection.execute(
                            """INSERT INTO nwic_river_features
                            (source_object_id, source_river_id, name, basin, sub_basin, states,
                             start_district, end_district, confluence_name, source_version, imported_at,
                             input_sha256, properties_json, geometry_json, source_feature_kml, source_url)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(source_object_id) DO UPDATE SET
                             source_river_id=excluded.source_river_id, name=excluded.name,
                             basin=excluded.basin, sub_basin=excluded.sub_basin, states=excluded.states,
                             start_district=excluded.start_district, end_district=excluded.end_district,
                             confluence_name=excluded.confluence_name, source_version=excluded.source_version,
                             imported_at=excluded.imported_at, input_sha256=excluded.input_sha256,
                             properties_json=excluded.properties_json, geometry_json=excluded.geometry_json,
                             source_feature_kml=excluded.source_feature_kml, source_url=excluded.source_url""",
                            (props["OBJECTID"], props.get("UID_River"), props.get("rivname"),
                             props.get("ba_name"), props.get("sub_basin"), props.get("state_al"),
                             props.get("st_loc_dst"), props.get("en_loc_dst"), props.get("Confluence"),
                             source_version, now, fingerprint, serialized_properties, geometry,
                             ET.tostring(element, encoding="unicode"), SOURCE_URL),
                        )
                        row_id = connection.execute(
                            "SELECT row_id FROM nwic_river_features WHERE source_object_id=?", (props["OBJECTID"],)
                        ).fetchone()["row_id"]
                        connection.execute("DELETE FROM nwic_river_bounds WHERE row_id=?", (row_id,))
                        connection.execute(
                            "INSERT INTO nwic_river_bounds VALUES (?, ?, ?, ?, ?)",
                            (row_id, bounds[0], bounds[2], bounds[1], bounds[3]),
                        )
                        connection.execute(
                            "UPDATE nwic_imports SET last_feature=?, updated_at=? WHERE sha256=?",
                            (index, now, fingerprint),
                        )
                    count += 1
                    if max_features is not None and count >= max_features:
                        return {"sha256": fingerprint, "last_feature": index, "completed": False, "imported": count}
                if len(stack) > 1:
                    stack[-2].remove(element)
                element.clear()
            stack.pop()
    if index == 0:
        raise ValueError("No KML placemarks were found")
    check_input_unchanged()
    with _catalog_connection() as connection:
        connection.execute(
            "UPDATE nwic_imports SET completed=1, updated_at=? WHERE sha256=? AND last_feature=?",
            (datetime.now(timezone.utc).isoformat(), fingerprint, index),
        )
        if connection.execute("SELECT changes()").fetchone()[0] != 1:
            raise ValueError("Import checkpoint changed before completion")
    return {"sha256": fingerprint, "last_feature": index, "completed": True, "imported": count}
