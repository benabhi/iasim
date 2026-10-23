"""Tests for deterministic per-agent MCP rate and text limits."""

from __future__ import annotations

import unittest

from iasim.app.session import GameSession
from iasim.mcp.limits import (
    ACTION_RATE_PER_SECOND,
    INFO_RATE_PER_SECOND,
    MAX_TEXT_FIELD_LENGTH,
    LimitKind,
    RateLimiter,
)
from iasim.mcp.server import _message_too_long, _rate_limited, _text_too_long


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RateLimiterTests(unittest.TestCase):
    def test_action_bucket_allows_five_immediate_calls_then_refills(self) -> None:
        clock = _Clock()
        limiter = RateLimiter(clock=clock)

        for _ in range(5):
            self.assertTrue(limiter.allow("ag_01", LimitKind.ACTION))
        self.assertFalse(limiter.allow("ag_01", LimitKind.ACTION))

        clock.advance(1.0 / ACTION_RATE_PER_SECOND)
        self.assertTrue(limiter.allow("ag_01", LimitKind.ACTION))
        self.assertFalse(limiter.allow("ag_01", LimitKind.ACTION))

    def test_info_and_action_buckets_are_independent(self) -> None:
        clock = _Clock()
        limiter = RateLimiter(clock=clock)

        for _ in range(int(INFO_RATE_PER_SECOND)):
            self.assertTrue(limiter.allow("ag_01", LimitKind.INFO))
        self.assertFalse(limiter.allow("ag_01", LimitKind.INFO))
        self.assertTrue(limiter.allow("ag_01", LimitKind.ACTION))

    def test_agents_do_not_share_buckets(self) -> None:
        limiter = RateLimiter(clock=_Clock())

        for _ in range(5):
            self.assertTrue(limiter.allow("ag_01", LimitKind.ACTION))

        self.assertFalse(limiter.allow("ag_01", LimitKind.ACTION))
        self.assertTrue(limiter.allow("ag_02", LimitKind.ACTION))

    def test_invalid_configuration_and_kind_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RateLimiter(info_rate=0)
        with self.assertRaises(ValueError):
            RateLimiter(action_rate=-1)
        with self.assertRaises(ValueError):
            RateLimiter().allow("ag_01", "info")  # type: ignore[arg-type]


class TextLimitTests(unittest.TestCase):
    def test_text_limit_accepts_boundary_and_rejects_oversized_values(self) -> None:
        self.assertFalse(_text_too_long(None))
        self.assertFalse(_text_too_long("x" * MAX_TEXT_FIELD_LENGTH))
        self.assertTrue(_text_too_long("x" * (MAX_TEXT_FIELD_LENGTH + 1)))
        self.assertTrue(_text_too_long(None, "ok", "x" * (MAX_TEXT_FIELD_LENGTH + 1)))

    def test_structured_limit_errors_have_stable_codes(self) -> None:
        session = GameSession(42, max_agents=1)

        rate_error = _rate_limited(session, LimitKind.INFO)
        text_error = _message_too_long(session)

        self.assertFalse(rate_error["ok"])
        self.assertEqual(rate_error["error"]["code"], "RATE_LIMITED")
        self.assertEqual(rate_error["tick"], 0)
        self.assertFalse(text_error["ok"])
        self.assertEqual(text_error["error"]["code"], "MESSAGE_TOO_LONG")
        self.assertEqual(text_error["tick"], 0)


if __name__ == "__main__":
    unittest.main()
