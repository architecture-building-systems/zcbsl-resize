"""Validate study/rooms.yaml against the model and report what it will run.

    python study/check_config.py [path]

Three jobs:

* **Errors.**  Every parameter name exists and every range sits inside the
  model's own declared limits.  Anything wrong here exits non-zero.
* **Overrides.**  Anything in the config standing on top of a value rooms.py
  sets deliberately gets named.  A room's baseline is not a suggestion: the
  shell is 7.0 kJ/m2K because the room is lined in aluminium, and a config
  that sweeps 5 to 15 has quietly replaced a measured property with a guess.
  This is a warning, not an error -- sometimes an override is exactly what you
  mean -- but it is never silent again.
* **Size.**  How many rows each grid produces and what the Sobol sample costs,
  so a sweep that will not fit in memory is obvious before you start it.

The parsing lives in ``zcbsl_resize.study`` so that this script and the
notebooks cannot drift apart in how they read the same file.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from zcbsl_resize import study as study_mod  # noqa: E402
from zcbsl_resize.params import PARAMS_BY_KEY  # noqa: E402

#: Parameters worth calling out with their declared range and unit, because
#: they are easy to misread without it (a percent looks like a bare number
#: otherwise).
HIGHLIGHT = {"added_mass_coverage"}


def describe_room(room: study_mod.RoomConfig, config: study_mod.StudyConfig) -> None:
    print(f"  {room.label}")
    print(
        f"    {len(room.specs)} parameters set here, "
        f"{len(PARAMS_BY_KEY) - len(room.specs)} from baseline rooms.{room.base}()"
    )
    print(
        f"    interior surface {room.interior_area:,.0f} m2 · floor {room.floor_area:,.0f} m2"
    )

    varying = room.varying
    bounds = sorted(k for k, s in room.specs.items() if s.kind == "bounds")
    print(f"    varying: {len(varying)}  (of which bounds-only: {len(bounds)})")

    for key in sorted(HIGHLIGHT & set(room.specs)):
        spec = room.specs[key]
        unit = PARAMS_BY_KEY[key].unit
        print(f"    {key}: {spec.low:,.0f}..{spec.high:,.0f} {unit}")

    overrides = room.overrides()
    if overrides:
        print("    overrides rooms.py:")
        for over in overrides:
            mark = "!!" if over.excludes_baseline else " ·"
            print(f"      {mark} {over.describe()}")
            if over.excludes_baseline:
                print("         the room's own value is never evaluated")

    for name, axes in config.grids.items():
        shape = room.grid_shape(axes)
        rows = 1
        detail = []
        for axis, points in shape.items():
            rows *= len(points)
            if len(points) > 1:
                detail.append(f"{axis}={len(points)}")
            elif axis in room.specs and room.specs[axis].kind == "bounds":
                detail.append(f"{axis}@midpoint")
        if not any(len(p) > 1 for p in shape.values()):
            print(f"    grid '{name}': not applicable, every axis is fixed for this room")
        else:
            print(f"    grid '{name}': {rows:,} rows  ({' x '.join(detail)})")

    k = len(varying)
    cost = config.sobol.n * (k + 2)
    print(f"    sobol: {k} factors x n={config.sobol.n:,} -> {cost:,} evaluations")
    print()


def main(path: Path) -> int:
    config = study_mod.load(path, strict=False)
    print(f"{config.title}\n")

    for room in config.rooms.values():
        describe_room(room, config)

    warnings = [(room, over) for room in config.rooms.values() for over in room.overrides()]
    loud = [(r, o) for r, o in warnings if o.excludes_baseline]

    if config.problems:
        print("PROBLEMS")
        for problem in config.problems:
            print(f"  - {problem}")
        return 1

    if loud:
        print(
            f"WARNING: {len(loud)} entr{'y' if len(loud) == 1 else 'ies'} sweep a value "
            "rooms.py sets deliberately, without ever evaluating it:"
        )
        for room, over in loud:
            print(f"  - {room.label}: {over.describe()}")
        print("  Remove it from the config, or widen the sweep to include the real value.")
        print()

    print("Config is valid." if not loud else "Config is valid, with warnings above.")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "study" / "rooms.yaml"
    raise SystemExit(main(target))
