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
from iasim.mcp.protocol import PROTOCOL_VERSION
from iasim.mcp.server import LAN_WARNING, create_app, create_server, server_connection_info
from iasim.world.layout import WorldLayout

TOOL_NAMES = {
    "iasim_join",
    "iasim_leave",
    "iasim_observe",
    "iasim_get_session_info",
    "iasim_get_recipes",
    "iasim_get_inventory",
    "iasim_inspect",
    "iasim_move",
    "iasim_move_to",
    "iasim_wait",
    "iasim_rest",
    "iasim_sleep",
    "iasim_gather",
    "iasim_pickup",
    "iasim_drop",
    "iasim_eat",
    "iasim_drink",
    "iasim_fill",
    "iasim_use",
    "iasim_equip",
    "iasim_unequip",
    "iasim_craft",
    "iasim_build",
    "iasim_attack",
    "iasim_throw",
    "iasim_flee",
    "iasim_loot",
    "iasim_offer_alliance",
    "iasim_accept_alliance",
    "iasim_break_alliance",
    "iasim_offer_trade",
    "iasim_accept_trade",
    "iasim_decline_trade",
    "iasim_say",
    "iasim_report_mind",
    "iasim_report_usage",
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


def _two_agent_layout() -> WorldLayout:
    return WorldLayout(
        seed=42,
        world=WorldMap(width=6, height=6, tiles=(TileType.GRASS,) * 36),
        spawn_points=(Position(2, 2), Position(3, 2)),
    )


def _data(result: Any) -> dict[str, Any]:
    content = result.structured_content
    if content is None:
        raise AssertionError("MCP tool did not return structured content")
    return content


def _start_server(app: Any) -> tuple[uvicorn.Server, threading.Thread, int]:
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=0,
        log_level="warning",
        timeout_graceful_shutdown=1,
    )
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
                        self.assertEqual(joined["protocol_version"], PROTOCOL_VERSION)

                        said = _data(
                            await client.call_tool(
                                "iasim_say",
                                {"message": "Hola desde el test"},
                            )
                        )
                        self.assertTrue(said["ok"])
                        duplicate_say = _data(
                            await client.call_tool(
                                "iasim_say",
                                {"message": "Segundo mensaje"},
                            )
                        )
                        self.assertEqual(duplicate_say["error"]["code"], "ALREADY_SAID")

                        mind = _data(
                            await client.call_tool(
                                "iasim_report_mind",
                                {
                                    "tick": 0,
                                    "intent": "Explorar",
                                    "thought": "Veo el borde del mapa.",
                                    "plan": "Caminar al este",
                                    "confidence": 60,
                                },
                            )
                        )
                        self.assertTrue(mind["ok"])
                        duplicate_mind = _data(
                            await client.call_tool(
                                "iasim_report_mind",
                                {
                                    "tick": 0,
                                    "intent": "Otra vez",
                                    "thought": "Duplicado",
                                },
                            )
                        )
                        self.assertEqual(
                            duplicate_mind["error"]["code"],
                            "ALREADY_REPORTED",
                        )

                        reported = _data(
                            await client.call_tool(
                                "iasim_report_usage",
                                {
                                    "tick": 0,
                                    "input_tokens": 120,
                                    "output_tokens": 30,
                                    "model": "gpt-5",
                                    "reasoning_effort": "high",
                                    "cost_usd": 0.01,
                                },
                            )
                        )
                        self.assertTrue(reported["ok"])
                        self.assertEqual(reported["usage"]["total_tokens"], 150)
                        self.assertEqual(reported["usage"]["cost_source"], "reported")
                        self.assertAlmostEqual(reported["usage"]["cost_usd"], 0.01)

                        invalid_usage = _data(
                            await client.call_tool(
                                "iasim_report_usage",
                                {
                                    "tick": 0,
                                    "input_tokens": -1,
                                    "output_tokens": 0,
                                    "model": "gpt-5",
                                },
                            )
                        )
                        self.assertFalse(invalid_usage["ok"])
                        self.assertEqual(invalid_usage["error"]["code"], "INVALID_USAGE")

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

                        eaten = _data(
                            await client.call_tool(
                                "iasim_eat",
                                {"tick": 2, "item_id": "berry"},
                            )
                        )
                        self.assertTrue(eaten["ok"])
                        observation = _data(await client.call_tool("iasim_observe", {}))
                        self.assertEqual(observation["tick"], 3)
                        self.assertEqual(observation["last_action_result"]["action"], "eat")
                        self.assertEqual(observation["last_action_result"]["status"], "rejected")
                        self.assertEqual(
                            observation["last_action_result"]["outcome"],
                            "missing_item",
                        )

                        drunk = _data(
                            await client.call_tool(
                                "iasim_drink",
                                {"tick": 3, "x": 2, "y": 2},
                            )
                        )
                        self.assertTrue(drunk["ok"])
                        observation = _data(await client.call_tool("iasim_observe", {}))
                        self.assertEqual(observation["tick"], 4)
                        self.assertEqual(observation["last_action_result"]["action"], "drink")
                        self.assertEqual(
                            observation["last_action_result"]["outcome"],
                            "not_drinkable",
                        )

                        crafted = _data(
                            await client.call_tool(
                                "iasim_craft",
                                {"tick": 4, "recipe_id": "sharp_stone"},
                            )
                        )
                        self.assertTrue(crafted["ok"])
                        observation = _data(await client.call_tool("iasim_observe", {}))
                        self.assertEqual(observation["tick"], 5)
                        self.assertEqual(observation["last_action_result"]["action"], "craft")
                        self.assertEqual(
                            observation["last_action_result"]["outcome"],
                            "missing_ingredients",
                        )

                asyncio.run(flow())
            finally:
                server.should_exit = True
                server.force_exit = True
                thread.join(timeout=10)

            self.assertFalse(thread.is_alive())
            self.assertEqual(session.state.agents[0].position, Position(3, 2))

    def test_http_message_limit_returns_structured_error(self) -> None:
        session = GameSession(42, layout=_layout())
        token = session.tokens[0]
        _, app = create_app(session)
        server, thread, port = _start_server(app)
        try:

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

                    too_long = _data(
                        await client.call_tool(
                            "iasim_sleep",
                            {"tick": 0, "until": "x" * 281},
                        )
                    )
                    self.assertFalse(too_long["ok"])
                    self.assertEqual(too_long["error"]["code"], "MESSAGE_TOO_LONG")

            asyncio.run(flow())
        finally:
            server.should_exit = True
            server.force_exit = True
            thread.join(timeout=10)

        self.assertFalse(thread.is_alive())

    def test_http_information_and_lifecycle_tools(self) -> None:
        session = GameSession(42, layout=_layout())
        token = session.tokens[0]
        _, app = create_app(session)
        server, thread, port = _start_server(app)
        try:

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
                    self.assertEqual(joined["protocol_version"], PROTOCOL_VERSION)

                    info = _data(await client.call_tool("iasim_get_session_info", {}))
                    self.assertEqual(info["protocol_version"], PROTOCOL_VERSION)
                    self.assertEqual(info["time"]["day"], 1)
                    self.assertNotIn("seed", json.dumps(info))
                    self.assertNotIn("rng_state", json.dumps(info))

                    recipes = _data(await client.call_tool("iasim_get_recipes", {}))
                    self.assertTrue(recipes["ok"])
                    self.assertTrue(recipes["recipes"])

                    inventory = _data(await client.call_tool("iasim_get_inventory", {}))
                    self.assertTrue(inventory["ok"])
                    self.assertEqual(inventory["equipment"], {})

                    inspected = _data(await client.call_tool("iasim_inspect", {"x": 2, "y": 2}))
                    self.assertTrue(inspected["ok"])
                    self.assertEqual(inspected["target"]["kind"], "tile")

                    left = _data(await client.call_tool("iasim_leave", {}))
                    self.assertTrue(left["ok"])
                    after = _data(await client.call_tool("iasim_observe", {}))
                    self.assertFalse(after["ok"])
                    self.assertEqual(after["error"]["code"], "UNAUTHORIZED")

            asyncio.run(flow())
        finally:
            server.should_exit = True
            server.force_exit = True
            thread.join(timeout=10)

        self.assertFalse(thread.is_alive())

    def test_http_request_ids_are_idempotent_and_scoped(self) -> None:
        session = GameSession(42, layout=_two_agent_layout())
        token_a = session.tokens[0]
        token_b = session.tokens[1]
        _, app = create_app(session)
        server, thread, port = _start_server(app)
        try:

            async def flow() -> None:
                headers_a = {"Authorization": f"Bearer {token_a}"}
                headers_b = {"Authorization": f"Bearer {token_b}"}
                async with (
                    create_mcp_http_client(headers=headers_a) as http_a,
                    streamable_http_client(
                        f"http://127.0.0.1:{port}/mcp",
                        http_client=http_a,
                    ) as (read_a, write_a),
                    ClientSession(read_a, write_a) as client_a,
                    create_mcp_http_client(headers=headers_b) as http_b,
                    streamable_http_client(
                        f"http://127.0.0.1:{port}/mcp",
                        http_client=http_b,
                    ) as (read_b, write_b),
                    ClientSession(read_b, write_b) as client_b,
                ):
                    await client_a.initialize()
                    await client_b.initialize()
                    joined_a = _data(await client_a.call_tool("iasim_join", {"name": "Nia"}))
                    joined_b = _data(await client_b.call_tool("iasim_join", {"name": "Kai"}))
                    self.assertEqual(joined_a["agent_id"], "ag_01")
                    self.assertEqual(joined_b["agent_id"], "ag_02")

                    first = _data(
                        await client_a.call_tool(
                            "iasim_wait",
                            {"tick": 0, "request_id": "req-a1"},
                        )
                    )
                    self.assertTrue(first["ok"])
                    replay = _data(
                        await client_a.call_tool(
                            "iasim_wait",
                            {"tick": 0, "request_id": "req-a1"},
                        )
                    )
                    self.assertEqual(replay, first)

                    duplicate = _data(
                        await client_a.call_tool(
                            "iasim_wait",
                            {"tick": 0, "request_id": "req-a2"},
                        )
                    )
                    self.assertEqual(duplicate["error"]["code"], "ALREADY_ACTED")
                    self.assertEqual(
                        duplicate["error"]["details"],
                        {"agent_id": "ag_01", "tick": 0},
                    )

                    self.assertTrue(
                        _data(
                            await client_b.call_tool(
                                "iasim_wait",
                                {"tick": 0, "request_id": "req-b1"},
                            )
                        )["ok"]
                    )
                    self.assertEqual(session.tick, 1)

                    stale = _data(
                        await client_a.call_tool(
                            "iasim_wait",
                            {"tick": 0, "request_id": "req-stale"},
                        )
                    )
                    self.assertEqual(stale["error"]["code"], "STALE_TICK")
                    self.assertEqual(
                        stale["error"]["details"],
                        {"received_tick": 0, "current_tick": 1},
                    )

                    # The action rate limiter allows five calls per second per
                    # agent; refill the bucket before the next burst.
                    time.sleep(1.1)

                    conflict = _data(
                        await client_a.call_tool(
                            "iasim_wait",
                            {"tick": 1, "request_id": "req-a1"},
                        )
                    )
                    self.assertEqual(conflict["error"]["code"], "REQUEST_ID_CONFLICT")

                    moved = _data(
                        await client_a.call_tool(
                            "iasim_move",
                            {"tick": 1, "dx": 0, "dy": 1, "request_id": "req-move"},
                        )
                    )
                    self.assertTrue(moved["ok"])
                    moved_replay = _data(
                        await client_a.call_tool(
                            "iasim_move",
                            {"tick": 1, "dx": 0, "dy": 1, "request_id": "req-move"},
                        )
                    )
                    self.assertEqual(moved_replay, moved)

                    self.assertTrue(
                        _data(
                            await client_b.call_tool(
                                "iasim_wait",
                                {"tick": 1, "request_id": "req-b2"},
                            )
                        )["ok"]
                    )
                    observation = _data(await client_a.call_tool("iasim_observe", {}))
                    self.assertEqual(observation["tick"], 2)
                    self.assertEqual(observation["agent"]["pos"], [2, 3])

                    shared_a = _data(
                        await client_a.call_tool(
                            "iasim_wait",
                            {"tick": 2, "request_id": "shared"},
                        )
                    )
                    shared_b = _data(
                        await client_b.call_tool(
                            "iasim_wait",
                            {"tick": 2, "request_id": "shared"},
                        )
                    )
                    self.assertTrue(shared_a["ok"])
                    self.assertTrue(shared_b["ok"])
                    self.assertEqual(session.tick, 3)

            asyncio.run(flow())
        finally:
            server.should_exit = True
            server.force_exit = True
            thread.join(timeout=10)

        self.assertFalse(thread.is_alive())

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
