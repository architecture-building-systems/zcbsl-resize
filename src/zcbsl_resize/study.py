"""Read ``study/rooms.yaml``.

One parser, shared by ``study/check_config.py`` and by the notebooks.  The
alternative -- each of them reading the file its own way -- is how a config and
its checker drift apart, which is exactly the failure this module exists to
stop.

What the file says
------------------
``shared:`` holds only what is physically one value across both rooms: the
tank temperatures and the plant that serves them, the outdoor design
conditions, the surface film, the safety margin.  Everything else describes a
room or an experiment and lives in that room's own block, even where the two
rooms currently start from the same number.

Each entry takes one of four forms::

    name: 1.2                  FIXED    one value, overriding the baseline
    name: [min, max, step]      GRID    points on the factorial grid
    name: [min, max, null]    BOUNDS    sampled globally; the grid holds the midpoint
    name: {values: [1, 2, 5]}   LIST    explicit points

Anything a room does not mention comes from its baseline in ``rooms.py``.

Overrides
---------
A room's baseline is not a suggestion: ``rooms.module_room()`` says the shell
is 7.0 kJ/m2K because the room is lined in aluminium.  A config entry that
sweeps that key replaces a measured property with a guess, and until this
module existed it did so silently.  :meth:`RoomConfig.overrides` reports every
such entry so the checker can say so out loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from . import rooms as rooms_mod
from .params import PARAMS_BY_KEY, ChamberParams
from .physics import RESULT_KEYS

#: Keys in a room block that describe it rather than parameterise it.
META_KEYS = frozenset({"label", "notes", "base"})

#: Outputs the study layer computes that ``compute()`` does not return.
DERIVED_OUTPUTS = frozenset({"fastest_ramp_minutes"})

#: Two floats are the same number if they agree this closely.
TOL = 1e-9


class ConfigError(ValueError):
    """The config cannot be used as written."""

    def __init__(self, problems: Iterable[str]):
        self.problems = tuple(problems)
        joined = "\n  - ".join(self.problems)
        super().__init__(f"{len(self.problems)} problem(s) in the study config:\n  - {joined}")


# --------------------------------------------------------------------------
# One entry
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Spec:
    """One parameter as the config declares it."""

    key: str
    kind: str  # "fixed" | "grid" | "bounds" | "list"
    values: tuple[float, ...]
    origin: str  # "shared" | "room"

    @property
    def low(self) -> float:
        return min(self.values)

    @property
    def high(self) -> float:
        return max(self.values)

    @property
    def varies(self) -> bool:
        """Does this entry describe more than one value?"""
        return self.kind != "fixed" and self.high - self.low > TOL

    @property
    def grid_points(self) -> tuple[float, ...]:
        """What a factorial grid steps over.

        A BOUNDS entry declares a range for global sampling and deliberately
        does not declare grid points, so the grid holds it at its midpoint.
        """
        if self.kind == "bounds":
            return (0.5 * (self.low + self.high),)
        return self.values

    @property
    def sample_range(self) -> tuple[float, float]:
        """The interval global sampling draws from, grid or bounds alike."""
        return self.low, self.high

    def covers(self, value: float) -> bool:
        """Would this entry ever put the model at ``value``?

        Compared with a relative tolerance, so a config that writes a computed
        constant to a few decimals still counts as naming it.
        """
        tol = max(TOL, 1e-6 * abs(value))
        if self.kind == "bounds":
            return self.low - tol <= value <= self.high + tol
        return any(abs(v - value) <= tol for v in self.values)


def parse_spec(key: str, value: Any, origin: str) -> Spec:
    """Turn one YAML value into a :class:`Spec`."""
    if isinstance(value, dict) and "values" in value:
        raw = list(value["values"])
        if not raw:
            raise ValueError("an empty values: list")
        return Spec(key, "list", tuple(float(v) for v in raw), origin)
    if isinstance(value, bool):
        raise ValueError(f"a boolean ({value!r}); parameters are numeric")
    if isinstance(value, (int, float)):
        return Spec(key, "fixed", (float(value),), origin)
    if isinstance(value, list) and len(value) == 3:
        low, high, step = value
        low, high = float(low), float(high)
        if high < low:
            raise ValueError(f"a reversed range [{low}, {high}]")
        if step is None:
            return Spec(key, "bounds", (low, high), origin)
        step = float(step)
        if step <= 0:
            raise ValueError(f"a non-positive step ({step})")
        count = int(round((high - low) / step)) + 1
        points = tuple(low + i * step for i in range(max(count, 1)))
        return Spec(key, "grid", points, origin)
    raise ValueError(f"{value!r}, which is none of FIXED, GRID, BOUNDS or LIST")


# --------------------------------------------------------------------------
# What a room's baseline actually claims
# --------------------------------------------------------------------------

def deliberate_keys(base: str) -> frozenset[str]:
    """Parameters this room *knows*, as opposed to ones it is guessing at.

    Declared in ``rooms.MEASURED``, because the distinction cannot be inferred
    from the numbers.  Diffing a room against a generic ``ChamberParams`` finds
    everything its constructor sets, which is not the same thing: the module
    room's facade U-value is set there and is still a placeholder, while its
    shell capacitance is set there and is a measured property of the lining.
    Only ``rooms.py`` can say which is which, so it does.
    """
    return rooms_mod.MEASURED.get(base, frozenset())


@dataclass(frozen=True)
class Override:
    """A config entry standing on top of a value ``rooms.py`` set deliberately."""

    key: str
    spec: Spec
    baseline: float

    @property
    def excludes_baseline(self) -> bool:
        """Is the room's own value never even evaluated?

        The loud case.  ``base_shell_capacity: [5.0, 15.0, 2.5]`` steps over
        5, 7.5, 10, 12.5, 15 and never touches the room's real 7.0.
        """
        return not self.spec.covers(self.baseline)

    def describe(self) -> str:
        if self.spec.kind == "fixed":
            shape = f"fixed at {self.spec.values[0]:g}"
        elif self.spec.kind == "bounds":
            shape = f"sampled over {self.spec.low:g}..{self.spec.high:g}"
        else:
            shape = f"swept over {len(self.spec.values)} points, {self.spec.low:g}..{self.spec.high:g}"
        return f"{self.key}: {shape}, but rooms.py sets it to {self.baseline:g}"


# --------------------------------------------------------------------------
# One room
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RoomConfig:
    key: str
    label: str
    base: str
    notes: str
    specs: dict[str, Spec]

    # -- geometry the config questions depend on --------------------------

    def baseline(self) -> ChamberParams:
        """The room as ``rooms.py`` describes it, untouched by the config."""
        return rooms_mod.get(self.base)

    @property
    def interior_area(self) -> float:
        """Total interior surface, m2.  What the film exchanges across."""
        b = self.baseline()
        return 2.0 * (b.width * b.height + b.depth * b.height + b.width * b.depth)

    @property
    def floor_area(self) -> float:
        b = self.baseline()
        return b.width * b.depth

    def coverage(self, area_m2: float) -> float:
        """An added-mass area as a fraction of interior surface.

        The honest way to compare the two rooms: 60 m2 of lining is half the
        module room and a sixth of the climate chamber, and it is the fraction
        that decides how hard the room is to charge, not the area.
        """
        return area_m2 / self.interior_area

    # -- what the config says ---------------------------------------------

    def nominal(self) -> ChamberParams:
        """Baseline plus every FIXED entry: the room's single design case.

        Entries that vary stay at their baseline, so this reproduces the
        sizing table rather than some midpoint of a sweep.
        """
        fixed = {k: s.values[0] for k, s in self.specs.items() if s.kind == "fixed"}
        return self.baseline().replace(**fixed)

    @property
    def varying(self) -> tuple[str, ...]:
        """Every parameter this room explores, grid or bounds alike.

        This is the factor list for global sensitivity: a GRID entry declares
        convenient points for a factorial sweep, not that the parameter is
        known only at those points.
        """
        return tuple(sorted(k for k, s in self.specs.items() if s.varies))

    def overrides(self) -> tuple[Override, ...]:
        deliberate = deliberate_keys(self.base)
        baseline = self.baseline().to_dict()
        out = []
        for key, spec in sorted(self.specs.items()):
            if key not in deliberate:
                continue
            if spec.kind == "fixed" and abs(spec.values[0] - baseline[key]) <= TOL:
                continue  # restating the baseline is not an override
            out.append(Override(key, spec, baseline[key]))
        return tuple(out)

    def grid_shape(self, axes: Iterable[str]) -> dict[str, tuple[float, ...]]:
        """The points this room would step over for the named axes."""
        shape = {}
        for axis in axes:
            spec = self.specs.get(axis)
            if spec is None:
                # Not declared for this room: held at its baseline. The climate
                # chamber's envelope cannot be exchanged, so it has nothing to
                # sweep, and that is a fact about the room, not a config error.
                shape[axis] = (self.baseline().to_dict()[axis],)
            else:
                shape[axis] = spec.grid_points
        return shape


# --------------------------------------------------------------------------
# The whole study
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SobolConfig:
    n: int
    seed: int
    targets: tuple[str, ...]

    @property
    def evaluations(self) -> int:
        """Saltelli's cost: N x (k + 2) rows, once k factors are known."""
        return self.n


@dataclass(frozen=True)
class StudyConfig:
    title: str
    notes: str
    rooms: dict[str, RoomConfig]
    outputs: tuple[str, ...]
    grids: dict[str, tuple[str, ...]]
    sobol: SobolConfig
    envelope_sample: dict[str, Any]
    path: Path
    problems: tuple[str, ...] = ()


def load(path: str | Path, *, strict: bool = True) -> StudyConfig:
    """Read and validate the study config.

    With ``strict`` (the default) any problem raises :class:`ConfigError`.
    The checker loads it non-strict so it can print every problem at once.
    """
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    problems: list[str] = []

    shared_raw = raw.get("shared") or {}
    shared: dict[str, Spec] = {}
    for key, value in shared_raw.items():
        if key not in PARAMS_BY_KEY:
            problems.append(f"shared.{key}: not a model parameter")
            continue
        try:
            shared[key] = parse_spec(key, value, "shared")
        except ValueError as err:
            problems.append(f"shared.{key}: {err}")

    rooms: dict[str, RoomConfig] = {}
    for room_key, block in (raw.get("rooms") or {}).items():
        base = block.get("base")
        if base not in rooms_mod.ROOMS:
            problems.append(f"{room_key}.base: unknown room {base!r}")
            continue
        specs = dict(shared)
        for key, value in block.items():
            if key in META_KEYS:
                continue
            if key not in PARAMS_BY_KEY:
                problems.append(f"{room_key}.{key}: not a model parameter")
                continue
            try:
                specs[key] = parse_spec(key, value, "room")
            except ValueError as err:
                problems.append(f"{room_key}.{key}: {err}")
        for key, spec in specs.items():
            limits = PARAMS_BY_KEY[key]
            for edge in (spec.low, spec.high):
                if not (limits.minimum <= edge <= limits.maximum):
                    problems.append(
                        f"{room_key}.{key}: {edge:g} is outside the model's "
                        f"{limits.minimum:g}..{limits.maximum:g} {limits.unit}".rstrip()
                    )
        rooms[room_key] = RoomConfig(
            key=room_key,
            label=block.get("label", room_key),
            base=base,
            notes=(block.get("notes") or "").strip(),
            specs=specs,
        )

    if not rooms:
        problems.append("no rooms defined")

    study = raw.get("study") or {}
    known_outputs = set(RESULT_KEYS) | DERIVED_OUTPUTS
    outputs = tuple(study.get("outputs") or ())
    for name in outputs:
        if name not in known_outputs:
            problems.append(f"study.outputs: {name!r} is not a model output")

    grids: dict[str, tuple[str, ...]] = {}
    for name, block in (study.get("grids") or {}).items():
        axes = tuple((block or {}).get("axes") or ())
        for axis in axes:
            if axis not in PARAMS_BY_KEY:
                problems.append(f"study.grids.{name}: {axis!r} is not a model parameter")
        grids[name] = axes

    sobol_raw = study.get("sobol") or {}
    sobol = SobolConfig(
        n=int(sobol_raw.get("n", 1024)),
        seed=int(sobol_raw.get("seed", 0)),
        targets=tuple(sobol_raw.get("targets") or ()),
    )
    for name in sobol.targets:
        if name not in known_outputs:
            problems.append(f"study.sobol.targets: {name!r} is not a model output")
    if sobol.n & (sobol.n - 1):
        problems.append(
            f"study.sobol.n: {sobol.n} is not a power of two, which a Sobol "
            "sequence needs for its balance properties"
        )

    config = StudyConfig(
        title=(raw.get("meta") or {}).get("title", path.name),
        notes=((raw.get("meta") or {}).get("notes") or "").strip(),
        rooms=rooms,
        outputs=outputs,
        grids=grids,
        sobol=sobol,
        envelope_sample=dict(study.get("envelope_sample") or {}),
        path=path,
        problems=tuple(problems),
    )
    if problems and strict:
        raise ConfigError(problems)
    return config
