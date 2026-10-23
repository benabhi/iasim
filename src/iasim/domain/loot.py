"""Loot resolver for corpses left by dead agents."""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum

from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent
from iasim.domain.identifiers import AgentId
from iasim.domain.items import Equipment, Inventory, InventoryError, ItemStack
from iasim.domain.session import SessionState
from iasim.domain.turns import ActionResolver, TurnEvent

LOOT_DISTANCE = 1


class LootOutcome(StrEnum):
    """Stable outcomes for corpse looting."""

    LOOTED = "looted"
    EMPTY = "empty"
    INVALID_TARGET = "invalid_target"
    OUT_OF_RANGE = "out_of_range"
    UNKNOWN_AGENT = "unknown_agent"
    INVENTORY_FULL = "inventory_full"


def resolve_loot(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Move all remaining loot from an adjacent corpse to the actor."""
    payload = action.payload_dict()
    corpse_id = payload.get("corpse_id")
    if not isinstance(corpse_id, str) or not corpse_id:
        return state, (_event(action, LootOutcome.INVALID_TARGET),)

    agent = _find_agent(state, action.agent_id)
    if agent is None:
        return state, (_event(action, LootOutcome.UNKNOWN_AGENT),)
    corpse = next(
        (candidate for candidate in state.corpses if candidate.corpse_id == corpse_id),
        None,
    )
    if corpse is None:
        return state, (_event(action, LootOutcome.INVALID_TARGET),)
    distance = max(
        abs(agent.position.x - corpse.position.x),
        abs(agent.position.y - corpse.position.y),
    )
    if distance > LOOT_DISTANCE:
        return state, (_event(action, LootOutcome.OUT_OF_RANGE),)
    if not corpse.has_items:
        return state, (_event(action, LootOutcome.EMPTY),)

    inventory = agent.inventory
    try:
        for stack in corpse.inventory.stacks:
            inventory = inventory.add(stack)
        for _, spec in corpse.equipment.items:
            inventory = inventory.add(ItemStack(spec.definition, 1))
    except InventoryError:
        return state, (_event(action, LootOutcome.INVENTORY_FULL),)

    updated_agents = tuple(
        replace(agent, inventory=inventory) if current.agent_id == agent.agent_id else current
        for current in state.agents
    )
    emptied = replace(
        corpse,
        inventory=Inventory(
            max_slots=corpse.inventory.max_slots,
            max_weight_grams=corpse.inventory.max_weight_grams,
        ),
        equipment=Equipment(),
    )
    updated_corpses = tuple(
        emptied if current.corpse_id == corpse.corpse_id else current for current in state.corpses
    )
    return (
        replace(state, agents=updated_agents, corpses=updated_corpses),
        (_event(action, LootOutcome.LOOTED),),
    )


def loot_resolvers() -> dict[ActionKind, ActionResolver]:
    """Return the corpse looting resolver for a TurnEngine."""
    return {ActionKind.LOOT: resolve_loot}


def _event(action: Action, outcome: LootOutcome) -> TurnEvent:
    return TurnEvent(action.tick, action.agent_id, action.kind, outcome.value)


def _find_agent(state: SessionState, agent_id: AgentId) -> Agent | None:
    return next(
        (agent for agent in state.agents if agent.agent_id == agent_id),
        None,
    )
