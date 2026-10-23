"""Tier-one and workbench-tier-two crafting action resolution."""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum
from typing import TYPE_CHECKING

from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.items import InventoryError
from iasim.domain.session import SessionState
from iasim.domain.turns import ActionResolver, TurnEvent
from iasim.domain.world import StructureKind

if TYPE_CHECKING:
    from iasim.crafting.catalog import Catalog


STATION_DISTANCE = 1


class CraftingOutcome(StrEnum):
    """Stable outcomes for crafting actions."""

    CRAFTED = "crafted"
    UNKNOWN_AGENT = "unknown_agent"
    INVALID_TARGET = "invalid_target"
    UNKNOWN_RECIPE = "unknown_recipe"
    STATION_REQUIRED = "station_required"
    MISSING_INGREDIENTS = "missing_ingredients"
    INVENTORY_FULL = "inventory_full"


def crafting_resolvers(catalog: Catalog) -> dict[ActionKind, ActionResolver]:
    """Return the crafting resolver using ``catalog`` recipe metadata."""

    def craft(state: SessionState, action: Action) -> tuple[SessionState, tuple[TurnEvent, ...]]:
        return resolve_craft(state, action, catalog)

    return {ActionKind.CRAFT: craft}


def resolve_craft(
    state: SessionState,
    action: Action,
    catalog: Catalog,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Consume exact ingredients and create the recipe output atomically."""
    recipe_id = action.payload_dict().get("recipe_id")
    if not isinstance(recipe_id, str) or not recipe_id:
        return state, (_event(action, CraftingOutcome.INVALID_TARGET),)
    agent = _find_agent(state, action.agent_id)
    if agent is None:
        return state, (_event(action, CraftingOutcome.UNKNOWN_AGENT),)
    recipe = catalog.recipes.get(recipe_id)
    if recipe is None:
        return state, (_event(action, CraftingOutcome.UNKNOWN_RECIPE),)
    if recipe.level == 2 and not _has_workbench(state, agent.position):
        return state, (_event(action, CraftingOutcome.STATION_REQUIRED),)

    for item_id, quantity in recipe.ingredients:
        stack = agent.inventory.stack_for(str(item_id))
        if stack is None or stack.quantity < quantity:
            return state, (_event(action, CraftingOutcome.MISSING_INGREDIENTS),)

    output = catalog.item(str(recipe.output))
    try:
        inventory = agent.inventory
        for item_id, quantity in recipe.ingredients:
            inventory = inventory.remove(str(item_id), quantity)
        inventory = inventory.add_quantity(output.definition, recipe.output_quantity)
    except InventoryError:
        return state, (_event(action, CraftingOutcome.INVENTORY_FULL),)

    return (
        _replace_agent(state, replace(agent, inventory=inventory)),
        (_event(action, CraftingOutcome.CRAFTED),),
    )


def _has_workbench(state: SessionState, position: Position) -> bool:
    return any(
        structure.kind is StructureKind.WORKBENCH
        and max(
            abs(structure.position.x - position.x),
            abs(structure.position.y - position.y),
        )
        <= STATION_DISTANCE
        for structure in state.structures
    )


def _replace_agent(state: SessionState, agent: Agent) -> SessionState:
    return replace(
        state,
        agents=tuple(
            agent if existing.agent_id == agent.agent_id else existing for existing in state.agents
        ),
    )


def _find_agent(state: SessionState, agent_id: AgentId) -> Agent | None:
    return next(
        (agent for agent in state.agents if agent.agent_id == agent_id),
        None,
    )


def _event(action: Action, outcome: CraftingOutcome) -> TurnEvent:
    return TurnEvent(action.tick, action.agent_id, action.kind, outcome.value)
