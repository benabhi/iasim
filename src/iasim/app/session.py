"""Application session that owns turn state and serves MCP tools."""

from __future__ import annotations

import contextlib
import json
import math
import os
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from iasim.app.social import SocialEvent, SocialEventKind, SocialLedger
from iasim.crafting import Catalog, load_catalog
from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent, AgentProfile, AgentStatus
from iasim.domain.alliance_actions import alliance_resolvers
from iasim.domain.alliances import (
    active_alliances,
    drop_agent_alliances,
    drop_departed_alliances,
    is_allied,
    pending_offers,
)
from iasim.domain.chat import (
    MAX_CHAT_MESSAGE_LENGTH,
    ChatMessage,
    sanitize_chat_text,
    within_chat_radius,
)
from iasim.domain.climate import apply_climate_tick, effective_vision
from iasim.domain.combat import combat_resolvers
from iasim.domain.construction import advance_fires, construction_resolvers
from iasim.domain.corpse import Corpse
from iasim.domain.crafting_actions import crafting_resolvers
from iasim.domain.flee import flee_resolvers
from iasim.domain.geometry import Position
from iasim.domain.hashing import canonical_state_hash
from iasim.domain.identifiers import AgentId
from iasim.domain.item_actions import item_action_resolvers
from iasim.domain.items import Equipment, GroundItem, Inventory, ItemStack
from iasim.domain.loot import loot_resolvers
from iasim.domain.memory import AgentMemory, MemoryEntry
from iasim.domain.mind import (
    MAX_INTENT_LENGTH,
    MAX_PLAN_LENGTH,
    MAX_THOUGHT_LENGTH,
    MindReport,
)
from iasim.domain.movement import movement_resolvers
from iasim.domain.needs import apply_needs_tick
from iasim.domain.resources import (
    advance_resource_nodes,
    available_resource_ids,
    initial_resource_nodes,
)
from iasim.domain.rng import U64_MASK
from iasim.domain.session import SessionState
from iasim.domain.sleep import apply_sleep_tick, rest_sleep_resolvers
from iasim.domain.status import (
    apply_status_tick,
    dexterity_penalty,
    status_tags,
    strength_penalty,
)
from iasim.domain.text import sanitize_text
from iasim.domain.throwing import throw_resolvers
from iasim.domain.tiles import TileType
from iasim.domain.trade_actions import trade_resolvers
from iasim.domain.trades import (
    drop_agent_trades,
    drop_departed_trades,
    expire_trades,
    open_trades,
    parse_lot,
)
from iasim.domain.turns import (
    ActionRejectedError,
    ResolvedAction,
    TurnEngine,
    TurnEvent,
    TurnResult,
)
from iasim.domain.usage import AgentUsage, CostSource, ModelPricing, UsageEntry
from iasim.domain.weather import (
    DEFAULT_WEATHER_MAX_TICKS,
    DEFAULT_WEATHER_MIN_TICKS,
    WeatherState,
    advance_weather,
    apply_weather_wetness,
)
from iasim.domain.world import Structure
from iasim.errors import PersistenceError
from iasim.persistence.export import write_metrics_csv, write_summary
from iasim.persistence.logs import SessionLogs
from iasim.persistence.metrics import MetricsRecorder
from iasim.persistence.replay import write_replay
from iasim.persistence.state import (
    SNAPSHOTS_DIRNAME,
    action_from_payload,
    action_to_payload,
    read_session_file,
    write_snapshot,
    write_state_file,
)
from iasim.protocol import (
    MAX_PROTOCOL_VERSION_LENGTH,
    PROTOCOL_VERSION,
    SCHEMA_VERSION,
)
from iasim.world.generation import generate_layout
from iasim.world.layout import WorldLayout
from iasim.world.pathfinding_actions import move_to_resolvers
from iasim.world.tcod_fov import compute_fov, has_line_of_sight

MAX_NAME_LENGTH = 40
DEFAULT_TURN_TIMEOUT_MS = 60_000
DEFAULT_TIMEOUT_DISCONNECTS = 3
MAX_AGENTS = 8


def _health_band(health: float) -> str:
    """Return a coarse health band for perception-limited observations."""
    if health >= 70:
        return "healthy"
    if health >= 40:
        return "hurt"
    return "critical"


class SessionPhase(StrEnum):
    """Application lifecycle phase of the open server."""

    WAITING = "waiting"
    RUNNING = "running"
    FINISHED = "finished"


class SessionEndReason(StrEnum):
    """Why the operator stopped the session."""

    OPERATOR = "operator"


class SessionWaitReason(StrEnum):
    """Why an open session is waiting rather than running."""

    NO_AGENTS = "no_agents"
    NO_ACTIVE_AGENTS = "no_active_agents"
    LAST_DEATH = "last_death"


class GameSession:
    """Single deterministic session exposed to agents through the MCP layer."""

    def __init__(
        self,
        seed: int,
        *,
        tick_minutes: int = 5,
        turn_timeout_ms: int = DEFAULT_TURN_TIMEOUT_MS,
        timeout_disconnects: int = DEFAULT_TIMEOUT_DISCONNECTS,
        max_agents: int | None = None,
        layout: WorldLayout | None = None,
        profiles: Sequence[AgentProfile] | None = None,
        token_path: Path | None = None,
        catalog: Catalog | None = None,
        weather_min_ticks: int = DEFAULT_WEATHER_MIN_TICKS,
        weather_max_ticks: int = DEFAULT_WEATHER_MAX_TICKS,
        usage_pricing: Mapping[str, ModelPricing] | None = None,
        log_dir: Path | None = None,
        snapshot_every_ticks: int = 100,
        wall_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if seed < 0:
            raise ValueError(f"seed must be non-negative, got {seed}")
        if turn_timeout_ms < 1:
            raise ValueError(f"turn_timeout_ms must be positive, got {turn_timeout_ms}")
        if timeout_disconnects < 1:
            raise ValueError(f"timeout_disconnects must be positive, got {timeout_disconnects}")
        if weather_min_ticks < 1:
            raise ValueError(f"weather_min_ticks must be positive, got {weather_min_ticks}")
        if weather_max_ticks < weather_min_ticks:
            raise ValueError(
                "weather_max_ticks must be >= weather_min_ticks, "
                f"got {weather_max_ticks} and {weather_min_ticks}"
            )
        if max_agents is not None and not 1 <= max_agents <= MAX_AGENTS:
            raise ValueError(f"max_agents must be within [1, {MAX_AGENTS}], got {max_agents}")
        if snapshot_every_ticks < 1:
            raise ValueError(f"snapshot_every_ticks must be positive, got {snapshot_every_ticks}")

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
        self._timeout_disconnects = timeout_disconnects
        self._wall_clock = wall_clock
        self._turn_deadline: float | None = None
        self._timeouts: dict[AgentId, int] = {}
        self._pending_actions: dict[AgentId, Action] = {}
        self._social = SocialLedger()
        self._max_agents = configured_max
        self._token_path = token_path
        self._catalog = catalog if catalog is not None else load_catalog()
        self._weather_min_ticks = weather_min_ticks
        self._weather_max_ticks = weather_max_ticks
        self._usage_pricing = dict(usage_pricing or {})
        self._usage: dict[AgentId, list[UsageEntry]] = {}
        self._log_dir = log_dir
        self._logs = None if log_dir is None else SessionLogs(log_dir)
        self._snapshot_every_ticks = snapshot_every_ticks
        self._snapshot_dir = None if log_dir is None else Path(log_dir) / SNAPSHOTS_DIRNAME
        self._last_saved_tick: int | None = None
        self._last_saved_file: str | None = None
        self._replay_turns: list[dict[str, Any]] = []
        self._replay_start_hash: str | None = None
        self._replay_start_tick = 0
        self._metrics = MetricsRecorder()
        self._pre_resolution_health: dict[AgentId, int] = {}
        self._pre_resolution_inventory: dict[AgentId, dict[str, int]] = {}
        self._logged_corpse_ids: set[str] = set()
        self._mind_reports: dict[AgentId, MindReport] = {}
        self._mind_tick: dict[AgentId, int] = {}
        self._pending_chat: list[ChatMessage] = []
        self._delivered_chat: list[ChatMessage] = []
        self._said_tick: dict[AgentId, int] = {}
        self._resolvers = {
            **movement_resolvers(),
            **move_to_resolvers(),
            **item_action_resolvers(self._catalog),
            **crafting_resolvers(self._catalog),
            **construction_resolvers(self._catalog),
            **combat_resolvers(),
            **throw_resolvers(has_line_of_sight),
            **flee_resolvers(),
            **loot_resolvers(),
            **rest_sleep_resolvers(),
            **alliance_resolvers(),
            **trade_resolvers(),
        }
        self._phase = SessionPhase.WAITING
        self._waiting_reason: SessionWaitReason | None = SessionWaitReason.NO_AGENTS
        self._end_reason: SessionEndReason | None = None
        self._final_state_hash: str | None = None
        self._state = SessionState(
            seed=seed,
            tick=0,
            rng_state=seed & U64_MASK,
            world=self._layout.world,
            tick_minutes=tick_minutes,
            weather=WeatherState.initial(weather_min_ticks),
            resource_nodes=initial_resource_nodes(self._layout.world, self._catalog),
        )
        self._engine = TurnEngine(
            self._state,
            resolvers=self._resolvers,
            tick_effect=self._apply_tick_effects,
        )
        self._names: dict[AgentId, str] = {}
        self._recent_events: deque[dict[str, Any]] = deque(maxlen=200)
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
        self._logged_phase = self._phase
        self._logged_waiting_reason: SessionWaitReason | None = self._waiting_reason
        self._started_at = datetime.now(UTC).isoformat()
        if self._logs is not None:
            self._write_session_metadata_locked()
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
    def waiting_reason(self) -> SessionWaitReason | None:
        """Return why the session is waiting, if it is."""
        with self._lock:
            return self._waiting_reason

    @property
    def max_agents(self) -> int:
        """Return the number of configured agent slots."""
        return self._max_agents

    @property
    def turn_timeout_ms(self) -> int:
        """Return the configured turn deadline in milliseconds."""
        return self._turn_timeout_ms

    @property
    def timeout_disconnects(self) -> int:
        """Return consecutive timeouts before an agent becomes absent."""
        return self._timeout_disconnects

    @property
    def snapshot_every_ticks(self) -> int:
        """Return the configured snapshot cadence in ticks."""
        return self._snapshot_every_ticks

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

    @property
    def state_hash(self) -> str:
        """Return the canonical hash of the current simulation state."""
        with self._lock:
            return canonical_state_hash(self._state)

    def agent_id_for_token(self, token: str) -> AgentId | None:
        """Return the slot agent id for a valid token, joined or not."""
        slot = self._token_slots.get(token)
        if slot is None:
            return None
        return AgentId(f"ag_{slot + 1:02d}")

    def agent_for_token(self, token: str) -> AgentId | None:
        """Return the joined agent id bound to a token."""
        return self._token_agents.get(token)

    def join(
        self,
        name: str,
        token: str,
        *,
        protocol_version: str | None = None,
    ) -> dict[str, Any]:
        """Join a free slot identified by a bearer token."""
        with self._lock:
            slot = self._token_slots.get(token)
            if slot is None:
                return self._error("UNAUTHORIZED", "invalid bearer token")
            if protocol_version is not None and not _protocol_supported(protocol_version):
                return self._error(
                    "UNSUPPORTED_PROTOCOL_VERSION",
                    f"unsupported protocol version {protocol_version!r}; "
                    f"this server speaks {PROTOCOL_VERSION}",
                    details={
                        "supported": PROTOCOL_VERSION,
                        "received": protocol_version,
                    },
                )
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
            # A joining agent is always new: never inherit a departed agent's
            # social records for the same slot id.
            self._state = replace(
                self._state,
                agents=(*self._state.agents, agent),
                alliances=drop_agent_alliances(self._state.alliances, agent_id),
                trades=drop_agent_trades(self._state.trades, agent_id),
            )
            self._engine = TurnEngine(
                self._state,
                resolvers=self._resolvers,
                tick_effect=self._apply_tick_effects,
                clock=self._engine.clock,
            )
            self._names[agent_id] = clean_name
            self._metrics.ensure(agent_id, clean_name)
            self._usage.pop(agent_id, None)
            self._said_tick.pop(agent_id, None)
            self._mind_reports.pop(agent_id, None)
            self._mind_tick.pop(agent_id, None)
            self._timeouts.pop(agent_id, None)
            self._pending_actions.pop(agent_id, None)
            self._joined_slots.add(slot)
            self._token_agents[token] = agent_id
            self._update_phase_locked()
            self._log_event_locked(
                "join",
                agent_id=str(agent_id),
                name=clean_name,
                spawn=[spawn.x, spawn.y],
            )
            self._write_session_metadata_locked()
            self._persist_tokens_locked()
            self._condition.notify_all()
            return {
                "ok": True,
                "schema_version": SCHEMA_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "agent_id": agent_id,
                "spawn": [spawn.x, spawn.y],
                "tick": self._state.tick,
                "phase": self._phase.value,
                "session": self._session_info_locked(),
            }

    def leave(self, agent_id: str, *, cause: str = "leave") -> dict[str, Any]:
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
            remaining_alliances = drop_agent_alliances(self._state.alliances, target)
            remaining_trades = drop_agent_trades(self._state.trades, target)
            if len(remaining_alliances) != len(self._state.alliances) or len(
                remaining_trades
            ) != len(self._state.trades):
                self._state = replace(
                    self._state,
                    alliances=remaining_alliances,
                    trades=remaining_trades,
                )
                self._engine.replace_state(self._state)
            self._engine.remove_agent(target)
            self._state = self._engine.state
            self._drop_inventory_locked(agent)
            self._names.pop(target, None)
            self._last_results.pop(target, None)
            self._usage.pop(target, None)
            self._said_tick.pop(target, None)
            self._mind_reports.pop(target, None)
            self._mind_tick.pop(target, None)
            self._timeouts.pop(target, None)
            self._pending_actions.pop(target, None)
            if token is not None:
                self._token_agents.pop(token, None)
                slot = self._token_slots.get(token)
                if slot is not None:
                    self._joined_slots.discard(slot)
            self._update_phase_locked()
            self._log_event_locked(
                "disconnect",
                agent_id=str(target),
                cause=cause,
            )
            self._write_session_metadata_locked()
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
            self._expire_turn_if_due_locked()
            target = AgentId(agent_id)
            agent = self._find_agent(agent_id)
            if target not in self._names or agent is None:
                return self._error("NOT_YOUR_TURN", "agent is not joined")
            updated = self._note_response_locked(agent)
            self._metrics.record_observation(agent.agent_id, self._wall_clock())
            return self._observation(updated)

    def recipes(self) -> dict[str, Any]:
        """Return every known crafting recipe with its requirements."""
        with self._lock:
            recipes = [
                {
                    "recipe_id": recipe.recipe_id,
                    "level": recipe.level,
                    "station": recipe.station.value if recipe.station is not None else None,
                    "ingredients": [
                        {"item_id": item_id, "qty": quantity}
                        for item_id, quantity in recipe.ingredients
                    ],
                    "output": recipe.output,
                    "output_quantity": recipe.output_quantity,
                }
                for recipe in sorted(
                    self._catalog.recipes.values(),
                    key=lambda candidate: candidate.recipe_id,
                )
            ]
            return {
                "ok": True,
                "schema_version": SCHEMA_VERSION,
                "tick": self._state.tick,
                "recipes": recipes,
            }

    def inventory_for(self, agent_id: str) -> dict[str, Any]:
        """Return the inventory, equipment, and capacity of a joined agent."""
        with self._lock:
            self._expire_turn_if_due_locked()
            target = AgentId(agent_id)
            agent = self._find_agent(agent_id)
            if target not in self._names or agent is None:
                return self._error("NOT_YOUR_TURN", "agent is not joined")
            agent = self._note_response_locked(agent)
            return {
                "ok": True,
                "schema_version": SCHEMA_VERSION,
                "tick": self._state.tick,
                "inventory": self._inventory_payload(agent),
                "equipment": self._equipment_payload(agent),
                "carry_kg": agent.inventory.total_weight_grams / 1000.0,
                "carry_capacity_kg": agent.carry_capacity_grams / 1000.0,
            }

    def info(self, agent_id: str) -> dict[str, Any]:
        """Return non-secret session information for a joined agent.

        The seed and the RNG state are never exposed to agents: with the seed an
        agent could predict initiative, hit chances, and weather.
        """
        with self._lock:
            self._expire_turn_if_due_locked()
            target = AgentId(agent_id)
            agent = self._find_agent(agent_id)
            if target not in self._names or agent is None:
                return self._error("NOT_YOUR_TURN", "agent is not joined")
            agent = self._note_response_locked(agent)
            clock = self._engine.clock
            return {
                "ok": True,
                "schema_version": SCHEMA_VERSION,
                "tick": self._state.tick,
                "time": {
                    "day": clock.day,
                    "hour": clock.hour,
                    "minute": clock.minute,
                    "phase": clock.phase.value,
                },
                "session": self._session_info_locked(),
                "tick_minutes": self._state.tick_minutes,
                "agents": [
                    {
                        "id": str(other.agent_id),
                        "name": self._names.get(other.agent_id, ""),
                        "alive": other.is_alive,
                        "status": other.status.value,
                    }
                    for other in sorted(self._state.agents, key=lambda item: item.agent_id)
                ],
            }

    def inspect(
        self,
        agent_id: str,
        target_id: str | None = None,
        x: int | None = None,
        y: int | None = None,
    ) -> dict[str, Any]:
        """Return details of one agent, corpse, or tile within perception."""
        with self._lock:
            self._expire_turn_if_due_locked()
            target = AgentId(agent_id)
            agent = self._find_agent(agent_id)
            if target not in self._names or agent is None:
                return self._error("NOT_YOUR_TURN", "agent is not joined")
            agent = self._note_response_locked(agent)
            has_position = x is not None or y is not None
            if target_id is not None and has_position:
                return self._error(
                    "INVALID_TARGET",
                    "provide either target_id or x,y, not both",
                )
            if target_id is None and (x is None or y is None):
                return self._error("INVALID_TARGET", "provide target_id or both x and y")

            perception = self._observation(agent)["perception"]
            if target_id is not None:
                entry = self._visible_agent(perception, target_id)
                if entry is None:
                    entry = self._visible_corpse(perception, target_id)
                if entry is None:
                    return self._error("NOT_VISIBLE", "target is not within perception")
            else:
                if type(x) is not int or type(y) is not int:
                    return self._error("INVALID_TARGET", "x and y must be integers")
                if not self._state.world.contains(Position(x, y)):
                    return self._error("INVALID_TARGET", "position is outside the world")
                entry = self._visible_tile(perception, x, y)
                if entry is None:
                    return self._error("NOT_VISIBLE", "tile is not within perception")

            return {
                "ok": True,
                "schema_version": SCHEMA_VERSION,
                "tick": self._state.tick,
                "target": entry,
            }

    def _visible_agent(
        self,
        perception: Mapping[str, Any],
        target_id: str,
    ) -> dict[str, Any] | None:
        for entry in perception["agents"]:
            if entry["id"] == target_id:
                return {"kind": "agent", **entry}
        return None

    def _visible_corpse(
        self,
        perception: Mapping[str, Any],
        target_id: str,
    ) -> dict[str, Any] | None:
        for tile in perception["visible"]:
            for entity in tile["entities"]:
                if entity.get("type") == "corpse" and entity.get("corpse_id") == target_id:
                    return {
                        "kind": "corpse",
                        "x": tile["x"],
                        "y": tile["y"],
                        **entity,
                    }
        return None

    def _visible_tile(
        self,
        perception: Mapping[str, Any],
        x: int,
        y: int,
    ) -> dict[str, Any] | None:
        for tile in perception["visible"]:
            if tile["x"] == x and tile["y"] == y:
                return {"kind": "tile", **tile}
        return None

    def _inventory_payload(self, agent: Agent) -> dict[str, Any]:
        inventory = agent.inventory
        return {
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
        }

    @staticmethod
    def _equipment_payload(agent: Agent) -> dict[str, str]:
        return {slot.value: spec.item_id for slot, spec in agent.equipment.items}

    def report_usage(
        self,
        agent_id: str,
        tick: int,
        *,
        input_tokens: int,
        output_tokens: int,
        model: str,
        reasoning_effort: str | None = None,
        cost_usd: float | None = None,
    ) -> dict[str, Any]:
        """Accumulate an agent-reported LLM usage record for the operator."""
        with self._lock:
            self._expire_turn_if_due_locked()
            target = AgentId(agent_id)
            agent = self._find_agent(agent_id)
            if target not in self._names or agent is None:
                return self._error("NOT_YOUR_TURN", "agent is not joined")
            self._note_response_locked(agent)
            if self._phase is SessionPhase.FINISHED:
                return self._error("SESSION_FINISHED", "the session has ended")
            if (
                isinstance(tick, bool)
                or not isinstance(tick, int)
                or not 0 <= tick <= self._state.tick
            ):
                return self._error(
                    "INVALID_TICK", "usage tick must be between 0 and the current tick"
                )
            for label, value in (
                ("input_tokens", input_tokens),
                ("output_tokens", output_tokens),
            ):
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    return self._error(
                        "INVALID_USAGE",
                        f"{label} must be a non-negative integer",
                    )
            if not isinstance(model, str):
                return self._error("INVALID_USAGE", "model must be a string")
            clean_model = model.strip()
            if (
                not clean_model
                or len(clean_model) > 80
                or any(not character.isprintable() for character in clean_model)
            ):
                return self._error(
                    "INVALID_USAGE",
                    "model must be 1-80 printable characters",
                )
            clean_effort: str | None = None
            if reasoning_effort is not None:
                if not isinstance(reasoning_effort, str):
                    return self._error("INVALID_USAGE", "reasoning_effort must be a string")
                candidate = reasoning_effort.strip()
                if candidate:
                    if len(candidate) > 32 or any(
                        not character.isprintable() for character in candidate
                    ):
                        return self._error(
                            "INVALID_USAGE",
                            "reasoning_effort must be 1-32 printable characters",
                        )
                    clean_effort = candidate
            if cost_usd is not None:
                if isinstance(cost_usd, bool) or not isinstance(cost_usd, (int, float)):
                    return self._error("INVALID_USAGE", "cost_usd must be a number")
                reported_cost = float(cost_usd)
                if not math.isfinite(reported_cost) or reported_cost < 0:
                    return self._error(
                        "INVALID_USAGE",
                        "cost_usd must be finite and non-negative",
                    )
                entry_cost: float | None = reported_cost
                cost_source = CostSource.REPORTED
            else:
                pricing = self._usage_pricing.get(clean_model)
                if pricing is None:
                    entry_cost = None
                    cost_source = CostSource.UNKNOWN
                else:
                    entry_cost = pricing.estimate(input_tokens, output_tokens)
                    cost_source = CostSource.ESTIMATED
            try:
                entry = UsageEntry(
                    model=clean_model,
                    reasoning_effort=clean_effort,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=entry_cost,
                    cost_source=cost_source,
                    cost_complete=entry_cost is not None,
                )
            except ValueError as exc:
                return self._error("INVALID_USAGE", str(exc))
            bucket = self._usage.setdefault(target, [])
            for index, current in enumerate(bucket):
                if (current.model, current.reasoning_effort) == (
                    clean_model,
                    clean_effort,
                ):
                    merged = current.merged_with(entry)
                    del bucket[index]
                    bucket.append(merged)
                    break
            else:
                bucket.append(entry)
            usage = AgentUsage(tuple(bucket))
            return {
                "ok": True,
                "schema_version": SCHEMA_VERSION,
                "tick": self._state.tick,
                "usage": usage.as_dict(),
            }

    def usage_for(self, agent_id: str) -> AgentUsage | None:
        """Return accumulated usage for a joined agent, or None if not joined."""
        with self._lock:
            target = AgentId(agent_id)
            if target not in self._names:
                return None
            return AgentUsage(tuple(self._usage.get(target, ())))

    def usage_snapshot(self) -> dict[AgentId, AgentUsage]:
        """Return accumulated usage for every agent that has reported it."""
        with self._lock:
            return {
                agent_id: AgentUsage(tuple(entries))
                for agent_id, entries in self._usage.items()
                if entries
            }

    def names_snapshot(self) -> dict[AgentId, str]:
        """Return a copy of the joined agent names for the operator UI."""
        with self._lock:
            return dict(self._names)

    def recent_events(self, limit: int = 50) -> tuple[dict[str, Any], ...]:
        """Return the most recent presentation events without reading log files."""
        with self._lock:
            if limit <= 0:
                return ()
            return tuple(list(self._recent_events)[-limit:])

    def say(
        self,
        agent_id: str,
        message: str,
        target_id: str | None = None,
    ) -> dict[str, Any]:
        """Queue one sanitized local chat message for next-tick delivery."""
        with self._lock:
            self._expire_turn_if_due_locked()
            target = AgentId(agent_id)
            agent = self._find_agent(agent_id)
            if target not in self._names or agent is None:
                return self._error("NOT_YOUR_TURN", "agent is not joined")
            if self._phase is SessionPhase.FINISHED:
                return self._error("SESSION_FINISHED", "the session has ended")
            if not agent.is_alive:
                return self._error("AGENT_DEAD", "agent is dead")
            if agent.status is AgentStatus.ABSENT:
                return self._error("AGENT_ABSENT", "agent is absent")
            if self._said_tick.get(target) == self._state.tick:
                return self._error("ALREADY_SAID", "agent already spoke this tick")
            if not isinstance(message, str):
                return self._error("INVALID_MESSAGE", "message must be a string")
            if len(message) > MAX_CHAT_MESSAGE_LENGTH:
                return self._error(
                    "MESSAGE_TOO_LONG",
                    f"chat messages are limited to {MAX_CHAT_MESSAGE_LENGTH} characters",
                )
            text = sanitize_chat_text(message)
            if not text:
                return self._error("INVALID_MESSAGE", "message is empty after sanitization")

            target_agent_id: AgentId | None = None
            if target_id is not None:
                if not isinstance(target_id, str) or not target_id:
                    return self._error("INVALID_TARGET", "target_id must be a non-empty string")
                target_agent_id = AgentId(target_id)
                recipient = self._find_agent(str(target_agent_id))
                if recipient is None or not recipient.is_alive or recipient.agent_id == target:
                    return self._error("INVALID_TARGET", "chat target is not a living agent")
                if not within_chat_radius(agent.position, recipient.position):
                    return self._error(
                        "NOT_IN_RANGE",
                        "chat target is outside the social radius",
                    )
                recipients: tuple[AgentId, ...] = (recipient.agent_id,)
            else:
                recipients = tuple(
                    sorted(
                        other.agent_id
                        for other in self._state.agents
                        if other.agent_id != target
                        and other.is_alive
                        and within_chat_radius(agent.position, other.position)
                    )
                )

            self._pending_chat.append(
                ChatMessage(
                    sender_id=target,
                    recipients=recipients,
                    text=text,
                    sent_tick=self._state.tick,
                    deliver_tick=self._state.tick + 1,
                    target_id=target_agent_id,
                )
            )
            self._said_tick[target] = self._state.tick
            self._social.record(
                SocialEvent(
                    tick=self._state.tick,
                    kind=SocialEventKind.MESSAGE,
                    agent_id=target,
                    target_id=target_agent_id,
                )
            )
            self._log_event_locked(
                "message",
                agent_id=str(target),
                target_id=None if target_agent_id is None else str(target_agent_id),
                text=text,
            )
            return {
                "ok": True,
                "schema_version": SCHEMA_VERSION,
                "tick": self._state.tick,
                "status": "queued",
            }

    def report_mind(
        self,
        agent_id: str,
        tick: int,
        *,
        intent: str,
        thought: str,
        plan: str | None = None,
        confidence: int | None = None,
    ) -> dict[str, Any]:
        """Record one sanitized mind report for the current tick."""
        with self._lock:
            self._expire_turn_if_due_locked()
            target = AgentId(agent_id)
            agent = self._find_agent(agent_id)
            if target not in self._names or agent is None:
                return self._error("NOT_YOUR_TURN", "agent is not joined")
            if self._phase is SessionPhase.FINISHED:
                return self._error("SESSION_FINISHED", "the session has ended")
            if not agent.is_alive:
                return self._error("AGENT_DEAD", "agent is dead")
            if agent.status is AgentStatus.ABSENT:
                return self._error("AGENT_ABSENT", "agent is absent")
            if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
                return self._error("INVALID_TICK", "mind report tick must be non-negative")
            if tick > self._state.tick:
                return self._error("INVALID_TICK", "mind report tick is in the future")
            if tick < self._state.tick:
                return self._error("STALE_TICK", "mind report tick is stale")
            if self._mind_tick.get(target) == tick:
                return self._error("ALREADY_REPORTED", "agent already reported this tick")
            if not isinstance(intent, str) or not isinstance(thought, str):
                return self._error("INVALID_MIND_REPORT", "intent and thought must be strings")
            clean_intent = sanitize_text(intent)
            clean_thought = sanitize_text(thought)
            if not clean_intent or not clean_thought:
                return self._error(
                    "INVALID_MIND_REPORT",
                    "intent and thought must not be empty after sanitization",
                )
            if len(clean_intent) > MAX_INTENT_LENGTH:
                return self._error(
                    "MESSAGE_TOO_LONG",
                    f"intent is limited to {MAX_INTENT_LENGTH} characters",
                )
            if len(clean_thought) > MAX_THOUGHT_LENGTH:
                return self._error(
                    "MESSAGE_TOO_LONG",
                    f"thought is limited to {MAX_THOUGHT_LENGTH} characters",
                )
            clean_plan: str | None = None
            if plan is not None:
                if not isinstance(plan, str):
                    return self._error("INVALID_MIND_REPORT", "plan must be a string")
                clean_plan = sanitize_text(plan) or None
                if clean_plan is not None and len(clean_plan) > MAX_PLAN_LENGTH:
                    return self._error(
                        "MESSAGE_TOO_LONG",
                        f"plan is limited to {MAX_PLAN_LENGTH} characters",
                    )
            if confidence is not None and (
                isinstance(confidence, bool)
                or not isinstance(confidence, int)
                or not 0 <= confidence <= 100
            ):
                return self._error(
                    "INVALID_MIND_REPORT",
                    "confidence must be an integer within [0, 100]",
                )
            try:
                report = MindReport(
                    agent_id=target,
                    tick=tick,
                    intent=clean_intent,
                    thought=clean_thought,
                    plan=clean_plan,
                    confidence=confidence,
                )
                self._append_mind_log_locked(report)
            except (PersistenceError, ValueError) as exc:
                return self._error("INTERNAL_ERROR", f"cannot record mind report: {exc}")
            self._mind_reports[target] = report
            self._mind_tick[target] = tick
            self._metrics.record_mind_report(target)
            return {
                "ok": True,
                "schema_version": SCHEMA_VERSION,
                "tick": tick,
                "status": "recorded",
            }

    def mind_report_for(self, agent_id: str) -> MindReport | None:
        """Return the latest operator-visible report for a joined agent."""
        with self._lock:
            target = AgentId(agent_id)
            if target not in self._names:
                return None
            return self._mind_reports.get(target)

    def mind_reports_snapshot(self) -> dict[AgentId, MindReport]:
        """Return latest mind reports for all reporting agents."""
        with self._lock:
            return dict(self._mind_reports)

    def _append_mind_log_locked(self, report: MindReport) -> None:
        if self._logs is None:
            return
        try:
            self._logs.thought(report.as_dict())
        except OSError as exc:
            raise PersistenceError(f"cannot append mind report: {exc}") from exc

    def _log_event_locked(
        self,
        kind: str,
        *,
        tick: int | None = None,
        agent_id: str | None = None,
        **fields: Any,
    ) -> None:
        event = {
            "kind": kind,
            "tick": self._state.tick if tick is None else tick,
            "agent_id": agent_id,
            **fields,
        }
        self._recent_events.append(event)
        if self._logs is None:
            return
        self._logs.event(**event)

    def _log_action_locked(
        self,
        event: TurnEvent,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        if self._logs is None:
            return
        pending = self._pending_actions.get(event.agent_id)
        self._logs.action(
            tick=event.tick,
            agent_id=str(event.agent_id),
            action=event.kind.value,
            status=status,
            arguments=None if pending is None else pending.payload_dict(),
            outcome=None if error is not None else event.outcome,
            error=error,
        )

    def _reject_action_locked(
        self,
        action: Action,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._logs is not None:
            self._logs.action(
                tick=action.tick,
                agent_id=str(action.agent_id),
                action=action.kind.value,
                status="rejected",
                arguments=action.payload_dict(),
                error=code,
            )
        self._metrics.record_action_submitted(action.agent_id, failed=True)
        return self._error(code, message, tick=action.tick, details=details)

    def _write_session_metadata_locked(self) -> None:
        if self._logs is None:
            return
        self._logs.write_session(
            {
                "protocol_version": PROTOCOL_VERSION,
                "seed": self._state.seed,
                "tick": self._state.tick,
                "tick_minutes": self._state.tick_minutes,
                "max_agents": self._max_agents,
                "turn_timeout_ms": self._turn_timeout_ms,
                "timeout_disconnects": self._timeout_disconnects,
                "weather": {
                    "min_ticks": self._weather_min_ticks,
                    "max_ticks": self._weather_max_ticks,
                },
                "started_at": self._started_at,
                "last_saved_tick": self._last_saved_tick,
                "last_saved_file": self._last_saved_file,
                "debug_used": False,
                "finished": self._phase is SessionPhase.FINISHED,
                "end_reason": (self._end_reason.value if self._end_reason is not None else None),
                "final_state_hash": self._final_state_hash,
                "agents": [
                    {
                        "id": str(agent.agent_id),
                        "name": self._names.get(agent.agent_id, ""),
                        "alive": agent.is_alive,
                        "status": agent.status.value,
                    }
                    for agent in sorted(self._state.agents, key=lambda item: item.agent_id)
                ],
            }
        )

    def _log_phase_transition_locked(self) -> None:
        if (
            self._phase is self._logged_phase
            and self._waiting_reason is self._logged_waiting_reason
        ):
            return
        self._logged_phase = self._phase
        self._logged_waiting_reason = self._waiting_reason
        if self._phase is SessionPhase.WAITING:
            self._log_event_locked(
                "waiting",
                reason=(self._waiting_reason.value if self._waiting_reason is not None else None),
            )
        else:
            self._log_event_locked("running")

    def _log_new_deaths_locked(self, state: SessionState) -> None:
        for corpse in state.corpses:
            if corpse.corpse_id in self._logged_corpse_ids:
                continue
            self._logged_corpse_ids.add(corpse.corpse_id)
            self._log_event_locked(
                "death",
                tick=corpse.death_tick,
                agent_id=str(corpse.agent_id),
                cause=corpse.cause,
                killer_id=(None if corpse.killer_id is None else str(corpse.killer_id)),
            )
            self._metrics.record_death(
                corpse.agent_id,
                cause=corpse.cause,
                killer_id=corpse.killer_id,
            )

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

    def use_item(self, agent_id: str, tick: int, item_id: str) -> dict[str, Any]:
        """Queue using a consumable such as a bandage."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.USE_ITEM,
            (("item_id", item_id),),
        )

    def equip(self, agent_id: str, tick: int, item_id: str) -> dict[str, Any]:
        """Queue equipping one inventory item into its declared slot."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.EQUIP,
            (("item_id", item_id),),
        )

    def unequip(self, agent_id: str, tick: int, slot: str) -> dict[str, Any]:
        """Queue moving one equipped item back into the inventory."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.UNEQUIP,
            (("slot", slot),),
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

    def attack(self, agent_id: str, tick: int, target_id: str) -> dict[str, Any]:
        """Queue one adjacent melee attack against another agent."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.ATTACK,
            (("target_id", target_id),),
        )

    def loot(self, agent_id: str, tick: int, corpse_id: str) -> dict[str, Any]:
        """Queue looting an adjacent corpse."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.LOOT,
            (("corpse_id", corpse_id),),
        )

    def flee(self, agent_id: str, tick: int, target_id: str) -> dict[str, Any]:
        """Queue fleeing up to two cells away from a target."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.FLEE,
            (("target_id", target_id),),
        )

    def throw(self, agent_id: str, tick: int, item_id: str, target_id: str) -> dict[str, Any]:
        """Queue throwing one stone at a target up to four tiles away."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.THROW,
            (("item_id", item_id), ("target_id", target_id)),
        )

    def offer_alliance(self, agent_id: str, tick: int, target_id: str) -> dict[str, Any]:
        """Queue an alliance offer to another agent."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.OFFER_ALLIANCE,
            (("target_id", target_id),),
        )

    def accept_alliance(self, agent_id: str, tick: int, alliance_id: str) -> dict[str, Any]:
        """Queue acceptance of a pending alliance offer."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.ACCEPT_ALLIANCE,
            (("alliance_id", alliance_id),),
        )

    def break_alliance(self, agent_id: str, tick: int, target_id: str) -> dict[str, Any]:
        """Queue breaking an alliance, or closing a pending offer."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.BREAK_ALLIANCE,
            (("target_id", target_id),),
        )

    def offer_trade(
        self,
        agent_id: str,
        tick: int,
        target_id: str,
        offer: object,
        request: object,
    ) -> dict[str, Any]:
        """Queue an item trade offer to a nearby living agent."""
        parsed_offer = parse_lot(offer)
        parsed_request = parse_lot(request)
        if parsed_offer is None or parsed_request is None:
            return self._error(
                "INVALID_TRADE",
                "offer and request must be non-empty lists of {item_id, qty}",
                tick=tick,
            )
        return self._queue(
            agent_id,
            tick,
            ActionKind.OFFER_TRADE,
            (
                ("target_id", target_id),
                ("offer", parsed_offer),
                ("request", parsed_request),
            ),
        )

    def accept_trade(self, agent_id: str, tick: int, trade_id: str) -> dict[str, Any]:
        """Queue accepting one open trade offer."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.ACCEPT_TRADE,
            (("trade_id", trade_id),),
        )

    def decline_trade(self, agent_id: str, tick: int, trade_id: str) -> dict[str, Any]:
        """Queue declining one open trade offer."""
        return self._queue(
            agent_id,
            tick,
            ActionKind.DECLINE_TRADE,
            (("trade_id", trade_id),),
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
            self._expire_turn_if_due_locked()
            agent = self._find_agent(agent_id)
            if target not in self._names or agent is None:
                return self._error("NOT_YOUR_TURN", "agent is not joined")
            agent = self._note_response_locked(agent)
            if self._is_finished_locked():
                return self._error("SESSION_FINISHED", "the session has ended")
            if since_tick > self._state.tick:
                return self._error("INVALID_TICK", "since_tick is in the future")
            if since_tick < self._state.tick:
                return self._observation(agent)

            deadline = self._wall_clock() + max(0, timeout_ms) / 1000.0
            while since_tick >= self._state.tick and not self._is_finished_locked():
                self._expire_turn_if_due_locked()
                if since_tick < self._state.tick:
                    break
                remaining = deadline - self._wall_clock()
                if remaining <= 0:
                    break
                wait = remaining
                if self._turn_deadline is not None:
                    wait = min(
                        wait,
                        max(0.0, self._turn_deadline - self._wall_clock()),
                    )
                self._condition.wait(timeout=max(0.001, wait))

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
                self._waiting_reason = None
                self._end_reason = reason
                self._final_state_hash = canonical_state_hash(self._state)
                self._log_event_locked(
                    "session_end",
                    reason=reason.value,
                    state_hash=self._final_state_hash,
                )
                self._write_session_metadata_locked()
                self._write_replay_locked()
                self._export_metrics_locked()
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

    def _export_metrics_locked(self) -> None:
        """Write summary.json and metrics.csv when a run directory exists."""
        if self._log_dir is None:
            return
        snapshot = self.metrics_snapshot()
        write_summary(Path(self._log_dir), snapshot)
        write_metrics_csv(Path(self._log_dir), snapshot)

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
                timeout_disconnects=self._timeout_disconnects,
                max_agents=self._max_agents,
                layout=layout,
                profiles=self._profiles,
                token_path=self._token_path,
                catalog=self._catalog,
                weather_min_ticks=self._weather_min_ticks,
                weather_max_ticks=self._weather_max_ticks,
                usage_pricing=self._usage_pricing,
                log_dir=self._log_dir,
                snapshot_every_ticks=self._snapshot_every_ticks,
                wall_clock=self._wall_clock,
            )

    def save(self, path: Path | None = None) -> Path:
        """Write a complete atomic save and record it in the session metadata."""
        with self._lock:
            if path is None:
                if self._snapshot_dir is None:
                    raise PersistenceError("no save location configured; pass an explicit path")
                path = self._snapshot_dir / f"tick_{self._state.tick:06d}.json"
            session_data: dict[str, Any] = {
                "names": {
                    str(agent_id): name
                    for agent_id, name in sorted(
                        self._names.items(),
                        key=lambda entry: str(entry[0]),
                    )
                },
                "max_agents": self._max_agents,
                "phase": self._phase.value,
                "waiting_reason": (
                    self._waiting_reason.value if self._waiting_reason is not None else None
                ),
                "end_reason": (self._end_reason.value if self._end_reason is not None else None),
                "final_state_hash": self._final_state_hash,
                "pending_actions": [
                    action_to_payload(self._pending_actions[agent_id])
                    for agent_id in sorted(self._pending_actions)
                ],
            }
            saved = write_state_file(Path(path), self._state, {"session": session_data})
            self._last_saved_tick = self._state.tick
            self._last_saved_file = str(saved.name)
            self._write_session_metadata_locked()
            self._write_replay_locked()
            self._log_event_locked("session_saved", path=str(saved.name))
            return saved

    def submit_action(self, action: Action) -> dict[str, Any]:
        """Submit one externally built action for replay, headless runs, or tests."""
        return self._submit(str(action.agent_id), action)

    def resolve_turn_by_deadline(self) -> None:
        """Resolve the pending turn as if its action deadline expired."""
        with self._condition:
            self._resolve_deadline_locked()

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        token_path: Path | None = None,
        log_dir: Path | None = None,
        snapshot_every_ticks: int = 100,
        catalog: Catalog | None = None,
        turn_timeout_ms: int = DEFAULT_TURN_TIMEOUT_MS,
        timeout_disconnects: int = DEFAULT_TIMEOUT_DISCONNECTS,
        weather_min_ticks: int = DEFAULT_WEATHER_MIN_TICKS,
        weather_max_ticks: int = DEFAULT_WEATHER_MAX_TICKS,
        usage_pricing: Mapping[str, ModelPricing] | None = None,
        wall_clock: Callable[[], float] = time.monotonic,
    ) -> GameSession:
        """Restore a saved session, including its pending turn queue."""
        resolved_catalog = catalog if catalog is not None else load_catalog()
        resolved_path = Path(path)
        state, session_data = read_session_file(resolved_path, resolved_catalog)
        saved_agents = _read_saved_agents(token_path)
        if saved_agents is not None:
            tokens, spawn_points = saved_agents
        else:
            tokens = None
            spawn_points = tuple(agent.position for agent in state.agents) or (Position(1, 1),)
        layout = WorldLayout(
            seed=state.seed,
            world=state.world,
            spawn_points=spawn_points,
        )
        session = cls(
            state.seed,
            tick_minutes=state.tick_minutes,
            turn_timeout_ms=turn_timeout_ms,
            timeout_disconnects=timeout_disconnects,
            max_agents=len(spawn_points),
            layout=layout,
            catalog=resolved_catalog,
            weather_min_ticks=weather_min_ticks,
            weather_max_ticks=weather_max_ticks,
            usage_pricing=usage_pricing,
            log_dir=log_dir,
            snapshot_every_ticks=snapshot_every_ticks,
            wall_clock=wall_clock,
        )
        session._state = state
        session._engine = TurnEngine(
            state,
            resolvers=session._resolvers,
            tick_effect=session._apply_tick_effects,
        )
        session._names = {
            AgentId(str(agent_id)): str(name)
            for agent_id, name in session_data.get("names", {}).items()
        }
        for agent in state.agents:
            session._names.setdefault(agent.agent_id, str(agent.agent_id))
        session._replay_start_tick = state.tick
        session._replay_start_hash = canonical_state_hash(state)
        session._joined_slots.clear()
        session._token_agents.clear()
        if tokens is not None:
            session._slot_tokens = tokens
            session._token_slots = {token: slot for slot, token in enumerate(tokens)}
            for slot, token in enumerate(tokens):
                agent_id = AgentId(f"ag_{slot + 1:02d}")
                if any(agent.agent_id == agent_id for agent in state.agents):
                    session._token_agents[token] = agent_id
                    session._joined_slots.add(slot)
        session._logged_corpse_ids = {corpse.corpse_id for corpse in state.corpses}
        phase_name = session_data.get("phase")
        session._phase = SessionPhase(str(phase_name)) if phase_name else session._phase
        waiting_name = session_data.get("waiting_reason")
        session._waiting_reason = SessionWaitReason(str(waiting_name)) if waiting_name else None
        end_name = session_data.get("end_reason")
        session._end_reason = SessionEndReason(str(end_name)) if end_name else None
        final_hash = session_data.get("final_state_hash")
        session._final_state_hash = str(final_hash) if final_hash else None
        if session._phase is not SessionPhase.FINISHED:
            session._update_phase_locked()
            for pending in session_data.get("pending_actions", []):
                action = action_from_payload(pending)
                session._engine.submit(action)
                session._pending_actions[action.agent_id] = action
            session._turn_deadline = None
        session._logged_phase = session._phase
        session._logged_waiting_reason = session._waiting_reason
        session._log_event_locked("session_loaded", path=resolved_path.name)
        session._write_session_metadata_locked()
        if token_path is not None:
            session._write_tokens(Path(token_path))
        return session

    def health(self) -> dict[str, Any]:
        """Return a minimal health payload without session secrets."""
        with self._lock:
            payload: dict[str, Any] = {
                "status": "ok",
                "schema_version": SCHEMA_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "tick": self._state.tick,
                "agents": len(self._names),
            }
            payload.update(self._session_info_locked())
            return payload

    def _submit(self, agent_id: str, action: Action) -> dict[str, Any]:
        with self._condition:
            self._expire_turn_if_due_locked()
            target = AgentId(agent_id)
            agent = self._find_agent(agent_id)
            if target not in self._names or agent is None:
                return self._reject_action_locked(action, "NOT_YOUR_TURN", "agent is not joined")
            if self._phase is SessionPhase.FINISHED:
                return self._reject_action_locked(
                    action, "SESSION_FINISHED", "the session has ended"
                )
            if not agent.is_alive:
                return self._reject_action_locked(action, "AGENT_DEAD", "agent is dead")
            if agent.status is not AgentStatus.ACTIVE:
                return self._reject_action_locked(
                    action,
                    "AGENT_ABSENT",
                    f"agent is {agent.status.value}",
                )
            if action.tick != self._state.tick:
                code = "STALE_TICK" if action.tick < self._state.tick else "INVALID_TICK"
                return self._reject_action_locked(
                    action,
                    code,
                    f"action tick {action.tick} does not match current tick {self._state.tick}",
                    details={
                        "received_tick": action.tick,
                        "current_tick": self._state.tick,
                    },
                )
            if target in self._engine.pending_agents:
                return self._reject_action_locked(
                    action,
                    "ALREADY_ACTED",
                    "agent already acted this tick",
                    details={"agent_id": str(target), "tick": action.tick},
                )

            try:
                self._engine.submit(action)
            except ActionRejectedError as exc:
                return self._reject_action_locked(action, "INTERNAL_ERROR", str(exc))

            self._timeouts.pop(target, None)
            self._pending_actions[target] = action
            self._metrics.record_action_submitted(target, failed=False)
            self._metrics.record_action_latency(target, self._wall_clock())
            if self._turn_deadline is None:
                self._turn_deadline = self._wall_clock() + self._turn_timeout_ms / 1000.0
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

        self._turn_deadline = None
        self._capture_replay_start_locked()
        self._capture_pre_resolution_locked()
        result = self._engine.resolve()
        self._state = self._engine.state
        self._record_result(result)
        self._update_phase_locked()
        self._maybe_snapshot_locked()
        self._condition.notify_all()

    def _expire_turn_if_due_locked(self) -> None:
        """Resolve the turn once its action deadline has passed."""
        if self._turn_deadline is None or self._phase is SessionPhase.FINISHED:
            return
        if self._wall_clock() < self._turn_deadline:
            return
        self._resolve_deadline_locked()

    def _resolve_deadline_locked(self) -> None:
        """Skip missing actions, count timeouts, and resolve the turn."""
        pending = self._engine.pending_agents
        self._turn_deadline = None
        if not pending:
            return

        absent: set[AgentId] = set()
        for agent in self._state.agents:
            if agent.status is not AgentStatus.ACTIVE or agent.agent_id in pending:
                continue
            timeouts = self._timeouts.get(agent.agent_id, 0) + 1
            self._timeouts[agent.agent_id] = timeouts
            self._metrics.record_timeout(agent.agent_id)
            self._log_event_locked(
                "timeout",
                agent_id=str(agent.agent_id),
                consecutive=timeouts,
            )
            if timeouts >= self._timeout_disconnects:
                absent.add(agent.agent_id)
        if absent:
            self._state = replace(
                self._state,
                agents=tuple(
                    replace(agent, status=AgentStatus.ABSENT) if agent.agent_id in absent else agent
                    for agent in self._state.agents
                ),
            )
            self._engine.replace_state(self._state)
            for agent_id in sorted(absent):
                self._log_event_locked(
                    "absent",
                    agent_id=str(agent_id),
                    consecutive=self._timeouts[agent_id],
                )

        self._capture_pre_resolution_locked()
        result = self._engine.resolve()
        self._state = self._engine.state
        self._record_result(result, resolved_by_deadline=True)
        self._update_phase_locked()
        self._maybe_snapshot_locked()
        self._condition.notify_all()

    def _capture_pre_resolution_locked(self) -> None:
        """Capture health and inventory so damage and gathering can be derived."""
        self._pre_resolution_health = {
            agent.agent_id: agent.attributes.health_centi for agent in self._state.agents
        }
        self._pre_resolution_inventory = {
            agent.agent_id: {
                stack.definition.item_id: stack.quantity for stack in agent.inventory.stacks
            }
            for agent in self._state.agents
        }

    def _maybe_snapshot_locked(self) -> None:
        """Write a periodic snapshot when the tick is due."""
        if self._snapshot_dir is None or self._snapshot_every_ticks <= 0:
            return
        if self._state.tick == 0 or self._state.tick % self._snapshot_every_ticks:
            return
        write_snapshot(self._snapshot_dir, self._state)

    def _note_response_locked(self, agent: Agent) -> Agent:
        """Mark a connected absent agent as active again after it responds."""
        if agent.status is not AgentStatus.ABSENT:
            return agent
        revived = replace(agent, status=AgentStatus.ACTIVE)
        self._state = replace(
            self._state,
            agents=tuple(
                revived if current.agent_id == agent.agent_id else current
                for current in self._state.agents
            ),
        )
        self._engine.replace_state(self._state)
        self._timeouts.pop(agent.agent_id, None)
        self._update_phase_locked()
        return revived

    def _is_finished_locked(self) -> bool:
        return self._phase is SessionPhase.FINISHED

    def _update_phase_locked(self) -> None:
        if self._phase is SessionPhase.FINISHED:
            return
        living = [agent for agent in self._state.agents if agent.is_alive]
        has_active_agent = any(agent.status is AgentStatus.ACTIVE for agent in living)
        if has_active_agent:
            self._phase = SessionPhase.RUNNING
            self._waiting_reason = None
            self._log_phase_transition_locked()
            return
        self._phase = SessionPhase.WAITING
        if not self._joined_slots and not self._state.agents:
            self._waiting_reason = SessionWaitReason.NO_AGENTS
        elif not living:
            self._waiting_reason = SessionWaitReason.LAST_DEATH
        else:
            self._waiting_reason = SessionWaitReason.NO_ACTIVE_AGENTS
        self._log_phase_transition_locked()

    def _session_info_locked(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "phase": self._phase.value,
            "max_agents": self._max_agents,
            "joined_agents": len(self._joined_slots),
            "alive_agents": sum(1 for agent in self._state.agents if agent.is_alive),
        }
        if self._waiting_reason is not None:
            info["waiting_reason"] = self._waiting_reason.value
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

    def _record_result(
        self,
        result: TurnResult,
        *,
        resolved_by_deadline: bool = False,
    ) -> None:
        recorded: dict[AgentId, dict[str, Any]] = {}
        resolved_actions: list[dict[str, Any]] = []
        gather_agents: set[AgentId] = set()
        for event in result.events:
            self._record_social_event_locked(event)
            # The first event of an agent carries its primary action outcome;
            # later events are annotations such as a betrayal and never replace it.
            if event.agent_id in recorded:
                continue
            pending = self._pending_actions.get(event.agent_id)
            if pending is not None:
                resolved_actions.append(action_to_payload(pending))
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
                "equipped",
                "unequipped",
                "rested",
                "sleeping",
                "offered",
                "accepted",
                "broken",
                "withdrawn",
                "declined",
            }
            self._record_action_metrics_locked(
                event,
                pending=pending,
                success=success,
                gather_agents=gather_agents,
            )
            recorded[event.agent_id] = {
                "tick": result.tick,
                "action": event.kind.value,
                "status": "success" if success else "rejected",
                "outcome": event.outcome,
            }
            self._log_action_locked(
                event,
                status="success" if success else "rejected",
            )
        self._record_gather_metrics_locked(gather_agents)
        self._record_damage_metrics_locked()
        if self._log_dir is not None:
            self._replay_turns.append(
                {
                    "tick": result.tick + 1,
                    "state_hash": canonical_state_hash(self._state),
                    "resolved_by": ("deadline" if resolved_by_deadline else "actions"),
                    "actions": resolved_actions,
                    "minds": [
                        report.as_dict()
                        for report in sorted(
                            self._mind_reports.values(),
                            key=lambda item: str(item.agent_id),
                        )
                    ],
                }
            )
        self._last_results.update(recorded)
        self._pending_actions.clear()

    def _record_action_metrics_locked(
        self,
        event: TurnEvent,
        *,
        pending: Action | None,
        success: bool,
        gather_agents: set[AgentId],
    ) -> None:
        """Record the metrics carried by one primary turn outcome."""
        executed = success or event.outcome in {"hit", "killed", "missed"}
        if not executed:
            self._metrics.record_action_failed(event.agent_id)
        payload = {} if pending is None else pending.payload_dict()
        if event.kind in {ActionKind.MOVE, ActionKind.MOVE_TO} and success:
            self._metrics.record_distance(event.agent_id)
        elif event.kind is ActionKind.GATHER and success:
            gather_agents.add(event.agent_id)
        elif event.kind is ActionKind.CRAFT and success:
            recipe_id = payload.get("recipe_id")
            if isinstance(recipe_id, str) and recipe_id:
                self._metrics.record_craft(event.agent_id, recipe_id)
        elif event.kind is ActionKind.BUILD and success:
            structure = self._structure_at(payload)
            if structure is not None:
                self._metrics.record_build(event.agent_id, structure.kind.value)
        elif event.kind in {ActionKind.ATTACK, ActionKind.THROW}:
            self._metrics.record_attack(event.agent_id)
            self._record_attack_damage_locked(event.agent_id, payload)

    def _record_attack_damage_locked(
        self,
        attacker: AgentId,
        payload: Mapping[str, Any],
    ) -> None:
        target_raw = payload.get("target_id")
        if not isinstance(target_raw, str) or not target_raw:
            return
        previous = self._pre_resolution_health.get(AgentId(target_raw))
        target = self._find_agent(target_raw)
        if previous is None or target is None:
            return
        dealt = max(0, previous - target.attributes.health_centi)
        if dealt:
            self._metrics.record_damage(attacker, dealt=dealt)

    def _structure_at(self, payload: Mapping[str, Any]) -> Structure | None:
        x = payload.get("x")
        y = payload.get("y")
        if type(x) is not int or type(y) is not int:
            return None
        for structure in self._state.structures:
            if structure.position.x == x and structure.position.y == y:
                return structure
        return None

    def _record_damage_metrics_locked(self) -> None:
        for agent in self._state.agents:
            previous = self._pre_resolution_health.get(agent.agent_id)
            if previous is None:
                continue
            taken = max(0, previous - agent.attributes.health_centi)
            if taken:
                self._metrics.record_damage(agent.agent_id, taken=taken)
        self._pre_resolution_health = {}
        self._pre_resolution_inventory = {}

    def _record_gather_metrics_locked(self, gather_agents: set[AgentId]) -> None:
        for agent_id in gather_agents:
            agent = self._find_agent(str(agent_id))
            if agent is None:
                continue
            previous = self._pre_resolution_inventory.get(agent_id, {})
            for stack in agent.inventory.stacks:
                before = previous.get(stack.definition.item_id, 0)
                gained = stack.quantity - before
                if gained > 0:
                    self._metrics.record_gather(
                        agent_id,
                        stack.definition.item_id,
                        gained,
                    )

    def _capture_replay_start_locked(self) -> None:
        """Record the state hash that the first replay turn starts from."""
        if self._log_dir is None or self._replay_start_hash is not None:
            return
        self._replay_start_hash = canonical_state_hash(self._state)
        self._replay_start_tick = self._state.tick

    def _write_replay_locked(self) -> None:
        """Write the replay record next to the session logs."""
        if self._log_dir is None:
            return
        write_replay(
            Path(self._log_dir),
            {
                "seed": self._state.seed,
                "tick_minutes": self._state.tick_minutes,
                "max_agents": self._max_agents,
                "weather_min_ticks": self._weather_min_ticks,
                "weather_max_ticks": self._weather_max_ticks,
                "timeout_disconnects": self._timeout_disconnects,
                "start_tick": self._replay_start_tick,
                "start_hash": self._replay_start_hash,
                "action_offset": 0,
                "agents": [
                    {"id": str(agent_id), "name": name}
                    for agent_id, name in sorted(
                        self._names.items(),
                        key=lambda entry: str(entry[0]),
                    )
                ],
                "turns": list(self._replay_turns),
            },
        )

    def _record_social_event_locked(self, event: TurnEvent) -> None:
        action = self._pending_actions.get(event.agent_id)
        target_id: AgentId | None = None
        if action is not None:
            raw_target = action.payload_dict().get("target_id")
            if isinstance(raw_target, str) and raw_target:
                target_id = AgentId(raw_target)
        recorded = self._social.record_outcome(
            tick=event.tick,
            agent_id=event.agent_id,
            action_kind=event.kind.value,
            outcome=event.outcome,
            target_id=target_id,
        )
        if recorded is not None:
            self._log_event_locked(
                recorded.kind.value,
                tick=recorded.tick,
                agent_id=str(recorded.agent_id),
                target_id=(None if recorded.target_id is None else str(recorded.target_id)),
            )

    def social_metrics(self) -> dict[str, Any]:
        """Return the social counters per session and per agent."""
        with self._lock:
            return self._social.snapshot()

    def social_events(self) -> tuple[SocialEvent, ...]:
        """Return the ordered social event log for the operator and the logs."""
        with self._lock:
            return self._social.events

    def metrics_snapshot(self) -> dict[str, Any]:
        """Return the aggregated per-agent and per-session MVP metrics."""
        with self._lock:
            final_hash = self._final_state_hash or canonical_state_hash(self._state)
            return self._metrics.snapshot(
                state=self._state,
                names=dict(self._names),
                final_hash=final_hash,
                social=self._social.snapshot(),
            )

    def _resource_ids_at(self, state: SessionState, position: Position) -> tuple[str, ...]:
        tile = state.world.tile_at(position)
        if not state.resource_nodes:
            return tuple(
                resource.resource_id for resource in self._catalog.resources_for_tile(tile)
            )
        return available_resource_ids(state.resource_nodes, position, tile, self._catalog)

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
        ground_items_by_position: dict[Position, list[GroundItem]] = {}
        for ground in self._state.ground_items:
            ground_items_by_position.setdefault(ground.position, []).append(ground)
        structures_by_position = {
            structure.position: structure for structure in self._state.structures
        }
        corpses_by_position: dict[Position, list[Corpse]] = {}
        for corpse in self._state.corpses:
            corpses_by_position.setdefault(corpse.position, []).append(corpse)
        visible = []
        for position in sorted(
            visible_positions,
            key=lambda item: (item.y, item.x),
        ):
            tile = self._state.world.tile_at(position)
            resources = list(self._resource_ids_at(self._state, position))
            entities: list[dict[str, Any]] = []
            for ground in ground_items_by_position.get(position, ()):
                entities.append(
                    {
                        "type": "item",
                        "item_id": ground.stack.definition.item_id,
                        "qty": ground.stack.quantity,
                        "charges": ground.stack.charges,
                    }
                )
            structure = structures_by_position.get(position)
            if structure is not None:
                entities.append({"type": "structure", "kind": structure.kind.value})
            for corpse in corpses_by_position.get(position, ()):
                entities.append(corpse.as_observation())
            visible.append(
                {
                    "x": position.x,
                    "y": position.y,
                    "tile": tile.value,
                    "glyph": tile.glyph,
                    "resource": resources[0] if resources else None,
                    "resources": resources,
                    "entities": entities,
                }
            )
        visible_agents = [
            {
                "id": other.agent_id,
                "name": self._names[other.agent_id],
                "pos": [other.position.x, other.position.y],
                "health_band": _health_band(other.attributes.health),
                "equipment_visible": [
                    spec.item_id
                    for _, spec in sorted(
                        other.equipment.items,
                        key=lambda item: item[0].value,
                    )
                ],
                "relation": (
                    "ally"
                    if is_allied(self._state.alliances, agent.agent_id, other.agent_id)
                    else "neutral"
                ),
            }
            for other in sorted(self._state.agents, key=lambda item: item.agent_id)
            if other.agent_id != agent.agent_id
            and other.is_alive
            and other.position in visible_positions
        ]
        observation: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
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
                "state": agent.status.value,
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
                "equipment": self._equipment_payload(agent),
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
                "agents": visible_agents,
                "messages": [
                    message.as_observation()
                    for message in sorted(
                        (
                            current
                            for current in self._delivered_chat
                            if current.deliver_tick == self._state.tick
                            and agent.agent_id in current.recipients
                        ),
                        key=lambda current: (current.sent_tick, str(current.sender_id)),
                    )
                ],
            },
            "inventory": self._inventory_payload(agent),
            "social": {
                "alliances": [
                    {
                        "alliance_id": alliance.alliance_id,
                        "with": str(alliance.other_member(agent.agent_id)),
                        "since_tick": (
                            alliance.accepted_tick
                            if alliance.accepted_tick is not None
                            else alliance.offered_tick
                        ),
                    }
                    for alliance in active_alliances(self._state.alliances, agent.agent_id)
                ],
                "offers": [
                    {
                        "alliance_id": alliance.alliance_id,
                        "from": str(alliance.proposed_by),
                        "to": str(alliance.other_member(alliance.proposed_by)),
                        "tick": alliance.offered_tick,
                        "mine": alliance.proposed_by == agent.agent_id,
                    }
                    for alliance in pending_offers(self._state.alliances, agent.agent_id)
                ],
                "trades": [
                    {
                        **trade.as_observation(),
                        "mine": trade.proposer_id == agent.agent_id,
                    }
                    for trade in open_trades(self._state.trades, agent.agent_id)
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
                {"action": "use", "available": True},
                {"action": "equip", "available": True},
                {"action": "unequip", "available": True},
                {"action": "attack", "available": True},
                {"action": "throw", "available": True},
                {"action": "flee", "available": True},
                {"action": "loot", "available": True},
                {"action": "offer_alliance", "available": True},
                {"action": "accept_alliance", "available": True},
                {"action": "break_alliance", "available": True},
                {"action": "offer_trade", "available": True},
                {"action": "accept_trade", "available": True},
                {"action": "decline_trade", "available": True},
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
        state = self._finalize_deaths_locked(state)
        self._log_new_deaths_locked(state)
        state = replace(
            state,
            resource_nodes=advance_resource_nodes(
                state.resource_nodes,
                tick=state.tick + 1,
            ),
            trades=expire_trades(state.trades, tick=state.tick + 1),
        )
        self._advance_chat_locked(state.tick + 1)
        final_state = self._update_memory_locked(state)
        self._metrics.record_tick(final_state.agents)
        return final_state

    def _finalize_deaths_locked(self, state: SessionState) -> SessionState:
        known = {corpse.agent_id for corpse in state.corpses}
        corpses = list(state.corpses)
        agents: list[Agent] = []
        for agent in state.agents:
            if agent.is_alive or agent.agent_id in known:
                agents.append(agent)
                continue
            corpses.append(
                Corpse.from_agent(
                    agent,
                    tick=state.tick,
                    cause="environment",
                )
            )
            agents.append(
                replace(
                    agent,
                    inventory=Inventory.for_strength(agent.attributes.strength),
                    equipment=Equipment(),
                )
            )
            known.add(agent.agent_id)
        alive = {agent.agent_id for agent in agents if agent.is_alive}
        return replace(
            state,
            agents=tuple(agents),
            corpses=tuple(corpses),
            alliances=drop_departed_alliances(state.alliances, alive),
            trades=drop_departed_trades(state.trades, alive),
        )

    def _advance_chat_locked(self, tick: int) -> None:
        ready = [message for message in self._pending_chat if message.deliver_tick <= tick]
        self._pending_chat = [
            message for message in self._pending_chat if message.deliver_tick > tick
        ]
        self._delivered_chat = ready

    def _update_memory_locked(self, state: SessionState) -> SessionState:
        clock = self._engine.clock
        structures_by_position = {
            structure.position: structure.kind for structure in state.structures
        }
        node_ids_by_position: dict[Position, set[str]] = {}
        for node in state.resource_nodes:
            if not node.depleted:
                node_ids_by_position.setdefault(node.position, set()).add(node.resource_id)
        resource_ids_by_tile: dict[TileType, tuple[str, ...]] = {}

        def resource_ids_at(position: Position) -> tuple[str, ...]:
            tile = state.world.tile_at(position)
            catalog_ids = resource_ids_by_tile.get(tile)
            if catalog_ids is None:
                catalog_ids = tuple(
                    resource.resource_id for resource in self._catalog.resources_for_tile(tile)
                )
                resource_ids_by_tile[tile] = catalog_ids
            if not state.resource_nodes:
                return catalog_ids
            available = node_ids_by_position.get(position, set())
            return tuple(resource_id for resource_id in catalog_ids if resource_id in available)

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
                    resources=resource_ids_at(position),
                    structure=structures_by_position.get(position),
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
        details: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if details:
            error["details"] = dict(details)
        return {
            "ok": False,
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "tick": self._state.tick if tick is None else tick,
            "error": error,
        }


def _read_saved_agents(
    path: Path | None,
) -> tuple[tuple[str, ...], tuple[Position, ...]] | None:
    """Return one token and spawn per slot from an agents file, if it exists."""
    if path is None:
        return None
    resolved = Path(path)
    if not resolved.exists():
        return None
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersistenceError(f"cannot read agent file {resolved}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise PersistenceError(f"agent file {resolved} has an unsupported schema")
    try:
        entries = sorted(data["agents"], key=lambda entry: int(entry["slot"]))
        tokens = tuple(str(entry["token"]) for entry in entries)
        spawn_points = tuple(
            Position(int(entry["spawn"][0]), int(entry["spawn"][1])) for entry in entries
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PersistenceError(f"agent file {resolved} is malformed: {exc}") from exc
    if not tokens:
        raise PersistenceError(f"agent file {resolved} has no agent slots")
    return tokens, spawn_points


def _protocol_supported(value: object) -> bool:
    """Return whether a client-declared protocol version is supported."""
    return (
        isinstance(value, str)
        and 0 < len(value) <= MAX_PROTOCOL_VERSION_LENGTH
        and value.strip() == PROTOCOL_VERSION
    )
