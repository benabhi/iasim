"""Tests for rest, sleep, energy recovery, and interruption."""

from __future__ import annotations

import unittest
from dataclasses import replace

from iasim.app.session import GameSession, SessionPhase
from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent, AgentAttributes, AgentProfile, AgentStatus
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.session import SessionState
from iasim.domain.sleep import (
    SleepOutcome,
    apply_sleep_tick,
    rest_sleep_resolvers,
)
from iasim.domain.status import apply_status_tick
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.turns import TurnEngine
from iasim.world.layout import WorldLayout


def _agent(
    *,
    energy_centi: int = 5_000,
    health_centi: int = 10_000,
    hunger_centi: int = 1_500,
) -> Agent:
    return Agent(
        AgentId("ag_01"),
        Position(2, 2),
        attributes=AgentAttributes(
            energy_centi=energy_centi,
            health_centi=health_centi,
            hunger_centi=hunger_centi,
        ),
    )


def _state(agent: Agent) -> SessionState:
    return SessionState(
        seed=42,
        tick=0,
        rng_state=42,
        world=WorldMap(width=5, height=5, tiles=(TileType.GRASS,) * 25),
        agents=(agent,),
    )


def _resolve(
    state: SessionState, kind: ActionKind, *, until: object = None
) -> tuple[SessionState, str]:
    engine = TurnEngine(state, resolvers=rest_sleep_resolvers())
    payload = () if kind is ActionKind.REST else (("until", until),)
    engine.submit(Action(AgentId("ag_01"), state.tick, kind, payload))
    result = engine.resolve()
    return engine.state, result.events[0].outcome


class RestSleepActionTests(unittest.TestCase):
    def test_rest_recovers_energy(self) -> None:
        state, outcome = _resolve(_state(_agent(energy_centi=5_000)), ActionKind.REST)

        self.assertEqual(outcome, SleepOutcome.RESTED.value)
        self.assertEqual(state.agents[0].attributes.energy_centi, 5_300)
        self.assertEqual(state.agents[0].status, AgentStatus.ACTIVE)

    def test_sleep_sets_status_and_target_for_hours(self) -> None:
        state, outcome = _resolve(
            _state(_agent(energy_centi=5_000)),
            ActionKind.SLEEP,
            until="hours:1",
        )

        self.assertEqual(outcome, SleepOutcome.SLEEPING.value)
        self.assertEqual(state.agents[0].status, AgentStatus.SLEEPING)
        self.assertEqual(state.agents[0].sleep_until_tick, 12)

    def test_energy_full_wakes_after_reaching_the_target(self) -> None:
        state, outcome = _resolve(
            _state(_agent(energy_centi=9_500)),
            ActionKind.SLEEP,
            until="energy_full",
        )
        self.assertEqual(outcome, SleepOutcome.SLEEPING.value)

        after_tick = apply_sleep_tick(state)
        self.assertEqual(after_tick.agents[0].status, AgentStatus.ACTIVE)
        self.assertIsNone(after_tick.agents[0].sleep_until_tick)
        self.assertEqual(
            after_tick.agents[0].attributes.energy_centi,
            10_000,
        )

    def test_invalid_until_is_rejected(self) -> None:
        state, outcome = _resolve(
            _state(_agent()),
            ActionKind.SLEEP,
            until="noon",
        )

        self.assertEqual(outcome, SleepOutcome.INVALID_UNTIL.value)
        self.assertEqual(state.agents[0].status, AgentStatus.ACTIVE)

    def test_damage_wakes_a_sleeping_agent(self) -> None:
        sleeping = replace(
            _agent(health_centi=1_000, hunger_centi=10_000),
            status=AgentStatus.SLEEPING,
            sleep_until_tick=100,
        )
        state = _state(sleeping)

        advanced = apply_status_tick(state)

        self.assertEqual(advanced.agents[0].status, AgentStatus.ACTIVE)
        self.assertIsNone(advanced.agents[0].sleep_until_tick)
        self.assertLess(advanced.agents[0].attributes.health_centi, 1_000)


class RestSleepSessionTests(unittest.TestCase):
    def _session(self, profile: AgentProfile) -> GameSession:
        return GameSession(
            42,
            layout=WorldLayout(
                seed=42,
                world=WorldMap(width=5, height=5, tiles=(TileType.GRASS,) * 25),
                spawn_points=(Position(2, 2),),
            ),
            profiles=(profile,),
        )

    def test_rest_is_observable_and_sleeping_is_reported(self) -> None:
        session = self._session(
            AgentProfile(
                attributes=AgentAttributes(energy_centi=5_000),
            )
        )
        agent_id = session.join("Nia", session.tokens[0])["agent_id"]

        rested = session.rest(agent_id, 0)
        rest_observation = session.observe(agent_id)
        slept = session.sleep(agent_id, 1, "hours:1")
        sleep_observation = session.observe(agent_id)

        self.assertTrue(rested["ok"])
        self.assertEqual(rest_observation["last_action_result"]["action"], "rest")
        self.assertTrue(slept["ok"])
        self.assertEqual(sleep_observation["last_action_result"]["action"], "sleep")
        self.assertTrue(sleep_observation["agent"]["sleeping"])
        self.assertEqual(session.phase, SessionPhase.WAITING)


if __name__ == "__main__":
    unittest.main()
