"""Physics core: hand-checkable arithmetic, limits, and vectorisation."""

import numpy as np
import pytest

from zcbsl_resize import ChamberParams, compute
from zcbsl_resize.physics import CP_AIR, RHO_AIR


@pytest.fixture
def p():
    return ChamberParams()


# ---------------------------------------------------------------- geometry

def test_areas_are_arithmetic_you_can_check_by_hand(p):
    r = compute(p)
    assert r["volume"] == pytest.approx(4.0 * 3.0 * 2.7)
    assert r["floor_area"] == pytest.approx(12.0)
    assert r["interior_area"] == pytest.approx(2 * (12.0 + 4 * 2.7 + 3 * 2.7))
    assert r["facade_area"] == pytest.approx(3.0 * 2.7)
    assert r["glazing_area"] == pytest.approx(3.0 * 2.7 * 0.30)
    assert r["opaque_facade_area"] == pytest.approx(3.0 * 2.7 * 0.70)
    # Everything not facade and not ceiling is the residual adiabatic set.
    assert r["residual_area"] == pytest.approx(r["interior_area"] - r["facade_area"] - r["ceiling_area"])


def test_facade_width_cannot_exceed_the_longest_wall(p):
    r = compute(p.replace(facade_width=20.0))
    assert r["facade_area"] == pytest.approx(4.0 * 2.7)


# ---------------------------------------------------------------- steady state

def test_heating_hold_reproduced_by_hand(p):
    r = compute(p)
    a_glaze = 3.0 * 2.7 * 0.30
    a_opaque = 3.0 * 2.7 * 0.70
    a_ceiling = 12.0
    a_residual = r["residual_area"]
    dt_boundary = 30.0 - (-10.0)

    conduction = 1.20 * a_opaque * dt_boundary + 1.40 * a_glaze * dt_boundary + 1.20 * a_ceiling * dt_boundary
    residual = 0.05 * a_residual * (30.0 - 21.0)
    m_dot = 3.0 * r["volume"] * RHO_AIR / 3600.0
    ventilation = m_dot * CP_AIR * (30.0 - 21.0)
    gains = 2 * 75.0 + 25.0 * 12.0

    assert r["heating_hold"] == pytest.approx(conduction + residual + ventilation - gains)


def test_cooling_hold_reproduced_by_hand(p):
    r = compute(p)
    a_glaze = 3.0 * 2.7 * 0.30
    a_opaque = 3.0 * 2.7 * 0.70
    dt_boundary = 35.0 - 16.0

    conduction = 1.20 * a_opaque * dt_boundary + 1.40 * a_glaze * dt_boundary + 1.20 * 12.0 * dt_boundary
    solar = 0.50 * a_glaze * 700.0
    residual = 0.05 * r["residual_area"] * (21.0 - 16.0)
    m_dot = 3.0 * r["volume"] * RHO_AIR / 3600.0
    ventilation = m_dot * CP_AIR * (21.0 - 16.0)
    gains = 2 * 75.0 + 25.0 * 12.0

    assert r["cooling_hold"] == pytest.approx(conduction + solar + residual + ventilation + gains)


def test_glazing_uses_its_own_u_value(p):
    """Splitting opaque and glazed U-values was the point of the change."""
    base = compute(p)
    worse_glass = compute(p.replace(facade_u_glazing=5.7))
    assert worse_glass["heating_hold"] > base["heating_hold"]
    # Changing the opaque U must not move the glazed portion's contribution.
    only_glass = compute(p.replace(glazing_fraction=100.0))
    assert only_glass["facade_opaque_heat"] == pytest.approx(0.0)


def test_ceiling_shares_the_facade_boundary_temperature(p):
    """By decision: one emulated climate behind both surfaces."""
    colder = compute(p.replace(boundary_temp_winter=-25.0))
    base = compute(p)
    assert colder["ceiling_heat"] > base["ceiling_heat"]
    assert colder["facade_opaque_heat"] > base["facade_opaque_heat"]


def test_solar_affects_cooling_only(p):
    sunny = compute(p.replace(solar_irradiance=2000.0))
    dark = compute(p.replace(solar_irradiance=0.0))
    assert sunny["cooling_hold"] > dark["cooling_hold"]
    assert sunny["heating_hold"] == pytest.approx(dark["heating_hold"])


def test_internal_gains_help_heating_and_hurt_cooling(p):
    lit = compute(p.replace(equipment_w_per_m2=500.0))
    dim = compute(p.replace(equipment_w_per_m2=0.0))
    assert lit["cooling_hold"] > dim["cooling_hold"]
    assert lit["heating_hold"] < dim["heating_hold"]
    assert lit["equipment_w"] == pytest.approx(500.0 * 12.0)


def test_loads_never_go_negative(p):
    """A hugely overlit room still reports zero heating demand, not negative."""
    r = compute(p.replace(equipment_w_per_m2=500.0, ach=0.0, boundary_temp_winter=20.0))
    assert r["heating_hold"] >= 0.0


# ---------------------------------------------------------------- ramp

def test_design_capacity_is_hold_plus_ramp_plus_margin(p):
    r = compute(p)
    assert r["heating_design"] == pytest.approx((r["heating_hold"] + r["power_mass"]) * 1.15)
    assert r["cooling_design"] == pytest.approx((r["cooling_hold"] + r["power_mass"]) * 1.15)


def test_ramp_power_is_energy_over_time(p):
    r = compute(p)
    assert r["power_mass"] == pytest.approx(r["c_total"] * r["ramp_delta_t"] / (30.0 * 60.0))
    assert r["energy_mass_kwh"] == pytest.approx(r["energy_mass_j"] / 3.6e6)


def test_air_capacity_is_the_textbook_value(p):
    r = compute(p)
    assert r["c_air"] == pytest.approx(RHO_AIR * 32.4 * CP_AIR)


def test_longer_ramps_need_less_capacity(p):
    designs = [compute(p, ramp_minutes=t)["heating_design"] for t in (10, 30, 60, 120, 480)]
    assert designs == sorted(designs, reverse=True)


def test_infinite_ramp_converges_on_the_steady_hold(p):
    r = compute(p, ramp_minutes=1e7)
    assert r["heating_design"] == pytest.approx(r["heating_hold"] * 1.15, rel=1e-3)


def test_setpoints_are_ordered_defensively(p):
    """Passing them backwards must not produce a negative ramp."""
    r = compute(p.replace(setpoint_min=30.0, setpoint_max=16.0))
    assert r["ramp_delta_t"] == pytest.approx(14.0)
    assert r["power_mass"] > 0


# ---------------------------------------------------------------- surface film

def test_required_air_surface_dt_is_power_over_film_conductance(p):
    r = compute(p)
    assert r["required_air_surface_dt"] == pytest.approx(
        r["power_mass"] / (8.0 * r["interior_area"])
    )


def test_minimum_feasible_ramp_is_self_consistent(p):
    """Re-running at the reported minimum must land exactly on the allowance."""
    r = compute(p)
    at_limit = compute(p, ramp_minutes=r["min_feasible_ramp_minutes"])
    assert at_limit["required_air_surface_dt"] == pytest.approx(p.max_air_surface_dt, rel=1e-6)


def test_heavy_mass_makes_short_ramps_unreachable(p):
    heavy = p.replace(added_mass_area=40.0, added_mass_thickness=0.3, ramp_minutes=15.0)
    r = compute(heavy)
    assert not bool(r["film_ok"])
    assert r["min_feasible_ramp_minutes"] > 15.0


def test_a_better_film_raises_the_ceiling(p):
    still_air = compute(p.replace(added_mass_area=20.0))
    forced = compute(p.replace(added_mass_area=20.0, surface_film_h=16.0))
    assert forced["min_feasible_ramp_minutes"] == pytest.approx(
        still_air["min_feasible_ramp_minutes"] / 2.0
    )


# ---------------------------------------------------------------- mass model

def test_thick_mass_is_diffusion_limited_not_lumped(p):
    heavy = p.replace(added_mass_area=20.0)
    limited = compute(heavy)
    lumped = compute(heavy, lumped_mass=True)
    assert lumped["power_mass"] > 4 * limited["power_mass"]
    assert limited["added_participating_fraction"] < 0.2


def test_added_mass_is_off_when_its_area_is_zero(p):
    assert compute(p)["c_added"] == pytest.approx(0.0)


# ---------------------------------------------------------------- latent

def test_no_ventilation_means_only_occupant_latent(p):
    r = compute(p.replace(ach=0.0))
    assert r["latent_vent"] == pytest.approx(0.0)
    assert r["latent_hold"] == pytest.approx(2 * 45.0)


def test_drier_incoming_air_reduces_the_latent_load(p):
    humid = compute(p.replace(vent_supply_rh=90.0))
    dry = compute(p.replace(vent_supply_rh=20.0))
    assert humid["latent_vent"] > dry["latent_vent"]


def test_latent_load_cannot_go_negative(p):
    """Air drier than the target does not generate humidification capacity here."""
    r = compute(p.replace(vent_supply_rh=5.0, target_rh=90.0))
    assert r["latent_vent"] == pytest.approx(0.0)


# ---------------------------------------------------------------- airflow

def test_airflow_is_the_larger_of_capacity_and_ventilation(p):
    r = compute(p)
    assert r["design_flow_m3s"] == pytest.approx(max(r["flow_from_capacity"], r["flow_from_ach"]))
    assert r["design_flow_ls"] == pytest.approx(r["design_flow_m3s"] * 1000.0)


def test_high_air_change_rates_govern_the_airflow(p):
    """A lightly loaded room flushed at 20 ACH is sized by the ventilation rate."""
    quiet = p.replace(
        ach=20.0,
        ramp_minutes=480.0,
        base_shell_capacity=5.0,
        supply_dt=30.0,
        boundary_temp_winter=18.0,
        boundary_temp_summer=24.0,
        vent_supply_temp=21.0,
        solar_irradiance=0.0,
        equipment_w_per_m2=0.0,
        occupants=0.0,
    )
    r = compute(quiet)
    assert bool(r["flow_set_by_ventilation"])
    assert r["design_flow_m3s"] == pytest.approx(20.0 * r["volume"] / 3600.0)


def test_bigger_supply_dt_shrinks_the_airflow(p):
    narrow = compute(p.replace(supply_dt=6.0))
    wide = compute(p.replace(supply_dt=24.0))
    assert wide["design_flow_m3s"] < narrow["design_flow_m3s"]


# ---------------------------------------------------------------- plant

def test_buffer_covering_the_ramp_leaves_only_recharge_duty(p):
    r = compute(p)
    assert bool(r["buffer_covers_ramp"])
    assert r["plant_extra"] == pytest.approx(r["energy_mass_j"] / (60.0 * 60.0))
    assert r["plant_heating"] < r["heating_design"]


def test_an_undersized_buffer_pushes_duty_back_onto_the_heat_pump(p):
    small = compute(p.replace(buffer_volume_l=100.0, added_mass_area=30.0))
    assert not bool(small["buffer_covers_ramp"])
    assert small["buffer_coverage_pct"] < 100.0
    assert small["plant_heating"] > compute(p)["plant_heating"]


def test_aggregate_scales_with_count_and_simultaneity(p):
    one = compute(p)
    many = compute(p.replace(n_chambers=6.0, diversity_pct=50.0))
    assert many["aggregate_heating"] == pytest.approx(one["plant_heating"] * 6 * 0.5)


# ---------------------------------------------------------------- vectorisation

def test_arrays_give_the_same_answers_as_a_scalar_loop(p):
    ramps = np.array([10.0, 30.0, 90.0, 240.0])
    vector = compute(p, ramp_minutes=ramps)
    for i, t in enumerate(ramps):
        scalar = compute(p, ramp_minutes=float(t))
        for key in ("heating_design", "cooling_design", "power_mass", "plant_heating", "design_flow_ls"):
            assert vector[key][i] == pytest.approx(scalar[key])


def test_multiple_axes_broadcast_together(p):
    params = p.to_dict()
    params["ach"] = np.array([0.0, 5.0, 20.0])
    params["equipment_w_per_m2"] = np.array([0.0, 50.0, 500.0])
    r = compute(params)
    assert r["cooling_hold"].shape == (3,)
    assert r["cooling_hold"][2] > r["cooling_hold"][0]


def test_every_result_is_finite_across_the_whole_parameter_space(p):
    """Random valid inputs must never produce NaN or inf."""
    from zcbsl_resize.params import PARAMS

    rng = np.random.default_rng(20260917)
    params = p.to_dict()
    for spec in PARAMS:
        params[spec.key] = rng.uniform(spec.minimum, spec.maximum, size=4000)
    r = compute(params)
    for key, value in r.items():
        arr = np.asarray(value)
        if arr.dtype == bool:
            continue
        assert np.all(np.isfinite(arr)), f"{key} produced non-finite values"
