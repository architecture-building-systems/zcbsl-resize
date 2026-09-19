"""The checker script, exercised the way you actually run it."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "study" / "check_config.py"
CONFIG = REPO / "study" / "rooms.yaml"


def run(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        capture_output=True, text=True, cwd=REPO,
    )


def test_the_shipped_config_passes():
    result = run(CONFIG)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Config is valid." in result.stdout
    assert "WARNING" not in result.stdout


def test_it_reports_added_mass_as_a_share_of_each_room():
    """Resolved 2026-09-18: the share is a real input now, printed directly."""
    out = run(CONFIG).stdout
    assert out.count("added_mass_coverage: 0..100 %") == 2


def test_a_bad_parameter_name_is_an_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        CONFIG.read_text(encoding="utf-8").replace(
            "    ach: [0.5, 12.0, null]", "    airchanges: [0.5, 12.0, null]", 1
        ),
        encoding="utf-8",
    )
    result = run(path)
    assert result.returncode == 1
    assert "not a model parameter" in result.stdout


def test_a_range_outside_the_model_is_an_error(tmp_path):
    path = tmp_path / "wide.yaml"
    path.write_text(
        CONFIG.read_text(encoding="utf-8").replace(
            "    ach: [0.5, 12.0, null]", "    ach: [0.5, 99.0, null]", 1
        ),
        encoding="utf-8",
    )
    result = run(path)
    assert result.returncode == 1
    assert "outside the model's" in result.stdout


@pytest.mark.parametrize("entry", [
    "base_shell_capacity: [5.0, 15.0, 2.5]",
    "base_shell_capacity: 12.0",
])
def test_sweeping_the_shell_warns_without_failing(tmp_path, entry):
    """Justin's bug, as it was written and as it might come back.

    A warning rather than an error: an override is sometimes what you mean.
    But it is never silent.
    """
    path = tmp_path / "regressed.yaml"
    path.write_text(
        CONFIG.read_text(encoding="utf-8").replace(
            "    added_mass_coverage: [0.0, 100.0, 10.0]",
            f"    {entry}\n    added_mass_coverage: [0.0, 100.0, 10.0]",
            1,
        ),
        encoding="utf-8",
    )
    result = run(path)
    assert result.returncode == 0
    assert "WARNING" in result.stdout
    assert "base_shell_capacity" in result.stdout
    assert "never evaluated" in result.stdout


def test_bounds_axes_are_counted_at_their_midpoint(tmp_path):
    """A BOUNDS entry declares a range, not grid points.

    Counting its two endpoints as an axis inflated the heat_pump grid by 2x
    and implied a sweep that was never going to run.
    """
    path = tmp_path / "bounds.yaml"
    path.write_text(
        CONFIG.read_text(encoding="utf-8").replace(
            "    supply_dt: [8.0, 20.0, 4.0]", "    supply_dt: [8.0, 20.0, null]"
        ),
        encoding="utf-8",
    )
    out = run(path).stdout
    assert "supply_dt@midpoint" in out
    assert "supply_dt=2" not in out
