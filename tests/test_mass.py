"""The diffusion-limited mass model, checked against an independent 1D solve."""

import numpy as np
import pytest

from zcbsl_resize import mass

RAMMED_EARTH = dict(rho_c_kj_m3k=1800.0, k_w_mk=1.25)


def test_penetration_coefficient_is_the_analytical_value():
    assert mass.RAMP_DEPTH_COEFF == pytest.approx(4.0 / (3.0 * np.sqrt(np.pi)))


@pytest.mark.parametrize("duration_min", [10, 30, 60, 120, 480])
def test_analytical_energy_matches_finite_difference(duration_min):
    """Closed form vs. explicit 1D solve, thick enough to stay semi-infinite."""
    duration_s = duration_min * 60.0
    thickness = 2.0  # deep enough that the back face never sees the ramp
    ramp_rate = 14.0 / duration_s

    areal = mass.effective_areal_capacity(
        RAMMED_EARTH["rho_c_kj_m3k"], thickness, RAMMED_EARTH["k_w_mk"], duration_s
    )
    analytical = areal * 1000.0 * (ramp_rate * duration_s)  # J/m2

    numerical = mass.finite_difference_stored_energy(
        RAMMED_EARTH["rho_c_kj_m3k"], thickness, RAMMED_EARTH["k_w_mk"], duration_s, ramp_rate, nodes=800
    )
    assert analytical == pytest.approx(numerical, rel=0.01)


def test_thin_layers_fully_participate():
    """A 10 mm gypsum lining saturates well inside a 30-minute ramp."""
    fraction = mass.participating_fraction(810.0, 0.010, 0.25, 1800.0)
    assert fraction == pytest.approx(1.0)


def test_thick_rammed_earth_barely_participates():
    fraction = mass.participating_fraction(1800.0, 0.30, 1.25, 1800.0)
    assert 0.05 < fraction < 0.15
    depth_mm = mass.penetration_depth(1800.0, 1.25, 1800.0) * 1000.0
    assert 20.0 < depth_mm < 35.0


def test_participation_grows_with_the_square_root_of_time():
    shallow = mass.penetration_depth(1800.0, 1.25, 1800.0)
    deep = mass.penetration_depth(1800.0, 1.25, 4 * 1800.0)
    assert deep / shallow == pytest.approx(2.0, rel=1e-9)


def test_lumped_mode_reproduces_the_old_behaviour():
    lumped = mass.effective_areal_capacity(1800.0, 0.30, 1.25, 1800.0, lumped=True)
    assert lumped == pytest.approx(1800.0 * 0.30)
    diffusion_limited = mass.effective_areal_capacity(1800.0, 0.30, 1.25, 1800.0)
    assert lumped > 5 * diffusion_limited


def test_analytical_model_is_conservative_against_a_real_surface_film():
    """With a finite film the surface lags, so less mass charges than the closed
    form predicts. Sizing on the closed form therefore errs high, which is the
    safe direction."""
    duration_s, ramp_rate = 1800.0, 14.0 / 1800.0
    perfect = mass.finite_difference_stored_energy(1800.0, 0.30, 1.25, duration_s, ramp_rate)
    with_film = mass.finite_difference_stored_energy(
        1800.0, 0.30, 1.25, duration_s, ramp_rate, film_h=8.0
    )
    assert with_film < perfect


def test_step_response_penetrates_further_than_a_ramp():
    step = mass.penetration_depth(1800.0, 1.25, 1800.0, coeff=mass.STEP_DEPTH_COEFF)
    ramp = mass.penetration_depth(1800.0, 1.25, 1800.0)
    assert step > ramp
