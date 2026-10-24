"""Release an agent when its MCP transport session terminates.

A streamable HTTP client closes its session with an authenticated ``DELETE``
request. The middleware observes that request before the MCP application
handles it, so the agent leaves the world, its pending action is cancelled, and
the slot and token become reusable by a new connection.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from iasim.app.session import GameSession

DELETED_METHOD = "DELETE"


class TerminateSessionMiddleware:
    """Call the session leave operation when a client deletes its MCP session."""

    def __init__(self, app: ASGIApp, session: GameSession) -> None:
        self._app = app
        self._session = session

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == DELETED_METHOD:
            self._release(scope)
        await self._app(scope, receive, send)

    def _release(self, scope: Scope) -> None:
        """Remove the agent bound to the request bearer token, if any."""
        authorization = ""
        for key, value in scope.get("headers", []):
            if key.lower() == b"authorization":
                authorization = value.decode("latin-1")
                break
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return
        agent_id = self._session.agent_for_token(token)
        if agent_id is not None:
            self._session.leave(str(agent_id), cause="transport_closed")
