"""Physics core: hand-checkable arithmetic, limits, and vectorisation."""

import numpy as np
import pytest

from zcbsl_resize import ChamberParams, compute, fastest_ramp_minutes, mode_crossover_minutes
from zcbsl_resize.physics import CP_AIR, RHO_AIR, _fastest_ramp_iterated
from zcbsl_resize.surfaces import SURFACES


@pytest.fixture
def p():
    return ChamberParams()


# ---------------------------------------------------------------- geometry

def test_areas_are_arithmetic_you_can_check_by_hand(p):
    """Default room: 3.0 wide x 4.0 deep x 2.7 high."""
    r = compute(p)
    assert r["volume"] == pytest.approx(3.0 * 4.0 * 2.7)
    assert r["floor_area"] == pytest.approx(12.0)
    # North and south are width x height; east and west are depth x height.
    assert r["area_north"] == pytest.approx(3.0 * 2.7)
    assert r["area_south"] == pytest.approx(3.0 * 2.7)
    assert r["area_east"] == pytest.approx(4.0 * 2.7)
    assert r["area_west"] == pytest.approx(4.0 * 2.7)
    assert r["area_roof"] == pytest.approx(12.0)
    assert r["area_floor"] == pytest.approx(12.0)
    assert r["interior_area"] == pytest.approx(2 * (12.0 + 3.0 * 2.7 + 4.0 * 2.7))


def test_the_six_surfaces_account_for_the_whole_room():
    """No residual bucket left over: every square metre belongs to a surface."""
    r = compute(ChamberParams(width=8.0, depth=4.5, height=12.0))
    total = sum(r[f"area_{s.key}"] for s in SURFACES)
    assert total == pytest.approx(r["interior_area"])


def test_glazing_splits_each_surface_independently(p):
    """WWR is per surface, so glazing one wall does not glaze another."""
    r = compute(p.with_surface("east", wwr=50.0))
    assert r["glazed_area_east"] == pytest.approx(0.5 * 4.0 * 2.7)
    assert r["glazed_area_west"] == pytest.approx(0.0)
    assert r["glazed_area_south"] == pytest.approx(0.3 * 3.0 * 2.7)


# ---------------------------------------------------------------- steady state

def test_heating_hold_reproduced_by_hand(p):
    """Default: south wall and roof exterior, the rest facing the lab at 21 C."""
    r = compute(p)
    # conductance = U_opaque x opaque area + U_glazing x glazed area
    south = 1.20 * (8.1 * 0.7) + 1.40 * (8.1 * 0.3)
    roof = 1.20 * 12.0
    north, east, west, floor = 0.05 * 8.1, 0.05 * 10.8, 0.05 * 10.8, 0.05 * 12.0

    exposed = (south + roof) * (30.0 - (-10.0))          # facing the winter design condition
    interior = (north + east + west + floor) * (30.0 - 21.0)  # facing the lab
    m_dot = 3.0 * r["volume"] * RHO_AIR / 3600.0
    ventilation = m_dot * CP_AIR * (30.0 - 21.0)
    gains = 2 * 75.0 + 25.0 * 12.0

    assert r["envelope_heat"] == pytest.approx(exposed + interior)
    assert r["heating_hold"] == pytest.approx(exposed + interior + ventilation - gains)


def test_cooling_hold_reproduced_by_hand(p):
    r = compute(p)
    south = 1.20 * (8.1 * 0.7) + 1.40 * (8.1 * 0.3)
    roof = 1.20 * 12.0
    north, east, west, floor = 0.05 * 8.1, 0.05 * 10.8, 0.05 * 10.8, 0.05 * 12.0

    exposed = (south + roof) * (35.0 - 16.0)
    interior = (north + east + west + floor) * (21.0 - 16.0)
    solar = 0.50 * (8.1 * 0.3) * 700.0
    m_dot = 3.0 * r["volume"] * RHO_AIR / 3600.0
    ventilation = m_dot * CP_AIR * (21.0 - 16.0)
    gains = 2 * 75.0 + 25.0 * 12.0

    assert r["solar_gain"] == pytest.approx(solar)
    assert r["cooling_hold"] == pytest.approx(exposed + interior + solar + ventilation + gains)


def test_envelope_conductance_is_the_sum_of_the_surfaces(p):
    r = compute(p)
    assert r["envelope_conductance"] == pytest.approx(
        sum(r[f"conductance_{s.key}"] for s in SURFACES)
    )


# ---------------------------------------------------------------- exposure

def test_exposure_blends_between_the_lab_and_outdoors(p):
    """exposure = 0.5 puts the surface exactly halfway between the two."""
    cold = compute(p.with_surface("north", u_opaque=1.0, exposure=1.0))["heat_north"]
    warm = compute(p.with_surface("north", u_opaque=1.0, exposure=0.0))["heat_north"]
    half = compute(p.with_surface("north", u_opaque=1.0, exposure=0.5))["heat_north"]
    assert half == pytest.approx(0.5 * (cold + warm))


def test_zero_conductance_makes_a_surface_adiabatic(p):
    r = compute(p.with_surface("floor", u_opaque=0.0, u_glazing=0.0))
    assert r["conductance_floor"] == pytest.approx(0.0)
    assert r["heat_floor"] == pytest.approx(0.0)
    assert r["cool_floor"] == pytest.approx(0.0)


def test_three_exterior_walls_are_not_treated_as_adiabatic():
    """The climate chamber case. The old one-facade model called 204 m2 of
    exterior wall adiabatic and understated the envelope by 2.4x."""
    from zcbsl_resize import rooms

    chamber = rooms.climate_chamber()
    r = compute(chamber)
    for wall in ("north", "east", "west"):
        assert getattr(chamber, f"{wall}_exposure") == 1.0
        assert r[f"conductance_{wall}"] > 50.0
    assert chamber.south_exposure == 0.0
    assert chamber.floor_exposure == 0.0
    # Envelope conductance must reflect all three exposed walls plus the roof.
    assert r["envelope_conductance"] > 290.0


def test_module_room_facade_is_the_south_wall_not_the_longest():
    """3.75 wide x 4.50 deep: the facade is the 3.75 m wall, not the 4.50 m one."""
    from zcbsl_resize import rooms

    r = compute(rooms.module_room())
    assert r["area_south"] == pytest.approx(3.75 * 5.20)
    assert r["area_east"] == pytest.approx(4.50 * 5.20)
    # The exterior one is the south wall.
    assert r["conductance_south"] > r["conductance_east"]


# ---------------------------------------------------------------- gains & solar

def test_solar_is_per_surface_and_affects_cooling_only(p):
    sunny = compute(p.with_surface("south", irradiance=2000.0))
    dark = compute(p.with_surface("south", irradiance=0.0))
    assert sunny["cooling_hold"] > dark["cooling_hold"]
    assert sunny["heating_hold"] == pytest.approx(dark["heating_hold"])
    assert dark["solar_gain"] == pytest.approx(0.0)


def test_solar_needs_glazing_to_enter(p):
    """An opaque wall gains nothing: there is no sol-air correction, by decision."""
    r = compute(p.with_surface("east", irradiance=1500.0, wwr=0.0))
    assert r["solar_east"] == pytest.approx(0.0)


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

def test_each_mode_carries_its_own_margin(p):
    r = compute(p)
    assert r["heating_operating"] == pytest.approx(r["heating_hold"] * 1.15)
    assert r["cooling_operating"] == pytest.approx(r["cooling_hold"] * 1.15)
    assert r["heating_ramp"] == pytest.approx((r["heating_hold_ramp"] + r["power_mass"]) * 1.15)
    assert r["cooling_ramp"] == pytest.approx((r["cooling_hold_ramp"] + r["power_mass"]) * 1.15)


@pytest.mark.parametrize("ramp", [5.0, 30.0, 480.0, 1e6])
def test_design_is_the_larger_mode_never_the_sum(p, ramp):
    """A room holds an experiment or ramps between two; it never does both."""
    r = compute(p, ramp_minutes=ramp)
    for duty in ("heating", "cooling"):
        op, rp = r[f"{duty}_operating"], r[f"{duty}_ramp"]
        assert r[f"{duty}_design"] == pytest.approx(max(op, rp))
        assert bool(r[f"{duty}_set_by_ramp"]) == (rp > op)
        if min(op, rp) > 0:
            assert r[f"{duty}_design"] < op + rp


def test_the_ramp_hold_has_nobody_inside_and_the_sun_off(p):
    """Same boundary as the operating hold, minus the gains that are off."""
    dark = compute(p.replace(ramp_equipment_pct=0.0))
    gains = dark["internal_sensible"]
    assert dark["ramp_internal_sensible"] == pytest.approx(0.0)
    assert dark["heating_hold_ramp"] == pytest.approx(dark["heating_hold"] + gains)
    assert dark["cooling_hold_ramp"] == pytest.approx(dark["cooling_hold"] - gains)

    # Equipment left on still counts; occupants never do.
    lit = compute(p.replace(ramp_equipment_pct=100.0))
    assert lit["ramp_internal_sensible"] == pytest.approx(lit["equipment_w"])
    people = p.occupants * p.sensible_per_person
    assert lit["cooling_hold_ramp"] == pytest.approx(lit["cooling_hold"] - people)


def test_the_ramp_sees_the_same_extreme_boundary(p):
    """Only the gains change between modes: a hotter summer moves both."""
    mild = compute(p.replace(boundary_temp_summer=30.0))
    hot = compute(p.replace(boundary_temp_summer=45.0))
    delta_op = hot["cooling_hold"] - mild["cooling_hold"]
    delta_ramp = hot["cooling_hold_ramp"] - mild["cooling_hold_ramp"]
    assert delta_op > 0
    assert delta_ramp == pytest.approx(delta_op)


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


def test_infinite_ramp_converges_on_the_larger_steady_hold(p):
    r = compute(p, ramp_minutes=1e7)
    expected = max(r["heating_hold"], r["heating_hold_ramp"]) * 1.15
    assert r["heating_design"] == pytest.approx(expected, rel=1e-3)


def test_crossover_is_where_the_modes_swap(p):
    """Past the crossover the operating mode sets the size; just before it the ramp does."""
    # A well-lit room whose lights go off for the ramp: the hold drops by the
    # lighting, so a long enough ramp hands the size back to the operating mode.
    cool = p.replace(ramp_equipment_pct=0.0, equipment_w_per_m2=100.0)
    t = mode_crossover_minutes(cool, "cooling")
    assert t is not None and t > 1.0
    after = compute(cool, ramp_minutes=t)
    before = compute(cool, ramp_minutes=t - 1.0)
    assert after["cooling_ramp"] <= after["cooling_operating"]
    assert before["cooling_ramp"] > before["cooling_operating"]


def test_no_crossover_when_the_ramp_hold_alone_is_bigger(p):
    """Heating with the Sun off during ramps: the ramp governs at any ramp time."""
    r = compute(p.replace(ramp_equipment_pct=0.0))
    assert r["heating_hold_ramp"] > r["heating_hold"]
    assert mode_crossover_minutes(p.replace(ramp_equipment_pct=0.0), "heating") is None


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
    heavy = p.replace(added_mass_coverage=40.0, added_mass_thickness=0.3, ramp_minutes=15.0)
    r = compute(heavy)
    assert not bool(r["film_ok"])
    assert r["min_feasible_ramp_minutes"] > 15.0


def test_a_better_film_raises_the_ceiling(p):
    still_air = compute(p.replace(added_mass_coverage=20.0))
    forced = compute(p.replace(added_mass_coverage=20.0, surface_film_h=16.0))
    assert forced["min_feasible_ramp_minutes"] == pytest.approx(
        still_air["min_feasible_ramp_minutes"] / 2.0
    )


# ---------------------------------------------------------------- mass model

def test_thick_mass_is_diffusion_limited_not_lumped(p):
    heavy = p.replace(added_mass_coverage=20.0)
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


def test_airflow_splits_by_mode(p):
    r = compute(p)
    ach = r["flow_from_ach"]
    op = max(r["flow_heating_operating"], r["flow_cooling_operating"], ach)
    rp = max(r["flow_heating_ramp"], r["flow_cooling_ramp"], ach)
    assert r["flow_operating_ls"] == pytest.approx(op * 1000.0)
    assert r["flow_ramp_ls"] == pytest.approx(rp * 1000.0)
    assert r["design_flow_m3s"] == pytest.approx(max(op, rp))


def test_airflow_is_sized_on_the_air_side_only(p):
    r = compute(p)
    per_m3s = RHO_AIR * CP_AIR * p.supply_dt
    assert r["flow_cooling_ramp"] == pytest.approx(r["air_cooling_ramp"] / per_m3s)
    assert r["flow_heating_operating"] == pytest.approx(r["air_heating_operating"] / per_m3s)


# ---------------------------------------------------------------- radiant

def test_radiant_panels_fill_first_and_the_air_carries_the_rest(p):
    r = compute(p)
    area = (r["area_floor"] + r["area_roof"]) * p.radiant_fraction / 100.0
    assert r["radiant_area_actual"] == pytest.approx(area)
    cap = p.radiant_cool_limit * area
    for mode in ("operating", "ramp"):
        load = r[f"cooling_{mode}"]
        assert r[f"radiant_cooling_{mode}"] == pytest.approx(min(load, cap))
        assert r[f"radiant_cooling_{mode}"] + r[f"air_cooling_{mode}"] == pytest.approx(load)


def test_radiant_helps_the_ramp_too(p):
    """Panels are not reserved for the hold: they cut the ramp's air side as well."""
    bare = compute(p.replace(radiant_fraction=0.0))
    panels = compute(p.replace(radiant_fraction=50.0))
    assert bare["air_cooling_ramp"] == pytest.approx(bare["cooling_ramp"])
    assert panels["air_cooling_ramp"] < bare["air_cooling_ramp"]
    assert panels["flow_ramp_ls"] < bare["flow_ramp_ls"]
    # The room total does not care which emitter delivers it.
    assert panels["cooling_design"] == pytest.approx(bare["cooling_design"])


def test_radiant_panels_do_not_move_the_film_limit(p):
    """Hung panels charge no mass directly, so the speed limit is unchanged."""
    bare = compute(p.replace(radiant_fraction=0.0, added_mass_coverage=20.0))
    panels = compute(p.replace(radiant_fraction=100.0, added_mass_coverage=20.0))
    assert panels["required_air_surface_dt"] == pytest.approx(bare["required_air_surface_dt"])


def test_high_air_change_rates_govern_the_airflow(p):
    """A lightly loaded room flushed at 20 ACH is sized by the ventilation rate."""
    quiet = p.replace(
        ach=20.0,
        ramp_minutes=480.0,
        base_shell_capacity=1.0,
        supply_dt=30.0,
        boundary_temp_winter=18.0,
        boundary_temp_summer=24.0,
        vent_supply_temp=21.0,
        equipment_w_per_m2=0.0,
        occupants=0.0,
    ).with_surface("south", irradiance=0.0)
    r = compute(quiet)
    assert bool(r["flow_set_by_ventilation"])
    assert r["design_flow_m3s"] == pytest.approx(20.0 * r["volume"] / 3600.0)


def test_bigger_supply_dt_shrinks_the_airflow(p):
    narrow = compute(p.replace(supply_dt=6.0))
    wide = compute(p.replace(supply_dt=24.0))
    assert wide["design_flow_m3s"] < narrow["design_flow_m3s"]


# ---------------------------------------------------------------- heat pump

def test_tanks_off_draws_on_outdoor_air(p):
    on = compute(p)
    off = compute(p.replace(tank_enabled=0.0))
    assert float(off["source_temp_heating"]) == pytest.approx(p.boundary_temp_winter)
    assert float(off["sink_temp_cooling"]) == pytest.approx(p.boundary_temp_summer)
    assert off["lift_cooling"] == pytest.approx(
        (p.boundary_temp_summer + p.outdoor_coil_approach)
        - (p.setpoint_min - p.supply_dt - p.exchanger_approach)
    )
    assert off["cop_cooling"] < on["cop_cooling"]
    assert off["cop_heating"] < on["cop_heating"]
    assert not bool(off["free_cooling"])
    # The tanks see nothing; the outdoor air sees it all.
    assert off["tank_reject_cooling"] == pytest.approx(0.0)
    assert off["tank_extract_heating"] == pytest.approx(0.0)
    assert off["source_reject_cooling"] == pytest.approx(off["hp_cooling"] + off["electric_cooling"])
    # Thermal capacity is the room's, not the plant's: switching sources moves none of it.
    assert off["cooling_design"] == pytest.approx(on["cooling_design"])


def test_the_outdoor_approach_only_matters_with_the_tanks_off(p):
    a = compute(p.replace(outdoor_coil_approach=4.0))
    b = compute(p.replace(outdoor_coil_approach=16.0))
    assert a["cop_cooling"] == pytest.approx(b["cop_cooling"])
    a_off = compute(p.replace(tank_enabled=0.0, outdoor_coil_approach=4.0))
    b_off = compute(p.replace(tank_enabled=0.0, outdoor_coil_approach=16.0))
    assert a_off["cop_cooling"] > b_off["cop_cooling"]


def test_electric_and_source_split_by_mode_in_proportion(p):
    r = compute(p)
    for duty, sign in (("heating", -1.0), ("cooling", 1.0)):
        verb = "extract" if duty == "heating" else "reject"
        for mode in ("operating", "ramp"):
            q = r[f"{duty}_{mode}"]
            e = r[f"electric_{duty}_{mode}"]
            assert e == pytest.approx(q / r[f"cop_{duty}"])
            assert r[f"source_{verb}_{duty}_{mode}"] == pytest.approx(q + sign * e)
        assert r[f"electric_{duty}"] == pytest.approx(
            max(r[f"electric_{duty}_operating"], r[f"electric_{duty}_ramp"])
        )


def test_the_room_machine_carries_the_full_design_capacity(p):
    """The tanks are a source, not a buffer, so nothing absorbs the ramp surge."""
    r = compute(p)
    assert r["hp_heating"] == pytest.approx(r["heating_design"])
    assert r["hp_cooling"] == pytest.approx(r["cooling_design"])


def test_lift_is_measured_from_the_tank_to_the_supply_temperature(p):
    r = compute(p)
    assert r["supply_temp_heating"] == pytest.approx(p.setpoint_max + p.supply_dt)
    assert r["supply_temp_cooling"] == pytest.approx(p.setpoint_min - p.supply_dt)
    # The approach is paid at both ends.
    assert r["lift_heating"] == pytest.approx(
        (p.setpoint_max + p.supply_dt + p.exchanger_approach)
        - (p.tank_temp_hot - p.exchanger_approach)
    )
    assert r["lift_cooling"] == pytest.approx(
        (p.tank_temp_cold + p.exchanger_approach)
        - (p.setpoint_min - p.supply_dt - p.exchanger_approach)
    )


def test_cop_is_carnot_times_the_efficiency_factor(p):
    r = compute(p)
    sink_k = p.setpoint_max + p.supply_dt + p.exchanger_approach + 273.15
    assert r["cop_heating"] == pytest.approx(p.carnot_efficiency * sink_k / r["lift_heating"])
    assert r["cop_heating"] > 1.0


def test_a_smaller_lift_gives_a_better_cop(p):
    warm_tank = compute(p.replace(tank_temp_hot=40.0))
    cold_tank = compute(p.replace(tank_temp_hot=15.0))
    assert warm_tank["cop_heating"] > cold_tank["cop_heating"]
    assert warm_tank["electric_heating"] < cold_tank["electric_heating"]


def test_electrical_input_is_thermal_over_cop(p):
    r = compute(p)
    assert r["electric_heating"] == pytest.approx(r["hp_heating"] / r["cop_heating"])
    assert r["electric_cooling"] == pytest.approx(r["hp_cooling"] / r["cop_cooling"])


def test_what_the_tanks_see_obeys_an_energy_balance(p):
    """Heating takes thermal minus the compressor work out of the hot tank;
    cooling pushes thermal plus the work into the cold one."""
    r = compute(p)
    assert r["tank_extract_heating"] == pytest.approx(r["hp_heating"] - r["electric_heating"])
    assert r["tank_reject_cooling"] == pytest.approx(r["hp_cooling"] + r["electric_cooling"])
    assert r["tank_reject_cooling"] > r["hp_cooling"]


def test_free_cooling_when_the_cold_tank_is_already_cold_enough(p):
    """A narrow supply dT lets the 10 C tank serve the coil directly."""
    direct = compute(p.replace(setpoint_min=20.0, supply_dt=5.0, tank_temp_cold=10.0))
    assert bool(direct["free_cooling"])
    assert direct["electric_cooling"] == pytest.approx(0.0)


def test_no_free_cooling_at_a_wide_supply_dt(p):
    """16 C setpoint with a 12 K supply dT wants 4 C air; a 10 C tank cannot."""
    r = compute(p)
    assert not bool(r["free_cooling"])
    assert r["electric_cooling"] > 0.0


def test_free_heating_when_the_hot_tank_is_already_hot_enough(p):
    direct = compute(p.replace(setpoint_max=20.0, supply_dt=5.0, tank_temp_hot=30.0))
    assert bool(direct["free_heating"])
    assert direct["electric_heating"] == pytest.approx(0.0)


def test_buffer_and_fleet_outputs_are_gone(p):
    """The tanks are held at temperature by the network, so stored energy and
    the per-room recharge duty no longer mean anything."""
    r = compute(p)
    for dead in ("buffer_energy_j", "buffer_coverage_pct", "plant_extra",
                 "plant_heating", "aggregate_heating"):
        assert dead not in r


# ---------------------------------------------------------------- vectorisation

def test_arrays_give_the_same_answers_as_a_scalar_loop(p):
    ramps = np.array([10.0, 30.0, 90.0, 240.0])
    vector = compute(p, ramp_minutes=ramps)
    for i, t in enumerate(ramps):
        scalar = compute(p, ramp_minutes=float(t))
        for key in ("heating_design", "cooling_design", "power_mass", "electric_cooling", "design_flow_ls"):
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


# ------------------------------------------------- the self-consistent ramp

def test_reported_minimum_ramp_is_only_self_consistent_without_added_mass(p):
    """The trap this model sets, pinned so nobody walks into it twice.

    ``min_feasible_ramp_minutes`` is conditional on the ramp it was given.
    With no added mass the shell is thermally thin and the two coincide, which
    is why the older self-consistency test passes.  Add mass and re-running at
    the reported minimum overshoots the allowance, because the longer ramp let
    heat reach deeper and recruited capacity that was not in the first answer.
    """
    bare = compute(p)
    at_limit = compute(p, ramp_minutes=bare["min_feasible_ramp_minutes"])
    assert at_limit["required_air_surface_dt"] == pytest.approx(p.max_air_surface_dt, rel=1e-6)

    massive = p.replace(added_mass_coverage=60.0)
    first = compute(massive)
    second = compute(massive, ramp_minutes=first["min_feasible_ramp_minutes"])
    assert second["required_air_surface_dt"] > p.max_air_surface_dt
    assert second["min_feasible_ramp_minutes"] > first["min_feasible_ramp_minutes"]


def test_fastest_ramp_is_a_true_fixed_point(p):
    for area in (0.0, 15.0, 60.0, 150.0):
        params = p.replace(added_mass_coverage=area)
        t_star = float(np.atleast_1d(fastest_ramp_minutes(params))[0])
        at_star = compute(params, ramp_minutes=t_star)
        assert at_star["min_feasible_ramp_minutes"] == pytest.approx(t_star, rel=1e-9)
        assert at_star["required_air_surface_dt"] == pytest.approx(p.max_air_surface_dt, rel=1e-9)


def test_fastest_ramp_ignores_the_ramp_it_is_handed(p):
    """The input ramp drops out of the fixed point entirely."""
    massive = p.replace(added_mass_coverage=60.0)
    answers = [
        float(np.atleast_1d(fastest_ramp_minutes(massive.replace(ramp_minutes=t)))[0])
        for t in (1.0, 30.0, 480.0)
    ]
    assert answers[0] == pytest.approx(answers[1], rel=1e-12)
    assert answers[1] == pytest.approx(answers[2], rel=1e-12)


def test_fastest_ramp_closed_form_matches_repeated_substitution(p):
    """Two solvers, no shared algebra, across both diffusion regimes."""
    for thickness in (0.02, 0.30):          # thin saturates, thick does not
        for area in (0.0, 30.0, 120.0):
            params = p.replace(added_mass_coverage=area, added_mass_thickness=thickness)
            closed = float(np.atleast_1d(fastest_ramp_minutes(params))[0])
            iterated = float(np.atleast_1d(_fastest_ramp_iterated(params))[0])
            assert closed == pytest.approx(iterated, rel=1e-8), (thickness, area)


def test_fastest_ramp_picks_the_right_diffusion_branch(p):
    """A thin layer saturates, and then behaves as a lumped capacity."""
    thin = p.replace(added_mass_coverage=60.0, added_mass_thickness=0.01)
    assert fastest_ramp_minutes(thin) == pytest.approx(
        fastest_ramp_minutes(thin, lumped_mass=True), rel=1e-9
    )
    thick = p.replace(added_mass_coverage=60.0, added_mass_thickness=0.60)
    assert fastest_ramp_minutes(thick) < fastest_ramp_minutes(thick, lumped_mass=True)


def test_fastest_ramp_broadcasts(p):
    areas = np.array([0.0, 30.0, 60.0, 120.0])
    out = fastest_ramp_minutes(p.replace(added_mass_coverage=areas))
    assert out.shape == (4,)
    assert np.all(np.diff(out) > 0)


def test_fastest_ramp_is_size_independent_at_equal_coverage():
    """Both rooms, same fraction of interior surface lined, same speed limit.

    The area cancels out of capacity-over-film-conductance for the shell and
    for the lining alike.  Only the air term fails to cancel, which is why
    these agree to within a minute rather than exactly.
    """
    from zcbsl_resize import rooms

    for coverage in (0.0, 0.25, 0.50):
        answers = []
        for key in ("module_room", "climate_chamber"):
            room = rooms.get(key)
            answers.append(float(np.atleast_1d(
                fastest_ramp_minutes(room.replace(added_mass_coverage=coverage * 100.0))
            )[0]))
        assert abs(answers[0] - answers[1]) < 4.0, (coverage, answers)
