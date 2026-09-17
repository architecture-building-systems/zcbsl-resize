"""Worked example: how much rammed earth can the chambers carry?

Run with:  PYTHONPATH=src python examples/rammed_earth_study.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from zcbsl_resize import ChamberParams, save_scenario
from zcbsl_resize.scenarios import grid_sweep, sensitivity_ranking

pd.set_option("display.width", 160)

base = ChamberParams()

# --- 1. Where does the ramp target stop being physically reachable? --------
sweep = grid_sweep(
    base,
    {
        "added_mass_area": [0, 10, 20, 40],
        "added_mass_thickness": [0.02, 0.05, 0.10, 0.30],
        "ramp_minutes": [15, 30, 60, 120],
    },
)

table = sweep.pivot_table(
    index=["added_mass_area", "added_mass_thickness"],
    columns="ramp_minutes",
    values="film_ok",
    aggfunc="first",
)
print("Is the ramp reachable at all? (surface-film check)\n")
print(table.map(lambda ok: "yes" if ok else "NO"))

# --- 2. What does the coil actually have to be? ---------------------------
print("\n\nHeating design capacity, kW\n")
print(
    sweep.pivot_table(
        index=["added_mass_area", "added_mass_thickness"],
        columns="ramp_minutes",
        values="heating_design",
        aggfunc="first",
    ).div(1000).round(1)
)
print("\nThickness stops mattering once the layer is deeper than heat reaches")
print("in the ramp: 27 mm for rammed earth at 30 minutes.")

# --- 3. How wrong was the lumped assumption? ------------------------------
limited = grid_sweep(base, {"added_mass_area": [0, 10, 20, 40]})
lumped = grid_sweep(base, {"added_mass_area": [0, 10, 20, 40]}, lumped_mass=True)
print("\n\nRamp power, kW: diffusion-limited vs. fully lumped\n")
print(
    pd.DataFrame(
        {
            "added_mass_area": limited["added_mass_area"],
            "diffusion_limited_kW": (limited["power_mass"] / 1000).round(1),
            "lumped_kW": (lumped["power_mass"] / 1000).round(1),
            "overstatement": (lumped["power_mass"] / limited["power_mass"]).round(1),
        }
    ).to_string(index=False)
)

# --- 4. Which inputs actually move the answer? ----------------------------
print("\n\nTop 10 movers for heating design capacity\n")
ranked = sensitivity_ranking(base.replace(added_mass_area=20.0), output="heating_design")
print(ranked.head(10)[["label", "unit", "low", "high", "span"]].round(0).to_string(index=False))

# --- 5. Save the case worth bringing to the workshop ----------------------
save_scenario(
    base.replace(added_mass_area=20.0, ramp_minutes=60.0),
    "scenarios/rammed-earth-60min.json",
    name="20 m2 rammed earth, 60 min ramp",
    notes="The shortest ramp the surface film permits with this much mass.",
    sweeps={"ramp_minutes": list(np.arange(30, 181, 15))},
)
print("\nSaved scenarios/rammed-earth-60min.json")
