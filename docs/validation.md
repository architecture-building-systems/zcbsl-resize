# Validation

Everything below is reproducible: `PYTHONPATH=src python -m pytest tests -q`.
The hand calculations use the shipped defaults, so you can check them with a
calculator and nothing else.

Default case: a 3.00 m wide x 4.00 m deep x 2.70 m high room with the south
wall and the roof exterior and everything else facing the lab at 21 C; south
wall 30% glazed; setpoints 16-30 C, 30-minute ramp, 3 ACH at 21 C / 60% RH, 2
occupants, 25 W/m2 equipment, 15% margin, Zurich pressure 96 500 Pa.

## 1. Areas

Width runs east-west and depth north-south, so the north and south walls are
width x height, the east and west walls are depth x height, and the roof and
floor are width x depth.

| Surface | By hand | Area |
| --- | --- | --- |
| North wall | 3.00 x 2.70 | 8.10 m2 |
| East wall | 4.00 x 2.70 | 10.80 m2 |
| South wall | 3.00 x 2.70 | 8.10 m2 |
| West wall | 4.00 x 2.70 | 10.80 m2 |
| Roof | 3.00 x 4.00 | 12.00 m2 |
| Floor | 3.00 x 4.00 | 12.00 m2 |
| **Interior total** | | **61.80 m2** |
| Volume | 3.00 x 4.00 x 2.70 | 32.40 m3 |

Every square metre belongs to a named surface. There is no residual bucket.

## 2. Conductances

Each surface carries its own opaque and glazing U-values, and its glazed share
comes from its own window-to-wall ratio.

| Surface | By hand | W/K |
| --- | --- | --- |
| South (30% glazed) | 1.20 x 5.67 + 1.40 x 2.43 | 10.206 |
| Roof (opaque) | 1.20 x 12.00 | 14.400 |
| North (interior) | 0.05 x 8.10 | 0.405 |
| East (interior) | 0.05 x 10.80 | 0.540 |
| West (interior) | 0.05 x 10.80 | 0.540 |
| Floor (interior) | 0.05 x 12.00 | 0.600 |
| **Envelope total** | | **26.691** |

## 3. Steady-state hold loads

Each surface faces a temperature set by its exposure: `T_face = T_lab +
exposure x (T_outdoor - T_lab)`. Exposed surfaces see -8 to -10 C in winter,
interior ones stay at the 21 C lab.

**Heating**, evaluated at the warm setpoint (30 C) against the winter boundary
(-10 C). Solar is ignored, which is conservative.

| Term | By hand | W |
| --- | --- | --- |
| South wall | 10.206 x (30 - (-10)) | 408.24 |
| Roof | 14.400 x 40 | 576.00 |
| North + east + west + floor | 2.085 x (30 - 21) | 18.77 |
| Ventilation | (3 x 32.4 x 1.2 / 3600) x 1005 x (30 - 21) | 293.06 |
| Internal gains | -(2 x 75 + 25 x 12) | -450.00 |
| **Hold** | | **846.06** |

The model returns 846.063 W.

**Cooling**, at the cold setpoint (16 C) against summer (35 C), with solar.

| Term | By hand | W |
| --- | --- | --- |
| South wall conduction | 10.206 x (35 - 16) | 193.91 |
| Solar through its glazing | 0.50 x 2.43 x 700 | 850.50 |
| Roof | 14.400 x 19 | 273.60 |
| North + east + west + floor | 2.085 x (21 - 16) | 10.43 |
| Ventilation | 0.0324 x 1005 x (21 - 16) | 162.81 |
| Internal gains | +450 | 450.00 |
| **Hold** | | **1941.25** |

The model returns 1941.249 W. Solar alone is 44% of it.

## 3a. Why the envelope is described surface by surface

The earlier version of this model had one facade plus a ceiling and lumped
everything else into an adiabatic residual. That works for a room embedded in a
building. It fails badly for a freestanding one.

The climate chamber is 8.00 x 4.50 x 12.00 m with its north, east and west
walls and its roof all exterior. Only the south wall and the floor face
interior space.

| | Single-facade model | Per-surface model |
| --- | --- | --- |
| Envelope conductance | 124.3 W/K | **310.7 W/K** |
| Exterior wall area treated as adiabatic | 204 m2 | 0 m2 |

A factor of 2.5, and the old model also had no slot at all for solar on the
east and west walls. `tests/test_physics.py` pins the corrected behaviour for
both real rooms, including that the module room's facade is its 3.75 m south
wall rather than whichever wall happens to be longest.

## 4. The ramp equation

For a lumped capacity under a linear ramp,

    C dT/dt = P(t) − UA (T − T_ext)

so holding dT/dt constant at ΔT / t_ramp means

    P(t) = C ΔT / t_ramp + UA (T(t) − T_ext)

which peaks at the far end of the ramp. That is exactly the
`hold + mass-charge` form of the **ramp mode**; it is not an approximation for
a lumped model. The hold in it is the one at the far setpoint *in ramp
conditions*: nobody inside, and only `ramp_equipment_pct` of the equipment
running (the default room keeps all of it, 300 W, and loses its two
occupants, 150 W). So the ramp hold is 846 + 150 = 996 W.

At defaults: C_total = 39 074 (air) + 927 000 (shell) = 966 074 J/K, so

    P_mass = 966 074 × 14 / 1800 = 7 514 W

and the heating ramp requirement is (996 + 7 514) × 1.15 = **9 786 W**.

The **operating mode** is the hold alone, 846 × 1.15 = 973 W. The design
capacity is the larger of the two, **9 786 W**, never their sum: the room is
either holding an experiment or ramping between two.

`tests/test_dynamic_reference.py` rebuilds the chamber as a differential
equation from the parameters alone, integrates it at 0.5-second steps, and
confirms:

- the peak of the required-power curve, integrated with the ramp-condition
  gains, matches `ramp hold + mass-charge` to within 0.01%, across ramp times
  from 10 to 240 minutes and with and without added mass, and with the Sun
  off as well as on;
- feeding that power in as a constant reaches setpoint at or before the target
  time;
- feeding in half of it does not (the control case, so the test above cannot
  pass by accident);
- running at the hold figure alone settles at exactly the setpoint.

## 5. Thermal mass is diffusion-limited

For a semi-infinite solid whose surface temperature rises linearly at rate `r`,

    T(x,t) − T₀ = 4 r t · i²erfc( x / (2√(αt)) )

Integrating the stored energy over depth and comparing with a layer raised
uniformly by `r t` gives an energy-equivalent participating depth

    d_eff = 4/(3√π) · √(αt) ≈ 0.752 √(αt)

For rammed earth (ρc = 1800 kJ/m³K, k = 1.25 W/mK, so α = 6.94 × 10⁻⁷ m²/s)
over a 30-minute ramp:

    d_eff = 0.752 × √(6.94e-7 × 1800) = 0.0266 m

So **27 mm of a 300 mm wall participates — 8.9% of it.**

`tests/test_mass.py` checks this against an independently written explicit 1D
finite-difference solve at ramp times from 10 to 480 minutes. Agreement is
better than 1%.

Consequence for 20 m² of 300 mm rammed earth on a 30-minute ramp:

| | Ramp power | Heating design |
| --- | --- | --- |
| Diffusion-limited (this tool) | 15.0 kW | 18.3 kW |
| Fully lumped (the old artifact) | 91.5 kW | 106.4 kW |

A factor of 5.8. The old number would have bought a machine nearly six times
larger than the physics calls for.

### The direction of the error

The closed form assumes the *surface* tracks the ramp perfectly, which needs
infinite film conductance. Real surfaces lag, so less mass participates than
this predicts and the sizing errs high. That is the safe direction, and
`test_analytical_model_is_conservative_against_a_real_surface_film` pins it.

## 6. The surface film limit

Heat enters the mass through combined convection and radiation, h ≈ 8 W/m²K
over the interior surface. At defaults:

    h·A = 8 × 61.8 = 494 W/K
    required air-to-surface ΔT = 7 514 / 494 = 15.2 K

So the air must run 15 K above the surfaces for the whole ramp — at the top of
the range, 45 °C air to bring surfaces to 30 °C. With 20 m² of rammed earth it
becomes 30 K, and the fastest ramp the film permits stretches from 30 to 61
minutes.

`tests/test_dynamic_reference.py` validates this with a two-node model (air
node and mass node coupled by h·A) in both regimes:

- **Ramp long compared with the mass time constant τ = C/(hA):** the coupled
  model's air-to-surface gap converges on the closed-form figure, within 10%.
- **Ramp short compared with τ:** the gap saturates at the size of the ramp
  itself. The mass never follows. This is the physically important case, and
  it is why the tool reports the required ΔT rather than silently assuming the
  mass comes along — the air hits setpoint while the radiant environment the
  experiment actually sees does not.

## 7. Psychrometrics

Saturation vapour pressure uses the ASHRAE Fundamentals (2017) Chapter 1
formulation, over ice below 0 °C and over liquid water above.

| T (°C) | ASHRAE table (Pa) | This implementation |
| --- | --- | --- |
| −10 | 259.9 | 259.9 |
| 0 | 611.2 | 611.2 |
| 20 | 2 338.8 | 2 338.8 |
| 25 | 3 169.2 | 3 169.2 |
| 30 | 4 246.0 | 4 246.0 |
| 40 | 7 384.9 | 7 384.9 |

Humidity ratio at 25 °C, 50% RH, sea level: **0.00988 kg/kg**, matching the
published value. Dew point at the same state: **13.9 °C**.

The suite also checks the inverse round-trip, saturated air (dew point equals
dry bulb), and the pressure effect — Zurich at 96 500 Pa holds about 5% more
moisture per kilogram of dry air than sea level, in the right proportion.
Where `psychrolib` is installed the two are compared directly across a grid of
states.

Latent load at defaults: incoming air at 21 °C / 60% RH carries
W = 0.00977 kg/kg; the chamber at 16 °C / 50% RH needs 0.00592 kg/kg. So

    0.0324 kg/s × (0.00977 − 0.00592) × 2.45e6 = 306 W

plus 90 W of occupant moisture, times the margin: **455 W**.

## 8. Sanity against published rules of thumb

| Check | Reference | Default case |
| --- | --- | --- |
| Radiant heating flux | EN 1264 / ISO 11855, ~100 W/m² in occupied zones | 176 W/m² over 4.8 m² — panels full, air carries the rest |
| Radiant cooling flux | ISO 11855, ~40–50 W/m² floor, ~90 W/m² chilled ceiling | 404 W/m² over 4.8 m² — panels full, air carries the rest |
| Occupant sensible/latent | ASHRAE Fundamentals, 75/45 W seated light work | used as defaults |
| Surface film coefficient | ~8 W/m²K combined interior, still air | used as default |
| Air density and cp | 1.2 kg/m³, 1005 J/kgK | used throughout |

The flux figures are the operating hold spread over the panels alone, to show
whether the panels *could* hold an experiment by themselves. They cannot at
the default 20 % of floor + ceiling (hung ceiling panels, decided
2026-09-23), and they are not expected to: the panels run at their limit in
both modes, and the air coil carries the rest. `tests/test_physics.py` checks
that split and that it never changes the room total.

## 9. Numerical robustness

`test_every_result_is_finite_across_the_whole_parameter_space` samples 4 000
random points across the full declared range of all 72 inputs simultaneously
and asserts every output is finite. Degenerate geometry, zero ventilation, zero
radiant area and inverted setpoints are all covered by their own tests.

## What is still unchecked

- Sol-air temperature on opaque surfaces is not modelled at all, by decision.
  Solar enters only through glazing, so an opaque wall or roof under 2 000 W/m²
  contributes nothing. At high irradiance this understates the cooling load
  materially.
- Per-surface irradiance is a peak value you supply, not a computed solar
  position. Nothing here knows the date, the latitude or the shading.
- The hot and cold tanks are assumed to hold 30 C and 10 C indefinitely, so
  nothing checks their discharge rate, the 70 kW interface heat pump, or what
  happens when all four rooms draw at once. See the fleet question in
  `assumptions.md`.
- COP is Carnot times an efficiency factor. Over the small lifts this
  arrangement gives, that produces numbers a real machine will not reach, since
  compressor minimum pressure ratio and part-load losses are not modelled.
  It is an upper bound, and it does not affect the thermal sizing at all.
- No validation against measured chamber data, because there is none yet. If
  the lab logs a real ramp, `tests/` is where that comparison belongs.
