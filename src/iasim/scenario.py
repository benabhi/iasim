"""Three-day, two-agent MVP scenario with cooperation, competition and death.

The scenario is operator-scripted and deterministic. It runs on the same
procedural island used by the normal game (seed ``20261023``), provisions the
two agents with enough berries and waterskin charges to survive the three days,
has them meet, form an alliance and equip spears, and forces a permanent death
during the third day. The complete run is recorded in a run directory and
replayed against the canonical hashes.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from iasim.app.replay import replay_saved_run
from iasim.app.session import GameSession
from iasim.crafting import load_catalog
from iasim.domain.agents import Agent, AgentProfile
from iasim.domain.alliances import AllianceStatus
from iasim.domain.geometry import Position
from iasim.domain.items import Inventory, ItemStack
from iasim.world.generation import generate_layout
from iasim.world.layout import WorldLayout

SCENARIO_SEED = 20261023
SCENARIO_DAYS = 3
TICKS_PER_DAY = 288
SCENARIO_TICKS = SCENARIO_DAYS * TICKS_PER_DAY
COMPETITION_START = 2 * TICKS_PER_DAY + 20
WATERSKIN_CHARGES = 200


@dataclass(frozen=True, slots=True)
class ScenarioReport:
    """Outcome of the three-day scenario for the release record."""

    seed: int
    ticks: int
    days: int
    survivor: str
    casualty: str
    death_tick: int | None
    death_cause: str | None
    killer: str | None
    alliance_formed: bool
    messages: int
    mind_reports: int
    looted: bool
    replay_matched: bool
    final_hash: str
    artifacts: tuple[str, ...]
    metrics: dict[str, Any]


def _scenario_layout() -> WorldLayout:
    return generate_layout(SCENARIO_SEED, agent_count=2)


def _profiles() -> tuple[AgentProfile, AgentProfile]:
    catalog = load_catalog()
    berry = catalog.item("berry").definition
    spear = catalog.item("stone_spear").definition
    waterskin = catalog.item("waterskin").definition
    inventory = (
        Inventory.for_strength(5)
        .add_quantity(berry, 40)
        .add(ItemStack(waterskin, 1, charges=WATERSKIN_CHARGES))
        .add(ItemStack(spear, 1))
    )
    profile = AgentProfile(inventory=inventory)
    return (profile, profile)


def _agent(session: GameSession, agent_id: str) -> Agent:
    return next(agent for agent in session.state.agents if str(agent.agent_id) == agent_id)


def _distance(session: GameSession, first: str, second: str) -> int:
    left = _agent(session, first).position
    right = _agent(session, second).position
    return max(abs(left.x - right.x), abs(left.y - right.y))


def _quantity(session: GameSession, agent_id: str, item_id: str) -> int:
    stack = _agent(session, agent_id).inventory.stack_for(item_id)
    return 0 if stack is None else stack.quantity


def _charges(session: GameSession, agent_id: str, item_id: str) -> int:
    stack = _agent(session, agent_id).inventory.stack_for(item_id)
    return 0 if stack is None else stack.charges


def _meeting_target(session: GameSession, agent_id: str, target_id: str) -> Position:
    """Return a free walkable cell adjacent to the target agent."""
    target = _agent(session, target_id).position
    origin = _agent(session, agent_id).position
    occupied = {agent.position for agent in session.state.agents if agent.is_alive}
    candidates = [
        Position(target.x + dx, target.y + dy)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        if (dx, dy) != (0, 0)
    ]
    free = [
        position
        for position in candidates
        if session.state.world.contains(position)
        and session.state.world.tile_at(position).walkable
        and position not in occupied
    ]
    if not free:
        return origin
    return min(
        free,
        key=lambda position: (
            abs(position.x - origin.x) + abs(position.y - origin.y),
            position.y,
            position.x,
        ),
    )


def _primary_action(
    session: GameSession,
    agent_id: str,
    other: str,
    tick: int,
    *,
    allied: bool,
    equipped: bool,
    loot_pending: bool,
    corpse_loot: str | None,
) -> tuple[str | None, bool]:
    """Queue one primary action and return (social event, looted flag)."""
    agent = _agent(session, agent_id)
    attributes = agent.attributes
    social: str | None = None

    if loot_pending and corpse_loot is not None:
        session.loot(agent_id, tick, corpse_loot)
        return social, True
    if attributes.thirst >= 55 and _charges(session, agent_id, "waterskin") > 0:
        session.drink(agent_id, tick, item_id="waterskin")
        return social, False
    if attributes.hunger >= 55 and _quantity(session, agent_id, "berry") > 0:
        session.eat(agent_id, tick, "berry")
        return social, False

    if not allied and _distance(session, agent_id, other) == 1:
        if agent_id < other:
            session.offer_alliance(agent_id, tick, other)
            social = "offer"
            return social, False
        pending = next(
            (
                alliance
                for alliance in session.state.alliances
                if alliance.status is AllianceStatus.PENDING
            ),
            None,
        )
        if pending is not None:
            session.accept_alliance(agent_id, tick, pending.alliance_id)
            social = "accept"
            return social, False

    if not equipped and _quantity(session, agent_id, "stone_spear") > 0:
        session.equip(agent_id, tick, "stone_spear")
        return social, False

    if tick >= COMPETITION_START and agent_id < other:
        if _distance(session, agent_id, other) > 1:
            target = _meeting_target(session, agent_id, other)
            session.move_to(agent_id, tick, target.x, target.y)
        else:
            session.attack(agent_id, tick, other)
        return social, False

    if tick < COMPETITION_START and _distance(session, agent_id, other) > 1:
        target = _meeting_target(session, agent_id, other)
        session.move_to(agent_id, tick, target.x, target.y)
        return social, False

    session.wait(agent_id, tick)
    return social, False


def run_three_day_scenario(directory: Path) -> ScenarioReport:
    """Run the deterministic three-day scenario and return its outcome."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    session = GameSession(
        SCENARIO_SEED,
        layout=_scenario_layout(),
        profiles=_profiles(),
        max_agents=2,
        log_dir=directory,
        snapshot_every_ticks=100,
        token_path=directory / "agents.json",
        turn_timeout_ms=60_000,
    )
    first = session.join("Nia", session.tokens[0])["agent_id"]
    second = session.join("Kai", session.tokens[1])["agent_id"]
    initial_snapshot = session.save(directory / "initial_snapshot.json")
    death_tick: int | None = None
    death_cause: str | None = None
    killer: str | None = None
    looted = False

    for tick in range(SCENARIO_TICKS):
        living = [str(agent.agent_id) for agent in session.state.agents if agent.is_alive]
        if not living:
            break
        corpse = next(
            (candidate for candidate in session.state.corpses if str(candidate.agent_id) == second),
            None,
        )
        allied = any(
            alliance.status is AllianceStatus.ACTIVE for alliance in session.state.alliances
        )
        for agent_id in living:
            other = second if agent_id == first else first
            equipped = any(
                spec.item_id == "stone_spear"
                for _slot, spec in _agent(session, agent_id).equipment.items
            )
            try:
                if tick == 0 and agent_id == first:
                    session.say(
                        agent_id,
                        "Cooperemos: propongo alianza y compartir la isla.",
                    )
                _social, did_loot = _primary_action(
                    session,
                    agent_id,
                    other,
                    tick,
                    allied=allied,
                    equipped=equipped,
                    loot_pending=(corpse is not None and not looted and agent_id == first),
                    corpse_loot=None if corpse is None else corpse.corpse_id,
                )
                looted = looted or did_loot
                if agent_id == first and tick % 48 == 0:
                    session.report_mind(
                        agent_id,
                        tick,
                        intent="Coordinar",
                        thought="La alianza sigue en pie.",
                        plan="Esperar",
                        confidence=80,
                    )
            except (ValueError, RuntimeError):
                session.wait(agent_id, tick)
        if session.tick != tick + 1:
            raise RuntimeError(f"scenario tick {tick} did not resolve")
        corpse = next(
            (candidate for candidate in session.state.corpses if str(candidate.agent_id) == second),
            None,
        )
        if corpse is not None and death_tick is None:
            death_tick = corpse.death_tick
            death_cause = corpse.cause
            killer = None if corpse.killer_id is None else str(corpse.killer_id)

    summary = session.finish()
    replay = replay_saved_run(
        directory / "replay.json",
        from_snapshot=initial_snapshot,
    )
    metrics = session.metrics_snapshot()
    agent_metrics = metrics["agents"].get(second, {})
    artifacts = tuple(
        sorted(
            entry.name
            for entry in directory.iterdir()
            if entry.is_file() or entry.name == "snapshots"
        )
    )
    session_metrics = metrics["session"]
    return ScenarioReport(
        seed=SCENARIO_SEED,
        ticks=session.tick,
        days=SCENARIO_DAYS,
        survivor=first,
        casualty=second,
        death_tick=death_tick,
        death_cause=death_cause,
        killer=killer,
        alliance_formed=(
            bool(session.state.alliances) or int(session_metrics.get("alliances_formed", 0)) > 0
        ),
        messages=int(session_metrics.get("messages_sent", 0)),
        mind_reports=int(session_metrics.get("mind_reports", 0)),
        looted=looted,
        replay_matched=replay.matched,
        final_hash=str(summary["state_hash"]),
        artifacts=artifacts,
        metrics={"session": session_metrics, "casualty": agent_metrics},
    )


def write_scenario_report(report: ScenarioReport, path: Path) -> Path:
    """Write the scenario outcome and metrics as a markdown record."""
    session = report.metrics["session"]
    casualty = report.metrics["casualty"]
    lines = [
        "# Three-day two-agent scenario — iasim-qul.7",
        "",
        f"- Seed: {report.seed}",
        f"- Duration: {report.ticks} ticks ({report.days} days, {TICKS_PER_DAY} ticks/day)",
        f"- Final hash: `{report.final_hash}`",
        f"- Replay: {'MATCH' if report.replay_matched else 'DIVERGED'}",
        "",
        "## Scenario outcome",
        "",
        f"- Survivor: `{report.survivor}`",
        f"- Casualty: `{report.casualty}` at tick {report.death_tick} "
        f"({report.death_cause}, killer {report.killer})",
        f"- Alliance formed: {report.alliance_formed}",
        f"- Corpse looted: {report.looted}",
        f"- Chat messages: {report.messages} · mind reports: {report.mind_reports}",
        "",
        "## Session metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    for key in (
        "survival_ticks",
        "actions_total",
        "actions_failed",
        "messages_sent",
        "alliances_formed",
        "attacks_made",
        "kills",
        "mind_reports",
        "exploration_pct",
        "resources_gathered",
        "items_crafted",
    ):
        lines.append(f"| {key} | {session.get(key)} |")
    lines.extend(
        [
            "",
            "## Casualty metrics",
            "",
            f"- Survival ticks: {casualty.get('survival_ticks')}",
            f"- Cause of death: {casualty.get('cause_of_death')}",
            f"- Killed by: {casualty.get('killed_by')}",
            f"- Actions: {casualty.get('actions_total')}",
            "",
            "## Artifacts",
            "",
            f"{', '.join(f'`{name}`' for name in report.artifacts)}",
            "",
            "The run directory, metrics, replay and hashes are deterministic for "
            f"seed {report.seed}; rerun with `python scripts/three_day_scenario.py`.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    """Run the scenario, write the report and print a short summary."""
    with tempfile.TemporaryDirectory() as directory:
        report = run_three_day_scenario(Path(directory))
        report_path = write_scenario_report(
            report,
            Path("docs/scenario-qul7.md"),
        )
        print(
            f"ticks={report.ticks} survivor={report.survivor} "
            f"casualty={report.casualty}@{report.death_tick} "
            f"replay={'match' if report.replay_matched else 'diverged'} "
            f"hash={report.final_hash}"
        )
        print(f"report: {report_path}")
    return 0 if report.replay_matched else 1
