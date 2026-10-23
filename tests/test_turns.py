"""Tests for the deterministic turn pipeline."""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent, AgentAttributes, AgentStatus
from iasim.domain.clock import SimulationClock
from iasim.domain.geometry import Position
from iasim.domain.hashing import canonical_state_hash
from iasim.domain.identifiers import AgentId
from iasim.domain.rng import roll_d6
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.turns import (
    ActionRejectedError,
    ActionResolver,
    TurnEngine,
    TurnEvent,
    TurnResult,
    TurnStateError,
    initiative,
)


def _world() -> WorldMap:
    tiles = [TileType.GRASS] * 9
    tiles[0] = TileType.SHELTER
    return WorldMap(width=3, height=3, tiles=tuple(tiles))


def _agent(
    agent_id: str,
    x: int = 1,
    y: int = 1,
    *,
    status: AgentStatus = AgentStatus.ACTIVE,
    health_centi: int = 10_000,
    dexterity: int = 5,
) -> Agent:
    return Agent(
        AgentId(agent_id),
        Position(x, y),
        attributes=AgentAttributes(health_centi=health_centi, dexterity=dexterity),
        status=status,
    )


def _state(
    agents: tuple[Agent, ...],
    *,
    tick: int = 0,
    tick_minutes: int = 5,
) -> SessionState:
    return SessionState(
        seed=42,
        tick=tick,
        rng_state=42,
        world=_world(),
        tick_minutes=tick_minutes,
        agents=agents,
    )


def _recorder(log: list[tuple[str, str]]) -> dict[ActionKind, ActionResolver]:
    def resolve(
        state: SessionState,
        action: Action,
    ) -> tuple[SessionState, tuple[TurnEvent, ...]]:
        log.append((action.agent_id, action.kind.value))
        return state, (TurnEvent(action.tick, action.agent_id, action.kind, "ok"),)

    return {kind: resolve for kind in ActionKind}


class InitiativeTests(unittest.TestCase):
    def test_initiative_matches_srs_formula(self) -> None:
        agent = _agent("ag_01", dexterity=7)
        expected = 7 + roll_d6(42, 5, "ag_01")

        self.assertEqual(initiative(agent, 42, 5), expected)
        self.assertEqual(initiative(agent, 42, 5, weapon_speed=3), expected + 3)


class TurnEngineTests(unittest.TestCase):
    def test_higher_initiative_resolves_first(self) -> None:
        agents = (_agent("ag_01"), _agent("ag_02", x=2, y=1))
        actions = (
            Action(AgentId("ag_01"), 0, ActionKind.MOVE),
            Action(AgentId("ag_02"), 0, ActionKind.WAIT),
        )
        log: list[tuple[str, str]] = []
        engine = TurnEngine(_state(agents), resolvers=_recorder(log))

        def fake_initiative(
            agent: Agent,
            seed: int,
            tick: int,
            weapon_speed: int = 0,
        ) -> int:
            return 20 if agent.agent_id == "ag_01" else 5

        with patch("iasim.domain.turns.initiative", side_effect=fake_initiative):
            for action in actions:
                engine.submit(action)
            engine.resolve()

        self.assertEqual(log, [("ag_01", "move"), ("ag_02", "wait")])

    def test_same_initiative_uses_category_then_agent_id(self) -> None:
        agents = (
            _agent("ag_01", x=1, y=1),
            _agent("ag_02", x=2, y=1),
            _agent("ag_03", x=1, y=2),
            _agent("ag_04", x=2, y=2),
        )
        actions = (
            Action(AgentId("ag_01"), 0, ActionKind.ATTACK),
            Action(AgentId("ag_02"), 0, ActionKind.MOVE),
            Action(AgentId("ag_03"), 0, ActionKind.CRAFT),
            Action(AgentId("ag_04"), 0, ActionKind.MOVE),
        )
        expected = [
            ("ag_02", "move"),
            ("ag_04", "move"),
            ("ag_03", "craft"),
            ("ag_01", "attack"),
        ]

        def run(order: tuple[Action, ...]) -> tuple[list[tuple[str, str]], TurnResult]:
            log: list[tuple[str, str]] = []
            engine = TurnEngine(_state(agents), resolvers=_recorder(log))
            with patch("iasim.domain.turns.initiative", return_value=10):
                for action in order:
                    engine.submit(action)
                result = engine.resolve()
            return log, result

        first_log, first_result = run(actions)
        second_log, second_result = run(tuple(reversed(actions)))

        self.assertEqual(first_log, expected)
        self.assertEqual(second_log, expected)
        self.assertEqual(first_result.resolved_actions, second_result.resolved_actions)
        self.assertEqual(first_result.state_hash, second_result.state_hash)

    def test_one_primary_action_per_agent(self) -> None:
        engine = TurnEngine(_state((_agent("ag_01"),)), resolvers=_recorder([]))
        engine.submit(Action(AgentId("ag_01"), 0, ActionKind.WAIT))

        with self.assertRaises(ActionRejectedError):
            engine.submit(Action(AgentId("ag_01"), 0, ActionKind.MOVE))

    def test_remove_agent_cancels_its_action_and_preserves_others(self) -> None:
        agents = (_agent("ag_01"), _agent("ag_02", x=2, y=1))
        engine = TurnEngine(_state(agents), resolvers=_recorder([]))
        engine.submit(Action(AgentId("ag_01"), 0, ActionKind.MOVE))
        engine.submit(Action(AgentId("ag_02"), 0, ActionKind.WAIT))

        engine.remove_agent(AgentId("ag_01"))

        self.assertEqual(engine.state.agents, (_agent("ag_02", x=2, y=1),))
        self.assertEqual(engine.pending_agents, frozenset({AgentId("ag_02")}))
        result = engine.resolve()
        self.assertEqual(
            [action.agent_id for action in result.resolved_actions],
            ["ag_02"],
        )

    def test_replace_state_preserves_pending_actions_and_rejects_tick_changes(self) -> None:
        engine = TurnEngine(_state((_agent("ag_01"),)), resolvers=_recorder([]))
        engine.submit(Action(AgentId("ag_01"), 0, ActionKind.WAIT))
        replacement = replace(engine.state, tick_minutes=10)

        engine.replace_state(replacement)

        self.assertEqual(engine.state.tick_minutes, 10)
        self.assertEqual(engine.pending_agents, frozenset({AgentId("ag_01")}))
        with self.assertRaises(TurnStateError):
            engine.replace_state(replace(engine.state, tick=1))

    def test_invalid_agents_and_stale_ticks_are_rejected(self) -> None:
        cases = (
            (_agent("ag_01"), Action(AgentId("ag_99"), 0, ActionKind.WAIT)),
            (
                _agent("ag_01", status=AgentStatus.ABSENT),
                Action(AgentId("ag_01"), 0, ActionKind.WAIT),
            ),
            (
                _agent("ag_01", status=AgentStatus.SLEEPING),
                Action(AgentId("ag_01"), 0, ActionKind.WAIT),
            ),
            (
                _agent("ag_01", status=AgentStatus.DEAD, health_centi=0),
                Action(AgentId("ag_01"), 0, ActionKind.WAIT),
            ),
        )
        for agent, action in cases:
            with self.subTest(agent=agent.agent_id, status=agent.status):
                engine = TurnEngine(_state((agent,)), resolvers=_recorder([]))
                with self.assertRaises(ActionRejectedError):
                    engine.submit(action)

        engine = TurnEngine(_state((_agent("ag_01"),)), resolvers=_recorder([]))
        with self.assertRaises(ActionRejectedError):
            engine.submit(Action(AgentId("ag_01"), 1, ActionKind.WAIT))

    def test_missing_resolver_is_rejected_before_advancing(self) -> None:
        engine = TurnEngine(_state((_agent("ag_01"),)))
        engine.submit(Action(AgentId("ag_01"), 0, ActionKind.WAIT))

        with self.assertRaises(TurnStateError):
            engine.resolve()

        self.assertEqual(engine.tick, 0)
        self.assertEqual(engine.state.tick, 0)

    def test_resolver_state_changes_and_tick_advance(self) -> None:
        def move(
            state: SessionState,
            action: Action,
        ) -> tuple[SessionState, tuple[TurnEvent, ...]]:
            moved = tuple(
                replace(agent, position=Position(agent.position.x + 1, agent.position.y))
                if agent.agent_id == action.agent_id
                else agent
                for agent in state.agents
            )
            return replace(state, agents=moved), ()

        engine = TurnEngine(
            _state((_agent("ag_01"),)),
            resolvers={ActionKind.MOVE: move},
        )
        engine.submit(Action(AgentId("ag_01"), 0, ActionKind.MOVE))

        result = engine.resolve()

        self.assertEqual(engine.state.agents[0].position, Position(2, 1))
        self.assertEqual(result.tick, 0)
        self.assertEqual(engine.tick, 1)
        self.assertEqual(engine.clock.tick, 1)
        self.assertEqual(result.state_hash, canonical_state_hash(engine.state))

    def test_tick_effect_runs_after_actions(self) -> None:
        def effect(
            state: SessionState,
            resolved: tuple,
        ) -> SessionState:
            agents = tuple(
                replace(
                    agent,
                    attributes=replace(
                        agent.attributes,
                        hunger_centi=agent.attributes.hunger_centi + 100,
                    ),
                )
                for agent in state.agents
            )
            return replace(state, agents=agents)

        engine = TurnEngine(
            _state((_agent("ag_01"),)),
            tick_effect=effect,
        )

        result = engine.resolve()

        self.assertEqual(engine.state.agents[0].attributes.hunger_centi, 1_600)
        self.assertEqual(result.state_hash, canonical_state_hash(engine.state))

    def test_tick_effect_cannot_change_tick(self) -> None:
        def effect(
            state: SessionState,
            resolved: tuple,
        ) -> SessionState:
            return replace(state, tick=state.tick + 1)

        engine = TurnEngine(
            _state((_agent("ag_01"),)),
            tick_effect=effect,
        )

        with self.assertRaises(TurnStateError):
            engine.resolve()

        self.assertEqual(engine.tick, 0)

    def test_empty_tick_advances_and_changes_hash(self) -> None:
        engine = TurnEngine(_state((_agent("ag_01"),)))
        before = canonical_state_hash(engine.state)

        result = engine.resolve()

        self.assertEqual(result.tick, 0)
        self.assertEqual(engine.tick, 1)
        self.assertNotEqual(result.state_hash, before)
        self.assertEqual(result.state_hash, canonical_state_hash(engine.state))

    def test_dying_agent_action_is_cancelled(self) -> None:
        agents = (_agent("ag_01"), _agent("ag_02", x=2, y=1))
        calls: list[str] = []

        def kill_second(
            state: SessionState,
            action: Action,
        ) -> tuple[SessionState, tuple[TurnEvent, ...]]:
            updated = tuple(
                replace(
                    agent,
                    attributes=replace(agent.attributes, health_centi=0),
                    status=AgentStatus.DEAD,
                )
                if agent.agent_id == "ag_02"
                else agent
                for agent in state.agents
            )
            return (
                replace(state, agents=updated),
                (TurnEvent(action.tick, action.agent_id, action.kind, "killed"),),
            )

        def record_second(
            state: SessionState,
            action: Action,
        ) -> tuple[SessionState, tuple[TurnEvent, ...]]:
            calls.append(action.agent_id)
            return state, ()

        engine = TurnEngine(
            _state(agents),
            resolvers={ActionKind.ATTACK: kill_second, ActionKind.MOVE: record_second},
        )
        engine.submit(Action(AgentId("ag_01"), 0, ActionKind.ATTACK))
        engine.submit(Action(AgentId("ag_02"), 0, ActionKind.MOVE))

        def fake_initiative(
            agent: Agent,
            seed: int,
            tick: int,
            weapon_speed: int = 0,
        ) -> int:
            return 20 if agent.agent_id == "ag_01" else 10

        with patch("iasim.domain.turns.initiative", side_effect=fake_initiative):
            result = engine.resolve()

        self.assertEqual(calls, [])
        self.assertEqual(
            [action.agent_id for action in result.resolved_actions],
            ["ag_01"],
        )
        self.assertTrue(any(event.outcome == "cancelled" for event in result.events))
        self.assertEqual(engine.state.agents[1].status, AgentStatus.DEAD)

    def test_resolver_cannot_change_tick(self) -> None:
        def bad_resolver(
            state: SessionState,
            action: Action,
        ) -> tuple[SessionState, tuple[TurnEvent, ...]]:
            return replace(state, tick=state.tick + 1), ()

        engine = TurnEngine(
            _state((_agent("ag_01"),)),
            resolvers={ActionKind.WAIT: bad_resolver},
        )
        engine.submit(Action(AgentId("ag_01"), 0, ActionKind.WAIT))

        with self.assertRaises(TurnStateError):
            engine.resolve()

        self.assertEqual(engine.tick, 0)

    def test_clock_must_match_state(self) -> None:
        state = _state((_agent("ag_01"),))

        with self.assertRaises(ValueError):
            TurnEngine(state, clock=SimulationClock(10))

        clock = SimulationClock(5)
        clock.advance(1)
        with self.assertRaises(ValueError):
            TurnEngine(state, clock=clock)

    def test_next_tick_actions_are_accepted(self) -> None:
        engine = TurnEngine(_state((_agent("ag_01"),)), resolvers=_recorder([]))
        engine.resolve()
        engine.submit(Action(AgentId("ag_01"), 1, ActionKind.WAIT))

        result = engine.resolve()

        self.assertEqual(result.tick, 1)


class ActionValidationTests(unittest.TestCase):
    def test_action_rejects_invalid_fields(self) -> None:
        with self.assertRaises(ValueError):
            Action(AgentId("bad"), 0, ActionKind.WAIT)
        with self.assertRaises(ValueError):
            Action(AgentId("ag_01"), -1, ActionKind.WAIT)
        with self.assertRaises(ValueError):
            Action(AgentId("ag_01"), 0, "wait")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.MOVE,
                (("x", 1), ("x", 2)),
            )
        with self.assertRaises(ValueError):
            Action(AgentId("ag_01"), 0, ActionKind.WAIT, (), "")

    def test_payload_can_be_read_as_a_dictionary(self) -> None:
        action = Action(
            AgentId("ag_01"),
            0,
            ActionKind.MOVE,
            (("x", 1), ("y", 2)),
            "request-1",
        )

        self.assertEqual(action.payload_dict(), {"x": 1, "y": 2})


if __name__ == "__main__":
    unittest.main()
