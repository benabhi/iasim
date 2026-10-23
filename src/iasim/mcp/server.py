"""Minimal MCP server exposing the IASim session."""

from __future__ import annotations

import socket
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
from iasim.config import is_loopback_host
from iasim.domain.identifiers import AgentId

DEFAULT_RESOURCE_URL = "http://127.0.0.1:8765/mcp"
DEFAULT_ISSUER_URL = "http://127.0.0.1:8765"
AUTH_SCOPE = "iasim:agent"
LAN_WARNING = (
    "MCP is exposed beyond loopback over plaintext HTTP. "
    "Use bearer tokens only on a trusted LAN; use a VPN or tunnel for untrusted networks."
)


def server_connection_info(host: str, port: int) -> dict[str, Any]:
    """Return advertised endpoints and a LAN exposure warning for ``host``/``port``."""
    advertised_host = _advertised_host(host)
    mcp_url = f"http://{advertised_host}:{port}/mcp"
    issuer_url = f"http://{advertised_host}:{port}"
    loopback = is_loopback_host(host)
    return {
        "host": host,
        "port": port,
        "advertised_host": advertised_host,
        "mcp_url": mcp_url,
        "issuer_url": issuer_url,
        "loopback": loopback,
        "warning": None if loopback else LAN_WARNING,
    }


def _advertised_host(host: str) -> str:
    normalized = host.strip()
    if normalized in {"0.0.0.0", "::"}:
        return _local_ipv4() or "127.0.0.1"
    return normalized or "127.0.0.1"


def _local_ipv4() -> str | None:
    try:
        addresses = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return None
    for info in addresses:
        address = str(info[4][0])
        if not is_loopback_host(address):
            return address
    return None


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
    def iasim_gather(tick: int, x: int, y: int) -> dict[str, Any]:
        """Gather a resource from an adjacent tile."""
        agent_id = _joined_agent(session)
        if agent_id is None:
            return _unauthorized(session)
        return session.gather(agent_id, tick, x, y)

    @server.tool()
    def iasim_pickup(
        tick: int,
        x: int,
        y: int,
        item_id: str | None = None,
    ) -> dict[str, Any]:
        """Pick up a ground item from the current or an adjacent tile."""
        agent_id = _joined_agent(session)
        if agent_id is None:
            return _unauthorized(session)
        return session.pickup(agent_id, tick, x, y, item_id)

    @server.tool()
    def iasim_drop(tick: int, item_id: str, qty: int = 1) -> dict[str, Any]:
        """Drop one or more units of an inventory item."""
        agent_id = _joined_agent(session)
        if agent_id is None:
            return _unauthorized(session)
        return session.drop(agent_id, tick, item_id, qty)

    @server.tool()
    def iasim_eat(tick: int, item_id: str) -> dict[str, Any]:
        """Eat one unit of food from the inventory."""
        agent_id = _joined_agent(session)
        if agent_id is None:
            return _unauthorized(session)
        return session.eat(agent_id, tick, item_id)

    @server.tool()
    def iasim_drink(
        tick: int,
        x: int | None = None,
        y: int | None = None,
        item_id: str | None = None,
    ) -> dict[str, Any]:
        """Drink from an adjacent fresh-water tile or from a waterskin."""
        agent_id = _joined_agent(session)
        if agent_id is None:
            return _unauthorized(session)
        return session.drink(agent_id, tick, x=x, y=y, item_id=item_id)

    @server.tool()
    def iasim_fill(tick: int, item_id: str) -> dict[str, Any]:
        """Fill a waterskin from adjacent fresh water."""
        agent_id = _joined_agent(session)
        if agent_id is None:
            return _unauthorized(session)
        return session.fill(agent_id, tick, item_id)

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
    connection = server_connection_info(host, port)
    print(f"MCP endpoint: {connection['mcp_url']}")
    if connection["warning"] is not None:
        print(f"warning: {connection['warning']}")
    server = create_server(
        session,
        resource_url=str(connection["mcp_url"]),
        issuer_url=str(connection["issuer_url"]),
    )
    server.run("streamable-http", host=host, port=port)
