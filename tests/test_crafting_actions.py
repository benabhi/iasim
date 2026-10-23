"""Tests for tier-one and workbench-tier-two crafting."""

from __future__ import annotations

import unittest

from iasim.crafting import load_catalog
from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent
from iasim.domain.crafting_actions import CraftingOutcome, crafting_resolvers
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.items import Inventory, ItemStack
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.turns import TurnEngine
from iasim.domain.world import Structure, StructureKind


def _world(*, workbench: bool = False) -> WorldMap:
    tiles = [TileType.GRASS] * 49
    if workbench:
        tiles[2 * 7 + 3] = TileType.WORKBENCH
    return WorldMap(width=7, height=7, tiles=tuple(tiles))


def _agent(*items: str, stone_quantity: int = 1) -> Agent:
    catalog = load_catalog()
    inventory = Inventory.for_strength(5)
    for item_id in items:
        quantity = stone_quantity if item_id == "stone" else 1
        inventory = inventory.add_quantity(catalog.item(item_id).definition, quantity)
    return Agent(AgentId("ag_01"), Position(2, 2), inventory=inventory)


def _state(
    agent: Agent,
    *,
    workbench: bool = False,
) -> SessionState:
    structures = (Structure(StructureKind.WORKBENCH, Position(3, 2)),) if workbench else ()
    return SessionState(
        seed=42,
        tick=0,
        rng_state=42,
        world=_world(workbench=workbench),
        agents=(agent,),
        structures=structures,
    )


def _resolve(
    state: SessionState,
    recipe_id: object,
) -> tuple[SessionState, str]:
    engine = TurnEngine(state, resolvers=crafting_resolvers(load_catalog()))
    engine.submit(
        Action(
            AgentId("ag_01"),
            0,
            ActionKind.CRAFT,
            (("recipe_id", recipe_id),),
        )
    )
    result = engine.resolve()
    return engine.state, result.events[0].outcome


class CraftingTests(unittest.TestCase):
    def test_level_one_recipe_consumes_exact_ingredients(self) -> None:
        state, outcome = _resolve(
            _state(_agent("stone", stone_quantity=2)),
            "sharp_stone",
        )

        self.assertEqual(outcome, CraftingOutcome.CRAFTED.value)
        self.assertIsNone(state.agents[0].inventory.stack_for("stone"))
        self.assertEqual(state.agents[0].inventory.stack_for("sharp_stone").quantity, 1)

    def test_level_two_recipe_requires_an_adjacent_workbench(self) -> None:
        state, outcome = _resolve(
            _state(_agent("wood", "stone", "sharp_stone", "fiber", stone_quantity=2)),
            "stone_axe",
        )

        self.assertEqual(outcome, CraftingOutcome.STATION_REQUIRED.value)
        self.assertIsNotNone(state.agents[0].inventory.stack_for("wood"))

    def test_level_two_recipe_succeeds_next_to_a_workbench(self) -> None:
        state, outcome = _resolve(
            _state(
                _agent("wood", "stone", "sharp_stone", "fiber", stone_quantity=2),
                workbench=True,
            ),
            "stone_axe",
        )

        self.assertEqual(outcome, CraftingOutcome.CRAFTED.value)
        self.assertIsNone(state.agents[0].inventory.stack_for("stone"))
        self.assertEqual(state.agents[0].inventory.stack_for("stone_axe").quantity, 1)

    def test_missing_ingredients_leave_the_inventory_unchanged(self) -> None:
        agent = _agent("stone")
        state, outcome = _resolve(_state(agent), "sharp_stone")

        self.assertEqual(outcome, CraftingOutcome.MISSING_INGREDIENTS.value)
        self.assertEqual(state.agents[0].inventory.stack_for("stone").quantity, 1)
        self.assertIsNone(state.agents[0].inventory.stack_for("sharp_stone"))

    def test_unknown_recipe_is_rejected_without_mutation(self) -> None:
        state, outcome = _resolve(_state(_agent("stone", stone_quantity=2)), "missing")

        self.assertEqual(outcome, CraftingOutcome.UNKNOWN_RECIPE.value)
        self.assertEqual(state.agents[0].inventory.stack_for("stone").quantity, 2)

    def test_output_capacity_failure_is_atomic(self) -> None:
        agent = Agent(
            AgentId("ag_01"),
            Position(2, 2),
            inventory=Inventory.for_strength(5),
        )
        catalog = load_catalog()
        inventory = agent.inventory
        for item_id in (
            "wood",
            "fiber",
            "coconut",
            "reed",
            "clay",
            "stone_spear",
            "stone_axe",
            "torch",
            "bandage",
        ):
            inventory = inventory.add(ItemStack(catalog.item(item_id).definition, 1))
        inventory = inventory.add_quantity(catalog.item("stone").definition, 3)
        agent = Agent(agent.agent_id, agent.position, inventory=inventory)

        state, outcome = _resolve(_state(agent), "sharp_stone")

        self.assertEqual(outcome, CraftingOutcome.INVENTORY_FULL.value)
        self.assertEqual(state.agents[0].inventory.stack_for("stone").quantity, 3)
        self.assertIsNone(state.agents[0].inventory.stack_for("sharp_stone"))

    def test_invalid_recipe_identifier_is_rejected(self) -> None:
        state, outcome = _resolve(_state(_agent()), 123)

        self.assertEqual(outcome, CraftingOutcome.INVALID_TARGET.value)
        self.assertTrue(state.agents[0].inventory.is_empty)


if __name__ == "__main__":
    unittest.main()
