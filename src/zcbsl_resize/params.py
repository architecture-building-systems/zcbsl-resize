"""Parameter schema for the chamber sizing model.

One source of truth: the dataclass below holds defaults and types, the
``PARAMS`` list holds everything the UI needs to render a control for each
field.  ``tests/test_params.py`` asserts the two never drift apart.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Iterable


# --------------------------------------------------------------------------
# Section metadata (order here is the order the UI renders them)
# --------------------------------------------------------------------------

SECTIONS: list[dict[str, str]] = [
    {
        "key": "geometry",
        "title": "Geometry",
        "blurb": "Internal clear dimensions of the chamber. The longest wall carries the reconfigurable facade.",
    },
    {
        "key": "mass",
        "title": "Thermal mass",
        "blurb": "The bare shell, plus any deliberate mass element (rammed earth, concrete) added inside it.",
    },
    {
        "key": "envelope",
        "title": "Envelope",
        "blurb": "Opaque and glazed facade separately, how much of the wall is glazed, plus the ceiling and the residual adiabatic surfaces.",
    },
    {
        "key": "boundary",
        "title": "Emulated climate",
        "blurb": "The conditions on the far side of the facade and ceiling. Both see the same emulated climate.",
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
        "blurb": "Each chamber's own heat pump, its hot and cold Pufferspeicher, and the shared grid tie-in.",
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
# Material presets for the added-mass layer
# --------------------------------------------------------------------------

MASS_PRESETS: dict[str, dict[str, float | str]] = {
    "rammed_earth": {
        "label": "Rammed earth",
        "rho_c": 1800.0,  # kJ/m3K  (~2000 kg/m3 x ~900 J/kgK)
        "k": 1.25,  # W/mK
        "note": "Stabilised rammed earth, the material currently in the chamber.",
    },
    "dense_concrete": {
        "label": "Dense concrete",
        "rho_c": 2100.0,
        "k": 1.80,
        "note": "2300 kg/m3 normal-weight concrete.",
    },
    "brick": {
        "label": "Solid brick",
        "rho_c": 1360.0,
        "k": 0.80,
        "note": "1700 kg/m3 fired clay brick.",
    },
    "gypsum": {
        "label": "Gypsum board",
        "rho_c": 810.0,
        "k": 0.25,
        "note": "Lightweight lining; saturates within minutes, so it behaves as pure capacitance.",
    },
    "water_wall": {
        "label": "Water (PCM stand-in)",
        "rho_c": 4186.0,
        "k": 0.60,
        "note": "Upper bound on sensible storage density; convection inside the container is not modelled.",
    },
}


# --------------------------------------------------------------------------
# The parameter set
# --------------------------------------------------------------------------

PARAMS: list[Param] = [
    # ---- geometry -------------------------------------------------------
    Param("length", "geometry", "Length", "m", 0.5, 20.0, 0.1, 1,
          "Internal clear dimension."),
    Param("width", "geometry", "Width", "m", 0.5, 20.0, 0.1, 1,
          "Internal clear dimension."),
    Param("height", "geometry", "Height", "m", 0.5, 20.0, 0.1, 1,
          "Internal clear dimension, floor to ceiling."),

    # ---- thermal mass ---------------------------------------------------
    Param("base_shell_capacity", "mass", "Baseline shell capacitance", "kJ/m²K", 5.0, 200.0, 5.0, 0,
          "The bare chamber shell spread over all interior surfaces, treated as fully participating. "
          "Lightweight panel ≈15 · gypsum + insulation ≈40 · masonry ≈150."),
    Param("added_mass_area", "mass", "Added mass: area", "m²", 0.0, 400.0, 1.0, 0,
          "Surface area the deliberate mass element covers. Zero disables the whole added-mass term."),
    Param("added_mass_thickness", "mass", "Added mass: thickness", "m", 0.02, 1.0, 0.01, 2,
          "Physical depth of the layer. Only the part the heat actually reaches within the ramp counts."),
    Param("added_mass_rho_c", "mass", "Added mass: ρc", "kJ/m³K", 200.0, 4500.0, 10.0, 0,
          "Volumetric heat capacity. Rammed earth ≈1800 · concrete ≈2100 · brick ≈1360."),
    Param("added_mass_k", "mass", "Added mass: conductivity", "W/mK", 0.05, 3.5, 0.05, 2,
          "Thermal conductivity. With ρc it sets diffusivity α = k/ρc, which decides how deep the ramp reaches."),

    # ---- envelope -------------------------------------------------------
    Param("facade_u_opaque", "envelope", "Facade U, opaque", "W/m²K", 0.08, 3.5, 0.01, 2,
          "Opaque part of the facade assembly."),
    Param("facade_u_glazing", "envelope", "Facade U, glazing", "W/m²K", 0.40, 6.0, 0.05, 2,
          "Glazed part. Triple ≈0.7 · double ≈1.2 · old double ≈2.8 · single ≈5.7."),
    Param("wwr", "envelope", "Window-to-wall ratio", "%", 0.0, 100.0, 1.0, 0,
          "Glazed share of the facade wall, which is the whole of the longest wall. "
          "The rest of it uses the opaque U-value."),
    Param("shgc", "envelope", "Glazing SHGC", "", 0.05, 0.90, 0.01, 2,
          "Solar heat gain coefficient of the glazed portion."),
    Param("ceiling_u", "envelope", "Ceiling U", "W/m²K", 0.08, 3.5, 0.01, 2,
          "The ceiling is a real boundary and sees the same emulated climate as the facade."),
    Param("residual_u", "envelope", "Residual U, floor + walls", "W/m²K", 0.0, 0.5, 0.01, 2,
          "Floor and remaining walls are nominally adiabatic; no real assembly is, so they get a small U "
          "against the surrounding lab."),
    Param("surrounding_temp", "envelope", "Surrounding lab temp", "°C", 10.0, 32.0, 0.5, 1,
          "What the nominally adiabatic surfaces face."),

    # ---- emulated climate ----------------------------------------------
    Param("boundary_temp_winter", "boundary", "Winter boundary temp", "°C", -35.0, 20.0, 0.5, 1,
          "Air temperature behind the facade and above the ceiling in the heating design case."),
    Param("boundary_temp_summer", "boundary", "Summer boundary temp", "°C", 10.0, 60.0, 0.5, 1,
          "Air temperature behind the facade and above the ceiling in the cooling design case."),
    Param("solar_irradiance", "boundary", "Irradiance on facade", "W/m²", 0.0, 2000.0, 25.0, 0,
          "Applied to the glazed area through the SHGC. Above ~1100 W/m² this is a lamp array, not the sun. "
          "Opaque surfaces are driven by air temperature only — no sol-air correction."),
    Param("boundary_rh", "boundary", "Boundary air RH", "%", 5.0, 100.0, 1.0, 0,
          "Relative humidity of the emulated climate. Only used if ventilation air is drawn from it."),

    # ---- setpoints & ramp ----------------------------------------------
    Param("setpoint_min", "setpoints", "Min setpoint", "°C", -10.0, 40.0, 0.5, 1,
          "Coldest chamber condition the experiments need."),
    Param("setpoint_max", "setpoints", "Max setpoint", "°C", -5.0, 50.0, 0.5, 1,
          "Warmest chamber condition the experiments need."),
    Param("ramp_minutes", "setpoints", "Target ramp time", "min", 5.0, 480.0, 5.0, 0,
          "Time allowed to move the full setpoint range. Watch the sensitivity chart as you drag this."),
    Param("margin_pct", "setpoints", "Safety margin", "%", 0.0, 50.0, 5.0, 0,
          "Applied to final capacities. Covers control lag, fan and duct heat, heat-exchanger approach."),

    # ---- ventilation & gains -------------------------------------------
    Param("ach", "ventilation", "Air changes per hour", "1/h", 0.0, 20.0, 0.5, 1,
          "Outdoor-air ventilation rate. High values are common in chambers doing contaminant or "
          "ventilation-effectiveness work."),
    Param("vent_supply_temp", "ventilation", "Ventilation air temp", "°C", -35.0, 60.0, 0.5, 1,
          "Set this to the boundary temperature if fresh air is drawn straight from the emulated climate."),
    Param("vent_supply_rh", "ventilation", "Ventilation air RH", "%", 5.0, 100.0, 1.0, 0,
          "Humidity of the incoming air before the coil sees it."),
    Param("target_rh", "ventilation", "Chamber target RH", "%", 10.0, 90.0, 1.0, 0,
          "The relative humidity the chamber has to hold. The gap between this and the incoming air is the "
          "latent load."),
    Param("occupants", "ventilation", "Occupants", "", 0.0, 20.0, 1.0, 0,
          "People in the chamber during an experiment."),
    Param("sensible_per_person", "ventilation", "Sensible per person", "W", 40.0, 200.0, 5.0, 0,
          "ASHRAE Fundamentals: ~70 W seated, ~75 W light office work, ~130 W light machine work."),
    Param("latent_per_person", "ventilation", "Latent per person", "W", 20.0, 200.0, 5.0, 0,
          "ASHRAE Fundamentals: ~45 W seated, ~55 W light work, rising steeply with activity."),
    Param("equipment_w_per_m2", "ventilation", "Equipment & lighting", "W/m²", 0.0, 500.0, 5.0, 0,
          "Per square metre of floor. Office-like ≈15 · dense instrumentation ≈50 · a large lighting "
          "or solar-simulator rig can reach several hundred."),

    # ---- delivery limits ------------------------------------------------
    Param("radiant_fraction", "delivery", "Radiant active area", "%", 0.0, 100.0, 5.0, 0,
          "Share of floor + ceiling that is actively radiant."),
    Param("radiant_heat_limit", "delivery", "Radiant heating limit", "W/m²", 20.0, 200.0, 5.0, 0,
          "EN 1264 / ISO 11855: ~100 W/m² for floor heating in occupied zones, higher in peripheral areas."),
    Param("radiant_cool_limit", "delivery", "Radiant cooling limit", "W/m²", 10.0, 120.0, 5.0, 0,
          "Condensation-limited. ISO 11855: ~40-50 W/m² floor, up to ~90 W/m² for chilled ceilings."),
    Param("supply_dt", "delivery", "Max supply-air ΔT", "K", 3.0, 30.0, 1.0, 0,
          "Coil-to-room temperature difference. Raising it shrinks the airflow but risks dumping and "
          "stratification during a ramp."),
    Param("surface_film_h", "delivery", "Surface film coefficient", "W/m²K", 2.0, 20.0, 0.5, 1,
          "Combined convective + radiative heat transfer between room air and interior surfaces. "
          "~8 W/m²K is the standard still-air value; forced air over the surfaces raises it."),
    Param("max_air_surface_dt", "delivery", "Allowable air-to-surface ΔT", "K", 2.0, 60.0, 1.0, 0,
          "How far the air is allowed to run from the surfaces while charging the mass. This is what "
          "decides whether a ramp time is physically reachable at all."),

    # ---- plant ----------------------------------------------------------
    Param("buffer_volume_l", "plant", "Buffer volume, per tank", "L", 100.0, 5000.0, 50.0, 0,
          "One hot and one cold Pufferspeicher of this size."),
    Param("buffer_dt", "plant", "Usable buffer ΔT", "K", 3.0, 40.0, 1.0, 0,
          "Temperature swing the tank can actually give up before it stops being useful."),
    Param("recharge_minutes", "plant", "Recharge window", "min", 10.0, 480.0, 5.0, 0,
          "Time the heat pump has to refill the buffer before the next ramp."),
    Param("n_chambers", "plant", "Chambers on the tie-in", "", 1.0, 12.0, 1.0, 0,
          "For the aggregate anergy-grid figure only."),
    Param("diversity_pct", "plant", "Simultaneity", "%", 10.0, 100.0, 5.0, 0,
          "Share of chambers assumed to peak together. Does not model staggered scheduling or N+1."),

    # ---- site -----------------------------------------------------------
    Param("pressure_pa", "site", "Atmospheric pressure", "Pa", 80000.0, 103000.0, 100.0, 0,
          "Sea level 101325 Pa; Zurich at ~410 m is about 96500 Pa. Shifts humidity ratios by a few percent."),
]

PARAMS_BY_KEY: dict[str, Param] = {p.key: p for p in PARAMS}


# --------------------------------------------------------------------------
# The dataclass
# --------------------------------------------------------------------------

@dataclass
class ChamberParams:
    """All model inputs. Defaults reproduce the workshop's first-pass case."""

    # geometry
    length: float = 4.0
    width: float = 3.0
    height: float = 2.7

    # thermal mass
    base_shell_capacity: float = 15.0
    added_mass_area: float = 0.0
    added_mass_thickness: float = 0.30
    added_mass_rho_c: float = 1800.0
    added_mass_k: float = 1.25

    # envelope
    facade_u_opaque: float = 1.20
    facade_u_glazing: float = 1.40
    wwr: float = 30.0
    shgc: float = 0.50
    ceiling_u: float = 1.20
    residual_u: float = 0.05
    surrounding_temp: float = 21.0

    # emulated climate
    boundary_temp_winter: float = -10.0
    boundary_temp_summer: float = 35.0
    solar_irradiance: float = 700.0
    boundary_rh: float = 60.0

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

SCENARIO_FORMAT = 1


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
        raise ValueError(f"scenario format {fmt!r} is not supported (expected {SCENARIO_FORMAT})")
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
        "params": [
            {
                "key": p.key,
                "section": p.section,
                "label": p.label,
                "unit": p.unit,
                "min": p.minimum,
                "max": p.maximum,
                "step": p.step,
                "decimals": p.decimals,
                "hint": p.hint,
                "default": defaults[p.key],
            }
            for p in PARAMS
        ],
    }
