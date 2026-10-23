"""Shared world generation and validation rules."""

from __future__ import annotations

from iasim.domain.tiles import TileType

WATER_TILES = frozenset({TileType.DEEP_WATER, TileType.SHALLOW_WATER, TileType.FRESH_WATER})

SPAWN_ALLOWED_TILES = frozenset(
    {
        TileType.SAND,
        TileType.GRASS,
        TileType.TALL_GRASS,
        TileType.BUSH,
        TileType.ROCKY_GROUND,
        TileType.CLAY,
    }
)

FRESH_WATER_SOURCES = frozenset({TileType.FRESH_WATER})
FOOD_SOURCES = frozenset({TileType.BUSH, TileType.PALM})
WOOD_SOURCES = frozenset({TileType.TREE, TileType.PALM})
ROCK_SOURCES = frozenset({TileType.ROCK, TileType.ROCKY_GROUND})

MIN_SPAWN_DISTANCE = 8
MAX_FRESH_WATER_DISTANCE = 15
MAX_RESOURCE_DISTANCE = 10
