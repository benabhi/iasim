"""Replay records: seed, configuration, recorded turns, and expected hashes.

A replay record is written next to the session logs. It holds everything a
deterministic replay needs: the seed and effective configuration, the joined
agents, the recorded turns with their submitted actions, and the canonical
state hash produced by each resolved tick.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from iasim.errors import PersistenceError
from iasim.protocol import SCHEMA_VERSION

REPLAY_FILENAME = "replay.json"


class ReplayError(PersistenceError):
    """A replay record is unreadable, malformed, or of an incompatible schema."""


@dataclass(frozen=True, slots=True)
class ReplayTurn:
    """One resolved tick with the actions that produced it."""

    tick: int
    state_hash: str
    resolved_by: str
    actions: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ReplayRecord:
    """The complete replay input for one session."""

    seed: int
    tick_minutes: int
    max_agents: int
    weather_min_ticks: int
    weather_max_ticks: int
    timeout_disconnects: int
    agents: tuple[tuple[str, str], ...]
    start_tick: int
    start_hash: str | None
    action_offset: int
    turns: tuple[ReplayTurn, ...]

    def hash_for(self, tick: int) -> str | None:
        """Return the recorded hash for a resolved tick, if it was recorded."""
        for turn in self.turns:
            if turn.tick == tick:
                return turn.state_hash
        return None


def write_replay(directory: Path, payload: Mapping[str, Any]) -> Path:
    """Write ``replay.json`` atomically and return its path."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / REPLAY_FILENAME
    document = {"schema_version": SCHEMA_VERSION, **payload}
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ReplayError(f"cannot write replay record {path}: {exc}") from exc
    return path


def read_replay(path: Path) -> ReplayRecord:
    """Read and validate a replay record."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReplayError(f"cannot read replay record {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReplayError(f"replay record {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ReplayError(f"replay record {path} is not a JSON object")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ReplayError(
            f"replay record {path} has schema_version {version!r}; "
            f"this server reads {SCHEMA_VERSION!r}"
        )
    try:
        agents = tuple((str(entry["id"]), str(entry["name"])) for entry in data["agents"])
        turns = tuple(_turn_from_payload(entry) for entry in data["turns"])
        start_hash = data.get("start_hash")
        return ReplayRecord(
            seed=int(data["seed"]),
            tick_minutes=int(data["tick_minutes"]),
            max_agents=int(data["max_agents"]),
            weather_min_ticks=int(data["weather_min_ticks"]),
            weather_max_ticks=int(data["weather_max_ticks"]),
            timeout_disconnects=int(data["timeout_disconnects"]),
            agents=agents,
            start_tick=int(data["start_tick"]),
            start_hash=str(start_hash) if start_hash is not None else None,
            action_offset=int(data["action_offset"]),
            turns=turns,
        )
    except KeyError as exc:
        raise ReplayError(f"replay record {path} is missing field {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise ReplayError(f"replay record {path} contains invalid data: {exc}") from exc


def _turn_from_payload(payload: Mapping[str, Any]) -> ReplayTurn:
    resolved_by = str(payload["resolved_by"])
    if resolved_by not in {"actions", "deadline"}:
        raise ValueError(f"unknown resolved_by value {resolved_by!r}")
    actions = tuple(dict(action) for action in payload["actions"])
    state_hash = str(payload["state_hash"])
    if not state_hash:
        raise ValueError("state_hash must not be empty")
    return ReplayTurn(
        tick=int(payload["tick"]),
        state_hash=state_hash,
        resolved_by=resolved_by,
        actions=actions,
    )
