from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, box

from scripts.inspect_sentinel2_coverage import _intersecting_centerline_km


def test_centerline_coverage_reports_item_and_baseline_increment() -> None:
    centerline = LineString([(0, 0), (1_000, 0)])
    bounds = SimpleNamespace(left=0, bottom=-100, right=1_000, top=100)
    item_footprint = box(200, -50, 700, 50)
    baseline_footprint = box(100, -50, 300, 50)

    covered_km, incremental_km = _intersecting_centerline_km(
        centerline,
        bounds,
        item_footprint,
        baseline_footprint,
    )

    assert covered_km == pytest.approx(0.5)
    assert incremental_km == pytest.approx(0.4)
