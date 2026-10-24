"""Tests for the request-id replay cache."""

from __future__ import annotations

import unittest

from iasim.mcp.idempotency import CachedResponse, RequestCache


def _result(tick: int) -> dict[str, object]:
    return {"ok": True, "tick": tick, "status": "queued"}


class RequestCacheTests(unittest.TestCase):
    def test_a_stored_response_is_replayed_verbatim(self) -> None:
        cache = RequestCache()
        signature = ("wait", 3)

        cache.store("ag_01", "req-1", signature, _result(3))
        cached = cache.lookup("ag_01", "req-1")

        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertEqual(cached.signature, signature)
        self.assertEqual(cached.result, _result(3))
        self.assertEqual(len(cache), 1)

    def test_the_cached_result_is_isolated_from_mutation(self) -> None:
        cache = RequestCache()
        result = _result(1)
        cache.store("ag_01", "req-1", ("wait", 1), result)
        result["status"] = "tampered"

        cached = cache.lookup("ag_01", "req-1")

        assert cached is not None
        self.assertEqual(cached.result["status"], "queued")

    def test_request_ids_are_scoped_per_agent(self) -> None:
        cache = RequestCache()
        cache.store("ag_01", "req-1", ("wait", 1), _result(1))

        self.assertIsNone(cache.lookup("ag_02", "req-1"))
        cache.store("ag_02", "req-1", ("move", 1, 1, 0), _result(1))
        self.assertEqual(len(cache), 2)

    def test_unknown_request_ids_return_none(self) -> None:
        cache = RequestCache()

        self.assertIsNone(cache.lookup("ag_01", "missing"))

    def test_a_cached_response_keeps_its_signature(self) -> None:
        cached = CachedResponse(("attack", 4, "ag_02"), _result(4))

        self.assertEqual(cached.signature, ("attack", 4, "ag_02"))
        self.assertEqual(cached.result["tick"], 4)


if __name__ == "__main__":
    unittest.main()
