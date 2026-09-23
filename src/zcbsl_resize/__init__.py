"""Sizing tools for the ZCBS Lab environmental test chambers.

Quick start::

    from zcbsl_resize import ChamberParams, compute
    r = compute(ChamberParams(ramp_minutes=45, added_mass_coverage=20))
    print(r["heating_design"] / 1000, "kW")
"""

from .params import ChamberParams, DEFAULTS, MASS_PRESETS, PARAMS, load_scenario, save_scenario, schema
from . import sensitivity, study
from .physics import compute, fastest_ramp_minutes, mode_crossover_minutes

__all__ = [
    "ChamberParams",
    "DEFAULTS",
    "MASS_PRESETS",
    "PARAMS",
    "compute",
    "fastest_ramp_minutes",
    "mode_crossover_minutes",
    "sensitivity",
    "study",
    "load_scenario",
    "save_scenario",
    "schema",
]
__version__ = "0.1.0"
