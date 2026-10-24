"""Canonical snapshot serialization and atomic snapshot files.

A snapshot stores the complete canonical session state. Items are referenced by
catalog id and rebuilt from the catalog on load, so a reloaded state must hash
identically to the state that produced the snapshot. Incompatible payload
versions are rejected with a clear error instead of being partially loaded.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from iasim.crafting import Catalog
from iasim.domain.agents import Agent, AgentAttributes, AgentStatus
from iasim.domain.alliances import Alliance, AllianceStatus
from iasim.domain.corpse import Corpse
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId, ItemId
from iasim.domain.items import Equipment, EquipSlot, GroundItem, Inventory, ItemStack
from iasim.domain.memory import AgentMemory, Memory, MemoryEntry
from iasim.domain.resources import ResourceNode
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.trades import TradeOffer, TradeStatus
from iasim.domain.weather import WeatherKind, WeatherState
from iasim.domain.world import Structure, StructureKind
from iasim.errors import PersistenceError
from iasim.protocol import SCHEMA_VERSION

SNAPSHOTS_DIRNAME = "snapshots"


class SnapshotError(PersistenceError):
    """A snapshot is unreadable, malformed, or of an incompatible schema."""


def state_to_payload(state: SessionState) -> dict[str, Any]:
    """Serialize a complete canonical state to JSON-ready data."""
    return {
        "seed": state.seed,
        "tick": state.tick,
        "rng_state": state.rng_state,
        "tick_minutes": state.tick_minutes,
        "world": {
            "width": state.world.width,
            "height": state.world.height,
            "tiles": [tile.value for tile in state.world.tiles],
        },
        "weather": {
            "kind": state.weather.kind.value,
            "remaining_ticks": state.weather.remaining_ticks,
            "wind": state.weather.wind,
        },
        "agents": [_agent_payload(agent) for agent in state.agents],
        "structures": [
            {
                "kind": structure.kind.value,
                "x": structure.position.x,
                "y": structure.position.y,
                "fuel": structure.fuel,
                "lit": structure.lit,
            }
            for structure in state.structures
        ],
        "ground_items": [
            {
                "x": item.position.x,
                "y": item.position.y,
                **_stack_payload(item.stack),
            }
            for item in state.ground_items
        ],
        "resource_nodes": [
            {
                "x": node.position.x,
                "y": node.position.y,
                "resource_id": node.resource_id,
                "remaining": node.remaining,
                "capacity": node.capacity,
                "regrow_at_tick": node.regrow_at_tick,
            }
            for node in state.resource_nodes
        ],
        "corpses": [
            {
                "corpse_id": corpse.corpse_id,
                "agent_id": corpse.agent_id,
                "x": corpse.position.x,
                "y": corpse.position.y,
                "death_tick": corpse.death_tick,
                "cause": corpse.cause,
                "killer_id": corpse.killer_id,
                "inventory": _inventory_payload(corpse.inventory),
                "equipment": _equipment_payload(corpse.equipment),
            }
            for corpse in state.corpses
        ],
        "alliances": [
            {
                "alliance_id": alliance.alliance_id,
                "members": [str(member) for member in alliance.members],
                "status": alliance.status.value,
                "proposed_by": alliance.proposed_by,
                "offered_tick": alliance.offered_tick,
                "accepted_tick": alliance.accepted_tick,
                "broken_tick": alliance.broken_tick,
            }
            for alliance in state.alliances
        ],
        "trades": [
            {
                "trade_id": trade.trade_id,
                "proposer_id": trade.proposer_id,
                "target_id": trade.target_id,
                "offered_tick": trade.offered_tick,
                "offer": _lot_payload(trade.offer),
                "request": _lot_payload(trade.request),
                "status": trade.status.value,
                "resolved_tick": trade.resolved_tick,
            }
            for trade in state.trades
        ],
    }


def state_from_payload(payload: Mapping[str, Any], catalog: Catalog) -> SessionState:
    """Rebuild a canonical state from ``state_to_payload`` output."""
    try:
        world_data = payload["world"]
        world = WorldMap(
            width=int(world_data["width"]),
            height=int(world_data["height"]),
            tiles=tuple(TileType(tile) for tile in world_data["tiles"]),
        )
        weather_data = payload["weather"]
        state = SessionState(
            seed=int(payload["seed"]),
            tick=int(payload["tick"]),
            rng_state=int(payload["rng_state"]),
            tick_minutes=int(payload["tick_minutes"]),
            world=world,
            weather=WeatherState(
                kind=WeatherKind(weather_data["kind"]),
                remaining_ticks=int(weather_data["remaining_ticks"]),
                wind=int(weather_data["wind"]),
            ),
            agents=tuple(_agent_from_payload(item, catalog) for item in payload["agents"]),
            structures=tuple(
                Structure(
                    StructureKind(item["kind"]),
                    Position(int(item["x"]), int(item["y"])),
                    fuel=int(item["fuel"]),
                    lit=bool(item["lit"]),
                )
                for item in payload["structures"]
            ),
            ground_items=tuple(
                GroundItem(
                    Position(int(item["x"]), int(item["y"])),
                    _stack_from_payload(item, catalog),
                )
                for item in payload["ground_items"]
            ),
            resource_nodes=tuple(
                ResourceNode(
                    Position(int(item["x"]), int(item["y"])),
                    str(item["resource_id"]),
                    int(item["remaining"]),
                    int(item["capacity"]),
                    int(item["regrow_at_tick"]) if item.get("regrow_at_tick") is not None else None,
                )
                for item in payload["resource_nodes"]
            ),
            corpses=tuple(_corpse_from_payload(item, catalog) for item in payload["corpses"]),
            alliances=tuple(
                Alliance(
                    alliance_id=str(item["alliance_id"]),
                    members=(
                        AgentId(item["members"][0]),
                        AgentId(item["members"][1]),
                    ),
                    status=AllianceStatus(item["status"]),
                    proposed_by=AgentId(item["proposed_by"]),
                    offered_tick=int(item["offered_tick"]),
                    accepted_tick=(
                        int(item["accepted_tick"])
                        if item.get("accepted_tick") is not None
                        else None
                    ),
                    broken_tick=(
                        int(item["broken_tick"]) if item.get("broken_tick") is not None else None
                    ),
                )
                for item in payload["alliances"]
            ),
            trades=tuple(
                TradeOffer(
                    trade_id=str(item["trade_id"]),
                    proposer_id=AgentId(item["proposer_id"]),
                    target_id=AgentId(item["target_id"]),
                    offered_tick=int(item["offered_tick"]),
                    offer=_lot_from_payload(item["offer"]),
                    request=_lot_from_payload(item["request"]),
                    status=TradeStatus(item["status"]),
                    resolved_tick=(
                        int(item["resolved_tick"])
                        if item.get("resolved_tick") is not None
                        else None
                    ),
                )
                for item in payload["trades"]
            ),
        )
    except KeyError as exc:
        raise SnapshotError(f"snapshot is missing field {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise SnapshotError(f"snapshot contains invalid data: {exc}") from exc
    return state


def write_snapshot(directory: Path, state: SessionState) -> Path:
    """Write one snapshot atomically and return its path."""
    directory = Path(directory)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "tick": state.tick,
        "state": state_to_payload(state),
    }
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"tick_{state.tick:06d}.json"
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise SnapshotError(f"cannot write snapshot {path}: {exc}") from exc
    return path


def read_snapshot(path: Path, catalog: Catalog) -> SessionState:
    """Load one snapshot, rejecting incompatible schema versions."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SnapshotError(f"cannot read snapshot {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"snapshot {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, Mapping):
        raise SnapshotError(f"snapshot {path} is not a JSON object")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SnapshotError(
            f"snapshot {path} has schema_version {version!r}; this server reads {SCHEMA_VERSION!r}"
        )
    state_data = data.get("state")
    if not isinstance(state_data, Mapping):
        raise SnapshotError(f"snapshot {path} has no state payload")
    return state_from_payload(state_data, catalog)


def _agent_payload(agent: Agent) -> dict[str, Any]:
    return {
        "agent_id": agent.agent_id,
        "x": agent.position.x,
        "y": agent.position.y,
        "status": agent.status.value,
        "sleep_until_tick": agent.sleep_until_tick,
        "bleeding": agent.bleeding,
        "attributes": {
            "health_centi": agent.attributes.health_centi,
            "hunger_centi": agent.attributes.hunger_centi,
            "thirst_centi": agent.attributes.thirst_centi,
            "energy_centi": agent.attributes.energy_centi,
            "wetness_centi": agent.attributes.wetness_centi,
            "body_temperature_centi": agent.attributes.body_temperature_centi,
            "vision": agent.attributes.vision,
            "strength": agent.attributes.strength,
            "dexterity": agent.attributes.dexterity,
            "endurance": agent.attributes.endurance,
        },
        "inventory": _inventory_payload(agent.inventory),
        "equipment": _equipment_payload(agent.equipment),
        "memory": {
            "tiles": [
                {
                    "x": entry.position.x,
                    "y": entry.position.y,
                    "tile": entry.tile.value,
                    "last_seen_tick": entry.last_seen_tick,
                    "resources": list(entry.resources),
                    "structure": (entry.structure.value if entry.structure is not None else None),
                    "stale": entry.stale,
                }
                for entry in agent.memory.tiles
            ],
            "agents": [
                {
                    "agent_id": entry.agent_id,
                    "x": entry.position.x,
                    "y": entry.position.y,
                    "last_seen_tick": entry.last_seen_tick,
                    "stale": entry.stale,
                }
                for entry in agent.memory.agents
            ],
        },
    }


def _agent_from_payload(payload: Mapping[str, Any], catalog: Catalog) -> Agent:
    attributes = payload["attributes"]
    memory = payload["memory"]
    return Agent(
        AgentId(payload["agent_id"]),
        Position(int(payload["x"]), int(payload["y"])),
        attributes=AgentAttributes(
            health_centi=int(attributes["health_centi"]),
            hunger_centi=int(attributes["hunger_centi"]),
            thirst_centi=int(attributes["thirst_centi"]),
            energy_centi=int(attributes["energy_centi"]),
            wetness_centi=int(attributes["wetness_centi"]),
            body_temperature_centi=int(attributes["body_temperature_centi"]),
            vision=int(attributes["vision"]),
            strength=int(attributes["strength"]),
            dexterity=int(attributes["dexterity"]),
            endurance=int(attributes["endurance"]),
        ),
        inventory=_inventory_from_payload(payload["inventory"], catalog),
        equipment=_equipment_from_payload(payload["equipment"], catalog),
        status=AgentStatus(payload["status"]),
        sleep_until_tick=(
            int(payload["sleep_until_tick"])
            if payload.get("sleep_until_tick") is not None
            else None
        ),
        memory=Memory(
            tiles=tuple(
                MemoryEntry(
                    Position(int(item["x"]), int(item["y"])),
                    TileType(item["tile"]),
                    int(item["last_seen_tick"]),
                    resources=tuple(str(resource) for resource in item["resources"]),
                    structure=(
                        StructureKind(item["structure"])
                        if item.get("structure") is not None
                        else None
                    ),
                    stale=bool(item["stale"]),
                )
                for item in memory["tiles"]
            ),
            agents=tuple(
                AgentMemory(
                    AgentId(item["agent_id"]),
                    Position(int(item["x"]), int(item["y"])),
                    int(item["last_seen_tick"]),
                    stale=bool(item["stale"]),
                )
                for item in memory["agents"]
            ),
        ),
        bleeding=bool(payload["bleeding"]),
    )


def _corpse_from_payload(payload: Mapping[str, Any], catalog: Catalog) -> Corpse:
    return Corpse(
        corpse_id=str(payload["corpse_id"]),
        agent_id=AgentId(payload["agent_id"]),
        position=Position(int(payload["x"]), int(payload["y"])),
        inventory=_inventory_from_payload(payload["inventory"], catalog),
        equipment=_equipment_from_payload(payload["equipment"], catalog),
        death_tick=int(payload["death_tick"]),
        cause=str(payload["cause"]),
        killer_id=(AgentId(payload["killer_id"]) if payload.get("killer_id") is not None else None),
    )


def _inventory_payload(inventory: Inventory) -> dict[str, Any]:
    return {
        "max_slots": inventory.max_slots,
        "max_weight_grams": inventory.max_weight_grams,
        "stacks": [
            _stack_payload(stack)
            for stack in sorted(
                inventory.stacks,
                key=lambda stack: stack.definition.item_id,
            )
        ],
    }


def _inventory_from_payload(payload: Mapping[str, Any], catalog: Catalog) -> Inventory:
    return Inventory(
        stacks=tuple(_stack_from_payload(item, catalog) for item in payload["stacks"]),
        max_slots=int(payload["max_slots"]),
        max_weight_grams=int(payload["max_weight_grams"]),
    )


def _stack_payload(stack: ItemStack) -> dict[str, Any]:
    return {
        "item_id": stack.definition.item_id,
        "quantity": stack.quantity,
        "charges": stack.charges,
    }


def _stack_from_payload(payload: Mapping[str, Any], catalog: Catalog) -> ItemStack:
    definition = catalog.item(str(payload["item_id"])).definition
    return ItemStack(
        definition,
        int(payload["quantity"]),
        charges=int(payload["charges"]),
    )


def _equipment_payload(equipment: Equipment) -> list[dict[str, str | None]]:
    return [
        {"slot": slot.value, "item_id": spec.item_id}
        for slot, spec in sorted(equipment.items, key=lambda entry: entry[0].value)
    ]


def _equipment_from_payload(payload: Any, catalog: Catalog) -> Equipment:
    items: list[tuple[EquipSlot, Any]] = []
    for entry in payload:
        slot = EquipSlot(str(entry["slot"]))
        spec = catalog.item(str(entry["item_id"]))
        if spec.equip_slot is not slot:
            raise ValueError(f"item {spec.item_id!r} belongs in {spec.equip_slot!r}, not {slot!r}")
        items.append((slot, spec))
    return Equipment(items=tuple(items))


def _lot_payload(lot: tuple[tuple[ItemId, int], ...]) -> list[dict[str, Any]]:
    return [{"item_id": item_id, "qty": qty} for item_id, qty in lot]


def _lot_from_payload(payload: Any) -> tuple[tuple[ItemId, int], ...]:
    return tuple((ItemId(str(item["item_id"])), int(item["qty"])) for item in payload)
