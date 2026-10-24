"""Request-id replay cache for the one-primary-action turn queue.

A request id identifies one attempted action by one agent. Repeating the same
call must never queue a second action, so the first successful response is
replayed verbatim; reusing the id for a different action is rejected instead of
silently acting twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any

MAX_REQUEST_ID_LENGTH = 64

RequestSignature = tuple[object, ...]


@dataclass(frozen=True, slots=True)
class CachedResponse:
    """One successful action response kept for idempotent replay."""

    signature: RequestSignature
    result: dict[str, Any]


class RequestConflictError(Exception):
    """A request id was reused for a different action."""


class RequestCache:
    """Per-agent replay cache scoped to one session server."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], CachedResponse] = {}
        self._lock = Lock()

    def lookup(self, agent_id: str, request_id: str) -> CachedResponse | None:
        """Return the cached response for a request id, if any."""
        with self._lock:
            return self._entries.get((agent_id, request_id))

    def store(
        self,
        agent_id: str,
        request_id: str,
        signature: RequestSignature,
        result: dict[str, Any],
    ) -> None:
        """Remember one successful action response."""
        with self._lock:
            self._entries[(agent_id, request_id)] = CachedResponse(signature, dict(result))

    def __len__(self) -> int:
        """Return how many request ids are cached."""
        with self._lock:
            return len(self._entries)
