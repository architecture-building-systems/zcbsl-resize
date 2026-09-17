"""Psychrometrics, ASHRAE Fundamentals (2017) Chapter 1 formulation.

Implemented here rather than pulled in as a dependency so that the test suite
can check it against published table values *and* against ``psychrolib`` when
that happens to be installed.  Two independent checks beat one library import.

All functions are numpy-safe: pass scalars or arrays.
"""

from __future__ import annotations

import numpy as np

#: Ratio of the molecular masses of water vapour and dry air (ASHRAE eq. 20).
MW_RATIO = 0.621945

#: Standard sea-level atmospheric pressure, Pa.
P_ATM_SEA_LEVEL = 101325.0

#: Latent heat of vaporisation of water near room temperature, J/kg.
H_FG = 2.45e6

# ASHRAE (2017) eq. 5, saturation over ice, -100 to 0 degC
_ICE = (
    -5.6745359e3,
    6.3925247e0,
    -9.677843e-3,
    6.2215701e-7,
    2.0747825e-9,
    -9.484024e-13,
    4.1635019e0,
)

# ASHRAE (2017) eq. 6, saturation over liquid water, 0 to 200 degC
_WATER = (
    -5.8002206e3,
    1.3914993e0,
    -4.8640239e-2,
    4.1764768e-5,
    -1.4452093e-8,
    6.5459673e0,
)


def saturation_pressure(t_db_c):
    """Saturation vapour pressure of water in air, Pa, for dry-bulb temp in degC."""
    t = np.asarray(t_db_c, dtype=float)
    tk = t + 273.15

    c1, c2, c3, c4, c5, c6, c7 = _ICE
    ln_ice = c1 / tk + c2 + c3 * tk + c4 * tk**2 + c5 * tk**3 + c6 * tk**4 + c7 * np.log(tk)

    c8, c9, c10, c11, c12, c13 = _WATER
    ln_water = c8 / tk + c9 + c10 * tk + c11 * tk**2 + c12 * tk**3 + c13 * np.log(tk)

    result = np.exp(np.where(t < 0.0, ln_ice, ln_water))
    return result if result.ndim else float(result)


def humidity_ratio(t_db_c, rh_pct, pressure_pa=P_ATM_SEA_LEVEL):
    """Humidity ratio W, kg water per kg dry air, from dry-bulb temp and RH."""
    rh = np.clip(np.asarray(rh_pct, dtype=float) / 100.0, 0.0, 1.0)
    p_w = rh * np.asarray(saturation_pressure(t_db_c), dtype=float)
    p = np.asarray(pressure_pa, dtype=float)
    # Guard the superheated edge case where p_w would meet or exceed p.
    p_w = np.minimum(p_w, 0.999 * p)
    w = MW_RATIO * p_w / (p - p_w)
    return w if w.ndim else float(w)


def relative_humidity(t_db_c, w, pressure_pa=P_ATM_SEA_LEVEL):
    """Inverse of :func:`humidity_ratio`: RH in percent from W."""
    w_arr = np.asarray(w, dtype=float)
    p = np.asarray(pressure_pa, dtype=float)
    p_w = p * w_arr / (MW_RATIO + w_arr)
    rh = 100.0 * p_w / np.asarray(saturation_pressure(t_db_c), dtype=float)
    return rh if rh.ndim else float(rh)


def enthalpy(t_db_c, w):
    """Moist-air specific enthalpy, J per kg of dry air (ASHRAE eq. 30)."""
    t = np.asarray(t_db_c, dtype=float)
    w_arr = np.asarray(w, dtype=float)
    h = 1006.0 * t + w_arr * (2_501_000.0 + 1860.0 * t)
    return h if h.ndim else float(h)


def dew_point(t_db_c, rh_pct, pressure_pa=P_ATM_SEA_LEVEL):
    """Dew-point temperature in degC. Solved by bisection on saturation_pressure.

    Used for the radiant-cooling condensation check, where the surface
    temperature has to stay above this.
    """
    w = humidity_ratio(t_db_c, rh_pct, pressure_pa)
    p = np.asarray(pressure_pa, dtype=float)
    w_arr = np.asarray(w, dtype=float)
    p_w = np.maximum(p * w_arr / (MW_RATIO + w_arr), 1e-6)

    lo = np.full(np.shape(p_w), -90.0)
    hi = np.full(np.shape(p_w), 90.0)
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        too_low = np.asarray(saturation_pressure(mid), dtype=float) < p_w
        lo = np.where(too_low, mid, lo)
        hi = np.where(too_low, hi, mid)
    out = 0.5 * (lo + hi)
    return out if out.ndim else float(out)


def latent_load_w(mass_flow_kg_s, w_in, w_target):
    """Dehumidification power, W. Positive means moisture must be removed."""
    return np.maximum(np.asarray(mass_flow_kg_s, dtype=float) * (np.asarray(w_in, dtype=float) - np.asarray(w_target, dtype=float)), 0.0) * H_FG
