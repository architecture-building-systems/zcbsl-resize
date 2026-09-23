"""Global sensitivity: the estimator, and what it says about these rooms."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from zcbsl_resize import sensitivity, study

CONFIG = Path(__file__).resolve().parents[1] / "study" / "rooms.yaml"


@pytest.fixture(scope="module")
def config():
    return study.load(CONFIG)


@pytest.fixture(scope="module")
def module_room(config):
    return config.rooms["module_room"]


# ------------------------------------------------------- the estimator alone

def _ishigami(x, a=7.0, b=0.1):
    return np.sin(x[:, 0]) + a * np.sin(x[:, 1]) ** 2 + b * x[:, 2] ** 4 * np.sin(x[:, 0])


def test_estimator_recovers_ishigami():
    """The standard benchmark, whose indices are known in closed form.

    a=7, b=0.1 over U(-pi, pi) gives S1 = [0.314, 0.442, 0] and
    ST = [0.558, 0.442, 0.244].  Third factor: no effect on its own, a real
    one in company -- exactly the case a one-at-a-time sweep misses.
    """
    n, k = 2 ** 14, 3
    rng = np.random.default_rng(20260918)
    base = sensitivity.unit_sample(n, 2 * k, rng) * (2 * np.pi) - np.pi
    a, b = base[:, :k], base[:, k:]

    ya, yb = _ishigami(a), _ishigami(b)
    y_ab = []
    for i in range(k):
        ab = a.copy()
        ab[:, i] = b[:, i]
        y_ab.append(_ishigami(ab))

    first, total, _, _ = sensitivity.sobol_indices(ya, yb, y_ab)
    assert first == pytest.approx([0.3139, 0.4424, 0.0], abs=0.03)
    assert total == pytest.approx([0.5576, 0.4424, 0.2437], abs=0.03)
    assert total[2] - first[2] > 0.15          # pure interaction, correctly seen


def test_estimator_is_flat_on_a_constant():
    n, k = 256, 3
    ones = np.ones(n)
    first, total, mean, var = sensitivity.sobol_indices(ones, ones, [ones] * k)
    assert var == 0.0
    assert mean == pytest.approx(1.0)
    assert np.all(first == 0.0) and np.all(total == 0.0)


def test_unit_sample_fills_the_cube():
    rng = np.random.default_rng(0)
    sample = sensitivity.unit_sample(1024, 4, rng)
    assert sample.shape == (1024, 4)
    assert sample.min() >= 0.0 and sample.max() < 1.0
    assert sample.mean(axis=0) == pytest.approx(0.5, abs=0.05)


def test_scale_maps_onto_the_declared_ranges():
    unit = np.array([[0.0, 0.5, 1.0]])
    out = sensitivity.scale(unit, [(10.0, 20.0), (0.0, 1.0), (-5.0, 5.0)])
    assert out[0] == pytest.approx([10.0, 0.5, 5.0])


# --------------------------------------------------------------- the screen

def test_screen_covers_the_rooms_declared_factors(module_room):
    result = sensitivity.screen(module_room, targets=["cooling_design"], n=128, seed=1)
    out = result["cooling_design"]
    assert out.factors == module_room.varying
    assert out.evaluations == 128 * (len(out.factors) + 2)
    assert out.variance > 0


def test_total_order_is_never_below_first_order_by_more_than_noise(module_room):
    out = sensitivity.screen(module_room, targets=["cooling_design"], n=1024, seed=2)
    r = out["cooling_design"]
    assert np.all(r.total_order - r.first_order > -0.02)


def test_first_order_shares_do_not_exceed_the_whole(module_room):
    out = sensitivity.screen(module_room, targets=["cooling_design"], n=1024, seed=3)
    assert out["cooling_design"].first_order.sum() < 1.05


def test_the_ramp_you_ask_for_cannot_move_the_ramp_you_can_get(module_room):
    """``fastest_ramp_minutes`` is a fixed point: its own input drops out.

    A non-zero index here would mean the fixed-point solver had leaked the
    input ramp, which is the bug it exists to remove.
    """
    out = sensitivity.screen(module_room, targets=["fastest_ramp_minutes"], n=512, seed=4)
    r = out["fastest_ramp_minutes"]
    i = r.factors.index("ramp_minutes")
    assert abs(r.first_order[i]) < 0.01
    assert abs(r.total_order[i]) < 0.01


def test_the_film_allowance_dominates_the_ramp(module_room):
    """And it does so mostly through interaction, which is the point."""
    r = sensitivity.screen(module_room, targets=["fastest_ramp_minutes"], n=1024, seed=5)[
        "fastest_ramp_minutes"
    ]
    top = r.table().iloc[0]
    assert top["factor"] == "max_air_surface_dt"
    assert top["interaction"] > top["S1"] / 2


def test_fixing_a_parameter_drops_it_from_the_factors(config):
    chamber = config.rooms["climate_chamber"]
    r = sensitivity.screen(
        chamber, targets=["heating_design"], n=128, seed=6,
        fixed={"equipment_w_per_m2": 0.0},
    )["heating_design"]
    assert "equipment_w_per_m2" not in r.factors
    assert r.mean > 0          # Sun off, so there is a heating duty to speak of


def test_the_chambers_heating_case_is_the_sun_off_one(config):
    """The Artificial Sun is 10.5 kW of gain, and it is always off during a ramp.

    So the ramp mode -- which is what sets the chamber's heating size -- is the
    Sun-off case whatever the operating scenario says, and switching the Sun
    on for an experiment moves only the operating column: heating hold down by
    the full gain, cooling hold up by it.  Before 2026-09-23 the ramp credited
    the Sun against heating, and this test had to pin a scenario choice to get
    the heating size right; now the model gets it right by construction.
    """
    from zcbsl_resize import compute, rooms

    chamber = config.rooms["climate_chamber"]
    sun_w_per_m2 = rooms.ARTIFICIAL_SUN_W / (10.5 * 6.9)
    on = compute(chamber.nominal().replace(equipment_w_per_m2=sun_w_per_m2))
    off = compute(chamber.nominal().replace(equipment_w_per_m2=0.0))

    assert float(on["heating_ramp"]) == pytest.approx(float(off["heating_ramp"]))
    assert float(off["heating_hold"]) - float(on["heating_hold"]) == pytest.approx(rooms.ARTIFICIAL_SUN_W, rel=1e-3)
    assert float(on["cooling_hold"]) - float(off["cooling_hold"]) == pytest.approx(rooms.ARTIFICIAL_SUN_W, rel=1e-3)
    # With the ramp governing heating, the Sun cannot shrink the heating machine.
    assert bool(on["heating_set_by_ramp"])
    assert float(on["heating_design"]) == pytest.approx(float(off["heating_design"]))


def test_an_unknown_fixed_parameter_is_rejected(module_room):
    with pytest.raises(KeyError):
        sensitivity.screen(module_room, targets=["cooling_design"], n=64, seed=8,
                           fixed={"not_a_parameter": 1.0})


def test_overlapping_setpoint_ranges_are_caught_not_reordered(module_room):
    """compute() would silently swap them; the sampler must not let it."""
    from dataclasses import replace

    specs = dict(module_room.specs)
    specs["setpoint_max"] = study.parse_spec("setpoint_max", [5.0, 12.0, 1.0], "room")
    broken = replace(module_room, specs=specs)
    with pytest.raises(ValueError, match="setpoint_max"):
        sensitivity.screen(broken, targets=["cooling_design"], n=64, seed=9)


def test_results_are_reproducible_from_the_seed(module_room):
    a = sensitivity.screen(module_room, targets=["cooling_design"], n=128, seed=11)
    b = sensitivity.screen(module_room, targets=["cooling_design"], n=128, seed=11)
    assert a["cooling_design"].total_order == pytest.approx(b["cooling_design"].total_order)


# ------------------------------------------------------------------ one at a time

def test_oat_returns_a_swing_per_factor(module_room):
    frame = sensitivity.oat(module_room, targets=["cooling_design"], points=9)
    assert len(frame) == len(module_room.varying)
    assert (frame["cooling_design_swing"] >= 0).all()


def test_oat_is_blind_to_the_mass_it_starts_without(module_room):
    """The reason both methods are in the notebook.

    The room's baseline has no added mass.  Move the lining's *thickness* on
    its own from there and nothing happens at all -- there is no lining for a
    thickness to describe.  A one-at-a-time tornado therefore ranks it dead
    last, at exactly zero.  Sobol samples area and thickness together, finds
    that they multiply, and gives it a real total-order share that is almost
    entirely interaction.
    """
    assert module_room.nominal().added_mass_coverage == 0.0

    frame = sensitivity.oat(
        module_room, targets=["fastest_ramp_minutes"], points=11
    ).set_index("factor")
    assert frame.loc["added_mass_thickness", "fastest_ramp_minutes_swing"] == pytest.approx(
        0.0, abs=1e-9
    )

    ranked = sensitivity.screen(
        module_room, targets=["fastest_ramp_minutes"], n=4096, seed=12
    )["fastest_ramp_minutes"].table().set_index("factor")
    row = ranked.loc["added_mass_thickness"]
    assert row["ST"] > 0.008           # small, but not the zero OAT reports
    assert row["interaction"] > 0.7 * row["ST"]


# ------------------------------------------------------------ the feasibility surface

def test_feasibility_grid_has_the_shape_you_asked_for(module_room):
    ramp = np.linspace(10, 240, 24)
    cover = np.linspace(0.0, 0.5, 11)
    grid = sensitivity.feasibility_grid(module_room, ramp_minutes=ramp, coverage=cover)
    for value in grid.values():
        assert value.shape == (11, 24)


def test_the_boundary_agrees_with_the_fixed_point(module_room):
    """Why the heatmap draws film_ok and not min_feasible_ramp_minutes.

    film_ok compares the required ΔT at *that* ramp against the allowance, so
    it flips exactly at the self-consistent fastest ramp.
    """
    ramp = np.linspace(5, 400, 400)
    cover = np.array([0.0, 0.1, 0.25, 0.5])
    grid = sensitivity.feasibility_grid(module_room, ramp_minutes=ramp, coverage=cover)
    for row in range(cover.size):
        ok = grid["film_ok"][row]
        t_star = grid["fastest_ramp_minutes"][row][0]
        crossing = ramp[np.argmax(ok)]
        assert crossing == pytest.approx(t_star, abs=ramp[1] - ramp[0])
        assert ok[ramp > t_star].all()
        assert not ok[ramp < t_star - 1e-9].any()


def test_more_lining_never_makes_a_room_faster(module_room):
    grid = sensitivity.feasibility_grid(
        module_room, ramp_minutes=np.array([30.0]), coverage=np.linspace(0, 0.5, 9)
    )
    t_star = grid["fastest_ramp_minutes"][:, 0]
    assert np.all(np.diff(t_star) > 0)
