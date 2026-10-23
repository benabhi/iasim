"""World tile types and the immutable world grid."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from iasim.domain.geometry import Position


class TileType(StrEnum):
    """Simulation properties of the SRS 3.3.1 tiles."""

    DEEP_WATER = "deep_water"
    SHALLOW_WATER = "shallow_water"
    FRESH_WATER = "fresh_water"
    SAND = "sand"
    GRASS = "grass"
    TALL_GRASS = "tall_grass"
    TREE = "tree"
    PALM = "palm"
    BUSH = "bush"
    ROCK = "rock"
    ROCKY_GROUND = "rocky_ground"
    CLAY = "clay"
    WORKBENCH = "workbench"
    SHELTER = "shelter"
    FIRE = "fire"
    CORPSE = "corpse"
    GROUND_ITEM = "ground_item"

    @property
    def walkable(self) -> bool:
        """Return whether an agent may enter the tile."""
        return self not in {
            TileType.DEEP_WATER,
            TileType.TREE,
            TileType.PALM,
            TileType.ROCK,
            TileType.WORKBENCH,
            TileType.FIRE,
        }

    @property
    def transparent(self) -> bool:
        """Return whether the tile lets vision pass through."""
        return self not in {
            TileType.DEEP_WATER,
            TileType.TREE,
            TileType.PALM,
            TileType.ROCK,
            TileType.WORKBENCH,
            TileType.FIRE,
        }

    @property
    def movement_cost(self) -> int | None:
        """Return the movement cost, or ``None`` when impassable."""
        if not self.walkable:
            return None
        if self in {TileType.SHALLOW_WATER, TileType.FRESH_WATER}:
            return 2
        return 1

    @property
    def drinkable(self) -> bool:
        """Return whether the tile provides fresh drinking water."""
        return self is TileType.FRESH_WATER


@dataclass(frozen=True, slots=True)
class WorldMap:
    """Immutable row-major grid of tiles."""

    width: int
    height: int
    tiles: tuple[TileType, ...]

    def __post_init__(self) -> None:
        if self.width < 1:
            raise ValueError(f"width must be at least 1, got {self.width}")
        if self.height < 1:
            raise ValueError(f"height must be at least 1, got {self.height}")
        expected = self.width * self.height
        if len(self.tiles) != expected:
            raise ValueError(f"tiles must contain {expected} entries, got {len(self.tiles)}")
        if not all(isinstance(tile, TileType) for tile in self.tiles):
            raise ValueError("tiles must contain only TileType values")

    def contains(self, position: Position) -> bool:
        """Return whether a position is inside the map."""
        return 0 <= position.x < self.width and 0 <= position.y < self.height

    def tile_at(self, position: Position) -> TileType:
        """Return the tile at a position, rejecting out-of-bounds access."""
        if not self.contains(position):
            raise ValueError(f"position {position} is outside the {self.width}x{self.height} map")
        return self.tiles[position.y * self.width + position.x]

    @classmethod
    def filled(cls, width: int, height: int, tile: TileType) -> WorldMap:
        """Create a map filled with one tile type."""
        return cls(width=width, height=height, tiles=(tile,) * (width * height))
