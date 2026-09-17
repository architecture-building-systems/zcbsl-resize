"""Independent time-stepped models, written without reference to physics.py.

The closed-form sizing equation says the peak power for a linear ramp is

    P_peak = C_total * dT / t_ramp + (steady-state load at the far setpoint)

This file rebuilds the chamber as a differential equation, integrates it, and
checks that claim.  If the closed form were wrong, these tests would fail.
"""

import numpy as np
import pytest

from zcbsl_resize import ChamberParams, compute
from zcbsl_resize.physics import CP_AIR, RHO_AIR


def envelope_ua(p: ChamberParams) -> float:
    """Total conductance to the outside, W/K, rebuilt from the parameters."""
    facade_area = max(p.length, p.width) * p.height
    glazing_area = facade_area * p.wwr / 100.0
    opaque_area = facade_area - glazing_area
    ceiling_area = p.length * p.width
    return (
        p.facade_u_opaque * opaque_area
        + p.facade_u_glazing * glazing_area
        + p.ceiling_u * ceiling_area
    )


def residual_ua(p: ChamberParams) -> float:
    interior = 2.0 * (p.length * p.width + p.length * p.height + p.width * p.height)
    facade_area = max(p.length, p.width) * p.height
    residual_area = interior - facade_area - p.length * p.width
    return p.residual_u * residual_area


def vent_conductance(p: ChamberParams) -> float:
    volume = p.length * p.width * p.height
    return p.ach * volume * RHO_AIR / 3600.0 * CP_AIR


def internal_gains(p: ChamberParams) -> float:
    return p.occupants * p.sensible_per_person + p.equipment_w_per_m2 * p.length * p.width


# --------------------------------------------------------------------------
# One-node model: validates the ramp equation itself
# --------------------------------------------------------------------------

def single_node_required_power(p: ChamberParams, c_total: float, steps: int = 20000):
    """Power needed at each instant to hold an exactly linear temperature ramp."""
    duration = p.ramp_minutes * 60.0
    rate = (p.setpoint_max - p.setpoint_min) / duration
    times = np.linspace(0.0, duration, steps + 1)
    temps = p.setpoint_min + rate * times

    ua = envelope_ua(p)
    ua_res = residual_ua(p)
    ua_vent = vent_conductance(p)

    loss = (
        ua * (temps - p.boundary_temp_winter)
        + ua_res * (temps - p.surrounding_temp)
        + ua_vent * (temps - p.vent_supply_temp)
    )
    return times, c_total * rate + loss - internal_gains(p)


def test_closed_form_peak_matches_the_integrated_model():
    p = ChamberParams()
    r = compute(p)
    _, power = single_node_required_power(p, float(r["c_total"]))
    assert power.max() == pytest.approx(r["heating_hold"] + r["power_mass"], rel=1e-4)


@pytest.mark.parametrize("ramp", [10.0, 30.0, 90.0, 240.0])
@pytest.mark.parametrize("mass_area", [0.0, 20.0])
def test_peak_matches_across_ramp_times_and_mass(ramp, mass_area):
    p = ChamberParams(ramp_minutes=ramp, added_mass_area=mass_area)
    r = compute(p)
    _, power = single_node_required_power(p, float(r["c_total"]))
    assert power.max() == pytest.approx(r["heating_hold"] + r["power_mass"], rel=1e-4)


def test_applying_the_sized_capacity_actually_reaches_setpoint_in_time():
    """Forward-integrate with constant power at the design figure.

    Because the closed form sizes for the worst instant, constant power at that
    level must reach the setpoint at or before the target time.
    """
    p = ChamberParams()
    r = compute(p)
    c_total = float(r["c_total"])
    power = float(r["heating_hold"] + r["power_mass"])

    ua = envelope_ua(p) + residual_ua(p) + vent_conductance(p)
    duration = p.ramp_minutes * 60.0
    dt = 0.5
    temp = p.setpoint_min
    reached_at = None
    for step in range(int(duration / dt) + 1):
        driving = (
            envelope_ua(p) * (temp - p.boundary_temp_winter)
            + residual_ua(p) * (temp - p.surrounding_temp)
            + vent_conductance(p) * (temp - p.vent_supply_temp)
        )
        temp += dt * (power + internal_gains(p) - driving) / c_total
        if reached_at is None and temp >= p.setpoint_max:
            reached_at = step * dt
            break
    assert ua > 0
    assert reached_at is not None, "sized capacity failed to reach setpoint"
    assert reached_at <= duration * 1.001


def test_undersized_capacity_fails_to_reach_setpoint():
    """A control, so the test above cannot pass trivially."""
    p = ChamberParams()
    r = compute(p)
    c_total = float(r["c_total"])
    power = 0.5 * float(r["heating_hold"] + r["power_mass"])
    duration = p.ramp_minutes * 60.0
    dt = 0.5
    temp = p.setpoint_min
    for _ in range(int(duration / dt) + 1):
        driving = (
            envelope_ua(p) * (temp - p.boundary_temp_winter)
            + residual_ua(p) * (temp - p.surrounding_temp)
            + vent_conductance(p) * (temp - p.vent_supply_temp)
        )
        temp += dt * (power + internal_gains(p) - driving) / c_total
    assert temp < p.setpoint_max


def test_steady_state_of_the_integrated_model_matches_the_hold_figure():
    """Run to equilibrium at the design power and confirm it settles where the
    closed form says the hold load applies."""
    p = ChamberParams()
    r = compute(p)
    c_total = float(r["c_total"])
    power = float(r["heating_hold"])
    temp = p.setpoint_max
    dt = 1.0
    for _ in range(200000):
        driving = (
            envelope_ua(p) * (temp - p.boundary_temp_winter)
            + residual_ua(p) * (temp - p.surrounding_temp)
            + vent_conductance(p) * (temp - p.vent_supply_temp)
        )
        temp += dt * (power + internal_gains(p) - driving) / c_total
    assert temp == pytest.approx(p.setpoint_max, abs=0.01)


# --------------------------------------------------------------------------
# Two-node model: validates the surface-film limit
# --------------------------------------------------------------------------

def two_node_ramp(p: ChamberParams, c_air: float, c_mass: float, duration_s: float, dt: float = 0.5):
    """Air node and mass node coupled by the surface film, air driven on a ramp.

    Returns the peak air-to-mass temperature difference over the ramp.
    """
    interior = 2.0 * (p.length * p.width + p.length * p.height + p.width * p.height)
    film = p.surface_film_h * interior  # W/K
    rate = (p.setpoint_max - p.setpoint_min) / duration_s

    t_mass = p.setpoint_min
    peak_gap = 0.0
    steps = int(duration_s / dt)
    for step in range(1, steps + 1):
        t_air = p.setpoint_min + rate * step * dt
        t_mass += dt * film * (t_air - t_mass) / c_mass
        peak_gap = max(peak_gap, t_air - t_mass)
    return peak_gap


def test_film_limit_agrees_with_the_two_node_model():
    """When the ramp is long compared with the mass time constant, the coupled
    model settles into exactly the air-to-surface gap the closed form reports."""
    p = ChamberParams(ramp_minutes=480.0)
    r = compute(p)
    interior = 2.0 * (p.length * p.width + p.length * p.height + p.width * p.height)
    tau = float(r["c_shell"]) / (p.surface_film_h * interior)
    assert p.ramp_minutes * 60.0 > 10 * tau, "premise: ramp must outlast the mass time constant"

    gap = two_node_ramp(p, float(r["c_air"]), float(r["c_shell"]), p.ramp_minutes * 60.0)
    assert gap == pytest.approx(r["required_air_surface_dt"], rel=0.10)


def test_short_ramps_leave_the_mass_behind_rather_than_charging_it():
    """The other regime, and the reason the film check exists.

    When the closed form asks for a bigger air-to-surface gap than the whole
    setpoint range, the mass cannot be dragged along at all: the air arrives and
    the mass stays cold.  The chamber hits its air setpoint while its radiant
    environment does not.
    """
    p = ChamberParams(base_shell_capacity=200.0, ramp_minutes=30.0)
    r = compute(p)
    assert r["required_air_surface_dt"] > r["ramp_delta_t"]
    assert not bool(r["film_ok"])

    gap = two_node_ramp(p, float(r["c_air"]), float(r["c_shell"]), p.ramp_minutes * 60.0)
    # The real gap saturates at the ramp size; the mass simply never follows.
    assert gap < r["ramp_delta_t"] * 1.01
    assert gap < 0.2 * r["required_air_surface_dt"]


def test_a_larger_film_coefficient_closes_the_gap():
    p = ChamberParams(base_shell_capacity=200.0, ramp_minutes=60.0)
    r = compute(p)
    weak = two_node_ramp(p, float(r["c_air"]), float(r["c_shell"]), 3600.0)
    strong = two_node_ramp(
        p.replace(surface_film_h=20.0), float(r["c_air"]), float(r["c_shell"]), 3600.0
    )
    assert strong < weak
