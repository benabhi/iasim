"""Tests for the libtcod-backed FOV adapter."""

from __future__ import annotations

import unittest

from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType, WorldMap
from iasim.world.tcod_fov import compute_fov


def _world(
    *,
    blocker: Position | None = None,
    blocker_type: TileType = TileType.TREE,
) -> WorldMap:
    tiles = [TileType.GRASS] * 49
    if blocker is not None:
        tiles[blocker.y * 7 + blocker.x] = blocker_type
    return WorldMap(width=7, height=7, tiles=tuple(tiles))


class TcodFovTests(unittest.TestCase):
    def test_open_fov_is_deterministic_and_bounded(self) -> None:
        first = compute_fov(_world(), Position(3, 3), 2)
        second = compute_fov(_world(), Position(3, 3), 2)

        self.assertEqual(first, second)
        self.assertIn(Position(3, 3), first)
        self.assertTrue(all(0 <= position.x < 7 and 0 <= position.y < 7 for position in first))
        self.assertEqual(len(first), 25)

    def test_tree_is_visible_but_hides_the_tile_behind_it(self) -> None:
        visible = compute_fov(_world(blocker=Position(4, 3)), Position(3, 3), 5)

        self.assertIn(Position(4, 3), visible)
        self.assertNotIn(Position(5, 3), visible)

    def test_opaque_structures_block_and_shelter_does_not(self) -> None:
        workbench = compute_fov(
            _world(blocker=Position(4, 3), blocker_type=TileType.WORKBENCH),
            Position(3, 3),
            5,
        )
        shelter = compute_fov(
            _world(blocker=Position(4, 3), blocker_type=TileType.SHELTER),
            Position(3, 3),
            5,
        )

        self.assertNotIn(Position(5, 3), workbench)
        self.assertIn(Position(5, 3), shelter)

    def test_radius_zero_and_invalid_inputs(self) -> None:
        self.assertEqual(
            compute_fov(_world(), Position(3, 3), 0),
            frozenset({Position(3, 3)}),
        )
        with self.assertRaises(ValueError):
            compute_fov(_world(), Position(3, 3), -1)
        with self.assertRaises(ValueError):
            compute_fov(_world(), Position(7, 3), 2)


if __name__ == "__main__":
    unittest.main()
