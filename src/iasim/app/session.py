"""Application session that owns turn state and serves MCP tools."""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent, AgentStatus
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.movement import movement_resolvers
from iasim.domain.rng import U64_MASK
from iasim.domain.session import SessionState
from iasim.domain.turns import ActionRejectedError, TurnEngine, TurnResult
from iasim.errors import PersistenceError
from iasim.world.generation import generate_layout
from iasim.world.layout import WorldLayout

SCHEMA_VERSION = "1.0"
PERCEPTION_RADIUS = 3
MAX_NAME_LENGTH = 40
DEFAULT_TURN_TIMEOUT_MS = 60_000


class GameSession:
    """Single deterministic session exposed to agents through the MCP layer."""

    def __init__(
        self,
        seed: int,
        *,
        tick_minutes: int = 5,
        turn_timeout_ms: int = DEFAULT_TURN_TIMEOUT_MS,
        allow_late_join: bool = False,
        layout: WorldLayout | None = None,
        token_path: Path | None = None,
    ) -> None:
        if seed < 0:
            raise ValueError(f"seed must be non-negative, got {seed}")
        if turn_timeout_ms < 1:
            raise ValueError(f"turn_timeout_ms must be positive, got {turn_timeout_ms}")
        self._layout = layout if layout is not None else generate_layout(seed, agent_count=8)
        self._turn_timeout_ms = turn_timeout_ms
        self._allow_late_join = allow_late_join
        self._state = SessionState(
            seed=seed,
            tick=0,
            rng_state=seed & U64_MASK,
            world=self._layout.world,
            tick_minutes=tick_minutes,
        )
        self._engine = TurnEngine(self._state, resolvers=movement_resolvers())
        self._names: dict[AgentId, str] = {}
        self._last_results: dict[AgentId, dict[str, Any]] = {}
        self._slot_tokens: tuple[str, ...] = tuple(
            secrets.token_urlsafe(32) for _ in range(len(self._layout.spawn_points))
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
        """Join the slot identified by a bearer token."""
        with self._lock:
            slot = self._token_slots.get(token)
            if slot is None:
                return self._error("UNAUTHORIZED", "invalid bearer token")
            if slot in self._joined_slots:
                return self._error("ALREADY_JOINED", "this token is already bound to an agent")

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
            if self._state.tick > 0 and not self._allow_late_join:
                return self._error("LATE_JOIN_DISABLED", "late joins are disabled")
            if self._engine.pending_agents:
                return self._error("LATE_JOIN_DISABLED", "cannot join while actions are pending")
            if len(self._joined_slots) >= len(self._layout.spawn_points):
                return self._error("SESSION_FULL", "no spawn slots remain")

            spawn = self._layout.spawn_points[slot]
            agent_id = AgentId(f"ag_{slot + 1:02d}")
            agent = Agent(agent_id, spawn)
            self._state = replace(self._state, agents=(*self._state.agents, agent))
            self._engine = TurnEngine(
                self._state,
                resolvers=movement_resolvers(),
                clock=self._engine.clock,
            )
            self._names[agent_id] = clean_name
            self._joined_slots.add(slot)
            self._token_agents[token] = agent_id
            return {
                "ok": True,
                "schema_version": SCHEMA_VERSION,
                "agent_id": agent_id,
                "spawn": [spawn.x, spawn.y],
                "tick": self._state.tick,
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
        if AgentId(agent_id) not in self._names:
            return self._error("NOT_YOUR_TURN", "agent is not joined")
        try:
            action = Action(
                AgentId(agent_id),
                tick,
                ActionKind.MOVE,
                (("dx", dx), ("dy", dy)),
            )
        except ValueError as exc:
            return self._error("INVALID_TICK", str(exc), tick=tick)
        return self._submit(agent_id, action)

    def wait(self, agent_id: str, tick: int) -> dict[str, Any]:
        """Queue one primary wait action for the current tick."""
        if AgentId(agent_id) not in self._names:
            return self._error("NOT_YOUR_TURN", "agent is not joined")
        try:
            action = Action(AgentId(agent_id), tick, ActionKind.WAIT)
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
            if since_tick > self._state.tick:
                return self._error("INVALID_TICK", "since_tick is in the future")
            if since_tick < self._state.tick:
                return self._observation(agent)

            timeout_seconds = max(0, timeout_ms) / 1000.0
            self._condition.wait(timeout=timeout_seconds)
            agent = self._find_agent(agent_id)
            if agent is None:
                return self._error("NOT_YOUR_TURN", "agent is not joined")
            if since_tick < self._state.tick:
                return self._observation(agent)
            return self._error("NO_NEW_TICK", "no tick arrived before the timeout")

    def health(self) -> dict[str, Any]:
        """Return a minimal health payload without session secrets."""
        with self._lock:
            return {
                "status": "ok",
                "schema_version": SCHEMA_VERSION,
                "tick": self._state.tick,
                "agents": len(self._names),
            }

    def _submit(self, agent_id: str, action: Action) -> dict[str, Any]:
        with self._condition:
            target = AgentId(agent_id)
            agent = self._find_agent(agent_id)
            if target not in self._names or agent is None:
                return self._error("NOT_YOUR_TURN", "agent is not joined")
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
        active_agents = [
            agent for agent in self._state.agents if agent.status is AgentStatus.ACTIVE
        ]
        if not active_agents:
            return
        if len(self._engine.pending_agents) < len(active_agents):
            return

        result = self._engine.resolve()
        self._state = self._engine.state
        self._record_result(result)
        self._condition.notify_all()

    def _record_result(self, result: TurnResult) -> None:
        for event in result.events:
            success = event.outcome in {"moved", "waited"}
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
        visible = [
            {
                "x": x,
                "y": y,
                "tile": self._state.world.tile_at(Position(x, y)).value,
            }
            for y in range(
                max(0, agent.position.y - PERCEPTION_RADIUS),
                min(self._state.world.height, agent.position.y + PERCEPTION_RADIUS + 1),
            )
            for x in range(
                max(0, agent.position.x - PERCEPTION_RADIUS),
                min(self._state.world.width, agent.position.x + PERCEPTION_RADIUS + 1),
            )
        ]
        observation: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "tick": self._state.tick,
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
                "status": [],
                "strength": attributes.strength,
                "dexterity": attributes.dexterity,
                "endurance": attributes.endurance,
                "effective_vision": attributes.vision,
                "carry_kg": inventory.total_weight_grams / 1000.0,
                "carry_capacity_kg": inventory.max_weight_grams / 1000.0,
            },
            "environment": {
                "weather": "clear",
                "temperature_c": 22.0,
                "wind": 0,
                "visibility_factor": 1.0,
            },
            "perception": {
                "visible": visible,
                "memory_updates": [],
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
                        "weight_kg": stack.total_weight_grams / 1000.0,
                    }
                    for stack in inventory.stacks
                ],
            },
            "available_actions": [
                {"action": "move", "available": True},
                {"action": "wait", "available": True},
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

    def _write_tokens(self, path: Path) -> None:
        data = {
            "schema_version": SCHEMA_VERSION,
            "seed": self._state.seed,
            "agents": [
                {
                    "slot": slot + 1,
                    "agent_id": f"ag_{slot + 1:02d}",
                    "spawn": [spawn.x, spawn.y],
                    "token": token,
                }
                for slot, (token, spawn) in enumerate(
                    zip(self._slot_tokens, self._layout.spawn_points, strict=True)
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
