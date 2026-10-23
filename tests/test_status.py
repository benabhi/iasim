"""Tests for survival status thresholds and exposure damage."""

from __future__ import annotations

import unittest

from iasim.app.session import GameSession
from iasim.domain.agents import Agent, AgentAttributes, AgentProfile, AgentStatus
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.session import SessionState
from iasim.domain.status import (
    Condition,
    apply_status_tick,
    dexterity_penalty,
    energy_damage_centi,
    health_damage_centi,
    status_tags,
    strength_penalty,
    vision_penalty,
)
from iasim.domain.tiles import TileType, WorldMap
from iasim.world.layout import WorldLayout


def _agent(
    *,
    health_centi: int = 10_000,
    hunger_centi: int = 1_500,
    thirst_centi: int = 1_500,
    energy_centi: int = 8_000,
    wetness_centi: int = 0,
    body_temperature_centi: int = 3_700,
    status: AgentStatus = AgentStatus.ACTIVE,
) -> Agent:
    return Agent(
        AgentId("ag_01"),
        Position(2, 2),
        attributes=AgentAttributes(
            health_centi=health_centi,
            hunger_centi=hunger_centi,
            thirst_centi=thirst_centi,
            energy_centi=energy_centi,
            wetness_centi=wetness_centi,
            body_temperature_centi=body_temperature_centi,
        ),
        status=status,
    )


def _state(agent: Agent) -> SessionState:
    return SessionState(
        seed=42,
        tick=0,
        rng_state=42,
        world=WorldMap(width=5, height=5, tiles=(TileType.GRASS,) * 25),
        agents=(agent,),
    )


class StatusTagTests(unittest.TestCase):
    def test_hunger_and_thirst_thresholds_are_exclusive(self) -> None:
        self.assertEqual(status_tags(_agent(hunger_centi=7_000)), ())
        self.assertEqual(status_tags(_agent(hunger_centi=7_001)), (Condition.HUNGRY,))
        self.assertEqual(
            status_tags(_agent(hunger_centi=10_000)),
            (Condition.STARVING,),
        )
        self.assertEqual(
            status_tags(_agent(thirst_centi=7_001)),
            (Condition.THIRSTY,),
        )
        self.assertEqual(
            status_tags(_agent(thirst_centi=10_000)),
            (Condition.DEHYDRATED,),
        )

    def test_energy_temperature_and_wetness_tags(self) -> None:
        self.assertIn(Condition.EXHAUSTED, status_tags(_agent(energy_centi=1_999)))
        self.assertIn(Condition.HYPOTHERMIA, status_tags(_agent(body_temperature_centi=3_499)))
        self.assertIn(Condition.HEAT_STROKE, status_tags(_agent(body_temperature_centi=4_001)))
        self.assertIn(Condition.WET, status_tags(_agent(wetness_centi=6_001)))
        self.assertIn(
            Condition.DEAD,
            status_tags(
                _agent(
                    health_centi=0,
                    status=AgentStatus.DEAD,
                )
            ),
        )


class StatusEffectTests(unittest.TestCase):
    def test_penalties_and_damage_follow_srs_bands(self) -> None:
        hungry = _agent(hunger_centi=7_001).attributes
        starving = _agent(hunger_centi=10_000).attributes
        thirsty = _agent(thirst_centi=7_001).attributes
        dehydrated = _agent(thirst_centi=10_000).attributes
        exhausted = _agent(energy_centi=1_999).attributes
        cold = _agent(body_temperature_centi=3_499).attributes
        hot = _agent(body_temperature_centi=4_001).attributes

        self.assertEqual(strength_penalty(hungry), 1)
        self.assertEqual(strength_penalty(starving), 2)
        self.assertEqual(health_damage_centi(hungry), 2)
        self.assertEqual(health_damage_centi(starving), 20)
        self.assertEqual(dexterity_penalty(thirsty), 1)
        self.assertEqual(vision_penalty(dehydrated), 1)
        self.assertEqual(dexterity_penalty(exhausted), 1)
        self.assertEqual(vision_penalty(exhausted), 1)
        self.assertEqual(dexterity_penalty(cold), 2)
        self.assertEqual(health_damage_centi(cold), 20)
        self.assertEqual(health_damage_centi(hot), 30)
        self.assertEqual(energy_damage_centi(hot), 20)

    def test_status_tick_damages_and_kills_without_mutating_the_original(self) -> None:
        agent = _agent(health_centi=30, hunger_centi=10_000)
        state = _state(agent)

        after_one = apply_status_tick(state)
        after_two = apply_status_tick(after_one)

        self.assertEqual(after_one.agents[0].attributes.health_centi, 10)
        self.assertTrue(after_one.agents[0].is_alive)
        self.assertEqual(after_two.agents[0].attributes.health_centi, 0)
        self.assertEqual(after_two.agents[0].status, AgentStatus.DEAD)
        self.assertEqual(agent.attributes.health_centi, 30)

    def test_heat_stroke_drains_energy(self) -> None:
        state = apply_status_tick(_state(_agent(body_temperature_centi=4_001, energy_centi=100)))

        self.assertEqual(state.agents[0].attributes.energy_centi, 80)


class StatusSessionTests(unittest.TestCase):
    def test_observation_exposes_status_and_effective_attributes(self) -> None:
        session = GameSession(
            42,
            layout=WorldLayout(
                seed=42,
                world=WorldMap(
                    width=5,
                    height=5,
                    tiles=(TileType.GRASS,) * 25,
                ),
                spawn_points=(Position(2, 2),),
            ),
            profiles=(
                AgentProfile(
                    attributes=AgentAttributes(
                        hunger_centi=10_000,
                        thirst_centi=10_000,
                        energy_centi=1_000,
                    )
                ),
            ),
        )
        agent_id = session.join("Nia", session.tokens[0])["agent_id"]
        session.wait(agent_id, 0)
        observation = session.observe(agent_id)

        self.assertIn("starving", observation["agent"]["status"])
        self.assertIn("dehydrated", observation["agent"]["status"])
        self.assertIn("exhausted", observation["agent"]["status"])
        self.assertLess(observation["agent"]["health"], 100.0)
        self.assertLess(observation["agent"]["dexterity"], 5)


if __name__ == "__main__":
    unittest.main()
