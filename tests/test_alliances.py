"""Tests for declarative alliances, their transitions, and betrayal annotations."""

from __future__ import annotations

import unittest

from iasim.app.session import GameSession
from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent, AgentAttributes, AgentProfile, AgentStatus
from iasim.domain.alliance_actions import (
    AllianceOutcome,
    alliance_resolvers,
)
from iasim.domain.alliances import (
    BETRAYAL,
    Alliance,
    AllianceStatus,
    alliance_id_for,
    is_allied,
    replace_alliance,
    within_alliance_radius,
)
from iasim.domain.combat import combat_resolvers
from iasim.domain.geometry import Position
from iasim.domain.hashing import canonical_state_hash
from iasim.domain.identifiers import AgentId
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.turns import ActionResolver, TurnEngine, TurnEvent
from iasim.world.layout import WorldLayout


def _world() -> WorldMap:
    return WorldMap(width=13, height=13, tiles=(TileType.GRASS,) * 169)


def _agent(
    agent_id: str,
    position: Position,
    *,
    health_centi: int = 100 * 100,
) -> Agent:
    return Agent(
        AgentId(agent_id),
        position,
        attributes=AgentAttributes(health_centi=health_centi),
    )


def _state(
    *,
    agents: tuple[Agent, ...] | None = None,
    alliances: tuple[Alliance, ...] = (),
    tick: int = 0,
    seed: int = 1,
) -> SessionState:
    return SessionState(
        seed=seed,
        tick=tick,
        rng_state=seed,
        world=_world(),
        agents=agents or (_agent("ag_01", Position(2, 2)), _agent("ag_02", Position(3, 2))),
        alliances=alliances,
    )


def _active(first: str = "ag_01", second: str = "ag_02") -> Alliance:
    return Alliance.propose(AgentId(first), AgentId(second), 0).accepted(0)


def _run(
    state: SessionState,
    kind: ActionKind,
    payload: tuple[tuple[str, object], ...],
    *,
    agent: str = "ag_01",
    resolvers: dict[ActionKind, ActionResolver] | None = None,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    engine = TurnEngine(state, resolvers=resolvers or alliance_resolvers())
    engine.submit(Action(AgentId(agent), state.tick, kind, payload))
    result = engine.resolve()
    return engine.state, result.events


def _offer(state: SessionState, target: str = "ag_02") -> tuple[SessionState, str]:
    reached, events = _run(state, ActionKind.OFFER_ALLIANCE, (("target_id", target),))
    return reached, events[0].outcome


def _accept(
    state: SessionState,
    alliance_id: str,
    *,
    agent: str = "ag_02",
) -> tuple[SessionState, str]:
    reached, events = _run(
        state,
        ActionKind.ACCEPT_ALLIANCE,
        (("alliance_id", alliance_id),),
        agent=agent,
    )
    return reached, events[0].outcome


def _break(
    state: SessionState,
    target: str = "ag_02",
    *,
    agent: str = "ag_01",
) -> tuple[SessionState, str]:
    reached, events = _run(
        state,
        ActionKind.BREAK_ALLIANCE,
        (("target_id", target),),
        agent=agent,
    )
    return reached, events[0].outcome


class AllianceModelTests(unittest.TestCase):
    def test_alliance_id_is_deterministic_and_sorted(self) -> None:
        first = AgentId("ag_01")
        second = AgentId("ag_02")

        self.assertEqual(alliance_id_for(first, second), "al_ag_01_ag_02")
        self.assertEqual(alliance_id_for(second, first), alliance_id_for(first, second))

    def test_alliance_rejects_invalid_records(self) -> None:
        with self.assertRaises(ValueError):
            Alliance(
                alliance_id="al_ag_01_ag_02",
                members=(AgentId("ag_02"), AgentId("ag_01")),
                status=AllianceStatus.PENDING,
                proposed_by=AgentId("ag_01"),
                offered_tick=0,
            )
        with self.assertRaises(ValueError):
            Alliance(
                alliance_id="al_ag_02_ag_01",
                members=(AgentId("ag_01"), AgentId("ag_02")),
                status=AllianceStatus.PENDING,
                proposed_by=AgentId("ag_01"),
                offered_tick=0,
            )
        with self.assertRaises(ValueError):
            Alliance.propose(AgentId("ag_01"), AgentId("ag_01"), 0)
        with self.assertRaises(ValueError):
            Alliance(
                alliance_id="al_ag_01_ag_02",
                members=(AgentId("ag_01"), AgentId("ag_02")),
                status=AllianceStatus.PENDING,
                proposed_by=AgentId("ag_01"),
                offered_tick=0,
                accepted_tick=1,
            )
        with self.assertRaises(ValueError):
            Alliance(
                alliance_id="al_ag_01_ag_02",
                members=(AgentId("ag_01"), AgentId("ag_02")),
                status=AllianceStatus.ACTIVE,
                proposed_by=AgentId("ag_01"),
                offered_tick=0,
            )

    def test_state_rejects_unsorted_or_duplicate_alliances(self) -> None:
        first = _active("ag_01", "ag_02")
        second = _active("ag_02", "ag_03")
        agents = (
            _agent("ag_01", Position(2, 2)),
            _agent("ag_02", Position(3, 2)),
            _agent("ag_03", Position(4, 2)),
        )

        with self.assertRaises(ValueError):
            _state(agents=agents, alliances=(first, first))
        with self.assertRaises(ValueError):
            _state(agents=agents, alliances=(second, first))

    def test_replacing_a_record_keeps_ids_sorted(self) -> None:
        first = _active("ag_01", "ag_02")
        second = _active("ag_02", "ag_03")

        unordered = replace_alliance((second,), first)

        self.assertEqual(
            [alliance.alliance_id for alliance in unordered],
            sorted(alliance.alliance_id for alliance in unordered),
        )

    def test_social_radius_matches_the_chat_radius(self) -> None:
        self.assertTrue(within_alliance_radius(Position(2, 2), Position(2, 10)))
        self.assertFalse(within_alliance_radius(Position(2, 2), Position(2, 11)))


class AllianceOfferTests(unittest.TestCase):
    def test_offer_creates_a_pending_record(self) -> None:
        reached, outcome = _offer(_state())

        self.assertEqual(outcome, AllianceOutcome.OFFERED.value)
        self.assertEqual(len(reached.alliances), 1)
        offer = reached.alliances[0]
        self.assertTrue(offer.is_pending)
        self.assertEqual(offer.proposed_by, "ag_01")
        self.assertEqual(offer.members, ("ag_01", "ag_02"))
        self.assertEqual(offer.offered_tick, 0)

    def test_a_pending_offer_is_not_an_alliance_yet(self) -> None:
        reached, _ = _offer(_state())

        self.assertFalse(is_allied(reached.alliances, AgentId("ag_01"), AgentId("ag_02")))

    def test_offer_requires_the_social_radius(self) -> None:
        far = _state(agents=(_agent("ag_01", Position(2, 2)), _agent("ag_02", Position(11, 11))))

        reached, outcome = _offer(far)

        self.assertEqual(outcome, AllianceOutcome.OUT_OF_RANGE.value)
        self.assertEqual(reached.alliances, ())

    def test_offer_rejects_self_unknown_and_dead_targets(self) -> None:
        state = _state()
        _, self_outcome = _offer(state, "ag_01")
        self.assertEqual(self_outcome, AllianceOutcome.INVALID_TARGET.value)

        _, unknown_outcome = _offer(state, "ag_09")
        self.assertEqual(unknown_outcome, AllianceOutcome.INVALID_TARGET.value)

        dead = _state(
            agents=(
                _agent("ag_01", Position(2, 2)),
                Agent(
                    AgentId("ag_02"),
                    Position(3, 2),
                    attributes=AgentAttributes(health_centi=0),
                    status=AgentStatus.DEAD,
                ),
            )
        )
        _, dead_outcome = _offer(dead)
        self.assertEqual(dead_outcome, AllianceOutcome.INVALID_TARGET.value)

        _, malformed_outcome = _offer(state, "")
        self.assertEqual(malformed_outcome, AllianceOutcome.INVALID_TARGET.value)

    def test_duplicate_and_redundant_offers_are_rejected(self) -> None:
        pending = _state(alliances=(Alliance.propose(AgentId("ag_01"), AgentId("ag_02"), 0),))
        reached, outcome = _offer(pending)

        self.assertEqual(outcome, AllianceOutcome.ALREADY_OFFERED.value)
        self.assertEqual(reached.alliances, pending.alliances)

        allied = _state(alliances=(_active(),))
        reached, outcome = _offer(allied)

        self.assertEqual(outcome, AllianceOutcome.ALREADY_ALLIED.value)
        self.assertTrue(reached.alliances[0].is_active)

    def test_a_broken_alliance_can_be_offered_again(self) -> None:
        broken = _state(alliances=(_active().ended(1),))

        reached, outcome = _offer(broken)

        self.assertEqual(outcome, AllianceOutcome.OFFERED.value)
        self.assertTrue(reached.alliances[0].is_pending)


class AllianceAcceptTests(unittest.TestCase):
    def test_invited_agent_accepts_the_offer(self) -> None:
        pending = _state(alliances=(Alliance.propose(AgentId("ag_01"), AgentId("ag_02"), 0),))
        alliance_id = pending.alliances[0].alliance_id

        reached, outcome = _accept(pending, alliance_id)

        self.assertEqual(outcome, AllianceOutcome.ACCEPTED.value)
        alliance = reached.alliances[0]
        self.assertTrue(alliance.is_active)
        self.assertEqual(alliance.accepted_tick, 0)
        self.assertTrue(is_allied(reached.alliances, AgentId("ag_01"), AgentId("ag_02")))

    def test_proposer_cannot_accept_its_own_offer(self) -> None:
        pending = _state(alliances=(Alliance.propose(AgentId("ag_01"), AgentId("ag_02"), 0),))
        alliance_id = pending.alliances[0].alliance_id

        reached, outcome = _accept(pending, alliance_id, agent="ag_01")

        self.assertEqual(outcome, AllianceOutcome.NOT_INVITED.value)
        self.assertTrue(reached.alliances[0].is_pending)

    def test_unknown_or_foreign_alliances_are_rejected(self) -> None:
        pending = _state(alliances=(Alliance.propose(AgentId("ag_01"), AgentId("ag_02"), 0),))
        alliance_id = pending.alliances[0].alliance_id

        _, unknown = _accept(pending, "al_ag_01_ag_09")
        self.assertEqual(unknown, AllianceOutcome.UNKNOWN_ALLIANCE.value)

        _, empty = _accept(pending, "")
        self.assertEqual(empty, AllianceOutcome.UNKNOWN_ALLIANCE.value)

        stranger = _state(
            agents=(
                _agent("ag_01", Position(2, 2)),
                _agent("ag_02", Position(3, 2)),
                _agent("ag_03", Position(4, 2)),
            ),
            alliances=pending.alliances,
        )
        _, foreign = _accept(stranger, alliance_id, agent="ag_03")
        self.assertEqual(foreign, AllianceOutcome.UNKNOWN_ALLIANCE.value)

    def test_accept_requires_the_proposer_in_range(self) -> None:
        pending = _state(
            agents=(_agent("ag_01", Position(2, 2)), _agent("ag_02", Position(12, 12))),
            alliances=(Alliance.propose(AgentId("ag_01"), AgentId("ag_02"), 0),),
        )

        reached, outcome = _accept(pending, pending.alliances[0].alliance_id)

        self.assertEqual(outcome, AllianceOutcome.OUT_OF_RANGE.value)
        self.assertTrue(reached.alliances[0].is_pending)

    def test_a_closed_offer_cannot_be_accepted(self) -> None:
        withdrawn = _state(alliances=(_active().ended(1),))

        _, outcome = _accept(withdrawn, withdrawn.alliances[0].alliance_id)
        self.assertEqual(outcome, AllianceOutcome.NO_OFFER.value)

        allied = _state(alliances=(_active(),))
        _, applied = _accept(allied, allied.alliances[0].alliance_id)
        self.assertEqual(applied, AllianceOutcome.ALREADY_ALLIED.value)


class AllianceBreakTests(unittest.TestCase):
    def test_breaking_an_active_alliance_marks_it_broken(self) -> None:
        allied = _state(alliances=(_active(),))

        reached, outcome = _break(allied)

        self.assertEqual(outcome, AllianceOutcome.BROKEN.value)
        alliance = reached.alliances[0]
        self.assertTrue(alliance.is_broken)
        self.assertEqual(alliance.broken_tick, 0)
        self.assertFalse(is_allied(reached.alliances, AgentId("ag_01"), AgentId("ag_02")))

    def test_breaking_without_an_alliance_is_rejected(self) -> None:
        reached, outcome = _break(_state())

        self.assertEqual(outcome, AllianceOutcome.NOT_ALLIED.value)
        self.assertEqual(reached.alliances, ())

    def test_proposer_withdraws_a_pending_offer(self) -> None:
        pending = _state(alliances=(Alliance.propose(AgentId("ag_01"), AgentId("ag_02"), 0),))

        reached, outcome = _break(pending)

        self.assertEqual(outcome, AllianceOutcome.WITHDRAWN.value)
        self.assertTrue(reached.alliances[0].is_broken)

    def test_invited_agent_declines_a_pending_offer(self) -> None:
        pending = _state(alliances=(Alliance.propose(AgentId("ag_01"), AgentId("ag_02"), 0),))

        reached, outcome = _break(pending, "ag_01", agent="ag_02")

        self.assertEqual(outcome, AllianceOutcome.DECLINED.value)
        self.assertTrue(reached.alliances[0].is_broken)

    def test_breaking_never_requires_closeness(self) -> None:
        allied = _state(
            agents=(_agent("ag_01", Position(2, 2)), _agent("ag_02", Position(12, 12))),
            alliances=(_active(),),
        )

        _, outcome = _break(allied)

        self.assertEqual(outcome, AllianceOutcome.BROKEN.value)

    def test_attacking_an_ally_is_allowed_and_annotated_as_betrayal(self) -> None:
        allied = _state(alliances=(_active(),))
        resolvers = {**alliance_resolvers(), **combat_resolvers()}

        reached, events = _run(
            allied,
            ActionKind.ATTACK,
            (("target_id", "ag_02"),),
            resolvers=resolvers,
        )

        self.assertEqual(events[0].outcome, "hit")
        self.assertEqual(events[1].outcome, BETRAYAL)
        target = next(agent for agent in reached.agents if agent.agent_id == "ag_02")
        self.assertLess(target.attributes.health_centi, 100 * 100)
        self.assertTrue(is_allied(reached.alliances, AgentId("ag_01"), AgentId("ag_02")))

    def test_attacking_a_non_ally_has_no_betrayal_annotation(self) -> None:
        resolvers = {**alliance_resolvers(), **combat_resolvers()}

        _, events = _run(
            _state(),
            ActionKind.ATTACK,
            (("target_id", "ag_02"),),
            resolvers=resolvers,
        )

        self.assertEqual([event.outcome for event in events], ["hit"])


class AllianceSessionTests(unittest.TestCase):
    def _layout(self) -> WorldLayout:
        return WorldLayout(
            seed=1,
            world=WorldMap(width=6, height=6, tiles=(TileType.GRASS,) * 36),
            spawn_points=(Position(2, 2), Position(3, 2)),
        )

    def _joined(self, seed: int = 7) -> tuple[GameSession, str, str]:
        session = GameSession(seed, layout=self._layout())
        first = session.join("Nia", session.tokens[0])["agent_id"]
        second = session.join("Kai", session.tokens[1])["agent_id"]
        return session, first, second

    def _allied(self, seed: int = 7) -> tuple[GameSession, str, str, str]:
        session, first, second = self._joined(seed)
        self.assertTrue(session.offer_alliance(first, 0, second)["ok"])
        self.assertTrue(session.wait(second, 0)["ok"])
        alliance_id = session.observe(second)["social"]["offers"][0]["alliance_id"]
        self.assertTrue(session.accept_alliance(second, 1, alliance_id)["ok"])
        self.assertTrue(session.wait(first, 1)["ok"])
        return session, first, second, alliance_id

    def test_offer_accept_and_break_are_visible_across_ticks(self) -> None:
        session, first, second = self._joined()

        self.assertTrue(session.offer_alliance(first, 0, second)["ok"])
        self.assertTrue(session.wait(second, 0)["ok"])
        offered = session.observe(second)
        offer = offered["social"]["offers"][0]
        alliance_id = offer["alliance_id"]

        self.assertEqual(offered["tick"], 1)
        self.assertEqual(offer["from"], first)
        self.assertEqual(offer["to"], second)
        self.assertEqual(offer["tick"], 0)
        self.assertFalse(offer["mine"])
        self.assertEqual(offered["social"]["alliances"], [])
        self.assertEqual(offered["last_action_result"]["outcome"], "waited")
        self.assertTrue(session.observe(first)["social"]["offers"][0]["mine"])

        self.assertTrue(session.accept_alliance(second, 1, alliance_id)["ok"])
        self.assertTrue(session.wait(first, 1)["ok"])
        accepted = session.observe(first)

        self.assertEqual(accepted["tick"], 2)
        self.assertEqual(
            accepted["social"]["alliances"],
            [
                {"alliance_id": alliance_id, "with": second, "since_tick": 1},
            ],
        )
        self.assertEqual(accepted["social"]["offers"], [])
        relations = {entry["id"]: entry["relation"] for entry in accepted["perception"]["agents"]}
        self.assertEqual(relations[second], "ally")

        self.assertTrue(session.break_alliance(first, 2, second)["ok"])
        self.assertTrue(session.wait(second, 2)["ok"])
        broken = session.observe(first)

        self.assertEqual(broken["tick"], 3)
        self.assertEqual(broken["social"]["alliances"], [])
        self.assertEqual(broken["last_action_result"]["outcome"], "broken")
        self.assertEqual(broken["last_action_result"]["status"], "success")
        relations = {entry["id"]: entry["relation"] for entry in broken["perception"]["agents"]}
        self.assertEqual(relations[second], "neutral")

    def test_an_offer_never_expires_while_both_agents_stay(self) -> None:
        session, first, second = self._joined()
        self.assertTrue(session.offer_alliance(first, 0, second)["ok"])
        self.assertTrue(session.wait(second, 0)["ok"])
        alliance_id = session.observe(second)["social"]["offers"][0]["alliance_id"]

        for tick in (1, 2, 3):
            self.assertTrue(session.wait(first, tick)["ok"])
            self.assertTrue(session.wait(second, tick)["ok"])

        self.assertEqual(session.state.tick, 4)
        self.assertEqual(len(session.state.alliances), 1)
        self.assertTrue(session.state.alliances[0].is_pending)
        self.assertEqual(
            session.observe(second)["social"]["offers"][0]["alliance_id"],
            alliance_id,
        )

    def test_attacking_an_ally_keeps_the_combat_outcome(self) -> None:
        session, first, second, _ = self._allied()

        self.assertTrue(session.attack(first, 2, second)["ok"])
        self.assertTrue(session.wait(second, 2)["ok"])
        result = session.observe(first)["last_action_result"]

        self.assertEqual(result["action"], "attack")
        self.assertIn(result["outcome"], {"hit", "missed"})
        self.assertNotEqual(result["outcome"], BETRAYAL)

    def test_leaving_an_agent_drops_its_alliance_records(self) -> None:
        session, first, second, alliance_id = self._allied()
        self.assertEqual(len(session.state.alliances), 1)

        self.assertTrue(session.leave(second)["ok"])

        self.assertEqual(session.state.alliances, ())
        observation = session.observe(first)
        self.assertEqual(observation["social"]["alliances"], [])
        self.assertEqual(alliance_id, f"al_{min(first, second)}_{max(first, second)}")

    def test_death_drops_alliance_records(self) -> None:
        layout = self._layout()
        session = GameSession(
            1,
            layout=layout,
            profiles=(
                AgentProfile(),
                AgentProfile(attributes=AgentAttributes(health_centi=100)),
            ),
        )
        first = session.join("Nia", session.tokens[0])["agent_id"]
        second = session.join("Kai", session.tokens[1])["agent_id"]
        self.assertTrue(session.offer_alliance(first, 0, second)["ok"])
        self.assertTrue(session.wait(second, 0)["ok"])
        alliance_id = session.observe(second)["social"]["offers"][0]["alliance_id"]
        self.assertTrue(session.accept_alliance(second, 1, alliance_id)["ok"])
        self.assertTrue(session.wait(first, 1)["ok"])
        self.assertEqual(len(session.state.alliances), 1)

        self.assertTrue(session.attack(first, 2, second)["ok"])
        self.assertTrue(session.wait(second, 2)["ok"])

        self.assertEqual(session.state.tick, 3)
        self.assertEqual(session.state.corpses[0].agent_id, second)
        self.assertEqual(session.state.alliances, ())
        self.assertEqual(session.observe(first)["last_action_result"]["outcome"], "killed")

    def test_alliance_flow_is_deterministic(self) -> None:
        first_session, _, _, _ = self._allied(seed=7)
        second_session, _, _, _ = self._allied(seed=7)

        self.assertEqual(
            canonical_state_hash(first_session.state),
            canonical_state_hash(second_session.state),
        )
        self.assertNotEqual(
            canonical_state_hash(first_session.state),
            canonical_state_hash(GameSession(7, layout=self._layout()).state),
        )


if __name__ == "__main__":
    unittest.main()
