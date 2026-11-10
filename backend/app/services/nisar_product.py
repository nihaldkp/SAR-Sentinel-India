from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import numpy as np


IDENTIFICATION_PATH = "science/LSAR/identification"
FREQUENCY_A_PATH = "science/LSAR/GCOV/grids/frequencyA"
NISAR_PRODUCT_ID = re.compile(r"^NISAR_L2_[A-Z0-9_]*GCOV_[A-Z0-9_]+$")


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict").strip()
    if isinstance(value, np.ndarray):
        if value.size != 1:
            raise ValueError("NISAR identification metadata must be scalar.")
        return _text(value.item())
    return str(value).strip()


def validate_nisar_gcov_hdf5(
    source: Any,
    expected_product_id: str,
) -> tuple[list[str], list[str]]:
    import h5py

    if not NISAR_PRODUCT_ID.fullmatch(expected_product_id):
        raise ValueError("The expected product identifier is not a NISAR L2 GCOV identifier.")

    identification_path = IDENTIFICATION_PATH
    fields = {
        "missionId": "NISAR",
        "platformName": "NISAR",
        "instrumentName": "LSAR",
        "productLevel": "L2",
        "productType": "GCOV",
        "granuleId": expected_product_id,
    }
    if identification_path not in source:
        raise ValueError("The HDF5 product is missing NISAR identification metadata.")
    for field, expected in fields.items():
        dataset_path = f"{identification_path}/{field}"
        if dataset_path not in source or _text(source[dataset_path][()]) != expected:
            raise ValueError(f"NISAR identification metadata does not match {field}.")
    if _text(source.attrs.get("mission_name", "")) != "NISAR":
        raise ValueError("The HDF5 root metadata does not identify the NISAR mission.")
    title = _text(source.attrs.get("title", ""))
    if "GCOV" not in title.upper():
        raise ValueError("The HDF5 root metadata does not identify a GCOV product.")
    frequencies_path = f"{identification_path}/listOfFrequencies"
    if frequencies_path not in source:
        raise ValueError("NISAR identification metadata is missing listOfFrequencies.")
    frequencies = {
        _text(value)
        for value in np.asarray(source[frequencies_path][()]).reshape(-1)
    }
    if "A" not in frequencies:
        raise ValueError("NISAR identification metadata does not declare frequency A.")

    required = (
        "HHHH",
        "HVHV",
        "mask",
        "xCoordinates",
        "yCoordinates",
        "projection",
        "xCoordinateSpacing",
        "yCoordinateSpacing",
        "listOfPolarizations",
    )
    missing = [
        f"{FREQUENCY_A_PATH}/{name}"
        for name in required
        if f"{FREQUENCY_A_PATH}/{name}" not in source
    ]
    if missing:
        raise ValueError(
            "The NISAR GCOV product is missing required frequency-A datasets."
        )

    hh = source[f"{FREQUENCY_A_PATH}/HHHH"]
    hv = source[f"{FREQUENCY_A_PATH}/HVHV"]
    mask = source[f"{FREQUENCY_A_PATH}/mask"]
    x = np.asarray(source[f"{FREQUENCY_A_PATH}/xCoordinates"][()])
    y = np.asarray(source[f"{FREQUENCY_A_PATH}/yCoordinates"][()])
    if (
        len(hh.shape) != 2
        or hh.shape != hv.shape
        or hh.shape != mask.shape
        or hh.shape != (len(y), len(x))
        or min(hh.shape) < 2
    ):
        raise ValueError("NISAR frequency-A rasters and coordinate axes are inconsistent.")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError("NISAR frequency-A coordinates contain invalid values.")
    x_spacing = float(source[f"{FREQUENCY_A_PATH}/xCoordinateSpacing"][()])
    y_spacing = float(source[f"{FREQUENCY_A_PATH}/yCoordinateSpacing"][()])
    if (
        not np.isfinite(x_spacing)
        or not np.isfinite(y_spacing)
        or x_spacing <= 0
        or y_spacing == 0
        or not np.allclose(np.diff(x), x_spacing, rtol=1e-6, atol=1e-5)
        or not np.allclose(np.diff(y), y_spacing, rtol=1e-6, atol=1e-5)
    ):
        raise ValueError("NISAR frequency-A coordinate axes are inconsistent with pixel spacing.")
    if not np.issubdtype(hh.dtype, np.number) or not np.issubdtype(hv.dtype, np.number):
        raise ValueError("NISAR frequency-A covariance rasters must contain numeric values.")
    polarizations = [
        _text(value)
        for value in np.asarray(
            source[f"{FREQUENCY_A_PATH}/listOfPolarizations"][()]
        ).reshape(-1)
    ]
    if "HH" not in polarizations or "HV" not in polarizations:
        raise ValueError("NISAR frequency-A metadata does not declare both HH and HV.")
    for dataset, label in ((hh, "HH"), (hv, "HV")):
        if _text(dataset.attrs.get("units", "")) != "1":
            raise ValueError(f"NISAR {label} covariance units are invalid.")
        if _text(dataset.attrs.get("grid_mapping", "")) != "projection":
            raise ValueError(f"NISAR {label} covariance projection mapping is invalid.")
    projection = source[f"{FREQUENCY_A_PATH}/projection"]
    if int(projection.attrs.get("epsg_code", 0)) <= 0:
        raise ValueError("NISAR GCOV projection metadata does not include a valid EPSG code.")

    groups = sorted(
        name for name, value in source.items() if isinstance(value, h5py.Group)
    )
    return groups, polarizations


def calculate_checksums(path: Path, include_md5: bool = False) -> dict[str, str]:
    sha256 = hashlib.sha256()
    md5 = hashlib.new("md5") if include_md5 else None
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            sha256.update(chunk)
            if md5 is not None:
                md5.update(chunk)
    checksums = {"sha256": sha256.hexdigest()}
    if md5 is not None:
        checksums["md5"] = md5.hexdigest()
    return checksums
