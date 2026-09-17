"""API surface: the browser must be able to render from what it is given."""

import json

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
        "/api/compute", json={"params": ChamberParams(added_mass_area=20.0).to_dict()}
    ).get_json()
    assert payload["lumped"]["power_mass"] > payload["results"]["power_mass"]


def test_scenario_endpoint_round_trips(client):
    payload = client.post(
        "/api/scenario", json={"params": {"ramp_minutes": 90}, "name": "slow ramp"}
    ).get_json()
    assert payload["format"] == 1
    assert payload["name"] == "slow ramp"
    assert payload["params"]["ramp_minutes"] == 90
