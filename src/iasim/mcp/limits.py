"""Per-agent MCP rate limiting and text limits."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

INFO_RATE_PER_SECOND = 20.0
ACTION_RATE_PER_SECOND = 5.0
MAX_TEXT_FIELD_LENGTH = 280


class LimitKind(StrEnum):
    """Independent rate-limit classes."""

    INFO = "info"
    ACTION = "action"


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float


class RateLimiter:
    """Thread-safe per-agent token buckets with a monotonic clock."""

    def __init__(
        self,
        *,
        info_rate: float = INFO_RATE_PER_SECOND,
        action_rate: float = ACTION_RATE_PER_SECOND,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if info_rate <= 0 or action_rate <= 0:
            raise ValueError("rate limits must be positive")
        self._rates = {LimitKind.INFO: info_rate, LimitKind.ACTION: action_rate}
        self._clock = clock
        self._buckets: dict[tuple[str, LimitKind], _Bucket] = {}
        self._lock = threading.Lock()

    def allow(self, agent_id: str, kind: LimitKind) -> bool:
        """Consume one token for ``agent_id`` and ``kind`` when available."""
        if not isinstance(kind, LimitKind):
            raise ValueError(f"kind must be a LimitKind, got {kind!r}")
        rate = self._rates[kind]
        now = self._clock()
        key = (agent_id, kind)
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=rate, updated_at=now)
                self._buckets[key] = bucket
            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(rate, bucket.tokens + elapsed * rate)
            bucket.updated_at = now
            if bucket.tokens < 1.0:
                return False
            bucket.tokens -= 1.0
            return True
