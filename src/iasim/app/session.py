"""Application session that owns turn state and serves MCP tools."""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import threading
import time
from collections.abc import Sequence
from dataclasses import replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from iasim.crafting import Catalog, load_catalog
from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent, AgentProfile, AgentStatus
from iasim.domain.climate import apply_climate_tick, effective_vision
from iasim.domain.construction import advance_fires, construction_resolvers
from iasim.domain.crafting_actions import crafting_resolvers
from iasim.domain.hashing import canonical_state_hash
from iasim.domain.identifiers import AgentId
from iasim.domain.item_actions import item_action_resolvers
from iasim.domain.items import GroundItem, ItemStack
from iasim.domain.memory import AgentMemory, MemoryEntry
from iasim.domain.movement import movement_resolvers
from iasim.domain.needs import apply_needs_tick
from iasim.domain.rng import U64_MASK
from iasim.domain.session import SessionState
from iasim.domain.sleep import apply_sleep_tick, rest_sleep_resolvers
from iasim.domain.status import (
    apply_status_tick,
    dexterity_penalty,
    status_tags,
    strength_penalty,
)
from iasim.domain.turns import (
    ActionRejectedError,
    ResolvedAction,
    TurnEngine,
    TurnResult,
)
from iasim.domain.weather import (
    DEFAULT_WEATHER_MAX_TICKS,
    DEFAULT_WEATHER_MIN_TICKS,
    WeatherState,
    advance_weather,
    apply_weather_wetness,
)
from iasim.errors import PersistenceError
from iasim.world.generation import generate_layout
from iasim.world.layout import WorldLayout
from iasim.world.pathfinding_actions import move_to_resolvers
from iasim.world.tcod_fov import compute_fov

SCHEMA_VERSION = "1.0"
MAX_NAME_LENGTH = 40
DEFAULT_TURN_TIMEOUT_MS = 60_000
MAX_AGENTS = 8


class SessionPhase(StrEnum):
    """Application lifecycle phase of the open server."""

    WAITING = "waiting"
    RUNNING = "running"
    FINISHED = "finished"


class SessionEndReason(StrEnum):
    """Why the operator stopped the session."""

    OPERATOR = "operator"


class GameSession:
    """Single deterministic session exposed to agents through the MCP layer."""

    def __init__(
        self,
        seed: int,
        *,
        tick_minutes: int = 5,
        turn_timeout_ms: int = DEFAULT_TURN_TIMEOUT_MS,
        max_agents: int | None = None,
        layout: WorldLayout | None = None,
        profiles: Sequence[AgentProfile] | None = None,
        token_path: Path | None = None,
        catalog: Catalog | None = None,
        weather_min_ticks: int = DEFAULT_WEATHER_MIN_TICKS,
        weather_max_ticks: int = DEFAULT_WEATHER_MAX_TICKS,
    ) -> None:
        if seed < 0:
            raise ValueError(f"seed must be non-negative, got {seed}")
        if turn_timeout_ms < 1:
            raise ValueError(f"turn_timeout_ms must be positive, got {turn_timeout_ms}")
        if weather_min_ticks < 1:
            raise ValueError(f"weather_min_ticks must be positive, got {weather_min_ticks}")
        if weather_max_ticks < weather_min_ticks:
            raise ValueError(
                "weather_max_ticks must be >= weather_min_ticks, "
                f"got {weather_max_ticks} and {weather_min_ticks}"
            )
        if max_agents is not None and not 1 <= max_agents <= MAX_AGENTS:
            raise ValueError(f"max_agents must be within [1, {MAX_AGENTS}], got {max_agents}")

        self._custom_layout = layout
        generated_count = max_agents if max_agents is not None else MAX_AGENTS
        self._layout = (
            layout if layout is not None else generate_layout(seed, agent_count=generated_count)
        )
        if profiles is not None:
            if max_agents is not None and len(profiles) != max_agents:
                raise ValueError(
                    f"profiles describe {len(profiles)} agents but max_agents is {max_agents}"
                )
            configured_max = len(profiles)
        elif max_agents is not None:
            configured_max = max_agents
        else:
            configured_max = len(self._layout.spawn_points)
        if not 1 <= configured_max <= MAX_AGENTS:
            raise ValueError(f"max_agents must be within [1, {MAX_AGENTS}], got {configured_max}")
        if configured_max > len(self._layout.spawn_points):
            raise ValueError(
                f"max_agents {configured_max} exceeds the {len(self._layout.spawn_points)} "
                "available spawn points"
            )

        self._spawns = self._layout.spawn_points[:configured_max]
        self._profiles = (
            tuple(profiles) if profiles is not None else tuple(AgentProfile() for _ in self._spawns)
        )
        self._turn_timeout_ms = turn_timeout_ms
        self._max_agents = configured_max
        self._token_path = token_path
        self._catalog = catalog if catalog is not None else load_catalog()
        self._weather_min_ticks = weather_min_ticks
        self._weather_max_ticks = weather_max_ticks
        self._resolvers = {
            **movement_resolvers(),
            **move_to_resolvers(),
            **item_action_resolvers(self._catalog),
            **crafting_resolvers(self._catalog),
            **construction_resolvers(self._catalog),
            **rest_sleep_resolvers(),
        }
        self._phase = SessionPhase.WAITING
        self._end_reason: SessionEndReason | None = None
        self._final_state_hash: str | None = None
        self._state = SessionState(
            seed=seed,
            tick=0,
            rng_state=seed & U64_MASK,
            world=self._layout.world,
            tick_minutes=tick_minutes,
            weather=WeatherState.initial(weather_min_ticks),
        )
        self._engine = TurnEngine(
            self._state,
            resolvers=self._resolvers,
            tick_effect=self._apply_tick_effects,
        )
        self._names: dict[AgentId, str] = {}
        self._last_results: dict[AgentId, dict[str, Any]] = {}
        self._slot_tokens: tuple[str, ...] = tuple(
            secrets.token_urlsafe(32) for _ in range(len(self._spawns))
        )
        self._token_slots: dict[str, int] = {
            token: slot for slot, token in enumerate(self._slot_tokens)
        }
        self._token_agents: dict[str, AgentId] = {}
        self._joined_slots: set[int] = set()
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        if token_path is not None:
            self._write_tokens(token_path)

    @property
    def state(self) -> SessionState:
        """Return the current session state."""
        with self._lock:
            return self._state

    @property
    def tick(self) -> int:
        """Return the current session tick."""
        with self._lock:
            return self._state.tick

    @property
    def tokens(self) -> tuple[str, ...]:
        """Return the slot tokens in spawn order for the run file and tests."""
        return self._slot_tokens

    @property
    def phase(self) -> SessionPhase:
        """Return the application lifecycle phase."""
        with self._lock:
            return self._phase

    @property
    def max_agents(self) -> int:
        """Return the number of configured agent slots."""
        return self._max_agents

    @property
    def joined_agents(self) -> int:
        """Return how many slots currently have a connected agent."""
        with self._lock:
            return len(self._joined_slots)

    @property
    def alive_agents(self) -> int:
        """Return how many connected agents are still alive."""
        with self._lock:
            return sum(1 for agent in self._state.agents if agent.is_alive)

    @property
    def is_finished(self) -> bool:
        """Return whether the operator ended the session."""
        with self._lock:
            return self._phase is SessionPhase.FINISHED

    @property
    def end_reason(self) -> SessionEndReason | None:
        """Return why the session ended, if it has ended."""
        with self._lock:
            return self._end_reason

    @property
    def final_state_hash(self) -> str | None:
        """Return the canonical hash captured when the session ended."""
        with self._lock:
            return self._final_state_hash

    def agent_id_for_token(self, token: str) -> AgentId | None:
        """Return the slot agent id for a valid token, joined or not."""
        slot = self._token_slots.get(token)
        if slot is None:
            return None
        return AgentId(f"ag_{slot + 1:02d}")

    def agent_for_token(self, token: str) -> AgentId | None:
        """Return the joined agent id bound to a token."""
        return self._token_agents.get(token)

    def join(self, name: str, token: str) -> dict[str, Any]:
        """Join a free slot identified by a bearer token."""
        with self._lock:
            slot = self._token_slots.get(token)
            if slot is None:
                return self._error("UNAUTHORIZED", "invalid bearer token")
            if slot in self._joined_slots:
                return self._error("ALREADY_JOINED", "this token is already bound to an agent")
            if self._phase is SessionPhase.FINISHED:
                return self._error("SESSION_FINISHED", "the session has ended")
            if self._engine.pending_agents:
                return self._error(
                    "TICK_IN_PROGRESS",
                    "the current tick is waiting for actions; retry at the next tick",
                )

            clean_name = name.strip()
            if (
                not clean_name
                or len(clean_name) > MAX_NAME_LENGTH
                or any(not character.isprintable() for character in clean_name)
            ):
                return self._error(
                    "INVALID_NAME",
                    f"name must be 1-{MAX_NAME_LENGTH} printable characters",
                )
            if len(self._joined_slots) >= len(self._spawns):
                return self._error("SESSION_FULL", "no spawn slots remain")

            spawn = self._spawns[slot]
            agent_id = AgentId(f"ag_{slot + 1:02d}")
            agent = self._profiles[slot].build(agent_id, spawn)
            self._state = replace(self._state, agents=(*self._state.agents, agent))
            self._engine = TurnEngine(
                self._state,
                resolvers=self._resolvers,
                tick_effect=self._apply_tick_effects,
                clock=self._engine.clock,
            )
            self._names[agent_id] = clean_name
            self._joined_slots.add(slot)
            self._token_agents[token] = agent_id
            self._update_phase_locked()
            self._persist_tokens_locked()
            self._condition.notify_all()
            return {
                "ok": True,
                "schema_version": SCHEMA_VERSION,
                "agent_id": agent_id,
                "spawn": [spawn.x, spawn.y],
                "tick": self._state.tick,
                "phase": self._phase.value,
                "session": self._session_info_locked(),
            }

    def leave(self, agent_id: str) -> dict[str, Any]:
        """Remove a connected living agent and free its slot for a new join."""
        with self._condition:
            target = AgentId(agent_id)
            agent = self._find_agent(agent_id)
            if target not in self._names or agent is None:
                return self._error("NOT_YOUR_TURN", "agent is not joined")
            if self._phase is SessionPhase.FINISHED:
                return self._error("SESSION_FINISHED", "the session has ended")
            if not agent.is_alive:
                return self._error(
                    "AGENT_DEAD",
                    "dead agents remain as corpses until the session ends",
                )

            token = self._token_for_agent_locked(target)
            self._engine.remove_agent(target)
            self._state = self._engine.state
            self._drop_inventory_locked(agent)
            self._names.pop(target, None)
            self._last_results.pop(target, None)
            if token is not None:
                self._token_agents.pop(token, None)
                slot = self._token_slots.get(token)
                if slot is not None:
                    self._joined_slots.discard(slot)
            self._update_phase_locked()
            self._persist_tokens_locked()
            self._condition.notify_all()
            self._resolve_if_complete()
            return {
                "ok": True,
                "schema_version": SCHEMA_VERSION,
                "agent_id": target,
                "tick": self._state.tick,
                "phase": self._phase.value,
                "session": self._session_info_locked(),
            }

    def observe(self, agent_id: str) -> dict[str, Any]:
        """Return the current perception-limited observation for an agent."""
        with self._lock:
            target = AgentId(agent_id)
            agent = self._find_agent(agent_id)
            if target not in self._names or agent is None:
                return self._error("NOT_YOUR_TURN", "agent is not joined")
            return self._observation(agent)

    def move(self, agent_id: str, tick: int, dx: int, dy: int) -> dict[str, Any]:
        """Queue one primary move action for the current tick."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.MOVE,
            (("dx", dx), ("dy", dy)),
        )

    def move_to(self, agent_id: str, tick: int, x: int, y: int) -> dict[str, Any]:
        """Queue one step along a deterministic route to a target tile."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.MOVE_TO,
            (("x", x), ("y", y)),
        )

    def wait(self, agent_id: str, tick: int) -> dict[str, Any]:
        """Queue one primary wait action for the current tick."""
        return self._queue(agent_id, tick, ActionKind.WAIT)

    def rest(self, agent_id: str, tick: int) -> dict[str, Any]:
        """Queue one tick of rest and energy recovery."""
        return self._queue(agent_id, tick, ActionKind.REST)

    def sleep(
        self,
        agent_id: str,
        tick: int,
        until: str | None = None,
    ) -> dict[str, Any]:
        """Queue sleep until a deterministic wake condition."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.SLEEP,
            (("until", until),),
        )

    def gather(
        self,
        agent_id: str,
        tick: int,
        x: int,
        y: int,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        """Queue a gather action on one adjacent resource tile."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.GATHER,
            (("x", x), ("y", y), ("node_id", node_id)),
        )

    def pickup(
        self,
        agent_id: str,
        tick: int,
        x: int,
        y: int,
        item_id: str | None = None,
    ) -> dict[str, Any]:
        """Queue a ground-item pickup from the current or an adjacent tile."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.PICKUP,
            (("x", x), ("y", y), ("item_id", item_id)),
        )

    def drop(
        self,
        agent_id: str,
        tick: int,
        item_id: str,
        qty: int = 1,
    ) -> dict[str, Any]:
        """Queue dropping one or more units of an inventory item."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.DROP,
            (("item_id", item_id), ("qty", qty)),
        )

    def eat(self, agent_id: str, tick: int, item_id: str) -> dict[str, Any]:
        """Queue consuming one unit of food from the inventory."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.EAT,
            (("item_id", item_id),),
        )

    def drink(
        self,
        agent_id: str,
        tick: int,
        *,
        x: int | None = None,
        y: int | None = None,
        item_id: str | None = None,
    ) -> dict[str, Any]:
        """Queue drinking from an adjacent source or from a waterskin."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.DRINK,
            (("x", x), ("y", y), ("item_id", item_id)),
        )

    def fill(self, agent_id: str, tick: int, item_id: str) -> dict[str, Any]:
        """Queue filling a waterskin from adjacent fresh water."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.FILL,
            (("item_id", item_id),),
        )

    def craft(self, agent_id: str, tick: int, recipe_id: str) -> dict[str, Any]:
        """Queue crafting one catalog recipe."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.CRAFT,
            (("recipe_id", recipe_id),),
        )

    def build(
        self,
        agent_id: str,
        tick: int,
        structure_id: str,
        x: int,
        y: int,
    ) -> dict[str, Any]:
        """Queue construction of one structure on an adjacent tile."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.BUILD,
            (("structure_id", structure_id), ("x", x), ("y", y)),
        )

    def _queue(
        self,
        agent_id: str,
        tick: int,
        kind: ActionKind,
        payload: tuple[tuple[str, object], ...] = (),
    ) -> dict[str, Any]:
        if AgentId(agent_id) not in self._names:
            return self._error("NOT_YOUR_TURN", "agent is not joined")
        try:
            action = Action(AgentId(agent_id), tick, kind, payload)
        except ValueError as exc:
            return self._error("INVALID_TICK", str(exc), tick=tick)
        return self._submit(agent_id, action)

    def wait_for_tick(
        self,
        agent_id: str,
        since_tick: int,
        timeout_ms: int = 1000,
    ) -> dict[str, Any]:
        """Wait for a tick newer than ``since_tick`` or return NO_NEW_TICK."""
        target = AgentId(agent_id)
        with self._condition:
            agent = self._find_agent(agent_id)
            if target not in self._names or agent is None:
                return self._error("NOT_YOUR_TURN", "agent is not joined")
            if self._is_finished_locked():
                return self._error("SESSION_FINISHED", "the session has ended")
            if since_tick > self._state.tick:
                return self._error("INVALID_TICK", "since_tick is in the future")
            if since_tick < self._state.tick:
                return self._observation(agent)

            deadline = time.monotonic() + max(0, timeout_ms) / 1000.0
            while since_tick >= self._state.tick and not self._is_finished_locked():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)

            agent = self._find_agent(agent_id)
            if agent is None:
                return self._error("NOT_YOUR_TURN", "agent is not joined")
            if self._is_finished_locked():
                return self._error("SESSION_FINISHED", "the session has ended")
            if since_tick < self._state.tick:
                return self._observation(agent)
            return self._error("NO_NEW_TICK", "no tick arrived before the timeout")

    def finish(self, reason: SessionEndReason = SessionEndReason.OPERATOR) -> dict[str, Any]:
        """End the session at the operator's request and return its summary."""
        if not isinstance(reason, SessionEndReason):
            raise ValueError(f"reason must be a SessionEndReason, got {reason!r}")
        with self._lock:
            if self._phase is not SessionPhase.FINISHED:
                self._phase = SessionPhase.FINISHED
                self._end_reason = reason
                self._final_state_hash = canonical_state_hash(self._state)
                self._condition.notify_all()
            summary = self._summary_locked()
            if summary is None:
                raise RuntimeError("session summary is unavailable after finish")
            return summary

    @property
    def summary(self) -> dict[str, Any] | None:
        """Return the final summary, or None while the session is active."""
        with self._lock:
            return self._summary_locked()

    def restart(self, seed: int | None = None) -> GameSession:
        """Create a clean session with the same configuration and a new seed."""
        with self._lock:
            if self._phase is not SessionPhase.FINISHED:
                raise RuntimeError("session must be finished before restarting")
            new_seed = secrets.randbits(63) if seed is None else seed
            if new_seed < 0:
                raise ValueError(f"seed must be non-negative, got {new_seed}")
            layout = None if self._custom_layout is None else self._custom_layout
            return GameSession(
                new_seed,
                tick_minutes=self._state.tick_minutes,
                turn_timeout_ms=self._turn_timeout_ms,
                max_agents=self._max_agents,
                layout=layout,
                profiles=self._profiles,
                token_path=self._token_path,
                catalog=self._catalog,
                weather_min_ticks=self._weather_min_ticks,
                weather_max_ticks=self._weather_max_ticks,
            )

    def health(self) -> dict[str, Any]:
        """Return a minimal health payload without session secrets."""
        with self._lock:
            payload: dict[str, Any] = {
                "status": "ok",
                "schema_version": SCHEMA_VERSION,
                "tick": self._state.tick,
                "agents": len(self._names),
            }
            payload.update(self._session_info_locked())
            return payload

    def _submit(self, agent_id: str, action: Action) -> dict[str, Any]:
        with self._condition:
            target = AgentId(agent_id)
            agent = self._find_agent(agent_id)
            if target not in self._names or agent is None:
                return self._error("NOT_YOUR_TURN", "agent is not joined")
            if self._phase is SessionPhase.FINISHED:
                return self._error("SESSION_FINISHED", "the session has ended", tick=action.tick)
            if not agent.is_alive:
                return self._error("AGENT_DEAD", "agent is dead", tick=action.tick)
            if agent.status is not AgentStatus.ACTIVE:
                return self._error(
                    "AGENT_ABSENT",
                    f"agent is {agent.status.value}",
                    tick=action.tick,
                )
            if action.tick != self._state.tick:
                code = "STALE_TICK" if action.tick < self._state.tick else "INVALID_TICK"
                return self._error(
                    code,
                    f"action tick {action.tick} does not match current tick {self._state.tick}",
                    tick=action.tick,
                )
            if target in self._engine.pending_agents:
                return self._error(
                    "ALREADY_ACTED", "agent already acted this tick", tick=action.tick
                )

            try:
                self._engine.submit(action)
            except ActionRejectedError as exc:
                return self._error("INTERNAL_ERROR", str(exc), tick=action.tick)

            self._resolve_if_complete()
            return {
                "ok": True,
                "schema_version": SCHEMA_VERSION,
                "tick": action.tick,
                "status": "queued",
            }

    def _resolve_if_complete(self) -> None:
        if self._phase is SessionPhase.FINISHED:
            return
        active_agents = [
            agent for agent in self._state.agents if agent.status is AgentStatus.ACTIVE
        ]
        self._update_phase_locked()
        if self._phase is SessionPhase.WAITING or not active_agents:
            self._condition.notify_all()
            return
        if len(self._engine.pending_agents) < len(active_agents):
            return

        result = self._engine.resolve()
        self._state = self._engine.state
        self._record_result(result)
        self._update_phase_locked()
        self._condition.notify_all()

    def _is_finished_locked(self) -> bool:
        return self._phase is SessionPhase.FINISHED

    def _update_phase_locked(self) -> None:
        if self._phase is SessionPhase.FINISHED:
            return
        has_active_agent = any(
            agent.is_alive and agent.status is AgentStatus.ACTIVE for agent in self._state.agents
        )
        self._phase = SessionPhase.RUNNING if has_active_agent else SessionPhase.WAITING

    def _session_info_locked(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "phase": self._phase.value,
            "max_agents": self._max_agents,
            "joined_agents": len(self._joined_slots),
            "alive_agents": sum(1 for agent in self._state.agents if agent.is_alive),
        }
        if self._end_reason is not None:
            info["end_reason"] = self._end_reason.value
        return info

    def _token_for_agent_locked(self, agent_id: AgentId) -> str | None:
        return next(
            (token for token, bound_agent in self._token_agents.items() if bound_agent == agent_id),
            None,
        )

    def _drop_inventory_locked(self, agent: Agent) -> None:
        stacks = [
            *agent.inventory.stacks,
            *(ItemStack(spec.definition, 1) for _, spec in agent.equipment.items),
        ]
        if not stacks:
            return
        dropped = tuple(GroundItem(agent.position, stack) for stack in stacks)
        new_state = replace(
            self._state,
            ground_items=(*self._state.ground_items, *dropped),
        )
        self._engine.replace_state(new_state)
        self._state = new_state

    def _persist_tokens_locked(self) -> None:
        if self._token_path is not None:
            self._write_tokens(self._token_path)

    def _summary_locked(self) -> dict[str, Any] | None:
        if self._phase is not SessionPhase.FINISHED or self._final_state_hash is None:
            return None
        return {
            "schema_version": SCHEMA_VERSION,
            "seed": self._state.seed,
            "tick": self._state.tick,
            "phase": self._phase.value,
            "end_reason": self._end_reason.value if self._end_reason is not None else None,
            "state_hash": self._final_state_hash,
            "alive_agents": sum(1 for agent in self._state.agents if agent.is_alive),
            "agents": [
                {
                    "id": str(agent.agent_id),
                    "name": self._names.get(agent.agent_id, ""),
                    "status": agent.status.value,
                    "alive": agent.is_alive,
                    "health": agent.attributes.health,
                }
                for agent in self._state.agents
            ],
        }

    def _record_result(self, result: TurnResult) -> None:
        for event in result.events:
            success = event.outcome in {
                "moved",
                "waited",
                "gathered",
                "picked_up",
                "dropped",
                "ate",
                "drank",
                "filled",
                "crafted",
                "built",
                "rested",
                "sleeping",
            }
            self._last_results[event.agent_id] = {
                "tick": result.tick,
                "action": event.kind.value,
                "status": "success" if success else "rejected",
                "outcome": event.outcome,
            }

    def _observation(self, agent: Agent) -> dict[str, Any]:
        clock = self._engine.clock
        attributes = agent.attributes
        inventory = agent.inventory
        vision_radius = effective_vision(
            agent,
            clock,
            self._state.weather,
            self._state.structures,
        )
        visible_positions = compute_fov(
            self._state.world,
            agent.position,
            vision_radius,
        )
        visible = [
            {
                "x": position.x,
                "y": position.y,
                "tile": self._state.world.tile_at(position).value,
            }
            for position in sorted(
                visible_positions,
                key=lambda position: (position.y, position.x),
            )
        ]
        observation: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "tick": self._state.tick,
            "session": self._session_info_locked(),
            "server_time_ms": int(time.time() * 1000),
            "deadline_ms": self._turn_timeout_ms,
            "time": {
                "day": clock.day,
                "hour": clock.hour,
                "minute": clock.minute,
                "phase": clock.phase.value,
                "light": clock.light_factor,
            },
            "agent": {
                "id": agent.agent_id,
                "name": self._names[agent.agent_id],
                "pos": [agent.position.x, agent.position.y],
                "health": attributes.health,
                "hunger": attributes.hunger,
                "thirst": attributes.thirst,
                "energy": attributes.energy,
                "body_temp_c": attributes.body_temperature_c,
                "wetness": attributes.wetness,
                "status": [tag.value for tag in status_tags(agent)],
                "sleeping": agent.status is AgentStatus.SLEEPING,
                "strength": max(0, attributes.strength - strength_penalty(attributes)),
                "dexterity": max(
                    0,
                    attributes.dexterity - dexterity_penalty(attributes),
                ),
                "endurance": attributes.endurance,
                "effective_vision": vision_radius,
                "carry_kg": inventory.total_weight_grams / 1000.0,
                "carry_capacity_kg": agent.carry_capacity_grams / 1000.0,
                "equipment": {slot.value: spec.item_id for slot, spec in agent.equipment.items},
            },
            "environment": {
                "weather": self._state.weather.kind.value,
                "temperature_c": self._state.weather.temperature_c,
                "wind": self._state.weather.wind,
                "visibility_factor": self._state.weather.visibility_factor,
            },
            "perception": {
                "visible": visible,
                "memory_updates": [
                    {
                        "x": entry.position.x,
                        "y": entry.position.y,
                        "tile": entry.tile.value,
                        "last_seen_tick": entry.last_seen_tick,
                        "resources": list(entry.resources),
                        "structure": (
                            entry.structure.value if entry.structure is not None else None
                        ),
                        "stale": entry.stale,
                    }
                    for entry in agent.memory.tiles
                ],
                "memory_agents": [
                    {
                        "id": entry.agent_id,
                        "x": entry.position.x,
                        "y": entry.position.y,
                        "last_seen_tick": entry.last_seen_tick,
                        "stale": entry.stale,
                    }
                    for entry in agent.memory.agents
                ],
                "agents": [],
                "messages": [],
            },
            "inventory": {
                "weight_kg": inventory.total_weight_grams / 1000.0,
                "slots_used": len(inventory.stacks),
                "slots_total": inventory.max_slots,
                "items": [
                    {
                        "item_id": stack.definition.item_id,
                        "qty": stack.quantity,
                        "charges": stack.charges,
                        "weight_kg": stack.total_weight_grams / 1000.0,
                    }
                    for stack in inventory.stacks
                ],
            },
            "available_actions": [
                {"action": "move", "available": True},
                {"action": "move_to", "available": True},
                {"action": "wait", "available": True},
                {"action": "gather", "available": True},
                {"action": "pickup", "available": True},
                {"action": "drop", "available": True},
                {"action": "eat", "available": True},
                {"action": "drink", "available": True},
                {"action": "fill", "available": True},
                {"action": "craft", "available": True},
                {"action": "build", "available": True},
                {"action": "rest", "available": True},
                {"action": "sleep", "available": True},
            ],
        }
        last_result = self._last_results.get(agent.agent_id)
        if last_result is not None:
            observation["last_action_result"] = last_result
        return observation

    def _find_agent(self, agent_id: str) -> Agent | None:
        target = AgentId(agent_id)
        return next(
            (agent for agent in self._state.agents if agent.agent_id == target),
            None,
        )

    def _apply_tick_effects(
        self,
        state: SessionState,
        resolved_actions: tuple[ResolvedAction, ...],
    ) -> SessionState:
        weather, rng_state = advance_weather(
            state.weather,
            state.rng_state,
            min_ticks=self._weather_min_ticks,
            max_ticks=self._weather_max_ticks,
        )
        state = replace(state, weather=weather, rng_state=rng_state)
        state = apply_weather_wetness(state)
        state = advance_fires(state)
        state = apply_climate_tick(state, self._engine.clock)
        state = apply_needs_tick(
            state,
            resolved_actions,
            ambient_temperature_centi=weather.ambient_temperature_centi,
        )
        state = apply_sleep_tick(state)
        state = apply_status_tick(state)
        return self._update_memory_locked(state)

    def _update_memory_locked(self, state: SessionState) -> SessionState:
        clock = self._engine.clock
        agents: list[Agent] = []
        for agent in state.agents:
            if not agent.is_alive:
                agents.append(agent)
                continue
            radius = effective_vision(
                agent,
                clock,
                state.weather,
                state.structures,
            )
            visible = compute_fov(state.world, agent.position, radius)
            visible_tiles = tuple(
                MemoryEntry(
                    position=position,
                    tile=state.world.tile_at(position),
                    last_seen_tick=state.tick,
                    resources=tuple(
                        resource.resource_id
                        for resource in self._catalog.resources_for_tile(
                            state.world.tile_at(position)
                        )
                    ),
                    structure=next(
                        (
                            structure.kind
                            for structure in state.structures
                            if structure.position == position
                        ),
                        None,
                    ),
                )
                for position in sorted(visible, key=lambda item: (item.y, item.x))
            )
            visible_agents = tuple(
                AgentMemory(
                    agent_id=other.agent_id,
                    position=other.position,
                    last_seen_tick=state.tick,
                )
                for other in state.agents
                if other.agent_id != agent.agent_id and other.is_alive and other.position in visible
            )
            agents.append(
                replace(
                    agent,
                    memory=agent.memory.refresh(visible_tiles, visible_agents),
                )
            )
        return replace(state, agents=tuple(agents))

    def _write_tokens(self, path: Path) -> None:
        data = {
            "schema_version": SCHEMA_VERSION,
            "seed": self._state.seed,
            "max_agents": self._max_agents,
            "agents": [
                {
                    "slot": slot + 1,
                    "agent_id": f"ag_{slot + 1:02d}",
                    "spawn": [spawn.x, spawn.y],
                    "joined": slot in self._joined_slots,
                    "token": token,
                }
                for slot, (token, spawn) in enumerate(
                    zip(self._slot_tokens, self._spawns, strict=True)
                )
            ],
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            with contextlib.suppress(OSError):
                os.chmod(temporary, 0o600)
            temporary.replace(path)
            with contextlib.suppress(OSError):
                os.chmod(path, 0o600)
        except OSError as exc:
            raise PersistenceError(f"cannot write agent tokens to {path}: {exc}") from exc

    def _error(
        self,
        code: str,
        message: str,
        *,
        tick: int | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "schema_version": SCHEMA_VERSION,
            "tick": self._state.tick if tick is None else tick,
            "error": {"code": code, "message": message},
        }
