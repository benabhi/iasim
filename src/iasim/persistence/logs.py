"""Append-only JSONL session logs and the session metadata file.

Every record is one JSON object on its own line with a ``schema_version``, so a
session can be reviewed, replayed, and diffed after the fact. Appends are
serialized per file so concurrent session threads cannot interleave lines, and
``session.json`` is replaced atomically. Tokens never reach these files.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from iasim.protocol import SCHEMA_VERSION

SESSION_FILENAME = "session.json"
EVENTS_FILENAME = "events.jsonl"
ACTIONS_FILENAME = "actions.jsonl"
THOUGHTS_FILENAME = "thoughts.jsonl"


class SessionLogs:
    """Thread-safe JSONL writers for one session run directory."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.session_path = self.directory / SESSION_FILENAME
        self.events_path = self.directory / EVENTS_FILENAME
        self.actions_path = self.directory / ACTIONS_FILENAME
        self.thoughts_path = self.directory / THOUGHTS_FILENAME
        self._locks = {
            path: threading.Lock()
            for path in (self.events_path, self.actions_path, self.thoughts_path)
        }

    def write_session(self, payload: Mapping[str, Any]) -> None:
        """Replace ``session.json`` atomically with the given metadata."""
        record = {"schema_version": SCHEMA_VERSION, **payload}
        temporary = self.session_path.with_name(self.session_path.name + ".tmp")
        temporary.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.session_path)

    def event(
        self,
        *,
        kind: str,
        tick: int,
        agent_id: str | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        """Append one world or connection event."""
        record: dict[str, Any] = {"event": kind, "tick": tick}
        if agent_id is not None:
            record["agent_id"] = agent_id
        record.update(fields)
        return self._append(self.events_path, record)

    def action(
        self,
        *,
        tick: int,
        agent_id: str,
        action: str,
        status: str,
        arguments: Mapping[str, Any] | None = None,
        request_id: str | None = None,
        outcome: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """Append one action attempt or resolution."""
        record: dict[str, Any] = {
            "tick": tick,
            "agent_id": agent_id,
            "action": action,
            "status": status,
            "arguments": {} if arguments is None else dict(arguments),
            "request_id": request_id,
        }
        if outcome is not None:
            record["outcome"] = outcome
        if error is not None:
            record["error"] = error
        return self._append(self.actions_path, record)

    def thought(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Append one sanitized mind report."""
        return self._append(self.thoughts_path, {"event": "mind_report", **payload})

    def _append(self, path: Path, record: Mapping[str, Any]) -> dict[str, Any]:
        payload = {"schema_version": SCHEMA_VERSION, **record}
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._locks[path], path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()
        return payload
