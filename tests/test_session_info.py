"""Tests for the informational MCP-backed session queries."""

from __future__ import annotations

import json
import unittest

from iasim.app.session import GameSession
from iasim.crafting import load_catalog
from iasim.domain.agents import AgentProfile
from iasim.domain.geometry import Position
from iasim.domain.items import Inventory, ItemStack
from iasim.domain.tiles import TileType, WorldMap
from iasim.world.layout import WorldLayout

CATALOG = load_catalog()


def _layout(points: tuple[Position, ...] = (Position(2, 2), Position(3, 2))) -> WorldLayout:
    return WorldLayout(
        seed=1,
        world=WorldMap(width=8, height=8, tiles=(TileType.GRASS,) * 64),
        spawn_points=points,
    )


def _session() -> tuple[GameSession, str, str]:
    session = GameSession(1, layout=_layout())
    return (
        session,
        session.join("Nia", session.tokens[0])["agent_id"],
        session.join("Kai", session.tokens[1])["agent_id"],
    )


class RecipesTests(unittest.TestCase):
    def test_recipes_list_every_catalog_recipe_in_order(self) -> None:
        session, first, _ = _session()

        result = session.recipes()

        self.assertTrue(result["ok"])
        recipes = result["recipes"]
        self.assertEqual(len(recipes), len(CATALOG.recipes))
        ids = [recipe["recipe_id"] for recipe in recipes]
        self.assertEqual(ids, sorted(ids))
        for recipe in recipes:
            self.assertEqual(
                set(recipe),
                {"recipe_id", "level", "station", "ingredients", "output", "output_quantity"},
            )
            self.assertTrue(recipe["ingredients"])
            if recipe["level"] == 1:
                self.assertIsNone(recipe["station"])
            else:
                self.assertEqual(recipe["station"], "workbench")
        self.assertEqual(first, "ag_01")
        self.assertEqual(session.tick, 0)


class InventoryTests(unittest.TestCase):
    def _session_with(self, **items: int) -> tuple[GameSession, str, str]:
        inventory = Inventory.for_strength(5)
        for item_id, quantity in items.items():
            inventory = inventory.add(ItemStack(CATALOG.item(item_id).definition, quantity))
        session = GameSession(
            1,
            layout=_layout(),
            profiles=(AgentProfile(inventory=inventory), AgentProfile()),
        )
        return (
            session,
            session.join("Nia", session.tokens[0])["agent_id"],
            session.join("Kai", session.tokens[1])["agent_id"],
        )

    def test_inventory_matches_the_observation_payload(self) -> None:
        session, first, _ = self._session_with(wood=2)

        result = session.inventory_for(first)
        observation = session.observe(first)

        self.assertTrue(result["ok"])
        self.assertEqual(result["inventory"], observation["inventory"])
        self.assertEqual(result["equipment"], observation["agent"]["equipment"])
        self.assertEqual(result["inventory"]["items"][0]["item_id"], "wood")
        self.assertEqual(result["inventory"]["items"][0]["qty"], 2)
        self.assertAlmostEqual(result["carry_kg"], 2.0)
        self.assertAlmostEqual(result["carry_capacity_kg"], 20.0)

    def test_equipment_is_reported_after_equipping(self) -> None:
        session, first, _ = self._session_with(stone_spear=1)
        self.assertTrue(session.equip(first, 0, "stone_spear")["ok"])
        self.assertTrue(session.wait("ag_02", 0)["ok"])

        result = session.inventory_for("ag_01")

        self.assertEqual(result["equipment"], {"hand": "stone_spear"})
        self.assertEqual(result["inventory"]["items"], [])

    def test_an_unjoined_agent_has_no_inventory_or_info_query(self) -> None:
        session, _, _ = _session()

        for result in (session.inventory_for("ag_09"), session.info("ag_09")):
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], "NOT_YOUR_TURN")
        self.assertTrue(session.recipes()["ok"])


class SessionInfoTests(unittest.TestCase):
    def test_info_reports_time_phase_and_roster(self) -> None:
        session, first, second = _session()

        result = session.info(first)

        self.assertTrue(result["ok"])
        self.assertEqual(result["tick"], 0)
        self.assertEqual(result["time"]["day"], 1)
        self.assertEqual(result["time"]["hour"], 6)
        self.assertEqual(result["session"]["phase"], "running")
        self.assertEqual(result["session"]["joined_agents"], 2)
        self.assertEqual(result["session"]["alive_agents"], 2)
        self.assertEqual(result["tick_minutes"], 5)
        self.assertEqual(
            [agent["id"] for agent in result["agents"]],
            [first, second],
        )
        self.assertTrue(all(agent["alive"] for agent in result["agents"]))

    def test_info_never_exposes_the_seed_or_the_rng(self) -> None:
        session, first, _ = _session()

        payload = json.dumps(session.info(first))

        self.assertNotIn("seed", payload)
        self.assertNotIn("rng_state", payload)
        self.assertNotIn("rng", payload)


if __name__ == "__main__":
    unittest.main()
