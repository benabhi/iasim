"""Resolve composite move_to actions with deterministic tcod pathfinding."""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum

from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.session import SessionState
from iasim.domain.turns import ActionResolver, TurnEvent
from iasim.world.tcod_pathfinding import find_path


class MoveToOutcome(StrEnum):
    """Stable outcomes for composite movement."""

    MOVED = "moved"
    UNKNOWN_AGENT = "unknown_agent"
    INVALID_TARGET = "invalid_target"
    OUT_OF_BOUNDS = "out_of_bounds"
    ALREADY_THERE = "already_there"
    NO_PATH = "no_path"


def move_to_resolvers() -> dict[ActionKind, ActionResolver]:
    """Return the composite movement resolver."""
    return {ActionKind.MOVE_TO: resolve_move_to}


def resolve_move_to(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Advance one step along a tcod path toward the requested target."""
    payload = action.payload_dict()
    target = _target_from_payload(payload)
    if target is None:
        return state, (_event(action, MoveToOutcome.INVALID_TARGET),)
    if not state.world.contains(target):
        return state, (_event(action, MoveToOutcome.OUT_OF_BOUNDS),)

    agent = _find_agent(state, action.agent_id)
    if agent is None:
        return state, (_event(action, MoveToOutcome.UNKNOWN_AGENT),)
    if target == agent.position:
        return state, (_event(action, MoveToOutcome.ALREADY_THERE),)

    blocked = frozenset(
        other.position
        for other in state.agents
        if other.agent_id != agent.agent_id and other.is_alive
    )
    path = find_path(state.world, agent.position, target, blocked=blocked)
    if not path:
        return state, (_event(action, MoveToOutcome.NO_PATH),)

    moved = replace(agent, position=path[0])
    return (
        replace(
            state,
            agents=tuple(
                moved if existing.agent_id == agent.agent_id else existing
                for existing in state.agents
            ),
        ),
        (_event(action, MoveToOutcome.MOVED),),
    )


def _target_from_payload(payload: dict[str, object]) -> Position | None:
    x = payload.get("x")
    y = payload.get("y")
    if type(x) is not int or type(y) is not int:
        return None
    return Position(x, y)


def _find_agent(state: SessionState, agent_id: AgentId) -> Agent | None:
    return next(
        (agent for agent in state.agents if agent.agent_id == agent_id),
        None,
    )


def _event(action: Action, outcome: MoveToOutcome) -> TurnEvent:
    return TurnEvent(action.tick, action.agent_id, action.kind, outcome.value)
