"""Parameter schema for the chamber sizing model.

One source of truth: the dataclass below holds defaults and types, the
``PARAMS`` list holds everything the UI needs to render a control for each
field.  ``tests/test_params.py`` asserts the two never drift apart.

The envelope is described surface by surface -- see ``surfaces.py`` for the
axis convention and what ``exposure`` means.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Iterable

from .surfaces import SURFACES

# --------------------------------------------------------------------------
# Section metadata (order here is the order the UI renders them)
# --------------------------------------------------------------------------

SECTIONS: list[dict[str, str]] = [
    {
        "key": "geometry",
        "title": "Geometry",
        "blurb": "Internal clear dimensions. Width runs east-west, depth runs north-south.",
    },
    {
        "key": "mass",
        "title": "Thermal mass",
        "blurb": "The bare shell, plus any deliberate mass element added inside it.",
    },
    {"key": "surf_north", "title": "North wall", "blurb": "Area width x height, from the room geometry."},
    {"key": "surf_east", "title": "East wall", "blurb": "Area depth x height, from the room geometry."},
    {"key": "surf_south", "title": "South wall", "blurb": "Area width x height, from the room geometry."},
    {"key": "surf_west", "title": "West wall", "blurb": "Area depth x height, from the room geometry."},
    {"key": "surf_roof", "title": "Roof", "blurb": "Area width x depth, from the room geometry."},
    {"key": "surf_floor", "title": "Floor", "blurb": "Area width x depth, from the room geometry."},
    {
        "key": "boundary",
        "title": "Design conditions",
        "blurb": "The outdoor design temperatures every exposed surface faces, and the lab around the room.",
    },
    {
        "key": "setpoints",
        "title": "Setpoints & ramp",
        "blurb": "The variables the workshop exists to converge on.",
    },
    {
        "key": "ventilation",
        "title": "Ventilation & internal gains",
        "blurb": "Fresh air, its humidity, and what the room generates internally.",
    },
    {
        "key": "delivery",
        "title": "Delivery limits",
        "blurb": "What the radiant surfaces, the supply air and the room surfaces can physically carry.",
    },
    {
        "key": "plant",
        "title": "Dedicated plant & buffer",
        "blurb": "Each chamber's own heat pump, its Pufferspeicher, and the shared grid tie-in.",
    },
    {"key": "site", "title": "Site", "blurb": "Ambient conditions that shift the psychrometrics."},
]


@dataclass(frozen=True)
class Param:
    """UI + validation metadata for one model input."""

    key: str
    section: str
    label: str
    unit: str = ""
    minimum: float = 0.0
    maximum: float = 1.0
    step: float = 0.1
    decimals: int = 1
    hint: str = ""

    def clamp(self, value: float) -> float:
        return min(max(float(value), self.minimum), self.maximum)


# --------------------------------------------------------------------------
# Material presets
# --------------------------------------------------------------------------

MASS_PRESETS: dict[str, dict[str, float | str]] = {
    "rammed_earth": {"label": "Rammed earth", "rho_c": 1800.0, "k": 1.25,
                     "note": "Stabilised rammed earth, the material currently in the chamber."},
    "dense_concrete": {"label": "Dense concrete", "rho_c": 2100.0, "k": 1.80,
                       "note": "2300 kg/m3 normal-weight concrete."},
    "brick": {"label": "Solid brick", "rho_c": 1360.0, "k": 0.80,
              "note": "1700 kg/m3 fired clay brick."},
    "gypsum": {"label": "Gypsum board", "rho_c": 810.0, "k": 0.25,
               "note": "Lightweight lining; saturates within minutes, so it behaves as pure capacitance."},
    "water_wall": {"label": "Water (PCM stand-in)", "rho_c": 4186.0, "k": 0.60,
                   "note": "Upper bound on sensible storage density; internal convection is not modelled."},
}

#: Areal heat capacity of common interior linings, kJ/m2K. All of these are
#: thermally thin at a ramp's timescale, so the whole layer participates and a
#: plain areal capacitance is exact.
SHELL_PRESETS: dict[str, dict[str, float | str]] = {
    "aluminium_2mm": {"label": "2 mm aluminium on insulation", "capacity": 4.9,
                      "note": "Bonded aluminium skin; the insulation behind it stores nothing."},
    "aluminium_3mm": {"label": "3 mm aluminium on insulation", "capacity": 7.3,
                      "note": "As above, heavier skin."},
    "composite_panel": {"label": "Aluminium composite panel", "capacity": 9.0,
                        "note": "2 x 0.5 mm aluminium skins over a 3 mm polymer core."},
    "glass_6mm": {"label": "6 mm glass", "capacity": 12.6, "note": "Single pane, fully participating."},
    "gypsum_lining": {"label": "Gypsum board lining", "capacity": 40.0,
                      "note": "Plasterboard over insulation, the usual lightweight interior."},
    "masonry": {"label": "Masonry or concrete", "capacity": 150.0,
                "note": "Only the surface layer participates in a short ramp; see mass.py."},
}


# --------------------------------------------------------------------------
# The parameter set
# --------------------------------------------------------------------------

PARAMS: list[Param] = [
    # ---- geometry -------------------------------------------------------
    Param("width", "geometry", "Width", "m", 0.5, 30.0, 0.05, 2,
          "East-west dimension. The north and south walls are this wide."),
    Param("depth", "geometry", "Depth", "m", 0.5, 30.0, 0.05, 2,
          "North-south dimension. The east and west walls are this wide."),
    Param("height", "geometry", "Height", "m", 0.5, 30.0, 0.05, 2,
          "Internal clear height, floor to ceiling."),

    # ---- thermal mass ---------------------------------------------------
    Param("base_shell_capacity", "mass", "Baseline shell capacitance", "kJ/m²K", 1.0, 200.0, 0.5, 1,
          "The bare shell spread over all interior surfaces, fully participating. "
          "Aluminium on insulation ≈5-9 · glass ≈13 · gypsum ≈40 · masonry ≈150."),
    Param("added_mass_area", "mass", "Added mass: area", "m²", 0.0, 400.0, 1.0, 0,
          "Surface area the deliberate mass element covers. Zero disables the whole added-mass term."),
    Param("added_mass_thickness", "mass", "Added mass: thickness", "m", 0.005, 1.0, 0.005, 3,
          "Physical depth of the layer. Only the part heat reaches within the ramp counts."),
    Param("added_mass_rho_c", "mass", "Added mass: ρc", "kJ/m³K", 200.0, 4500.0, 10.0, 0,
          "Volumetric heat capacity. Rammed earth ≈1800 · concrete ≈2100 · brick ≈1360."),
    Param("added_mass_k", "mass", "Added mass: conductivity", "W/mK", 0.05, 250.0, 0.05, 2,
          "With ρc this sets diffusivity α = k/ρc, which decides how deep the ramp reaches."),

    # ---- per-surface envelope -------------------------------------------
    Param("north_u_opaque", "surf_north", "North wall: U, opaque", "W/m²K", 0.0, 5.0, 0.01, 2,
          "Opaque part of the assembly. Zero makes the surface perfectly adiabatic."),
    Param("north_u_glazing", "surf_north", "North wall: U, glazing", "W/m²K", 0.0, 6.0, 0.05, 2,
          "Glazed part. Xenon-filled ≈0.4 · triple ≈0.7 · double ≈1.2 · single ≈5.7."),
    Param("north_wwr", "surf_north", "North wall: Glazed fraction", "%", 0.0, 100.0, 1.0, 0,
          "Glazed share of this surface. The rest uses the opaque U-value."),
    Param("north_shgc", "surf_north", "North wall: Glazing SHGC", "", 0.0, 1.0, 0.01, 2,
          "Solar heat gain coefficient of the glazed part."),
    Param("north_irradiance", "surf_north", "North wall: Peak irradiance", "W/m²", 0.0, 2000.0, 25.0, 0,
          "Peak solar or lamp irradiance on this surface, used in the cooling case only."),
    Param("north_exposure", "surf_north", "North wall: Exposure to outdoors", "", 0.0, 1.0, 0.05, 2,
          "1 faces the outdoor design condition, 0 faces the surrounding lab, in between is a buffer space."),
    Param("east_u_opaque", "surf_east", "East wall: U, opaque", "W/m²K", 0.0, 5.0, 0.01, 2,
          "Opaque part of the assembly. Zero makes the surface perfectly adiabatic."),
    Param("east_u_glazing", "surf_east", "East wall: U, glazing", "W/m²K", 0.0, 6.0, 0.05, 2,
          "Glazed part. Xenon-filled ≈0.4 · triple ≈0.7 · double ≈1.2 · single ≈5.7."),
    Param("east_wwr", "surf_east", "East wall: Glazed fraction", "%", 0.0, 100.0, 1.0, 0,
          "Glazed share of this surface. The rest uses the opaque U-value."),
    Param("east_shgc", "surf_east", "East wall: Glazing SHGC", "", 0.0, 1.0, 0.01, 2,
          "Solar heat gain coefficient of the glazed part."),
    Param("east_irradiance", "surf_east", "East wall: Peak irradiance", "W/m²", 0.0, 2000.0, 25.0, 0,
          "Peak solar or lamp irradiance on this surface, used in the cooling case only."),
    Param("east_exposure", "surf_east", "East wall: Exposure to outdoors", "", 0.0, 1.0, 0.05, 2,
          "1 faces the outdoor design condition, 0 faces the surrounding lab, in between is a buffer space."),
    Param("south_u_opaque", "surf_south", "South wall: U, opaque", "W/m²K", 0.0, 5.0, 0.01, 2,
          "Opaque part of the assembly. Zero makes the surface perfectly adiabatic."),
    Param("south_u_glazing", "surf_south", "South wall: U, glazing", "W/m²K", 0.0, 6.0, 0.05, 2,
          "Glazed part. Xenon-filled ≈0.4 · triple ≈0.7 · double ≈1.2 · single ≈5.7."),
    Param("south_wwr", "surf_south", "South wall: Glazed fraction", "%", 0.0, 100.0, 1.0, 0,
          "Glazed share of this surface. The rest uses the opaque U-value."),
    Param("south_shgc", "surf_south", "South wall: Glazing SHGC", "", 0.0, 1.0, 0.01, 2,
          "Solar heat gain coefficient of the glazed part."),
    Param("south_irradiance", "surf_south", "South wall: Peak irradiance", "W/m²", 0.0, 2000.0, 25.0, 0,
          "Peak solar or lamp irradiance on this surface, used in the cooling case only."),
    Param("south_exposure", "surf_south", "South wall: Exposure to outdoors", "", 0.0, 1.0, 0.05, 2,
          "1 faces the outdoor design condition, 0 faces the surrounding lab, in between is a buffer space."),
    Param("west_u_opaque", "surf_west", "West wall: U, opaque", "W/m²K", 0.0, 5.0, 0.01, 2,
          "Opaque part of the assembly. Zero makes the surface perfectly adiabatic."),
    Param("west_u_glazing", "surf_west", "West wall: U, glazing", "W/m²K", 0.0, 6.0, 0.05, 2,
          "Glazed part. Xenon-filled ≈0.4 · triple ≈0.7 · double ≈1.2 · single ≈5.7."),
    Param("west_wwr", "surf_west", "West wall: Glazed fraction", "%", 0.0, 100.0, 1.0, 0,
          "Glazed share of this surface. The rest uses the opaque U-value."),
    Param("west_shgc", "surf_west", "West wall: Glazing SHGC", "", 0.0, 1.0, 0.01, 2,
          "Solar heat gain coefficient of the glazed part."),
    Param("west_irradiance", "surf_west", "West wall: Peak irradiance", "W/m²", 0.0, 2000.0, 25.0, 0,
          "Peak solar or lamp irradiance on this surface, used in the cooling case only."),
    Param("west_exposure", "surf_west", "West wall: Exposure to outdoors", "", 0.0, 1.0, 0.05, 2,
          "1 faces the outdoor design condition, 0 faces the surrounding lab, in between is a buffer space."),
    Param("roof_u_opaque", "surf_roof", "Roof: U, opaque", "W/m²K", 0.0, 5.0, 0.01, 2,
          "Opaque part of the assembly. Zero makes the surface perfectly adiabatic."),
    Param("roof_u_glazing", "surf_roof", "Roof: U, glazing", "W/m²K", 0.0, 6.0, 0.05, 2,
          "Glazed part. Xenon-filled ≈0.4 · triple ≈0.7 · double ≈1.2 · single ≈5.7."),
    Param("roof_wwr", "surf_roof", "Roof: Glazed fraction", "%", 0.0, 100.0, 1.0, 0,
          "Glazed share of this surface. The rest uses the opaque U-value."),
    Param("roof_shgc", "surf_roof", "Roof: Glazing SHGC", "", 0.0, 1.0, 0.01, 2,
          "Solar heat gain coefficient of the glazed part."),
    Param("roof_irradiance", "surf_roof", "Roof: Peak irradiance", "W/m²", 0.0, 2000.0, 25.0, 0,
          "Peak solar or lamp irradiance on this surface, used in the cooling case only."),
    Param("roof_exposure", "surf_roof", "Roof: Exposure to outdoors", "", 0.0, 1.0, 0.05, 2,
          "1 faces the outdoor design condition, 0 faces the surrounding lab, in between is a buffer space."),
    Param("floor_u_opaque", "surf_floor", "Floor: U, opaque", "W/m²K", 0.0, 5.0, 0.01, 2,
          "Opaque part of the assembly. Zero makes the surface perfectly adiabatic."),
    Param("floor_u_glazing", "surf_floor", "Floor: U, glazing", "W/m²K", 0.0, 6.0, 0.05, 2,
          "Glazed part. Xenon-filled ≈0.4 · triple ≈0.7 · double ≈1.2 · single ≈5.7."),
    Param("floor_wwr", "surf_floor", "Floor: Glazed fraction", "%", 0.0, 100.0, 1.0, 0,
          "Glazed share of this surface. The rest uses the opaque U-value."),
    Param("floor_shgc", "surf_floor", "Floor: Glazing SHGC", "", 0.0, 1.0, 0.01, 2,
          "Solar heat gain coefficient of the glazed part."),
    Param("floor_irradiance", "surf_floor", "Floor: Peak irradiance", "W/m²", 0.0, 2000.0, 25.0, 0,
          "Peak solar or lamp irradiance on this surface, used in the cooling case only."),
    Param("floor_exposure", "surf_floor", "Floor: Exposure to outdoors", "", 0.0, 1.0, 0.05, 2,
          "1 faces the outdoor design condition, 0 faces the surrounding lab, in between is a buffer space."),

    # ---- design conditions ----------------------------------------------
    Param("boundary_temp_winter", "boundary", "Winter design temp", "°C", -40.0, 25.0, 0.5, 1,
          "Outdoor air temperature in the heating design case, seen by every exposed surface."),
    Param("boundary_temp_summer", "boundary", "Summer design temp", "°C", 5.0, 60.0, 0.5, 1,
          "Outdoor air temperature in the cooling design case."),
    Param("boundary_rh", "boundary", "Outdoor air RH", "%", 5.0, 100.0, 1.0, 0,
          "Only used if ventilation air is drawn from outdoors unconditioned."),
    Param("surrounding_temp", "boundary", "Surrounding lab temp", "°C", 5.0, 35.0, 0.5, 1,
          "What surfaces with zero exposure face."),

    # ---- setpoints & ramp ----------------------------------------------
    Param("setpoint_min", "setpoints", "Min setpoint", "°C", -20.0, 40.0, 0.5, 1,
          "Coldest chamber condition the experiments need."),
    Param("setpoint_max", "setpoints", "Max setpoint", "°C", -15.0, 60.0, 0.5, 1,
          "Warmest chamber condition the experiments need."),
    Param("ramp_minutes", "setpoints", "Target ramp time", "min", 1.0, 480.0, 1.0, 0,
          "Time allowed to move the full setpoint range."),
    Param("margin_pct", "setpoints", "Safety margin", "%", 0.0, 50.0, 5.0, 0,
          "Applied to final capacities. Covers control lag, fan and duct heat, coil approach."),

    # ---- ventilation & gains -------------------------------------------
    Param("ach", "ventilation", "Air changes per hour", "1/h", 0.0, 20.0, 0.5, 1,
          "Outdoor-air ventilation rate."),
    Param("vent_supply_temp", "ventilation", "Ventilation air temp", "°C", -40.0, 60.0, 0.5, 1,
          "Set to the outdoor design temperature if fresh air is unconditioned."),
    Param("vent_supply_rh", "ventilation", "Ventilation air RH", "%", 5.0, 100.0, 1.0, 0,
          "Humidity of the incoming air before the coil sees it."),
    Param("target_rh", "ventilation", "Chamber target RH", "%", 10.0, 90.0, 1.0, 0,
          "The relative humidity the chamber has to hold."),
    Param("occupants", "ventilation", "Occupants", "", 0.0, 20.0, 1.0, 0,
          "People in the chamber during an experiment."),
    Param("sensible_per_person", "ventilation", "Sensible per person", "W", 40.0, 200.0, 5.0, 0,
          "ASHRAE Fundamentals: ~70 W seated, ~75 W light office work, ~130 W light machine work."),
    Param("latent_per_person", "ventilation", "Latent per person", "W", 20.0, 200.0, 5.0, 0,
          "ASHRAE Fundamentals: ~45 W seated, ~55 W light work."),
    Param("equipment_w_per_m2", "ventilation", "Equipment & lighting", "W/m²", 0.0, 500.0, 5.0, 0,
          "Per square metre of floor. Office-like ≈15 · dense instrumentation ≈50 · "
          "a large lighting or solar-simulator rig can reach several hundred."),

    # ---- delivery limits ------------------------------------------------
    Param("radiant_fraction", "delivery", "Radiant active area", "%", 0.0, 100.0, 5.0, 0,
          "Share of floor + roof that is actively radiant."),
    Param("radiant_heat_limit", "delivery", "Radiant heating limit", "W/m²", 20.0, 200.0, 5.0, 0,
          "EN 1264 / ISO 11855: ~100 W/m² for floor heating in occupied zones."),
    Param("radiant_cool_limit", "delivery", "Radiant cooling limit", "W/m²", 10.0, 120.0, 5.0, 0,
          "Condensation-limited. ISO 11855: ~40-50 W/m² floor, up to ~90 for chilled ceilings."),
    Param("supply_dt", "delivery", "Max supply-air ΔT", "K", 3.0, 30.0, 1.0, 0,
          "Coil-to-room temperature difference."),
    Param("surface_film_h", "delivery", "Surface film coefficient", "W/m²K", 2.0, 30.0, 0.5, 1,
          "Combined convective + radiative transfer between room air and interior surfaces. "
          "~8 W/m²K is the standard still-air value; forced air over the surfaces raises it."),
    Param("max_air_surface_dt", "delivery", "Allowable air-to-surface ΔT", "K", 1.0, 60.0, 1.0, 0,
          "How far the air may run from the surfaces while charging the mass. "
          "This decides whether a ramp time is physically reachable at all."),

    # ---- plant ----------------------------------------------------------
    Param("buffer_volume_l", "plant", "Buffer volume, per tank", "L", 100.0, 10000.0, 50.0, 0,
          "One hot and one cold Pufferspeicher of this size."),
    Param("buffer_dt", "plant", "Usable buffer ΔT", "K", 3.0, 40.0, 1.0, 0,
          "Temperature swing the tank can give up before it stops being useful."),
    Param("recharge_minutes", "plant", "Recharge window", "min", 5.0, 480.0, 5.0, 0,
          "Time the heat pump has to refill the buffer before the next ramp."),
    Param("n_chambers", "plant", "Chambers on the tie-in", "", 1.0, 12.0, 1.0, 0,
          "For the aggregate anergy-grid figure only."),
    Param("diversity_pct", "plant", "Simultaneity", "%", 10.0, 100.0, 5.0, 0,
          "Share of chambers assumed to peak together."),

    # ---- site -----------------------------------------------------------
    Param("pressure_pa", "site", "Atmospheric pressure", "Pa", 80000.0, 103000.0, 100.0, 0,
          "Sea level 101325 Pa; Zurich at ~410 m is about 96500 Pa."),
]

PARAMS_BY_KEY: dict[str, Param] = {p.key: p for p in PARAMS}


# --------------------------------------------------------------------------
# The dataclass
# --------------------------------------------------------------------------

@dataclass
class ChamberParams:
    """All model inputs.

    Defaults describe a generic single-exterior-wall room: the south wall and
    the roof face outdoors, everything else faces the surrounding lab.
    """

    # geometry
    width: float = 3.0
    depth: float = 4.0
    height: float = 2.7

    # thermal mass
    base_shell_capacity: float = 15.0
    added_mass_area: float = 0.0
    added_mass_thickness: float = 0.30
    added_mass_rho_c: float = 1800.0
    added_mass_k: float = 1.25

    # per-surface envelope
    north_u_opaque: float = 0.05
    north_u_glazing: float = 1.4
    north_wwr: float = 0.0
    north_shgc: float = 0.5
    north_irradiance: float = 0.0
    north_exposure: float = 0.0
    east_u_opaque: float = 0.05
    east_u_glazing: float = 1.4
    east_wwr: float = 0.0
    east_shgc: float = 0.5
    east_irradiance: float = 0.0
    east_exposure: float = 0.0
    south_u_opaque: float = 1.2
    south_u_glazing: float = 1.4
    south_wwr: float = 30.0
    south_shgc: float = 0.5
    south_irradiance: float = 700.0
    south_exposure: float = 1.0
    west_u_opaque: float = 0.05
    west_u_glazing: float = 1.4
    west_wwr: float = 0.0
    west_shgc: float = 0.5
    west_irradiance: float = 0.0
    west_exposure: float = 0.0
    roof_u_opaque: float = 1.2
    roof_u_glazing: float = 1.4
    roof_wwr: float = 0.0
    roof_shgc: float = 0.5
    roof_irradiance: float = 0.0
    roof_exposure: float = 1.0
    floor_u_opaque: float = 0.05
    floor_u_glazing: float = 1.4
    floor_wwr: float = 0.0
    floor_shgc: float = 0.5
    floor_irradiance: float = 0.0
    floor_exposure: float = 0.0

    # design conditions
    boundary_temp_winter: float = -10.0
    boundary_temp_summer: float = 35.0
    boundary_rh: float = 60.0
    surrounding_temp: float = 21.0

    # setpoints & ramp
    setpoint_min: float = 16.0
    setpoint_max: float = 30.0
    ramp_minutes: float = 30.0
    margin_pct: float = 15.0

    # ventilation & gains
    ach: float = 3.0
    vent_supply_temp: float = 21.0
    vent_supply_rh: float = 60.0
    target_rh: float = 50.0
    occupants: float = 2.0
    sensible_per_person: float = 75.0
    latent_per_person: float = 45.0
    equipment_w_per_m2: float = 25.0

    # delivery limits
    radiant_fraction: float = 60.0
    radiant_heat_limit: float = 100.0
    radiant_cool_limit: float = 60.0
    supply_dt: float = 12.0
    surface_film_h: float = 8.0
    max_air_surface_dt: float = 15.0

    # plant
    buffer_volume_l: float = 1000.0
    buffer_dt: float = 15.0
    recharge_minutes: float = 60.0
    n_chambers: float = 1.0
    diversity_pct: float = 100.0

    # site
    pressure_pa: float = 96500.0

    # -- conversion helpers ----------------------------------------------

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    def replace(self, **overrides: Any) -> "ChamberParams":
        """Copy with fields overridden. Unknown keys raise rather than pass silently."""
        unknown = set(overrides) - {f.name for f in fields(self)}
        if unknown:
            raise KeyError(f"unknown parameter(s): {sorted(unknown)}")
        data = self.to_dict()
        data.update(overrides)
        return ChamberParams(**data)

    def with_surface(self, surface_key: str, **props: Any) -> "ChamberParams":
        """Set several properties of one surface at once.

            params.with_surface("north", u_opaque=0.9, wwr=40, exposure=1)
        """
        known = {s.key for s in SURFACES}
        if surface_key not in known:
            raise KeyError(f"unknown surface {surface_key!r}; expected one of {sorted(known)}")
        return self.replace(**{f"{surface_key}_{k}": v for k, v in props.items()})

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, strict: bool = True) -> "ChamberParams":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown and strict:
            raise KeyError(f"unknown parameter(s): {sorted(unknown)}")
        return cls(**{k: float(v) for k, v in data.items() if k in known})

    def clamped(self) -> "ChamberParams":
        """Every field pulled inside its declared UI range."""
        data = self.to_dict()
        for key, value in data.items():
            spec = PARAMS_BY_KEY.get(key)
            if spec is not None:
                data[key] = spec.clamp(value)
        return ChamberParams(**data)

    def validate(self) -> list[str]:
        """Return a list of human-readable problems. Empty means usable."""
        problems: list[str] = []
        for key, value in self.to_dict().items():
            spec = PARAMS_BY_KEY.get(key)
            if spec is None:
                continue
            if not (spec.minimum <= value <= spec.maximum):
                problems.append(
                    f"{spec.label} = {value} is outside {spec.minimum}..{spec.maximum} {spec.unit}".strip()
                )
        if self.setpoint_max <= self.setpoint_min:
            problems.append("Max setpoint must be above min setpoint.")
        if self.ramp_minutes <= 0:
            problems.append("Ramp time must be positive.")
        return problems


DEFAULTS = ChamberParams()


# --------------------------------------------------------------------------
# Scenario files (JSON in, JSON out)
# --------------------------------------------------------------------------

SCENARIO_FORMAT = 2


def save_scenario(
    params: ChamberParams,
    path: str | Path,
    *,
    name: str = "",
    notes: str = "",
    sweeps: dict[str, Iterable[float]] | None = None,
) -> Path:
    """Write a scenario file: the full parameter set plus optional sweep axes."""
    payload: dict[str, Any] = {
        "format": SCENARIO_FORMAT,
        "name": name,
        "notes": notes,
        "params": params.to_dict(),
    }
    if sweeps:
        payload["sweeps"] = {k: [float(x) for x in v] for k, v in sweeps.items()}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def load_scenario(path: str | Path) -> dict[str, Any]:
    """Read a scenario file back. Returns {'params', 'sweeps', 'name', 'notes'}."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    fmt = payload.get("format")
    if fmt != SCENARIO_FORMAT:
        raise ValueError(
            f"scenario format {fmt!r} is not supported (expected {SCENARIO_FORMAT}). "
            "Format 1 predates the per-surface envelope and cannot be converted automatically."
        )
    return {
        "name": payload.get("name", ""),
        "notes": payload.get("notes", ""),
        "params": ChamberParams.from_dict(payload["params"]),
        "sweeps": {k: list(v) for k, v in payload.get("sweeps", {}).items()},
    }


def schema() -> dict[str, Any]:
    """Everything the browser needs to draw the control panel."""
    defaults = DEFAULTS.to_dict()
    return {
        "sections": SECTIONS,
        "presets": MASS_PRESETS,
        "shell_presets": SHELL_PRESETS,
        "surfaces": [{"key": s.key, "label": s.label, "axis": s.axis} for s in SURFACES],
        "params": [
            {
                "key": p.key, "section": p.section, "label": p.label, "unit": p.unit,
                "min": p.minimum, "max": p.maximum, "step": p.step,
                "decimals": p.decimals, "hint": p.hint, "default": defaults[p.key],
            }
            for p in PARAMS
        ],
    }
