"""The study config: how it parses, and what it is not allowed to do silently."""

from __future__ import annotations

from pathlib import Path

import pytest

from zcbsl_resize import compute, fastest_ramp_minutes, rooms, study
from zcbsl_resize.params import PARAMS_BY_KEY

CONFIG = Path(__file__).resolve().parents[1] / "study" / "rooms.yaml"

#: What the shared block is allowed to contain: quantities that are physically
#: ONE value across both rooms.  Anything else describes a room or an
#: experiment and belongs in that room's block, even where the two rooms start
#: from the same number.  This list is the agreement; the test is the fence.
GENUINELY_SHARED = frozenset({
    "tank_enabled", "tank_temp_hot", "tank_temp_cold", "exchanger_approach", "carnot_efficiency",
    "outdoor_coil_approach",
    "boundary_temp_winter", "boundary_temp_summer", "boundary_rh", "surrounding_temp",
    "pressure_pa", "surface_film_h", "margin_pct",
})


@pytest.fixture(scope="module")
def config():
    return study.load(CONFIG)


# ---------------------------------------------------------------- parsing

def test_the_four_entry_forms():
    assert study.parse_spec("margin_pct", 15.0, "room").kind == "fixed"
    assert study.parse_spec("ach", [0.5, 12.0, None], "room").kind == "bounds"
    assert study.parse_spec("ach", {"values": [1, 2, 5]}, "room").kind == "list"
    grid = study.parse_spec("ach", [0.0, 10.0, 2.5], "room")
    assert grid.kind == "grid"
    assert grid.values == (0.0, 2.5, 5.0, 7.5, 10.0)


@pytest.mark.parametrize("bad", [
    [1.0, 2.0],                 # wrong length
    [2.0, 1.0, 0.5],            # reversed
    [0.0, 10.0, 0.0],           # zero step
    {"values": []},             # empty
    True,                       # a boolean is not a number
    "3",                        # nor a string
])
def test_nonsense_entries_are_rejected(bad):
    with pytest.raises(ValueError):
        study.parse_spec("ach", bad, "room")


def test_bounds_are_sampled_fully_but_gridded_at_the_midpoint():
    spec = study.parse_spec("supply_dt", [8.0, 20.0, None], "room")
    assert spec.sample_range == (8.0, 20.0)
    assert spec.grid_points == (14.0,)
    assert spec.varies


def test_a_grid_axis_keeps_its_points():
    spec = study.parse_spec("supply_dt", [8.0, 20.0, 4.0], "room")
    assert spec.grid_points == (8.0, 12.0, 16.0, 20.0)
    assert spec.sample_range == (8.0, 20.0)


def test_a_fixed_entry_does_not_vary():
    assert not study.parse_spec("margin_pct", 15.0, "room").varies


# ---------------------------------------------------------------- validation

def test_a_broken_config_raises_with_every_problem_at_once(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "rooms:\n"
        "  module_room:\n"
        "    base: module_room\n"
        "    nonsense_key: 1.0\n"
        "    ach: [0.5, 99.0, 1.0]\n"
        "study:\n"
        "  outputs: [not_an_output]\n",
        encoding="utf-8",
    )
    with pytest.raises(study.ConfigError) as err:
        study.load(bad)
    joined = "\n".join(err.value.problems)
    assert "nonsense_key" in joined
    assert "ach" in joined              # 99 is outside the model's 0..20
    assert "not_an_output" in joined


def test_non_strict_loading_collects_problems_instead_of_raising(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("rooms:\n  r:\n    base: no_such_room\n", encoding="utf-8")
    config = study.load(bad, strict=False)
    assert config.problems
    assert "no_such_room" in config.problems[0]


def test_outputs_and_grid_axes_are_real(config):
    known = set(study.RESULT_KEYS) | study.DERIVED_OUTPUTS
    assert set(config.outputs) <= known
    assert set(config.sobol.targets) <= known
    for axes in config.grids.values():
        assert set(axes) <= set(PARAMS_BY_KEY)


# ------------------------------------------------- the shared/room boundary

def test_shared_holds_only_what_is_physically_one_value(config):
    """The restructure, pinned.

    A parameter creeping back into ``shared:`` is how one range ends up
    stretched across a 120 m2 room and a 372 m2 one.
    """
    shared = {k for room in config.rooms.values() for k, s in room.specs.items()
              if s.origin == "shared"}
    assert shared == GENUINELY_SHARED, sorted(shared ^ GENUINELY_SHARED)


def test_both_rooms_declare_their_own_operation(config):
    """Anything a room could reasonably differ on is declared per room."""
    per_room = {"setpoint_min", "setpoint_max", "ramp_minutes", "added_mass_coverage",
                "ach", "supply_dt", "max_air_surface_dt", "equipment_w_per_m2",
                "occupants", "target_rh"}
    for room in config.rooms.values():
        declared = {k for k, s in room.specs.items() if s.origin == "room"}
        assert per_room <= declared, (room.key, sorted(per_room - declared))


# ---------------------------------------------------------------- overrides

def test_sweeping_a_measured_value_is_reported(tmp_path):
    """The bug this check exists for: the shell is 7.0 because it is aluminium."""
    text = CONFIG.read_text(encoding="utf-8").replace(
        '    added_mass_coverage: [0.0, 100.0, 10.0]\n    added_mass_thickness: [0.05, 0.50, null]',
        "    base_shell_capacity: [5.0, 15.0, 2.5]\n" + '    added_mass_coverage: [0.0, 100.0, 10.0]\n    added_mass_thickness: [0.05, 0.50, null]',
    )
    path = tmp_path / "regressed.yaml"
    path.write_text(text, encoding="utf-8")

    room = study.load(path).rooms["module_room"]
    overrides = {o.key: o for o in room.overrides()}
    assert "base_shell_capacity" in overrides
    assert overrides["base_shell_capacity"].excludes_baseline
    assert "7" in overrides["base_shell_capacity"].describe()


def test_an_override_that_includes_the_real_value_is_reported_quietly(tmp_path):
    text = CONFIG.read_text(encoding="utf-8").replace(
        '    added_mass_coverage: [0.0, 100.0, 10.0]\n    added_mass_thickness: [0.05, 0.50, null]',
        "    base_shell_capacity: [5.0, 15.0, 1.0]\n" + '    added_mass_coverage: [0.0, 100.0, 10.0]\n    added_mass_thickness: [0.05, 0.50, null]',
    )
    path = tmp_path / "included.yaml"
    path.write_text(text, encoding="utf-8")
    over = {o.key: o for o in study.load(path).rooms["module_room"].overrides()}
    assert not over["base_shell_capacity"].excludes_baseline


def test_swapping_the_exchangeable_facade_is_not_an_override(config):
    """The module room's facade is a placeholder, not a measurement.

    Sweeping it is the study doing its job, so it must not be reported -- a
    warning that cries wolf is a warning nobody reads.
    """
    reported = {o.key for o in config.rooms["module_room"].overrides()}
    assert not reported & {"south_u_opaque", "south_wwr", "south_shgc",
                           "south_u_glazing", "south_irradiance", "roof_u_opaque"}


def test_the_chambers_fixed_envelope_would_be_an_override(tmp_path):
    """The same key, in the room that cannot exchange it, is reported."""
    text = CONFIG.read_text(encoding="utf-8").replace(
        "    added_mass_coverage: [0.0, 100.0, 10.0]\n    added_mass_thickness: 0.50",
        "    north_u_opaque: [0.05, 2.50, 0.35]\n"
        "    added_mass_coverage: [0.0, 100.0, 10.0]\n    added_mass_thickness: 0.50",
    )
    path = tmp_path / "chamber.yaml"
    path.write_text(text, encoding="utf-8")
    over = {o.key for o in study.load(path).rooms["climate_chamber"].overrides()}
    assert "north_u_opaque" in over


def test_the_shipped_config_has_no_unevaluated_measured_values(config):
    for room in config.rooms.values():
        loud = [o.describe() for o in room.overrides() if o.excludes_baseline]
        assert not loud, (room.key, loud)


def test_restating_a_baseline_exactly_is_not_an_override(tmp_path):
    text = CONFIG.read_text(encoding="utf-8").replace(
        '    added_mass_coverage: [0.0, 100.0, 10.0]\n    added_mass_thickness: [0.05, 0.50, null]',
        "    base_shell_capacity: 7.0\n" + '    added_mass_coverage: [0.0, 100.0, 10.0]\n    added_mass_thickness: [0.05, 0.50, null]',
    )
    path = tmp_path / "restated.yaml"
    path.write_text(text, encoding="utf-8")
    over = {o.key for o in study.load(path).rooms["module_room"].overrides()}
    assert "base_shell_capacity" not in over


# ---------------------------------------------------------------- geometry

def test_interior_area_matches_the_model(config):
    for room in config.rooms.values():
        assert room.interior_area == pytest.approx(
            float(compute(room.baseline())["interior_area"])
        )


def test_added_mass_is_the_same_share_of_both_rooms(config):
    """Resolved 2026-09-18: parity is structural now, not a coincidence to check.

    added_mass_area no longer exists as a settable input -- added_mass_coverage
    (percent of interior surface) is the only way to set it, and both rooms
    declare the identical GRID. There is no "do these two absolute-m2 ranges
    happen to line up" question left to ask: it is the same spec values for
    both rooms, by construction.
    """
    specs = [room.specs["added_mass_coverage"] for room in config.rooms.values()]
    assert len({(s.low, s.high) for s in specs}) == 1


def test_equal_coverage_gives_both_rooms_the_same_speed_limit(config):
    """And the consequence, which is the finding that makes the fix worth it.

    Not exact -- only the shell and added-mass terms fully cancel by area; the
    air term does not, and how far it's off depends on each room's own
    volume-to-interior-area ratio (see rooms.py). With the chamber's corrected
    geometry (10.5 x 6.9 x 8.7) that ratio sits further from the module room's
    than the old, wrong dimensions did, so the residual grew from ~1 minute to
    ~2.3. Still the same order of magnitude as the ramp itself is wrong to
    matter for a purchasing decision, which is the actual claim this test
    checks.
    """
    answers = []
    for room in config.rooms.values():
        params = room.nominal().replace(added_mass_coverage=25.0)
        answers.append(float(fastest_ramp_minutes(params)))
    assert abs(answers[0] - answers[1]) < 2.5, answers


# ---------------------------------------------------------------- the rooms

def test_nominal_reproduces_the_sizing_table(config):
    """The numbers in the project doc, straight out of the config.

    If a restructure of rooms.yaml moves any of these, it changed something it
    was not supposed to.
    """
    expected = {
        # Cooling numbers assume boundary_temp_summer=45 (confirmed 2026-09-18:
        # a deliberate climate-change design margin, not the historical Zurich
        # condition of 32). Heating is unaffected by that -- it is evaluated
        # against boundary_temp_winter only. The chamber's own geometry was
        # corrected 2026-09-18 (10.5 x 6.9 x 8.7, was wrongly 8.00 x 4.50 x
        # 12.00), which moves every chamber number here, including heating
        # (bigger room -> bigger ventilation volume and envelope, even before
        # the boundary-temperature question).
        #
        # 2026-09-23: design capacity is now the larger of the operating and
        # ramp modes, not hold + ramp, and the ramp runs with nobody inside and
        # the Sun off.  The chamber row also absorbs the 2026-09-21 edits to
        # rooms.yaml (ACH fixed at 1.0, added-mass coverage 0-10 %, so the
        # nominal is 0 % coverage).
        "module_room": (20.5, 9.6, 16.7, 15.3),
        "climate_chamber": (330.5, 48.6, 49.4, 16.9),
    }
    for key, (ua, heat_kw, cool_kw, t_star) in expected.items():
        params = config.rooms[key].nominal()
        r = compute(params)
        assert float(r["envelope_conductance"]) == pytest.approx(ua, abs=0.1)
        assert float(r["heating_design"]) / 1000.0 == pytest.approx(heat_kw, abs=0.1)
        assert float(r["cooling_design"]) / 1000.0 == pytest.approx(cool_kw, abs=0.1)
        assert float(fastest_ramp_minutes(params)) == pytest.approx(t_star, abs=0.1)


def test_neither_room_sets_the_shell_capacitance(config):
    """It is 7.0 from the aluminium lining, and rooms.py is where that lives."""
    for room in config.rooms.values():
        assert "base_shell_capacity" not in room.specs
        assert room.nominal().base_shell_capacity == pytest.approx(
            rooms.ALUMINIUM_AND_GLASS_SHELL
        )


def test_varying_covers_grid_and_bounds_alike(config):
    """The factor list for Sobol: a grid entry is not a claim of certainty."""
    room = config.rooms["module_room"]
    assert "supply_dt" in room.varying          # grid
    assert "ach" in room.varying                # bounds
    assert "margin_pct" not in room.varying     # fixed, and shared
    assert "added_mass_rho_c" not in room.varying


def test_an_axis_a_room_does_not_declare_sits_at_its_baseline(config):
    """The chamber cannot exchange its envelope, which is not a config error."""
    chamber = config.rooms["climate_chamber"]
    shape = chamber.grid_shape(["south_wwr"])
    assert shape["south_wwr"] == (chamber.baseline().south_wwr,)


def test_sobol_sample_size_is_a_power_of_two(config):
    assert config.sobol.n & (config.sobol.n - 1) == 0
