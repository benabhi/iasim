"""Construction of fires, workbenches, and shelters."""

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
from iasim.domain.weather import WeatherKind
from iasim.domain.world import FIRE_MAX_FUEL, Structure, StructureKind

if TYPE_CHECKING:
    from iasim.crafting.catalog import Catalog


STRUCTURE_KITS: dict[StructureKind, str] = {
    StructureKind.FIRE: "camp_kit",
    StructureKind.WORKBENCH: "workbench_kit",
    StructureKind.SHELTER: "shelter_kit",
}

INTERACTION_DISTANCE = 1
FIRE_FUEL_PER_TICK = 1


class ConstructionOutcome(StrEnum):
    """Stable outcomes for construction actions."""

    BUILT = "built"
    UNKNOWN_AGENT = "unknown_agent"
    INVALID_TARGET = "invalid_target"
    UNKNOWN_STRUCTURE = "unknown_structure"
    OUT_OF_BOUNDS = "out_of_bounds"
    NOT_IN_RANGE = "not_in_range"
    OCCUPIED = "occupied"
    INVALID_TERRAIN = "invalid_terrain"
    MISSING_KIT = "missing_kit"


def construction_resolvers(catalog: Catalog) -> dict[ActionKind, ActionResolver]:
    """Return the construction resolver using ``catalog`` kit metadata."""

    def build(state: SessionState, action: Action) -> tuple[SessionState, tuple[TurnEvent, ...]]:
        return resolve_build(state, action, catalog)

    return {ActionKind.BUILD: build}


def resolve_build(
    state: SessionState,
    action: Action,
    catalog: Catalog,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Consume a kit and place a structure on an adjacent free tile."""
    payload = action.payload_dict()
    structure_id = payload.get("structure_id")
    if not isinstance(structure_id, str) or not structure_id:
        return state, (_event(action, ConstructionOutcome.INVALID_TARGET),)
    try:
        kind = StructureKind(structure_id)
    except ValueError:
        return state, (_event(action, ConstructionOutcome.UNKNOWN_STRUCTURE),)

    target = _target_from_payload(payload)
    if target is None:
        return state, (_event(action, ConstructionOutcome.INVALID_TARGET),)
    if not state.world.contains(target):
        return state, (_event(action, ConstructionOutcome.OUT_OF_BOUNDS),)
    agent = _find_agent(state, action.agent_id)
    if agent is None:
        return state, (_event(action, ConstructionOutcome.UNKNOWN_AGENT),)
    if not _is_adjacent(agent.position, target):
        return state, (_event(action, ConstructionOutcome.NOT_IN_RANGE),)
    if any(structure.position == target for structure in state.structures):
        return state, (_event(action, ConstructionOutcome.OCCUPIED),)
    if any(
        other.agent_id != agent.agent_id and other.is_alive and other.position == target
        for other in state.agents
    ):
        return state, (_event(action, ConstructionOutcome.OCCUPIED),)
    if any(ground.position == target for ground in state.ground_items):
        return state, (_event(action, ConstructionOutcome.OCCUPIED),)
    if not state.world.tile_at(target).walkable:
        return state, (_event(action, ConstructionOutcome.INVALID_TERRAIN),)

    kit_id = STRUCTURE_KITS[kind]
    kit = catalog.item(kit_id)
    if kit.structure is not kind:
        return state, (_event(action, ConstructionOutcome.UNKNOWN_STRUCTURE),)
    if agent.inventory.stack_for(kit_id) is None:
        return state, (_event(action, ConstructionOutcome.MISSING_KIT),)
    try:
        inventory = agent.inventory.remove(kit_id, 1)
    except InventoryError:
        return state, (_event(action, ConstructionOutcome.MISSING_KIT),)

    world = replace(
        state.world,
        tiles=tuple(
            kind.tile if index == target.y * state.world.width + target.x else tile
            for index, tile in enumerate(state.world.tiles)
        ),
    )
    structure = Structure(
        kind=kind,
        position=target,
        fuel=FIRE_MAX_FUEL if kind is StructureKind.FIRE else 0,
        lit=kind is StructureKind.FIRE,
    )
    new_state = replace(
        state,
        world=world,
        agents=tuple(
            replace(agent, inventory=inventory) if existing.agent_id == agent.agent_id else existing
            for existing in state.agents
        ),
        structures=(*state.structures, structure),
    )
    return new_state, (_event(action, ConstructionOutcome.BUILT),)


def advance_fires(state: SessionState) -> SessionState:
    """Consume fuel and apply rain/wind rules to every lit fire."""
    structures: list[Structure] = []
    for structure in state.structures:
        if structure.kind is not StructureKind.FIRE or not structure.lit:
            structures.append(structure)
            continue
        sheltered = _has_adjacent_shelter(state.structures, structure.position)
        if state.weather.kind in {WeatherKind.RAIN, WeatherKind.STORM} and not sheltered:
            structures.append(replace(structure, lit=False))
            continue
        wind_cost = 1 if state.weather.wind >= 8 and not sheltered else 0
        fuel = max(0, structure.fuel - FIRE_FUEL_PER_TICK - wind_cost)
        structures.append(replace(structure, fuel=fuel, lit=fuel > 0))
    return replace(state, structures=tuple(structures))


def _has_adjacent_shelter(structures: tuple[Structure, ...], position: Position) -> bool:
    return any(
        structure.kind is StructureKind.SHELTER and _is_adjacent(structure.position, position)
        for structure in structures
    )


def _is_adjacent(origin: Position, target: Position) -> bool:
    return max(abs(target.x - origin.x), abs(target.y - origin.y)) == INTERACTION_DISTANCE


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


def _event(action: Action, outcome: ConstructionOutcome) -> TurnEvent:
    return TurnEvent(action.tick, action.agent_id, action.kind, outcome.value)
