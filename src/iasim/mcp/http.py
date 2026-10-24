"""HTTP request handling shared by the MCP application.

The auth middleware may reject an unauthenticated request without reading its
body. Uvicorn then resets the client connection on some platforms instead of
delivering the 401 response, so this middleware buffers the body first and
replays it to the application. It also enforces the maximum request size.
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_REQUEST_BODY_BYTES = 1_000_000
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class BufferedRequestBodyMiddleware:
    """Buffer request bodies so rejection responses reach the client cleanly."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in _BODY_METHODS:
            await self._app(scope, receive, send)
            return

        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > MAX_REQUEST_BODY_BYTES:
                await _payload_too_large(send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self._app(scope, replay, send)


async def _payload_too_large(send: Send) -> None:
    payload = {
        "ok": False,
        "error": {
            "code": "PAYLOAD_TOO_LARGE",
            "message": f"request bodies are limited to {MAX_REQUEST_BODY_BYTES} bytes",
        },
    }
    body = json.dumps(payload).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class DevOpenAuthMiddleware:
    """Inject the first session token for loopback dev-open requests.

    This is an explicitly opt-in development convenience: it only exists when
    the operator passed ``--dev-open`` on a loopback host, and it always maps
    every unauthenticated request to slot 1, so multi-agent auth remains
    exercised through the normal bearer-token path.
    """

    def __init__(self, app: ASGIApp, *, token: str) -> None:
        self._app = app
        self._header = (b"authorization", f"Bearer {token}".encode("ascii"))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = list(scope.get("headers", ()))
            if not any(name.lower() == b"authorization" for name, _ in headers):
                scope = dict(scope)
                scope["headers"] = [*headers, self._header]
        await self._app(scope, receive, send)
