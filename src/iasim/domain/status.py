"""Deterministic survival status thresholds and exposure damage."""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum

from iasim.domain.agents import Agent, AgentAttributes, AgentStatus
from iasim.domain.session import SessionState

HUNGER_THRESHOLD_CENTI = 70 * 100
THIRST_THRESHOLD_CENTI = 70 * 100
ENERGY_THRESHOLD_CENTI = 20 * 100
HYPOTHERMIA_CENTI = 35 * 100
HEAT_STROKE_CENTI = 40 * 100
WET_THRESHOLD_CENTI = 60 * 100

HUNGRY_DAMAGE_CENTI = 2
STARVATION_DAMAGE_CENTI = 20
DEHYDRATION_DAMAGE_CENTI = 40
HYPOTHERMIA_DAMAGE_CENTI = 20
HEAT_STROKE_DAMAGE_CENTI = 30
HEAT_STROKE_ENERGY_DAMAGE_CENTI = 20


class Condition(StrEnum):
    """Serializable condition tags exposed in observations and the UI."""

    HUNGRY = "hungry"
    STARVING = "starving"
    THIRSTY = "thirsty"
    DEHYDRATED = "dehydrated"
    EXHAUSTED = "exhausted"
    HYPOTHERMIA = "hypothermia"
    HEAT_STROKE = "heat_stroke"
    WET = "wet"
    DEAD = "dead"


def status_tags(agent: Agent) -> tuple[Condition, ...]:
    """Return the ordered condition tags for an agent."""
    tags: list[Condition] = []
    attributes = agent.attributes
    if attributes.hunger_centi >= 100 * 100:
        tags.append(Condition.STARVING)
    elif attributes.hunger_centi > HUNGER_THRESHOLD_CENTI:
        tags.append(Condition.HUNGRY)
    if attributes.thirst_centi >= 100 * 100:
        tags.append(Condition.DEHYDRATED)
    elif attributes.thirst_centi > THIRST_THRESHOLD_CENTI:
        tags.append(Condition.THIRSTY)
    if attributes.energy_centi < ENERGY_THRESHOLD_CENTI:
        tags.append(Condition.EXHAUSTED)
    if attributes.body_temperature_centi < HYPOTHERMIA_CENTI:
        tags.append(Condition.HYPOTHERMIA)
    elif attributes.body_temperature_centi > HEAT_STROKE_CENTI:
        tags.append(Condition.HEAT_STROKE)
    if attributes.wetness_centi > WET_THRESHOLD_CENTI:
        tags.append(Condition.WET)
    if agent.status is AgentStatus.DEAD:
        tags.append(Condition.DEAD)
    return tuple(tags)


def strength_penalty(attributes: AgentAttributes) -> int:
    """Return the status penalty applied to effective strength."""
    if attributes.hunger_centi >= 100 * 100:
        return 2
    if attributes.hunger_centi > HUNGER_THRESHOLD_CENTI:
        return 1
    return 0


def dexterity_penalty(attributes: AgentAttributes) -> int:
    """Return the status penalty applied to effective dexterity."""
    penalty = 0
    if attributes.thirst_centi > THIRST_THRESHOLD_CENTI:
        penalty += 1
    if attributes.energy_centi < ENERGY_THRESHOLD_CENTI:
        penalty += 1
    if attributes.body_temperature_centi < HYPOTHERMIA_CENTI:
        penalty += 2
    return penalty


def vision_penalty(attributes: AgentAttributes) -> int:
    """Return the status penalty applied to effective vision."""
    penalty = 0
    if attributes.thirst_centi >= 100 * 100:
        penalty += 1
    if attributes.energy_centi < ENERGY_THRESHOLD_CENTI:
        penalty += 1
    return penalty


def health_damage_centi(attributes: AgentAttributes) -> int:
    """Return the health loss for one tick of exposure conditions."""
    damage = 0
    if attributes.hunger_centi >= 100 * 100:
        damage += STARVATION_DAMAGE_CENTI
    elif attributes.hunger_centi > HUNGER_THRESHOLD_CENTI:
        damage += HUNGRY_DAMAGE_CENTI
    if attributes.thirst_centi >= 100 * 100:
        damage += DEHYDRATION_DAMAGE_CENTI
    if attributes.body_temperature_centi < HYPOTHERMIA_CENTI:
        damage += HYPOTHERMIA_DAMAGE_CENTI
    elif attributes.body_temperature_centi > HEAT_STROKE_CENTI:
        damage += HEAT_STROKE_DAMAGE_CENTI
    return damage


def energy_damage_centi(attributes: AgentAttributes) -> int:
    """Return the energy loss for one tick of exposure conditions."""
    if attributes.body_temperature_centi > HEAT_STROKE_CENTI:
        return HEAT_STROKE_ENERGY_DAMAGE_CENTI
    return 0


def apply_status_tick(state: SessionState) -> SessionState:
    """Apply exposure damage and mark agents dead when health reaches zero."""
    agents: list[Agent] = []
    for agent in state.agents:
        if not agent.is_alive:
            agents.append(agent)
            continue
        damage = health_damage_centi(agent.attributes)
        energy_damage = energy_damage_centi(agent.attributes)
        health = max(0, agent.attributes.health_centi - damage)
        energy = max(0, agent.attributes.energy_centi - energy_damage)
        attributes = replace(
            agent.attributes,
            health_centi=health,
            energy_centi=energy,
        )
        status = AgentStatus.DEAD if health == 0 else agent.status
        agents.append(replace(agent, attributes=attributes, status=status))
    return replace(state, agents=tuple(agents))
