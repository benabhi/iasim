"""Pure deterministic primitives and models for the IASim domain."""

from __future__ import annotations

from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent, AgentAttributes, AgentProfile, AgentStatus
from iasim.domain.clock import DayPhase, SimulationClock
from iasim.domain.geometry import Position
from iasim.domain.hashing import canonical_state_hash
from iasim.domain.identifiers import AgentId, ItemId
from iasim.domain.items import (
    Equipment,
    EquipSlot,
    GroundItem,
    Inventory,
    InventoryError,
    ItemDefinition,
    ItemKind,
    ItemSpec,
    ItemStack,
)
from iasim.domain.movement import (
    MovementOutcome,
    movement_resolvers,
    resolve_move,
    resolve_wait,
)
from iasim.domain.needs import apply_needs_tick
from iasim.domain.rng import DeterministicRng, roll_d6
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.turns import (
    ActionRejectedError,
    ActionResolver,
    ResolvedAction,
    TickEffect,
    TurnEngine,
    TurnError,
    TurnEvent,
    TurnResult,
    TurnStateError,
    initiative,
)
from iasim.domain.world import Structure, StructureKind

__all__ = [
    "Action",
    "ActionKind",
    "ActionRejectedError",
    "ActionResolver",
    "Agent",
    "AgentAttributes",
    "AgentId",
    "AgentProfile",
    "AgentStatus",
    "DayPhase",
    "DeterministicRng",
    "EquipSlot",
    "Equipment",
    "GroundItem",
    "Inventory",
    "InventoryError",
    "ItemDefinition",
    "ItemId",
    "ItemKind",
    "ItemSpec",
    "ItemStack",
    "MovementOutcome",
    "Position",
    "ResolvedAction",
    "SessionState",
    "SimulationClock",
    "Structure",
    "StructureKind",
    "TickEffect",
    "TileType",
    "TurnEngine",
    "TurnError",
    "TurnEvent",
    "TurnResult",
    "TurnStateError",
    "WorldMap",
    "apply_needs_tick",
    "canonical_state_hash",
    "initiative",
    "movement_resolvers",
    "resolve_move",
    "resolve_wait",
    "roll_d6",
]
