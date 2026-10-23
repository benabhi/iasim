"""F0 smoke-agent integration test over the real authenticated MCP transport."""

from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path

import uvicorn

from iasim.app.session import GameSession
from iasim.domain.identifiers import AgentId
from iasim.mcp.server import create_app
from iasim.reference_agent.smoke import run_smoke_agent
from iasim.ui.layout import render_base_screen


class SmokeAgentTests(unittest.TestCase):
    def test_smoke_agent_moves_twenty_ticks_and_ui_reflects_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = GameSession(42, token_path=Path(directory) / "agents.json")
            token = session.tokens[0]
            _, app = create_app(session)
            config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
            server = uvicorn.Server(config)
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 5
                while not server.started and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(server.started)
                port = server.servers[0].sockets[0].getsockname()[1]

                positions = asyncio.run(
                    run_smoke_agent(
                        f"http://127.0.0.1:{port}/mcp",
                        token,
                        name="Smoke",
                        ticks=20,
                    )
                )
            finally:
                server.should_exit = True
                server.force_exit = True
                thread.join(timeout=1)

            self.assertEqual(len(positions), 21)
            self.assertGreater(len(set(positions)), 1)
            self.assertGreaterEqual(session.state.tick, 20)
            self.assertEqual(len(session.state.agents), 1)
            self.assertEqual(session.state.agents[0].position, positions[-1])

            agent_id = session.state.agents[0].agent_id
            session.report_usage(
                agent_id,
                session.tick,
                input_tokens=100,
                output_tokens=25,
                model="smoke-model",
                reasoning_effort="low",
                cost_usd=0.001,
            )
            names = {AgentId(agent_id): "Smoke"}
            screen = render_base_screen(
                session.state,
                names,
                selected_agent_id=AgentId(agent_id),
                usage=session.usage_snapshot(),
            )
            last = positions[-1]
            self.assertEqual(screen.cell_at(last.x, last.y).char, "@")
            panel = "\n".join(screen.row_text(y)[80:] for y in range(45))
            self.assertIn("Smoke", panel)
            self.assertIn(f"({last.x}, {last.y})", panel)
            self.assertIn("USO IA (REPORTADO)", panel)
            self.assertIn("smoke-model / low", panel)


if __name__ == "__main__":
    unittest.main()
