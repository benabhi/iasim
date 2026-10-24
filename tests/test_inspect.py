"""Tests for perception-limited inspection of agents, corpses, and tiles."""

from __future__ import annotations

import unittest

from iasim.app.session import GameSession
from iasim.crafting import load_catalog
from iasim.domain.agents import AgentAttributes, AgentProfile
from iasim.domain.geometry import Position
from iasim.domain.items import Inventory, ItemStack
from iasim.domain.tiles import TileType, WorldMap
from iasim.world.layout import WorldLayout

CATALOG = load_catalog()


def _layout(points: tuple[Position, ...], *, size: int = 30) -> WorldLayout:
    return WorldLayout(
        seed=1,
        world=WorldMap(width=size, height=size, tiles=(TileType.GRASS,) * (size * size)),
        spawn_points=points,
    )


def _inventory_with_wood() -> Inventory:
    return Inventory.for_strength(5).add(ItemStack(CATALOG.item("wood").definition, 1))


def _joined(points: tuple[Position, ...], session: GameSession) -> tuple[str, str]:
    return (
        session.join("Nia", session.tokens[0])["agent_id"],
        session.join("Kai", session.tokens[1])["agent_id"],
    )


class InspectAgentTests(unittest.TestCase):
    def test_nearby_agent_is_inspected_with_perception_details(self) -> None:
        session = GameSession(1, layout=_layout((Position(2, 2), Position(3, 2))))
        first, second = _joined((Position(2, 2), Position(3, 2)), session)

        result = session.inspect(first, target_id=second)

        self.assertTrue(result["ok"])
        target = result["target"]
        self.assertEqual(target["kind"], "agent")
        self.assertEqual(target["id"], second)
        self.assertEqual(target["name"], "Kai")
        self.assertEqual(target["pos"], [3, 2])
        self.assertEqual(target["relation"], "neutral")
        self.assertIn(target["health_band"], {"healthy", "hurt", "critical"})
        self.assertEqual(result["tick"], 0)

    def test_an_agent_outside_perception_is_not_visible(self) -> None:
        session = GameSession(1, layout=_layout((Position(2, 2), Position(28, 28))))
        first, second = _joined((Position(2, 2), Position(28, 28)), session)

        result = session.inspect(first, target_id=second)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "NOT_VISIBLE")

    def test_the_inspecting_agent_is_not_a_perception_target(self) -> None:
        session = GameSession(1, layout=_layout((Position(2, 2), Position(3, 2))))
        first, _ = _joined((Position(2, 2), Position(3, 2)), session)

        result = session.inspect(first, target_id=first)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "NOT_VISIBLE")


class InspectTileTests(unittest.TestCase):
    def test_a_visible_tile_is_inspected(self) -> None:
        session = GameSession(1, layout=_layout((Position(2, 2), Position(3, 2))))
        first, second = _joined((Position(2, 2), Position(3, 2)), session)

        result = session.inspect(first, x=3, y=2)

        self.assertTrue(result["ok"])
        target = result["target"]
        self.assertEqual(target["kind"], "tile")
        self.assertEqual((target["x"], target["y"]), (3, 2))
        self.assertEqual(target["tile"], "grass")
        self.assertIsNone(target["resource"])
        self.assertEqual(target["entities"], [])
        self.assertEqual(second, "ag_02")

    def test_a_tile_outside_the_world_is_rejected(self) -> None:
        session = GameSession(1, layout=_layout((Position(2, 2), Position(3, 2))))
        first, _ = _joined((Position(2, 2), Position(3, 2)), session)

        result = session.inspect(first, x=99, y=99)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_TARGET")

    def test_a_tile_outside_perception_is_not_visible(self) -> None:
        session = GameSession(1, layout=_layout((Position(2, 2), Position(3, 2))))
        first, _ = _joined((Position(2, 2), Position(3, 2)), session)

        result = session.inspect(first, x=20, y=20)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "NOT_VISIBLE")


class InspectArgumentTests(unittest.TestCase):
    def _session(self) -> tuple[GameSession, str]:
        session = GameSession(1, layout=_layout((Position(2, 2), Position(3, 2))))
        first, _ = _joined((Position(2, 2), Position(3, 2)), session)
        return session, first

    def test_target_and_position_are_mutually_exclusive(self) -> None:
        session, first = self._session()

        result = session.inspect(first, target_id="ag_02", x=3, y=2)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_TARGET")

    def test_one_argument_is_not_enough(self) -> None:
        session, first = self._session()

        result = session.inspect(first, x=3)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_TARGET")

    def test_an_unjoined_agent_cannot_inspect(self) -> None:
        session, _ = self._session()

        result = session.inspect("ag_09", target_id="ag_02")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "NOT_YOUR_TURN")


class InspectCorpseTests(unittest.TestCase):
    def test_a_visible_corpse_shows_cause_and_loot(self) -> None:
        layout = _layout((Position(2, 2), Position(3, 2)))
        session = GameSession(
            1,
            layout=layout,
            profiles=(
                AgentProfile(),
                AgentProfile(
                    attributes=AgentAttributes(health_centi=100),
                    inventory=_inventory_with_wood(),
                ),
            ),
        )
        first, second = _joined((Position(2, 2), Position(3, 2)), session)
        self.assertTrue(session.attack(first, 0, second)["ok"])
        self.assertTrue(session.wait(second, 0)["ok"])
        corpse_id = session.state.corpses[0].corpse_id

        result = session.inspect(first, target_id=corpse_id)

        self.assertTrue(result["ok"])
        target = result["target"]
        self.assertEqual(target["kind"], "corpse")
        self.assertEqual(target["corpse_id"], corpse_id)
        self.assertEqual(target["agent_id"], second)
        self.assertEqual(target["cause"], "attack")
        self.assertTrue(target["lootable"])
        self.assertEqual((target["x"], target["y"]), (3, 2))


if __name__ == "__main__":
    unittest.main()
