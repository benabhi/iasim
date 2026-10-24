"""Deterministic replay of recorded sessions.

Replay rebuilds a session from its seed and configuration, resubmits the
recorded actions turn by turn, and compares the canonical state hash of every
resolved tick with the recorded one. It can start from a snapshot to skip the
ticks that the snapshot already contains.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from iasim.app.session import GameSession
from iasim.crafting import Catalog, load_catalog
from iasim.domain.hashing import canonical_state_hash
from iasim.persistence.replay import ReplayError, ReplayRecord, read_replay
from iasim.persistence.state import action_from_payload, read_session_file


@dataclass(frozen=True, slots=True)
class ReplayReport:
    """The result of replaying one recorded session."""

    matched: bool
    ticks_replayed: int
    actions_replayed: int
    action_offset: int
    start_tick: int
    final_hash: str | None
    first_divergence_tick: int | None = None
    expected_hash: str | None = None
    actual_hash: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready summary for the operator and the CLI."""
        return {
            "matched": self.matched,
            "ticks_replayed": self.ticks_replayed,
            "actions_replayed": self.actions_replayed,
            "action_offset": self.action_offset,
            "start_tick": self.start_tick,
            "final_hash": self.final_hash,
            "first_divergence_tick": self.first_divergence_tick,
            "expected_hash": self.expected_hash,
            "actual_hash": self.actual_hash,
            "detail": self.detail,
        }


def replay_saved_run(
    replay_path: Path,
    *,
    from_snapshot: Path | None = None,
    catalog: Catalog | None = None,
) -> ReplayReport:
    """Replay a recorded session from its seed or from a snapshot."""
    record = read_replay(replay_path)
    resolved_catalog = catalog if catalog is not None else load_catalog()
    if from_snapshot is None:
        session, start_tick, action_offset, setup_failure = _start_from_seed(record)
        if setup_failure is not None:
            return setup_failure
    else:
        session, start_tick, action_offset, setup_failure = _start_from_snapshot(
            record,
            from_snapshot,
            resolved_catalog,
        )
        if setup_failure is not None:
            return setup_failure

    ticks_replayed = 0
    actions_replayed = 0
    for turn in record.turns:
        if turn.tick <= start_tick:
            continue
        for action_payload in turn.actions:
            action = action_from_payload(action_payload)
            result = session.submit_replay_action(action)
            if not result.get("ok"):
                return ReplayReport(
                    matched=False,
                    ticks_replayed=ticks_replayed,
                    actions_replayed=actions_replayed,
                    action_offset=action_offset,
                    start_tick=start_tick,
                    final_hash=None,
                    first_divergence_tick=turn.tick,
                    expected_hash=turn.state_hash,
                    actual_hash=None,
                    detail=f"recorded action was rejected: {result.get('error')}",
                )
            actions_replayed += 1
        if session.state.tick == turn.tick - 1 and turn.resolved_by == "deadline":
            session.resolve_turn_by_deadline()
        actual_hash = session.state_hash
        if session.state.tick != turn.tick or actual_hash != turn.state_hash:
            return ReplayReport(
                matched=False,
                ticks_replayed=ticks_replayed,
                actions_replayed=actions_replayed,
                action_offset=action_offset,
                start_tick=start_tick,
                final_hash=None,
                first_divergence_tick=turn.tick,
                expected_hash=turn.state_hash,
                actual_hash=actual_hash,
                detail=(
                    f"canonical hash diverged at tick {turn.tick}: "
                    f"recorded {turn.state_hash}, actual {actual_hash}"
                ),
            )
        ticks_replayed += 1
    final_hash = session.state_hash if ticks_replayed or start_tick else None
    return ReplayReport(
        matched=True,
        ticks_replayed=ticks_replayed,
        actions_replayed=actions_replayed,
        action_offset=action_offset,
        start_tick=start_tick,
        final_hash=final_hash,
    )


def _start_from_seed(
    record: ReplayRecord,
) -> tuple[GameSession, int, int, ReplayReport | None]:
    if record.start_tick != 0:
        raise ReplayError(
            f"replay record starts at tick {record.start_tick}; "
            "pass its start snapshot to replay it"
        )
    session = GameSession(
        record.seed,
        tick_minutes=record.tick_minutes,
        max_agents=record.max_agents,
        timeout_disconnects=record.timeout_disconnects,
        weather_min_ticks=record.weather_min_ticks,
        weather_max_ticks=record.weather_max_ticks,
        snapshot_every_ticks=1000,
    )
    for agent_id, name in record.agents:
        slot = int(agent_id.rsplit("_", maxsplit=1)[1]) - 1
        result = session.join(name, session.tokens[slot])
        if not result.get("ok"):
            raise ReplayError(f"cannot rejoin recorded agent {agent_id}: {result.get('error')}")
    if record.start_hash is not None:
        actual = canonical_state_hash(session.state)
        if actual != record.start_hash:
            return (
                session,
                0,
                0,
                ReplayReport(
                    matched=False,
                    ticks_replayed=0,
                    actions_replayed=0,
                    action_offset=0,
                    start_tick=0,
                    final_hash=None,
                    first_divergence_tick=0,
                    expected_hash=record.start_hash,
                    actual_hash=actual,
                    detail="initial state hash does not match the recorded start hash",
                ),
            )
    return session, 0, 0, None


def _start_from_snapshot(
    record: ReplayRecord,
    snapshot_path: Path,
    catalog: Catalog,
) -> tuple[GameSession, int, int, ReplayReport | None]:
    start_state, _ = read_session_file(snapshot_path, catalog)
    start_tick = start_state.tick
    if start_tick < record.start_tick:
        raise ReplayError(
            f"snapshot tick {start_tick} precedes the replay start tick {record.start_tick}"
        )
    session = GameSession.load(snapshot_path, catalog=catalog)
    expected = record.hash_for(start_tick)
    actual = canonical_state_hash(start_state)
    if expected is not None and expected != actual:
        return (
            session,
            start_tick,
            0,
            ReplayReport(
                matched=False,
                ticks_replayed=0,
                actions_replayed=0,
                action_offset=0,
                start_tick=start_tick,
                final_hash=None,
                first_divergence_tick=start_tick,
                expected_hash=expected,
                actual_hash=actual,
                detail="snapshot state does not match the recorded hash",
            ),
        )
    action_offset = sum(len(turn.actions) for turn in record.turns if turn.tick <= start_tick)
    return session, start_tick, action_offset, None
