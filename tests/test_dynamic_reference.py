"""Independent time-stepped models, written without reference to physics.py.

The closed-form sizing equation says the peak power for a linear ramp is

    P_peak = C_total * dT / t_ramp + (steady-state load at the far setpoint)

where the steady-state load is evaluated in ramp conditions: nobody inside and
only ``ramp_equipment_pct`` of the equipment running.

This file rebuilds the chamber as a differential equation from the parameters
alone, integrates it, and checks that claim.  If the closed form were wrong,
these tests would fail.
"""

import numpy as np
import pytest

from zcbsl_resize import ChamberParams, compute, rooms
from zcbsl_resize.physics import CP_AIR, RHO_AIR
from zcbsl_resize.surfaces import SURFACES


# --------------------------------------------------------------------------
# The chamber, rebuilt from its parameters
# --------------------------------------------------------------------------

def surface_terms(p: ChamberParams, summer: bool = False):
    """[(conductance W/K, face temperature C)] for each of the six surfaces."""
    outdoor = p.boundary_temp_summer if summer else p.boundary_temp_winter
    terms = []
    for surface in SURFACES:
        area = float(surface.area(p.width, p.depth, p.height))
        wwr = getattr(p, f"{surface.key}_wwr") / 100.0
        glazed = area * wwr
        opaque = area - glazed
        ua = (
            getattr(p, f"{surface.key}_u_opaque") * opaque
            + getattr(p, f"{surface.key}_u_glazing") * glazed
        )
        exposure = getattr(p, f"{surface.key}_exposure")
        face = p.surrounding_temp + exposure * (outdoor - p.surrounding_temp)
        terms.append((ua, face))
    return terms


def envelope_loss(p: ChamberParams, temp, summer: bool = False) -> float:
    """Total conduction out of the room at air temperature ``temp``, W."""
    return sum(ua * (temp - face) for ua, face in surface_terms(p, summer))


def vent_conductance(p: ChamberParams) -> float:
    volume = p.width * p.depth * p.height
    return p.ach * volume * RHO_AIR / 3600.0 * CP_AIR


def internal_gains(p: ChamberParams) -> float:
    return p.occupants * p.sensible_per_person + p.equipment_w_per_m2 * p.width * p.depth


def ramp_gains(p: ChamberParams) -> float:
    """During a ramp nobody is inside and only the share of equipment left on runs."""
    return p.ramp_equipment_pct / 100.0 * p.equipment_w_per_m2 * p.width * p.depth


def total_loss(p: ChamberParams, temp) -> float:
    return envelope_loss(p, temp) + vent_conductance(p) * (temp - p.vent_supply_temp)


# --------------------------------------------------------------------------
# One-node model: validates the ramp equation itself
# --------------------------------------------------------------------------

def single_node_required_power(p: ChamberParams, c_total: float, steps: int = 20000):
    """Power needed at each instant to hold an exactly linear temperature ramp."""
    duration = p.ramp_minutes * 60.0
    rate = (p.setpoint_max - p.setpoint_min) / duration
    times = np.linspace(0.0, duration, steps + 1)
    temps = p.setpoint_min + rate * times
    loss = np.array([total_loss(p, float(t)) for t in temps])
    return times, c_total * rate + loss - ramp_gains(p)


def test_closed_form_peak_matches_the_integrated_model():
    p = ChamberParams()
    r = compute(p)
    _, power = single_node_required_power(p, float(r["c_total"]), steps=2000)
    assert power.max() == pytest.approx(r["heating_hold_ramp"] + r["power_mass"], rel=1e-4)
    assert power.max() * 1.15 == pytest.approx(r["heating_ramp"], rel=1e-4)


def test_the_sun_off_ramp_is_integrated_with_the_sun_off():
    """With nothing running during the ramp, the integrated peak rises by exactly the gains."""
    p = ChamberParams(ramp_equipment_pct=0.0)
    r = compute(p)
    _, power = single_node_required_power(p, float(r["c_total"]), steps=2000)
    assert power.max() == pytest.approx(r["heating_hold_ramp"] + r["power_mass"], rel=1e-4)


@pytest.mark.parametrize("ramp", [10.0, 30.0, 90.0, 240.0])
@pytest.mark.parametrize("mass_coverage", [0.0, 20.0])
def test_peak_matches_across_ramp_times_and_mass(ramp, mass_coverage):
    p = ChamberParams(ramp_minutes=ramp, added_mass_coverage=mass_coverage)
    r = compute(p)
    _, power = single_node_required_power(p, float(r["c_total"]), steps=2000)
    assert power.max() == pytest.approx(r["heating_hold_ramp"] + r["power_mass"], rel=1e-4)


@pytest.mark.parametrize("room", ["module_room", "climate_chamber"])
def test_peak_matches_for_the_real_rooms(room):
    """The rooms the study is actually about, with three exterior walls in one case."""
    p = rooms.get(room)
    r = compute(p)
    _, power = single_node_required_power(p, float(r["c_total"]), steps=2000)
    assert power.max() == pytest.approx(r["heating_hold_ramp"] + r["power_mass"], rel=1e-4)


def _integrate(p: ChamberParams, c_total: float, power: float, duration: float, dt: float = 0.5):
    """Forward-integrate the air temperature under constant input power."""
    temp = p.setpoint_min
    reached_at = None
    for step in range(int(duration / dt) + 1):
        temp += dt * (power + ramp_gains(p) - total_loss(p, temp)) / c_total
        if reached_at is None and temp >= p.setpoint_max:
            reached_at = step * dt
    return temp, reached_at


def test_applying_the_sized_capacity_actually_reaches_setpoint_in_time():
    """Constant power at the design figure must reach setpoint by the target time.

    The closed form sizes for the worst instant, so a constant feed at that
    level arrives at or before the deadline.
    """
    p = ChamberParams()
    r = compute(p)
    duration = p.ramp_minutes * 60.0
    _, reached_at = _integrate(p, float(r["c_total"]), float(r["heating_hold_ramp"] + r["power_mass"]), duration)
    assert reached_at is not None, "sized capacity failed to reach setpoint"
    assert reached_at <= duration * 1.001


def test_undersized_capacity_fails_to_reach_setpoint():
    """A control, so the test above cannot pass trivially."""
    p = ChamberParams()
    r = compute(p)
    duration = p.ramp_minutes * 60.0
    final, _ = _integrate(p, float(r["c_total"]), 0.5 * float(r["heating_hold_ramp"] + r["power_mass"]), duration)
    assert final < p.setpoint_max


def test_steady_state_of_the_integrated_model_matches_the_hold_figure():
    """Run to equilibrium at the hold power and confirm it settles on setpoint."""
    p = ChamberParams()
    r = compute(p)
    c_total = float(r["c_total"])
    power = float(r["heating_hold"])
    temp = p.setpoint_max
    for _ in range(200000):
        temp += 1.0 * (power + internal_gains(p) - total_loss(p, temp)) / c_total
    assert temp == pytest.approx(p.setpoint_max, abs=0.01)


def test_climate_chamber_steady_state_settles_on_setpoint():
    """Same check on the three-exterior-wall room, where the envelope is 2.4x
    what the old single-facade model assumed."""
    p = rooms.climate_chamber()
    r = compute(p)
    c_total = float(r["c_total"])
    temp = p.setpoint_max
    for _ in range(400000):
        temp += 1.0 * (float(r["heating_hold"]) + internal_gains(p) - total_loss(p, temp)) / c_total
    assert temp == pytest.approx(p.setpoint_max, abs=0.05)


# --------------------------------------------------------------------------
# Two-node model: validates the surface-film limit
# --------------------------------------------------------------------------

def two_node_ramp(p: ChamberParams, c_mass: float, duration_s: float, dt: float = 0.5):
    """Air node and mass node coupled by the surface film, air driven on a ramp.

    Returns the peak air-to-mass temperature difference over the ramp.
    """
    interior = sum(float(s.area(p.width, p.depth, p.height)) for s in SURFACES)
    film = p.surface_film_h * interior  # W/K
    rate = (p.setpoint_max - p.setpoint_min) / duration_s

    t_mass = p.setpoint_min
    peak_gap = 0.0
    for step in range(1, int(duration_s / dt) + 1):
        t_air = p.setpoint_min + rate * step * dt
        t_mass += dt * film * (t_air - t_mass) / c_mass
        peak_gap = max(peak_gap, t_air - t_mass)
    return peak_gap


def test_film_limit_agrees_with_the_two_node_model():
    """When the ramp is long compared with the mass time constant, the coupled
    model settles into exactly the air-to-surface gap the closed form reports."""
    p = ChamberParams(ramp_minutes=480.0)
    r = compute(p)
    interior = float(r["interior_area"])
    tau = float(r["c_shell"]) / (p.surface_film_h * interior)
    assert p.ramp_minutes * 60.0 > 10 * tau, "premise: ramp must outlast the mass time constant"

    gap = two_node_ramp(p, float(r["c_shell"]), p.ramp_minutes * 60.0)
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

    gap = two_node_ramp(p, float(r["c_shell"]), p.ramp_minutes * 60.0)
    assert gap < r["ramp_delta_t"] * 1.01
    assert gap < 0.2 * r["required_air_surface_dt"]


def test_a_larger_film_coefficient_closes_the_gap():
    p = ChamberParams(base_shell_capacity=200.0, ramp_minutes=60.0)
    r = compute(p)
    weak = two_node_ramp(p, float(r["c_shell"]), 3600.0)
    strong = two_node_ramp(p.replace(surface_film_h=20.0), float(r["c_shell"]), 3600.0)
    assert strong < weak
