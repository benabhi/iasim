"""Tests for combat bleeding and bandage treatment."""

from __future__ import annotations

import unittest

from iasim.crafting import load_catalog
from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent, AgentAttributes, AgentStatus
from iasim.domain.combat import resolve_attack
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.item_actions import ItemActionOutcome, item_action_resolvers
from iasim.domain.items import Inventory, ItemStack
from iasim.domain.session import SessionState
from iasim.domain.status import Condition, apply_status_tick, status_tags
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.turns import TurnEngine


def _world() -> WorldMap:
    return WorldMap(width=6, height=6, tiles=(TileType.GRASS,) * 36)


def _agent(
    agent_id: str,
    position: Position,
    *,
    bleeding: bool = False,
    inventory: Inventory | None = None,
) -> Agent:
    return Agent(
        AgentId(agent_id),
        position,
        inventory=inventory or Inventory.for_strength(5),
        bleeding=bleeding,
    )


def _state(*, bleeding: bool = False, inventory: Inventory | None = None) -> SessionState:
    return SessionState(
        seed=5,
        tick=0,
        rng_state=5,
        world=_world(),
        agents=(
            _agent("ag_01", Position(2, 2)),
            _agent("ag_02", Position(3, 2), bleeding=bleeding, inventory=inventory),
        ),
    )


def _attack(state: SessionState) -> SessionState:
    return resolve_attack(
        state,
        Action(
            AgentId("ag_01"),
            0,
            ActionKind.ATTACK,
            (("target_id", "ag_02"),),
        ),
    )[0]


class BleedingTests(unittest.TestCase):
    def test_hit_can_cause_bleeding(self) -> None:
        state = _attack(_state())

        self.assertTrue(state.agents[1].bleeding)
        self.assertIn(Condition.BLEEDING, status_tags(state.agents[1]))

    def test_bleeding_deals_deterministic_damage_per_tick(self) -> None:
        state = _state(bleeding=True)

        after = apply_status_tick(state)

        self.assertEqual(after.agents[1].attributes.health_centi, 100 * 100 - 20)
        self.assertTrue(after.agents[1].bleeding)

    def test_bandage_stops_bleeding_and_is_consumed(self) -> None:
        catalog = load_catalog()
        inventory = Inventory.for_strength(5).add(ItemStack(catalog.item("bandage").definition, 1))
        state = _state(bleeding=True, inventory=inventory)
        engine = TurnEngine(state, resolvers=item_action_resolvers(catalog))
        engine.submit(
            Action(
                AgentId("ag_02"),
                0,
                ActionKind.USE_ITEM,
                (("item_id", "bandage"),),
            )
        )
        result = engine.resolve()

        self.assertEqual(result.events[0].outcome, ItemActionOutcome.USED.value)
        self.assertFalse(engine.state.agents[1].bleeding)
        self.assertIsNone(engine.state.agents[1].inventory.stack_for("bandage"))

    def test_bandage_without_bleeding_is_not_consumed(self) -> None:
        catalog = load_catalog()
        inventory = Inventory.for_strength(5).add(ItemStack(catalog.item("bandage").definition, 1))
        state = _state(inventory=inventory)
        engine = TurnEngine(state, resolvers=item_action_resolvers(catalog))
        engine.submit(
            Action(
                AgentId("ag_02"),
                0,
                ActionKind.USE_ITEM,
                (("item_id", "bandage"),),
            )
        )
        result = engine.resolve()

        self.assertEqual(result.events[0].outcome, ItemActionOutcome.NOT_NEEDED.value)
        self.assertIsNotNone(engine.state.agents[1].inventory.stack_for("bandage"))

    def test_dead_agents_do_not_bleed_further(self) -> None:
        state = _state(bleeding=True)
        dead = state.agents[1]
        state = state.__class__(
            seed=state.seed,
            tick=state.tick,
            rng_state=state.rng_state,
            world=state.world,
            agents=(
                state.agents[0],
                Agent(
                    dead.agent_id,
                    dead.position,
                    attributes=AgentAttributes(health_centi=0),
                    status=AgentStatus.DEAD,
                    bleeding=True,
                ),
            ),
        )

        after = apply_status_tick(state)

        self.assertEqual(after.agents[1].attributes.health_centi, 0)
        self.assertTrue(after.agents[1].bleeding)


if __name__ == "__main__":
    unittest.main()
