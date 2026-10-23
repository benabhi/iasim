"""Rest and sleep actions with deterministic energy recovery."""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum

from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent, AgentStatus
from iasim.domain.clock import MINUTES_PER_DAY, SimulationClock
from iasim.domain.session import SessionState
from iasim.domain.turns import ActionResolver, TurnEvent

MAX_ENERGY_CENTI = 100 * 100
REST_RECOVERY_CENTI = 3 * 100
SLEEP_RECOVERY_CENTI = 5 * 100
_DEFAULT_SLEEP_UNTIL = "energy_full"
_DAWN_MINUTE = 5 * 60


class SleepOutcome(StrEnum):
    """Stable outcomes for rest and sleep."""

    RESTED = "rested"
    SLEEPING = "sleeping"
    UNKNOWN_AGENT = "unknown_agent"
    INVALID_UNTIL = "invalid_until"


def rest_sleep_resolvers() -> dict[ActionKind, ActionResolver]:
    """Return resolvers for resting and sleeping."""
    return {
        ActionKind.REST: resolve_rest,
        ActionKind.SLEEP: resolve_sleep,
    }


def resolve_rest(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Recover a small amount of energy during a one-tick rest."""
    agent = _find_agent(state, action.agent_id)
    if agent is None:
        return state, (_event(action, SleepOutcome.UNKNOWN_AGENT),)
    attributes = replace(
        agent.attributes,
        energy_centi=min(MAX_ENERGY_CENTI, agent.attributes.energy_centi + REST_RECOVERY_CENTI),
    )
    return (
        _replace_agent(state, replace(agent, attributes=attributes)),
        (_event(action, SleepOutcome.RESTED),),
    )


def resolve_sleep(
    state: SessionState,
    action: Action,
) -> tuple[SessionState, tuple[TurnEvent, ...]]:
    """Set an agent sleeping until its requested wake condition."""
    agent = _find_agent(state, action.agent_id)
    if agent is None:
        return state, (_event(action, SleepOutcome.UNKNOWN_AGENT),)
    until = action.payload_dict().get("until", _DEFAULT_SLEEP_UNTIL)
    target = _sleep_until_tick(state, until, agent.attributes.energy_centi)
    if target is None:
        return state, (_event(action, SleepOutcome.INVALID_UNTIL),)
    sleeping = replace(
        agent,
        status=AgentStatus.SLEEPING,
        sleep_until_tick=target,
    )
    return _replace_agent(state, sleeping), (_event(action, SleepOutcome.SLEEPING),)


def apply_sleep_tick(state: SessionState) -> SessionState:
    """Recover sleeping agents' energy and wake them at their target tick."""
    agents: list[Agent] = []
    for agent in state.agents:
        if agent.status is not AgentStatus.SLEEPING or not agent.is_alive:
            agents.append(agent)
            continue
        attributes = replace(
            agent.attributes,
            energy_centi=min(
                MAX_ENERGY_CENTI, agent.attributes.energy_centi + SLEEP_RECOVERY_CENTI
            ),
        )
        if agent.sleep_until_tick is not None and state.tick >= agent.sleep_until_tick:
            agents.append(
                replace(
                    agent,
                    attributes=attributes,
                    status=AgentStatus.ACTIVE,
                    sleep_until_tick=None,
                )
            )
        else:
            agents.append(replace(agent, attributes=attributes))
    return replace(state, agents=tuple(agents))


def _sleep_until_tick(
    state: SessionState,
    until: object,
    energy_centi: int,
) -> int | None:
    if until is None:
        until = _DEFAULT_SLEEP_UNTIL
    if not isinstance(until, str) or not until:
        return None
    if until == "energy_full":
        missing = max(0, MAX_ENERGY_CENTI - energy_centi)
        ticks = max(1, (missing + SLEEP_RECOVERY_CENTI - 1) // SLEEP_RECOVERY_CENTI)
        return state.tick + ticks
    if until == "dawn":
        clock = SimulationClock(state.tick_minutes)
        clock.advance(state.tick)
        minutes = (_DAWN_MINUTE - clock.minute_of_day) % MINUTES_PER_DAY
        if minutes == 0:
            minutes = MINUTES_PER_DAY
        ticks = max(1, (minutes + state.tick_minutes - 1) // state.tick_minutes)
        return state.tick + ticks
    if until.startswith("hours:"):
        raw_hours = until.removeprefix("hours:")
        if not raw_hours.isdigit() or int(raw_hours) < 1:
            return None
        duration = max(
            1,
            (int(raw_hours) * 60 + state.tick_minutes - 1) // state.tick_minutes,
        )
        return state.tick + duration
    return None


def _replace_agent(state: SessionState, agent: Agent) -> SessionState:
    return replace(
        state,
        agents=tuple(
            agent if existing.agent_id == agent.agent_id else existing for existing in state.agents
        ),
    )


def _find_agent(state: SessionState, agent_id: str) -> Agent | None:
    return next(
        (agent for agent in state.agents if agent.agent_id == agent_id),
        None,
    )


def _event(action: Action, outcome: SleepOutcome) -> TurnEvent:
    return TurnEvent(action.tick, action.agent_id, action.kind, outcome.value)
