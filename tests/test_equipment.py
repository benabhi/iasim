"""Tests for equipping and unequipping catalog items."""

from __future__ import annotations

import unittest

from iasim.crafting import load_catalog
from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId, ItemId
from iasim.domain.item_actions import ItemActionOutcome, item_action_resolvers
from iasim.domain.items import (
    EquipSlot,
    Inventory,
    ItemDefinition,
    ItemStack,
)
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.turns import TurnEngine, TurnEvent

CATALOG = load_catalog()


def _definition(item_id: str) -> ItemDefinition:
    return CATALOG.item(item_id).definition


def _inventory(**items: int) -> Inventory:
    inventory = Inventory.for_strength(5)
    for item_id, quantity in items.items():
        inventory = inventory.add(ItemStack(_definition(item_id), quantity))
    return inventory


def _agent(agent_id: str, position: Position, inventory: Inventory) -> Agent:
    return Agent(AgentId(agent_id), position, inventory=inventory)


def _state(agent: Agent) -> SessionState:
    return SessionState(
        seed=1,
        tick=0,
        rng_state=1,
        world=WorldMap(width=6, height=6, tiles=(TileType.GRASS,) * 36),
        agents=(agent,),
    )


def _run(
    state: SessionState,
    kind: ActionKind,
    payload: tuple[tuple[str, object], ...],
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    engine = TurnEngine(state, resolvers=item_action_resolvers(CATALOG))
    engine.submit(Action(AgentId("ag_01"), state.tick, kind, payload))
    result = engine.resolve()
    return engine.state, result.events


def _equip(state: SessionState, item_id: str) -> tuple[SessionState, str]:
    reached, events = _run(state, ActionKind.EQUIP, (("item_id", item_id),))
    return reached, events[0].outcome


def _unequip(state: SessionState, slot: str) -> tuple[SessionState, str]:
    reached, events = _run(state, ActionKind.UNEQUIP, (("slot", slot),))
    return reached, events[0].outcome


def _only_agent(state: SessionState) -> Agent:
    return state.agents[0]


class EquipTests(unittest.TestCase):
    def test_equip_moves_the_item_to_the_hand_slot(self) -> None:
        state = _state(_agent("ag_01", Position(2, 2), _inventory(stone_spear=1)))

        reached, outcome = _equip(state, "stone_spear")

        self.assertEqual(outcome, ItemActionOutcome.EQUIPPED.value)
        agent = _only_agent(reached)
        self.assertIsNone(agent.inventory.stack_for("stone_spear"))
        hand = agent.equipment.item(EquipSlot.HAND)
        self.assertIsNotNone(hand)
        self.assertEqual(hand.item_id, "stone_spear")
        self.assertEqual(agent.weapon_damage, 7)

    def test_equip_clothing_and_backpack_raise_capacity(self) -> None:
        state = _state(
            _agent(
                "ag_01",
                Position(2, 2),
                _inventory(fiber_clothes=1, backpack=1),
            )
        )

        reached, _ = _equip(state, "fiber_clothes")
        reached, _ = _equip(reached, "backpack")

        agent = _only_agent(reached)
        self.assertEqual(agent.equipment.item(EquipSlot.BODY).item_id, "fiber_clothes")
        self.assertEqual(agent.equipment.item(EquipSlot.BACK).item_id, "backpack")
        self.assertEqual(agent.max_slots, 16)
        self.assertEqual(agent.carry_capacity_grams, 30_000)

    def test_equip_requires_the_item_in_the_inventory(self) -> None:
        state = _state(_agent("ag_01", Position(2, 2), _inventory()))

        reached, outcome = _equip(state, "stone_spear")

        self.assertEqual(outcome, ItemActionOutcome.MISSING_ITEM.value)
        self.assertIsNone(_only_agent(reached).equipment.item(EquipSlot.HAND))

    def test_equip_rejects_items_without_a_slot(self) -> None:
        state = _state(_agent("ag_01", Position(2, 2), _inventory(wood=1)))

        _, outcome = _equip(state, "wood")

        self.assertEqual(outcome, ItemActionOutcome.NOT_EQUIPPABLE.value)

    def test_equip_rejects_unknown_catalog_items(self) -> None:
        mystery = ItemDefinition(ItemId("mystery_relic"), 100, True, 10)
        inventory = Inventory.for_strength(5).add(ItemStack(mystery, 1))
        state = _state(_agent("ag_01", Position(2, 2), inventory))

        _, outcome = _equip(state, "mystery_relic")

        self.assertEqual(outcome, ItemActionOutcome.NOT_EQUIPPABLE.value)

    def test_equip_rejects_an_occupied_slot(self) -> None:
        state = _state(_agent("ag_01", Position(2, 2), _inventory(stone_spear=1, stone_axe=1)))

        reached, _ = _equip(state, "stone_spear")
        reached, outcome = _equip(reached, "stone_axe")

        self.assertEqual(outcome, ItemActionOutcome.SLOT_OCCUPIED.value)
        agent = _only_agent(reached)
        self.assertEqual(agent.equipment.item(EquipSlot.HAND).item_id, "stone_spear")
        self.assertIsNotNone(agent.inventory.stack_for("stone_axe"))


class UnequipTests(unittest.TestCase):
    def test_unequip_returns_the_item_to_the_inventory(self) -> None:
        state = _state(_agent("ag_01", Position(2, 2), _inventory(stone_spear=1)))
        armed, _ = _equip(state, "stone_spear")

        reached, outcome = _unequip(armed, "hand")

        self.assertEqual(outcome, ItemActionOutcome.UNEQUIPPED.value)
        agent = _only_agent(reached)
        self.assertIsNotNone(agent.inventory.stack_for("stone_spear"))
        self.assertIsNone(agent.equipment.item(EquipSlot.HAND))
        self.assertEqual(agent.weapon_damage, 0)

    def test_unequip_rejects_an_empty_slot(self) -> None:
        state = _state(_agent("ag_01", Position(2, 2), _inventory()))

        _, outcome = _unequip(state, "hand")

        self.assertEqual(outcome, ItemActionOutcome.EMPTY_SLOT.value)

    def test_unequip_rejects_an_unknown_slot(self) -> None:
        state = _state(_agent("ag_01", Position(2, 2), _inventory(stone_spear=1)))

        _, outcome = _unequip(state, "hat")

        self.assertEqual(outcome, ItemActionOutcome.INVALID_SLOT.value)

    def test_unequip_fails_when_the_inventory_cannot_hold_the_item(self) -> None:
        backpack = CATALOG.item("backpack")
        inventory = Inventory.for_strength(
            5,
            bonus_slots=backpack.bonus_slots,
            bonus_weight_grams=backpack.bonus_weight_grams,
        )
        inventory = inventory.add(ItemStack(backpack.definition, 1))
        inventory = inventory.add_quantity(_definition("wood"), 21)
        agent = _agent("ag_01", Position(2, 2), inventory).equip(backpack)
        self.assertEqual(agent.inventory.total_weight_grams, 21_000)
        state = _state(agent)

        reached, outcome = _unequip(state, "back")

        self.assertEqual(outcome, ItemActionOutcome.INVENTORY_FULL.value)
        self.assertIsNotNone(_only_agent(reached).equipment.item(EquipSlot.BACK))


if __name__ == "__main__":
    unittest.main()
