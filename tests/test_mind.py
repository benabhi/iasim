"""Tests for operator-visible mind reports and thoughts.jsonl logging."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from iasim.app.session import GameSession
from iasim.domain.agents import Agent
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.mind import MAX_INTENT_LENGTH, MAX_THOUGHT_LENGTH, MindReport
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.ui.layout import render_base_screen
from iasim.world.generation import generate_layout
from iasim.world.layout import WorldLayout


def _layout() -> WorldLayout:
    return WorldLayout(
        seed=42,
        world=WorldMap(width=5, height=5, tiles=(TileType.GRASS,) * 25),
        spawn_points=(Position(2, 2),),
    )


class MindReportTests(unittest.TestCase):
    def test_report_is_stored_and_logged_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "thoughts.jsonl"
            session = GameSession(42, layout=_layout(), log_dir=Path(directory))
            agent_id = session.join("Nia", session.tokens[0])["agent_id"]

            result = session.report_mind(
                agent_id,
                0,
                intent="Buscar agua",
                thought="Tengo sed.",
                plan="Ir al río",
                confidence=80,
            )

            self.assertTrue(result["ok"])
            report = session.mind_report_for(agent_id)
            assert report is not None
            self.assertEqual(report.intent, "Buscar agua")
            self.assertEqual(report.thought, "Tengo sed.")
            self.assertEqual(report.plan, "Ir al río")
            self.assertEqual(report.confidence, 80)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["event"], "mind_report")
            self.assertEqual(record["agent_id"], agent_id)
            self.assertEqual(record["intent"], "Buscar agua")

    def test_report_is_sanitized_and_limited_to_one_per_tick(self) -> None:
        session = GameSession(42, layout=_layout())
        agent_id = session.join("Nia", session.tokens[0])["agent_id"]

        first = session.report_mind(
            agent_id,
            0,
            intent="\x1b[31mBuscar\x1b[0m\nagua",
            thought="Tengo\t sed\x00",
            plan="  ",
        )
        second = session.report_mind(agent_id, 0, intent="Otra", thought="Otra")

        self.assertTrue(first["ok"])
        self.assertEqual(second["error"]["code"], "ALREADY_REPORTED")
        report = session.mind_report_for(agent_id)
        assert report is not None
        self.assertEqual(report.intent, "Buscar agua")
        self.assertEqual(report.thought, "Tengo sed")
        self.assertIsNone(report.plan)

    def test_report_rejects_invalid_ticks_confidence_and_lengths(self) -> None:
        session = GameSession(42, layout=_layout())
        agent_id = session.join("Nia", session.tokens[0])["agent_id"]

        future = session.report_mind(agent_id, 1, intent="Uno", thought="Dos")
        invalid_confidence = session.report_mind(
            agent_id,
            0,
            intent="Uno",
            thought="Dos",
            confidence=101,
        )
        long_intent = session.report_mind(
            agent_id,
            0,
            intent="x" * (MAX_INTENT_LENGTH + 1),
            thought="Dos",
        )
        long_thought = session.report_mind(
            agent_id,
            0,
            intent="Uno",
            thought="x" * (MAX_THOUGHT_LENGTH + 1),
        )

        self.assertEqual(future["error"]["code"], "INVALID_TICK")
        self.assertEqual(invalid_confidence["error"]["code"], "INVALID_MIND_REPORT")
        self.assertEqual(long_intent["error"]["code"], "MESSAGE_TOO_LONG")
        self.assertEqual(long_thought["error"]["code"], "MESSAGE_TOO_LONG")

    def test_report_resets_after_leave(self) -> None:
        session = GameSession(42, layout=_layout())
        token = session.tokens[0]
        agent_id = session.join("Nia", token)["agent_id"]
        session.report_mind(agent_id, 0, intent="Uno", thought="Dos")

        self.assertTrue(session.leave(agent_id)["ok"])
        rejoined = session.join("Nia", token)["agent_id"]

        self.assertIsNone(session.mind_report_for(rejoined))


class MindLayoutTests(unittest.TestCase):
    def test_selected_mind_report_is_rendered(self) -> None:
        layout = generate_layout(42, agent_count=1)
        state = SessionState(
            seed=42,
            tick=0,
            rng_state=42,
            world=layout.world,
            agents=(Agent(AgentId("ag_01"), layout.spawn_points[0]),),
        )
        reports = {
            AgentId("ag_01"): MindReport(
                agent_id=AgentId("ag_01"),
                tick=0,
                intent="Explorar",
                thought="Veo un río.",
                plan="Caminar al este",
                confidence=70,
            )
        }

        screen = render_base_screen(
            state,
            {AgentId("ag_01"): "Nia"},
            selected_agent_id=AgentId("ag_01"),
            mind_reports=reports,
        )
        panel = "\n".join(screen.row_text(y)[80:] for y in range(45))

        self.assertIn("MENTE (REPORTADO)", panel)
        self.assertIn("Intención: Explorar", panel)
        self.assertIn("Pensamiento: Veo un río.", panel)
        self.assertIn("Plan: Caminar al este", panel)
        self.assertIn("Confianza: 70", panel)

    def test_missing_mind_report_keeps_placeholder(self) -> None:
        layout = generate_layout(42, agent_count=1)
        state = SessionState(
            seed=42,
            tick=0,
            rng_state=42,
            world=layout.world,
            agents=(Agent(AgentId("ag_01"), layout.spawn_points[0]),),
        )

        screen = render_base_screen(
            state,
            {AgentId("ag_01"): "Nia"},
            selected_agent_id=AgentId("ag_01"),
            mind_reports={},
        )
        panel = "\n".join(screen.row_text(y)[80:] for y in range(45))

        self.assertIn("— sin reporte —", panel)


if __name__ == "__main__":
    unittest.main()
