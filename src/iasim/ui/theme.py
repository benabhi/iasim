"""Glyphs and colors for the operator terminal UI."""

from __future__ import annotations

from iasim.domain.tiles import TileType

RGB = tuple[int, int, int]

BLACK: RGB = (8, 9, 12)
WHITE: RGB = (228, 231, 236)
DIM: RGB = (110, 116, 128)
CYAN: RGB = (120, 210, 220)
YELLOW: RGB = (240, 220, 120)
RED: RGB = (230, 120, 120)
GREEN: RGB = (140, 220, 140)
PANEL_BG: RGB = (14, 17, 23)
SELECTED_BG: RGB = (30, 58, 74)
BAR_BG: RGB = (30, 34, 42)
BAR_FG: RGB = (235, 238, 242)
AGENT_COLOR: RGB = (255, 230, 120)

TILE_GLYPHS: dict[TileType, str] = {tile: tile.glyph for tile in TileType}

ASCII_TILE_GLYPHS: dict[TileType, str] = {
    TileType.DEEP_WATER: "~",
    TileType.SHALLOW_WATER: "~",
    TileType.FRESH_WATER: "~",
    TileType.SAND: ".",
    TileType.GRASS: ",",
    TileType.TALL_GRASS: '"',
    TileType.TREE: "T",
    TileType.PALM: "P",
    TileType.BUSH: "b",
    TileType.ROCK: "^",
    TileType.ROCKY_GROUND: ":",
    TileType.CLAY: "c",
    TileType.WORKBENCH: "=",
    TileType.SHELTER: "n",
    TileType.FIRE: "*",
    TileType.CORPSE: "x",
    TileType.GROUND_ITEM: "!",
}

ASCII_BAR_FILLED = "#"
ASCII_BAR_EMPTY = "-"
ASCII_VERTICAL = "|"
ASCII_HORIZONTAL = "-"


def tile_glyph(tile: TileType, *, ascii_mode: bool = False) -> str:
    """Return the map glyph for a tile, using the ASCII fallback when requested."""
    return ASCII_TILE_GLYPHS[tile] if ascii_mode else TILE_GLYPHS[tile]


TILE_COLORS: dict[TileType, RGB] = {
    TileType.DEEP_WATER: (70, 110, 180),
    TileType.SHALLOW_WATER: (90, 150, 220),
    TileType.FRESH_WATER: (120, 200, 240),
    TileType.SAND: (220, 200, 150),
    TileType.GRASS: (100, 190, 100),
    TileType.TALL_GRASS: (70, 150, 80),
    TileType.TREE: (50, 130, 60),
    TileType.PALM: (180, 200, 90),
    TileType.BUSH: (130, 210, 110),
    TileType.ROCK: (160, 160, 160),
    TileType.ROCKY_GROUND: (190, 190, 170),
    TileType.CLAY: (200, 150, 100),
    TileType.WORKBENCH: (200, 150, 90),
    TileType.SHELTER: (210, 180, 130),
    TileType.FIRE: (250, 150, 60),
    TileType.CORPSE: (220, 220, 220),
    TileType.GROUND_ITEM: (240, 220, 120),
}

TILE_BACKGROUNDS: dict[TileType, RGB] = {
    TileType.DEEP_WATER: (8, 16, 32),
    TileType.SHALLOW_WATER: (12, 32, 52),
    TileType.FRESH_WATER: (16, 48, 64),
    TileType.SAND: (42, 38, 28),
    TileType.GRASS: (18, 34, 20),
    TileType.TALL_GRASS: (16, 30, 18),
    TileType.TREE: (10, 26, 14),
    TileType.PALM: (28, 38, 16),
    TileType.BUSH: (20, 38, 22),
    TileType.ROCK: (32, 32, 34),
    TileType.ROCKY_GROUND: (28, 28, 30),
    TileType.CLAY: (38, 28, 22),
    TileType.WORKBENCH: (36, 26, 18),
    TileType.SHELTER: (34, 28, 22),
    TileType.FIRE: (48, 24, 12),
    TileType.CORPSE: (28, 28, 28),
    TileType.GROUND_ITEM: (34, 30, 18),
}

TILE_LABELS: dict[TileType, str] = {
    TileType.DEEP_WATER: "agua profunda",
    TileType.SHALLOW_WATER: "agua somera",
    TileType.FRESH_WATER: "río",
    TileType.SAND: "arena",
    TileType.GRASS: "pasto",
    TileType.TALL_GRASS: "pasto alto",
    TileType.TREE: "árbol",
    TileType.PALM: "palmera",
    TileType.BUSH: "arbusto",
    TileType.ROCK: "roca",
    TileType.ROCKY_GROUND: "suelo rocoso",
    TileType.CLAY: "arcilla",
    TileType.WORKBENCH: "mesa de trabajo",
    TileType.SHELTER: "refugio",
    TileType.FIRE: "fuego",
    TileType.CORPSE: "cadáver",
    TileType.GROUND_ITEM: "objeto",
}
