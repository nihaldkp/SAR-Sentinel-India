import numpy as np
import pytest

from app.services.sentinel2 import calculate_indices


def test_indices_apply_surface_reflectance_scaling_and_formulas() -> None:
    blue = np.array([[1000]], dtype=np.uint16)
    red = np.array([[2000]], dtype=np.uint16)
    nir = np.array([[6000]], dtype=np.uint16)
    swir = np.array([[3000]], dtype=np.uint16)

    result = calculate_indices(blue, red, nir, swir, np.array([[True]]))

    assert result["ndvi"][0, 0] == pytest.approx((0.6 - 0.2) / (0.6 + 0.2))
    assert result["ndmi"][0, 0] == pytest.approx((0.6 - 0.3) / (0.6 + 0.3))
    assert result["evi"][0, 0] == pytest.approx(2.5 * (0.6 - 0.2) / (0.6 + 6 * 0.2 - 7.5 * 0.1 + 1))


def test_indices_exclude_invalid_pixels_and_zero_denominators() -> None:
    values = np.array([[0, 1000]], dtype=np.uint16)
    result = calculate_indices(values, values, values, values, np.array([[True, False]]))

    assert np.isnan(result["ndvi"][0, 0])
    assert np.isnan(result["evi"][0, 0])
    assert np.isnan(result["ndmi"][0, 0])
    assert np.isnan(result["ndvi"][0, 1])
    assert np.isnan(result["evi"][0, 1])
    assert np.isnan(result["ndmi"][0, 1])
