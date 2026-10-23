"""Minimal MCP server exposing the IASim session."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from iasim.app.session import GameSession


def create_server(session: GameSession) -> MCPServer[Any]:
    """Create the MCP server and register the minimal F0 tools."""
    server: MCPServer[Any] = MCPServer("IASim")

    @server.tool()
    def iasim_join(name: str) -> dict[str, Any]:
        """Join the session and return the agent id and spawn coordinates."""
        return session.join(name)

    @server.tool()
    def iasim_observe(agent_id: str) -> dict[str, Any]:
        """Return the current perception-limited observation for an agent."""
        return session.observe(agent_id)

    @server.tool()
    def iasim_move(agent_id: str, tick: int, dx: int, dy: int) -> dict[str, Any]:
        """Queue a one-cell move in one of eight directions."""
        return session.move(agent_id, tick, dx, dy)

    @server.tool()
    def iasim_wait(agent_id: str, tick: int) -> dict[str, Any]:
        """Queue a wait action for the current tick."""
        return session.wait(agent_id, tick)

    @server.tool()
    def iasim_wait_for_tick(
        agent_id: str,
        since_tick: int,
        timeout_ms: int = 1000,
    ) -> dict[str, Any]:
        """Wait until a tick newer than since_tick is available."""
        return session.wait_for_tick(agent_id, since_tick, timeout_ms)

    @server.custom_route("/healthz", methods=["GET"])  # type: ignore[untyped-decorator]
    async def healthz(request: Request) -> Response:
        """Return a minimal unauthenticated health response."""
        return JSONResponse(session.health())

    return server


def create_app(session: GameSession) -> tuple[MCPServer[Any], Starlette]:
    """Create the MCP server and its streamable HTTP application."""
    server = create_server(session)
    return server, server.streamable_http_app()


def run_server(
    session: GameSession,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Run the streamable HTTP MCP server until stopped."""
    server = create_server(session)
    server.run("streamable-http", host=host, port=port)
