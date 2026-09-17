"""Scenario engine: shapes, correctness against scalar calls, and guard rails."""

import numpy as np
import pytest

from zcbsl_resize import ChamberParams, compute, save_scenario
from zcbsl_resize.scenarios import (
    evaluate,
    grid_sweep,
    latin_hypercube,
    one_at_a_time,
    ramp_sweep,
    run_scenario_file,
    sensitivity_ranking,
)


def test_grid_sweep_is_a_full_factorial():
    df = grid_sweep(ChamberParams(), {"ramp_minutes": [15, 30, 60], "ach": [0, 5, 10, 20]})
    assert len(df) == 12
    assert set(df["ramp_minutes"]) == {15, 30, 60}
    assert set(df["ach"]) == {0, 5, 10, 20}


def test_sweep_rows_match_individual_calls():
    df = grid_sweep(ChamberParams(), {"ramp_minutes": [12, 47, 300]})
    for _, row in df.iterrows():
        scalar = compute(ChamberParams(ramp_minutes=row["ramp_minutes"]))
        assert row["heating_design"] == pytest.approx(scalar["heating_design"])
        assert row["min_feasible_ramp_minutes"] == pytest.approx(scalar["min_feasible_ramp_minutes"])


def test_inputs_and_outputs_both_land_in_the_frame():
    df = grid_sweep(ChamberParams(), {"ramp_minutes": [30, 60]})
    assert "ramp_minutes" in df.columns
    assert "heating_design" in df.columns
    assert "film_ok" in df.columns
    assert df["film_ok"].dtype == bool


def test_a_typo_in_an_axis_name_raises():
    with pytest.raises(KeyError):
        grid_sweep(ChamberParams(), {"ramp_time": [30]})


def test_oversized_grids_are_refused():
    with pytest.raises(ValueError, match="exceeds max_cases"):
        grid_sweep(
            ChamberParams(),
            {"ramp_minutes": np.arange(1000), "ach": np.arange(1000), "length": np.arange(20)},
            max_cases=1_000_000,
        )


def test_a_million_cases_stay_fast():
    import time

    start = time.perf_counter()
    df = grid_sweep(
        ChamberParams(),
        {"ramp_minutes": np.linspace(5, 480, 1000), "added_mass_area": np.linspace(0, 100, 1000)},
    )
    elapsed = time.perf_counter() - start
    assert len(df) == 1_000_000
    assert elapsed < 30.0


def test_ramp_sweep_is_monotonic_in_capacity():
    df = ramp_sweep(ChamberParams())
    assert df["heating_design"].is_monotonic_decreasing


def test_one_at_a_time_covers_every_requested_parameter():
    df = one_at_a_time(ChamberParams(), ["ach", "ramp_minutes"], points=5)
    assert set(df["parameter"]) == {"ach", "ramp_minutes"}
    assert len(df) == 10
    assert "heating_design_ratio" in df.columns


def test_sensitivity_ranking_puts_mass_and_ramp_on_top():
    ranked = sensitivity_ranking(ChamberParams(added_mass_area=20.0), points=9)
    top = set(ranked.head(4)["parameter"])
    assert {"added_mass_area", "base_shell_capacity", "ramp_minutes"} & top


def test_latin_hypercube_stays_inside_its_ranges():
    df = latin_hypercube(
        ChamberParams(), {"ramp_minutes": (10.0, 120.0), "ach": (0.0, 20.0)}, n=500, seed=1
    )
    assert len(df) == 500
    assert df["ramp_minutes"].between(10.0, 120.0).all()
    assert df["ach"].between(0.0, 20.0).all()


def test_latin_hypercube_is_reproducible():
    a = latin_hypercube(ChamberParams(), {"ach": (0.0, 20.0)}, n=50, seed=7)
    b = latin_hypercube(ChamberParams(), {"ach": (0.0, 20.0)}, n=50, seed=7)
    assert np.allclose(a["ach"], b["ach"])


def test_scenario_file_drives_a_sweep(tmp_path):
    path = save_scenario(
        ChamberParams(added_mass_area=15.0),
        tmp_path / "s.json",
        sweeps={"ramp_minutes": [20, 40, 80]},
    )
    df = run_scenario_file(path)
    assert len(df) == 3
    assert (df["added_mass_area"] == 15.0).all()


def test_evaluate_without_overrides_gives_one_row():
    assert len(evaluate(ChamberParams())) == 1


def test_lumped_mode_is_carried_through_the_sweep():
    limited = grid_sweep(ChamberParams(added_mass_area=20.0), {"ramp_minutes": [30]})
    lumped = grid_sweep(ChamberParams(added_mass_area=20.0), {"ramp_minutes": [30]}, lumped_mass=True)
    assert lumped["power_mass"].iloc[0] > limited["power_mass"].iloc[0]
