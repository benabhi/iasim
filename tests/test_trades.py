"""Tests for atomic item trades, expiry, and range rules."""

from __future__ import annotations

import unittest

from iasim.app.session import GameSession
from iasim.crafting import load_catalog
from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent, AgentAttributes, AgentProfile, AgentStatus
from iasim.domain.geometry import Position
from iasim.domain.hashing import canonical_state_hash
from iasim.domain.identifiers import AgentId, ItemId
from iasim.domain.items import Inventory, ItemStack
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.trade_actions import TradeOutcome, trade_resolvers
from iasim.domain.trades import (
    TRADE_RANGE,
    TRADE_TTL_TICKS,
    TradeOffer,
    TradeStatus,
    expire_trades,
    find_trade,
    open_trades,
    parse_lot,
    trade_id_for,
)
from iasim.domain.turns import TurnEngine, TurnEvent
from iasim.world.layout import WorldLayout

WOOD = "wood"
BERRY = "berry"
STONE = "stone"


def _definition(item_id: str):
    return load_catalog().item(item_id).definition


def _inventory(**items: int) -> Inventory:
    inventory = Inventory.for_strength(5)
    for item_id, quantity in items.items():
        inventory = inventory.add(ItemStack(_definition(item_id), quantity))
    return inventory


def _agent(
    agent_id: str,
    position: Position,
    *,
    inventory: Inventory | None = None,
    health_centi: int = 100 * 100,
) -> Agent:
    dead = health_centi == 0
    return Agent(
        AgentId(agent_id),
        position,
        attributes=AgentAttributes(health_centi=health_centi),
        inventory=inventory if inventory is not None else Inventory.for_strength(5),
        status=AgentStatus.DEAD if dead else AgentStatus.ACTIVE,
    )


def _lot(**items: int) -> tuple[tuple[ItemId, int], ...]:
    return tuple(sorted((ItemId(item_id), quantity) for item_id, quantity in items.items()))


def _propose(
    *,
    offered_tick: int = 0,
    offer: tuple[tuple[ItemId, int], ...] | None = None,
    request: tuple[tuple[ItemId, int], ...] | None = None,
) -> TradeOffer:
    return TradeOffer.propose(
        AgentId("ag_01"),
        AgentId("ag_02"),
        offered_tick,
        offer if offer is not None else _lot(**{WOOD: 1}),
        request if request is not None else _lot(**{BERRY: 1}),
    )


def _state(
    *,
    proposer: Agent | None = None,
    recipient: Agent | None = None,
    trades: tuple[TradeOffer, ...] = (),
    tick: int = 0,
    seed: int = 1,
) -> SessionState:
    return SessionState(
        seed=seed,
        tick=tick,
        rng_state=seed,
        world=WorldMap(width=9, height=9, tiles=(TileType.GRASS,) * 81),
        agents=(
            proposer or _agent("ag_01", Position(2, 2), inventory=_inventory(**{WOOD: 2})),
            recipient or _agent("ag_02", Position(3, 2), inventory=_inventory(**{BERRY: 2})),
        ),
        trades=trades,
    )


def _run(
    state: SessionState,
    kind: ActionKind,
    payload: tuple[tuple[str, object], ...],
    *,
    agent: str = "ag_01",
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    engine = TurnEngine(state, resolvers=trade_resolvers())
    engine.submit(Action(AgentId(agent), state.tick, kind, payload))
    result = engine.resolve()
    return engine.state, result.events


def _offer(
    state: SessionState,
    *,
    offer: object | None = None,
    request: object | None = None,
    target: str = "ag_02",
) -> tuple[SessionState, str]:
    reached, events = _run(
        state,
        ActionKind.OFFER_TRADE,
        (
            ("target_id", target),
            ("offer", offer if offer is not None else _lot(**{WOOD: 1})),
            ("request", request if request is not None else _lot(**{BERRY: 1})),
        ),
    )
    return reached, events[0].outcome


def _accept(
    state: SessionState,
    trade: TradeOffer,
    *,
    agent: str = "ag_02",
) -> tuple[SessionState, str]:
    reached, events = _run(
        state,
        ActionKind.ACCEPT_TRADE,
        (("trade_id", trade.trade_id),),
        agent=agent,
    )
    return reached, events[0].outcome


def _decline(
    state: SessionState,
    trade: TradeOffer,
    *,
    agent: str = "ag_02",
) -> tuple[SessionState, str]:
    reached, events = _run(
        state,
        ActionKind.DECLINE_TRADE,
        (("trade_id", trade.trade_id),),
        agent=agent,
    )
    return reached, events[0].outcome


def _stacks(agent: Agent) -> dict[str, int]:
    return {stack.definition.item_id: stack.quantity for stack in agent.inventory.stacks}


def _agent_in(state: SessionState, agent_id: str) -> Agent:
    return next(agent for agent in state.agents if agent.agent_id == agent_id)


class TradeModelTests(unittest.TestCase):
    def test_trade_id_is_deterministic_and_directional(self) -> None:
        self.assertEqual(
            trade_id_for(AgentId("ag_01"), AgentId("ag_02"), 7),
            "tr_ag_01_ag_02_000007",
        )
        self.assertNotEqual(
            trade_id_for(AgentId("ag_01"), AgentId("ag_02"), 7),
            trade_id_for(AgentId("ag_02"), AgentId("ag_01"), 7),
        )

    def test_trade_rejects_invalid_records(self) -> None:
        offer = _lot(**{WOOD: 1})
        request = _lot(**{BERRY: 1})
        with self.assertRaises(ValueError):
            TradeOffer.propose(AgentId("ag_01"), AgentId("ag_01"), 0, offer, request)
        with self.assertRaises(ValueError):
            TradeOffer.propose(AgentId("ag_01"), AgentId("ag_02"), 0, (), request)
        with self.assertRaises(ValueError):
            TradeOffer.propose(
                AgentId("ag_01"),
                AgentId("ag_02"),
                0,
                ((ItemId(WOOD), 1), (ItemId(BERRY), 1)),
                request,
            )
        with self.assertRaises(ValueError):
            TradeOffer.propose(
                AgentId("ag_01"),
                AgentId("ag_02"),
                0,
                ((ItemId(WOOD), 0),),
                request,
            )
        with self.assertRaises(ValueError):
            TradeOffer(
                trade_id="tr_ag_02_ag_01_000000",
                proposer_id=AgentId("ag_01"),
                target_id=AgentId("ag_02"),
                offered_tick=0,
                offer=offer,
                request=request,
            )
        with self.assertRaises(ValueError):
            TradeOffer(
                trade_id=trade_id_for(AgentId("ag_01"), AgentId("ag_02"), 0),
                proposer_id=AgentId("ag_01"),
                target_id=AgentId("ag_02"),
                offered_tick=0,
                offer=offer,
                request=request,
                resolved_tick=1,
            )

    def test_parse_lot_normalizes_wire_lots(self) -> None:
        self.assertEqual(
            parse_lot([{"item_id": WOOD, "qty": 2}, {"item_id": BERRY, "qty": 1}]),
            ((ItemId(BERRY), 1), (ItemId(WOOD), 2)),
        )
        self.assertEqual(parse_lot([(WOOD, 1)]), ((ItemId(WOOD), 1),))
        for invalid in (
            [],
            [{"item_id": WOOD, "qty": 0}],
            [{"item_id": WOOD, "qty": True}],
            [{"item_id": "", "qty": 1}],
            [{"item_id": "Bad Id", "qty": 1}],
            [{"item_id": WOOD, "qty": 1}, {"item_id": WOOD, "qty": 2}],
            "wood",
            None,
        ):
            self.assertIsNone(parse_lot(invalid))

    def test_expiry_marks_only_open_expired_offers(self) -> None:
        open_trade = _propose(offered_tick=0)
        accepted = _propose(offered_tick=0, offer=_lot(**{WOOD: 1})).accepted(1)

        fresh = expire_trades((open_trade,), tick=TRADE_TTL_TICKS - 1)
        stale = expire_trades((open_trade,), tick=TRADE_TTL_TICKS)

        self.assertEqual(fresh, (open_trade,))
        self.assertEqual(stale[0].status, TradeStatus.EXPIRED)
        self.assertEqual(stale[0].resolved_tick, TRADE_TTL_TICKS)
        self.assertEqual(expire_trades((accepted,), tick=99), (accepted,))
        self.assertEqual(open_trade.expires_at_tick, TRADE_TTL_TICKS)

    def test_open_trades_filter_by_agent(self) -> None:
        trade = _propose()

        self.assertEqual(open_trades((trade,), AgentId("ag_02")), (trade,))
        self.assertEqual(open_trades((trade,), AgentId("ag_03")), ())
        self.assertEqual(open_trades((trade.accepted(1),), AgentId("ag_02")), ())

    def test_state_rejects_unsorted_or_duplicate_trades(self) -> None:
        first = _propose(offered_tick=0)
        second = TradeOffer.propose(
            AgentId("ag_02"), AgentId("ag_03"), 0, _lot(**{WOOD: 1}), _lot(**{BERRY: 1})
        )
        agents = (
            _agent("ag_01", Position(2, 2)),
            _agent("ag_02", Position(3, 2)),
            _agent("ag_03", Position(4, 2)),
        )

        with self.assertRaises(ValueError):
            _state(proposer=agents[0], recipient=agents[1], trades=(first, first))
        with self.assertRaises(ValueError):
            _state(proposer=agents[0], recipient=agents[1], trades=(second, first))


class TradeOfferTests(unittest.TestCase):
    def test_offer_creates_an_open_trade(self) -> None:
        reached, outcome = _offer(_state())

        self.assertEqual(outcome, TradeOutcome.OFFERED.value)
        self.assertEqual(len(reached.trades), 1)
        trade = reached.trades[0]
        self.assertTrue(trade.is_open)
        self.assertEqual(trade.trade_id, "tr_ag_01_ag_02_000000")
        self.assertEqual(trade.offer, _lot(**{WOOD: 1}))
        self.assertEqual(trade.request, _lot(**{BERRY: 1}))

    def test_offer_range_is_two_cells(self) -> None:
        near = _state(recipient=_agent("ag_02", Position(2 + TRADE_RANGE, 2)))
        _, near_outcome = _offer(near)
        self.assertEqual(near_outcome, TradeOutcome.OFFERED.value)

        far = _state(recipient=_agent("ag_02", Position(2 + TRADE_RANGE + 1, 2)))
        reached, far_outcome = _offer(far)
        self.assertEqual(far_outcome, TradeOutcome.OUT_OF_RANGE.value)
        self.assertEqual(reached.trades, ())

    def test_offer_requires_the_offered_items(self) -> None:
        poor = _state(proposer=_agent("ag_01", Position(2, 2), inventory=_inventory(**{WOOD: 1})))

        reached, outcome = _offer(poor, offer=_lot(**{WOOD: 2}))

        self.assertEqual(outcome, TradeOutcome.MISSING_ITEMS.value)
        self.assertEqual(reached.trades, ())

    def test_offer_rejects_invalid_lots(self) -> None:
        _, empty_offer = _offer(_state(), offer=())
        self.assertEqual(empty_offer, TradeOutcome.INVALID_TRADE.value)

        _, zero_request = _offer(_state(), request=((ItemId(BERRY), 0),))
        self.assertEqual(zero_request, TradeOutcome.INVALID_TRADE.value)

        _, wrong_shape = _offer(_state(), request=[{"item_id": BERRY, "qty": 1}])
        self.assertEqual(wrong_shape, TradeOutcome.INVALID_TRADE.value)

    def test_offer_rejects_unsorted_lots(self) -> None:
        rich = _state(
            proposer=_agent("ag_01", Position(2, 2), inventory=_inventory(**{WOOD: 1, BERRY: 1})),
        )

        reached, outcome = _offer(rich, offer=((ItemId(WOOD), 1), (ItemId(BERRY), 1)))

        self.assertEqual(outcome, TradeOutcome.INVALID_TRADE.value)
        self.assertEqual(reached.trades, ())

    def test_offer_rejects_self_unknown_and_dead_targets(self) -> None:
        _, self_outcome = _offer(_state(), target="ag_01")
        self.assertEqual(self_outcome, TradeOutcome.INVALID_TARGET.value)

        _, unknown_outcome = _offer(_state(), target="ag_09")
        self.assertEqual(unknown_outcome, TradeOutcome.INVALID_TARGET.value)

        dead = _state(recipient=_agent("ag_02", Position(3, 2), health_centi=0))
        _, dead_outcome = _offer(dead)
        self.assertEqual(dead_outcome, TradeOutcome.INVALID_TARGET.value)


class TradeAcceptTests(unittest.TestCase):
    def test_accept_swaps_the_items_atomically(self) -> None:
        trade = _propose()

        reached, outcome = _accept(_state(trades=(trade,)), trade)

        self.assertEqual(outcome, TradeOutcome.ACCEPTED.value)
        proposer = _agent_in(reached, "ag_01")
        recipient = _agent_in(reached, "ag_02")
        self.assertEqual(_stacks(proposer), {WOOD: 1, BERRY: 1})
        self.assertEqual(_stacks(recipient), {BERRY: 1, WOOD: 1})
        self.assertEqual(reached.trades[0].status, TradeStatus.ACCEPTED)
        self.assertEqual(reached.trades[0].resolved_tick, 0)

    def test_accept_without_the_items_changes_nothing(self) -> None:
        trade = _propose()
        recipient = _agent("ag_02", Position(3, 2), inventory=_inventory(fiber=1))
        state = _state(recipient=recipient, trades=(trade,))

        reached, outcome = _accept(state, trade)

        self.assertEqual(outcome, TradeOutcome.MISSING_ITEMS.value)
        self.assertEqual(_agent_in(reached, "ag_01").inventory, _agent_in(state, "ag_01").inventory)
        self.assertEqual(_agent_in(reached, "ag_02").inventory, recipient.inventory)
        self.assertTrue(find_trade(reached.trades, trade.trade_id).is_open)

    def test_accept_with_a_full_inventory_changes_nothing(self) -> None:
        trade = _propose(
            offer=_lot(**{STONE: 1, "waterskin": 1}),
            request=_lot(**{BERRY: 1}),
        )
        crowded = _inventory(
            wood=1,
            fiber=1,
            berry=1,
            coconut=1,
            reed=1,
            clay=1,
            sharp_stone=1,
            bandage=1,
            torch=1,
            stone_spear=1,
        )
        proposer = _agent(
            "ag_01",
            Position(2, 2),
            inventory=_inventory(**{STONE: 1, "waterskin": 1}),
        )
        recipient = _agent("ag_02", Position(3, 2), inventory=crowded)
        state = _state(proposer=proposer, recipient=recipient, trades=(trade,))

        reached, outcome = _accept(state, trade)

        self.assertEqual(outcome, TradeOutcome.INVENTORY_FULL.value)
        self.assertEqual(_agent_in(reached, "ag_01").inventory, proposer.inventory)
        self.assertEqual(_agent_in(reached, "ag_02").inventory, crowded)
        self.assertTrue(find_trade(reached.trades, trade.trade_id).is_open)

    def test_proposer_cannot_accept_its_own_offer(self) -> None:
        trade = _propose()

        _, outcome = _accept(_state(trades=(trade,)), trade, agent="ag_01")

        self.assertEqual(outcome, TradeOutcome.NOT_YOUR_TRADE.value)

    def test_stranger_cannot_accept_the_offer(self) -> None:
        trade = _propose()
        state = SessionState(
            seed=1,
            tick=0,
            rng_state=1,
            world=WorldMap(width=9, height=9, tiles=(TileType.GRASS,) * 81),
            agents=(
                _agent("ag_01", Position(2, 2)),
                _agent("ag_02", Position(3, 2)),
                _agent("ag_03", Position(4, 2)),
            ),
            trades=(trade,),
        )

        _, outcome = _accept(state, trade, agent="ag_03")

        self.assertEqual(outcome, TradeOutcome.UNKNOWN_TRADE.value)

    def test_a_closed_trade_cannot_be_accepted_again(self) -> None:
        trade = _propose()
        accepted, _ = _accept(_state(trades=(trade,)), trade)

        _, second = _accept(accepted, trade)
        self.assertEqual(second, TradeOutcome.ALREADY_RESOLVED.value)

        declined, _ = _decline(_state(trades=(trade,)), trade)
        _, after_decline = _accept(declined, trade)
        self.assertEqual(after_decline, TradeOutcome.ALREADY_RESOLVED.value)

    def test_expired_offers_cannot_execute(self) -> None:
        trade = _propose()
        stale = _state(trades=(trade,), tick=TRADE_TTL_TICKS)

        reached, outcome = _accept(stale, trade)

        self.assertEqual(outcome, TradeOutcome.EXPIRED.value)
        self.assertEqual(reached.trades[0].status, TradeStatus.EXPIRED)
        self.assertEqual(_stacks(_agent_in(reached, "ag_01")), {WOOD: 2})
        self.assertEqual(_stacks(_agent_in(reached, "ag_02")), {BERRY: 2})

    def test_accept_requires_the_proposer_nearby(self) -> None:
        trade = _propose()
        far = _state(
            proposer=_agent("ag_01", Position(8, 8), inventory=_inventory(**{WOOD: 2})),
            trades=(trade,),
        )

        _, outcome = _accept(far, trade)

        self.assertEqual(outcome, TradeOutcome.OUT_OF_RANGE.value)

    def test_accept_rejects_a_dead_proposer(self) -> None:
        trade = _propose()
        dead = _state(
            proposer=_agent("ag_01", Position(2, 2), health_centi=0),
            trades=(trade,),
        )

        _, outcome = _accept(dead, trade)

        self.assertEqual(outcome, TradeOutcome.INVALID_TARGET.value)

    def test_decline_closes_the_offer(self) -> None:
        trade = _propose()

        reached, outcome = _decline(_state(trades=(trade,)), trade)

        self.assertEqual(outcome, TradeOutcome.DECLINED.value)
        self.assertEqual(reached.trades[0].status, TradeStatus.DECLINED)
        self.assertEqual(_stacks(_agent_in(reached, "ag_01")), {WOOD: 2})

    def test_proposer_cannot_decline_its_own_offer(self) -> None:
        trade = _propose()

        _, outcome = _decline(_state(trades=(trade,)), trade, agent="ag_01")

        self.assertEqual(outcome, TradeOutcome.NOT_YOUR_TRADE.value)

    def test_unknown_trade_ids_are_rejected(self) -> None:
        trade = _propose()
        engine = TurnEngine(_state(trades=(trade,)), resolvers=trade_resolvers())
        engine.submit(
            Action(
                AgentId("ag_02"),
                0,
                ActionKind.ACCEPT_TRADE,
                (("trade_id", "tr_ag_01_ag_09_000000"),),
            )
        )
        result = engine.resolve()

        self.assertEqual(result.events[0].outcome, TradeOutcome.UNKNOWN_TRADE.value)


class TradeSessionTests(unittest.TestCase):
    def _layout(self) -> WorldLayout:
        return WorldLayout(
            seed=1,
            world=WorldMap(width=8, height=8, tiles=(TileType.GRASS,) * 64),
            spawn_points=(Position(2, 2), Position(3, 2)),
        )

    def _session(self) -> tuple[GameSession, str, str]:
        session = GameSession(
            1,
            layout=self._layout(),
            profiles=(
                AgentProfile(inventory=_inventory(**{WOOD: 2})),
                AgentProfile(inventory=_inventory(**{BERRY: 2})),
            ),
        )
        return (
            session,
            session.join("Nia", session.tokens[0])["agent_id"],
            session.join("Kai", session.tokens[1])["agent_id"],
        )

    def _offer_and_resolve(
        self,
        session: GameSession,
        proposer: str,
        recipient: str,
    ) -> str:
        self.assertTrue(
            session.offer_trade(
                proposer,
                0,
                recipient,
                [{"item_id": WOOD, "qty": 1}],
                [{"item_id": BERRY, "qty": 1}],
            )["ok"]
        )
        self.assertTrue(session.wait(recipient, 0)["ok"])
        observation = session.observe(recipient)
        trade = observation["social"]["trades"][0]
        self.assertFalse(trade["mine"])
        self.assertEqual(trade["from"], proposer)
        self.assertEqual(trade["to"], recipient)
        self.assertEqual(trade["offer"], [{"item_id": WOOD, "qty": 1}])
        self.assertEqual(trade["request"], [{"item_id": BERRY, "qty": 1}])
        self.assertEqual(trade["expires_at_tick"], TRADE_TTL_TICKS)
        return trade["trade_id"]

    def test_offer_accept_and_swap_are_visible_across_ticks(self) -> None:
        session, proposer, recipient = self._session()
        trade_id = self._offer_and_resolve(session, proposer, recipient)

        self.assertTrue(session.accept_trade(recipient, 1, trade_id)["ok"])
        self.assertTrue(session.wait(proposer, 1)["ok"])

        observation = session.observe(recipient)
        self.assertEqual(observation["tick"], 2)
        self.assertEqual(observation["last_action_result"]["outcome"], "accepted")
        self.assertEqual(observation["social"]["trades"], [])
        self.assertEqual(
            _stacks(_agent_in(session.state, proposer)),
            {WOOD: 1, BERRY: 1},
        )
        self.assertEqual(
            _stacks(_agent_in(session.state, recipient)),
            {BERRY: 1, WOOD: 1},
        )

    def test_offers_expire_after_five_ticks(self) -> None:
        session, proposer, recipient = self._session()
        trade_id = self._offer_and_resolve(session, proposer, recipient)

        for tick in range(1, TRADE_TTL_TICKS):
            self.assertTrue(session.wait(proposer, tick)["ok"])
            self.assertTrue(session.wait(recipient, tick)["ok"])

        self.assertEqual(session.state.tick, TRADE_TTL_TICKS)
        self.assertEqual(session.state.trades[0].status, TradeStatus.EXPIRED)
        self.assertTrue(session.accept_trade(recipient, TRADE_TTL_TICKS, trade_id)["ok"])
        self.assertTrue(session.wait(proposer, TRADE_TTL_TICKS)["ok"])

        observation = session.observe(recipient)
        self.assertEqual(observation["last_action_result"]["outcome"], "expired")
        self.assertEqual(_stacks(_agent_in(session.state, proposer)), {WOOD: 2})
        self.assertEqual(_stacks(_agent_in(session.state, recipient)), {BERRY: 2})

    def test_invalid_wire_lots_are_rejected_before_queueing(self) -> None:
        session, proposer, recipient = self._session()

        result = session.offer_trade(proposer, 0, recipient, [], [{"item_id": BERRY, "qty": 1}])

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_TRADE")
        self.assertTrue(session.observe(proposer)["social"]["trades"] == [])

    def test_leaving_an_agent_drops_its_trades(self) -> None:
        session, proposer, recipient = self._session()
        self._offer_and_resolve(session, proposer, recipient)
        self.assertEqual(len(session.state.trades), 1)

        self.assertTrue(session.leave(recipient)["ok"])

        self.assertEqual(session.state.trades, ())
        self.assertEqual(session.observe(proposer)["social"]["trades"], [])

    def test_trade_flow_is_deterministic(self) -> None:
        first_session, first_proposer, first_recipient = self._session()
        second_session, second_proposer, second_recipient = self._session()
        for session, proposer, recipient in (
            (first_session, first_proposer, first_recipient),
            (second_session, second_proposer, second_recipient),
        ):
            trade_id = self._offer_and_resolve(session, proposer, recipient)
            self.assertTrue(session.accept_trade(recipient, 1, trade_id)["ok"])
            self.assertTrue(session.wait(proposer, 1)["ok"])

        self.assertEqual(
            canonical_state_hash(first_session.state),
            canonical_state_hash(second_session.state),
        )
        self.assertNotEqual(
            canonical_state_hash(first_session.state),
            canonical_state_hash(GameSession(1, layout=self._layout()).state),
        )


if __name__ == "__main__":
    unittest.main()
