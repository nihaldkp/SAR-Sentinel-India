import json
from pathlib import Path

from app.schemas.rivers import NisarPreparedEnvelope, River, RiverGeometry

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "rivers.geojson"


def _geojson_geometry(feature: dict) -> RiverGeometry:
    geometry = feature["geometry"]
    return RiverGeometry(type=geometry["type"], coordinates=geometry["coordinates"])


def load_river_catalog() -> list[River]:
    with DATA_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    rivers: list[River] = []
    for feature in payload.get("features", []):
        props = feature["properties"]
        river = River(
            id=props["id"],
            name=props["name"],
            display_name=props["display_name"],
            states=props["states"],
            geographical_location=props["location"],
            data_source=props["source"],
            source_url=props["source_url"],
            retrieval_url=props["retrieval_url"],
            osm_element_type=props["osm_element_type"],
            osm_element_id=props["osm_element_id"],
            retrieval_date=props["retrieval_date"],
            license=props["license"],
            license_url=props["license_url"],
            upstream_quality_note=props["upstream_quality_note"],
            available_geographical_data=props["available_geographical_data"],
            boundary_data_status=props["boundary_data_status"],
            left_bank_boundary=None,
            right_bank_boundary=None,
            centerline=_geojson_geometry(feature),
            future_nisar_integration=NisarPreparedEnvelope(
                supported=True,
                acquisition_datetime=None,
                polarizations=[],
                geographic_footprint=None,
                processed_water_masks=[],
                extracted_riverbank_boundaries=[],
                multi_date_change_detection_results=[],
            ),
        )
        rivers.append(river)
    return rivers


RIVER_CATALOG = load_river_catalog()
