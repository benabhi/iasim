"""Deterministic adjacent melee attack resolution."""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum

from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent, AgentStatus
from iasim.domain.alliances import BETRAYAL, is_allied
from iasim.domain.corpse import Corpse
from iasim.domain.identifiers import AgentId
from iasim.domain.items import Equipment, Inventory
from iasim.domain.rng import DeterministicRng
from iasim.domain.session import SessionState
from iasim.domain.status import dexterity_penalty, strength_penalty
from iasim.domain.turns import ActionResolver, TurnEvent

FIST_DAMAGE = 2
MIN_HIT_CHANCE = 0.25
MAX_HIT_CHANCE = 0.95


class CombatOutcome(StrEnum):
    """Stable outcomes for melee attacks."""

    HIT = "hit"
    MISSED = "missed"
    KILLED = "killed"
    OUT_OF_RANGE = "out_of_range"
    INVALID_TARGET = "invalid_target"
    UNKNOWN_AGENT = "unknown_agent"


def resolve_attack(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Resolve one adjacent melee attack using the SRS combat formula."""
    payload = action.payload_dict()
    target_id = payload.get("target_id")
    if not isinstance(target_id, str) or not target_id:
        return state, (_event(action, CombatOutcome.INVALID_TARGET),)

    attacker = _find_agent(state, action.agent_id)
    if attacker is None:
        return state, (_event(action, CombatOutcome.UNKNOWN_AGENT),)
    target_agent_id = AgentId(target_id)
    target = _find_agent(state, target_agent_id)
    if target is None or target.agent_id == attacker.agent_id or not target.is_alive:
        return state, (_event(action, CombatOutcome.INVALID_TARGET),)

    distance = max(
        abs(attacker.position.x - target.position.x),
        abs(attacker.position.y - target.position.y),
    )
    if distance != 1:
        return state, (_event(action, CombatOutcome.OUT_OF_RANGE),)

    attacker_dexterity = max(
        0,
        attacker.attributes.dexterity - dexterity_penalty(attacker.attributes),
    )
    defender_dexterity = max(
        0,
        target.attributes.dexterity - dexterity_penalty(target.attributes),
    )
    hit_probability = max(
        MIN_HIT_CHANCE,
        min(
            MAX_HIT_CHANCE,
            0.65 + 0.04 * (attacker_dexterity - defender_dexterity) - 0.10 * (distance - 1),
        ),
    )
    rng = DeterministicRng.from_state(state.rng_state)
    # Attacking an ally is always allowed; it only records a betrayal annotation
    # for the operator and the future social metrics (RF-806).
    betrayal = is_allied(state.alliances, attacker.agent_id, target.agent_id)
    if not rng.chance(hit_probability):
        return (
            replace(state, rng_state=rng.state),
            _events(action, CombatOutcome.MISSED, betrayal),
        )

    strength = max(
        0,
        attacker.attributes.strength - strength_penalty(attacker.attributes),
    )
    damage = max(
        1,
        max(FIST_DAMAGE, attacker.weapon_damage) + strength // 2 + rng.randint(-1, 1),
    )
    health = max(0, target.attributes.health_centi - damage * 100)
    dead = health == 0
    bleeding = target.bleeding or (not dead and rng.chance(0.25))
    attributes = replace(target.attributes, health_centi=health)
    updated_target = replace(
        target,
        attributes=attributes,
        inventory=Inventory.for_strength(target.attributes.strength) if dead else target.inventory,
        equipment=Equipment() if dead else target.equipment,
        status=AgentStatus.DEAD if dead else target.status,
        sleep_until_tick=None if dead else target.sleep_until_tick,
        bleeding=bleeding,
    )
    updated_agents = tuple(
        updated_target if agent.agent_id == target.agent_id else agent for agent in state.agents
    )
    corpses = state.corpses
    if dead:
        corpses = (
            *corpses,
            Corpse.from_agent(
                target,
                tick=action.tick,
                cause="attack",
                killer_id=attacker.agent_id,
            ),
        )
    outcome = CombatOutcome.KILLED if dead else CombatOutcome.HIT
    return (
        replace(
            state,
            agents=updated_agents,
            corpses=corpses,
            rng_state=rng.state,
        ),
        _events(action, outcome, betrayal),
    )


def combat_resolvers() -> dict[ActionKind, ActionResolver]:
    """Return the melee combat resolver for a TurnEngine."""
    return {ActionKind.ATTACK: resolve_attack}


def _event(action: Action, outcome: CombatOutcome) -> TurnEvent:
    return TurnEvent(action.tick, action.agent_id, action.kind, outcome.value)


def _events(
    action: Action,
    outcome: CombatOutcome,
    betrayal: bool,
) -> tuple[TurnEvent, ...]:
    """Return the combat outcome first, then the optional betrayal annotation."""
    primary = _event(action, outcome)
    if not betrayal:
        return (primary,)
    return (primary, TurnEvent(action.tick, action.agent_id, action.kind, BETRAYAL))


def _find_agent(state: SessionState, agent_id: AgentId) -> Agent | None:
    return next(
        (agent for agent in state.agents if agent.agent_id == agent_id),
        None,
    )
