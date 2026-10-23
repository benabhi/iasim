"""Tests for canonical session-state hashing."""

from __future__ import annotations

import unittest

from iasim.domain.agents import Agent
from iasim.domain.geometry import Position
from iasim.domain.hashing import canonical_state_hash
from iasim.domain.identifiers import AgentId, ItemId
from iasim.domain.items import GroundItem, Inventory, ItemDefinition, ItemStack
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.world import Structure, StructureKind

BERRY = ItemDefinition(ItemId("berry"), 50, True, 99)
WOOD = ItemDefinition(ItemId("wood"), 1000, True, 99)


def _world() -> WorldMap:
    return WorldMap(
        width=4,
        height=3,
        tiles=(
            TileType.SHELTER,
            TileType.GRASS,
            TileType.GRASS,
            TileType.GRASS,
            TileType.FIRE,
            TileType.GRASS,
            TileType.GRASS,
            TileType.GRASS,
            TileType.GRASS,
            TileType.GRASS,
            TileType.GRASS,
            TileType.GRASS,
        ),
    )


def _agents() -> tuple[Agent, ...]:
    return (
        Agent(AgentId("ag_01"), Position(1, 1)),
        Agent(AgentId("ag_02"), Position(2, 1)),
    )


def _structures() -> tuple[Structure, ...]:
    return (
        Structure(StructureKind.SHELTER, Position(0, 0)),
        Structure(StructureKind.FIRE, Position(0, 1)),
    )


def _ground_items() -> tuple[GroundItem, ...]:
    return (
        GroundItem(Position(2, 2), ItemStack(BERRY, 3)),
        GroundItem(Position(3, 2), ItemStack(WOOD, 1)),
    )


def _state(
    *,
    agents: tuple[Agent, ...] | None = None,
    structures: tuple[Structure, ...] | None = None,
    ground_items: tuple[GroundItem, ...] | None = None,
    tick: int = 0,
) -> SessionState:
    return SessionState(
        seed=42,
        tick=tick,
        rng_state=42,
        world=_world(),
        agents=_agents() if agents is None else agents,
        structures=_structures() if structures is None else structures,
        ground_items=_ground_items() if ground_items is None else ground_items,
    )


class CanonicalHashTests(unittest.TestCase):
    def test_same_state_has_same_hash(self) -> None:
        self.assertEqual(canonical_state_hash(_state()), canonical_state_hash(_state()))

    def test_agent_order_does_not_change_hash(self) -> None:
        first, second = _agents()

        self.assertEqual(
            canonical_state_hash(_state(agents=(first, second))),
            canonical_state_hash(_state(agents=(second, first))),
        )

    def test_structure_and_item_order_does_not_change_hash(self) -> None:
        shelter, fire = _structures()
        berry, wood = _ground_items()

        self.assertEqual(
            canonical_state_hash(_state(structures=(shelter, fire), ground_items=(berry, wood))),
            canonical_state_hash(_state(structures=(fire, shelter), ground_items=(wood, berry))),
        )

    def test_tick_and_position_changes_change_hash(self) -> None:
        base = _state()
        _, second = _agents()
        moved = Agent(AgentId("ag_01"), Position(1, 2))

        self.assertNotEqual(canonical_state_hash(base), canonical_state_hash(_state(tick=1)))
        self.assertNotEqual(
            canonical_state_hash(base),
            canonical_state_hash(_state(agents=(moved, second))),
        )

    def test_inventory_change_changes_hash_and_stack_order_does_not(self) -> None:
        items = Inventory(
            stacks=(ItemStack(BERRY, 3), ItemStack(WOOD, 1)),
            max_slots=10,
            max_weight_grams=20_000,
        )
        reversed_items = Inventory(
            stacks=(ItemStack(WOOD, 1), ItemStack(BERRY, 3)),
            max_slots=10,
            max_weight_grams=20_000,
        )
        changed_items = Inventory(
            stacks=(ItemStack(BERRY, 4), ItemStack(WOOD, 1)),
            max_slots=10,
            max_weight_grams=20_000,
        )
        agent = Agent(AgentId("ag_01"), Position(1, 1), inventory=items)
        reversed_agent = Agent(
            AgentId("ag_01"),
            Position(1, 1),
            inventory=reversed_items,
        )
        changed_agent = Agent(
            AgentId("ag_01"),
            Position(1, 1),
            inventory=changed_items,
        )
        other = Agent(AgentId("ag_02"), Position(2, 1))
        base = _state(agents=(agent, other))

        self.assertEqual(
            canonical_state_hash(base),
            canonical_state_hash(_state(agents=(reversed_agent, other))),
        )
        self.assertNotEqual(
            canonical_state_hash(base),
            canonical_state_hash(_state(agents=(changed_agent, other))),
        )


if __name__ == "__main__":
    unittest.main()
