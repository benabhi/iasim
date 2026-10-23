"""Tests for per-agent memory and stale tracking."""

from __future__ import annotations

import unittest

from iasim.app.session import GameSession
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.memory import AgentMemory, Memory, MemoryEntry
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.world import StructureKind
from iasim.world.layout import WorldLayout


def _entry(
    position: Position,
    *,
    tile: TileType = TileType.BUSH,
    tick: int = 1,
    resources: tuple[str, ...] = ("bush_berries",),
    structure: StructureKind | None = None,
    stale: bool = False,
) -> MemoryEntry:
    return MemoryEntry(
        position=position,
        tile=tile,
        last_seen_tick=tick,
        resources=resources,
        structure=structure,
        stale=stale,
    )


class MemoryTests(unittest.TestCase):
    def test_unseen_tiles_and_agents_become_stale(self) -> None:
        memory = Memory(
            tiles=(_entry(Position(2, 2)),),
            agents=(
                AgentMemory(
                    AgentId("ag_02"),
                    Position(3, 3),
                    last_seen_tick=1,
                ),
            ),
        )

        refreshed = memory.refresh((), ())

        self.assertTrue(refreshed.tiles[0].stale)
        self.assertTrue(refreshed.agents[0].stale)

    def test_visible_entries_refresh_last_seen_and_clear_stale(self) -> None:
        memory = Memory(tiles=(_entry(Position(2, 2), stale=True),))
        refreshed = memory.refresh(
            (_entry(Position(2, 2), tick=4),),
            (),
        )

        self.assertEqual(refreshed.tiles[0].last_seen_tick, 4)
        self.assertFalse(refreshed.tiles[0].stale)
        self.assertEqual(refreshed.tiles[0].resources, ("bush_berries",))

    def test_memory_is_sorted_and_deterministic(self) -> None:
        first = Memory().refresh(
            (
                _entry(Position(3, 2), structure=StructureKind.FIRE),
                _entry(Position(2, 2)),
            ),
            (),
        )
        second = Memory().refresh(
            (
                _entry(Position(2, 2)),
                _entry(Position(3, 2), structure=StructureKind.FIRE),
            ),
            (),
        )

        self.assertEqual(first, second)
        self.assertEqual(
            [entry.position for entry in first.tiles],
            [Position(2, 2), Position(3, 2)],
        )


class MemorySessionTests(unittest.TestCase):
    def test_observation_receives_only_perceived_tiles_and_resources(self) -> None:
        tiles = [TileType.GRASS] * 400
        tiles[2 * 20 + 3] = TileType.BUSH
        session = GameSession(
            42,
            layout=WorldLayout(
                seed=42,
                world=WorldMap(width=20, height=20, tiles=tuple(tiles)),
                spawn_points=(Position(2, 2),),
            ),
        )
        agent_id = session.join("Nia", session.tokens[0])["agent_id"]
        session.wait(agent_id, 0)
        observation = session.observe(agent_id)
        updates = observation["perception"]["memory_updates"]

        self.assertTrue(updates)
        self.assertLess(len(updates), 400)
        bush = next(entry for entry in updates if entry["x"] == 3 and entry["y"] == 2)
        self.assertIn("bush_berries", bush["resources"])
        self.assertFalse(bush["stale"])
        self.assertEqual(observation["perception"]["memory_agents"], [])


if __name__ == "__main__":
    unittest.main()
