from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.services import production_catalogue


def test_production_catalogue_preserves_only_supported_evidence() -> None:
    catalogue = production_catalogue.load_production_catalogue()
    records = {record.product.product_id: record for record in catalogue.records}
    a009 = next(record for product_id, record in records.items() if "_A_009_" in product_id)
    a010 = next(record for product_id, record in records.items() if "_A_010_" in product_id)
    a009_result = a009.product.processing_result
    a010_result = a010.product.processing_result

    assert len(records) == 2
    assert {river.river_id: river.nisar_status for river in catalogue.rivers} == {
        "kaveri": "no_data",
        "tungabhadra": "metadata_found",
    }
    assert a009.processing_status == "unvalidated_candidate"
    assert a009_result is not None
    assert a009_result.status == "unvalidated_candidate"
    assert a009.product.sha256 == "681af3bb7f67c64938e48c5d923a32ebe0b8541e596f61e89778424de60436ac"
    assert a009.product.integrity_status == "sha256_fingerprint_only"
    assert a009.product.provider_checksum is None
    assert a009.product.provider_authenticity_status == "not_verified"
    assert a009.product.scientific_validation_status == "not_performed"
    assert a009.product.acquisition_identifier == a009.product.product_id
    assert a009.product.size_bytes == 6811549696
    assert a009.product.acquisition_start is not None
    assert a009.product.acquisition_start.isoformat() == "2026-11-06T00:25:20+00:00"
    assert a009.source_availability
    assert a009_result.input_crs == "EPSG:32643"
    assert a009_result.pixel_size_m == 10.0
    assert a009.product.artifact_availability == "metadata_only"
    assert a009.product.local_path is None
    assert a009.product.source_url is None
    assert a009.candidate_geojson is not None
    assert a009_result.polygons_url is not None
    assert a009_result.mask_url is None

    assert a010.processing_status == "no_data"
    assert a010_result is not None
    assert a010_result.status == "no_valid_corridor_data"
    assert a010.product.sha256 == "69c67d71be73a4f8a00bc9ac3c6d5800ad4c9fd9989cf75073455027f3bf8d5d"
    assert a010_result.valid_pixel_count == 0
    assert a010_result.candidate_water_area_m2 is None
    assert a010.candidate_geojson is None
    assert all(record.river_id == "tungabhadra" for record in catalogue.records)


def test_missing_and_invalid_catalogues_fail_explicitly(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(production_catalogue.ProductionCatalogueError, match="missing"):
        production_catalogue.load_production_catalogue(missing, tmp_path)

    corrupted = tmp_path / "corrupted.json"
    corrupted.write_text("{", encoding="utf-8")
    with pytest.raises(production_catalogue.ProductionCatalogueError, match="invalid"):
        production_catalogue.load_production_catalogue(corrupted, tmp_path)


def test_corrupted_packaged_geojson_fails_sha256_validation(tmp_path: Path) -> None:
    manifest = json.loads(production_catalogue.PRODUCTION_CATALOGUE_PATH.read_text(encoding="utf-8"))
    artifact = manifest["records"][0]["candidate_geojson"]
    source = production_catalogue.PRODUCTION_DATA_ROOT / Path(*artifact["relative_path"].split("/"))
    artifact_root = tmp_path / "artifacts"
    destination = artifact_root / Path(*artifact["relative_path"].split("/"))
    destination.parent.mkdir(parents=True)
    shutil.copyfile(source, destination)
    destination.write_bytes(destination.read_bytes() + b" ")
    manifest_path = tmp_path / "catalogue.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(production_catalogue.ProductionCatalogueError, match="SHA-256"):
        production_catalogue.load_production_catalogue(manifest_path, artifact_root)
