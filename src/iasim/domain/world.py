"""World structures and their placement."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType


class StructureKind(StrEnum):
    """Placeable structures from SRS section 3.7."""

    WORKBENCH = "workbench"
    SHELTER = "shelter"
    FIRE = "fire"

    @property
    def tile(self) -> TileType:
        """Return the map tile that represents this structure."""
        return _STRUCTURE_TILES[self]


_STRUCTURE_TILES: dict[StructureKind, TileType] = {
    StructureKind.WORKBENCH: TileType.WORKBENCH,
    StructureKind.SHELTER: TileType.SHELTER,
    StructureKind.FIRE: TileType.FIRE,
}

FIRE_MAX_FUEL = 100


@dataclass(frozen=True, slots=True)
class Structure:
    """A placed world structure."""

    kind: StructureKind
    position: Position
    fuel: int = 0
    lit: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.kind, StructureKind):
            raise ValueError(f"kind must be a StructureKind, got {self.kind!r}")
        if type(self.fuel) is not int or not 0 <= self.fuel <= FIRE_MAX_FUEL:
            raise ValueError(f"fuel must be within [0, {FIRE_MAX_FUEL}], got {self.fuel!r}")
        if not isinstance(self.lit, bool):
            raise ValueError(f"lit must be a boolean, got {self.lit!r}")
        if self.kind is not StructureKind.FIRE and (self.fuel != 0 or self.lit):
            raise ValueError("only fires may carry fuel or a lit state")
