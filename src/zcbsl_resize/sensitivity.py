"""Global sensitivity for the chamber model.

Why Sobol rather than a screening method
----------------------------------------
Morris exists because most models are expensive.  This one is analytic and
vectorised: a hundred thousand cases is a handful of numpy calls and a couple
of seconds, so the usual reason to settle for a screening rank does not apply.
Sobol indices answer the sharper question directly --

* ``S1``  the share of output variance this factor explains on its own;
* ``ST``  its share including every interaction it takes part in;
* ``ST - S1``  the interaction itself, which is the thing a one-at-a-time
  sweep structurally cannot see.

That last column is the whole reason this file exists.  Mass and ramp time
multiply, and ``film_ok`` is a step, so from a baseline of
``added_mass_coverage = 0`` a one-at-a-time sweep never trips the film constraint
and ranks it irrelevant.

Estimators
----------
``S1`` follows Saltelli et al. (2010) and ``ST`` follows Jansen (1999), both
computed from the standard A / B / AB construction at a cost of
``n x (k + 2)`` model evaluations.

Sampling
--------
A scrambled Sobol sequence if SciPy is installed, and a Latin hypercube out of
numpy if it is not.  The estimators are unbiased either way; the sequence only
converges faster.  No hard dependency is added either way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from .physics import compute, fastest_ramp_minutes
from .study import RoomConfig

#: Outputs that are not columns of ``compute()`` and have to be asked for.
DERIVED = {"fastest_ramp_minutes": fastest_ramp_minutes}


# --------------------------------------------------------------------------
# Sampling
# --------------------------------------------------------------------------

def unit_sample(n: int, d: int, rng: np.random.Generator) -> np.ndarray:
    """``n`` points in the ``d``-dimensional unit cube.

    Uses SciPy's scrambled Sobol sequence when it is available and falls back
    to a Latin hypercube built from numpy alone.  The fallback is not a
    second-class option -- it stratifies every margin -- it just does not have
    the sequence's low-discrepancy behaviour in higher dimensions.
    """
    try:
        from scipy.stats import qmc
    except ImportError:
        pass
    else:
        return qmc.Sobol(d=d, scramble=True, seed=rng).random(n)

    out = np.empty((n, d), dtype=float)
    for j in range(d):
        out[:, j] = (rng.permutation(n) + rng.random(n)) / n
    return out


def scale(unit: np.ndarray, ranges: Sequence[tuple[float, float]]) -> np.ndarray:
    """Map unit-cube columns onto each factor's declared range."""
    low = np.array([lo for lo, _ in ranges], dtype=float)
    high = np.array([hi for _, hi in ranges], dtype=float)
    return low + unit * (high - low)


# --------------------------------------------------------------------------
# Evaluating the model on a sample matrix
# --------------------------------------------------------------------------

def _evaluate(
    room: RoomConfig,
    factors: Sequence[str],
    matrix: np.ndarray,
    targets: Sequence[str],
    fixed: Mapping[str, float] | None,
) -> dict[str, np.ndarray]:
    """Run the model over one sample matrix and pull out the targets."""
    params: dict[str, Any] = room.nominal().to_dict()
    if fixed:
        unknown = set(fixed) - set(params)
        if unknown:
            raise KeyError(f"unknown parameter(s) in fixed: {sorted(unknown)}")
        params.update(fixed)
    for j, key in enumerate(factors):
        params[key] = matrix[:, j]

    # compute() orders the setpoints defensively rather than complaining, so a
    # sample that inverted them would be silently reinterpreted rather than
    # caught.  Catch it here instead.
    lo = np.asarray(params["setpoint_min"], dtype=float)
    hi = np.asarray(params["setpoint_max"], dtype=float)
    if np.any(hi <= lo):
        bad = int(np.sum(hi <= lo))
        raise ValueError(
            f"{bad} sample(s) have setpoint_max <= setpoint_min; the declared "
            "ranges overlap and the model would silently reorder them"
        )

    rows = matrix.shape[0]
    results = compute(params)
    out: dict[str, np.ndarray] = {}
    for target in targets:
        if target in DERIVED:
            value = DERIVED[target](params)
        else:
            value = results[target]
        out[target] = np.broadcast_to(np.asarray(value, dtype=float), (rows,)).astype(float)
    return out



def sobol_indices(
    ya: np.ndarray,
    yb: np.ndarray,
    y_ab: Sequence[np.ndarray],
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """First-order and total-order indices from the A / B / AB evaluations.

    ``S1`` after Saltelli et al. (2010), ``ST`` after Jansen (1999).  Split out
    from :func:`screen` so it can be checked against a function whose indices
    are known analytically -- see ``tests/test_sensitivity.py``, which runs it
    against Ishigami.

    Returns ``(first_order, total_order, mean, variance)``.
    """
    ya = np.asarray(ya, dtype=float)
    yb = np.asarray(yb, dtype=float)
    pooled = np.concatenate([ya, yb])
    variance = float(np.var(pooled, ddof=1))
    k = len(y_ab)

    first = np.zeros(k)
    total = np.zeros(k)
    if variance <= 0.0:
        # A target this sample cannot move: ramp_minutes against the
        # fixed-point ramp, for instance.  Zero, not a divide by zero.
        return first, total, float(np.mean(pooled)), variance

    for i, yab_i in enumerate(y_ab):
        yab = np.asarray(yab_i, dtype=float)
        first[i] = float(np.mean(yb * (yab - ya))) / variance
        total[i] = float(0.5 * np.mean((ya - yab) ** 2)) / variance
    return first, total, float(np.mean(pooled)), variance


# --------------------------------------------------------------------------
# The result
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SobolResult:
    room: str
    target: str
    factors: tuple[str, ...]
    first_order: np.ndarray
    total_order: np.ndarray
    mean: float
    variance: float
    n: int
    evaluations: int

    @property
    def interaction(self) -> np.ndarray:
        """``ST - S1``: variance this factor explains only in company."""
        return self.total_order - self.first_order

    def table(self, *, top: int | None = None) -> pd.DataFrame:
        frame = pd.DataFrame({
            "factor": self.factors,
            "S1": self.first_order,
            "ST": self.total_order,
            "interaction": self.interaction,
        }).sort_values("ST", ascending=False).reset_index(drop=True)
        return frame if top is None else frame.head(top)

    def __repr__(self) -> str:  # pragma: no cover - convenience only
        return (
            f"<SobolResult {self.room}/{self.target} "
            f"k={len(self.factors)} n={self.n} evals={self.evaluations:,}>"
        )


# --------------------------------------------------------------------------
# The screen
# --------------------------------------------------------------------------

def screen(
    room: RoomConfig,
    *,
    targets: Iterable[str],
    n: int = 4096,
    seed: int = 0,
    factors: Sequence[str] | None = None,
    fixed: Mapping[str, float] | None = None,
) -> dict[str, SobolResult]:
    """Sobol indices for one room, one sample matrix, several targets.

    ``factors`` defaults to everything the room's config varies.  Anything
    passed in ``fixed`` is pinned and dropped from the factor list, which is
    how a scenario switch such as the Artificial Sun is handled: it is a
    separate world to screen, not a continuous input to sample across.
    """
    targets = tuple(targets)
    if factors is None:
        factors = room.varying
    factors = tuple(f for f in factors if not (fixed and f in fixed))
    if not factors:
        raise ValueError(f"{room.key} has nothing left to vary")

    ranges = [room.specs[f].sample_range for f in factors]
    k = len(factors)

    rng = np.random.default_rng(seed)
    base = unit_sample(n, 2 * k, rng)
    a = scale(base[:, :k], ranges)
    b = scale(base[:, k:], ranges)

    f_a = _evaluate(room, factors, a, targets, fixed)
    f_b = _evaluate(room, factors, b, targets, fixed)

    f_ab: list[dict[str, np.ndarray]] = []
    for i in range(k):
        ab = a.copy()
        ab[:, i] = b[:, i]
        f_ab.append(_evaluate(room, factors, ab, targets, fixed))

    out: dict[str, SobolResult] = {}
    for target in targets:
        first, total, mean, variance = sobol_indices(
            f_a[target], f_b[target], [f_ab[i][target] for i in range(k)]
        )
        out[target] = SobolResult(
            room=room.key,
            target=target,
            factors=factors,
            first_order=first,
            total_order=total,
            mean=mean,
            variance=variance,
            n=n,
            evaluations=n * (k + 2),
        )
    return out


# --------------------------------------------------------------------------
# One at a time, kept as the cross-check
# --------------------------------------------------------------------------

def oat(
    room: RoomConfig,
    *,
    targets: Iterable[str],
    points: int = 21,
    factors: Sequence[str] | None = None,
    fixed: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    """Swing in each target from moving one factor across its range alone.

    Kept precisely so the notebook can show where it disagrees with the Sobol
    ranking.  Where the two agree the factor acts on its own; where OAT ranks a
    factor far lower, that factor only matters in company, and reading the OAT
    tornado would have sent you after the wrong thing.
    """
    targets = tuple(targets)
    if factors is None:
        factors = room.varying
    factors = tuple(f for f in factors if not (fixed and f in fixed))

    rows = []
    for key in factors:
        low, high = room.specs[key].sample_range
        sweep = np.linspace(low, high, points)
        matrix = np.zeros((points, 1))
        matrix[:, 0] = sweep
        values = _evaluate(room, (key,), matrix, targets, fixed)
        row: dict[str, Any] = {"factor": key, "low": low, "high": high}
        for target in targets:
            v = values[target]
            row[f"{target}_min"] = float(np.min(v))
            row[f"{target}_max"] = float(np.max(v))
            row[f"{target}_swing"] = float(np.max(v) - np.min(v))
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# The feasibility surface
# --------------------------------------------------------------------------

def feasibility_grid(
    room: RoomConfig,
    *,
    ramp_minutes: np.ndarray,
    coverage: np.ndarray,
    fixed: Mapping[str, float] | None = None,
) -> dict[str, np.ndarray]:
    """Ramp time against lined area, as a share of interior surface.

    Returns ``film_ok`` on the grid along with the required air-to-surface ΔT
    and the self-consistent fastest ramp.  Draw the boundary from ``film_ok``:
    it compares the required ΔT at *that* ramp against the allowance, so it is
    self-consistent everywhere.  ``min_feasible_ramp_minutes`` is not -- see
    ``physics.fastest_ramp_minutes``.
    """
    ramp = np.asarray(ramp_minutes, dtype=float)[None, :]
    cover = np.asarray(coverage, dtype=float)[:, None]

    params: dict[str, Any] = room.nominal().to_dict()
    if fixed:
        params.update(fixed)
    params["ramp_minutes"] = np.broadcast_to(ramp, (cover.size, ramp.size))
    params["added_mass_coverage"] = np.broadcast_to(cover * 100.0, (cover.size, ramp.size))

    r = compute(params)
    return {
        "film_ok": np.asarray(r["film_ok"]),
        "required_air_surface_dt": np.asarray(r["required_air_surface_dt"], dtype=float),
        "cooling_design": np.asarray(r["cooling_design"], dtype=float),
        "fastest_ramp_minutes": np.broadcast_to(
            np.asarray(fastest_ramp_minutes(params), dtype=float),
            (cover.size, ramp.size),
        ).astype(float),
    }
