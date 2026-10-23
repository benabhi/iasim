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


@dataclass(frozen=True, slots=True)
class Structure:
    """A placed world structure."""

    kind: StructureKind
    position: Position

    def __post_init__(self) -> None:
        if not isinstance(self.kind, StructureKind):
            raise ValueError(f"kind must be a StructureKind, got {self.kind!r}")
