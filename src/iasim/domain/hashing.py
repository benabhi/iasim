"""Canonical deterministic hashing of session state."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from iasim.domain.agents import Agent
from iasim.domain.alliances import Alliance
from iasim.domain.corpse import Corpse
from iasim.domain.items import GroundItem, ItemStack
from iasim.domain.resources import ResourceNode
from iasim.domain.session import SessionState
from iasim.domain.trades import TradeOffer
from iasim.domain.world import Structure


def canonical_state_hash(state: SessionState) -> str:
    """Return the SHA-256 hash of a canonical session state."""
    encoded = json.dumps(
        canonical_state_payload(state),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_state_payload(state: SessionState) -> dict[str, Any]:
    """Return a canonical JSON-serializable payload for a session state."""
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
            "ambient_temperature_centi": state.weather.ambient_temperature_centi,
        },
        "agents": [
            _agent_payload(agent)
            for agent in sorted(state.agents, key=lambda agent: agent.agent_id)
        ],
        "structures": [
            _structure_payload(structure)
            for structure in sorted(
                state.structures,
                key=lambda structure: (
                    structure.kind.value,
                    structure.position.y,
                    structure.position.x,
                ),
            )
        ],
        "ground_items": [
            _ground_item_payload(item)
            for item in sorted(
                state.ground_items,
                key=lambda item: (
                    item.position.y,
                    item.position.x,
                    item.stack.definition.item_id,
                    item.stack.definition.unit_weight_grams,
                    item.stack.definition.stackable,
                    item.stack.definition.max_stack,
                    item.stack.quantity,
                    item.stack.charges,
                ),
            )
        ],
        "resource_nodes": [
            _resource_node_payload(node)
            for node in sorted(
                state.resource_nodes,
                key=lambda node: (
                    node.position.y,
                    node.position.x,
                    node.resource_id,
                ),
            )
        ],
        "corpses": [
            _corpse_payload(corpse)
            for corpse in sorted(state.corpses, key=lambda corpse: corpse.corpse_id)
        ],
        "alliances": [
            _alliance_payload(alliance)
            for alliance in sorted(state.alliances, key=lambda alliance: alliance.alliance_id)
        ],
        "trades": [
            _trade_payload(trade)
            for trade in sorted(state.trades, key=lambda trade: trade.trade_id)
        ],
    }


def _agent_payload(agent: Agent) -> dict[str, Any]:
    return {
        "id": agent.agent_id,
        "x": agent.position.x,
        "y": agent.position.y,
        "status": agent.status.value,
        "sleep_until_tick": agent.sleep_until_tick,
        "bleeding": agent.bleeding,
        "memory": _memory_payload(agent),
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
        "inventory": {
            "max_slots": agent.inventory.max_slots,
            "max_weight_grams": agent.inventory.max_weight_grams,
            "stacks": [
                _stack_payload(stack)
                for stack in sorted(
                    agent.inventory.stacks,
                    key=lambda stack: stack.definition.item_id,
                )
            ],
        },
        "equipment": [
            {"slot": slot.value, "item_id": spec.item_id}
            for slot, spec in sorted(agent.equipment.items, key=lambda entry: entry[0].value)
        ],
    }


def _memory_payload(agent: Agent) -> dict[str, Any]:
    return {
        "tiles": [
            {
                "x": entry.position.x,
                "y": entry.position.y,
                "tile": entry.tile.value,
                "last_seen_tick": entry.last_seen_tick,
                "resources": list(entry.resources),
                "structure": entry.structure.value if entry.structure is not None else None,
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
    }


def _stack_payload(stack: ItemStack) -> dict[str, Any]:
    return {
        "item_id": stack.definition.item_id,
        "unit_weight_grams": stack.definition.unit_weight_grams,
        "stackable": stack.definition.stackable,
        "max_stack": stack.definition.max_stack,
        "quantity": stack.quantity,
        "charges": stack.charges,
    }


def _structure_payload(structure: Structure) -> dict[str, Any]:
    return {
        "kind": structure.kind.value,
        "x": structure.position.x,
        "y": structure.position.y,
        "fuel": structure.fuel,
        "lit": structure.lit,
    }


def _ground_item_payload(item: GroundItem) -> dict[str, Any]:
    return {
        "x": item.position.x,
        "y": item.position.y,
        **_stack_payload(item.stack),
    }


def _corpse_payload(corpse: Corpse) -> dict[str, Any]:
    return {
        "corpse_id": corpse.corpse_id,
        "agent_id": corpse.agent_id,
        "x": corpse.position.x,
        "y": corpse.position.y,
        "death_tick": corpse.death_tick,
        "cause": corpse.cause,
        "killer_id": corpse.killer_id,
        "inventory": [
            _stack_payload(stack)
            for stack in sorted(
                corpse.inventory.stacks,
                key=lambda stack: stack.definition.item_id,
            )
        ],
        "equipment": [
            {"slot": slot.value, "item_id": spec.item_id}
            for slot, spec in sorted(corpse.equipment.items, key=lambda entry: entry[0].value)
        ],
    }


def _resource_node_payload(node: ResourceNode) -> dict[str, Any]:
    return {
        "x": node.position.x,
        "y": node.position.y,
        "resource_id": node.resource_id,
        "remaining": node.remaining,
        "capacity": node.capacity,
        "regrow_at_tick": node.regrow_at_tick,
    }


def _alliance_payload(alliance: Alliance) -> dict[str, Any]:
    return {
        "alliance_id": alliance.alliance_id,
        "members": [str(member) for member in alliance.members],
        "status": alliance.status.value,
        "proposed_by": str(alliance.proposed_by),
        "offered_tick": alliance.offered_tick,
        "accepted_tick": alliance.accepted_tick,
        "broken_tick": alliance.broken_tick,
    }


def _trade_payload(trade: TradeOffer) -> dict[str, Any]:
    return {
        "trade_id": trade.trade_id,
        "proposer_id": str(trade.proposer_id),
        "target_id": str(trade.target_id),
        "offered_tick": trade.offered_tick,
        "offer": [{"item_id": item_id, "qty": qty} for item_id, qty in trade.offer],
        "request": [{"item_id": item_id, "qty": qty} for item_id, qty in trade.request],
        "status": trade.status.value,
        "resolved_tick": trade.resolved_tick,
    }
