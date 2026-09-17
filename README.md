# zcbsl-resize

Sizing tools for the ZCBS Lab environmental test chambers, built for the HVAC
retrofit where each chamber moves to a dedicated heat pump backed by hot and
cold Pufferspeicher on ETH's anergy grid.

The physics is a Python package. A small Flask app serves a browser front end
for the interactive case; there is no second implementation of the model in
JavaScript, so the page and a scenario sweep can never disagree.

## Why it exists

"The HVAC is undersized" turns out to be three separate problems that are fixed
in different ways:

| Problem | What sets it | What fixes it |
| --- | --- | --- |
| **Ramping** between setpoints | Total heat capacity over the time allowed | More coil capacity, less mass, or more time |
| **Holding** a setpoint | Envelope, ventilation, internal gains | Radiant capacity, envelope, plant |
| **Plant sizing** | Steady hold plus whatever the buffer cannot absorb | Bigger tank, longer recharge window |

And a fourth constraint that no amount of equipment touches: heat only crosses
from the room air into the thermal mass through a surface film of roughly
8 W/m²K. Past a certain mass and a certain ramp time, the air would have to run
further from the surfaces than any experiment tolerates, and the ramp becomes
unreachable. That check is a first-class output here.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run the interactive tool

```bash
PYTHONPATH=src python -m zcbsl_resize.server
# http://127.0.0.1:5000
```

Sliders post the parameter set to `/api/compute` and the page redraws. Scenario
save and load write and read the same JSON format the Python API uses.

## Use it as a library

```python
from zcbsl_resize import ChamberParams, compute

params = ChamberParams(ramp_minutes=45, added_mass_area=20, added_mass_thickness=0.30)
r = compute(params)

print(r["heating_design"] / 1000, "kW at the coil")
print(r["plant_heating"] / 1000, "kW at the heat pump")
print(r["min_feasible_ramp_minutes"], "min is the fastest the surface film allows")
```

Every input accepts a numpy array, and every output broadcasts, so a sweep is
one call rather than a loop.

## Scenarios and combinatorics

```python
from zcbsl_resize import ChamberParams, save_scenario
from zcbsl_resize.scenarios import grid_sweep, sensitivity_ranking, latin_hypercube

df = grid_sweep(ChamberParams(), {
    "ramp_minutes": [15, 30, 45, 60, 120],
    "added_mass_area": [0, 10, 20, 40],
    "added_mass_thickness": [0.10, 0.20, 0.30],
    "ach": [1, 3, 6, 12],
})                                   # 240 rows, inputs and outputs side by side

ranked = sensitivity_ranking(ChamberParams(), output="heating_design")
sample = latin_hypercube(ChamberParams(), {"ramp_minutes": (10, 120)}, n=5000, seed=1)

save_scenario(ChamberParams(ramp_minutes=45), "scenarios/slow-ramp.json",
              name="45 min ramp", sweeps={"added_mass_area": [0, 10, 20, 40]})
```

A million cases run in a few seconds. `grid_sweep` refuses anything above five
million unless you raise `max_cases` on purpose.

## Trusting the numbers

```bash
PYTHONPATH=src python -m pytest tests -q
```

The suite checks four different things, deliberately:

- **Arithmetic.** Steady-state loads are rebuilt by hand in the tests, so
  `U × A × ΔT` has nowhere to hide. See `docs/validation.md` for the same
  calculations written out for a calculator.
- **Psychrometrics** against published ASHRAE saturation-pressure and humidity-
  ratio table values, and against `psychrolib` when it is installed
  (`pip install -r requirements-dev.txt`).
- **The mass model** against an independently written 1D finite-difference
  solve of the same slab. The closed form and the numerical solve agree to
  better than 1%.
- **The ramp equation** against a time-stepped model of the chamber built from
  the parameters without reference to `physics.py`, including a control case
  where deliberately undersized capacity fails to reach setpoint.

`docs/validation.md` has the worked numbers. `docs/assumptions.md` records what
the model does not do.

## Layout

```
src/zcbsl_resize/
  params.py       parameter schema, defaults, scenario JSON
  physics.py      the model; numpy-safe, scalar or array
  mass.py         diffusion-limited thermal mass + FD reference solver
  psychro.py      ASHRAE psychrometrics
  scenarios.py    grid sweeps, sensitivity, Latin hypercube -> DataFrame
  server.py       Flask API
  web/            browser front end (no physics)
tests/            arithmetic, limits, validation against independent models
docs/             assumptions and worked validation
scenarios/        saved parameter sets
```

## Relationship to the workshop artifact

This repo supersedes the Chamber Ramp Sizer artifact from the 2026-09-17
workshop, which is frozen as the record of what the room saw that day. The
numbers here differ from it deliberately:

- Thermal mass is diffusion-limited rather than fully lumped. For thick, dense
  layers the old tool overstated the ramp requirement by roughly 6×.
- The facade has separate opaque and glazing U-values.
- The ceiling shares the facade's emulated climate instead of having its own
  boundary temperatures.
- Equipment gains are per square metre of floor, up to 500 W/m².
- Latent load comes from real psychrometrics on both air states rather than a
  "moisture excess" figure nobody could estimate.
- The surface-film limit on mass charging is new, and it often binds first.

`compute(params, lumped_mass=True)` reproduces the old mass treatment if you
need to explain a number someone wrote down at the workshop.

## Not modelled

Sol-air temperature on opaque surfaces, fan and duct heat, control-loop
dynamics, coil bypass and reheat, the buffer tank's own discharge rate, the
anergy-grid source side and heat-pump COP, and staggered scheduling across
chambers. A first-pass sizing envelope, not a mechanical engineer's load
calculation.
