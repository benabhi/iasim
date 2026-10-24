"""libtcod-backed field-of-view adapter for the immutable world model."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import tcod

from iasim.domain.geometry import Position
from iasim.domain.tiles import WorldMap

FOV_ALGORITHM = tcod.constants.FOV_RESTRICTIVE


@lru_cache(maxsize=8)
def _transparency(world: WorldMap) -> np.ndarray:
    """Return the cached [x, y] transparency array for an immutable world."""
    return np.asarray(
        [
            [world.tile_at(Position(x, y)).transparent for y in range(world.height)]
            for x in range(world.width)
        ],
        dtype=bool,
    )


def compute_fov(
    world: WorldMap,
    origin: Position,
    radius: int,
) -> frozenset[Position]:
    """Return the positions visible from ``origin`` using libtcod.

    The world remains the source of truth for tiles and blockers. The result is
    converted to immutable ``Position`` values before leaving this adapter.
    """
    if not world.contains(origin):
        raise ValueError(f"origin {origin} is outside the world")
    if type(radius) is not int or radius < 0:
        raise ValueError(f"radius must be a non-negative integer, got {radius!r}")
    if radius == 0:
        return frozenset({origin})

    # python-tcod map arrays are indexed by [x, y], unlike row-major consoles.
    visibility = tcod.map.compute_fov(
        _transparency(world),
        (origin.x, origin.y),
        radius=radius,
        light_walls=True,
        algorithm=FOV_ALGORITHM,
    )
    return frozenset(Position(int(x), int(y)) for x, y in np.argwhere(visibility))


def has_line_of_sight(
    world: WorldMap,
    origin: Position,
    target: Position,
    radius: int,
) -> bool:
    """Return whether ``target`` lies in the area visible from ``origin``.

    Used by the thrown-stone resolver so combat and perception agree on what an
    agent can see.
    """
    return target in compute_fov(world, origin, radius)
