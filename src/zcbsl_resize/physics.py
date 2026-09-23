"""Sizing calculations for an environmental test chamber.

Two problems get conflated under "the HVAC is undersized":

* **Ramping** between setpoints, which is a mass-charging problem.  The power
  needed scales with total heat capacity over the time allowed.
* **Holding** a setpoint during an experiment, which is a steady-state problem
  set by the envelope, the ventilation and the internal gains.

A third distinction matters once each room gets a dedicated heat pump: the hot
and cold tanks it draws on are held at temperature by the interface heat pump on
the anergy network, so they are an unlimited *source*, not a store.  Nothing
absorbs the ramp surge on its way to the room, which means the room's own
machine has to carry the full design capacity, not a buffer-relieved fraction
of it.  With the tanks switched off (``tank_enabled = 0``) the machine works
against outdoor air instead.

Design capacity is the larger of two modes, never their sum.  **Operating**
is the steady hold during an experiment.  **Ramp** is the mass-charging power
plus the hold at the far end of the ramp, evaluated in ramp conditions: the
same extreme boundary, but nobody inside and the Artificial Sun off.  Hung
radiant panels carry load up to their limit in both modes; the air system
carries the rest, and the supply airflow is sized on that remainder.

And a fourth, which the original workshop tool missed entirely: heat only
enters the thermal mass through a surface film of roughly 8 W/m^2K.  That puts
a hard ceiling on mass-charging power regardless of how large the coil is.  See
``required_air_surface_dt`` and ``min_feasible_ramp_minutes`` -- and note that the
latter is conditional on the ramp you asked for; :func:`fastest_ramp_minutes`
is the unconditional answer.

Everything here is numpy-safe.  Pass scalars for one case, or arrays for a
sweep of millions.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from . import mass as mass_mod
from . import psychro
from .params import ChamberParams
from .surfaces import SURFACES

#: Density of air, kg/m^3, at roughly 20 degC.
RHO_AIR = 1.2
#: Specific heat capacity of dry air, J/kgK.
CP_AIR = 1005.0
#: Specific heat capacity of water, J/kgK.
CP_WATER = 4186.0


def _as_dict(params: ChamberParams | dict[str, Any]) -> dict[str, Any]:
    if isinstance(params, ChamberParams):
        return params.to_dict()
    return dict(params)


def compute(
    params: ChamberParams | dict[str, Any],
    ramp_minutes: Any = None,
    *,
    lumped_mass: bool = False,
) -> dict[str, Any]:
    """Run the whole sizing calculation.

    Parameters
    ----------
    params:
        A :class:`~zcbsl_resize.params.ChamberParams` or a plain dict.  Any
        value may be a numpy array, in which case every result broadcasts.
    ramp_minutes:
        Override the ramp time without rebuilding the parameter set.  Used by
        the sensitivity sweep.
    lumped_mass:
        Credit every added mass layer with its full heat capacity, as the
        original workshop artifact did.  Physically wrong for thick layers;
        kept so the difference can be shown.
    """
    p = _as_dict(params)
    ramp_min = np.asarray(p["ramp_minutes"] if ramp_minutes is None else ramp_minutes, dtype=float)
    ramp_s = np.maximum(ramp_min, 1e-6) * 60.0

    # -- setpoints, ordered defensively ----------------------------------
    t_min = np.minimum(p["setpoint_min"], p["setpoint_max"])
    t_max = np.maximum(p["setpoint_min"], p["setpoint_max"])
    ramp_delta_t = t_max - t_min

    # -- geometry ---------------------------------------------------------
    width = np.maximum(p["width"], 0.1)
    depth = np.maximum(p["depth"], 0.1)
    height = np.maximum(p["height"], 0.1)

    volume = width * depth * height
    floor_area = width * depth

    surface_area = {s.key: s.area(width, depth, height) for s in SURFACES}
    interior_area = sum(surface_area.values())

    # -- thermal capacity -------------------------------------------------
    c_air = RHO_AIR * volume * CP_AIR
    c_shell = interior_area * np.asarray(p["base_shell_capacity"], dtype=float) * 1000.0

    added_area = np.maximum(p["added_mass_coverage"], 0.0) / 100.0 * interior_area  # added_mass_coverage is % of interior surface
    added_areal_capacity = mass_mod.effective_areal_capacity(
        p["added_mass_rho_c"], p["added_mass_thickness"], p["added_mass_k"], ramp_s,
        lumped=lumped_mass,
    )
    c_added = added_area * added_areal_capacity * 1000.0
    c_total = c_air + c_shell + c_added

    added_penetration_m = mass_mod.penetration_depth(p["added_mass_rho_c"], p["added_mass_k"], ramp_s)
    added_fraction = mass_mod.participating_fraction(
        p["added_mass_rho_c"], p["added_mass_thickness"], p["added_mass_k"], ramp_s
    )

    # -- ventilation ------------------------------------------------------
    m_dot_vent = np.asarray(p["ach"], dtype=float) * volume * RHO_AIR / 3600.0  # kg/s

    # -- internal gains ---------------------------------------------------
    equipment_w = np.asarray(p["equipment_w_per_m2"], dtype=float) * floor_area
    internal_sensible = np.asarray(p["occupants"], dtype=float) * p["sensible_per_person"] + equipment_w
    # During a ramp nobody is in the room and the Artificial Sun is off.  What
    # stays on is the share of equipment the room keeps running (computers,
    # small electronics): ramp_equipment_pct of it, and no occupants.
    ramp_internal_sensible = equipment_w * np.clip(
        np.asarray(p["ramp_equipment_pct"], dtype=float), 0.0, 100.0
    ) / 100.0

    # -- envelope, surface by surface -------------------------------------
    # Each surface faces a temperature blended by its exposure: 1 is outdoors,
    # 0 is the surrounding lab.  Heating is evaluated at the warm setpoint
    # against the winter condition and ignores solar (conservative); cooling at
    # the cold setpoint against summer, including solar through the glazing.
    t_surround = np.asarray(p["surrounding_temp"], dtype=float)
    t_winter = np.asarray(p["boundary_temp_winter"], dtype=float)
    t_summer = np.asarray(p["boundary_temp_summer"], dtype=float)

    envelope_heat = 0.0
    envelope_cool = 0.0
    solar_gain = 0.0
    envelope_conductance = 0.0
    glazed_area_total = 0.0
    per_surface: dict[str, Any] = {}

    for surface in SURFACES:
        area = surface_area[surface.key]
        exposure = np.clip(p[f"{surface.key}_exposure"], 0.0, 1.0)
        glazed = area * np.clip(p[f"{surface.key}_wwr"], 0.0, 100.0) / 100.0
        opaque = np.maximum(area - glazed, 0.0)
        conductance = (
            np.asarray(p[f"{surface.key}_u_opaque"], dtype=float) * opaque
            + np.asarray(p[f"{surface.key}_u_glazing"], dtype=float) * glazed
        )

        face_winter = t_surround + exposure * (t_winter - t_surround)
        face_summer = t_surround + exposure * (t_summer - t_surround)

        heat = conductance * (t_max - face_winter)
        solar = np.asarray(p[f"{surface.key}_shgc"], dtype=float) * glazed * p[f"{surface.key}_irradiance"]
        cool = conductance * (face_summer - t_min) + solar

        envelope_heat = envelope_heat + heat
        envelope_cool = envelope_cool + cool
        solar_gain = solar_gain + solar
        envelope_conductance = envelope_conductance + conductance
        glazed_area_total = glazed_area_total + glazed

        per_surface[f"area_{surface.key}"] = area
        per_surface[f"glazed_area_{surface.key}"] = glazed
        per_surface[f"conductance_{surface.key}"] = conductance
        per_surface[f"heat_{surface.key}"] = heat
        per_surface[f"cool_{surface.key}"] = cool
        per_surface[f"solar_{surface.key}"] = solar

    # -- operating mode: steady-state hold ------------------------------
    vent_sensible_heat = m_dot_vent * CP_AIR * (t_max - p["vent_supply_temp"])
    heating_hold = np.maximum(envelope_heat + vent_sensible_heat - internal_sensible, 0.0)

    vent_sensible_cool = m_dot_vent * CP_AIR * (p["vent_supply_temp"] - t_min)
    cooling_hold = np.maximum(envelope_cool + vent_sensible_cool + internal_sensible, 0.0)

    # -- ramp mode ----------------------------------------------------------
    # For a lumped capacity under a linear ramp, C dT/dt = P - UA(T - T_ext),
    # so the peak demand is the mass-charging term plus the steady load at the
    # far end of the ramp.  Exact for the lumped model; see tests.
    #
    # The far-end load is evaluated at the same extreme boundary as the
    # operating mode (the weather does not wait for the ramp to finish, and
    # real sun through glazing still counts), but with the room in ramp
    # conditions: nobody inside, the Artificial Sun off, and only
    # ramp_equipment_pct of the equipment running.
    heating_hold_ramp = np.maximum(envelope_heat + vent_sensible_heat - ramp_internal_sensible, 0.0)
    cooling_hold_ramp = np.maximum(envelope_cool + vent_sensible_cool + ramp_internal_sensible, 0.0)

    energy_mass = c_total * ramp_delta_t  # J
    power_mass = energy_mass / ramp_s  # W

    # -- design: the larger of the two modes, never their sum ---------------
    # A room is either holding an experiment or ramping between two; it is
    # never doing both.  The ramp column already carries the hold at its own
    # far end, so adding the operating hold on top would count it twice.
    margin_frac = np.asarray(p["margin_pct"], dtype=float) / 100.0
    heating_operating = heating_hold * (1.0 + margin_frac)
    cooling_operating = cooling_hold * (1.0 + margin_frac)
    heating_ramp = (heating_hold_ramp + power_mass) * (1.0 + margin_frac)
    cooling_ramp = (cooling_hold_ramp + power_mass) * (1.0 + margin_frac)

    heating_design = np.maximum(heating_operating, heating_ramp)
    cooling_design = np.maximum(cooling_operating, cooling_ramp)
    heating_set_by_ramp = heating_ramp > heating_operating
    cooling_set_by_ramp = cooling_ramp > cooling_operating

    # -- surface film limit on mass charging ------------------------------
    # Whatever the coil can produce, the heat still has to cross the air-to-
    # surface film.  This is usually what actually caps the ramp rate.
    exchange_area = interior_area
    film_conductance = np.asarray(p["surface_film_h"], dtype=float) * exchange_area  # W/K
    required_air_surface_dt = power_mass / np.maximum(film_conductance, 1e-9)
    max_mass_power = film_conductance * np.asarray(p["max_air_surface_dt"], dtype=float)
    film_ok = required_air_surface_dt <= p["max_air_surface_dt"]
    # Conditional on the ramp asked for: with added mass, a longer ramp lets
    # heat reach deeper, so this number moves as you chase it.  The
    # unconditional answer is fastest_ramp_minutes() below.
    min_feasible_ramp_s = energy_mass / np.maximum(max_mass_power, 1e-9)
    min_feasible_ramp_min = min_feasible_ramp_s / 60.0

    # -- latent -----------------------------------------------------------
    w_supply = psychro.humidity_ratio(p["vent_supply_temp"], p["vent_supply_rh"], p["pressure_pa"])
    # The chamber has to hold target RH across its whole setpoint range; the
    # cold end is the harder case, so size the coil against it.
    w_target = psychro.humidity_ratio(t_min, p["target_rh"], p["pressure_pa"])
    latent_vent = psychro.latent_load_w(m_dot_vent, w_supply, w_target)
    latent_occupants = np.asarray(p["occupants"], dtype=float) * p["latent_per_person"]
    latent_hold = latent_vent + latent_occupants
    latent_design = latent_hold * (1.0 + margin_frac)
    dew_point_c = psychro.dew_point(t_min, p["target_rh"], p["pressure_pa"])

    # -- radiant panels -------------------------------------------------
    # Hung ceiling panels.  They carry load up to their flux limit in both
    # modes -- holding and ramping -- and the air system carries the rest.
    # Hanging clear of the structure, they do not charge the mass directly, so
    # the surface-film limit above is unchanged by them.  radiant_fraction is
    # a share of floor + roof area, as it always has been.
    radiant_area_actual = np.maximum(
        (surface_area["floor"] + surface_area["roof"])
        * np.asarray(p["radiant_fraction"], dtype=float) / 100.0,
        0.0,
    )
    radiant_capacity_heat = np.asarray(p["radiant_heat_limit"], dtype=float) * radiant_area_actual
    radiant_capacity_cool = np.asarray(p["radiant_cool_limit"], dtype=float) * radiant_area_actual

    radiant_heating_operating = np.minimum(heating_operating, radiant_capacity_heat)
    radiant_heating_ramp = np.minimum(heating_ramp, radiant_capacity_heat)
    radiant_cooling_operating = np.minimum(cooling_operating, radiant_capacity_cool)
    radiant_cooling_ramp = np.minimum(cooling_ramp, radiant_capacity_cool)

    air_heating_operating = heating_operating - radiant_heating_operating
    air_heating_ramp = heating_ramp - radiant_heating_ramp
    air_cooling_operating = cooling_operating - radiant_cooling_operating
    air_cooling_ramp = cooling_ramp - radiant_cooling_ramp

    radiant_heating_design = np.maximum(radiant_heating_operating, radiant_heating_ramp)
    radiant_cooling_design = np.maximum(radiant_cooling_operating, radiant_cooling_ramp)
    air_heating_design = np.maximum(air_heating_operating, air_heating_ramp)
    air_cooling_design = np.maximum(air_cooling_operating, air_cooling_ramp)

    # Could the panels alone hold the operating load?  Flux of the unmargined
    # hold over the active area.  Floored so a zero area reads as "no".
    radiant_area = np.maximum(radiant_area_actual, 0.1)
    radiant_flux_heat = heating_hold / radiant_area
    radiant_flux_cool = cooling_hold / radiant_area
    radiant_heat_ok = radiant_flux_heat <= p["radiant_heat_limit"]
    radiant_cool_ok = radiant_flux_cool <= p["radiant_cool_limit"]
    air_steady_heating = np.maximum(heating_hold - radiant_capacity_heat, 0.0)
    air_steady_cooling = np.maximum(cooling_hold - radiant_capacity_cool, 0.0)

    # -- supply airflow ---------------------------------------------------
    # Sized on the air side only, mode by mode.  Ventilation runs in both
    # modes, so the air-change minimum floors each.
    rho_cp_dt = RHO_AIR * CP_AIR * np.maximum(p["supply_dt"], 1e-6)
    flow_heating_operating = air_heating_operating / rho_cp_dt
    flow_cooling_operating = air_cooling_operating / rho_cp_dt
    flow_heating_ramp = air_heating_ramp / rho_cp_dt
    flow_cooling_ramp = air_cooling_ramp / rho_cp_dt
    flow_from_ach = np.asarray(p["ach"], dtype=float) * volume / 3600.0

    flow_operating = np.maximum(np.maximum(flow_heating_operating, flow_cooling_operating), flow_from_ach)
    flow_ramp = np.maximum(np.maximum(flow_heating_ramp, flow_cooling_ramp), flow_from_ach)

    flow_from_heating = np.maximum(flow_heating_operating, flow_heating_ramp)
    flow_from_cooling = np.maximum(flow_cooling_operating, flow_cooling_ramp)
    flow_from_capacity = np.maximum(flow_from_heating, flow_from_cooling)
    design_flow = np.maximum(flow_from_capacity, flow_from_ach)
    flow_set_by_ventilation = flow_from_ach > flow_from_capacity
    flow_set_by_ramp = (~flow_set_by_ventilation) & (flow_ramp > flow_operating)

    # -- dedicated heat pump ----------------------------------------------
    # Each room has its own machine.  With the tanks on, it exchanges with the
    # hot and cold tanks, which the interface heat pump on the anergy network
    # holds at temperature: an unlimited source rather than a store, so
    # nothing absorbs the ramp surge and the machine carries the full design
    # capacity.  With the tanks off it works against outdoor air at the design
    # temperatures instead -- winter for heating, summer for cooling -- across
    # an outdoor coil with its own, larger approach.
    #
    # Heating lifts from the source up to the supply temperature; cooling
    # lifts from the supply temperature up to the sink.  If the cooling return
    # actually goes to the warm tank, set tank_temp_cold to the hot tank's
    # value and watch the cooling COP fall.
    tank_on = np.asarray(p["tank_enabled"], dtype=float) >= 0.5
    approach = np.asarray(p["exchanger_approach"], dtype=float)  # room side
    source_approach = np.where(tank_on, approach, np.asarray(p["outdoor_coil_approach"], dtype=float))
    source_temp_heating = np.where(tank_on, np.asarray(p["tank_temp_hot"], dtype=float), t_winter)
    sink_temp_cooling = np.where(tank_on, np.asarray(p["tank_temp_cold"], dtype=float), t_summer)
    eta = np.asarray(p["carnot_efficiency"], dtype=float)

    supply_temp_heating = t_max + np.asarray(p["supply_dt"], dtype=float)
    supply_temp_cooling = t_min - np.asarray(p["supply_dt"], dtype=float)

    # Free exchange: no compressor needed when the source is already past the
    # temperature the coil has to reach.
    free_heating = supply_temp_heating <= (source_temp_heating - source_approach)
    free_cooling = supply_temp_cooling >= (sink_temp_cooling + source_approach)

    # Lift across the compressor, with an approach paid at each end.
    lift_heating = np.maximum(
        (supply_temp_heating + approach) - (source_temp_heating - source_approach), 0.0
    )
    lift_cooling = np.maximum(
        (sink_temp_cooling + source_approach) - (supply_temp_cooling - approach), 0.0
    )

    # Carnot, times an efficiency factor. Guard the zero-lift limit.
    sink_k_heating = supply_temp_heating + approach + 273.15
    source_k_cooling = supply_temp_cooling - approach + 273.15
    cop_heating = eta * sink_k_heating / np.maximum(lift_heating, 0.5)
    cop_cooling = eta * source_k_cooling / np.maximum(lift_cooling, 0.5)

    # When a duty is free the compressor is not needed at all, so the COP
    # figure is meaningless; read free_heating / free_cooling alongside it.
    # The lift is clamped rather than divided by zero, so these stay finite and
    # a DataFrame of them stays plottable.
    #
    # The COP depends only on temperatures, not on the mode, so every electric
    # and source figure below splits by mode in exact proportion.
    def _electric_heating(q):
        return np.where(free_heating, 0.0, q / np.maximum(cop_heating, 1e-9))

    def _electric_cooling(q):
        return np.where(free_cooling, 0.0, q / np.maximum(cop_cooling, 1e-9))

    hp_heating = heating_design
    hp_cooling = cooling_design
    electric_heating = _electric_heating(hp_heating)
    electric_cooling = _electric_cooling(hp_cooling)
    electric_heating_operating = _electric_heating(heating_operating)
    electric_heating_ramp = _electric_heating(heating_ramp)
    electric_cooling_operating = _electric_cooling(cooling_operating)
    electric_cooling_ramp = _electric_cooling(cooling_ramp)

    # What the source sees: heating extracts thermal minus compressor work,
    # cooling rejects thermal plus compressor work.
    source_extract_heating = hp_heating - electric_heating
    source_reject_cooling = hp_cooling + electric_cooling
    source_extract_heating_operating = heating_operating - electric_heating_operating
    source_extract_heating_ramp = heating_ramp - electric_heating_ramp
    source_reject_cooling_operating = cooling_operating + electric_cooling_operating
    source_reject_cooling_ramp = cooling_ramp + electric_cooling_ramp

    # The tanks and the network only see it when the tanks are in use.
    tank_extract_heating = np.where(tank_on, source_extract_heating, 0.0)
    tank_reject_cooling = np.where(tank_on, source_reject_cooling, 0.0)

    return {
        # geometry
        "volume": volume,
        "floor_area": floor_area,
        "interior_area": interior_area,
        "added_mass_area": added_area,
        "glazed_area": glazed_area_total,
        "envelope_conductance": envelope_conductance,
        # capacity
        "c_air": c_air,
        "c_shell": c_shell,
        "c_added": c_added,
        "c_total": c_total,
        "added_areal_capacity": added_areal_capacity,
        "added_penetration_mm": added_penetration_m * 1000.0,
        "added_participating_fraction": added_fraction,
        # setpoints & ramp
        "setpoint_min": t_min,
        "setpoint_max": t_max,
        "ramp_delta_t": ramp_delta_t,
        "ramp_minutes": ramp_min,
        "energy_mass_j": energy_mass,
        "energy_mass_kwh": energy_mass / 3.6e6,
        "power_mass": power_mass,
        # steady state, operating mode
        "heating_hold": heating_hold,
        "cooling_hold": cooling_hold,
        # steady state at the far end of a ramp (Sun off, nobody in)
        "heating_hold_ramp": heating_hold_ramp,
        "cooling_hold_ramp": cooling_hold_ramp,
        "ramp_internal_sensible": ramp_internal_sensible,
        "envelope_heat": envelope_heat,
        "envelope_cool": envelope_cool,
        "vent_sensible_heat": vent_sensible_heat,
        "vent_sensible_cool": vent_sensible_cool,
        "solar_gain": solar_gain,
        **per_surface,
        "internal_sensible": internal_sensible,
        "equipment_w": equipment_w,
        # design: operating and ramp, each with margin, and the larger of the two
        "margin_frac": margin_frac,
        "heating_operating": heating_operating,
        "cooling_operating": cooling_operating,
        "heating_ramp": heating_ramp,
        "cooling_ramp": cooling_ramp,
        "heating_design": heating_design,
        "cooling_design": cooling_design,
        "heating_set_by_ramp": heating_set_by_ramp,
        "cooling_set_by_ramp": cooling_set_by_ramp,
        # film limit
        "exchange_area": exchange_area,
        "required_air_surface_dt": required_air_surface_dt,
        "max_mass_power": max_mass_power,
        "film_ok": film_ok,
        "min_feasible_ramp_minutes": min_feasible_ramp_min,
        # latent
        "w_supply": w_supply,
        "w_target": w_target,
        "latent_vent": latent_vent,
        "latent_occupants": latent_occupants,
        "latent_hold": latent_hold,
        "latent_design": latent_design,
        "dew_point_c": dew_point_c,
        # airflow (air side only, radiant already taken off)
        "design_flow_m3s": design_flow,
        "design_flow_ls": design_flow * 1000.0,
        "design_flow_m3h": design_flow * 3600.0,
        "flow_heating_operating": flow_heating_operating,
        "flow_cooling_operating": flow_cooling_operating,
        "flow_heating_ramp": flow_heating_ramp,
        "flow_cooling_ramp": flow_cooling_ramp,
        "flow_operating_ls": flow_operating * 1000.0,
        "flow_ramp_ls": flow_ramp * 1000.0,
        "flow_from_capacity": flow_from_capacity,
        "flow_from_ach": flow_from_ach,
        "flow_set_by_ventilation": flow_set_by_ventilation,
        "flow_set_by_ramp": flow_set_by_ramp,
        # radiant panels and the air-side remainder, by mode
        "radiant_area_actual": radiant_area_actual,
        "radiant_capacity_heat": radiant_capacity_heat,
        "radiant_capacity_cool": radiant_capacity_cool,
        "radiant_heating_operating": radiant_heating_operating,
        "radiant_heating_ramp": radiant_heating_ramp,
        "radiant_cooling_operating": radiant_cooling_operating,
        "radiant_cooling_ramp": radiant_cooling_ramp,
        "radiant_heating_design": radiant_heating_design,
        "radiant_cooling_design": radiant_cooling_design,
        "air_heating_operating": air_heating_operating,
        "air_heating_ramp": air_heating_ramp,
        "air_cooling_operating": air_cooling_operating,
        "air_cooling_ramp": air_cooling_ramp,
        "air_heating_design": air_heating_design,
        "air_cooling_design": air_cooling_design,
        "radiant_area": radiant_area,
        "radiant_flux_heat": radiant_flux_heat,
        "radiant_flux_cool": radiant_flux_cool,
        "radiant_heat_ok": radiant_heat_ok,
        "radiant_cool_ok": radiant_cool_ok,
        "air_steady_heating": air_steady_heating,
        "air_steady_cooling": air_steady_cooling,
        # dedicated heat pump
        "tank_on": tank_on,
        "source_temp_heating": source_temp_heating,
        "sink_temp_cooling": sink_temp_cooling,
        "hp_heating": hp_heating,
        "hp_cooling": hp_cooling,
        "supply_temp_heating": supply_temp_heating,
        "supply_temp_cooling": supply_temp_cooling,
        "lift_heating": lift_heating,
        "lift_cooling": lift_cooling,
        "cop_heating": cop_heating,
        "cop_cooling": cop_cooling,
        "electric_heating": electric_heating,
        "electric_cooling": electric_cooling,
        "electric_heating_operating": electric_heating_operating,
        "electric_heating_ramp": electric_heating_ramp,
        "electric_cooling_operating": electric_cooling_operating,
        "electric_cooling_ramp": electric_cooling_ramp,
        "source_extract_heating": source_extract_heating,
        "source_reject_cooling": source_reject_cooling,
        "source_extract_heating_operating": source_extract_heating_operating,
        "source_extract_heating_ramp": source_extract_heating_ramp,
        "source_reject_cooling_operating": source_reject_cooling_operating,
        "source_reject_cooling_ramp": source_reject_cooling_ramp,
        "tank_extract_heating": tank_extract_heating,
        "tank_reject_cooling": tank_reject_cooling,
        "free_heating": free_heating,
        "free_cooling": free_cooling,
    }


# --------------------------------------------------------------------------
# The self-consistent fastest ramp
# --------------------------------------------------------------------------
#
# ``min_feasible_ramp_minutes`` above answers a narrower question than its name
# suggests: *given a ramp of the length you asked for, how long would the
# fastest one be?*  Those are only the same question when the participating
# mass does not depend on the ramp.  For the bare shell that holds -- aluminium
# and glass are thermally thin, so the whole layer participates whatever the
# timescale -- but as soon as there is added mass it does not.  A longer ramp
# lets heat diffuse deeper, more mass takes part, and the minimum ramp moves
# out from under you.
#
# So the honest answer is the fixed point: the ramp time that is exactly its
# own minimum.  Below it the film cannot deliver; above it it can.  Solve
#
#     t * h * A * dT_allowed = dT_ramp * C(t)
#
# with C(t) = C0 + A_add * rho_c * d_eff(t) and d_eff = min(coeff*sqrt(a t), L).
# In the unsaturated regime that is a quadratic in sqrt(t); once the layer is
# fully penetrated C stops moving and it is linear.  ``_fastest_ramp_iterated``
# solves the same thing by repeated substitution and shares no algebra with it;
# ``tests/test_physics.py`` checks the two agree.


def fastest_ramp_minutes(
    params: ChamberParams | dict[str, Any],
    *,
    lumped_mass: bool = False,
) -> Any:
    """The ramp time that equals its own minimum feasible ramp, in minutes.

    This is the room's actual speed limit, and unlike
    ``compute()["min_feasible_ramp_minutes"]`` it does not depend on the
    ``ramp_minutes`` you happen to pass in -- that input drops out entirely.
    Use this one whenever the question is "how fast can this room go".

    Numpy-safe: broadcasts like everything else here.
    """
    p = _as_dict(params)

    # Clamped exactly as compute() clamps them, so the two never disagree.
    width = np.maximum(p["width"], 0.1)
    depth = np.maximum(p["depth"], 0.1)
    height = np.maximum(p["height"], 0.1)
    volume = width * depth * height
    interior_area = sum(s.area(width, depth, height) for s in SURFACES)

    delta_t = np.abs(
        np.asarray(p["setpoint_max"], dtype=float) - np.asarray(p["setpoint_min"], dtype=float)
    )

    # Capacity that does not move with the ramp, J/K.
    c_fixed = (
        RHO_AIR * volume * CP_AIR
        + interior_area * np.asarray(p["base_shell_capacity"], dtype=float) * 1000.0
    )

    added_area = (np.maximum(np.asarray(p["added_mass_coverage"], dtype=float), 0.0) / 100.0
                  * interior_area)  # added_mass_coverage is % of interior surface
    rho_c = np.asarray(p["added_mass_rho_c"], dtype=float) * 1000.0  # kJ/m3K -> J/m3K
    thickness = np.asarray(p["added_mass_thickness"], dtype=float)
    alpha = np.asarray(p["added_mass_k"], dtype=float) / np.maximum(rho_c, 1e-9)

    # What the film can push into the mass, W.
    max_mass_power = np.maximum(
        np.asarray(p["surface_film_h"], dtype=float)
        * interior_area
        * np.asarray(p["max_air_surface_dt"], dtype=float),
        1e-9,
    )

    # Fully penetrated: capacity is constant, so the root is linear in t.
    c_saturated = c_fixed + added_area * rho_c * thickness
    t_saturated = delta_t * c_saturated / max_mass_power

    if lumped_mass:
        return t_saturated / 60.0

    # Diffusion-limited: quadratic in u = sqrt(t).
    b = added_area * rho_c * mass_mod.RAMP_DEPTH_COEFF * np.sqrt(alpha)
    disc = (delta_t * b) ** 2 + 4.0 * max_mass_power * delta_t * c_fixed
    u = (delta_t * b + np.sqrt(np.maximum(disc, 0.0))) / (2.0 * max_mass_power)
    t_diffusing = u * u

    # The layer saturates when the penetration depth reaches its thickness.
    # C(t) is continuous and increasing, so exactly one branch is consistent.
    penetration = mass_mod.RAMP_DEPTH_COEFF * np.sqrt(alpha * np.maximum(t_diffusing, 0.0))
    seconds = np.where(penetration <= thickness, t_diffusing, t_saturated)
    return np.maximum(seconds, 0.0) / 60.0


def _fastest_ramp_iterated(
    params: ChamberParams | dict[str, Any],
    *,
    lumped_mass: bool = False,
    start_minutes: float = 30.0,
    iterations: int = 200,
) -> Any:
    """Repeated substitution onto ``min_feasible_ramp_minutes``.

    An independent check on :func:`fastest_ramp_minutes`, sharing none of its
    algebra.  Slow, so it lives here for the tests rather than for use.
    """
    p = _as_dict(params)
    shape = np.broadcast_shapes(*(np.shape(np.asarray(v, dtype=float)) for v in p.values()))
    t = np.full(shape or (1,), float(start_minutes))
    for _ in range(iterations):
        t = np.asarray(
            compute(p, ramp_minutes=t, lumped_mass=lumped_mass)["min_feasible_ramp_minutes"],
            dtype=float,
        )
    return t


# --------------------------------------------------------------------------
# Where the ramp stops setting the size
# --------------------------------------------------------------------------

def mode_crossover_minutes(
    params: ChamberParams | dict[str, Any],
    duty: str,
    *,
    longest: float = 480.0,
    step: float = 1.0,
) -> float | None:
    """The shortest ramp time at which the operating mode, not the ramp, sets
    the design capacity for ``duty`` ("heating" or "cooling").

    The ramp requirement falls monotonically as the ramp gets longer, the
    operating requirement does not move, so there is at most one crossing.
    Returns ``None`` when the ramp governs all the way out to ``longest``
    minutes -- which is always the case when the hold in ramp conditions
    alone already exceeds the operating hold, as it does for heating once the
    Sun is off.  Scalar parameters only; evaluated on a ``step``-minute grid.
    """
    if duty not in ("heating", "cooling"):
        raise ValueError(f"duty must be 'heating' or 'cooling', not {duty!r}")
    minutes = np.arange(step, longest + step / 2, step)
    r = compute(params, ramp_minutes=minutes)
    operating = np.broadcast_to(np.asarray(r[f"{duty}_operating"], dtype=float), minutes.shape)
    ramp = np.asarray(r[f"{duty}_ramp"], dtype=float)
    governed = ramp <= operating
    if not governed.any():
        return None
    return float(minutes[int(np.argmax(governed))])


RESULT_KEYS: tuple[str, ...] = tuple(compute(ChamberParams()).keys())
