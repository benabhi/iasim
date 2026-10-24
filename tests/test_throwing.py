"""Tests for deterministic thrown-stone attacks with range and line of sight."""

from __future__ import annotations

import unittest

from iasim.app.session import GameSession
from iasim.crafting import load_catalog
from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent, AgentAttributes, AgentProfile, AgentStatus
from iasim.domain.alliances import BETRAYAL, Alliance
from iasim.domain.combat import MIN_HIT_CHANCE, hit_probability
from iasim.domain.geometry import Position
from iasim.domain.hashing import canonical_state_hash
from iasim.domain.identifiers import AgentId
from iasim.domain.items import Inventory, ItemStack
from iasim.domain.session import SessionState
from iasim.domain.throwing import (
    THROW_RANGE,
    THROWN_STONE_DAMAGE,
    ThrowOutcome,
    throw_resolvers,
)
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.turns import TurnEngine, TurnEvent
from iasim.world.layout import WorldLayout
from iasim.world.tcod_fov import has_line_of_sight

STONE = "stone"


def _world(tiles: tuple[TileType, ...] | None = None) -> WorldMap:
    tiles = tiles or (TileType.GRASS,) * 81
    return WorldMap(width=9, height=9, tiles=tiles)


def _wall_at(position: Position) -> tuple[TileType, ...]:
    """Return a 9x9 grass world with one rock tile at ``position``."""
    tiles = [TileType.GRASS] * 81
    tiles[position.y * 9 + position.x] = TileType.ROCK
    return tuple(tiles)


def _inventory_with(stones: int) -> Inventory:
    catalog = load_catalog()
    spec = catalog.item(STONE)
    inventory = Inventory.for_strength(5)
    if stones > 0:
        inventory = inventory.add(ItemStack(spec.definition, stones))
    return inventory


def _agent(
    agent_id: str,
    position: Position,
    *,
    stones: int = 1,
    health_centi: int = 100 * 100,
) -> Agent:
    return Agent(
        AgentId(agent_id),
        position,
        attributes=AgentAttributes(health_centi=health_centi),
        inventory=_inventory_with(stones),
    )


def _state(
    *,
    attacker: Agent | None = None,
    target: Agent | None = None,
    alliances: tuple[Alliance, ...] = (),
    world: WorldMap | None = None,
    seed: int = 1,
) -> SessionState:
    return SessionState(
        seed=seed,
        tick=0,
        rng_state=seed,
        world=world or _world(),
        agents=(
            attacker or _agent("ag_01", Position(2, 2)),
            target or _agent("ag_02", Position(2, 4)),
        ),
        alliances=alliances,
    )


def _throw(
    state: SessionState,
    *,
    item_id: str = STONE,
    target_id: str = "ag_02",
    agent: str = "ag_01",
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    engine = TurnEngine(state, resolvers=throw_resolvers(has_line_of_sight))
    engine.submit(
        Action(
            AgentId(agent),
            state.tick,
            ActionKind.THROW,
            (("item_id", item_id), ("target_id", target_id)),
        )
    )
    result = engine.resolve()
    return engine.state, result.events


def _stones(agent: Agent) -> int:
    stack = agent.inventory.stack_for(STONE)
    return 0 if stack is None else stack.quantity


class ThrowHitTests(unittest.TestCase):
    def test_throw_hits_with_stone_damage(self) -> None:
        reached, events = _throw(_state(seed=3))

        self.assertEqual(events[0].outcome, ThrowOutcome.HIT.value)
        target = next(agent for agent in reached.agents if agent.agent_id == "ag_02")
        damage = 100 * 100 - target.attributes.health_centi
        self.assertGreaterEqual(damage, (THROWN_STONE_DAMAGE + 5 // 2 - 1) * 100)
        self.assertLessEqual(damage, (THROWN_STONE_DAMAGE + 5 // 2 + 1) * 100)

    def test_throw_consumes_one_stone_on_a_hit(self) -> None:
        reached, _ = _throw(_state(attacker=_agent("ag_01", Position(2, 2), stones=3), seed=3))

        self.assertEqual(_stones(reached.agents[0]), 2)

    def test_throw_consumes_one_stone_on_a_miss(self) -> None:
        reached, events = _throw(_state(seed=42))

        self.assertEqual(events[0].outcome, ThrowOutcome.MISSED.value)
        target = next(agent for agent in reached.agents if agent.agent_id == "ag_02")
        self.assertEqual(target.attributes.health_centi, 100 * 100)
        self.assertEqual(_stones(reached.agents[0]), 0)

    def test_throw_can_kill_and_leaves_a_lootable_corpse(self) -> None:
        reached, events = _throw(
            _state(target=_agent("ag_02", Position(2, 4), health_centi=100), seed=3)
        )

        self.assertEqual(events[0].outcome, ThrowOutcome.KILLED.value)
        target = next(agent for agent in reached.agents if agent.agent_id == "ag_02")
        self.assertEqual(target.status, AgentStatus.DEAD)
        corpse = reached.corpses[0]
        self.assertEqual(corpse.cause, "throw")
        self.assertEqual(corpse.killer_id, "ag_01")
        self.assertEqual(corpse.death_tick, 0)

    def test_throw_is_reproducible(self) -> None:
        first, first_events = _throw(_state(seed=3))
        second, second_events = _throw(_state(seed=3))

        self.assertEqual(first_events, second_events)
        self.assertEqual(canonical_state_hash(first), canonical_state_hash(second))
        self.assertNotEqual(canonical_state_hash(first), canonical_state_hash(_state(seed=3)))


class ThrowRejectionTests(unittest.TestCase):
    def test_targets_beyond_four_tiles_are_rejected(self) -> None:
        far = _state(target=_agent("ag_02", Position(2, 2 + THROW_RANGE + 1)))

        reached, events = _throw(far)

        self.assertEqual(events[0].outcome, ThrowOutcome.OUT_OF_RANGE.value)
        self.assertEqual(_stones(reached.agents[0]), 1)
        self.assertEqual(reached.rng_state, far.rng_state)

    def test_targets_at_the_maximum_range_are_allowed(self) -> None:
        edge = _state(target=_agent("ag_02", Position(2, 2 + THROW_RANGE)), seed=3)

        _, events = _throw(edge)

        self.assertNotEqual(events[0].outcome, ThrowOutcome.OUT_OF_RANGE.value)

    def test_walls_block_the_throw(self) -> None:
        blocked = _state(world=_world(_wall_at(Position(2, 3))))

        reached, events = _throw(blocked)

        self.assertEqual(events[0].outcome, ThrowOutcome.NO_LINE_OF_SIGHT.value)
        self.assertEqual(_stones(reached.agents[0]), 1)

    def test_missing_or_unknown_items_are_rejected(self) -> None:
        reached, events = _throw(_state(), item_id="")
        self.assertEqual(events[0].outcome, ThrowOutcome.INVALID_ITEM.value)

        reached, events = _throw(_state(), item_id="wood")
        self.assertEqual(events[0].outcome, ThrowOutcome.NOT_THROWABLE.value)
        self.assertEqual(_stones(reached.agents[0]), 1)

        reached, events = _throw(_state(attacker=_agent("ag_01", Position(2, 2), stones=0)))
        self.assertEqual(events[0].outcome, ThrowOutcome.NOT_IN_INVENTORY.value)

    def test_invalid_targets_are_rejected(self) -> None:
        _, self_events = _throw(_state(), target_id="ag_01")
        self.assertEqual(self_events[0].outcome, ThrowOutcome.INVALID_TARGET.value)

        _, unknown_events = _throw(_state(), target_id="ag_09")
        self.assertEqual(unknown_events[0].outcome, ThrowOutcome.INVALID_TARGET.value)

        dead = _state(
            target=Agent(
                AgentId("ag_02"),
                Position(2, 4),
                attributes=AgentAttributes(health_centi=0),
                status=AgentStatus.DEAD,
            )
        )
        reached, events = _throw(dead)
        self.assertEqual(events[0].outcome, ThrowOutcome.INVALID_TARGET.value)
        self.assertEqual(_stones(reached.agents[0]), 1)

    def test_throw_rejects_a_missing_target_payload(self) -> None:
        engine = TurnEngine(_state(), resolvers=throw_resolvers(has_line_of_sight))
        engine.submit(Action(AgentId("ag_01"), 0, ActionKind.THROW, (("item_id", STONE),)))
        result = engine.resolve()

        self.assertEqual(result.events[0].outcome, ThrowOutcome.INVALID_TARGET.value)


class ThrowFormulaTests(unittest.TestCase):
    def test_distance_reduces_the_hit_chance(self) -> None:
        attacker = _agent("ag_01", Position(2, 2))
        target = _agent("ag_02", Position(2, 4))

        self.assertAlmostEqual(hit_probability(attacker, target, 1), 0.65)
        self.assertAlmostEqual(hit_probability(attacker, target, 2), 0.55)
        self.assertAlmostEqual(hit_probability(attacker, target, THROW_RANGE), 0.35)
        self.assertGreaterEqual(
            hit_probability(attacker, _agent("ag_02", Position(2, 4)), 40),
            MIN_HIT_CHANCE,
        )

    def test_throwing_at_an_ally_is_allowed_and_annotated_as_betrayal(self) -> None:
        alliances = (Alliance.propose(AgentId("ag_01"), AgentId("ag_02"), 0).accepted(0),)

        reached, events = _throw(_state(alliances=alliances, seed=3))

        self.assertEqual(events[0].outcome, ThrowOutcome.HIT.value)
        self.assertEqual(events[1].outcome, BETRAYAL)
        self.assertEqual(len(reached.alliances), 1)


class ThrowSessionTests(unittest.TestCase):
    def _session(self) -> tuple[GameSession, str, str]:
        session = GameSession(
            1,
            layout=WorldLayout(
                seed=1,
                world=_world(),
                spawn_points=(Position(2, 2), Position(2, 4)),
            ),
        )
        return (
            session,
            session.join("Nia", session.tokens[0])["agent_id"],
            session.join("Kai", session.tokens[1])["agent_id"],
        )

    def test_session_throw_requires_a_stone_in_the_inventory(self) -> None:
        session, thrower, target = self._session()

        self.assertTrue(session.throw(thrower, 0, STONE, target)["ok"])
        self.assertTrue(session.wait(target, 0)["ok"])
        observation = session.observe(thrower)

        self.assertEqual(observation["tick"], 1)
        self.assertEqual(observation["last_action_result"]["outcome"], "not_in_inventory")
        self.assertEqual(observation["last_action_result"]["status"], "rejected")


class ThrowSessionIntegrationTests(unittest.TestCase):
    def _session_with_stone(self) -> tuple[GameSession, str, str]:
        session = GameSession(
            3,
            layout=WorldLayout(
                seed=3,
                world=_world(),
                spawn_points=(Position(2, 2), Position(2, 4)),
            ),
            profiles=(
                AgentProfile(inventory=_inventory_with(1)),
                AgentProfile(),
            ),
        )
        thrower = session.join("Nia", session.tokens[0])["agent_id"]
        target = session.join("Kai", session.tokens[1])["agent_id"]
        return session, thrower, target

    def test_session_throw_consumes_the_stone_and_reports_the_outcome(self) -> None:
        session, thrower, target = self._session_with_stone()

        self.assertTrue(session.throw(thrower, 0, STONE, target)["ok"])
        self.assertTrue(session.wait(target, 0)["ok"])
        observation = session.observe(thrower)

        self.assertEqual(observation["tick"], 1)
        self.assertEqual(observation["last_action_result"]["outcome"], "hit")
        thrower_agent = next(agent for agent in session.state.agents if agent.agent_id == thrower)
        self.assertEqual(_stones(thrower_agent), 0)

    def test_available_actions_lists_throw(self) -> None:
        session, thrower, _ = self._session_with_stone()

        observation = session.observe(thrower)

        self.assertIn(
            {"action": "throw", "available": True},
            observation["available_actions"],
        )


if __name__ == "__main__":
    unittest.main()
