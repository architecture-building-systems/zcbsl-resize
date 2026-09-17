"""How much thermal mass actually participates in a ramp.

The frozen artifact credited every added mass layer with its full areal heat
capacity, as though a 300 mm rammed-earth wall reached a uniform temperature
within the ramp.  It does not.  Heat diffuses in from the surface, and in a
half-hour ramp it reaches a few centimetres.

For a semi-infinite solid whose surface temperature rises linearly at rate
``r`` from a uniform start, the exact solution is

    T(x, t) - T0 = 4 r t i^2 erfc( x / (2 sqrt(alpha t)) )

and integrating the stored energy over depth gives

    E(t) = (4 / (3 sqrt(pi))) rho_c r t sqrt(alpha t)

Comparing that with a layer of depth ``d`` raised uniformly by ``r t`` gives an
effective participating depth

    d_eff = (4 / (3 sqrt(pi))) sqrt(alpha t)  ~=  0.752 sqrt(alpha t)

capped at the layer's real thickness.

Note the direction of the approximation: this assumes the *surface* follows the
ramp perfectly, which requires infinite film conductance.  Real surfaces lag the
air, so less mass participates than this predicts.  The number here is therefore
an upper bound on participating mass, which is the conservative direction for
sizing.  ``finite_difference_stored_energy`` exists to quantify that gap, and
``tests/test_mass.py`` checks the two against each other.
"""

from __future__ import annotations

import numpy as np

#: 4 / (3 * sqrt(pi)) -- the ramp-response penetration coefficient derived above.
RAMP_DEPTH_COEFF = 4.0 / (3.0 * np.sqrt(np.pi))

#: 2 / sqrt(pi) -- the equivalent coefficient for a *step* change in surface
#: temperature, kept for reference.  A step reaches ~50% deeper than a ramp.
STEP_DEPTH_COEFF = 2.0 / np.sqrt(np.pi)


def diffusivity(rho_c_kj_m3k, k_w_mk):
    """Thermal diffusivity alpha = k / (rho c), m^2/s."""
    rho_c = np.asarray(rho_c_kj_m3k, dtype=float) * 1000.0  # kJ/m3K -> J/m3K
    return np.asarray(k_w_mk, dtype=float) / np.maximum(rho_c, 1e-9)


def penetration_depth(rho_c_kj_m3k, k_w_mk, duration_s, coeff=RAMP_DEPTH_COEFF):
    """Energy-equivalent participating depth, m, for a linear surface ramp."""
    alpha = diffusivity(rho_c_kj_m3k, k_w_mk)
    return coeff * np.sqrt(alpha * np.maximum(np.asarray(duration_s, dtype=float), 0.0))


def effective_areal_capacity(
    rho_c_kj_m3k,
    thickness_m,
    k_w_mk,
    duration_s,
    *,
    lumped=False,
):
    """Participating areal heat capacity, kJ/m^2K.

    With ``lumped=True`` the whole layer counts, reproducing the frozen
    artifact's behaviour for comparison.
    """
    rho_c = np.asarray(rho_c_kj_m3k, dtype=float)
    thickness = np.asarray(thickness_m, dtype=float)
    if lumped:
        return rho_c * thickness
    d_eff = np.minimum(penetration_depth(rho_c, k_w_mk, duration_s), thickness)
    return rho_c * d_eff


def participating_fraction(rho_c_kj_m3k, thickness_m, k_w_mk, duration_s):
    """Share of the layer that takes part, 0..1. Useful for the UI readout."""
    thickness = np.maximum(np.asarray(thickness_m, dtype=float), 1e-9)
    d_eff = np.minimum(penetration_depth(rho_c_kj_m3k, k_w_mk, duration_s), thickness)
    return d_eff / thickness


# --------------------------------------------------------------------------
# Independent numerical reference, used only by the tests
# --------------------------------------------------------------------------

def finite_difference_stored_energy(
    rho_c_kj_m3k: float,
    thickness_m: float,
    k_w_mk: float,
    duration_s: float,
    ramp_rate_k_s: float,
    *,
    film_h: float | None = None,
    nodes: int = 400,
    fourier_limit: float = 0.35,
) -> float:
    """Stored energy per unit area, J/m^2, from an explicit 1D solve.

    This deliberately shares no code with the analytical path above.  With
    ``film_h=None`` the surface temperature is driven directly (matching the
    analytical boundary condition).  With a finite ``film_h`` the surface is
    coupled to air that follows the ramp, which is the physically real case.
    """
    rho_c = float(rho_c_kj_m3k) * 1000.0
    alpha = float(k_w_mk) / rho_c
    dx = float(thickness_m) / nodes
    dt = fourier_limit * dx * dx / alpha
    steps = max(int(np.ceil(duration_s / dt)), 1)
    dt = duration_s / steps
    fo = alpha * dt / (dx * dx)

    temps = np.zeros(nodes + 1)  # node 0 at the exposed surface, node N insulated

    for step in range(1, steps + 1):
        t_now = step * dt
        driver = ramp_rate_k_s * t_now  # air (or surface) temperature rise
        new = temps.copy()

        if film_h is None:
            new[0] = driver
        else:
            # Surface node: half-cell energy balance with convection in.
            bi = film_h * dx / float(k_w_mk)
            new[0] = temps[0] + 2.0 * fo * (temps[1] - temps[0] + bi * (driver - temps[0]))

        new[1:-1] = temps[1:-1] + fo * (temps[2:] - 2.0 * temps[1:-1] + temps[:-2])
        # Back face insulated (mirror node).
        new[-1] = temps[-1] + 2.0 * fo * (temps[-2] - temps[-1])
        temps = new

    weights = np.full(nodes + 1, dx)
    weights[0] = weights[-1] = dx / 2.0
    return float(rho_c * np.sum(temps * weights))
