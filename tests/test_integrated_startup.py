"""Tests for the integrated startup: background MCP server and GUI render."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client import streamable_http
from mcp.client.streamable_http import streamable_http_client

from iasim.app.session import GameSession
from iasim.mcp.server import RunningServer, start_server
from iasim.ui.app import OperatorApp, format_event
from iasim.ui.controls import UiView


def _join(url: str, token: str | None) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        headers = {} if token is None else {"Authorization": f"Bearer {token}"}
        async with (
            streamable_http.create_mcp_http_client(  # type: ignore[attr-defined]
                headers=headers
            ) as http_client,
            streamable_http_client(url, http_client=http_client) as (
                read_stream,
                write_stream,
            ),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            result = await session.call_tool("iasim_join", {"name": "Lan"})
            return dict(result.structured_content or {})

    return asyncio.run(run())


class RunningServerTests(unittest.TestCase):
    def _server(self, directory: Path) -> tuple[GameSession, RunningServer]:
        session = GameSession(7, token_path=directory / "agents.json")
        return session, start_server(session, host="127.0.0.1", port=0)

    def test_the_server_is_healthy_and_authenticates_agents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session, server = self._server(Path(directory))
            try:
                self.assertTrue(server.healthy)
                self.assertGreater(server.port, 0)
                with urllib.request.urlopen(f"{server.url_for('/healthz')}") as response:
                    self.assertEqual(response.status, 200)
                    health = json.loads(response.read().decode("utf-8"))
                    self.assertTrue(health.get("ok", True))
                joined = _join(server.mcp_url, session.tokens[0])
                self.assertTrue(joined["ok"], joined)
                self.assertEqual(joined["agent_id"], "ag_01")
                with self.assertRaises(BaseExceptionGroup):
                    _join(server.mcp_url, "not-a-real-token")
            finally:
                server.stop()

            self.assertFalse(server.healthy)
            server.stop()

    def test_a_second_start_uses_a_free_ephemeral_port(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first_session = GameSession(1, token_path=Path(directory) / "agents.json")
            first = start_server(first_session, host="127.0.0.1", port=0)
            second_session = GameSession(2, token_path=Path(directory) / "agents.json")
            second = start_server(second_session, host="127.0.0.1", port=0)
            try:
                self.assertNotEqual(first.port, second.port)
                self.assertTrue(first.healthy)
                self.assertTrue(second.healthy)
            finally:
                first.stop()
                second.stop()

    def test_dev_open_allows_loopback_join_without_a_bearer_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = GameSession(7, token_path=Path(directory) / "agents.json")
            server = start_server(
                session,
                host="127.0.0.1",
                port=0,
                dev_open=True,
            )
            try:
                joined = _join(server.mcp_url, None)
            finally:
                server.stop()

            self.assertTrue(joined["ok"], joined)
            self.assertEqual(joined["agent_id"], "ag_01")


class OperatorAppTests(unittest.TestCase):
    def _app(self, directory: Path) -> tuple[GameSession, OperatorApp]:
        session = GameSession(7, token_path=directory / "agents.json")
        session.join("Nia", session.tokens[0])
        return session, OperatorApp(session, capacity=8)

    def test_the_full_160x45_gui_renders_live_session_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session, app = self._app(Path(directory))
            screen = app.render()

        self.assertEqual((screen.width, screen.height), (160, 45))
        self.assertTrue(all(len(screen.row_text(y)) == 160 for y in range(45)))
        agent = session.state.agents[0]
        self.assertEqual(screen.cell_at(agent.position.x, agent.position.y).char, "@")
        text = screen.to_text()
        self.assertIn("Nia", text)
        self.assertIn("AGENTES", text)
        self.assertIn("[F1] Ayuda", text)
        self.assertIn("SE UNIÓ", text)

    def test_keys_route_through_the_controls_and_quit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _session, app = self._app(Path(directory))

            self.assertIsNone(app.press("f4"))
            self.assertEqual(app.ui.view, UiView.EVENT_LOG)
            self.assertIsNone(app.press("esc"))
            self.assertEqual(app.ui.view, UiView.NONE)
            self.assertIsNone(app.press("q"))
            self.assertEqual(app.press("q"), "quit")

    def test_recent_events_are_formatted_with_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session, _app_instance = self._app(Path(directory))
            events = session.recent_events(10)
            names = session.names_snapshot()

        rendered = [format_event(event, names) for event in events]
        self.assertTrue(any("SE UNIÓ" in line and "Nia" in line for line in rendered))


if __name__ == "__main__":
    unittest.main()
