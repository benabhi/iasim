"""Security tests for the MCP agent surface."""

from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from typing import Any

import uvicorn

from iasim.app.session import GameSession
from iasim.crafting import load_catalog
from iasim.domain.agents import AgentProfile
from iasim.domain.geometry import Position
from iasim.domain.items import Inventory, ItemStack
from iasim.domain.tiles import TileType, WorldMap
from iasim.mcp.policy import (
    ALLOWED_TOOL_NAMES,
    FORBIDDEN_ARGUMENT_NAMES,
    FORBIDDEN_TOOL_TOKENS,
    enforce_tool_policy,
)
from iasim.mcp.server import create_app, create_server
from iasim.world.layout import WorldLayout

CATALOG = load_catalog()
HIDDEN_STATE_KEYS = ("seed", "rng_state", "world", "tiles")
PERCEPTION_AGENT_FIELDS = {
    "id",
    "name",
    "pos",
    "health_band",
    "equipment_visible",
    "relation",
}


def _layout(first: Position, second: Position, *, size: int = 30) -> WorldLayout:
    return WorldLayout(
        seed=42,
        world=WorldMap(width=size, height=size, tiles=(TileType.GRASS,) * (size * size)),
        spawn_points=(first, second),
    )


def _wood() -> Inventory:
    return Inventory.for_strength(5).add(ItemStack(CATALOG.item("wood").definition, 1))


def _far_session() -> tuple[GameSession, str, str]:
    session = GameSession(
        42,
        layout=_layout(Position(2, 2), Position(26, 26)),
        profiles=(AgentProfile(), AgentProfile(inventory=_wood())),
    )
    return (
        session,
        session.join("Nia", session.tokens[0])["agent_id"],
        session.join("Kai", session.tokens[1])["agent_id"],
    )


def _near_session() -> tuple[GameSession, str, str]:
    session = GameSession(
        42,
        layout=_layout(Position(2, 2), Position(3, 2), size=6),
        profiles=(AgentProfile(), AgentProfile(inventory=_wood())),
    )
    return (
        session,
        session.join("Nia", session.tokens[0])["agent_id"],
        session.join("Kai", session.tokens[1])["agent_id"],
    )


def _tool_names(session: GameSession) -> set[str]:
    server = create_server(session)
    return set(server._tool_manager._tools)


def _tools(session: GameSession) -> dict[str, Any]:
    server = create_server(session)
    return dict(server._tool_manager._tools)


class ToolAllowlistTests(unittest.TestCase):
    def test_registered_tools_match_the_allowlist(self) -> None:
        names = _tool_names(GameSession(42, layout=_layout(Position(2, 2), Position(3, 2))))

        self.assertEqual(names, set(ALLOWED_TOOL_NAMES))

    def test_an_unexpected_tool_breaks_the_policy(self) -> None:
        with self.assertRaises(RuntimeError):
            enforce_tool_policy(set(ALLOWED_TOOL_NAMES) | {"iasim_admin_spawn"})

    def test_a_missing_tool_breaks_the_policy(self) -> None:
        with self.assertRaises(RuntimeError):
            enforce_tool_policy(set(ALLOWED_TOOL_NAMES) - {"iasim_observe"})

    def test_no_tool_name_uses_a_forbidden_token(self) -> None:
        for name in ALLOWED_TOOL_NAMES:
            with self.subTest(tool=name):
                token = name.removeprefix("iasim_")
                self.assertFalse(
                    any(forbidden in token for forbidden in FORBIDDEN_TOOL_TOKENS),
                    f"forbidden tool exposed: {name}",
                )

    def test_no_tool_accepts_hidden_state_arguments(self) -> None:
        session = GameSession(42, layout=_layout(Position(2, 2), Position(3, 2)))

        for name, tool in _tools(session).items():
            properties = set(tool.parameters.get("properties", {}))
            with self.subTest(tool=name):
                self.assertEqual(properties & FORBIDDEN_ARGUMENT_NAMES, set())


class HiddenStateTests(unittest.TestCase):
    def test_observation_hides_the_world_rng_and_far_agents(self) -> None:
        session, first, second = _far_session()

        payload = json.dumps(session.observe(first))

        for key in HIDDEN_STATE_KEYS:
            self.assertNotIn(key, payload)
        self.assertNotIn(second, payload)
        self.assertNotIn("wood", payload)
        self.assertNotIn(session.tokens[0], payload)

    def test_nearby_agents_expose_only_perception_fields(self) -> None:
        session, first, second = _near_session()

        observation = session.observe(first)

        visible = {entry["id"]: entry for entry in observation["perception"]["agents"]}
        self.assertIn(second, visible)
        self.assertEqual(set(visible[second]), PERCEPTION_AGENT_FIELDS)
        self.assertNotIn("wood", json.dumps(visible[second]))

    def test_inspect_is_limited_to_perception(self) -> None:
        session, first, second = _far_session()

        result = session.inspect(first, target_id=second)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "NOT_VISIBLE")

    def test_session_info_has_no_seed_rng_or_positions(self) -> None:
        session, first, _ = _far_session()

        info = session.info(first)
        payload = json.dumps(info)

        for key in HIDDEN_STATE_KEYS:
            self.assertNotIn(key, payload)
        self.assertTrue(info["agents"])
        for agent in info["agents"]:
            self.assertEqual(set(agent), {"id", "name", "alive", "status"})

    def test_inventory_and_recipes_are_agent_scoped(self) -> None:
        session, first, second = _far_session()

        first_inventory = session.inventory_for(first)
        recipes = session.recipes()

        self.assertNotIn("wood", json.dumps(first_inventory))
        self.assertIn("wood", json.dumps(session.inventory_for(second)))
        self.assertNotIn("agents", recipes)
        self.assertNotIn("seed", json.dumps(recipes))

    def test_join_payload_has_no_secrets(self) -> None:
        session = GameSession(42, layout=_layout(Position(2, 2), Position(3, 2)))

        joined = session.join("Nia", session.tokens[0])
        payload = json.dumps(joined)

        self.assertNotIn("seed", payload)
        self.assertNotIn("rng_state", payload)
        self.assertNotIn(session.tokens[0], payload)


def _start(app: Any) -> tuple[uvicorn.Server, threading.Thread, int]:
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        raise RuntimeError("test server did not start")
    return server, thread, server.servers[0].sockets[0].getsockname()[1]


def _stop(server: uvicorn.Server, thread: threading.Thread) -> None:
    server.should_exit = True
    server.force_exit = True
    thread.join(timeout=10)


class HealthEndpointTests(unittest.TestCase):
    def test_health_endpoint_has_no_secrets(self) -> None:
        session = GameSession(42, layout=_layout(Position(2, 2), Position(3, 2)))
        _, app = create_app(session)
        server, thread, port = _start(app)
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/healthz",
                timeout=5,
            ) as response:
                payload = json.dumps(json.loads(response.read()))
        finally:
            _stop(server, thread)

        self.assertFalse(thread.is_alive())
        for key in ("seed", "rng_state", "world", "tiles"):
            self.assertNotIn(key, payload)
        self.assertNotIn(session.tokens[0], payload)

    def test_unauthenticated_requests_are_consistently_rejected(self) -> None:
        session = GameSession(42, layout=_layout(Position(2, 2), Position(3, 2)))
        _, app = create_app(session)
        server, thread, port = _start(app)
        try:
            for attempt in range(5):
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/mcp",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.subTest(attempt=attempt):
                    with self.assertRaises(urllib.error.HTTPError) as raised:
                        urllib.request.urlopen(request, timeout=5)
                    self.assertEqual(raised.exception.code, 401)
        finally:
            _stop(server, thread)

        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
