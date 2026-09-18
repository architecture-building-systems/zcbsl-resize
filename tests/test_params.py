"""The dataclass and the UI schema must never drift apart."""

from dataclasses import fields

import pytest

from zcbsl_resize.surfaces import SURFACES, SURFACE_FIELDS
from zcbsl_resize.params import (
    PARAMS,
    PARAMS_BY_KEY,
    SECTIONS,
    ChamberParams,
    load_scenario,
    save_scenario,
    schema,
)


def test_schema_and_dataclass_cover_the_same_fields():
    declared = {p.key for p in PARAMS}
    actual = {f.name for f in fields(ChamberParams)}
    assert declared == actual


def test_every_param_belongs_to_a_declared_section():
    known = {s["key"] for s in SECTIONS}
    assert {p.section for p in PARAMS} <= known


def test_defaults_sit_inside_their_declared_ranges():
    assert ChamberParams().validate() == []


def test_ranges_requested_in_the_workshop_review():
    assert PARAMS_BY_KEY["equipment_w_per_m2"].maximum == 500.0
    assert PARAMS_BY_KEY["ach"].maximum == 20.0
    for key in ("width", "depth", "height"):
        assert PARAMS_BY_KEY[key].maximum >= 20.0
    # Irradiance is now per surface, and still reaches the lamp-array range.
    assert PARAMS_BY_KEY["south_irradiance"].maximum == 2000.0


def test_every_surface_carries_a_full_construction():
    """Each of the six faces gets its own U-values, glazing, solar and exposure."""
    for surface in SURFACES:
        for suffix, _, _ in SURFACE_FIELDS:
            key = f"{surface.key}_{suffix}"
            assert key in PARAMS_BY_KEY, f"missing {key}"
            assert PARAMS_BY_KEY[key].section == f"surf_{surface.key}"


def test_single_facade_parameters_are_gone_not_hidden():
    """The one-facade-plus-residual abstraction is removed outright."""
    for dead in (
        "facade_width", "glazing_fraction", "facade_u_opaque", "facade_u_glazing",
        "ceiling_u", "residual_u", "solar_irradiance", "wwr", "shgc", "length",
    ):
        assert dead not in PARAMS_BY_KEY


def test_exposure_spans_interior_to_exterior():
    spec = PARAMS_BY_KEY["north_exposure"]
    assert (spec.minimum, spec.maximum) == (0.0, 1.0)


def test_a_surface_can_be_made_perfectly_adiabatic():
    """Zero U on both parts, rather than a special boundary type."""
    assert PARAMS_BY_KEY["north_u_opaque"].minimum == 0.0
    assert PARAMS_BY_KEY["north_u_glazing"].minimum == 0.0


def test_unknown_keys_are_rejected_not_ignored():
    with pytest.raises(KeyError):
        ChamberParams().replace(nonexistent_input=1.0)
    with pytest.raises(KeyError):
        ChamberParams.from_dict({"length": 4.0, "typo_key": 1.0})


def test_clamping_pulls_values_into_range():
    clamped = ChamberParams(ach=999.0, depth=-4.0).clamped()
    assert clamped.ach == PARAMS_BY_KEY["ach"].maximum
    assert clamped.depth == PARAMS_BY_KEY["depth"].minimum


def test_scenario_round_trip(tmp_path):
    original = ChamberParams(ramp_minutes=45.0, added_mass_area=18.0)
    path = save_scenario(original, tmp_path / "s.json", name="test", sweeps={"ramp_minutes": [15, 30, 60]})
    loaded = load_scenario(path)
    assert loaded["params"] == original
    assert loaded["sweeps"]["ramp_minutes"] == [15.0, 30.0, 60.0]
    assert loaded["name"] == "test"


def test_schema_is_json_shaped():
    payload = schema()
    assert {"sections", "params", "presets"} <= set(payload)
    assert all({"key", "min", "max", "default"} <= set(p) for p in payload["params"])
