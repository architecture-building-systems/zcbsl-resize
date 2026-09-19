"""Scenario and combinatorics helpers.

``physics.compute`` broadcasts, so a sweep of a million cases is one call, not
a million.  These helpers build the parameter arrays, run them, and hand back a
pandas DataFrame with the inputs and the results side by side.

    from zcbsl_resize import ChamberParams
    from zcbsl_resize.scenarios import grid_sweep

    df = grid_sweep(
        ChamberParams(),
        {"ramp_minutes": [15, 30, 60, 120], "added_mass_coverage": [0, 10, 20, 40]},
    )
    df.plot(x="ramp_minutes", y="heating_design")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from .params import PARAMS, PARAMS_BY_KEY, ChamberParams, load_scenario
from .physics import compute

#: Refuse to build a grid larger than this unless explicitly raised.
DEFAULT_MAX_CASES = 5_000_000


def _broadcast_to_frame(
    inputs: Mapping[str, Any],
    results: Mapping[str, Any],
    n: int,
    outputs: Sequence[str] | None = None,
) -> pd.DataFrame:
    columns: dict[str, np.ndarray] = {}
    for key, value in inputs.items():
        columns[key] = np.broadcast_to(np.asarray(value), (n,)).copy()
    wanted = results if outputs is None else {k: results[k] for k in outputs}
    for key, value in wanted.items():
        arr = np.asarray(value)
        if arr.dtype == bool:
            columns[key] = np.broadcast_to(arr, (n,)).copy()
        else:
            columns[key] = np.broadcast_to(arr.astype(float), (n,)).copy()
    return pd.DataFrame(columns)


def _validate_keys(keys: Iterable[str]) -> None:
    unknown = sorted(set(keys) - set(PARAMS_BY_KEY))
    if unknown:
        raise KeyError(f"not model parameters: {unknown}")


def evaluate(
    params: ChamberParams,
    overrides: Mapping[str, np.ndarray] | None = None,
    *,
    lumped_mass: bool = False,
    outputs: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Run one already-built set of parameter arrays and return a DataFrame.

    ``outputs`` selects which result columns to keep.  The model returns over a
    hundred of them, including a per-surface breakdown, so a large sweep that
    keeps everything can need gigabytes.  Name the handful you actually plot.
    """
    overrides = dict(overrides or {})
    _validate_keys(overrides)
    base = params.to_dict()
    base.update(overrides)

    lengths = {np.asarray(v).size for v in overrides.values()} or {1}
    n = max(lengths)
    results = compute(base, lumped_mass=lumped_mass)
    if outputs is not None:
        unknown = sorted(set(outputs) - set(results))
        if unknown:
            raise KeyError(f"not model outputs: {unknown}")
    return _broadcast_to_frame(base, results, n, outputs)


def grid_sweep(
    params: ChamberParams,
    axes: Mapping[str, Sequence[float]],
    *,
    lumped_mass: bool = False,
    outputs: Sequence[str] | None = None,
    max_cases: int = DEFAULT_MAX_CASES,
) -> pd.DataFrame:
    """Full factorial over ``axes``. One row per combination.

    ``axes`` maps parameter names to the values to try, e.g.
    ``{"ramp_minutes": [15, 30, 60], "added_mass_coverage": [0, 20]}`` gives 6 rows.
    """
    _validate_keys(axes)
    if not axes:
        return evaluate(params, lumped_mass=lumped_mass, outputs=outputs)

    vectors = [np.asarray(v, dtype=float).ravel() for v in axes.values()]
    total = int(np.prod([v.size for v in vectors]))
    if total > max_cases:
        raise ValueError(
            f"{total:,} combinations exceeds max_cases={max_cases:,}. "
            "Narrow the axes or raise max_cases deliberately."
        )
    mesh = np.meshgrid(*vectors, indexing="ij")
    overrides = {key: grid.ravel() for key, grid in zip(axes.keys(), mesh)}
    return evaluate(params, overrides, lumped_mass=lumped_mass, outputs=outputs)


def ramp_sweep(
    params: ChamberParams,
    minutes: Sequence[float] | None = None,
    *,
    lumped_mass: bool = False,
    outputs: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Design capacity across a range of ramp times. Drives the sensitivity chart."""
    if minutes is None:
        minutes = [5, 10, 15, 20, 25, 30, 40, 50, 60, 75, 90, 105, 120, 150, 180, 240, 300, 360, 420, 480]
    return grid_sweep(params, {"ramp_minutes": minutes}, lumped_mass=lumped_mass, outputs=outputs)


def one_at_a_time(
    params: ChamberParams,
    keys: Sequence[str] | None = None,
    *,
    points: int = 21,
    outputs: Sequence[str] = ("heating_design", "cooling_design", "electric_cooling", "design_flow_ls"),
    lumped_mass: bool = False,
) -> pd.DataFrame:
    """Local sensitivity: vary each parameter across its full declared range.

    Returns a tidy frame with one row per (parameter, step), giving each output
    and its ratio to the baseline value.  Sort by ``span`` to see which inputs
    actually move the answer.
    """
    keys = list(keys) if keys is not None else [p.key for p in PARAMS]
    _validate_keys(keys)
    baseline = compute(params, lumped_mass=lumped_mass)

    frames = []
    for key in keys:
        spec = PARAMS_BY_KEY[key]
        values = np.linspace(spec.minimum, spec.maximum, points)
        df = evaluate(params, {key: values}, lumped_mass=lumped_mass, outputs=list(outputs))
        tidy = pd.DataFrame({"parameter": key, "label": spec.label, "unit": spec.unit, "value": values})
        for out in outputs:
            base_val = float(np.asarray(baseline[out]))
            tidy[out] = df[out].to_numpy()
            tidy[f"{out}_ratio"] = df[out].to_numpy() / (base_val if base_val else np.nan)
        frames.append(tidy)
    return pd.concat(frames, ignore_index=True)


def sensitivity_ranking(
    params: ChamberParams,
    keys: Sequence[str] | None = None,
    *,
    output: str = "heating_design",
    points: int = 21,
) -> pd.DataFrame:
    """Which inputs move ``output`` the most, across their full declared ranges."""
    tidy = one_at_a_time(params, keys, points=points, outputs=(output,))
    grouped = tidy.groupby(["parameter", "label", "unit"], as_index=False).agg(
        low=(output, "min"), high=(output, "max")
    )
    grouped["span"] = grouped["high"] - grouped["low"]
    grouped["span_ratio"] = grouped["high"] / grouped["low"].replace(0.0, np.nan)
    return grouped.sort_values("span", ascending=False, ignore_index=True)


def latin_hypercube(
    params: ChamberParams,
    ranges: Mapping[str, tuple[float, float]],
    n: int,
    *,
    seed: int | None = None,
    lumped_mass: bool = False,
    outputs: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Space-filling sample over ``ranges``, for when a full grid is too large."""
    _validate_keys(ranges)
    rng = np.random.default_rng(seed)
    overrides: dict[str, np.ndarray] = {}
    for key, (low, high) in ranges.items():
        cut = (np.arange(n) + rng.random(n)) / n
        overrides[key] = low + rng.permutation(cut) * (high - low)
    return evaluate(params, overrides, lumped_mass=lumped_mass, outputs=outputs)


def run_scenario_file(path: str | Path, *, lumped_mass: bool = False) -> pd.DataFrame:
    """Load a saved scenario JSON and run whatever sweeps it declares."""
    scenario = load_scenario(path)
    if scenario["sweeps"]:
        return grid_sweep(scenario["params"], scenario["sweeps"], lumped_mass=lumped_mass)
    return evaluate(scenario["params"], lumped_mass=lumped_mass)
