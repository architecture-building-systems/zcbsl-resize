"""The two real rooms.

Baseline parameter sets for the ZCBS Lab rooms being sized.  The study config
in ``study/rooms.yaml`` sweeps around these; anything not swept stays as
defined here.

Axis convention (see ``surfaces.py``): width runs east-west, depth runs
north-south, so the north and south walls are ``width x height``.  Both rooms
happen to put their exterior facade on a width wall.
"""

from __future__ import annotations

from .params import ChamberParams

#: Interior lining of both rooms is aluminium bonded to insulated panels, with
#: some glass. Thermally thin, so the whole layer participates: kJ/m2K.
ALUMINIUM_AND_GLASS_SHELL = 7.0

#: Total light output of the Artificial Sun into the climate chamber, W.
#: 1200 W/m2 over an 8.75 m2 aperture.
ARTIFICIAL_SUN_W = 1200.0 * 8.75


def module_room() -> ChamberParams:
    """The module room: one exterior wall plus the roof, exchangeable envelope.

    3.75 wide x 4.50 deep x 5.20 high.  The south wall faces outdoors with real
    solar exposure; the other three walls and the floor face conditioned lab
    space.  The roof is a real roof.

    Envelope values here are mid-range placeholders: this room's whole point is
    that the construction is swappable, so ``study/rooms.yaml`` sweeps them.
    """
    params = ChamberParams(
        width=3.75,
        depth=4.50,
        height=5.20,
        base_shell_capacity=ALUMINIUM_AND_GLASS_SHELL,
        boundary_temp_winter=-8.0,
        boundary_temp_summer=45.0,
        surrounding_temp=21.0,
    )
    params = params.with_surface(
        "south", u_opaque=0.30, u_glazing=1.00, wwr=40.0, shgc=0.50,
        irradiance=1500.0, exposure=1.0,
    )
    params = params.with_surface(
        "roof", u_opaque=0.30, u_glazing=0.0, wwr=0.0, shgc=0.0,
        irradiance=0.0, exposure=1.0,
    )
    for wall in ("north", "east", "west"):
        params = params.with_surface(
            wall, u_opaque=0.05, u_glazing=0.0, wwr=0.0, shgc=0.0,
            irradiance=0.0, exposure=0.0,
        )
    return params.with_surface(
        "floor", u_opaque=0.05, u_glazing=0.0, wwr=0.0, shgc=0.0,
        irradiance=0.0, exposure=0.0,
    )


def climate_chamber() -> ChamberParams:
    """The climate chamber: three exterior walls plus the roof, fixed envelope.

    10.5 wide x 6.9 deep x 8.7 high (corrected 2026-09-18; the geometry was
    previously wrong -- 8.00 x 4.50 x 12.00). North, east and west walls are
    exterior and carry the clerestory glazing at 40%.  The south wall faces
    interior space, as does the floor.  The roof is a real roof.

    The envelope cannot be exchanged, so these are fixed values rather than
    sweep baselines.  Glazing is xenon-filled insulating glass extrusions; the
    U-value of 1.2 is the figure given for the installed units, which is
    conservative for a xenon fill.

    Houses the Artificial Sun: 1200 W/m2 over 8.75 m2 is 10 500 W of light into
    the room.  LED cooling is extracted separately, so only the light itself is
    an internal gain.  Over a 72.45 m2 floor that is 144.9 W/m2.
    """
    params = ChamberParams(
        width=10.5,
        depth=6.9,
        height=8.7,
        base_shell_capacity=ALUMINIUM_AND_GLASS_SHELL,
        boundary_temp_winter=-8.0,
        boundary_temp_summer=45.0,
        surrounding_temp=21.0,
        equipment_w_per_m2=ARTIFICIAL_SUN_W / (10.5 * 6.9),
    )
    # North, east and west: exterior, clerestory glazing.
    # East and west irradiance is an assumption - only the north figure was given.
    for wall, irradiance in (("north", 400.0), ("east", 550.0), ("west", 550.0)):
        params = params.with_surface(
            wall, u_opaque=0.90, u_glazing=1.20, wwr=40.0, shgc=0.10,
            irradiance=irradiance, exposure=1.0,
        )
    params = params.with_surface(
        "south", u_opaque=0.90, u_glazing=0.0, wwr=0.0, shgc=0.0,
        irradiance=0.0, exposure=0.0,
    )
    params = params.with_surface(
        "roof", u_opaque=0.40, u_glazing=0.0, wwr=0.0, shgc=0.0,
        irradiance=0.0, exposure=1.0,
    )
    return params.with_surface(
        "floor", u_opaque=0.05, u_glazing=0.0, wwr=0.0, shgc=0.0,
        irradiance=0.0, exposure=0.0,
    )



#: Which of each room's baseline values are *measured properties* rather than
#: mid-range placeholders waiting to be swept.
#:
#: The distinction cannot be inferred.  Both rooms set ``south_u_opaque``, but
#: for the module room that is a placeholder -- the whole point of the room is
#: that the facade is exchangeable -- while for the climate chamber it is the
#: construction that is actually installed and cannot be changed.  Sweeping a
#: measured value replaces a known number with a guess, so ``check_config.py``
#: says so out loud; sweeping a placeholder is the study doing its job.
_GEOMETRY_AND_SITE = frozenset({
    "width", "depth", "height",
    "base_shell_capacity",
    "boundary_temp_winter", "boundary_temp_summer", "surrounding_temp",
    *(f"{wall}_exposure" for wall in ("north", "east", "south", "west", "roof", "floor")),
})

#: The climate chamber's envelope is installed and fixed, so every surface
#: property is measured.  East and west irradiance are the exception in spirit
#: -- 550 W/m2 is an assumption, only the north figure of 400 was given -- but
#: nothing sweeps them, and the assumption is recorded in study/rooms.yaml.
_CHAMBER_ENVELOPE = frozenset(
    f"{wall}_{prop}"
    for wall in ("north", "east", "south", "west", "roof", "floor")
    for prop in ("u_opaque", "u_glazing", "wwr", "shgc", "irradiance")
)

MEASURED: dict[str, frozenset[str]] = {
    "module_room": _GEOMETRY_AND_SITE,
    "climate_chamber": _GEOMETRY_AND_SITE | _CHAMBER_ENVELOPE | {"equipment_w_per_m2"},
}


ROOMS = {
    "module_room": ("Module room", module_room),
    "climate_chamber": ("Climate chamber", climate_chamber),
}


def get(name: str) -> ChamberParams:
    """Look up a room by key."""
    if name not in ROOMS:
        raise KeyError(f"unknown room {name!r}; expected one of {sorted(ROOMS)}")
    return ROOMS[name][1]()
