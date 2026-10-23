"""Contract tests for the perception-limited MCP observation."""

from __future__ import annotations

import json
import unittest

from iasim.app.session import GameSession
from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType, WorldMap
from iasim.world.layout import WorldLayout


def _layout(
    spawns: tuple[Position, ...],
    *,
    bush: Position | None = None,
    tree: Position | None = None,
) -> WorldLayout:
    width = 10
    height = 10
    tiles = [TileType.GRASS] * (width * height)
    if bush is not None:
        tiles[bush.y * width + bush.x] = TileType.BUSH
    if tree is not None:
        tiles[tree.y * width + tree.x] = TileType.TREE
    return WorldLayout(
        seed=42,
        world=WorldMap(width=width, height=height, tiles=tuple(tiles)),
        spawn_points=spawns,
    )


class ObservationTests(unittest.TestCase):
    def test_visible_tiles_include_glyph_and_catalog_resources(self) -> None:
        session = GameSession(
            42,
            layout=_layout((Position(2, 2),), bush=Position(3, 2)),
        )
        agent_id = session.join("Nia", session.tokens[0])["agent_id"]
        session.wait(agent_id, 0)
        observation = session.observe(agent_id)
        visible = {
            (entry["x"], entry["y"]): entry for entry in observation["perception"]["visible"]
        }

        bush = visible[(3, 2)]
        self.assertEqual(bush["tile"], "bush")
        self.assertEqual(bush["glyph"], "♠")
        self.assertEqual(bush["resource"], "bush_berries")
        self.assertIn("bush_berries", bush["resources"])
        self.assertEqual(bush["entities"], [])

    def test_hidden_agents_are_absent_and_visible_agents_are_reported(self) -> None:
        session = GameSession(
            42,
            layout=_layout(
                (Position(2, 2), Position(3, 2)),
                tree=Position(4, 3),
            ),
        )
        first = session.join("Nia", session.tokens[0])["agent_id"]
        second = session.join("Kai", session.tokens[1])["agent_id"]
        observation = session.observe(first)

        self.assertEqual(
            [entry["id"] for entry in observation["perception"]["agents"]],
            [second],
        )
        self.assertNotIn("ag_01", json.dumps(observation["perception"]["agents"]))
        self.assertNotIn("world", observation)
        self.assertNotIn("rng_state", observation)
        self.assertNotIn("seed", observation)

    def test_observation_has_required_contract_sections(self) -> None:
        session = GameSession(42, layout=_layout((Position(2, 2),)))
        agent_id = session.join("Nia", session.tokens[0])["agent_id"]
        observation = session.observe(agent_id)

        for key in (
            "schema_version",
            "tick",
            "session",
            "server_time_ms",
            "deadline_ms",
            "time",
            "agent",
            "environment",
            "perception",
            "inventory",
            "available_actions",
        ):
            self.assertIn(key, observation)
        for key in ("visible", "memory_updates", "agents", "messages"):
            self.assertIn(key, observation["perception"])


if __name__ == "__main__":
    unittest.main()
