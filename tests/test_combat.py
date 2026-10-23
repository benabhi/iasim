"""Tests for deterministic adjacent melee attacks."""

from __future__ import annotations

import unittest

from iasim.app.session import GameSession
from iasim.crafting import load_catalog
from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent, AgentAttributes, AgentStatus
from iasim.domain.combat import CombatOutcome, combat_resolvers
from iasim.domain.geometry import Position
from iasim.domain.hashing import canonical_state_hash
from iasim.domain.identifiers import AgentId
from iasim.domain.items import Inventory, ItemStack
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.turns import TurnEngine
from iasim.world.layout import WorldLayout


def _world() -> WorldMap:
    return WorldMap(width=6, height=6, tiles=(TileType.GRASS,) * 36)


def _agent(
    agent_id: str,
    position: Position,
    *,
    health_centi: int = 100 * 100,
    weapon: str | None = None,
) -> Agent:
    catalog = load_catalog()
    inventory = Inventory.for_strength(5)
    agent = Agent(
        AgentId(agent_id),
        position,
        attributes=AgentAttributes(health_centi=health_centi),
        inventory=inventory,
    )
    if weapon is not None:
        spec = catalog.item(weapon)
        agent = agent.__class__(
            agent.agent_id,
            agent.position,
            attributes=agent.attributes,
            inventory=inventory.add(ItemStack(spec.definition, 1)),
        ).equip(spec)
    return agent


def _state(
    *,
    attacker: Agent | None = None,
    target: Agent | None = None,
    seed: int = 1,
) -> SessionState:
    return SessionState(
        seed=seed,
        tick=0,
        rng_state=seed,
        world=_world(),
        agents=(
            attacker or _agent("ag_01", Position(2, 2)),
            target or _agent("ag_02", Position(3, 2)),
        ),
    )


def _attack(state: SessionState) -> tuple[SessionState, str]:
    engine = TurnEngine(state, resolvers=combat_resolvers())
    engine.submit(
        Action(
            AgentId("ag_01"),
            0,
            ActionKind.ATTACK,
            (("target_id", "ag_02"),),
        )
    )
    result = engine.resolve()
    return engine.state, result.events[0].outcome


class CombatTests(unittest.TestCase):
    def test_seed_one_hits_with_fist_damage(self) -> None:
        reached, outcome = _attack(_state(seed=1))

        self.assertEqual(outcome, CombatOutcome.HIT.value)
        self.assertEqual(reached.agents[1].attributes.health_centi, 96 * 100)

    def test_equipped_weapon_increases_damage(self) -> None:
        reached, outcome = _attack(
            _state(
                attacker=_agent("ag_01", Position(2, 2), weapon="stone_spear"),
                seed=1,
            )
        )

        self.assertEqual(outcome, CombatOutcome.HIT.value)
        self.assertEqual(reached.agents[1].attributes.health_centi, 91 * 100)

    def test_seed_forty_two_misses_without_damage(self) -> None:
        reached, outcome = _attack(_state(seed=42))

        self.assertEqual(outcome, CombatOutcome.MISSED.value)
        self.assertEqual(reached.agents[1].attributes.health_centi, 100 * 100)
        self.assertEqual(reached.rng_state, 11400714819323198527)

    def test_hit_can_kill_and_marks_the_target_dead(self) -> None:
        reached, outcome = _attack(
            _state(
                target=_agent("ag_02", Position(3, 2), health_centi=100),
                seed=1,
            )
        )

        self.assertEqual(outcome, CombatOutcome.KILLED.value)
        self.assertEqual(reached.agents[1].status, AgentStatus.DEAD)
        self.assertEqual(reached.agents[1].attributes.health_centi, 0)

    def test_out_of_range_and_self_targets_are_rejected_without_rng_use(self) -> None:
        out_of_range = _state(
            target=_agent("ag_02", Position(2, 4)),
        )
        reached, outcome = _attack(out_of_range)
        self.assertEqual(outcome, CombatOutcome.OUT_OF_RANGE.value)
        self.assertEqual(reached.rng_state, out_of_range.rng_state)

        engine = TurnEngine(_state(), resolvers=combat_resolvers())
        engine.submit(
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.ATTACK,
                (("target_id", "ag_01"),),
            )
        )
        result = engine.resolve()
        self.assertEqual(result.events[0].outcome, CombatOutcome.INVALID_TARGET.value)

    def test_game_session_attack_resolves_with_the_primary_action(self) -> None:
        layout = WorldLayout(
            seed=1,
            world=_world(),
            spawn_points=(Position(2, 2), Position(3, 2)),
        )
        session = GameSession(1, layout=layout)
        first = session.join("Nia", session.tokens[0])["agent_id"]
        second = session.join("Kai", session.tokens[1])["agent_id"]

        self.assertTrue(session.attack(first, 0, second)["ok"])
        self.assertTrue(session.wait(second, 0)["ok"])
        observation = session.observe(first)

        self.assertEqual(observation["tick"], 1)
        self.assertEqual(observation["last_action_result"]["outcome"], "hit")
        health = next(
            agent for agent in session.state.agents if agent.agent_id == second
        ).attributes.health_centi
        self.assertLess(health, 100 * 100)
        self.assertGreaterEqual(health, 96 * 100)

    def test_attack_is_reproducible_and_changes_hash(self) -> None:
        first, first_outcome = _attack(_state(seed=1))
        second, second_outcome = _attack(_state(seed=1))

        self.assertEqual(first_outcome, second_outcome)
        self.assertEqual(first.agents[1].attributes, second.agents[1].attributes)
        self.assertEqual(first.rng_state, second.rng_state)
        self.assertNotEqual(
            canonical_state_hash(first),
            canonical_state_hash(_state(seed=1)),
        )


if __name__ == "__main__":
    unittest.main()
