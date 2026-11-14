import json
import sqlite3
from typing import Any

from rasterio.warp import transform_geom
from shapely.geometry import shape

from app.services.acquisitions import _catalog_connection
from app.services.rivers import RIVER_CATALOG

PILOT_SOURCE_SHA256 = "e360257af967e954efb87d3172b0c74a813a05f82fef3a5e404973357d57bf06"
PILOT_SOURCE_IDENTITIES = {
    "245": ("2912", "Tungabhadra River", "Krishna", "tungabhadra"),
    "548": ("6983", "Cauvery River", "Cauvery", "kaveri"),
}


def _literal_like(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _available(connection: sqlite3.Connection) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nwic_river_features'"
    ).fetchone() is not None


def search_features(
    *, query: str | None, basin: str | None, sub_basin: str | None,
    state: str | None, district: str | None,
    bbox: tuple[float, float, float, float] | None, limit: int, offset: int,
) -> dict[str, Any]:
    clauses: list[str] = []
    parameters: list[object] = []
    if query:
        clauses.append("(f.name LIKE ? ESCAPE '\\' OR f.source_object_id LIKE ? ESCAPE '\\' OR f.source_river_id LIKE ? ESCAPE '\\')")
        parameters.extend([_literal_like(query)] * 3)
    for column, value in (("basin", basin), ("sub_basin", sub_basin), ("states", state)):
        if value:
            clauses.append(f"f.{column} LIKE ? ESCAPE '\\'")
            parameters.append(_literal_like(value))
    if district:
        clauses.append("(f.start_district LIKE ? ESCAPE '\\' OR f.end_district LIKE ? ESCAPE '\\')")
        parameters.extend([_literal_like(district)] * 2)
    if bbox:
        west, south, east, north = bbox
        clauses.append("b.maxx >= ? AND b.minx <= ? AND b.maxy >= ? AND b.miny <= ?")
        parameters.extend((west, east, south, north))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    join = " JOIN nwic_river_bounds b ON b.row_id=f.row_id" if bbox else ""
    with _catalog_connection() as connection:
        if not _available(connection):
            return {"source_status": "not_imported", "total": 0, "limit": limit, "offset": offset, "features": []}
        import_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nwic_imports'"
        ).fetchone()
        completed = connection.execute(
            "SELECT completed FROM nwic_imports ORDER BY updated_at DESC LIMIT 1"
        ).fetchone() if import_table else None
        total = connection.execute(
            "SELECT count(*) FROM nwic_river_features f" + join + where, parameters
        ).fetchone()[0]
        rows = connection.execute(
            """SELECT f.source_object_id, f.source_river_id, f.name, f.basin, f.sub_basin,
                      f.states, f.start_district, f.end_district, f.confluence_name,
                      f.source_version, f.imported_at, f.source_url
               FROM nwic_river_features f""" + join + where
            + " ORDER BY f.name COLLATE NOCASE, f.source_object_id COLLATE BINARY LIMIT ? OFFSET ?",
            [*parameters, limit, offset],
        ).fetchall()
    return {
        "source_status": "available", "import_complete": bool(completed and completed["completed"]),
        "total": total, "limit": limit, "offset": offset,
        "features": [
            {**dict(row), "source": "CWC/NWIC River Network", "geometry_available": True,
             "monitoring_status": "unknown", "district_scope": "source start or end point only"}
            for row in rows
        ],
    }


def feature_geometry(source_object_id: str) -> dict[str, Any] | None:
    with _catalog_connection() as connection:
        if not _available(connection):
            return None
        row = connection.execute(
            "SELECT geometry_json, source_river_id, name, basin, source_version, input_sha256 "
            "FROM nwic_river_features WHERE source_object_id=?",
            (source_object_id,),
        ).fetchone()
    if not row:
        return None
    geometry = json.loads(row["geometry_json"])
    identity = PILOT_SOURCE_IDENTITIES.get(source_object_id)
    if (identity and row["input_sha256"] == PILOT_SOURCE_SHA256
            and row["source_version"] == "2025-11-17"
            and (row["source_river_id"], row["name"], row["basin"]) == identity[:3]):
        river = next((item for item in RIVER_CATALOG if item.id == identity[3]), None)
        if river is not None:
            nwic_line = shape(transform_geom("EPSG:4326", "EPSG:32643", geometry))
            pilot_line = shape(transform_geom("EPSG:4326", "EPSG:32643", river.centerline.model_dump()))
            if nwic_line.length and pilot_line.length:
                nwic_overlap = min(1.0, nwic_line.intersection(pilot_line.buffer(1500)).length / nwic_line.length)
                pilot_overlap = min(1.0, pilot_line.intersection(nwic_line.buffer(1500)).length / pilot_line.length)
                if nwic_overlap >= 0.95 and pilot_overlap >= 0.95:
                    geometry["pilot_match"] = {
                        "river_id": identity[3],
                        "method": "Verified source identity and at least 95% mutual centerline overlap within 1,500 m in EPSG:32643.",
                        "nwic_overlap_fraction": nwic_overlap,
                        "pilot_overlap_fraction": pilot_overlap,
                    }
    return geometry
