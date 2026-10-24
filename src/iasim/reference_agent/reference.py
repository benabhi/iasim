"""Deterministic scripted reference agent that plays the MVP over MCP.

The agent is intentionally simple: it only uses the perception-limited
observation, the public inventory/recipe tools, and the documented action
surface. It never asks for the seed, the full map, or other agents' hidden
state, so it doubles as an adversarial check that the MCP boundary is sound.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from mcp import ClientSession
from mcp.client import streamable_http
from mcp.client.streamable_http import streamable_http_client

from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType

# MCP tools the reference agent is allowed to call. Anything else is a
# boundary violation and makes the integration test fail.
ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "iasim_join",
        "iasim_observe",
        "iasim_get_inventory",
        "iasim_get_recipes",
        "iasim_move",
        "iasim_move_to",
        "iasim_wait",
        "iasim_rest",
        "iasim_gather",
        "iasim_eat",
        "iasim_drink",
        "iasim_craft",
        "iasim_report_mind",
        "iasim_wait_for_tick",
    }
)

_DIRECTIONS: tuple[tuple[int, int], ...] = (
    (1, 0),
    (1, 1),
    (0, 1),
    (-1, 1),
    (-1, 0),
    (-1, -1),
    (0, -1),
    (1, -1),
)
_BUSH_RESOURCES = frozenset({"bush_berries"})
_THIRST_SEEK = 55.0
_HUNGER_SEEK = 55.0
_LOW_ENERGY = 25.0
_REPORT_EVERY_TICKS = 20
_MAX_RATE_LIMIT_RETRIES = 20
_RATE_LIMIT_BACKOFF_SECONDS = 0.1


class ToolCaller(Protocol):
    """Minimal MCP tool client used by the reference agent."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


@dataclass(frozen=True, slots=True)
class ReferenceCommand:
    """One deterministic scripted action for the current tick."""

    tool: str
    arguments: dict[str, Any]
    intent: str
    thought: str


@dataclass(frozen=True, slots=True)
class ReferenceReport:
    """Observable outcome of one reference-agent run."""

    ticks_run: int
    actions: int
    minds_reported: int
    final_position: Position
    alive: bool
    errors: tuple[str, ...] = ()


@dataclass(slots=True)
class ReferenceAgent:
    """A deterministic gather/eat/drink/explore loop driven only through MCP."""

    client: ToolCaller
    name: str = "Reference"
    report_every: int = _REPORT_EVERY_TICKS
    _agent_id: str | None = None
    _position: Position | None = None
    _tick: int = 0
    _heading: int = 0
    _actions: int = 0
    _minds: int = 0
    _health: float = 100.0
    _errors: list[str] = field(default_factory=list)
    _inventory: dict[str, int] = field(default_factory=dict)

    @property
    def agent_id(self) -> str:
        if self._agent_id is None:
            raise RuntimeError("agent has not joined")
        return self._agent_id

    async def join(self) -> str:
        """Join the session over the authenticated MCP client."""
        result = _data(await self.client.call_tool("iasim_join", {"name": self.name}))
        if not result.get("ok"):
            raise RuntimeError(f"join failed: {result}")
        self._agent_id = str(result["agent_id"])
        self._position = _position_from(result["spawn"])
        return self._agent_id

    async def _call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in ALLOWED_TOOLS:
            raise RuntimeError(f"reference agent is not allowed to call {name}")
        for attempt in range(_MAX_RATE_LIMIT_RETRIES):
            result = _data(await self.client.call_tool(name, arguments))
            error = result.get("error")
            if not isinstance(error, dict) or error.get("code") != "RATE_LIMITED":
                return result
            if attempt + 1 < _MAX_RATE_LIMIT_RETRIES:
                await asyncio.sleep(_RATE_LIMIT_BACKOFF_SECONDS)
        raise RuntimeError(f"tool {name} remained rate limited")

    async def observe(self) -> dict[str, Any]:
        result = await self._call("iasim_observe", {})
        if not result.get("ok", True):
            raise RuntimeError(f"observe failed: {result}")
        self._tick = int(result["tick"])
        self._position = _position_from(result["agent"]["pos"])
        self._health = float(result["agent"].get("health", 0))
        return result

    async def _refresh_inventory(self) -> dict[str, int]:
        result = await self._call("iasim_get_inventory", {})
        if not result.get("ok", True):
            raise RuntimeError(f"inventory failed: {result}")
        items = result["inventory"]["items"]
        self._inventory = {str(item["item_id"]): int(item["qty"]) for item in items}
        return self._inventory

    async def _cached_inventory(self) -> dict[str, int]:
        if not self._inventory or self._tick % 5 == 0:
            return await self._refresh_inventory()
        return self._inventory

    async def _report_mind(self, command: ReferenceCommand) -> None:
        result = await self._call(
            "iasim_report_mind",
            {
                "tick": self._tick,
                "intent": command.intent,
                "thought": command.thought,
                "plan": command.tool,
                "confidence": 70,
            },
        )
        if result.get("ok", True):
            self._minds += 1
        else:
            self._errors.append(str(result.get("error", "mind report failed")))

    async def step(self) -> None:
        """Run one observed tick: choose one action and optionally report mind."""
        observation = await self.observe()
        if self._health <= 0:
            return
        inventory = await self._cached_inventory()
        command = choose_action(observation, inventory, self._heading)
        if command is None:
            return
        if self.report_every > 0 and self._tick % self.report_every == 0:
            await self._report_mind(command)
        result = await self._call(command.tool, command.arguments)
        if not result.get("ok", True):
            self._errors.append(str(result.get("error", f"{command.tool} failed")))
        else:
            self._actions += 1
            if command.tool in {"iasim_gather", "iasim_eat", "iasim_drink", "iasim_craft"}:
                await self._refresh_inventory()

    async def run(
        self,
        ticks: int = 500,
        max_attempts: int | None = None,
    ) -> ReferenceReport:
        """Play at least ``ticks`` resolved ticks and return the outcome."""
        if ticks < 1:
            raise ValueError("ticks must be positive")
        if self._agent_id is None:
            raise RuntimeError("agent has not joined")
        start_tick = self._tick
        attempts_limit = max_attempts if max_attempts is not None else ticks * 3
        attempts = 0
        while self._tick - start_tick < ticks and attempts < attempts_limit:
            attempts += 1
            if self._health <= 0:
                break
            await self.step()
        final = await self.observe()
        return ReferenceReport(
            ticks_run=max(0, self._tick - start_tick),
            actions=self._actions,
            minds_reported=self._minds,
            final_position=self._position or _position_from(final["agent"]["pos"]),
            alive=float(final["agent"].get("health", 0)) > 0,
            errors=tuple(self._errors),
        )


def choose_action(
    observation: Mapping[str, Any],
    inventory: Mapping[str, int],
    heading: int,
) -> ReferenceCommand | None:
    """Choose one deterministic action from a perception-limited observation."""
    agent = observation["agent"]
    position = _position_from(agent["pos"])
    hunger = float(agent.get("hunger", 0))
    thirst = float(agent.get("thirst", 0))
    energy = float(agent.get("energy", 100))
    visible = observation.get("perception", {}).get("visible", [])
    tiles: dict[tuple[int, int], str] = {}
    resources: dict[tuple[int, int], str] = {}
    for tile in visible:
        key = (int(tile["x"]), int(tile["y"]))
        tiles[key] = str(tile["tile"])
        values = tile.get("resources") or []
        if values:
            resources[key] = str(values[0])

    adjacent = {(position.x + dx, position.y + dy): (dx, dy) for dx, dy in _DIRECTIONS}
    water_tiles = [
        Position(int(tile["x"]), int(tile["y"]))
        for tile in visible
        if str(tile["tile"]) == "fresh_water"
    ]
    bush_tiles = [
        Position(int(tile["x"]), int(tile["y"]))
        for tile in visible
        if resources.get((int(tile["x"]), int(tile["y"]))) in _BUSH_RESOURCES
    ]

    if thirst >= _THIRST_SEEK:
        for key, (dx, dy) in adjacent.items():
            del dx, dy
            if tiles.get(key) == "fresh_water":
                return ReferenceCommand(
                    "iasim_drink",
                    {"tick": int(observation["tick"]), "x": key[0], "y": key[1]},
                    "Beber agua",
                    f"Sed {thirst:.0f}: bebo del agua adyacente.",
                )
        if inventory.get("waterskin", 0) > 0:
            return ReferenceCommand(
                "iasim_drink",
                {"tick": int(observation["tick"]), "item_id": "waterskin"},
                "Beber del odre",
                f"Sed {thirst:.0f}: uso el odre.",
            )
        target = _nearest(position, water_tiles)
        if target is not None:
            return _move_to(observation["tick"], target, "Buscar agua", thirst)
        return _explore(observation["tick"], position, tiles, heading, "Buscar agua")

    if hunger >= _HUNGER_SEEK:
        if inventory.get("berry", 0) > 0:
            return ReferenceCommand(
                "iasim_eat",
                {"tick": int(observation["tick"]), "item_id": "berry"},
                "Comer",
                f"Hambre {hunger:.0f}: como una baya.",
            )
        for key, _direction in adjacent.items():
            if resources.get(key) in _BUSH_RESOURCES:
                return ReferenceCommand(
                    "iasim_gather",
                    {"tick": int(observation["tick"]), "x": key[0], "y": key[1]},
                    "Recoger bayas",
                    f"Hambre {hunger:.0f}: recojo bayas del arbusto.",
                )
        target = _nearest(position, bush_tiles)
        if target is not None:
            return _move_to(observation["tick"], target, "Buscar comida", hunger)
        return _explore(observation["tick"], position, tiles, heading, "Buscar comida")

    if energy <= _LOW_ENERGY:
        return ReferenceCommand(
            "iasim_rest",
            {"tick": int(observation["tick"])},
            "Descansar",
            f"Energía {energy:.0f}: descanso.",
        )

    for key, resource in resources.items():
        if key in adjacent and resource in _BUSH_RESOURCES:
            return ReferenceCommand(
                "iasim_gather",
                {"tick": int(observation["tick"]), "x": key[0], "y": key[1]},
                "Abastecerse",
                "Recojo bayas para la reserva.",
            )
    if inventory.get("fiber", 0) >= 3 and inventory.get("clay", 0) >= 2:
        return ReferenceCommand(
            "iasim_craft",
            {"tick": int(observation["tick"]), "recipe_id": "waterskin"},
            "Fabricar odre",
            "Tengo fibras y arcilla: fabrico un odre.",
        )
    if inventory.get("waterskin", 0) == 0:
        target = _nearest(
            position,
            [
                Position(int(tile["x"]), int(tile["y"]))
                for tile in visible
                if resources.get((int(tile["x"]), int(tile["y"])))
                in {"tall_grass_fiber", "river_clay"}
            ],
        )
        if target is not None:
            return _move_to(observation["tick"], target, "Buscar materiales", 0.0)
    return _explore(observation["tick"], position, tiles, heading, "Explorar")


def _move_to(
    tick: int,
    target: Position,
    intent: str,
    need: float,
) -> ReferenceCommand:
    return ReferenceCommand(
        "iasim_move_to",
        {"tick": tick, "x": target.x, "y": target.y},
        intent,
        f"Me dirijo a ({target.x}, {target.y}) (necesidad {need:.0f}).",
    )


def _explore(
    tick: int,
    position: Position,
    tiles: Mapping[tuple[int, int], str],
    heading: int,
    intent: str,
) -> ReferenceCommand:
    for offset in range(8):
        index = (heading + offset) % 8
        dx, dy = _DIRECTIONS[index]
        tile = tiles.get((position.x + dx, position.y + dy))
        if tile is None:
            continue
        try:
            parsed = TileType(tile)
        except ValueError:
            continue
        if parsed.walkable:
            return ReferenceCommand(
                "iasim_move",
                {"tick": tick, "dx": dx, "dy": dy},
                intent,
                f"Exploro hacia ({dx}, {dy}).",
            )
    return ReferenceCommand(
        "iasim_wait",
        {"tick": tick},
        "Esperar",
        "No hay un paso libre visible: espero.",
    )


def _nearest(origin: Position, targets: list[Position]) -> Position | None:
    if not targets:
        return None
    return min(
        targets,
        key=lambda target: (
            abs(target.x - origin.x) + abs(target.y - origin.y),
            target.y,
            target.x,
        ),
    )


async def run_reference_agent(
    url: str,
    token: str,
    *,
    name: str = "Reference",
    ticks: int = 500,
) -> ReferenceReport:
    """Connect with a bearer token, join, and play ``ticks`` resolved ticks."""
    headers = {"Authorization": f"Bearer {token}"}
    async with (
        streamable_http.create_mcp_http_client(  # type: ignore[attr-defined]
            headers=headers
        ) as http_client,
        streamable_http_client(url, http_client=http_client) as (
            read_stream,
            write_stream,
        ),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        agent = ReferenceAgent(session, name)
        await agent.join()
        return await agent.run(ticks=ticks)


def _data(result: Any) -> dict[str, Any]:
    content = result.structured_content
    if not isinstance(content, dict):
        raise RuntimeError("MCP tool returned no structured content")
    return {str(key): value for key, value in content.items()}


def _position_from(values: Any) -> Position:
    return Position(int(values[0]), int(values[1]))
