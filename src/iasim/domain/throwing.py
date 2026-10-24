"""Deterministic thrown-stone attacks with range and line of sight."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from enum import StrEnum
from functools import partial

from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent
from iasim.domain.alliances import is_allied
from iasim.domain.combat import (
    apply_hit,
    combat_events,
    distance_between,
    hit_probability,
)
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.rng import DeterministicRng
from iasim.domain.session import SessionState
from iasim.domain.tiles import WorldMap
from iasim.domain.turns import ActionResolver, TurnEvent

THROW_RANGE = 4
THROWN_STONE_ITEM_ID = "stone"
THROWN_STONE_DAMAGE = 3

# Injected by the application layer so the domain stays free of the tcod adapter.
LineOfSight = Callable[[WorldMap, Position, Position, int], bool]


class ThrowOutcome(StrEnum):
    """Stable outcomes for thrown-stone attacks."""

    HIT = "hit"
    MISSED = "missed"
    KILLED = "killed"
    OUT_OF_RANGE = "out_of_range"
    INVALID_TARGET = "invalid_target"
    UNKNOWN_AGENT = "unknown_agent"
    NO_LINE_OF_SIGHT = "no_line_of_sight"
    INVALID_ITEM = "invalid_item"
    NOT_THROWABLE = "not_throwable"
    NOT_IN_INVENTORY = "not_in_inventory"


def resolve_throw(
    state: SessionState,
    action: Action,
    *,
    line_of_sight: LineOfSight,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Throw one stone at a visible living target within four cells.

    The stone is consumed as soon as the throw executes, even if it misses.
    A rejected throw never consumes anything.
    """
    payload = action.payload_dict()
    target_id = payload.get("target_id")
    item_id = payload.get("item_id")
    if not isinstance(target_id, str) or not target_id:
        return state, combat_events(action, ThrowOutcome.INVALID_TARGET.value, False)
    if not isinstance(item_id, str) or not item_id:
        return state, combat_events(action, ThrowOutcome.INVALID_ITEM.value, False)

    attacker = _find_agent(state, action.agent_id)
    if attacker is None:
        return state, combat_events(action, ThrowOutcome.UNKNOWN_AGENT.value, False)
    target = _find_agent(state, AgentId(target_id))
    if target is None or target.agent_id == attacker.agent_id or not target.is_alive:
        return state, combat_events(action, ThrowOutcome.INVALID_TARGET.value, False)

    distance = distance_between(attacker, target)
    if distance > THROW_RANGE:
        return state, combat_events(action, ThrowOutcome.OUT_OF_RANGE.value, False)
    if not line_of_sight(state.world, attacker.position, target.position, THROW_RANGE):
        return state, combat_events(action, ThrowOutcome.NO_LINE_OF_SIGHT.value, False)
    if item_id != THROWN_STONE_ITEM_ID:
        return state, combat_events(action, ThrowOutcome.NOT_THROWABLE.value, False)
    stack = attacker.inventory.stack_for(item_id)
    if stack is None or stack.quantity < 1:
        return state, combat_events(action, ThrowOutcome.NOT_IN_INVENTORY.value, False)

    updated_attacker = replace(attacker, inventory=attacker.inventory.remove(item_id, 1))
    state = replace(
        state,
        agents=tuple(
            updated_attacker if current.agent_id == attacker.agent_id else current
            for current in state.agents
        ),
    )
    betrayal = is_allied(state.alliances, attacker.agent_id, target.agent_id)
    rng = DeterministicRng.from_state(state.rng_state)
    if not rng.chance(hit_probability(attacker, target, distance)):
        return (
            replace(state, rng_state=rng.state),
            combat_events(action, ThrowOutcome.MISSED.value, betrayal),
        )

    state, dead = apply_hit(
        state,
        action,
        updated_attacker,
        target,
        rng,
        base_damage=THROWN_STONE_DAMAGE,
        cause="throw",
    )
    outcome = ThrowOutcome.KILLED if dead else ThrowOutcome.HIT
    return state, combat_events(action, outcome.value, betrayal)


def throw_resolvers(line_of_sight: LineOfSight) -> dict[ActionKind, ActionResolver]:
    """Return the thrown-stone resolver bound to a line-of-sight adapter."""
    return {ActionKind.THROW: partial(resolve_throw, line_of_sight=line_of_sight)}


def _find_agent(state: SessionState, agent_id: AgentId) -> Agent | None:
    return next(
        (agent for agent in state.agents if agent.agent_id == agent_id),
        None,
    )
