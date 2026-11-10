import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import acquisitions
from app.services.nwic_river_import import import_nwic_kml
from app.services.nwic_snapshot_review import abandon_snapshot, compare_snapshots, stage_snapshot
from test_nwic_river_import import placemark, write_kml


def test_staging_compare_resume_and_live_isolation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "catalog.sqlite3")
    old = tmp_path / "old.kml"
    new = tmp_path / "new.kml"
    write_kml(old, placemark("1"), placemark("2"))
    write_kml(new, placemark("1", "76,15 78,16").replace("river-1", "different-river"), placemark("3"))
    live = import_nwic_kml(old, "live-v1")
    first = stage_snapshot(old, "v1", max_features=1)
    with pytest.raises(ValueError, match="incomplete"):
        stage_snapshot(new, "v2")
    assert stage_snapshot(old, "v1")["completed"]
    assert stage_snapshot(old, "v1")["staged"] == 0
    second = stage_snapshot(new, "v2")
    result = compare_snapshots(first["sha256"], second["sha256"])
    features = {item["source_object_id"]: item for item in result["features"]}
    assert features["1"]["geometry_changed"] == 1
    assert features["1"]["attributes_changed"] == 1
    assert features["1"]["identity_conflict"]
    assert features["2"]["removed"] == 1
    assert features["3"]["added"] == 1
    assert len(compare_snapshots(first["sha256"], second["sha256"], limit=1)["features"]) == 1
    with acquisitions._catalog_connection() as db:
        rows = db.execute("SELECT * FROM nwic_review_snapshots ORDER BY rowid").fetchall()
        assert rows[1]["previous_sha256"] == first["sha256"]
        assert rows[1]["reconciliation_status"] == "awaiting_review"
        assert rows[1]["last_feature"] == 2 and rows[1]["completed_at"]
        assert db.execute("SELECT COUNT(*) FROM nwic_river_features WHERE input_sha256=?", (live["sha256"],)).fetchone()[0] == 2


def test_failed_snapshot_is_retained_and_can_be_abandoned(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", tmp_path / "catalog.sqlite3")
    bad = tmp_path / "bad.kml"
    good = tmp_path / "good.kml"
    write_kml(bad, placemark("1"), placemark("1"))
    write_kml(good, placemark("2"))
    with pytest.raises(ValueError, match="Duplicate OBJECTID"):
        stage_snapshot(bad, "bad")
    with acquisitions._catalog_connection() as db:
        row = db.execute("SELECT * FROM nwic_review_snapshots").fetchone()
        assert row["status"] == "failed" and row["error_count"] == 1 and row["last_feature"] == 1
        fingerprint = row["sha256"]
    with pytest.raises(ValueError, match="incomplete or failed"):
        stage_snapshot(good, "good")
    abandon_snapshot(fingerprint)
    assert stage_snapshot(good, "good")["completed"]
    with acquisitions._catalog_connection() as db:
        assert db.execute("SELECT status FROM nwic_review_snapshots WHERE sha256=?", (fingerprint,)).fetchone()[0] == "abandoned"
        assert db.execute("SELECT COUNT(*) FROM nwic_review_features WHERE snapshot_sha256=?", (fingerprint,)).fetchone()[0] == 1


def test_cross_process_lock_released_on_process_exit(monkeypatch, tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite3"
    monkeypatch.setattr(acquisitions, "CATALOG_PATH", database)
    first = tmp_path / "first.kml"
    second = tmp_path / "second.kml"
    write_kml(first, placemark("1"), placemark("2"))
    write_kml(second, placemark("3"))
    code = """
import sys
from pathlib import Path
from app.services import acquisitions, nwic_snapshot_review as review
acquisitions.CATALOG_PATH = Path(sys.argv[1])
original = review._feature
count = 0
def gated(element):
    global count
    count += 1
    if count == 2:
        print('locked', flush=True)
        sys.stdin.readline()
    return original(element)
review._feature = gated
review.stage_snapshot(Path(sys.argv[2]), 'one')
"""
    env = os.environ.copy()
    env["SAR_AUTO_ACQUISITION_ENABLED"] = "false"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(database), str(first)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env=env,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "locked"
        with pytest.raises(RuntimeError, match="retry"):
            stage_snapshot(first, "one")
        with pytest.raises(RuntimeError, match="retry"):
            stage_snapshot(second, "two")
        with pytest.raises(RuntimeError, match="retry"):
            import_nwic_kml(second, "two")
    finally:
        process.terminate()
        process.wait(timeout=10)
    result = stage_snapshot(first, "one")
    assert result["completed"] and result["staged"] == 1
