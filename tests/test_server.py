"""API surface: the browser must be able to render from what it is given."""

import json

import numpy as np
import pytest

from zcbsl_resize.params import ChamberParams
from zcbsl_resize.server import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_index_and_assets_are_served(client):
    assert client.get("/").status_code == 200
    assert client.get("/app.js").status_code == 200
    assert client.get("/styles.css").status_code == 200


def test_schema_has_everything_the_ui_needs(client):
    payload = client.get("/api/schema").get_json()
    assert payload["params"]
    assert {"sections", "params", "presets"} <= set(payload)
    sections = {s["key"] for s in payload["sections"]}
    assert {p["section"] for p in payload["params"]} <= sections


def test_compute_returns_json_serialisable_numbers(client):
    res = client.post("/api/compute", json={"params": ChamberParams().to_dict()})
    assert res.status_code == 200
    payload = res.get_json()
    json.dumps(payload)  # raises if numpy types leaked through
    assert payload["results"]["heating_design"] > 0
    assert isinstance(payload["results"]["film_ok"], bool)
    assert len(payload["sweep"]["ramp_minutes"]) == len(payload["sweep"]["heating_design"])


def test_compute_accepts_a_partial_parameter_set(client):
    payload = client.post("/api/compute", json={"params": {"ramp_minutes": 45}}).get_json()
    assert payload["params"]["ramp_minutes"] == 45
    assert payload["problems"] == []


def test_out_of_range_input_is_clamped_not_rejected(client):
    payload = client.post("/api/compute", json={"params": {"ach": 999}}).get_json()
    assert payload["params"]["ach"] == 20.0


def test_unknown_keys_do_not_crash_the_endpoint(client):
    payload = client.post("/api/compute", json={"params": {"nonsense": 1, "ach": 4}}).get_json()
    assert payload["params"]["ach"] == 4
    assert "nonsense" not in payload["params"]


def test_inverted_setpoints_are_reported_as_a_problem(client):
    payload = client.post(
        "/api/compute", json={"params": {"setpoint_min": 30, "setpoint_max": 16}}
    ).get_json()
    assert any("setpoint" in problem.lower() for problem in payload["problems"])


def test_lumped_comparison_is_returned_for_the_ui_callout(client):
    payload = client.post(
        "/api/compute", json={"params": ChamberParams(added_mass_coverage=20.0).to_dict()}
    ).get_json()
    assert payload["lumped"]["power_mass"] > payload["results"]["power_mass"]


def test_scenario_endpoint_round_trips(client):
    payload = client.post(
        "/api/scenario", json={"params": {"ramp_minutes": 90}, "name": "slow ramp"}
    ).get_json()
    assert payload["format"] == 1
    assert payload["name"] == "slow ramp"
    assert payload["params"]["ramp_minutes"] == 90


# --------------------------------------------------- the ramp the browser shows

def test_compute_payload_carries_the_self_consistent_ramp(client):
    """The browser must not show the conditional figure as "fastest reachable".

    ``min_feasible_ramp_minutes`` depends on the ramp it was handed. With added
    mass the two diverge, and the tile that says "Fastest reachable ramp" has to
    be the fixed point.
    """
    from zcbsl_resize import ChamberParams, fastest_ramp_minutes

    params = ChamberParams(added_mass_coverage=60.0, ramp_minutes=30.0)
    payload = client.post("/api/compute", json={"params": params.to_dict()}).get_json()

    expected = float(np.atleast_1d(fastest_ramp_minutes(params))[0])
    assert payload["results"]["fastest_ramp_minutes"] == pytest.approx(expected, rel=1e-9)
    assert payload["sweep"]["fastest_ramp_minutes"] == pytest.approx(expected, rel=1e-9)

    # And they really are different here, or the test proves nothing.
    conditional = payload["results"]["min_feasible_ramp_minutes"]
    assert expected > conditional * 1.4


def test_the_unreachable_band_is_not_read_off_the_shortest_ramp(client):
    """The old bug: the sweep reported its first row, at a 5-minute ramp.

    Almost no added mass participates in five minutes, so the boundary came out
    far too optimistic and the chart's unreachable band was drawn too narrow.
    """
    from zcbsl_resize import ChamberParams, compute

    params = ChamberParams(added_mass_coverage=60.0)
    payload = client.post("/api/compute", json={"params": params.to_dict()}).get_json()

    at_five_minutes = float(compute(params, ramp_minutes=5.0)["min_feasible_ramp_minutes"])
    assert payload["sweep"]["fastest_ramp_minutes"] > at_five_minutes * 2


def test_a_bare_room_shows_the_same_number_either_way(client):
    """With no added mass the shell is thermally thin and the two coincide."""
    from zcbsl_resize import ChamberParams

    params = ChamberParams(added_mass_coverage=0.0)
    results = client.post("/api/compute", json={"params": params.to_dict()}).get_json()["results"]
    assert results["fastest_ramp_minutes"] == pytest.approx(
        results["min_feasible_ramp_minutes"], rel=1e-9
    )
