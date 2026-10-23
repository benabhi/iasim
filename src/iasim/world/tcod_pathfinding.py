"""libtcod-backed deterministic pathfinding adapter."""

from __future__ import annotations

import numpy as np
import tcod.path

from iasim.domain.geometry import Position
from iasim.domain.tiles import WorldMap

DIAGONAL_COST = 1.0


def find_path(
    world: WorldMap,
    start: Position,
    goal: Position,
    *,
    blocked: frozenset[Position] = frozenset(),
) -> tuple[Position, ...]:
    """Return a deterministic route from ``start`` to ``goal``.

    The returned path excludes ``start`` and contains the goal as its last
    element. An empty tuple means the goal is invalid or unreachable.
    """
    if not world.contains(start):
        raise ValueError(f"start {start} is outside the world")
    if not world.contains(goal):
        raise ValueError(f"goal {goal} is outside the world")
    if goal in blocked:
        return ()

    cost = np.zeros((world.width, world.height), dtype=np.float32)
    for y in range(world.height):
        for x in range(world.width):
            position = Position(x, y)
            if position in blocked:
                continue
            movement_cost = world.tile_at(position).movement_cost
            if movement_cost is not None:
                cost[x, y] = movement_cost

    path = tcod.path.AStar(cost, diagonal=DIAGONAL_COST).get_path(
        start.x,
        start.y,
        goal.x,
        goal.y,
    )
    return tuple(Position(int(x), int(y)) for x, y in path)
