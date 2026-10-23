"""Tests for gathering, ground items, and consumable actions."""

from __future__ import annotations

import unittest

from iasim.crafting import load_catalog
from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.item_actions import ItemActionOutcome, item_action_resolvers
from iasim.domain.items import GroundItem, Inventory, ItemStack
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.turns import TurnEngine


def _world() -> WorldMap:
    width = 7
    height = 7
    tiles = [TileType.GRASS] * (width * height)
    tiles[2 * width + 3] = TileType.BUSH
    tiles[3 * width + 3] = TileType.FRESH_WATER
    return WorldMap(width=width, height=height, tiles=tuple(tiles))


def _agent(*item_ids: str, charges: dict[str, int] | None = None) -> Agent:
    catalog = load_catalog()
    inventory = Inventory.for_strength(5)
    charge_map = charges or {}
    for item_id in item_ids:
        inventory = inventory.add(
            ItemStack(
                catalog.item(item_id).definition,
                1,
                charges=charge_map.get(item_id, 0),
            )
        )
    return Agent(AgentId("ag_01"), Position(2, 2), inventory=inventory)


def _state(
    agent: Agent,
    *,
    ground_items: tuple[GroundItem, ...] = (),
    world: WorldMap | None = None,
) -> SessionState:
    return SessionState(
        seed=42,
        tick=0,
        rng_state=42,
        world=_world() if world is None else world,
        agents=(agent,),
        ground_items=ground_items,
    )


def _resolve(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, str]:
    engine = TurnEngine(state, resolvers=item_action_resolvers(load_catalog()))
    engine.submit(action)
    result = engine.resolve()
    return engine.state, result.events[0].outcome


class GatherTests(unittest.TestCase):
    def test_gather_adds_catalog_resource_to_inventory(self) -> None:
        state, outcome = _resolve(
            _state(_agent()),
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.GATHER,
                (("x", 3), ("y", 2)),
            ),
        )

        self.assertEqual(outcome, ItemActionOutcome.GATHERED.value)
        self.assertEqual(state.agents[0].inventory.stack_for("berry").quantity, 2)

    def test_gather_rejects_out_of_range_without_changing_state(self) -> None:
        state, outcome = _resolve(
            _state(_agent()),
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.GATHER,
                (("x", 6), ("y", 2)),
            ),
        )

        self.assertEqual(outcome, ItemActionOutcome.NOT_IN_RANGE.value)
        self.assertTrue(state.agents[0].inventory.is_empty)

    def test_gather_rejects_a_tile_without_resources(self) -> None:
        state, outcome = _resolve(
            _state(_agent()),
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.GATHER,
                (("x", 2), ("y", 3)),
            ),
        )

        self.assertEqual(outcome, ItemActionOutcome.NO_RESOURCE.value)
        self.assertTrue(state.agents[0].inventory.is_empty)

    def test_gather_is_atomic_when_inventory_is_full(self) -> None:
        catalog = load_catalog()
        inventory = Inventory.for_strength(5)
        for item_id in (
            "wood",
            "fiber",
            "stone",
            "coconut",
            "reed",
            "clay",
            "sharp_stone",
            "stone_spear",
            "stone_axe",
            "torch",
        ):
            inventory = inventory.add(ItemStack(catalog.item(item_id).definition, 1))
        agent = Agent(AgentId("ag_01"), Position(2, 2), inventory=inventory)

        state, outcome = _resolve(
            _state(agent),
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.GATHER,
                (("x", 3), ("y", 2)),
            ),
        )

        self.assertEqual(outcome, ItemActionOutcome.INVENTORY_FULL.value)
        self.assertIsNone(state.agents[0].inventory.stack_for("berry"))
        self.assertEqual(len(state.agents[0].inventory.stacks), 10)


class GroundItemTests(unittest.TestCase):
    def test_pickup_moves_a_ground_stack_into_inventory(self) -> None:
        catalog = load_catalog()
        ground = GroundItem(
            Position(2, 3),
            ItemStack(catalog.item("berry").definition, 3),
        )

        state, outcome = _resolve(
            _state(_agent(), ground_items=(ground,)),
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.PICKUP,
                (("x", 2), ("y", 3), ("item_id", None)),
            ),
        )

        self.assertEqual(outcome, ItemActionOutcome.PICKED_UP.value)
        self.assertEqual(state.agents[0].inventory.stack_for("berry").quantity, 3)
        self.assertEqual(state.ground_items, ())

    def test_pickup_rejects_ambiguous_items_when_no_item_id_is_given(self) -> None:
        catalog = load_catalog()
        ground_items = (
            GroundItem(Position(2, 3), ItemStack(catalog.item("berry").definition, 1)),
            GroundItem(Position(2, 3), ItemStack(catalog.item("wood").definition, 1)),
        )

        state, outcome = _resolve(
            _state(_agent(), ground_items=ground_items),
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.PICKUP,
                (("x", 2), ("y", 3)),
            ),
        )

        self.assertEqual(outcome, ItemActionOutcome.AMBIGUOUS_ITEM.value)
        self.assertEqual(state.ground_items, ground_items)
        self.assertTrue(state.agents[0].inventory.is_empty)

    def test_drop_creates_a_ground_stack_and_keeps_the_remainder(self) -> None:
        state, outcome = _resolve(
            _state(_agent("berry", "berry")),
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.DROP,
                (("item_id", "berry"), ("qty", 1)),
            ),
        )

        self.assertEqual(outcome, ItemActionOutcome.DROPPED.value)
        self.assertEqual(state.agents[0].inventory.stack_for("berry").quantity, 1)
        self.assertEqual(len(state.ground_items), 1)
        self.assertEqual(state.ground_items[0].stack.quantity, 1)

    def test_pickup_preserves_waterskin_charges(self) -> None:
        catalog = load_catalog()
        ground = GroundItem(
            Position(2, 3),
            ItemStack(catalog.item("waterskin").definition, 1, charges=2),
        )

        state, outcome = _resolve(
            _state(_agent(), ground_items=(ground,)),
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.PICKUP,
                (("x", 2), ("y", 3), ("item_id", "waterskin")),
            ),
        )

        self.assertEqual(outcome, ItemActionOutcome.PICKED_UP.value)
        self.assertEqual(state.agents[0].inventory.stack_for("waterskin").charges, 2)

    def test_drop_preserves_waterskin_charges(self) -> None:
        state, outcome = _resolve(
            _state(_agent("waterskin", charges={"waterskin": 2})),
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.DROP,
                (("item_id", "waterskin"), ("qty", 1)),
            ),
        )

        self.assertEqual(outcome, ItemActionOutcome.DROPPED.value)
        self.assertEqual(state.ground_items[0].stack.charges, 2)

    def test_drop_rejects_missing_items_without_side_effects(self) -> None:
        state, outcome = _resolve(
            _state(_agent()),
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.DROP,
                (("item_id", "berry"), ("qty", 1)),
            ),
        )

        self.assertEqual(outcome, ItemActionOutcome.MISSING_ITEM.value)
        self.assertEqual(state.ground_items, ())
        self.assertTrue(state.agents[0].inventory.is_empty)


class ConsumableTests(unittest.TestCase):
    def test_eat_consumes_food_and_restores_hunger(self) -> None:
        state, outcome = _resolve(
            _state(_agent("berry")),
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.EAT,
                (("item_id", "berry"),),
            ),
        )

        self.assertEqual(outcome, ItemActionOutcome.ATE.value)
        self.assertIsNone(state.agents[0].inventory.stack_for("berry"))
        self.assertEqual(state.agents[0].attributes.hunger_centi, 0)

    def test_eat_rejects_non_food(self) -> None:
        state, outcome = _resolve(
            _state(_agent("wood")),
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.EAT,
                (("item_id", "wood"),),
            ),
        )

        self.assertEqual(outcome, ItemActionOutcome.NOT_FOOD.value)
        self.assertIsNotNone(state.agents[0].inventory.stack_for("wood"))

    def test_drink_from_adjacent_fresh_water_restores_thirst(self) -> None:
        state, outcome = _resolve(
            _state(_agent()),
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.DRINK,
                (("x", 3), ("y", 3)),
            ),
        )

        self.assertEqual(outcome, ItemActionOutcome.DRANK.value)
        self.assertEqual(state.agents[0].attributes.thirst_centi, 500)

    def test_drink_from_waterskin_consumes_one_charge(self) -> None:
        state, outcome = _resolve(
            _state(_agent("waterskin", charges={"waterskin": 2})),
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.DRINK,
                (("item_id", "waterskin"),),
            ),
        )

        self.assertEqual(outcome, ItemActionOutcome.DRANK.value)
        self.assertEqual(state.agents[0].inventory.stack_for("waterskin").charges, 1)
        self.assertEqual(state.agents[0].attributes.thirst_centi, 500)

    def test_empty_waterskin_is_rejected(self) -> None:
        state, outcome = _resolve(
            _state(_agent("waterskin")),
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.DRINK,
                (("item_id", "waterskin"),),
            ),
        )

        self.assertEqual(outcome, ItemActionOutcome.EMPTY.value)
        self.assertEqual(state.agents[0].attributes.thirst_centi, 1_500)

    def test_fill_waterskin_from_adjacent_fresh_water(self) -> None:
        state, outcome = _resolve(
            _state(_agent("waterskin")),
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.FILL,
                (("item_id", "waterskin"),),
            ),
        )

        self.assertEqual(outcome, ItemActionOutcome.FILLED.value)
        self.assertEqual(state.agents[0].inventory.stack_for("waterskin").charges, 3)

    def test_fill_rejects_a_tile_without_adjacent_fresh_water(self) -> None:
        dry_world = WorldMap(
            width=7,
            height=7,
            tiles=(TileType.GRASS,) * 49,
        )
        state, outcome = _resolve(
            _state(_agent("waterskin"), world=dry_world),
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.FILL,
                (("item_id", "waterskin"),),
            ),
        )

        self.assertEqual(outcome, ItemActionOutcome.NO_WATER.value)
        self.assertEqual(state.agents[0].inventory.stack_for("waterskin").charges, 0)


if __name__ == "__main__":
    unittest.main()
