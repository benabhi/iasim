"""Tests for deterministic island generation."""

from __future__ import annotations

import hashlib
import unittest
from collections import deque
from collections.abc import Callable

from iasim.domain.tiles import TileType, WorldMap
from iasim.world.generation import WORLD_HEIGHT, WORLD_WIDTH, generate_world

REPRESENTATIVE_SEEDS = (0, 1, 42, 12345)
GOLDEN_HASH_SEED_42 = "8dd90a111c8bb89dc712f98cd91771b0d0db144819ac3278ce80634867e8deb9"

WATER_TILES = frozenset({TileType.DEEP_WATER, TileType.SHALLOW_WATER, TileType.FRESH_WATER})
NATURAL_TILES = frozenset(
    {
        TileType.DEEP_WATER,
        TileType.SHALLOW_WATER,
        TileType.FRESH_WATER,
        TileType.SAND,
        TileType.GRASS,
        TileType.TALL_GRASS,
        TileType.TREE,
        TileType.PALM,
        TileType.BUSH,
        TileType.ROCK,
        TileType.ROCKY_GROUND,
        TileType.CLAY,
    }
)


def _hash(world: WorldMap) -> str:
    payload = ",".join(tile.value for tile in world.tiles).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _components(world: WorldMap, predicate: Callable[[TileType], bool]) -> list[int]:
    seen: set[int] = set()
    sizes: list[int] = []
    for start, tile in enumerate(world.tiles):
        if start in seen or not predicate(tile):
            continue
        queue = deque([start])
        seen.add(start)
        size = 0
        while queue:
            current = queue.popleft()
            size += 1
            y, x = divmod(current, WORLD_WIDTH)
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < WORLD_WIDTH and 0 <= ny < WORLD_HEIGHT:
                    neighbour = ny * WORLD_WIDTH + nx
                    if neighbour not in seen and predicate(world.tiles[neighbour]):
                        seen.add(neighbour)
                        queue.append(neighbour)
        sizes.append(size)
    return sorted(sizes, reverse=True)


def _touches(world: WorldMap, index: int, targets: frozenset[TileType]) -> bool:
    y, x = divmod(index, WORLD_WIDTH)
    for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
        if (
            0 <= nx < WORLD_WIDTH
            and 0 <= ny < WORLD_HEIGHT
            and world.tiles[ny * WORLD_WIDTH + nx] in targets
        ):
            return True
    return False


class WorldGenerationTests(unittest.TestCase):
    def test_dimensions_and_border_are_fixed(self) -> None:
        world = generate_world(42)

        self.assertEqual(world.width, WORLD_WIDTH)
        self.assertEqual(world.height, WORLD_HEIGHT)
        self.assertEqual(len(world.tiles), WORLD_WIDTH * WORLD_HEIGHT)
        for x in range(WORLD_WIDTH):
            self.assertIs(world.tiles[x], TileType.DEEP_WATER)
            self.assertIs(
                world.tiles[(WORLD_HEIGHT - 1) * WORLD_WIDTH + x],
                TileType.DEEP_WATER,
            )
        for y in range(WORLD_HEIGHT):
            self.assertIs(world.tiles[y * WORLD_WIDTH], TileType.DEEP_WATER)
            self.assertIs(
                world.tiles[y * WORLD_WIDTH + WORLD_WIDTH - 1],
                TileType.DEEP_WATER,
            )

    def test_same_seed_is_deterministic(self) -> None:
        first = generate_world(42)
        second = generate_world(42)

        self.assertEqual(first.tiles, second.tiles)
        self.assertEqual(_hash(first), _hash(second))

    def test_golden_map_for_seed_42(self) -> None:
        self.assertEqual(_hash(generate_world(42)), GOLDEN_HASH_SEED_42)

    def test_different_seeds_produce_different_maps(self) -> None:
        self.assertNotEqual(_hash(generate_world(42)), _hash(generate_world(43)))

    def test_representative_seeds_have_all_natural_tiles(self) -> None:
        for seed in REPRESENTATIVE_SEEDS:
            with self.subTest(seed=seed):
                world = generate_world(seed)

                self.assertEqual(set(world.tiles), NATURAL_TILES)

    def test_land_is_connected(self) -> None:
        for seed in REPRESENTATIVE_SEEDS:
            with self.subTest(seed=seed):
                world = generate_world(seed)
                components = _components(world, lambda tile: tile not in WATER_TILES)

                self.assertEqual(len(components), 1)
                self.assertGreater(components[0], 0)

    def test_river_is_connected_and_reaches_the_sea(self) -> None:
        for seed in REPRESENTATIVE_SEEDS:
            with self.subTest(seed=seed):
                world = generate_world(seed)
                components = _components(world, lambda tile: tile is TileType.FRESH_WATER)
                river = [
                    index for index, tile in enumerate(world.tiles) if tile is TileType.FRESH_WATER
                ]

                self.assertEqual(len(components), 1)
                self.assertGreater(components[0], 0)
                self.assertTrue(
                    any(
                        _touches(
                            world,
                            index,
                            frozenset({TileType.DEEP_WATER, TileType.SHALLOW_WATER}),
                        )
                        for index in river
                    )
                )

    def test_clay_is_adjacent_to_fresh_water(self) -> None:
        for seed in REPRESENTATIVE_SEEDS:
            with self.subTest(seed=seed):
                world = generate_world(seed)
                for index, tile in enumerate(world.tiles):
                    if tile is TileType.CLAY:
                        self.assertTrue(
                            _touches(world, index, frozenset({TileType.FRESH_WATER})),
                            f"clay at index {index} is not next to fresh water",
                        )

    def test_land_share_is_plausible(self) -> None:
        for seed in REPRESENTATIVE_SEEDS:
            with self.subTest(seed=seed):
                world = generate_world(seed)
                land = sum(1 for tile in world.tiles if tile not in WATER_TILES)
                percentage = land * 100 // (WORLD_WIDTH * WORLD_HEIGHT)

                self.assertGreaterEqual(percentage, 30)
                self.assertLessEqual(percentage, 70)

    def test_negative_seed_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            generate_world(-1)


if __name__ == "__main__":
    unittest.main()
