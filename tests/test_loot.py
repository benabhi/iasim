"""Tests for corpse creation and looting."""

from __future__ import annotations

import unittest
from dataclasses import replace

from iasim.app.session import GameSession
from iasim.crafting import load_catalog
from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent, AgentAttributes, AgentProfile, AgentStatus
from iasim.domain.corpse import Corpse
from iasim.domain.geometry import Position
from iasim.domain.hashing import canonical_state_hash
from iasim.domain.identifiers import AgentId
from iasim.domain.items import EquipSlot, Inventory, ItemStack
from iasim.domain.loot import LootOutcome, loot_resolvers
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.turns import TurnEngine
from iasim.world.layout import WorldLayout


def _world() -> WorldMap:
    return WorldMap(width=6, height=6, tiles=(TileType.GRASS,) * 36)


def _dead_agent(with_loot: bool = True) -> Agent:
    catalog = load_catalog()
    inventory = Inventory.for_strength(5)
    if with_loot:
        inventory = inventory.add(ItemStack(catalog.item("berry").definition, 2))
        inventory = inventory.add(ItemStack(catalog.item("stone_spear").definition, 1))
    agent = Agent(
        AgentId("ag_02"),
        Position(3, 2),
        inventory=inventory,
    )
    if with_loot:
        agent = agent.equip(catalog.item("stone_spear"))
    return replace(
        agent,
        attributes=AgentAttributes(health_centi=0),
        status=AgentStatus.DEAD,
    )


def _state(
    *,
    with_loot: bool = True,
    corpse_position: Position | None = None,
) -> SessionState:
    attacker = Agent(AgentId("ag_01"), Position(2, 2))
    dead = _dead_agent(with_loot)
    corpse = Corpse.from_agent(
        dead,
        tick=4,
        cause="attack",
        killer_id=AgentId("ag_01"),
    )
    if corpse_position is not None and corpse_position != corpse.position:
        corpse = replace(corpse, position=corpse_position)
    return SessionState(
        seed=42,
        tick=4,
        rng_state=42,
        world=_world(),
        agents=(attacker, dead),
        corpses=(corpse,),
    )


def _loot(state: SessionState, corpse_id: str) -> tuple[SessionState, str]:
    engine = TurnEngine(state, resolvers=loot_resolvers())
    engine.submit(
        Action(
            AgentId("ag_01"),
            state.tick,
            ActionKind.LOOT,
            (("corpse_id", corpse_id),),
        )
    )
    result = engine.resolve()
    return engine.state, result.events[0].outcome


class LootTests(unittest.TestCase):
    def test_loot_moves_inventory_and_equipment_atomically(self) -> None:
        state, outcome = _loot(_state(), "corpse_ag_02")

        self.assertEqual(outcome, LootOutcome.LOOTED.value)
        inventory = state.agents[0].inventory
        self.assertEqual(inventory.stack_for("berry").quantity, 2)  # type: ignore[union-attr]
        self.assertEqual(inventory.stack_for("stone_spear").quantity, 1)  # type: ignore[union-attr]
        self.assertEqual(len(state.corpses), 1)
        self.assertFalse(state.corpses[0].has_items)

    def test_empty_corpse_returns_empty_and_remains(self) -> None:
        state, outcome = _loot(_state(with_loot=False), "corpse_ag_02")

        self.assertEqual(outcome, LootOutcome.EMPTY.value)
        self.assertEqual(len(state.corpses), 1)

    def test_looted_corpse_stays_as_an_empty_record(self) -> None:
        state, outcome = _loot(_state(), "corpse_ag_02")
        self.assertEqual(outcome, LootOutcome.LOOTED.value)

        state, second = _loot(state, "corpse_ag_02")

        self.assertEqual(second, LootOutcome.EMPTY.value)
        self.assertEqual(len(state.corpses), 1)
        self.assertFalse(state.corpses[0].has_items)

    def test_out_of_range_corpse_is_rejected_without_changes(self) -> None:
        state, outcome = _loot(
            _state(corpse_position=Position(5, 5)),
            "corpse_ag_02",
        )

        self.assertEqual(outcome, LootOutcome.OUT_OF_RANGE.value)
        self.assertEqual(state.corpses[0].inventory.stacks[0].quantity, 2)
        self.assertTrue(state.agents[0].inventory.is_empty)

    def test_unknown_corpse_is_rejected(self) -> None:
        state, outcome = _loot(_state(), "corpse_missing")

        self.assertEqual(outcome, LootOutcome.INVALID_TARGET.value)
        self.assertEqual(len(state.corpses), 1)

    def test_corpse_equipment_includes_the_weapon(self) -> None:
        corpse = _state().corpses[0]

        self.assertIsNotNone(corpse.equipment.item(EquipSlot.HAND))
        self.assertTrue(corpse.has_items)

    def test_corpse_state_is_part_of_the_canonical_hash(self) -> None:
        state = _state()

        self.assertNotEqual(
            canonical_state_hash(state),
            canonical_state_hash(replace(state, corpses=())),
        )

    def test_environmental_death_creates_a_corpse_with_a_death_record(self) -> None:
        profile = AgentProfile(
            attributes=AgentAttributes(
                health_centi=100,
                hunger_centi=100 * 100,
                thirst_centi=100 * 100,
            )
        )
        session = GameSession(
            42,
            layout=WorldLayout(
                seed=42,
                world=_world(),
                spawn_points=(Position(2, 2),),
            ),
            profiles=(profile,),
        )
        agent_id = session.join("Nia", session.tokens[0])["agent_id"]

        self.assertTrue(session.wait(agent_id, 0)["ok"])
        self.assertTrue(session.wait(agent_id, 1)["ok"])

        self.assertEqual(session.state.agents[0].status, AgentStatus.DEAD)
        self.assertEqual(len(session.state.corpses), 1)
        corpse = session.state.corpses[0]
        self.assertEqual(corpse.death_tick, 1)
        self.assertEqual(corpse.cause, "environment")
        self.assertIsNone(corpse.killer_id)
        self.assertEqual(session.leave(agent_id)["error"]["code"], "AGENT_DEAD")
        self.assertEqual(
            session.join("Nia", session.tokens[0])["error"]["code"],
            "ALREADY_JOINED",
        )

    def test_session_kill_then_loot_integration(self) -> None:
        catalog = load_catalog()
        target_inventory = Inventory.for_strength(5).add(
            ItemStack(catalog.item("berry").definition, 2)
        )
        profiles = (
            AgentProfile(),
            AgentProfile(
                attributes=AgentAttributes(health_centi=100),
                inventory=target_inventory,
            ),
        )
        layout = WorldLayout(
            seed=1,
            world=_world(),
            spawn_points=(Position(2, 2), Position(3, 2)),
        )
        session = GameSession(1, layout=layout, profiles=profiles)
        first = session.join("Nia", session.tokens[0])["agent_id"]
        second = session.join("Kai", session.tokens[1])["agent_id"]

        self.assertTrue(session.attack(first, 0, second)["ok"])
        self.assertTrue(session.wait(second, 0)["ok"])
        self.assertEqual(len(session.state.corpses), 1)
        self.assertEqual(session.state.corpses[0].killer_id, first)
        observation = session.observe(first)
        corpse_tile = next(
            tile
            for tile in observation["perception"]["visible"]
            if tile["x"] == 3 and tile["y"] == 2
        )
        self.assertTrue(any(entity["type"] == "corpse" for entity in corpse_tile["entities"]))

        self.assertTrue(session.loot(first, 1, "corpse_ag_02")["ok"])
        observation = session.observe(first)
        self.assertEqual(observation["last_action_result"]["outcome"], "looted")
        self.assertEqual(session.state.agents[0].inventory.stack_for("berry").quantity, 2)
        self.assertFalse(session.state.corpses[0].has_items)


if __name__ == "__main__":
    unittest.main()
