"""Tests for per-tick needs evolution."""

from __future__ import annotations

import unittest

from iasim.domain.actions import ActionKind
from iasim.domain.agents import Agent, AgentAttributes, AgentStatus
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.needs import apply_needs_tick
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.turns import ResolvedAction


def _world() -> WorldMap:
    return WorldMap(
        width=5,
        height=5,
        tiles=(TileType.GRASS,) * 25,
    )


def _agent(
    *,
    status: AgentStatus = AgentStatus.ACTIVE,
    health_centi: int = 10_000,
    hunger_centi: int = 1_500,
    thirst_centi: int = 1_500,
    energy_centi: int = 8_000,
    body_temperature_centi: int = 3_700,
    endurance: int = 5,
) -> Agent:
    return Agent(
        AgentId("ag_01"),
        Position(2, 2),
        attributes=AgentAttributes(
            health_centi=health_centi,
            hunger_centi=hunger_centi,
            thirst_centi=thirst_centi,
            energy_centi=energy_centi,
            body_temperature_centi=body_temperature_centi,
            endurance=endurance,
        ),
        status=status,
    )


def _state(agent: Agent) -> SessionState:
    return SessionState(
        seed=42,
        tick=0,
        rng_state=42,
        world=_world(),
        agents=(agent,),
    )


def _resolved(kind: ActionKind) -> ResolvedAction:
    return ResolvedAction(AgentId("ag_01"), kind, 10)


def _evolve(
    agent: Agent,
    resolved: tuple[ResolvedAction, ...] = (),
    *,
    ambient: int = 2000,
):
    result = apply_needs_tick(
        _state(agent),
        resolved,
        ambient_temperature_centi=ambient,
    )
    return result.agents[0].attributes


class NeedsEvolutionTests(unittest.TestCase):
    def test_walking_consumes_needs_by_activity(self) -> None:
        attributes = _evolve(_agent(), (_resolved(ActionKind.MOVE),))

        self.assertEqual(attributes.hunger_centi, 1_535)
        self.assertEqual(attributes.thirst_centi, 1_560)
        self.assertEqual(attributes.energy_centi, 7_975)

    def test_resting_and_no_action_use_the_rest_factor(self) -> None:
        waiting = _evolve(_agent(), (_resolved(ActionKind.WAIT),))
        idle = _evolve(_agent(), ())

        self.assertEqual(waiting.hunger_centi, 1_517)
        self.assertEqual(waiting.thirst_centi, 1_530)
        self.assertEqual(waiting.energy_centi, 7_988)
        self.assertEqual(idle, waiting)

    def test_sleeping_uses_the_sleep_factor(self) -> None:
        attributes = _evolve(_agent(status=AgentStatus.SLEEPING))

        self.assertEqual(attributes.hunger_centi, 1_510)
        self.assertEqual(attributes.thirst_centi, 1_518)
        self.assertEqual(attributes.energy_centi, 7_993)

    def test_heat_increases_thirst(self) -> None:
        attributes = _evolve(
            _agent(),
            (_resolved(ActionKind.ATTACK),),
            ambient=3000,
        )

        self.assertEqual(attributes.hunger_centi, 1_552)
        self.assertEqual(attributes.thirst_centi, 1_635)
        self.assertEqual(attributes.energy_centi, 7_963)

    def test_endurance_reduces_hunger_drain(self) -> None:
        attributes = _evolve(
            _agent(endurance=10),
            (_resolved(ActionKind.MOVE),),
        )

        self.assertEqual(attributes.hunger_centi, 1_529)
        self.assertEqual(attributes.thirst_centi, 1_560)
        self.assertEqual(attributes.energy_centi, 7_975)

    def test_needs_are_clamped(self) -> None:
        attributes = _evolve(
            _agent(hunger_centi=9_999, thirst_centi=9_999, energy_centi=10),
            (_resolved(ActionKind.MOVE),),
        )

        self.assertEqual(attributes.hunger_centi, 10_000)
        self.assertEqual(attributes.thirst_centi, 10_000)
        self.assertEqual(attributes.energy_centi, 0)

    def test_health_recovers_slowly_when_stable(self) -> None:
        attributes = _evolve(_agent(health_centi=9_999))

        self.assertEqual(attributes.health_centi, 10_000)
        self.assertEqual(attributes.hunger_centi, 1_517)

    def test_health_does_not_recover_when_needs_are_unstable(self) -> None:
        attributes = _evolve(_agent(health_centi=9_999, hunger_centi=8_000))

        self.assertEqual(attributes.health_centi, 9_999)

    def test_dead_agents_do_not_evolve(self) -> None:
        dead = _agent(health_centi=0, status=AgentStatus.DEAD)

        attributes = _evolve(dead, (_resolved(ActionKind.MOVE),))

        self.assertEqual(attributes, dead.attributes)


if __name__ == "__main__":
    unittest.main()
