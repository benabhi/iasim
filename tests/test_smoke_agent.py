"""F0 smoke-agent integration test over the real MCP HTTP transport."""

from __future__ import annotations

import asyncio
import threading
import time
import unittest

import uvicorn
from mcp import Client

from iasim.app.session import GameSession
from iasim.domain.identifiers import AgentId
from iasim.mcp.server import create_app
from iasim.reference_agent.smoke import SmokeAgent
from iasim.ui.layout import render_base_screen


class SmokeAgentTests(unittest.TestCase):
    def test_smoke_agent_moves_twenty_ticks_and_ui_reflects_position(self) -> None:
        session = GameSession(42)
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

            async def flow() -> tuple[str, tuple]:
                async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                    agent = SmokeAgent(client, name="Smoke")
                    await agent.join()
                    positions = await agent.run(ticks=20)
                    return agent.agent_id, positions

            agent_id, positions = asyncio.run(flow())
        finally:
            server.should_exit = True
            thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(positions), 21)
        self.assertGreater(len(set(positions)), 1)
        self.assertGreaterEqual(session.state.tick, 20)
        self.assertEqual(len(session.state.agents), 1)
        self.assertEqual(session.state.agents[0].position, positions[-1])

        names = {AgentId(agent_id): "Smoke"}
        screen = render_base_screen(
            session.state,
            names,
            selected_agent_id=AgentId(agent_id),
        )
        last = positions[-1]
        self.assertEqual(screen.cell_at(last.x, last.y).char, "@")
        panel = "\n".join(screen.row_text(y)[80:] for y in range(45))
        self.assertIn("Smoke", panel)
        self.assertIn(f"({last.x}, {last.y})", panel)


if __name__ == "__main__":
    unittest.main()
