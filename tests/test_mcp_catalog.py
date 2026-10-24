"""Tests for the MCP tool catalog schemas and the protocol identity."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from mcp.client import Client

from iasim.app.session import GameSession
from iasim.domain.geometry import Position
from iasim.domain.items import EquipSlot
from iasim.domain.tiles import TileType, WorldMap
from iasim.mcp.policy import FORBIDDEN_TOOL_TOKENS
from iasim.mcp.server import create_server
from iasim.protocol import PROTOCOL_VERSION
from iasim.world.layout import WorldLayout


def _layout() -> WorldLayout:
    return WorldLayout(
        seed=42,
        world=WorldMap(width=5, height=5, tiles=(TileType.GRASS,) * 25),
        spawn_points=(Position(2, 2),),
    )


async def _tools(session: GameSession) -> dict[str, Any]:
    server = create_server(session)
    async with Client(server) as client:
        tools = await client.list_tools()
        return {tool.name: tool for tool in tools.tools}


async def _call(session: GameSession, name: str, arguments: dict[str, Any]) -> Any:
    server = create_server(session)
    async with Client(server) as client:
        return await client.call_tool(name, arguments)


class ToolSchemaTests(unittest.TestCase):
    def test_every_tool_has_an_object_input_schema(self) -> None:
        tools = asyncio.run(_tools(GameSession(42, layout=_layout())))

        self.assertTrue(tools)
        for name, tool in tools.items():
            with self.subTest(tool=name):
                schema = tool.input_schema
                self.assertEqual(schema["type"], "object")
                self.assertIn("properties", schema)
                self.assertTrue(tool.description)

    def test_tick_arguments_are_non_negative_integers(self) -> None:
        tools = asyncio.run(_tools(GameSession(42, layout=_layout())))

        for name in (
            "iasim_move",
            "iasim_wait",
            "iasim_attack",
            "iasim_equip",
            "iasim_unequip",
            "iasim_offer_trade",
            "iasim_report_mind",
        ):
            with self.subTest(tool=name):
                tick = tools[name].input_schema["properties"]["tick"]
                if "$ref" in tick:
                    tick = _resolve(tools[name].input_schema, tick)
                self.assertEqual(tick["type"], "integer")
                self.assertEqual(tick["minimum"], 0)

    def test_equipment_slot_is_an_enum(self) -> None:
        tools = asyncio.run(_tools(GameSession(42, layout=_layout())))

        schema = tools["iasim_unequip"].input_schema
        slot = _resolve(schema, schema["properties"]["slot"])
        self.assertEqual(slot["enum"], [member.value for member in EquipSlot])
        self.assertEqual(set(schema["required"]), {"tick", "slot"})

    def test_trade_lots_are_strict_item_lists(self) -> None:
        tools = asyncio.run(_tools(GameSession(42, layout=_layout())))

        schema = tools["iasim_offer_trade"].input_schema
        for field in ("offer", "request"):
            lot = schema["properties"][field]
            self.assertEqual(lot["type"], "array")
            item = _resolve(schema, lot["items"])
            self.assertEqual(item["type"], "object")
            self.assertFalse(item["additionalProperties"])
            self.assertEqual(set(item["required"]), {"item_id", "qty"})
            self.assertEqual(item["properties"]["qty"]["minimum"], 1)
            self.assertEqual(item["properties"]["item_id"]["minLength"], 1)

    def test_quantity_and_timeout_bounds_are_declared(self) -> None:
        tools = asyncio.run(_tools(GameSession(42, layout=_layout())))

        drop = tools["iasim_drop"].input_schema["properties"]["qty"]
        self.assertEqual(drop["minimum"], 1)
        wait = tools["iasim_wait_for_tick"].input_schema["properties"]["timeout_ms"]
        self.assertEqual(wait["minimum"], 0)
        self.assertEqual(wait["maximum"], 60_000)

    def test_no_administration_or_debug_tools_are_exposed(self) -> None:
        tools = asyncio.run(_tools(GameSession(42, layout=_layout())))

        for name in tools:
            with self.subTest(tool=name):
                token = name.removeprefix("iasim_")
                self.assertFalse(
                    any(forbidden in token for forbidden in FORBIDDEN_TOOL_TOKENS),
                    f"forbidden tool exposed: {name}",
                )
        self.assertIn("iasim_observe", tools)
        self.assertIn("iasim_get_session_info", tools)

    def test_primary_actions_accept_a_request_id(self) -> None:
        tools = asyncio.run(_tools(GameSession(42, layout=_layout())))

        for name in ("iasim_move", "iasim_wait", "iasim_attack", "iasim_offer_trade"):
            with self.subTest(tool=name):
                schema = tools[name].input_schema
                request_id = schema["properties"]["request_id"]
                if "anyOf" in request_id:
                    request_id = next(
                        option for option in request_id["anyOf"] if option.get("type") == "string"
                    )
                self.assertEqual(request_id["minLength"], 1)
                self.assertEqual(request_id["maxLength"], 64)
                self.assertNotIn("request_id", schema.get("required", []))

    def test_server_advertises_the_protocol_version(self) -> None:
        server = create_server(GameSession(42, layout=_layout()))

        self.assertEqual(server.version, PROTOCOL_VERSION)
        self.assertEqual(PROTOCOL_VERSION, "iasim-mcp/1.0")


class ToolArgumentValidationTests(unittest.TestCase):
    def test_unknown_equipment_slot_is_rejected(self) -> None:
        result = asyncio.run(
            _call(
                GameSession(42, layout=_layout()),
                "iasim_unequip",
                {"tick": 0, "slot": "hat"},
            )
        )

        self.assertTrue(result.is_error)

    def test_negative_tick_is_rejected(self) -> None:
        result = asyncio.run(_call(GameSession(42, layout=_layout()), "iasim_wait", {"tick": -1}))

        self.assertTrue(result.is_error)

    def test_trade_lot_with_zero_quantity_is_rejected(self) -> None:
        result = asyncio.run(
            _call(
                GameSession(42, layout=_layout()),
                "iasim_offer_trade",
                {
                    "tick": 0,
                    "target_id": "ag_02",
                    "offer": [{"item_id": "wood", "qty": 0}],
                    "request": [{"item_id": "berry", "qty": 1}],
                },
            )
        )

        self.assertTrue(result.is_error)

    def test_trade_lot_with_extra_keys_is_rejected(self) -> None:
        result = asyncio.run(
            _call(
                GameSession(42, layout=_layout()),
                "iasim_offer_trade",
                {
                    "tick": 0,
                    "target_id": "ag_02",
                    "offer": [{"item_id": "wood", "qty": 1, "note": "extra"}],
                    "request": [{"item_id": "berry", "qty": 1}],
                },
            )
        )

        self.assertTrue(result.is_error)

    def test_timeout_above_the_limit_is_rejected(self) -> None:
        result = asyncio.run(
            _call(
                GameSession(42, layout=_layout()),
                "iasim_wait_for_tick",
                {"since_tick": 0, "timeout_ms": 120_000},
            )
        )

        self.assertTrue(result.is_error)


def _resolve(schema: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    """Resolve one ``$ref`` into the tool schema ``$defs``."""
    name = reference["$ref"].rsplit("/", 1)[-1]
    return schema["$defs"][name]


if __name__ == "__main__":
    unittest.main()
