"""Tests for agent-reported LLM usage accounting."""

from __future__ import annotations

import unittest

from iasim.app.session import GameSession
from iasim.domain.hashing import canonical_state_hash
from iasim.domain.usage import AgentUsage, CostSource, ModelPricing, UsageEntry


class UsageValueTests(unittest.TestCase):
    def test_model_pricing_estimates_cost_per_million_tokens(self) -> None:
        pricing = ModelPricing(
            input_per_million_usd=1.0,
            output_per_million_usd=2.0,
        )

        self.assertAlmostEqual(pricing.estimate(1_000_000, 500_000), 2.0)

    def test_unknown_cost_is_not_invented(self) -> None:
        usage = AgentUsage(entries=(UsageEntry(model="local", input_tokens=10, output_tokens=5),))

        self.assertIsNone(usage.cost_usd)
        self.assertFalse(usage.cost_complete)
        self.assertIs(usage.cost_source, CostSource.UNKNOWN)
        self.assertEqual(usage.total_tokens, 15)

    def test_invalid_pricing_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ModelPricing(input_per_million_usd=-1.0, output_per_million_usd=1.0)


class SessionUsageTests(unittest.TestCase):
    def _session(self) -> tuple[GameSession, str, str]:
        session = GameSession(42, max_agents=1)
        token = session.tokens[0]
        joined = session.join("Nia", token)
        return session, token, joined["agent_id"]

    def test_usage_accumulates_by_model_and_effort(self) -> None:
        session = GameSession(
            42,
            max_agents=1,
            usage_pricing={
                "gpt-5": ModelPricing(
                    input_per_million_usd=1.0,
                    output_per_million_usd=2.0,
                )
            },
        )
        token = session.tokens[0]
        agent_id = session.join("Nia", token)["agent_id"]
        before_hash = canonical_state_hash(session.state)

        first = session.report_usage(
            agent_id,
            0,
            input_tokens=100,
            output_tokens=50,
            model="gpt-5",
            reasoning_effort="high",
        )
        second = session.report_usage(
            agent_id,
            0,
            input_tokens=20,
            output_tokens=10,
            model="gpt-5",
            reasoning_effort="high",
            cost_usd=0.5,
        )
        third = session.report_usage(
            agent_id,
            0,
            input_tokens=1_000,
            output_tokens=200,
            model="local",
            reasoning_effort="low",
            cost_usd=1.25,
        )

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertTrue(third["ok"])
        usage = session.usage_for(agent_id)
        assert usage is not None
        self.assertEqual(usage.input_tokens, 1_120)
        self.assertEqual(usage.output_tokens, 260)
        self.assertEqual(usage.total_tokens, 1_380)
        self.assertAlmostEqual(usage.cost_usd or 0.0, 1.7502)
        self.assertTrue(usage.cost_complete)
        self.assertEqual(usage.cost_source, CostSource.MIXED)
        self.assertEqual([entry.model for entry in usage.entries], ["gpt-5", "local"])
        self.assertEqual(usage.latest.model if usage.latest else None, "local")
        self.assertEqual(canonical_state_hash(session.state), before_hash)
        self.assertEqual(session.tick, 0)

    def test_pricing_estimates_cost_when_agent_does_not_report_it(self) -> None:
        session = GameSession(
            42,
            max_agents=1,
            usage_pricing={
                "gpt-5": ModelPricing(
                    input_per_million_usd=1.0,
                    output_per_million_usd=2.0,
                )
            },
        )
        agent_id = session.join("Nia", session.tokens[0])["agent_id"]

        result = session.report_usage(
            agent_id,
            0,
            input_tokens=100,
            output_tokens=50,
            model="gpt-5",
        )

        self.assertTrue(result["ok"])
        usage = session.usage_for(agent_id)
        assert usage is not None
        self.assertAlmostEqual(usage.cost_usd or 0.0, 0.0002)
        self.assertTrue(usage.cost_complete)
        self.assertEqual(usage.cost_source, CostSource.ESTIMATED)

    def test_reported_cost_overrides_pricing(self) -> None:
        session = GameSession(
            42,
            max_agents=1,
            usage_pricing={
                "gpt-5": ModelPricing(
                    input_per_million_usd=100.0,
                    output_per_million_usd=100.0,
                )
            },
        )
        agent_id = session.join("Nia", session.tokens[0])["agent_id"]

        session.report_usage(
            agent_id,
            0,
            input_tokens=100,
            output_tokens=50,
            model="gpt-5",
            cost_usd=0.25,
        )

        usage = session.usage_for(agent_id)
        assert usage is not None
        self.assertAlmostEqual(usage.cost_usd or 0.0, 0.25)
        self.assertEqual(usage.cost_source, CostSource.REPORTED)

    def test_usage_is_discarded_when_the_agent_leaves(self) -> None:
        session, token, agent_id = self._session()
        session.report_usage(
            agent_id,
            0,
            input_tokens=10,
            output_tokens=5,
            model="gpt-5",
        )

        left = session.leave(agent_id)

        self.assertTrue(left["ok"])
        self.assertIsNone(session.usage_for(agent_id))
        rejoined = session.join("Nia", token)
        self.assertTrue(rejoined["ok"])
        self.assertEqual(rejoined["agent_id"], agent_id)
        usage = session.usage_for(agent_id)
        assert usage is not None
        self.assertEqual(usage.entries, ())

    def test_invalid_usage_is_rejected_without_accumulating(self) -> None:
        session, _, agent_id = self._session()

        base = {"input_tokens": 1, "output_tokens": 0, "model": "gpt-5"}
        cases = (
            ({"input_tokens": -1, "output_tokens": 0}, 0, "INVALID_USAGE"),
            ({"input_tokens": 0, "output_tokens": -1}, 0, "INVALID_USAGE"),
            ({"model": "  "}, 0, "INVALID_USAGE"),
            ({"cost_usd": -0.1}, 0, "INVALID_USAGE"),
            ({"reasoning_effort": "x" * 33}, 0, "INVALID_USAGE"),
            ({}, 1, "INVALID_TICK"),
        )
        for overrides, tick, code in cases:
            arguments = {**base, **overrides}
            with self.subTest(code=code, arguments=arguments):
                result = session.report_usage(agent_id, tick, **arguments)
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], code)

        usage = session.usage_for(agent_id)
        assert usage is not None
        self.assertEqual(usage.entries, ())

    def test_usage_snapshot_only_contains_reporting_agents(self) -> None:
        session = GameSession(42, max_agents=2)
        first = session.join("Nia", session.tokens[0])["agent_id"]
        second = session.join("Kai", session.tokens[1])["agent_id"]
        session.report_usage(
            first,
            0,
            input_tokens=10,
            output_tokens=5,
            model="gpt-5",
        )

        snapshot = session.usage_snapshot()

        self.assertEqual(set(snapshot), {first})
        self.assertNotIn(second, snapshot)


if __name__ == "__main__":
    unittest.main()
