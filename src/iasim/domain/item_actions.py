"""Gather, ground-item, food, drink, and waterskin action resolvers."""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum
from typing import TYPE_CHECKING

from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.items import (
    EquipSlot,
    GroundItem,
    Inventory,
    InventoryError,
    ItemKind,
    ItemStack,
)
from iasim.domain.session import SessionState
from iasim.domain.turns import ActionResolver, TurnEvent

if TYPE_CHECKING:
    from iasim.crafting.catalog import Catalog


INTERACTION_DISTANCE = 1
WATER_RESTORE = 10


class ItemActionOutcome(StrEnum):
    """Stable outcomes for resource and consumable actions."""

    GATHERED = "gathered"
    PICKED_UP = "picked_up"
    DROPPED = "dropped"
    ATE = "ate"
    DRANK = "drank"
    FILLED = "filled"
    UNKNOWN_AGENT = "unknown_agent"
    INVALID_TARGET = "invalid_target"
    OUT_OF_BOUNDS = "out_of_bounds"
    NOT_IN_RANGE = "not_in_range"
    NO_RESOURCE = "no_resource"
    UNKNOWN_RESOURCE = "unknown_resource"
    TOOL_REQUIRED = "tool_required"
    INVENTORY_FULL = "inventory_full"
    NO_ITEM = "no_item"
    AMBIGUOUS_ITEM = "ambiguous_item"
    MISSING_ITEM = "missing_item"
    INVALID_QUANTITY = "invalid_quantity"
    NOT_FOOD = "not_food"
    NOT_DRINKABLE = "not_drinkable"
    NOT_CONTAINER = "not_container"
    EMPTY = "empty"
    ALREADY_FULL = "already_full"
    NO_WATER = "no_water"


def item_action_resolvers(catalog: Catalog) -> dict[ActionKind, ActionResolver]:
    """Return resource and consumable resolvers using ``catalog`` metadata."""

    def gather(state: SessionState, action: Action) -> tuple[SessionState, tuple[TurnEvent, ...]]:
        return resolve_gather(state, action, catalog)

    def pickup(state: SessionState, action: Action) -> tuple[SessionState, tuple[TurnEvent, ...]]:
        return resolve_pickup(state, action)

    def drop(state: SessionState, action: Action) -> tuple[SessionState, tuple[TurnEvent, ...]]:
        return resolve_drop(state, action)

    def eat(state: SessionState, action: Action) -> tuple[SessionState, tuple[TurnEvent, ...]]:
        return resolve_eat(state, action, catalog)

    def drink(state: SessionState, action: Action) -> tuple[SessionState, tuple[TurnEvent, ...]]:
        return resolve_drink(state, action, catalog)

    def fill(state: SessionState, action: Action) -> tuple[SessionState, tuple[TurnEvent, ...]]:
        return resolve_fill(state, action, catalog)

    return {
        ActionKind.GATHER: gather,
        ActionKind.PICKUP: pickup,
        ActionKind.DROP: drop,
        ActionKind.EAT: eat,
        ActionKind.DRINK: drink,
        ActionKind.FILL: fill,
    }


def resolve_gather(
    state: SessionState,
    action: Action,
    catalog: Catalog,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Gather a manual or tool-gated resource from an adjacent tile.

    ``node_id`` selects a catalog resource id on the target tile. Without it,
    the first manual resource is selected, falling back to the first catalog
    resource when every option requires a tool.
    """
    payload = action.payload_dict()
    target = _target_from_payload(payload)
    if target is None:
        return state, (_event(action, ItemActionOutcome.INVALID_TARGET),)
    if not state.world.contains(target):
        return state, (_event(action, ItemActionOutcome.OUT_OF_BOUNDS),)
    agent = _find_agent(state, action.agent_id)
    if agent is None:
        return state, (_event(action, ItemActionOutcome.UNKNOWN_AGENT),)
    if not _is_interactable(agent.position, target):
        return state, (_event(action, ItemActionOutcome.NOT_IN_RANGE),)

    node_id = payload.get("node_id")
    if node_id is not None and (not isinstance(node_id, str) or not node_id):
        return state, (_event(action, ItemActionOutcome.INVALID_TARGET),)

    resources = catalog.resources_for_tile(state.world.tile_at(target))
    if not resources:
        return state, (_event(action, ItemActionOutcome.NO_RESOURCE),)
    if node_id is not None:
        resource = next(
            (candidate for candidate in resources if candidate.resource_id == node_id),
            None,
        )
        if resource is None:
            return state, (_event(action, ItemActionOutcome.UNKNOWN_RESOURCE),)
    else:
        resource = next(
            (candidate for candidate in resources if candidate.required_tool is None),
            resources[0],
        )

    if resource.required_tool is not None:
        tool = agent.equipment.item(EquipSlot.HAND)
        if tool is None or tool.item_id != resource.required_tool:
            return state, (_event(action, ItemActionOutcome.TOOL_REQUIRED),)

    spec = catalog.item(str(resource.item_id))
    try:
        inventory = agent.inventory.add_quantity(spec.definition, resource.quantity)
    except InventoryError:
        return state, (_event(action, ItemActionOutcome.INVENTORY_FULL),)

    return (
        _replace_agent(state, replace(agent, inventory=inventory)),
        (_event(action, ItemActionOutcome.GATHERED),),
    )


def resolve_pickup(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Pick up one ground-item stack from the current or an adjacent tile."""
    payload = action.payload_dict()
    target = _target_from_payload(payload)
    if target is None:
        return state, (_event(action, ItemActionOutcome.INVALID_TARGET),)
    if not state.world.contains(target):
        return state, (_event(action, ItemActionOutcome.OUT_OF_BOUNDS),)
    agent = _find_agent(state, action.agent_id)
    if agent is None:
        return state, (_event(action, ItemActionOutcome.UNKNOWN_AGENT),)
    if not _is_interactable(agent.position, target):
        return state, (_event(action, ItemActionOutcome.NOT_IN_RANGE),)

    item_id = payload.get("item_id")
    if item_id is not None and (not isinstance(item_id, str) or not item_id):
        return state, (_event(action, ItemActionOutcome.INVALID_TARGET),)

    candidates = [
        ground
        for ground in state.ground_items
        if ground.position == target
        and (item_id is None or ground.stack.definition.item_id == item_id)
    ]
    if not candidates:
        return state, (_event(action, ItemActionOutcome.NO_ITEM),)
    if item_id is None and len({ground.stack.definition.item_id for ground in candidates}) > 1:
        return state, (_event(action, ItemActionOutcome.AMBIGUOUS_ITEM),)

    picked = candidates[0]
    try:
        inventory = agent.inventory.add(picked.stack)
    except InventoryError:
        return state, (_event(action, ItemActionOutcome.INVENTORY_FULL),)

    remaining = tuple(ground for ground in state.ground_items if ground is not picked)
    new_state = replace(
        state,
        agents=tuple(
            replace(agent, inventory=inventory) if existing.agent_id == agent.agent_id else existing
            for existing in state.agents
        ),
        ground_items=remaining,
    )
    return new_state, (_event(action, ItemActionOutcome.PICKED_UP),)


def resolve_drop(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Drop a requested quantity of one inventory item at the agent position."""
    payload = action.payload_dict()
    item_id = payload.get("item_id")
    if not isinstance(item_id, str) or not item_id:
        return state, (_event(action, ItemActionOutcome.INVALID_TARGET),)
    quantity = payload.get("qty", 1)
    if type(quantity) is not int or quantity < 1:
        return state, (_event(action, ItemActionOutcome.INVALID_QUANTITY),)

    agent = _find_agent(state, action.agent_id)
    if agent is None:
        return state, (_event(action, ItemActionOutcome.UNKNOWN_AGENT),)
    existing = agent.inventory.stack_for(item_id)
    if existing is None:
        return state, (_event(action, ItemActionOutcome.MISSING_ITEM),)
    if quantity > existing.quantity:
        return state, (_event(action, ItemActionOutcome.INVALID_QUANTITY),)

    try:
        inventory = agent.inventory.remove(item_id, quantity)
    except InventoryError:
        return state, (_event(action, ItemActionOutcome.MISSING_ITEM),)

    dropped_charges = existing.charges if quantity == existing.quantity else 0
    dropped = ItemStack(existing.definition, quantity, charges=dropped_charges)
    new_state = replace(
        state,
        agents=tuple(
            replace(agent, inventory=inventory) if current.agent_id == agent.agent_id else current
            for current in state.agents
        ),
        ground_items=(*state.ground_items, GroundItem(agent.position, dropped)),
    )
    return new_state, (_event(action, ItemActionOutcome.DROPPED),)


def resolve_eat(
    state: SessionState,
    action: Action,
    catalog: Catalog,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Consume one unit of food and apply its catalog restoration values."""
    item_id = action.payload_dict().get("item_id")
    if not isinstance(item_id, str) or not item_id:
        return state, (_event(action, ItemActionOutcome.INVALID_TARGET),)
    agent = _find_agent(state, action.agent_id)
    if agent is None:
        return state, (_event(action, ItemActionOutcome.UNKNOWN_AGENT),)
    if agent.inventory.stack_for(item_id) is None:
        return state, (_event(action, ItemActionOutcome.MISSING_ITEM),)

    spec = catalog.item(item_id)
    if spec.kind is not ItemKind.FOOD:
        return state, (_event(action, ItemActionOutcome.NOT_FOOD),)

    inventory = agent.inventory.remove(item_id, 1)
    attributes = replace(
        agent.attributes,
        hunger_centi=max(0, agent.attributes.hunger_centi - spec.hunger_restore * 100),
        thirst_centi=max(0, agent.attributes.thirst_centi - spec.thirst_restore * 100),
    )
    return (
        _replace_agent(state, replace(agent, inventory=inventory, attributes=attributes)),
        (_event(action, ItemActionOutcome.ATE),),
    )


def resolve_drink(
    state: SessionState,
    action: Action,
    catalog: Catalog,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Drink from an adjacent fresh-water tile or from a waterskin charge."""
    payload = action.payload_dict()
    item_id = payload.get("item_id")
    target = _target_from_payload(payload)
    if item_id is not None and target is not None:
        return state, (_event(action, ItemActionOutcome.INVALID_TARGET),)
    if item_id is None and target is None:
        return state, (_event(action, ItemActionOutcome.INVALID_TARGET),)

    agent = _find_agent(state, action.agent_id)
    if agent is None:
        return state, (_event(action, ItemActionOutcome.UNKNOWN_AGENT),)

    if item_id is not None:
        if not isinstance(item_id, str) or not item_id:
            return state, (_event(action, ItemActionOutcome.INVALID_TARGET),)
        stack = agent.inventory.stack_for(item_id)
        if stack is None:
            return state, (_event(action, ItemActionOutcome.MISSING_ITEM),)
        spec = catalog.item(item_id)
        if spec.water_charges < 1:
            return state, (_event(action, ItemActionOutcome.NOT_CONTAINER),)
        if stack.charges < 1:
            return state, (_event(action, ItemActionOutcome.EMPTY),)
        inventory = _replace_stack(agent.inventory, stack.with_charges(stack.charges - 1))
        return (
            _restore_thirst(state, agent, inventory),
            (_event(action, ItemActionOutcome.DRANK),),
        )

    assert target is not None
    if not state.world.contains(target):
        return state, (_event(action, ItemActionOutcome.OUT_OF_BOUNDS),)
    if not _is_interactable(agent.position, target):
        return state, (_event(action, ItemActionOutcome.NOT_IN_RANGE),)
    if not state.world.tile_at(target).drinkable:
        return state, (_event(action, ItemActionOutcome.NOT_DRINKABLE),)

    return (
        _restore_thirst(state, agent, agent.inventory),
        (_event(action, ItemActionOutcome.DRANK),),
    )


def resolve_fill(
    state: SessionState,
    action: Action,
    catalog: Catalog,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Fill a waterskin from an adjacent fresh-water tile."""
    item_id = action.payload_dict().get("item_id")
    if not isinstance(item_id, str) or not item_id:
        return state, (_event(action, ItemActionOutcome.INVALID_TARGET),)
    agent = _find_agent(state, action.agent_id)
    if agent is None:
        return state, (_event(action, ItemActionOutcome.UNKNOWN_AGENT),)
    stack = agent.inventory.stack_for(item_id)
    if stack is None:
        return state, (_event(action, ItemActionOutcome.MISSING_ITEM),)

    spec = catalog.item(item_id)
    if spec.water_charges < 1:
        return state, (_event(action, ItemActionOutcome.NOT_CONTAINER),)
    if not _has_adjacent_fresh_water(state, agent.position):
        return state, (_event(action, ItemActionOutcome.NO_WATER),)
    if stack.charges >= spec.water_charges:
        return state, (_event(action, ItemActionOutcome.ALREADY_FULL),)

    inventory = _replace_stack(agent.inventory, stack.with_charges(spec.water_charges))
    return (
        _replace_agent(state, replace(agent, inventory=inventory)),
        (_event(action, ItemActionOutcome.FILLED),),
    )


def _target_from_payload(payload: dict[str, object]) -> Position | None:
    x = payload.get("x")
    y = payload.get("y")
    if type(x) is not int or type(y) is not int:
        return None
    return Position(x, y)


def _is_interactable(origin: Position, target: Position) -> bool:
    return max(abs(target.x - origin.x), abs(target.y - origin.y)) <= INTERACTION_DISTANCE


def _has_adjacent_fresh_water(state: SessionState, position: Position) -> bool:
    for y in range(position.y - 1, position.y + 2):
        for x in range(position.x - 1, position.x + 2):
            target = Position(x, y)
            if state.world.contains(target) and state.world.tile_at(target).drinkable:
                return True
    return False


def _restore_thirst(state: SessionState, agent: Agent, inventory: Inventory) -> SessionState:
    attributes = replace(
        agent.attributes,
        thirst_centi=max(0, agent.attributes.thirst_centi - WATER_RESTORE * 100),
    )
    return _replace_agent(
        state,
        replace(agent, inventory=inventory, attributes=attributes),
    )


def _replace_stack(inventory: Inventory, replacement: ItemStack) -> Inventory:
    stacks = tuple(
        replacement if stack.definition.item_id == replacement.definition.item_id else stack
        for stack in inventory.stacks
    )
    return replace(inventory, stacks=stacks)


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


def _event(action: Action, outcome: ItemActionOutcome) -> TurnEvent:
    return TurnEvent(action.tick, action.agent_id, action.kind, outcome.value)
