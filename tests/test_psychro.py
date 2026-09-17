"""Psychrometrics against published ASHRAE values, and against psychrolib if present."""

import numpy as np
import pytest

from zcbsl_resize import psychro

# ASHRAE Handbook of Fundamentals, saturation pressure of water vapour, Pa.
SATURATION_TABLE = {
    -10.0: 259.9,   # over ice
    -5.0: 401.7,    # over ice
    0.0: 611.2,
    5.0: 872.6,
    10.0: 1228.1,
    20.0: 2338.8,
    25.0: 3169.2,
    30.0: 4246.0,
    40.0: 7384.9,
    50.0: 12351.0,
}


@pytest.mark.parametrize("t_c,expected", sorted(SATURATION_TABLE.items()))
def test_saturation_pressure_matches_ashrae_table(t_c, expected):
    assert psychro.saturation_pressure(t_c) == pytest.approx(expected, rel=2e-4)


def test_humidity_ratio_matches_published_value():
    # 25 degC, 50% RH, sea level: W = 0.00988 kg/kg
    assert psychro.humidity_ratio(25.0, 50.0) == pytest.approx(0.00988, rel=2e-3)


def test_dew_point_matches_published_value():
    assert psychro.dew_point(25.0, 50.0) == pytest.approx(13.9, abs=0.1)


def test_humidity_ratio_inverts_cleanly():
    for t in (-5.0, 5.0, 22.0, 35.0):
        for rh in (15.0, 45.0, 90.0):
            w = psychro.humidity_ratio(t, rh, 96500.0)
            assert psychro.relative_humidity(t, w, 96500.0) == pytest.approx(rh, rel=1e-6)


def test_saturated_air_has_dew_point_equal_to_dry_bulb():
    assert psychro.dew_point(18.0, 100.0) == pytest.approx(18.0, abs=0.02)


def test_lower_pressure_raises_humidity_ratio():
    """Zurich at ~96.5 kPa holds more moisture per kg of dry air than sea level."""
    sea = psychro.humidity_ratio(22.0, 50.0, 101325.0)
    zurich = psychro.humidity_ratio(22.0, 50.0, 96500.0)
    assert zurich > sea
    assert zurich / sea == pytest.approx(101325.0 / 96500.0, rel=0.01)


def test_vectorised_and_scalar_agree():
    temps = np.array([-10.0, 0.0, 20.0, 35.0])
    vector = psychro.humidity_ratio(temps, 55.0)
    scalar = [psychro.humidity_ratio(float(t), 55.0) for t in temps]
    assert np.allclose(vector, scalar)


def test_against_psychrolib_if_installed():
    psychrolib = pytest.importorskip("psychrolib")
    psychrolib.SetUnitSystem(psychrolib.SI)
    for t in (-8.0, 4.0, 21.0, 33.0):
        for rh in (0.25, 0.60, 0.95):
            theirs = psychrolib.GetHumRatioFromRelHum(t, rh, 101325.0)
            ours = psychro.humidity_ratio(t, rh * 100.0, 101325.0)
            assert ours == pytest.approx(theirs, rel=1e-3)
