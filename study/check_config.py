"""Validate study/rooms.yaml against the model and report grid sizes.

    python study/check_config.py [path]

Checks every parameter name exists, every range sits inside the model's own
declared limits, and prints how many rows each configured grid would produce.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import yaml  # noqa: E402

from zcbsl_resize import rooms  # noqa: E402
from zcbsl_resize.params import PARAMS_BY_KEY  # noqa: E402

#: Keys that describe a room but are not model parameters.
META_KEYS = {"label", "notes", "base"}


def spec_kind(value):
    """Classify one entry: fixed, grid, bounds, or list."""
    if isinstance(value, dict) and "values" in value:
        return "list", list(value["values"])
    if isinstance(value, (int, float)):
        return "fixed", [float(value)]
    if isinstance(value, list) and len(value) == 3:
        low, high, step = value
        if step is None:
            return "bounds", [float(low), float(high)]
        count = int(round((float(high) - float(low)) / float(step))) + 1
        return "grid", [float(low) + i * float(step) for i in range(max(count, 1))]
    raise ValueError(f"cannot interpret {value!r}")


def main(path: Path) -> int:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    shared = config.get("shared", {})
    problems: list[str] = []

    print(f"{config.get('meta', {}).get('title', path.name)}\n")

    for room_key, room in config["rooms"].items():
        base_key = room.get("base")
        if base_key is not None and base_key not in rooms.ROOMS:
            problems.append(f"{room_key}.base: unknown room {base_key!r}")
        merged = {**shared, **room}
        resolved: dict[str, tuple[str, list[float]]] = {}

        for key, value in merged.items():
            if key in META_KEYS:
                continue
            model_key = key
            spec = PARAMS_BY_KEY.get(model_key)
            if spec is None:
                problems.append(f"{room_key}.{key}: not a model parameter")
                continue
            try:
                kind, values = spec_kind(value)
            except ValueError as err:
                problems.append(f"{room_key}.{key}: {err}")
                continue
            for v in (min(values), max(values)):
                if not (spec.minimum <= v <= spec.maximum):
                    problems.append(
                        f"{room_key}.{key}: {v} outside the model's "
                        f"{spec.minimum}..{spec.maximum} {spec.unit}".rstrip()
                    )
            resolved[model_key] = (kind, values)

        # A room's baseline supplies anything the config does not mention.
        missing = sorted(set(PARAMS_BY_KEY) - set(resolved))
        print(f"  {room.get('label', room_key)}")
        source = f"baseline rooms.{base_key}()" if base_key else "model defaults"
        print(f"    {len(resolved)} parameters set here, {len(missing)} taken from {source}")
        swept = {k: len(v) for k, (kind, v) in resolved.items() if kind == "grid"}
        bounds = [k for k, (kind, _) in resolved.items() if kind == "bounds"]
        print(f"    grid axes available: {len(swept)}  bounds-only: {len(bounds)}")

        for name, grid in config.get("study", {}).get("grids", {}).items():
            rows = 1
            detail = []
            varying = 0
            for axis in grid["axes"]:
                if axis not in PARAMS_BY_KEY:
                    problems.append(f"grid '{name}': {axis} is not a model parameter")
                    continue
                kind, values = resolved.get(axis, ("baseline", [None]))
                # An axis this room does not declare is simply fixed at its
                # baseline value, which is not an error: the climate chamber's
                # envelope cannot be exchanged, so it has nothing to sweep.
                rows *= len(values)
                if len(values) > 1:
                    varying += 1
                    detail.append(f"{axis}={len(values)}")
            if varying == 0:
                print(f"    grid '{name}': not applicable, every axis is fixed for this room")
            else:
                print(f"    grid '{name}': {rows:,} rows  ({' x '.join(detail)})")
        print()

    if problems:
        print("PROBLEMS")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("Config is valid.")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "study" / "rooms.yaml"
    raise SystemExit(main(target))
