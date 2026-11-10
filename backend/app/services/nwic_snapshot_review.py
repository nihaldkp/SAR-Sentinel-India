"""Stage NWIC snapshots for comparison without changing the active explorer."""

import hashlib
import json
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from app.services.acquisitions import _catalog_connection
from app.services.nwic_river_import import KML, SOURCE_ID, SOURCE_URL, _feature, source_import_lock


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _initialize(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS nwic_review_snapshots (
        sha256 TEXT PRIMARY KEY, source_id TEXT NOT NULL, source_url TEXT NOT NULL,
        source_version TEXT NOT NULL, started_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        completed_at TEXT, status TEXT NOT NULL, last_feature INTEGER NOT NULL DEFAULT 0,
        error_count INTEGER NOT NULL DEFAULT 0, last_error TEXT,
        previous_sha256 TEXT, reconciliation_status TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS nwic_review_features (
        snapshot_sha256 TEXT NOT NULL, source_object_id TEXT NOT NULL,
        properties_json TEXT NOT NULL, geometry_json TEXT NOT NULL, source_feature_kml TEXT NOT NULL,
        PRIMARY KEY (snapshot_sha256, source_object_id)
    )""")


def stage_snapshot(path: Path, source_version: str, *, max_features: int | None = None) -> dict[str, object]:
    """Stage an immutable input for manual review; never modify live NWIC or pilot features."""
    if not source_version.strip() or (max_features is not None and max_features < 1):
        raise ValueError("A source version and a positive feature limit are required")
    with source_import_lock():
        return _stage_snapshot(path, source_version, max_features)


def _stage_snapshot(path: Path, source_version: str, max_features: int | None) -> dict[str, object]:
    stat = path.stat()
    identity = (stat.st_size, stat.st_mtime_ns, stat.st_ino)

    def check_input() -> None:
        current = path.stat()
        if (current.st_size, current.st_mtime_ns, current.st_ino) != identity:
            raise ValueError("Input KML changed during staging")

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    check_input()
    fingerprint = digest.hexdigest()
    with _catalog_connection() as db:
        _initialize(db)
        row = db.execute("SELECT * FROM nwic_review_snapshots WHERE sha256=?", (fingerprint,)).fetchone()
        if row and row["source_version"] != source_version:
            raise ValueError("This fingerprint is already associated with a different source version")
        if row and row["status"] == "complete":
            return {"sha256": fingerprint, "last_feature": row["last_feature"], "completed": True, "staged": 0}
        if row and row["status"] == "abandoned":
            raise ValueError("This snapshot was abandoned and cannot be resumed")
        other = db.execute(
            "SELECT sha256 FROM nwic_review_snapshots WHERE sha256 != ? AND status IN ('staging', 'failed') LIMIT 1",
            (fingerprint,),
        ).fetchone()
        if other:
            raise ValueError("Another snapshot is incomplete or failed; resume it before staging a new snapshot")
        last_feature = row["last_feature"] if row else 0
        previous = db.execute(
            "SELECT sha256 FROM nwic_review_snapshots WHERE status='complete' ORDER BY completed_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        now = _now()
        if not row:
            db.execute(
                """INSERT INTO nwic_review_snapshots
                (sha256, source_id, source_url, source_version, started_at, updated_at, status,
                 previous_sha256, reconciliation_status) VALUES (?, ?, ?, ?, ?, ?, 'staging', ?, 'pending')""",
                (fingerprint, SOURCE_ID, SOURCE_URL, source_version, now, now, previous["sha256"] if previous else None),
            )
        else:
            db.execute("UPDATE nwic_review_snapshots SET status='staging', updated_at=?, last_error=NULL WHERE sha256=?",
                       (now, fingerprint))

    count = 0
    index = 0
    stack: list[ET.Element] = []
    try:
        with path.open("rb") as source:
            for event, element in ET.iterparse(source, events=("start", "end")):
                if event == "start":
                    stack.append(element)
                    continue
                if element.tag == f"{KML}Placemark":
                    index += 1
                    if index > last_feature:
                        check_input()
                        props, geometry, _ = _feature(element)
                        with _catalog_connection() as db:
                            try:
                                db.execute(
                                    "INSERT INTO nwic_review_features VALUES (?, ?, ?, ?, ?)",
                                    (fingerprint, props["OBJECTID"],
                                     json.dumps(props, ensure_ascii=False, sort_keys=True), geometry,
                                     ET.tostring(element, encoding="unicode")),
                                )
                            except sqlite3.IntegrityError as exc:
                                raise ValueError(f"Duplicate OBJECTID in snapshot: {props['OBJECTID']}") from exc
                            db.execute(
                                "UPDATE nwic_review_snapshots SET last_feature=?, updated_at=? WHERE sha256=?",
                                (index, _now(), fingerprint),
                            )
                        count += 1
                        if max_features is not None and count >= max_features:
                            return {"sha256": fingerprint, "last_feature": index, "completed": False, "staged": count}
                    if len(stack) > 1:
                        stack[-2].remove(element)
                    element.clear()
                stack.pop()
        if index == 0:
            raise ValueError("No KML placemarks were found")
        check_input()
        with _catalog_connection() as db:
            db.execute(
                """UPDATE nwic_review_snapshots SET status='complete', completed_at=?, updated_at=?,
                   reconciliation_status='awaiting_review' WHERE sha256=? AND last_feature=?""",
                (_now(), _now(), fingerprint, index),
            )
            if db.execute("SELECT changes()").fetchone()[0] != 1:
                raise ValueError("Snapshot checkpoint changed before completion")
    except (ValueError, OSError, sqlite3.Error, ET.ParseError) as exc:
        with _catalog_connection() as db:
            db.execute(
                """UPDATE nwic_review_snapshots SET status='failed', error_count=error_count+1,
                   last_error=?, updated_at=? WHERE sha256=?""",
                (str(exc), _now(), fingerprint),
            )
        raise
    return {"sha256": fingerprint, "last_feature": index, "completed": True, "staged": count}


def abandon_snapshot(fingerprint: str) -> None:
    """Retain a failed or incomplete snapshot while allowing a different input."""
    with source_import_lock(), _catalog_connection() as db:
        _initialize(db)
        db.execute(
            """UPDATE nwic_review_snapshots SET status='abandoned', updated_at=?
               WHERE sha256=? AND status IN ('staging', 'failed')""",
            (_now(), fingerprint),
        )
        if db.execute("SELECT changes()").fetchone()[0] != 1:
            raise ValueError("Snapshot is not incomplete or failed")


def snapshot_history(*, offset: int = 0, limit: int = 100) -> list[dict[str, object]]:
    if offset < 0 or not 1 <= limit <= 1000:
        raise ValueError("Offset must be nonnegative and limit must be between 1 and 1000")
    with _catalog_connection() as db:
        _initialize(db)
        rows = db.execute(
            "SELECT * FROM nwic_review_snapshots ORDER BY rowid DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
    return [dict(row) for row in rows]


def compare_snapshots(old: str, new: str, *, offset: int = 0, limit: int = 100) -> dict[str, object]:
    """Compare same-ID source records as review candidates, not verified identities."""
    if offset < 0 or not 1 <= limit <= 1000:
        raise ValueError("Offset must be nonnegative and limit must be between 1 and 1000")
    with _catalog_connection() as db:
        _initialize(db)
        for fingerprint in (old, new):
            row = db.execute("SELECT status FROM nwic_review_snapshots WHERE sha256=?", (fingerprint,)).fetchone()
            if not row or row["status"] != "complete":
                raise ValueError("Both snapshots must be completely staged")
        rows = db.execute(
            """SELECT COALESCE(a.source_object_id, b.source_object_id) AS source_object_id,
                      a.source_object_id IS NULL AS added, b.source_object_id IS NULL AS removed,
                      a.properties_json != b.properties_json AS attributes_changed,
                      a.geometry_json != b.geometry_json AS geometry_changed,
                      a.properties_json AS old_properties, b.properties_json AS new_properties
               FROM nwic_review_features a LEFT JOIN nwic_review_features b
                 ON b.snapshot_sha256=? AND a.source_object_id=b.source_object_id
               WHERE a.snapshot_sha256=?
               UNION ALL
               SELECT b.source_object_id, 1, 0, NULL, NULL, NULL, b.properties_json
               FROM nwic_review_features b LEFT JOIN nwic_review_features a
                 ON a.snapshot_sha256=? AND a.source_object_id=b.source_object_id
               WHERE b.snapshot_sha256=? AND a.source_object_id IS NULL
               ORDER BY source_object_id LIMIT ? OFFSET ?""", (new, old, old, new, limit, offset),
        ).fetchall()
    features = []
    for row in rows:
        item = dict(row)
        old_json = item.pop("old_properties")
        new_json = item.pop("new_properties")
        old_properties = json.loads(old_json) if old_json else None
        new_properties = json.loads(new_json) if new_json else None
        item["old_source_river_id"] = old_properties.get("UID_River") if old_properties else None
        item["new_source_river_id"] = new_properties.get("UID_River") if new_properties else None
        item["identity_conflict"] = bool(
            old_properties and new_properties
            and item["old_source_river_id"] != item["new_source_river_id"]
        )
        features.append(item)
    return {
        "old_sha256": old, "new_sha256": new, "offset": offset, "limit": limit,
        "identity_warning": "OBJECTID stability is unverified; all matches and differences require review.",
        "features": features,
    }
