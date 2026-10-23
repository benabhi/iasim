"""Eight-direction movement and wait resolvers."""

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

_DIRECTIONS = frozenset({-1, 0, 1})


class MovementOutcome(StrEnum):
    """Stable outcomes for movement and wait actions."""

    MOVED = "moved"
    WAITED = "waited"
    OUT_OF_BOUNDS = "out_of_bounds"
    IMPASSABLE = "impassable"
    STRUCTURE = "structure"
    OCCUPIED = "occupied"
    INVALID_DIRECTION = "invalid_direction"
    UNKNOWN_AGENT = "unknown_agent"


def resolve_move(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Move one agent by one cell in one of eight directions."""
    payload = action.payload_dict()
    dx = payload.get("dx")
    dy = payload.get("dy")
    if (
        not isinstance(dx, int)
        or isinstance(dx, bool)
        or not isinstance(dy, int)
        or isinstance(dy, bool)
        or dx not in _DIRECTIONS
        or dy not in _DIRECTIONS
        or (dx == 0 and dy == 0)
    ):
        return state, (_event(action, MovementOutcome.INVALID_DIRECTION),)

    agent = _find_agent(state, action.agent_id)
    if agent is None:
        return state, (_event(action, MovementOutcome.UNKNOWN_AGENT),)

    target_x = agent.position.x + dx
    target_y = agent.position.y + dy
    if not (0 <= target_x < state.world.width and 0 <= target_y < state.world.height):
        return state, (_event(action, MovementOutcome.OUT_OF_BOUNDS),)
    target = Position(target_x, target_y)

    structure = next(
        (item for item in state.structures if item.position == target),
        None,
    )
    if structure is not None and structure.kind is not StructureKind.SHELTER:
        return state, (_event(action, MovementOutcome.STRUCTURE),)

    if not state.world.tile_at(target).walkable:
        return state, (_event(action, MovementOutcome.IMPASSABLE),)

    if any(
        other.agent_id != agent.agent_id and other.is_alive and other.position == target
        for other in state.agents
    ):
        return state, (_event(action, MovementOutcome.OCCUPIED),)

    moved = replace(agent, position=target)
    updated_agents = tuple(
        moved if existing.agent_id == agent.agent_id else existing for existing in state.agents
    )
    return (
        replace(state, agents=updated_agents),
        (_event(action, MovementOutcome.MOVED),),
    )


def resolve_wait(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Leave the agent in place for one tick."""
    return state, (_event(action, MovementOutcome.WAITED),)


def movement_resolvers() -> dict[ActionKind, ActionResolver]:
    """Return the movement and wait resolvers for a TurnEngine."""
    return {
        ActionKind.MOVE: resolve_move,
        ActionKind.WAIT: resolve_wait,
    }


def _event(action: Action, outcome: MovementOutcome) -> TurnEvent:
    return TurnEvent(action.tick, action.agent_id, action.kind, outcome.value)


def _find_agent(state: SessionState, agent_id: AgentId) -> Agent | None:
    return next(
        (agent for agent in state.agents if agent.agent_id == agent_id),
        None,
    )
