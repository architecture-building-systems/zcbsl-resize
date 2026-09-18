"""The six surfaces of a shoebox room.

The earlier model had one "facade" plus a ceiling, and lumped everything else
into a single adiabatic residual.  That breaks the moment a room has more than
one exterior wall: the climate chamber has three, carrying 204 m2 that the old
model called adiabatic.  Understating its envelope conductance by 2.4x.

So the envelope is now described surface by surface.  Areas come from the
geometry; each surface carries its own construction and its own exposure.

Axis convention
---------------
``width`` runs east-west, ``depth`` runs north-south.  So the north and south
walls are ``width x height``, the east and west walls are ``depth x height``,
and the roof and floor are ``width x depth``.  Rotate the room by relabelling
which wall you call north.

Exposure
--------
``exposure`` blends the temperature a surface faces, from the surrounding lab
to the outdoor design condition::

    T_face = T_surrounding + exposure * (T_outdoor - T_surrounding)

So ``exposure = 1`` is a true exterior surface, ``exposure = 0`` is one facing
conditioned space, and values between cover a buffer space such as an
unheated corridor.  A surface that conducts nothing at all is expressed by
setting its U-values to zero, not by its exposure.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Surface:
    """One face of the shoebox."""

    key: str
    label: str
    axis: str  # "width" | "depth" | "plan"

    def area(self, width, depth, height):
        """Surface area, m^2, from the room geometry."""
        if self.axis == "width":
            return np.asarray(width, dtype=float) * np.asarray(height, dtype=float)
        if self.axis == "depth":
            return np.asarray(depth, dtype=float) * np.asarray(height, dtype=float)
        return np.asarray(width, dtype=float) * np.asarray(depth, dtype=float)


SURFACES: tuple[Surface, ...] = (
    Surface("north", "North wall", "width"),
    Surface("east", "East wall", "depth"),
    Surface("south", "South wall", "width"),
    Surface("west", "West wall", "depth"),
    Surface("roof", "Roof", "plan"),
    Surface("floor", "Floor", "plan"),
)

SURFACES_BY_KEY: dict[str, Surface] = {s.key: s for s in SURFACES}

#: The per-surface properties, as (suffix, label, unit).
SURFACE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("u_opaque", "U, opaque", "W/m²K"),
    ("u_glazing", "U, glazing", "W/m²K"),
    ("wwr", "Glazed fraction", "%"),
    ("shgc", "Glazing SHGC", ""),
    ("irradiance", "Peak irradiance", "W/m²"),
    ("exposure", "Exposure to outdoors", ""),
)


def field_name(surface_key: str, suffix: str) -> str:
    """Flat parameter name, e.g. ``north_u_opaque``.

    Kept flat so the parameter set stays a plain float mapping: numpy
    broadcasting, scenario JSON and DataFrame sweeps all keep working unchanged.
    """
    return f"{surface_key}_{suffix}"


def surface_field_names() -> list[str]:
    return [field_name(s.key, suffix) for s in SURFACES for suffix, _, _ in SURFACE_FIELDS]


def areas(width, depth, height) -> dict[str, np.ndarray]:
    """Every surface area, keyed by surface."""
    return {s.key: s.area(width, depth, height) for s in SURFACES}


def interior_area(width, depth, height):
    """Total interior surface area, the sum of all six faces."""
    total = 0.0
    for surface in SURFACES:
        total = total + surface.area(width, depth, height)
    return total
