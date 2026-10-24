"""Aggregate per-agent and per-session MVP metrics.

The recorder accumulates the counters that cannot be derived from the final
state alone (ticks lived, need samples, action attempts, latencies), while
exploration and social totals are read from the session state and social
ledger when a snapshot is produced. Every rate metric is accompanied by its
numerator and denominator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from iasim.domain.agents import Agent
from iasim.domain.identifiers import AgentId
from iasim.domain.session import SessionState
from iasim.protocol import SCHEMA_VERSION

SURVIVAL_TICKS_PER_DAY = 288
HUNGER_CRITICAL_CENTI = 8_000
THIRST_CRITICAL_CENTI = 8_000
ENERGY_CRITICAL_CENTI = 2_000


@dataclass(slots=True)
class _AgentAccumulator:
    name: str = ""
    alive_ticks: int = 0
    hunger_sum: int = 0
    thirst_sum: int = 0
    energy_sum: int = 0
    critical_ticks: int = 0
    distance_traveled: int = 0
    resources_gathered: dict[str, int] = field(default_factory=dict)
    items_crafted: dict[str, int] = field(default_factory=dict)
    structures_built: dict[str, int] = field(default_factory=dict)
    actions_total: int = 0
    actions_failed: int = 0
    timeouts: int = 0
    attacks_made: int = 0
    damage_dealt: int = 0
    damage_taken: int = 0
    kills: int = 0
    mind_reports: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    last_observation_at: float | None = None
    cause_of_death: str | None = None
    killed_by: str | None = None
    explored_cells: int = 0


class MetricsRecorder:
    """Accumulate raw metric inputs while a session runs."""

    def __init__(self) -> None:
        self._agents: dict[AgentId, _AgentAccumulator] = {}

    def ensure(self, agent_id: AgentId, name: str = "") -> _AgentAccumulator:
        """Return the accumulator for an agent, creating it when needed."""
        accumulator = self._agents.setdefault(agent_id, _AgentAccumulator())
        if name:
            accumulator.name = name
        return accumulator

    def record_tick(self, agents: tuple[Agent, ...]) -> None:
        """Sample needs, exploration, and survival for agents alive after a tick."""
        for agent in agents:
            if not agent.is_alive:
                continue
            accumulator = self.ensure(agent.agent_id)
            accumulator.alive_ticks += 1
            accumulator.hunger_sum += agent.attributes.hunger_centi
            accumulator.thirst_sum += agent.attributes.thirst_centi
            accumulator.energy_sum += agent.attributes.energy_centi
            accumulator.explored_cells = max(
                accumulator.explored_cells,
                len(agent.memory.tiles),
            )
            if (
                agent.attributes.hunger_centi >= HUNGER_CRITICAL_CENTI
                or agent.attributes.thirst_centi >= THIRST_CRITICAL_CENTI
                or agent.attributes.energy_centi <= ENERGY_CRITICAL_CENTI
            ):
                accumulator.critical_ticks += 1

    def record_action_submitted(self, agent_id: AgentId, *, failed: bool) -> None:
        """Count one primary action attempt and whether it was rejected at once."""
        accumulator = self.ensure(agent_id)
        accumulator.actions_total += 1
        if failed:
            accumulator.actions_failed += 1

    def record_action_failed(self, agent_id: AgentId) -> None:
        """Count a queued action whose resolution failed or was cancelled."""
        self.ensure(agent_id).actions_failed += 1

    def record_observation(self, agent_id: AgentId, at: float) -> None:
        """Remember when the agent last observed to derive decision latency."""
        self.ensure(agent_id).last_observation_at = at

    def record_action_latency(self, agent_id: AgentId, now: float) -> None:
        """Record the time between the last observation and an action."""
        accumulator = self.ensure(agent_id)
        if accumulator.last_observation_at is None:
            return
        accumulator.latencies_ms.append(max(0.0, (now - accumulator.last_observation_at) * 1000.0))
        accumulator.last_observation_at = None

    def record_distance(self, agent_id: AgentId, steps: int = 1) -> None:
        """Count successful movement steps."""
        self.ensure(agent_id).distance_traveled += steps

    def record_gather(self, agent_id: AgentId, resource_id: str, quantity: int) -> None:
        """Count gathered resource units by type."""
        accumulator = self.ensure(agent_id)
        accumulator.resources_gathered[resource_id] = (
            accumulator.resources_gathered.get(resource_id, 0) + quantity
        )

    def record_craft(self, agent_id: AgentId, recipe_id: str) -> None:
        """Count crafted items by recipe."""
        accumulator = self.ensure(agent_id)
        accumulator.items_crafted[recipe_id] = accumulator.items_crafted.get(recipe_id, 0) + 1

    def record_build(self, agent_id: AgentId, structure_kind: str) -> None:
        """Count built structures by kind."""
        accumulator = self.ensure(agent_id)
        accumulator.structures_built[structure_kind] = (
            accumulator.structures_built.get(structure_kind, 0) + 1
        )

    def record_timeout(self, agent_id: AgentId) -> None:
        """Count one turn timeout."""
        self.ensure(agent_id).timeouts += 1

    def record_attack(self, agent_id: AgentId) -> None:
        """Count one melee or thrown attack."""
        self.ensure(agent_id).attacks_made += 1

    def record_damage(
        self,
        agent_id: AgentId,
        *,
        dealt: int = 0,
        taken: int = 0,
    ) -> None:
        """Add dealt or received damage in centi-health units."""
        accumulator = self.ensure(agent_id)
        accumulator.damage_dealt += max(0, dealt)
        accumulator.damage_taken += max(0, taken)

    def record_death(
        self,
        agent_id: AgentId,
        *,
        cause: str,
        killer_id: AgentId | None,
    ) -> None:
        """Record the cause of death and credit the killer."""
        accumulator = self.ensure(agent_id)
        accumulator.cause_of_death = cause
        accumulator.killed_by = None if killer_id is None else str(killer_id)
        if killer_id is not None:
            self.ensure(killer_id).kills += 1

    def record_mind_report(self, agent_id: AgentId) -> None:
        """Count one mind report."""
        self.ensure(agent_id).mind_reports += 1

    def snapshot(
        self,
        *,
        state: SessionState,
        names: dict[AgentId, str],
        final_hash: str,
        social: dict[str, Any],
    ) -> dict[str, Any]:
        """Return the per-agent and per-session metric payload."""
        for agent in state.agents:
            self.ensure(agent.agent_id, names.get(agent.agent_id, ""))
        social_agents = social.get("agents", {})
        social_session = social.get("session", {})
        transitable = sum(1 for tile in state.world.tiles if tile.walkable)
        accumulators = {agent.agent_id: self.ensure(agent.agent_id) for agent in state.agents}

        agents_payload = {
            str(agent_id): _agent_metrics(
                accumulator,
                transitable=transitable,
                counters=social_agents.get(str(agent_id), {}),
            )
            for agent_id, accumulator in accumulators.items()
        }
        session_metrics = _session_metrics(
            accumulators,
            social_session=social_session,
            final_hash=final_hash,
            transitable=transitable,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "final_state_hash": final_hash,
            "session": session_metrics,
            "agents": agents_payload,
        }


def _agent_metrics(
    accumulator: _AgentAccumulator,
    *,
    transitable: int,
    counters: dict[str, Any],
) -> dict[str, Any]:
    alive_ticks = accumulator.alive_ticks
    actions_total = accumulator.actions_total
    return {
        "name": accumulator.name,
        "survival_ticks": alive_ticks,
        "days_survived": round(alive_ticks / SURVIVAL_TICKS_PER_DAY, 4),
        "cause_of_death": accumulator.cause_of_death,
        "killed_by": accumulator.killed_by,
        "avg_hunger": _average(accumulator.hunger_sum, alive_ticks),
        "avg_thirst": _average(accumulator.thirst_sum, alive_ticks),
        "avg_energy": _average(accumulator.energy_sum, alive_ticks),
        "critical_need_ticks": accumulator.critical_ticks,
        "alive_ticks": alive_ticks,
        "critical_need_ratio": _ratio(accumulator.critical_ticks, alive_ticks),
        "explored_cells": accumulator.explored_cells,
        "transitable_cells": transitable,
        "exploration_pct": _ratio(accumulator.explored_cells, transitable),
        "distance_traveled": accumulator.distance_traveled,
        "resources_gathered": dict(accumulator.resources_gathered),
        "items_crafted": dict(accumulator.items_crafted),
        "structures_built": dict(accumulator.structures_built),
        "actions_total": actions_total,
        "actions_failed": accumulator.actions_failed,
        "invalid_action_rate": _ratio(accumulator.actions_failed, actions_total),
        "timeouts": accumulator.timeouts,
        "messages_sent": int(counters.get("messages_sent", 0)),
        "trades_offered": int(counters.get("trades_offered", 0)),
        "trades_completed": int(counters.get("trades_completed", 0)),
        "alliances_formed": int(counters.get("alliances_formed", 0)),
        "betrayals": int(counters.get("betrayals", 0)),
        "attacks_made": accumulator.attacks_made,
        "damage_dealt": accumulator.damage_dealt,
        "damage_taken": accumulator.damage_taken,
        "kills": accumulator.kills,
        "mind_reports": accumulator.mind_reports,
        "mind_report_rate": _ratio(accumulator.mind_reports, alive_ticks),
        "decision_latency_p50_ms": _percentile(accumulator.latencies_ms, 50),
        "decision_latency_p95_ms": _percentile(accumulator.latencies_ms, 95),
        "decision_latency_samples": len(accumulator.latencies_ms),
    }


def _session_metrics(
    accumulators: dict[AgentId, _AgentAccumulator],
    *,
    social_session: dict[str, Any],
    final_hash: str,
    transitable: int,
) -> dict[str, Any]:
    alive_ticks = sum(item.alive_ticks for item in accumulators.values())
    actions_total = sum(item.actions_total for item in accumulators.values())
    actions_failed = sum(item.actions_failed for item in accumulators.values())
    critical_ticks = sum(item.critical_ticks for item in accumulators.values())
    explored = sum(item.explored_cells for item in accumulators.values())
    latencies = [latency for item in accumulators.values() for latency in item.latencies_ms]
    mind_reports = sum(item.mind_reports for item in accumulators.values())

    def merged(key: str) -> dict[str, int]:
        collected: dict[str, int] = {}
        for item in accumulators.values():
            for name, value in getattr(item, key).items():
                collected[name] = collected.get(name, 0) + int(value)
        return collected

    return {
        "agent_count": len(accumulators),
        "survival_ticks": alive_ticks,
        "days_survived": round(alive_ticks / SURVIVAL_TICKS_PER_DAY, 4),
        "cause_of_death": None,
        "killed_by": None,
        "avg_hunger": _average(
            sum(item.hunger_sum for item in accumulators.values()),
            alive_ticks,
        ),
        "avg_thirst": _average(
            sum(item.thirst_sum for item in accumulators.values()),
            alive_ticks,
        ),
        "avg_energy": _average(
            sum(item.energy_sum for item in accumulators.values()),
            alive_ticks,
        ),
        "critical_need_ticks": critical_ticks,
        "alive_ticks": alive_ticks,
        "critical_need_ratio": _ratio(critical_ticks, alive_ticks),
        "explored_cells": explored,
        "transitable_cells": transitable,
        "exploration_pct": _ratio(explored, transitable),
        "distance_traveled": sum(item.distance_traveled for item in accumulators.values()),
        "resources_gathered": merged("resources_gathered"),
        "items_crafted": merged("items_crafted"),
        "structures_built": merged("structures_built"),
        "actions_total": actions_total,
        "actions_failed": actions_failed,
        "invalid_action_rate": _ratio(actions_failed, actions_total),
        "timeouts": sum(item.timeouts for item in accumulators.values()),
        "messages_sent": int(social_session.get("messages_sent", 0)),
        "trades_offered": int(social_session.get("trades_offered", 0)),
        "trades_completed": int(social_session.get("trades_completed", 0)),
        "alliances_formed": int(social_session.get("alliances_formed", 0)),
        "betrayals": int(social_session.get("betrayals", 0)),
        "attacks_made": sum(item.attacks_made for item in accumulators.values()),
        "damage_dealt": sum(item.damage_dealt for item in accumulators.values()),
        "damage_taken": sum(item.damage_taken for item in accumulators.values()),
        "kills": sum(item.kills for item in accumulators.values()),
        "mind_reports": mind_reports,
        "mind_report_rate": _ratio(mind_reports, alive_ticks),
        "decision_latency_p50_ms": _percentile(latencies, 50),
        "decision_latency_p95_ms": _percentile(latencies, 95),
        "decision_latency_samples": len(latencies),
        "final_state_hash": final_hash,
    }


def _average(total: int, samples: int) -> float:
    if samples <= 0:
        return 0.0
    return round(total / samples / 100.0, 2)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _percentile(values: list[float], percent: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, (percent * len(ordered) + 99) // 100)
    return round(ordered[rank - 1], 2)
