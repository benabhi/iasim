"""Tests for the social event ledger and its metrics."""

from __future__ import annotations

import unittest

from iasim.app.session import GameSession
from iasim.app.social import (
    COUNTER_BY_KIND,
    SOCIAL_COUNTERS,
    SocialEventKind,
)
from iasim.crafting import load_catalog
from iasim.domain.agents import AgentProfile
from iasim.domain.alliances import alliance_id_for
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.items import Inventory, ItemStack
from iasim.domain.tiles import TileType, WorldMap
from iasim.world.layout import WorldLayout

CATALOG = load_catalog()
WOOD = "wood"
BERRY = "berry"


def _layout() -> WorldLayout:
    return WorldLayout(
        seed=1,
        world=WorldMap(width=8, height=8, tiles=(TileType.GRASS,) * 64),
        spawn_points=(Position(2, 2), Position(3, 2)),
    )


def _session(
    *,
    first_items: dict[str, int] | None = None,
    second_items: dict[str, int] | None = None,
) -> tuple[GameSession, str, str]:
    profiles = (
        AgentProfile(inventory=_inventory(first_items)),
        AgentProfile(inventory=_inventory(second_items)),
    )
    session = GameSession(1, layout=_layout(), profiles=profiles)
    return (
        session,
        session.join("Nia", session.tokens[0])["agent_id"],
        session.join("Kai", session.tokens[1])["agent_id"],
    )


def _inventory(items: dict[str, int] | None) -> Inventory:
    inventory = Inventory.for_strength(5)
    for item_id, quantity in (items or {}).items():
        inventory = inventory.add(ItemStack(CATALOG.item(item_id).definition, quantity))
    return inventory


def _count(snapshot: dict, counter: str) -> int:
    return int(snapshot["session"][counter])


def _agent_count(snapshot: dict, agent_id: str, counter: str) -> int:
    return int(snapshot["agents"][agent_id][counter])


def _events_of(session: GameSession, kind: SocialEventKind) -> list:
    return [event for event in session.social_events() if event.kind is kind]


class SocialLedgerBaselineTests(unittest.TestCase):
    def test_a_new_session_has_zeroed_counters(self) -> None:
        session, _, _ = _session()

        snapshot = session.social_metrics()

        self.assertEqual(set(snapshot["session"]), set(SOCIAL_COUNTERS))
        self.assertTrue(all(value == 0 for value in snapshot["session"].values()))
        self.assertEqual(snapshot["agents"], {})
        self.assertEqual(session.social_events(), ())


class MessageMetricTests(unittest.TestCase):
    def test_each_accepted_say_is_counted_once(self) -> None:
        session, first, second = _session()

        self.assertTrue(session.say(first, "Hola")["ok"])
        self.assertTrue(session.say(second, "Hey")["ok"])
        self.assertFalse(session.say(first, "Otra vez")["ok"])

        snapshot = session.social_metrics()
        self.assertEqual(_count(snapshot, "messages_sent"), 2)
        self.assertEqual(_agent_count(snapshot, first, "messages_sent"), 1)
        self.assertEqual(_agent_count(snapshot, second, "messages_sent"), 1)
        messages = _events_of(session, SocialEventKind.MESSAGE)
        self.assertEqual(len(messages), 2)
        self.assertIsNone(messages[0].target_id)

    def test_a_targeted_say_records_the_target(self) -> None:
        session, first, second = _session()

        self.assertTrue(session.say(first, "Solo para ti", target_id=second)["ok"])

        message = _events_of(session, SocialEventKind.MESSAGE)[0]
        self.assertEqual(message.target_id, second)

    def test_rejected_messages_are_not_counted(self) -> None:
        session, first, second = _session()

        self.assertFalse(session.say(first, "")["ok"])
        self.assertFalse(session.say(first, "x" * 281)["ok"])
        self.assertFalse(session.say(first, "hola", target_id="ag_09")["ok"])

        self.assertEqual(_count(session.social_metrics(), "messages_sent"), 0)
        self.assertEqual(session.social_events(), ())
        self.assertEqual(second, "ag_02")


class AllianceMetricTests(unittest.TestCase):
    def test_offer_accept_and_break_are_counted(self) -> None:
        session, first, second = _session()
        alliance_id = alliance_id_for(AgentId(first), AgentId(second))

        self.assertTrue(session.offer_alliance(first, 0, second)["ok"])
        self.assertTrue(session.wait(second, 0)["ok"])
        self.assertTrue(session.accept_alliance(second, 1, alliance_id)["ok"])
        self.assertTrue(session.wait(first, 1)["ok"])
        self.assertTrue(session.break_alliance(first, 2, second)["ok"])
        self.assertTrue(session.wait(second, 2)["ok"])

        snapshot = session.social_metrics()
        self.assertEqual(_count(snapshot, "alliances_offered"), 1)
        self.assertEqual(_count(snapshot, "alliances_formed"), 1)
        self.assertEqual(_count(snapshot, "alliances_broken"), 1)
        offered = _events_of(session, SocialEventKind.ALLIANCE_OFFERED)[0]
        self.assertEqual(offered.target_id, second)

    def test_withdrawn_and_declined_offers_are_counted(self) -> None:
        session, first, second = _session()

        self.assertTrue(session.offer_alliance(first, 0, second)["ok"])
        self.assertTrue(session.wait(second, 0)["ok"])
        self.assertTrue(session.break_alliance(first, 1, second)["ok"])
        self.assertTrue(session.wait(second, 1)["ok"])
        self.assertTrue(session.offer_alliance(first, 2, second)["ok"])
        self.assertTrue(session.wait(second, 2)["ok"])
        self.assertTrue(session.break_alliance(second, 3, first)["ok"])
        self.assertTrue(session.wait(first, 3)["ok"])

        snapshot = session.social_metrics()
        self.assertEqual(_count(snapshot, "alliances_offered"), 2)
        self.assertEqual(_count(snapshot, "alliances_withdrawn"), 1)
        self.assertEqual(_count(snapshot, "alliances_declined"), 1)
        self.assertEqual(_count(snapshot, "alliances_formed"), 0)
        self.assertEqual(_count(snapshot, "alliances_broken"), 0)


class TradeMetricTests(unittest.TestCase):
    def _trading_session(self) -> tuple[GameSession, str, str]:
        return _session(first_items={WOOD: 1}, second_items={BERRY: 1})

    def test_offers_and_completed_trades_are_counted(self) -> None:
        session, first, second = self._trading_session()

        self.assertTrue(
            session.offer_trade(
                first,
                0,
                second,
                [{"item_id": WOOD, "qty": 1}],
                [{"item_id": BERRY, "qty": 1}],
            )["ok"]
        )
        self.assertTrue(session.wait(second, 0)["ok"])
        trade_id = session.observe(second)["social"]["trades"][0]["trade_id"]
        self.assertTrue(session.accept_trade(second, 1, trade_id)["ok"])
        self.assertTrue(session.wait(first, 1)["ok"])

        snapshot = session.social_metrics()
        self.assertEqual(_count(snapshot, "trades_offered"), 1)
        self.assertEqual(_count(snapshot, "trades_completed"), 1)
        self.assertEqual(_count(snapshot, "trades_declined"), 0)

    def test_declined_trades_are_counted(self) -> None:
        session, first, second = self._trading_session()

        self.assertTrue(
            session.offer_trade(
                first,
                0,
                second,
                [{"item_id": WOOD, "qty": 1}],
                [{"item_id": BERRY, "qty": 1}],
            )["ok"]
        )
        self.assertTrue(session.wait(second, 0)["ok"])
        trade_id = session.observe(second)["social"]["trades"][0]["trade_id"]
        self.assertTrue(session.decline_trade(second, 1, trade_id)["ok"])
        self.assertTrue(session.wait(first, 1)["ok"])

        snapshot = session.social_metrics()
        self.assertEqual(_count(snapshot, "trades_offered"), 1)
        self.assertEqual(_count(snapshot, "trades_declined"), 1)
        self.assertEqual(_count(snapshot, "trades_completed"), 0)


class BetrayalMetricTests(unittest.TestCase):
    def _allied_session(self) -> tuple[GameSession, str, str]:
        session, first, second = _session()
        alliance_id = alliance_id_for(AgentId(first), AgentId(second))
        self.assertTrue(session.offer_alliance(first, 0, second)["ok"])
        self.assertTrue(session.wait(second, 0)["ok"])
        self.assertTrue(session.accept_alliance(second, 1, alliance_id)["ok"])
        self.assertTrue(session.wait(first, 1)["ok"])
        return session, first, second

    def test_attacking_an_ally_is_counted_as_a_betrayal(self) -> None:
        session, first, second = self._allied_session()

        self.assertTrue(session.attack(first, 2, second)["ok"])
        self.assertTrue(session.wait(second, 2)["ok"])
        self.assertTrue(session.attack(first, 3, second)["ok"])
        self.assertTrue(session.wait(second, 3)["ok"])

        snapshot = session.social_metrics()
        self.assertEqual(_count(snapshot, "betrayals"), 2)
        self.assertEqual(_agent_count(snapshot, first, "betrayals"), 2)
        betrayals = _events_of(session, SocialEventKind.BETRAYAL)
        self.assertEqual([event.target_id for event in betrayals], [second, second])

    def test_attacking_a_non_ally_is_not_a_betrayal(self) -> None:
        session, first, second = _session()

        self.assertTrue(session.attack(first, 0, second)["ok"])
        self.assertTrue(session.wait(second, 0)["ok"])

        self.assertEqual(_count(session.social_metrics(), "betrayals"), 0)


class LedgerConsistencyTests(unittest.TestCase):
    def _mixed_session(self) -> tuple[GameSession, str, str]:
        session, first, second = _session(first_items={WOOD: 1}, second_items={BERRY: 1})
        self.assertTrue(session.say(first, "Hola")["ok"])
        self.assertTrue(session.say(second, "Hey")["ok"])
        self.assertTrue(session.offer_alliance(first, 0, second)["ok"])
        self.assertTrue(session.wait(second, 0)["ok"])
        alliance_id = alliance_id_for(AgentId(first), AgentId(second))
        self.assertTrue(session.accept_alliance(second, 1, alliance_id)["ok"])
        self.assertTrue(session.wait(first, 1)["ok"])
        self.assertTrue(session.attack(first, 2, second)["ok"])
        self.assertTrue(session.wait(second, 2)["ok"])
        return session, first, second

    def test_counters_match_the_emitted_events(self) -> None:
        session, _, _ = self._mixed_session()

        snapshot = session.social_metrics()
        counts_by_kind = {kind: len(_events_of(session, kind)) for kind in SocialEventKind}

        for kind, counter in COUNTER_BY_KIND.items():
            with self.subTest(kind=kind.value):
                self.assertEqual(_count(snapshot, counter), counts_by_kind[kind])

    def test_session_totals_are_the_sum_of_the_agents(self) -> None:
        session, first, second = self._mixed_session()

        snapshot = session.social_metrics()

        for counter in SOCIAL_COUNTERS:
            with self.subTest(counter=counter):
                self.assertEqual(
                    _count(snapshot, counter),
                    _agent_count(snapshot, first, counter)
                    + _agent_count(snapshot, second, counter),
                )

    def test_an_agent_that_leaves_keeps_its_counters(self) -> None:
        session, first, _ = _session()
        self.assertTrue(session.say(first, "Adiós")["ok"])

        self.assertTrue(session.leave(first)["ok"])

        snapshot = session.social_metrics()
        self.assertEqual(_agent_count(snapshot, first, "messages_sent"), 1)
        self.assertEqual(_count(snapshot, "messages_sent"), 1)

    def test_restarting_the_session_resets_the_ledger(self) -> None:
        session, first, _ = _session()
        self.assertTrue(session.say(first, "Hola")["ok"])
        self.assertEqual(_count(session.social_metrics(), "messages_sent"), 1)
        session.finish()

        restarted = session.restart(seed=2)

        self.assertTrue(all(value == 0 for value in restarted.social_metrics()["session"].values()))
        self.assertEqual(restarted.social_events(), ())

    def test_the_same_sequence_yields_the_same_ledger(self) -> None:
        first_session, _, _ = self._mixed_session()
        second_session, _, _ = self._mixed_session()

        self.assertEqual(
            first_session.social_metrics(),
            second_session.social_metrics(),
        )
        self.assertEqual(
            [event.as_dict() for event in first_session.social_events()],
            [event.as_dict() for event in second_session.social_events()],
        )


if __name__ == "__main__":
    unittest.main()
