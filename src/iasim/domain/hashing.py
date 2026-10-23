"""Canonical deterministic hashing of session state."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from iasim.domain.agents import Agent
from iasim.domain.items import GroundItem, ItemStack
from iasim.domain.session import SessionState
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
    }


def _agent_payload(agent: Agent) -> dict[str, Any]:
    return {
        "id": agent.agent_id,
        "x": agent.position.x,
        "y": agent.position.y,
        "status": agent.status.value,
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
    }


def _ground_item_payload(item: GroundItem) -> dict[str, Any]:
    return {
        "x": item.position.x,
        "y": item.position.y,
        **_stack_payload(item.stack),
    }
