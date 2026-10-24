"""Tests for the aggregated per-agent and per-session metrics."""

from __future__ import annotations

import unittest

from iasim.app.session import GameSession
from iasim.crafting import load_catalog
from iasim.domain.agents import AgentAttributes, AgentProfile
from iasim.domain.alliances import alliance_id_for
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.items import Inventory, ItemStack
from iasim.domain.tiles import TileType, WorldMap
from iasim.world.layout import WorldLayout

CATALOG = load_catalog()

DOCUMENTED_METRICS = {
    "survival_ticks",
    "days_survived",
    "cause_of_death",
    "killed_by",
    "avg_hunger",
    "avg_thirst",
    "avg_energy",
    "critical_need_ratio",
    "exploration_pct",
    "distance_traveled",
    "resources_gathered",
    "items_crafted",
    "structures_built",
    "actions_total",
    "actions_failed",
    "invalid_action_rate",
    "timeouts",
    "messages_sent",
    "trades_offered",
    "trades_completed",
    "alliances_formed",
    "betrayals",
    "attacks_made",
    "damage_dealt",
    "damage_taken",
    "kills",
    "mind_reports",
    "mind_report_rate",
    "decision_latency_p50_ms",
    "decision_latency_p95_ms",
}


def _layout() -> WorldLayout:
    tiles = [TileType.GRASS] * 36
    tiles[3 * 6 + 2] = TileType.TREE
    return WorldLayout(
        seed=2,
        world=WorldMap(width=6, height=6, tiles=tuple(tiles)),
        spawn_points=(Position(2, 2), Position(3, 2)),
    )


def _session(
    *,
    profiles: tuple[AgentProfile, AgentProfile] | None = None,
    wall_clock=None,
    turn_timeout_ms: int = 60_000,
    timeout_disconnects: int = 3,
) -> tuple[GameSession, str, str]:
    kwargs = {}
    if wall_clock is not None:
        kwargs["wall_clock"] = wall_clock
    session = GameSession(
        2,
        layout=_layout(),
        profiles=profiles,
        turn_timeout_ms=turn_timeout_ms,
        timeout_disconnects=timeout_disconnects,
        **kwargs,
    )
    return (
        session,
        session.join("Nia", session.tokens[0])["agent_id"],
        session.join("Kai", session.tokens[1])["agent_id"],
    )


class MetricShapeTests(unittest.TestCase):
    def test_every_documented_metric_is_present(self) -> None:
        session, first, _ = _session()

        snapshot = session.metrics_snapshot()

        self.assertTrue(set(snapshot["session"]) >= DOCUMENTED_METRICS)
        self.assertIn("final_state_hash", snapshot["session"])
        self.assertTrue(set(snapshot["agents"][first]) >= DOCUMENTED_METRICS)
        self.assertEqual(snapshot["schema_version"], "1.0")
        self.assertEqual(snapshot["final_state_hash"], session.state_hash)


class KnownFixtureTests(unittest.TestCase):
    def test_counters_match_a_known_sequence(self) -> None:
        session, first, second = _session()

        session.observe(first)
        self.assertTrue(session.say(first, "Hola")["ok"])
        self.assertTrue(
            session.report_mind(first, 0, intent="Buscar", thought="Quiero madera")["ok"]
        )
        self.assertTrue(session.gather(first, 0, 2, 3)["ok"])
        self.assertTrue(session.wait(second, 0)["ok"])
        self.assertTrue(session.wait(first, 1)["ok"])
        self.assertTrue(session.wait(second, 1)["ok"])

        snapshot = session.metrics_snapshot()
        agent = snapshot["agents"][first]
        other = snapshot["agents"][second]
        totals = snapshot["session"]

        self.assertEqual(agent["survival_ticks"], 2)
        self.assertEqual(agent["alive_ticks"], 2)
        self.assertEqual(agent["actions_total"], 2)
        self.assertEqual(agent["actions_failed"], 0)
        self.assertEqual(agent["invalid_action_rate"], 0.0)
        self.assertEqual(agent["resources_gathered"], {"wood": 1})
        self.assertEqual(agent["messages_sent"], 1)
        self.assertEqual(agent["mind_reports"], 1)
        self.assertEqual(agent["mind_report_rate"], 0.5)
        self.assertEqual(agent["decision_latency_samples"], 1)
        self.assertIsNotNone(agent["decision_latency_p50_ms"])
        self.assertGreater(agent["explored_cells"], 0)
        self.assertLess(agent["explored_cells"], 35)
        self.assertEqual(agent["transitable_cells"], 35)
        self.assertEqual(other["messages_sent"], 0)
        self.assertEqual(other["actions_total"], 2)
        self.assertEqual(totals["agent_count"], 2)
        self.assertEqual(totals["survival_ticks"], 4)
        self.assertEqual(totals["days_survived"], round(4 / 288, 4))
        self.assertEqual(totals["actions_total"], 4)
        self.assertEqual(totals["messages_sent"], 1)
        self.assertEqual(totals["mind_reports"], 1)
        self.assertEqual(totals["resources_gathered"], {"wood": 1})
        self.assertEqual(totals["invalid_action_rate"], 0.0)

    def test_a_rejected_action_counts_as_failed(self) -> None:
        session, first, second = _session()
        session.wait(first, 0)
        session.wait(second, 0)
        self.assertFalse(session.wait(first, 0)["ok"])

        snapshot = session.metrics_snapshot()
        agent = snapshot["agents"][first]

        self.assertEqual(agent["actions_total"], 2)
        self.assertEqual(agent["actions_failed"], 1)
        self.assertEqual(agent["invalid_action_rate"], 0.5)
        self.assertEqual(snapshot["session"]["actions_total"], 3)
        self.assertEqual(snapshot["session"]["actions_failed"], 1)

    def test_deaths_and_damage_are_attributed(self) -> None:
        profiles = (
            AgentProfile(),
            AgentProfile(attributes=AgentAttributes(health_centi=100)),
        )
        session, first, second = _session(profiles=profiles)

        self.assertTrue(session.attack(first, 0, second)["ok"])
        self.assertTrue(session.wait(second, 0)["ok"])

        snapshot = session.metrics_snapshot()
        killer = snapshot["agents"][first]
        victim = snapshot["agents"][second]

        self.assertEqual(killer["attacks_made"], 1)
        self.assertEqual(killer["kills"], 1)
        self.assertGreater(killer["damage_dealt"], 0)
        self.assertEqual(victim["cause_of_death"], "attack")
        self.assertEqual(victim["killed_by"], first)
        self.assertEqual(victim["survival_ticks"], 0)
        self.assertGreater(victim["damage_taken"], 0)
        self.assertEqual(snapshot["session"]["kills"], 1)
        self.assertEqual(snapshot["session"]["attacks_made"], 1)

    def test_timeouts_are_counted_per_agent_and_session(self) -> None:
        clock = [0.0]
        session, first, second = _session(
            wall_clock=lambda: clock[0],
            turn_timeout_ms=1_000,
        )
        for tick in range(2):
            session.wait(first, tick)
            clock[0] += 2.0
            session.observe(first)

        snapshot = session.metrics_snapshot()

        self.assertEqual(snapshot["agents"][second]["timeouts"], 2)
        self.assertEqual(snapshot["session"]["timeouts"], 2)
        self.assertEqual(snapshot["agents"][first]["timeouts"], 0)
        self.assertEqual(snapshot["agents"][second]["survival_ticks"], 2)

    def test_social_counters_come_from_the_ledger(self) -> None:
        profiles = (
            AgentProfile(inventory=_inventory(wood=1)),
            AgentProfile(inventory=_inventory(berry=1)),
        )
        session, first, second = _session(profiles=profiles)
        self.assertTrue(
            session.offer_trade(
                first,
                0,
                second,
                [{"item_id": "wood", "qty": 1}],
                [{"item_id": "berry", "qty": 1}],
            )["ok"]
        )
        self.assertTrue(session.wait(second, 0)["ok"])
        trade_id = session.observe(second)["social"]["trades"][0]["trade_id"]
        self.assertTrue(session.accept_trade(second, 1, trade_id)["ok"])
        self.assertTrue(session.wait(first, 1)["ok"])
        alliance_id = alliance_id_for(AgentId(first), AgentId(second))
        self.assertTrue(session.offer_alliance(first, 2, second)["ok"])
        self.assertTrue(session.wait(second, 2)["ok"])
        self.assertTrue(session.accept_alliance(second, 3, alliance_id)["ok"])
        self.assertTrue(session.wait(first, 3)["ok"])

        snapshot = session.metrics_snapshot()

        self.assertEqual(snapshot["agents"][first]["trades_offered"], 1)
        self.assertEqual(snapshot["agents"][second]["trades_completed"], 1)
        self.assertEqual(snapshot["agents"][second]["alliances_formed"], 1)
        self.assertEqual(snapshot["session"]["trades_offered"], 1)
        self.assertEqual(snapshot["session"]["trades_completed"], 1)
        self.assertEqual(snapshot["session"]["alliances_formed"], 1)
        self.assertEqual(snapshot["session"]["betrayals"], 0)


def _inventory(**items: int) -> Inventory:
    inventory = Inventory.for_strength(5)
    for item_id, quantity in items.items():
        inventory = inventory.add(ItemStack(CATALOG.item(item_id).definition, quantity))
    return inventory


if __name__ == "__main__":
    unittest.main()
