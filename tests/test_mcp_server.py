"""Tests for the minimal MCP server surface."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import unittest
import urllib.request
from typing import Any

import uvicorn
from mcp import Client
from starlette.requests import Request

from iasim.app.session import GameSession
from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType, WorldMap
from iasim.mcp.server import create_app, create_server
from iasim.world.layout import WorldLayout

TOOL_NAMES = {
    "iasim_join",
    "iasim_observe",
    "iasim_move",
    "iasim_wait",
    "iasim_wait_for_tick",
}


def _layout() -> WorldLayout:
    return WorldLayout(
        seed=42,
        world=WorldMap(
            width=5,
            height=5,
            tiles=(TileType.GRASS,) * 25,
        ),
        spawn_points=(Position(2, 2),),
    )


def _data(result: Any) -> dict[str, Any]:
    content = result.structured_content
    if content is None:
        raise AssertionError("MCP tool did not return structured content")
    return content


class McpServerTests(unittest.TestCase):
    def test_client_joins_observes_moves_and_waits(self) -> None:
        session = GameSession(42, layout=_layout())
        server = create_server(session)

        async def flow() -> None:
            async with Client(server) as client:
                tools = await client.list_tools()
                self.assertEqual({tool.name for tool in tools.tools}, TOOL_NAMES)

                joined = _data(await client.call_tool("iasim_join", {"name": "Nia"}))
                agent_id = joined["agent_id"]
                self.assertTrue(joined["ok"])
                self.assertEqual(joined["spawn"], [2, 2])

                observation = _data(await client.call_tool("iasim_observe", {"agent_id": agent_id}))
                self.assertEqual(observation["tick"], 0)
                self.assertEqual(observation["agent"]["pos"], [2, 2])
                self.assertNotIn("world", observation)
                self.assertNotIn("seed", observation)
                self.assertNotIn("rng_state", observation)
                self.assertLessEqual(len(observation["perception"]["visible"]), 49)

                moved = _data(
                    await client.call_tool(
                        "iasim_move",
                        {"agent_id": agent_id, "tick": 0, "dx": 1, "dy": 0},
                    )
                )
                self.assertTrue(moved["ok"])
                observation = _data(await client.call_tool("iasim_observe", {"agent_id": agent_id}))
                self.assertEqual(observation["tick"], 1)
                self.assertEqual(observation["agent"]["pos"], [3, 2])
                self.assertEqual(observation["last_action_result"]["status"], "success")

                waited = _data(
                    await client.call_tool(
                        "iasim_wait",
                        {"agent_id": agent_id, "tick": 1},
                    )
                )
                self.assertTrue(waited["ok"])
                observation = _data(await client.call_tool("iasim_observe", {"agent_id": agent_id}))
                self.assertEqual(observation["tick"], 2)
                self.assertEqual(observation["agent"]["pos"], [3, 2])
                self.assertEqual(observation["last_action_result"]["action"], "wait")

                fresh = _data(
                    await client.call_tool(
                        "iasim_wait_for_tick",
                        {"agent_id": agent_id, "since_tick": 1, "timeout_ms": 100},
                    )
                )
                self.assertEqual(fresh["tick"], 2)

                timed_out = _data(
                    await client.call_tool(
                        "iasim_wait_for_tick",
                        {"agent_id": agent_id, "since_tick": 2, "timeout_ms": 10},
                    )
                )
                self.assertFalse(timed_out["ok"])
                self.assertEqual(timed_out["error"]["code"], "NO_NEW_TICK")

        asyncio.run(flow())

    def test_http_transport_join_observe_move_wait(self) -> None:
        session = GameSession(42, layout=_layout())
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

            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/healthz",
                timeout=5,
            ) as response:
                health = json.loads(response.read())
            self.assertEqual(health["status"], "ok")

            async def flow() -> None:
                async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                    joined = _data(await client.call_tool("iasim_join", {"name": "Nia"}))
                    agent_id = joined["agent_id"]
                    observation = _data(
                        await client.call_tool("iasim_observe", {"agent_id": agent_id})
                    )
                    self.assertEqual(observation["tick"], 0)

                    moved = _data(
                        await client.call_tool(
                            "iasim_move",
                            {"agent_id": agent_id, "tick": 0, "dx": 1, "dy": 0},
                        )
                    )
                    self.assertTrue(moved["ok"])
                    observation = _data(
                        await client.call_tool("iasim_observe", {"agent_id": agent_id})
                    )
                    self.assertEqual(observation["tick"], 1)

                    waited = _data(
                        await client.call_tool(
                            "iasim_wait",
                            {"agent_id": agent_id, "tick": 1},
                        )
                    )
                    self.assertTrue(waited["ok"])
                    observation = _data(
                        await client.call_tool("iasim_observe", {"agent_id": agent_id})
                    )
                    self.assertEqual(observation["tick"], 2)

            asyncio.run(flow())
        finally:
            server.should_exit = True
            thread.join(timeout=5)

        self.assertFalse(thread.is_alive())

    def test_health_route_responds_without_secrets(self) -> None:
        session = GameSession(42, layout=_layout())
        _, app = create_app(session)
        route = next(route for route in app.routes if getattr(route, "path", None) == "/healthz")
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/healthz",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 123),
            "scheme": "http",
            "root_path": "",
        }

        response = asyncio.run(route.endpoint(Request(scope)))
        payload = json.loads(response.body)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["agents"], 0)
        self.assertNotIn("world", payload)
        self.assertNotIn("seed", payload)
        self.assertNotIn("rng_state", payload)


if __name__ == "__main__":
    unittest.main()
