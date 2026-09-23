# Context and assumptions

## The retrofit

The ZCBS Lab test chambers have an undersized HVAC supply for both heating and
cooling. Each chamber is adiabatic except for one reconfigurable facade and the
ceiling, both of which carry real boundary conditions. A radiant system exists
but is meant for in-experiment delivery, not rapid setpoint ramping.

Each chamber is moving to a **dedicated** heat pump — the pooled plant is being
retired because it cannot serve chambers that need different conditions at the
same time — backed by a hot and a cold 1000 L Pufferspeicher, tied into ETH's
anergy grid.

Scoped at a workshop on 2026-09-17.

## What the model covers

- Two modes, sized separately: **operating** (holding an experiment) and
  **ramp** (moving between setpoints). Design capacity is the larger of the
  two, never their sum. Decided 2026-09-23.
- Room-level supply air, sized per mode on what the radiant panels cannot
  carry, floored by baseline ventilation.
- Radiant system: hung ceiling panels, 20 % of floor + ceiling area, carrying
  load up to their limit in both modes. Decided 2026-09-23 (previously a
  steady-state check only).
- Per-room dedicated heat pump carrying the full design capacity, drawing on
  the tanks, or on outdoor air with the tanks switched off.
- Latent load and dehumidification.
- The physical ceiling on mass-charging rate imposed by the surface film.

Thermal mass is parametric rather than a fixed light/medium/heavy category,
because the lab is experimenting with different interior mass materials
(rammed earth at present).

Ramp time, setpoint range, window-to-wall ratio and facade construction are
workshop-exploration variables, not fixed inputs. That is the whole reason every input is a slider.

## Boundary conditions

- The facade's far side is an emulated extreme climate, a real driving load.
  Facade U-value, glazing U-value, window-to-wall ratio, SHGC and boundary
  temperature are all real, swappable variables.
- The facade is **the whole of the longest wall**, not a strip of it. The
  window-to-wall ratio splits that wall into glazed and opaque; there is no
  separate facade-width input.
- The ceiling is also a real boundary and sees **the same emulated climate** as
  the facade. It gets its own U-value but not its own temperatures.
- Only the floor and the three walls that are not the facade are treated as
  adiabatic, and even they carry a small residual U-value against the
  surrounding lab, since no real assembly is perfectly adiabatic.

At the default geometry the ceiling, at 12.0 m², is still marginally the
largest single conducting surface — the 10.8 m² facade only overtakes it once
the chamber is longer than it is wide by more than the ceiling's own area.
Worth confirming what is actually above it.

## Modelling assumptions

- **Operating and ramp never happen at once.** Design capacity is the larger
  of the two modes, each with its margin.
- **Linear ramp.** Peak instantaneous power is evaluated at the target
  setpoint, the worst instant against the boundary. Exact for a lumped
  capacity; see `validation.md`.
- **Ramp conditions.** During a ramp the boundary stays at the extreme design
  condition (including real sun through glazing), but nobody is inside and the
  Artificial Sun is off. Only `ramp_equipment_pct` of the equipment runs: 0 %
  for the climate chamber, 100 % for the module room, whose computers and
  small electronics stay on.
- **Hung radiant panels** carry up to their W/m² limit in either mode. They
  hang clear of the structure, so they do not charge the mass directly and the
  surface-film limit is unchanged by them.
- **Diffusion-limited mass.** Only the depth heat reaches within the ramp
  counts, from the closed-form linear-ramp solution for a semi-infinite solid.
  This assumes the surface follows the ramp perfectly, so it overstates
  participating mass and the sizing errs high.
- **Surface film check.** Mass charging is capped at `h × A × ΔT_allowed`. This
  is reported separately rather than folded into the capacity, because it is
  not a capacity problem and cannot be solved by buying a bigger machine.
- **Winter heating ignores solar gain** (conservative). Summer cooling includes
  it through SHGC × glazed area × irradiance.
- **No sol-air correction.** Opaque surfaces are driven by air temperature
  only, so solar enters exclusively through glazing. At high irradiance on a
  dark opaque roof this understates the cooling load, by decision, to keep the
  input set small.
- **Irradiance is a peak figure you supply per surface**, not a computed solar
  position. The model knows nothing of date, latitude or shading, and applies
  every surface's peak simultaneously in the cooling case, which cannot happen
  in reality. That is deliberately conservative.
- **Latent load** uses ASHRAE psychrometrics from dry-bulb and RH on both
  sides, sized at the cold setpoint. It does not model coil bypass, reheat, or
  moisture buffering in the room's own materials.
- **The tanks are an unlimited source at fixed temperature** (30 C hot, 10 C
  cold), because the 70 kW interface heat pump on the anergy network holds them
  there. They are not a store, so nothing absorbs the ramp surge and each
  room's machine carries its full design capacity.
- **The tanks can be switched off** (`tank_enabled = 0`). The machine then
  works against outdoor air at the winter and summer design temperatures,
  across an outdoor coil approach of 8 K by default, and the tanks see
  nothing. No free cooling is possible at summer design conditions.
- **Each duty exchanges with the tank on its own side**: heating lifts from the
  hot tank to the supply temperature, cooling lifts from the supply temperature
  to the cold tank. If the return actually goes to the warm side, set
  `tank_temp_cold` to the hot tank's value and the cooling COP falls sharply.
- **COP is Carnot times an efficiency factor**, not a manufacturer curve. Over
  the small lifts an anergy network gives, this produces high numbers that a
  real machine will not reach: compressors have a minimum pressure ratio and
  part-load losses that are not modelled. Treat the COP as an upper bound and
  detune `carnot_efficiency` to taste.
- **Nothing at fleet level is modelled.** Four rooms share two tanks and one
  70 kW interface pump; whether that holds up is the open question below.
- Fan heat, duct gain, filter pressure drop and defrost energy are excluded.
  That is what the margin slider is for.

## Two numbers to keep separate at the workshop

**Operating** and **ramp** are different questions with different drivers, and
the design capacity is whichever is larger, not both added. A 20 kW hold and a
40 kW ramp need a 40 kW room, provided the 40 kW already includes the hold at
the far end of the ramp in ramp conditions, which it does here. The browser
tool shows both side by side and the ramp time past which the operating mode
takes over.

(An earlier version of this section described a buffer tank absorbing the
ramp surge. That is not the arrangement: the tanks are a source, and the room's
machine carries the full design capacity.)

## Open items

- East and west peak irradiance on the climate chamber is set to 550 W/m2 as an
  assumption. Only the north figure of 400 W/m2 was given.
- Every exposed surface takes its peak irradiance at once in the cooling case.
  For a room with three exposed walls facing different directions that is
  pessimistic; a real worst hour would have one or two of them near peak.
- Decide the allowable air-to-surface ΔT. It is the parameter that decides
  whether a ramp target is reachable, and nobody has put a number on it yet.
  15 K is a placeholder.
- Agree a ramp time. Below the film limit the question stops being about
  equipment.
- Radiant panels are set at 20 % of floor + ceiling (40 % of the ceiling),
  although they physically cover closer to 75 % of the ceiling. Confirm the
  lower figure is deliberate.
- Latent load is reported separately and is not part of the cooling capacity.
