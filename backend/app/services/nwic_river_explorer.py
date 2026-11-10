import json
import sqlite3
from typing import Any

from app.services.acquisitions import _catalog_connection


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
            return {"total": 0, "limit": limit, "offset": offset, "features": []}
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
            "SELECT geometry_json FROM nwic_river_features WHERE source_object_id=?",
            (source_object_id,),
        ).fetchone()
    return json.loads(row["geometry_json"]) if row else None
