"""Sizing calculations for an environmental test chamber.

Two problems get conflated under "the HVAC is undersized":

* **Ramping** between setpoints, which is a mass-charging problem.  The power
  needed scales with total heat capacity over the time allowed.
* **Holding** a setpoint during an experiment, which is a steady-state problem
  set by the envelope, the ventilation and the internal gains.

A third distinction matters once each chamber gets a dedicated heat pump backed
by a buffer tank: the air-handling coil still has to deliver the full ramp peak
to the room, but the heat pump can be smaller if the Pufferspeicher stores
enough energy to cover the ramp surge.

And a fourth, which the original workshop tool missed entirely: heat only
enters the thermal mass through a surface film of roughly 8 W/m^2K.  That puts
a hard ceiling on mass-charging power regardless of how large the coil is.  See
``required_air_surface_dt`` and ``min_feasible_ramp_minutes``.

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

    added_area = np.maximum(p["added_mass_area"], 0.0)
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

    # -- steady-state hold loads ------------------------------------------
    vent_sensible_heat = m_dot_vent * CP_AIR * (t_max - p["vent_supply_temp"])
    heating_hold = np.maximum(envelope_heat + vent_sensible_heat - internal_sensible, 0.0)

    vent_sensible_cool = m_dot_vent * CP_AIR * (p["vent_supply_temp"] - t_min)
    cooling_hold = np.maximum(envelope_cool + vent_sensible_cool + internal_sensible, 0.0)

    # -- ramp -------------------------------------------------------------
    # For a lumped capacity under a linear ramp, C dT/dt = P - UA(T - T_ext),
    # so the peak demand is the mass-charging term plus the steady load at the
    # far end of the ramp.  Exact for the lumped model; see tests.
    energy_mass = c_total * ramp_delta_t  # J
    power_mass = energy_mass / ramp_s  # W

    margin_frac = np.asarray(p["margin_pct"], dtype=float) / 100.0
    heating_design = (heating_hold + power_mass) * (1.0 + margin_frac)
    cooling_design = (cooling_hold + power_mass) * (1.0 + margin_frac)

    # -- surface film limit on mass charging ------------------------------
    # Whatever the coil can produce, the heat still has to cross the air-to-
    # surface film.  This is usually what actually caps the ramp rate.
    exchange_area = interior_area
    film_conductance = np.asarray(p["surface_film_h"], dtype=float) * exchange_area  # W/K
    required_air_surface_dt = power_mass / np.maximum(film_conductance, 1e-9)
    max_mass_power = film_conductance * np.asarray(p["max_air_surface_dt"], dtype=float)
    film_ok = required_air_surface_dt <= p["max_air_surface_dt"]
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

    # -- supply airflow ---------------------------------------------------
    flow_from_heating = heating_design / (RHO_AIR * CP_AIR * np.maximum(p["supply_dt"], 1e-6))
    flow_from_cooling = cooling_design / (RHO_AIR * CP_AIR * np.maximum(p["supply_dt"], 1e-6))
    flow_from_capacity = np.maximum(flow_from_heating, flow_from_cooling)
    flow_from_ach = np.asarray(p["ach"], dtype=float) * volume / 3600.0
    design_flow = np.maximum(flow_from_capacity, flow_from_ach)
    flow_set_by_ventilation = flow_from_ach > flow_from_capacity

    # -- radiant check (steady-state hold only) ---------------------------
    # Floor plus roof are the radiant surfaces.
    radiant_area = np.maximum(
        (surface_area["floor"] + surface_area["roof"])
        * np.asarray(p["radiant_fraction"], dtype=float) / 100.0,
        0.1,
    )
    radiant_flux_heat = heating_hold / radiant_area
    radiant_flux_cool = cooling_hold / radiant_area
    radiant_heat_ok = radiant_flux_heat <= p["radiant_heat_limit"]
    radiant_cool_ok = radiant_flux_cool <= p["radiant_cool_limit"]
    air_steady_heating = np.maximum(heating_hold - np.asarray(p["radiant_heat_limit"], dtype=float) * radiant_area, 0.0)
    air_steady_cooling = np.maximum(cooling_hold - np.asarray(p["radiant_cool_limit"], dtype=float) * radiant_area, 0.0)

    # -- dedicated plant and buffer ---------------------------------------
    buffer_energy = np.asarray(p["buffer_volume_l"], dtype=float) * CP_WATER * p["buffer_dt"]  # J per tank
    energy_from_buffer = np.minimum(energy_mass, buffer_energy)
    energy_shortfall = np.maximum(energy_mass - buffer_energy, 0.0)
    plant_during_ramp = energy_shortfall / ramp_s
    plant_recharge = energy_from_buffer / np.maximum(np.asarray(p["recharge_minutes"], dtype=float) * 60.0, 1e-9)
    plant_extra = np.maximum(plant_during_ramp, plant_recharge)
    plant_heating = (heating_hold + plant_extra) * (1.0 + margin_frac)
    plant_cooling = (cooling_hold + plant_extra) * (1.0 + margin_frac)
    buffer_covers_ramp = buffer_energy >= energy_mass
    buffer_coverage_pct = np.where(
        energy_mass > 0.0, np.minimum(buffer_energy / np.maximum(energy_mass, 1e-9), 1.0) * 100.0, 100.0
    )

    diversity = np.asarray(p["diversity_pct"], dtype=float) / 100.0
    aggregate_heating = plant_heating * p["n_chambers"] * diversity
    aggregate_cooling = plant_cooling * p["n_chambers"] * diversity

    return {
        # geometry
        "volume": volume,
        "floor_area": floor_area,
        "interior_area": interior_area,
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
        # steady state
        "heating_hold": heating_hold,
        "cooling_hold": cooling_hold,
        "envelope_heat": envelope_heat,
        "envelope_cool": envelope_cool,
        "vent_sensible_heat": vent_sensible_heat,
        "vent_sensible_cool": vent_sensible_cool,
        "solar_gain": solar_gain,
        **per_surface,
        "internal_sensible": internal_sensible,
        "equipment_w": equipment_w,
        # design
        "margin_frac": margin_frac,
        "heating_design": heating_design,
        "cooling_design": cooling_design,
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
        # airflow
        "design_flow_m3s": design_flow,
        "design_flow_ls": design_flow * 1000.0,
        "design_flow_m3h": design_flow * 3600.0,
        "flow_from_capacity": flow_from_capacity,
        "flow_from_ach": flow_from_ach,
        "flow_set_by_ventilation": flow_set_by_ventilation,
        # radiant
        "radiant_area": radiant_area,
        "radiant_flux_heat": radiant_flux_heat,
        "radiant_flux_cool": radiant_flux_cool,
        "radiant_heat_ok": radiant_heat_ok,
        "radiant_cool_ok": radiant_cool_ok,
        "air_steady_heating": air_steady_heating,
        "air_steady_cooling": air_steady_cooling,
        # plant
        "buffer_energy_j": buffer_energy,
        "buffer_energy_kwh": buffer_energy / 3.6e6,
        "buffer_covers_ramp": buffer_covers_ramp,
        "buffer_coverage_pct": buffer_coverage_pct,
        "plant_extra": plant_extra,
        "plant_heating": plant_heating,
        "plant_cooling": plant_cooling,
        "aggregate_heating": aggregate_heating,
        "aggregate_cooling": aggregate_cooling,
    }


RESULT_KEYS: tuple[str, ...] = tuple(compute(ChamberParams()).keys())
