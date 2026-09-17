# Validation

Everything below is reproducible: `PYTHONPATH=src python -m pytest tests -q`.
The hand calculations use the shipped defaults, so you can check them with a
calculator and nothing else.

Default case: 4.0 × 3.0 × 2.7 m chamber, 3.0 m wide facade at 30% glazing,
setpoints 16–30 °C, 30-minute ramp, 3 ACH at 21 °C / 60% RH, 2 occupants,
25 W/m² equipment, 15% margin, Zurich pressure 96 500 Pa.

## 1. Areas

| Quantity | By hand | Model |
| --- | --- | --- |
| Volume | 4.0 × 3.0 × 2.7 | 32.4 m³ |
| Interior surface | 2 × (12.0 + 10.8 + 8.1) | 61.8 m² |
| Facade | 3.0 × 2.7 | 8.10 m² |
| — glazed | 8.10 × 0.30 | 2.43 m² |
| — opaque | 8.10 × 0.70 | 5.67 m² |
| Ceiling | 4.0 × 3.0 | 12.0 m² |
| Residual adiabatic | 61.8 − 8.1 − 12.0 | 41.7 m² |

## 2. Steady-state heating hold

Evaluated at the warm setpoint (30 °C) against the winter boundary (−10 °C),
so ΔT = 40 K. Solar is ignored in the heating case, which is conservative.

| Term | By hand | W |
| --- | --- | --- |
| Opaque facade | 1.20 × 5.67 × 40 | 272.2 |
| Glazed facade | 1.40 × 2.43 × 40 | 136.1 |
| Ceiling | 1.20 × 12.0 × 40 | 576.0 |
| Residual surfaces | 0.05 × 41.7 × (30 − 21) | 18.8 |
| Ventilation | (3 × 32.4 × 1.2 / 3600) × 1005 × (30 − 21) | 293.1 |
| Internal gains | −(2 × 75 + 25 × 12) | −450.0 |
| **Hold** | | **846.1** |

The model returns 846.063 W.

Note what dominates: the ceiling, at 576 W, is more than the whole facade. It
is the largest single surface facing the emulated climate, and it has the same
U-value. Worth a look during the workshop.

## 3. Steady-state cooling hold

At the cold setpoint (16 °C) against the summer boundary (35 °C), ΔT = 19 K,
with solar included.

| Term | By hand | W |
| --- | --- | --- |
| Opaque facade | 1.20 × 5.67 × 19 | 129.3 |
| Glazed facade | 1.40 × 2.43 × 19 | 64.6 |
| Ceiling | 1.20 × 12.0 × 19 | 273.6 |
| Solar through glazing | 0.50 × 2.43 × 700 | 850.5 |
| Residual surfaces | 0.05 × 41.7 × (21 − 16) | 10.4 |
| Ventilation | 0.0324 × 1005 × (21 − 16) | 162.8 |
| Internal gains | +450 | 450.0 |
| **Hold** | | **1941.2** |

The model returns 1941.25 W. Solar alone is 44% of it, which is why the
irradiance slider now reaches 2000 W/m².

## 4. The ramp equation

For a lumped capacity under a linear ramp,

    C dT/dt = P(t) − UA (T − T_ext)

so holding dT/dt constant at ΔT / t_ramp means

    P(t) = C ΔT / t_ramp + UA (T(t) − T_ext)

which peaks at the far end of the ramp. That is exactly the
`hold + mass-charge` form the tool reports; it is not an approximation for a
lumped model.

At defaults: C_total = 39 074 (air) + 927 000 (shell) = 966 074 J/K, so

    P_mass = 966 074 × 14 / 1800 = 7 514 W

and the heating design becomes (846 + 7 514) × 1.15 = **9 614 W**.

`tests/test_dynamic_reference.py` rebuilds the chamber as a differential
equation from the parameters alone, integrates it at 0.5-second steps, and
confirms:

- the peak of the required-power curve matches `hold + mass-charge` to within
  0.01%, across ramp times from 10 to 240 minutes and with and without added
  mass;
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
| Diffusion-limited (this tool) | 15.0 kW | 18.2 kW |
| Fully lumped (the old artifact) | 91.5 kW | 105.9 kW |

A factor of 6.1. The old number would have bought a machine six times larger
than the physics calls for.

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
| Radiant heating flux | EN 1264 / ISO 11855, ~100 W/m² in occupied zones | 59 W/m² — within limit |
| Radiant cooling flux | ISO 11855, ~40–50 W/m² floor, ~90 W/m² chilled ceiling | 135 W/m² — **exceeds**, air must carry the rest |
| Occupant sensible/latent | ASHRAE Fundamentals, 75/45 W seated light work | used as defaults |
| Surface film coefficient | ~8 W/m²K combined interior, still air | used as default |
| Air density and cp | 1.2 kg/m³, 1005 J/kgK | used throughout |

The radiant cooling result is a real finding, not a modelling artefact: solar
gain through the glazing puts the steady cooling load well beyond what radiant
surfaces can shed, so the air system carries it continuously on top of its ramp
duty.

## 9. Numerical robustness

`test_every_result_is_finite_across_the_whole_parameter_space` samples 4 000
random points across the full declared range of all 44 inputs simultaneously
and asserts every output is finite. Degenerate geometry, zero ventilation, zero
radiant area and inverted setpoints are all covered by their own tests.

## What is still unchecked

- Sol-air temperature on opaque surfaces is not modelled at all, by decision.
  At 2 000 W/m² on a dark opaque roof this understates the cooling load
  materially.
- The buffer tank check verifies stored energy only, never its discharge rate.
- No validation against measured chamber data, because there is none yet. If
  the lab logs a real ramp, `tests/` is where that comparison belongs.
