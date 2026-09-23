"""Flask app serving the browser front end.

The browser holds no physics.  It fetches the parameter schema, draws a control
for each entry, and posts the parameter set back on every change.  One
implementation of the model, in Python, is the whole point.

Run it with::

    python -m zcbsl_resize.server
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
from flask import Flask, jsonify, request, send_from_directory

from .params import ChamberParams, schema
from .physics import compute, fastest_ramp_minutes, mode_crossover_minutes
from .scenarios import ramp_sweep

WEB_DIR = "web"


def jsonable(value: Any) -> Any:
    """numpy scalars and arrays are not JSON-serialisable; plain Python is."""
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return jsonable(value.item())
        return [jsonable(v) for v in value.tolist()]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return f if np.isfinite(f) else None
    return value


def _params_from_request() -> tuple[ChamberParams, list[str]]:
    payload = request.get_json(silent=True) or {}
    raw = payload.get("params", payload)
    params = ChamberParams.from_dict(raw, strict=False).clamped()
    return params, params.validate()


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/<path:filename>")
    def static_files(filename: str):
        return send_from_directory(WEB_DIR, filename)

    @app.get("/api/schema")
    def api_schema():
        return jsonify(jsonable(schema()))

    @app.post("/api/compute")
    def api_compute():
        params, problems = _params_from_request()
        results = compute(params)
        lumped = compute(params, lumped_mass=True)
        sweep = ramp_sweep(params)

        # The speed limit the room actually has.  results["min_feasible_ramp_minutes"]
        # answers a narrower question -- what the minimum would be *given the ramp
        # you asked for* -- and with added mass the two are not the same, because a
        # longer ramp reaches deeper and recruits more capacity.  The browser shows
        # the fixed point; see physics.fastest_ramp_minutes.
        results = dict(results)
        results["fastest_ramp_minutes"] = fastest_ramp_minutes(params)
        # Past this ramp time the operating mode sets the size, not the ramp.
        # None means the ramp governs at every ramp time the tool allows.
        results["heating_crossover_minutes"] = mode_crossover_minutes(params, "heating")
        results["cooling_crossover_minutes"] = mode_crossover_minutes(params, "cooling")

        return jsonify(
            {
                "params": params.to_dict(),
                "problems": problems,
                "results": jsonable(results),
                "lumped": {
                    "power_mass": jsonable(lumped["power_mass"]),
                    "heating_design": jsonable(lumped["heating_design"]),
                    "cooling_design": jsonable(lumped["cooling_design"]),
                },
                "sweep": {
                    "ramp_minutes": sweep["ramp_minutes"].tolist(),
                    "heating_design": sweep["heating_design"].tolist(),
                    "cooling_design": sweep["cooling_design"].tolist(),
                    "heating_operating": sweep["heating_operating"].tolist(),
                    "cooling_operating": sweep["cooling_operating"].tolist(),
                    "heating_ramp": sweep["heating_ramp"].tolist(),
                    "cooling_ramp": sweep["cooling_ramp"].tolist(),
                    # Was sweep["min_feasible_ramp_minutes"].iloc[0] -- the value at
                    # the *shortest* ramp in the sweep, where almost no added mass
                    # participates, so the unreachable band was drawn far too narrow.
                    "fastest_ramp_minutes": float(np.asarray(fastest_ramp_minutes(params)).item()),
                },
            }
        )

    @app.post("/api/scenario")
    def api_scenario():
        """Round-trip a scenario file through the browser's download/upload."""
        params, problems = _params_from_request()
        payload = request.get_json(silent=True) or {}
        return jsonify(
            {
                "format": 1,
                "name": payload.get("name", ""),
                "notes": payload.get("notes", ""),
                "params": params.to_dict(),
                "problems": problems,
            }
        )

    return app


app = create_app()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Chamber sizing tool")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    print(f"Chamber sizing tool on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
