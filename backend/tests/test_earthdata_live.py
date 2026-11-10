import os
from pathlib import Path

import pytest

from app.services import acquisitions

LIVE_NISAR_PRODUCT_ID = (
    "NISAR_L2_UR_GCOV_035_012_A_009_4005_DHDH_A_20261106T002520_"
    "20261106T002555_P05036_F_F_J_001"
)


@pytest.mark.earthdata_live
def test_live_authenticated_nisar_range_access() -> None:
    if os.getenv("SAR_EARTHDATA_LIVE_TEST") != "1":
        pytest.skip("Set SAR_EARTHDATA_LIVE_TEST=1 to run the real ASF/Earthdata access check.")

    session, authentication_error = acquisitions._earthdata_session()
    assert session is not None, acquisitions._earthdata_authentication_message(authentication_error)

    asf = acquisitions.import_module("asf_search")
    results = asf.granule_search(
        [LIVE_NISAR_PRODUCT_ID],
        opts=asf.ASFSearchOptions(session=session),
    )
    if hasattr(results, "raise_if_incomplete"):
        results.raise_if_incomplete()
    assert results, "ASF returned no metadata for the known NISAR GCOV product."
    product = acquisitions._nisar_product_metadata(
        results[0].geojson(),
        authenticated=True,
    )
    assert product is not None

    access_status, message = acquisitions._check_nisar_download(
        product.get("_download_url") or product["source_url"],
        session=session,
    )

    assert access_status == "authenticated_access_verified", message


@pytest.mark.earthdata_live
def test_live_authenticated_nisar_full_download_verification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    if os.getenv("SAR_EARTHDATA_LIVE_DOWNLOAD_TEST") != "1":
        pytest.skip(
            "Set SAR_EARTHDATA_LIVE_DOWNLOAD_TEST=1 and "
            "SAR_EARTHDATA_LIVE_DOWNLOAD_PRODUCT_ID to run a bounded full-product check."
        )
    product_id = os.getenv("SAR_EARTHDATA_LIVE_DOWNLOAD_PRODUCT_ID", "").strip()
    if not product_id:
        pytest.skip("Set SAR_EARTHDATA_LIVE_DOWNLOAD_PRODUCT_ID to a known small GCOV product.")

    session, authentication_error = acquisitions._earthdata_session()
    assert session is not None, acquisitions._earthdata_authentication_message(authentication_error)
    product = acquisitions._search_nisar_product_by_id(product_id, session)
    maximum_size = 128 * 1024 * 1024
    if not product.get("size_bytes") or product["size_bytes"] > maximum_size:
        pytest.skip("The selected NISAR product is not catalogued below the 128 MiB live-test limit.")
    access_status, message = acquisitions._check_nisar_download(
        product["_download_url"],
        session=session,
    )
    assert access_status == "authenticated_access_verified", message

    monkeypatch.setattr(acquisitions, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(acquisitions, "ACQUISITION_ROOT", tmp_path / "data" / "acquisitions")
    downloaded = acquisitions._download_nisar_product(
        "kaveri",
        product,
        session,
    )

    assert downloaded["download_status"] == "downloaded"
    assert downloaded["structure_verification_status"] == "verified"
    assert downloaded["sha256"]
    assert downloaded["scientific_validation_status"] == "not_performed"
    local_path = tmp_path / downloaded["local_path"]
    assert local_path.is_file()
    assert local_path.stat().st_size == product["size_bytes"]
    assert acquisitions.calculate_checksums(local_path)["sha256"] == downloaded["sha256"]
