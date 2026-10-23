"""Tests for world layout validation and spawn selection."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import iasim.world.generation as generation
from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType, WorldMap
from iasim.errors import WorldGenerationError, WorldValidationError
from iasim.world.generation import generate_layout
from iasim.world.layout import WorldLayout
from iasim.world.rules import MIN_SPAWN_DISTANCE, SPAWN_ALLOWED_TILES
from iasim.world.validation import manhattan, validate_layout

REPRESENTATIVE_SEEDS = (0, 1, 42, 12345)


def _replace_tiles(world: WorldMap, replacements: dict[int, TileType]) -> WorldMap:
    tiles = list(world.tiles)
    for index, tile in replacements.items():
        tiles[index] = tile
    return WorldMap(width=world.width, height=world.height, tiles=tuple(tiles))


def _find_index(world: WorldMap, tile_type: TileType) -> int:
    return next(index for index, tile in enumerate(world.tiles) if tile is tile_type)


def _position(world: WorldMap, index: int) -> Position:
    return Position(index % world.width, index // world.width)


def _close_allowed_position(world: WorldMap, origin: Position) -> Position:
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        x, y = origin.x + dx, origin.y + dy
        if (
            0 <= x < world.width
            and 0 <= y < world.height
            and world.tile_at(Position(x, y)) in SPAWN_ALLOWED_TILES
        ):
            return Position(x, y)
    raise AssertionError("no allowed neighbour found")


class WorldValidationTests(unittest.TestCase):
    def test_generated_layouts_are_valid_for_one_to_eight_agents(self) -> None:
        for seed in REPRESENTATIVE_SEEDS:
            for agent_count in (1, 2, 8):
                with self.subTest(seed=seed, agent_count=agent_count):
                    layout = generate_layout(seed, agent_count=agent_count)

                    self.assertEqual(len(layout.spawn_points), agent_count)
                    self.assertEqual(len(set(layout.spawn_points)), agent_count)
                    validate_layout(layout)

    def test_spawns_are_walkable_and_separated(self) -> None:
        layout = generate_layout(42, agent_count=8)

        for spawn in layout.spawn_points:
            self.assertIn(layout.world.tile_at(spawn), SPAWN_ALLOWED_TILES)
        for index, first in enumerate(layout.spawn_points):
            for second in layout.spawn_points[index + 1 :]:
                self.assertGreaterEqual(manhattan(first, second), MIN_SPAWN_DISTANCE)

    def test_agent_count_bounds_are_enforced(self) -> None:
        with self.assertRaises(ValueError):
            generate_layout(42, agent_count=0)
        with self.assertRaises(ValueError):
            generate_layout(42, agent_count=9)

    def test_validate_rejects_spawn_on_water_and_rock(self) -> None:
        layout = generate_layout(42, agent_count=2)
        world = layout.world

        water = _position(world, _find_index(world, TileType.FRESH_WATER))
        invalid = WorldLayout(
            seed=42,
            world=world,
            spawn_points=(water, layout.spawn_points[1]),
        )
        with self.assertRaises(WorldValidationError) as raised:
            validate_layout(invalid)
        self.assertIn("is on fresh_water", str(raised.exception))

        rock = _position(world, _find_index(world, TileType.ROCK))
        invalid = WorldLayout(
            seed=42,
            world=world,
            spawn_points=(rock, layout.spawn_points[1]),
        )
        with self.assertRaises(WorldValidationError) as raised:
            validate_layout(invalid)
        self.assertIn("is on rock", str(raised.exception))

    def test_validate_rejects_duplicate_and_too_close_spawns(self) -> None:
        layout = generate_layout(42, agent_count=2)
        first = layout.spawn_points[0]

        duplicate = WorldLayout(
            seed=42,
            world=layout.world,
            spawn_points=(first, first),
        )
        with self.assertRaises(WorldValidationError) as raised:
            validate_layout(duplicate)
        self.assertIn("spawn points must be distinct", str(raised.exception))

        close = _close_allowed_position(layout.world, first)
        too_close = WorldLayout(
            seed=42,
            world=layout.world,
            spawn_points=(first, close),
        )
        with self.assertRaises(WorldValidationError) as raised:
            validate_layout(too_close)
        self.assertIn("cells apart", str(raised.exception))

    def test_validate_rejects_disconnected_spawn(self) -> None:
        width, height = 12, 3
        tiles = [TileType.DEEP_WATER] * (width * height)
        for x, y in ((0, 0), (1, 0), (0, 1), (1, 1), (10, 0), (11, 0), (10, 1), (11, 1)):
            tiles[y * width + x] = TileType.GRASS
        world = WorldMap(width=width, height=height, tiles=tuple(tiles))
        layout = WorldLayout(
            seed=1,
            world=world,
            spawn_points=(Position(1, 0), Position(11, 0)),
        )

        with self.assertRaises(WorldValidationError) as raised:
            validate_layout(layout)
        self.assertIn(
            "is not connected to the largest walkable component",
            str(raised.exception),
        )

    def test_validate_rejects_missing_resources(self) -> None:
        cases = (
            (
                "fresh water",
                frozenset({TileType.FRESH_WATER}),
                TileType.GRASS,
            ),
            (
                "food",
                frozenset({TileType.BUSH, TileType.PALM}),
                TileType.GRASS,
            ),
            (
                "wood",
                frozenset({TileType.TREE, TileType.PALM}),
                TileType.GRASS,
            ),
            (
                "rock",
                frozenset({TileType.ROCK, TileType.ROCKY_GROUND}),
                TileType.GRASS,
            ),
        )

        for resource_name, sources, replacement in cases:
            with self.subTest(resource=resource_name):
                layout = generate_layout(42, agent_count=1)
                replacements = {
                    index: replacement
                    for index, tile in enumerate(layout.world.tiles)
                    if tile in sources
                }
                world = _replace_tiles(layout.world, replacements)
                invalid = WorldLayout(
                    seed=42,
                    world=world,
                    spawn_points=layout.spawn_points,
                )

                with self.assertRaises(WorldValidationError) as raised:
                    validate_layout(invalid)
                self.assertIn(f"missing {resource_name} source", str(raised.exception))

    def test_validate_rejects_spawn_too_far_from_resources(self) -> None:
        width, height = 40, 40
        tiles = [TileType.GRASS] * (width * height)
        tiles[0] = TileType.FRESH_WATER
        tiles[1] = TileType.BUSH
        tiles[2] = TileType.TREE
        tiles[3] = TileType.ROCK
        world = WorldMap(width=width, height=height, tiles=tuple(tiles))
        layout = WorldLayout(
            seed=1,
            world=world,
            spawn_points=(Position(39, 39),),
        )

        with self.assertRaises(WorldValidationError) as raised:
            validate_layout(layout)
        message = str(raised.exception)
        self.assertIn("cells from fresh water", message)
        self.assertIn("cells from food", message)
        self.assertIn("cells from wood", message)
        self.assertIn("cells from rock", message)

    def test_validate_rejects_out_of_bounds_and_empty_spawns(self) -> None:
        world = generate_layout(42, agent_count=1).world

        outside = WorldLayout(
            seed=42,
            world=world,
            spawn_points=(Position(world.width, 0),),
        )
        with self.assertRaises(WorldValidationError) as raised:
            validate_layout(outside)
        self.assertIn("is outside the world", str(raised.exception))

        empty = WorldLayout(seed=42, world=world, spawn_points=())
        with self.assertRaises(WorldValidationError) as raised:
            validate_layout(empty)
        self.assertIn("no spawn points", str(raised.exception))

    def test_retries_are_bounded_and_deterministic(self) -> None:
        seeds: list[int] = []

        def fail_generation(seed: int) -> None:
            seeds.append(seed)
            return None

        with patch.object(generation, "_generate_once", side_effect=fail_generation):
            with self.assertRaises(WorldGenerationError):
                generation.generate_layout(42, agent_count=1)
            first = list(seeds)
            seeds.clear()
            with self.assertRaises(WorldGenerationError):
                generation.generate_layout(42, agent_count=1)
            second = list(seeds)

        self.assertEqual(len(first), generation._MAX_ATTEMPTS)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
