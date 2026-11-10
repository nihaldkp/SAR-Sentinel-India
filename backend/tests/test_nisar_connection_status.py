from app.schemas.acquisitions import AcquisitionStatus, NisarProduct, RiverAcquisitionStatus
from app.schemas.satellite import SatelliteObservation


def test_connection_status_reports_cached_records_not_live_connectivity() -> None:
    product = NisarProduct(
        product_id="example",
        product_level="GCOV",
        availability="downloaded_verified",
        download_status="downloaded",
        hdf5_groups=["science"],
        acquisition_start="2026-11-06T00:25:20Z",
    )
    river = RiverAcquisitionStatus(
        river_id="tungabhadra",
        status="failed",
        nisar_status="error",
        nisar_products=[product, product],
        observations=[],
        issues=[],
    )
    status = AcquisitionStatus(
        enabled=False,
        polling_interval_seconds=60,
        source="Microsoft Planetary Computer Sentinel-1 RTC",
        source_url="https://example.test",
        license="test",
        rivers=[river],
    ).model_dump(mode="json")["nisar_connection_status"]

    assert status["provider_connectivity"] == "unknown"
    assert status["authentication_status"] == "unknown"
    assert status["last_successful_search"] is None
    assert status["cached_product_count"] == 1
    assert status["recorded_download_count"] == 1
    assert status["recorded_inspection_count"] == 1
    assert status["recorded_processing_count"] == 0
    assert status["latest_recorded_inspection_product_id"] == "example"
    assert status["recorded_error"] is True


def test_empty_catalog_does_not_claim_provider_success() -> None:
    status = AcquisitionStatus(
        enabled=False,
        polling_interval_seconds=60,
        source="Microsoft Planetary Computer Sentinel-1 RTC",
        source_url="https://example.test",
        license="test",
        rivers=[],
    ).model_dump(mode="json")["nisar_connection_status"]
    assert status["cached_product_count"] == 0
    assert status["latest_recorded_inspection_product_id"] is None
    assert status["latest_recorded_processing"] is None
    assert status["provider_connectivity"] == "unknown"
    assert status["recorded_error"] is False


def test_live_authentication_summary_uses_recorded_attempt_not_cached_downloads() -> None:
    river = RiverAcquisitionStatus(
        river_id="tungabhadra",
        status="processed",
        nisar_status="metadata_found",
        earthdata_authentication_status="data_access_verified",
        earthdata_authentication_checked_at="2026-11-10T12:00:00Z",
        last_successful_nisar_search="2026-11-10T11:59:59Z",
        nisar_products=[],
        observations=[],
        issues=[],
    )

    status = AcquisitionStatus(
        enabled=False,
        polling_interval_seconds=60,
        source="Microsoft Planetary Computer Sentinel-1 RTC",
        source_url="https://example.test",
        license="test",
        rivers=[river],
    ).model_dump(mode="json")["nisar_connection_status"]

    assert status["provider_connectivity"] == "available"
    assert status["authentication_status"] == "data_access_verified"
    assert status["authentication_checked_at"] == "2026-11-10T12:00:00Z"
    assert status["last_successful_search"] == "2026-11-10T11:59:59Z"


def test_api_schema_redacts_credentials_from_urls_and_messages(monkeypatch) -> None:
    token = "earthdata-unit-test-secret"
    monkeypatch.setenv("EARTHDATA_TOKEN", token)

    product = NisarProduct(
        product_id="example",
        product_level="GCOV",
        availability="metadata_found",
        download_status="not_attempted",
        source_url=(
            "https://nisar.asf.earthdatacloud.nasa.gov/example.h5"
            f"?signature=signed-secret&token={token}&download=1"
        ),
        message=f"Authorization: Bearer {token}\nCookie: session={token}",
    ).model_dump(mode="json")
    observation = SatelliteObservation(
        id="example",
        mission="NISAR",
        metadata_url="https://example.test/item?access_token=metadata-secret",
        download_url="https://example.test/file?sig=asset-secret",
        source="ASF DAAC",
        analysis_readiness="test",
    ).model_dump(mode="json")

    serialized = str({"product": product, "observation": observation})
    assert token not in serialized
    assert "signed-secret" not in serialized
    assert "metadata-secret" not in serialized
    assert "asset-secret" not in serialized
    assert "[REDACTED]" in serialized
    assert "download=1" in serialized
