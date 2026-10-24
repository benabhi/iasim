"""Tests for the deterministic scripted reference agent."""

from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn

from iasim.app.session import GameSession
from iasim.mcp.policy import FORBIDDEN_TOOL_TOKENS
from iasim.mcp.server import create_app
from iasim.reference_agent.reference import (
    ALLOWED_TOOLS,
    ReferenceAgent,
    choose_action,
    run_reference_agent,
)


@dataclass
class _ToolResult:
    structured_content: dict[str, Any]


class _SessionToolClient:
    """Tool-contract double that drives the real session without HTTP."""

    def __init__(self, session: GameSession, token: str) -> None:
        self.session = session
        self.token = token
        self.agent_id: str | None = None
        self.calls: list[str] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> _ToolResult:
        self.calls.append(name)
        session = self.session
        agent_id = self.agent_id
        if name == "iasim_join":
            result = session.join(arguments["name"], self.token)
            self.agent_id = result.get("agent_id")
        elif agent_id is None:
            raise AssertionError(f"{name} called before join")
        elif name == "iasim_observe":
            result = session.observe(agent_id)
        elif name == "iasim_get_inventory":
            result = session.inventory_for(agent_id)
        elif name == "iasim_get_recipes":
            result = session.recipes()
        elif name == "iasim_move":
            result = session.move(
                agent_id,
                arguments["tick"],
                arguments["dx"],
                arguments["dy"],
            )
        elif name == "iasim_move_to":
            result = session.move_to(
                agent_id,
                arguments["tick"],
                arguments["x"],
                arguments["y"],
            )
        elif name == "iasim_wait":
            result = session.wait(agent_id, arguments["tick"])
        elif name == "iasim_rest":
            result = session.rest(agent_id, arguments["tick"])
        elif name == "iasim_gather":
            result = session.gather(
                agent_id,
                arguments["tick"],
                arguments["x"],
                arguments["y"],
                arguments.get("node_id"),
            )
        elif name == "iasim_eat":
            result = session.eat(agent_id, arguments["tick"], arguments["item_id"])
        elif name == "iasim_drink":
            result = session.drink(
                agent_id,
                arguments["tick"],
                x=arguments.get("x"),
                y=arguments.get("y"),
                item_id=arguments.get("item_id"),
            )
        elif name == "iasim_craft":
            result = session.craft(
                agent_id,
                arguments["tick"],
                arguments["recipe_id"],
            )
        elif name == "iasim_report_mind":
            result = session.report_mind(
                agent_id,
                arguments["tick"],
                intent=arguments["intent"],
                thought=arguments["thought"],
                plan=arguments.get("plan"),
                confidence=arguments.get("confidence"),
            )
        elif name == "iasim_wait_for_tick":
            result = session.wait_for_tick(
                agent_id,
                arguments["since_tick"],
                arguments["timeout_ms"],
            )
        else:
            raise RuntimeError(f"unexpected tool {name}")
        return _ToolResult(dict(result))


def _observation(
    *,
    position: tuple[int, int] = (10, 10),
    hunger: float = 10.0,
    thirst: float = 10.0,
    energy: float = 80.0,
    tiles: dict[tuple[int, int], str] | None = None,
    resources: dict[tuple[int, int], str] | None = None,
    tick: int = 3,
) -> dict[str, Any]:
    tiles = tiles or {}
    resources = resources or {}
    visible = [
        {
            "x": x,
            "y": y,
            "tile": tile,
            "glyph": ".",
            "resource": resources.get((x, y)),
            "resources": [resources[(x, y)]] if (x, y) in resources else [],
            "entities": [],
        }
        for (x, y), tile in tiles.items()
    ]
    return {
        "tick": tick,
        "agent": {
            "id": "ag_01",
            "name": "Ref",
            "pos": [position[0], position[1]],
            "health": 100.0,
            "hunger": hunger,
            "thirst": thirst,
            "energy": energy,
        },
        "perception": {"visible": visible},
    }


class ReferencePolicyTests(unittest.TestCase):
    def test_thirsty_agent_drinks_from_adjacent_fresh_water(self) -> None:
        observation = _observation(
            thirst=70,
            tiles={(11, 10): "fresh_water"},
        )

        command = choose_action(observation, {}, 0)

        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.tool, "iasim_drink")
        self.assertEqual(command.arguments, {"tick": 3, "x": 11, "y": 10})
        self.assertTrue(command.intent)
        self.assertTrue(command.thought)

    def test_thirsty_agent_walks_to_visible_water(self) -> None:
        observation = _observation(
            thirst=80,
            tiles={(14, 10): "fresh_water"},
        )

        command = choose_action(observation, {}, 0)

        assert command is not None
        self.assertEqual(command.tool, "iasim_move_to")
        self.assertEqual(command.arguments["x"], 14)

    def test_hungry_agent_eats_berries_from_the_inventory(self) -> None:
        command = choose_action(_observation(hunger=70), {"berry": 2}, 0)

        assert command is not None
        self.assertEqual(command.tool, "iasim_eat")
        self.assertEqual(command.arguments["item_id"], "berry")

    def test_hungry_agent_gathers_berries_from_an_adjacent_bush(self) -> None:
        observation = _observation(
            hunger=70,
            tiles={(11, 10): "bush"},
            resources={(11, 10): "bush_berries"},
        )

        command = choose_action(observation, {}, 0)

        assert command is not None
        self.assertEqual(command.tool, "iasim_gather")
        self.assertEqual(command.arguments["x"], 11)

    def test_low_energy_rests(self) -> None:
        command = choose_action(_observation(energy=10), {}, 0)

        assert command is not None
        self.assertEqual(command.tool, "iasim_rest")

    def test_healthy_agent_explores_a_walkable_neighbour(self) -> None:
        observation = _observation(
            tiles={(11, 10): "grass", (10, 11): "tree"},
        )

        command = choose_action(observation, {}, 0)

        assert command is not None
        self.assertIn(command.tool, {"iasim_move", "iasim_wait"})
        self.assertTrue(command.thought)

    def test_the_allowed_tool_set_has_no_administration_or_debug_access(
        self,
    ) -> None:
        for name in ALLOWED_TOOLS:
            token = name.removeprefix("iasim_")
            self.assertFalse(
                any(forbidden in token for forbidden in FORBIDDEN_TOOL_TOKENS),
                f"forbidden tool allowed: {name}",
            )
        self.assertNotIn("iasim_get_seed", ALLOWED_TOOLS)
        self.assertNotIn("iasim_debug", ALLOWED_TOOLS)


class ReferenceAgentLoopTests(unittest.TestCase):
    def _client(self, directory: Path) -> tuple[GameSession, _SessionToolClient]:
        session = GameSession(7, token_path=directory / "agents.json")
        return session, _SessionToolClient(session, session.tokens[0])

    def test_the_agent_survives_and_reports_minds_for_five_hundred_ticks(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session, client = self._client(Path(directory))
            agent = ReferenceAgent(client, "Ref")

            async def run() -> Any:
                await agent.join()
                return await agent.run(ticks=500)

            report = asyncio.run(run())

            self.assertGreaterEqual(report.ticks_run, 500)
            self.assertTrue(report.alive, report.errors)
            self.assertGreaterEqual(report.actions, 500)
            self.assertGreater(report.minds_reported, 0)
            self.assertEqual(report.errors, ())
            self.assertTrue(set(client.calls) <= ALLOWED_TOOLS)
            mind_reports = session.mind_reports_snapshot()
            self.assertTrue(mind_reports)
            report_data = next(iter(mind_reports.values()))
            self.assertTrue(report_data.intent)
            self.assertTrue(report_data.thought)
            self.assertGreaterEqual(session.state.tick, 500)
            self.assertTrue(session.state.agents[0].is_alive)

    def test_the_agent_never_calls_tools_outside_the_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, client = self._client(Path(directory))
            agent = ReferenceAgent(client, "Ref")

            async def run() -> Any:
                await agent.join()
                return await agent.run(ticks=30)

            asyncio.run(run())

            self.assertTrue(client.calls)
            self.assertTrue(set(client.calls) <= ALLOWED_TOOLS)


class ReferenceAgentMcpTests(unittest.TestCase):
    def test_the_reference_agent_plays_over_the_authenticated_mcp_endpoint(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session = GameSession(
                7,
                log_dir=path,
                token_path=path / "agents.json",
            )
            token = session.tokens[0]
            _, app = create_app(session)
            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=0,
                log_level="warning",
            )
            server = uvicorn.Server(config)
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 5
                while not server.started and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(server.started)
                port = server.servers[0].sockets[0].getsockname()[1]

                report = asyncio.run(
                    run_reference_agent(
                        f"http://127.0.0.1:{port}/mcp",
                        token,
                        name="Reference",
                        ticks=40,
                    )
                )
            finally:
                server.should_exit = True
                server.force_exit = True
                thread.join(timeout=1)

            self.assertGreaterEqual(report.ticks_run, 40)
            self.assertTrue(report.alive, report.errors)
            self.assertGreater(report.minds_reported, 0)
            self.assertEqual(report.errors, ())
            self.assertGreaterEqual(session.state.tick, 40)
            thoughts = (path / "thoughts.jsonl").read_text(encoding="utf-8")
            self.assertIn('"intent"', thoughts)
            self.assertIn('"thought"', thoughts)


if __name__ == "__main__":
    unittest.main()
