"""Deterministic turn pipeline and action ordering."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Protocol

from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent, AgentStatus
from iasim.domain.clock import SimulationClock
from iasim.domain.hashing import canonical_state_hash
from iasim.domain.identifiers import AgentId
from iasim.domain.rng import roll_d6
from iasim.domain.session import SessionState


class TurnError(Exception):
    """Base class for turn pipeline errors."""


class ActionRejectedError(TurnError):
    """A submitted action cannot enter the current tick."""


class TurnStateError(TurnError):
    """The turn pipeline was configured or driven incorrectly."""


@dataclass(frozen=True, slots=True)
class TurnEvent:
    """A deterministic outcome emitted while resolving a tick."""

    tick: int
    agent_id: AgentId
    kind: ActionKind
    outcome: str


@dataclass(frozen=True, slots=True)
class ResolvedAction:
    """One action that was resolved in a tick."""

    agent_id: AgentId
    kind: ActionKind
    initiative: int


@dataclass(frozen=True, slots=True)
class TurnResult:
    """The result of resolving one tick.

    ``tick`` is the tick that was closed. ``state_hash`` hashes the state after
    the clock advanced to ``tick + 1``.
    """

    tick: int
    resolved_actions: tuple[ResolvedAction, ...]
    events: tuple[TurnEvent, ...]
    state_hash: str


class ActionResolver(Protocol):
    """Apply one action to a state and return the new state plus events."""

    def __call__(
        self,
        state: SessionState,
        action: Action,
    ) -> tuple[SessionState, tuple[TurnEvent, ...]]: ...


class TickEffect(Protocol):
    """Apply deterministic world or needs effects after all actions resolve."""

    def __call__(
        self,
        state: SessionState,
        resolved_actions: tuple[ResolvedAction, ...],
    ) -> SessionState: ...


def initiative(agent: Agent, seed: int, tick: int, weapon_speed: int = 0) -> int:
    """Return the SRS initiative roll for one agent and tick.

    Weapon speed is zero until equipment is modelled.
    """
    return agent.attributes.dexterity + weapon_speed + roll_d6(seed, tick, agent.agent_id)


class TurnEngine:
    """Collect one primary action per agent and resolve a tick deterministically.

    Agents without a submitted action are skipped; deadline handling belongs
    to the MCP turn queue.
    """

    def __init__(
        self,
        state: SessionState,
        *,
        resolvers: Mapping[ActionKind, ActionResolver] | None = None,
        tick_effect: TickEffect | None = None,
        clock: SimulationClock | None = None,
    ) -> None:
        self._state = state
        if clock is None:
            clock = SimulationClock(state.tick_minutes)
            clock.advance(state.tick)
        elif clock.tick_minutes != state.tick_minutes:
            raise ValueError("clock tick_minutes must match the state")
        if clock.tick != state.tick:
            raise ValueError("clock tick must match the state")
        self._clock = clock
        self._resolvers = dict(resolvers or {})
        self._tick_effect = tick_effect
        self._actions: dict[AgentId, Action] = {}

    @property
    def state(self) -> SessionState:
        """Return the current session state."""
        return self._state

    @property
    def tick(self) -> int:
        """Return the tick currently accepting actions."""
        return self._state.tick

    @property
    def clock(self) -> SimulationClock:
        """Return the simulation clock."""
        return self._clock

    @property
    def pending_agents(self) -> frozenset[AgentId]:
        """Return the agents that already submitted an action for this tick."""
        return frozenset(self._actions)

    def submit(self, action: Action) -> None:
        """Queue one primary action for the current tick."""
        if action.tick != self._state.tick:
            raise ActionRejectedError(
                f"action tick {action.tick} does not match current tick {self._state.tick}"
            )
        agent = self._find_agent(action.agent_id)
        if agent is None:
            raise ActionRejectedError(f"unknown agent {action.agent_id!r}")
        if not agent.is_alive:
            raise ActionRejectedError(f"agent {action.agent_id!r} is dead")
        if agent.status is not AgentStatus.ACTIVE:
            raise ActionRejectedError(
                f"agent {action.agent_id!r} is {agent.status.value} and cannot act"
            )
        if action.agent_id in self._actions:
            raise ActionRejectedError(f"agent {action.agent_id!r} already acted this tick")
        self._actions[action.agent_id] = action

    def remove_agent(self, agent_id: AgentId) -> None:
        """Remove an agent and its pending action without advancing the tick."""
        self._actions.pop(agent_id, None)
        if self._find_agent(agent_id) is None:
            return
        self._state = replace(
            self._state,
            agents=tuple(agent for agent in self._state.agents if agent.agent_id != agent_id),
        )

    def replace_state(self, state: SessionState) -> None:
        """Replace the state while preserving pending actions and the clock."""
        if state.tick != self._state.tick:
            raise TurnStateError("replacement state must keep the current tick")
        self._state = state

    def resolve(self) -> TurnResult:
        """Resolve the current tick in stable initiative order."""
        missing = {action.kind for action in self._actions.values()} - self._resolvers.keys()
        if missing:
            names = ", ".join(sorted(kind.value for kind in missing))
            raise TurnStateError(f"missing resolver for: {names}")

        closed_tick = self._state.tick
        entries: list[tuple[int, Action]] = []
        for action in self._actions.values():
            agent = self._find_agent(action.agent_id)
            if agent is None:
                raise TurnStateError(f"agent {action.agent_id!r} disappeared before resolution")
            entries.append((initiative(agent, self._state.seed, closed_tick), action))

        entries.sort(
            key=lambda entry: (
                -entry[0],
                entry[1].kind.order,
                entry[1].agent_id,
            )
        )

        events: list[TurnEvent] = []
        resolved: list[ResolvedAction] = []
        for action_initiative, action in entries:
            agent = self._find_agent(action.agent_id)
            if agent is None or not agent.is_alive:
                events.append(TurnEvent(closed_tick, action.agent_id, action.kind, "cancelled"))
                continue

            new_state, new_events = self._resolvers[action.kind](self._state, action)
            if not isinstance(new_state, SessionState):
                raise TurnStateError("resolver must return a SessionState")
            if new_state.tick != closed_tick:
                raise TurnStateError("resolver must not change the tick")
            self._state = new_state
            resolved.append(ResolvedAction(action.agent_id, action.kind, action_initiative))
            events.extend(new_events)

        if self._tick_effect is not None:
            new_state = self._tick_effect(self._state, tuple(resolved))
            if not isinstance(new_state, SessionState):
                raise TurnStateError("tick effect must return a SessionState")
            if new_state.tick != closed_tick:
                raise TurnStateError("tick effect must not change the tick")
            self._state = new_state

        self._clock.advance()
        self._state = replace(self._state, tick=self._clock.tick)
        self._actions.clear()
        return TurnResult(
            tick=closed_tick,
            resolved_actions=tuple(resolved),
            events=tuple(events),
            state_hash=canonical_state_hash(self._state),
        )

    def _find_agent(self, agent_id: AgentId) -> Agent | None:
        return next(
            (agent for agent in self._state.agents if agent.agent_id == agent_id),
            None,
        )
