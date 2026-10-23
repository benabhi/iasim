"""Per-tick evolution of agent needs."""

from __future__ import annotations

from dataclasses import replace

from iasim.domain.actions import ActionKind
from iasim.domain.agents import Agent, AgentAttributes, AgentStatus
from iasim.domain.session import SessionState
from iasim.domain.turns import ResolvedAction

_CENTI = 100
_ACTIVITY_FACTORS: dict[ActionKind, int] = {
    ActionKind.MOVE: 1000,
    ActionKind.MOVE_TO: 1000,
    ActionKind.GATHER: 1200,
    ActionKind.PICKUP: 1000,
    ActionKind.DROP: 1000,
    ActionKind.EAT: 500,
    ActionKind.DRINK: 500,
    ActionKind.FILL: 1000,
    ActionKind.CRAFT: 1200,
    ActionKind.BUILD: 1200,
    ActionKind.USE_ITEM: 1200,
    ActionKind.TRADE: 1200,
    ActionKind.ATTACK: 1500,
    ActionKind.WAIT: 500,
}
_REST_ACTIVITY = 500
_SLEEP_ACTIVITY = 300


def apply_needs_tick(
    state: SessionState,
    resolved_actions: tuple[ResolvedAction, ...],
    ambient_temperature_centi: int = 22 * _CENTI,
) -> SessionState:
    """Evolve hunger, thirst, energy, and slow health recovery for one tick."""
    actions_by_agent = {action.agent_id: action.kind for action in resolved_actions}
    agents: list[Agent] = []
    for agent in state.agents:
        if not agent.is_alive:
            agents.append(agent)
            continue
        action_kind = actions_by_agent.get(agent.agent_id)
        activity = (
            _SLEEP_ACTIVITY
            if agent.status is AgentStatus.SLEEPING
            else _ACTIVITY_FACTORS[action_kind]
            if action_kind is not None
            else _REST_ACTIVITY
        )
        attributes = _evolve_attributes(
            agent.attributes,
            activity,
            ambient_temperature_centi,
        )
        agents.append(replace(agent, attributes=attributes))
    return replace(state, agents=tuple(agents))


def _evolve_attributes(
    attributes: AgentAttributes,
    activity: int,
    ambient_temperature_centi: int,
) -> AgentAttributes:
    endurance_factor = 1000 - 30 * (attributes.endurance - 5)
    heat_factor = 1000 + max(
        0,
        (ambient_temperature_centi - 20 * _CENTI) * 1000 // (20 * _CENTI),
    )
    hunger_delta = (35 * activity * endurance_factor) // 1_000_000
    thirst_delta = (60 * activity * heat_factor) // 1_000_000
    energy_delta = (25 * activity) // 1000
    health_delta = 0
    if (
        attributes.health_centi < 100 * _CENTI
        and attributes.hunger_centi < 70 * _CENTI
        and attributes.thirst_centi < 70 * _CENTI
        and attributes.energy_centi > 20 * _CENTI
        and 36 * _CENTI <= attributes.body_temperature_centi <= 38 * _CENTI
    ):
        health_delta = 1

    return replace(
        attributes,
        health_centi=min(100 * _CENTI, attributes.health_centi + health_delta),
        hunger_centi=min(100 * _CENTI, attributes.hunger_centi + hunger_delta),
        thirst_centi=min(100 * _CENTI, attributes.thirst_centi + thirst_delta),
        energy_centi=max(0, attributes.energy_centi - energy_delta),
    )
