"""Tests for the minimal authenticated MCP server surface."""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import uvicorn
from mcp import Client, ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
from starlette.requests import Request

from iasim.app.session import GameSession
from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType, WorldMap
from iasim.mcp.server import LAN_WARNING, create_app, create_server, server_connection_info
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


def _start_server(app: Any) -> tuple[uvicorn.Server, threading.Thread, int]:
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        raise RuntimeError("MCP test server did not start")
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, thread, port


class McpServerTests(unittest.TestCase):
    def test_tool_catalog_is_registered(self) -> None:
        session = GameSession(42, layout=_layout())
        server = create_server(session)

        async def flow() -> None:
            async with Client(server) as client:
                tools = await client.list_tools()
                self.assertEqual({tool.name for tool in tools.tools}, TOOL_NAMES)

        asyncio.run(flow())

    def test_missing_token_is_rejected_at_the_transport(self) -> None:
        session = GameSession(42, layout=_layout())
        _, app = create_app(session)
        server, thread, port = _start_server(app)
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/mcp",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=5)
            self.assertEqual(raised.exception.code, 401)
        finally:
            server.should_exit = True
            server.force_exit = True
            thread.join(timeout=10)

        self.assertFalse(thread.is_alive())

    def test_http_transport_with_token_join_observe_move_wait(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "agents.json"
            session = GameSession(42, layout=_layout(), token_path=token_path)
            token = session.tokens[0]
            _, app = create_app(session)
            server, thread, port = _start_server(app)
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/healthz",
                    timeout=5,
                ) as response:
                    health = json.loads(response.read())
                self.assertEqual(health["status"], "ok")

                async def flow() -> None:
                    headers = {"Authorization": f"Bearer {token}"}
                    async with (
                        create_mcp_http_client(headers=headers) as http_client,
                        streamable_http_client(
                            f"http://127.0.0.1:{port}/mcp",
                            http_client=http_client,
                        ) as (read_stream, write_stream),
                        ClientSession(read_stream, write_stream) as client,
                    ):
                        await client.initialize()
                        joined = _data(await client.call_tool("iasim_join", {"name": "Nia"}))
                        self.assertTrue(joined["ok"])
                        self.assertEqual(joined["spawn"], [2, 2])

                        observation = _data(await client.call_tool("iasim_observe", {}))
                        self.assertEqual(observation["tick"], 0)
                        self.assertEqual(observation["agent"]["pos"], [2, 2])
                        self.assertNotIn("world", observation)
                        self.assertNotIn("seed", observation)
                        self.assertNotIn("rng_state", observation)
                        self.assertNotIn(token, json.dumps(observation))
                        self.assertLessEqual(
                            len(observation["perception"]["visible"]),
                            49,
                        )

                        moved = _data(
                            await client.call_tool(
                                "iasim_move",
                                {"tick": 0, "dx": 1, "dy": 0},
                            )
                        )
                        self.assertTrue(moved["ok"])
                        observation = _data(await client.call_tool("iasim_observe", {}))
                        self.assertEqual(observation["tick"], 1)
                        self.assertEqual(observation["agent"]["pos"], [3, 2])
                        self.assertEqual(
                            observation["last_action_result"]["status"],
                            "success",
                        )

                        waited = _data(await client.call_tool("iasim_wait", {"tick": 1}))
                        self.assertTrue(waited["ok"])
                        observation = _data(await client.call_tool("iasim_observe", {}))
                        self.assertEqual(observation["tick"], 2)
                        self.assertEqual(
                            observation["last_action_result"]["action"],
                            "wait",
                        )

                        fresh = _data(
                            await client.call_tool(
                                "iasim_wait_for_tick",
                                {"since_tick": 1, "timeout_ms": 100},
                            )
                        )
                        self.assertEqual(fresh["tick"], 2)

                        timed_out = _data(
                            await client.call_tool(
                                "iasim_wait_for_tick",
                                {"since_tick": 2, "timeout_ms": 10},
                            )
                        )
                        self.assertFalse(timed_out["ok"])
                        self.assertEqual(timed_out["error"]["code"], "NO_NEW_TICK")

                asyncio.run(flow())
            finally:
                server.should_exit = True
                server.force_exit = True
                thread.join(timeout=10)

            self.assertFalse(thread.is_alive())
            self.assertEqual(session.state.agents[0].position, Position(3, 2))

    def test_loopback_connection_info_has_no_warning(self) -> None:
        info = server_connection_info("127.0.0.1", 8765)

        self.assertTrue(info["loopback"])
        self.assertIsNone(info["warning"])
        self.assertEqual(info["mcp_url"], "http://127.0.0.1:8765/mcp")
        self.assertEqual(info["issuer_url"], "http://127.0.0.1:8765")

    def test_lan_connection_info_advertises_url_and_warning(self) -> None:
        info = server_connection_info("0.0.0.0", 8765)

        self.assertFalse(info["loopback"])
        self.assertEqual(info["warning"], LAN_WARNING)
        self.assertTrue(str(info["mcp_url"]).endswith(":8765/mcp"))
        self.assertNotIn("0.0.0.0", str(info["mcp_url"]))
        self.assertEqual(
            info["issuer_url"],
            str(info["mcp_url"]).removesuffix("/mcp"),
        )

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
