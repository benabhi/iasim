"""Deterministic melee attack resolution and the shared combat formulas."""

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
BLEEDING_CHANCE = 0.25


class CombatOutcome(StrEnum):
    """Stable outcomes for melee attacks."""

    HIT = "hit"
    MISSED = "missed"
    KILLED = "killed"
    OUT_OF_RANGE = "out_of_range"
    INVALID_TARGET = "invalid_target"
    UNKNOWN_AGENT = "unknown_agent"


def distance_between(first: Agent, second: Agent) -> int:
    """Return the Chebyshev distance between two agents."""
    return max(
        abs(first.position.x - second.position.x),
        abs(first.position.y - second.position.y),
    )


def hit_probability(attacker: Agent, defender: Agent, distance: int) -> float:
    """Return the SRS hit chance for one attack at ``distance``.

    Distance is measured in cells; adjacent melee uses one, a thrown stone uses
    the real distance.
    """
    if distance < 1:
        raise ValueError(f"distance must be positive, got {distance}")
    attacker_dexterity = max(
        0,
        attacker.attributes.dexterity - dexterity_penalty(attacker.attributes),
    )
    defender_dexterity = max(
        0,
        defender.attributes.dexterity - dexterity_penalty(defender.attributes),
    )
    return max(
        MIN_HIT_CHANCE,
        min(
            MAX_HIT_CHANCE,
            0.65 + 0.04 * (attacker_dexterity - defender_dexterity) - 0.10 * (distance - 1),
        ),
    )


def roll_damage(attacker: Agent, rng: DeterministicRng, base_damage: int) -> int:
    """Return the SRS damage for one successful hit with ``base_damage``."""
    strength = max(
        0,
        attacker.attributes.strength - strength_penalty(attacker.attributes),
    )
    return max(1, base_damage + strength // 2 + rng.randint(-1, 1))


def apply_hit(
    state: SessionState,
    action: Action,
    attacker: Agent,
    target: Agent,
    rng: DeterministicRng,
    *,
    base_damage: int,
    cause: str,
) -> tuple[SessionState, bool]:
    """Apply damage, bleeding, and death for one hit.

    Returns the new state, with the advanced RNG, and whether the target died.
    ``cause`` is recorded on the corpse when the hit is fatal.
    """
    damage = roll_damage(attacker, rng, base_damage)
    health = max(0, target.attributes.health_centi - damage * 100)
    dead = health == 0
    bleeding = target.bleeding or (not dead and rng.chance(BLEEDING_CHANCE))
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
                cause=cause,
                killer_id=attacker.agent_id,
            ),
        )
    return (
        replace(
            state,
            agents=updated_agents,
            corpses=corpses,
            rng_state=rng.state,
        ),
        dead,
    )


def combat_events(action: Action, outcome: str, betrayal: bool) -> tuple[TurnEvent, ...]:
    """Return the primary outcome first, then the optional betrayal annotation.

    Attacking an ally is always allowed; the annotation exists only so the
    operator and the future social metrics can see it (RF-806).
    """
    primary = TurnEvent(action.tick, action.agent_id, action.kind, outcome)
    if not betrayal:
        return (primary,)
    return (primary, TurnEvent(action.tick, action.agent_id, action.kind, BETRAYAL))


def resolve_attack(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Resolve one adjacent melee attack using the SRS combat formula."""
    payload = action.payload_dict()
    target_id = payload.get("target_id")
    if not isinstance(target_id, str) or not target_id:
        return state, combat_events(action, CombatOutcome.INVALID_TARGET.value, False)

    attacker = _find_agent(state, action.agent_id)
    if attacker is None:
        return state, combat_events(action, CombatOutcome.UNKNOWN_AGENT.value, False)
    target_agent_id = AgentId(target_id)
    target = _find_agent(state, target_agent_id)
    if target is None or target.agent_id == attacker.agent_id or not target.is_alive:
        return state, combat_events(action, CombatOutcome.INVALID_TARGET.value, False)

    distance = distance_between(attacker, target)
    if distance != 1:
        return state, combat_events(action, CombatOutcome.OUT_OF_RANGE.value, False)

    rng = DeterministicRng.from_state(state.rng_state)
    betrayal = is_allied(state.alliances, attacker.agent_id, target.agent_id)
    if not rng.chance(hit_probability(attacker, target, distance)):
        return (
            replace(state, rng_state=rng.state),
            combat_events(action, CombatOutcome.MISSED.value, betrayal),
        )

    state, dead = apply_hit(
        state,
        action,
        attacker,
        target,
        rng,
        base_damage=max(FIST_DAMAGE, attacker.weapon_damage),
        cause="attack",
    )
    outcome = CombatOutcome.KILLED if dead else CombatOutcome.HIT
    return state, combat_events(action, outcome.value, betrayal)


def combat_resolvers() -> dict[ActionKind, ActionResolver]:
    """Return the melee combat resolver for a TurnEngine."""
    return {ActionKind.ATTACK: resolve_attack}


def _find_agent(state: SessionState, agent_id: AgentId) -> Agent | None:
    return next(
        (agent for agent in state.agents if agent.agent_id == agent_id),
        None,
    )
