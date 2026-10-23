"""Minimal deterministic F0 smoke agent for the IASim MCP server."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mcp import Client

from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType

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
_TURN_ORDER = (0, 1, -1, 2, -2, 3, -3, 4)
_LAND_TILES = frozenset(
    {
        TileType.SAND,
        TileType.GRASS,
        TileType.TALL_GRASS,
        TileType.BUSH,
        TileType.ROCKY_GROUND,
        TileType.CLAY,
        TileType.SHELTER,
        TileType.CORPSE,
        TileType.GROUND_ITEM,
    }
)


class SmokeAgent:
    """A deterministic agent that joins and walks for a smoke-test loop."""

    def __init__(self, client: Client, name: str = "Smoke") -> None:
        self._client = client
        self._name = name
        self._agent_id: str | None = None
        self._position: Position | None = None
        self._heading = 0

    @property
    def agent_id(self) -> str:
        """Return the joined agent id."""
        if self._agent_id is None:
            raise RuntimeError("agent has not joined")
        return self._agent_id

    @property
    def position(self) -> Position:
        """Return the last observed position."""
        if self._position is None:
            raise RuntimeError("agent has not joined")
        return self._position

    async def join(self) -> str:
        """Join the session and remember the assigned spawn."""
        result = _data(await self._client.call_tool("iasim_join", {"name": self._name}))
        if not result.get("ok"):
            raise RuntimeError(f"join failed: {result}")
        self._agent_id = str(result["agent_id"])
        self._position = _position_from(result["spawn"])
        return self._agent_id

    async def observe(self) -> dict[str, Any]:
        """Fetch the current observation."""
        result = _data(await self._client.call_tool("iasim_observe", {"agent_id": self.agent_id}))
        if not result.get("ok", True):
            raise RuntimeError(f"observe failed: {result}")
        return result

    async def step(self) -> bool:
        """Attempt one move or wait and return whether the move succeeded."""
        observation = await self.observe()
        tick = int(observation["tick"])
        direction = self._choose_direction(observation)
        if direction is None:
            self._heading = (self._heading + 1) % 8
            result = _data(
                await self._client.call_tool(
                    "iasim_wait",
                    {"agent_id": self.agent_id, "tick": tick},
                )
            )
        else:
            dx, dy = direction
            result = _data(
                await self._client.call_tool(
                    "iasim_move",
                    {
                        "agent_id": self.agent_id,
                        "tick": tick,
                        "dx": dx,
                        "dy": dy,
                    },
                )
            )
        if not result.get("ok"):
            raise RuntimeError(f"action failed: {result}")
        observation = await self.observe()
        self._position = _position_from(observation["agent"]["pos"])
        last_result = observation.get("last_action_result", {})
        return bool(last_result.get("status") == "success")

    async def run(
        self,
        ticks: int = 20,
        max_attempts: int | None = None,
    ) -> tuple[Position, ...]:
        """Walk for at least ``ticks`` successful moves."""
        if ticks < 1:
            raise ValueError("ticks must be positive")
        if self._agent_id is None:
            raise RuntimeError("agent has not joined")
        attempts_limit = max_attempts if max_attempts is not None else ticks * 4
        positions = [self.position]
        successes = 0
        attempts = 0
        while successes < ticks and attempts < attempts_limit:
            attempts += 1
            if await self.step():
                successes += 1
                positions.append(self.position)
        if successes < ticks:
            raise RuntimeError(f"smoke agent moved only {successes}/{ticks} ticks")
        return tuple(positions)

    def _choose_direction(
        self,
        observation: Mapping[str, Any],
    ) -> tuple[int, int] | None:
        current = _position_from(observation["agent"]["pos"])
        visible = {
            (int(tile["x"]), int(tile["y"])): str(tile["tile"])
            for tile in observation["perception"]["visible"]
        }
        for offset in _TURN_ORDER:
            dx, dy = _DIRECTIONS[(self._heading + offset) % 8]
            tile_name = visible.get((current.x + dx, current.y + dy))
            if tile_name is None:
                continue
            try:
                tile = TileType(tile_name)
            except ValueError:
                continue
            if tile in _LAND_TILES:
                self._heading = (self._heading + offset) % 8
                return dx, dy
        return None


async def run_smoke_agent(
    url: str,
    *,
    name: str = "Smoke",
    ticks: int = 20,
) -> tuple[Position, ...]:
    """Connect to an MCP server, join, and walk for ``ticks`` moves."""
    async with Client(url) as client:
        agent = SmokeAgent(client, name)
        await agent.join()
        return await agent.run(ticks=ticks)


def _data(result: Any) -> dict[str, Any]:
    content = result.structured_content
    if not isinstance(content, dict):
        raise RuntimeError("MCP tool returned no structured content")
    return {str(key): value for key, value in content.items()}


def _position_from(values: Any) -> Position:
    return Position(int(values[0]), int(values[1]))
