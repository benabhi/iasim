"""Headless runner that advances a session with a deterministic action script.

The runner uses the same session, turn queue, and tick loop as the MCP server;
it only removes the presentation layer. It is the shared driver for headless
runs, performance tests, and deterministic "equivalent test run" comparisons.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from iasim.app.session import GameSession
from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import AgentStatus
from iasim.domain.identifiers import AgentId

ActionScript = Callable[[int, AgentId], Action]


@dataclass(frozen=True, slots=True)
class HeadlessReport:
    """Summary of one headless run."""

    ticks: int
    state_hashes: tuple[str, ...]
    actions_submitted: int
    final_hash: str

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-ready summary for the operator and tests."""
        return {
            "ticks": self.ticks,
            "actions_submitted": self.actions_submitted,
            "final_hash": self.final_hash,
            "state_hashes": list(self.state_hashes),
        }


def wait_script(tick: int, agent_id: AgentId) -> Action:
    """Return a deterministic wait action for the given tick and agent."""
    return Action(agent_id, tick, ActionKind.WAIT)


def run_headless(
    session: GameSession,
    *,
    ticks: int,
    script: ActionScript | None = None,
    finish: bool = False,
) -> HeadlessReport:
    """Advance ``ticks`` resolved turns without opening any UI.

    The script must return one primary action per living active agent for each
    tick; the default script waits. Every turn must resolve when its actions
    are submitted, so a mismatched script fails loudly instead of hanging.
    """
    if ticks < 1:
        raise ValueError(f"ticks must be positive, got {ticks}")
    action_script = wait_script if script is None else script
    hashes: list[str] = []
    submitted = 0
    start_tick = session.state.tick
    for tick in range(start_tick, start_tick + ticks):
        active = tuple(
            agent.agent_id
            for agent in session.state.agents
            if agent.is_alive and agent.status is AgentStatus.ACTIVE
        )
        if not active:
            raise RuntimeError("headless run has no active agents to act")
        for agent_id in active:
            action = action_script(tick, agent_id)
            result = session.submit_action(action)
            if not result.get("ok"):
                raise RuntimeError(
                    f"headless action was rejected for {agent_id} at tick {tick}: "
                    f"{result.get('error')}"
                )
            submitted += 1
        if session.state.tick != tick + 1:
            raise RuntimeError(
                f"headless turn did not resolve: expected tick {tick + 1}, got {session.state.tick}"
            )
        hashes.append(session.state_hash)
    report = HeadlessReport(
        ticks=ticks,
        state_hashes=tuple(hashes),
        actions_submitted=submitted,
        final_hash=session.state_hash,
    )
    if finish:
        session.finish()
    return report
