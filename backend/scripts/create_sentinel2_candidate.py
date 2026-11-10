import argparse
import sys
import time
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.optical_reference import create_ndwi_candidate

COLLECTION = "sentinel-2-l2a"
ITEM_ID = "S2C_MSIL2A_20261106T052011_R062_T43PGT_20261106T101206"
ADDITIONAL_ITEM_IDS = {
    "S2C_MSIL2A_20261106T052011_R062_T43PER_20261106T101206",
    "S2C_MSIL2A_20261106T052011_R062_T43PES_20261106T101206",
    "S2C_MSIL2A_20261106T052011_R062_T43PFS_20261106T101206",
    "S2C_MSIL2A_20261106T052011_R062_T43PFT_20261106T101206",
}
STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
SIGN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
ASSET_KEYS = ("B03", "B08", "SCL")


def _signed_asset_urls(client: httpx.Client, item: dict[str, Any]) -> dict[str, str]:
    signed_urls: dict[str, str] = {}
    for key in ASSET_KEYS:
        asset = item.get("assets", {}).get(key)
        if not isinstance(asset, dict) or not isinstance(asset.get("href"), str):
            raise RuntimeError(f"Sentinel-2 catalog item is missing required asset {key}.")
        if signed_urls:
            time.sleep(2.5)
        response = client.get(SIGN_URL, params={"href": asset["href"]})
        response.raise_for_status()
        signed = response.json()
        if not isinstance(signed.get("href"), str):
            raise RuntimeError(f"Planetary Computer did not return a signed {key} asset URL.")
        signed_urls[key] = signed["href"]
    return signed_urls


def main() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    product_matches = list(
        (
            repository_root / "data" / "acquisitions" / "tungabhadra"
        ).glob("NISAR_L2_UR_GCOV_035_012_A_009_4005_DHDH_A_20261106T002520*")
    )
    if len(product_matches) != 1:
        raise RuntimeError(
            "Expected exactly one local A_009 product matching the verified acquisition."
        )
    product_directory = product_matches[0]
    parser = argparse.ArgumentParser(
        description=(
            "Create a separate, explicitly unvalidated Sentinel-2 NDWI candidate "
            "mask for a screened A_009 overpass tile."
        )
    )
    parser.add_argument("--item-id", default=ITEM_ID)
    parser.add_argument(
        "--nisar-mask",
        type=Path,
        default=product_directory / "nisar-processing" / "candidate-water-mask.tif",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=None,
    )
    parser.add_argument("--ndwi-threshold", type=float, default=0.0)
    args = parser.parse_args()
    if args.item_id != ITEM_ID and args.item_id not in ADDITIONAL_ITEM_IDS:
        parser.error("The item is not in the screened A_009 same-overpass tile set.")
    if not args.nisar_mask.is_file():
        parser.error(f"NISAR candidate mask does not exist: {args.nisar_mask}")
    output_directory = args.output_directory or (
        product_directory
        / "nisar-processing"
        / (
            "sentinel2-reference"
            if args.item_id == ITEM_ID
            else Path("sentinel2-observations") / args.item_id
        )
    )
    processing_directory = (product_directory / "nisar-processing").resolve()
    if not output_directory.resolve().is_relative_to(processing_directory):
        parser.error("Output directory must remain inside this NISAR product's processing folder.")

    with httpx.Client(timeout=60) as client:
        response = client.get(
            f"{STAC_URL}/collections/{COLLECTION}/items/{args.item_id}"
        )
        response.raise_for_status()
        item = response.json()
        if item.get("id") != args.item_id or item.get("collection") != COLLECTION:
            raise RuntimeError("The catalog returned an unexpected Sentinel-2 item.")
        signed_urls = _signed_asset_urls(client, item)

    properties = item.get("properties", {})
    source_metadata = {
        "provider": "Microsoft Planetary Computer",
        "collection": COLLECTION,
        "item_id": args.item_id,
        "acquisition_datetime": properties.get("start_datetime")
        or properties.get("datetime"),
        "mgrs_tile": properties.get("s2:mgrs_tile"),
        "catalog_cloud_cover_percent": properties.get("eo:cloud_cover"),
        "assets_used": list(ASSET_KEYS),
        "signed_asset_urls_persisted": False,
        "nisar_product_id": product_directory.name,
    }
    result = create_ndwi_candidate(
        band03_path=signed_urls["B03"],
        band08_path=signed_urls["B08"],
        scl_path=signed_urls["SCL"],
        nisar_mask_path=args.nisar_mask,
        footprint=item["geometry"],
        output_directory=output_directory,
        source_metadata=source_metadata,
        ndwi_threshold=args.ndwi_threshold,
    )
    counts = result["counts"]
    print(f"Status: {result['status']}")
    print(f"Output: {result['output_directory']}")
    print(f"Common valid pixels: {counts['common_valid_pixels']}")
    print(f"NDWI candidate pixels: {counts['ndwi_candidate_pixels']}")
    print(f"Candidate area: {counts['candidate_area_m2']:.1f} m2")
    print("Interpretation: exploratory candidate only; not a validated water mask.")


if __name__ == "__main__":
    main()
