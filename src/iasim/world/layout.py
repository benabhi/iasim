"""Validated world layout with agent spawn points."""

from __future__ import annotations

from dataclasses import dataclass

from iasim.domain.geometry import Position
from iasim.domain.tiles import WorldMap


@dataclass(frozen=True, slots=True)
class WorldLayout:
    """A generated world and its validated agent spawn points."""

    seed: int
    world: WorldMap
    spawn_points: tuple[Position, ...]
