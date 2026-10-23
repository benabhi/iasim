"""Minimal MCP server exposing the IASim session."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from iasim.app.session import SCHEMA_VERSION, GameSession
from iasim.domain.identifiers import AgentId

DEFAULT_RESOURCE_URL = "http://127.0.0.1:8765/mcp"
DEFAULT_ISSUER_URL = "http://127.0.0.1:8765"
AUTH_SCOPE = "iasim:agent"


class SessionTokenVerifier:
    """Validate per-slot session tokens without an external OAuth server."""

    def __init__(self, session: GameSession) -> None:
        self._session = session

    async def verify_token(self, token: str) -> AccessToken | None:
        agent_id = self._session.agent_id_for_token(token)
        if agent_id is None:
            return None
        return AccessToken(
            token=token,
            client_id=str(agent_id),
            scopes=[AUTH_SCOPE],
            resource=None,
        )


def create_server(
    session: GameSession,
    *,
    resource_url: str = DEFAULT_RESOURCE_URL,
    issuer_url: str = DEFAULT_ISSUER_URL,
) -> MCPServer[Any]:
    """Create the authenticated MCP server and minimal F0 tools."""
    server: MCPServer[Any] = MCPServer(
        "IASim",
        token_verifier=SessionTokenVerifier(session),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer_url),
            resource_server_url=AnyHttpUrl(resource_url),
            required_scopes=[AUTH_SCOPE],
            validate_token_resource=False,
        ),
    )

    @server.tool()
    def iasim_join(name: str) -> dict[str, Any]:
        """Join the session with the bearer token and return the agent id."""
        access = get_access_token()
        if access is None:
            return _unauthorized(session)
        return session.join(name, access.token)

    @server.tool()
    def iasim_observe() -> dict[str, Any]:
        """Return the current perception-limited observation."""
        agent_id = _joined_agent(session)
        if agent_id is None:
            return _unauthorized(session)
        return session.observe(agent_id)

    @server.tool()
    def iasim_move(tick: int, dx: int, dy: int) -> dict[str, Any]:
        """Queue a one-cell move in one of eight directions."""
        agent_id = _joined_agent(session)
        if agent_id is None:
            return _unauthorized(session)
        return session.move(agent_id, tick, dx, dy)

    @server.tool()
    def iasim_wait(tick: int) -> dict[str, Any]:
        """Queue a wait action for the current tick."""
        agent_id = _joined_agent(session)
        if agent_id is None:
            return _unauthorized(session)
        return session.wait(agent_id, tick)

    @server.tool()
    def iasim_wait_for_tick(since_tick: int, timeout_ms: int = 1000) -> dict[str, Any]:
        """Wait until a tick newer than since_tick is available."""
        agent_id = _joined_agent(session)
        if agent_id is None:
            return _unauthorized(session)
        return session.wait_for_tick(agent_id, since_tick, timeout_ms)

    @server.custom_route("/healthz", methods=["GET"])  # type: ignore[untyped-decorator]
    async def healthz(request: Request) -> Response:
        """Return a minimal unauthenticated health response."""
        return JSONResponse(session.health())

    return server


def _joined_agent(session: GameSession) -> AgentId | None:
    access = get_access_token()
    if access is None:
        return None
    return session.agent_for_token(access.token)


def _unauthorized(session: GameSession) -> dict[str, Any]:
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "tick": session.tick,
        "error": {
            "code": "UNAUTHORIZED",
            "message": "bearer token is not bound to a joined agent",
        },
    }


def create_app(
    session: GameSession,
    *,
    resource_url: str = DEFAULT_RESOURCE_URL,
    issuer_url: str = DEFAULT_ISSUER_URL,
) -> tuple[MCPServer[Any], Starlette]:
    """Create the MCP server and its streamable HTTP application."""
    server = create_server(session, resource_url=resource_url, issuer_url=issuer_url)
    return server, server.streamable_http_app()


def run_server(
    session: GameSession,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Run the streamable HTTP MCP server until stopped."""
    server = create_server(
        session,
        resource_url=f"http://{host}:{port}/mcp",
        issuer_url=f"http://{host}:{port}",
    )
    server.run("streamable-http", host=host, port=port)
