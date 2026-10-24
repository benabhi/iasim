"""Tests for the protocol version contract and compatibility errors."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from mcp.client import Client

from iasim.app.session import SCHEMA_VERSION, GameSession
from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType, WorldMap
from iasim.mcp.server import create_server
from iasim.protocol import MAX_PROTOCOL_VERSION_LENGTH, PROTOCOL_VERSION
from iasim.world.layout import WorldLayout


def _layout() -> WorldLayout:
    return WorldLayout(
        seed=42,
        world=WorldMap(width=5, height=5, tiles=(TileType.GRASS,) * 25),
        spawn_points=(Position(2, 2),),
    )


def _session() -> GameSession:
    return GameSession(42, layout=_layout())


async def _join_schema() -> dict[str, Any]:
    server = create_server(_session())
    async with Client(server) as client:
        tools = await client.list_tools()
        join = next(tool for tool in tools.tools if tool.name == "iasim_join")
        return join.input_schema


class ProtocolConstantTests(unittest.TestCase):
    def test_the_protocol_version_is_fixed(self) -> None:
        self.assertEqual(PROTOCOL_VERSION, "iasim-mcp/1.0")
        self.assertEqual(SCHEMA_VERSION, "1.0")
        self.assertEqual(MAX_PROTOCOL_VERSION_LENGTH, 32)

    def test_the_observation_carries_both_versions(self) -> None:
        session = _session()
        agent_id = session.join("Nia", session.tokens[0])["agent_id"]

        observation = session.observe(agent_id)

        self.assertEqual(observation["protocol_version"], PROTOCOL_VERSION)
        self.assertEqual(observation["schema_version"], SCHEMA_VERSION)

    def test_the_health_payload_carries_both_versions(self) -> None:
        health = _session().health()

        self.assertEqual(health["protocol_version"], PROTOCOL_VERSION)
        self.assertEqual(health["schema_version"], SCHEMA_VERSION)

    def test_errors_carry_the_protocol_version(self) -> None:
        session = _session()

        error = session.join("Nia", "invalid-token")

        self.assertFalse(error["ok"])
        self.assertEqual(error["protocol_version"], PROTOCOL_VERSION)


class JoinVersionTests(unittest.TestCase):
    def test_join_without_a_declared_version_is_accepted(self) -> None:
        session = _session()

        joined = session.join("Nia", session.tokens[0])

        self.assertTrue(joined["ok"])
        self.assertEqual(joined["protocol_version"], PROTOCOL_VERSION)

    def test_join_with_the_current_version_is_accepted(self) -> None:
        session = _session()

        joined = session.join("Nia", session.tokens[0], protocol_version=PROTOCOL_VERSION)

        self.assertTrue(joined["ok"])
        self.assertEqual(joined["protocol_version"], PROTOCOL_VERSION)

    def test_join_with_an_incompatible_version_is_rejected(self) -> None:
        session = _session()
        token = session.tokens[0]

        joined = session.join("Nia", token, protocol_version="iasim-mcp/9.9")

        self.assertFalse(joined["ok"])
        self.assertEqual(joined["error"]["code"], "UNSUPPORTED_PROTOCOL_VERSION")
        self.assertEqual(
            joined["error"]["details"],
            {"supported": PROTOCOL_VERSION, "received": "iasim-mcp/9.9"},
        )
        self.assertIsNone(session.agent_for_token(token))
        self.assertEqual(session.state.agents, ())

    def test_join_rejects_blank_or_oversized_versions(self) -> None:
        session = _session()
        token = session.tokens[0]

        for invalid in ("", " ", "x" * (MAX_PROTOCOL_VERSION_LENGTH + 1)):
            with self.subTest(version=invalid):
                result = session.join("Nia", token, protocol_version=invalid)
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], "UNSUPPORTED_PROTOCOL_VERSION")


class JoinToolSchemaTests(unittest.TestCase):
    def test_the_join_tool_accepts_an_optional_protocol_version(self) -> None:
        schema = asyncio.run(_join_schema())

        self.assertEqual(set(schema["required"]), {"name"})
        version = schema["properties"]["protocol_version"]
        if "anyOf" in version:
            version = next(option for option in version["anyOf"] if option.get("type") == "string")
        self.assertEqual(version["maxLength"], MAX_PROTOCOL_VERSION_LENGTH)


if __name__ == "__main__":
    unittest.main()
