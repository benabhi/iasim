"""Tests for the HTTP body buffering middleware."""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

from iasim.mcp.http import MAX_REQUEST_BODY_BYTES, BufferedRequestBodyMiddleware


def _scope(*, method: str = "POST") -> dict[str, Any]:
    return {
        "type": "http",
        "method": method,
        "path": "/mcp",
        "headers": [],
    }


class _Recorder:
    """ASGI app that records the received body and sends a 200 response."""

    def __init__(self) -> None:
        self.body = b""

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        chunks: list[bytes] = []
        while True:
            message = await receive()
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        self.body = b"".join(chunks)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


class _CapturingSend:
    def __init__(self) -> None:
        self.status: int | None = None
        self.body = b""

    async def __call__(self, message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]
        elif message["type"] == "http.response.body":
            self.body += message.get("body", b"")


class _ChunkedReceive:
    def __init__(self, chunks: list[bytes]) -> None:
        self._pending = list(chunks)

    async def __call__(self) -> dict[str, Any]:
        if self._pending:
            chunk = self._pending.pop(0)
            return {
                "type": "http.request",
                "body": chunk,
                "more_body": bool(self._pending),
            }
        return {"type": "http.disconnect"}


class _EmptyReceive:
    async def __call__(self) -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}


class BufferedRequestBodyMiddlewareTests(unittest.TestCase):
    def test_the_body_is_replayed_to_the_application(self) -> None:
        app = _Recorder()
        middleware = BufferedRequestBodyMiddleware(app)
        send = _CapturingSend()

        asyncio.run(
            middleware(
                _scope(),
                _ChunkedReceive([b'{"jsonrpc":', b'"2.0"}']),
                send,
            )
        )

        self.assertEqual(app.body, b'{"jsonrpc":"2.0"}')
        self.assertEqual(send.status, 200)

    def test_an_empty_body_is_forwarded(self) -> None:
        app = _Recorder()
        middleware = BufferedRequestBodyMiddleware(app)
        send = _CapturingSend()

        asyncio.run(middleware(_scope(method="DELETE"), _EmptyReceive(), send))

        self.assertEqual(app.body, b"")
        self.assertEqual(send.status, 200)

    def test_an_oversized_body_is_rejected_with_413(self) -> None:
        app = _Recorder()
        middleware = BufferedRequestBodyMiddleware(app)
        send = _CapturingSend()

        asyncio.run(
            middleware(
                _scope(),
                _ChunkedReceive([b"x" * (MAX_REQUEST_BODY_BYTES + 1)]),
                send,
            )
        )

        self.assertEqual(send.status, 413)
        payload = json.loads(send.body)
        self.assertEqual(payload["error"]["code"], "PAYLOAD_TOO_LARGE")
        self.assertEqual(app.body, b"")

    def test_get_requests_are_not_buffered(self) -> None:
        app = _Recorder()
        middleware = BufferedRequestBodyMiddleware(app)
        send = _CapturingSend()

        asyncio.run(middleware(_scope(method="GET"), _EmptyReceive(), send))

        self.assertEqual(app.body, b"")


if __name__ == "__main__":
    unittest.main()
