"""Tests for canonical session-state hashing."""

from __future__ import annotations

import json
import unittest

from iasim.app.session import GameSession
from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent
from iasim.domain.alliances import Alliance
from iasim.domain.corpse import Corpse
from iasim.domain.geometry import Position
from iasim.domain.hashing import canonical_state_hash, canonical_state_payload
from iasim.domain.identifiers import AgentId, ItemId
from iasim.domain.items import GroundItem, Inventory, ItemDefinition, ItemStack
from iasim.domain.memory import AgentMemory, Memory, MemoryEntry
from iasim.domain.movement import movement_resolvers
from iasim.domain.resources import ResourceNode
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.trades import TradeOffer
from iasim.domain.turns import TurnEngine
from iasim.domain.weather import WeatherKind, WeatherState
from iasim.domain.world import Structure, StructureKind
from iasim.world.layout import WorldLayout

BERRY = ItemDefinition(ItemId("berry"), 50, True, 99)
WOOD = ItemDefinition(ItemId("wood"), 1000, True, 99)
WATERSKIN = ItemDefinition(ItemId("waterskin"), 500, False, 1)


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
    seed: int = 42,
    rng_state: int = 42,
    tick_minutes: int = 5,
    weather: WeatherState | None = None,
    resource_nodes: tuple[ResourceNode, ...] = (),
    corpses: tuple[Corpse, ...] = (),
    alliances: tuple[Alliance, ...] = (),
    trades: tuple[TradeOffer, ...] = (),
) -> SessionState:
    return SessionState(
        seed=seed,
        tick=tick,
        rng_state=rng_state,
        world=_world(),
        tick_minutes=tick_minutes,
        agents=_agents() if agents is None else agents,
        structures=_structures() if structures is None else structures,
        ground_items=_ground_items() if ground_items is None else ground_items,
        weather=WeatherState() if weather is None else weather,
        resource_nodes=resource_nodes,
        corpses=corpses,
        alliances=alliances,
        trades=trades,
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

    def test_waterskin_charges_change_hash(self) -> None:
        empty = Agent(
            AgentId("ag_01"),
            Position(1, 1),
            inventory=Inventory.for_strength(5).add(ItemStack(WATERSKIN, 1)),
        )
        filled = Agent(
            AgentId("ag_01"),
            Position(1, 1),
            inventory=Inventory.for_strength(5).add(ItemStack(WATERSKIN, 1, charges=2)),
        )

        self.assertNotEqual(
            canonical_state_hash(_state(agents=(empty,))),
            canonical_state_hash(_state(agents=(filled,))),
        )


class MemoryPayloadTests(unittest.TestCase):
    def _agent_with_memory(
        self,
        tiles: tuple[MemoryEntry, ...],
        agents: tuple[AgentMemory, ...],
    ) -> Agent:
        return Agent(
            AgentId("ag_01"),
            Position(1, 1),
            memory=Memory(tiles=tiles, agents=agents),
        )

    def test_memory_tile_and_agent_order_does_not_change_the_hash(self) -> None:
        first_tile = MemoryEntry(Position(1, 1), TileType.GRASS, 2)
        second_tile = MemoryEntry(Position(2, 1), TileType.TREE, 3)
        first_seen = AgentMemory(AgentId("ag_02"), Position(2, 1), 1)
        second_seen = AgentMemory(AgentId("ag_03"), Position(3, 1), 2)
        forward = self._agent_with_memory(
            (first_tile, second_tile),
            (first_seen, second_seen),
        )
        backward = self._agent_with_memory(
            (second_tile, first_tile),
            (second_seen, first_seen),
        )

        self.assertEqual(
            canonical_state_hash(_state(agents=(forward, _agents()[1]))),
            canonical_state_hash(_state(agents=(backward, _agents()[1]))),
        )

    def test_memory_resource_order_does_not_change_the_hash(self) -> None:
        forward = MemoryEntry(
            Position(1, 1),
            TileType.ROCKY_GROUND,
            2,
            resources=("stone", "sharp_stone"),
        )
        backward = MemoryEntry(
            Position(1, 1),
            TileType.ROCKY_GROUND,
            2,
            resources=("sharp_stone", "stone"),
        )

        self.assertEqual(
            canonical_state_hash(_state(agents=(self._agent_with_memory((forward,), ()),))),
            canonical_state_hash(_state(agents=(self._agent_with_memory((backward,), ()),))),
        )

    def test_the_payload_is_json_safe_and_has_no_object_identity(self) -> None:
        text = json.dumps(
            canonical_state_payload(_state()),
            sort_keys=True,
            ensure_ascii=False,
        )

        self.assertNotIn("0x", text)
        self.assertNotIn("object at", text)


class StateFieldCoverageTests(unittest.TestCase):
    def test_each_state_field_changes_the_hash(self) -> None:
        base_hash = canonical_state_hash(_state())
        first_agent = _agents()[0]
        variants = {
            "seed": _state(seed=7),
            "rng_state": _state(rng_state=99),
            "tick_minutes": _state(tick_minutes=10),
            "weather": _state(
                weather=WeatherState(
                    kind=WeatherKind.RAIN,
                    remaining_ticks=5,
                    wind=3,
                )
            ),
            "resource_nodes": _state(
                resource_nodes=(ResourceNode(Position(1, 2), "berries", 2, 3),)
            ),
            "corpses": _state(corpses=(Corpse.from_agent(first_agent, tick=0, cause="test"),)),
            "alliances": _state(
                alliances=(Alliance.propose(AgentId("ag_01"), AgentId("ag_02"), 0),)
            ),
            "trades": _state(
                trades=(
                    TradeOffer.propose(
                        AgentId("ag_01"),
                        AgentId("ag_02"),
                        0,
                        ((ItemId("wood"), 1),),
                        ((ItemId("berry"), 1),),
                    ),
                )
            ),
        }

        for name, state in variants.items():
            with self.subTest(field=name):
                self.assertNotEqual(canonical_state_hash(state), base_hash)


class TurnHashTests(unittest.TestCase):
    def _engine(self) -> TurnEngine:
        return TurnEngine(_state(), resolvers=movement_resolvers())

    def _resolve(self, engine: TurnEngine) -> str:
        tick = engine.tick
        for agent_id in ("ag_01", "ag_02"):
            engine.submit(Action(AgentId(agent_id), tick, ActionKind.WAIT))
        return engine.resolve().state_hash

    def test_every_tick_produces_a_reproducible_hash(self) -> None:
        first_engine = self._engine()
        second_engine = self._engine()

        first_hashes = [self._resolve(first_engine) for _ in range(3)]
        second_hashes = [self._resolve(second_engine) for _ in range(3)]

        self.assertEqual(first_hashes, second_hashes)
        self.assertEqual(len(set(first_hashes)), 3)
        self.assertEqual(first_hashes[-1], canonical_state_hash(first_engine.state))


class SessionHashTests(unittest.TestCase):
    def _session(self) -> tuple[GameSession, str, str]:
        layout = WorldLayout(
            seed=42,
            world=_world(),
            spawn_points=(Position(1, 1), Position(2, 1)),
        )
        session = GameSession(42, layout=layout)
        return (
            session,
            session.join("Nia", session.tokens[0])["agent_id"],
            session.join("Kai", session.tokens[1])["agent_id"],
        )

    def test_session_hashes_follow_the_ticks_and_are_reproducible(self) -> None:
        first_session, first, second = self._session()
        other_session, other_first, other_second = self._session()
        first_hashes = [first_session.state_hash]
        other_hashes = [other_session.state_hash]
        self.assertEqual(
            first_hashes[0],
            canonical_state_hash(first_session.state),
        )

        for tick in range(3):
            first_session.wait(first, tick)
            first_session.wait(second, tick)
            other_session.wait(other_first, tick)
            other_session.wait(other_second, tick)
            first_hashes.append(first_session.state_hash)
            other_hashes.append(other_session.state_hash)

        self.assertEqual(first_hashes, other_hashes)
        self.assertEqual(len(set(first_hashes)), 4)


if __name__ == "__main__":
    unittest.main()
