from app.schemas.acquisitions import AcquisitionStatus, NisarProduct, RiverAcquisitionStatus


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
