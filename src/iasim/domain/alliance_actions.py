"""Resolvers for alliance offers, acceptance, breaking, and withdrawal."""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum

from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent
from iasim.domain.alliances import (
    Alliance,
    alliance_between,
    replace_alliance,
    within_alliance_radius,
)
from iasim.domain.identifiers import AgentId
from iasim.domain.session import SessionState
from iasim.domain.turns import ActionResolver, TurnEvent


class AllianceOutcome(StrEnum):
    """Stable outcomes for the three alliance actions."""

    OFFERED = "offered"
    ACCEPTED = "accepted"
    BROKEN = "broken"
    WITHDRAWN = "withdrawn"
    DECLINED = "declined"
    INVALID_TARGET = "invalid_target"
    UNKNOWN_AGENT = "unknown_agent"
    OUT_OF_RANGE = "out_of_range"
    ALREADY_ALLIED = "already_allied"
    ALREADY_OFFERED = "already_offered"
    NO_OFFER = "no_offer"
    UNKNOWN_ALLIANCE = "unknown_alliance"
    NOT_INVITED = "not_invited"
    NOT_ALLIED = "not_allied"


def resolve_offer_alliance(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Propose an alliance to a nearby living agent.

    The offer never expires: it stays pending, and therefore visible to both
    agents, until it is accepted, withdrawn, declined, or one agent leaves.
    """
    target = _target_agent(state, action)
    if isinstance(target, AllianceOutcome):
        return state, (_event(action, target),)

    actor = _find_agent(state, action.agent_id)
    if actor is None:
        return state, (_event(action, AllianceOutcome.UNKNOWN_AGENT),)
    if not within_alliance_radius(actor.position, target.position):
        return state, (_event(action, AllianceOutcome.OUT_OF_RANGE),)

    existing = alliance_between(state.alliances, actor.agent_id, target.agent_id)
    if existing is not None and existing.is_active:
        return state, (_event(action, AllianceOutcome.ALREADY_ALLIED),)
    if existing is not None and existing.is_pending:
        return state, (_event(action, AllianceOutcome.ALREADY_OFFERED),)

    offer = Alliance.propose(actor.agent_id, target.agent_id, action.tick)
    return (
        replace(state, alliances=replace_alliance(state.alliances, offer)),
        (_event(action, AllianceOutcome.OFFERED),),
    )


def resolve_accept_alliance(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Accept one pending offer addressed to the acting agent."""
    actor = _find_agent(state, action.agent_id)
    if actor is None:
        return state, (_event(action, AllianceOutcome.UNKNOWN_AGENT),)
    payload = action.payload_dict()
    alliance_id = payload.get("alliance_id")
    if not isinstance(alliance_id, str) or not alliance_id:
        return state, (_event(action, AllianceOutcome.UNKNOWN_ALLIANCE),)

    offer = _find_offer(state, alliance_id)
    if offer is None or not offer.involves(actor.agent_id):
        return state, (_event(action, AllianceOutcome.UNKNOWN_ALLIANCE),)
    if offer.is_active:
        return state, (_event(action, AllianceOutcome.ALREADY_ALLIED),)
    if offer.is_broken:
        return state, (_event(action, AllianceOutcome.NO_OFFER),)
    if offer.proposed_by == actor.agent_id:
        return state, (_event(action, AllianceOutcome.NOT_INVITED),)

    proposer = _find_agent(state, offer.proposed_by)
    if proposer is None or not proposer.is_alive:
        return state, (_event(action, AllianceOutcome.INVALID_TARGET),)
    if not within_alliance_radius(actor.position, proposer.position):
        return state, (_event(action, AllianceOutcome.OUT_OF_RANGE),)

    accepted = offer.accepted(action.tick)
    return (
        replace(state, alliances=replace_alliance(state.alliances, accepted)),
        (_event(action, AllianceOutcome.ACCEPTED),),
    )


def resolve_break_alliance(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Break an active alliance, or close a pending offer.

    Distance never blocks a break: an alliance is a declaration, not a bond.
    The proposer withdraws the pending offer and the invited agent declines it.
    """
    target = _target_agent(state, action)
    if isinstance(target, AllianceOutcome):
        return state, (_event(action, target),)

    actor = _find_agent(state, action.agent_id)
    if actor is None:
        return state, (_event(action, AllianceOutcome.UNKNOWN_AGENT),)
    existing = alliance_between(state.alliances, actor.agent_id, target.agent_id)
    if existing is None or existing.is_broken:
        return state, (_event(action, AllianceOutcome.NOT_ALLIED),)

    if existing.is_pending:
        outcome = (
            AllianceOutcome.WITHDRAWN
            if existing.proposed_by == actor.agent_id
            else AllianceOutcome.DECLINED
        )
    else:
        outcome = AllianceOutcome.BROKEN
    ended = existing.ended(action.tick)
    return (
        replace(state, alliances=replace_alliance(state.alliances, ended)),
        (_event(action, outcome),),
    )


def alliance_resolvers() -> dict[ActionKind, ActionResolver]:
    """Return the alliance resolvers for a TurnEngine."""
    return {
        ActionKind.OFFER_ALLIANCE: resolve_offer_alliance,
        ActionKind.ACCEPT_ALLIANCE: resolve_accept_alliance,
        ActionKind.BREAK_ALLIANCE: resolve_break_alliance,
    }


def _target_agent(
    state: SessionState,
    action: Action,
) -> Agent | AllianceOutcome:
    """Return the living target agent or the rejection outcome."""
    payload = action.payload_dict()
    target_id = payload.get("target_id")
    if not isinstance(target_id, str) or not target_id:
        return AllianceOutcome.INVALID_TARGET
    target = _find_agent(state, AgentId(target_id))
    if target is None or target.agent_id == action.agent_id or not target.is_alive:
        return AllianceOutcome.INVALID_TARGET
    return target


def _find_offer(state: SessionState, alliance_id: str) -> Alliance | None:
    return next(
        (alliance for alliance in state.alliances if alliance.alliance_id == alliance_id),
        None,
    )


def _event(action: Action, outcome: AllianceOutcome) -> TurnEvent:
    return TurnEvent(action.tick, action.agent_id, action.kind, outcome.value)


def _find_agent(state: SessionState, agent_id: AgentId) -> Agent | None:
    return next(
        (agent for agent in state.agents if agent.agent_id == agent_id),
        None,
    )
