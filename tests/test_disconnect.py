"""Tests for transport-termination handling."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from iasim.app.session import GameSession
from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType, WorldMap
from iasim.mcp.disconnect import TerminateSessionMiddleware
from iasim.world.layout import WorldLayout


def _layout() -> WorldLayout:
    return WorldLayout(
        seed=42,
        world=WorldMap(width=5, height=5, tiles=(TileType.GRASS,) * 25),
        spawn_points=(Position(2, 2),),
    )


def _scope(*, method: str, token: str | None = None) -> dict[str, Any]:
    headers: list[tuple[bytes, bytes]] = []
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode("latin-1")))
    return {
        "type": "http",
        "method": method,
        "path": "/mcp",
        "headers": headers,
    }


class _DisconnectedReceive:
    """ASGI receive callable that reports a client disconnect."""

    async def __call__(self) -> dict[str, Any]:
        return {"type": "http.disconnect"}


class _KeepAliveReceive:
    """ASGI receive callable that reports a completed request body."""

    async def __call__(self) -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}


async def _send(message: dict[str, Any]) -> None:
    return None


async def _wait_for_body(scope: Any, receive: Any, send: Any) -> None:
    await receive()


class TerminateSessionMiddlewareTests(unittest.TestCase):
    def _session(self) -> tuple[GameSession, str]:
        session = GameSession(42, layout=_layout())
        token = session.tokens[0]
        self.assertTrue(session.join("Nia", token)["ok"])
        return session, token

    def _run(self, session: GameSession, scope: dict[str, Any], receive: Any) -> None:
        middleware = TerminateSessionMiddleware(_wait_for_body, session)
        asyncio.run(middleware(scope, receive, _send))

    def test_a_delete_removes_the_agent_and_frees_the_slot(self) -> None:
        session, token = self._session()

        self._run(session, _scope(method="DELETE", token=token), _DisconnectedReceive())

        self.assertEqual(session.state.agents, ())
        self.assertIsNone(session.agent_for_token(token))
        self.assertTrue(session.join("Kai", token)["ok"])

    def test_a_request_without_a_token_is_ignored(self) -> None:
        session, token = self._session()

        self._run(session, _scope(method="DELETE"), _DisconnectedReceive())

        self.assertEqual(len(session.state.agents), 1)
        self.assertEqual(session.agent_for_token(token), "ag_01")

    def test_a_normal_request_keeps_the_agent(self) -> None:
        session, token = self._session()

        self._run(session, _scope(method="POST", token=token), _KeepAliveReceive())

        self.assertEqual(len(session.state.agents), 1)
        self.assertEqual(session.agent_for_token(token), "ag_01")

    def test_a_non_http_scope_is_forwarded_untouched(self) -> None:
        session, token = self._session()

        self._run(session, {"type": "lifespan"}, _KeepAliveReceive())

        self.assertEqual(len(session.state.agents), 1)
        self.assertEqual(session.agent_for_token(token), "ag_01")


if __name__ == "__main__":
    unittest.main()
