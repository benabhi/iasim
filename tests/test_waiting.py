"""Tests for the open-server waiting lifecycle after the last death."""

from __future__ import annotations

import unittest

from iasim.app.session import GameSession, SessionPhase, SessionWaitReason
from iasim.domain.agents import Agent, AgentAttributes, AgentProfile
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.ui.layout import render_base_screen
from iasim.world.layout import WorldLayout


def _layout() -> WorldLayout:
    return WorldLayout(
        seed=42,
        world=WorldMap(width=5, height=5, tiles=(TileType.GRASS,) * 25),
        spawn_points=(Position(2, 2), Position(3, 2)),
    )


class WaitingStateTests(unittest.TestCase):
    def test_new_session_waits_for_agents(self) -> None:
        session = GameSession(42, layout=_layout())

        self.assertEqual(session.phase, SessionPhase.WAITING)
        self.assertEqual(session.waiting_reason, SessionWaitReason.NO_AGENTS)
        self.assertEqual(session.health()["waiting_reason"], "no_agents")

    def test_last_death_pauses_without_extra_ticks_and_allows_a_free_slot(self) -> None:
        starving = AgentProfile(
            attributes=AgentAttributes(
                health_centi=100,
                hunger_centi=100 * 100,
                thirst_centi=100 * 100,
            )
        )
        session = GameSession(
            42,
            layout=_layout(),
            profiles=(starving, AgentProfile()),
        )
        first = session.join("Nia", session.tokens[0])["agent_id"]

        self.assertTrue(session.wait(first, 0)["ok"])
        self.assertTrue(session.wait(first, 1)["ok"])

        self.assertEqual(session.phase, SessionPhase.WAITING)
        self.assertEqual(session.waiting_reason, SessionWaitReason.LAST_DEATH)
        self.assertEqual(session.health()["waiting_reason"], "last_death")
        self.assertEqual(len(session.state.corpses), 1)
        self.assertEqual(session.wait(first, 2)["error"]["code"], "AGENT_DEAD")
        self.assertEqual(session.state.tick, 2)

        joined = session.join("Kai", session.tokens[1])
        self.assertTrue(joined["ok"])
        self.assertEqual(session.phase, SessionPhase.RUNNING)
        self.assertIsNone(session.waiting_reason)
        self.assertNotIn("waiting_reason", session.health())

    def test_operator_can_finish_and_restart_after_the_waiting_state(self) -> None:
        starving = AgentProfile(
            attributes=AgentAttributes(
                health_centi=100,
                hunger_centi=100 * 100,
                thirst_centi=100 * 100,
            )
        )
        session = GameSession(42, layout=_layout(), profiles=(starving, AgentProfile()))
        first = session.join("Nia", session.tokens[0])["agent_id"]
        self.assertTrue(session.wait(first, 0)["ok"])
        self.assertTrue(session.wait(first, 1)["ok"])
        self.assertEqual(session.waiting_reason, SessionWaitReason.LAST_DEATH)

        summary = session.finish()
        self.assertEqual(summary["phase"], "finished")
        self.assertEqual(session.phase, SessionPhase.FINISHED)
        self.assertIsNone(session.waiting_reason)

        restarted = session.restart(seed=43)
        self.assertEqual(restarted.phase, SessionPhase.WAITING)
        self.assertEqual(restarted.waiting_reason, SessionWaitReason.NO_AGENTS)

    def test_ui_shows_waiting_state(self) -> None:
        state = SessionState(
            seed=42,
            tick=0,
            rng_state=42,
            world=_layout().world,
            agents=(Agent(AgentId("ag_01"), Position(2, 2)),),
        )

        screen = render_base_screen(
            state,
            {AgentId("ag_01"): "Nia"},
            selected_agent_id=AgentId("ag_01"),
            waiting_reason="last_death",
        )
        panel = "\n".join(screen.row_text(y)[80:] for y in range(45))

        self.assertIn("ESPERANDO AGENTES", panel)
        self.assertIn("ÚLTIMA MUERTE", panel)


if __name__ == "__main__":
    unittest.main()
