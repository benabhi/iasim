"""Tests for live full-screen routing in the integrated operator app."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from iasim.app.session import GameSession
from iasim.ui.app import OperatorApp
from iasim.ui.controls import UiView


class OperatorViewRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = GameSession(42, max_agents=2)
        self.first = self.session.join("Nia", self.session.tokens[0])["agent_id"]
        self.session.join("Kai", self.session.tokens[1])
        self.app = OperatorApp(self.session, capacity=2)

    def assert_view(self, marker: str) -> None:
        screen = self.app.render()
        self.assertEqual((screen.width, screen.height), (160, 45))
        self.assertTrue(
            all(len(screen.row_text(y)) == 160 for y in range(45)),
        )
        self.assertIn(marker, screen.to_text())

    def test_base_view_and_help_route(self) -> None:
        self.assert_view("AGENTES")
        self.app.press("f1")
        self.assert_view("AYUDA Y LEYENDA")
        self.app.press("esc")
        self.assert_view("AGENTES")

    def test_f2_agent_sheet(self) -> None:
        self.app.press("f2")
        self.assertEqual(self.app.ui.view, UiView.AGENT_SHEET)
        self.assert_view("F2")
        self.assert_view("Nia")
        self.app.press("esc")
        self.assert_view("AGENTES")

    def test_f3_world_summary(self) -> None:
        self.app.press("f3")
        self.assert_view("F3")
        self.assert_view("MUNDO")

    def test_f4_event_log_and_filters(self) -> None:
        self.app.press("f4")
        self.assert_view("F4 · EVENTOS")
        self.assertIn("SE UNIÓ", self.app.render().to_text())

        self.app.press("/")
        for char in "Nia":
            self.app.press(char)
        self.app.press("enter")
        self.assertIn("Búsqueda: nia", self.app.render().to_text())

        self.app.press("t")
        self.assertIn("Filtro: ACCIONES", self.app.render().to_text())

    def test_f5_replay_notice(self) -> None:
        self.app.press("f5")
        screen = self.app.render()
        text = screen.to_text()

        self.assertIn("REPLAY", text)
        self.assertIn("iasim --replay", text)
        self.assertIn("El replay interactivo en vivo", text)
        self.assert_view("REPLAY")

    def test_f6_map_and_f7_metrics_and_f8_settings(self) -> None:
        self.app.press("f6")
        self.assert_view("F6 · MAPA")
        self.app.press("esc")

        self.app.press("f7")
        self.assert_view("F7 · MÉTRICAS")
        self.app.press("esc")

        self.app.press("f8")
        self.assert_view("F8 · AJUSTES")
        self.assert_view("Paleta")

    def test_f11_calls_the_fullscreen_adapter(self) -> None:
        with patch("iasim.ui.app.request_fullscreen") as request:
            self.app.press("f11")
            request.assert_called_once_with(True)
            self.app.press("f11")
            request.assert_called_with(False)


if __name__ == "__main__":
    unittest.main()
