"""libtcod-backed field-of-view adapter for the immutable world model."""

from __future__ import annotations

import numpy as np
import tcod

from iasim.domain.geometry import Position
from iasim.domain.tiles import WorldMap

FOV_ALGORITHM = tcod.constants.FOV_RESTRICTIVE


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
    transparency = np.asarray(
        [
            [world.tile_at(Position(x, y)).transparent for y in range(world.height)]
            for x in range(world.width)
        ],
        dtype=bool,
    )
    visibility = tcod.map.compute_fov(
        transparency,
        (origin.x, origin.y),
        radius=radius,
        light_walls=True,
        algorithm=FOV_ALGORITHM,
    )
    return frozenset(Position(int(x), int(y)) for x, y in np.argwhere(visibility))
