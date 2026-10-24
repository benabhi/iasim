"""End-to-end MCP integration tests over the real HTTP transport."""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import (
    create_mcp_http_client,
    streamable_http_client,
)

from iasim.app.session import GameSession
from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType, WorldMap
from iasim.mcp.server import LAN_WARNING, RunningServer, start_server
from iasim.world.layout import WorldLayout


def _layout() -> WorldLayout:
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


async def _connect(url: str, token: str) -> tuple[Any, Any, Any]:
    """Open one authenticated MCP session and initialize it."""
    headers = {"Authorization": f"Bearer {token}"}
    http_client = create_mcp_http_client(headers=headers)
    client = await http_client.__aenter__()
    streams = streamable_http_client(url, http_client=client)
    read_stream, write_stream = await streams.__aenter__()
    session = await ClientSession(read_stream, write_stream).__aenter__()
    await session.initialize()
    return http_client, streams, session


class McpIntegrationTests(unittest.TestCase):
    def _server(
        self,
        directory: Path,
        *,
        host: str = "127.0.0.1",
        turn_timeout_ms: int = 60_000,
        timeout_disconnects: int = 3,
        max_agents: int = 2,
    ) -> tuple[GameSession, RunningServer]:
        session = GameSession(
            42,
            layout=_layout(),
            max_agents=max_agents,
            token_path=directory / "agents.json",
            turn_timeout_ms=turn_timeout_ms,
            timeout_disconnects=timeout_disconnects,
        )
        server = start_server(session, host=host, port=0)
        return session, server

    def test_a_slow_agent_is_resolved_by_the_deadline_without_hanging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session, server = self._server(
                Path(directory),
                turn_timeout_ms=150,
                timeout_disconnects=2,
            )
            first_token, second_token = session.tokens[:2]
            started = time.monotonic()
            try:

                async def flow() -> dict[str, Any]:
                    http_a, streams_a, client_a = await _connect(
                        server.mcp_url,
                        first_token,
                    )
                    http_b, streams_b, client_b = await _connect(
                        server.mcp_url,
                        second_token,
                    )
                    try:
                        await client_a.call_tool("iasim_join", {"name": "Nia"})
                        await client_b.call_tool("iasim_join", {"name": "Kai"})
                        self.assertTrue(
                            _data(
                                await client_a.call_tool(
                                    "iasim_wait",
                                    {"tick": 0},
                                )
                            )["ok"]
                        )
                        self.assertEqual(session.tick, 0)
                        advanced = _data(
                            await client_a.call_tool(
                                "iasim_wait_for_tick",
                                {"since_tick": 0, "timeout_ms": 1500},
                            )
                        )
                        self.assertEqual(advanced["tick"], 1)
                        observation = _data(await client_a.call_tool("iasim_observe", {}))
                        return observation
                    finally:
                        await client_b.__aexit__(None, None, None)
                        await streams_b.__aexit__(None, None, None)
                        await http_b.__aexit__(None, None, None)
                        await client_a.__aexit__(None, None, None)
                        await streams_a.__aexit__(None, None, None)
                        await http_a.__aexit__(None, None, None)

                observation = asyncio.run(flow())
            finally:
                server.stop()

            self.assertLess(time.monotonic() - started, 10)
            self.assertEqual(observation["tick"], 1)
            self.assertEqual(
                observation["last_action_result"]["status"],
                "success",
            )
            self.assertEqual(
                observation["last_action_result"]["outcome"],
                "waited",
            )
            self.assertFalse(server.healthy)
            self.assertEqual(session.state.agents, ())

    def test_token_and_slot_are_reusable_after_leave(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session, server = self._server(Path(directory))
            token = session.tokens[0]
            try:

                async def flow() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
                    http_client, streams, client = await _connect(
                        server.mcp_url,
                        token,
                    )
                    try:
                        joined = _data(await client.call_tool("iasim_join", {"name": "Nia"}))
                        left = _data(await client.call_tool("iasim_leave", {}))
                        rejoined = _data(await client.call_tool("iasim_join", {"name": "Nia"}))
                        return joined, left, rejoined
                    finally:
                        await client.__aexit__(None, None, None)
                        await streams.__aexit__(None, None, None)
                        await http_client.__aexit__(None, None, None)

                joined, left, rejoined = asyncio.run(flow())
            finally:
                server.stop()

            self.assertTrue(joined["ok"])
            self.assertTrue(left["ok"])
            self.assertTrue(rejoined["ok"])
            self.assertEqual(joined["agent_id"], rejoined["agent_id"])
            self.assertEqual(joined["spawn"], rejoined["spawn"])
            self.assertEqual(session.state.agents, ())

    def test_lan_binding_accepts_an_authenticated_join(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session, server = self._server(Path(directory), host="0.0.0.0")
            token = session.tokens[0]
            self.assertEqual(server.warning, LAN_WARNING)
            self.assertNotIn("0.0.0.0", server.mcp_url)
            try:
                url = f"http://127.0.0.1:{server.port}/mcp"

                async def flow() -> dict[str, Any]:
                    http_client, streams, client = await _connect(url, token)
                    try:
                        return _data(await client.call_tool("iasim_join", {"name": "Lan"}))
                    finally:
                        await client.__aexit__(None, None, None)
                        await streams.__aexit__(None, None, None)
                        await http_client.__aexit__(None, None, None)

                joined = asyncio.run(flow())
            finally:
                server.stop()

            self.assertTrue(joined["ok"])
            self.assertEqual(joined["agent_id"], "ag_01")

    def test_unauthenticated_and_malformed_requests_are_structured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session, server = self._server(Path(directory))
            try:
                with self.assertRaises(urllib.error.HTTPError) as unauth:
                    urllib.request.urlopen(
                        server.mcp_url,
                        data=json.dumps({"jsonrpc": "2.0"}).encode("utf-8"),
                        timeout=5,
                    )
                self.assertEqual(unauth.exception.code, 401)
                request = urllib.request.Request(
                    server.mcp_url,
                    data=b"{not-json",
                    headers={
                        "Authorization": f"Bearer {session.tokens[0]}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as malformed:
                    urllib.request.urlopen(request, timeout=5)
                self.assertIn(malformed.exception.code, {400, 406})
                body = malformed.exception.read().decode("utf-8")
                self.assertTrue(body)
            finally:
                server.stop()

            self.assertFalse(server.healthy)


if __name__ == "__main__":
    unittest.main()
