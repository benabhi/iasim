"""Deterministic flee movement away from a combat target."""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum

from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.session import SessionState
from iasim.domain.turns import ActionResolver, TurnEvent
from iasim.domain.world import StructureKind

FLEE_ENERGY_COST_CENTI = 100
_DIRECTIONS = (
    (-1, -1),
    (0, -1),
    (1, -1),
    (-1, 0),
    (1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
)


class FleeOutcome(StrEnum):
    """Stable outcomes for fleeing."""

    FLED = "fled"
    BLOCKED = "blocked"
    INVALID_TARGET = "invalid_target"
    UNKNOWN_AGENT = "unknown_agent"


def resolve_flee(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Move up to two cells away from a living target."""
    target_id = action.payload_dict().get("target_id")
    if not isinstance(target_id, str) or not target_id:
        return state, (_event(action, FleeOutcome.INVALID_TARGET),)

    agent = _find_agent(state, action.agent_id)
    if agent is None:
        return state, (_event(action, FleeOutcome.UNKNOWN_AGENT),)
    target = _find_agent(state, AgentId(target_id))
    if target is None or target.agent_id == agent.agent_id or not target.is_alive:
        return state, (_event(action, FleeOutcome.INVALID_TARGET),)

    first = _best_step(
        state, agent, target.position, min_distance=_distance(agent.position, target.position) + 1
    )
    if first is None:
        return state, (_event(action, FleeOutcome.BLOCKED),)

    second = _best_step(
        state,
        replace(agent, position=first),
        target.position,
        min_distance=_distance(first, target.position) + 1,
    )
    destination = second if second is not None else first
    energy = max(0, agent.attributes.energy_centi - FLEE_ENERGY_COST_CENTI)
    updated = replace(
        agent,
        position=destination,
        attributes=replace(agent.attributes, energy_centi=energy),
    )
    return (
        replace(
            state,
            agents=tuple(
                updated if current.agent_id == agent.agent_id else current
                for current in state.agents
            ),
        ),
        (_event(action, FleeOutcome.FLED),),
    )


def flee_resolvers() -> dict[ActionKind, ActionResolver]:
    """Return the flee action resolver."""
    return {ActionKind.FLEE: resolve_flee}


def _best_step(
    state: SessionState,
    agent: Agent,
    target: Position,
    *,
    min_distance: int,
) -> Position | None:
    candidates: list[Position] = []
    current_distance = _distance(agent.position, target)
    for dx, dy in _DIRECTIONS:
        x = agent.position.x + dx
        y = agent.position.y + dy
        if not (0 <= x < state.world.width and 0 <= y < state.world.height):
            continue
        position = Position(x, y)
        distance = _distance(position, target)
        if distance <= current_distance or distance < min_distance:
            continue
        if _can_stand(state, agent.agent_id, position):
            candidates.append(position)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda position: (
            -_distance(position, target),
            position.y,
            position.x,
        ),
    )


def _can_stand(state: SessionState, agent_id: AgentId, position: Position) -> bool:
    if not state.world.contains(position):
        return False
    if not state.world.tile_at(position).walkable:
        return False
    structure = next(
        (candidate for candidate in state.structures if candidate.position == position),
        None,
    )
    if structure is not None and structure.kind is not StructureKind.SHELTER:
        return False
    return not any(
        other.agent_id != agent_id and other.is_alive and other.position == position
        for other in state.agents
    )


def _distance(first: Position, second: Position) -> int:
    return max(abs(first.x - second.x), abs(first.y - second.y))


def _event(action: Action, outcome: FleeOutcome) -> TurnEvent:
    return TurnEvent(action.tick, action.agent_id, action.kind, outcome.value)


def _find_agent(state: SessionState, agent_id: AgentId) -> Agent | None:
    return next(
        (agent for agent in state.agents if agent.agent_id == agent_id),
        None,
    )
